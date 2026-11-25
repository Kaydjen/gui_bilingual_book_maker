"""The view-model of the settings panel (window_spec 11, 11.7): keys with states, models, pace, keep awake, library
row, app data row, graphics. Every change saves at once; the foot says so (`Saved`, `Saved · applies from the next
start`, `2 keys added · checking…`). Disk and network work runs on a lane; the answer comes back through the pump.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, Qt, QTimer, Signal, Slot

from .. import keystates, keystore, platform, tips
from ..ctl import keycheck
from ..ctl import settingsrules as sr
from ..runtime import markers, paths

SAVED_MS = 3000


class KeyModel(QAbstractListModel):
    MASKED, WORD, RED, TIP, GLOW = (Qt.ItemDataRole.UserRole + i for i in range(1, 6))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []            # (masked, word, red, tip, glow)

    def roleNames(self):
        return {self.MASKED: b"masked", self.WORD: b"word", self.RED: b"red", self.TIP: b"tip", self.GLOW: b"glow"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        r = self.rows[index.row()]
        if role in (self.MASKED, Qt.ItemDataRole.DisplayRole):
            return r[0]
        return {self.WORD: r[1], self.RED: r[2], self.TIP: r[3], self.GLOW: r[4]}.get(role)

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()


class ModelModel(QAbstractListModel):
    NAME, WORD, RED, UP, DOWN, TIP, GLOW = (Qt.ItemDataRole.UserRole + i for i in range(1, 8))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []            # (name, word, red, can_up, can_down, tip, glow)

    def roleNames(self):
        return {self.NAME: b"name", self.WORD: b"word", self.RED: b"red", self.UP: b"canUp", self.DOWN: b"canDown",
                self.TIP: b"tip", self.GLOW: b"glow"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        r = self.rows[index.row()]
        if role in (self.NAME, Qt.ItemDataRole.DisplayRole):
            return r[0]
        return {self.WORD: r[1], self.RED: r[2], self.UP: r[3], self.DOWN: r[4], self.TIP: r[5], self.GLOW: r[6]}.get(role)

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()


class SettingsVM(QObject):
    savedChanged = Signal()
    paceChanged = Signal()
    awakeChanged = Signal()
    libraryChanged = Signal()
    appDataChanged = Signal()
    graphicsChanged = Signal()
    googleChanged = Signal()
    glow = Signal(str)

    def __init__(self, app, keystore_, lanes, local_dir=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.settings = app.settings
        self.keystore = keystore_
        self.lanes = lanes
        self.local = local_dir or paths.local_dir()
        self.key_model = KeyModel(self)
        self.model_model = ModelModel(self)
        self._models = sr.stored_models(self.settings.get("models"))
        self._states: dict = {}                 # key -> keystates.KeyState (pool files)
        self._missing: set = set()
        self._checked: dict = {}                # key -> state word of the check on add
        self._pending = 0
        self._google: list = []
        self._saved = ""
        self._pace = self._read_pace()
        self._data_text = ""
        self._cache = keycheck.ModelCache(self.local)
        self._glow_new = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVED_MS)
        self._timer.timeout.connect(self._clear_saved)
        app.libraryChanged.connect(self.libraryChanged)
        app.runChanged.connect(self.libraryChanged)
        self.rebuild()

    @Property(QObject, constant=True)
    def keys(self):
        return self.key_model

    @Property(QObject, constant=True)
    def modelRows(self):
        return self.model_model

    # ------------------------------------------------------------- rows
    def rebuild(self) -> None:
        self.key_model.set_rows(self._key_rows())
        self.model_model.set_rows(self._model_rows())

    def _key_rows(self) -> list:
        rows = []
        for k in self.keystore.keys:
            checked = self._checked.get(k, "")
            if checked and checked != keycheck.READY:
                word, red, tip = checked, checked == keycheck.INVALID, keycheck.TIPS.get(checked, "")
            else:
                st = self._states.get(k)
                word = keystates.text(st) if st else ""
                word = "" if word == "ready" else word
                red = bool(st and st.kind == keystates.INVALID)
                tip = tips.KEY_INVALID if red else ""
            rows.append((keystore.mask(k), word, red, tip, False))
        return rows

    def _model_rows(self) -> list:
        n = len(self._models)
        rows = []
        for i, m in enumerate(self._models):
            nf = m in self._missing
            rows.append((m, "not found" if nf else "", False, i > 0, i < n - 1, tips.MODEL_NOT_FOUND if nf else "", False))
        return rows

    # ------------------------------------------------------------- saved line
    @Property(str, notify=savedChanged)
    def saved(self):
        return self._saved

    def _say(self, text: str, row: str = "") -> None:
        self._saved = text
        self.savedChanged.emit()
        self._timer.start()
        if row:
            self.glow.emit(row)

    def _clear_saved(self) -> None:
        if self._pending:
            return
        self._saved = ""
        self.savedChanged.emit()

    def _ok(self, row: str) -> None:
        self._say(sr.saved_line(self.app.run.busy), row)

    @Property(bool, notify=libraryChanged)
    def running(self):
        return self.app.run.busy

    # ------------------------------------------------------------- keys
    @Slot(str, result=int)
    def addKeys(self, text):
        before = list(self.keystore.keys)
        n = self.keystore.add(text)
        if not n:
            return 0
        new = [k for k in self.keystore.keys if k not in before]
        self.app.log.add("%d %s added" % (n, "key" if n == 1 else "keys"))
        self._checked.update({k: "" for k in new})
        self.rebuild()
        self._pending += len(new)
        self._say(sr.keys_added_line(n), "keys")
        for k in new:
            self.lanes.submit(lambda ctx, key=k: (key, keycheck.fetch(key)), on_result=self._checked_key,
                              on_error=lambda exc, key=k: self._checked_key((key, (keycheck.NO_CONNECTION, []))),
                              lane="read")
        self.refreshStates()
        return n

    def _checked_key(self, result) -> None:
        key, (state, names) = result
        self._pending = max(0, self._pending - 1)
        if key in self.keystore.keys:
            self._checked[key] = state
        if state == keycheck.READY and names:
            self._cache.save(names)
            self._google = names
            self.googleChanged.emit()
        if state != keycheck.READY:
            self.app.log.add("A key was not accepted: %s" % state, problem=state == keycheck.INVALID)
        self.rebuild()
        if not self._pending:
            self._say(sr.saved_line(self.app.run.busy))

    @Slot(int)
    def removeKey(self, index):
        if 0 <= index < len(self.keystore.keys):
            key = self.keystore.keys[index]
            self.keystore.remove(key)
            self._checked.pop(key, None)
            self.app.log.add("A key was removed")
            self.rebuild()
            self._ok("keys")

    @Slot()
    def refreshStates(self):
        """Read the pool files of the library on a lane; the rows show their state when the answer arrives."""
        lib = self.app.libraryPath
        keys, models = list(self.keystore.keys), list(self._models)
        if not lib or not keys:
            self._states, self._missing = {}, set()
            self.rebuild()
            return
        from ..facade import quota
        self.lanes.submit(lambda ctx: quota.key_states(lib, keys, models, time.time()), on_result=self._got_states,
                          lane="read", group="keystates")

    def _got_states(self, result) -> None:
        self._states, self._missing = result
        self.rebuild()

    # ------------------------------------------------------------- models
    def _save_models(self, models) -> None:
        self._models = models
        self.settings.set("models", list(models))
        self.rebuild()
        self.refreshStates()
        self._ok("models")

    @Slot(str)
    def addModel(self, name):
        name = name.strip()
        if name and name not in self._models:
            self.app.log.add("Model added: %s" % name)
            self._save_models(self._models + [name])

    @Slot(int, int)
    def moveModel(self, index, delta):
        moved = sr.move_model(self._models, index, delta)
        if moved != self._models:
            self._save_models(moved)

    @Slot(int)
    def removeModel(self, index):
        out = sr.remove_model(self._models, index)
        if out != self._models:
            self._save_models(out)
        else:
            self.app.message = "The last model cannot be removed: a job needs one."

    @Slot(int, str)
    def renameModel(self, index, name):
        out = sr.rename_model(self._models, index, name)
        if out != self._models:
            self._save_models(out)

    @Slot(str, result="QVariantList")
    def modelEntries(self, typed):
        return sr.model_entries(self._models, self._google, typed)

    @Slot()
    def loadGoogle(self):
        """Opening the Models drop-down: the cached list of Google at once; a due refresh with a ready key on a lane.
        Offline or without keys only Recommended stays."""
        names, _age = self._cache.load()
        if names != self._google:
            self._google = names
            self.googleChanged.emit()
        base = keycheck.api_base()
        if not self.keystore.keys or not base or not self._cache.due():
            return
        key = self.keystore.keys[0]
        self.lanes.submit(lambda ctx: keycheck.fetch(key, base), on_result=self._google_fetched, lane="read",
                          group="google")

    def _google_fetched(self, result) -> None:
        state, names = result
        if state == keycheck.READY and names:
            self._cache.save(names)
            self._google = names
            self.googleChanged.emit()

    # ------------------------------------------------------------- pace and keep awake
    def _read_pace(self) -> str:
        v = self.settings.get("pace")
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and sr.clean_pace(int(v)) is not None
        return str(int(v)) if ok else str(sr.PACE_DEFAULT)

    @Property(str, notify=paceChanged)
    def pace(self):
        return self._pace

    @Property(str, notify=paceChanged)
    def paceUnit(self):
        return sr.pace_unit(self._pace)

    @Slot(str, result=str)
    def unitFor(self, text):
        return sr.pace_unit(text)

    @Slot(str, result=bool)
    def setPace(self, text):
        """Enter: a pace outside 1-120 is refused (the field stays for correction)."""
        p = sr.clean_pace(text)
        if p is None:
            return False
        self._pace = str(p)
        self.settings.set("pace", p)
        self.paceChanged.emit()
        self._ok("pace")
        return True

    @Property(bool, notify=awakeChanged)
    def keepAwake(self):
        return bool(self.settings.get("keep_awake"))

    @Property(bool, constant=True)
    def awakeAvailable(self):
        return platform.IS_WINDOWS

    @Slot(bool)
    def setKeepAwake(self, on):
        if not platform.IS_WINDOWS:
            return
        self.settings.set("keep_awake", bool(on))
        self.awakeChanged.emit()
        self._ok("awake")

    @Property("QVariant", constant=True)
    def awakeTip(self):
        return tips.AWAKE_ROW if platform.IS_WINDOWS else tips.AWAKE_ROW_OFF

    # ------------------------------------------------------------- library, app data, graphics
    @Property(str, notify=libraryChanged)
    def libraryName(self):
        return sr.library_label(self.app.libraryPath)

    @Property("QVariant", notify=libraryChanged)
    def libraryTip(self):
        return [self.app.libraryPath or "Not chosen", [["Click", "opens the folder"]]]

    @Property("QVariant", notify=libraryChanged)
    def changeTip(self):
        return tips.LIBRARY_ROW_CHANGE_BUSY if self.app.run.busy else tips.LIBRARY_CHANGE[0]

    @Slot()
    def openLibrary(self):
        if self.app.libraryPath:
            platform.open_folder(self.app.libraryPath)

    @Slot()
    def changeLibrary(self):
        self.app.changeLibrary()

    @Property(str, notify=appDataChanged)
    def appDataText(self):
        return self._data_text

    @Slot()
    def measureAppData(self):
        folder = self.local
        self.lanes.submit(lambda ctx: sr.folder_size(folder), on_result=self._got_size, lane="read", group="appdata")

    def _got_size(self, n) -> None:
        self._data_text = sr.size_text(int(n))
        self.appDataChanged.emit()

    @Slot()
    def openAppData(self):
        platform.open_folder(self.local)

    @Property(str, notify=graphicsChanged)
    def graphics(self):
        v = self.settings.get("graphics")
        return v if v in ("auto", "software") else "auto"

    @Slot(str)
    def setGraphics(self, value):
        if value not in ("auto", "software") or value == self.graphics:
            return
        self.settings.set("graphics", value)
        if value == "auto":
            markers.Markers(self.local).remove(markers.SOFTWARE)     # a stuck software start is released (11.7)
        self.graphicsChanged.emit()
        self._say(sr.SAVED_RUN, "graphics")
