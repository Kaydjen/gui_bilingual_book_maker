"""Scheduler over (key, model) pairs: one even send rate for the whole process, per-key rate windows,
cooldowns, daily quota, and the shared pause that follows a throttled answer."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .clock import SystemClock
from .store import atomic_write_text

WINDOW = 60.0
SAFETY = 1.1  # a pair is held to RPM / 1.1
MINUTE_PAD = 3.0
MINUTE_MIN, MINUTE_MAX = 8.0, 90.0
MINUTE_DEFAULT = 20.0  # cooldown when a 429 gave no retry hint
DAY_MARGIN = 60.0

DEFAULT_PACE = 5  # sends per minute in total, over all keys and models
PACE_MIN, PACE_MAX = 1, 120
SHUT_FIRST, SHUT_MAX = 60.0, 900.0  # first pause after a throttled answer, and the longest one
SHUT_LIMIT = 1800.0  # the pauses of one shut state may add up to this many seconds
PROBE_POLL = 1.0  # how often a request re-asks while the probe is in flight
# A single throttled answer is only retried; the shared pause starts when refusals are dense:
THROTTLE_WINDOW = 8  # the last this-many answers (ok, empty, truncated, throttled) ...
THROTTLE_IN_WINDOW = 3  # ... holding at least this many throttled ones, or
THROTTLE_IN_ROW = 3  # this many throttled answers in a row

READY, COOL, DAY, DEAD = "ready", "cool", "day", "dead"
OPEN, PAUSED, PROBING = "open", "paused", "probing"  # phases of the shared throttle state
THROTTLED = "throttled"  # Acquire.reason while sending is paused


class QuotaExhausted(Exception):
    """Every usable pair is used up for the day; `until` is the epoch when the first one returns."""

    def __init__(self, until: float):
        super().__init__(f"daily quota used up until {until:.0f}")
        self.until = until


def clean_pace(value) -> float:
    """Sends per minute in total: None gives the default, anything outside 1-120 is an error."""
    if value is None:
        return float(DEFAULT_PACE)
    try:
        pace = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"pace must be a number from {PACE_MIN} to {PACE_MAX}, got {value!r}") from None
    if not PACE_MIN <= pace <= PACE_MAX:
        raise ValueError(f"pace must be from {PACE_MIN} to {PACE_MAX} requests per minute, got {value!r}")
    return pace


def default_rpm(model: str) -> int:
    """Shipped free-tier requests per minute by model name."""
    name = model.lower()
    if "flash-lite" in name:
        return 15
    if "flash" in name:
        return 5
    return 10


def _pacific_offset(utc_naive: dt.datetime) -> int:
    """Hours from UTC for US Pacific time (DST: second Sunday of March to first Sunday of November)."""
    y = utc_naive.year
    mar = dt.datetime(y, 3, 8)
    mar += dt.timedelta(days=(6 - mar.weekday()) % 7)
    nov = dt.datetime(y, 11, 1)
    nov += dt.timedelta(days=(6 - nov.weekday()) % 7)
    start = mar.replace(hour=10)  # 02:00 PST = 10:00 UTC
    end = nov.replace(hour=9)  # 02:00 PDT = 09:00 UTC
    return -7 if start <= utc_naive < end else -8


def day_return(now: float) -> float:
    """Epoch when a pair used up for the day is usable again: next Pacific midnight + a margin."""
    utc = dt.datetime.fromtimestamp(now, dt.timezone.utc).replace(tzinfo=None)
    off = _pacific_offset(utc)
    local = utc + dt.timedelta(hours=off)
    midnight = (local + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    off_then = _pacific_offset(midnight - dt.timedelta(hours=off))
    reset = midnight - dt.timedelta(hours=off_then)
    return reset.replace(tzinfo=dt.timezone.utc).timestamp() + DAY_MARGIN


def pacific_day(now: float) -> str:
    """The US Pacific calendar date (YYYY-MM-DD) of an epoch: the day the free quota counts in."""
    utc = dt.datetime.fromtimestamp(now, dt.timezone.utc).replace(tzinfo=None)
    return (utc + dt.timedelta(hours=_pacific_offset(utc))).date().isoformat()


def _read_state(state_path):
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_day_usage(state_path, now: float) -> dict:
    """Requests sent today (Pacific day of `now`) per key hash and model, read from a pool state file
    without a live pool: {key_hash: {model: n}}. Empty when the file is missing or counts an earlier day."""
    usage = _read_state(state_path).get("usage")
    if not isinstance(usage, dict) or usage.get("day") != pacific_day(now) or not isinstance(usage.get("used"), dict):
        return {}
    out: dict = {}
    for kh, models in usage["used"].items():
        if isinstance(models, dict):
            out[str(kh)] = {str(m): int(n) for m, n in models.items() if isinstance(n, int) and n >= 0}
    return out


def read_day_exhausted(state_path, now: float) -> set:
    """`key_hash|model` of the pairs a state file holds as used up for the day (and not yet returned)."""
    pairs = _read_state(state_path).get("pairs")
    out = set()
    if isinstance(pairs, dict):
        for name, rec in pairs.items():
            if isinstance(rec, dict) and rec.get("state") == DAY and isinstance(rec.get("until"), (int, float))                     and rec["until"] > now:
                out.add(str(name))
    return out


def key_hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


class Pair:
    def __init__(self, key_index: int, model: str, khash: str):
        self.key_index = key_index
        self.model = model
        self.khash = khash
        self.state = READY
        self.until = 0.0
        self.reason = ""
        self.used = 0  # ticket of the last send through this pair (0 = never): least recently used goes first
        self.window: deque[float] = deque()

    @property
    def label(self) -> str:
        return f"key{self.key_index + 1}/{self.model}"

    def active(self, now: float) -> int:
        while self.window and self.window[0] <= now - WINDOW:
            self.window.popleft()
        return len(self.window)

    def __repr__(self) -> str:
        return f"Pair({self.label}, {self.state})"


@dataclass
class Acquire:
    """Either a pair to use now, or when to ask again (`until`, epoch seconds).
    `exhausted` means asking again will never help (every pair is dead, or the service stayed shut
    for too long); `reason` then says why. `ticket` numbers a granted send; `probe` marks the one
    send let through after a pause; `mark` is the time the limiter released the send."""

    pair: Pair | None = None
    until: float | None = None
    exhausted: bool = False
    reason: str = ""
    ticket: int = 0
    probe: bool = False
    mark: float = 0.0
    all_day: bool = False  # nothing was granted because every usable pair is out for the day


class Limiter:
    """One send rate for the whole process: two sends are never less than 60 / rate apart.

    A send is allowed once the mark of the previous one plus the gap has passed; after an idle
    gap the next send is allowed at once but the one after it still waits a full gap (no bursts,
    no catching up)."""

    def __init__(self):
        self.next_slot = float("-inf")

    def take(self, now: float, rate: float):
        """None when a send may go now (the slot is taken), else the time of the next slot."""
        if now < self.next_slot:
            return self.next_slot
        self.next_slot = now + 60.0 / rate
        return None


class Pool:
    def __init__(self, keys, models, clock=None, state_path=None, rpm=None, on_change=None,
                 shared_limit=True, pace=None):
        if not keys or not models:
            raise ValueError("at least one key and one model are required")
        self.clock = clock or SystemClock()
        self.models = list(models)
        self.pairs: list[Pair] = []
        self._by_model: dict[str, list[Pair]] = {m: [] for m in self.models}
        for m in self.models:
            for i, k in enumerate(keys):
                p = Pair(i, m, key_hash(k))
                self.pairs.append(p)
                self._by_model[m].append(p)
        self._rpm = dict(rpm or {})  # explicit table entries by model
        self.learned: dict[str, int] = {}
        self._lock = threading.Lock()
        self._path = Path(state_path) if state_path else None
        self._on_change = on_change
        self._pending: list[tuple] = []
        self.pace = clean_pace(pace)
        self.limiter: Limiter | None = Limiter() if shared_limit else None  # None: tests with a manual clock
        self._issued = 0  # tickets handed out so far
        # shared throttle state: after a throttled answer nothing is sent for a while, then one probe
        self._phase = OPEN
        self._pause_at = 0.0
        self._pause_until = 0.0
        self._pause_len = SHUT_FIRST
        self._shut_total = 0.0  # pause seconds scheduled in the current shut state
        self._epoch = 0  # tickets below this were issued before the latest pause began
        self._probe_ticket = 0
        self._abort = ""
        self.pauses = 0
        self.retried = 0  # throttled answers that started no pause (the request was just repeated)
        self._recent: deque[bool] = deque(maxlen=THROTTLE_WINDOW)  # recent answers, True = throttled
        self._row = 0  # throttled answers in a row
        self._paused_done = 0.0  # seconds spent in finished pauses
        self._day = pacific_day(self.clock.now())  # Pacific day the send counts below belong to
        self._used: dict[str, dict[str, int]] = {}  # key hash -> model -> requests sent that day
        self._restore()

    # -- limits ----------------------------------------------------------
    def rpm(self, model: str) -> int:
        return self.learned.get(model) or self._rpm.get(model) or default_rpm(model)

    def window_limit(self, model: str) -> int:
        return max(1, int(self.rpm(model) / SAFETY))

    # -- acquiring -------------------------------------------------------
    def acquire(self) -> Acquire:
        try:
            with self._lock:
                return self._acquire_locked()
        finally:
            self._flush_notes()

    def _acquire_locked(self) -> Acquire:
        now = self.clock.now()
        self._refresh(now)
        if self._abort:
            return Acquire(exhausted=True, reason=self._abort)
        if self._phase == PAUSED and now < self._pause_until:
            return Acquire(until=self._pause_until, reason=THROTTLED)
        if self._phase == PROBING:  # the probe decides; everybody else waits for its answer
            return Acquire(until=now + PROBE_POLL, reason=THROTTLED)
        for model in self.models:
            ready = [p for p in self._by_model[model] if p.state == READY]
            if not ready:
                continue
            cap = self.window_limit(model)
            free = [p for p in ready if p.active(now) < cap]
            if free:
                if self.limiter is not None:
                    slot = self.limiter.take(now, self._effective_pace(model))
                    if slot is not None:
                        return Acquire(until=slot, reason="rate")
                # least recently used first, so the daily quota is spent evenly
                pick = min(free, key=lambda p: (p.used, p.key_index))
                pick.window.append(now)
                self._issued += 1
                pick.used = self._issued
                self._count_send(pick, now)
                got = Acquire(pair=pick, ticket=self._issued, mark=now)
                if self._phase == PAUSED:  # the pause is over: this send is the probe
                    self._phase = PROBING
                    self._probe_ticket = got.ticket
                    self._paused_done += now - self._pause_at
                    got.probe = True
                return got
            # Every ready pair of this model is at its rate: wait here instead of
            # falling to the next (weaker) model.
            return Acquire(until=min(p.window[0] for p in ready) + WINDOW, reason="rate")
        alive = [p for p in self.pairs if p.state != DEAD]
        if not alive:
            return Acquire(exhausted=True, reason="no usable key/model pair is left")
        soonest = min(alive, key=lambda p: p.until)
        return Acquire(until=soonest.until, reason=soonest.state, all_day=all(p.state == DAY for p in alive))

    def _count_send(self, pair: Pair, now: float) -> None:
        self._roll_day(now)
        per = self._used.setdefault(pair.khash, {})
        per[pair.model] = per.get(pair.model, 0) + 1
        self._save()

    def _roll_day(self, now: float) -> None:
        day = pacific_day(now)
        if day != self._day:
            self._day, self._used = day, {}

    def day_usage(self) -> dict:
        """Requests sent today per key hash and model: {key_hash: {model: n}} (never the key itself)."""
        with self._lock:
            self._roll_day(self.clock.now())
            return {kh: dict(m) for kh, m in self._used.items()}

    def _effective_pace(self, model: str) -> float:
        """The set pace, but never above the per-key limits of the ready pairs of the model."""
        total = sum(self.window_limit(model) for p in self._by_model[model] if p.state == READY)
        return max(1.0, min(self.pace, total)) if total > 0 else self.pace

    def _refresh(self, now: float) -> None:
        for p in self.pairs:
            if p.state in (COOL, DAY) and p.until <= now:
                p.state = READY
                self._note(p)

    # -- outcomes --------------------------------------------------------
    def success(self, pair: Pair, ticket: int = 0) -> bool:
        """The service answered the request of `ticket` as usual. True when that ends a shut state
        (the answer is the probe's)."""
        with self._lock:
            cleared = self._phase == PROBING and ticket == self._probe_ticket
            if cleared:
                self._phase = OPEN
                self._pause_len = SHUT_FIRST
                self._shut_total = 0.0
                self._recent.clear()
                self._row = 0
                self._save()  # the saved pause is over
            elif self._phase == OPEN and ticket >= self._epoch:
                self._recent.append(False)
                self._row = 0
        return cleared

    def throttled(self, ticket: int) -> dict | None:
        """A 429 without quota details, shared by every key.

        One such answer only means the caller repeats its request. When refusals are dense (at least
        THROTTLE_IN_WINDOW of the last THROTTLE_WINDOW answers, or THROTTLE_IN_ROW in a row) all
        sending stops for a while; the answer of the probe doubles the pause (up to SHUT_MAX).
        Answers to requests that were in flight when the latest pause began change nothing.
        Returns the pause that was started (`until`, `seconds`; `abort` when the pauses add up to
        more than SHUT_LIMIT) or None."""
        with self._lock:
            now = self.clock.now()
            if self._phase == PROBING and ticket == self._probe_ticket:
                self._pause_len = min(self._pause_len * 2, SHUT_MAX)
            elif self._phase == OPEN and ticket >= self._epoch:
                self._recent.append(True)
                self._row += 1
                if self._row < THROTTLE_IN_ROW and sum(self._recent) < THROTTLE_IN_WINDOW:
                    self.retried += 1
                    return None
                self._pause_len = SHUT_FIRST
                self._shut_total = 0.0
            else:
                self.retried += 1
                return None
            length = self._pause_len
            if self._shut_total + length > SHUT_LIMIT:
                minutes = int(SHUT_LIMIT // 60)
                self._abort = f"the service refused every request for {minutes} minutes"
                self._phase = OPEN  # nothing more is sent: `acquire` reports the abort
                return {"until": now, "seconds": 0.0, "abort": self._abort}
            self._shut_total += length
            self._phase = PAUSED
            self._pause_at, self._pause_until = now, now + length
            self._epoch = self._issued + 1
            self.pauses += 1
            self._save()
            return {"until": self._pause_until, "seconds": length, "abort": ""}

    def finish(self, ticket: int) -> None:
        """The send of `ticket` is over. A probe that ended without a verdict (503, timeout, a dead
        key ...) lets the next send be the probe."""
        with self._lock:
            if self._phase == PROBING and ticket == self._probe_ticket:
                self._phase = PAUSED
                self._pause_at = self._pause_until = self.clock.now()

    def paused_seconds(self) -> float:
        """Seconds nothing was sent because of the shared throttle state."""
        with self._lock:
            now = self.clock.now()
            return self._paused_done + (now - self._pause_at if self._phase == PAUSED else 0.0)

    def pace_info(self) -> dict:
        """The set pace, the pace now in force (per-key limits may lower it), pauses so far."""
        with self._lock:
            now = self.clock.now()
            ready = [m for m in self.models if any(p.state == READY for p in self._by_model[m])]
            eff = self._effective_pace(ready[0]) if ready else self.pace
            paused = self._paused_done + (now - self._pause_at if self._phase == PAUSED else 0.0)
            return {"pace": self.pace, "effective": round(eff, 1), "pauses": self.pauses, "retried": self.retried,
                    "paused_seconds": round(paused, 1), "phase": self._phase}

    def minute_limit(self, pair: Pair, retry_after=None, limit=None) -> float:
        """Cool the pair; returns the time it is usable again."""
        with self._lock:
            now = self.clock.now()
            wait = MINUTE_DEFAULT if retry_after is None else retry_after + MINUTE_PAD
            wait = min(max(wait, MINUTE_MIN), MINUTE_MAX)
            if pair.state in (READY, COOL):
                pair.state, pair.until = COOL, max(pair.until if pair.state == COOL else 0.0, now + wait)
            pair.reason = "minute"
            if limit and limit != self.rpm(pair.model):
                self.learned[pair.model] = int(limit)
            self._note(pair)
            self._save()
            until = pair.until
        self._flush_notes()
        return until

    def day_limit(self, pair: Pair) -> float:
        with self._lock:
            pair.state, pair.until, pair.reason = DAY, day_return(self.clock.now()), "day"
            self._note(pair)
            self._save()
            until = pair.until
        self._flush_notes()
        return until

    def dead(self, pair: Pair, reason: str) -> None:
        with self._lock:
            pair.state, pair.until, pair.reason = DEAD, 0.0, reason
            self._note(pair)
            self._save()
        self._flush_notes()

    def dead_model(self, model: str, reason: str) -> None:
        with self._lock:
            for p in self._by_model.get(model, []):
                p.state, p.until, p.reason = DEAD, 0.0, reason
                self._note(p)
            self._save()
        self._flush_notes()

    def revive_dead(self) -> None:
        """Give dead pairs another chance (after the user fixed a key or a model name)."""
        with self._lock:
            for p in self.pairs:
                if p.state == DEAD:
                    p.state, p.reason = READY, ""
                    self._note(p)
            self._save()
        self._flush_notes()

    # -- observation -----------------------------------------------------
    def states(self) -> list[dict]:
        with self._lock:
            now = self.clock.now()
            self._refresh(now)
            rows = [
                {"label": p.label, "key": p.key_index + 1, "model": p.model, "state": p.state,
                 "until": p.until if p.state in (COOL, DAY) else None, "reason": p.reason,
                 "recent": p.active(now)}
                for p in self.pairs
            ]
        self._flush_notes()
        return rows

    def _note(self, p: Pair) -> None:
        self._pending.append((p.label, p.state, p.until if p.state in (COOL, DAY) else None, p.reason))

    def _flush_notes(self) -> None:
        with self._lock:
            items, self._pending = self._pending, []
        if self._on_change:
            for it in items:
                self._on_change(*it)

    # -- persistence -----------------------------------------------------
    def _save(self) -> None:
        if self._path is None:
            return
        pairs = {}
        for p in self.pairs:
            if p.state in (COOL, DAY, DEAD):
                pairs[f"{p.khash}|{p.model}"] = {"state": p.state, "until": p.until, "reason": p.reason}
        data = {"version": 1, "learned": self.learned, "pairs": pairs,
                "usage": {"day": self._day, "used": self._used}}
        if self._phase in (PAUSED, PROBING):  # the shared pause outlives a restart
            data["shut"] = {"until": self._pause_until, "length": self._pause_len, "total": self._shut_total}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self._path, json.dumps(data, indent=1))
        except OSError:
            pass

    def _restore(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        learned = data.get("learned")
        if isinstance(learned, dict):
            self.learned = {m: int(n) for m, n in learned.items() if m in self._by_model and isinstance(n, int)}
        saved = data.get("pairs") if isinstance(data.get("pairs"), dict) else {}
        now = self.clock.now()
        used = read_day_usage(self._path, now)
        self._used = {kh: dict(m) for kh, m in used.items()}
        for p in self.pairs:
            rec = saved.get(f"{p.khash}|{p.model}")
            if not isinstance(rec, dict):
                continue
            state, until = rec.get("state"), rec.get("until")
            if state == DEAD:
                p.state, p.reason = DEAD, str(rec.get("reason") or "")
            elif state in (COOL, DAY) and isinstance(until, (int, float)) and until > now:
                p.state, p.until, p.reason = state, float(until), str(rec.get("reason") or "")
        shut = data.get("shut")
        if isinstance(shut, dict):
            try:
                until, length = float(shut["until"]), float(shut["length"])
                total = float(shut.get("total", 0.0))
            except (KeyError, TypeError, ValueError):
                return
            # a pause that already ended still leads to one probe, not to a full-speed start
            self._phase = PAUSED
            self._pause_at = now
            self._pause_until = max(until, now)
            self._pause_len = min(max(length, SHUT_FIRST), SHUT_MAX)
            self._shut_total = max(total, 0.0)
