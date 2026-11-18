"""One rotating log and the hooks that feed it. A hook never raises.

`<logs>/novelgui.log` (1 MB x 3) takes: uncaught exceptions of the main thread and of other threads, unraisable
errors, Qt and QML messages. `<logs>/fault.log` takes the faulthandler dump of a hard crash.
A slot exception is logged and the program goes on; it asks for a toast `Something went wrong · Details`, and the
same traceback more than 3 times in 10 s is one line with a count. Strict mode (NOVELGUI_STRICT=1, tests): any
exception or QML warning is recorded and the program exits with code 1.
"""

from __future__ import annotations

import faulthandler
import hashlib
import logging
import logging.handlers
import os
import sys
import threading
import time
import traceback
from pathlib import Path

LOG_NAME = "novelgui.log"
FAULT_NAME = "fault.log"
ENV_STRICT = "NOVELGUI_STRICT"
TOAST_TITLE = "Something went wrong"
TOAST_TEXT = "Details"
BURST_SECONDS = 10.0
BURST_FULL = 3

logger = logging.getLogger("novelgui")


class ErrorGate:
    """Rate limit: the first BURST_FULL occurrences of one traceback in BURST_SECONDS are reported in full, later
    ones are only counted; the count line comes with the next report after the window, or from `flush`."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._seen: dict = {}       # key -> [window start, count in window, suppressed]

    def note(self, text: str):
        """Returns (report in full?, count lines of windows that ended)."""
        now = self.clock()
        key = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
        lines = self._expire(now)
        entry = self._seen.get(key)
        if entry is None:
            entry = self._seen[key] = [now, 0, 0]
        entry[1] += 1
        if entry[1] <= BURST_FULL:
            return True, lines
        entry[2] += 1
        return False, lines

    def flush(self) -> list:
        return self._expire(self.clock())

    def _expire(self, now: float) -> list:
        lines = []
        for key, (start, _count, suppressed) in list(self._seen.items()):
            if now - start > BURST_SECONDS:
                if suppressed:
                    lines.append("The same error repeated %d more times in %d s" % (suppressed, BURST_SECONDS))
                del self._seen[key]
        return lines


class RuntimeLog:
    def __init__(self, logs_dir, strict=None):
        self.dir = Path(logs_dir)
        self.path = self.dir / LOG_NAME
        self.fault_path = self.dir / FAULT_NAME
        self.strict = (os.environ.get(ENV_STRICT) == "1") if strict is None else strict
        self.failures: list = []            # strict mode: what was recorded
        self.gate = ErrorGate()
        self.toast_handler = None           # callable(title, text, route), set by the shell
        self.exit_handler = None            # callable(code), set once the application exists
        self._fault_file = None
        self._lock = threading.Lock()

    # -- setup ----------------------------------------------------------------------------------------------
    def install(self) -> None:
        logging.raiseExceptions = False
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(self.path, maxBytes=1_000_000, backupCount=3,
                                                           encoding="utf-8", delay=True)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        except OSError:
            pass
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            self._fault_file = open(self.fault_path, "a", encoding="utf-8")
            faulthandler.enable(file=self._fault_file, all_threads=True)
        except (OSError, RuntimeError, ValueError):
            self._fault_file = None
        sys.excepthook = self.on_exception
        threading.excepthook = self.on_thread_exception
        sys.unraisablehook = self.on_unraisable
        try:
            from PySide6.QtCore import qInstallMessageHandler
            qInstallMessageHandler(self.on_qt_message)
        except Exception:
            pass

    def close(self) -> None:
        try:
            for line in self.gate.flush():
                logger.error(line)
            for h in list(logger.handlers):
                h.flush()
                h.close()
                logger.removeHandler(h)
            if self._fault_file is not None:
                faulthandler.disable()
                self._fault_file.close()
                self._fault_file = None
        except Exception:
            pass

    # -- hooks ----------------------------------------------------------------------------------------------
    def on_exception(self, exc_type, exc, tb) -> None:
        try:
            self._report("Uncaught exception", "".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass

    def on_thread_exception(self, args) -> None:
        try:
            name = args.thread.name if args.thread else "?"
            text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            self._report("Uncaught exception in thread %s" % name, text)
        except Exception:
            pass

    def on_unraisable(self, args) -> None:
        try:
            text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            self._report("Unraisable exception (%s)" % (args.err_msg or "no message"), text)
        except Exception:
            pass

    def on_qt_message(self, mode, context, message) -> None:
        try:
            name = getattr(mode, "name", str(mode))
            file = getattr(context, "file", None) or ""
            where = (" (%s:%s)" % (file, context.line)) if file else ""
            line = "Qt %s: %s%s" % (name, message, where)
            is_error = name in ("QtCriticalMsg", "QtFatalMsg", "QtSystemMsg")
            category = getattr(context, "category", "") or ""
            is_qml = ".qml" in file or ".qml" in message or category.startswith("qml")
            if is_error:
                logger.error(line)
                self._strict_fail(line)
            elif name == "QtWarningMsg":
                logger.warning(line)
                if is_qml:
                    self._strict_fail(line)
            elif name == "QtInfoMsg":
                logger.info(line)
            else:
                logger.debug(line)
        except Exception:
            pass

    # -- reporting ------------------------------------------------------------------------------------------
    def _report(self, what: str, text: str) -> None:
        with self._lock:
            full, lines = self.gate.note(text)
        for line in lines:
            logger.error(line)
        if full:
            logger.error("%s\n%s", what, text)
            self._toast()
        tail = text.strip().splitlines()[-1] if text.strip() else ""
        self._strict_fail("%s: %s" % (what, tail))

    def _toast(self) -> None:
        handler = self.toast_handler
        if handler is not None:
            try:
                handler(TOAST_TITLE, TOAST_TEXT, "details")
            except Exception:
                pass

    def _strict_fail(self, text: str) -> None:
        if not self.strict:
            return
        self.failures.append(text)
        logger.error("STRICT: %s", text)
        handler = self.exit_handler
        if handler is not None:
            try:
                handler(1)
            except Exception:
                pass

    def info(self, text: str, *args) -> None:
        try:
            logger.info(text, *args)
        except Exception:
            pass
