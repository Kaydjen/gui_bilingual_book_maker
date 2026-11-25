"""The tray icon (window_spec 14.24) behind an interface.

`Tray`: what the window needs: `available`, `show` / `hide`, `update(lines, actions, tooltip, alert)` (the menu:
status lines on top, actions below), and two callbacks the owner sets: `on_activate()` (a left click) and
`on_action(id)` (a menu action: verb | open | quit). `RealTray` is a QSystemTrayIcon with its menu. `RecordingTray`
keeps everything in memory (and one JSON line per change in `<settings folder>/tray.log`) so checks can read what
the menu says and press its items; it is used whenever NOVELGUI_DATA is set unless NOVELGUI_TRAY=real.
"""

from __future__ import annotations

import json
import os
import time

from . import paths

ENV_TRAY = "NOVELGUI_TRAY"
LOG_NAME = "tray.log"


class Tray:
    available = False
    visible = False

    def __init__(self):
        self.on_activate = lambda: None
        self.on_action = lambda action_id: None
        self.on_message_click = lambda route: None

    def show_message(self, title: str, text: str, route: str = "") -> None:
        raise NotImplementedError

    def show(self) -> None:
        raise NotImplementedError

    def hide(self) -> None:
        raise NotImplementedError

    def update(self, lines, actions, tooltip: str, alert: bool) -> None:
        raise NotImplementedError


class RecordingTray(Tray):
    def __init__(self, folder=None, available: bool = True):
        super().__init__()
        self.available = available
        self.visible = False
        self.lines: list = []
        self.actions: list = []
        self.tooltip = ""
        self.alert = False
        self.history: list = []
        self.path = (folder or paths.settings_dir()) / LOG_NAME

    def _write(self, record: dict) -> None:
        record["t"] = round(time.time(), 3)
        self.history.append(record)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def show(self) -> None:
        self.visible = True
        self._write({"kind": "show"})

    def hide(self) -> None:
        self.visible = False
        self._write({"kind": "hide"})

    def update(self, lines, actions, tooltip: str, alert: bool) -> None:
        self.lines, self.actions, self.tooltip, self.alert = list(lines), list(actions), tooltip, bool(alert)
        self._write({"kind": "update", "lines": [list(x) for x in lines], "actions": [list(x) for x in actions],
                     "tooltip": tooltip, "alert": bool(alert)})

    def show_message(self, title: str, text: str, route: str = "") -> None:
        self._write({"kind": "message", "title": title, "text": text, "route": route})

    # ---- what a check does with it
    def activate(self) -> None:
        self.on_activate()

    def trigger(self, action_id: str) -> None:
        enabled = {a[0]: a[2] for a in self.actions}
        if enabled.get(action_id):
            self.on_action(action_id)


def _icon(alert: bool):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#161616"))
    p.setPen(QColor("#8a8a8a"))
    p.drawRoundedRect(QRectF(1.5, 1.5, 29, 29), 7, 7)
    f = QFont("Segoe UI")
    f.setPixelSize(20)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#f4f4f4"))
    p.drawText(QRectF(0, 0, 32, 32), Qt.AlignmentFlag.AlignCenter, "N")
    if alert:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e5383b"))
        p.drawEllipse(QRectF(20, 2, 10, 10))
    p.end()
    return QIcon(pm)


class RealTray(Tray):
    def __init__(self):
        super().__init__()
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        self._icon = QSystemTrayIcon()
        self._menu = QMenu()
        self._icon.setContextMenu(self._menu)
        self._icon.setIcon(_icon(False))
        self._icon.activated.connect(self._activated)
        self._route = ""
        self._icon.messageClicked.connect(lambda: self.on_message_click(self._route))
        self.available = bool(QSystemTrayIcon.isSystemTrayAvailable())

    def _activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.on_activate()

    def show(self) -> None:
        self._icon.show()
        self.visible = True

    def hide(self) -> None:
        self._icon.hide()
        self.visible = False

    def show_message(self, title: str, text: str, route: str = "") -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        self._route = route
        self._icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.NoIcon, 8000)

    def update(self, lines, actions, tooltip: str, alert: bool) -> None:
        self._menu.clear()
        for text, _kind in lines:
            act = self._menu.addAction(text)
            act.setEnabled(False)
        self._menu.addSeparator()
        for aid, text, enabled in actions:
            if aid == "quit":
                self._menu.addSeparator()
            act = self._menu.addAction(text)
            act.setEnabled(bool(enabled))
            act.triggered.connect(lambda _checked=False, a=aid: self.on_action(a))
        self._icon.setToolTip(tooltip)
        self._icon.setIcon(_icon(alert))


def make_tray() -> Tray:
    if os.environ.get(paths.ENV_DATA) and os.environ.get(ENV_TRAY) != "real":
        return RecordingTray()
    try:
        return RealTray()
    except Exception:
        return RecordingTray(available=False)
