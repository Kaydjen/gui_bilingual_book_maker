"""In-process fake of the Gemini generateContent API and a drivable clock for tests."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from novelcore.translate import TEXT_HEADER

_MAP = dict(zip("abcdefghijklmnopqrstuvwxyz", "абцдефгхийклмнопкрстуввкыз"))
_MARK = re.compile(r"(<\/?\d+\/?>)")


def fake_translate(text: str) -> str:
    """Deterministic 'translation' into Cyrillic letters; markers are kept."""
    out = []
    for part in _MARK.split(text):
        if _MARK.fullmatch(part):
            out.append(part)
            continue
        for c in part:
            low = _MAP.get(c.lower())
            out.append(c if low is None else (low.upper() if c.isupper() else low))
    return "".join(out)


class FakeClock:
    """Virtual time. With auto=True the time jumps to the earliest deadline as soon as every
    registered worker thread is waiting; with auto=False the test calls advance()."""

    def __init__(self, start: float = 1_760_000_000.0, auto: bool = True):
        self._t = start
        self.auto = auto
        self._cond = threading.Condition()
        self._waiters: dict[object, float] = {}
        self._registered = 0

    def now(self) -> float:
        return self._t

    def enter(self) -> None:
        with self._cond:
            self._registered += 1

    def leave(self) -> None:
        with self._cond:
            self._registered -= 1
            if self.auto:
                self._advance_locked()

    def advance(self, seconds: float) -> None:
        with self._cond:
            self._t += seconds
            self._cond.notify_all()

    def _advance_locked(self) -> None:
        if self._registered > 0 and self._waiters and len(self._waiters) >= self._registered:
            target = min(self._waiters.values())
            if target > self._t:
                self._t = target
            self._cond.notify_all()

    def wait(self, event: threading.Event, timeout: float) -> bool:
        with self._cond:
            deadline = self._t + max(timeout, 0.0)
            token = object()
            self._waiters[token] = deadline
            try:
                while True:
                    if event.is_set():
                        return True
                    if self._t >= deadline:
                        return False
                    if self.auto:
                        self._advance_locked()
                        if self._t >= deadline:
                            return event.is_set()
                    self._cond.wait(0.02)
            finally:
                del self._waiters[token]


def _err(code, status, message, details=None):
    return code, {"error": {"code": code, "message": message, "status": status, "details": details or []}}


class FakeApi:
    """Configurable Gemini double. Faults by kind: empty, max_tokens, missing, shift, blank,
    latin, nomarkers, short, garbage."""

    def __init__(self, keys, clock=None, rpm=None, day_limit=None, unavailable_at=(), faults=None,
                 fault_fn=None, unknown_models=(), invalid_keys=(), latency=0.0, retry_delay=17,
                 translate=fake_translate, bucket=None, shut=(), poll_interval=0.5, model_names=None, region_blocked=()):
        self.keys = list(keys)
        self.clock = clock or FakeClock(auto=False)
        self.rpm = rpm  # per (key, model) requests per 60 s, None = unlimited
        self.day_limit = day_limit  # int, or {model: int}
        self.unavailable_at = set(unavailable_at)
        self.faults = dict(faults or {})  # request number (1-based) -> fault kind
        self.fault_fn = fault_fn  # f(entry dict) -> fault kind or None
        self.unknown_models = set(unknown_models)
        self.invalid_keys = set(invalid_keys)
        self.model_names = list(model_names if model_names is not None else ("gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-image"))
        self.region_blocked = set(region_blocked)     # key indexes refused as FAILED_PRECONDITION (location)
        self.gets: list[dict] = []                    # GET /v1beta/models calls: {key (index), path}
        self.latency = latency
        self.retry_delay = retry_delay
        self.translate = translate
        # Global allowance over ALL keys: token bucket {capacity, per_minute, debt}. When it is empty a
        # request is refused with a 429 that has no details, and each refusal digs the bucket deeper.
        self.bucket = dict(bucket) if bucket else None
        self._tokens = float(self.bucket["capacity"]) if bucket else 0.0
        self._bucket_at = self.clock.now()
        # Shut windows: (from, to) on the clock; a request that arrives inside one is refused with a
        # 429 that has no details (the state shared by every key), whatever else is configured.
        self.shut = [tuple(w) for w in shut]
        self.in_flight = 0  # requests being served now, and the most there ever were
        self.max_in_flight = 0
        self.day_reset = None  # epoch at which the per-day counters start again
        self.log: list[dict] = []
        self._lock = threading.Lock()
        self._n = 0
        self._window: dict[tuple, deque] = defaultdict(deque)
        self._served: dict[tuple, int] = defaultdict(int)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": poll_interval},
                                        daemon=True)

    def start(self) -> "FakeApi":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # -- helpers for tests ---------------------------------------------
    def requests(self, key=None, model=None, status=None):
        return [e for e in self.log
                if (key is None or e["key"] == key) and (model is None or e["model"] == model)
                and (status is None or e["status"] == status)]

    def max_in_window(self, key=None, window=60.0) -> int:
        """Most requests in any `window` seconds, for one key or (key=None) for all of them."""
        times = sorted(e["t"] for e in (self.log if key is None else self.requests(key=key)))
        best, lo = 0, 0
        for hi, t in enumerate(times):
            while times[lo] <= t - window:
                lo += 1
            best = max(best, hi - lo + 1)
        return best

    def min_gap(self) -> float:
        """Smallest time between two consecutive requests (inf with fewer than two)."""
        times = sorted(e["t"] for e in self.log)
        return min((b - a for a, b in zip(times, times[1:])), default=float("inf"))

    def sends_per_key(self) -> list[int]:
        return [len(self.requests(key=k)) for k in range(len(self.keys))]

    # -- server ----------------------------------------------------------
    def _handler(self):
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                code, body = api._models(self.path, self.headers.get("x-goog-api-key", ""))
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                with api._lock:
                    api.in_flight += 1
                    api.max_in_flight = max(api.max_in_flight, api.in_flight)
                try:
                    code, body = api._serve(self.path, self.headers.get("x-goog-api-key", ""), raw)
                finally:
                    with api._lock:
                        api.in_flight -= 1
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:  # the client gave up (a read timeout in a test)
                    pass

        return H

    def _models(self, path, key):
        """The model list (the call that costs no quota): used to check a key on add and to read Google's list."""
        kidx = self.keys.index(key) if key in self.keys else -1
        with self._lock:
            self.gets.append({"key": kidx, "path": path})
        if kidx < 0 or kidx in self.invalid_keys:
            return _err(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                        [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}])
        if kidx in self.region_blocked:
            return _err(400, "FAILED_PRECONDITION", "User location is not supported for the API use.")
        return 200, {"models": [{"name": "models/" + n, "supportedGenerationMethods": ["generateContent"]}
                                for n in self.model_names]}

    def _serve(self, path, key, raw):
        if self.latency:
            time.sleep(self.latency)
        m = re.match(r"/v1beta/models/([^:/]+):generateContent$", path)
        model = m.group(1) if m else ""
        try:
            req = json.loads(raw.decode("utf-8"))
            user = req["contents"][0]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            return _err(400, "INVALID_ARGUMENT", "bad body")
        ids, texts = [], []
        lines = re.findall(r"(?m)^" + TEXT_HEADER + r"\b.*\n(.*)$", user)
        if lines:
            items = json.loads(lines[-1])
            ids = [it["id"] for it in items]
            texts = [it["text"] for it in items]
        with self._lock:
            self._n += 1
            n = self._n
            if self.day_reset is not None and self.clock.now() >= self.day_reset:
                self._served.clear()
                self.day_reset = None
            kidx = self.keys.index(key) if key in self.keys else -1
            now = self.clock.now()
            entry = {"n": n, "key": kidx, "model": model, "t": now, "ids": ids, "texts": texts,
                     "user": user, "body": req, "status": 200, "fault": None}
            self.log.append(entry)
            pair = (kidx, model)
            if kidx < 0 or kidx in self.invalid_keys:
                entry["status"] = 400
                return _err(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                            [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}])
            if not m or model in self.unknown_models:
                entry["status"] = 404
                return _err(404, "NOT_FOUND", f"models/{model} is not found")
            if any(a <= now < b for a, b in self.shut):
                entry["status"] = 429
                entry["fault"] = "throttle"
                return _err(429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota).")
            if n in self.unavailable_at:
                entry["status"] = 503
                return _err(503, "UNAVAILABLE", "The model is overloaded.")
            if self.bucket is not None:
                b = self.bucket
                self._tokens = min(b["capacity"], self._tokens + (now - self._bucket_at) * b["per_minute"] / 60.0)
                self._bucket_at = now
                if self._tokens < 1.0:
                    self._tokens = max(-b["debt"], self._tokens - b.get("penalty", 1.0))
                    entry["status"] = 429
                    entry["fault"] = "throttle"
                    return _err(429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota).")
                self._tokens -= 1.0
            cap = self.day_limit.get(model) if isinstance(self.day_limit, dict) else self.day_limit
            if cap is not None and self._served[pair] >= cap:
                entry["status"] = 429
                return self._limit(model, "GenerateRequestsPerDayPerProjectPerModel-FreeTier", cap, None)
            if self.rpm is not None:
                win = self._window[pair]
                while win and win[0] <= now - 60.0:
                    win.popleft()
                if len(win) >= self.rpm:
                    entry["status"] = 429
                    return self._limit(model, "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                                       self.rpm, self.retry_delay)
                win.append(now)
            self._served[pair] += 1
            fault = self.faults.get(n) or (self.fault_fn(entry) if self.fault_fn else None)
            entry["fault"] = fault
        return 200, self._answer(ids, texts, fault)

    def _limit(self, model, quota_id, value, retry):
        details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                                    "quotaId": quota_id, "quotaDimensions": {"model": model},
                                    "quotaValue": str(value)}]}]
        if retry is not None:
            details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": f"{retry}s"})
        return _err(429, "RESOURCE_EXHAUSTED",
                    f"You exceeded your current quota. Quota exceeded for metric: requests, limit: {value}, model: {model}",
                    details)

    def _answer(self, ids, texts, fault):
        if fault == "empty":
            return {"candidates": [], "usageMetadata": {}}
        out = [{"id": i, "text": self.translate(t)} for i, t in zip(ids, texts)]
        finish = "STOP"
        if fault == "max_tokens":
            finish = "MAX_TOKENS"
            out = out[:1]
        elif fault == "missing" and out:
            out = out[:-1]
        elif fault == "shift" and len(out) > 1:
            tr = [o["text"] for o in out]
            tr = tr[1:] + tr[:1]
            out = [{"id": i, "text": t} for i, t in zip(ids, tr)]
        elif fault == "blank" and out:
            out[0]["text"] = ""
        elif fault == "latin":
            out = [{"id": i, "text": t} for i, t in zip(ids, texts)]
        elif fault == "nomarkers":
            out = [{"id": o["id"], "text": _MARK.sub("", o["text"])} for o in out]
        elif fault == "short":
            out = [{"id": o["id"], "text": o["text"][:3]} for o in out]
        text = "this is not json" if fault == "garbage" else json.dumps(out, ensure_ascii=False)
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 10}}
