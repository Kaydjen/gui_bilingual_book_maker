"""The only module that talks to `novelcore`. Everything the window needs from the core is here.

Functions named `*_task` take a worker context first and run in a worker thread; the rest are quick and
run on the Tk thread. Books are opened per thread (a `Book` is not shared between threads).
"""

from __future__ import annotations

import difflib
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from novelcore import Book, Series
from novelcore import profiles
from novelcore.exporter import NothingToExport
from novelcore.exporter import export as core_export
from novelcore.htmlscan import strip_markers
from novelcore.store import chapter_file_name, read_jsonl, safe_name, split_target
from novelcore.termmatch import Matcher
from novelcore.terms import FILE_NAME as TERMS_FILE
from novelcore.terms import TYPES, TermBase, import_glossary

from . import chapterlogic as cl
from .termlogic import PRONOUNS

EXPORT_READY = True
GENDERS = ("male", "female", "neuter", "plural", "unknown")
TARGETS = (("ru:Russian", "Russian"), ("uk:Ukrainian", "Ukrainian"), ("pl:Polish", "Polish"))


# ---------------------------------------------------------------- books, one per thread
_local = threading.local()


def open_book(path) -> Book:
    cache = getattr(_local, "books", None)
    if cache is None:
        cache = _local.books = {}
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


def list_series_task(ctx, library) -> list[SeriesInfo]:
    out = []
    lib = Path(library)
    try:
        folders = sorted((p for p in lib.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        return out
    for p in folders:
        if not (p / "series.json").exists():
            continue
        try:
            s = Series.open(p)
        except (FileNotFoundError, ValueError):
            continue
        out.append(SeriesInfo(str(s.settings.get("name") or p.name), str(p), str(s.settings.get("target", "")),
                              s.target_tag, tuple(s.book_names())))
    return out


def series_folder(library, name: str) -> Path:
    return Path(library) / safe_name(name, 80, "series")


def series_exists(library, name: str) -> bool:
    return (series_folder(library, name) / "series.json").exists()


def create_series_task(ctx, library, name: str, target: str, epub) -> str:
    """New series with its first book. Returns the series folder."""
    series = Series.create(library, name, target)
    series.add_book(epub)
    return str(series.path)


def add_book_task(ctx, series_path, epub) -> str:
    return Series.open(series_path).add_book(epub)


def gender_marks(tag: str) -> dict:
    """Short gender marks of the target language (core profile), plus `?` for unknown."""
    marks = dict(profiles.get(tag).gender_marks)
    marks["unknown"] = "?"
    return marks


def target_label(target: str) -> str:
    """Language name for column headers: 'ru:Russian' -> 'Russian' (profile name for a bare tag)."""
    tag, name = split_target(target)
    return profiles.get(tag, name if name != tag else None).name


def target_of(choice: str, other: str = "") -> str:
    """'tag:Name' of a language choice; `other` is the text typed for the Other choice."""
    for value, label in TARGETS:
        if choice == label:
            return value
    tag, name = split_target(other)
    return "%s:%s" % (tag, name) if tag else "ru:Russian"


# ---------------------------------------------------------------- chapters of a book
class Want:
    """The rows the user looks at now; the scanner serves them first."""

    def __init__(self):
        self._lock = threading.Lock()
        self.first = 0
        self.last = 60

    def set(self, first: int, last: int) -> None:
        with self._lock:
            self.first, self.last = first, last

    def get(self) -> tuple[int, int]:
        with self._lock:
            return self.first, self.last


def log_file(series_path, book: str, index: int, href: str) -> Path:
    name = chapter_file_name(SimpleNamespace(index=index, href=href))
    return Path(series_path) / "chapters" / safe_name(book, 80) / name


def scan_chapters_task(ctx, series_path, book_name: str, want: Want) -> dict:
    """Fills the chapter list of one book: titles, contents-page flags, block counts and translation counts.

    Emits ("skeleton", infos) once and then ("rows", infos) batches. Block counts are cached in
    <series>/.state keyed by the book file's size and mtime, log counts by each log file's size and mtime.
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
    ctx.emit(("skeleton", [i.copy() for i in infos]))
    computed = refreshed = 0
    todo = [True] * n
    left = n
    pointer = 0
    batch: list = []
    last_emit = time.perf_counter()
    last_save = computed
    while left and not ctx.cancelled:
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
        if info.blocks is None or info.title is None:
            try:
                book = open_book(bpath)
                ch = book.chapters[idx]
                info.title = ch.title or ""
                info.is_toc = bool(ch.is_toc)
                info.blocks = len(book.blocks(ch))
            except Exception:
                info.title = info.title or ""
                info.is_toc = bool(info.is_toc)
                info.blocks = info.blocks or 0
            computed += 1
            changed = True
        lpath = log_file(series_path, book_name, info.index, info.href)
        sig = cl.file_sig(lpath)
        if cl.log_changed(info, sig):
            info.done, info.failed = cl.count_log(read_jsonl(lpath)) if sig != (0, 0) else (0, 0)
            info.log_sig = sig
            refreshed += 1
            changed = True
        if changed:
            batch.append(info.copy())
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


# ---------------------------------------------------------------- terms
class TermsDoc:
    """The term base of one series with saving after every change."""

    def __init__(self, series_path, tag: str):
        self.series_path = Path(series_path)
        self.path = self.series_path / TERMS_FILE
        self.tag = tag
        self.base = TermBase.load(self.path, tag)
        self.save_ms = 0.0
        self.saves = 0

    def entries(self) -> list:
        return self.base.sorted_entries()

    def save(self) -> None:
        t0 = time.perf_counter()
        self.base.save()
        self.save_ms = (time.perf_counter() - t0) * 1000
        self.saves += 1

    # -- single changes ----------------------------------------------------
    def set_field(self, entry, field: str, value: str) -> bool:
        """The user typed or chose a value: the field is kept against model passes, its question is closed,
        the entry's status is left as it is. Returns True when something changed."""
        value = str(value).strip()
        had_q = field in entry.questions
        old = getattr(entry, field)
        if old == value and not had_q:
            return False
        if field == "type" and value not in TYPES:
            return False
        if field == "gender" and value not in GENDERS:
            return False
        setattr(entry, field, value)
        entry.questions.pop(field, None)
        entry.locked.add(field)
        self.base._touch(entry)
        self.save()
        return True

    def answer_same_as(self, entry, value: str) -> None:
        self.base.answer(entry, "same_as", value)
        self.save()

    def confirm(self, entries) -> None:
        for e in entries:
            self.base.confirm(e)
        self.save()

    def unconfirm(self, entries) -> None:
        for e in entries:
            e.status = "new"
            self.base._touch(e)
        self.save()

    def keep(self, entries, field: str) -> None:
        """Quick answer of a question: keep the value in use."""
        for e in entries:
            if field in e.questions:
                value = {"gender": e.gender, "tr": e.tr, "same_as": e.same_as}[field]
                self.base.answer(e, field, value)
        self.save()

    def delete(self, entries) -> list:
        gone = []
        for e in entries:
            if self.base.delete(e.source):
                gone.append(e)
        self.save()
        return gone

    def restore(self, gone) -> list:
        back = []
        for e in gone:
            try:
                back.append(self.base.add(
                    e.source, status=e.status, forms=e.forms, type=e.type, gender=e.gender, tr=e.tr, note=e.note,
                    hint=e.hint, same_as=e.same_as, seen=e.seen, count=e.count, evidence=e.evidence,
                    changed=e.changed, questions=e.questions, locked=e.locked, extra=e.extra))
            except ValueError:
                continue
        self.save()
        return back

    def merge(self, keep, others) -> object:
        for o in others:
            self.base.merge(keep.source, o.source)
        self.save()
        return keep

    def similar(self, entry, n: int = 10) -> list:
        key = entry.source.lower()
        others = [e for e in self.base.sorted_entries() if e is not entry]
        others.sort(key=lambda e: -difflib.SequenceMatcher(None, key, e.source.lower()).ratio())
        return others[:n]

    # -- files ---------------------------------------------------------------
    def import_files(self, files):
        rep = import_glossary(self.base, [Path(f) for f in files])
        self.save()
        return rep

    def export_file(self, path) -> None:
        self.base.save(path)


def load_terms_task(ctx, series_path, tag: str) -> TermsDoc:
    return TermsDoc(series_path, tag)


def terms_in_selection_task(ctx, doc: TermsDoc, series_path, book_name: str, indices) -> set:
    """Ids of the entries that are found in the selected chapters."""
    if not indices:
        return set()
    book = open_book(book_file(series_path, book_name))
    for attempt in range(3):
        try:
            matcher = Matcher(doc.base)
            found: set[int] = set()
            for i in indices:
                if ctx.cancelled:
                    return found
                ch = book.chapters[i]
                if ch.is_toc:
                    continue
                for e in matcher.scan_chapter(book.blocks(ch)):
                    found.add(id(e))
            return found
        except RuntimeError:        # the base changed under the scan: try again
            time.sleep(0.05)
    return set()


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


# ---------------------------------------------------------------- running a job
import inspect  # noqa: E402
import os  # noqa: E402

from novelcore import frontier as core_frontier  # noqa: E402
from novelcore import job as core_job  # noqa: E402
from novelcore.pool import DEFAULT_PACE, PACE_MAX, PACE_MIN, key_hash, read_day_exhausted, read_day_usage  # noqa: E402
from novelcore.run import Runner, from_ranges  # noqa: E402
from novelcore.store import ChapterLog  # noqa: E402

from .jobstate import JobView, assemble_problems, kept_record, manual_record  # noqa: E402

# Free-tier requests per key and day by model (AI Studio figure of 2026-11-13). Unknown model: None.
DAILY_LIMITS = {"gemini-3.1-flash-lite": 500}
HAS_CHAPTERS = "chapters" in inspect.signature(core_job.Job.__init__).parameters
HAS_GATE_FOR = callable(getattr(core_frontier, "gate_for", None))
SeriesBusy = core_job.SeriesBusy


@dataclass
class RunConfig:
    keys: list
    models: list
    pace: float | None = None
    base_url: str | None = None


def clean_pace(value):
    """Pace in requests a minute, or None for the core default; raises ValueError outside 1-120."""
    if value in (None, ""):
        return None
    p = float(value)
    if not PACE_MIN <= p <= PACE_MAX:
        raise ValueError("pace must be from %d to %d" % (PACE_MIN, PACE_MAX))
    return p


def default_pace() -> int:
    return DEFAULT_PACE


def job_view(series_path) -> JobView:
    """The job of a series as the window shows it (cheap: reads the record and the lock)."""
    st = core_job.job_status(series_path)
    rec = st["job"]
    if rec is None:
        return JobView()
    state = "interrupted" if st["interrupted"] else rec["state"]
    if isinstance(rec.get("chapters"), list):
        chapters = tuple(from_ranges(rec["chapters"]))
    else:
        last = rec.get("last")
        chapters = tuple(range(rec.get("first") or 0, last + 1)) if isinstance(last, int) else ()
    blocked = st["blocked_chapter"]
    return JobView(state, rec["book"], chapters, st["blocks_done"], st["blocks_total"], st["chapters_done"],
                   st["chapters_total"], st["blocks_failed"], st["terms_pending"],
                   blocked if isinstance(blocked, int) else None, rec.get("wake_at"), str(rec.get("error") or ""),
                   foreign=bool(st["running"] and st["pid"] != os.getpid()))


class RunHandle:
    """Control of one run (a job or a sample) started by `run_task` / `sample_task`."""

    def __init__(self):
        self.job = None
        self.runner = None
        self.stopping = False
        self.finished = threading.Event()

    def stop(self) -> None:
        self.stopping = True
        target = self.job or self.runner
        if target is not None:
            target.stop()


def make_gate(ctx, handle, series: Series, book: str):
    """Callable chapter -> unreviewed terms. None when the core supplies its own gate (frontier.gate_for)."""
    if HAS_GATE_FOR:
        return None
    base = TermBase.load(series.path / TERMS_FILE, series.target_tag)
    fr = core_frontier.Frontier.for_series(series, book, base)
    fr.scan(progress=lambda d, t: ctx.emit(("scan", d, t)), cancel=lambda: handle.stopping)
    return fr.check_chapter


def run_task(ctx, handle: RunHandle, series_path, book: str, chapters, cfg: RunConfig, resume: bool = False):
    """Start a job (or continue the recorded one) and relay its events; returns the run summary.
    Emits ("event", Event), ("scan", done, total), ("busy", message)."""
    series = Series.open(series_path)
    try:
        try:
            gate = make_gate(ctx, handle, series, book)
            if handle.stopping:
                return {"stopped": True}
            kw = dict(base_url=cfg.base_url, pace=cfg.pace)
            if gate is not None:
                kw["gate"] = gate
            if resume:
                job = core_job.resume(series, cfg.keys, cfg.models, **kw)
            elif HAS_CHAPTERS:
                job = core_job.Job(series, book, cfg.keys, cfg.models, chapters=list(chapters), **kw)
            else:
                job = core_job.Job(series, book, cfg.keys, cfg.models, min(chapters), max(chapters), **kw)
            handle.job = job
            job.start()
        except (core_job.SeriesBusy, core_job.JobError) as exc:
            ctx.emit(("busy", str(exc)))
            return {"busy": True}
        sent_stop = False
        while True:
            done = False
            for ev in job.drain():
                ctx.emit(("event", ev))
                done = done or ev.kind == "done"
            if done:
                break
            if handle.stopping and not sent_stop:
                sent_stop = True
                job.stop()
            if job._thread is not None and not job._thread.is_alive():
                for ev in job.drain():
                    ctx.emit(("event", ev))
                break
            time.sleep(0.05)
        job.join()
        return {"stopped": handle.stopping, "error": job.error or (str(job.exception) if job.exception else "")}
    finally:
        handle.finished.set()


def sample_task(ctx, handle: RunHandle, series_path, book: str, chapter: int, blocks: int, cfg: RunConfig):
    """Translate the first blocks of one chapter into samples/ (never gated, never written to chapters/)."""
    series = Series.open(series_path)
    try:
        r = Runner(series, book, cfg.keys, cfg.models, state_path=series.path / ".state" / "pool.json",
                   base_url=cfg.base_url, pace=cfg.pace, end_on_quota=True, gate=None)
        r.listener = lambda ev: ctx.emit(("event", ev))
        handle.runner = r
        if handle.stopping:
            return {"stopped": True}
        return r.sample(chapter, blocks)
    finally:
        handle.finished.set()


def sample_rows(series_path, book: str, chapter: int, n: int) -> list:
    """[(source text, translation or None, reason)] of the first n blocks of a sampled chapter."""
    series = Series.open(series_path)
    with series.open_book(book) as b:
        ch = b.chapters[chapter]
        log = ChapterLog(series.sample_log(book, ch).path)
        rows = []
        for blk in b.blocks(ch)[:n]:
            rec = log.lookup(blk.index, blk.sha)
            src = " ".join(strip_markers(blk.text).split())
            if rec is None:
                rows.append((src, None, ""))
            elif rec.get("status") == "ok":
                rows.append((src, " ".join(strip_markers(rec["text"]).split()), ""))
            else:
                rows.append((src, None, str(rec.get("reason") or "failed")))
        return rows


# ---------------------------------------------------------------- failed blocks
def problems_task(ctx, series_path, book: str, chapters) -> list:
    """Failed blocks of the given chapters (latest record of the block is not ok)."""
    series = Series.open(series_path)
    out = []
    with series.open_book(book) as b:
        for i in chapters:
            if ctx.cancelled or i >= len(b.chapters):
                break
            ch = b.chapters[i]
            path = series.chapter_log(book, ch).path
            if not path.exists() or cl.count_log(read_jsonl(path))[1] == 0:
                continue
            log = ChapterLog(path)
            blocks = [(blk.index, blk.sha, " ".join(strip_markers(blk.text).split())) for blk in b.blocks(ch)]
            out.extend(assemble_problems(i, ch.title or "", blocks, log.lookup))
    return out


def resolve_problems_task(ctx, series_path, book: str, problems, action: str, typed: str = "") -> int:
    """Keep the original text (`keep`) or a typed translation (`manual`) for failed blocks; appends ok records
    to the chapter logs through the core's ChapterLog. Returns the number of blocks written."""
    series = Series.open(series_path)
    now = time.time()
    done = 0
    by_chapter: dict = {}
    for p in problems:
        by_chapter.setdefault(p.chapter, []).append(p)
    with series.open_book(book) as b:
        for i, items in by_chapter.items():
            ch = b.chapters[i]
            texts = {blk.index: blk.text for blk in b.blocks(ch)}
            recs = []
            for p in items:
                if action == "keep":
                    recs.append(kept_record(p.block, p.sha, texts.get(p.block, p.source), now))
                elif typed.strip():
                    recs.append(manual_record(p.block, p.sha, typed, now))
            series.chapter_log(book, ch).append(recs)
            done += len(recs)
    return done


# ---------------------------------------------------------------- quota
@dataclass
class Quota:
    keys: int = 0
    models: int = 0
    per_key: int | None = None     # daily limit of the first model
    used: int = 0
    left: int | None = None        # None when a model's limit is unknown
    capacity: int | None = None    # requests a full day allows


def quota_status(library, keys, models, now: float) -> Quota:
    """Requests left today over all keys. Counts come from the pool state files of every series of the
    library (the daily quota belongs to the key, not to a series)."""
    hashes = [key_hash(k) for k in keys]
    used: dict = {}
    exhausted: set = set()
    try:
        folders = [p for p in Path(library).iterdir() if p.is_dir()]
    except OSError:
        folders = []
    for f in folders:
        state = f / ".state" / "pool.json"
        if not state.exists():
            continue
        for kh, per in read_day_usage(state, now).items():
            for m, n in per.items():
                used[(kh, m)] = used.get((kh, m), 0) + n
        exhausted |= read_day_exhausted(state, now)
    limits = [DAILY_LIMITS.get(m) for m in models]
    total_used = sum(used.get((h, m), 0) for h in hashes for m in models)
    left = cap = None
    if hashes and models and all(x is not None for x in limits):
        left = cap = 0
        for h in hashes:
            for m, lim in zip(models, limits):
                cap += lim
                if "%s|%s" % (h, m) not in exhausted:
                    left += max(0, lim - used.get((h, m), 0))
    return Quota(len(hashes), len(models), limits[0] if limits else None, total_used, left, cap)


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


def terms_blocking_task(ctx, series_path, book: str, chapter: int) -> int:
    """Unreviewed terms that hold back one chapter now (from the cached scan of the whole book)."""
    series = Series.open(series_path)
    use = gate_candidates()
    fr = core_frontier.Frontier.for_series(series, book)
    fr.scan(cancel=lambda: ctx.cancelled, mine=use)
    return fr.check_chapter(chapter, candidates=use)


# ---------------------------------------------------------------- the terms frontier
def make_frontier(doc: "TermsDoc", series_path, book: str):
    """The whole-book frontier over the base of the terms screen (shared, so a change shows at once)."""
    return core_frontier.Frontier(doc.base, book_file(series_path, book), Path(series_path) / ".state",
                                  book_name=book)


def frontier_scan_task(ctx, fr, force: bool = False):
    """Scan the book (cached under .state); emits (done, total). Cancelled with the token."""
    fr.scan(progress=lambda d, t: ctx.emit((d, t)), cancel=lambda: ctx.cancelled, force=force)
    return fr


def frontier_ready(fr) -> bool:
    return fr is not None and fr._d is not None


def gate_candidates() -> bool:
    """Whether mined names hold a job back (the core decides; read live)."""
    return bool(core_frontier.GATE_CANDIDATES)


def next_items(fr, indices) -> list:
    """Unreviewed items of the chapters: objects with text, kind, count, first, candidate, blocking.
    Blocking items first (frontier order: first chapter, then count), then the suggestions. Candidates are mined
    names that are not in the base; they block only while the core gates on them."""
    acc: dict = {}
    for c in sorted(indices):
        for it in fr.unreviewed(c, candidates=True):
            key = (it.kind == core_frontier.KIND_CANDIDATE, it.text.lower())
            a = acc.get(key)
            if a is None:
                acc[key] = [it.text, it.kind, it.count, c]
            else:
                a[2] += it.count
    gate = gate_candidates()
    out = [SimpleNamespace(text=a[0], kind=a[1], count=a[2], first=a[3],
                           candidate=a[1] == core_frontier.KIND_CANDIDATE,
                           blocking=gate or a[1] != core_frontier.KIND_CANDIDATE) for a in acc.values()]
    out.sort(key=lambda it: (not it.blocking, it.first, -it.count, it.text.lower()))
    return out


def _doc_add_confirmed(self, source: str, tr: str, count: int = 0, first=None):
    """A mined candidate the user translated: becomes a confirmed entry."""
    e = self.base.add(source, status="confirmed", tr=str(tr).strip(), count=count,
                      seen={first} if first is not None else None)
    self.save()
    return e


TermsDoc.add_confirmed = _doc_add_confirmed


def new_candidate(text: str, count: int, first: int):
    """A row for a mined name that is not in the base (shown with an empty translation)."""
    from novelcore.terms import Entry
    e = Entry(text, status="new", tr="", count=count, seen={first})
    e.cand = True
    e.suggest = False
    return e
