"""What the window looks at now: the series, the book and the chapter selection. One owner, plain observers.

Screens never copy the selection; they observe the `Session` and read it (the Tk window pushed copies around).
`Session` lives on the GUI thread.
"""

from __future__ import annotations

import logging

from ..selection import Selection, make

log = logging.getLogger("novelgui.session")


class Observers:
    """A list of callbacks; one that raises is logged and the others still run."""

    def __init__(self):
        self._fns: list = []

    def add(self, fn):
        self._fns.append(fn)
        return lambda: self.remove(fn)

    def remove(self, fn) -> None:
        try:
            self._fns.remove(fn)
        except ValueError:
            pass

    def notify(self, *args) -> None:
        for fn in list(self._fns):
            try:
                fn(*args)
            except Exception:
                log.exception("observer failed")

    def __len__(self) -> int:
        return len(self._fns)


class Session:
    def __init__(self):
        self.series = None              # facade.books.SeriesInfo or None
        self.book = ""
        self.selection = Selection()
        self.changed = Observers()      # fn(what) with what in {"series", "book", "selection"}

    @property
    def series_path(self) -> str:
        return self.series.path if self.series is not None else ""

    def set_series(self, info) -> None:
        same = (info is None and self.series is None) or (
            info is not None and self.series is not None and info.path == self.series.path)
        self.series = info
        if same:
            self.changed.notify("series")
            return
        self.book = ""
        self.selection = Selection()
        self.changed.notify("series")

    def set_book(self, book: str) -> None:
        if book == self.book:
            return
        self.book = book
        self.selection = Selection(book)
        self.changed.notify("book")

    def select(self, indices) -> None:
        sel = make(self.book, indices)
        if sel == self.selection:
            return
        self.selection = sel
        self.changed.notify("selection")
