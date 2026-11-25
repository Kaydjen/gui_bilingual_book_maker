"""The view-model of the Books screen (window_spec 4.1-4.7): the series list, the open book's chapter list, the selection
and its capsule, rename in place, delete / remove with Undo, move a book, the reader hand-off.

Rules live in ctl/ (bookrows, addplan, BooksSession, RowSelection, chapterlogic) and libraryops; this object is the
glue: it turns their plain data into Qt properties and models and sends the user's intents back. Disk work runs on the
data lane (`lanes.submit`), the chapter scan in the helper process through BooksSession. Timers are Python QTimers.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .. import addbook, chapterlogic as cl, libraryops as ops, libraryrules as rules, tips
from ..ctl import bookrows
from ..ctl.books import BooksSession
from ..facade import books as fbooks
from .chaptermodel import ChapterModel, ranges
from .rowselection import RowSelection
from .seriesmodel import SeriesModel

LOADING_MS = 300
KEY_LAST = "books_last"


def _fact(*parts) -> list:
    """[{text, kind}] for the Message component: ("Deleted ", ""), ("Knights", "n")."""
    return [{"text": t, "kind": k} for t, k in parts]


class BooksVM(QObject):
    viewChanged = Signal()
    seriesChanged = Signal()
    chaptersChanged = Signal()
    selectionChanged = Signal()
    typingChanged = Signal()
    noticeChanged = Signal()
    editChanged = Signal()
    busyChanged = Signal()
    scrollRequested = Signal(int)
    rangeRejected = Signal()
    renameRejected = Signal(str)
    movePanelChanged = Signal()
    readRequested = Signal(str, str, int)       # series path, book, chapter position
    nextRequested = Signal(str)                 # "translate" | "export"
    openFolderRequested = Signal(str)
    filesDialogRequested = Signal(str)

    def __init__(self, app, lanes, crunch=None, add=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.lanes = lanes
        self.session = BooksSession(lanes.submit, crunch)
        self.series_model = SeriesModel(self)
        self.chapter_model = ChapterModel(self)
        self.add = add
        self.infos: tuple = ()
        self._path = ""
        self._book = ""
        self._view = "empty"
        self._loaded = False
        self._loading_library = False
        self._loading_chapters = False
        self._adding = False
        self._busy_ops = 0
        self._numbers = True
        self._sel = RowSelection(selectable=self._selectable)
        self._memo: dict = {}
        self._typing = False
        self._typing_text = ""
        self._typing_count = ""
        self._edit = None                   # (kind, key)
        self._edit_value = ""
        self._edit_bad = ""
        self._notice: dict = {}
        self._undo = None
        self._move_open = False
        self._want_scroll = False
        self._force_open = False
        self._then = None
        self.scan_hold_ms = 0                # a test hook: the skeleton is taken late (the loading state is then visible)
        self.blocking_terms = 0              # terms that block the selected chapters (the Terms step feeds it, step 6)
        self._scrolled = False
        self._last_visible = (-1, -1)
        self._lib_line = False
        self._lib_timer = QTimer(self)
        self._lib_timer.setSingleShot(True)
        self._lib_timer.setInterval(LOADING_MS)
        self._lib_timer.timeout.connect(self._show_library_line)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(LOADING_MS)
        self._load_timer.timeout.connect(self._show_skeleton)
        self.session.changed.add(self._on_session)
        self.session.failed.add(self._on_failed)
        app.libraryChanged.connect(self._library_changed)
        app.addBooksRequested.connect(self.addFiles)
        app.runChanged.connect(self.seriesChanged)
        app.rescan = self.rescan
        if add is not None:
            add.attach(self)
        self._library_changed()

    # ------------------------------------------------------------- the library
    @property
    def library(self) -> str:
        return self.app.libraryPath if self.app.libraryState == "ready" else ""

    def _library_changed(self) -> None:
        if self.library:
            self.reload()
        else:
            self._loaded = False
            self.infos = ()
            self._path = self._book = ""
            self._rebuild()

    @Slot()
    def reload(self, then=None) -> None:
        """Read the library again on the data lane (`then(infos)` runs when it has arrived)."""
        if not self.library:
            return
        self._loading_library = True
        self._lib_timer.start()
        self._then = then
        self.session.load_library(self.library)

    def rescan(self) -> None:
        """The window got the focus (14.7): a cheap listing, the selection stays where it still exists."""
        if self.library and not self._busy_ops:
            self.reload()

    def _on_session(self, kind, payload) -> None:
        if kind == "series":
            self._loading_library = False
            self._lib_timer.stop()
            self._lib_line = False
            self._loaded = True
            self.infos = tuple(payload)
            self._after_series()
            then, self._then = getattr(self, "_then", None), None
            if then is not None:
                then(self.infos)
            self.busyChanged.emit()
        elif kind == "skeleton":
            if self.scan_hold_ms:
                QTimer.singleShot(self.scan_hold_ms, self._on_skeleton)
                self.scan_hold_ms = 0
            else:
                self._on_skeleton()
        elif kind == "rows":
            self.chapter_model.update(payload, self.session.infos)
            self._renumber_soon()
        elif kind == "scanned":
            self._on_scanned()

    def _show_library_line(self) -> None:
        self._lib_line = self._loading_library
        self.busyChanged.emit()

    def _on_failed(self, kind, exc) -> None:
        self._loading_library = False
        self._lib_line = False
        self._loading_chapters = False
        self.chapterChanged_all()
        self.app.message = "The %s could not be read: %s." % ("library" if kind == "library" else "book", exc)

    def chapterChanged_all(self) -> None:
        self.viewChanged.emit()
        self.chaptersChanged.emit()
        self.busyChanged.emit()

    # ------------------------------------------------------------- what is selected
    def info(self, path: str = ""):
        path = path or self._path
        for i in self.infos:
            if i.path == path:
                return i
        return None

    def _after_series(self) -> None:
        info = self.info()
        force, self._force_open = self._force_open, False
        if info is None:
            path, book = self._saved() if not self._path else ("", "")
            info = self.info(path) or (self.infos[0] if self.infos else None)
            self._path = info.path if info else ""
            self._book = bookrows.pick_book(info, book)
            self._open_current()
        else:
            book = bookrows.pick_book(info, self._book)
            if force or book != self._book:
                self._book = book
                self._open_current()
        self._rebuild()

    def _saved(self) -> tuple:
        last = self.app.win.get_dict(KEY_LAST) if hasattr(self.app.win, "get_dict") else None
        if isinstance(last, dict):
            for i in self.infos:
                if Path(i.path).name == last.get("series"):
                    return i.path, str(last.get("book", ""))
        return "", ""

    def _remember(self) -> None:
        if self._path:
            self.app.win.set(KEY_LAST, {"series": Path(self._path).name, "book": self._book})

    def _compute_view(self) -> str:
        info = self.info()
        if not self._loaded:
            return "loading"
        if not self.infos:
            return "empty"
        if info is None:
            return "empty"
        if info.broken:
            return "broken"
        if not info.books:
            return "nobooks"
        if not fbooks.book_file(info.path, self._book).exists():
            return "missing"
        return "chapters"

    def _rebuild(self) -> None:
        edit = self._edit
        self.series_model.set_rows(bookrows.series_rows(self.infos, self._path, self._book, edit))
        self._view = self._compute_view()
        self.viewChanged.emit()
        self.seriesChanged.emit()
        self.selectionChanged.emit()
        info = self.info()
        self.app.set_context(info.name if info else "", bookrows.book_label(info, self._book) if info and self._book else "")

    @Slot(int)
    def pickRow(self, index: int) -> None:
        """A click on a row of the left list."""
        row = self.series_model.row(index)
        if not row or self._edit is not None:
            return
        self._clear_notice()
        kind, key = row[0], row[1]
        if kind == "series":
            self.selectSeries(key)
        else:
            self.selectBook(self._path, key)

    def selectSeries(self, path: str, book: str = "") -> None:
        info = self.info(path)
        if info is None:
            return
        if path == self._path and not book:
            return
        self._flush_memo()
        self._path = path
        self._book = bookrows.pick_book(info, book or self._memo_book(path))
        self._open_current()
        self._rebuild()

    def selectBook(self, path: str, stem: str) -> None:
        if path == self._path and stem == self._book:
            return
        self._flush_memo()
        self._path, self._book = path, stem
        self._open_current()
        self._rebuild()

    def _memo_book(self, path: str) -> str:
        return self._memo.get(("book", path), "")

    def _flush_memo(self) -> None:
        if self._path and self._book:
            self._memo[(self._path, self._book)] = frozenset(self._sel.ids)
            self._memo[("book", self._path)] = self._book

    def _open_current(self) -> None:
        """Start reading the chapters of the selected book (the previous scan is superseded)."""
        self._typing = False
        self._scrolled = False
        self._want_scroll = True
        self._sel = RowSelection(selectable=self._selectable)
        self.chapter_model.reset([])
        self._remember()
        view = self._compute_view()
        if view != "chapters":
            self._loading_chapters = False
            self._load_timer.stop()
            return
        self._loading_chapters = False
        self._load_timer.start()
        self.session.open_book(self._path, self._book)

    def refresh_book(self) -> None:
        """Read the open book's chapter states again (a job or a resolved block changed the logs): the selection stays
        (it is restored from the memo when the skeleton arrives)."""
        if self._view == "chapters" and self._path and self._book:
            self._push_selection()
            self.session.open_book(self._path, self._book)

    def _show_skeleton(self) -> None:
        if self.chapter_model.rowCount() == 0 and self._view == "chapters":
            self._loading_chapters = True
            self.chaptersChanged.emit()

    def _selectable(self, i) -> bool:
        infos = self.session.infos
        return 0 <= i < len(infos) and not infos[i].is_toc

    def _on_skeleton(self) -> None:
        self._load_timer.stop()
        self._loading_chapters = False
        infos = self.session.infos
        self.chapter_model.reset(infos)
        self._sel.set_rows(range(len(infos)))
        saved = self._memo.get((self._path, self._book))
        if saved:
            self._sel.set_selection(saved)
        self._numbers = not bookrows.titles_numbered(infos) if infos else False
        self._push_selection()
        self.chaptersChanged.emit()
        self._try_scroll(initial=True)

    def _on_scanned(self) -> None:
        self._numbers = not bookrows.titles_numbered(self.session.infos)
        self._push_selection()
        self.chaptersChanged.emit()
        self._try_scroll(initial=False)

    def _renumber_soon(self) -> None:
        self.chaptersChanged.emit()

    def _try_scroll(self, initial: bool) -> None:
        if not self._want_scroll or self._scrolled:
            return
        infos = self.session.infos
        i = bookrows.first_open(infos)
        if infos and (infos[i].blocks is not None or not initial):
            self._want_scroll = False
            self.scrollRequested.emit(i)

    @Slot(int, int)
    def visibleRows(self, first: int, last: int) -> None:
        """The rows the list shows now: the scan serves them first (and the user has scrolled by himself)."""
        if (first, last) != self._last_visible:
            if self._last_visible != (-1, -1) and first > 0:
                self._scrolled = True
            self._last_visible = (first, last)
            self.session.set_visible(first, last)

    # ------------------------------------------------------------- properties of the screen
    @Property(str, notify=viewChanged)
    def view(self):
        return self._view

    @Property(bool, notify=busyChanged)
    def libraryLoading(self):
        """The thin moving line under the header: the library takes longer than 0.3 s to read (10.1)."""
        return self._lib_line

    @Property(bool, notify=chaptersChanged)
    def chaptersLoading(self):
        return self._loading_chapters

    @Property(bool, notify=busyChanged)
    def adding(self):
        return self._adding

    def set_adding(self, on: bool) -> None:
        if on != self._adding:
            self._adding = on
            self.busyChanged.emit()

    @Property(QObject, constant=True)
    def seriesList(self):
        return self.series_model

    @Property(QObject, constant=True)
    def chapters(self):
        return self.chapter_model

    @Property(QObject, constant=True)
    def addPanel(self):
        return self.add

    @Property(str, notify=viewChanged)
    def reason(self):
        info = self.info()
        if self._view == "broken" and info is not None:
            return info.broken
        if self._view == "missing":
            return "file not found"
        return ""

    @Property(str, notify=viewChanged)
    def missingName(self):
        return self._book + ".epub" if self._view == "missing" else ""

    @Property(bool, notify=chaptersChanged)
    def showNumbers(self):
        return self._numbers

    @Property(str, notify=viewChanged)
    def currentSeries(self):
        info = self.info()
        return info.name if info else ""

    @Property(str, notify=viewChanged)
    def currentBook(self):
        info = self.info()
        return bookrows.book_label(info, self._book) if info and self._book else ""

    @Property(int, notify=chaptersChanged)
    def chapterCount(self):
        return len(self.session.infos)

    @Property("QVariantMap", constant=True)
    def tips(self):
        t = tips
        return {"plus": t.ADD_BOOK_PLUS, "adding": t.ADDING, "head": t.CHAPTERS_HEAD, "series": t.SERIES_ACTIONS,
                "book": t.VOLUME_ACTIONS, "state": t.CHAPTER_STATE, "range": t.CHAPTERS_FIELD,
                "next": t.NEXT_STEP, "moveOff": t.MOVE_OFF, "updateOff": t.UPDATE_FILE_OFF,
                "readOff": t.READ_OFF, "name": t.RENAME_TAKEN}

    # ------------------------------------------------------------- selection
    def _push_selection(self) -> None:
        cursor = self._sel.cursor_index
        self.chapter_model.set_selection(self._sel.ids, -1 if cursor is None else cursor)
        self.selectionChanged.emit()
        self.typingChanged.emit()
        if self._path and self._book:
            self._memo[(self._path, self._book)] = frozenset(self._sel.ids)

    @Property(int, notify=selectionChanged)
    def cursor(self):
        c = self._sel.cursor_index
        return -1 if c is None else c

    @Property(int, notify=selectionChanged)
    def selectedCount(self):
        return len(self._sel.ids)

    @Property(str, notify=selectionChanged)
    def headState(self):
        n, total = len(self._sel.ids), sum(1 for i in range(len(self.session.infos)) if self._selectable(i))
        return "none" if n == 0 else ("all" if n >= total else "some")

    @Property(bool, notify=typingChanged)
    def capsuleVisible(self):
        return bool(self._sel.ids) or self._typing

    @Property(str, notify=typingChanged)
    def capsuleCount(self):
        if self._typing:
            return self._typing_count
        return bookrows.count_text(len(self._sel.ids))

    @Property(str, notify=typingChanged)
    def capsuleRange(self):
        return bookrows.range_text(self.session.infos, self._sel.ids) if self._sel.ids else ""

    def _next(self) -> tuple:
        return bookrows.next_step(self.session.infos, sorted(self._sel.ids), self.blocking_terms)

    @Property(str, notify=typingChanged)
    def nextText(self):
        return self._next()[1]

    @Property(str, notify=typingChanged)
    def nextKind(self):
        return self._next()[0]

    def terms_context(self) -> tuple:
        """What the Terms screen needs of Books: (series path, book stem, selected chapter positions, their range text, the
        chapter numbers by position). The selection is read here, never copied around."""
        ids = tuple(sorted(self._sel.ids))
        rng = bookrows.range_text(self.session.infos, ids) if ids else ""
        return self._path, self._book, ids, rng, bookrows.shown_numbers(self.session.infos)

    def set_blocking(self, n: int) -> None:
        """Terms that block the selected chapters (step 6 will feed this from the term base)."""
        self.blocking_terms = int(n)
        self.typingChanged.emit()

    @Property(bool, notify=typingChanged)
    def typing(self):
        return self._typing

    @Property(str, notify=typingChanged)
    def typingText(self):
        return self._typing_text

    @Slot(int, bool, bool)
    def rowPressed(self, index: int, ctrl: bool, shift: bool) -> None:
        """A click on a box AND on a row both toggle that row; Shift takes the range (4.7)."""
        self._clear_notice()
        if self._sel.click(index, ctrl=not shift, shift=shift):
            self._push_selection()

    @Slot(int)
    def rowDragged(self, index: int) -> None:
        if self._sel.drag(index):
            self._push_selection()

    @Slot(int)
    def rowContext(self, index: int) -> None:
        if self._sel.context(index):
            self._push_selection()

    @Slot(int, bool)
    def moveCursor(self, delta: int, extend: bool) -> None:
        self._sel.move(delta, extend)
        self._push_selection()

    @Slot(str, bool)
    def moveTo(self, where: str, extend: bool) -> None:
        (self._sel.home if where == "home" else self._sel.end)(extend)
        self._push_selection()

    @Slot()
    def selectAll(self) -> None:
        self._sel.select_all()
        self._push_selection()

    @Slot()
    def toggleCurrent(self) -> None:
        if self._sel.toggle_cursor():
            self._push_selection()

    @Slot()
    def headBox(self) -> None:
        """The head box: none -> all, some or all -> none."""
        if self._sel.ids:
            self._sel.ids = set()
        else:
            self._sel.select_all()
        self._push_selection()

    @Slot("QVariantList")
    def selectPositions(self, positions) -> None:
        """These chapters become the selection (Export's `Translate ›`, 8.7); the list scrolls to the first one."""
        ids = sorted({int(p) for p in positions if self._selectable(int(p))})
        self._sel.set_selection(ids)
        self._push_selection()
        if ids:
            self.scrollRequested.emit(ids[0])

    @Slot()
    def clearSelection(self) -> None:
        self._sel.clear()
        self._push_selection()

    @Slot()
    def goNext(self) -> None:
        kind = self.nextKind
        self.nextRequested.emit(kind)
        self.app.go({"export": "export", "review": "terms"}.get(kind, "translate"))

    # ------------------------------------------------------------- typing a range (4.5, 4.7)
    @Slot(str)
    def beginTyping(self, text: str) -> None:
        self._typing = True
        self._typing_text = text or bookrows.range_text(self.session.infos, self._sel.ids)
        self._typing_count = ""
        self.typingEdited(self._typing_text)

    @Slot(str)
    def typingEdited(self, text: str) -> None:
        res = self._parse(text)
        self._typing_text = text
        self._typing_count = bookrows.count_text(len(res.indices)) if not res.error else "0 chapters"
        self.typingChanged.emit()

    def _parse(self, text: str):
        infos = self.session.infos
        return cl.select_by_numbers(text, bookrows.numbers_of(infos), [bool(i.is_toc) for i in infos])

    @Slot(str, result=bool)
    def commitRange(self, text: str) -> bool:
        """Enter in the range field: takes it, or the field flashes (a wrong value stays open for correction)."""
        if not text.strip():
            self.cancelTyping()
            return True
        res = self._parse(text)
        if res.error:
            self.rangeRejected.emit()
            return False
        self._sel.set_selection(res.indices)
        self._typing = False
        self._push_selection()
        if res.indices:
            self.scrollRequested.emit(res.indices[0])
        return True

    @Slot()
    def cancelTyping(self) -> None:
        self._typing = False
        self.typingChanged.emit()

    @Slot(int)
    def activate(self, index: int) -> None:
        """Enter / double-click on a chapter row: read it when it has a translation."""
        info = self.session.infos[index] if 0 <= index < len(self.session.infos) else None
        if info is not None and info.done > 0:
            self.readChapter(index)

    @Slot(int)
    def readChapter(self, index: int) -> None:
        self.readRequested.emit(self._path, self._book, index)
        self.app.go("translate")

    @Slot(int, str)
    def chapterPicked(self, index: int, item_id: str) -> None:
        if item_id == "read":
            self.readChapter(index)

    @Slot()
    def chooseFiles(self) -> None:
        """`Add book` / `+`: the file chooser (several .epub files) is the window's; its answer comes to `dropped`."""
        self._clear_notice()
        self.filesDialogRequested.emit(str(Path(self._path).parent) if self._path else self.library)

    @Slot(int, result="QVariantList")
    def chapterMenu(self, index: int) -> list:
        info = self.session.infos[index] if 0 <= index < len(self.session.infos) else None
        ok = info is not None and info.done > 0
        return [{"text": "Read", "id": "read", "kind": "" if ok else "off"}]

    # ------------------------------------------------------------- menus (4.2, 4.3)
    def _busy_with(self, info, stem: str = "") -> bool:
        run = self.app.run
        if not run.busy or run.series != info.name:
            return False
        return not stem or run.book in ("", stem, bookrows.book_label(info, stem))

    def _book_items(self, info, stem: str) -> list:
        label = bookrows.book_label(info, stem)
        translated = ops.has_translation(info.path, stem)
        busy = self._busy_with(info, stem)
        many = len(info.books) > 1
        return [{"text": "Rename %s" % label, "id": "rename:" + stem},
                {"text": "Remove %s" % label, "id": "remove:" + stem, "kind": "off" if busy else "",
                 "tip": tips.CANNOT_NOW % "A job of this book is running." if busy else ""},
                {"text": "Move %s to series…" % label, "id": "move:" + stem,
                 "kind": "off" if translated or busy or len(self.infos) < 2 else "", "many": many,
                 "tip": tips.MOVE_OFF if translated else ""},
                {"text": "Update file…", "id": "update:" + stem, "kind": "off", "tip": tips.UPDATE_FILE_OFF}]

    @Slot(int, result="QVariantList")
    def menuFor(self, index: int) -> list:
        row = self.series_model.row(index)
        if not row:
            return []
        info = self.info(row[1]) if row[0] == "series" else self.info()
        if info is None:
            return []
        if row[0] == "book":
            return self._book_items(info, row[1])
        busy = self._busy_with(info)
        items = [{"text": "Open folder", "id": "open:" + info.path}]
        if not info.broken:
            items.insert(0, {"text": "Rename series", "id": "rename:" + info.path})
        items.append({"text": "Delete series", "id": "delete:" + info.path, "kind": "off" if busy else "",
                      "tip": tips.CANNOT_NOW % "A job of this series is running." if busy else ""})
        if not info.broken and len(info.books) == 1:
            items.append({"kind": "divider", "text": ""})
            items.extend(self._book_items(info, info.books[0]))
        return items

    @Slot(int, str)
    def menuPicked(self, index: int, item_id: str) -> None:
        row = self.series_model.row(index)
        if not row:
            return
        kind, _, key = item_id.partition(":")
        self._clear_notice()
        series_row = row[0] == "series"
        if kind == "rename":
            self.startRename("series" if series_row and key == row[1] else "book", key)
        elif kind == "open":
            self.openFolderRequested.emit(key)
            QDesktopServices.openUrl(QUrl.fromLocalFile(key))
        elif kind == "delete":
            self.deleteSeries(key)
        elif kind == "remove":
            self.removeBook(self.info(row[1]).path if series_row else self._path, key)
        elif kind == "move":
            self.openMove(key)

    # ------------------------------------------------------------- rename in place (9.12)
    @Property(str, notify=editChanged)
    def editKind(self):
        return self._edit[0] if self._edit else ""

    @Property(str, notify=editChanged)
    def editKey(self):
        return self._edit[1] if self._edit else ""

    @Property(str, notify=editChanged)
    def editValue(self):
        return self._edit_value

    @Slot(str, str)
    def startRename(self, kind: str, key: str) -> None:
        info = self.info(key) if kind == "series" else self.info()
        if info is None:
            return
        self._edit = (kind, key)
        self._edit_value = info.name if kind == "series" else bookrows.book_label(info, key)
        self._edit_bad = ""
        self.editChanged.emit()
        self._rebuild()

    def _end_rename(self) -> None:
        self._edit = None
        self._edit_bad = ""
        self.editChanged.emit()
        self._rebuild()

    @Slot()
    def cancelRename(self) -> None:
        if self._edit is not None:
            self._end_rename()

    def rename_problem(self, text: str) -> str:
        kind, key = self._edit
        text = text.strip()
        if kind == "series":
            return addbook.rename_problem(text, key, [(i.path, i.name) for i in self.infos])
        info = self.info()
        if not text:
            return "Enter a name."
        taken = [bookrows.book_label(info, s).lower() for s in info.books if s != key]
        return "Another book of this series has this name." if text.lower() in taken else ""

    @Slot(str, result=str)
    def renameProblem(self, text: str) -> str:
        return self.rename_problem(text) if self._edit is not None else ""

    @Slot(str, result=bool)
    def commitRename(self, text: str) -> bool:
        """Enter in the row field. A taken name keeps the field open (the caller shakes it); returns True when it ended."""
        if self._edit is None:
            return True
        problem = self.rename_problem(text)
        if problem:
            self._edit_bad = problem
            self.renameRejected.emit(problem)
            return False
        kind, key = self._edit
        info = self.info(key) if kind == "series" else self.info()
        old = info.name if kind == "series" else bookrows.book_label(info, key)
        self._end_rename()
        if text.strip() == old:
            return True
        path = key if kind == "series" else self._path
        self._op(lambda ctx: (ops.rename_series(path, text) if kind == "series" else ops.rename_volume(path, key, text)),
                 lambda _r: self.reload())
        return True

    # ------------------------------------------------------------- disk operations on the data lane
    def _op(self, fn, done, before_release: str = "") -> None:
        """Run `fn(ctx)` on the data lane; open books are closed first when `before_release` names a folder."""
        self._busy_ops += 1

        def go(_n=0):
            self.lanes.submit(fn, on_result=lambda r: self._op_done(done, r), on_error=self._op_failed, lane="data")
        if before_release:
            self.session.close_scan()
            self.lanes.close_lane_books(before_release, on_done=go)
        else:
            go()

    def _op_done(self, done, result) -> None:
        self._busy_ops -= 1
        done(result)

    def _op_failed(self, exc) -> None:
        self._busy_ops = max(0, self._busy_ops - 1)
        self.app.message = str(exc)
        self.app.log.add(str(exc), problem=True)
        self.reload()

    # ------------------------------------------------------------- delete / remove with Undo (4.4)
    def _set_notice(self, fact, verbs=()) -> None:
        self._notice = {"fact": fact, "verbs": list(verbs)}
        self.noticeChanged.emit()

    def _clear_notice(self) -> None:
        if self._notice:
            self._notice = {}
            self._undo = None
            self.noticeChanged.emit()

    @Property("QVariantMap", notify=noticeChanged)
    def notice(self):
        return self._notice

    def notify(self, fact, verbs=()) -> None:
        """A message under the lists (Added, Already in, Moved); gone with the next action."""
        self._undo = None
        self._set_notice(fact, verbs)

    @Slot(str)
    def deleteSeries(self, path: str) -> None:
        info = self.info(path)
        if info is None or self._busy_with(info):
            return
        library, name = self.library, info.name
        idx = bookrows.row_index(self.series_model.rows, "series", path)
        self._op(lambda ctx: ops.delete_series(library, path), lambda dest: self._deleted(name, path, str(dest), idx),
                 before_release=path)

    def _deleted(self, name, path, dest, idx) -> None:
        self._undo = ("series", path, dest, name)
        self._set_notice(_fact(("Deleted ", ""), (name, "n")), [{"text": "Undo", "id": "undo"}])
        if self._path == path:
            self._path = self._book = ""
            self._pick_neighbour(path)
        self.reload()

    def _pick_neighbour(self, gone: str) -> None:
        """The series next to the deleted one (the one below it, else the one above) becomes the selected one."""
        keys = [r[1] for r in self.series_model.rows if r[0] == "series"]
        i = keys.index(gone) if gone in keys else 0
        keys = [k for k in keys if k != gone]
        if keys:
            self._path = keys[min(i, len(keys) - 1)]

    @Slot(str, str)
    def removeBook(self, path: str, stem: str) -> None:
        info = self.info(path)
        if info is None or self._busy_with(info, stem):
            return
        library, label = self.library, bookrows.book_label(info, stem)
        custom = dict(info.labels).get(stem, "")
        job_book = stem
        self._op(lambda ctx: ops.remove_volume(library, path, stem, job_book),
                 lambda dest: self._removed(info.name, label, custom, path, stem, str(dest)), before_release=path)

    def _removed(self, series, label, custom, path, stem, dest) -> None:
        self._undo = ("book", path, dest, series, stem, custom, label)
        self._set_notice(_fact(("Removed ", ""), (series, "n"), (" · %s" % label, "")), [{"text": "Undo", "id": "undo"}])
        if self._path == path and self._book == stem:
            self._book = ""
        self.reload()

    @Slot()
    def undo(self) -> None:
        u, self._undo = self._undo, None
        self._notice = {}
        self.noticeChanged.emit()
        if not u:
            return
        if u[0] == "series":
            _k, path, dest, name = u
            self._op(lambda ctx: ops.restore_series(self.library, path, dest),
                     lambda now: self._restored(str(now), ""), before_release=self.library)
        else:
            _k, path, dest, series, stem, custom, label = u

            def run(ctx):
                stems = ops.restore_volume(path, dest)
                if custom:
                    ops.rename_volume(path, stem, custom)
                return stems
            self._op(run, lambda _s: self._restored(path, stem))

    def _restored(self, path: str, stem: str) -> None:
        self._path, self._book = path, stem
        self._force_open = True
        self.reload()

    # ------------------------------------------------------------- move a book to another series (4.7)
    @Property("QVariantList", notify=movePanelChanged)
    def moveTargets(self):
        return [{"text": i.name, "id": i.path} for i in self.infos if i.path != self._path and not i.broken]

    @Property(str, notify=movePanelChanged)
    def moveTitle(self):
        info = self.info()
        return "Move %s to series" % (bookrows.book_label(info, self._move_stem) if info and self._move_stem else "book")

    _move_stem = ""

    @Property(bool, notify=movePanelChanged)
    def moveOpen(self):
        return self._move_open

    def openMove(self, stem: str) -> None:
        self._move_stem = stem
        self._move_open = True
        self.movePanelChanged.emit()

    @Slot()
    def closeMove(self) -> None:
        self._move_open = False
        self.movePanelChanged.emit()

    @Slot(str)
    def moveBook(self, target: str) -> None:
        info, dst = self.info(), self.info(target)
        stem = self._move_stem
        self.closeMove()
        if info is None or dst is None or not stem:
            return
        src, label = info.path, bookrows.book_label(info, stem)
        self._op(lambda ctx: ops.move_volume(src, stem, target),
                 lambda new: self._moved(label, dst.name, target, new), before_release=src)

    def _moved(self, label, dst_name, target, new) -> None:
        self.notify(_fact(("Moved ", ""), (label, "n"), (" to ", ""), (dst_name, "n")))
        self._path, self._book = target, new
        self._force_open = True
        self.reload()

    # ------------------------------------------------------------- Add book (hand-off to the Add panel)
    @Slot(list)
    def addFiles(self, paths) -> None:
        if self.add is not None and self.library:
            self._clear_notice()
            self.add.open_files([str(p) for p in paths])

    @Slot("QVariant")
    def dropped(self, urls) -> None:
        """Files dropped on the window (any screen): the .epub ones open the Add panel."""
        paths = []
        for u in urls:
            p = QUrl(u).toLocalFile() if not isinstance(u, QUrl) else u.toLocalFile()
            if p and p.lower().endswith(".epub"):
                paths.append(os.path.normpath(p))
        if paths:
            self.addFiles(paths)

    @Slot("QVariant", result=int)
    def epubCount(self, urls) -> int:
        """How many of the dragged files are books (the dashed frame says `Add 3 books`)."""
        n = 0
        for u in urls:
            p = u.toLocalFile() if isinstance(u, QUrl) else QUrl(u).toLocalFile()
            n += 1 if p.lower().endswith(".epub") else 0
        return n

    def select_added(self, series: str, volume: str, dup_note=None) -> None:
        """After an Add (or an already-there file): that series and book are selected."""
        self._path, self._book = series, volume
        self._force_open = True
        self.reload()

    @Slot(str)
    def openFolder(self, path: str) -> None:
        self.openFolderRequested.emit(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot()
    def openCurrentFolder(self) -> None:
        if self._path:
            self.openFolder(self._path)

    @Slot()
    def openBooksFolder(self) -> None:
        if self._path:
            self.openFolder(str(Path(self._path) / "books"))

    def current_selection_ranges(self) -> list:
        return ranges(self._sel.ids)
