"""RunControl of the new window (novelgui.ctl) without a window: the one start path, the queue carried out, the
quota wake-up on ONE single-shot timer, nothing at start.

A port of test_gui_runctl.py: the assertions are the same, the stand-ins differ (an injected submit, a clock and
a timer stub instead of the Tk app and its `after`). The series and job records are real files in a temp library.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from novelcore import Series
from novelcore import job as core_job
from novelgui import jobqueue, platform
from novelgui.ctl import runcontrol
from novelgui.facade import run as frun
from novelgui.settings import Settings
from novelgui.winstate import WinState
from tests.core_support import KEYS, MODEL
from tests.test_core_epub import make_epub


class StubWorker:
    def __init__(self):
        self.calls = []

    def submit(self, fn, on_result=None, on_error=None, on_item=None, lane="bulk", token=None):
        self.calls.append(SimpleNamespace(fn=fn, lane=lane, on_result=on_result, on_item=on_item))


class StubTimers:
    """Single-shot timers on the test's clock: `fire_due()` runs every armed timer whose time has come."""

    def __init__(self, clock):
        self.clock = clock
        self.armed = []

    def __call__(self, ms, fn):
        h = SimpleNamespace(due=self.clock() + ms / 1000.0, fn=fn, cancelled=False)
        h.cancel = lambda h=h: setattr(h, "cancelled", True)
        self.armed.append(h)
        return h

    def fire_due(self):
        while True:
            due = [h for h in self.armed if not h.cancelled and h.due <= self.clock()]
            if not due:
                return
            for h in due:
                self.armed.remove(h)
                h.fn()


class StubApp:
    def __init__(self, folder):
        self.settings = Settings(folder)
        self.ui = SimpleNamespace(winstate=WinState(self.settings), worker=StubWorker())
        self.keystore = SimpleNamespace(keys=list(KEYS))
        self.series = None
        self.book = ""
        self.infos = []
        self.changes = []

    def models(self):
        return [MODEL]

    def run_config(self):
        return frun.RunConfig(list(self.keystore.keys), [MODEL], 30, "http://127.0.0.1:9")

    def runs_changed(self, starting=False, ended=None, tick=False):
        self.changes.append((starting, ended is not None, tick))

    def run_progress(self, run):
        pass


def make_runs(app, clock, timers):
    return runcontrol.RunControl(
        winstate=app.ui.winstate, submit=app.ui.worker.submit, timer=timers, sink=app,
        keys=lambda: app.keystore.keys, models=app.models, run_config=app.run_config,
        setting=app.settings.get,
        view=lambda: (app.series.path if app.series is not None else "", app.book, app.infos), clock=clock)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lib = self.root / "lib"
        self.lib.mkdir()
        self.app = StubApp(self.root / "data")
        self.awake = []
        self.real_awake = platform.keep_awake
        platform.keep_awake = lambda on: self.awake.append(bool(on))
        self.addCleanup(lambda: setattr(platform, "keep_awake", self.real_awake))
        self.now = 1_800_000_000.0
        self.timers = StubTimers(lambda: self.now)
        self.runs = make_runs(self.app, lambda: self.now, self.timers)
        self.app.runs = self.runs

    def tick(self):
        """Time passed: the timers that are due fire (the Tk version ticked every 500 ms instead)."""
        self.timers.fire_due()

    def series(self, name, target="ru:Russian", **kw):
        s = Series.create(self.lib, name, target, **kw)
        ep = self.root / (name + ".epub")
        make_epub(ep, {"c0.xhtml": "<p>One two three four five.</p>", "c1.xhtml": "<p>Six seven eight nine.</p>"})
        stem = s.add_book(ep)
        return str(s.path), stem

    def record(self, path, book, state, chapters=(0, 1), **kw):
        from novelcore.run import to_ranges
        rec = {"version": 1, "book": book, "first": chapters[0], "last": chapters[-1], "chapters": to_ranges(chapters),
               "state": state, "models": [MODEL], "chapter_blocks": {}, "wake_at": None, "error": None,
               "terms_pending": 0, "blocked_chapter": None, "blocks_failed": 0, "chapters_total": len(chapters)}
        rec.update(kw)
        core_job.write_job(path, rec)

    def end(self, state, **kw):
        """The running job ends with this record state."""
        r = self.runs.run
        self.record(r.series, r.book, state, tuple(r.chapters), **kw)
        self.runs._done(r, {"stopped": False})

    def starts(self):
        return [c for c in self.app.ui.worker.calls if c.lane == "run"]


class StartPath(Base):
    def test_refusals_say_why(self):
        path, stem = self.series("Alpha")
        self.app.keystore.keys = []
        self.assertIn("API key", self.runs.start(path, stem, [0]))
        self.app.keystore.keys = list(KEYS)
        self.assertIn("volume", self.runs.start(path, "nope", [0]))
        self.assertIn("no chapters", self.runs.start(path, stem, []))
        self.assertIn("gone", self.runs.start(str(self.lib / "Nowhere"), stem, [0]))
        fresh, fstem = self.series("Fresh", target_chosen=False)
        self.assertIn("no language", self.runs.start(fresh, fstem, [0]))
        self.assertIn("no unfinished job", self.runs.start(path, "", [], resume=True))
        self.assertEqual(self.starts(), [])
        self.assertFalse(self.runs.running)

    def test_one_start_one_job(self):
        path, stem = self.series("Alpha")
        other, ostem = self.series("Beta")
        self.assertEqual(self.runs.start(path, stem, [0, 1]), "")
        self.assertTrue(self.runs.job_running)
        self.assertEqual(len(self.starts()), 1)
        self.assertIn("running", self.runs.start(other, ostem, [0]))
        self.assertIn("running", self.runs.start(path, "", [], resume=True))
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(self.awake, [])                    # the setting is off

    def test_keep_awake_follows_the_run_when_the_setting_is_on(self):
        self.app.settings.set("keep_awake", True)
        path, stem = self.series("Alpha")
        self.runs.start(path, stem, [0])
        self.assertEqual(self.awake, [True])
        self.end("finished")
        self.assertEqual(self.awake, [True, False])

    def test_another_process_holding_the_series_refuses_the_start(self):
        path, stem = self.series("Alpha")
        real = frun.job_view
        frun.job_view = lambda p: real(p).__class__(foreign=True)
        try:
            self.assertIn("Another program", self.runs.start(path, stem, [0]))
        finally:
            frun.job_view = real

    def test_a_sample_is_refused_while_a_job_waits_for_the_quota(self):
        path, stem = self.series("Alpha")
        self.runs.sched.wait = jobqueue.Wait(path, self.now + 100)
        self.assertIn("waits", self.runs.start_sample(path, stem, 0, 5))
        self.runs.sched.wait = None
        self.assertEqual(self.runs.start_sample(path, stem, 0, 5), "")
        self.assertEqual(self.runs.run.kind, "sample")
        self.assertIn("running", self.runs.start(path, stem, [0]))


class QueueCarriedOut(Base):
    def item(self, path, stem, chapters=(0, 1), **kw):
        return jobqueue.Item(path, stem, jobqueue.spans_of(chapters), **kw)

    def test_finishing_starts_the_next_item_and_removes_it(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.runs.start(a, astem, [0, 1])
        self.runs.enqueue(self.item(b, bstem))
        self.assertEqual(json.loads(self.app.settings.path.read_text())["win"]["queue"][0]["book"], bstem)
        self.end("finished")
        self.assertTrue(self.runs.job_running and self.runs.run.series == b)
        self.assertEqual(len(self.runs.queue), 0)
        self.assertEqual(json.loads(self.app.settings.path.read_text())["win"]["queue"], [])

    def test_finished_with_failed_blocks_still_goes_on(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.runs.start(a, astem, [0, 1])
        self.runs.enqueue(self.item(b, bstem))
        self.end("finished", blocks_failed=3)
        self.assertEqual(self.runs.run.series, b)

    def test_stop_halts_the_queue(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.runs.start(a, astem, [0, 1])
        self.runs.enqueue(self.item(b, bstem))
        self.runs.stop()
        self.assertTrue(self.runs.run.stopping)
        self.end("stopped")
        self.assertFalse(self.runs.running)
        self.assertEqual(self.runs.indicator(), "Stopped")
        self.assertEqual(len(self.runs.queue), 1)
        self.runs.continue_queue()
        self.assertEqual(self.runs.run.series, b)

    def test_waiting_for_terms_halts_the_queue_and_names_the_count(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.runs.start(a, astem, [0, 1])
        self.runs.enqueue(self.item(b, bstem))
        self.end("waiting_terms", terms_pending=12, blocked_chapter=1)
        self.assertFalse(self.runs.running)
        self.assertEqual(self.runs.indicator(), "Terms 12")

    def test_the_daily_quota_waits_and_the_window_continues_at_wake_at(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.app.settings.set("keep_awake", True)
        self.runs.start(a, astem, [0, 1])
        self.runs.enqueue(self.item(b, bstem))
        wake = self.now + 600
        self.end("waiting_quota", wake_at=wake)
        self.assertFalse(self.runs.running)
        self.assertEqual(self.runs.sched.wait.series, a)
        self.assertEqual(self.runs.indicator(), "Wait " + time.strftime("%H:%M", time.localtime(wake)))
        self.assertEqual(self.awake[-1], True)                  # still awake while it waits
        self.assertIsNotNone(self.runs.quota_wait())
        n = len(self.starts())
        self.now = wake - 1
        self.tick()
        self.assertEqual(len(self.starts()), n)
        self.now = wake
        self.tick()
        self.assertEqual(len(self.starts()), n + 1)
        self.assertTrue(self.runs.job_running and self.runs.run.series == a and self.runs.run.resume)
        self.end("finished")
        self.assertEqual(self.runs.run.series, b)               # the queue goes on after the continued job

    def test_stop_during_the_wait_cancels_it(self):
        a, astem = self.series("Alpha")
        self.runs.start(a, astem, [0, 1])
        self.end("waiting_quota", wake_at=self.now + 10)
        self.runs.stop_wait()
        self.assertEqual(core_job.read_job(a)["state"], "stopped")
        self.assertIsNone(self.runs.sched.wait)
        n = len(self.starts())
        self.now += 100
        self.tick()
        self.assertEqual(len(self.starts()), n)
        self.assertFalse(self.awake and self.awake[-1])

    def test_an_item_that_cannot_start_stops_the_queue_with_the_reason(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        fresh, fstem = self.series("Fresh", target_chosen=False)
        self.runs.start(a, astem, [0, 1])
        self.runs.enqueue(self.item(fresh, fstem))
        self.runs.enqueue(self.item(b, bstem))
        self.end("finished")
        self.assertFalse(self.runs.running)
        self.assertEqual(len(self.runs.queue), 2)               # it stays at the head
        self.assertIn("no language", self.runs.sched.why)
        self.assertEqual(self.runs.indicator(), "Stopped")

    def test_a_conflicting_unfinished_job_is_not_replaced_without_the_confirmation(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.record(b, bstem, "stopped", (0,))
        self.runs.start(a, astem, [0, 1])
        self.runs.enqueue(self.item(b, bstem, (1,)))
        self.end("finished")
        self.assertFalse(self.runs.running)
        self.assertIn("unfinished job", self.runs.sched.why)
        # the same item that was confirmed to replace it does start
        self.runs.queue.items[0] = self.item(b, bstem, (1,), replace=True)
        self.runs.continue_queue()
        self.assertEqual(self.runs.run.series, b)

    def test_a_deleted_series_or_volume_leaves_the_queue(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.runs.enqueue(self.item(a, astem))
        self.runs.enqueue(self.item(b, bstem))
        self.runs.series_gone(a)
        self.assertEqual([i.series for i in self.runs.queue.items], [b])
        self.runs.series_gone(b, bstem)
        self.assertEqual(len(self.runs.queue), 0)
        self.assertEqual(json.loads(self.app.settings.path.read_text())["win"]["queue"], [])

    def test_a_refused_start_by_the_core_halts_the_queue(self):
        a, astem = self.series("Alpha")
        self.runs.start(a, astem, [0, 1])
        r = self.runs.run
        self.runs._on_item(r, ("busy", "the series is taken"))
        self.runs._done(r, {"busy": True})
        self.assertIn("taken", self.runs.sched.why)
        self.assertEqual(self.runs.sched.halted, "Stopped")

    def test_the_retry_chip_comes_only_from_the_waiting_event(self):
        a, astem = self.series("Alpha")
        self.runs.start(a, astem, [0, 1])
        r = self.runs.run
        self.assertIsNone(r.retry_until)
        ev = SimpleNamespace(kind="waiting", data={"until": self.now + 5, "reason": "cool"})
        self.runs._on_item(r, ("event", ev))
        self.assertEqual(r.retry_until, self.now + 5)
        self.runs._on_item(r, ("event", SimpleNamespace(kind="resumed", data={})))
        self.assertIsNone(r.retry_until)


class NothingAtStart(Base):
    def test_a_saved_queue_and_waiting_jobs_start_nothing(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        g, gstem = self.series("Gamma")
        self.record(a, astem, "running", (0, 1), pid=999999)
        self.record(b, bstem, "waiting_quota", (0, 1), wake_at=self.now - 3600)
        self.record(g, gstem, "waiting_quota", (0, 1), wake_at=self.now + 30)
        self.app.ui.winstate.set("queue", [jobqueue.Item(a, astem, ((0, 1),)).to_dict()])
        runs = make_runs(self.app, lambda: self.now, self.timers)
        self.assertEqual(len(runs.queue), 1)
        self.assertEqual(runs.sched.halted, jobqueue.Scheduler.RESTART)
        for dt in (0, 5, 40, 4000):
            self.now += dt
            self.tick()
        self.assertEqual(self.starts(), [])
        self.assertFalse(runs.running)
        self.assertEqual(runs.indicator(), "Queue 1")
        runs.continue_queue()                   # only the click starts the head
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(runs.run.series, a)


class NoPollingAndClosing(Base):
    """What the port adds: one wake-up timer instead of a tick, `activated()`, closing as a state."""

    def test_one_timer_armed_to_wake_at_and_re_armed_on_change(self):
        a, astem = self.series("Alpha")
        self.runs.start(a, astem, [0, 1])
        self.assertEqual([h for h in self.timers.armed if not h.cancelled and h.due > self.now + 1], [])
        self.end("waiting_quota", wake_at=self.now + 300)
        live = [h for h in self.timers.armed if not h.cancelled and h.due > self.now + 1]
        self.assertEqual([h.due for h in live], [self.now + 300])
        self.runs.stop_wait()
        self.assertTrue(all(h.cancelled for h in live))

    def test_activation_after_sleep_continues_a_due_wait(self):
        a, astem = self.series("Alpha")
        self.runs.start(a, astem, [0, 1])
        self.end("waiting_quota", wake_at=self.now + 300)
        n = len(self.starts())
        self.now += 301                 # the PC slept through the timer
        self.runs.activated()
        self.assertEqual(len(self.starts()), n + 1)

    def test_closing_is_a_state_that_ends_on_finished(self):
        a, astem = self.series("Alpha")
        closed = []
        self.app.closed = lambda: closed.append(True)
        self.runs.start(a, astem, [0, 1])
        self.assertFalse(self.runs.shutdown())
        self.assertEqual(self.runs.state, "closing")
        self.assertTrue(self.runs.run.handle.stopping)
        self.assertIn("closing", self.runs.start(a, astem, [0]))
        self.end("stopped")
        self.assertEqual((self.runs.state, closed), ("closed", [True]))

    def test_closing_gives_up_after_the_cap(self):
        a, astem = self.series("Alpha")
        closed = []
        self.app.closed = lambda: closed.append(True)
        self.runs.start(a, astem, [0, 1])
        self.runs.shutdown()
        self.now += 61
        self.tick()
        self.assertEqual(closed, [True])

    def test_progress_wakes_at_once_then_coalesces(self):
        a, astem = self.series("Alpha")
        seen = []
        self.app.run_progress = lambda run: seen.append(run.snapshot)
        self.runs.start(a, astem, [0, 1])
        r = self.runs.run
        ev = lambda i, d: SimpleNamespace(kind="progress", data={"index": i, "done": d, "total": 10, "failed": 0})
        self.runs._on_item(r, ("event", ev(0, 1)))
        self.assertEqual(len(seen), 1)                          # leading edge: at once
        for d in range(2, 8):
            self.runs._on_item(r, ("event", ev(0, d)))
        self.assertEqual(len(seen), 1)                          # inside the gate
        self.now += 0.1
        self.tick()
        self.assertEqual(len(seen), 2)                          # one trailing wake with the latest numbers
        self.assertEqual(seen[-1].chap[0], (7, 10, 0))
        self.assertEqual(self.runs.percent(), 70)


class RetryWaits(Base):
    """Check findings to translate again: the marks travel with the item and the core marks them only at the real
    start (window_spec 13.1)."""

    MARKS = ((0, 1, "abc", "k1"), (1, 0, "def", "k2"))

    def started_with(self, call):
        """Run the submitted task body with `frun.run_task` replaced; returns the `retry` argument it received."""
        seen = []
        real = frun.run_task
        frun.run_task = lambda ctx, handle, path, book, chapters, cfg, resume, retry, events=None: seen.append(retry)
        try:
            call.fn(None)
        finally:
            frun.run_task = real
        return seen[0]

    def test_item_keeps_the_marks_through_the_saved_queue(self):
        it = jobqueue.Item("p", "b", ((0, 1),), retry=self.MARKS)
        again = jobqueue.item_from(json.loads(json.dumps(it.to_dict())))
        self.assertEqual(again, it)
        self.assertEqual(again.retry, self.MARKS)
        old = jobqueue.item_from({"series": "p", "book": "b", "spans": [[0, 1]]})
        self.assertEqual(old.retry, ())
        bad = jobqueue.item_from({"series": "p", "book": "b", "spans": [[0, 1]], "retry": [[1, 2], "x", [0, 1, 2, 3]]})
        self.assertEqual(bad.retry, ())
        notlist = jobqueue.item_from({"series": "p", "book": "b", "spans": [[0, 1]], "retry": "abc"})
        self.assertEqual(notlist.retry, ())

    def test_start_hands_the_marks_to_the_run(self):
        a, astem = self.series("Alpha")
        self.assertEqual(self.runs.start(a, astem, [0, 1], retry=self.MARKS), "")
        self.assertEqual(self.started_with(self.starts()[0]), self.MARKS)

    def test_a_queued_item_starts_with_its_marks_and_the_saved_queue_keeps_them(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        marks = ((0, 0, "sha", "key"),)
        self.assertEqual(self.runs.start(a, astem, [0, 1]), "")
        self.runs.enqueue(jobqueue.Item(b, bstem, ((0, 0),), retry=marks))
        saved = json.loads(self.app.settings.path.read_text())["win"]["queue"][0]
        self.assertEqual(saved["retry"], [list(marks[0])])
        self.assertEqual(len(self.starts()), 1)
        self.end("finished")
        self.assertEqual(self.runs.run.series, b)
        self.assertEqual(len(self.starts()), 2)
        self.assertEqual(self.started_with(self.starts()[1]), marks)
        self.assertEqual(self.started_with(self.starts()[0]), ())

    def test_nothing_is_marked_while_the_item_waits(self):
        a, astem = self.series("Alpha")
        b, bstem = self.series("Beta")
        self.runs.start(a, astem, [0, 1])
        before = sorted(str(p) for p in Path(b).rglob("*") if p.is_file())
        self.runs.enqueue(jobqueue.Item(b, bstem, ((0, 0),), retry=((0, 0, "sha", "key"),)))
        self.assertEqual(sorted(str(p) for p in Path(b).rglob("*") if p.is_file()), before)
        self.assertEqual(len(self.starts()), 1)


if __name__ == "__main__":
    unittest.main()
