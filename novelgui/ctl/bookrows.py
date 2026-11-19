"""The Books screen as plain rows: series and book rows, book labels, chapter rows, the range text, the next step.

Pure (no Qt): the list models and the view-model only turn these tuples into Qt roles (window_spec 4.7, review D6).
"""

from __future__ import annotations

from .. import chapterlogic as cl

# ---------------------------------------------------------------- book labels (4.7)


def book_label(info, stem: str) -> str:
    """The label shown for a book: the user's own, else `Book N` by the position in the natural order of the file names."""
    own = dict(info.labels).get(stem)
    if own:
        return own
    try:
        return "Book %d" % (list(info.books).index(stem) + 1)
    except ValueError:
        return stem


def book_labels(info) -> list:
    return [(stem, book_label(info, stem)) for stem in info.books]


def label_for_new(info_books, labels, stem: str) -> str:
    """The label a file will get when it joins a series whose books are `info_books` (natural order is applied)."""
    from ..libraryrules import natural_key
    order = sorted(set(info_books) | {stem}, key=natural_key)
    own = dict(labels).get(stem)
    return own or "Book %d" % (order.index(stem) + 1)


# ---------------------------------------------------------------- series rows
# (kind, key, text, tail, count, mode, editing); kind series | book; mode "" | parent | selected | broken
def series_rows(infos, selected_path: str, selected_book: str, editing=None) -> list:
    """Rows of the left list: the series, and under the selected series its books when there are two or more.
    `editing` = (kind, key) of the row being renamed."""
    rows = []
    for s in infos:
        many = len(s.books) > 1 and not s.broken
        chosen = s.path == selected_path
        if s.broken:
            mode = "brokenSelected" if chosen else "broken"
        elif chosen and many:
            mode = "parent"
        elif chosen:
            mode = "selected"
        else:
            mode = ""
        count = len(s.books) if many and not chosen else 0
        rows.append(("series", s.path, s.name, "" if s.broken else _tag(s), count, mode,
                     editing == ("series", s.path)))
        if chosen and many:
            for stem, label in book_labels(s):
                rows.append(("book", stem, label, "", 0, "selected" if stem == selected_book else "",
                             editing == ("book", stem)))
    return rows


def _tag(info) -> str:
    return info.tag if info.chosen else ""


def row_index(rows, kind: str, key: str) -> int:
    for i, r in enumerate(rows):
        if r[0] == kind and r[1] == key:
            return i
    return -1


def pick_book(info, wanted: str = "") -> str:
    """The book to open in a series: the wanted one when it exists, else the first one."""
    if info is None or not info.books:
        return ""
    return wanted if wanted in info.books else info.books[0]


# ---------------------------------------------------------------- chapter rows
BAR = {"none": 0.0, "unknown": 0.0, "toc": 0.0}


def state_text(state) -> str:
    if state.kind == "translated":
        return "translated"
    if state.kind == "failed":
        return "%d failed" % state.failed
    if state.kind == "partly":
        return "%d / %d" % (state.done, state.total)
    return ""


def chapter_row(info) -> tuple:
    """(no, title, kind, state text, fraction, failed fraction) of one chapter, strings made once."""
    st = info.state
    title = info.title if info.title is not None else ""
    if info.is_toc:
        title = title or "Contents"
    return (str(cl.display_no(info.index)), title, st.kind, state_text(st),
            st.fraction if st.kind in ("partly", "translated", "failed") else 0.0, st.failed_fraction)


def titles_numbered(infos) -> bool:
    """True when >= 95 % of the chapters carry a title number and the numbers grow along the list (4.7: `No.` hidden)."""
    nums = [cl.title_number(i.title or "") for i in infos if not i.is_toc]
    if not nums:
        return False
    hit = [n for n in nums if n is not None]
    if len(hit) < 0.95 * len(nums):
        return False
    return all(b > a for a, b in zip(hit, hit[1:]))


def numbers_of(infos) -> list:
    return [cl.title_number(i.title or "") for i in infos]


def first_open(infos) -> int:
    """The first chapter that is not fully translated (a book opens scrolled to it); 0 when none known."""
    for i in infos:
        if i.is_toc:
            continue
        if i.blocks is None:
            return i.index
        if i.state.kind != "translated":
            return i.index
    return 0


# ---------------------------------------------------------------- the selection capsule
def _shown_number(info) -> int:
    n = cl.title_number(info.title or "")
    return n if n is not None else cl.display_no(info.index)


def shown_numbers(infos) -> list:
    """The chapter number the user reads for each list position (Terms shows First and the selection by them)."""
    return [_shown_number(i) for i in infos]


def range_text(infos, indices) -> str:
    """`2697-2750`, or `5, 9-12`: runs of consecutive list positions by the numbers the user reads."""
    out = []
    run: list = []
    for i in sorted(indices):
        if run and i == run[-1] + 1:
            run.append(i)
        else:
            if run:
                out.append(run)
            run = [i]
    if run:
        out.append(run)
    parts = []
    for r in out:
        a, b = _shown_number(infos[r[0]]), _shown_number(infos[r[-1]])
        parts.append(str(a) if len(r) == 1 else "%d-%d" % (a, b))
    return ", ".join(parts)


def count_text(n: int) -> str:
    return "%d %s" % (n, "chapter" if n == 1 else "chapters")


def next_step(infos, indices, blocking: int = 0) -> tuple:
    """(kind, text): what the selection leads to: `Review 12 terms ›` (red) when terms block it, `Export ›` when every
    selected chapter is translated, else `Translate ›`."""
    if indices and blocking:
        return "review", "Review %d %s ›" % (blocking, "term" if blocking == 1 else "terms")
    if indices and all(infos[i].state.kind == "translated" for i in indices):
        return "export", "Export ›"
    return "translate", "Translate ›"
