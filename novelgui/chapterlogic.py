"""Pure logic of the chapter list: title numbers, range typing, chapter state, the state cache.

No Tk and no core imports here, so everything can be tested without a window.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

from . import atomic

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


def unique_hit(n: int, numbers: list) -> int | None:
    """Position of the one chapter whose title number is `n`, else None."""
    hits = [i for i, v in enumerate(numbers) if v == n]
    return hits[0] if len(hits) == 1 else None


def select_piece(a: int, b: int, numbers: list, toc: list) -> tuple[set, bool]:
    """Chapters of one typed range a-b (inclusive, a <= b) and whether the numbers were taken as list positions.
    Title numbers decide; a number that does not exist is simply not in the selection. Only when no chapter
    carries a number inside the range are the numbers taken as positions of the list (typed 1-based)."""
    count = len(numbers)
    pa, pb = unique_hit(a, numbers), unique_hit(b, numbers)
    if pa is not None and pb is not None:
        lo, hi = min(pa, pb), max(pa, pb)
        return {i for i in range(lo, hi + 1) if not toc[i]}, False
    by_number = {i for i, v in enumerate(numbers) if v is not None and a <= v <= b and not toc[i]}
    if by_number:
        return by_number, False
    lo, hi = max(a, 1), min(b, count)
    return {from_display(n) for n in range(lo, hi + 1) if not toc[from_display(n)]}, True


def select_by_numbers(text: str, numbers: list, toc: list) -> RangeResult:
    """Chapters named by the ranges typed in `text` (window_spec 4.5): inclusive, `2750-2697` is `2697-2750`,
    title numbers first, list positions as the fallback, numbers that do not exist are left out. `numbers[i]`
    is the title number of chapter i (or None), `toc[i]` tells whether it is a contents page (never selected)."""
    pieces = parse_pieces(text)
    if pieces is None:
        return RangeResult((), "", False, "not a range")
    picked: set[int] = set()
    fallback = False
    for a, b in pieces:
        got, pos = select_piece(a, b, numbers, toc)
        picked |= got
        fallback = fallback or (pos and bool(got))
    idx = tuple(sorted(picked))
    if not idx:
        return RangeResult((), "", fallback, "no chapter in this range")
    return RangeResult(idx, "%d %s" % (len(idx), "chapter" if len(idx) == 1 else "chapters"), fallback)


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


SHA_LEN = 16    # leading hex digits of a block's source hash kept in the cache (enough to tell versions apart)


def short_sha(sha) -> str:
    return str(sha or "")[:SHA_LEN]


def count_log_by_hash(records, shas) -> tuple[int, int]:
    """(done, failed) block counts of a chapter log against the CURRENT blocks of the chapter (window_spec
    14.12): a block counts only by a record of its own (index, source hash), the latest such record decides. An
    ok line left from an older text of the block (changed by Update file) does not count. `shas[i]` is the
    (short) hash of block i; records of indices outside the chapter are ignored."""
    last: dict[tuple[int, str], str] = {}
    for r in records:
        last[(r["i"], short_sha(r.get("src_sha")))] = r.get("status", "")
    done = failed = 0
    for i, sha in enumerate(shas):
        st = last.get((i, short_sha(sha)))
        if st is None:
            continue
        if st == "ok":
            done += 1
        else:
            failed += 1
    return done, failed


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
    shas: tuple | None = None   # short source hashes of the blocks (None = unknown); never sent to a screen

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

    def public(self) -> "ChapterInfo":
        """A copy without the block hashes (what a screen gets)."""
        return replace(self, shas=None)


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
CACHE_VERSION = 2     # 2: block hashes per chapter (counts by (index, hash))


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
            index, href, title, toc, blocks, ls, lm, done, failed = row[:9]
            shas = tuple(row[9]) if len(row) > 9 and isinstance(row[9], list) else None
            out[index] = ChapterInfo(index, href, title, toc, blocks, (ls, lm), done, failed, shas)
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def save_cache(path, book_sig, infos) -> bool:
    """Write every chapter row (rows not computed yet keep None, so the list of files is cached too); atomic."""
    rows = [[i.index, i.href, i.title, i.is_toc, i.blocks, i.log_sig[0], i.log_sig[1], i.done, i.failed]
            + ([list(i.shas)] if i.shas is not None else []) for i in infos]
    data = {"v": CACHE_VERSION, "sig": list(book_sig), "ch": rows}
    return atomic.try_write_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def log_changed(info: ChapterInfo, sig: tuple) -> bool:
    """True when the chapter log is not the one the counts were made from."""
    return tuple(info.log_sig) != tuple(sig)
