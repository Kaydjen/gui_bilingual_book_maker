"""One app window at a time (window_spec 10.9): a lock file in the app data folder.

The first window writes its process id, its start time and its window handle into the file; a second start finds
a live holder, shows a message and brings the first window to the front. A lock left by a process that is gone
(crash, power loss) is taken over. `alive(info) -> bool` is handed in so this module needs no process calls.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

FILE_NAME = "app.lock"


class AppLock:
    def __init__(self, folder, alive, pid: int | None = None, clock=time.time):
        self.path = Path(folder) / FILE_NAME
        self.alive = alive
        self.pid = os.getpid() if pid is None else pid
        self.clock = clock
        self.held = False
        self.holder: dict | None = None     # the live holder found by a failed acquire

    def read(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def acquire(self) -> bool:
        """True when this process now holds the lock. False: another live window holds it (`holder`)."""
        info = self.read()
        if info is not None and info.get("pid") != self.pid:
            try:
                live = bool(self.alive(info))
            except Exception:
                live = False
            if live:
                self.holder = info
                return False
        self.holder = None
        self._write({"pid": self.pid, "started": self.clock(), "hwnd": 0})
        self.held = True
        return True

    def set_window(self, hwnd: int) -> None:
        """Record the window handle of the first window so a second start can bring it to the front."""
        if not self.held:
            return
        info = self.read() or {"pid": self.pid, "started": self.clock()}
        info["hwnd"] = int(hwnd)
        self._write(info)

    def _write(self, info: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(FILE_NAME + ".tmp")
            tmp.write_text(json.dumps(info), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        info = self.read()
        if info is None or info.get("pid") == self.pid:
            try:
                self.path.unlink()
            except OSError:
                pass
