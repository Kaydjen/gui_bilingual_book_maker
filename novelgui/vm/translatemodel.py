"""The three list models of the Translate screen (review_window_arch D6): plain tuples, at most 8 roles per row, display
strings made once, ids not objects.

- `ChapterRows`: the chapters of the selection with their state word and bar. A new selection is ONE reset; a progress
  tick sends `dataChanged` for the changed rows only (merged into ranges); the current row moves with `set_current`.
- `ProblemRows`: failed blocks and check findings; the selected row (the editor opens under the list) is a computed role.
- `QueueRows`: the Queue tab, the running job first.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

from .chaptermodel import ranges

CHAPTER_ROLES = ("no", "title", "fraction", "failed", "word", "tone", "current", "flags")
PROBLEM_ROLES = ("chapter", "title", "block", "source", "reason", "kind", "detail")
QUEUE_ROLES = ("series", "start", "name", "detail", "percent", "flags", "why", "tip")


class TupleModel(QAbstractListModel):
    NAMES: tuple = ()
    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []
        self.resets = 0
        self.batches = 0            # dataChanged signals sent since the last reset

    @classmethod
    def role_map(cls) -> dict:
        return {Qt.ItemDataRole.UserRole + 1 + i: n.encode() for i, n in enumerate(cls.NAMES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self):
        return self.role_map()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r, k = index.row(), role - Qt.ItemDataRole.UserRole - 1
        if not (0 <= r < len(self._rows)) or not 0 <= k < len(self.NAMES):
            return None
        return self._rows[r][k]

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.resets += 1
        self.batches = 0
        self.endResetModel()
        self.countChanged.emit()

    def replace(self, updates: dict) -> int:
        """`{row: tuple}`: store the changed rows; one `dataChanged` per run of neighbours. Returns the signals sent."""
        hit = []
        for i, row in updates.items():
            if 0 <= i < len(self._rows) and self._rows[i] != row:
                self._rows[i] = row
                hit.append(i)
        sent = 0
        for a, b in ranges(hit):
            self.dataChanged.emit(self.index(a), self.index(b))
            sent += 1
        self.batches += sent
        return sent

    def row(self, i: int) -> tuple:
        return self._rows[i] if 0 <= i < len(self._rows) else ()

    @property
    def rows(self) -> list:
        return self._rows

    def __len__(self) -> int:
        return len(self._rows)


class ChapterRows(TupleModel):
    NAMES = CHAPTER_ROLES


class QueueRows(TupleModel):
    NAMES = QUEUE_ROLES


class ProblemRows(TupleModel):
    NAMES = PROBLEM_ROLES
    SELECTED = Qt.ItemDataRole.UserRole + 1 + len(PROBLEM_ROLES)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cursor = -1

    def roleNames(self):
        return {**self.role_map(), self.SELECTED: b"selected"}

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == self.SELECTED:
            return index.row() == self._cursor
        return super().data(index, role)

    @property
    def cursor(self) -> int:
        return self._cursor

    def set_rows(self, rows) -> None:
        self._cursor = -1
        super().set_rows(rows)

    def set_cursor(self, i: int) -> None:
        i = i if 0 <= i < len(self._rows) else -1
        if i == self._cursor:
            return
        old, self._cursor = self._cursor, i
        for k in (old, i):
            if k >= 0:
                self.dataChanged.emit(self.index(k), self.index(k), [self.SELECTED])
