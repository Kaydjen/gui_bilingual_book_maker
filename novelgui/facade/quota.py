"""Today's quota and the state of every key, read from the pool files of the library (no Qt, no Tk)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from novelcore.pool import day_return, key_hash, read_day_exhausted, read_day_usage

from .. import keystates

# Free-tier requests per key and day by model (AI Studio figure of 2026-11-13). Unknown model: None.
DAILY_LIMITS = {"gemini-3.1-flash-lite": 500}


# ---------------------------------------------------------------- quota
def renew_at(now: float) -> float:
    """The epoch the daily quota returns: next Pacific midnight by the core's rule, margin included, so the
    `Renew at` of the Time popover and the `Resumes` word of the job read the same minute (works without a tz
    database)."""
    return day_return(now)


@dataclass
class Quota:
    keys: int = 0
    models: int = 0
    per_key: int | None = None     # daily limit of the first model
    used: int = 0
    left: int | None = None        # None when a model's limit is unknown
    capacity: int | None = None    # requests a full day allows


def quota_status(library, keys, models, now: float) -> Quota:
    """Requests left today over all keys. Counts come from the pool state files of every series of the
    library (the daily quota belongs to the key, not to a series)."""
    hashes = [key_hash(k) for k in keys]
    used: dict = {}
    exhausted: set = set()
    try:
        folders = [p for p in Path(library).iterdir() if p.is_dir()]
    except OSError:
        folders = []
    try:        # series moved to .deleted today spent today's quota too (window_spec 13.10)
        folders += [p for p in (Path(library) / ".deleted").iterdir() if p.is_dir()]
    except OSError:
        pass
    for f in folders:
        state = f / ".state" / "pool.json"
        if not state.exists():
            continue
        for kh, per in read_day_usage(state, now).items():
            for m, n in per.items():
                used[(kh, m)] = used.get((kh, m), 0) + n
        exhausted |= read_day_exhausted(state, now)
    limits = [DAILY_LIMITS.get(m) for m in models]
    total_used = sum(used.get((h, m), 0) for h in hashes for m in models)
    left = cap = None
    if hashes and models and all(x is not None for x in limits):
        left = cap = 0
        for h in hashes:
            for m, lim in zip(models, limits):
                cap += lim
                if "%s|%s" % (h, m) not in exhausted:
                    left += max(0, lim - used.get((h, m), 0))
    return Quota(len(hashes), len(models), limits[0] if limits else None, total_used, left, cap)


def key_states(library, keys, models, now: float):
    """State of every key (`{key: keystates.KeyState}`) and the models held as not found (`set`), merged over the
    pool files of all series of the library (window_spec 11.2, 11.4). Reads files: call it on a worker thread."""
    tables = []
    try:
        folders = [p for p in Path(library).iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        folders = []
    for f in folders:
        try:
            data = json.loads((f / ".state" / "pool.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("pairs"), dict):
            tables.append(data["pairs"])
    hashes = {k: key_hash(k) for k in keys}
    by_hash, missing = keystates.merge_pairs(tables, list(hashes.values()), list(models), now)
    return {k: by_hash[h] for k, h in hashes.items()}, missing


def key_states_task(ctx, library, keys, models):
    return key_states(library, keys, models, time.time())

