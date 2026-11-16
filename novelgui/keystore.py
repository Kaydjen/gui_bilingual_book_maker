"""API keys and the prompt library of the window, kept in the app data folder (never in a series).

keys.json    {"version": 1, "keys": [...]}   a damaged file is kept as keys.json.bad and reads as empty
prompts/     <name>.txt                      saved system prompts
Keys are never logged or printed; `mask` is the only form that may be shown.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

KEYS_FILE = "keys.json"
MIN_KEY_LEN = 16
_SPLIT = re.compile(r"[\s,;]+")


def parse_keys(text: str) -> list[str]:
    """Keys typed or pasted, one per line (commas and spaces also separate). Duplicates dropped, order kept;
    tokens too short to be a key (prose) are left out."""
    out: list[str] = []
    for tok in _SPLIT.split(text or ""):
        tok = tok.strip().strip("\"'")
        if len(tok) >= MIN_KEY_LEN and tok not in out:
            out.append(tok)
    return out


def mask(key: str) -> str:
    """Dots and the last 4 characters."""
    return "•" * 8 + key[-4:] if len(key) > 4 else "•" * 8


def _atomic(path: Path, text: str) -> bool:
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


class KeyStore:
    def __init__(self, folder):
        self.path = Path(folder) / KEYS_FILE
        self.keys: list[str] = []
        self.damaged = False
        self.load()

    def load(self) -> None:
        self.keys, self.damaged = [], False
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            data = json.loads(raw)
            keys = data.get("keys") if isinstance(data, dict) else None
            if not isinstance(keys, list):
                raise ValueError("no key list")
        except ValueError:
            self.damaged = True
            try:
                os.replace(self.path, self.path.with_name(KEYS_FILE + ".bad"))
            except OSError:
                pass
            return
        for k in keys:
            if isinstance(k, str) and k.strip() and k.strip() not in self.keys:
                self.keys.append(k.strip())

    def save(self) -> bool:
        return _atomic(self.path, json.dumps({"version": 1, "keys": self.keys}, indent=1))

    def add(self, text: str) -> int:
        """Add pasted keys; returns how many were new."""
        new = [k for k in parse_keys(text) if k not in self.keys]
        self.keys.extend(new)
        if new:
            self.save()
        return len(new)

    def remove(self, key: str) -> None:
        if key in self.keys:
            self.keys.remove(key)
            self.save()

    def masked(self) -> list[str]:
        return [mask(k) for k in self.keys]


def old_app_keys(folder) -> list[str]:
    """Keys of the earlier app's settings file (`key`: separated by commas, spaces or lines); [] when absent."""
    try:
        data = json.loads((Path(folder) / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get("key") if isinstance(data, dict) else None
    return parse_keys(raw) if isinstance(raw, str) else []


# ---------------------------------------------------------------- prompts
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = "default"


def prompt_file_name(name: str) -> str:
    s = re.sub(r"\s+", " ", _BAD.sub("_", name)).strip(" .")[:60]
    return s


class PromptStore:
    """Saved prompts: <folder>/prompts/<name>.txt."""

    def __init__(self, folder):
        self.dir = Path(folder) / "prompts"

    def names(self) -> list[str]:
        try:
            return sorted((p.stem for p in self.dir.glob("*.txt")), key=str.lower)
        except OSError:
            return []

    def read(self, name: str) -> str | None:
        try:
            return (self.dir / (prompt_file_name(name) + ".txt")).read_text(encoding="utf-8")
        except OSError:
            return None

    def save(self, name: str, text: str) -> str:
        """Save under a clean name; returns the name used. The name `Default` is not allowed."""
        clean = prompt_file_name(name)
        if not clean or clean.lower() == RESERVED:
            raise ValueError("choose another name")
        if not _atomic(self.dir / (clean + ".txt"), text):
            raise OSError("the prompt could not be written")
        return clean

    def delete(self, name: str) -> None:
        try:
            (self.dir / (prompt_file_name(name) + ".txt")).unlink()
        except OSError:
            pass
