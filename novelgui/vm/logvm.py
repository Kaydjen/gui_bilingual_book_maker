"""The view-model of the log window (window_spec 14.4): the lines of window.log, filter `Everything | Problems`,
`Copy` (to the clipboard), `Open folder`. Keys are scrubbed when a line is written and again when text is copied."""

from __future__ import annotations

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .. import platform, tips
from ..ctl import winlog

REFRESH_MS = 150


class LogModel(QAbstractListModel):
    WHEN, SERIES, TEXT, PROBLEM = (Qt.ItemDataRole.UserRole + i for i in range(1, 5))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []

    def roleNames(self):
        return {self.WHEN: b"when", self.SERIES: b"series", self.TEXT: b"text", self.PROBLEM: b"problem"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        e = self.rows[index.row()]
        return {self.WHEN: e.when[11:19] or e.when, self.SERIES: e.series, self.TEXT: e.text, self.PROBLEM: e.problem,
                Qt.ItemDataRole.DisplayRole: e.line()}.get(role)

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()


class LogVM(QObject):
    filterChanged = Signal()
    copied = Signal()

    def __init__(self, log: winlog.WindowLog, keys=None, clipboard=None, parent=None):
        super().__init__(parent)
        self.log = log
        self._keys = keys or (lambda: [])
        self._clipboard = clipboard
        self.model = LogModel(self)
        self._problems = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.reload)
        log.listeners.append(self._later)

    def _later(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    @Property("QVariantMap", constant=True)
    def tips(self):
        return {"copy": tips.LOG_COPY}

    @Property(QObject, constant=True)
    def lines(self):
        return self.model

    @Property(int, notify=filterChanged)
    def filter(self):
        return 1 if self._problems else 0

    @Slot(int)
    def setFilter(self, index):
        problems = index == 1
        if problems != self._problems:
            self._problems = problems
            self.filterChanged.emit()
            self.reload()

    @Slot()
    def reload(self):
        self.model.set_rows(self.log.entries(self._problems))

    def text(self) -> str:
        return winlog.scrub("\n".join(e.line() for e in self.model.rows), self._keys())

    @Slot()
    def copy(self):
        cb = self._clipboard or QGuiApplication.clipboard()
        cb.setText(self.text())
        self.copied.emit()

    @Slot(str, "QVariantMap")
    def copyDetails(self, version, info):
        """`Copy details` of a failed job (7.16 bar, later): the job, the last log lines, the version."""
        tail = [e.line() for e in self.log.entries(False, 30)]
        cb = self._clipboard or QGuiApplication.clipboard()
        cb.setText(winlog.details_text(version, dict(info), tail, self._keys()))
        self.copied.emit()

    @Slot()
    def openFolder(self):
        platform.open_folder(self.log.path.parent)
