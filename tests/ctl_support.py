"""Stand-ins for the controller tests of the new window: a clock with single-shot timers, lanes without Qt."""

from __future__ import annotations

import time
from types import SimpleNamespace

from novelgui import lanes


class Clock:
    """A test clock with single-shot timers: `advance(s)` moves the time and fires what is due."""

    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now
        self.armed: list = []

    def __call__(self) -> float:
        return self.now

    def timer(self, ms, fn):
        h = SimpleNamespace(due=self.now + ms / 1000.0, fn=fn, cancelled=False)
        h.cancel = lambda h=h: setattr(h, "cancelled", True)
        self.armed.append(h)
        return h

    def live(self) -> list:
        return [h for h in self.armed if not h.cancelled]

    def advance(self, seconds: float = 0.0) -> None:
        self.now += seconds
        while True:
            due = sorted((h for h in self.armed if not h.cancelled and h.due <= self.now), key=lambda h: h.due)
            if not due:
                return
            h = due[0]
            self.armed.remove(h)
            h.fn()


class PlainLanes:
    """Real lanes with the plain pump; `settle()` delivers until nothing is left."""

    def __init__(self):
        self.pump = lanes.ManualPump()
        self.lanes = lanes.Lanes(self.pump)

    def submit(self, *a, **kw):
        return self.lanes.submit(*a, **kw)

    def settle(self, timeout: float = 10.0) -> None:
        end = time.monotonic() + timeout
        while not self.lanes.idle():
            if time.monotonic() > end:
                raise AssertionError("lanes did not settle")
            self.pump.drain(timeout=0.02)

    def close(self) -> None:
        done = []
        self.lanes.close_lane_books(None, done.append)
        try:
            self.settle(5)
        finally:
            self.lanes.close()
