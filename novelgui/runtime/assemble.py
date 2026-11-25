"""Builds the main window from its parts: settings, keys, window log, lanes, view-models, tray, notifier, the QML shell, the
native frame. Used by `boot` and by the scripted checks, so both run the same assembly (the checks pass a recording
tray; the tray and the notifier choose themselves from NOVELGUI_DATA).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QWindow

from .. import keystore, platform
from ..ctl.winlog import WindowLog
from ..lanes import Lanes
from ..settings import Settings
from ..vm.appvm import AppVM
from ..vm.logvm import LogVM
from ..vm.settingsvm import SettingsVM
from . import notify, paths, tray as trays
from .frame import FrameModel

QML_DIR = Path(__file__).resolve().parent.parent / "qml"
QML_MAIN = QML_DIR / "Main.qml"


class Parts:
    """Everything the window owns, kept alive together."""

    def __init__(self, settings_dir=None, local=None, tray=None, notifier=None):
        self.settings_dir = Path(settings_dir or paths.settings_dir())
        self.local = Path(local or paths.local_dir())
        self.settings = Settings(self.settings_dir)
        self.keystore = keystore.KeyStore(self.settings_dir)
        self.winlog = WindowLog(self.local, keys=lambda: list(self.keystore.keys))
        self.lanes = Lanes()
        self.tray = tray if tray is not None else trays.make_tray()
        self.notifier = notifier
        self.frame = FrameModel()
        self.app = AppVM(self.settings, self.winlog, self.tray, None)
        self.settings_vm = SettingsVM(self.app, self.keystore, self.lanes, self.local)
        self.log_vm = LogVM(self.winlog, keys=lambda: list(self.keystore.keys))
        self.window = None
        self.frame_filter = None

    def context(self, shell) -> dict:
        return {"shellVm": shell, "appVm": self.app, "settingsVm": self.settings_vm, "logVm": self.log_vm,
                "frameVm": self.frame}

    def close(self) -> None:
        self.app.flush()
        self.lanes.close()


def screens() -> list:
    """The available areas of the visible screens, the primary one first."""
    primary = QGuiApplication.primaryScreen()
    ordered = sorted(QGuiApplication.screens(), key=lambda s: s is not primary)
    out = []
    for s in ordered:
        g = s.availableGeometry()
        out.append([g.x(), g.y(), g.width(), g.height()])
    return out


def _hide(window: QWindow):
    return lambda: window.hide()


def _show(window: QWindow):
    def show():
        if window.visibility() == QWindow.Visibility.Minimized:
            window.showNormal()
        elif window.visibility() == QWindow.Visibility.Hidden:
            window.show()
        window.raise_()
        window.requestActivate()
    return show


def attach_window(parts: Parts, window, app) -> None:
    """Hand the OS side to the view-model, restore the geometry, install the native frame."""
    parts.window = window
    vm = parts.app
    vm.hide_window = _hide(window)
    vm.show_window = _show(window)
    vm.exit_app = lambda: QTimer.singleShot(0, lambda: app.exit(0))
    vm.window_active = window.isActive
    vm.window_visible = window.isVisible
    parts.tray.on_message_click = vm.bring_forward
    parts.notifier = notify.make_notifier(window, parts.tray)
    vm.notifier = parts.notifier
    g = vm.startGeometry(screens())
    window.setX(g["x"])
    window.setY(g["y"])
    window.setWidth(g["w"])
    window.setHeight(g["h"])
    parts.frame_filter = platform.install_frame(app, window, parts.frame)


def create_window(app, engine, shell, parts: Parts | None = None):
    """Load Main.qml with the view-models as context objects; returns (window, parts). The window is not shown yet."""
    parts = parts or Parts()
    engine.addImportPath(str(QML_DIR))
    ctx = engine.rootContext()
    for name, obj in parts.context(shell).items():
        ctx.setContextProperty(name, obj)
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        raise RuntimeError("The window file could not be loaded: %s" % QML_MAIN.name)
    window = engine.rootObjects()[0]
    attach_window(parts, window, app)
    return window, parts

