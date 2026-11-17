"""What the settings panel says about each key and model (window_spec 11.2, 11.4): the pair records of every
series' pool.json merged into one state per key. The worst state wins (invalid > daily quota > paused > ready) and,
between equal ones, the later `until`. A model the pool holds as not found is shown on its row.

Pure: the records come in as plain dicts, `merge_pairs` touches no file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

READY, PAUSED, DAY, INVALID = "ready", "paused", "day", "invalid"
_RANK = {READY: 0, PAUSED: 1, DAY: 2, INVALID: 3}
INVALID_KEY = "invalid key"
MODEL_NOT_FOUND = "model not found"


@dataclass(frozen=True)
class KeyState:
    kind: str = READY
    until: float | None = None

    def worse_than(self, other: "KeyState") -> bool:
        a, b = _RANK[self.kind], _RANK[other.kind]
        if a != b:
            return a > b
        return (self.until or 0) > (other.until or 0)


def text(state: KeyState) -> str:
    """The words next to a key: `ready`, `paused until 09:41`, `daily quota until 10:00`, `invalid`."""
    if state.kind == INVALID:
        return "invalid"
    if state.kind == DAY:
        return "daily quota until " + _clock(state.until)
    if state.kind == PAUSED:
        return "paused until " + _clock(state.until)
    return "ready"


def _clock(epoch) -> str:
    return time.strftime("%H:%M", time.localtime(epoch)) if isinstance(epoch, (int, float)) else "-"


def merge_pairs(pair_tables, hashes, models, now: float):
    """`pair_tables`: the `pairs` dicts of the pool files (`"<key hash>|<model>": {state, until, reason}`).
    Returns ({key hash: KeyState}, {model names held as not found}) for the keys and models asked about."""
    states = {h: KeyState() for h in hashes}
    missing: set = set()
    wanted = set(models)
    for table in pair_tables:
        if not isinstance(table, dict):
            continue
        for name, rec in table.items():
            if not isinstance(rec, dict) or not isinstance(name, str) or "|" not in name:
                continue
            khash, _, model = name.partition("|")
            if khash not in states or model not in wanted:
                continue
            raw, until = rec.get("state"), rec.get("until")
            until = float(until) if isinstance(until, (int, float)) and not isinstance(until, bool) else None
            if raw == "dead":
                reason = str(rec.get("reason") or "")
                if reason == MODEL_NOT_FOUND:
                    missing.add(model)
                    continue
                new = KeyState(INVALID)
            elif raw in ("day", "cool") and until is not None and until > now:
                new = KeyState(DAY if raw == "day" else PAUSED, until)
            else:
                continue
            if new.worse_than(states[khash]):
                states[khash] = new
    return states, missing
