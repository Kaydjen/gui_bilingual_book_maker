"""One app instance per user (window_spec 14.9): a QLockFile is the arbiter, a QLocalServer carries the request.

The first instance holds the lock and listens. A second start connects, sends one JSON line
`{"cmd":"raise","paths":[...]}`, waits up to 2 s for `{"ok":true,"pid":N}`, hands the foreground right to the first
instance and exits. No answer in 2 s (or a lock held but no server): `NOT_ANSWERING`; never a second window.
"""

from __future__ import annotations

import json
import os
import time

from PySide6.QtCore import QCoreApplication, QLockFile, QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .. import platform

FIRST = "first"
FORWARDED = "forwarded"
NOT_ANSWERING = "not_answering"
ANSWER_SECONDS = 2.0
MAX_REQUEST = 1 << 20


class InstanceLock:
    """The lock file. Stale detection by process id only (a held lock is never old by the clock)."""

    def __init__(self, path):
        self.path = str(path)
        self.lock = None
        self.error = None

    def acquire(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError:
            pass
        lock = QLockFile(self.path)
        lock.setStaleLockTime(0)
        if lock.tryLock(0):
            self.lock = lock
            return True
        self.error = lock.error()
        return False

    def release(self) -> None:
        if self.lock is not None:
            self.lock.unlock()
            self.lock = None


def forward(name: str, paths: list, seconds: float = ANSWER_SECONDS) -> str:
    """Send the raise request to the first instance. FORWARDED when it answered, else NOT_ANSWERING."""
    if QCoreApplication.instance() is None:
        QCoreApplication(["novel"])
    deadline = time.monotonic() + seconds

    def left_ms() -> int:
        return max(1, int((deadline - time.monotonic()) * 1000))

    sock = QLocalSocket()
    while True:
        sock.connectToServer(name)
        if sock.waitForConnected(min(300, left_ms())):
            break
        sock.abort()
        if time.monotonic() >= deadline:
            return NOT_ANSWERING
        time.sleep(0.05)
    request = json.dumps({"cmd": "raise", "paths": list(paths)}) + "\n"
    sock.write(request.encode("utf-8"))
    sock.waitForBytesWritten(min(1000, left_ms()))
    buf = b""
    while b"\n" not in buf:
        if time.monotonic() >= deadline or not sock.waitForReadyRead(left_ms()):
            if sock.bytesAvailable() == 0:
                sock.abort()
                return NOT_ANSWERING
        buf += bytes(sock.readAll())
    sock.abort()
    try:
        answer = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except ValueError:
        return NOT_ANSWERING
    if not (isinstance(answer, dict) and answer.get("ok") is True):
        return NOT_ANSWERING
    platform.allow_set_foreground(int(answer.get("pid") or 0))
    return FORWARDED


class InstanceServer(QObject):
    """The first instance's side: answers each request line with {"ok":true,"pid":N} after `on_raise(paths)`."""

    def __init__(self, name: str, on_raise, parent=None):
        super().__init__(parent)
        self.name = name
        self.on_raise = on_raise
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self._buffers: dict = {}

    def listen(self) -> bool:
        QLocalServer.removeServer(self.name)
        return self.server.listen(self.name)

    def error_text(self) -> str:
        return self.server.errorString()

    def close(self) -> None:
        self.server.close()

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self._buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _drop(self, sock) -> None:
        self._buffers.pop(sock, None)
        sock.deleteLater()

    def _read(self, sock) -> None:
        buf = self._buffers.get(sock, b"") + bytes(sock.readAll())
        self._buffers[sock] = buf
        if b"\n" not in buf and len(buf) < MAX_REQUEST:
            return
        self._buffers[sock] = b""
        ok = False
        try:
            request = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
            if isinstance(request, dict) and request.get("cmd") == "raise":
                paths = [p for p in request.get("paths") or [] if isinstance(p, str)]
                self.on_raise(paths)
                ok = True
        except Exception:
            from . import log
            log.logger.exception("Bad request to the running instance")
        answer = {"ok": ok, "pid": os.getpid()}
        sock.write((json.dumps(answer) + "\n").encode("utf-8"))
        sock.flush()
        sock.disconnectFromServer()
