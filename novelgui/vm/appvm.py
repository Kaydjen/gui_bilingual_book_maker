"""The view-model of the window shell: steps and their states in the header, the library state (first start,
library not found), closing and the tray, notifications, window memory, the focus-rescan hook.

QML only binds to it. The rules are in ctl/shellrules.py (pure); what the OS does (hide, show, exit) is handed in as
callbacks so the same object runs in tests with fakes. Run state comes from the real RunControl through
`set_run_info` (the Translate view-model builds it with ctl/runinfo); `setRun` stays for scenes that feed fake data.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from .. import libraryrules as rules
from .. import tips
from ..ctl import shellrules as sr
from ..ctl.winlog import WindowLog
from ..winstate import WinState

GEOMETRY_DELAY_MS = 500
KEY_SCREEN, KEY_GEOMETRY, KEY_TRAY_SEEN = "screen", "geometry", "tray_seen"
LIBRARY_READY, LIBRARY_FIRST, LIBRARY_MISSING = "ready", "first", "missing"
TOAST_TITLES = {"finished": "Translation finished", "failed": "Translation stopped", "key": "A key stopped working"}


def _tip(value):
    """A tips.py tuple as the list the QML tooltip takes."""
    return [value[0], [list(f) for f in value[1]]] if isinstance(value, tuple) else value


class AppVM(QObject):
    screenChanged = Signal()
    libraryChanged = Signal()
    runChanged = Signal()
    panelChanged = Signal()
    messageChanged = Signal()
    settingsOpenChanged = Signal()
    logOpenChanged = Signal()
    bannerChanged = Signal()
    folderDialogRequested = Signal(str)
    addBooksRequested = Signal(list)
    rescanRequested = Signal()
    verbRequested = Signal(str)
    stopRequested = Signal()
    quitRequested = Signal()
    visibleChanged = Signal()
    glowRequested = Signal(str)
    pickedChanged = Signal()

    def __init__(self, settings, winlog: WindowLog, tray=None, notifier=None, home=None, onedrive=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.win = WinState(settings)
        self.log = winlog
        self.tray = tray
        self.notifier = notifier
        self.home = Path(home) if home else Path.home()
        self.onedrive = onedrive if onedrive is not None else os.environ.get("OneDrive")
        # callbacks of the assembler (the OS side); defaults do nothing so a bare VM is testable
        self.hide_window = lambda: None
        self.show_window = lambda: None
        self.exit_app = lambda: None
        self.window_active = lambda: True
        self.window_visible = lambda: True
        self.rescan = lambda: None                  # 14.7: BooksSession.rescan once step 5 has one
        self.rescan_calls = 0
        self._run = sr.RunInfo()
        self._quitting = False
        self._terms_scan = -1.0
        self._panel = ""
        self._panel_data: dict = {}
        self._message = ""
        self._settings_open = False
        self._log_open = False
        self._banner = False
        self._start_screen = ""
        self._screen = "books"
        self._library = ""
        self._library_state = LIBRARY_FIRST
        self._picked = ""
        self._pending_geometry = None
        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(GEOMETRY_DELAY_MS)
        self._geo_timer.timeout.connect(self.flush)
        self.load_library()
        self._screen = sr.clean_screen(self.win.get_str(KEY_SCREEN, "books"), self._library_state == LIBRARY_READY)
        if tray is not None:
            tray.on_activate = self._tray_activate
            tray.on_action = self._tray_action
            tray.show()
        self._sync_tray()

    # ------------------------------------------------------------- the library (2.1-2.4, 2.7, 9.11)
    def load_library(self) -> None:
        path = self.settings.get("library")
        if not isinstance(path, str) or not path.strip():
            self._library, self._library_state = "", LIBRARY_FIRST
        elif Path(path).is_dir():
            self._library, self._library_state = path, LIBRARY_READY
        else:
            self._library, self._library_state = path, LIBRARY_MISSING

    @Property(str, notify=libraryChanged)
    def libraryState(self):
        return self._library_state

    @Property(str, notify=libraryChanged)
    def libraryPath(self):
        return self._library

    @Property(str, constant=True)
    def defaultPath(self):
        return str(rules.default_library_path(self.home, self.onedrive))

    @Property(bool, notify=libraryChanged)
    def stepsDim(self):
        return self._library_state != LIBRARY_READY

    @Slot(result=str)
    def chooserStart(self):
        return rules.chooser_start(self._library, self.home)

    @Slot(str)
    def chooseFolder(self, start):
        self.folderDialogRequested.emit(start or self.chooserStart())

    @Slot(str)
    def useFolder(self, path):
        """`Create` (first start) or a folder chosen on the Library not found panel / in Settings: the rules of 2.2
        and 2.3 decide; a failure leaves the library as it was and says why in plain words."""
        path = (path or "").strip()
        if not path:
            return
        scan = rules.scan_folder(path)
        if scan.kind == "invalid":
            self._fail(path, "the path is a file, not a folder")
            return
        created, problem = rules.prepare_library(scan.library)
        if problem:
            self._fail(str(scan.library), problem)
            return
        self.settings.set("library", str(scan.library))
        self.log.add("Library set to %s%s" % (scan.library, " (created)" if created else ""))
        self.load_library()
        self.libraryChanged.emit()
        if scan.kind == "epubs":
            self.addBooksRequested.emit([str(p) for p in scan.epubs])
        self._sync_tray()

    def _fail(self, path: str, reason: str) -> None:
        text = "The folder %s cannot be used: %s." % (path, reason)
        self.log.add(text, problem=True)
        self.message = text

    @Property(str, notify=pickedChanged)
    def pickedPath(self):
        return self._picked

    @Slot(str)
    def folderChosen(self, chosen):
        """The folder dialog answered (a file: address or a path). On the first-start block it fills the field; anywhere
        else (Library not found, Settings) the folder is used at once."""
        path = str(Path(QUrl(chosen).toLocalFile())) if chosen.startswith("file:") else chosen
        if not path:
            return
        if self._library_state == LIBRARY_FIRST:
            self._picked = path
            self.pickedChanged.emit()
        else:
            self.useFolder(path)

    @Slot()
    def changeLibrary(self):
        """`Change…` of Settings (dim during a run, 2.3)."""
        if not self._run.busy:
            self.chooseFolder("")

    # ------------------------------------------------------------- messages
    def _get_message(self):
        return self._message

    def _set_message(self, text):
        if text != self._message:
            self._message = text
            self.messageChanged.emit()

    message = Property(str, _get_message, _set_message, notify=messageChanged)

    @Slot()
    def dismissMessage(self):
        self.message = ""

    # ------------------------------------------------------------- steps (1.1-1.9)
    @Property(str, notify=screenChanged)
    def screen(self):
        return self._screen

    @Property("QVariantList", constant=True)
    def steps(self):
        return [{"id": s, "text": sr.LABELS[s]} for s in sr.STEPS]

    @Slot(str)
    def go(self, screen):
        if screen not in sr.STEPS or self._screen == screen or self.stepsDim:
            return
        if self._panel or self._settings_open:
            return                                 # only the panel's own keys work while one is open (10.7)
        self._screen = screen
        self.win.set(KEY_SCREEN, screen)
        self.screenChanged.emit()

    @Slot(int)
    def goDigit(self, n):
        self.go(sr.step_for_digit(n))

    def set_context(self, series: str, book: str) -> None:
        """The series and book chosen on Books: the dim `series · book` of the header (1.1, 1.3)."""
        if (series, book) != getattr(self, "_context", ("", "")):
            self._context = (series, book)
            self.runChanged.emit()

    @Property(str, notify=runChanged)
    def contextLine(self):
        series, book = getattr(self, "_context", ("", ""))
        return sr.context_line(series, book) if self._library_state == LIBRARY_READY else ""

    @Property(str, notify=runChanged)
    def termsState(self):
        return sr.header_states(self._run)["terms"]

    @Property(float, notify=runChanged)
    def termsScan(self):
        """Progress 0..100 of the book scan of the open series (a thin line under the word Terms), -1 when none runs."""
        return self._terms_scan

    def set_terms_scan(self, percent: float) -> None:
        if percent != self._terms_scan:
            self._terms_scan = float(percent)
            self.runChanged.emit()

    @Property(str, notify=runChanged)
    def translateState(self):
        return sr.header_states(self._run)["translate"]

    @Property("QVariant", notify=runChanged)
    def translateTip(self):
        return sr.translate_tip(self._run)

    @Property(bool, notify=runChanged)
    def busy(self):
        return self._run.busy

    @Property("QVariantMap", constant=True)
    def tips(self):
        return {"gear": tips.GEAR, "min": tips.TITLE_MIN, "max": tips.TITLE_MAX, "restore": tips.TITLE_RESTORE,
                "close": tips.TITLE_CLOSE, "context": _tip(tips.CONTEXT_LINE),
                "books": _tip(tips.PATH_BOOKS), "terms": _tip(tips.PATH_TERMS), "export": _tip(tips.PATH_EXPORT),
                "termsRed": tips.PATH_TERMS_RED, "firstPath": _tip(tips.FIRST_START_FOLDER),
                "missingFolder": tips.LIBRARY_NOT_FOUND_FOLDER, "keysHead": _tip(tips.KEYS_HEAD),
                "keysPlus": _tip(tips.KEYS_PLUS), "modelsHead": tips.MODELS_HEAD, "paceRow": _tip(tips.PACE_ROW),
                "appData": _tip(tips.APP_DATA_ROW), "graphics": tips.GRAPHICS_ROW, "logButton": tips.LOG_BUTTON}

    @Slot("QVariantMap")
    def setRun(self, data):
        """Fake run data for scenes and tests; the real app uses `set_run_info`."""
        fields = {k: v for k, v in dict(data).items() if k in sr.RunInfo.__dataclass_fields__}
        self.set_run_info(sr.RunInfo(**fields))

    def set_run_info(self, info: sr.RunInfo) -> None:
        """The state of the jobs as the shell shows it: the header word and pulses, the tray lines, the closing panel,
        Books' `working during a run`, the red pulse of Terms."""
        if info == self._run:
            return
        self._run = info
        self.runChanged.emit()
        self._sync_tray()

    def run_closed(self) -> None:
        """RunControl has finished closing (the requests in flight ended): the panel of 9.11 completes the quit."""
        if self._panel == "closing" and not self._quitting:
            self.quitNow()

    @property
    def run(self) -> sr.RunInfo:
        return self._run

    # ------------------------------------------------------------- settings and log windows
    @Property(bool, notify=settingsOpenChanged)
    def settingsOpen(self):
        return self._settings_open

    @Slot()
    def openSettings(self):
        if self._library_state == LIBRARY_READY or self._library_state == LIBRARY_MISSING:
            self._set_settings(True)

    @Slot()
    def closeSettings(self):
        self._set_settings(False)

    def _set_settings(self, on):
        if self._settings_open != on:
            self._settings_open = on
            self.settingsOpenChanged.emit()

    @Property(bool, notify=logOpenChanged)
    def logOpen(self):
        return self._log_open

    @Slot()
    def openLog(self):
        if not self._log_open:
            self._log_open = True
            self.logOpenChanged.emit()

    @Slot()
    def logClosed(self):
        if self._log_open:
            self._log_open = False
            self.logOpenChanged.emit()

    # ------------------------------------------------------------- panels: closing, the first tray hide
    @Property(str, notify=panelChanged)
    def panel(self):
        return self._panel

    @Property("QVariantMap", notify=panelChanged)
    def panelData(self):
        return self._panel_data

    def _open_panel(self, name: str, data=None) -> None:
        self._panel, self._panel_data = name, data or {}
        self.panelChanged.emit()

    def show_panel(self, name: str, data=None) -> None:
        """A panel owned by another view-model (Add book): the shell only learns that one is open (keys, rescan)."""
        self._open_panel(name, data)

    @Slot()
    def closePanel(self):
        if self._panel:
            self._panel, self._panel_data = "", {}
            self.panelChanged.emit()

    @property
    def tray_available(self) -> bool:
        return bool(self.tray is not None and self.tray.available)

    @Slot()
    def requestClose(self):
        """The window's `✕`: quit while idle; hide to the tray while work goes on (first time with the panel);
        without a tray the 9.11 / 14.6 panel."""
        what = sr.close_decision(self._run, self.tray_available, self.win.get_bool(KEY_TRAY_SEEN))
        self.log.add("Close requested: %s" % what)
        if what == "quit":
            self.quitNow()
        elif what == "hide":
            self.hide_window()
            self.visibleChanged.emit()
        elif what == "hide_first":
            self._open_panel("trayFirst")
        else:
            self._open_closing()

    def _open_closing(self) -> None:
        """The 9.11 / 14.6 panel; while a run is going the stop begins as the panel opens, the app closes when the
        answers are saved (or `Close now`)."""
        data = sr.closing_panel(self._run)
        self._open_panel("closing", data)
        if data["kind"] == "running":
            self.stopRequested.emit()

    @Slot()
    def hideToTray(self):
        """`Hide to tray` of the first-time panel: never asked again."""
        self.win.set(KEY_TRAY_SEEN, True)
        self.closePanel()
        self.hide_window()
        self.visibleChanged.emit()

    @Slot()
    def quitNow(self):
        """`Quit`, `Close now`, `Close`: the run is told to stop first (RunControl at step 7), then the app ends."""
        self._quitting = True
        if self._run.busy:
            self.stopRequested.emit()
        self.flush()
        self.quitRequested.emit()
        self.exit_app()

    @Slot()
    def quitViaPanel(self):
        """`Quit` of the first-time tray panel: the stop path of 9.11 / 14.6 (the panel of the work going on)."""
        if sr.quit_decision(self._run) == "quit":
            self.quitNow()
        else:
            self._open_closing()

    # ------------------------------------------------------------- the tray (14.24)
    def _sync_tray(self) -> None:
        if self.tray is None:
            return
        self.tray.update(sr.tray_lines(self._run), sr.tray_actions(self._run), sr.tray_tooltip(self._run),
                         self._run.failed)

    def _tray_activate(self) -> None:
        if self.window_visible():
            self.hide_window()
        else:
            self.show_window()
        self.visibleChanged.emit()

    def _tray_action(self, action_id: str) -> None:
        if action_id == "open":
            self.show_window()
        elif action_id == "verb":
            self.verbRequested.emit(self._run.verb)
        elif action_id == "quit":
            if sr.quit_decision(self._run) == "quit":
                self.quitNow()
            else:
                self.show_window()
                self._open_closing()
        self.visibleChanged.emit()

    def bring_forward(self, route: str = "") -> None:
        """A toast was clicked or the second start asked: show the window on the screen where the fix is."""
        self.show_window()
        if route == "translate":
            self.go("translate")
        elif route == "settings":
            self.openSettings()
        elif route == "details":
            self.openLog()

    # ------------------------------------------------------------- notifications (14.6)
    @Slot(str, str, str)
    def announce(self, kind, series, text):
        """A translation ended, a job failed, a key was found invalid during a run: a toast and a taskbar flash while
        the window is NOT the active one; nothing while it is (the header already shows it). Always in the log."""
        self.log.add(text, series=series, problem=kind in ("failed", "key"))
        if self.window_active() or self.notifier is None:
            return
        route = {"finished": "translate", "failed": "translate", "key": "settings"}.get(kind, "translate")
        self.notifier.toast(TOAST_TITLES.get(kind, "Novel"), text, route)
        self.notifier.flash()

    @Slot(str, str, str)
    def runtimeToast(self, title, text, route):
        """A slot exception of the runtime asked for a toast (`Something went wrong`, route details)."""
        if self.notifier is not None and not self.window_active():
            self.notifier.toast(title, text, route)

    # ------------------------------------------------------------- focus rescan (14.7)
    @Slot()
    def windowActivated(self):
        """The window got the focus: the library listing is read again (a cheap listing). Not while a panel is open or
        a job writes; the hook `rescan` (BooksSession at step 5) does the listing, the signal lets the screens refresh."""
        if self._library_state != LIBRARY_READY or self._panel or self._settings_open or self._run.running:
            return
        self.rescan_calls += 1
        try:
            self.rescan()
        finally:
            self.rescanRequested.emit()

    # ------------------------------------------------------------- the second start banner
    def show_banner(self) -> None:
        self._banner = True
        self.bannerChanged.emit()

    # ------------------------------------------------------------- window memory (10.6, 10.8)
    @Slot("QVariantList", result="QVariantMap")
    def startGeometry(self, screens):
        """The saved geometry clamped to the visible screens: {x, y, w, h, max}."""
        scr = [tuple(int(v) for v in s) for s in screens]
        return sr.clamp_geometry(self.win.get_dict(KEY_GEOMETRY) or None, scr)

    @Slot(int, int, int, int, bool)
    def geometryChanged(self, x, y, w, h, maximized):
        """Keep the geometry; written 500 ms after the last change. A maximized window keeps its restored size."""
        old = self.win.get_dict(KEY_GEOMETRY)
        if maximized and old:
            self._pending_geometry = dict(old, max=True)
        else:
            self._pending_geometry = {"x": x, "y": y, "w": w, "h": h, "max": bool(maximized)}
        self._geo_timer.start()

    @Slot()
    def flush(self):
        self._geo_timer.stop()
        if self._pending_geometry is not None:
            self.win.set(KEY_GEOMETRY, self._pending_geometry)
            self._pending_geometry = None
