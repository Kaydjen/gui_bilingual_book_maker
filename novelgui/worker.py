"""Background work for the window: tasks run in worker threads, results are handed to the Tk thread.

A task is a function `fn(ctx)`; `ctx.emit(item)` sends progress items (delivered to `on_item`) and
`ctx.cancelled` turns true once the task's token is cancelled. The return value goes to `on_result`,
an exception to `on_error`. Callbacks run on the Tk thread, polled with `after`.
Each lane is one thread, so a long scan in one lane never delays a quick request in another.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import traceback


class Token:
    def __init__(self):
        self._flag = threading.Event()

    def cancel(self) -> None:
        self._flag.set()

    @property
    def cancelled(self) -> bool:
        return self._flag.is_set()


class Ctx:
    def __init__(self, worker: "Worker", job: int, token: Token):
        self._worker = worker
        self._job = job
        self.token = token

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled

    def emit(self, item) -> None:
        self._worker._out.put(("item", self._job, item))


SWITCH_INTERVAL = 0.0005    # seconds: a busy worker thread gives the UI thread the interpreter this quickly
POLL_BUDGET = 0.008         # seconds of callbacks the UI thread runs per poll before it lets the window breathe


class Worker:
    POLL_MS = 25

    def __init__(self, root, lanes=("bulk", "fast")):
        self.root = root
        self._out: queue.Queue = queue.Queue()
        self._lanes = {name: queue.Queue() for name in lanes}
        self._handlers: dict[int, tuple] = {}
        self._next = 1
        self._closed = False
        self._after = None
        # Every Tk call of the UI thread gives up the interpreter and has to win it back; with the default 5 ms
        # interval a busy worker makes each canvas call cost milliseconds and the window feels frozen.
        sys.setswitchinterval(min(sys.getswitchinterval(), SWITCH_INTERVAL))
        self._threads = [threading.Thread(target=self._run, args=(q,), daemon=True, name="lane-" + n)
                         for n, q in self._lanes.items()]
        for t in self._threads:
            t.start()
        self._poll()

    def submit(self, fn, on_result=None, on_error=None, on_item=None, lane="bulk", token=None) -> Token:
        token = token or Token()
        job = self._next
        self._next += 1
        self._handlers[job] = (on_result, on_error, on_item, token)
        self._lanes[lane].put((job, fn, token))
        return token

    def _run(self, q: queue.Queue) -> None:
        while True:
            entry = q.get()
            if entry is None:
                return
            job, fn, token = entry
            if token.cancelled:
                self._out.put(("skip", job, None))
                continue
            try:
                result = fn(Ctx(self, job, token))
                self._out.put(("result", job, result))
            except BaseException as exc:  # reported to the Tk thread, never lost
                exc.__traceback_text__ = traceback.format_exc()
                self._out.put(("error", job, exc))

    def _poll(self) -> None:
        if self._closed:
            return
        start = time.perf_counter()
        try:
            while True:
                if time.perf_counter() - start > POLL_BUDGET:
                    break               # the rest is handled by the next poll
                kind, job, payload = self._out.get_nowait()
                h = self._handlers.get(job)
                if h is None:
                    continue
                on_result, on_error, on_item, token = h
                if kind == "item":
                    if on_item and not token.cancelled:
                        on_item(payload)
                    continue
                del self._handlers[job]
                if kind == "result" and on_result and not token.cancelled:
                    on_result(payload)
                elif kind == "error":
                    if on_error:
                        on_error(payload)
                    else:
                        import sys
                        sys.stderr.write(getattr(payload, "__traceback_text__", repr(payload)) + "\n")
        except queue.Empty:
            pass
        try:
            self._after = self.root.after(self.POLL_MS, self._poll)
        except Exception:
            self._closed = True

    def idle(self) -> bool:
        """True when no task is waiting or running and every callback has been delivered."""
        return not self._handlers

    def close(self) -> None:
        self._closed = True
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except Exception:
                pass
        for q in self._lanes.values():
            q.put(None)
