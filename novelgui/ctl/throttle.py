"""A leading-edge throttle for the GUI thread: the first mark wakes at once, then a gate.

`mark()` while the gate is closed wakes now and opens a gate of `gate_ms`; marks inside the gate are remembered
and wake once when the gate ends (the trailing wake), which opens a new gate. `mark(urgent=True)` wakes now
whatever the gate says (a terminal run event). Built on an injected single-shot `timer(ms, fn) -> handle` (with
`cancel()`), so it is tested without Qt.
"""

from __future__ import annotations


class LeadingThrottle:
    def __init__(self, timer, wake, gate_ms: int = 100):
        self._timer = timer
        self._wake = wake
        self.gate_ms = gate_ms
        self._gate = None           # timer handle while the gate is open
        self._pending = False
        self.wakes = 0

    def mark(self, urgent: bool = False) -> None:
        if urgent:
            self._pending = False
            self._fire()
            return
        if self._gate is not None:
            self._pending = True
            return
        self._fire()

    def _fire(self) -> None:
        if self._gate is not None:
            self._gate.cancel()
        self._gate = self._timer(self.gate_ms, self._gate_end)
        self.wakes += 1
        self._wake()

    def _gate_end(self) -> None:
        self._gate = None
        if self._pending:
            self._pending = False
            self._fire()

    def cancel(self) -> None:
        if self._gate is not None:
            self._gate.cancel()
            self._gate = None
        self._pending = False


class Debounce:
    """Trailing debounce: `poke()` (re)arms a single-shot timer of `ms`; `fn` runs once after the last poke.
    `flush()` runs it now when it is pending; `cancel()` forgets it."""

    def __init__(self, timer, fn, ms: int):
        self._timer = timer
        self._fn = fn
        self.ms = ms
        self._handle = None

    @property
    def pending(self) -> bool:
        return self._handle is not None

    def poke(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
        self._handle = self._timer(self.ms, self._due)

    def _due(self) -> None:
        self._handle = None
        self._fn()

    def flush(self) -> bool:
        if self._handle is None:
            return False
        self._handle.cancel()
        self._handle = None
        self._fn()
        return True

    def cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None
