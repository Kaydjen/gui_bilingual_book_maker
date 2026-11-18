"""Books, series and the library: plain `*_task` functions over the core (no Qt, no Tk).

Functions named `*_task` take a lane context first and run off the GUI thread (a lane thread or the helper
process); the rest are quick. Arguments and results are plain data. Books are opened per thread and every handle
is registered, so `release_books_task` run on each lane closes them all (an open zip blocks a move on Windows).
"""

from __future__ import annotations

import gc
import json
import re
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from novelcore import Book, Series
from novelcore import profiles
from novelcore.exporter import NothingToExport
from novelcore.exporter import export as core_export
from novelcore.htmlscan import strip_markers
from novelcore.store import chapter_file_name, read_jsonl, safe_name, split_target
from novelcore.terms import FILE_NAME as TERMS_FILE
from novelcore.terms import TermBase

from .. import chapterlogic as cl
from .. import atomic, langrules, pieces
from ..lanes import Want
from ..libraryrules import explain_oserror, natural_key
from ..termlogic import PRONOUNS

EXPORT_READY = True
TARGETS = (("ru:Russian", "Russian"), ("uk:Ukrainian", "Ukrainian"), ("pl:Polish", "Polish"))


# ---------------------------------------------------------------- books, one per thread, all registered
_local = threading.local()
_registry_lock = threading.Lock()
_registry: dict[str, dict] = {}     # thread name -> that thread's cache (read for counts, closed only by its thread)


def _cache() -> dict:
    cache = getattr(_local, "books", None)
    if cache is None:
        cache = _local.books = {}
        with _registry_lock:
            _registry[threading.current_thread().name] = cache
    return cache


def open_handles() -> dict:
    """{thread name: [book paths it holds open]}: what `release_books_task` still has to close."""
    with _registry_lock:
        return {name: sorted(cache) for name, cache in _registry.items() if cache}


def open_book(path) -> Book:
    cache = _cache()
    key = str(path)
    sig = cl.file_sig(path)
    hit = cache.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1]
    if hit is not None:
        try:
            hit[1].close()
        except Exception:
            pass
    book = Book.open(path)
    if len(cache) >= 3:
        old = cache.pop(next(iter(cache)))
        try:
            old[1].close()
        except Exception:
            pass
    cache[key] = (sig, book)
    return book


def book_file(series_path, book: str) -> Path:
    return Path(series_path) / "books" / (book + ".epub")


# ---------------------------------------------------------------- library and series
@dataclass(frozen=True)
class SeriesInfo:
    name: str
    path: str
    target: str
    tag: str
    books: tuple
    labels: tuple = ()      # ((volume name, label shown), ...) set by Rename volume
    broken: str = ""        # why the series cannot be opened ("" = fine)
    chosen: bool = True     # False for a series created by Add book whose language is not chosen yet (3.1)

    def label_of(self, stem: str) -> str:
        return dict(self.labels).get(stem) or stem


def _series_info(p: Path) -> SeriesInfo:
    """The list entry of one series folder; a folder whose series.json cannot be read is marked `broken`."""
    try:
        s = Series.open(p)
    except (FileNotFoundError, ValueError):
        return SeriesInfo(p.name, str(p), "", "", (), (), _broken_reason(p))
    labels = s.settings.get("volume_labels")
    labels = tuple(sorted((str(k), str(v)) for k, v in labels.items() if isinstance(v, str) and v.strip()))         if isinstance(labels, dict) else ()
    books = tuple(sorted(s.book_names(), key=natural_key))
    return SeriesInfo(str(s.settings.get("name") or p.name), str(p), str(s.settings.get("target", "")),
                      s.target_tag, books, labels, chosen=s.settings.get("target_chosen") is not False)


def list_series_task(ctx, library) -> list[SeriesInfo]:
    """Every series of the library, the series folders only (`.deleted` and other hidden folders are not
    series). A folder whose series.json cannot be read is listed too, marked `broken`, so the user sees it."""
    out = []
    lib = Path(library)
    try:
        folders = sorted((p for p in lib.iterdir() if p.is_dir() and not p.name.startswith(".")),
                         key=lambda p: p.name.lower())
    except OSError:
        return out
    for p in folders:
        if (p / "series.json").exists():
            out.append(_series_info(p))
    return out


def read_series(series_path) -> SeriesInfo | None:
    """One series as the list shows it now, or None when its folder or series.json is gone."""
    p = Path(series_path)
    return _series_info(p) if (p / "series.json").exists() else None


# ---------------------------------------------------------------- the language of a series (window 3.1)
def series_language(info) -> str | None:
    """The ONE reader of a series' target language: `tag:Name`, or None while the user has not chosen it. A
    series without the `target_chosen` flag (made before this window, or by the core) counts as chosen."""
    if info is None or not info.chosen or not info.target:
        return None
    return info.target


def set_series_language(series_path, target: str) -> None:
    """The ONE writer: the target and `target_chosen` go into series.json in one atomic write."""
    tag, _name = split_target(target)
    if not tag:
        raise ValueError("no language")

    def put(settings):
        settings["target"] = target
        settings["target_chosen"] = True
    update_series_settings(series_path, put)


def with_language(info, target: str):
    """`info` as the list would read it after `set_series_language(info.path, target)`."""
    from dataclasses import replace
    return replace(info, target=target, tag=split_target(target)[0], chosen=True)


def language_lock(series_path) -> tuple[bool, bool]:
    """(a block is translated, a term is confirmed): while either holds, the language cannot change."""
    root = Path(series_path)
    translated = False
    for f in sorted((root / "chapters").glob("*/*.jsonl")):
        if any(r.get("status") == "ok" for r in read_jsonl(f)):
            translated = True
            break
    confirmed = False
    tf = root / TERMS_FILE
    if tf.is_file():
        try:
            base = TermBase.load(tf, split_target(str(Series.open(root).settings.get("target", "")))[0] or None)
            confirmed = any(e.status == "confirmed" for e in base.sorted_entries())
        except (OSError, ValueError):
            confirmed = False
    return translated, confirmed


def book_language_tag(book_path) -> str:
    """The dc:language of an EPUB as a primary tag ("" when it has none or cannot be read)."""
    try:
        with zipfile.ZipFile(book_path) as z:
            cont = z.read("META-INF/container.xml").decode("utf-8", "replace")
            m = re.search(r'full-path="([^"]+)"', cont)
            if not m:
                return ""
            return langrules.dc_language(z.read(m.group(1)).decode("utf-8", "replace"))
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""


def source_language(series_path, book: str) -> langrules.SourceLang:
    """Source language for export names (13.11): the book's dc:language, else the series' source_lang, else
    Original / src."""
    try:
        src = str(Series.open(series_path).settings.get("source_lang") or "")
    except (FileNotFoundError, ValueError):
        src = ""
    return langrules.source_language(book_language_tag(book_file(series_path, book)) if book else "", src)


def _broken_reason(folder: Path) -> str:
    """Why series.json of a folder cannot be used, in plain words."""
    try:
        data = json.loads((folder / "series.json").read_text(encoding="utf-8"))
    except OSError as exc:
        return "series.json cannot be opened (%s)" % explain_oserror(exc)
    except ValueError:
        return "series.json is damaged"
    return "series.json is not a series record" if not isinstance(data, dict) else "series.json cannot be read"


def clean_name(text: str, maxlen: int = 60, fallback: str = "item") -> str:
    """The core's file name cleaning (window rules that build names call this, never a copy of it)."""
    return safe_name(text, maxlen, fallback)


def check_epub(path) -> int:
    """Open a file with the core's EPUB reader; returns its number of chapters. Raises ValueError with the
    reason in plain words when it cannot be read."""
    p = Path(path)
    try:
        book = Book.open(p)
    except zipfile.BadZipFile:
        raise ValueError("it is not an EPUB file (not a zip archive)") from None
    except OSError as exc:
        raise ValueError("it cannot be opened (%s)" % (exc.strerror or exc)) from None
    except Exception as exc:
        text = str(exc)
        if "not a zip" in text.lower():
            raise ValueError("it is not an EPUB file (not a zip archive)") from None
        raise ValueError("it cannot be read as an EPUB (%s)" % (text.rsplit(": ", 1)[-1][:120]
                                                                or type(exc).__name__)) from None
    try:
        n = len(book.chapters)
    except Exception as exc:
        raise ValueError("it cannot be read as an EPUB (%s)" % (str(exc)[:120] or type(exc).__name__)) from None
    finally:
        try:
            book.close()
        except Exception:
            pass
    if n == 0:
        raise ValueError("it has no chapters")
    return n


def create_series_record(library, name: str, target: str, **settings) -> str:
    """Write series.json (and the folders) of a new series; returns the series folder. One write."""
    return str(Series.create(library, name, target, **settings).path)


def update_series_settings(series_path, fn) -> None:
    """Read series.json, let `fn(settings_dict)` change it, write it back atomically."""
    s = Series.open(series_path)
    fn(s.settings)
    s.save_settings()


def release_books_task(ctx, folder=None) -> int:
    """Close every book of `folder` (None = every book) that this thread holds open (an open zip blocks a move on
    Windows). Runs once on every lane thread (`Lanes.close_lane_books`). Returns how many were closed."""
    cache = getattr(_local, "books", None)
    n = 0
    if cache:
        root = str(Path(folder)).lower() if folder else ""
        for key in list(cache):
            if str(key).lower().startswith(root):
                try:
                    cache.pop(key)[1].close()
                except Exception:
                    pass
                n += 1
    gc.collect()        # a book dropped without being closed sits in a reference cycle until the collector runs
    return n


def gender_marks(tag: str) -> dict:
    """Short gender marks of the target language (core profile), plus `?` for unknown."""
    marks = dict(profiles.get(tag).gender_marks)
    marks["unknown"] = "?"
    return marks


def target_label(target: str) -> str:
    """Language name for column headers: 'ru:Russian' -> 'Russian' (profile name for a bare tag)."""
    tag, name = split_target(target)
    return profiles.get(tag, name if name != tag else None).name


# ---------------------------------------------------------------- chapters of a book
def log_file(series_path, book: str, index: int, href: str) -> Path:
    name = chapter_file_name(SimpleNamespace(index=index, href=href))
    return Path(series_path) / "chapters" / safe_name(book, 80) / name


def scan_chapters_task(ctx, series_path, book_name: str, want: Want) -> dict:
    """Fills the chapter list of one book: titles, contents-page flags, block counts and translation counts.

    Emits ("skeleton", infos) once and then ("rows", infos) batches (copies without block hashes). Block counts
    and block hashes are cached in <series>/.state keyed by the book file's size and mtime, log counts by each
    log file's size and mtime. A block counts as done only by an ok line of its own (index, source hash)
    (window_spec 14.12): an ok line of an older text of the block does not.
    """
    bpath = book_file(series_path, book_name)
    bsig = cl.file_sig(bpath)
    cpath = cl.cache_path(series_path, book_name)
    cached = cl.load_cache(cpath, bsig)
    t0 = time.perf_counter()
    if cached:
        infos = [cached[i] for i in sorted(cached)]
        from_cache = True
    else:
        book = open_book(bpath)
        infos = [cl.ChapterInfo(ch.index, ch.href) for ch in book.chapters]
        from_cache = False
    n = len(infos)
    ctx.emit(("skeleton", [i.public() for i in infos]))
    computed = refreshed = 0
    todo = [True] * n
    left = n
    pointer = 0
    batch: list = []
    last_emit = time.perf_counter()
    last_save = computed
    breathe = getattr(ctx, "breathe", None)
    while left and not ctx.cancelled:
        if breathe is not None:
            breathe()
        a, b = want.get()
        idx = None
        for i in range(max(0, a), min(n, b + 1)):
            if todo[i]:
                idx = i
                break
        if idx is None:
            while pointer < n and not todo[pointer]:
                pointer += 1
            if pointer >= n:
                break
            idx = pointer
        todo[idx] = False
        left -= 1
        info = infos[idx]
        changed = False
        if info.blocks is None or info.title is None or info.shas is None:
            try:
                book = open_book(bpath)
                ch = book.chapters[idx]
                blocks = book.blocks(ch)
                info.title = ch.title or ""
                info.is_toc = bool(ch.is_toc)
                info.blocks = len(blocks)
                info.shas = tuple(cl.short_sha(blk.sha) for blk in blocks)
            except Exception:
                info.title = info.title or ""
                info.is_toc = bool(info.is_toc)
                info.blocks = info.blocks or 0
                info.shas = ()
            info.log_sig = (-1, -1)         # hashes are new: count the log again
            computed += 1
            changed = True
        lpath = log_file(series_path, book_name, info.index, info.href)
        sig = cl.file_sig(lpath)
        if cl.log_changed(info, sig):
            info.done, info.failed = cl.count_log_by_hash(read_jsonl(lpath), info.shas) if sig != (0, 0) else (0, 0)
            info.log_sig = sig
            refreshed += 1
            changed = True
        if changed:
            batch.append(info.public())
        now = time.perf_counter()
        if batch and (len(batch) >= 40 or now - last_emit > 0.08):
            ctx.emit(("rows", batch))
            batch = []
            last_emit = now
        if computed - last_save >= 1500:
            cl.save_cache(cpath, bsig, infos)
            last_save = computed
    if batch:
        ctx.emit(("rows", batch))
    if computed or refreshed or not from_cache:
        cl.save_cache(cpath, bsig, infos)
    return {"chapters": n, "computed": computed, "refreshed": refreshed, "from_cache": from_cache,
            "seconds": round(time.perf_counter() - t0, 3), "complete": left == 0}


EXPORT_MODES = (("single", "Translation"), ("bilingual", "Bilingual"))


@dataclass
class ExportOutcome:
    path: str = ""
    name: str = ""
    folder: str = ""
    mode: str = "single"
    kept: int = 0
    skipped: tuple = ()       # (chapter index, title, missing blocks)
    size: int = 0
    problems: tuple = ()
    nothing: bool = False
    detail: str = ""


def export_selection(series_path, book: str, indices, mode: str, out_path=None) -> ExportOutcome:
    """Export the selected chapters that are fully translated. Never raises for 'nothing to export'."""
    series = Series.open(series_path)
    try:
        res = core_export(series, book, chapters=list(indices), mode=mode, out_path=out_path)
    except NothingToExport as exc:
        return ExportOutcome(mode=mode, nothing=True, detail=str(exc), folder=str(series.path / "out"))
    p = Path(res.path)
    return ExportOutcome(str(p), p.name, str(p.parent), mode, len(res.kept), tuple((s.index, s.title, s.missing)
                         for s in res.skipped), res.bytes_written, tuple(str(x) for x in res.problems))


def export_task(ctx, series_path, book: str, indices, mode: str) -> ExportOutcome:
    return export_selection(series_path, book, indices, mode)


def export_piece_task(ctx, series_path, book: str, positions, mode: str, name: str) -> ExportOutcome:
    """Export chapters of one volume into `<series>/out/` under `name`; a taken name gets ` (2)`, ` (3)` ...
    (never overwritten, window_spec 8.4). The file is written as `<name>.part` and renamed at the end, so a crash
    leaves only a `.part` that `sweep_parts` removes when the library is opened (write order rule e)."""
    out_dir = Path(series_path) / "out"
    final = pieces.unique_path(out_dir, name)
    part = final.with_name(final.name + PART)
    res = export_selection(series_path, book, positions, mode, out_path=part)
    if res.nothing:
        return res
    try:
        atomic.replace(part, final)
    except OSError:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    from dataclasses import replace as dc_replace
    return dc_replace(res, path=str(final), name=final.name, folder=str(final.parent))


PART = ".part"


def sweep_parts(library) -> int:
    """Remove export leftovers (`*.part`) in the `out` folders of every series of the library; returns how many.
    Runs when the library is opened (window rule e); a running export of this window cannot exist then."""
    n = 0
    try:
        folders = [p for p in Path(library).iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return 0
    for f in folders:
        try:
            parts = list((f / "out").glob("*" + PART))
        except OSError:
            continue
        for x in parts:
            try:
                x.unlink()
                n += 1
            except OSError:
                pass
    return n


# ---------------------------------------------------------------- reading the book for the reader pane
def find_occurrences_task(ctx, series_path, book_name: str, pattern, seen, need_pron: bool) -> int:
    """Paragraphs of the whole book that mention a term. Emits lists of (chapter, block, mentions, pronoun)
    as they are found. Chapters named in `seen` are searched when there are any, else the whole book."""
    book = open_book(book_file(series_path, book_name))
    chapters = book.chapters
    order = sorted(i for i in seen if 0 <= i < len(chapters)) if seen else range(len(chapters))
    found = 0
    batch: list = []
    last = time.perf_counter()
    for i in order:
        if ctx.cancelled:
            return found
        ch = chapters[i]
        try:
            if not seen and ch.is_toc:
                continue
            for b in book.blocks(ch):
                text = strip_markers(b.text)
                n = len(pattern.findall(text))
                if n:
                    batch.append((i, b.index, n, bool(PRONOUNS.search(text))))
        except Exception:
            continue
        now = time.perf_counter()
        if batch and (len(batch) >= 25 or now - last > 0.1):
            found += len(batch)
            ctx.emit(batch)
            batch = []
            last = now
    if batch:
        found += len(batch)
        ctx.emit(batch)
    return found


def chapter_payload_task(ctx, series_path, book_name: str, index: int) -> tuple:
    """(title, [block texts]) of one chapter."""
    book = open_book(book_file(series_path, book_name))
    ch = book.chapters[index]
    blocks = book.blocks(ch)
    return ch.title or "", [strip_markers(b.text) for b in blocks], [b.index for b in blocks]


# ---------------------------------------------------------------- series settings, prompt
def series_settings(series_path) -> dict:
    return dict(Series.open(series_path).settings)


def save_series_setting(series_path, key: str, value) -> None:
    s = Series.open(series_path)
    s.settings[key] = value
    s.save_settings()


def apply_prompt(series_path, name: str, text: str | None) -> None:
    """Make a saved prompt the series prompt (`text` None = the shipped default: prompt.txt is removed)."""
    s = Series.open(series_path)
    f = s.path / "prompt.txt"
    if text is None:
        try:
            f.unlink()
        except OSError:
            pass
        s.settings["prompt"] = "default"
    else:
        f.write_text(text, encoding="utf-8")
        s.settings["prompt"] = name
    s.save_settings()


def current_prompt_text(series_path) -> str:
    return Series.open(series_path).prompt_text()

