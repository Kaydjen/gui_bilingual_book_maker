"""Window-side state in the app data folder (settings.json), never in the library.

Everything the window remembers about its own use lives under one key, `win`, of the settings file: the
prompt draft, the chapter selection of each volume, the queue and so on. The layer is typed: a value of the
wrong type reads as the default, so a hand-edited or old file never breaks a screen. Writes go through
`Settings.save`, which replaces the file atomically.
"""

from __future__ import annotations

import copy

from .settings import Settings

SECTION = "win"
_NO = object()


def _is(value, kind) -> bool:
    if kind is None:
        return True
    if kind is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is bool:
        return isinstance(value, bool)
    return isinstance(value, kind)


class WinState:
    """Typed get / set over `settings["win"]`. Keys are plain strings; `scope` adds a second level
    (for example a series path) so one setting can be kept per series or per volume."""

    def __init__(self, settings: Settings):
        self.settings = settings

    # ------------------------------------------------------------- raw
    def _section(self) -> dict:
        sec = self.settings.get(SECTION)
        return sec if isinstance(sec, dict) else {}

    def get(self, key: str, default=None, kind=None):
        """The stored value, or `default` when missing or not of type `kind`."""
        v = self._section().get(key, _NO)
        if v is _NO or not _is(v, kind):
            return default
        return copy.deepcopy(v)

    def set(self, key: str, value) -> bool:
        """Store a JSON value; False when the file could not be written (the value is kept in memory)."""
        sec = dict(self._section())
        if sec.get(key, _NO) == value:
            return True
        sec[key] = copy.deepcopy(value)
        return self._write(sec)

    def delete(self, key: str) -> bool:
        sec = dict(self._section())
        if key not in sec:
            return True
        del sec[key]
        return self._write(sec)

    def _write(self, sec: dict) -> bool:
        self.settings.data[SECTION] = sec
        return self.settings.save()

    # ------------------------------------------------------------- typed shortcuts
    def get_str(self, key: str, default: str = "") -> str:
        return self.get(key, default, str)

    def get_int(self, key: str, default: int = 0) -> int:
        return self.get(key, default, int)

    def get_bool(self, key: str, default: bool = False) -> bool:
        return self.get(key, default, bool)

    def get_list(self, key: str, default=None) -> list:
        return self.get(key, [] if default is None else default, list)

    def get_dict(self, key: str, default=None) -> dict:
        return self.get(key, {} if default is None else default, dict)

    # ------------------------------------------------------------- scoped values
    def get_in(self, key: str, scope: str, default=None, kind=None):
        """Value kept under `key` for one scope (series path, volume ...)."""
        table = self.get_dict(key)
        v = table.get(scope, _NO)
        if v is _NO or not _is(v, kind):
            return default
        return v

    def set_in(self, key: str, scope: str, value) -> bool:
        table = self.get_dict(key)
        if table.get(scope, _NO) == value:
            return True
        table[scope] = value
        return self.set(key, table)

    def delete_in(self, key: str, scope: str) -> bool:
        table = self.get_dict(key)
        if scope not in table:
            return True
        del table[scope]
        return self.set(key, table)

    # ------------------------------------------------------------- named values used by the steps
    def prompt_draft(self, series: str):
        """(name, text) of an unsaved prompt of the series, or None."""
        d = self.get_in("prompt_draft", series, None, dict)
        if d and isinstance(d.get("name"), str) and isinstance(d.get("text"), str):
            return d["name"], d["text"]
        return None

    def set_prompt_draft(self, series: str, name: str, text: str) -> bool:
        return self.set_in("prompt_draft", series, {"name": name, "text": text})

    def clear_prompt_draft(self, series: str) -> bool:
        return self.delete_in("prompt_draft", series)

    def volume_selection(self, series: str, volume: str):
        """Chapter ranges [[a, b], ...] chosen on a volume, or None when nothing is stored."""
        d = self.get_in("selection", series, None, dict)
        v = d.get(volume) if d else None
        if isinstance(v, list) and all(isinstance(p, list) and len(p) == 2 and all(_is(x, int) for x in p)
                                       for p in v):
            return [list(p) for p in v]
        return None

    def set_volume_selection(self, series: str, volume: str, spans) -> bool:
        d = self.get_in("selection", series, None, dict) or {}
        d = dict(d)
        d[volume] = [[int(a), int(b)] for a, b in spans]
        return self.set_in("selection", series, d)

    def clear_volume_selection(self, series: str, volume: str) -> bool:
        """Forget the chapter selection (and the remembered volume choice) of a volume that was removed."""
        d = self.get_in("selection", series, None, dict)
        if d and volume in d:
            d = dict(d)
            del d[volume]
            self.set_in("selection", series, d)
        if self.last_volume(series) == volume:
            return self.delete_in("volume", series)
        return True

    def forget_series(self, series: str) -> bool:
        """Drop everything the window remembers about a series that was deleted."""
        ok = True
        for key in ("selection", "prompt_draft", "volume"):
            ok = self.delete_in(key, series) and ok
        return ok

    def last_volume(self, series: str) -> str:
        return self.get_in("volume", series, "", str)

    def set_last_volume(self, series: str, volume: str) -> bool:
        return self.set_in("volume", series, volume)
