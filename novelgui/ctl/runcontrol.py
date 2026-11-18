"""The translation run of the window: ONE place that starts, watches and stops jobs (window_spec 7.2, 13.2-13.4).

Every start - the Run button, Continue, Replace, the queue's next item, the wake-up after the daily quota - goes
through `RunControl.start`, which refuses while another job runs. The queue and its rules live in `jobqueue`;
this class carries them out and keeps the queue in the window state (never in the library).

No Qt, no Tk, no polling: everything it needs is injected.
- `submit(fn, on_result, on_error, on_item, lane)`: the lanes; the run relay goes to lane "run".
- `timer(ms, fn) -> handle with cancel()`: single shot. The quota wake-up is ONE timer armed to `wake_at`
  (re-armed whenever the wait changes, checked again by `activated()`); progress repaints go through a
  leading-edge throttle on the same timer.
- `sink`: `runs_changed(starting=False, ended=None, tick=False)`, `run_progress(run)`, optional `message(text)`
  and `closed()`.
- `view() -> (series path, book, chapter infos)` of the screen, `keys()`, `models()`, `run_config()`,
  `setting(name)`, `flush()` (write the window state now), `keep_awake(on)`.
Closing is a state: `shutdown()` stops the run and `closed()` is called when the run has finished (or after the
60 s cap), never a busy loop.
"""

from __future__ import annotations

import math
import time

from .. import jobqueue as jq
from .. import jobstate as js
from .. import platform
from ..facade import books as fbooks
from ..facade import run as frun
from ..jobqueue import Item, Queue, Scheduler
from . import eta
from .runevents import URGENT, RunEvents
from .throttle import LeadingThrottle

ENDED = {"finished": jq.FINISHED, "waiting_quota": jq.QUOTA, "waiting_terms": jq.TERMS, "stopped": jq.STOPPED,
         "failed": jq.FAILED}
PROGRESS_GATE_MS = 100
WAKE_CAP_S = 600            # a long wait is re-armed in steps (a sleeping PC skews a single long timer)
CLOSE_CAP_MS = 60_000


class Run:
    """One job or sample that this window runs now."""

    def __init__(self, kind, series, name, book, chapters, resume, clock=time.time):
        self.kind = kind                    # job | sample
        self.series = series                # series folder
        self.name = name
        self.book = book
        self.chapters = list(chapters)
        self.resume = resume
        self.handle = frun.RunHandle()
        self.events = RunEvents()
        self.snapshot = None                # the latest RunSnapshot the screen got
        self.stopping = False
        self.user_stop = False
        self.busy_text = ""                 # the core refused to start (another process holds the series)
        self.started = clock()
        self.done_at_start = 0

    @property
    def paused_until(self):
        return self.events.paused_until

    @property
    def retry_until(self):
        return self.events.retry_until

    @property
    def last_error(self) -> str:
        return self.events.last_error

    @last_error.setter
    def last_error(self, text: str) -> None:
        self.events.note_error(text)

    @property
    def chap(self):
        return self.events.chap_view()


class RunControl:
    def __init__(self, *, winstate, submit, timer, sink, keys, models, run_config, setting=lambda name: None,
                 view=lambda: ("", "", []), flush=lambda: None, keep_awake=None, clock=time.time):
        self.winstate = winstate
        self.submit = submit
        self.timer = timer
        self.sink = sink
        self.keys = keys
        self.models = models
        self.run_config = run_config
        self.setting = setting
        self.view = view
        self.flush = flush
        self._keep_awake = keep_awake or (lambda on: platform.keep_awake(on))
        self.clock = clock
        self.queue = Queue.from_list(winstate.get("queue", [], list))
        self.sched = Scheduler(self.queue, clock=clock)
        self.run: Run | None = None
        self.last_series = ""               # the series of the latest job of this window (header state)
        self.closing = False
        self.closed = False
        self.waiting_elsewhere: tuple | None = None     # (wake_at, series) of a saved job that waits for the quota
        self.last_start_error = ""
        self._awake = False
        self._wake_timer = None
        self._wake_armed: float | None = None
        self._close_timer = None
        self._throttle = LeadingThrottle(timer, self._flush_progress, PROGRESS_GATE_MS)

    # ------------------------------------------------------------- queries
    @property
    def running(self) -> bool:
        return self.run is not None

    @property
    def job_running(self) -> bool:
        return self.run is not None and self.run.kind == "job"

    @property
    def state(self) -> str:
        """idle | running | waiting (daily quota) | closing | closed."""
        if self.closed:
            return "closed"
        if self.closing:
            return "closing"
        if self.run is not None:
            return "running"
        return "waiting" if self.sched.wait is not None else "idle"

    def runs_series(self, path: str) -> bool:
        return self.run is not None and self.run.series == path

    def job_series(self) -> str:
        return self.run.series if self.job_running else ""

    def quota_wait(self):
        """(wake_at, series) of the job that waits for the daily quota in this window, else of a saved job that
        waits; None when none does. A wait whose time has passed is not a wait any more."""
        w = self.sched.wait
        if w is not None:
            return w.wake_at, w.series
        e = self.waiting_elsewhere
        if e is not None and e[0] > self.clock():
            return e
        return None

    def percent(self) -> int | None:
        r = self.run
        if r is None or r.kind != "job":
            return None
        done, total, _full, _n = r.events.totals()
        return int(done * 100 / total) if total else 0

    def counts(self):
        """(blocks done, blocks total, chapters done, chapters total) of the running job."""
        r = self.run
        if r is None:
            return 0, 0, 0, 0
        return r.events.totals()

    def time_left(self) -> str:
        """`about 2 h` / `about 40 min` / `under a minute` for the running job; "" while unknown."""
        r = self.run
        if r is None or r.kind != "job":
            return ""
        done, total, _full, _n = r.events.totals()
        return eta.run_left(done - r.done_at_start, self.clock() - r.started, total - done)

    def queued(self, series: str) -> Item | None:
        return self.queue.get(series)

    def queue_items(self) -> list:
        return list(self.queue.items)

    # ------------------------------------------------------------- the header (1.2)
    def indicator(self) -> str:
        """What follows `Translate` in the path: the running job as `▶ series · 62 %` and the queue count; else the
        reason a job or the queue waits; else empty."""
        r = self.run
        n = len(self.queue)
        if r is not None and r.kind == "job":
            text = "▶ %s · %d %%" % (_short(r.name, 22), self.percent() or 0)
            return text + (" · %d" % n if n else "")
        if r is not None:
            return "Sample"
        st = self.sched.status()
        if st:
            return st
        v = self._tracked_view()
        if v is not None and v.unfinished:
            now = self.clock()
            if v.state == "waiting_quota" and v.wake_at is not None and now < v.wake_at:
                return "Wait " + js.clock_text(v.wake_at)
            if v.state == "waiting_terms" and v.terms_pending:
                return "Terms %d" % v.terms_pending
            return "Failed" if v.state == "failed" else "Stopped"
        return ""

    def indicator_series(self) -> str:
        """The series the header state is about (a click on it opens that series)."""
        r = self.run
        if r is not None:
            return r.series
        if self.sched.wait is not None:
            return self.sched.wait.series
        if self.last_series:
            return self.last_series
        if self.sched.status() and self.queue:
            return self.queue.head().series
        return self.view()[0] or ""

    def _tracked_view(self):
        path = self.last_series or self.view()[0]
        if not path:
            return None
        try:
            return frun.job_view(path)
        except Exception:
            return None

    # ------------------------------------------------------------- the one start path (13.2)
    def start(self, series_path: str, book: str, chapters, resume: bool = False, source: str = "user",
              retry=()) -> str:
        """Start or continue the job of a series. Returns "" when it started, else the reason in plain words.
        Refuses while a job (or a sample) of this window runs or while the window closes. `retry`: check findings
        to translate again; the core marks them here, at the real start, not before. The caller has done the
        write order of rule (b) (`ordering.before_book_work`) before calling."""
        if self.closing:
            return "The window is closing."
        if self.run is not None:
            return "A translation is running. Only one runs at a time."
        info = fbooks.read_series(series_path)
        if info is None or info.broken:
            return "The series is gone."
        if not resume and book not in info.books:
            return "The volume %s is gone." % book
        keys = list(self.keys())
        if not keys:
            return "No API key. Add one in the settings."
        if fbooks.series_language(info) is None:
            return "%s has no language chosen." % info.name
        view = frun.job_view(series_path)
        if view.foreign:
            return "Another program is working on %s." % info.name
        if resume:
            if not view.unfinished:
                return "%s has no unfinished job to continue." % info.name
            book, chapters = view.book, list(view.chapters)
            if book not in info.books:
                return "The volume %s is gone." % book
            if view.state == "failed" and (view.dead or "no usable key" in view.error):
                frun.revive_dead_pairs(series_path, keys, self.models())
        chapters = list(chapters)
        if not chapters:
            return "There are no chapters to translate."
        cfg = self.run_config()
        run = Run("job", series_path, info.name, book, chapters, resume, self.clock)
        self._prepare_chap(run)
        self.run = run
        self.last_series = series_path
        self.last_start_error = ""
        self.sched.user_started()
        self.flush()                                    # the window state is on disk before a job starts
        self.sink.runs_changed(starting=True)
        self.submit(
            lambda ctx, h=run.handle, ev=run.events: frun.run_task(ctx, h, series_path, book, chapters, cfg, resume,
                                                                    tuple(retry), events=ev),
            on_item=lambda item, r=run: self._on_item(r, item),
            on_result=lambda res, r=run: self._done(r, res),
            on_error=lambda exc, r=run: self._failed(r, exc), lane="run")
        self._changed()
        return ""

    def start_sample(self, series_path: str, book: str, chapter: int, blocks: int) -> str:
        if self.closing:
            return "The window is closing."
        if self.run is not None:
            return "A translation is running."
        info = fbooks.read_series(series_path)
        keys = list(self.keys())
        if info is None or info.broken:
            return "The series is gone."
        if not keys:
            return "No API key. Add one in the settings."
        if fbooks.series_language(info) is None:
            return "%s has no language chosen." % info.name
        if frun.job_view(series_path).foreign:
            return "Another program is working on %s." % info.name
        if self.quota_wait() is not None:
            return "A job waits for the daily quota."
        cfg = self.run_config()
        run = Run("sample", series_path, info.name, book, [chapter], False, self.clock)
        self.run = run
        self.sink.runs_changed(starting=True)
        self.submit(
            lambda ctx, h=run.handle: frun.sample_task(ctx, h, series_path, book, chapter, blocks, cfg),
            on_item=lambda item, r=run: self._on_item(r, item),
            on_result=lambda res, r=run: self._done(r, res),
            on_error=lambda exc, r=run: self._failed(r, exc), lane="run")
        self._changed()
        return ""

    def _prepare_chap(self, run: Run) -> None:
        """Progress of the chapters the job covers, from the chapter list when that volume is open."""
        series, book, infos = self.view()
        if series != run.series or book != run.book:
            return
        chap = {}
        for i in run.chapters:
            if i < len(infos) and infos[i].is_toc is not True and infos[i].blocks is not None:
                chap[i] = (min(infos[i].done, infos[i].blocks), infos[i].blocks, infos[i].failed)
        run.events = RunEvents(chap)
        run.done_at_start = run.events.totals()[0]

    # ------------------------------------------------------------- events
    def _on_item(self, run: Run, item) -> None:
        if run is not self.run:
            return
        kind = item[0]
        if kind == "busy":
            run.busy_text = str(item[1])
            run.last_error = run.busy_text
            return
        if kind == "wake":                  # the relay folded events into run.events
            self._throttle.mark(urgent=bool(item[1]) if len(item) > 1 else False)
            return
        if kind != "event":
            return
        ev = item[1]
        if run.kind == "sample":
            if ev.kind == "error":
                run.last_error = str((ev.data or {}).get("message", ""))
            return
        wake = run.events.feed(ev)
        if wake:
            self._throttle.mark(urgent=wake == URGENT)

    def _flush_progress(self) -> None:
        r = self.run
        if r is None:
            return
        r.snapshot = r.events.take()
        self.sink.run_progress(r)

    def _failed(self, run: Run, exc) -> None:
        if run is not self.run:
            return
        run.last_error = "%s: %s" % (exc.__class__.__name__, exc)
        self._done(run, None, crashed=True)

    def _done(self, run: Run, result, crashed: bool = False) -> None:
        if run is not self.run:
            return
        self.run = None
        self._throttle.cancel()
        run.snapshot = run.events.take()
        series = run.series
        if run.kind == "sample":
            self._changed()
            self.sink.runs_changed(ended=run)
            self._closing_done()
            return
        view = frun.job_view(series) if fbooks.read_series(series) is not None else js.JobView()
        busy = bool(result and result.get("busy")) or bool(run.busy_text)
        kind = ENDED.get(view.state, jq.STOPPED)
        action = None
        if busy:
            self.sched.halt("Stopped", run.busy_text)
        elif run.user_stop:
            self.sched.halt("Stopped")
        elif crashed:
            self.sched.halt("Failed", run.last_error)
        elif kind == jq.TERMS:
            action = self.sched.job_ended(kind, series, label="Terms %d" % view.terms_pending)
        elif kind == jq.FAILED:
            action = self.sched.job_ended(kind, series, label="Failed", why=view.error)
        elif kind == jq.QUOTA:
            action = self.sched.job_ended(kind, series, wake_at=view.wake_at)
        else:
            action = self.sched.job_ended(kind, series)
        self._changed()             # after the scheduler knows whether a quota wait begins: no flapping
        self.sink.runs_changed(ended=run)
        if crashed and not self.closing:
            msg = getattr(self.sink, "message", None)
            if msg is not None:
                msg("The run stopped on an error: %s" % run.last_error)
        if self._closing_done():
            return
        if action is not None:
            self._dispatch(action)

    # ------------------------------------------------------------- stopping
    def stop(self) -> None:
        """Stop the running job or sample (the requests in flight finish). Stops the queue too."""
        r = self.run
        if r is None or r.stopping:
            return
        r.stopping = True
        r.user_stop = True
        r.handle.stop()
        self.sink.runs_changed()

    def stop_wait(self) -> None:
        """Stop during the wait for the daily quota: the job becomes stopped, nothing continues by itself."""
        w = self.sched.wait
        if w is None:
            return
        frun.set_job_state(w.series, "stopped")
        self.sched.cancel_wait()
        self._changed()
        self.sink.runs_changed()

    def discard(self, series: str) -> bool:
        """Discard the unfinished job of a series (translated chapters stay)."""
        if self.runs_series(series):
            return False
        ok = frun.set_job_state(series, "finished")
        if self.sched.wait is not None and self.sched.wait.series == series:
            self.sched.wait = None
        if self.last_series == series:
            self.last_series = ""
        self._changed()
        self.sink.runs_changed()
        return ok

    # ------------------------------------------------------------- the queue (7.5)
    def enqueue(self, item: Item) -> Item | None:
        old = self.queue.add(item)
        self._save_queue()
        self.sink.runs_changed()
        return old

    def dequeue(self, series: str) -> None:
        self.queue.remove(series)
        self._save_queue()
        self.sink.runs_changed()

    def move(self, series: str, delta: int) -> None:
        if self.queue.move(series, delta):
            self._save_queue()
            self.sink.runs_changed()

    def clear_queue(self) -> None:
        self.queue.clear()
        self.sched.wait = None
        self._save_queue()
        self._changed()
        self.sink.runs_changed()

    def series_gone(self, series: str, book: str | None = None) -> None:
        """A series was deleted or a volume removed: it leaves the queue (and a quota wait on it ends)."""
        before = len(self.queue)
        self.sched.series_gone(series, book)
        if book is None and self.last_series == series:
            self.last_series = ""
        if len(self.queue) != before:
            self._save_queue()
        self._changed()
        self.sink.runs_changed()

    def continue_queue(self) -> None:
        act = self.sched.continue_queue(self.run is not None)
        self.sink.runs_changed()
        if act is not None:
            self._dispatch(act)

    def _save_queue(self) -> None:
        self.winstate.set("queue", self.queue.to_list())
        self.flush()                                    # the queue is written at once, never debounced

    def _dispatch(self, action) -> None:
        if self.closing:
            return
        if action.kind == "next":
            self._start_head()
        elif action.kind == "resume":
            why = self.start(action.series, "", [], resume=True, source="wake")
            if why:
                self.sched.halt("Stopped", why)
                self.last_start_error = why
                self._changed()
                self.sink.runs_changed()

    def _start_head(self) -> None:
        item = self.queue.head()
        if item is None:
            return
        why = self._item_problem(item)
        if not why:
            why = self.start(item.series, item.book, item.indices(), resume=item.resume, source="queue",
                             retry=item.retry)
        if why:
            self.sched.halt("Stopped", why)
            self.last_start_error = why
            self.sink.runs_changed()
            return
        self.queue.remove(item.series)
        self._save_queue()
        self.sink.runs_changed()

    def _item_problem(self, item: Item) -> str:
        """Why a queued item cannot start now ("" = it can): a conflicting unfinished job it was not allowed to
        replace, a series or volume that is gone."""
        info = fbooks.read_series(item.series)
        if info is None or info.broken:
            return "A queued series is gone. Remove it from the queue."
        if item.book not in info.books:
            return "%s: the volume %s is gone. Remove it from the queue." % (info.name, item.book)
        view = frun.job_view(item.series)
        if item.resume:
            if not view.unfinished:
                return "%s has no unfinished job to continue." % info.name
            return ""
        if view.unfinished and not item.replace and set(view.chapters) != set(item.indices()):
            return "%s has an unfinished job on other chapters." % info.name
        return ""

    # ------------------------------------------------------------- time: one timer, no tick
    def note_waiting(self, views) -> None:
        """Saved jobs that wait for the daily quota, from a library read ([(series path, JobView)]): the latest
        wake-up is kept so a new start is offered as a queue item. Called after a library scan, never polled."""
        best = None
        now = self.clock()
        for path, v in views:
            if v is not None and v.state == "waiting_quota" and v.wake_at is not None and v.wake_at > now:
                if best is None or v.wake_at > best[0]:
                    best = (v.wake_at, path)
        if best != self.waiting_elsewhere:
            self.waiting_elsewhere = best
            self.sink.runs_changed()

    def activated(self) -> None:
        """The window became active (or the PC woke up): a wake-up that is due now happens now."""
        self._check_wake()

    def _changed(self) -> None:
        self._sync_awake()
        self._arm()

    def _arm(self) -> None:
        """Keep ONE single-shot timer armed to the quota wake-up of this window (or none)."""
        w = self.sched.wait
        want = w.wake_at if (w is not None and self.run is None and not self.closing) else None
        if want == self._wake_armed and (want is None or self._wake_timer is not None):
            return
        if self._wake_timer is not None:
            self._wake_timer.cancel()
            self._wake_timer = None
        self._wake_armed = want
        if want is not None:
            delay = min(max(0.0, want - self.clock()), WAKE_CAP_S)
            self._wake_timer = self.timer(int(math.ceil(delay * 1000)), self._wake_fired)

    def _wake_fired(self) -> None:
        self._wake_timer = None
        self._wake_armed = None
        self._check_wake()

    def _check_wake(self) -> None:
        if self.closing:
            return
        act = self.sched.tick(self.run is not None)
        if act is not None:
            self._dispatch(act)
        self._changed()

    def _sync_awake(self) -> None:
        """Keep the computer awake while a job runs and while a job or the queue waits for the quota here."""
        want = bool(self.setting("keep_awake")) and not self.closed and (
            self.run is not None or self.sched.wait is not None)
        if want != self._awake:
            self._awake = want
            self._keep_awake(want)

    # ------------------------------------------------------------- closing: a state, not a loop
    def shutdown(self) -> bool:
        """The window is closing: stop a run; `sink.closed()` follows when it has finished (at most 60 s).
        Returns True when it is closed already (nothing ran)."""
        if self.closing:
            return self.closed
        self.closing = True
        self._arm()
        self._throttle.cancel()
        r = self.run
        if r is None:
            self._finish_close()
            return True
        r.stopping = True
        r.user_stop = True
        r.handle.stop()
        self.sink.runs_changed()
        self._close_timer = self.timer(CLOSE_CAP_MS, self._finish_close)
        return False

    def _closing_done(self) -> bool:
        if self.closing and self.run is None and not self.closed:
            self._finish_close()
            return True
        return self.closing

    def _finish_close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._close_timer is not None:
            self._close_timer.cancel()
            self._close_timer = None
        if self._wake_timer is not None:
            self._wake_timer.cancel()
            self._wake_timer = None
        if self._awake:
            self._awake = False
            self._keep_awake(False)
        self.flush()
        done = getattr(self.sink, "closed", None)
        if done is not None:
            done()


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"
