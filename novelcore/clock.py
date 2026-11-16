"""Time source used wherever the core waits, so tests can drive time."""

from __future__ import annotations

import threading
import time

MAX_CHUNK = 60.0  # longest single wait; long waits are repeated in chunks


class SystemClock:
    """Real time. `wait` sleeps on an event, so a stop request wakes it at once."""

    def now(self) -> float:
        return time.time()

    def wait(self, event: threading.Event, timeout: float) -> bool:
        """Wait up to `timeout` seconds; returns True when `event` was set."""
        return event.wait(max(0.0, min(timeout, MAX_CHUNK)))

    # A simulated clock needs to know which threads are alive; here it does not.
    def enter(self) -> None:
        pass

    def leave(self) -> None:
        pass
