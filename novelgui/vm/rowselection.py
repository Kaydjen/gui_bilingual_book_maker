"""Row selection of a list: ids, cursor, anchor. Pure Python, no Qt.

Ported from the rules of vtable.py (spec 10.7): click selects one row, Shift+click selects the range from the
anchor, Ctrl+click toggles one row, a drag selects the range from the anchor to the row under the pointer,
arrows move the cursor (Shift extends from the anchor), Home / End jump, Ctrl+A selects every selectable row,
Space toggles the cursor row. Rows are known by id; their order is the order given to `set_rows`, so a sort or a
filter keeps the selection of the rows that survive.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional


class RowSelection:
    def __init__(self, selectable: Optional[Callable[[object], bool]] = None):
        self._selectable = selectable
        self.rows: list = []            # ids in display order
        self._pos: dict = {}            # id -> position
        self.ids: set = set()
        self.cursor = None              # id or None
        self.anchor = None

    # ---- the rows
    def set_rows(self, ids: Iterable) -> None:
        """New row order; selection, cursor and anchor survive for the ids that are still there."""
        self.rows = list(ids)
        self._pos = {r: i for i, r in enumerate(self.rows)}
        self.ids = {r for r in self.ids if r in self._pos}
        if self.cursor not in self._pos:
            self.cursor = None
        if self.anchor not in self._pos:
            self.anchor = None

    def selectable(self, id_) -> bool:
        return self._selectable is None or bool(self._selectable(id_))

    def positions(self) -> set:
        """Positions (display order) of the selected ids."""
        return {self._pos[r] for r in self.ids if r in self._pos}

    def selected(self) -> list:
        """Selected ids in display order."""
        return [r for r in self.rows if r in self.ids]

    def is_selected(self, id_) -> bool:
        return id_ in self.ids

    @property
    def cursor_index(self) -> Optional[int]:
        return self._pos.get(self.cursor) if self.cursor is not None else None

    def _range(self, a, b) -> set:
        lo, hi = sorted((self._pos[a], self._pos[b]))
        return {r for r in self.rows[lo:hi + 1] if self.selectable(r)}

    # ---- pointer
    def click(self, index: int, ctrl: bool = False, shift: bool = False) -> bool:
        """A press on row `index`. Returns True when something changed."""
        if not 0 <= index < len(self.rows):
            return False
        r = self.rows[index]
        ok = self.selectable(r)
        if not ok and not (ctrl or shift):
            return False
        before = (set(self.ids), self.cursor, self.anchor)
        if shift and self.anchor is not None:
            self.ids = self._range(self.anchor, r)
        elif ctrl:
            if ok:
                self.ids ^= {r}
            self.anchor = r
        else:
            self.ids = {r}
            self.anchor = r
        self.cursor = r
        return before != (self.ids, self.cursor, self.anchor)

    def drag(self, index: int) -> bool:
        """The pointer moved over row `index` with the button down."""
        if not 0 <= index < len(self.rows) or self.anchor is None:
            return False
        before = (set(self.ids), self.cursor)
        self.ids = self._range(self.anchor, self.rows[index])
        self.cursor = self.rows[index]
        return before != (self.ids, self.cursor)

    def context(self, index: int) -> bool:
        """A right press: a row outside the selection becomes the selection, one inside only moves the cursor."""
        if not 0 <= index < len(self.rows):
            return False
        r = self.rows[index]
        if r not in self.ids:
            self.ids, self.cursor, self.anchor = {r}, r, r
        else:
            self.cursor = r
        return True

    # ---- keyboard
    def goto(self, index: int, extend: bool = False, select: bool = True) -> None:
        """Move the cursor to row `index`. `select=False` (Terms: the selection is the ticks) moves the cursor and the
        anchor only."""
        if not self.rows:
            return
        index = max(0, min(len(self.rows) - 1, index))
        r = self.rows[index]
        if not select:
            self.cursor = self.anchor = r
            return
        if extend and self.anchor is not None:
            self.ids = self._range(self.anchor, r)
        else:
            self.ids = {r} if self.selectable(r) else set()
            self.anchor = r
        self.cursor = r

    def move(self, delta: int, extend: bool = False, select: bool = True) -> None:
        """Arrows and Page keys: the cursor moves by `delta` rows (from row 0 when there is no cursor)."""
        cur = self.cursor_index
        self.goto((0 if cur is None else cur) + delta, extend, select)

    def home(self, extend: bool = False, select: bool = True) -> None:
        self.goto(0, extend, select)

    def end(self, extend: bool = False, select: bool = True) -> None:
        self.goto(len(self.rows) - 1, extend, select)

    def point(self, index: int) -> bool:
        """A click on a row's body in a table whose selection is the ticks: the cursor goes there, the ticks stay."""
        if not 0 <= index < len(self.rows):
            return False
        before = self.cursor
        self.cursor = self.anchor = self.rows[index]
        return before != self.cursor

    def select_all(self) -> None:
        self.ids = {r for r in self.rows if self.selectable(r)}
        self.anchor = self.rows[0] if self.rows else None
        if self.cursor is None and self.rows:
            self.cursor = self.rows[0]

    def toggle_cursor(self) -> bool:
        """Space: the cursor row joins or leaves the selection."""
        c = self.cursor
        if c is None or not self.selectable(c):
            return False
        self.ids ^= {c}
        self.anchor = c
        return True

    def clear(self) -> None:
        self.ids, self.cursor, self.anchor = set(), None, None

    # ---- programmatic
    def set_selection(self, ids: Iterable) -> None:
        """Select exactly these ids (unknown or unselectable ones are dropped); the first becomes cursor and anchor."""
        keep = sorted((i for i in ids if i in self._pos and self.selectable(i)), key=self._pos.get)
        self.ids = set(keep)
        self.cursor = self.anchor = keep[0] if keep else None
