"""The only place that builds the program's own folders.

Settings folder: settings.json and small user files (Windows %APPDATA%\novelgui, Linux $XDG_CONFIG_HOME/novelgui).
Local data folder: databases, logs, markers, locks (Windows %LOCALAPPDATA%\novelgui, Linux $XDG_DATA_HOME/novelgui).
With NOVELGUI_DATA set (tests, scripted checks) the settings folder is that folder and the local data folder is
`local` inside it, so nothing of the owner's real folders is touched.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_DATA = "NOVELGUI_DATA"
APP_DIR = "novelgui"


def _override() -> Path | None:
    env = os.environ.get(ENV_DATA)
    return Path(env) if env else None


def default_settings_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR


def default_local_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR


def settings_dir() -> Path:
    return _override() or default_settings_dir()


def local_dir() -> Path:
    over = _override()
    return over / "local" if over else default_local_dir()


def logs_dir() -> Path:
    return local_dir() / "logs"


def lock_path() -> Path:
    return local_dir() / "app.lock"
