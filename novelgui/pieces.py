"""The Export step's pure logic (window_spec 8.1-8.5): ready pieces of a volume, chapter numbers and positions,
file names. No Tk and no core imports.

A chapter is `ok` (fully translated), `fail` (has failed blocks), `gap` (anything else: not translated, partly,
not known yet) or a contents page (skipped, never a break). A piece is a run of chapters without a gap that holds
at least one ok chapter; failed chapters inside it stay in it (it is not split), failed chapters at its edges are
not part of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import chapterlogic as cl

OK, FAIL, GAP, TOC = "ok", "fail", "gap", "toc"


def kind_of(info) -> str:
    k = info.state.kind
    if k == "toc":
        return TOC
    if k == "translated":
        return OK
    if k == "failed":
        return FAIL
    return GAP


def number_of(info) -> int:
    """The number shown for a chapter: the one printed in its title, else its position (1-based)."""
    n = info.number
    return n if n is not None else cl.display_no(info.index)


@dataclass(frozen=True)
class Piece:
    first: int          # position of the first chapter (0-based)
    last: int           # position of the last chapter
    first_no: int       # numbers as shown
    last_no: int
    done: int           # fully translated chapters
    total: int          # chapters of the run (translated + with problems; contents pages not counted)
    problems: int       # chapters with failed blocks inside the run
    problem_at: tuple = ()      # their positions

    @property
    def label(self) -> str:
        return number_label(self.first_no, self.last_no)

    @property
    def complete(self) -> bool:
        return self.problems == 0

    def detail(self) -> str:
        """`53 of 54 · 1 problem`, empty when everything of the run is translated."""
        if not self.problems:
            return ""
        return "%d of %d · %d %s" % (self.done, self.total, self.problems,
                                          "problem" if self.problems == 1 else "problems")


def number_label(a: int, b: int) -> str:
    return str(a) if a == b else "%d-%d" % (a, b)


def compute(infos) -> list:
    """Ready pieces of a volume in book order, from the chapter states as they are now."""
    out = []
    run: list = []          # (position, kind)

    def flush():
        while run and run[0][1] == FAIL:
            run.pop(0)
        while run and run[-1][1] == FAIL:
            run.pop()
        if run and any(k == OK for _p, k in run):
            a, b = run[0][0], run[-1][0]
            fails = tuple(p for p, k in run if k == FAIL)
            out.append(Piece(a, b, number_of(infos[a]), number_of(infos[b]), sum(1 for _p, k in run if k == OK),
                             len(run), len(fails), fails))
        run.clear()
    for i, info in enumerate(infos):
        k = kind_of(info)
        if k == TOC:
            continue
        if k == GAP:
            flush()
        else:
            run.append((i, k))
    flush()
    return out


def positions_for(infos, a: int, b: int) -> tuple:
    """(positions, by_position): the chapters named by the numbers a..b (inclusive, swapped when reversed), by
    the numbers in the titles, else by position; contents pages never. Numbers that do not exist are absent."""
    if a > b:
        a, b = b, a
    numbers = [i.number for i in infos]
    toc = [bool(i.is_toc) for i in infos]
    got, by_pos = cl.select_piece(a, b, numbers, toc)
    return tuple(sorted(got)), by_pos


_PAIR = re.compile(r"^\s*(\d+)\s*$")


def parse_number(text: str):
    """The number typed into a `from` / `to` field, or None."""
    m = _PAIR.match(text or "")
    return int(m.group(1)) if m else None


def piece_at(pieces, a: int, b: int):
    """The piece that holds the typed pair a..b entirely, else None."""
    if a > b:
        a, b = b, a
    for p in pieces:
        lo, hi = sorted((p.first_no, p.last_no))
        if lo <= a and b <= hi:
            return p
    return None


def kept_positions(infos, positions) -> list:
    """The chapters of `positions` the export will write: the fully translated ones."""
    return [p for p in positions if 0 <= p < len(infos) and kind_of(infos[p]) == OK]


# ---------------------------------------------------------------- names (8.4)
def file_name(series: str, first_no: int, last_no: int, tag: str, source_tag: str = "") -> str:
    """`<Series> <first>-<last> <tag>.epub`, or `... <tag>+<source tag>.epub` for the bilingual book."""
    tail = tag if not source_tag else "%s+%s" % (tag, source_tag)
    return "%s %s %s.epub" % (series, number_label(first_no, last_no), tail)


def unique_path(folder, name: str) -> Path:
    """`folder/name`, or `folder/<stem> (2).epub`, `(3)` ... when the name is taken. Never an existing file."""
    folder = Path(folder)
    p = folder / name
    if not p.exists():
        return p
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    k = 2
    while True:
        cand = folder / ("%s (%d)%s" % (stem, k, "." + ext if ext else ""))
        if not cand.exists():
            return cand
        k += 1


def size_text(n: int) -> str:
    return "%.1f MB" % (n / 1e6) if n >= 1e6 else "%d KB" % max(1, round(n / 1e3))


def result_line(kept: int, left_out: int, size: int) -> tuple:
    """The result panel's line as parts: (`54 chapters`, `3 not translated yet, left out` or "", `2.4 MB`)."""
    head = "%d %s" % (kept, "chapter" if kept == 1 else "chapters")
    out = "%d not translated yet, left out" % left_out if left_out else ""
    return head, out, size_text(size)
