"""The left list of Books: series rows with the books of the selected series under it (ctl/bookrows.series_rows).

Rows are tuples (kind, key, text, tail, count, mode, editing); a new list with the same rows in the same places only
sends `dataChanged` (the scroll position stays), another shape resets the model.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

ROLE_NAMES = ("kind", "key", "text", "tail", "count", "mode", "editing")


class SeriesModel(QAbstractListModel):
    countChanged = Signal()
    ROLES = {Qt.ItemDataRole.UserRole + 1 + i: n.encode() for i, n in enumerate(ROLE_NAMES)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self):
        return self.ROLES

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = index.row()
        k = role - Qt.ItemDataRole.UserRole - 1
        if 0 <= r < len(self._rows) and 0 <= k < len(ROLE_NAMES):
            return self._rows[r][k]
        return None

    def set_rows(self, rows) -> None:
        rows = [tuple(r) for r in rows]
        if len(rows) == len(self._rows) and all(a[:2] == b[:2] for a, b in zip(rows, self._rows)):
            old, self._rows = self._rows, rows
            for i, (a, b) in enumerate(zip(rows, old)):
                if a != b:
                    self.dataChanged.emit(self.index(i), self.index(i))
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    def row(self, i: int) -> tuple:
        return self._rows[i] if 0 <= i < len(self._rows) else ()

    @property
    def rows(self) -> list:
        return list(self._rows)
