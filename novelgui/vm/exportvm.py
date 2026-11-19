"""The view-model of the Export screen (window_spec 8.1-8.7, 9.9, 10.5, 14.12, 14.14).

Rules live in ctl/exportrows (pieces, marks, boxes, ranges, names, bar, result texts); this object is the glue: the open
volume and its chapter states come from Books (never its selection), the export history and the source language are read
on the data / read lanes, the build runs in the helper process (`.part`, then the rename; cancel kills it and the leftovers
are swept), and the running job's chapters join the pieces live through TranslateVM's `runTouched` (no polling).

The interface for the QML screen: .ai/notes/export_vm_api.md.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .. import langrules, platform, tips
from ..ctl import exportrows as er
from ..ctl.ordering import WriteOrder
from ..facade import books as fbooks
from ..facade import exports as fex
from .exportmodel import ExportRows

SYNC_MS = 40


def _tip(value):
    return [value[0], [list(f) for f in value[1]]] if isinstance(value, tuple) else value


class ExportVM(QObject):
    viewChanged = Signal()
    choiceChanged = Signal()
    barChanged = Signal()
    panelChanged = Signal()
    runChanged = Signal()

    def __init__(self, app, lanes, books, crunch=None, translate=None, parent=None):
        super().__init__(parent)
        self.app, self.lanes, self.books, self.crunch, self.translate = app, lanes, books, crunch, translate
        self.rows = ExportRows(self)
        self.order = WriteOrder(lanes.submit, lanes.close_lane_books, flush_state=app.flush,
                                release_helper=(crunch.release if crunch is not None else None))
        self.reveal = platform.reveal_file          # a test hook: nothing opens a file manager in a test
        self._path = self._book = ""
        self._info = None
        self._hist: dict = {}
        self._hist_ready = False
        self._ctx = {"source": langrules.FALLBACK.name, "source_tag": langrules.FALLBACK.tag}
        self._ticks: set = set()
        self._touched = False
        self._opened: set = set()
        self._anchor = None
        self._cursor = -1
        self._gs: list = []
        self._kl: list = []
        self._nums: list = []
        self._refs: list = []
        self._oks: list = []
        self._live: dict = {}
        self._loading = False
        self._busy = ""
        self._token = None
        self._last = None
        self._panel = ""
        self._panel_data: dict = {}
        self._pending_hist = None
        self._bar: list = []
        self._rev = 0
        self._head = "none"
        self._summary = ("", "")
        self._sync_t = QTimer(self)
        self._sync_t.setSingleShot(True)
        self._sync_t.setInterval(SYNC_MS)
        self._sync_t.timeout.connect(self._sync)
        for sig in (books.viewChanged, books.selectionChanged, books.seriesChanged, books.chaptersChanged):
            sig.connect(self._sync_later)
        books.session.changed.add(lambda kind, payload=None: self._sync_later())
        app.screenChanged.connect(self._screen_changed)
        app.panelChanged.connect(self._app_panel_changed)
        if translate is not None:
            translate.runTouched.connect(self._sync_later)
        self._sync()

    # ------------------------------------------------------------- what the screen shows
    @Property(QObject, constant=True)
    def list(self):
        return self.rows

    @Property(str, notify=viewChanged)
    def view(self):
        """none (no series or book) | loading | broken | ready."""
        v = self.books.view
        if not self._path or v in ("empty", "nobooks", "missing"):
            return "none"
        if v == "broken":
            return "broken"
        if v == "loading" or self._loading or not self._hist_ready:
            return "loading"
        return "ready"

    @Property(str, notify=choiceChanged)
    def headState(self):
        return self._head

    @Property(str, notify=choiceChanged)
    def summaryCount(self):
        return self._summary[0]

    @Property(str, notify=choiceChanged)
    def summaryRanges(self):
        return self._summary[1]

    @Property(int, notify=choiceChanged)
    def rev(self):
        """Bumped whenever the rows are built again: a tooltip that shows a moving fact asks again."""
        return self._rev

    @Property(int, notify=choiceChanged)
    def cursor(self):
        """The row the keyboard stands on (-1 = none)."""
        return self._cursor

    @Property(int, notify=choiceChanged)
    def ticked(self):
        return len(self._ticks)

    @Property("QVariantList", notify=barChanged)
    def bar(self):
        return self._bar

    @Property(str, notify=barChanged)
    def busy(self):
        return self._busy

    @Property(bool, notify=runChanged)
    def running(self):
        return bool(self._live)

    @Property("QVariantMap", constant=True)
    def tips(self):
        t = tips
        return {"head": t.EX_HEAD, "open": t.EX_OPEN, "from": t.EX_RANGE_FROM, "to": t.EX_RANGE_TO, "box": t.EX_ROW_BOX,
                "summary": t.EX_SUMMARY, "noBook": t.EX_NO_BOOK, "problemChapter": t.EX_PROBLEM_CHAPTER,
                "gap": _tip(t.EX_GAP), "busy": t.EX_BTN_BUSY}

    # ------------------------------------------------------------- following Books and the run
    def _sync_later(self, *a) -> None:
        self._sync_t.start(SYNC_MS)

    def _screen_changed(self) -> None:
        if self.app.screen == "export":
            if not self._touched:
                self._ticks = set()                 # the default is taken again: the pieces may have changed
            self._sync()

    def _sync(self) -> None:
        path, book, _idx, _rng, _numbers = self.books.terms_context()
        info = self.books.info() if path else None
        if info is not None and info.broken:
            info = None
        key = (path, book if info is not None else "")
        changed = key != (self._path, self._book)
        self._path, self._book, self._info = key[0], key[1], info
        if changed:
            self._reset_series()
            if self._path and self._book:
                self._load()
        self._update_glow()
        if self.app.screen == "export" or changed:
            self._rebuild()
        self.viewChanged.emit()

    def _reset_series(self) -> None:
        self.cancelExport()
        self._hist, self._hist_ready = {}, False
        self._ctx = {"source": langrules.FALLBACK.name, "source_tag": langrules.FALLBACK.tag}
        self._ticks, self._touched, self._opened, self._anchor = set(), False, set(), None
        self._cursor = -1
        self._close_panel(apply=False)

    def _key(self):
        return (self._path, self._book)

    def _load(self) -> None:
        path, book, key = self._path, self._book, self._key()

        def got_hist(h):
            if self._key() == key:
                self._hist, self._hist_ready = dict(h), True
                self._rebuild()
                self.viewChanged.emit()

        def got_ctx(c):
            if self._key() == key:
                self._ctx = dict(c)
                self._compute_bar()

        self.lanes.submit(lambda ctx: fex.history_task(ctx, path, book), on_result=got_hist,
                          on_error=lambda e: got_hist({}), lane="data", group="export-history")
        self.lanes.submit(lambda ctx: fex.context_task(ctx, path, book), on_result=got_ctx,
                          on_error=lambda e: None, lane="read", group="export-context")

    def _live_table(self) -> dict:
        tv = self.translate
        rc = tv.rc if tv is not None else None
        run = rc.run if rc is not None else None
        if run is None or run.kind != "job" or run.series != self._path or run.book != self._book:
            return {}
        return dict(run.chap)

    def _update_glow(self) -> None:
        """Export glows once and stays bright while every chosen chapter is translated (7.16)."""
        _p, _b, idx, _r, _n = self.books.terms_context()
        infos = self.books.session.infos
        self.app.set_export_ready(bool(idx) and er.all_translated(infos, idx, self._live_table()))

    # ------------------------------------------------------------- the rows
    def _rebuild(self) -> None:
        infos = list(self.books.session.infos) if self._path and self._book else []
        self._loading = any(i.blocks is None and i.is_toc is not True for i in infos)
        live = self._live_table()
        if bool(live) != bool(self._live):
            self._live = live
            self.runChanged.emit()
        self._live = live
        if not infos or self._loading:
            self._gs, self._kl, self._refs, self._oks = [], [], [], []
            self.rows.sync([])
            self._after_rows()
            return
        self._kl = er.kinds(infos, live)
        self._nums = er.numbers(infos)
        self._gs = er.groups(self._kl, self._hist)
        self._oks = er.all_oks(self._gs)
        self._ticks &= set(self._oks)
        if not self._touched:
            self._ticks = er.default_ticks(self._gs)
        firsts = {g.first for g in self._gs if g.kind == er.PIECE}
        self._opened &= firsts
        titles = [i.title or "" for i in infos]
        rows, self._refs = er.rows_of(self._gs, self._kl, self._nums, titles, self._ticks, self._opened)
        self._cursor = min(self._cursor, len(rows) - 1)
        self.rows.sync(rows)
        self._after_rows()

    def _after_rows(self) -> None:
        self._rev += 1
        self._head = er.head_state(self._ticks, self._oks)
        self._summary = er.summary(self._ticks, self._kl, self._nums) if self._kl else ("", "")
        self.choiceChanged.emit()
        self._compute_bar()

    def _target(self) -> str:
        lang = fbooks.series_language(self._info) if self._info is not None else None
        return fbooks.target_label(lang) if lang else ""

    def _why_off(self) -> str:
        if not self._target():
            return _plain(tips.EX_BTN_LANGUAGE)
        if not self._oks:
            return tips.EX_BTN_EMPTY
        if not self._ticks:
            return tips.EX_BTN_NONE
        return ""

    def _compute_bar(self) -> None:
        target, source = self._target(), self._ctx["source"]
        folder = self._info.name if self._info is not None else ""
        one = (tips.EX_BTN_ONE[0] % (target or "translated"), [[k, v % folder] for k, v in tips.EX_BTN_ONE[1]])
        both = (tips.EX_BTN_BOTH[0] % (target or "translated", source, target or "translated", source),
                [[k, v % folder] for k, v in tips.EX_BTN_BOTH[1]])
        why = self._why_off()
        segs = er.segments(len(self._ticks), self._busy, target, source, why, (_tip(one), _tip(both)))
        if self._busy:
            segs = [dict(s, tip=tips.EX_BTN_BUSY if s["busy"] else s["tip"]) for s in segs]
        if segs != self._bar:
            self._bar = segs
            self.barChanged.emit()

    # ------------------------------------------------------------- choosing (8.7: boxes as on Books)
    def _ref_span(self, ref: int):
        """(first, last, oks) of a row reference: a group, or one chapter row."""
        if ref >= 0:
            g = self._gs[ref]
            return g.first, g.last, g.oks
        p = -ref - 1
        return p, p, ((p,) if self._kl[p] == er.OK else ())

    @Slot(int, bool, bool)
    def rowPressed(self, index: int, ctrl: bool, shift: bool) -> None:
        """A click on a row or its box (Ctrl the same): toggles it; Shift takes every translated chapter between the last
        click and this row, across pieces."""
        if not 0 <= index < len(self._refs):
            return
        self._cursor = index
        a, b, oks = self._ref_span(self._refs[index])
        if not oks:
            self.choiceChanged.emit()
            return
        if shift and self._anchor is not None:
            lo, hi = min(a, self._anchor[0]), max(b, self._anchor[1])
            self._ticks = er.between(self._ticks, self._oks, lo, hi)
        else:
            self._ticks = er.toggled(self._ticks, oks)
        self._anchor = (a, b)
        self._touched = True
        self._rebuild()

    @Slot(int)
    def moveCursor(self, delta: int) -> None:
        n = len(self._refs)
        if n:
            self._cursor = max(0, min(n - 1, (-1 if self._cursor < 0 and delta > 0 else self._cursor) + delta))
            self.choiceChanged.emit()

    @Slot(str)
    def moveTo(self, where: str) -> None:
        if self._refs:
            self._cursor = 0 if where == "home" else len(self._refs) - 1
            self.choiceChanged.emit()

    @Slot()
    def toggleCurrent(self) -> None:
        """Space: the row under the cursor, like a click on its box."""
        if self._cursor >= 0:
            self.rowPressed(self._cursor, False, False)

    @Slot(int)
    def activateRow(self, index: int) -> None:
        """Enter or a double click: a piece opens or closes, a link row follows its link."""
        if not 0 <= index < len(self._refs):
            return
        if self.rows.row(index)[0] == er.PIECE:
            self.toggleOpen(index)
        else:
            self.markClicked(index)

    @Slot()
    def headBox(self) -> None:
        self._ticks = er.head_toggled(self._ticks, self._oks)
        self._touched = True
        self._rebuild()

    @Slot(int)
    def toggleOpen(self, index: int) -> None:
        """The `▸` of a piece: its chapters with the same boxes."""
        if not 0 <= index < len(self._refs) or self._refs[index] < 0:
            return
        first = self._gs[self._refs[index]].first
        self._opened ^= {first}
        self._rebuild()

    @Slot(int, str, str, result=bool)
    def setSpan(self, index: int, first: str, last: str) -> bool:
        """The two framed fields of an opened piece: the part of it that goes into the file. A wrong number gives False
        (the field flashes and goes back); From > To is swapped."""
        if not 0 <= index < len(self._refs) or self._refs[index] < 0:
            return False
        g = self._gs[self._refs[index]]
        try:
            a, b = int(first.strip()), int(last.strip())
        except ValueError:
            return False
        a, b = min(a, b), max(a, b)
        mine = [p for p in g.oks if a <= self._nums[p] <= b]
        have = {self._nums[p] for p in g.oks}
        if not mine or a < min(have) or b > max(have):
            return False
        self._ticks = (self._ticks - set(g.oks)) | set(mine)
        self._touched = True
        self._rebuild()
        return True

    # ------------------------------------------------------------- the marks (links)
    @Slot(int)
    def markClicked(self, index: int) -> None:
        if not 0 <= index < len(self._refs):
            return
        row = self.rows.row(index)
        kind, ref = row[4], self._refs[index]
        if kind == "problem":
            pos = self._gs[ref].fails[0] if ref >= 0 else -ref - 1
            self._show_problem(pos)
        elif kind == "go" and ref >= 0:
            self.books.selectPositions(list(self._gs[ref].members))
            self.app.go("translate")
        elif kind == "exported" and ref >= 0:
            self._reveal(self._gs[ref].stamp)

    def _show_problem(self, pos: int) -> None:
        self.app.go("translate")
        if self.translate is not None:
            self.translate.showProblemAt(pos)

    def _reveal(self, stamp) -> None:
        if stamp and self._path:
            self.reveal(str(Path(self._path) / "out" / stamp[1]))

    @Slot(int, result="QVariant")
    def markTip(self, index: int):
        row = self.rows.row(index)
        if not row or not row[3] or not 0 <= index < len(self._refs):
            return ""
        ref, kind = self._refs[index], row[4]
        if ref < 0:
            return tips.EX_PROBLEM_CHAPTER
        g = self._gs[ref]
        if kind == "problem":
            names = ", ".join("chapter %d" % self._nums[p] for p in g.fails[:3]) + ("…" if len(g.fails) > 3 else "")
            one = tips.EX_PROBLEM if len(g.fails) == 1 else tips.EX_PROBLEMS
            return _tip((one[0] % names, one[1]))
        if kind == "wave":
            return self._run_tip(g)
        if kind == "go":
            return _tip(tips.EX_GAP)
        if kind == "part":
            return tips.EX_PART % (er.ticked_count(g, self._ticks), len(g.oks))
        if kind == "exported" and g.stamp:
            t = tips.EX_EXPORTED
            return _tip((t[0] % fex.day_text(g.stamp[0]), [[t[1][0][0], g.stamp[1]], list(t[1][1])]))
        return ""

    def _run_tip(self, g):
        live = self._live
        cur = next((p for p in g.members if p in live and live[p][1] and live[p][0] < live[p][1]), None)
        if cur is None:
            return _tip(tips.EX_RUN_WAIT)
        done, total, _f = live[cur]
        t = tips.EX_RUN
        return _tip((t[0] % (self._nums[cur], int(done * 100 / total) if total else 0), t[1]))

    # ------------------------------------------------------------- the export (8.3-8.5)
    @Slot(str)
    def act(self, seg_id: str) -> None:
        if seg_id in ("single", "bilingual"):
            self._export(seg_id)

    def _export(self, mode: str) -> None:
        if self._busy or self._why_off() or not self._info:
            return
        positions = sorted(self._ticks)
        self._touched = True                        # the choice stays as it was pressed, also after the rows split
        rs = er.ranges(self._ticks, self._kl, self._nums)
        tag = langrules.split(fbooks.series_language(self._info) or "")[0]
        name = er.file_name(fbooks.clean_name(self._info.name, 60, "series"), rs, tag,
                            self._ctx["source_tag"] if mode == "bilingual" else "")
        self._run_export(mode, positions, name)

    def _run_export(self, mode: str, positions, name: str) -> None:
        path, book, key = self._path, self._book, self._key()
        self._busy = mode
        self._last = (mode, tuple(positions), name)
        self._compute_bar()
        args = {"series_path": path, "book": book, "positions": list(positions), "mode": mode, "name": name}

        def done(out):
            if self._busy == mode and self._key() == key:
                self._exported(out, positions)

        def failed(exc):
            if self._busy == mode and self._key() == key:
                self._busy, self._token = "", None
                self._compute_bar()
                self._open_panel("error", {"title": "Export failed", "file": "Nothing written",
                                           "facts": er.error_text(exc), "left": "", "tip": ""})

        def go():
            if self._busy != mode or self._key() != key:
                return
            if self.crunch is not None:
                self._token = self.crunch.submit("export", args, on_result=done, on_error=failed, group="export",
                                                  keep=True)
            else:
                self._token = self.lanes.submit(lambda ctx: fbooks.export_piece_task(ctx, **args), on_result=done,
                                                on_error=failed, lane="read", group="export")

        self.order.before_book_work(go, folder=path)

    def _exported(self, out, positions) -> None:
        self._busy, self._token = "", None
        self._compute_bar()
        if out.nothing:
            self._open_panel("nothing", {"title": "No file was written", "file": "",
                                         "facts": "No chosen chapter is fully translated yet.", "left": "", "tip": ""})
            return
        skipped = {int(s[0]) for s in out.skipped}
        kept = [p for p in positions if p not in skipped]
        facts, _ = er.result_texts(out.kept, out.size, 0)
        left = ""
        tip = ""
        if skipped:
            left = "%d not translated yet, left out" % len(skipped)
            names = "; ".join((s[1] or "Chapter %d" % (int(s[0]) + 1))[:40] for s in list(out.skipped)[:8])
            tip = tips.EX_RESULT_LEFT % names
        self._pending_hist = None
        path, book, name = self._path, self._book, out.name
        self._open_panel("ok", {"title": "Exported", "file": out.name, "facts": facts, "left": left, "tip": tip,
                                "path": out.path})

        def saved(h):
            self._pending_hist = dict(h)
        self.lanes.submit(lambda ctx: fex.add_history(path, book, kept, name), on_result=saved,
                          on_error=lambda e: None, lane="data")

    @Slot()
    def cancelExport(self) -> None:
        """Esc, another book, closing: the helper is killed (it releases the book) and the leftovers are swept."""
        if not self._busy:
            return
        tok, path = self._token, self._path
        self._busy, self._token, self._last = "", None, None
        if tok is not None:
            tok.cancel()
        self._compute_bar()
        if path:
            self.lanes.submit(lambda ctx: _sweep_when_free(path), lane="data")

    @Slot()
    def escape(self) -> None:
        self.cancelExport()

    # ------------------------------------------------------------- the result panel
    @Property(str, notify=panelChanged)
    def panel(self):
        return self._panel

    @Property("QVariantMap", notify=panelChanged)
    def panelData(self):
        return self._panel_data

    def _open_panel(self, name: str, data: dict) -> None:
        self._panel, self._panel_data = name, data
        self.app.show_panel("export", {"kind": name})
        self.panelChanged.emit()

    def _close_panel(self, apply: bool = True) -> None:
        if not self._panel:
            return
        was = self._panel
        self._panel, self._panel_data = "", {}
        if self.app.panel == "export":
            self.app.closePanel()
        if apply and was == "ok" and self._pending_hist is not None:
            self._hist, self._pending_hist = self._pending_hist, None      # after Close the exported rows get the mark
            self._rebuild()
        self.panelChanged.emit()

    def _app_panel_changed(self) -> None:
        if self._panel and self.app.panel != "export":
            was, self._panel, self._panel_data = self._panel, "", {}
            if was == "ok" and self._pending_hist is not None:
                self._hist, self._pending_hist = self._pending_hist, None
                self._rebuild()
            self.panelChanged.emit()

    @Slot()
    def panelClose(self) -> None:
        self._close_panel()

    @Slot()
    def panelOk(self) -> None:
        """`Show in folder` of the result, `Try again` of the error."""
        panel, data, last = self._panel, self._panel_data, self._last
        if panel == "ok":
            if data.get("path"):
                self.reveal(data["path"])
            self._close_panel()
        elif panel == "error" and last is not None:
            self._close_panel(apply=False)
            self._run_export(*last)
        else:
            self._close_panel()

    def shutdown(self) -> None:
        self._sync_t.stop()
        self.cancelExport()


def _plain(value):
    return value[0] if isinstance(value, tuple) else value


def _sweep_when_free(path) -> int:
    """The killed helper may still hold its `.part` for a moment: try again for up to two seconds."""
    import time
    n = 0
    for _ in range(20):
        n += fex.sweep_task(None, path)
        if not list((Path(path) / "out").glob("*" + fbooks.PART)):
            break
        time.sleep(0.1)
    return n
