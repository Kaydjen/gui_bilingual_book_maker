"""Background work of the window: serial lanes of Python threads and one pump back to the GUI thread.

A task is a function `fn(ctx)`. `ctx.emit(item)` sends a progress item (delivered to `on_item`), `ctx.cancelled`
turns true once the task's token is cancelled, `ctx.breathe()` lets the GUI thread have the interpreter (call it
in every loop of pure-Python work: a busy thread otherwise starves every Python call the window makes). The
return value goes to `on_result`, an exception to `on_error`. Callbacks run on the GUI thread.

Lanes:
- "data" and "read" are serial: one thread each, tasks run in the order they were submitted (save N before
  N+1). Books a lane thread opens stay in that thread's cache; `close_lane_books` reaches every serial lane.
- "run" is not serial: each task gets its own thread (a translation relay runs for hours and must not hold a
  serial lane).

The pump is the only door from a lane thread to the GUI thread: the lane hands plain data to `pump.post`, the
GUI side delivers it. `QtPump` is ONE GUI-thread QObject with a queued `Signal(int, str, object)`: nothing
polls, an idle window costs nothing. A lane thread never calls into any other QObject.

Generations: `submit(..., group="chapters")` supersedes the previous task of that group: its token is cancelled
and its late replies (items, result, error) are dropped, whichever arrives first.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
import traceback

SERIAL_LANES = ("data", "read")
RUN_LANE = "run"
SWITCH_INTERVAL = 0.0005    # a safety net only; the defence is `ctx.breathe()`
BREATH_EVERY = 0.003        # seconds of work between two breaths
BREATH = 0.001              # seconds of sleep per breath

log = logging.getLogger("novelgui.lanes")


class Token:
    def __init__(self):
        self._flag = threading.Event()

    def cancel(self) -> None:
        self._flag.set()

    @property
    def cancelled(self) -> bool:
        return self._flag.is_set()


class Want:
    """The rows the user looks at now; a scanner serves them first. Written by the GUI, read by a worker."""

    def __init__(self, first: int = 0, last: int = 60):
        self._lock = threading.Lock()
        self.first = first
        self.last = last

    def set(self, first: int, last: int) -> None:
        with self._lock:
            self.first, self.last = first, last

    def get(self) -> tuple[int, int]:
        with self._lock:
            return self.first, self.last


class Ctx:
    """What a task sees of its lane."""

    def __init__(self, post, job: int, token: Token):
        self._post = post
        self._job = job
        self.token = token
        self._breath = time.perf_counter()

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled

    def emit(self, item) -> None:
        self._post(self._job, "item", item)

    def breathe(self) -> None:
        """Sleep 1 ms when 3 ms passed since the last breath (gives the GUI thread the interpreter)."""
        now = time.perf_counter()
        if now - self._breath >= BREATH_EVERY:
            time.sleep(BREATH)
            self._breath = time.perf_counter()


class PlainCtx:
    """A context for calling a task directly (tests, the helper process): items go to a list or a callback."""

    def __init__(self, on_item=None, token: Token | None = None):
        self.items: list = []
        self._on_item = on_item
        self.token = token or Token()

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled

    def emit(self, item) -> None:
        if self._on_item is not None:
            self._on_item(item)
        else:
            self.items.append(item)

    def breathe(self) -> None:
        pass


# ---------------------------------------------------------------- pumps
class ManualPump:
    """A pump without Qt: posts wait in a queue until `drain()` runs them (tests, scripts)."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._deliver = None

    def connect(self, deliver) -> None:
        self._deliver = deliver

    def post(self, job: int, kind: str, payload) -> None:
        self._q.put((job, kind, payload))

    def drain(self, timeout: float = 0.0) -> int:
        """Deliver what has arrived; with `timeout`, wait that long for the first post. Returns the count."""
        n = 0
        try:
            entry = self._q.get(timeout=timeout) if timeout > 0 else self._q.get_nowait()
        except queue.Empty:
            return 0
        while True:
            self._deliver(*entry)
            n += 1
            try:
                entry = self._q.get_nowait()
            except queue.Empty:
                return n


class QtPump:
    """One QObject living on the GUI thread; lane threads emit its queued signal with plain data."""

    def __init__(self):
        from PySide6.QtCore import QObject, Qt, Signal

        class _Door(QObject):
            ready = Signal(int, str, object)

        self._door = _Door()
        self._conn = Qt.ConnectionType.QueuedConnection

    def connect(self, deliver) -> None:
        self._door.ready.connect(deliver, self._conn)

    def post(self, job: int, kind: str, payload) -> None:
        self._door.ready.emit(job, kind, payload)


# ---------------------------------------------------------------- lanes
class _Handler:
    __slots__ = ("on_result", "on_error", "on_item", "token", "group", "gen")

    def __init__(self, on_result, on_error, on_item, token, group, gen):
        self.on_result, self.on_error, self.on_item = on_result, on_error, on_item
        self.token, self.group, self.gen = token, group, gen


class Lanes:
    def __init__(self, pump=None, lanes=SERIAL_LANES):
        self.pump = pump if pump is not None else QtPump()
        self.pump.connect(self._deliver)
        self._queues = {name: queue.Queue() for name in lanes}
        self._handlers: dict[int, _Handler] = {}
        self._gens: dict[str, tuple[int, Token]] = {}
        self._next = 1
        self._closed = False
        sys.setswitchinterval(min(sys.getswitchinterval(), SWITCH_INTERVAL))
        self._threads = {n: threading.Thread(target=self._run, args=(q,), daemon=True, name="lane-" + n)
                         for n, q in self._queues.items()}
        for t in self._threads.values():
            t.start()

    @property
    def lane_names(self) -> list:
        return list(self._queues)

    def thread_names(self) -> list:
        return [t.name for t in self._threads.values()]

    def submit(self, fn, on_result=None, on_error=None, on_item=None, lane="data", token=None, group=None) -> Token:
        token = token or Token()
        job = self._next
        self._next += 1
        gen = 0
        if group is not None:
            prev = self._gens.get(group)
            if prev is not None:
                prev[1].cancel()
            gen = (prev[0] + 1) if prev else 1
            self._gens[group] = (gen, token)
        self._handlers[job] = _Handler(on_result, on_error, on_item, token, group, gen)
        if lane == RUN_LANE:
            threading.Thread(target=self._one, args=(job, fn, token), daemon=True, name="run-%d" % job).start()
        else:
            self._queues[lane].put((job, fn, token))
        return token

    def generation(self, group: str) -> int:
        g = self._gens.get(group)
        return g[0] if g else 0

    def _run(self, q: queue.Queue) -> None:
        while True:
            entry = q.get()
            if entry is None:
                return
            self._one(*entry)

    def _one(self, job: int, fn, token: Token) -> None:
        post = self.pump.post
        if token.cancelled:
            post(job, "skip", None)
            return
        try:
            result = fn(Ctx(post, job, token))
            post(job, "result", result)
        except BaseException as exc:  # reported to the GUI thread, never lost
            exc.__traceback_text__ = traceback.format_exc()
            post(job, "error", exc)

    def _live(self, h: _Handler) -> bool:
        if h.token.cancelled:
            return False
        if h.group is not None and self._gens.get(h.group, (0,))[0] != h.gen:
            return False
        return True

    def _deliver(self, job: int, kind: str, payload) -> None:
        """GUI thread: one post of a lane."""
        h = self._handlers.get(job)
        if h is None:
            return
        if kind == "item":
            if h.on_item is not None and self._live(h):
                h.on_item(payload)
            return
        del self._handlers[job]
        live = self._live(h)
        if kind == "result":
            if h.on_result is not None and live:
                h.on_result(payload)
        elif kind == "error":
            if not live:
                return
            if h.on_error is not None:
                h.on_error(payload)
            else:
                log.error("task failed: %s", getattr(payload, "__traceback_text__", repr(payload)))

    def idle(self) -> bool:
        """True when no task is waiting or running and every reply has been delivered."""
        return not self._handlers

    # ------------------------------------------------------------- open books
    def close_lane_books(self, folder=None, on_done=None) -> None:
        """Close the books every serial lane holds open (of `folder`, or all). `on_done(n)` runs on the GUI thread
        once every lane has done it (n = books closed). An open zip blocks a move or a replace on Windows."""
        from .facade.books import release_books_task
        left = [len(self._queues)]
        total = [0]

        def one(n):
            total[0] += int(n or 0)
            left[0] -= 1
            if left[0] == 0 and on_done is not None:
                on_done(total[0])

        for name in self._queues:
            self.submit(lambda ctx: release_books_task(ctx, folder), on_result=one,
                        on_error=lambda exc: one(0), lane=name)

    def close(self) -> None:
        self._closed = True
        for q in self._queues.values():
            q.put(None)

    def join(self, timeout: float = 5.0) -> None:
        for t in self._threads.values():
            t.join(timeout)
