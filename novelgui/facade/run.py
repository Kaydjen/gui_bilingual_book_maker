"""Running a job or a sample and reading the job record: plain functions over the core (no Qt, no Tk).

`run_task` only relays the core's events (the core runs its own threads); with a `RunEvents` passed in it folds
them there and wakes the GUI once per batch instead of posting every event.
"""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from novelcore import Series
from novelcore import checks as core_checks
from novelcore import frontier as core_frontier
from novelcore import job as core_job
from novelcore.htmlscan import strip_markers
from novelcore.pool import DEFAULT_PACE, PACE_MAX, PACE_MIN, day_return  # noqa: F401
from novelcore.run import Runner, from_ranges
from novelcore.store import ChapterLog
from novelcore.terms import FILE_NAME as TERMS_FILE
from novelcore.terms import TermBase

from ..jobstate import JobView
from .checks import fresh_marks

HAS_CHAPTERS = "chapters" in inspect.signature(core_job.Job.__init__).parameters
HAS_GATE_FOR = callable(getattr(core_frontier, "gate_for", None))
SeriesBusy = core_job.SeriesBusy


@dataclass
class RunConfig:
    keys: list
    models: list
    pace: float | None = None
    base_url: str | None = None


def clean_pace(value):
    """Pace in requests a minute, or None for the core default; raises ValueError outside 1-120."""
    if value in (None, ""):
        return None
    p = float(value)
    if not PACE_MIN <= p <= PACE_MAX:
        raise ValueError("pace must be from %d to %d" % (PACE_MIN, PACE_MAX))
    return p


def default_pace() -> int:
    return DEFAULT_PACE


def job_view(series_path) -> JobView:
    """The job of a series as the window shows it (cheap: reads the record and the lock)."""
    st = core_job.job_status(series_path)
    rec = st["job"]
    if rec is None:
        return JobView()
    state = "interrupted" if st["interrupted"] else rec["state"]
    if isinstance(rec.get("chapters"), list):
        chapters = tuple(from_ranges(rec["chapters"]))
    else:
        last = rec.get("last")
        chapters = tuple(range(rec.get("first") or 0, last + 1)) if isinstance(last, int) else ()
    blocked = st["blocked_chapter"]
    return JobView(state, rec["book"], chapters, st["blocks_done"], st["blocks_total"], st["chapters_done"],
                   st["chapters_total"], st["blocks_failed"], st["terms_pending"],
                   blocked if isinstance(blocked, int) else None, rec.get("wake_at"), str(rec.get("error") or ""),
                   foreign=bool(st["running"] and st["pid"] != os.getpid()),
                   dead=dead_reasons(series_path) if state == "failed" else ())


def dead_reasons(series_path) -> tuple:
    """Why the pool holds key/model pairs of the series as dead (`invalid key`, `model not found`)."""
    try:
        data = json.loads((Path(series_path) / ".state" / "pool.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    pairs = data.get("pairs") if isinstance(data, dict) else None
    if not isinstance(pairs, dict):
        return ()
    return tuple(sorted({str(r.get("reason") or "") for r in pairs.values()
                         if isinstance(r, dict) and r.get("state") == "dead"} - {""}))


def revive_dead_pairs(series_path, keys, models) -> None:
    """Give the dead key/model pairs of the series another chance (the pairs are keyed by key hash and model, so
    a key or a model that was fixed outside the app stays marked dead otherwise). Uses the core's own call."""
    if not keys or not models:
        return
    from novelcore.pool import Pool
    Pool(list(keys), list(models), state_path=Path(series_path) / ".state" / "pool.json").revive_dead()


def set_job_state(series_path, state: str) -> bool:
    """Rewrite the state of the series' job record (`stopped` ends a quota wait, `finished` discards an
    unfinished job; translated chapters are never touched). False when there is no record."""
    rec = core_job.read_job(series_path)
    if rec is None:
        return False
    rec.update(state=state, wake_at=None, terms_pending=0, blocked_chapter=None, error=None, updated=time.time())
    core_job.write_job(series_path, rec)
    return True


def holder_alive(info) -> bool:
    """Whether the process named in a lock record (pid, start time) is still the one that wrote it."""
    return bool(core_job._holder_alive(info))


class RunHandle:
    """Control of one run (a job or a sample) started by `run_task` / `sample_task`."""

    def __init__(self):
        self.job = None
        self.runner = None
        self.stopping = False
        self.finished = threading.Event()

    def stop(self) -> None:
        self.stopping = True
        target = self.job or self.runner
        if target is not None:
            target.stop()


def make_gate(ctx, handle, series: Series, book: str):
    """Callable chapter -> unreviewed terms. None when the core supplies its own gate (frontier.gate_for)."""
    if HAS_GATE_FOR:
        return None
    base = TermBase.load(series.path / TERMS_FILE, series.target_tag)
    fr = core_frontier.Frontier.for_series(series, book, base)
    fr.scan(progress=lambda d, t: ctx.emit(("scan", d, t)), cancel=lambda: handle.stopping)
    return fr.check_chapter


def run_task(ctx, handle: RunHandle, series_path, book: str, chapters, cfg: RunConfig, resume: bool = False,
             retry=(), events=None):
    """Start a job (or continue the recorded one) and relay its events; returns the run summary.
    `retry`: marks (chapter, block, source hash, text digest) of check findings; the core marks exactly the ones
    that still describe the block and a job over their chapters follows (checks.retry, called only here, at the
    real start). Emits ("event", Event), ("scan", done, total), ("busy", message). With `events` (a
    `ctl.runevents.RunEvents`) the core events are folded there on this thread and only ("wake", urgent) is
    emitted when the folded state turns dirty (or at once for a terminal event)."""
    relay = _relay(ctx, events)
    series = Series.open(series_path)
    try:
        try:
            gate = make_gate(ctx, handle, series, book)
            if handle.stopping:
                return {"stopped": True}
            kw = dict(base_url=cfg.base_url, pace=cfg.pace)
            if gate is not None:
                kw["gate"] = gate
            if resume:
                job = core_job.resume(series, cfg.keys, cfg.models, **kw)
            elif retry:
                marks = fresh_marks(series, book, retry)
                if not marks:
                    raise core_job.JobError("These blocks changed since the check: nothing to translate again.")
                job = core_checks.retry(series, book, marks, cfg.keys, cfg.models, **kw)
            elif HAS_CHAPTERS:
                job = core_job.Job(series, book, cfg.keys, cfg.models, chapters=list(chapters), **kw)
            else:
                job = core_job.Job(series, book, cfg.keys, cfg.models, min(chapters), max(chapters), **kw)
            handle.job = job
            job.start()
        except (core_job.SeriesBusy, core_job.JobError) as exc:
            ctx.emit(("busy", str(exc)))
            return {"busy": True}
        sent_stop = False
        while True:
            done = False
            for ev in job.drain():
                relay(ev)
                done = done or ev.kind == "done"
            if done:
                break
            if handle.stopping and not sent_stop:
                sent_stop = True
                job.stop()
            if job._thread is not None and not job._thread.is_alive():
                for ev in job.drain():
                    relay(ev)
                break
            time.sleep(0.05)
        job.join()
        return {"stopped": handle.stopping, "error": job.error or (str(job.exception) if job.exception else "")}
    finally:
        handle.finished.set()


def _relay(ctx, events):
    if events is None:
        return lambda ev: ctx.emit(("event", ev))

    def fold(ev):
        wake = events.feed(ev)
        if wake:
            ctx.emit(("wake", wake == "urgent"))
    return fold


def sample_task(ctx, handle: RunHandle, series_path, book: str, chapter: int, blocks: int, cfg: RunConfig):
    """Translate the first blocks of one chapter into samples/ (never gated, never written to chapters/)."""
    series = Series.open(series_path)
    try:
        r = Runner(series, book, cfg.keys, cfg.models, state_path=series.path / ".state" / "pool.json",
                   base_url=cfg.base_url, pace=cfg.pace, end_on_quota=True, gate=None)
        r.listener = lambda ev: ctx.emit(("event", ev))
        handle.runner = r
        if handle.stopping:
            return {"stopped": True}
        return r.sample(chapter, blocks)
    finally:
        handle.finished.set()


def sample_rows(series_path, book: str, chapter: int, n: int) -> list:
    """[(source text, translation or None, reason)] of the first n blocks of a sampled chapter."""
    series = Series.open(series_path)
    with series.open_book(book) as b:
        ch = b.chapters[chapter]
        log = ChapterLog(series.sample_log(book, ch).path)
        rows = []
        for blk in b.blocks(ch)[:n]:
            rec = log.lookup(blk.index, blk.sha)
            src = " ".join(strip_markers(blk.text).split())
            if rec is None:
                rows.append((src, None, ""))
            elif rec.get("status") == "ok":
                rows.append((src, " ".join(strip_markers(rec["text"]).split()), ""))
            else:
                rows.append((src, None, str(rec.get("reason") or "failed")))
        return rows

