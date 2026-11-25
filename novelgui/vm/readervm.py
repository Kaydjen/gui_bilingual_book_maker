"""The Reader tab (window_spec 14.2): one chapter as block pairs, the source dim on the left, the translation on the right.

Read-only until core C15 (hand edits as versions): the version chooser shows the one version that exists. The chapter is
read on the read lane (book blocks + the chapter log); the model holds one chapter's blocks (a few hundred rows).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, Qt, Signal, Slot

from .. import chapterlogic as cl
from .. import tips
from ..facade import books as fbooks

ROLES = ("source", "target", "mark", "block")


def pairs_task(ctx, series_path, book: str, index: int) -> dict:
    """{title, number, pairs: [(block index, source, translation, mark)]} of one chapter."""
    bk = fbooks.open_book(fbooks.book_file(series_path, book))
    ch = bk.chapters[index]
    blocks = bk.blocks(ch)
    lpath = fbooks.log_file(series_path, book, index, ch.href)
    last: dict = {}
    if lpath.exists():
        for r in fbooks.read_jsonl(lpath):
            last[(r.get("i"), cl.short_sha(r.get("src_sha")))] = r
    pairs = []
    for b in blocks:
        rec = last.get((b.index, cl.short_sha(b.sha)))
        target, mark = "", ""
        if rec is not None:
            if rec.get("status") == "ok":
                target = str(rec.get("text") or "")
                mark = ", ".join(str(f) for f in rec.get("flags") or [])
            else:
                mark = "failed"
        pairs.append((b.index, fbooks.strip_markers(b.text), target, mark))
        ctx.breathe()
    title = ch.title or ""
    return {"title": title, "number": cl.title_number(title) or cl.display_no(index), "pairs": pairs}


class ReaderModel(QAbstractListModel):
    ROLE_IDS = {Qt.ItemDataRole.UserRole + 1 + i: n.encode() for i, n in enumerate(ROLES)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def roleNames(self):
        return self.ROLE_IDS

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r, k = index.row(), role - Qt.ItemDataRole.UserRole - 1
        if 0 <= r < len(self.rows) and 0 <= k < 4:
            row = self.rows[r]
            return (row[1], row[2], row[3], row[0])[k]
        return None

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()


class ReaderVM(QObject):
    changed = Signal()

    def __init__(self, lanes, parent=None):
        super().__init__(parent)
        self.lanes = lanes
        self.model = ReaderModel(self)
        self._open = False
        self._loading = False
        self._title = ""
        self._number = 0
        self._error = ""
        self._where = ""

    @Property("QVariantMap", constant=True)
    def tips(self):
        return {"close": tips.READER_CLOSE, "version": tips.READER_VERSION, "edit": tips.READER_EDIT}

    @Property(QObject, constant=True)
    def blocks(self):
        return self.model

    @Property(bool, notify=changed)
    def isOpen(self):
        return self._open

    @Property(bool, notify=changed)
    def loading(self):
        return self._loading

    @Property(str, notify=changed)
    def tabText(self):
        return "Reader · %d" % self._number if self._number else "Reader"

    @Property(str, notify=changed)
    def title(self):
        return self._title

    @Property(str, notify=changed)
    def where(self):
        return self._where

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Property(str, constant=True)
    def version(self):
        return "r1"

    @Slot(str, str, int)
    def openChapter(self, series_path: str, book: str, index: int) -> None:
        self._open, self._loading, self._error = True, True, ""
        self._number = index + 1
        self._where = "%s · %s" % (Path(series_path).name, book)
        self.model.set_rows([])
        self.changed.emit()
        self.lanes.submit(lambda ctx: pairs_task(ctx, series_path, book, index), on_result=self._done,
                          on_error=self._failed, lane="read", group="reader")

    def _done(self, res) -> None:
        self._loading = False
        self._title, self._number = res["title"], res["number"]
        self.model.set_rows(res["pairs"])
        self.changed.emit()

    def _failed(self, exc) -> None:
        self._loading = False
        self._error = "This chapter cannot be read: %s." % exc
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        if self._open:
            self._open = False
            self.model.set_rows([])
            self.changed.emit()
