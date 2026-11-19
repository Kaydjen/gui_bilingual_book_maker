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
    def __init__(self, submit, timer, crunch=None, save_ms: int = SAVE_MS, snapshot_dir=None, history=None):
        self.submit = submit
        self.history = history              # a TermsHistory: a snapshot before every bulk change (14.11)
        self.suggestions: list = []         # mined names without a rendering (rows of status `suggest`), not in the base
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
        self.suggestions = []
        self._inflight = {}

        def load(ctx, path=str(series_path), tag=tag):
            self._store = fterms.TermStore(path, tag)
            if self.history is not None:
                self._store.history = lambda label, h=self.history, st=self._store: h.snapshot(st.snapshot, label)
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

    def confirm(self, keys, label: str = "") -> None:
        keys = tuple(keys)
        self._optimistic(keys, status="confirmed", questions=(), choices=())
        self._command(fterms.TermCommand("confirm", keys, label=label))

    def unconfirm(self, keys, label: str = "") -> None:
        self._optimistic(keys, status="new")
        self._command(fterms.TermCommand("unconfirm", tuple(keys), label=label))

    def delete(self, keys, label: str = "", op: str = "delete") -> None:
        """Delete (Undo through `undo_delete`) or, with op="dismiss", Not a term: gone and never suggested again."""
        keys = tuple(keys)
        names = [x.source for x in self.suggestions if x.key in keys]       # a mined name: only "never suggest it again"
        real = tuple(k for k in keys if not k.startswith("?"))
        for k in real:
            self.rows.pop(k, None)
        self.suggestions = [x for x in self.suggestions if x.key not in keys]
        self.changed.notify("removed", keys)
        if names:
            self._command(fterms.TermCommand("dismiss_names", (), value="\n".join(names), label=label))
        if real:
            self._command(fterms.TermCommand(op, real, label=label))

    def merge(self, keys, label: str = "") -> None:
        """The first key keeps; the others become its other spellings."""
        keys = tuple(keys)
        for k in keys[1:]:
            self.rows.pop(k, None)
        self.changed.notify("removed", keys[1:])
        self._command(fterms.TermCommand("merge", keys, label=label))

    def undo_delete(self) -> None:
        self._command(fterms.TermCommand("undo_delete", ()))

    def add_name(self, text: str, tr: str) -> None:
        """A mined name the user gave a rendering: a confirmed entry (the suggestion goes)."""
        key = next((x.key for x in self.suggestions if x.source == text), "")
        self.suggestions = [x for x in self.suggestions if x.source != text]
        if key:
            self.changed.notify("removed", (key,))
        self._command(fterms.TermCommand("add", (), field=text, value=tr))

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
    def scan_book(self, book: str, chapters=None, on_done=None, on_error=None, on_progress=None) -> None:
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
                self.crunch.submit("term_scan", args, on_result=apply, on_error=on_error, on_item=on_progress,
                                   group="term-scan")
            else:
                self.submit(lambda ctx: fterms.term_scan_task(ctx, **args), on_result=apply, on_error=on_error,
                            on_item=on_progress, lane="read", group="term-scan")
        self.submit(make_snapshot, on_result=scan, on_error=on_error, lane="data")


    # ------------------------------------------------------------- questions of the screen
    def ask_store(self, fn, on_result, group=None) -> None:
        """Run `fn(store)` on the data lane (the only thread that touches the base); the answer comes back plain."""
        def run(ctx):
            return fn(self._store) if self._store is not None else None
        self.submit(run, on_result=on_result, on_error=lambda exc: on_result(None), lane="data", group=group)

    def blocking_keys(self, chapters, on_result) -> None:
        chapters = tuple(chapters)
        self.ask_store(lambda st: st.blocking_keys(chapters), on_result, group="terms-blocking")

    def places(self, key: str, book: str, on_batch, on_done=None, on_error=None, names=None) -> None:
        """Paragraphs of the book that mention a term, in batches (`on_batch(list)`), off the UI thread: in the
        helper process, or on the read lane without one. The chapters the scan noted are read first and only."""
        series = self.series_path

        def start(info):
            if not info:
                return
            names, chapters = info
            args = {"series_path": series, "book_name": book, "names": list(names),
                    "chapters": list(chapters) or None}
            if self.crunch is not None:
                self.crunch.submit("term_places", args, on_result=on_done, on_error=on_error, on_item=on_batch,
                                   group="term-places")
            else:
                self.submit(lambda ctx: fterms.term_places_task(ctx, **args), on_result=on_done, on_error=on_error,
                            on_item=on_batch, lane="read", group="term-places")
        if names:                       # a mined name: not in the base, the whole book is read
            start((tuple(names), ()))
            return
        self.ask_store(lambda st: (st.names_of(key), st.chapters_of(key)), start, group="terms-places-of")

    def load_names(self, book: str, on_done=None, on_error=None) -> None:
        """The names the offline scan found that are not in the base, as suggestion rows."""
        from .termrows import Suggestion
        series = self.series_path

        def done(found):
            have = {r.key for r in self.rows.values()}
            self.suggestions = [x for x in (Suggestion(t, n, f) for t, n, f in found or ()) if x.key not in have]
            self.changed.notify("reset", ())
            if on_done is not None:
                on_done(len(self.suggestions))
        args = {"series_path": series, "book_name": book}
        if self.crunch is not None:
            self.crunch.submit("term_names", args, on_result=done, on_error=on_error, group="term-names")
        else:
            self.submit(lambda ctx: fterms.term_names_task(ctx, **args), on_result=done, on_error=on_error,
                        lane="read", group="term-names")

    # ------------------------------------------------------------- files
    def read_glossaries(self, files, on_done, on_error=None) -> None:
        self.submit(lambda ctx: fterms.read_glossary_task(ctx, list(files)), on_result=on_done, on_error=on_error,
                    lane="data")

    def import_files(self, files, confirmed: dict, on_progress=None, on_done=None, on_error=None) -> None:
        """Add the terms of the glossary files; `confirmed` {file name: goes to Confirmed}. `on_done(stats)` after the
        rows are read back."""
        files = list(files)

        def run(ctx):
            if self._store is None:
                raise RuntimeError("The terms are not open.")
            stats = self._store.import_glossaries(files, confirmed, "Import %d %s" % (
                len(files), "glossary" if len(files) == 1 else "glossaries"),
                progress=lambda n, t, name: ctx.emit((n, t, name)))
            return stats, self._store.rows(ctx.breathe)

        def done(res):
            stats, rows = res
            self.rows = {r.key: r for r in rows}
            self.changed.notify("reset", tuple(self.rows))
            self._save.poke()
            if on_done is not None:
                on_done(stats)
        self.submit(run, on_result=done, on_error=on_error, on_item=on_progress, lane="data")

    def export_file(self, path, on_done=None, on_error=None) -> None:
        def run(ctx):
            return self._store.export_to(path) if self._store is not None else 0
        self.submit(run, on_result=on_done, on_error=on_error, lane="data")


def _remove(path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
