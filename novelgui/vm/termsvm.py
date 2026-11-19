"""The view-model of the Terms screen (window_spec 6.1-6.7, 9.12, 10.3, 10.7, 14.11, 14.13).

Rules live in ctl/ (termrows: tabs, order, cells, the floating element, the `To` list; TermsSession: the base on the
data lane, commands, scans, snapshots) and RowSelection; this object is the glue: plain data to Qt properties and one
list model, the user's intents back to the session. The table is arranged (filter, order, strings) on the data lane
and swapped in as ONE reset; ticks and the cursor are sent at once. Timers are Python QTimers (logic never waits on a
QML timer, qml_probes (f)). Heavy book work (the whole-book scan, the occurrences of a term) runs in the helper process
through the session.
"""

from __future__ import annotations

import bisect
import dataclasses
import html
import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .. import langrules, qtclock, termtips
from ..ctl import termrows as tr
from ..ctl.termshistory import TermsHistory, series_key
from ..ctl.terms import TermsSession
from ..facade import books as fbooks
from ..termlogic import term_regex
from ..terms_const import TYPES
from .rowselection import RowSelection
from .termmodel import TermModel

KEY_MEMORY = "terms"
SKELETON_MS = 300
ARRANGE_MS = 60
SEARCH_MS = 180
MESSAGE_MS = 6000
FIELDS = {"ren": "tr", "about": "note"}


def _tips() -> dict:
    return {"nolang": termtips.NO_LANGUAGE, "confirmTicked": "Confirm the ticked terms as they are (rows with two values or "
            "without a rendering stay; a confirmed term keeps the value in use).", "merge": termtips.MERGE,
            "notATerm": termtips.NOT_A_TERM, "scanning": termtips.SCANNING, "goTranslate": "%s",
            "confirmN": termtips.confirm_tip}


class TermsVM(QObject):
    viewChanged = Signal()
    listChanged = Signal()
    floatChanged = Signal()
    readerChanged = Signal()
    editChanged = Signal()
    importChanged = Signal()
    languageChanged = Signal()
    selectionChanged = Signal()
    importDialogRequested = Signal(str)
    exportDialogRequested = Signal(str)
    openFolderRequested = Signal(str)
    translateRequested = Signal()

    def __init__(self, app, lanes, books, crunch=None, local=None, parent=None):
        super().__init__(parent)
        self.app, self.lanes, self.books = app, lanes, books
        self.local = Path(local) if local else None
        self.session = TermsSession(lanes.submit, qtclock.timer, crunch)
        self.model = TermModel(self)
        self.session.changed.add(self._on_session)
        self.session.rejected.add(self._on_rejected)
        self._sel = RowSelection()
        self._shown: list = []
        self._ctx = ("", "", (), "", [])
        self._open_key = None
        self._info = None
        self._loaded = False
        self._loading = False
        self._skeleton = False
        self._total = 0
        self._counts = {t: 0 for t in tr.TABS}
        self._blocking: frozenset = frozenset()
        self._tab = "blocking"
        self._search, self._search_open = "", False
        self._type = ""
        self._sort, self._desc = "first", False
        self._keep: set = set()
        self._imported = None
        self._confirm_keys: list = []
        self._edit = None                       # (row index, field)
        self._scanning = 0
        self._percent = 0.0
        self._msg = None
        self._lang_locked = (False, False)
        self._source_tag = ""
        self._places: list = []
        self._place = 0
        self._places_done = True
        self._reader_key = ""
        self._import = {"open": False, "files": [], "paths": []}
        self._importing = False
        self._last_save = ""
        self.mine_names = True              # tests switch the offline name miner off to count exactly
        self.auto_scan = True               # ... and the scan on open, to look at an unscanned base
        self.feed_blocking = True           # ... and the Blocking count Books shows (a Books scene injects its own)
        self._import_names: list = []
        self._imp_keys: set = set()
        self.arranges = 0
        self._sync_t = self._timer(ARRANGE_MS, self._sync)
        self._arrange_t = self._timer(ARRANGE_MS, self._arrange)
        self._recount_t = self._timer(ARRANGE_MS, self._recount)
        self._skeleton_t = self._timer(SKELETON_MS, self._show_skeleton)
        self._msg_t = self._timer(MESSAGE_MS, self._expire_message)
        for sig in (books.viewChanged, books.selectionChanged, books.seriesChanged, app.screenChanged):
            sig.connect(self._sync_later)
        self._restore_memory()

    def _sync_later(self) -> None:
        self._sync_t.start(ARRANGE_MS)

    def _timer(self, ms, fn) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(ms)
        t.timeout.connect(fn)
        return t

    # ------------------------------------------------------------- window memory (10.6)
    def _restore_memory(self) -> None:
        raw = self.app.win.get_dict(KEY_MEMORY) if hasattr(self.app.win, "get_dict") else {}
        mem = tr.clean_memory(raw, TYPES)
        self._tab = mem.get("tab", "blocking")
        self._type = mem.get("type", "")
        self._search = mem.get("query", "")
        self._search_open = bool(self._search)
        s = mem.get("sort")
        if s:
            self._sort, self._desc = s["key"], s["desc"]

    def _remember(self) -> None:
        mem = {"tab": self._tab, "type": self._type, "query": self._search}
        if (self._sort, self._desc) != ("first", False):
            mem["sort"] = {"key": self._sort, "desc": self._desc}
        self.app.win.set(KEY_MEMORY, mem)

    # ------------------------------------------------------------- following Books
    def _sync(self) -> None:
        path, book, idx, rng, numbers = self.books.terms_context()
        info = self.books.info() if path else None
        key = (path, book, info.tag if info else "", self._language(info))
        self._info = info
        old_sel = self._ctx[2]
        self._ctx = (path, book, idx, rng, numbers)
        if not path or not book or info is None or info.broken:
            if self._open_key is not None:
                self._open_key = None
                self._reset_state()
            return
        if key != self._open_key:
            self._open_key = key
            self._open(path, book, info)
        elif idx != old_sel:
            self._recount_t.start(ARRANGE_MS)
        self.floatChanged.emit()

    @staticmethod
    def _language(info) -> str:
        return (fbooks.series_language(info) or "") if info is not None else ""

    def _reset_state(self) -> None:
        self.session.rows = {}
        self.session.suggestions = []
        self._loaded = self._loading = False
        self._blocking = frozenset()
        self.books.set_blocking(0)
        self._arrange()

    def _open(self, path: str, book: str, info) -> None:
        self._reset_state()
        self._loading, self._loaded = True, False
        self._skeleton = False
        self._skeleton_t.start()
        self._imported = None
        self._keep = set()
        self._msg = None
        self._sel.clear()
        if self.local is not None:
            self.session.history = TermsHistory(self.local / "terms_history" / series_key(path))
        self.session.open(path, info.tag or "ru", on_done=self._opened)
        self._ask_language_lock(path, book)
        self.viewChanged.emit()
        self.languageChanged.emit()

    def _ask_language_lock(self, path: str, book: str) -> None:
        def work(ctx):
            return fbooks.language_lock(path), fbooks.source_language(path, book).tag

        def done(res):
            self._lang_locked, self._source_tag = res
            self.languageChanged.emit()
        self.lanes.submit(work, on_result=done, on_error=lambda exc: None, lane="data", group="terms-lang")

    def _opened(self, n: int) -> None:
        self._loading, self._loaded = False, True
        self._skeleton_t.stop()
        self._skeleton = False
        self._recount()
        self._start_scan(first=True)

    def _show_skeleton(self) -> None:
        if self._loading or (self._scanning and not self.session.rows and not self.session.suggestions):
            self._skeleton = True
            self.viewChanged.emit()

    # ------------------------------------------------------------- the book scan (6.7: it belongs to the series)
    def _start_scan(self, first: bool = False) -> None:
        path, book = self._ctx[0], self._ctx[1]
        if not path or not book or not self.auto_scan:
            return
        rows = list(self.session.rows.values())
        unscanned = not rows or any(r.first is None for r in rows)
        if first and not unscanned:
            if self.mine_names:
                self.session.load_names(book, on_done=lambda n: self._arrange_now())
            return
        self._scanning += 1
        self._percent = 0.0
        self._set_scan_line()
        self._skeleton_t.start()
        if rows:
            self._scanning += 1
            self.session.scan_book(book, on_done=lambda n: self._scan_done(), on_error=lambda e: self._scan_failed(e),
                                   on_progress=self._scan_progress)
        if self.mine_names:
            self._scanning += 1
            self.session.load_names(book, on_done=lambda n: self._scan_done(), on_error=lambda e: self._scan_failed(e))
        self._scan_done()

    def _scan_progress(self, item) -> None:
        if isinstance(item, (list, tuple)) and len(item) == 3 and item[2]:
            self._percent = max(self._percent, 100.0 * item[1] / item[2])
            self._set_scan_line()
            self.floatChanged.emit()

    def _scan_done(self) -> None:
        self._scanning = max(0, self._scanning - 1)
        if not self._scanning:
            self._skeleton = False
        self._set_scan_line()
        self._recount_t.start(ARRANGE_MS)
        self.viewChanged.emit()
        self.floatChanged.emit()

    def _scan_failed(self, exc) -> None:
        self.app.message = "The book could not be read for terms: %s." % exc
        self._scan_done()

    def _set_scan_line(self) -> None:
        self.app.set_terms_scan(self._percent if self._scanning else -1)

    # ------------------------------------------------------------- the session tells
    def _on_session(self, kind: str, keys) -> None:
        if kind == "rows":
            for k in keys:
                self._patch(k)
        self._recount_t.start(ARRANGE_MS)

    def _on_rejected(self, keys, error) -> None:
        self.app.message = error

    def _patch(self, key: str) -> None:
        row = self.session.rows.get(key)
        if row is None:
            return
        for i, r in enumerate(self._shown):
            if r.key == key:
                self._shown[i] = row
                self.model.replace(i, tr.model_row(row, self._ctx[4], self.nolang))
                return

    def _recount(self) -> None:
        """Which unconfirmed terms occur in the selected chapters = Blocking: the same number Books and Translate show."""
        idx = self._ctx[2]
        if not idx:
            self._set_blocking(frozenset())
            return
        self.session.blocking_keys(idx, lambda keys: self._set_blocking(keys if keys is not None else frozenset()))

    def _set_blocking(self, keys) -> None:
        was = bool(self._blocking)
        self._blocking = frozenset(keys)
        if self.feed_blocking:
            self.books.set_blocking(len(self._blocking))
        if was and not self._blocking and self.app.termsState == "red":
            fields = dataclasses.asdict(self.app.run)
            fields["terms_red"] = False
            self.app.setRun(fields)
        self._arrange_t.start(ARRANGE_MS)

    # ------------------------------------------------------------- arranging (data lane)
    def _arrange_now(self) -> None:
        self._arrange_t.start(ARRANGE_MS)

    def _arrange(self) -> None:
        rows = list(self.session.rows.values()) + list(self.session.suggestions)
        args = dict(tab=self.effective_tab, blocking=self._blocking, query=self._search, type_filter=self._type,
                    imported=self._imported, keep=frozenset(self._keep), key=self._sort, desc=self._desc)
        numbers, nolang = self._ctx[4], self.nolang

        def work(ctx):
            shown = tr.arrange(rows, **args)
            ctx.breathe()
            cells = []
            for n, r in enumerate(shown):
                cells.append(tr.model_row(r, numbers, nolang))
                if not n & 255:
                    ctx.breathe()
            counts = tr.counts(rows, args["blocking"], args["type_filter"], args["imported"])
            return shown, cells, counts, len(rows), [r.key for r in tr.confirmable(shown)]
        self.lanes.submit(work, on_result=self._arranged, lane="data", group="terms-arrange")

    def _arranged(self, res) -> None:
        shown, cells, counts, total, confirm = res
        self.arranges += 1
        self._shown, self._counts, self._total, self._confirm_keys = shown, counts, total, confirm
        self._sel.set_rows(r.key for r in shown)
        self.model.set_rows(cells)
        self._push_selection(reader=False)
        if self._reader_key != self._cursor_key():
            self._open_reader()
        self.viewChanged.emit()
        self.listChanged.emit()
        self.floatChanged.emit()

    def _push_selection(self, reader: bool = True) -> None:
        cur = self._sel.cursor_index
        self.model.set_selection(self._sel.positions(), -1 if cur is None else cur)
        self.selectionChanged.emit()
        self.floatChanged.emit()
        if reader and self._reader_key != self._cursor_key():
            self._open_reader()

    # ------------------------------------------------------------- properties
    @Property(QObject, constant=True)
    def table(self):
        return self.model

    @Property("QVariantMap", constant=True)
    def tips(self):
        return {"blocking": termtips.TAB_BLOCKING, "blockingNone": termtips.TAB_BLOCKING_NONE,
                "notconf": termtips.TAB_NOTCONF, "confirmed": termtips.TAB_CONFIRMED, "search": termtips.SEARCH,
                "clear": termtips.SEARCH_CLEAR, "more": termtips.MORE, "moreBusy": termtips.MORE_BUSY,
                "toEmpty": termtips.HEAD_TO_EMPTY, "type": termtips.HEAD_TYPE, "noLang": termtips.NO_LANGUAGE,
                "slot": termtips.NO_RENDERING, "unknown": list(self._unknown()), "prev": termtips.PREV_PLACE,
                "next": termtips.NEXT_PLACE, "importGoes": termtips.IMPORT_GOES, "importWhere": termtips.IMPORT_WHERE,
                "neuter": termtips.NEUTER, "scanning": termtips.SCANNING, "emptyImport": "Add terms from a glossary file "
                "(JSON). Only adds, never replaces."}

    @staticmethod
    def _unknown():
        from .. import tips as app_tips
        return app_tips.UNKNOWN_FIELD[0], [list(f) for f in app_tips.UNKNOWN_FIELD[1]]

    @Property(bool, notify=languageChanged)
    def nolang(self):
        return self._info is not None and not self._language(self._info)

    @Property(str, notify=languageChanged)
    def languageName(self):
        target = self._language(self._info)
        return langrules.split(target)[1] if target else ""

    @Property(str, notify=viewChanged)
    def view(self):
        if self._open_key is None:
            return "none"
        if self._loading or (self._scanning and self._skeleton and not self._shown):
            return "loading"
        if not self._total:
            return "empty"
        return "rows" if self._shown else "zero"

    @Property(bool, notify=viewChanged)
    def skeleton(self):
        return self._skeleton and (self._loading or (self._scanning and not self._total))

    @Property(bool, notify=viewChanged)
    def scanning(self):
        return self._scanning > 0

    @Property(int, notify=viewChanged)
    def count(self):
        return len(self._shown)

    @property
    def effective_tab(self) -> str:
        return "notconf" if self._tab == "blocking" and not self._ctx[2] else self._tab

    @Property(str, notify=viewChanged)
    def tab(self):
        return self.effective_tab

    @Property("QVariantList", notify=viewChanged)
    def tabList(self):
        out = []
        none = not self._ctx[2]
        for t in tr.TABS:
            n = "…" if self._scanning and t != "confirmed" else str(self._counts[t])
            tip = (termtips.TAB_BLOCKING_NONE if none else termtips.TAB_BLOCKING) if t == "blocking" else (
                termtips.TAB_NOTCONF if t == "notconf" else termtips.TAB_CONFIRMED)
            out.append({"id": t, "text": tr.TAB_LABELS[t], "count": n, "on": t == self.effective_tab,
                        "dim": t == "blocking" and none, "tip": tip})
        return out

    @Property(int, notify=viewChanged)
    def blockingCount(self):
        return len(self._blocking)

    @Property(str, notify=viewChanged)
    def chapters(self):
        return self._ctx[3]

    @Property(str, notify=viewChanged)
    def search(self):
        return self._search

    @Property(bool, notify=viewChanged)
    def searchOpen(self):
        return self._search_open or bool(self._search)

    @Property(bool, notify=viewChanged)
    def searchZero(self):
        return bool(self._search.strip()) and not self._shown and self._total > 0

    @Property(str, notify=viewChanged)
    def typeFilter(self):
        return self._type

    @Property(str, notify=viewChanged)
    def sortKey(self):
        return self._sort

    @Property(bool, notify=viewChanged)
    def sortDesc(self):
        return self._desc

    @Property(int, notify=viewChanged)
    def importedCount(self):
        return len(self._imported) if self._imported is not None else 0

    @Property(bool, notify=viewChanged)
    def importing(self):
        return self._importing

    @Property(int, notify=selectionChanged)
    def cursor(self):
        c = self._sel.cursor_index
        return -1 if c is None else c

    @Property(int, notify=selectionChanged)
    def tickedCount(self):
        return len(self._sel.ids)

    @Property(str, notify=selectionChanged)
    def headState(self):
        n = len(self._sel.ids)
        return "none" if not n else ("all" if n >= len(self._shown) else "some")

    @Property("QVariantMap", notify=floatChanged)
    def floating(self):
        return tr.float_spec(self._msg, len(self._sel.ids), self.effective_tab, self.nolang, self._scanning > 0,
                             self._percent, len(self._blocking), self.app.termsState == "red", self._ctx[3],
                             len(self._confirm_keys), bool(self._search.strip()), self._total > 0, self._loading,
                             self._imported is not None, self._float_tips())

    def float_text(self) -> str:
        """The fact line of the floating element as plain text (what a person reads; tests assert on it)."""
        return "".join(p["text"] for p in self.floating.get("fact", []))

    def _float_tips(self) -> dict:
        t = _tips()
        t["goTranslate"] = termtips.GO_TRANSLATE % self._ctx[3]
        return t

    # ------------------------------------------------------------- tabs, search, type, order
    @Slot(str)
    def selectTab(self, tab: str) -> None:
        if tab not in tr.TABS or (tab == "blocking" and not self._ctx[2]):
            return
        self._tab = tab
        self._reset_choice()
        self._remember()
        self._arrange()
        self.viewChanged.emit()

    def _reset_choice(self) -> None:
        """Another tab or filter: the rows kept by a chip, the ticks, the cursor and the message go (F6)."""
        self._keep = set()
        self._sel.clear()
        self._edit = None
        self._msg = None
        self.editChanged.emit()

    @Slot(str)
    def setSearch(self, text: str) -> None:
        if text == self._search:
            return
        self._search = text
        self._remember()
        self._arrange_t.start(SEARCH_MS)
        self.viewChanged.emit()

    @Slot()
    def openSearch(self) -> None:
        self._search_open = True
        self.viewChanged.emit()

    @Slot()
    def closeSearch(self) -> None:
        self._search_open = False
        self.setSearch("")
        self.viewChanged.emit()

    @Slot(result="QVariantList")
    def typeFilterItems(self) -> list:
        items = [{"text": "All types", "id": "", "kind": "check" if not self._type else ""}, {"kind": "divider", "text": ""}]
        return items + [{"text": t, "id": t, "kind": "check" if t == self._type else ""} for t in TYPES]

    @Slot(str)
    def pickTypeFilter(self, t: str) -> None:
        self._type = t if t in TYPES else ""
        self._reset_choice()
        self._remember()
        self._arrange()
        self.viewChanged.emit()

    @Slot(str)
    def sortBy(self, column: str) -> None:
        key = tr.SORT_COLUMNS.get(column)
        if key is None:
            return
        self._desc = (not self._desc) if key == self._sort else key in ("count",)
        self._sort = key
        self._remember()
        self._arrange()
        self.viewChanged.emit()

    # ------------------------------------------------------------- selection and keys (10.7)
    def _cursor_key(self) -> str:
        return self._sel.cursor if self._sel.cursor is not None else ""

    @Slot(int, bool, bool, bool)
    def rowPressed(self, index: int, onBox: bool, ctrl: bool, shift: bool) -> None:
        """The box, Ctrl or Shift tick rows; a click on the row itself opens the reader and KEEPS the ticks (F6); a second
        click on the open row closes it."""
        self._msg = None
        cursor = self._sel.cursor
        if onBox or ctrl:
            self._sel.click(index, ctrl=True)
            self._sel.cursor = cursor
        elif shift:
            self._sel.click(index, shift=True)
            self._sel.cursor = cursor
        elif 0 <= index < len(self._sel.rows) and self._sel.cursor == self._sel.rows[index]:
            self._sel.cursor = None
        else:
            self._sel.point(index)
        self._push_selection()

    @Slot(int)
    def rowDragged(self, index: int) -> None:
        pass

    @Slot(int, bool)
    def moveCursor(self, delta: int, extend: bool) -> None:
        if self._sel.cursor is None and delta > 0:
            delta -= 1                      # the first Down lands on the first row
        self._sel.move(delta, extend, select=False)
        self._push_selection()

    @Slot(str, bool)
    def moveTo(self, where: str, extend: bool) -> None:
        (self._sel.home if where == "home" else self._sel.end)(extend, select=False)
        self._push_selection()

    @Slot()
    def selectAll(self) -> None:
        self._sel.select_all()
        self._push_selection()

    @Slot()
    def toggleCurrent(self) -> None:
        """Space: tick the cursor row."""
        if self._sel.toggle_cursor():
            self._msg = None
            self._push_selection()

    @Slot()
    def headBox(self) -> None:
        if self._sel.ids:
            self._sel.ids = set()
        else:
            self._sel.select_all()
            self._sel.cursor = None
        self._msg = None
        self._push_selection()

    @Slot()
    def clearTicks(self) -> None:
        self._sel.ids = set()
        self._push_selection()

    @Slot()
    def escape(self) -> None:
        """Esc on the table: the Imported filter goes first, then the ticks."""
        if self._imported is not None:
            self.clearImported()
        elif self._sel.ids:
            self.clearTicks()

    @Slot()
    def copyCursor(self) -> None:
        i = self.cursor
        row = self._shown[i] if 0 <= i < len(self._shown) else None
        if row is not None and isinstance(QGuiApplication.instance(), QGuiApplication):
            QGuiApplication.clipboard().setText("\t".join((row.source, row.tr, row.type, row.gender)))

    # ------------------------------------------------------------- editing in place (9.12)
    @Property(int, notify=editChanged)
    def editRow(self):
        return self._edit[0] if self._edit else -1

    @Property(str, notify=editChanged)
    def editField(self):
        return self._edit[1] if self._edit else ""

    @Slot(int, str)
    def beginEdit(self, index: int, field: str) -> None:
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        if row is None or field not in FIELDS or (field == "ren" and (self.nolang or tr.is_suggestion(row))):
            return
        self._edit = (index, field)
        self.editChanged.emit()

    @Slot(int)
    def activate(self, index: int) -> None:
        """Enter or a double-click on a row: its rendering becomes a field."""
        self.beginEdit(index, "ren")

    @Slot(str)
    def commitCell(self, text: str) -> None:
        if not self._edit:
            return
        index, field = self._edit
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        if row is not None and text.strip() != getattr(row, FIELDS[field]):
            self.session.edit(row.key, FIELDS[field], text)

    @Slot()
    def endEdit(self) -> None:
        if self._edit:
            self._edit = None
            self.editChanged.emit()

    @Slot()
    def nextCell(self) -> None:
        """Tab: the rendering is taken and the About cell of the row opens."""
        if self._edit and self._edit[1] == "ren":
            self._edit = (self._edit[0], "about")
            self.editChanged.emit()

    @Slot(int, str)
    def nameRendering(self, index: int, text: str) -> None:
        """A mined name got a rendering (type it + Enter): it becomes a confirmed entry."""
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        if row is None or not text.strip() or not tr.is_suggestion(row) or self.nolang:
            return
        self._msg = None
        self.session.add_name(row.source, text.strip())

    @Slot(int, str, int)
    def takeChip(self, index: int, field: str, k: int) -> None:
        """A click on a candidate takes it: the field is locked, the row is ticked and stays in the list (F6)."""
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        cands = tr.choice_of(row, "tr" if field == "ren" else "gender") if row is not None else ()
        if not cands or not 0 <= k < len(cands):
            return
        self._keep.add(row.key)
        self._msg = None
        self.session.edit(row.key, "tr" if field == "ren" else "gender", cands[k][0])
        if row.key not in self._sel.ids:
            self._sel.ids.add(row.key)
        self._sel.anchor = row.key
        self._push_selection()

    @Slot(int, str, int, result="QVariant")
    def chipTip(self, index: int, field: str, k: int):
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        cands = tr.choice_of(row, "tr" if field == "ren" else "gender") if row is not None else ()
        if not cands or not 0 <= k < len(cands):
            return ""
        value = tr.gender_short(cands[k][0]) or cands[k][0]
        return termtips.chip_tip(value, cands[k][1])

    @Slot(int, result="QVariantList")
    def typeItems(self, index: int) -> list:
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        cur = row.type if row is not None else ""
        items = [{"text": t, "id": t, "kind": "check" if t == cur else ""} for t in TYPES if t != "term"]
        items.append({"text": "term", "id": "term", "kind": "check" if cur == "term" else ""})
        return items + [{"kind": "divider", "text": ""}, {"text": "—  not known", "id": "term"}]

    @Slot(int, result="QVariantList")
    def genderItems(self, index: int) -> list:
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        cur = row.gender if row is not None else ""
        items = [{"text": code, "id": stored, "kind": "check" if stored == cur else "",
                  "tip": termtips.NEUTER if stored == "neuter" else ""} for stored, code, _w in tr.GENDER_CODES]
        return items + [{"kind": "divider", "text": ""}, {"text": "—  not known", "id": "unknown",
                                                          "kind": "check" if cur not in ("male", "female", "neuter") else ""}]

    @Slot(int, str, str)
    def pickCell(self, index: int, field: str, value: str) -> None:
        row = self._shown[index] if 0 <= index < len(self._shown) else None
        if row is None or tr.is_suggestion(row):
            return
        self.session.edit(row.key, field, value)

    # ------------------------------------------------------------- the floating element
    @Slot(str)
    def floatVerb(self, vid: str) -> None:
        if vid == "translate":
            self.translateRequested.emit()
            self.app.go("translate")
        elif vid == "confirmAll":
            self._confirm(list(self._confirm_keys))
        elif vid == "confirm":
            self._confirm([k for k in self._sel.selected() if self._can_confirm(k)])
        elif vid in ("merge", "dismiss", "delete"):
            self._bulk(vid)
        elif vid == "undo":
            self._undo()
        elif vid == "showImported":
            self.showImported()
        elif vid == "showFolder":
            self.openFolderRequested.emit(self._last_save)

    def _can_confirm(self, key: str) -> bool:
        row = self.session.rows.get(key)
        return (row is not None and not tr.is_suggestion(row) and not self.nolang and not row.questions
                and bool(row.tr or row.status == "confirmed"))

    def _confirm(self, keys: list) -> None:
        if not keys or self.nolang:
            return
        self._msg = None
        self._keep -= set(keys)
        self._sel.ids -= set(keys)
        self.session.confirm(keys, "Confirm %s" % tr.plural(len(keys)))
        self._push_selection()

    def _bulk(self, what: str) -> None:
        keys = [k for k in self._sel.selected() if k in self.session.rows or k.startswith("?")]
        if what == "merge":
            keys = [k for k in keys if not k.startswith("?")]
        if not keys or (what == "merge" and len(keys) < 2):
            return
        self._sel.ids = set()
        if what == "merge":
            self.session.merge(keys, "Merge %s" % tr.plural(len(keys)))
            self._say(tr.done_fact("Merged", len(keys)), [])
        else:
            word = "Not a term %d" % len(keys) if what == "dismiss" else "Delete %s" % tr.plural(len(keys))
            self.session.delete(keys, word, op=what)
            self._say(tr.done_fact("Deleted", len(keys)), [{"text": "Undo", "id": "undo", "kind": "main"}])
        self._push_selection()

    def _undo(self) -> None:
        self._msg = None
        self.session.undo_delete()
        self.floatChanged.emit()

    def _say(self, fact: list, verbs: list, progress: float = -1, expire: bool = True) -> None:
        self._msg = {"fact": fact, "verbs": verbs, "progress": progress}
        if expire:
            self._msg_t.start(MESSAGE_MS)
        else:
            self._msg_t.stop()
        self.floatChanged.emit()

    def _expire_message(self) -> None:
        if self._msg and not self._importing:
            self._msg = None
            self.floatChanged.emit()

    # ------------------------------------------------------------- language (3.2, 3.4, 9.12)
    @Slot(str, result="QVariantList")
    def languageEntries(self, query: str) -> list:
        locked = any(self._lang_locked) and bool(self._language(self._info))
        return tr.language_entries(query, self._language(self._info), self._source_tag, locked, termtips.ENGLISH_LATER,
                                   langrules.lock_reason(*self._lang_locked))

    @Slot(str)
    def chooseLanguage(self, target: str) -> None:
        if target.startswith("use:"):
            target = self._typed_language(target[4:])
        if not target or target == self._language(self._info) or self._info is None:
            return
        if any(self._lang_locked) and self._language(self._info):
            return                          # translated blocks or confirmed terms are written in it (3.6)
        path = self._info.path

        def done(_r):
            self.books.reload(then=lambda infos: self._sync())

        self.lanes.submit(lambda ctx: fbooks.set_series_language(path, target), on_result=done,
                          on_error=lambda exc: setattr(self.app, "message", "The language could not be saved: %s." % exc),
                          lane="data")

    def _typed_language(self, text: str) -> str:
        text = text.strip()
        if ":" not in text:
            tag = next((t for t, n in langrules.NAMES.items() if n.lower() == text.lower()), "")
            if not tag:
                self.app.message = langrules.FORMAT_HELP
                return ""
            text = "%s:%s" % (tag, langrules.NAMES[tag])
        try:
            return langrules.parse_other(text)
        except ValueError as exc:
            self.app.message = str(exc)
            return ""

    # ------------------------------------------------------------- reader (6.6)
    @Property("QVariantMap", notify=readerChanged)
    def reader(self):
        row = self._reader_row()
        if row is None:
            return {"open": False}
        n, k = len(self._places), self._place
        pl = self._places[k] if 0 <= k < n else None
        pat = term_regex(row)
        mentions = sum(p[2] for p in self._places)
        out = {"open": True, "title": row.source, "searching": not self._places_done, "total": n, "place": k + 1 if n else 0,
               "chapter": ("chapter %s" % self._chapter_text(pl[0])) if pl else "", "before": "", "text": "", "after": "",
               "tip": termtips.reader_counter_tip(k + 1, n, mentions, not self._places_done)[0] if n else ""}
        if pl is not None:
            out["before"] = " ".join(html.escape(t) for t in pl[3])
            out["text"] = pat.sub(lambda m: "<font color='#f4f4f4'><b><u>%s</u></b></font>" % m.group(0), html.escape(pl[4]))
            out["after"] = " ".join(html.escape(t) for t in pl[5])
        return out

    def _chapter_text(self, i: int) -> str:
        nums = self._ctx[4]
        return str(nums[i]) if 0 <= i < len(nums) else str(i + 1)

    def _reader_row(self):
        i = self.cursor
        return self._shown[i] if 0 <= i < len(self._shown) else None

    def _open_reader(self) -> None:
        row = self._reader_row()
        self._reader_key = row.key if row is not None else ""
        self._places, self._place, self._places_done = [], 0, row is None
        if row is not None:
            names = [row.source] + list(row.forms) if tr.is_suggestion(row) else None
            self.session.places(row.key, self._ctx[1], self._place_batch, self._places_finished, names=names)
        self.readerChanged.emit()

    def _place_batch(self, batch) -> None:
        for p in batch:
            bisect.insort(self._places, tuple(p), key=lambda x: (x[0], x[1]))
        self.readerChanged.emit()

    def _places_finished(self, found) -> None:
        self._places_done = True
        self.readerChanged.emit()

    @Slot(int)
    def stepPlace(self, delta: int) -> None:
        """‹ › and Alt+Left / Alt+Right: the next or the previous place of the term."""
        if self._places:
            self._place = max(0, min(len(self._places) - 1, self._place + delta))
            self.readerChanged.emit()

    # ------------------------------------------------------------- Import and Export (9.12)
    @Property(bool, notify=importChanged)
    def canImport(self):
        return not self.nolang and not self._importing and self._open_key is not None

    @Slot()
    def openImportDialog(self) -> None:
        if self.canImport:
            self.importDialogRequested.emit(self._ctx[0])

    @Slot("QVariantList")
    def importPicked(self, urls) -> None:
        paths = [_local(u) for u in urls]
        paths = [p for p in paths if p]
        if not paths or not self.canImport:
            return
        self.session.read_glossaries(paths, lambda res: self._glossaries_read(paths, res), on_error=self._import_bad)

    def _import_bad(self, exc) -> None:
        self.app.message = "A glossary could not be read: %s." % exc

    def _glossaries_read(self, paths, res) -> None:
        self._import = {"open": True, "paths": list(paths), "read": res,
                        "files": [{"name": n, "terms": c, "confirmed": True} for n, c, _k in res]}
        self.importChanged.emit()

    @Slot(int, bool)
    def setFileGoes(self, i: int, confirmed: bool) -> None:
        files = self._import.get("files", [])
        if 0 <= i < len(files):
            files[i]["confirmed"] = confirmed
            self.importChanged.emit()

    @Property("QVariantMap", notify=importChanged)
    def importPanel(self):
        files = self._import.get("files", [])
        if not self._import.get("open"):
            return {"open": False}
        read = self._import["read"]
        base = {k: r.tr for k, r in self.session.rows.items()}
        plan = tr.plan_import([(f["name"], f["terms"], read[n][2], f["confirmed"]) for n, f in enumerate(files)], base,
                              sum(1 for r in self.session.rows.values() if r.status == "confirmed" and not r.questions),
                              sum(1 for r in self.session.rows.values() if r.status == "new" or r.questions))
        return {"open": True, "files": files, "title": "Import %d %s" % (len(files), "glossary" if len(files) == 1 else "glossaries"),
                "confirmed": plan["confirmed"], "unconfirmed": plan["unconfirmed"], "choices": plan["choices"],
                "action": "Import %s" % tr.plural(plan["terms"])}

    @Slot()
    def cancelImport(self) -> None:
        self._import = {"open": False, "files": [], "paths": []}
        self.importChanged.emit()

    @Slot()
    def runImport(self) -> None:
        files = list(self._import.get("files", []))
        paths = list(self._import.get("paths", []))
        self.cancelImport()
        if not files:
            return
        names = [f["name"] for f in files]
        self._import_names = names
        self._importing = True
        self._say(tr.importing_fact(names, 1, len(names)), [], 0.05, expire=False)
        self.viewChanged.emit()
        self.session.import_files(paths, {f["name"]: f["confirmed"] for f in files}, self._import_progress, self._imported_done,
                                  self._import_failed)

    def _import_progress(self, item) -> None:
        n, total, _name = item
        self._say(tr.importing_fact(self._import_names, n, total), [], (n - 1) / max(1, total) + 0.1, expire=False)

    def _import_failed(self, exc) -> None:
        self._importing = False
        self._msg = None
        self.app.message = "The glossaries could not be imported: %s." % exc
        self.viewChanged.emit()
        self.floatChanged.emit()

    def _imported_done(self, stats) -> None:
        self._importing = False
        self._imp_keys = set(stats["keys"])
        verbs = [{"text": "Show imported", "id": "showImported", "kind": "main", "tip": termtips.SHOW_IMPORTED}]
        self._say(tr.import_fact(stats), verbs, expire=False)
        self._start_scan()
        self._recount_t.start(ARRANGE_MS)
        self.viewChanged.emit()

    @Slot()
    def showImported(self) -> None:
        keys = getattr(self, "_imp_keys", set())
        self._imported = set(keys)
        self._msg = None
        self._tab = "notconf" if any(self.session.rows.get(k) and tr.in_tab(self.session.rows[k], "notconf", ()) for k in keys) \
            else "confirmed"
        self._reset_choice()
        self._arrange()
        self.viewChanged.emit()

    @Slot()
    def clearImported(self) -> None:
        self._imported = None
        self._sel.clear()
        self._arrange()
        self.viewChanged.emit()

    @Slot()
    def openExportDialog(self) -> None:
        if self._open_key is not None:
            name = "terms-%s.json" % (Path(self._ctx[0]).name or "series")
            self.exportDialogRequested.emit(name)

    @Slot(str)
    def exportPicked(self, url: str) -> None:
        path = _local(url)
        if not path:
            return
        self._last_save = path

        def done(n):
            self._say(tr.saved_fact(Path(path).name), [{"text": "Show in folder", "id": "showFolder", "kind": ""}])
        self.session.export_file(path, done, lambda exc: setattr(self.app, "message", "The glossary could not be saved: %s." % exc))

    @Slot(result="QVariantList")
    def moreItems(self) -> list:
        return [{"text": "Import…", "id": "import", "kind": "" if self.canImport else "off",
                 "tip": termtips.NO_LANGUAGE if self.nolang else ""}, {"text": "Export…", "id": "export"}]

    @Slot(str)
    def morePicked(self, item: str) -> None:
        (self.openImportDialog if item == "import" else self.openExportDialog)()

    # ------------------------------------------------------------- tests and the shell
    def hold_loading(self) -> None:
        """A test hook: the base is being read (the skeleton after 0.3 s)."""
        self._loading = self._skeleton = True
        self.viewChanged.emit()

    def hold_importing(self, n: int, total: int, progress: float) -> None:
        """A test hook: the import is at file `n` of `total`."""
        self._importing = True
        self._say(tr.importing_fact(["glossary_a.json", "glossary_b.json"][:total], n, total), [], progress, expire=False)
        self.viewChanged.emit()

    def hold_scan(self, percent: float) -> None:
        """A test hook: the screen shows a running book scan (the real one ends too fast to be looked at)."""
        self._scanning = 1 if percent >= 0 else 0
        self._percent = max(0.0, percent)
        self._skeleton_t.start(SKELETON_MS)
        self._set_scan_line()
        self.viewChanged.emit()
        self.floatChanged.emit()

    def rows_snapshot(self) -> list:
        return list(self._shown)

    def key_at(self, index: int) -> str:
        return self._sel.rows[index] if 0 <= index < len(self._sel.rows) else ""


def _local(url) -> str:
    text = str(url)
    if text.startswith("file:"):
        return QUrl(text).toLocalFile()
    return os.path.normpath(text) if text else ""
