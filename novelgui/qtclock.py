"""The single-shot timer the controllers get injected, built on QTimer (GUI thread only)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer

_live: set = set()      # a timer must outlive the call that armed it


class _Handle:
    __slots__ = ("_t",)

    def __init__(self, t: QTimer):
        self._t = t

    def cancel(self) -> None:
        t, self._t = self._t, None
        if t is not None:
            t.stop()
            _live.discard(t)
            t.deleteLater()


def timer(ms: int, fn) -> _Handle:
    """Call `fn` once after `ms` milliseconds; `handle.cancel()` before that forgets it."""
    t = QTimer()
    t.setSingleShot(True)
    t.setTimerType(Qt.TimerType.PreciseTimer)
    h = _Handle(t)

    def fire():
        if h._t is None:
            return
        h._t = None
        _live.discard(t)
        t.deleteLater()
        fn()
    t.timeout.connect(fire)
    _live.add(t)
    t.start(max(0, int(ms)))
    return h
