"""The window's own state file (settings.json in the app data folder): one writer, debounced, atomic, with a backup.

- `Persistence.settings` is a `Settings` whose `save()` only marks the state dirty; `winstate` is the typed
  `WinState` over it (readers stay typed, a wrong type reads as the default).
- A change is written 500 ms after the LAST change (trailing debounce): a window drag never writes per move.
  `flush()` writes now: on demand, on close, when the window turns inactive, before a job starts, and at once
  for the queue and the keys. A write whose text equals the last one is skipped.
- A write is atomic (`atomic.write_text`) and keeps the previous file as `settings.json.bak`. With `submit` it
  runs on the data lane (one writer, in order); the text is made on the GUI thread, so a later change never
  leaks into an earlier write.
- A damaged file is kept as `settings.json.bad` (as `Settings` does) and the state is read from `.bak`.
"""

from __future__ import annotations

import json
import threading

from .. import atomic
from ..settings import FILE_NAME, Settings
from ..winstate import WinState

DEBOUNCE_MS = 500


class DurableSettings(Settings):
    def __init__(self, folder, owner: "Persistence"):
        self._owner = owner
        self.restored = False
        super().__init__(folder)

    def load(self) -> None:
        super().load()
        self.restored = False
        if not self.damaged:
            return
        bak = self.path.with_name(FILE_NAME + ".bak")
        try:
            data = json.loads(bak.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.data = data
            self.restored = True

    def save(self) -> bool:
        owner = getattr(self, "_owner", None)
        if owner is None:
            return True
        owner.mark()
        return True

    def text(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False)


class Persistence:
    def __init__(self, folder=None, timer=None, submit=None, delay_ms: int = DEBOUNCE_MS):
        self._timer = timer
        self._submit = submit
        self.delay_ms = delay_ms
        self._pending = None
        self.dirty = False
        self.writes = 0
        self.failed = False
        self._seq = 0                   # every text made gets a number; an older text never overwrites a newer
        self._written = 0
        self._wlock = threading.Lock()
        self.settings = DurableSettings(folder, self)
        self.winstate = WinState(self.settings)
        try:
            self._last = self.settings.path.read_text(encoding="utf-8") if not self.settings.damaged else None
        except OSError:
            self._last = None
        if self.settings.restored:
            self.mark()                 # write the restored state back as settings.json

    @property
    def path(self):
        return self.settings.path

    def mark(self) -> None:
        """Something changed: write it `delay_ms` after the last change (or now, without a timer)."""
        self.dirty = True
        if self._timer is None:
            self.flush()
            return
        if self._pending is not None:
            self._pending.cancel()
        self._pending = self._timer(self.delay_ms, self._due)

    def _due(self) -> None:
        self._pending = None
        self.flush()

    def flush(self) -> bool:
        """Write now when something changed. True when the state is (or is being) written."""
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        if not self.dirty:
            return True
        self.dirty = False
        text = self.settings.text()
        if text == self._last:
            return True
        self._last = text
        self._seq += 1
        if self._submit is None:
            return self._write(text, self._seq)
        self._submit(lambda ctx, t=text, n=self._seq: self._write(t, n), lane="data")
        return True

    def _write(self, text: str, seq: int) -> bool:
        with self._wlock:
            if seq <= self._written:
                return True
            ok = atomic.try_write_text(self.path, text, bak=True)
            self.failed = not ok
            if ok:
                self.writes += 1
                self._written = seq
            return ok

    def close(self) -> bool:
        """The window closes: write what is left, on this thread."""
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        if not self.dirty:
            return True
        self.dirty = False
        text = self.settings.text()
        if text == self._last:
            return True
        self._last = text
        self._seq += 1
        return self._write(text, self._seq)
