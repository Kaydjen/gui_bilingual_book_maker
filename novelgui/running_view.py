"""The running screen of Translate (window_spec 7.9): the chapters of the job as a list, a progress bar each,
the chapters being translated now in bright text.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import chapterlogic as cl
from .theme import ACCENT, BRIGHT, DIM, FAINT, S4, TEXT
from .vtable import Col, VTable

TRACK = "#1c1c1c"
BAR_PART = "#7d7d7d"
BAR_FULL = "#d0d0d0"


@dataclass
class Row:
    index: int
    title: str = ""
    done: int = 0
    total: int = 0
    failed: int = 0

    @property
    def state(self) -> str:
        if not self.total:
            return "waiting"
        if self.done >= self.total:
            return "done"
        return "now" if self.done > 0 or self.failed else "started"


def build_rows(chapters, chap: dict, titles) -> list:
    """Rows for every chapter of the job: figures from the job's progress, titles from `titles(index)`."""
    out = []
    for i in chapters:
        d, t, f = chap.get(i, (0, 0, 0))
        out.append(Row(i, titles(i), d, t, f))
    return out


def current_of(rows) -> list:
    """The chapters being translated now: started and not finished."""
    return [r.index for r in rows if r.state in ("now", "started")]


class RunningTable(VTable):
    def __init__(self, master, ui):
        super().__init__(master, ui, [Col("no", "No.", 7, "e", sortable=False),
                                      Col("title", "Title", None, sortable=False),
                                      Col("bar", "Progress", 26, sortable=False)], header=False, resizable=False)

    def selectable(self, row) -> bool:
        return False

    def draw_cells(self, c, row, cols, y, mid):
        st = row.state
        bright = st in ("now", "started")
        x, w = cols["no"]
        c.create_text(x + w - self.pad, y + mid, text=str(cl.display_no(row.index)), anchor="e", font=self.font,
                      fill=BRIGHT if bright else (DIM if st == "done" else FAINT))
        x, w = cols["title"]
        c.create_text(x + self.pad, y + mid, text=self.fit(row.title or "", w - 2 * self.pad), anchor="w",
                      font=self.font, fill=BRIGHT if bright else (TEXT if st == "done" else DIM))
        x, w = cols["bar"]
        bx0, bx1 = x + self.pad, x + w - self.pad
        bh = max(4, int(self.rh * 0.2))
        y0 = y + mid - bh / 2
        c.create_rectangle(bx0, y0, bx1, y0 + bh, fill=TRACK, outline="")
        if row.total:
            span = bx1 - bx0
            dw = int(span * min(1.0, row.done / row.total))
            if dw > 0:
                c.create_rectangle(bx0, y0, bx0 + dw, y0 + bh, fill=BAR_FULL if st == "done" else BAR_PART,
                                   outline="")
            if row.failed:
                fw = max(3, int(span * row.failed / row.total))
                c.create_rectangle(bx0 + dw, y0, min(bx1, bx0 + dw + fw), y0 + bh, fill=ACCENT, outline="")

    def tip_body(self, e):
        i = self.row_at(e.y)
        if i is None:
            return None
        r = self.rows[i]
        if not r.total:
            return "This chapter has not been started yet."
        return ("%d of %d blocks of this chapter are translated%s." % (
            r.done, r.total, ", %d failed" % r.failed if r.failed else ""),
            [("Comes from", "the running job"), ("You can edit", "no")])
