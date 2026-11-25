"""GUI side of the helper process (`novelgui.crunch`): starts it lazily on a QProcess and talks JSON lines.

`submit(task, args, on_result, on_error, on_item, group)` has the shape of `Lanes.submit`; callbacks run on the
GUI thread (QProcess signals, no polling). Items arrive one by one to `on_item` even though the child sends them
in batches.

- Start: on first use; writes wait until the process has started.
- Cancel: the process is killed (that releases every book it holds open) and started again for the tasks that
  are still waiting; a cancelled or superseded task never reports.
- Idle: the child exits after `idle` seconds without work and says so (`bye`); tasks sent meanwhile are resent.
- Crash or kill from outside: every task in flight gets `on_error(CrunchError)`; the next use starts a new one.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment

from . import wire
from .lanes import Token

log = logging.getLogger("novelgui.crunch")
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class CrunchError(RuntimeError):
    def __init__(self, message: str, kind: str = "", trace: str = ""):
        super().__init__(message)
        self.kind = kind
        self.__traceback_text__ = trace or message


class CrunchToken(Token):
    def __init__(self, client: "CrunchClient", tid: int):
        super().__init__()
        self._client = client
        self.id = tid

    def cancel(self) -> None:
        if not self.cancelled:
            super().cancel()
            self._client._cancel(self.id)


class _Task:
    __slots__ = ("id", "task", "args", "on_result", "on_error", "on_item", "token", "group", "gen", "sent", "want")

    def __init__(self, tid, task, args, on_result, on_error, on_item, token, group, gen):
        self.id, self.task, self.args = tid, task, args
        self.on_result, self.on_error, self.on_item = on_result, on_error, on_item
        self.token, self.group, self.gen = token, group, gen
        self.sent = False
        self.want = None


def default_python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "python.exe":
        w = exe.with_name("pythonw.exe")       # no console window for the helper
        if w.is_file():
            return str(w)
    return str(exe)


class CrunchClient(QObject):
    def __init__(self, python: str | None = None, package_root=None, idle: float = 60.0, parent=None):
        super().__init__(parent)
        self.python = python or default_python()
        self.package_root = str(package_root or PACKAGE_ROOT)
        self.idle = idle
        self._proc: QProcess | None = None
        self._ready = False
        self._buf = b""
        self._pending: dict[int, _Task] = {}
        self._gens: dict[str, tuple[int, CrunchToken]] = {}
        self._next = 1
        self._expected: set = set()     # processes this side killed or saw say `bye`
        self.child_pid = 0
        self.child_package = ""
        self.starts = 0

    # ------------------------------------------------------------- public
    def submit(self, task: str, args: dict | None = None, on_result=None, on_error=None, on_item=None,
               group: str | None = None) -> CrunchToken:
        tid = self._next
        self._next += 1
        token = CrunchToken(self, tid)
        gen = 0
        if group is not None:
            prev = self._gens.get(group)
            if prev is not None:
                prev[1].cancel()
            gen = (prev[0] + 1) if prev else 1
            self._gens[group] = (gen, token)
        t = _Task(tid, task, dict(args or {}), on_result, on_error, on_item, token, group, gen)
        self._pending[tid] = t
        self._ensure()
        if self._ready:
            self._send(t)
        return token

    def want(self, token: CrunchToken, first: int, last: int) -> None:
        """The rows the screen shows now (for a running chapter scan)."""
        t = self._pending.get(token.id)
        if t is None:
            return
        t.want = (int(first), int(last))
        if t.sent and self._ready:
            self._write({"want": t.id, "range": [t.want[0], t.want[1]]})

    def idle_now(self) -> bool:
        return not self._pending

    def running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def close(self) -> None:
        """Stop the helper (app exit). Waiting tasks are dropped silently; returns once the process is gone."""
        for t in self._pending.values():
            Token.cancel(t.token)
        self._pending.clear()
        procs = list(self._expected) + ([self._proc] if self._proc is not None else [])
        self._proc = None
        self._ready = False
        self._expected.clear()
        for p in procs:
            for sig in (p.started, p.readyReadStandardOutput, p.readyReadStandardError, p.finished, p.errorOccurred):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            try:
                p.kill()
                p.waitForFinished(2000)
                p.deleteLater()
            except RuntimeError:
                pass

    # ------------------------------------------------------------- process
    def _ensure(self) -> None:
        if self._proc is not None:
            return
        p = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        old = env.value("PYTHONPATH", "")
        env.insert("PYTHONPATH", self.package_root + (os.pathsep + old if old else ""))
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(self.package_root)
        p.setProgram(self.python)
        p.setArguments(["-m", "novelgui.crunch", "--parent", str(os.getpid()), "--idle", str(self.idle)])
        p.started.connect(lambda p=p: self._started(p))
        p.readyReadStandardOutput.connect(lambda p=p: self._read(p))
        p.readyReadStandardError.connect(lambda p=p: self._stderr(p))
        p.finished.connect(lambda code, status, p=p: self._finished(p, code))
        p.errorOccurred.connect(lambda err, p=p: self._failed(p, err))
        self._proc = p
        self._ready = False
        self._buf = b""
        self.starts += 1
        p.start()

    def _started(self, p: QProcess) -> None:
        if p is not self._proc:
            return
        self._ready = True
        for t in list(self._pending.values()):
            if not t.sent:
                self._send(t)

    def _send(self, t: _Task) -> None:
        t.sent = True
        self._write({"id": t.id, "task": t.task, "args": t.args})
        if t.want is not None:
            self._write({"want": t.id, "range": [t.want[0], t.want[1]]})

    def _write(self, msg) -> None:
        if self._proc is not None:
            self._proc.write(wire.dumps(msg))

    def _kill(self) -> None:
        p = self._proc
        self._proc = None
        self._ready = False
        if p is not None:
            self._expected.add(p)
            p.kill()

    def release(self) -> None:
        """Kill the helper now and wait for it: every zip handle it holds goes with it (a move or a delete of a series needs
        them closed on Windows). A task still in flight is sent again to a fresh helper."""
        p = self._proc
        if p is None:
            return
        self._kill()
        p.waitForFinished(2000)
        for t in self._pending.values():
            t.sent = False
        if self._pending:
            self._ensure()

    def _cancel(self, tid: int) -> None:
        t = self._pending.pop(tid, None)
        if t is None or not t.sent:
            return
        self._kill()
        for other in self._pending.values():
            other.sent = False
        if self._pending:
            self._ensure()

    def _stderr(self, p: QProcess) -> None:
        data = bytes(p.readAllStandardError().data()).decode("utf-8", "replace").strip()
        if data:
            log.warning("helper: %s", data[-4000:])

    def _read(self, p: QProcess) -> None:
        if p is not self._proc:
            p.readAllStandardOutput()
            return
        self._buf += bytes(p.readAllStandardOutput().data())
        self._read_lines(p)

    def _read_lines(self, p: QProcess) -> None:
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                return
            line, self._buf = self._buf[:nl], self._buf[nl + 1:]
            if line.strip():
                try:
                    self._handle(p, wire.loads(line))
                except Exception:
                    log.exception("helper reply could not be handled")

    def _live(self, t: _Task) -> bool:
        if t.token.cancelled:
            return False
        return t.group is None or self._gens.get(t.group, (0,))[0] == t.gen

    def _handle(self, p: QProcess, msg) -> None:
        if not isinstance(msg, dict):
            return
        if "hello" in msg:
            self.child_pid = int(msg["hello"].get("pid") or 0)
            self.child_package = str(msg["hello"].get("package") or "")
            return
        if "bye" in msg:
            self._expected.add(p)
            return
        tid = msg.get("id")
        if "item" in msg:
            t = self._pending.get(tid)
            if t is not None and t.on_item is not None and self._live(t):
                for item in msg["item"]:
                    t.on_item(item)
                    if not self._live(t):
                        break
            return
        t = self._pending.pop(tid, None)
        if t is None or not self._live(t):
            return
        if "result" in msg:
            if t.on_result is not None:
                t.on_result(msg["result"])
        elif "error" in msg:
            exc = CrunchError(str(msg["error"]), str(msg.get("type") or ""), str(msg.get("trace") or ""))
            if t.on_error is not None:
                t.on_error(exc)
            else:
                log.error("helper task %s failed: %s", t.task, exc.__traceback_text__)

    def _failed(self, p: QProcess, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self._finished(p, -1)

    def _finished(self, p: QProcess, code: int) -> None:
        try:
            rest = bytes(p.readAllStandardOutput().data())
        except RuntimeError:            # the process object is gone already (app exit)
            self._expected.discard(p)
            return
        if p is self._proc and rest:
            self._buf += rest
            self._read_lines(p)
        expected = p in self._expected
        self._expected.discard(p)
        current = p is self._proc
        if current:
            self._proc = None
            self._ready = False
        p.deleteLater()
        if expected:
            if current:
                for t in self._pending.values():
                    t.sent = False
            if self._pending and self._proc is None:
                self._ensure()
            return
        if not current:
            return
        lost = list(self._pending.values())
        for t in lost:
            self._pending.pop(t.id, None)
            if self._live(t) and t.on_error is not None:
                t.on_error(CrunchError("The helper process stopped unexpectedly (exit code %s)." % code,
                                       "HelperStopped"))
