"""Minimal Gemini REST client with typed errors.

Errors are classified from the HTTP status and the JSON body, not from prose,
except for the human-readable `limit: N` that Google puts in 429 messages.
The API key travels only in a header and never appears in any message here.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

DEFAULT_BASE = "https://generativelanguage.googleapis.com"
SAFETY_CATEGORIES = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)
MAX_OUTPUT_TOKENS = 65536


class GeminiError(Exception):
    """Base class of every error raised by `generate`."""

    kind = "error"


class MinuteLimit(GeminiError):
    kind = "minute"

    def __init__(self, retry_after: float | None = None, limit: int | None = None, unknown: bool = False,
                 quota_id: str = ""):
        super().__init__(f"per-minute limit (retry in {retry_after}s, limit {limit}, {quota_id})")
        self.quota_id = quota_id
        self.retry_after = retry_after
        self.limit = limit
        self.unknown = unknown  # the body did not say which quota was hit


class Throttled(GeminiError):
    """A 429 whose body names no quota (no details at all): the service refuses this client for every
    key, project and account alike, so the whole run must pause, not one pair."""

    kind = "throttled"


class DayLimit(GeminiError):
    kind = "day"

    def __init__(self, limit: int | None = None):
        super().__init__(f"per-day quota is used up (limit {limit})")
        self.limit = limit


class Unavailable(GeminiError):
    """The service could not serve this request (5xx, network error): the same request is worth repeating."""

    kind = "unavailable"


class TimedOut(Unavailable):
    """No answer within the read timeout."""

    kind = "timeout"


class InvalidKey(GeminiError):
    kind = "invalid_key"


class ModelNotFound(GeminiError):
    kind = "model_not_found"


class BadRequest(GeminiError):
    """The request itself was refused (a 400 that is not a key problem)."""

    kind = "bad_request"


class EmptyAnswer(GeminiError):
    """No usable candidate: nothing came back, or the prompt/answer was blocked."""

    kind = "empty"


class Truncated(GeminiError):
    """The model stopped for a reason other than STOP (for example MAX_TOKENS)."""

    kind = "truncated"


@dataclass
class Result:
    text: str
    json: object = None  # parsed answer, None when the text is not valid JSON
    finish: str = "STOP"
    usage: dict = field(default_factory=dict)
    model: str = ""
    seconds: float = 0.0


def default_base() -> str:
    return os.environ.get("NOVELCORE_API_BASE") or DEFAULT_BASE


def mask(key: str) -> str:
    return "..." + key[-4:] if key else ""


def build_body(system: str, user: str, schema, temperature) -> dict:
    cfg: dict = {"maxOutputTokens": MAX_OUTPUT_TOKENS}
    if schema is not None:
        cfg["responseMimeType"] = "application/json"
        cfg["responseSchema"] = schema
    if temperature is not None:
        cfg["temperature"] = temperature
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": cfg,
        "safetySettings": [{"category": c, "threshold": "BLOCK_NONE"} for c in SAFETY_CATEGORIES],
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _opener(url: str):
    host = urllib.parse.urlsplit(url).hostname or ""
    return _DIRECT if host in ("127.0.0.1", "localhost", "::1") else urllib.request.build_opener()


def generate(model, key, system, user, schema=None, temperature=None, base_url=None, timeout=300) -> Result:
    """One generateContent call. Raises a GeminiError subclass on any failure."""
    base = (base_url or default_base()).rstrip("/")
    url = f"{base}/v1beta/models/{urllib.parse.quote(model, safe='.-_')}:generateContent"
    data = json.dumps(build_body(system, user, schema, temperature)).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    started = time.monotonic()
    try:
        with _opener(url).open(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        raise classify_http(exc.code, raw) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(
                getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
            raise TimedOut(f"network: {type(exc).__name__}") from None
        raise Unavailable(f"network: {type(exc).__name__}") from None
    except Exception as exc:  # http.client errors such as IncompleteRead, RemoteDisconnected
        raise Unavailable(f"network: {type(exc).__name__}") from None
    result = parse_response(raw)
    result.model = model
    result.seconds = time.monotonic() - started
    return result


def _body_json(raw: bytes) -> dict:
    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _seconds(text) -> float | None:
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)s\s*", str(text or ""))
    return float(m.group(1)) if m else None


def classify_http(status: int, raw: bytes) -> GeminiError:
    """Map an error response to a typed exception."""
    err = _body_json(raw).get("error")
    err = err if isinstance(err, dict) else {}
    message = str(err.get("message") or "")
    state = str(err.get("status") or "")
    details = [d for d in (err.get("details") or []) if isinstance(d, dict)]
    if status == 429:
        return _classify_429(message, details)
    if status in (500, 502, 503, 504) or state in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"):
        return Unavailable(f"HTTP {status} {state}".strip())
    if status == 404 or state == "NOT_FOUND":
        return ModelNotFound("model not found")
    reasons = {str(d.get("reason") or "") for d in details}
    if status == 400 and ("API_KEY_INVALID" in reasons or "api key not valid" in message.lower()):
        return InvalidKey("API key not valid")
    if status in (401, 403):
        return InvalidKey(f"HTTP {status} {state}".strip())
    return BadRequest(f"HTTP {status} {state}".strip())


def _classify_429(message: str, details: list) -> GeminiError:
    ids: list[str] = []
    values: list[int] = []
    retry = None
    for d in details:
        kind = str(d.get("@type") or "")
        if "RetryInfo" in kind:
            retry = _seconds(d.get("retryDelay"))
        for v in d.get("violations") or []:
            if isinstance(v, dict):
                ids.append(f"{v.get('quotaId', '')} {v.get('quotaMetric', '')}")
                try:
                    values.append(int(v.get("quotaValue")))
                except (TypeError, ValueError):
                    pass
    limit = values[0] if values else None
    if limit is None:
        m = re.search(r"limit: (\d+)", message)
        limit = int(m.group(1)) if m else None
    joined = " ".join(ids).lower()
    low = message.lower()
    if "perday" in joined or (not joined and "per day" in low and "per minute" not in low):
        return DayLimit(limit)
    if "perminute" in joined or "per minute" in low:
        return MinuteLimit(retry, limit, quota_id=" ".join(ids))
    if not details and limit is None:
        return Throttled("HTTP 429 without quota details")
    return MinuteLimit(retry, limit, unknown=True, quota_id=" ".join(ids))


def parse_response(raw: bytes) -> Result:
    body = _body_json(raw)
    usage = body.get("usageMetadata") if isinstance(body.get("usageMetadata"), dict) else {}
    feedback = body.get("promptFeedback") if isinstance(body.get("promptFeedback"), dict) else {}
    if feedback.get("blockReason"):
        raise EmptyAnswer(f"prompt blocked: {feedback.get('blockReason')}")
    cands = body.get("candidates")
    if not isinstance(cands, list) or not cands or not isinstance(cands[0], dict):
        raise EmptyAnswer("no candidates")
    cand = cands[0]
    parts = ((cand.get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    finish = str(cand.get("finishReason") or "STOP")
    if finish != "STOP":
        if text.strip() and finish == "MAX_TOKENS":
            raise Truncated(f"finishReason {finish}")
        if not text.strip():
            raise EmptyAnswer(f"finishReason {finish}, no text")
        raise Truncated(f"finishReason {finish}")
    if not text.strip():
        raise EmptyAnswer("no text")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    return Result(text=text, json=parsed, finish=finish, usage=dict(usage))
