"""Persistent settings and the per-user data folder."""
import json
import os
import sys
from pathlib import Path

APP = "bbm-gui"


def data_dir() -> Path:
    override = os.environ.get("BBM_GUI_DATA")
    if override:
        d = Path(override)
        d.mkdir(parents=True, exist_ok=True)
        return d
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


class Settings(dict):
    def __init__(self):
        super().__init__()
        self.path = data_dir() / "settings.json"
        try:
            self.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
