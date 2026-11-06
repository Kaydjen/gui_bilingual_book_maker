"""Key pool: several keys (one per Google project) used one after another.

A run uses one (key, model) pair. Pairs are ordered key by key, and inside a key model by model, so a key is left
only when all its models are used up. A used-up pair is remembered until its reset time (epoch seconds).
"""
import hashlib
import re

SPLIT = re.compile(r"[\s,;]+")
SHORT_WAIT = 300  # seconds a pair rests after a quota stop that is not known to be the daily limit


def parse(text):
    """Tokens separated by commas, spaces, semicolons or new lines; duplicates dropped, order kept."""
    out = []
    for t in SPLIT.split(text or ""):
        if t and t not in out:
            out.append(t)
    return out


def fingerprint(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def mask(key):
    return key[:4] + "…" + key[-4:] if len(key) > 12 else "…" + key[-3:]


class Pool:
    def __init__(self, keys, models, spent=None):
        self.keys = list(keys)
        self.models = list(models) or [""]
        self.spent = dict(spent or {})  # "fingerprint|model" -> epoch when the pair is usable again
        self.bad = set()  # keys the API refused in this session

    def _id(self, key, model):
        return fingerprint(key) + "|" + model

    def pairs(self):
        return [(k, m) for k in self.keys for m in self.models]

    def purge(self, now):
        self.spent = {k: v for k, v in self.spent.items() if v > now}

    def is_spent(self, key, model, now):
        return self.spent.get(self._id(key, model), 0) > now

    def mark(self, key, model, until):
        self.spent[self._id(key, model)] = until

    def mark_bad(self, key):
        self.bad.add(key)

    def next_pair(self, now):
        for k, m in self.pairs():
            if k not in self.bad and not self.is_spent(k, m, now):
                return k, m
        return None

    def usable_keys(self, now):
        return [k for k in self.keys if k not in self.bad and any(not self.is_spent(k, m, now) for m in self.models)]

    def state(self, key, now):
        """('bad'|'used'|'part'|'ready', epoch of the earliest return or 0)."""
        if key in self.bad:
            return "bad", 0
        left = [m for m in self.models if self.is_spent(key, m, now)]
        if not left:
            return "ready", 0
        if len(left) < len(self.models):
            return "part", min(self.spent[self._id(key, m)] for m in left)
        return "used", min(self.spent[self._id(key, m)] for m in left)

    def earliest_return(self, now):
        """When some pair becomes usable again (None if no key is left to wait for)."""
        times = [self.spent[self._id(k, m)] for k, m in self.pairs()
                 if k not in self.bad and self.is_spent(k, m, now)]
        return min(times) if times else None
