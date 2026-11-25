"""RunControl without a window: the one start path, the queue carried out, the quota wake-up, nothing at start.

The app, its worker and the clock are stand-ins; the series and job records are real files in a temp library.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from novelcore import Series
from novelcore import job as core_job
from novelgui import jobqueue, model, platform, runctl
from novelgui.settings import Settings
from novelgui.winstate import WinState
from tests.core_support import KEYS, MODEL
from tests.test_core_epub import make_epub


class StubWorker:
    def __init__(self):
        self.calls = []

    def submit(self, fn, on_result=None, on_error=None, on_item=None, lane="bulk", token=None):
        self.calls.append(SimpleNamespace(fn=fn, lane=lane, on_result=on_result, on_item=on_item))


class StubRoot:
    def after(self, ms, fn):
        return "id"

    def after_cancel(self, i):
        pass

    def update(self):
        pass


class StubApp:
    def __init__(self, folder):
        self.settings = Settings(folder)
        self.ui = SimpleNamespace(winstate=WinState(self.settings), worker=StubWorker())
        self.root = StubRoot()
        self.keystore = SimpleNamespace(keys=list(KEYS))
        self.steps = {}
        self.series = None
        self.book = ""
        self.infos = []
        self.changes = []

    def models(self):
        return [MODEL]

    def run_config(self):
        return model.RunConfig(list(self.keystore.keys), [MODEL], 30, "http://127.0.0.1:9")

    def runs_changed(self, starting=False, ended=None, tick=False):
        self.changes.append((starting, ended is not None, tick))

    def run_progress(self, run):
        pass


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
        self.runs = runctl.RunControl(self.app, clock=lambda: self.now)
        self.app.runs = self.runs

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
        real = model.job_view
        model.job_view = lambda p: real(p).__class__(foreign=True)
        try:
            self.assertIn("Another program", self.runs.start(path, stem, [0]))
        finally:
            model.job_view = real

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
        self.runs.tick()
        self.assertEqual(len(self.starts()), n)
        self.now = wake
        self.runs.tick()
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
        self.runs.tick()
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
        runs = runctl.RunControl(self.app, clock=lambda: self.now)
        self.assertEqual(len(runs.queue), 1)
        self.assertEqual(runs.sched.halted, jobqueue.Scheduler.RESTART)
        for dt in (0, 5, 40, 4000):
            self.now += dt
            runs.tick()
        self.assertEqual(self.starts(), [])
        self.assertFalse(runs.running)
        self.assertEqual(runs.indicator(), "Queue 1")
        runs.continue_queue()                   # only the click starts the head
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(runs.run.series, a)


if __name__ == "__main__":
    unittest.main()
