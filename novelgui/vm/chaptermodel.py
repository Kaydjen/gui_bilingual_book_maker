"""The chapter list of a book as a Qt list model (review_window_arch D6): at most 8 roles per row, display strings made once,
ids not objects. Rows arrive from the scan in batches; they are merged into dirty ranges and flushed as one `dataChanged`
per range, at most one flush every FLUSH_MS (the first change goes out at once), so a 3000-chapter scan stays a few dozen
signals. Selection and cursor changes of the user are sent at once.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, QTimer, Signal

from ..ctl import bookrows

FLUSH_MS = 400


def ranges(indices) -> list:
    out: list = []
    for i in sorted(indices):
        if out and out[-1][1] == i - 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [tuple(r) for r in out]


class ChapterModel(QAbstractListModel):
    NO, TITLE, KIND, STATE, FRACTION, FAILED, SELECTED, CURRENT = (Qt.ItemDataRole.UserRole + 1 + k for k in range(8))
    ROLES = {NO: b"no", TITLE: b"title", KIND: b"kind", STATE: b"stateText", FRACTION: b"fraction", FAILED: b"failed",
             SELECTED: b"selected", CURRENT: b"current"}
    countChanged = Signal()
    flushed = Signal(int)           # ranges sent by one flush (tests count the batches)

    def __init__(self, parent: QObject | None = None, flush_ms: int = FLUSH_MS):
        super().__init__(parent)
        self._rows: list = []
        self._selected: set = set()
        self._cursor = -1
        self._dirty: set = set()
        self._flush_ms = flush_ms
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush)
        self.batches = 0            # dataChanged signals sent since the last reset

    # ---------------------------------------------------------- model interface
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self):
        return self.ROLES

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = index.row()
        if not 0 <= r < len(self._rows):
            return None
        row = self._rows[r]
        if role == self.SELECTED:
            return r in self._selected
        if role == self.CURRENT:
            return r == self._cursor
        k = role - self.NO
        return row[k] if 0 <= k < 6 else None

    # ---------------------------------------------------------- filling
    def reset(self, infos) -> None:
        """A new list (the skeleton of a scan, or an empty list)."""
        self.beginResetModel()
        self._rows = [bookrows.chapter_row(i) for i in infos]
        self._selected = set()
        self._cursor = -1
        self._dirty.clear()
        self._timer.stop()
        self.batches = 0
        self.endResetModel()
        self.countChanged.emit()

    def update(self, spans, infos) -> None:
        """Rows of the scan: `spans` are (first, last) position runs whose infos changed."""
        n = len(self._rows)
        for a, b in spans:
            for i in range(a, min(b, n - 1) + 1):
                self._rows[i] = bookrows.chapter_row(infos[i])
                self._dirty.add(i)
        self._schedule()

    def _schedule(self) -> None:
        if not self._dirty or self._timer.isActive():
            return
        wait = self._flush_ms - (time.monotonic() - self._last) * 1000
        if wait <= 0:
            self.flush()
        else:
            self._timer.start(int(wait) + 1)

    def flush(self) -> None:
        self._timer.stop()
        if not self._dirty:
            return
        dirty, self._dirty = self._dirty, set()
        self._last = time.monotonic()
        spans = ranges(dirty)
        for a, b in spans:
            self.dataChanged.emit(self.index(a), self.index(b))
            self.batches += 1
        self.flushed.emit(len(spans))

    # ---------------------------------------------------------- selection (sent at once)
    def set_selection(self, selected, cursor: int) -> None:
        changed = self._selected ^ set(selected)
        if cursor != self._cursor:
            changed |= {i for i in (self._cursor, cursor) if i >= 0}
        self._selected = set(selected)
        self._cursor = cursor
        for a, b in ranges(i for i in changed if 0 <= i < len(self._rows)):
            self.dataChanged.emit(self.index(a), self.index(b), [self.SELECTED, self.CURRENT])

    @property
    def selected(self) -> set:
        return set(self._selected)

    def kind_of(self, i: int) -> str:
        return self._rows[i][2] if 0 <= i < len(self._rows) else ""
