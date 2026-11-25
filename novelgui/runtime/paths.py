"""The only place that builds the program's own folders.

Settings folder: settings.json and small user files (per user: the roaming folder on Windows, $XDG_CONFIG_HOME on Linux).
Local data folder: databases, logs, markers, locks (per user: the local folder on Windows, $XDG_DATA_HOME on Linux).
With NOVELGUI_DATA set (tests, scripted checks) the settings folder is that folder and the local data folder is
`local` inside it, so nothing of the owner's real folders is touched.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import platform

ENV_DATA = "NOVELGUI_DATA"
APP_DIR = "novelgui"


def _override() -> Path | None:
    env = os.environ.get(ENV_DATA)
    return Path(env) if env else None


def default_settings_dir() -> Path:
    return platform.config_base() / APP_DIR


def default_local_dir() -> Path:
    return platform.local_data_base() / APP_DIR


def settings_dir() -> Path:
    return _override() or default_settings_dir()


def local_dir() -> Path:
    over = _override()
    return over / "local" if over else default_local_dir()


def logs_dir() -> Path:
    return local_dir() / "logs"


def lock_path() -> Path:
    return local_dir() / "app.lock"
