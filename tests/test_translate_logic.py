"""Pure logic of the Translate screen (ctl/translateplan.py) and the RunInfo of the real run control."""

import time
import unittest
from types import SimpleNamespace

from novelgui import startlabel as sl
from novelgui.ctl import translateplan as tp
from novelgui.ctl.runinfo import run_info
from novelgui.ctl.shellrules import header_states

NOW = time.mktime((2026, 11, 19, 12, 0, 0, 0, 0, -1))


def start(**kw):
    return sl.choose(sl.StartFacts(reach="2703-2750", **kw))


def texts(f):
    return [(s.id, s.text, s.tone, s.enabled) for s in tp.bar_segments(f)]


class BarTest(unittest.TestCase):
    def test_ready(self):
        self.assertEqual(texts(tp.BarFacts(start())), [("translate", "Translate · 2703-2750", "main", True)])

    def test_first_blocked_is_red_review(self):
        f = tp.BarFacts(start(first_blocked=True, review_n=12))
        self.assertEqual(texts(f), [("review", "Review 12 terms", "red", True)])

    def test_no_keys(self):
        self.assertEqual(texts(tp.BarFacts(start(keys=False), keys=False)), [("add_keys", "Add keys", "red", True)])

    def test_running_stop_and_queue_for_other_selection(self):
        s = start(something_runs=True, own_running=True)
        f = tp.BarFacts(s, job_state="running", reach="2800-2830")
        self.assertEqual([x[0] for x in texts(f)], ["stop", "queue"])

    def test_stopped_continue_and_replace(self):
        s = start(own_unfinished=True)
        f = tp.BarFacts(s, job_state="stopped", job_reach="2730-2750")
        self.assertEqual(texts(f), [("continue", "Continue 2730-2750", "main", True), ("more", "•••", "dim", True),
                                    ("replace", "Replace job · 2703-2750", "normal", True)])

    def test_failed_has_settings_first(self):
        f = tp.BarFacts(start(own_unfinished=True), job_state="failed", job_reach="2730-2750")
        self.assertEqual(tp.bar_segments(f)[0].id, "settings")
        self.assertEqual(tp.bar_segments(f)[0].tone, "red")

    def test_quota_wait_dont_resume_only(self):
        f = tp.BarFacts(start(quota_waiting=True), job_state="waiting_quota")
        self.assertEqual(texts(f), [("dont_resume", "Don't resume", "main", True)])

    def test_terms_wait(self):
        f = tp.BarFacts(start(), job_state="waiting_terms", job_terms=12)
        self.assertEqual(texts(f), [("review", "Review 12 terms", "red", True), ("more", "•••", "dim", True)])

    def test_another_runs_add_to_queue(self):
        f = tp.BarFacts(start(something_runs=True))
        self.assertEqual(texts(f)[0][:2], ("queue", "Add to queue · 2703-2750"))

    def test_translated_reads_retranslate(self):
        f = tp.BarFacts(start(translated=True), translated=True, reach="2703-2750")
        self.assertEqual(texts(f), [("translate", "Retranslate · 2703-2750", "dim", False)])

    def test_busy_elsewhere_no_bar(self):
        self.assertEqual(tp.bar_segments(tp.BarFacts(start(foreign=True), foreign=True)), [])

    def test_problems_and_queue_tabs(self):
        self.assertEqual(texts(tp.BarFacts(start(), tab="problems", check_reach="2703-2750"))[0][1],
                         "Check 2703-2750")
        f = tp.BarFacts(start(), tab="queue", queue_restart=True)
        self.assertEqual(texts(f)[0][1], "Continue queue")


class WordTest(unittest.TestCase):
    def test_words(self):
        w = lambda **k: tp.row_word(tp.RowFacts(**k), NOW)
        self.assertEqual(w(job_state="stopped", current=True).text, "Stopped")
        self.assertEqual(w(job_state="failed", current=True, error_kind="key"), tp.Word("Key invalid", "red", "key"))
        self.assertEqual(w(job_state="failed", current=True, error_kind="model").text, "Model not found")
        self.assertEqual(w(job_state="waiting_quota", current=True, wake_at=NOW + 3600).text[:8], "Resumes ")
        self.assertEqual(w(job_state="running", current=True, running=True, retry_until=NOW + 12).text, "Retrying 0:12")
        self.assertEqual(w(job_state="running", current=True, running=True, paused_until=NOW + 42).text, "Paused 0:42")
        self.assertEqual(w(terms=12, terms_holds=True), tp.Word("12 terms", "red", "terms", "terms"))
        self.assertEqual(w(terms=3).tone, "dim")
        self.assertEqual(w(foreign=True, current=True).text, "Busy elsewhere on this PC")
        self.assertEqual(w(problems=1).text, "1 problem")
        self.assertEqual(w(problems=4).click, "problems")
        self.assertEqual(w(), tp.Word())
        self.assertEqual(w(job_state="waiting_quota", current=True, wake_at=NOW - 5), tp.Word())


class TimeTest(unittest.TestCase):
    def test_pill(self):
        p = tp.time_pill(600, 5, 5.0, 1491, 8, "2703-2750", False, None, NOW + 3600)
        self.assertTrue(p.visible)
        self.assertEqual([o.per for o in p.options], [1, 5, 10])
        self.assertTrue(p.options[2].untested)
        self.assertEqual(p.left_text, "1 491 / 4 000")
        self.assertEqual(p.heading, "Chapters 2703-2750")
        self.assertTrue(p.renew.startswith("Renew at "))
        self.assertTrue(p.text.startswith("≈ "))

    def test_hidden_and_running(self):
        self.assertFalse(tp.time_pill(0, 5, 5.0, 10, 8, "", False, None, NOW).visible)
        p = tp.time_pill(0, 5, 5.0, 10, 8, "1-2", True, 3780, NOW)
        self.assertEqual(p.text, "≈ 1 h 03 min left")
        self.assertTrue(p.locked)

    def test_tomorrow(self):
        p = tp.time_pill(100000, 1, 5.0, 100, 8, "1-2", False, None, NOW)
        self.assertIn("finishes tomorrow", p.text)

    def test_renew_time_comes_from_the_core_rule(self):
        from novelgui.facade import quota
        t = quota.renew_at(NOW)
        self.assertTrue(NOW < t <= NOW + 86400)
        self.assertTrue(tp.renew_text(t).startswith("Renew at "))
        self.assertEqual(tp.renew_text(None), "")


class QueueTest(unittest.TestCase):
    def test_rows(self):
        a = tp.QueueFacts("a", "Gamma", "Book 2", "12-40", "Ukrainian")
        b = tp.QueueFacts("b", "Delta", "Book 1", "1-9", "Polish", 60)
        c = tp.QueueFacts("c", "Eps", "Book 1", "1-9", "Polish", 60)
        rows = tp.queue_rows(a, 71, 600, [b, c], False, None, NOW, 1.0)
        self.assertEqual([r.start[:1] for r in rows], ["n", "≈", "≈"])
        self.assertTrue(rows[0].running and rows[0].percent == 71)
        self.assertEqual((rows[1].up, rows[1].down, rows[2].up, rows[2].down), (False, True, True, False))
        self.assertEqual(rows[0].detail, "Book 2 · 12-40 · Ukrainian")
        rr = tp.queue_rows(None, 0, None, [b, c], True, None, NOW)
        self.assertEqual([r.start for r in rr], ["next", "then"])
        q = tp.queue_rows(a, 71, 0, [b], False, NOW + 3600, NOW)
        self.assertTrue(q[0].dont_resume)

    def test_tip_and_tabs(self):
        s = tp.add_to_queue_tip("Gamma", 71, ["Gamma", "Delta"], NOW)
        self.assertTrue(s.startswith("Another series is translating now: Gamma, 71 % done."))
        self.assertIn("after Gamma and Delta", s)
        self.assertEqual(tp.tabs(0, False, 0, False, False), [])
        t = tp.tabs(2, True, 1, True, True, 7)
        self.assertEqual([x[0] for x in t], ["chapters", "problems", "queue", "sample"])
        self.assertEqual(t[1][2], "red")
        self.assertEqual(t[3][1], "Sample · 7 terms unreviewed")
        self.assertTrue(tp.queue_tab_visible(True, False, 0, False))
        self.assertEqual(tp.header_click(True, False), "queue")
        self.assertEqual(tp.header_click(True, True), "scroll")

    def test_sample(self):
        self.assertEqual(tp.sample_label(7), "Sample · 7 unreviewed")
        self.assertEqual(tp.sample_enabled(True, False, True, True), (False, "running"))
        self.assertEqual(tp.sample_enabled(False, False, False, True), (False, "keys"))
        self.assertEqual(tp.sample_enabled(False, False, True, True), (True, ""))


class FakeRC:
    def __init__(self, run=None, wait=None, ind="", queue=0, halted="", why=""):
        self.run, self._wait, self._ind, self.queue = run, wait, ind, [0] * queue
        self.last_start_error = "Key invalid"
        self.sched = SimpleNamespace(halted=halted, why=why)

    def queue_items(self):
        return [SimpleNamespace(series="C:/lib/Delta")] * len(self.queue)

    def view(self):
        return "", "", []

    def clock(self):
        return NOW

    def quota_wait(self):
        return self._wait

    def indicator(self, view=None):
        return self._ind

    def indicator_series(self):
        return "C:/lib/Gamma"

    def counts(self):
        return 40, 100, 3, 10


class RunInfoTest(unittest.TestCase):
    def test_running(self):
        r = SimpleNamespace(kind="job", name="Gamma", book="Book 2", done_at_start=0, started=NOW - 100, stopping=False,
                            series="C:/lib/Gamma", chap={4: (2, 5, 0), 5: (0, 5, 0)})
        info = run_info(FakeRC(run=r, queue=2))
        self.assertTrue(info.running and info.busy)
        self.assertEqual((info.series, info.verb, info.done, info.total, info.queued), ("Gamma", "Stop", 3, 10, 2))
        self.assertIsNotNone(info.left_s)
        self.assertEqual(info.chapter, 5)           # position 4, shown 1-based
        self.assertEqual(header_states(info)["translate"], "wave")

    def test_quota_wait(self):
        info = run_info(FakeRC(wait=(NOW + 3600, "C:/lib/Gamma")))
        self.assertTrue(info.waiting)
        self.assertEqual((info.series, info.verb), ("Gamma", "Don't resume"))
        self.assertTrue(info.wake)

    def test_failed_pulses_red_and_terms(self):
        info = run_info(FakeRC(ind="Failed"))
        self.assertEqual(header_states(info)["translate"], "attention")
        self.assertEqual(info.reason, "Key invalid")
        self.assertEqual(header_states(run_info(FakeRC(ind="Terms 12")))["terms"], "red")
        self.assertEqual(header_states(run_info(FakeRC(), terms_blocked=True))["terms"], "red")

    def test_needs_user_follows_the_real_job_state(self):
        from novelgui.jobstate import JobView
        key = JobView("failed", "Book 1", (0, 1), error="no usable key/model pair is left", dead=("invalid key",))
        info = run_info(FakeRC(ind="Failed"), view=key)
        self.assertTrue(info.needs_user and info.failed)
        self.assertEqual(info.reason, "Key invalid")
        gone = JobView("failed", "Book 1", (0, 1), error="the service keeps failing")
        info = run_info(FakeRC(ind="Failed"), view=gone)
        self.assertFalse(info.failed or info.needs_user)          # a failure the user cannot fix: stopped, no red
        model = JobView("failed", "Book 1", (0, 1), error="x", dead=("model not found",))
        self.assertEqual(run_info(FakeRC(ind="Failed"), view=model).reason, "Model not found")

    def test_a_queue_stopped_at_an_item_needs_the_user(self):
        """9.12: the header pulses red and the tray line names the series; a restored queue (`Restart`) does not pulse."""
        from novelgui import jobqueue as jq
        info = run_info(FakeRC(queue=2, halted="Stopped", why="Delta: the volume Book 9 is gone."))
        self.assertTrue(info.needs_user)
        self.assertFalse(info.failed)
        self.assertEqual((info.series, info.reason), ("Delta", "Delta: the volume Book 9 is gone."))
        self.assertEqual(header_states(info)["translate"], "attention")
        self.assertFalse(run_info(FakeRC(queue=2, halted=jq.Scheduler.RESTART)).needs_user)
        self.assertFalse(run_info(FakeRC(queue=0, halted="Stopped")).needs_user, "nothing queued: nothing is stuck")
        self.assertFalse(run_info(FakeRC(queue=2, halted="Stopped", wait=(NOW + 60, "C:/lib/Gamma"))).needs_user)

    def test_error_kinds(self):
        self.assertEqual(tp.error_kind("", ("invalid key",)), "key")
        self.assertEqual(tp.error_kind("DiskError: no space left"), "disk")
        self.assertEqual(tp.error_kind("ValueError: x"), "crash")
        self.assertEqual(tp.error_kind(""), "")
        self.assertTrue(tp.needs_user("failed", "model"))
        self.assertFalse(tp.needs_user("stopped", "model"))

    def test_idle(self):
        info = run_info(FakeRC())
        self.assertFalse(info.busy)
        self.assertEqual(header_states(info), {"terms": "", "translate": ""})


if __name__ == "__main__":
    unittest.main()
