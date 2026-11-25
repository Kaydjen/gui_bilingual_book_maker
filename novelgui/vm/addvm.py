"""The Add book panel (window_spec 5.1-5.4, 9.11, 13.5, 14.7): ONE panel for one or many files.

`open_files(paths)` checks the files off the GUI thread (readable, protected, already in the library), then opens the panel
with one row per file: File | Series | the label the file will get. `accept()` copies the files in on the data lane
(`<name>.part`, renamed to .epub last). The rules are in ctl/addplan.py.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, Qt, Signal, Slot

from ..ctl import addplan, bookrows

ROLES = ("file", "series", "isNew", "label", "note", "status")
MAX_ROWS = 6


class AddModel(QAbstractListModel):
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
        if not (0 <= r < len(self.rows) and 0 <= k < len(ROLES)):
            return None
        row = self.rows[r]
        if k == 3:
            return row.label if row.addable else ""
        return (row.name, row.series, row.new, row.label, row.note, row.state)[k]

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def replace(self, rows) -> None:
        """Same files, new labels / series: one dataChanged."""
        self.rows = list(rows)
        if rows:
            self.dataChanged.emit(self.index(0), self.index(len(rows) - 1))


class AddVM(QObject):
    openChanged = Signal()
    rowsChanged = Signal()
    checkingChanged = Signal()

    def __init__(self, app, lanes, parent=None):
        super().__init__(parent)
        self.app = app
        self.lanes = lanes
        self.books = None
        self.model = AddModel(self)
        self._open = False
        self._checking = False
        self._shown = 1
        self._skipped: list = []
        self._token = None

    def attach(self, books) -> None:
        self.books = books

    @Property(QObject, constant=True)
    def rows(self):
        return self.model

    @Property(bool, notify=openChanged)
    def isOpen(self):
        return self._open

    @Property(bool, notify=checkingChanged)
    def checking(self):
        return self._checking

    @Property(int, notify=openChanged)
    def rowsShown(self):
        return self._shown

    @Property(str, notify=rowsChanged)
    def title(self):
        return addplan.title_for(len(self.model.rows))

    @Property(str, notify=rowsChanged)
    def actionText(self):
        return addplan.action_text(self.model.rows)

    @Property(bool, notify=rowsChanged)
    def canAdd(self):
        return any(r.addable and r.series.strip() for r in self.model.rows)

    # ------------------------------------------------------------- opening
    def open_files(self, paths) -> None:
        paths = [p for p in paths if str(p).lower().endswith(".epub")]
        if not paths or self.books is None or self._open:
            return
        self._checking = True
        self.checkingChanged.emit()
        library = self.books.library
        self.lanes.submit(lambda ctx: addplan.prepare_task(ctx, library, paths), on_result=self._checked,
                          on_error=self._check_failed, lane="data")

    def _check_failed(self, exc) -> None:
        self._checking = False
        self.checkingChanged.emit()
        self.app.message = "The files could not be checked: %s." % exc

    def _checked(self, files) -> None:
        self._checking = False
        self.checkingChanged.emit()
        infos = self.books.infos
        fresh = [f for f in files if not f["dup"]]
        dups = [f for f in files if f["dup"]]
        if dups:
            self._already_there(dups[0], infos)
        if not fresh:
            return
        if len(files) == 1 and fresh[0]["state"] == "unreadable":
            self.app.message = "%s cannot be added: %s. Nothing was created." % (Path(fresh[0]["path"]).name,
                                                                                 fresh[0]["note"])
            return
        rows = addplan.make_rows(fresh, infos)
        self.model.set_rows(rows)
        self._shown = max(1, min(len(rows), MAX_ROWS))
        self._skipped = []
        self._open = True
        self.app.show_panel("add")
        self.openChanged.emit()
        self.rowsChanged.emit()

    def _already_there(self, f, infos) -> None:
        series_path, stem = f["dup"]
        info = next((i for i in infos if i.path == series_path), None)
        if info is None:
            return
        label = bookrows.book_label(info, stem)
        self.books.notify([{"text": "Already in ", "kind": ""}, {"text": info.name, "kind": "n"},
                           {"text": " · %s" % label, "kind": ""}])
        self.books.select_added(series_path, stem)

    # ------------------------------------------------------------- the rows
    def _relabel(self, rows) -> None:
        self.model.replace(addplan.assign_labels(rows, self.books.infos))
        self.rowsChanged.emit()

    @Slot(int, str)
    def setSeries(self, index: int, name: str) -> None:
        rows = list(self.model.rows)
        if 0 <= index < len(rows):
            from dataclasses import replace
            rows[index] = replace(rows[index], series=name.strip())
            self._relabel(rows)

    @Slot(int)
    def leaveOut(self, index: int) -> None:
        rows = list(self.model.rows)
        if 0 <= index < len(rows) and len(rows) > 1:
            del rows[index]
            self.model.set_rows(addplan.assign_labels(rows, self.books.infos))
            self.rowsChanged.emit()

    @Slot(int, str, result="QVariantList")
    def entries(self, index: int, typed: str) -> list:
        row = self.model.rows[index] if 0 <= index < len(self.model.rows) else None
        return addplan.series_entries(self.books.infos, typed, row.series if row is not None and row.new else "")

    @Slot(int, result=str)
    def seriesTip(self, index: int) -> str:
        from .. import tips
        row = self.model.rows[index] if 0 <= index < len(self.model.rows) else None
        if row is None or not row.addable:
            return ""
        return tips.ADD_NEW_SERIES if row.new else tips.ADD_VOLUME_OF

    # ------------------------------------------------------------- closing and adding
    @Slot()
    def close(self) -> None:
        if self._open:
            self._open = False
            self.app.closePanel()
            self.openChanged.emit()

    @Slot()
    def accept(self) -> None:
        if not self.canAdd:
            return
        rows = self.model.rows
        items = [{"path": r.path, "series": r.series, "new": r.new} for r in rows if r.addable and r.series.strip()]
        skipped = [r.name for r in rows if r.state == "protected"]
        library = self.books.library
        self.close()
        self.books.set_adding(True)
        self.lanes.submit(lambda ctx: addplan.add_task(ctx, library, items),
                          on_result=lambda res: self._added(res, skipped), on_error=self._add_failed, lane="data")

    def _add_failed(self, exc) -> None:
        self.books.set_adding(False)
        self.app.message = "The books could not be added: %s." % exc
        self.books.reload()

    def _added(self, results, skipped) -> None:
        self.books.set_adding(False)
        errors = [r["error"] for r in results if r["error"]]
        done = [r for r in results if r["ok"]]
        text = addplan.summary(results, skipped)
        if errors:
            self.app.message = " ".join(errors[:2]) + (" The other books were added." if done else "")
        if text:
            self.books.notify([{"text": text, "kind": ""}])
        if done:
            last = done[-1]
            self.books.select_added(last["series"], last["volume"])
        else:
            self.books.reload()
