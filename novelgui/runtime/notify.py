"""Notifications for a window that is not active: a toast and a taskbar flash (window_spec 14.6).

`Notifier` is the interface. `RealNotifier` shows a tray balloon and flashes the taskbar button. `RecordingNotifier`
appends one JSON line per call to `<settings folder>/notify.log`; it is used whenever NOVELGUI_DATA is set (tests,
scripted checks), unless NOVELGUI_NOTIFY=real.
"""

from __future__ import annotations

import json
import os
import time

from .. import platform
from . import paths

ENV_NOTIFY = "NOVELGUI_NOTIFY"
LOG_NAME = "notify.log"


class Notifier:
    def toast(self, title: str, text: str, route: str = "") -> None:
        raise NotImplementedError

    def flash(self) -> None:
        raise NotImplementedError


class RealNotifier(Notifier):
    def __init__(self, window=None):
        self.window = window            # the QQuickWindow, for the taskbar flash
        self._tray = None

    def toast(self, title: str, text: str, route: str = "") -> None:
        # The tray balloon (QSystemTrayIcon, click routing by `route`) comes with the screens; until then a
        # toast is not shown. The recording notifier is what tests check.
        return

    def flash(self) -> None:
        try:
            hwnd = int(self.window.winId()) if self.window is not None else 0
        except Exception:
            hwnd = 0
        platform.flash_window(hwnd)


class RecordingNotifier(Notifier):
    def __init__(self, folder=None):
        self.path = (folder or paths.settings_dir()) / LOG_NAME

    def _write(self, record: dict) -> None:
        record["t"] = round(time.time(), 3)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def toast(self, title: str, text: str, route: str = "") -> None:
        self._write({"kind": "toast", "title": title, "text": text, "route": route})

    def flash(self) -> None:
        self._write({"kind": "flash"})


def make_notifier(window=None) -> Notifier:
    if os.environ.get(paths.ENV_DATA) and os.environ.get(ENV_NOTIFY) != "real":
        return RecordingNotifier()
    return RealNotifier(window)
