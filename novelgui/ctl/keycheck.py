"""Checking a key and reading Google's model list (window_spec 11.7, 14.5) with the one request that costs no quota:
`GET <base>/v1beta/models`. Plain functions, no Qt; they run on a lane. The service address comes from
NOVELGUI_API_BASE; with a data override (tests, scripted checks) and no such address nothing is requested, so the
real service is never called from a check.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import atomic
from ..runtime import paths

DEFAULT_BASE = "https://generativelanguage.googleapis.com"
READY, INVALID, NO_ACCESS, NO_CONNECTION, UNCHECKED = "ready", "invalid", "no access", "no connection", ""
CACHE_NAME = "models_cache.json"
CACHE_SECONDS = 24 * 3600
SKIP = re.compile(r"tts|image|live|embedding|audio|transcribe|robotics|computer-use|antigravity|deep-research|lyria|"
                  r"nano-banana|customtools|omni|aqa|argon", re.I)
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api_base() -> str | None:
    """The address to ask, or None when a check must not reach the network (data override without a test address)."""
    env = os.environ.get("NOVELGUI_API_BASE")
    if env:
        return env.rstrip("/")
    if os.environ.get(paths.ENV_DATA):
        return None
    return DEFAULT_BASE


def usable(models) -> list:
    """Names of the models of Google's answer that can translate text, newest first."""
    names = []
    for m in models:
        name = str(m.get("name", "")).replace("models/", "", 1)
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if not re.match(r"(gemini|gemma)-", name) or SKIP.search(name):
            continue
        names.append(name)

    def order(n):
        nums = [int(x) for x in re.findall(r"\d+", n)]
        return (0 if n.startswith("gemini") else 1, not nums, [-x for x in nums], n)

    return sorted(set(names), key=order)


def _opener(url: str):
    host = urllib.parse.urlsplit(url).hostname or ""
    return _DIRECT if host in ("127.0.0.1", "localhost", "::1") else urllib.request.build_opener()


def classify(status: int, raw: bytes) -> str:
    """The state word for an answer that is not 200 (14.5)."""
    try:
        err = json.loads(raw.decode("utf-8", "replace")).get("error") or {}
    except (ValueError, AttributeError):
        err = {}
    text = (str(err.get("message") or "") + " " + str(err.get("status") or "")).lower()
    reasons = " ".join(str(d.get("reason") or "") for d in (err.get("details") or []) if isinstance(d, dict))
    if status == 429 or status >= 500:
        return READY                    # the key is accepted; quota and service trouble are not a key state
    if "API_KEY_INVALID" in reasons or "api key not valid" in text or status in (401, 403):
        return INVALID
    if "failed_precondition" in text or "location" in text:
        return NO_ACCESS
    return INVALID if status == 400 else NO_CONNECTION


def fetch(key: str, base: str | None = None, timeout: float = 8.0) -> tuple:
    """(state, model names). The state is one of READY, INVALID, NO_ACCESS, NO_CONNECTION; the key travels in a
    header, never in the address."""
    base = base if base is not None else api_base()
    if not base:
        return NO_CONNECTION, []
    url = base + "/v1beta/models?pageSize=1000"
    req = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with _opener(url).open(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except OSError:
            raw = b""
        return classify(exc.code, raw), []
    except (urllib.error.URLError, OSError, ValueError):
        return NO_CONNECTION, []
    return READY, usable(data.get("models", []) if isinstance(data, dict) else [])


def check_key(key: str, base: str | None = None, timeout: float = 8.0) -> str:
    return fetch(key, base, timeout)[0]


TIPS = {
    INVALID: "Google does not accept this key. It may be copied incompletely, or switched off in Google AI Studio.",
    NO_ACCESS: "Google's API is not available from your location for this key.",
    NO_CONNECTION: "Cannot reach Google. Check the internet connection and the proxy settings.",
}


# ---------------------------------------------------------------- the daily cache of Google's list
class ModelCache:
    """Google's model list, read at most once a day with a ready key and kept in the local data folder."""

    def __init__(self, folder=None):
        self.path = Path(folder or paths.local_dir()) / CACHE_NAME

    def load(self) -> tuple:
        """(names, age in seconds); ([], None) when there is none."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            names = [n for n in data["models"] if isinstance(n, str)]
            return names, max(0.0, time.time() - float(data["at"]))
        except (OSError, ValueError, KeyError, TypeError):
            return [], None

    def save(self, names) -> None:
        atomic.try_write_text(self.path, json.dumps({"at": time.time(), "models": list(names)}))

    def due(self) -> bool:
        names, age = self.load()
        return age is None or age >= CACHE_SECONDS
