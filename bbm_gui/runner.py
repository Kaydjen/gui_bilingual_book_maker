"""Running the engine as a child process: output splitting, progress and failure monitoring, stop and kill."""
import codecs
import datetime as dt
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

from . import engine

SHIM = engine.HELPERS / "shim.py"
MAXSEG = 64 * 1024
GUARD_ATTEMPT = 5  # a Retry attempt line with this number or higher ends the run (the next failure is cached as done)
STOP_CODES = {0, 130, 3221225786, -2, -15}

TQDM = re.compile(
    r"(?P<pct>\d{1,3})%\|[^|]*\|\s*(?P<n>[\d.]+[kMG]?)/(?P<total>[\d.]+[kMG]?)\s*\[(?P<el>[\d:]+)<(?P<eta>[\d:?]+)"
)
TRANSLATING = re.compile(r"^translating (?P<i>\d+)/(?P<n>\d+)\s*$")
RETRY = re.compile(r"Retry attempt (?P<n>\d+) due to")
FAILED = re.compile(r"Translation failed for this paragraph")
FATAL = re.compile(r"Translation disabled due to fatal error|Fatal translation error detected")
AUTH = re.compile(r"API key not valid|API_KEY_INVALID|UNAUTHENTICATED|PERMISSION_DENIED|\b401\b|\b403\b")
QUOTA = re.compile(r"\b429\b|RESOURCE_EXHAUSTED|quota", re.I)
GONE = re.compile(r"NOT_FOUND|no longer available|\b404\b")
DAILY =re.compile(r"PerDay", re.I)
SAVED = re.compile(r"^(?:Bilingual book saved: (?P<a>.+)|Bilingual EPUB saved beside the source file: (?P<b>.+))$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _num(text):
    mult = {"k": 1e3, "M": 1e6, "G": 1e9}.get(text[-1:], 1)
    return int(float(text.rstrip("kMG")) * mult)


class Splitter:
    """Raw bytes -> events. LF or CRLF ends a line; a lone CR ends a frame (a progress rewrite)."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        b = self.buf
        start = i = 0
        n = len(b)
        while i < n:
            c = b[i]
            if c == 10:
                out.append(("line", bytes(b[start:i]).decode("utf-8", "replace")))
                start = i + 1
            elif c == 13:
                if i + 1 >= n:
                    break
                if b[i + 1] == 10:
                    out.append(("line", bytes(b[start:i]).decode("utf-8", "replace")))
                    i += 1
                    start = i + 1
                else:
                    out.append(("frame", bytes(b[start:i]).decode("utf-8", "replace")))
                    start = i + 1
            i += 1
        del b[:start]
        while len(b) > MAXSEG:
            cut = MAXSEG
            while cut > 0 and (b[cut] & 0xC0) == 0x80:
                cut -= 1
            out.append(("line", bytes(b[:cut]).decode("utf-8", "replace")))
            del b[:cut]
        return out

    def flush(self):
        text = bytes(self.buf).decode("utf-8", "replace")
        self.buf.clear()
        return [("line", text)] if text else []


class Masker:
    def __init__(self, secrets):
        self.secrets = sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True)

    def __call__(self, text):
        for s in self.secrets:
            if s in text:
                text = text.replace(s, "********")
        return text


class Monitor:
    """Reads the engine's lines and keeps what the GUI shows: progress, retries, failures, saved path."""

    def __init__(self):
        self.n = self.total = 0
        self.elapsed = ""
        self.retry_attempt = 0
        self.retrying = False
        self.quota = False
        self.daily = False  # the 429 text names a per-day quota
        self.key_error = False
        self.failed = 0
        self.fatal = False
        self.saved = None

    def feed(self, stream, kind, text):
        """Return a guard reason ('quota', 'failed', 'key') when the run must stop, else None."""
        text = ANSI.sub("", text)
        if self.retrying and DAILY.search(text):  # the engine's console wraps the error text over several lines
            self.daily = True
        m = TQDM.search(text)
        if m and stream == "err":
            n, total = _num(m.group("n")), _num(m.group("total"))
            if n != self.n:
                self.retrying = False
                self.retry_attempt = 0
            self.n, self.total, self.elapsed = n, total, m.group("el")
            return None
        m = TRANSLATING.match(text)
        if m:
            self.n, self.total = int(m.group("i")), int(m.group("n"))
            self.retrying = False
            return None
        m = SAVED.match(text.strip())
        if m:
            self.saved = (m.group("a") or m.group("b")).strip()
            return None
        if FATAL.search(text):
            self.fatal = True
        m = RETRY.search(text)
        if m:
            self.retrying = True
            if DAILY.search(text):
                self.daily = True
            self.retry_attempt = max(self.retry_attempt, int(m.group("n")))
            if AUTH.search(text):
                self.key_error = True
                return "key"
            if GONE.search(text):
                return "model"
            if QUOTA.search(text):
                self.quota = True
                if self.retry_attempt >= GUARD_ATTEMPT:
                    return "quota"
            elif self.retry_attempt >= GUARD_ATTEMPT:
                return "failed"
            return None
        if FAILED.search(text):
            self.failed += 1
            return "failed"
        return None


def _us_pacific_offset(utc):
    """Hours from UTC for US Pacific time (DST from the second Sunday of March to the first Sunday of November)."""
    y = utc.year
    mar = dt.datetime(y, 3, 8)
    mar += dt.timedelta(days=(6 - mar.weekday()) % 7)
    nov = dt.datetime(y, 11, 1)
    nov += dt.timedelta(days=(6 - nov.weekday()) % 7)
    start = mar.replace(hour=10)  # 02:00 PST = 10:00 UTC
    end = nov.replace(hour=9)  # 02:00 PDT = 09:00 UTC
    naive = utc.replace(tzinfo=None)
    return -7 if start <= naive < end else -8


def quota_reset_utc(now=None):
    """The next midnight in US Pacific time (when the free daily quota resets), as an aware UTC datetime."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    off = _us_pacific_offset(now)
    pacific = now + dt.timedelta(hours=off)
    midnight = (pacific + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    off_then = _us_pacific_offset(midnight - dt.timedelta(hours=off))
    return (midnight - dt.timedelta(hours=off_then)).replace(tzinfo=dt.timezone.utc)


def local_hhmm(epoch):
    return dt.datetime.fromtimestamp(epoch).strftime("%H:%M")


def quota_reset_local(now=None):
    return quota_reset_utc(now).astimezone().strftime("%H:%M")


def classify(rc, stop_requested, killed, guard, monitor, out_ok):
    """(state, chip): state is finished / stopped / error; chip is a short word for the status area."""
    if killed:
        return "stopped", "Killed"
    if stop_requested and rc in STOP_CODES:
        if guard == "quota":
            return "stopped", "Quota " + quota_reset_local()
        if guard == "failed":
            return "stopped", "Failed %d" % max(monitor.failed, 1)
        if guard == "key":
            return "error", "Key"
        if guard == "model":
            return "error", "Model"
        return "stopped", ""
    if monitor.key_error and rc != 0:
        return "error", "Key"
    if monitor.fatal:
        return "error", "Error"
    if rc == 0 and monitor.saved and out_ok:
        return "finished", ("Failed %d" % monitor.failed) if monitor.failed else ""
    if rc == 0:
        return "error", "No output"
    return "error", "Exit %s" % rc


class Runner:
    def __init__(self):
        self.events = queue.Queue()
        self.proc = None
        self.stop_requested = False
        self.killed = False
        self.guard = None
        self._log = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, python, engine_root, args, env_extra, cwd, log_path, secrets):
        env = engine.child_env(env_extra)
        env["ENGINE_DIR"] = str(engine_root)
        cmd = [python, "-X", "utf8", "-B", str(SHIM), "--"] + list(args)
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = engine.NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        self.stop_requested = self.killed = False
        self.guard = None
        self._log = open(log_path, "ab")
        mask = Masker(secrets)
        self.proc = subprocess.Popen(
            cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, **kwargs
        )
        readers = [
            threading.Thread(target=self._read, args=("out", self.proc.stdout, mask), daemon=True),
            threading.Thread(target=self._read, args=("err", self.proc.stderr, mask), daemon=True),
        ]
        for t in readers:
            t.start()
        threading.Thread(target=self._wait, args=(readers,), daemon=True).start()

    def _read(self, stream, pipe, mask):
        sp = Splitter()
        fd = pipe.fileno()
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            for kind, text in sp.feed(data):
                self._emit(stream, kind, mask(text))
        for kind, text in sp.flush():
            self._emit(stream, kind, mask(text))

    def _emit(self, stream, kind, text):
        if kind == "line" and self._log:
            try:
                self._log.write((text + "\n").encode("utf-8", "replace"))
                self._log.flush()
            except (OSError, ValueError):
                pass
        self.events.put((stream, kind, text))

    def _wait(self, readers):
        rc = self.proc.wait()
        for t in readers:
            t.join(timeout=5)
        try:
            self._log.close()
        except (OSError, AttributeError):
            pass
        self.events.put(("exit", "exit", rc))

    def stop(self, guard=None):
        """Graceful stop: the engine saves its progress. Sent once."""
        if not self.running or self.stop_requested:
            return
        self.stop_requested = True
        self.guard = guard
        try:
            self.proc.stdin.write(b"STOP\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def kill(self):
        if not self.running:
            return
        self.killed = True
        pid = self.proc.pid
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=engine.NO_WINDOW)
        else:
            import signal

            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                self.proc.kill()


def run_tool(python, script, args, timeout=60):
    """Run a helper under the engine's Python and return its JSON answer."""
    import json

    proc = subprocess.run(
        [python, "-I", "-B", str(script)] + list(args), capture_output=True, timeout=timeout,
        creationflags=engine.NO_WINDOW, env=engine.child_env()
    )
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        return {"error": (proc.stderr or proc.stdout)[-300:].decode("utf-8", "replace")}
