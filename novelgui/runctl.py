"""The translation run of the window: ONE place that starts, watches and stops jobs (window_spec 7.2, 13.2-13.4).

Every start - the Run button, Continue, Replace, the queue's next item, the wake-up after the daily quota - goes
through `RunControl.start`, which refuses while another job runs. The queue and its rules live in `jobqueue`;
this class carries them out, keeps the queue in the window state (never in the library) and the clock ticking.
A job belongs to its series, not to the series shown: switching series never stops or hides it.
"""

from __future__ import annotations

import time

from . import jobqueue as jq
from . import jobstate as js
from . import model, platform
from .jobqueue import Item, Queue, Scheduler

ENDED = {"finished": jq.FINISHED, "waiting_quota": jq.QUOTA, "waiting_terms": jq.TERMS, "stopped": jq.STOPPED,
         "failed": jq.FAILED}
TICK_MS = 500


class Run:
    """One job or sample that this window runs now."""

    def __init__(self, kind, series, name, book, chapters, resume):
        self.kind = kind                    # job | sample
        self.series = series                # series folder
        self.name = name
        self.book = book
        self.chapters = list(chapters)
        self.resume = resume
        self.handle = model.RunHandle()
        self.stopping = False
        self.user_stop = False
        self.paused_until: float | None = None
        self.retry_until: float | None = None
        self.last_error = ""
        self.chap: dict = {}                # chapter -> [done, total, failed]
        self.chap_dirty = False
        self.busy_text = ""                 # the core refused to start (another process holds the series)
        self.started = time.time()


class RunControl:
    def __init__(self, app, clock=time.time):
        self.app = app
        self.ui = app.ui
        self.clock = clock
        ws = self.ui.winstate
        self.queue = Queue.from_list(ws.get("queue", [], list))
        self.sched = Scheduler(self.queue, clock=clock)
        self.run: Run | None = None
        self.last_series = ""               # the series of the latest job of this window (header state)
        self.closing = False
        self.waiting_elsewhere: tuple | None = None     # (wake_at, series) of a saved job that waits for the quota
        self._awake = False
        self._tick_job = None
        self._tick_n = 0
        self._tick_at = 0.0
        self.last_start_error = ""
        self._schedule()

    # ------------------------------------------------------------- queries
    @property
    def running(self) -> bool:
        return self.run is not None

    @property
    def job_running(self) -> bool:
        return self.run is not None and self.run.kind == "job"

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
        done = sum(min(d, t) for d, t, _f in r.chap.values())
        total = sum(t for _d, t, _f in r.chap.values())
        return int(done * 100 / total) if total else 0

    def counts(self):
        """(blocks done, blocks total, chapters done, chapters total) of the running job."""
        r = self.run
        if r is None or not r.chap:
            return 0, 0, 0, 0
        done = sum(min(d, t) for d, t, _f in r.chap.values())
        total = sum(t for _d, t, _f in r.chap.values())
        full = sum(1 for d, t, _f in r.chap.values() if t and d >= t)
        return done, total, full, len(r.chap)

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
        return self.app.series.path if self.app.series is not None else ""

    def _tracked_view(self):
        path = self.last_series or (self.app.series.path if self.app.series is not None else "")
        if not path:
            return None
        try:
            return model.job_view(path)
        except Exception:
            return None

    # ------------------------------------------------------------- the one start path (13.2)
    def start(self, series_path: str, book: str, chapters, resume: bool = False, source: str = "user",
              retry=()) -> str:
        """Start or continue the job of a series. Returns "" when it started, else the reason in plain words.
        Refuses while a job (or a sample) of this window runs. `retry`: check findings to translate again; the
        core marks them here, at the real start, not before."""
        if self.run is not None:
            return "A translation is running. Only one runs at a time."
        info = model.read_series(series_path)
        if info is None or info.broken:
            return "The series is gone."
        if not resume and book not in info.books:
            return "The volume %s is gone." % book
        keys = list(self.app.keystore.keys)
        if not keys:
            return "No API key. Add one in the settings."
        if model.series_language(info) is None:
            return "%s has no language chosen." % info.name
        view = model.job_view(series_path)
        if view.foreign:
            return "Another program is working on %s." % info.name
        if resume:
            if not view.unfinished:
                return "%s has no unfinished job to continue." % info.name
            book, chapters = view.book, list(view.chapters)
            if book not in info.books:
                return "The volume %s is gone." % book
            if view.state == "failed" and (view.dead or "no usable key" in view.error):
                model.revive_dead_pairs(series_path, keys, self.app.models())
        chapters = list(chapters)
        if not chapters:
            return "There are no chapters to translate."
        cfg = self.app.run_config()
        run = Run("job", series_path, info.name, book, chapters, resume)
        self._prepare_chap(run)
        self.run = run
        self.last_series = series_path
        self.last_start_error = ""
        self.sched.user_started()
        self.app.runs_changed(starting=True)
        self.ui.worker.submit(
            lambda ctx, h=run.handle: model.run_task(ctx, h, series_path, book, chapters, cfg, resume, tuple(retry)),
            on_item=lambda item, r=run: self._on_item(r, item),
            on_result=lambda res, r=run: self._done(r, res),
            on_error=lambda exc, r=run: self._failed(r, exc), lane="run")
        self._sync_awake()
        return ""

    def start_sample(self, series_path: str, book: str, chapter: int, blocks: int) -> str:
        if self.run is not None:
            return "A translation is running."
        info = model.read_series(series_path)
        keys = list(self.app.keystore.keys)
        if info is None or info.broken:
            return "The series is gone."
        if not keys:
            return "No API key. Add one in the settings."
        if model.series_language(info) is None:
            return "%s has no language chosen." % info.name
        if model.job_view(series_path).foreign:
            return "Another program is working on %s." % info.name
        if self.quota_wait() is not None:
            return "A job waits for the daily quota."
        cfg = self.app.run_config()
        run = Run("sample", series_path, info.name, book, [chapter], False)
        self.run = run
        self.app.runs_changed(starting=True)
        self.ui.worker.submit(
            lambda ctx, h=run.handle: model.sample_task(ctx, h, series_path, book, chapter, blocks, cfg),
            on_item=lambda item, r=run: self._on_item(r, item),
            on_result=lambda res, r=run: self._done(r, res),
            on_error=lambda exc, r=run: self._failed(r, exc), lane="run")
        self._sync_awake()
        return ""

    def _prepare_chap(self, run: Run) -> None:
        """Progress of the chapters the job covers, from the chapter list when that volume is open."""
        app = self.app
        if app.series is None or app.series.path != run.series or app.book != run.book:
            return
        infos = app.infos
        for i in run.chapters:
            if i < len(infos) and infos[i].is_toc is not True and infos[i].blocks is not None:
                run.chap[i] = [min(infos[i].done, infos[i].blocks), infos[i].blocks, infos[i].failed]

    # ------------------------------------------------------------- events
    def _on_item(self, run: Run, item) -> None:
        if run is not self.run:
            return
        kind = item[0]
        if kind == "busy":
            run.busy_text = str(item[1])
            run.last_error = run.busy_text
            return
        if kind != "event":
            return
        ev = item[1]
        k, data = ev.kind, ev.data
        if k == "error":
            run.last_error = str(data.get("message", ""))
        if run.kind == "sample":
            return
        if k == "chapter_started":
            if not data.get("toc"):
                i = data["index"]
                prev = run.chap.get(i)
                run.chap[i] = [prev[0] if prev else 0, data["blocks"], prev[2] if prev else 0]
                run.chap_dirty = True
        elif k == "progress":
            run.chap[data["index"]] = [data["done"], data["total"], data["failed"]]
            run.chap_dirty = True
        elif k == "chapter_finished":
            if not data.get("toc"):
                run.chap[data["index"]] = [data["ok"], data["blocks"], data["failed"]]
                run.chap_dirty = True
        elif k == "paused":
            if not data.get("abort"):
                run.paused_until = data.get("until")
        elif k == "unpaused":
            run.paused_until = None
        elif k == "waiting":
            run.retry_until = data.get("until")      # the runner repeats a request after a fault (never faked)
        elif k == "resumed":
            run.retry_until = None

    def _failed(self, run: Run, exc) -> None:
        if run is not self.run:
            return
        run.last_error = "%s: %s" % (exc.__class__.__name__, exc)
        self._done(run, None, crashed=True)

    def _done(self, run: Run, result, crashed: bool = False) -> None:
        if run is not self.run:
            return
        self.run = None
        series = run.series
        if run.kind == "sample":
            self._sync_awake()
            self.app.runs_changed(ended=run)
            return
        view = model.job_view(series) if model.read_series(series) is not None else js.JobView()
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
        self._sync_awake()          # after the scheduler knows whether a quota wait begins: no flapping
        self.app.runs_changed(ended=run)
        if crashed:
            from .dialog import message
            message(self.ui, "The run stopped on an error: %s" % run.last_error)
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
        self.app.runs_changed()

    def stop_wait(self) -> None:
        """Stop during the wait for the daily quota: the job becomes stopped, nothing continues by itself."""
        w = self.sched.wait
        if w is None:
            return
        model.set_job_state(w.series, "stopped")
        self.sched.cancel_wait()
        self._sync_awake()
        self.app.runs_changed()

    def discard(self, series: str) -> bool:
        """Discard the unfinished job of a series (translated chapters stay)."""
        if self.runs_series(series):
            return False
        ok = model.set_job_state(series, "finished")
        if self.sched.wait is not None and self.sched.wait.series == series:
            self.sched.wait = None
        if self.last_series == series:
            self.last_series = ""
        self._sync_awake()
        self.app.runs_changed()
        return ok

    # ------------------------------------------------------------- the queue (7.5)
    def enqueue(self, item: Item) -> Item | None:
        old = self.queue.add(item)
        self._save_queue()
        self.app.runs_changed()
        return old

    def dequeue(self, series: str) -> None:
        self.queue.remove(series)
        self._save_queue()
        self.app.runs_changed()

    def move(self, series: str, delta: int) -> None:
        if self.queue.move(series, delta):
            self._save_queue()
            self.app.runs_changed()

    def clear_queue(self) -> None:
        self.queue.clear()
        self.sched.wait = None
        self._save_queue()
        self.app.runs_changed()

    def series_gone(self, series: str, book: str | None = None) -> None:
        """A series was deleted or a volume removed: it leaves the queue (and a quota wait on it ends)."""
        before = len(self.queue)
        self.sched.series_gone(series, book)
        if book is None and self.last_series == series:
            self.last_series = ""
        if len(self.queue) != before:
            self._save_queue()
        self._sync_awake()
        self.app.runs_changed()

    def continue_queue(self) -> None:
        act = self.sched.continue_queue(self.run is not None)
        self.app.runs_changed()
        if act is not None:
            self._dispatch(act)

    def _save_queue(self) -> None:
        self.ui.winstate.set("queue", self.queue.to_list())

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
                self.app.runs_changed()

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
            self.app.runs_changed()
            return
        self.queue.remove(item.series)
        self._save_queue()
        self.app.runs_changed()

    def _item_problem(self, item: Item) -> str:
        """Why a queued item cannot start now ("" = it can): a conflicting unfinished job it was not allowed to
        replace, a series or volume that is gone."""
        info = model.read_series(item.series)
        if info is None or info.broken:
            return "A queued series is gone. Remove it from the queue."
        if item.book not in info.books:
            return "%s: the volume %s is gone. Remove it from the queue." % (info.name, item.book)
        view = model.job_view(item.series)
        if item.resume:
            if not view.unfinished:
                return "%s has no unfinished job to continue." % info.name
            return ""
        if view.unfinished and not item.replace and set(view.chapters) != set(item.indices()):
            return "%s has an unfinished job on other chapters." % info.name
        return ""

    # ------------------------------------------------------------- time
    def _schedule(self) -> None:
        try:
            self._tick_job = self.app.root.after(TICK_MS, self.tick)
        except Exception:
            self._tick_job = None

    def tick(self) -> None:
        if self.closing:
            return
        self._schedule()
        self._tick_n += 1
        if self._tick_n % 6 == 1:
            self._scan_waiting()
        act = self.sched.tick(self.run is not None)
        if act is not None:
            self._dispatch(act)
        r = self.run
        if r is not None and r.chap_dirty:
            r.chap_dirty = False
            self.app.run_progress(r)
        if r is not None or self.sched.wait is not None or self.waiting_elsewhere is not None:
            self.app.runs_changed(tick=True)
        self._sync_awake()

    def _scan_waiting(self) -> None:
        """Which saved job waits for the daily quota (any series), so a new start is offered as a queue item."""
        best = None
        now = self.clock()
        books = self.app.steps.get("books")
        for s in (books.series_list if books is not None else []):
            if s.broken:
                continue
            try:
                v = model.job_view(s.path)
            except Exception:
                continue
            if v.state == "waiting_quota" and v.wake_at is not None and v.wake_at > now:
                if best is None or v.wake_at > best[0]:
                    best = (v.wake_at, s.path)
        changed = best != self.waiting_elsewhere
        self.waiting_elsewhere = best
        if changed:
            self.app.runs_changed()

    def _sync_awake(self) -> None:
        """Keep the computer awake while a job runs and while a job or the queue waits for the quota here."""
        want = bool(self.app.settings.get("keep_awake")) and (
            self.run is not None or self.sched.wait is not None)
        if want != self._awake:
            self._awake = want
            platform.keep_awake(want)

    # ------------------------------------------------------------- closing
    def shutdown(self) -> None:
        """The window is closing: stop a run and wait for it (up to a minute), with a visible Stopping state."""
        self.closing = True
        if self._tick_job is not None:
            try:
                self.app.root.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        r = self.run
        if r is not None:
            r.stopping = True
            r.user_stop = True
            r.handle.stop()
            self.app.runs_changed()
            end = time.time() + 60
            root = self.app.root
            while not r.handle.finished.is_set() and time.time() < end:
                try:
                    root.update()
                except Exception:
                    break
                time.sleep(0.02)
        if self._awake:
            self._awake = False
            platform.keep_awake(False)


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"
