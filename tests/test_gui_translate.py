"""Pure logic of the Translate step of stage 3 step 5: the start button, zone 1, the queue, the app lock."""

import json
import tempfile
import unittest
from pathlib import Path

from novelgui import applock, jobqueue, startlabel, zonestate
from novelgui import jobstate as js
from novelgui.jobqueue import Action, Item, Queue, Scheduler
from novelgui.startlabel import StartFacts, choose
from novelgui.zonestate import ZoneFacts, zone1

NOW = 1_800_000_000.0


class StartButton(unittest.TestCase):
    def kind(self, **kw):
        kw.setdefault("reach", "2697-2750")
        return choose(StartFacts(**kw))

    def test_plain_start(self):
        s = self.kind()
        self.assertEqual((s.kind, s.text, s.enabled), ("translate", "Translate · 2697-2750", True))
        self.assertFalse(s.queue)
        self.assertFalse(s.confirm)

    def test_something_runs_or_quota_waits_adds_to_queue(self):
        for kw in ({"something_runs": True}, {"quota_waiting": True, "quota_back": "09:01"}):
            s = self.kind(**kw)
            self.assertEqual((s.kind, s.text, s.queue), ("queue", "Add to queue · 2697-2750", True), kw)
            self.assertTrue(s.enabled)
        self.assertEqual(self.kind(quota_waiting=True, quota_back="09:01").quota_back, "09:01")
        self.assertEqual(self.kind(something_runs=True).quota_back, "")

    def test_a_stopped_job_on_other_chapters_is_replaced_at_once(self):
        s = self.kind(own_unfinished=True)
        self.assertEqual((s.kind, s.text, s.confirm), ("replace", "Replace job · 2697-2750", True))
        s = self.kind(own_unfinished=True, something_runs=True)
        self.assertEqual((s.kind, s.text, s.queue, s.confirm),
                         ("queue_replace", "Queue · replace job · 2697-2750", True, True))

    def test_a_running_job_of_this_series_on_other_chapters_is_a_queue_item(self):
        s = self.kind(own_running=True, something_runs=True)
        self.assertEqual((s.kind, s.confirm), ("queue", False))

    def test_the_selection_of_the_unfinished_job_has_no_start_button(self):
        for kw in ({"own_unfinished": True}, {"own_running": True, "something_runs": True}):
            s = self.kind(own_same=True, **kw)
            self.assertEqual((s.kind, s.text, s.has_button), ("none", "", False), kw)

    def test_terms_shorten_the_reach_or_stop_the_start(self):
        s = self.kind(reach="2697-2730", later_blocked=True, review_n=12)
        self.assertEqual((s.text, s.review, s.enabled), ("Translate · 2697-2730", 12, True))
        s = self.kind(first_blocked=True, review_n=5, reach="")
        self.assertEqual((s.kind, s.has_button, s.review), ("review", False, 5))
        self.assertEqual(self.kind(reach="1-5", review_n=3).review, 0)      # nothing blocks later chapters

    def test_translated_selection_is_disabled_with_a_reason(self):
        s = self.kind(translated=True)
        self.assertEqual((s.enabled, s.why, s.text), (False, "done", "Translate · 2697-2750"))

    def test_keys_come_first(self):
        s = self.kind(keys=False, language=False, first_blocked=True, review_n=4)
        self.assertEqual((s.kind, s.text, s.enabled), ("add_keys", "Add keys", True))

    def test_language_and_sample_and_foreign_disable(self):
        self.assertEqual(self.kind(language=False).why, "language")
        self.assertEqual(self.kind(sample_runs=True).why, "sample")
        self.assertEqual(self.kind(foreign=True).why, "foreign")
        self.assertFalse(self.kind(language=False).enabled)

    def test_no_selection_or_series(self):
        self.assertEqual((self.kind(selected=False).enabled, self.kind(selected=False).why), (False, "selection"))
        self.assertFalse(self.kind(has_series=False).enabled)

    def test_label_without_reach(self):
        self.assertEqual(startlabel.label("Translate", ""), "Translate")


def view(state="", **kw):
    return js.JobView(state=state, book="b", chapters=(1, 2, 3), **kw)


class Strip(unittest.TestCase):
    def z(self, v, **kw):
        kw.setdefault("now", NOW)
        return zone1(ZoneFacts(v, **kw))

    def test_no_job_and_finished_jobs_have_no_strip(self):
        self.assertFalse(self.z(view()).visible)
        self.assertFalse(self.z(view("finished")).visible)
        self.assertFalse(self.z(view("finished", blocks_failed=3)).visible)

    def test_running_shows_stop(self):
        z = self.z(view("running"), running_here=True)
        self.assertEqual((z.visible, z.button, z.action, z.enabled), (True, "Stop", "stop", True))
        z = self.z(view("running"), running_here=True, stopping=True)
        self.assertEqual((z.chip.text, z.enabled), ("Stopping", False))

    def test_chips_while_running(self):
        z = self.z(view("running"), running_here=True, paused_until=NOW + 30)
        self.assertEqual(z.chip.text, "Paused 0:30")
        z = self.z(view("running"), running_here=True, retry_until=NOW + 5)
        self.assertEqual(z.chip.text, "Retrying")
        z = self.z(view("running"), running_here=True, retry_until=NOW - 1)
        self.assertEqual(z.chip.text, "")

    def test_stopped_and_interrupted_continue_with_their_chapters(self):
        for st in ("stopped", "interrupted"):
            z = self.z(view(st), reach="2731-2750")
            self.assertEqual((z.button, z.action, z.enabled, z.chip.text), ("Continue 2731-2750", "continue", True,
                                                                           "Stopped"), st)

    def test_while_another_job_runs_continue_is_queued(self):
        z = self.z(view("stopped"), reach="2731-2750", another_busy=True)
        self.assertEqual((z.button, z.action, z.enabled), ("Queue continue 2731-2750", "queue_continue", True))

    def test_waiting_for_terms(self):
        z = self.z(view("waiting_terms", terms_pending=12), terms_now=12)
        self.assertEqual((z.enabled, z.why, z.second, z.second_text), (False, "terms", "review", "Review 12 terms"))
        z = self.z(view("waiting_terms", terms_pending=12), terms_now=0)
        self.assertEqual((z.enabled, z.second), (True, ""))

    def test_waiting_for_the_quota(self):
        v = view("waiting_quota", wake_at=NOW + 600)
        z = self.z(v)
        self.assertEqual((z.enabled, z.why, z.chip.text, z.second), (False, "quota", "Wait " + js.clock_text(NOW + 600),
                                                                    ""))
        z = self.z(v, auto_armed=True)
        self.assertEqual((z.second, z.second_text), ("stop_wait", "Stop"))
        z = self.z(v, now=NOW + 601, auto_armed=True)
        self.assertEqual((z.enabled, z.second), (True, ""))

    def test_failed_names_the_reason_and_offers_settings(self):
        z = self.z(view("failed", error="no usable key/model pair is left", dead=("invalid key",)))
        self.assertEqual((z.chip.text, z.second, z.enabled), ("Failed · key invalid", "settings", True))
        z = self.z(view("failed", error="no usable key/model pair is left", dead=("model not found",)))
        self.assertEqual(z.chip.text, "Failed · model not found")
        z = self.z(view("failed", error="the service keeps failing"))
        self.assertEqual((z.chip.text, z.second), ("Failed · the service keeps failing", ""))

    def test_no_keys_or_language_disable_continue(self):
        self.assertEqual(self.z(view("stopped"), keys=False).why, "keys")
        self.assertEqual(self.z(view("stopped"), language=False).why, "language")

    def test_elsewhere(self):
        z = self.z(view("running", foreign=True))
        self.assertEqual((z.visible, z.chip.text, z.enabled, z.button), (True, "Running elsewhere", False, ""))

    def test_fault_classes(self):
        self.assertEqual(zonestate.fault_of("", ("invalid key",)).kind, "key")
        self.assertEqual(zonestate.fault_of("x", ("model not found",)).kind, "model")
        self.assertEqual(zonestate.fault_of("requests keep being refused").kind, "service")
        self.assertEqual(zonestate.fault_of("").text, "stopped on an error")


class QueueRules(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.q = Queue()
        self.s = Scheduler(self.q, clock=lambda: self.now)

    def item(self, name, a=0, b=4, **kw):
        return Item("/lib/" + name, "book", jobqueue.spans_of(range(a, b + 1)), **kw)

    def test_one_item_per_series_replaces_in_place(self):
        self.q.add(self.item("A"))
        self.q.add(self.item("B"))
        old = self.q.add(self.item("A", 5, 9))
        self.assertEqual(old.spans, ((0, 4),))
        self.assertEqual([i.series for i in self.q.items], ["/lib/A", "/lib/B"])
        self.assertEqual(self.q.get("/lib/A").spans, ((5, 9),))

    def test_move_and_remove(self):
        for n in "ABC":
            self.q.add(self.item(n))
        self.assertTrue(self.q.move("/lib/C", -1))
        self.assertEqual([i.series[-1] for i in self.q.items], ["A", "C", "B"])
        self.assertFalse(self.q.move("/lib/A", -1))
        self.assertTrue(self.q.remove("/lib/C"))
        self.assertFalse(self.q.remove("/lib/C"))

    def test_storage_round_trip_and_damage(self):
        self.q.add(self.item("A", 2, 6, resume=True))
        self.q.add(self.item("B", replace=True))
        back = Queue.from_list(json.loads(json.dumps(self.q.to_list())))
        self.assertEqual(back.items, self.q.items)
        self.assertEqual(len(Queue.from_list([{"series": "x"}, 5, {"series": "a", "book": "b", "spans": [[3, 1]]},
                                              {"series": "a", "book": "b", "spans": [[1, 2]]}])), 1)
        self.assertEqual(len(Queue.from_list("nonsense")), 0)

    def test_a_new_scheduler_does_nothing(self):
        self.q.add(self.item("A"))
        self.assertEqual(self.s.halted, Scheduler.RESTART)
        self.assertIsNone(self.s.tick(False))
        self.assertEqual(self.s.status(), "Queue 1")
        self.assertIsNone(self.s.job_ended("finished"))       # halted: no automatic next item

    def test_finish_starts_the_next_item(self):
        self.q.add(self.item("B"))
        self.s.user_started()
        self.assertEqual(self.s.job_ended("finished"), Action("next"))
        self.assertIsNone(Scheduler(Queue()).job_ended("finished"))

    def test_other_stops_halt_the_queue(self):
        self.q.add(self.item("B"))
        for kind, label in (("stopped", "Stopped"), ("terms", "Terms 12"), ("failed", "Failed")):
            self.s.user_started()
            self.assertIsNone(self.s.job_ended(kind, label=label))
            self.assertEqual(self.s.status(), label)
            self.assertIsNone(self.s.job_ended("finished"))

    def test_quota_wait_resumes_the_job_at_wake_at_once(self):
        self.q.add(self.item("B"))
        self.s.user_started()
        self.assertIsNone(self.s.job_ended("quota", "/lib/A", NOW + 3600))
        self.assertEqual(self.s.status(), "Wait " + js.clock_text(NOW + 3600))
        self.assertIsNone(self.s.tick(False))
        self.now = NOW + 3599
        self.assertIsNone(self.s.tick(False))
        self.now = NOW + 3600
        self.assertIsNone(self.s.tick(True))          # something runs: nothing happens
        self.assertEqual(self.s.tick(False), Action("resume", "/lib/A"))
        self.assertIsNone(self.s.tick(False))
        # the resumed job finishes: the queue goes on
        self.assertEqual(self.s.job_ended("finished"), Action("next"))

    def test_stop_cancels_the_wait(self):
        self.q.add(self.item("B"))
        self.s.user_started()
        self.s.job_ended("quota", "/lib/A", NOW + 10)
        self.s.cancel_wait()
        self.now = NOW + 100
        self.assertIsNone(self.s.tick(False))
        self.assertEqual(self.s.status(), "Stopped")

    def test_continue_queue_after_a_restart(self):
        self.q.add(self.item("B"))
        self.assertEqual(self.s.continue_queue(False), Action("next"))
        self.assertEqual(self.s.halted, "")
        self.assertIsNone(self.s.continue_queue(True))
        self.assertIsNone(Scheduler(Queue()).continue_queue(False))

    def test_a_failed_start_halts_with_the_reason(self):
        self.q.add(self.item("B"))
        self.s.user_started()
        self.s.halt("Stopped", "B has no language")
        self.assertEqual((self.s.halted, self.s.why), ("Stopped", "B has no language"))
        self.assertIsNone(self.s.job_ended("finished"))

    def test_a_deleted_series_leaves_the_queue_and_ends_its_wait(self):
        self.q.add(self.item("A"))
        self.q.add(self.item("B"))
        self.s.user_started()
        self.s.job_ended("quota", "/lib/A", NOW + 10)
        self.s.series_gone("/lib/A")
        self.assertIsNone(self.s.wait)
        self.assertEqual([i.series for i in self.q.items], ["/lib/B"])
        self.q.add(Item("/lib/B", "vol2", ((0, 1),)))
        self.s.series_gone("/lib/B", "vol2")
        self.assertEqual(len(self.q), 0)


class OneWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live = {}

    def lock(self, pid):
        return applock.AppLock(self.tmp.name, lambda info: self.live.get(info.get("pid"), False), pid=pid)

    def test_second_start_finds_the_first(self):
        a, b = self.lock(100), self.lock(200)
        self.assertTrue(a.acquire())
        a.set_window(4242)
        self.live[100] = True
        self.assertFalse(b.acquire())
        self.assertEqual(b.holder["hwnd"], 4242)
        self.assertFalse(b.held)

    def test_a_stale_lock_is_taken_over(self):
        a, b = self.lock(100), self.lock(200)
        a.acquire()
        self.live[100] = False
        self.assertTrue(b.acquire())
        self.assertEqual(b.read()["pid"], 200)

    def test_release_removes_only_its_own_lock(self):
        a, b = self.lock(100), self.lock(200)
        a.acquire()
        a.release()
        self.assertFalse((Path(self.tmp.name) / applock.FILE_NAME).exists())
        b.acquire()
        a.held = True
        a.release()                                       # not the owner any more
        self.assertTrue((Path(self.tmp.name) / applock.FILE_NAME).exists())

    def test_a_damaged_lock_file_is_replaced(self):
        (Path(self.tmp.name) / applock.FILE_NAME).write_text("{not json", encoding="utf-8")
        self.assertTrue(self.lock(100).acquire())


if __name__ == "__main__":
    unittest.main()
