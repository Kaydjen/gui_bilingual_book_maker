"""The term table as a Qt list model (review_window_arch D6): plain tuples from `ctl.termrows.model_row`, seven roles of
display strings made once on the data lane, ticks and the cursor as two computed roles. A new arrangement is ONE reset
(a 20,000-row reset is a pointer swap); an edit of a shown row sends `dataChanged` for that row; a tick or a cursor move
sends it for the rows that changed. Ids are positions here; the view-model keeps the keys.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

from .chaptermodel import ranges

ROLE_NAMES = ("src", "ren", "typ", "gen", "fc", "about", "flags")


class TermModel(QAbstractListModel):
    SELECTED, CURRENT = (Qt.ItemDataRole.UserRole + 1 + len(ROLE_NAMES) + k for k in range(2))
    ROLES = {**{Qt.ItemDataRole.UserRole + 1 + i: n.encode() for i, n in enumerate(ROLE_NAMES)},
             SELECTED: b"selected", CURRENT: b"current"}
    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []
        self._ticked: set = set()
        self._cursor = -1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self):
        return self.ROLES

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = index.row()
        if not 0 <= r < len(self._rows):
            return None
        if role == self.SELECTED:
            return r in self._ticked
        if role == self.CURRENT:
            return r == self._cursor
        k = role - Qt.ItemDataRole.UserRole - 1
        return self._rows[r][k] if 0 <= k < len(ROLE_NAMES) else None

    # ---------------------------------------------------------- filling
    def set_rows(self, rows, in_place: bool = False) -> None:
        """A new arrangement: ticks and cursor start empty (the view-model sets them right after). `in_place`: the same rows
        in the same places (the caller knows), so only the cells that differ are announced and no delegate is rebuilt: a cell
        being edited keeps its focus and its text."""
        if in_place and len(rows) == len(self._rows):
            old, self._rows = self._rows, rows
            for a, b in ranges(i for i, (x, y) in enumerate(zip(rows, old)) if x != y):
                self.dataChanged.emit(self.index(a), self.index(b))
            return
        self.beginResetModel()
        self._rows = rows
        self._ticked = set()
        self._cursor = -1
        self.endResetModel()
        self.countChanged.emit()

    def replace(self, i: int, row: tuple) -> None:
        if 0 <= i < len(self._rows) and self._rows[i] != row:
            self._rows[i] = row
            self.dataChanged.emit(self.index(i), self.index(i))

    def set_selection(self, ticked, cursor: int) -> None:
        changed = self._ticked ^ set(ticked)
        if cursor != self._cursor:
            changed |= {i for i in (self._cursor, cursor) if i >= 0}
        self._ticked = set(ticked)
        self._cursor = cursor
        n = len(self._rows)
        for a, b in ranges(i for i in changed if 0 <= i < n):
            self.dataChanged.emit(self.index(a), self.index(b), [self.SELECTED, self.CURRENT])

    def row(self, i: int) -> tuple:
        return self._rows[i] if 0 <= i < len(self._rows) else ()

    @property
    def rows(self) -> list:
        return self._rows
