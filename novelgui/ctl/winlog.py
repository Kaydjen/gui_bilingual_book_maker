"""The window's own log (window_spec 14.4): `window.log` in the local data folder, rotated by size. Each line is
`time TAB series TAB kind TAB text`. Keys never reach the file: a key the window knows is written as `key 3` (its
place in the key list), anything that looks like a Google key or a `key=` value as `key ••••`.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

FILE_NAME = "window.log"
MAX_BYTES = 512_000
KEEP = 2
PROBLEM, INFO = "p", "i"
_GOOGLE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_PARAM = re.compile(r"(?i)\b(key|api[_-]?key|x-goog-api-key)(\s*[=:]\s*)([^\s&\"',;]+)")


@dataclass(frozen=True)
class Entry:
    when: str
    series: str
    text: str
    problem: bool

    def line(self) -> str:
        return " · ".join(p for p in (self.when[11:19] or self.when, self.series, self.text) if p)


def scrub(text: str, keys=()) -> str:
    """The text with every known key replaced by `key N` and every key-looking token by `key ••••`."""
    out = str(text)
    for i, k in sorted(enumerate(keys, 1), key=lambda p: -len(p[1])):
        if k and len(k) >= 8:
            out = out.replace(k, "key %d" % i)
    out = _GOOGLE.sub("key ••••", out)
    return _PARAM.sub(lambda m: m.group(1) + m.group(2) + "••••", out)


def _clean(text: str) -> str:
    return " ".join(str(text).replace("\t", " ").split())


class WindowLog:
    def __init__(self, folder, keys=None):
        self.path = Path(folder) / FILE_NAME
        self._keys = keys or (lambda: [])
        self.listeners: list = []           # called after every line is written (the log window refreshes)

    def add(self, text: str, series: str = "", problem: bool = False, now: float | None = None) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() if now is None else now))
        line = "\t".join((stamp, _clean(scrub(series, self._keys())), PROBLEM if problem else INFO,
                          _clean(scrub(text, self._keys())))) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:
                pass

    def _rotate(self) -> None:
        try:
            if self.path.stat().st_size < MAX_BYTES:
                return
        except OSError:
            return
        for i in range(KEEP, 0, -1):
            src = self.path if i == 1 else self.path.with_name("%s.%d" % (FILE_NAME, i - 1))
            dst = self.path.with_name("%s.%d" % (FILE_NAME, i))
            try:
                os.replace(src, dst)
            except OSError:
                pass

    def entries(self, problems_only: bool = False, limit: int = 2000) -> list:
        """The newest `limit` entries, oldest first."""
        out = []
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return out
        for ln in raw.splitlines():
            parts = ln.split("\t", 3)
            if len(parts) != 4:
                continue
            e = Entry(parts[0], parts[1], parts[3], parts[2] == PROBLEM)
            if e.problem or not problems_only:
                out.append(e)
        return out[-limit:]


def details_text(version: str, info: dict, tail, keys=()) -> str:
    """One text block for `Copy details` (14.4): what the job was, the last log lines, the program version. Keys
    are scrubbed again here, whatever the caller passed in."""
    lines = ["Novel %s" % version]
    for k in ("series", "book", "chapters", "state", "error"):
        if info.get(k):
            lines.append("%s: %s" % (k.capitalize(), info[k]))
    lines.append("")
    lines.extend(str(t) for t in tail)
    return scrub("\n".join(lines), keys)
