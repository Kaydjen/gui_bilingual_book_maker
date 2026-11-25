"""The Export screen as plain rows (window_spec 8.1-8.7, 10.5, 14.12, 14.14): pieces, gap rows, the running job's row, the
marks, the boxes, the ranges of a choice, the file name, the bar and the result texts.

Pure (no Qt, no core): the list model and the view-model only turn these tuples into Qt roles.

A chapter is `ok` (fully translated, selectable), `fail` (has a failed block: it stays in its piece, never in the file),
`run` (not translated yet, but part of the job that runs now), `gap` (anything else) or `toc` (a contents page: skipped,
never a break). A piece is a run of ok / fail chapters that holds at least one ok chapter; it is split where the export
history changes (a part already exported is its own row).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OK, FAIL, RUN, GAP, TOC = "ok", "fail", "run", "gap", "toc"
PIECE, CHAPTER, GAP_ROW, RUN_ROW = "piece", "chapter", "gap", "run"
ROLE_NAMES = ("kind", "label", "title", "mark", "markKind", "box", "flags", "span")
OPEN_LIMIT = 4000


def sp(n: int) -> str:
    """`2 749` (a space between thousands, as the mock-up writes them)."""
    return "{:,}".format(int(n)).replace(",", " ")


def plural(n: int, one: str, many: str) -> str:
    return "%s %s" % (sp(n), one if n == 1 else many)


def label_of(a: int, b: int) -> str:
    return str(a) if a == b else "%d-%d" % (a, b)


# ---------------------------------------------------------------- the chapters
def kinds(infos, live=None) -> list:
    """The kind of every chapter position. `live` = {position: (done, total, failed)} of the job that runs in this volume
    now (None without one): a chapter it finished joins the pieces at once, the ones it still has are `run`."""
    live = live or {}
    return [kind_of(i, live.get(i.index)) for i in infos]


def kind_of(info, entry=None) -> str:
    """One chapter's kind; `entry` = (done, total, failed) from the running job, if it covers the chapter."""
    if info.is_toc:
        return TOC
    k = info.state.kind
    own = OK if k == "translated" else FAIL if k == "failed" else GAP
    if entry is None:
        return own
    done, total, failed = entry
    if failed:
        return FAIL
    if total and done >= total:
        return OK
    return own if own == OK else RUN


def all_translated(infos, positions, live=None) -> bool:
    """True when every chapter of `positions` is fully translated now (the header's `Export` glows then, 7.16)."""
    live = live or {}
    return bool(positions) and all(0 <= p < len(infos) and kind_of(infos[p], live.get(p)) == OK for p in positions)


def numbers(infos) -> list:
    """The number the user reads for each position: the one in the title, else the position (1-based)."""
    return [i.number if i.number is not None else i.index + 1 for i in infos]


# ---------------------------------------------------------------- rows
@dataclass(frozen=True)
class Group:
    """One row of the map: a run of chapters of one kind (a piece is also split by the export history)."""
    kind: str                       # piece | gap | run
    first: int                      # positions, inclusive
    last: int
    oks: tuple = ()                 # positions of the fully translated chapters
    fails: tuple = ()               # positions with failed blocks
    stamp: tuple | None = None      # (date, file) of the export these chapters went into, None = never exported
    members: tuple = ()             # every non-contents position of the row (opened pieces list them)


def groups(kind_list, history) -> list:
    """The map of a volume in book order. `history`: {position: (date, file)} of the exported chapters."""
    out: list = []
    run: list = []
    cur = None

    def flush():
        nonlocal run, cur
        if run:
            out.extend(_close(cur, run, history))
        run, cur = [], None
    for pos, k in enumerate(kind_list):
        if k == TOC:
            continue
        side = PIECE if k in (OK, FAIL) else k
        if side != cur:
            flush()
            cur = side
        run.append((pos, k))
    flush()
    return out


def _close(side, run, history) -> list:
    if side == GAP:
        return [Group(GAP_ROW, run[0][0], run[-1][0], members=tuple(p for p, _k in run))]
    if side == RUN:
        return [Group(RUN_ROW, run[0][0], run[-1][0], members=tuple(p for p, _k in run))]
    cut: list = []
    key = _UNSET
    cur: list = []
    for pos, k in run:
        if k == OK:
            stamp = history.get(pos)
            if key is not _UNSET and stamp != key:
                cut.append((key, cur))
                cur = []
            key = stamp
        cur.append((pos, k))
    cut.append((None if key is _UNSET else key, cur))
    out = []
    for stamp, items in cut:
        oks = tuple(p for p, k in items if k == OK)
        fails = tuple(p for p, k in items if k == FAIL)
        kind = PIECE if oks else GAP_ROW           # a run of failed chapters only: no box, the link to the problem
        out.append(Group(kind, items[0][0], items[-1][0], oks, fails, stamp if oks else None,
                         tuple(p for p, _k in items)))
    return out


_UNSET = object()


def ticked_count(g: Group, ticks) -> int:
    return sum(1 for p in g.oks if p in ticks)


def box_of(g: Group, ticks) -> str:
    if g.kind != PIECE:
        return "none"
    t = ticked_count(g, ticks)
    return "empty" if t == 0 else ("on" if t >= len(g.oks) else "part")


def mark_of(g: Group, ticks) -> tuple:
    """(text, kind) of the ONE mark of a row, by priority: problem > part > Translating > exported > Translate ›."""
    if g.kind == RUN_ROW:
        return "Translating", "wave"
    if g.fails:
        return plural(len(g.fails), "problem", "problems"), "problem"
    if g.kind == GAP_ROW:
        return "Translate ›", "go"
    t = ticked_count(g, ticks)
    if 0 < t < len(g.oks):
        return "%s of %s" % (sp(t), sp(len(g.oks))), "part"
    if g.stamp is not None:
        return "exported", "exported"
    return "", ""


def span_of(g: Group, ticks, nums) -> str:
    """`from|to` of an opened piece's two fields: the ticked part of it, else the whole piece."""
    mine = [p for p in g.oks if p in ticks] or list(g.oks)
    return "%d|%d" % (nums[mine[0]], nums[mine[-1]]) if mine else ""


def rows_of(gs, kind_list, nums, titles, ticks, opened) -> tuple:
    """(rows, refs): the rows the list shows as tuples of ROLE_NAMES, opened pieces followed by their chapters, and for each
    row its reference: the index of its group, or `-(position + 1)` for a chapter row. `opened` = positions of the first
    chapter of the opened pieces."""
    lo = min(ticks) if ticks else None
    hi = max(ticks) if ticks else None
    out, refs = [], []
    for gi, g in enumerate(gs):
        mark, mk = mark_of(g, ticks)
        t = ticked_count(g, ticks) if g.kind == PIECE else 0
        flags = []
        if t:
            flags.append("sel")
        elif g.kind == PIECE and g.stamp is not None:
            flags.append("old")
        if g.kind in (GAP_ROW, RUN_ROW):
            flags.append("faint")
        if not t and lo is not None and g.first > lo and g.last < hi and g.kind in (PIECE, GAP_ROW):
            flags.append("hatch")
        is_open = g.kind == PIECE and g.first in opened
        if is_open:
            flags.append("open")
        out.append((g.kind, label_of(nums[g.first], nums[g.last]), "", mark, mk, box_of(g, ticks), ",".join(flags),
                    span_of(g, ticks, nums) if is_open else ""))
        refs.append(gi)
        if is_open:
            more = _chapter_rows(g, kind_list, nums, titles, ticks)
            out.extend(r for r, _p in more)
            refs.extend(-(p + 1) for _r, p in more)
    return out, refs


def _chapter_rows(g, kind_list, nums, titles, ticks) -> list:
    out = []
    for p in g.members[:OPEN_LIMIT]:
        bad = kind_list[p] == FAIL
        on = p in ticks
        out.append(((CHAPTER, str(nums[p]), titles[p], "1 problem" if bad else "", "problem" if bad else "",
                     "none" if bad else ("on" if on else "empty"), "sel" if on else "", ""), p))
    return out


# ---------------------------------------------------------------- the choice (ticks)
def toggled(ticks, oks) -> set:
    """A click on a row or its box: every chapter of the row, or none when they all are ticked already."""
    ticks = set(ticks)
    if oks and all(p in ticks for p in oks):
        ticks.difference_update(oks)
    else:
        ticks.update(oks)
    return ticks


def between(ticks, all_oks, a: int, b: int) -> set:
    """Shift: every fully translated chapter from position a to b, across pieces, joins the choice."""
    lo, hi = (a, b) if a <= b else (b, a)
    out = set(ticks)
    out.update(p for p in all_oks if lo <= p <= hi)
    return out


def all_oks(gs) -> list:
    return [p for g in gs if g.kind == PIECE for p in g.oks]


def head_state(ticks, everything) -> str:
    """none | some | all: the head box counts every translated chapter."""
    n = sum(1 for p in everything if p in ticks)
    return "none" if n == 0 else ("all" if n >= len(everything) else "some")


def head_toggled(ticks, everything) -> set:
    return set() if head_state(ticks, everything) == "all" else set(everything)


def default_ticks(gs) -> set:
    """On opening: the newest piece (in book order) that was never exported; nothing when there is none."""
    for g in reversed(gs):
        if g.kind == PIECE and g.stamp is None:
            return set(g.oks)
    return set()


def ranges(ticks, kind_list, nums) -> list:
    """[(first number, last number)] of the choice: consecutive chapters make one range; contents pages and chapters with a
    failed block between two chosen ones do not split it."""
    out: list = []
    prev = None
    for p in sorted(ticks):
        if prev is not None and all(kind_list[q] in (TOC, FAIL) for q in range(prev + 1, p)):
            out[-1][1] = nums[p]
        else:
            out.append([nums[p], nums[p]])
        prev = p
    return [(a, b) for a, b in out]


def range_text(rs) -> str:
    return ", ".join(label_of(a, b) for a, b in rs)


def summary(ticks, kind_list, nums) -> tuple:
    """(`54 chapters`, `· 2697-2750`) of the line above the buttons; ("", "") with nothing chosen."""
    if not ticks:
        return "", ""
    return plural(len(ticks), "chapter", "chapters"), "· " + range_text(ranges(ticks, kind_list, nums))


# ---------------------------------------------------------------- names (8.4, 8.7, 13.11)
NAME_LIMIT = 120


def file_name(series: str, rs, tag: str, source_tag: str = "") -> str:
    """`<Series> 2697-2750 ru.epub`, `<Series> 1-1200, 2697-2750 ru.epub`, `... ru+en.epub`. A very long list of ranges is
    shortened to the first and last number (the file still names the language)."""
    span = range_text(rs)
    if len(series) + len(span) > NAME_LIMIT and rs:
        span = "%d-%d" % (rs[0][0], rs[-1][1])
    tail = tag if not source_tag else "%s+%s" % (tag, source_tag)
    return "%s %s %s.epub" % (series, span, tail)


def button_names(target: str, source: str) -> tuple:
    """(`Export Russian`, `Russian + English`); without a language `Export` and `+ English` (the buttons are dim then)."""
    if not target:
        return "Export", "+ %s" % source
    return "Export %s" % target, "%s + %s" % (target, source)


def segments(total: int, busy: str, target: str, source: str, why: str, tips: tuple) -> list:
    """The bottom bar: two segments of equal weight. `busy` = "" | "single" | "bilingual" (the pressed one shows
    `Exporting…`, the other stays dim); `why` = the reason both are dim ("" when they work)."""
    a, b = button_names(target, source)
    off = bool(why) or bool(busy)
    out = []
    for sid, text, tip in (("single", a, tips[0]), ("bilingual", b, tips[1])):
        shown = "Exporting…" if busy == sid else text
        out.append({"id": sid, "text": shown, "kind": "off" if off else "", "tip": why if why and not busy else tip,
                    "busy": busy == sid})
    return out


# ---------------------------------------------------------------- the result (8.5, 9.9)
def size_text(n: int) -> str:
    return "%.1f MB" % (n / 1e6) if n >= 1e5 else "%d KB" % max(1, round(n / 1e3))


def result_texts(kept: int, size: int, left_out: int) -> tuple:
    """(`54 chapters · 0.9 MB`, the dim fact of chapters the user left out by choice or "")."""
    facts = "%s · %s" % (plural(kept, "chapter", "chapters"), size_text(size))
    return facts, ("%d not translated yet, left out" % left_out if left_out else "")


_BAD = re.compile(r"[\r\n]+")


def error_text(exc) -> str:
    """The reason of a failed export in plain words (the facade raises OSError for disk problems)."""
    text = _BAD.sub(" ", str(exc) or type(exc).__name__).strip()
    low = text.lower()
    if "no space" in low or "disk full" in low or getattr(exc, "errno", None) == 28:
        return "The disk is full. Free some space, then try again."
    if "permission" in low or "access is denied" in low or getattr(exc, "errno", None) in (1, 13):
        return "The file or the folder cannot be written. Close the program that holds it, then try again."
    if "helper process stopped" in low:
        return "The export stopped unexpectedly. Try again."
    return text[:200] if text else "The export failed."
