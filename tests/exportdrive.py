"""Drives the Export screen's states in a scene (tests/shellfactory.py registers `Drive.extras()` as the scene's `py` actions): the
choice by row labels, an opened piece, a held `Exporting…`, an export that fails. Plain JSON arguments only. A run is fed by
tests/translatedrive.py (`tr_begin`, `tr_progress`), here `ex_progress_to` completes a span of its chapters."""

from __future__ import annotations

import errno

from tests import translatedemo as demo
from tests import translatedrive


class Drive:
    def __init__(self, parts, lib, tr: translatedrive.Drive):
        self.parts, self.lib, self.tr = parts, lib, tr
        self.vm = parts.export_vm

    def settle(self) -> bool:
        translatedrive.settle(self.parts)
        return True

    def index(self, label: str) -> int:
        for i, r in enumerate(self.vm.rows.rows):
            if r[1] == label and r[0] != "chapter":
                return i
        raise KeyError("no row %r in %s" % (label, [r[1] for r in self.vm.rows.rows]))

    def press(self, label: str, ctrl: bool = False, shift: bool = False) -> bool:
        self.vm.rowPressed(self.index(label), ctrl, shift)
        return True

    def tick(self, *spans) -> bool:
        """The choice becomes these title-number ranges (pairs first, last, ...), as if the user had ticked them."""
        pos = set()
        for a, b in zip(spans[::2], spans[1::2]):
            pos.update(range(demo.position(a), demo.position(b) + 1))
        self.vm._ticks = pos & set(self.vm._oks)
        self.vm._touched = True
        self.vm._rebuild()
        return True

    def open(self, label: str) -> bool:
        self.vm.toggleOpen(self.index(label))
        return True

    def hold_busy(self, mode: str) -> bool:
        """The look of a running export (the build itself ends too fast to be shot)."""
        self.vm._busy = mode
        self.vm._compute_bar()
        return True

    def fail_next(self) -> bool:
        """The next export fails like a full disk (the build runs in this process, so the failure can be planted)."""
        from novelgui.facade import books as fbooks

        def full(ctx, *a, **kw):
            raise OSError(errno.ENOSPC, "No space left on device")

        fbooks.export_piece_task = full
        self.vm.crunch = None
        return True

    def nothing_next(self) -> bool:
        """The next export finds nothing fully translated any more (a chapter changed after the press)."""
        from novelgui.facade import books as fbooks

        def none(ctx, series_path, book, positions, mode, name):
            return fbooks.ExportOutcome(mode=mode, nothing=True, detail="no selected chapter is fully translated")

        fbooks.export_piece_task = none
        self.vm.crunch = None
        return True

    def progress_to(self, first: int, last: int) -> bool:
        for n in range(first, last + 1):
            self.tr.feed("progress", {"index": demo.position(n), "done": 3, "total": 3, "failed": 0})
        self.tr.rc._flush_progress()
        translatedrive.settle(self.parts)
        return True

    def state(self) -> dict:
        """What the view-models say now (a scene action cannot read a property)."""
        vm, app = self.vm, self.parts.app
        nums = sorted(p + demo.FIRST_NUMBER - 1 for p in vm._ticks)
        return {"screen": app.screen, "ticked": nums, "head": vm.headState, "busy": vm.busy, "panel": vm.panel,
                "selection": list(self.parts.books_vm.terms_context()[2]), "tab": self.parts.translate_vm.tab,
                "problem_cursor": self.parts.translate_vm.problem_rows.cursor, "cursor": vm.cursor,
                "summary": [vm.summaryCount, vm.summaryRanges], "exportState": app.exportState,
                "appPanel": app.panel}

    def history(self) -> dict:
        from novelgui.facade import exports as fex
        return {str(k): list(v) for k, v in fex.read_history(self.lib / "Knights", "Book 1").items()}

    def rows(self) -> list:
        return [list(r) for r in self.vm.rows.rows]

    def out_files(self) -> list:
        out = self.lib / "Knights" / "out"
        return sorted(p.name for p in out.glob("*")) if out.exists() else []

    def extras(self) -> dict:
        names = ("settle", "press", "tick", "open", "hold_busy", "fail_next", "nothing_next", "progress_to", "history", "rows", "out_files", "state")
        return {"ex_" + n: getattr(self, n) for n in names}
