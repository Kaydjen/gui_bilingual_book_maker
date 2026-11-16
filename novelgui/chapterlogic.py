"""Pure logic of the chapter list: title numbers, range typing, chapter state, the state cache.

No Tk and no core imports here, so everything can be tested without a window.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

# ---------------------------------------------------------------- title numbers
_WORD_NUMBER = re.compile(r"(?:chapter|глава|ch\.?)\s*[#№.:-]?\s*(\d+)", re.I)
_FIRST_NUMBER = re.compile(r"\d+")


def title_number(title: str) -> int | None:
    """The number printed in a chapter title: the first integer after "Chapter" / "Глава", else the first
    integer of the title. A way to find a chapter, never its identity."""
    if not title:
        return None
    m = _WORD_NUMBER.search(title) or _FIRST_NUMBER.search(title)
    if not m:
        return None
    try:
        return int(m.group(m.lastindex or 0))
    except (ValueError, IndexError):
        return None


@dataclass(frozen=True)
class RangeResult:
    indices: tuple          # chapter positions, ascending, TOC pages left out
    note: str               # what was selected and how, for the screen
    by_position: bool       # at least one number was taken as a position, not a title number
    error: str = ""


def display_no(index: int) -> int:
    """Chapter position as shown to the user (1-based); the core and the files keep 0-based positions."""
    return index + 1


def from_display(number: int) -> int:
    return number - 1


_PIECE = re.compile(r"^\s*(\d+)\s*(?:[-–—:]\s*(\d+))?\s*$")


def parse_pieces(text: str) -> list[tuple[int, int]] | None:
    """'2729-2783, 3000' -> [(2729, 2783), (3000, 3000)]; None when the text is not a range list."""
    out = []
    for part in re.split(r"[,;]", text):
        if not part.strip():
            continue
        m = _PIECE.match(part)
        if not m:
            return None
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if b < a:
            a, b = b, a
        out.append((a, b))
    return out or None


def resolve_number(n: int, numbers: list, count: int) -> tuple[int | None, bool]:
    """Position of the chapter whose title number is `n`. When the number is missing or repeats in the book
    it is taken as a position instead (typed 1-based, as shown in the list). Returns (index or None,
    taken_as_position)."""
    hits = [i for i, v in enumerate(numbers) if v == n]
    if len(hits) == 1:
        return hits[0], False
    if 1 <= n <= count:
        return from_display(n), True
    return None, True


def select_by_numbers(text: str, numbers: list, toc: list) -> RangeResult:
    """Chapters named by the numbers typed in `text`. `numbers[i]` is the title number of chapter i (or None),
    `toc[i]` tells whether it is a contents page (never selected)."""
    pieces = parse_pieces(text)
    if pieces is None:
        return RangeResult((), "", False, "not a range")
    count = len(numbers)
    picked: set[int] = set()
    fallback = False
    for a, b in pieces:
        pa, fa = resolve_number(a, numbers, count)
        pb, fb = resolve_number(b, numbers, count)
        fallback = fallback or fa or fb
        if pa is None or pb is None:
            return RangeResult((), "", fallback, "no such chapter: %d" % (a if pa is None else b))
        lo, hi = min(pa, pb), max(pa, pb)
        picked.update(i for i in range(lo, hi + 1) if not toc[i])
    idx = tuple(sorted(picked))
    how = "by position" if fallback else "by title numbers"
    if not idx:
        return RangeResult((), "", fallback, "nothing to select")
    first, last = display_no(idx[0]), display_no(idx[-1])
    note = "%d chapters %s, %d to %d" % (len(idx), how, first, last)
    return RangeResult(idx, note, fallback)


# ---------------------------------------------------------------- state of a chapter
@dataclass(frozen=True)
class State:
    kind: str       # unknown | toc | none | partly | translated | failed
    done: int
    failed: int
    total: int

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / self.total) if self.total else 0.0

    @property
    def failed_fraction(self) -> float:
        return min(1.0, self.failed / self.total) if self.total else 0.0


def count_log(records) -> tuple[int, int]:
    """(done, failed) block counts of a chapter log: the latest record of every block index decides."""
    last: dict[int, str] = {}
    for r in records:
        last[r["i"]] = r.get("status", "")
    done = sum(1 for s in last.values() if s == "ok")
    return done, len(last) - done


def chapter_state(is_toc, blocks, done: int, failed: int) -> State:
    """State of one chapter from its block count (None while unknown) and log counts."""
    if is_toc:
        return State("toc", 0, 0, blocks or 0)
    if blocks is None or is_toc is None:
        return State("unknown", done, failed, blocks or 0)
    done = min(done, blocks)
    if failed > 0:
        return State("failed", done, failed, blocks)
    if blocks == 0 or done == 0:
        return State("none", done, 0, blocks)
    if done >= blocks:
        return State("translated", done, 0, blocks)
    return State("partly", done, 0, blocks)


@dataclass
class ChapterInfo:
    index: int
    href: str = ""
    title: str | None = None
    is_toc: bool | None = None
    blocks: int | None = None
    log_sig: tuple = (0, 0)     # (size, mtime_ns) of the chapter log the counts belong to
    done: int = 0
    failed: int = 0

    @property
    def state(self) -> State:
        return chapter_state(self.is_toc, self.blocks, self.done, self.failed)

    @property
    def number(self) -> int | None:
        return title_number(self.title or "")

    @property
    def known(self) -> bool:
        return self.blocks is not None

    def copy(self) -> "ChapterInfo":
        return replace(self)


def selection_size(infos, indices) -> tuple[int, int, bool]:
    """(chapters, blocks, blocks_complete) of the selected positions."""
    chapters = blocks = 0
    complete = True
    for i in indices:
        info = infos[i]
        chapters += 1
        if info.blocks is None:
            complete = False
        else:
            blocks += info.blocks
    return chapters, blocks, complete


# ---------------------------------------------------------------- cache under <series>/.state/
CACHE_VERSION = 1


def file_sig(path) -> tuple[int, int]:
    """(size, mtime_ns), (0, 0) when the file is missing."""
    try:
        st = os.stat(path)
    except OSError:
        return (0, 0)
    return (st.st_size, st.st_mtime_ns)


def cache_path(series_dir, book: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", book)
    return Path(series_dir) / ".state" / ("chapters-%s.json" % safe)


def load_cache(path, book_sig) -> dict[int, ChapterInfo] | None:
    """Cached infos when the file exists, is readable and was made for this book file (size + mtime)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("v") != CACHE_VERSION or tuple(data.get("sig", ())) != tuple(book_sig):
            return None
        out = {}
        for row in data["ch"]:
            index, href, title, toc, blocks, ls, lm, done, failed = row
            out[index] = ChapterInfo(index, href, title, toc, blocks, (ls, lm), done, failed)
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def save_cache(path, book_sig, infos) -> bool:
    """Write every chapter row (rows not computed yet keep None, so the list of files is cached too); atomic."""
    rows = [[i.index, i.href, i.title, i.is_toc, i.blocks, i.log_sig[0], i.log_sig[1], i.done, i.failed]
            for i in infos]
    data = {"v": CACHE_VERSION, "sig": list(book_sig), "ch": rows}
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def log_changed(info: ChapterInfo, sig: tuple) -> bool:
    """True when the chapter log is not the one the counts were made from."""
    return tuple(info.log_sig) != tuple(sig)
