"""Write order between the window, its lanes, the helper process and the core (review_window_arch 5.3).

(a) A term edit: memory + optimistic screen at once, the save debounced (`TermsSession`).
(b) BEFORE a run start, an export, a check, Update file, Move or Remove: the terms are saved, the window state
    is written and every book handle of the lanes and of the helper is closed (`WriteOrder.before_book_work`);
    the runner reads terms.json and prompt.txt itself, and an open zip blocks a move on Windows.
(c) The window never writes a chapter log: blocks are resolved only through the core's `ChapterLog`
    (`facade.checks.resolve_problems_task`), and never in a chapter the running job of the series covers
    (`resolve_allowed`, window_spec 14.18).
(d) series.json only by read-modify-write on the data lane (`WriteOrder.update_series`); while such a write is
    on its way the series is in `own_writes`, so a focus rescan does not take its own `os.replace` for a loss.
(e) An export is written as `name.part` and renamed at the end (`facade.books.export_piece_task`); leftovers
    are swept when the library is opened (`facade.books.sweep_parts`, run by `ctl.books.library_task`).
"""

from __future__ import annotations

from collections import Counter

from ..facade import books as fbooks


def resolve_allowed(run_series: str, run_chapters, series: str, chapters) -> bool:
    """Rule (c): a failed block may be kept or typed only in chapters the running job of the series does not
    cover (the core is the one writer of those logs while it runs)."""
    if not run_series or run_series != series:
        return True
    return not (set(run_chapters) & set(chapters))


class WriteOrder:
    def __init__(self, submit, close_lane_books, flush_state=lambda: True, flush_terms=None, release_helper=None):
        """`submit` of the lanes; `close_lane_books(folder, on_done)` of the lanes; `flush_state()` writes the
        window state; `flush_terms(on_done)` saves the term base (TermsSession); `release_helper()` makes the
        helper process let go of its books (kills it when idle; it is started again on next use)."""
        self.submit = submit
        self.close_lane_books = close_lane_books
        self.flush_state = flush_state
        self.flush_terms = flush_terms
        self.release_helper = release_helper
        self.own_writes: Counter = Counter()

    # ------------------------------------------------------------- (b)
    def before_book_work(self, on_ready, folder=None) -> None:
        """Run `on_ready()` once the terms are saved, the state is written and no lane holds a book of `folder`
        (None = any) open. The data lane is serial, so the save lands before the books are let go."""
        self.flush_state()
        if self.release_helper is not None:
            self.release_helper()

        def books_closed(_n):
            on_ready()

        def terms_saved(_wrote=None):
            self.close_lane_books(folder, books_closed)

        if self.flush_terms is not None:
            self.flush_terms(terms_saved)
        else:
            terms_saved()

    # ------------------------------------------------------------- (d)
    def update_series(self, series_path, fn, on_done=None, on_error=None) -> None:
        """Read series.json, let `fn(settings)` change it, write it back - on the data lane, in order."""
        path = str(series_path)
        self.own_writes[path] += 1

        def finish(ok, payload):
            self.own_writes[path] -= 1
            if self.own_writes[path] <= 0:
                del self.own_writes[path]
            cb = on_done if ok else on_error
            if cb is not None:
                cb(payload)
        self.submit(lambda ctx: fbooks.update_series_settings(path, fn), lane="data",
                    on_result=lambda res: finish(True, res), on_error=lambda exc: finish(False, exc))

    def own_write_in_progress(self, series_path) -> bool:
        return self.own_writes.get(str(series_path), 0) > 0
