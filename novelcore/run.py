"""Runner: chapters in parallel, blocks of a chapter in order, over a pool of (key, model) pairs."""

from __future__ import annotations

import errno
import heapq
import json
import os
import queue
import random
import threading
from dataclasses import dataclass, field

from . import gemini
from .clock import SystemClock
from .htmlscan import strip_markers
from .pool import THROTTLED, Pool, QuotaExhausted, clean_pace, key_hash
from .termmatch import hook_for_series
from .translate import GroupTranslator, ServiceDown, Stopped

MAX_UNAVAILABLE = 12  # consecutive service failures (503, timeout) of one request before giving up
MAX_REFUSED = 10  # consecutive refused requests (bad request) before giving up
RETRY_FIRST, RETRY_MAX = 2.0, 60.0  # backoff before repeating a request the service could not serve
THROTTLE_RETRY_FIRST = 5.0  # the same for a request that got a lone throttled answer
RETRY_JITTER = 0.25  # the backoff is multiplied by a random factor within 1 +/- this
DEFAULT_IN_FLIGHT = 12  # requests in flight at once


def retry_delay(attempt: int, rng, first: float = RETRY_FIRST) -> float:
    """Seconds to wait before repeat number `attempt` (1, 2, ...): first, 2*first ... capped at 60, +/- 25%."""
    base = min(first * 2.0 ** (attempt - 1), RETRY_MAX)
    return base * rng.uniform(1.0 - RETRY_JITTER, 1.0 + RETRY_JITTER)


class DiskError(Exception):
    """A translation could not be written (disk full or any other write error); nothing of it counts as done."""

    def __init__(self, exc: OSError):
        full = exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == 112
        self.reason = "disk full" if full else (str(exc) or exc.__class__.__name__)
        super().__init__(self.reason)


def normalize_chapters(chapters) -> list[int]:
    """Sorted unique non-negative chapter indices of a selection list."""
    return sorted({int(i) for i in chapters if int(i) >= 0})


def to_ranges(indices) -> list[list[int]]:
    """[2, 3, 4, 9] -> [[2, 4], [9, 9]] (the compact form kept in the job record)."""
    out: list[list[int]] = []
    for i in normalize_chapters(indices):
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def from_ranges(ranges) -> list[int]:
    """Inverse of to_ranges; malformed items are ignored."""
    out: list[int] = []
    for r in ranges or []:
        if isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(x, int) for x in r):
            out.extend(range(r[0], r[1] + 1))
    return normalize_chapters(out)


@dataclass
class Event:
    kind: str
    data: dict = field(default_factory=dict)
    at: float = 0.0

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)


class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.counts: dict[str, int] = {}
        self.stamps: list[float] = []

    def add(self, kind: str, at: float | None = None) -> None:
        with self._lock:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            if at is not None and kind == "request":
                self.stamps.append(at)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.counts)

    def peak_per_minute(self) -> int:
        with self._lock:
            ts = sorted(self.stamps)
        best, lo = 0, 0
        for hi, t in enumerate(ts):
            while ts[lo] <= t - 60:
                lo += 1
            best = max(best, hi - lo + 1)
        return best


class Requester:
    """Callable `ask(system, user, schema) -> Result`: picks a pair, sends, reacts to quota errors."""

    def __init__(self, pool: Pool, keys, clock, stop: threading.Event, emit, temperature=None,
                 base_url=None, timeout=300, generate=None, stats=None, end_on_quota=False):
        self.end_on_quota = end_on_quota
        self.pool, self.keys, self.clock, self.stop = pool, list(keys), clock, stop
        self.emit = emit
        self.temperature, self.base_url, self.timeout = temperature, base_url, timeout
        self.generate = generate or gemini.generate
        self.stats = stats or Stats()
        self.local = threading.local()
        self._lock = threading.Lock()
        self._waiting: float | None = None
        self._refused = 0
        self.jitter = random.Random()

    @property
    def last_model(self) -> str:
        return getattr(self.local, "model", "")

    def __call__(self, system, user, schema):
        unavailable = refused = 0
        while True:
            if self.stop.is_set():
                raise Stopped()
            got = self.pool.acquire()
            if got.exhausted:
                raise ServiceDown(got.reason or "no usable key/model pair is left")
            if got.pair is None:
                if got.all_day and self.end_on_quota:
                    raise QuotaExhausted(got.until)
                self._wait(got)
                continue
            pair = got.pair
            sent = self.clock.now()
            self.stats.add("request", sent)
            if got.probe:
                self._debug({"event": "probe", "at": sent, "ticket": got.ticket})
            try:
                result = self._send(pair, sent, got, system, user, schema)
            except gemini.MinuteLimit as exc:
                self.stats.add("minute")
                self.pool.minute_limit(pair, exc.retry_after, exc.limit)
            except gemini.Throttled:
                # the request is repeated; it fails nothing. A lone refusal waits a short backoff,
                # dense refusals pause every send (the request goes on when sending is allowed again)
                self.stats.add("throttled")
                pause = self.pool.throttled(got.ticket)
                if pause is not None:
                    self._debug({"event": "pause", "at": self.clock.now(), "seconds": pause["seconds"],
                                 "until": pause["until"], "abort": pause["abort"]})
                    self.emit("paused", pause)
                else:
                    refused += 1
                    self.pool.finish(got.ticket)
                    self._sleep(retry_delay(refused, self.jitter, THROTTLE_RETRY_FIRST))
            except gemini.DayLimit:
                self.stats.add("day")
                self.pool.day_limit(pair)
            except gemini.Unavailable as exc:
                # 503 or a timeout: repeat the same request after a backoff; no pair is cooled
                self.stats.add(exc.kind)
                self.pool.finish(got.ticket)  # a probe without a verdict must not hold the others back
                unavailable += 1
                if unavailable >= MAX_UNAVAILABLE:
                    raise ServiceDown("the service keeps failing") from None
                self._sleep(retry_delay(unavailable, self.jitter))
            except gemini.InvalidKey:
                self.stats.add("invalid_key")
                self.pool.dead(pair, "invalid key")
            except gemini.ModelNotFound:
                self.stats.add("model_not_found")
                self.pool.dead_model(pair.model, "model not found")
            except (gemini.EmptyAnswer, gemini.Truncated) as exc:
                self.stats.add(exc.kind)
                self.local.model = pair.model
                self._served(pair, got.ticket)
                raise
            except gemini.BadRequest:
                self.stats.add("bad_request")
                self.local.model = pair.model
                with self._lock:
                    self._refused += 1
                    if self._refused >= MAX_REFUSED:
                        raise ServiceDown("requests keep being refused") from None
                raise
            else:
                self.stats.add("ok")
                self.local.model = pair.model
                self._served(pair, got.ticket)
                return result
            finally:
                self.pool.finish(got.ticket)

    def _debug(self, record: dict) -> None:
        """With NOVELCORE_DEBUG_LOG set, append one JSON line (requests, probes, pauses)."""
        path = os.environ.get("NOVELCORE_DEBUG_LOG")
        if path:
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

    def _send(self, pair, sent, got, system, user, schema):
        """One HTTP call; with NOVELCORE_DEBUG_LOG set, one line per request (key hash, limiter mark,
        times, outcome)."""
        status, extra = "ok", ""
        try:
            return self.generate(pair.model, self.keys[pair.key_index], system, user, schema,
                                 self.temperature, self.base_url, self.timeout)
        except gemini.GeminiError as exc:
            status = exc.kind
            extra = getattr(exc, "quota_id", "")
            raise
        finally:
            self._debug({"key": key_hash(self.keys[pair.key_index]), "model": pair.model, "ticket": got.ticket,
                         "mark": got.mark, "sent": sent, "answered": self.clock.now(), "status": status,
                         "quota": extra, "chars": len(user)})

    def _served(self, pair, ticket) -> None:
        cleared = self.pool.success(pair, ticket)
        with self._lock:
            self._refused = 0
            was, self._waiting = self._waiting, None
        if cleared:
            self._debug({"event": "resume", "at": self.clock.now(), "ticket": ticket})
            self.emit("unpaused", {})
        if was is not None:
            self.emit("resumed", {})

    def _sleep(self, seconds: float) -> None:
        """Wait the whole time (the clock may cut a long wait short); a stop request ends it."""
        end = self.clock.now() + seconds
        while (left := end - self.clock.now()) > 0:
            if self.clock.wait(self.stop, left):
                raise Stopped()

    def _wait(self, got) -> None:
        now = self.clock.now()
        delay = max((got.until or now) - now, 0.01)
        if got.reason not in ("rate", THROTTLED):
            with self._lock:
                fresh = self._waiting is None or abs(self._waiting - got.until) > 1.0
                self._waiting = got.until
            if fresh:
                self.emit("waiting", {"until": got.until, "reason": got.reason})
        if self.clock.wait(self.stop, delay):
            raise Stopped()


class Runner:
    def __init__(self, series, book_name, keys, models, first=0, last=None, *, clock=None,
                 base_url=None, in_flight=None, terms_for=None, state_path=None, rpm=None,
                 timeout=300, generate=None, shared_limit=True, pace=None, end_on_quota=False,
                 chapters=None, gate=None):
        """`pace`: sends per minute in total (1-120); `in_flight`: requests at once. Both fall back to the
        series settings `pace` and `in_flight`, then to 24 and 12. With `end_on_quota` the run ends (event
        `quota`, `quota_until` set) when every pair is used up for the day, instead of waiting for it.
        `listener(event)`, if set, sees every event in the emitting thread before it is queued.
        `chapters`: a list of chapter indices (any order, duplicates and out-of-range ones dropped)
        instead of first..last. `gate(index) -> int`: unreviewed terms of that chapter; the run translates
        the selected chapters (ascending) before the first one with a non-zero value and then reports it
        as `blocked` (event `terms`, summary key `blocked`). A chapter that is already fully translated
        never blocks. None or False: no gate."""
        self.series = series
        self.book_name = book_name
        self.keys = list(keys)
        self.models = list(models)
        self.first, self.last = first, last
        self.chapters = normalize_chapters(chapters) if chapters is not None else None
        self.gate = gate or None
        self.blocked: dict | None = None  # {"index", "title", "terms"[, "error"]}: where the gate stopped the run
        self.clock = clock or SystemClock()
        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.user_stopped = False  # stop() was called, as opposed to the run halting itself on an error
        self.listener = None
        self.fatal: str | None = None  # "disk": a write failed; "service": the service kept failing
        self.quota_until: float | None = None
        self.stats = Stats()
        # a series with a terms.json supplies the term lines itself; without the file nothing changes
        self.terms_for = terms_for if terms_for is not None else hook_for_series(series, self._chapter_blocks)
        settings = series.settings
        self.in_flight = max(1, int(in_flight or settings.get("in_flight") or DEFAULT_IN_FLIGHT))
        self.pace = clean_pace(pace if pace is not None else settings.get("pace"))
        self.pool = Pool(self.keys, self.models, self.clock, state_path, rpm, on_change=self._pair_event,
                         shared_limit=shared_limit, pace=self.pace)
        self.requester = Requester(self.pool, self.keys, self.clock, self.stop_event, self._emit,
                                   float(series.settings.get("temperature") or 1.0), base_url, timeout,
                                   generate, self.stats, end_on_quota)
        self._book = None
        self._book_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.totals = {"ok": 0, "failed": 0, "flagged": 0, "reused": 0}
        self._tot_lock = threading.Lock()

    def _chapter_blocks(self, chapter):
        with self._book_lock:
            return list(self._book.blocks(chapter))

    # -- events ----------------------------------------------------------
    def _emit(self, kind: str, data: dict) -> None:
        ev = Event(kind, data, self.clock.now())
        if self.listener is not None:
            self.listener(ev)
        self.events.put(ev)

    def _pair_event(self, label, state, until, reason) -> None:
        self._emit("pair", {"label": label, "state": state, "until": until, "reason": reason})

    def drain(self) -> list[Event]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    # -- control ---------------------------------------------------------
    def stop(self) -> None:
        """Finish the requests in flight, record them, then stop."""
        self.user_stopped = True
        self.stop_event.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="novelcore-run", daemon=True)
        self._thread.start()

    def join(self, timeout=None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # -- running ---------------------------------------------------------
    def _select(self):
        book = self._book
        n = len(book.chapters)
        if self.chapters is not None:
            return [book.chapters[i] for i in self.chapters if i < n]
        last = n - 1 if self.last is None else min(self.last, n - 1)
        return [book.chapters[i] for i in range(max(self.first, 0), last + 1)]

    def _fully_done(self, chapter) -> bool:
        """Every block of the chapter has a finished record (no request is needed for it)."""
        log = self.series.chapter_log(self.book_name, chapter)
        blocks = self._chapter_blocks(chapter)
        if not blocks:
            return True
        if not log.path.exists():
            return False
        return all(log.done(b.index, b.sha) for b in blocks)

    def _apply_gate(self, chapters: list) -> list:
        """The chapters before the first one the gate holds back (self.blocked says which)."""
        if self.gate is None:
            return chapters
        for pos, c in enumerate(chapters):
            if self.stop_event.is_set():
                return []
            error = None
            try:
                terms = int(self.gate(c.index))
            except Exception as exc:  # unknown count: never "allowed"
                terms, error = -1, f"{exc.__class__.__name__}: {exc}"
            if terms == 0:
                continue
            # the parse and the log are only looked at for a chapter the gate holds back
            if self._fully_done(c):
                continue
            with self._book_lock:
                title = c.title
            self.blocked = {"index": c.index, "title": title, "terms": terms}
            if error:
                self.blocked["error"] = error
            return chapters[:pos]
        return chapters

    def run(self) -> dict:
        self._book = self.series.open_book(self.book_name)
        try:
            selected = self._select()
            chapters = self._apply_gate(selected)
            with self._book_lock:
                counted = sum(1 for c in chapters if not c.is_toc)
            todo: queue.Queue = queue.Queue()
            for c in chapters:
                todo.put(c)
            # every worker has one request in flight at a time, so the workers are the in-flight cap
            width = max(1, min(self.in_flight, len(chapters)))
            # `pages` are the chapters sent now; `selected` all that were asked for (the gate may hold some back)
            self._emit("started", {"chapters": counted, "pages": len(chapters), "workers": width,
                                   "pace": self.pace, "selected": len(selected)})
            threads = [threading.Thread(target=self._worker, args=(todo,), name=f"novelcore-w{i}")
                       for i in range(width)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            self._book.close()
        if self.blocked:
            self._emit("terms", dict(self.blocked))
        summary = self._summary()
        self._emit("done", summary)
        return summary

    def _summary(self) -> dict:
        """Counters of the run: requests by outcome, blocks, and the throttle state: `throttled` answers
        in all, of which `retried` were lone refusals that were only repeated, and `pauses` begun
        (`paused_seconds` nothing was sent)."""
        info = self.pool.pace_info()
        requests = self.stats.snapshot()
        return {"stopped": self.stop_event.is_set(), "error": self.error, "requests": requests,
                "blocks": dict(self.totals), "fatal": self.fatal, "quota_until": self.quota_until,
                "blocked": dict(self.blocked) if self.blocked else None,
                "throttle": {"throttled": requests.get("throttled", 0), "retried": info["retried"],
                             "pauses": info["pauses"], "paused_seconds": info["paused_seconds"]},
                "pace": {"set": info["pace"], "in_force": info["effective"]}}

    def _worker(self, todo: queue.Queue) -> None:
        self.clock.enter()
        try:
            while not self.stop_event.is_set():
                try:
                    chapter = todo.get_nowait()
                except queue.Empty:
                    return
                try:
                    self._chapter(chapter, self.series.chapter_log(self.book_name, chapter), True, None)
                except Stopped:
                    return
                except ServiceDown as exc:
                    self._halt("service", str(exc))
                    return
                except DiskError as exc:
                    self._halt("disk", exc.reason)
                    return
                except QuotaExhausted as exc:
                    with self._tot_lock:
                        first = self.quota_until is None
                        self.quota_until = exc.until if first else min(self.quota_until, exc.until)
                    if first:
                        self._emit("quota", {"until": exc.until})
                    self.stop_event.set()
                    return
        finally:
            self.clock.leave()

    def _halt(self, kind: str, message: str) -> None:
        """The run cannot go on: remember why, tell the listener, let the requests in flight finish."""
        with self._tot_lock:
            first = self.fatal is None
            if first:
                self.fatal, self.error = kind, message
        if first:
            self._emit("error", {"message": message})
        self.stop_event.set()

    def sample(self, chapter_index: int, blocks: int = 50) -> dict:
        """Translate the first `blocks` blocks of one chapter into samples/ only."""
        self._book = self.series.open_book(self.book_name)
        self.clock.enter()
        try:
            chapter = self._book.chapters[chapter_index]
            log = self.series.sample_log(self.book_name, chapter)
            log.clear()
            self._emit("started", {"chapters": 1, "pages": 1, "workers": 1})
            try:
                self._chapter(chapter, log, False, blocks)
            except (Stopped, ServiceDown, QuotaExhausted) as exc:
                self.error = str(exc) or "stopped"
                self._emit("error", {"message": self.error})
        finally:
            self.clock.leave()
            self._book.close()
        summary = self._summary()
        self._emit("done", summary)
        return summary

    def _chapter(self, chapter, log, reuse: bool, limit) -> None:
        with self._book_lock:
            blocks = list(self._book.blocks(chapter))
            title, is_toc = chapter.title, chapter.is_toc
        if limit is not None:
            blocks = blocks[:limit]
        index = chapter.index
        self._emit("chapter_started", {"index": index, "title": title, "blocks": len(blocks), "toc": is_toc})
        done: dict[int, tuple[str, str]] = {}
        pending = []
        reused = []
        now = self.clock.now()
        for b in blocks:
            rec = log.done(b.index, b.sha)
            if rec is None and reuse:
                hit = self.series.find_done(b.sha)
                if hit is not None:
                    rec = {"i": b.index, "src_sha": b.sha, "text": hit["text"], "model": hit.get("model", ""),
                           "at": now, "status": "ok", "flags": list(hit.get("flags") or []), "reuse": True}
                    reused.append(rec)
            if rec is not None:
                done[b.index] = (strip_markers(b.text), strip_markers(rec["text"]))
            else:
                pending.append(b)
        self._write(log, reused)
        self._add_totals(reused=len(reused))
        counts = {"ok": len(done), "failed": 0, "flagged": 0}
        buffer: list[dict] = []

        def context(first_index):
            keys = heapq.nlargest(3, (i for i in done if i < first_index))
            return [done[i] for i in sorted(keys)]

        def on_ok(b, text, flags):
            buffer.append({"i": b.index, "src_sha": b.sha, "text": text, "model": self.requester.last_model,
                           "at": self.clock.now(), "status": "ok", "flags": flags})
            done[b.index] = (strip_markers(b.text), strip_markers(text))
            counts["ok"] += 1
            counts["flagged"] += 1 if flags else 0
            self._add_totals(ok=1, flagged=1 if flags else 0)

        def on_fail(b, reason):
            buffer.append({"i": b.index, "src_sha": b.sha, "text": "", "model": self.requester.last_model,
                           "at": self.clock.now(), "status": "failed", "reason": reason})
            counts["failed"] += 1
            self._add_totals(failed=1)
            self._emit("block_failed", {"index": index, "block": b.index, "reason": reason})

        def flush():
            batch = buffer[:]
            buffer.clear()
            try:
                self._write(log, batch)
            except DiskError:  # what was not written is not done
                self._add_totals(ok=-sum(r["status"] == "ok" for r in batch),
                                 failed=-sum(r["status"] != "ok" for r in batch),
                                 flagged=-sum(bool(r.get("flags")) for r in batch))
                raise

        def commit():
            flush()
            self._emit("progress", {"index": index, "done": counts["ok"], "total": len(blocks),
                                    "failed": counts["failed"],
                                    "paused_seconds": self.pool.paused_seconds()})

        terms_fn = (lambda group: self.terms_for(chapter, group)) if self.terms_for else None
        tr = GroupTranslator(self.requester, self.series.system_prompt(), self.series.target_tag,
                             self.series.per_request, terms_fn, context, self.stop_event.is_set)
        complete = True
        try:
            tr.run(pending, on_ok, on_fail, commit)
        except (Stopped, ServiceDown, QuotaExhausted, DiskError):
            complete = False
            raise
        finally:
            try:
                flush()
            finally:
                self._emit("chapter_finished", {"index": index, "title": title, "toc": is_toc, "ok": counts["ok"],
                                                "failed": counts["failed"], "flagged": counts["flagged"],
                                                "blocks": len(blocks),
                                                "complete": complete and counts["failed"] == 0,
                                                "requests": tr.out.requests})

    @staticmethod
    def _write(log, recs) -> None:
        try:
            log.append(recs)
        except OSError as exc:
            raise DiskError(exc) from exc

    def _add_totals(self, ok=0, failed=0, flagged=0, reused=0) -> None:
        with self._tot_lock:
            self.totals["ok"] += ok
            self.totals["failed"] += failed
            self.totals["flagged"] += flagged
            self.totals["reused"] += reused

