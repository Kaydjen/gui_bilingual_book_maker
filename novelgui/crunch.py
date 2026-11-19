"""The helper process for heavy book work: `python -m novelgui.crunch [--parent PID] [--idle SECONDS]`.

CPU-heavy pure-Python reading of a book (chapter scan, term scan, occurrences, export build, problem and check
readers) runs here, so the window's interpreter stays free for the screen. The protocol is JSON lines
(`novelgui.wire`) over stdin / stdout:

  in   {"id": 7, "task": "scan_book", "args": {...}}      run a task (one at a time, in order)
       {"cancel": 7}                                      cancel task 7 (it stops between chapters)
       {"want": 7, "range": [first, last]}                the rows the screen shows now (chapter scan)
  out  {"hello": {"pid": ..., "package": ...}}           once, at start
       {"id": 7, "item": [...]}                           progress items, batched (<= 500 or 80 ms)
       {"id": 7, "result": ...} | {"id": 7, "error": "...", "type": "...", "trace": "..."}
       {"bye": "idle"}                                    before it exits after `--idle` seconds without work

It exits by itself when stdin closes or the parent process is gone. It never imports PySide6. The task
functions are the facade's plain functions, callable in-process too (`run_task_here`).
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
import traceback

from . import wire
from .facade import books, checks, terms
from .lanes import Token, Want

BATCH_ROWS = 500
BATCH_SECONDS = 0.08
IDLE_SECONDS = 60.0
PARENT_CHECK = 1.0


def _ping(ctx, wait: float = 0.0) -> dict:
    end = time.monotonic() + wait
    while time.monotonic() < end and not ctx.cancelled:
        time.sleep(0.01)
    return {"pid": os.getpid(), "package": os.path.dirname(os.path.abspath(__file__)),
            "pyside": any(m == "PySide6" or m.startswith("PySide6.") for m in sys.modules)}


def _scan_book(ctx, series_path, book, first=0, last=60):
    want = ctx.want(first, last) if hasattr(ctx, "want") else Want(first, last)
    return books.scan_chapters_task(ctx, series_path, book, want)


TASKS = {
    "ping": _ping,
    "scan_book": _scan_book,
    "term_scan": terms.term_scan_task,
    "term_keys": terms.term_keys_in_chapters_task,
    "term_names": terms.term_names_task,
    "term_places": terms.term_places_task,
    "occurrences": books.find_occurrences_task,
    "export": books.export_piece_task,
    "problems": checks.problems_task,
    "check": checks.check_task,
}


# ---------------------------------------------------------------- the parent
def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x00100000 | 0x1000, False, pid)     # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5                  # access denied: it exists
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102        # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _Parent:
    def __init__(self, pid: int):
        self.pid = pid
        self._next = 0.0
        self._alive = True

    def alive(self) -> bool:
        if not self.pid or not self._alive:
            return self._alive
        now = time.monotonic()
        if now >= self._next:
            self._next = now + PARENT_CHECK
            if os.name != "nt" and os.getppid() != self.pid:
                self._alive = False
            elif not pid_alive(self.pid):
                self._alive = False
        return self._alive


# ---------------------------------------------------------------- output
class _Out:
    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, msg) -> None:
        data = wire.dumps(msg)
        with self._lock:
            try:
                self._stream.write(data)
                self._stream.flush()
            except (OSError, ValueError):
                os._exit(0)             # the window is gone: nobody reads


class _ChildCtx:
    def __init__(self, out: _Out, tid, token: Token, parent: _Parent, wants: dict):
        self._out = out
        self._id = tid
        self.token = token
        self._parent = parent
        self._wants = wants
        self._batch: list = []
        self._since = time.perf_counter()

    @property
    def cancelled(self) -> bool:
        if not self._parent.alive():
            self.token.cancel()
        return self.token.cancelled

    def want(self, first, last) -> Want:
        w = self._wants.get(self._id)
        if w is None:
            w = self._wants[self._id] = Want(first, last)
        return w

    def emit(self, item) -> None:
        if not self._batch:
            self._since = time.perf_counter()
        self._batch.append(item)
        if len(self._batch) >= BATCH_ROWS or time.perf_counter() - self._since >= BATCH_SECONDS:
            self.flush()

    def breathe(self) -> None:
        if self._batch and time.perf_counter() - self._since >= BATCH_SECONDS:
            self.flush()

    def flush(self) -> None:
        if self._batch:
            batch, self._batch = self._batch, []
            self._out.send({"id": self._id, "item": batch})


def run_task_here(name: str, ctx, args: dict):
    """Run one task of the helper in this process (tests; the same function the child runs)."""
    return TASKS[name](ctx, **args)


# ---------------------------------------------------------------- main loop
def serve(stdin, stdout, parent_pid: int = 0, idle: float = IDLE_SECONDS) -> int:
    out = _Out(stdout)
    parent = _Parent(parent_pid)
    inbox: queue.Queue = queue.Queue()
    tokens: dict = {}
    wants: dict = {}
    lock = threading.Lock()

    def read():
        for raw in stdin:
            if not raw.strip():
                continue
            try:
                msg = wire.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if "cancel" in msg:
                with lock:
                    tok = tokens.get(msg["cancel"])
                    if tok is None:
                        tok = tokens[msg["cancel"]] = Token()
                tok.cancel()
            elif "want" in msg:
                rng = msg.get("range") or (0, 60)
                w = wants.get(msg["want"])
                if w is None:
                    wants[msg["want"]] = Want(int(rng[0]), int(rng[1]))
                else:
                    w.set(int(rng[0]), int(rng[1]))
            else:
                inbox.put(msg)
        # stdin closed: the window is gone or killed this helper (through a launcher, the kill reaches only the
        # launcher). Nobody reads the answers; leave at once, even in the middle of a task, so every book handle
        # this process holds is released now.
        os._exit(0)

    threading.Thread(target=read, daemon=True, name="crunch-in").start()
    out.send({"hello": {"pid": os.getpid(), "package": os.path.dirname(os.path.abspath(__file__))}})
    last_work = time.monotonic()
    while True:
        try:
            msg = inbox.get(timeout=0.25)
        except queue.Empty:
            if not parent.alive():
                return 0
            if time.monotonic() - last_work >= idle:
                out.send({"bye": "idle"})
                return 0
            continue
        if msg is None:
            return 0
        tid = msg.get("id")
        with lock:
            token = tokens.setdefault(tid, Token())
        ctx = _ChildCtx(out, tid, token, parent, wants)
        try:
            if token.cancelled:
                raise RuntimeError("cancelled")
            fn = TASKS.get(msg.get("task"))
            if fn is None:
                raise ValueError("unknown task %r" % msg.get("task"))
            result = fn(ctx, **(msg.get("args") or {}))
            ctx.flush()
            out.send({"id": tid, "result": result})
        except Exception as exc:
            ctx.flush()
            out.send({"id": tid, "error": str(exc) or type(exc).__name__, "type": type(exc).__name__,
                      "trace": traceback.format_exc()})
        finally:
            with lock:
                tokens.pop(tid, None)
            wants.pop(tid, None)
        if not parent.alive():
            return 0
        last_work = time.monotonic()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="novelgui.crunch")
    ap.add_argument("--parent", type=int, default=0)
    ap.add_argument("--idle", type=float, default=IDLE_SECONDS)
    a = ap.parse_args(argv)
    proto = sys.stdout.buffer
    sys.stdout = sys.stderr             # a stray print never corrupts the protocol
    return serve(sys.stdin.buffer, proto, a.parent, a.idle)


if __name__ == "__main__":
    code = main()
    try:
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    os._exit(code)      # the stdin reader thread may sit in a blocking read: no interpreter shutdown under it
