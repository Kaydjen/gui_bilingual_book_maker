"""The library and the open book as the window sees them (review_window_arch D2, D6).

The series list is read on the data lane; the chapter list of a book is filled by the chapter scan in the helper
process (or, without one, on the read lane), skeleton first, then batches merged by position. Observers get the
changed row ranges, so a list model sends one `dataChanged` per range. Opening another book supersedes the scan
of the previous one: its late rows never reach the new list (generation of the group "chapters").
"""

from __future__ import annotations

from ..facade import books as fbooks
from ..facade import run as frun
from ..lanes import Want
from .session import Observers


def _ranges(indices) -> list:
    out: list = []
    for i in sorted(indices):
        if out and out[-1][1] == i - 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [tuple(r) for r in out]


def library_task(ctx, library) -> tuple:
    """(series infos, [(series path, JobView)]) of a library; export leftovers are swept first (rule e)."""
    fbooks.sweep_parts(library)
    infos = tuple(fbooks.list_series_task(ctx, library))
    views = []
    for s in infos:
        if s.broken:
            continue
        try:
            views.append((s.path, frun.job_view(s.path)))
        except Exception:
            continue
        ctx.breathe()
    return infos, tuple(views)


class BooksSession:
    def __init__(self, submit, crunch=None):
        self.submit = submit
        self.crunch = crunch
        self.library = ""
        self.series_list: tuple = ()
        self.series_path = ""
        self.book = ""
        self.infos: list = []
        self.want = Want()
        self.scanning = False
        self.changed = Observers()      # fn(kind, payload): "series" | "skeleton" | "rows" (ranges) | "scanned"
        self.failed = Observers()       # fn(kind, error, key): the key of the request that failed (library path | (series, book))
        self._token = None

    def load_library(self, library, on_done=None) -> None:
        self.library = str(library)

        def done(res):
            infos, views = res
            self.series_list = infos
            self.changed.notify("series", infos)
            if on_done is not None:
                on_done(views)
        self.submit(lambda ctx, lib=self.library: library_task(ctx, lib), on_result=done,
                    on_error=lambda exc, lib=self.library: self.failed.notify("library", exc, lib), lane="data", group="library")

    def open_book(self, series_path, book: str) -> None:
        self.series_path, self.book = str(series_path), book
        self.infos = []
        self.scanning = True
        on_item, on_result = self._on_item, self._on_done
        key = (self.series_path, book)
        on_error = lambda exc: self._on_error(exc, key)         # noqa: E731
        if self.crunch is not None:
            a, b = self.want.get()
            self._token = self.crunch.submit("scan_book", {"series_path": self.series_path, "book": book,
                                                           "first": a, "last": b},
                                             on_result=on_result, on_error=on_error, on_item=on_item,
                                             group="chapters")
        else:
            want = self.want
            self._token = self.submit(
                lambda ctx, s=self.series_path, b=book: fbooks.scan_chapters_task(ctx, s, b, want),
                on_result=on_result, on_error=on_error, on_item=on_item, lane="read", group="chapters")

    def close_scan(self) -> None:
        """Stop the chapter scan of the open book (cancel kills the helper: its zip handles go with it) before a move."""
        if self._token is not None:
            self._token.cancel()
            self._token = None
        self.scanning = False
        if self.crunch is not None:
            self.crunch.release()

    def set_visible(self, first: int, last: int) -> None:
        """The rows the list shows now: the scan serves them first."""
        self.want.set(first, last)
        if self.crunch is not None and self._token is not None and self.scanning:
            self.crunch.want(self._token, first, last)

    def _on_item(self, item) -> None:
        kind, rows = item[0], item[1]
        if kind == "skeleton":
            self.infos = list(rows)
            self.changed.notify("skeleton", len(self.infos))
        elif kind == "rows":
            n = len(self.infos)
            hit = []
            for info in rows:
                if 0 <= info.index < n:
                    self.infos[info.index] = info
                    hit.append(info.index)
            if hit:
                self.changed.notify("rows", _ranges(hit))

    def _on_done(self, res) -> None:
        self.scanning = False
        self.changed.notify("scanned", res)

    def _on_error(self, exc, key=None) -> None:
        if key is None or key == (self.series_path, self.book):
            self.scanning = False
        self.failed.notify("scan", exc, key)

    def view(self) -> tuple:
        """(series path, book, chapter infos): what RunControl reads of the screen."""
        return self.series_path, self.book, self.infos
