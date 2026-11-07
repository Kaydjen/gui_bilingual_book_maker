"""Running the engine as a child process: output splitting, progress and failure monitoring, stop and kill."""
import codecs
import datetime as dt
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import engine

SHIM = engine.HELPERS / "shim.py"
MAXSEG = 64 * 1024
GUARD_ATTEMPT = 5  # a Retry attempt line with this number or higher ends the run (the next failure is cached as done)
BLOCK_STREAK = 5  # paragraphs in a row that the model answered with nothing: the run stops (it is not a quota problem)
UNKNOWN_ATTEMPT = 3  # an unrecognised 429 is not worth more retries
MINUTE_ATTEMPT = 6  # a per-minute 429 that the engine rides out in place: its back-off (1+2+4+8+16 s) covers a window
BLOCK_CAP = 4096  # longest error block kept for classification
MIN_STEP_GAP = 0.3  # seconds: a faster progress step was a paragraph served from the checkpoint
STOP_CODES = {0, 130, 3221225786, -2, -15}

TQDM = re.compile(
    r"(?P<pct>\d{1,3})%\|[^|]*\|\s*(?P<n>[\d.]+[kMG]?)/(?P<total>[\d.]+[kMG]?)\s*\[(?P<el>[\d:]+)<(?P<eta>[\d:?]+)"
)
TRANSLATING = re.compile(r"^translating (?P<i>\d+)/(?P<n>\d+)\s*$")
RETRY = re.compile(r"Retry attempt (?P<n>\d+) due to")
FAILED = re.compile(r"Translation failed for this paragraph")
# The engine warns on every resume that the checkpoint carries no run record: the checkpoint repair drops it on purpose,
# so the warning says nothing to the user (it stays in the log file).
NOISE = re.compile(r"the resume cache .{0,300}? was written before runs recorded", re.I)
FATAL = re.compile(r"Translation disabled due to fatal error|Fatal translation error detected")
AUTH = re.compile(r"API key not valid|API_KEY_INVALID|UNAUTHENTICATED|PERMISSION_DENIED|\b401\b|\b403\b")
QUOTA = re.compile(r"\b429\b|RESOURCE_EXHAUSTED|quota", re.I)
GONE = re.compile(r"NOT_FOUND|no longer available|\b404\b")
EMPTY = re.compile(r"AttributeError|NoneType|Invalid batch|blocked|SAFETY|PROHIBITED_CONTENT|finish_reason", re.I)
DAILY = re.compile(r"PerDay|per day", re.I)
PER_MINUTE = re.compile(r"PerMinute|per minute", re.I)
API_ERROR = re.compile(r"due to (?:\w+\.)*(?:ClientError|ServerError|APIError)\b")
STATUS = re.compile(r"Error: (\d{3})\b")
LIMIT = re.compile(r"limit: (\d+)")
RETRY_IN = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", re.I)
RETRY_DELAY = re.compile(r"'retryDelay': '(\d+)s'")
TERMINATOR = re.compile(r"\((?:rotating key|switching model)\)\s*$")
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


class Event:
    """One classified engine error block. kind: minute, day, zero, unknown, busy, notfound, invalid, content.
    `empty` marks a content error that is the model's own empty or blocked answer (the engine reads a missing text as
    an AttributeError): it does not depend on the key or the quota, so no key or model is blamed for it."""

    def __init__(self, kind, attempt=1, delay=None, limit=None, empty=False):
        self.kind = kind
        self.attempt = attempt
        self.delay = delay  # seconds the server asked to wait, if it said
        self.limit = limit  # the quota value named in the text
        self.empty = empty

    def __repr__(self):
        return "Event(%s, attempt=%s, delay=%s, limit=%s)" % (self.kind, self.attempt, self.delay, self.limit)


def _seconds(text):
    m = RETRY_IN.search(text)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))
    m = RETRY_DELAY.search(text)
    return float(m.group(1)) if m else None


def classify_block(text, attempt=1):
    """Classify one retry block (all its wrapped lines joined by single spaces) into an Event."""
    code = STATUS.search(text)
    code = int(code.group(1)) if code else 0
    limit = LIMIT.search(text)
    limit = int(limit.group(1)) if limit else None
    delay = _seconds(text)
    if code in (400, 401, 403) and AUTH.search(text) or code in (401, 403):
        return Event("invalid", attempt, delay, limit)
    if code == 404 or GONE.search(text) and code != 429:
        return Event("notfound", attempt, delay, limit)
    if code == 429 or code == 0 and QUOTA.search(text):
        if limit == 0 or "'quotaValue': '0'" in text:
            return Event("zero", attempt, delay, limit)
        if DAILY.search(text):
            return Event("day", attempt, delay, limit)
        if PER_MINUTE.search(text):
            return Event("minute", attempt, delay, limit)
        return Event("unknown", attempt, delay, limit)
    if code in (500, 502, 503, 504) or "UNAVAILABLE" in text:
        return Event("busy", attempt, delay, limit)
    return Event("content", attempt, delay, limit, empty=bool(EMPTY.search(text)))


class Monitor:
    """Reads the engine's lines and keeps what the GUI shows: progress, retries, failures, saved path.

    The engine prints a retry as one block that its console wraps over several lines and that ends with
    "(rotating key)" or "(switching model)". The lines are joined and classified when the block is complete.
    `policy(event)` says whether a per-minute 429 is worth a stop (hop to another pair) or is better waited out."""

    def __init__(self, policy=None, step=1, clock=time.monotonic):
        self.n = self.total = 0
        self.elapsed = ""
        self.eta = ""
        self.step = max(step, 1)  # paragraphs per request: the largest progress step that is one request
        self.clock = clock
        self.gaps = []  # seconds between progress steps that were one clean request each
        self._tq_n = self._tq_t = None
        self._dirty = False  # a retry happened since the last progress step
        self.retry_attempt = 0
        self.retrying = False
        self.quota = False
        self.daily = False  # the 429 is a per-day quota
        self.key_error = False
        self.failed = 0
        self.blocked = 0  # paragraphs that failed after empty or blocked answers
        self._empty_seen = False  # an empty-answer retry happened for the paragraph in progress
        self._streak = 0  # blocked paragraphs in a row
        self._fail_pending = False  # the next progress step is the failed paragraph itself
        self.fatal = False
        self.saved = None
        self.policy = policy or (lambda event: True)
        self.event = None  # the last classified block
        self.events = []
        self._buf = None  # lines of the block being read
        self._buf_stream = None
        self._buf_attempt = 0

    def feed(self, stream, kind, text):
        """Return a guard reason ('quota', 'busy', 'failed', 'key', 'model') when the run must stop, else None."""
        text = ANSI.sub("", text)
        guard = None
        if self._buf is not None and stream == self._buf_stream:  # the other stream does not end a block
            if kind == "line" and not RETRY.search(text) and not self._ends_block(text):
                self._add(text)
                if TERMINATOR.search(text) or sum(map(len, self._buf)) > BLOCK_CAP:
                    return self._close()
                return None
            guard = self._close()  # a new block or a line that cannot belong to this one
        m = TQDM.search(text)
        if m and stream == "err":
            n, total = _num(m.group("n")), _num(m.group("total"))
            self._step(n)
            if n != self.n:
                if self._fail_pending:
                    self._fail_pending = False
                else:  # a paragraph went through without a failure
                    self._streak = 0
                    self._empty_seen = False
                self.retrying = False
                self.retry_attempt = 0
            self.n, self.total, self.elapsed, self.eta = n, total, m.group("el"), m.group("eta")
            return guard
        m = TRANSLATING.match(text)
        if m:
            self.n, self.total = int(m.group("i")), int(m.group("n"))
            self.retrying = False
            return guard
        m = SAVED.match(text.strip())
        if m:
            self.saved = (m.group("a") or m.group("b")).strip()
            return guard
        if FATAL.search(text):
            self.fatal = True
        m = RETRY.search(text)
        if m and kind == "line":
            self.retrying = self._dirty = True
            self.retry_attempt = max(self.retry_attempt, int(m.group("n")))
            self._buf = []
            self._buf_stream = stream
            self._buf_attempt = int(m.group("n"))
            self._add(text)
            if TERMINATOR.search(text) or not API_ERROR.search(text):
                return self._close() or guard  # one line, or an error that is not an API block
            return guard
        if FAILED.search(text):
            self.failed += 1
            if self._empty_seen:  # the model gave nothing for this paragraph: go on, count it, stop on a streak
                self._empty_seen = False
                self._fail_pending = True
                self.blocked += 1
                self._streak += 1
                return "blocked" if self._streak >= BLOCK_STREAK else guard
            return "failed"
        return guard

    def _step(self, n):
        """A progress frame: remember how long the last request took if the step was exactly one clean request."""
        if n == self._tq_n:
            return
        now = self.clock()
        if self._tq_n is not None and 0 < n - self._tq_n <= self.step and not self._dirty:
            gap = now - self._tq_t
            if gap >= MIN_STEP_GAP:
                self.gaps.append(gap)
                del self.gaps[:-100]
        self._tq_n, self._tq_t, self._dirty = n, now, False

    @staticmethod
    def _ends_block(text):
        return bool(TRANSLATING.match(text) or SAVED.match(text.strip()))

    def _add(self, text):
        self._buf.append(text.strip())

    def flush(self):
        """The process ended: classify a block that never got its terminator."""
        return self._close() if self._buf is not None else None

    def _close(self):
        text = " ".join(self._buf or [])
        attempt = self._buf_attempt
        self._buf = None
        ev = classify_block(text, attempt)
        return self._decide(ev)

    def _decide(self, ev):
        self.event = ev
        self.events.append(ev)
        k = ev.kind
        if ev.empty and k == "content":
            self._empty_seen = True
            return None  # the engine's own seven attempts decide; the failed paragraph is counted when it is given up
        if k == "invalid":
            self.key_error = True
            return "key"
        if k == "notfound":
            return "model"
        if k in ("day", "zero"):
            self.quota = True
            self.daily = k == "day"
            return "quota"
        if k == "minute":
            self.quota = True
            return "quota" if ev.attempt >= MINUTE_ATTEMPT or self.policy(ev) else None
        if k == "unknown":
            self.quota = True
            return "quota" if ev.attempt >= UNKNOWN_ATTEMPT else None
        if k == "busy":
            return "busy" if ev.attempt >= GUARD_ATTEMPT else None
        return "failed" if ev.attempt >= GUARD_ATTEMPT else None


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
    """The next midnight in US Pacific time (when the free daily quota resets), as an aware UTC datetime.
    BBM_GUI_RESET_AT (epoch seconds) replaces it so that a test does not have to wait for the real midnight."""
    fixed = os.environ.get("BBM_GUI_RESET_AT")
    if fixed:
        try:
            return dt.datetime.fromtimestamp(float(fixed), dt.timezone.utc)
        except ValueError:
            pass
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    off = _us_pacific_offset(now)
    pacific = now + dt.timedelta(hours=off)
    midnight = (pacific + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    off_then = _us_pacific_offset(midnight - dt.timedelta(hours=off))
    return (midnight - dt.timedelta(hours=off_then)).replace(tzinfo=dt.timezone.utc)


DAY_MARGIN = 60  # seconds after the reset before a used-up pair is tried again


def day_return(now=None):
    """Epoch when a pair used up for the day is usable again."""
    margin = 0 if os.environ.get("BBM_GUI_RESET_AT") else DAY_MARGIN
    return quota_reset_utc(now).timestamp() + margin


def clock(seconds):
    """m:ss for a countdown."""
    s = max(int(seconds + 0.999), 0)
    return "%d:%02d" % divmod(s, 60)


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
        if guard == "busy":
            return "stopped", "Busy"
        if guard == "blocked":
            return "stopped", "Blocked"
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
        return "finished", ""
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
