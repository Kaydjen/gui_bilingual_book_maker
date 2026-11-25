"""The list model of the Export screen (review_window_arch D6): plain tuples, 8 roles, display strings made once.

`sync` takes the rows as they should be now and sends the smallest change: rows that kept their place and differ get one
`dataChanged` per run, a piece that was opened or closed is an insert or a remove. So a tick, a live job and an opened
piece never reset the list (the scroll position stays).
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex

from ..ctl.exportrows import ROLE_NAMES
from .chaptermodel import ranges
from .translatemodel import TupleModel


class ExportRows(TupleModel):
    NAMES = ROLE_NAMES

    def sync(self, rows) -> None:
        new = list(rows)
        old = self._rows
        if not old or not new:
            if old != new:
                self.set_rows(new)
            return
        n, m = len(old), len(new)
        p = 0
        while p < n and p < m and old[p] == new[p]:
            p += 1
        s = 0
        while s < n - p and s < m - p and old[n - 1 - s] == new[m - 1 - s]:
            s += 1
        if p == n == m:
            return
        hi_old, hi_new = n - s, m - s
        if hi_old - p == hi_new - p:
            self._replace_span(p, hi_new, new)
            return
        keep = min(hi_old, hi_new) - p              # rows that stay in place and may differ
        if keep > 0:
            self._replace_span(p, p + keep, new)
            p += keep
        if hi_old > p:
            self.beginRemoveRows(QModelIndex(), p, hi_old - 1)
            del old[p:hi_old]
            self.endRemoveRows()
        if hi_new > p:
            self.beginInsertRows(QModelIndex(), p, hi_new - 1)
            old[p:p] = new[p:hi_new]
            self.endInsertRows()
        self.countChanged.emit()

    def _replace_span(self, a: int, b: int, new) -> None:
        hit = [i for i in range(a, b) if self._rows[i] != new[i]]
        for i in hit:
            self._rows[i] = new[i]
        for x, y in ranges(hit):
            self.dataChanged.emit(self.index(x), self.index(y))
            self.batches += 1
