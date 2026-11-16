"""Per-user settings file (window geometry, library folder, last series, pane height)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .platform import default_data_dir

ENV_DATA = "NOVELGUI_DATA"
ENV_API_BASE = "NOVELGUI_API_BASE"      # test hook: base URL of the translation service
ENV_OLD_DATA = "NOVELGUI_OLD_DATA"      # test hook: folder of the earlier app's settings file
DEFAULT_MODEL = "gemini-3.1-flash-lite"
FILE_NAME = "settings.json"


def data_dir() -> Path:
    env = os.environ.get(ENV_DATA)
    return Path(env) if env else default_data_dir()


def api_base() -> str | None:
    return os.environ.get(ENV_API_BASE) or None


def old_data_dir() -> Path:
    env = os.environ.get(ENV_OLD_DATA)
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "bbm-gui"


class Settings:
    """A flat JSON dict. A missing or damaged file gives an empty one (the damaged file is kept as .bad)."""

    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else data_dir()
        self.path = self.folder / FILE_NAME
        self.data: dict = {}
        self.damaged = False
        self.load()

    def load(self) -> None:
        self.data = {}
        self.damaged = False
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, dict):
            self.data = data
        else:
            self.damaged = True
            try:
                os.replace(self.path, self.path.with_name(FILE_NAME + ".bad"))
            except OSError:
                pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def get_float(self, key: str, default: float, lo: float, hi: float) -> float:
        v = self.data.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return default
        return min(hi, max(lo, float(v)))

    def set(self, key: str, value) -> None:
        if self.data.get(key) != value:
            self.data[key] = value
            self.save()

    def update(self, **values) -> None:
        self.data.update(values)
        self.save()

    def save(self) -> bool:
        tmp = self.path.with_name(FILE_NAME + ".tmp")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False
