"""The term base of the open series as the window sees it (review_window_arch D2, write order rule a).

The base itself (`facade.terms.TermStore`) is owned by the data lane: only tasks on that lane touch it. The GUI
holds immutable `TermRow`s keyed by the entry key. An edit is a command: the row changes in memory at once
(optimistic), the command runs on the data lane, its reply is the truth (reconcile; a refusal puts the true row
back and tells `rejected`). Saving is debounced (500 ms after the last edit) and coalesced; `flush_terms` saves
now (before a run, an export, a check, Update file, Move/Remove: rule b).

A scan of the book against the base works on a SNAPSHOT: the data lane writes the base to a snapshot file, the
helper process (or, without one, the read lane) reads the book against it and returns {key: [[chapter, hits]]},
the data lane applies it to the live base. The base is never read while it changes.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace

from ..facade import terms as fterms
from .session import Observers
from .throttle import Debounce

SAVE_MS = 500


class TermsSession:
    def __init__(self, submit, timer, crunch=None, save_ms: int = SAVE_MS, snapshot_dir=None):
        self.submit = submit
        self.crunch = crunch
        self.rows: dict = {}                # key -> TermRow (what the screen shows)
        self.series_path = ""
        self.tag = ""
        self.changed = Observers()          # fn(kind, keys): "reset" | "rows" | "removed"
        self.rejected = Observers()         # fn(keys, error)
        self.saved = Observers()            # fn(saves so far)
        self._store = None                  # data lane only
        self._inflight: dict = {}           # key -> commands not answered yet
        self._save = Debounce(timer, self._save_now, save_ms)
        self._snap_dir = snapshot_dir or tempfile.gettempdir()
        self.saves = 0

    # ------------------------------------------------------------- open
    def open(self, series_path, tag: str, on_done=None) -> None:
        self.series_path, self.tag = str(series_path), tag
        self.rows = {}
        self._inflight = {}

        def load(ctx, path=str(series_path), tag=tag):
            self._store = fterms.TermStore(path, tag)
            return self._store.rows(ctx.breathe)

        def done(rows):
            self.rows = {r.key: r for r in rows}
            self.changed.notify("reset", tuple(self.rows))
            if on_done is not None:
                on_done(len(rows))
        self.submit(load, on_result=done, lane="data", group="terms-open")

    def ordered(self) -> list:
        return sorted(self.rows.values(), key=lambda r: (r.key, r.source))

    # ------------------------------------------------------------- edits (rule a)
    def edit(self, key: str, field: str, value) -> None:
        row = self.rows.get(key)
        if row is not None and field in ("tr", "type", "gender", "note", "same_as"):
            q = tuple(f for f in row.questions if f != field)
            self.rows[key] = replace(row, **{field: str(value).strip(), "questions": q})
            self.changed.notify("rows", (key,))
        self._command(fterms.TermCommand("set_field", (key,), field, str(value)))

    def confirm(self, keys) -> None:
        self._optimistic(keys, status="confirmed")
        self._command(fterms.TermCommand("confirm", tuple(keys)))

    def unconfirm(self, keys) -> None:
        self._optimistic(keys, status="new")
        self._command(fterms.TermCommand("unconfirm", tuple(keys)))

    def delete(self, keys) -> None:
        gone = tuple(k for k in keys if self.rows.pop(k, None) is not None)
        if gone:
            self.changed.notify("removed", gone)
        self._command(fterms.TermCommand("delete", tuple(keys)))

    def _optimistic(self, keys, **fields) -> None:
        hit = []
        for k in keys:
            row = self.rows.get(k)
            if row is not None:
                self.rows[k] = replace(row, **fields)
                hit.append(k)
        if hit:
            self.changed.notify("rows", tuple(hit))

    def _command(self, cmd) -> None:
        for k in cmd.keys:
            self._inflight[k] = self._inflight.get(k, 0) + 1

        def run(ctx, cmd=cmd):
            if self._store is None:
                return fterms.CommandResult((), (), "The terms are not open.")
            return self._store.apply(cmd)
        self.submit(run, on_result=lambda res, cmd=cmd: self._answer(cmd, res),
                    on_error=lambda exc, cmd=cmd: self._answer(cmd, fterms.CommandResult((), (), str(exc))),
                    lane="data")
        self._save.poke()

    def _answer(self, cmd, res) -> None:
        for k in cmd.keys:
            n = self._inflight.get(k, 0) - 1
            if n > 0:
                self._inflight[k] = n
            else:
                self._inflight.pop(k, None)
        touched = []
        for row in res.rows:
            if res.error or row.key not in self._inflight:      # a later edit of the row is still on its way
                self.rows[row.key] = row
                touched.append(row.key)
        if touched:
            self.changed.notify("rows", tuple(touched))
        gone = tuple(k for k in res.removed if self.rows.pop(k, None) is not None)
        if gone:
            self.changed.notify("removed", gone)
        if res.error:
            self.rejected.notify(tuple(cmd.keys), res.error)

    # ------------------------------------------------------------- saving
    def _save_now(self, on_done=None) -> None:
        def save(ctx):
            return self._store.save() if self._store is not None else False

        def done(wrote):
            if wrote:
                self.saves += 1
                self.saved.notify(self.saves)
            if on_done is not None:
                on_done(bool(wrote))
        self.submit(save, on_result=done, on_error=lambda exc: on_done and on_done(False), lane="data")

    def flush_terms(self, on_done=None) -> None:
        """Save now if anything is unsaved; `on_done(wrote)` after the save (data lane order: every command
        submitted before is in it)."""
        self._save.cancel()
        self._save_now(on_done)

    @property
    def save_pending(self) -> bool:
        return self._save.pending

    # ------------------------------------------------------------- reading the book (snapshot)
    def scan_book(self, book: str, chapters=None, on_done=None, on_error=None) -> None:
        """Note in which chapters every term occurs (`seen` / `count`), from a snapshot of the base."""
        series, tag = self.series_path, self.tag
        snap = os.path.join(self._snap_dir, "terms-snapshot-%d-%d.json" % (os.getpid(), id(self)))

        def make_snapshot(ctx):
            return self._store.snapshot(snap) if self._store is not None else None

        def apply(found):
            def run(ctx, found=found):
                n = self._store.apply_scan(found) if self._store is not None else 0
                return n, (self._store.rows(ctx.breathe) if n else ())

            def applied(res):
                n, rows = res
                for r in rows:
                    if r.key not in self._inflight:
                        self.rows[r.key] = r
                if n:
                    self.changed.notify("reset", tuple(self.rows))
                    self._save.poke()
                _remove(snap)
                if on_done is not None:
                    on_done(n)
            self.submit(run, on_result=applied, on_error=on_error, lane="data")

        def scan(path):
            if path is None:
                return
            args = {"snapshot_path": path, "tag": tag, "series_path": series, "book_name": book,
                    "chapters": None if chapters is None else list(chapters)}
            if self.crunch is not None:
                self.crunch.submit("term_scan", args, on_result=apply, on_error=on_error, group="term-scan")
            else:
                self.submit(lambda ctx: fterms.term_scan_task(ctx, **args), on_result=apply, on_error=on_error,
                            lane="read", group="term-scan")
        self.submit(make_snapshot, on_result=scan, on_error=on_error, lane="data")


def _remove(path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
