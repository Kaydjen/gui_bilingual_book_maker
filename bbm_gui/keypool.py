"""Key pool: several keys (one per Google project) used one after another.

A run uses one (key, model) pair. Pairs are ordered model by model (all keys of the first model, then all keys of
the second ...), so a book stays on one model as long as any key can serve it; quotas belong to a (project, model)
pair, so the total capacity does not depend on the order. The next pair is always the first one that is ready.

Each pair has a state that the GUI sets from the classified engine error:
  cool - a per-minute or temporary limit: usable again after a cooldown;
  day  - the daily quota is spent: usable again after the Pacific midnight;
  dead - the model is not available to this key: skipped until the keys or models change.
Times are epoch seconds. A pair also counts its repeated unexplained failures (hits) so that the cooldown doubles.
"""
import hashlib
import re

SPLIT = re.compile(r"[\s,;]+")
MINUTE_PAD = 3  # seconds added to the delay the server names
MINUTE_MIN, MINUTE_MAX, MINUTE_DEFAULT = 8, 90, 65
UNKNOWN_BASE, UNKNOWN_CAP = 120, 900  # unexplained 429 and 503: base cooldown, doubled on each repeat
FAR = 4102444800  # 2100-01-01: "until the keys or models change"
DAY_THRESHOLD = 900  # a migrated cooldown longer than this was a daily one
LOOP_LIMIT = 10  # segments in a row without any progress end the run


def parse(text):
    """Tokens separated by commas, spaces, semicolons or new lines; duplicates dropped, order kept."""
    out = []
    for t in SPLIT.split(text or ""):
        if t and t not in out:
            out.append(t)
    return out


def looks_like_key(token):
    """A soft check that keeps pasted prose out of the list: no real key is this short."""
    return len(token) >= 20


def fingerprint(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def mask(key):
    return key[:4] + "…" + key[-4:] if len(key) > 12 else "…" + key[-3:]


def minute_cooldown(delay):
    """Seconds a pair rests after a per-minute 429: the server's delay plus a margin, within sane bounds."""
    if delay is None:
        return MINUTE_DEFAULT
    return min(max(delay + MINUTE_PAD, MINUTE_MIN), MINUTE_MAX)


def cooldown(kind, delay, hits, now, day_at):
    """(state, until) for an event kind: minute, day, zero, unknown, busy, notfound."""
    if kind == "minute":
        return "cool", now + minute_cooldown(delay)
    if kind == "day":
        return "day", day_at
    if kind in ("zero", "notfound"):
        return "dead", FAR
    return "cool", now + min(UNKNOWN_BASE * 2 ** min(hits, 6), UNKNOWN_CAP)


def migrate_spent(spent, now):
    """The old format {id: until} -> pair states."""
    out = {}
    for pid, until in (spent or {}).items():
        if until > now:
            out[pid] = {"s": "day" if until - now > DAY_THRESHOLD else "cool", "until": until, "hits": 0}
    return out


class Pool:
    def __init__(self, keys, models, states=None):
        self.keys = list(keys)
        self.models = list(models) or [""]
        self.states = {k: dict(v) for k, v in (states or {}).items() if isinstance(v, dict)}
        self.bad = set()  # keys the API refused in this session

    def _id(self, key, model):
        return fingerprint(key) + "|" + model

    def pairs(self):
        return [(k, m) for m in self.models for k in self.keys]

    def purge(self, now):
        """Drop finished cooldowns (a pair that has repeated failures keeps its count) and marks of removed keys or models."""
        live = {self._id(k, m) for k, m in self.pairs()}
        out = {}
        for pid, e in self.states.items():
            if pid not in live:
                continue
            if e.get("until", 0) > now:
                out[pid] = e
            elif e.get("hits"):
                out[pid] = {"s": "", "until": 0, "hits": e["hits"]}
        self.states = out

    def _entry(self, key, model):
        return self.states.get(self._id(key, model), {})

    def blocked(self, key, model, now):
        e = self._entry(key, model)
        return bool(e.get("s")) and e.get("until", 0) > now

    is_spent = blocked

    def until(self, key, model):
        return self._entry(key, model).get("until", 0)

    def kind(self, key, model, now):
        """'cool', 'day', 'dead' or '' (ready)."""
        return self._entry(key, model).get("s", "") if self.blocked(key, model, now) else ""

    def mark(self, key, model, state, until):
        e = self.states.setdefault(self._id(key, model), {"hits": 0})
        e["s"], e["until"] = state, until

    def record(self, key, model, kind, delay, now, day_at):
        """Set the pair's state from a classified event and return (state, until)."""
        e = self.states.setdefault(self._id(key, model), {"hits": 0})
        state, until = cooldown(kind, delay, e.get("hits", 0), now, day_at)
        e["s"], e["until"] = state, until
        if kind in ("unknown", "busy"):
            e["hits"] = e.get("hits", 0) + 1
        return state, until

    def success(self, key, model):
        """The pair did work: its failure count starts again."""
        e = self.states.get(self._id(key, model))
        if e:
            e["hits"] = 0

    def mark_bad(self, key):
        self.bad.add(key)

    def next_pair(self, now):
        for k, m in self.pairs():
            if k not in self.bad and not self.blocked(k, m, now):
                return k, m
        return None

    def usable_keys(self, now):
        return [k for k in self.keys if k not in self.bad and any(not self.blocked(k, m, now) for m in self.models)]

    def state(self, key, now):
        """(name, epoch): bad / ready / part (some models resting) / wait (all resting for a short time) /
        day (all resting until the reset) / dead (no model of this key can be used)."""
        if key in self.bad:
            return "bad", 0
        rest = [m for m in self.models if self.blocked(key, m, now) and self.kind(key, m, now) != "dead"]
        dead = [m for m in self.models if self.kind(key, m, now) == "dead"]
        if len(dead) == len(self.models):
            return "dead", 0
        if not rest:
            return "ready", 0
        soonest = min(rest, key=lambda m: self.until(key, m))
        t = self.until(key, soonest)
        if len(rest) + len(dead) < len(self.models):
            return "part", t
        return ("day" if self.kind(key, soonest, now) == "day" else "wait"), t

    def earliest_return(self, now):
        """When some pair becomes usable again (None if nothing is left to wait for)."""
        times = [self.until(k, m) for k, m in self.pairs()
                 if k not in self.bad and self.blocked(k, m, now) and self.kind(k, m, now) != "dead"]
        return min(times) if times else None

    def earliest_kind(self, now):
        """'cool' or 'day': what the earliest returning pair is waiting for."""
        best = None
        for k, m in self.pairs():
            if k in self.bad or not self.blocked(k, m, now) or self.kind(k, m, now) == "dead":
                continue
            if best is None or self.until(k, m) < best[0]:
                best = (self.until(k, m), self.kind(k, m, now))
        return best[1] if best else None
