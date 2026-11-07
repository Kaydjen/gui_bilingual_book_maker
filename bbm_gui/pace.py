"""Pace of a run on the Gemini route: the pause between requests is computed, not typed.

A pair (key, model) may send RPM requests per minute. One request takes L seconds, so the engine is asked to wait
I = (1 + margin) * 60 / RPM - L_low seconds after each request, where L_low is a LOW estimate of L (0 until measured).
The stream then runs at 60 / (L + I) <= RPM / (1 + margin) for every real L >= L_low, so a slow or fast answer can never
push the rate over the limit. The typical latency (mean of the measured gaps) is used only to show the plan and the ETA.
Limits come from a shipped table, are corrected by the `limit: N` that a 429 reports, and are kept per model in
settings["limits"]; the latencies are kept per model (and per grouping) in settings["latency"] as {"l": typical,
"lo": low, "n": runs}."""
import statistics

GROUPS = (1, 5, 10, 20)  # paragraphs per request offered in the window
MAX_GROUP = 50
MARGIN = 0.10  # share of the minute limit left unused
DEFAULT_LATENCY = 3.0  # seconds per request shown in the plan until one is measured (never used for the interval)
DEFAULT_LOW = 0.0  # the latency the interval may count on until a low estimate is measured
DEFAULT_RPM = 10  # a model that is not in the table
MIN_SAMPLES = 3  # gaps needed for the typical latency
MIN_LOW_SAMPLES = 8  # gaps needed for the low estimate
LOW_QUANTILE = 0.10
KEEP_SAMPLES = 40
LATENCY_FLOOR = 0.2
MIN_PYTHON = (3, 12)  # the engine's request grouping needs it

# (model name contains, but does not contain) -> (requests per minute, requests per day)
TABLE = (
    (("lite",), (), (15, 500)),
    (("flash",), ("lite",), (5, 20)),
)


def table_limits(model):
    name = (model or "").lower()
    for need, forbid, lim in TABLE:
        if all(w in name for w in need) and not any(w in name for w in forbid):
            return lim
    return None


def limits(model, learned=None):
    """(rpm, rpd, source): learned values win over the table; an unknown model gets the conservative default
    and no daily limit (None)."""
    rpm = rpd = None
    src = "default"
    tab = table_limits(model)
    if tab:
        rpm, rpd = tab
        src = "table"
    got = (learned or {}).get(model) or {}
    if got.get("rpm"):
        rpm, src = int(got["rpm"]), "learned"
    if got.get("rpd"):
        rpd, src = int(got["rpd"]), "learned"
    return rpm or DEFAULT_RPM, rpd, src


def interval(low, rpm, margin=MARGIN):
    """Seconds to wait after a request so that the stream stays below the minute limit, counting on a request taking
    at least `low` seconds."""
    return max(0.0, (1.0 + margin) * 60.0 / max(rpm, 1) - max(low, 0.0))


def fmt_interval(seconds):
    s = "%.1f" % seconds
    return "0" if float(s) == 0 else s


def latency_key(model, per_request=1):
    return model if per_request <= 1 else "%s|%d" % (model, per_request)


def latency_of(stored, model, per_request=1):
    got = (stored or {}).get(latency_key(model, per_request)) or {}
    return float(got["l"]) if got.get("l") else DEFAULT_LATENCY


def latency_low_of(stored, model, per_request=1):
    got = (stored or {}).get(latency_key(model, per_request)) or {}
    return float(got["lo"]) if got.get("lo") is not None else DEFAULT_LOW


def measured(deltas, wait):
    """Typical seconds per request for the plan and the ETA, from the gaps between progress steps (each gap = request +
    the wait that follows it). The mean, not the median: the short first items (titles) make the median too small and a
    plan built on it is too optimistic. None until enough steps were seen."""
    if len(deltas) < MIN_SAMPLES:
        return None
    recent = deltas[-KEEP_SAMPLES:]
    return max(sum(recent) / len(recent) - wait, LATENCY_FLOOR)


def measured_low(deltas, wait):
    """A low estimate of the seconds per request (10th percentile of the gaps minus the wait, never below 0), so that one
    lucky gap does not count; None until MIN_LOW_SAMPLES gaps were seen."""
    if len(deltas) < MIN_LOW_SAMPLES:
        return None
    recent = sorted(deltas[-KEEP_SAMPLES:])
    return max(recent[int(LOW_QUANTILE * (len(recent) - 1))] - wait, 0.0)


def store_latency(stored, model, per_request, value, low=None):
    """Typical latency: exponential average (0.5 / 0.5). Low estimate: the smallest one ever seen (the safe side)."""
    key = latency_key(model, per_request)
    old = stored.get(key) or {}
    new = value if not old.get("l") else 0.5 * old["l"] + 0.5 * value
    entry = {"l": round(new, 2), "n": int(old.get("n", 0)) + 1}
    lows = [x for x in (old.get("lo"), low) if x is not None]
    if lows:
        entry["lo"] = round(min(lows), 2)
    stored[key] = entry


def learn(stored, model, events):
    """Keep the limits that 429 blocks reported. Returns True if something changed."""
    changed = False
    for ev in events:
        if not ev.limit:
            continue
        field = {"minute": "rpm", "day": "rpd"}.get(ev.kind)
        if not field:
            continue
        entry = stored.setdefault(model, {})
        if entry.get(field) != ev.limit:
            entry[field] = int(ev.limit)
            changed = True
    return changed


def grouping_ok(version):
    return bool(version) and tuple(version[:2]) >= MIN_PYTHON


def group_size(per_request, py_version):
    """Paragraphs per request the engine really gets: the chosen value if it is sane and the engine can group."""
    n = per_request if isinstance(per_request, int) and 1 <= per_request <= MAX_GROUP else 1
    return n if grouping_ok(py_version) else 1


def owned_flags(model, per_request, settings, py_version):
    """The pace flags of one run: {flag: value}. `--block_size` only when grouping is chosen and possible."""
    rpm, _rpd, _src = limits(model, settings.get("limits"))
    n = group_size(per_request, py_version)
    out = {"--interval": fmt_interval(interval(latency_low_of(settings.get("latency"), model, n), rpm))}
    if n > 1:
        out["--block_size"] = str(n)
    return out


def eta_seconds(text):
    """tqdm's 'h:mm:ss' or 'mm:ss' -> seconds (None for '?')."""
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        return None
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec
