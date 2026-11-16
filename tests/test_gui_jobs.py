"""Pure logic of the Translate step, keys, prompts (no Tk)."""

import json
import tempfile
import unittest
from pathlib import Path

from novelgui import jobstate as js
from novelgui import keystore, termlogic
from novelgui.chapterlogic import ChapterInfo
from novelcore.terms import Entry

NOW = 1_800_000_000.0


class Estimate(unittest.TestCase):
    def test_requests_time_days(self):
        e = js.estimate(1000, 5, 24, 500, 1500)
        self.assertEqual(e.requests, 200)
        self.assertAlmostEqual(e.seconds, 200 * 60 / 24)
        self.assertEqual(e.days, 1)

    def test_more_than_left_today_needs_more_days(self):
        e = js.estimate(5000, 5, 60, 300, 1000)       # 1000 requests, 300 left, 1000 a day
        self.assertEqual(e.requests, 1000)
        self.assertEqual(e.days, 1 + 1)               # 700 more -> one more day
        e = js.estimate(50000, 5, 60, 0, 1000)
        self.assertEqual(e.days, 1 + 10)

    def test_per_request_divides_and_rounds_up(self):
        self.assertEqual(js.estimate(11, 10, 24, None, None).requests, 2)
        self.assertEqual(js.estimate(11, 1, 24, None, None).requests, 11)
        self.assertEqual(js.estimate(0, 5, 24, 10, 10).days, 0)
        self.assertEqual(js.estimate(10, 5, 24, None, None).days, 1)    # unknown quota: today is assumed

    def test_text_and_formats(self):
        e = js.estimate(5000, 5, 60, 300, 1000)
        t = js.quota_text(e, 300)
        self.assertIn("300 left today", t)
        self.assertIn("1 000 requests", t)
        self.assertIn("2 days", t)
        self.assertEqual(js.quota_text(None, None), "? left today")
        self.assertEqual(js.fmt_duration(45), "45 s")
        self.assertEqual(js.fmt_duration(600), "10 min")
        self.assertEqual(js.fmt_duration(3 * 3600 + 1200), "3 h 20 min")

    def test_remaining_blocks_from_the_chapter_list(self):
        infos = [ChapterInfo(0, blocks=10, done=4), ChapterInfo(1, blocks=6, done=6), ChapterInfo(2)]
        self.assertEqual(js.remaining_blocks(infos, [0, 1]), (6, True))
        self.assertEqual(js.remaining_blocks(infos, [0, 2]), (6, False))


def view(state="", **kw):
    return js.JobView(state=state, book="b", chapters=(1, 2, 3), **kw)


class Buttons(unittest.TestCase):
    def action(self, v, running=False, stopping=False, sel=True, same=True, terms_now=None, now=NOW):
        return js.main_action(v, running, stopping, sel, same, now, terms_now)

    def test_no_job(self):
        self.assertEqual(self.action(view(), sel=True), js.Action("Run", True))
        self.assertEqual(self.action(view(), sel=False), js.Action("Run", False))
        self.assertEqual(self.action(view("finished")), js.Action("Run", True))

    def test_running_and_stopping(self):
        self.assertEqual(self.action(view("running"), running=True), js.Action("Stop", True))
        self.assertEqual(self.action(view("running"), running=True, stopping=True), js.Action("Stop", False))

    def test_unfinished_states_continue(self):
        for st in ("stopped", "interrupted", "failed"):
            self.assertEqual(self.action(view(st)).label, "Continue")
            self.assertTrue(self.action(view(st)).enabled, st)

    def test_waiting_quota_only_after_its_time(self):
        v = view("waiting_quota", wake_at=NOW + 100)
        self.assertEqual(self.action(v), js.Action("Continue", False))
        self.assertTrue(self.action(v, now=NOW + 101).enabled)
        self.assertFalse(self.action(view("waiting_quota")).enabled)

    def test_waiting_terms_only_after_review(self):
        v = view("waiting_terms", terms_pending=4)
        self.assertFalse(self.action(v).enabled)
        self.assertFalse(self.action(v, terms_now=2).enabled)
        self.assertTrue(self.action(v, terms_now=0).enabled)

    def test_new_run_only_with_a_different_selection(self):
        self.assertFalse(self.action(view("stopped"), same=True).new_run)
        self.assertTrue(self.action(view("stopped"), same=False).new_run)
        self.assertFalse(self.action(view("stopped"), same=False, sel=False).new_run)
        self.assertFalse(self.action(view(), same=False).new_run)

    def test_running_elsewhere_disables_everything(self):
        a = self.action(view("running", foreign=True))
        self.assertFalse(a.enabled)
        self.assertEqual(js.chip_for(view("running", foreign=True), False, False, None, NOW).text, "Running elsewhere")


class Chips(unittest.TestCase):
    def chip(self, v, **kw):
        kw.setdefault("running", False)
        kw.setdefault("stopping", False)
        kw.setdefault("paused_until", None)
        kw.setdefault("now", NOW)
        return js.chip_for(v, **kw)

    def test_each_state(self):
        self.assertEqual(self.chip(view("stopped")).text, "Stopped")
        self.assertEqual(self.chip(view("interrupted")).text, "Stopped")
        self.assertEqual(self.chip(view("failed")).text, "Failed")
        self.assertEqual(self.chip(view("finished")).text, "Done")
        self.assertEqual(self.chip(view("")).text, "")
        c = self.chip(view("waiting_quota", wake_at=NOW + 3600))
        self.assertTrue(c.text.startswith("Wait ") and c.kind == "dim")
        self.assertEqual(len(c.text), len("Wait 00:00"))
        self.assertEqual(self.chip(view("waiting_quota", wake_at=NOW - 1)).text, "Stopped")

    def test_terms_chip_is_accent_and_clickable_kind(self):
        c = self.chip(view("waiting_terms", terms_pending=7))
        self.assertEqual((c.text, c.kind, c.key), ("Terms 7", "accent", "terms"))
        self.assertEqual(self.chip(view("waiting_terms", terms_pending=7), terms_now=0).text, "Stopped")
        self.assertEqual(self.chip(view("waiting_terms", terms_pending=7), terms_now=3).text, "Terms 3")

    def test_paused_and_stopping_while_running(self):
        self.assertEqual(self.chip(view("running"), running=True, paused_until=NOW + 75).text, "Paused 1:15")
        self.assertEqual(self.chip(view("running"), running=True, paused_until=NOW - 1).text, "")
        self.assertEqual(self.chip(view("running"), running=True, stopping=True).text, "Stopping")


class Accent(unittest.TestCase):
    def test_one_owner(self):
        run = js.Action("Run", True)
        cont = js.Action("Continue", True)
        none = js.Chip()
        terms = js.Chip("Terms 3", "accent", "terms")
        self.assertEqual(js.accent_owner(run, none, 0, False), "action")
        self.assertEqual(js.accent_owner(run, none, 2, False), "problems")
        self.assertEqual(js.accent_owner(cont, none, 2, False), "action")
        self.assertEqual(js.accent_owner(js.Action("Stop", True), none, 2, True), "")
        self.assertEqual(js.accent_owner(js.Action("Continue", False), terms, 2, False), "terms")
        self.assertEqual(js.accent_owner(js.Action("Run", False), none, 2, False), "problems")


class Problems(unittest.TestCase):
    def test_assembly_from_chapter_log_records(self):
        recs = {(0, "a"): {"status": "ok"}, (1, "b"): {"status": "failed", "reason": "length"},
                (2, "c"): {"status": "failed"}}
        blocks = [(0, "a", "one"), (1, "b", "two"), (2, "c", "three"), (3, "d", "four")]
        out = js.assemble_problems(7, "Ch", blocks, lambda i, s: recs.get((i, s)))
        self.assertEqual([(p.block, p.reason, p.source) for p in out], [(1, "length", "two"), (2, "failed", "three")])
        self.assertEqual({p.chapter for p in out}, {7})

    def test_records_written_for_keep_and_manual(self):
        k = js.kept_record(3, "sha", "Original <1>text</1>", 5.0)
        self.assertEqual((k["status"], k["flags"], k["text"], k["i"], k["src_sha"]),
                         ("ok", ["kept"], "Original <1>text</1>", 3, "sha"))
        m = js.manual_record(3, "sha", "  typed  ", 5.0)
        self.assertEqual((m["status"], m["flags"], m["text"]), ("ok", ["manual"], "typed"))

    def test_shorten(self):
        self.assertEqual(js.shorten("a  b\nc", 10), "a b c")
        self.assertEqual(js.shorten("x" * 20, 8), "xxxxxxx…")


class Keys(unittest.TestCase):
    K1, K2 = "k1-" + "a" * 30, "k2-" + "b" * 30

    def test_mask_shows_only_the_last_four(self):
        m = keystore.mask(self.K1)
        self.assertTrue(m.endswith("aaaa"))
        self.assertNotIn(self.K1[:10], m)
        self.assertEqual(len(m), 12)

    def test_parse_one_per_line_dedup_and_prose_ignored(self):
        text = "%s\n  %s  \n%s\nsome words here\nshort" % (self.K1, self.K2, self.K1)
        self.assertEqual(keystore.parse_keys(text), [self.K1, self.K2])
        self.assertEqual(keystore.parse_keys("%s, %s;" % (self.K1, self.K2)), [self.K1, self.K2])

    def test_round_trip_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            ks = keystore.KeyStore(tmp)
            self.assertEqual(ks.add("%s\n%s" % (self.K1, self.K2)), 2)
            self.assertEqual(ks.add(self.K1), 0)
            again = keystore.KeyStore(tmp)
            self.assertEqual(again.keys, [self.K1, self.K2])
            again.remove(self.K1)
            self.assertEqual(keystore.KeyStore(tmp).keys, [self.K2])
            self.assertEqual(json.loads((Path(tmp) / "keys.json").read_text())["version"], 1)

    def test_damaged_file_reads_empty_and_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "keys.json").write_text("{broken", encoding="utf-8")
            ks = keystore.KeyStore(tmp)
            self.assertEqual(ks.keys, [])
            self.assertTrue(ks.damaged)
            self.assertTrue((Path(tmp) / "keys.json.bad").exists())
            ks.add(self.K1)
            self.assertEqual(keystore.KeyStore(tmp).keys, [self.K1])
            (Path(tmp) / "keys.json").write_text('{"keys": "no"}', encoding="utf-8")
            self.assertEqual(keystore.KeyStore(tmp).keys, [])

    def test_old_app_settings_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(keystore.old_app_keys(tmp), [])
            (Path(tmp) / "settings.json").write_text(json.dumps({"key": "%s,%s" % (self.K1, self.K2)}))
            self.assertEqual(keystore.old_app_keys(tmp), [self.K1, self.K2])
            (Path(tmp) / "settings.json").write_text("nope")
            self.assertEqual(keystore.old_app_keys(tmp), [])


class Prompts(unittest.TestCase):
    def test_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            ps = keystore.PromptStore(tmp)
            self.assertEqual(ps.names(), [])
            self.assertEqual(ps.save("My prompt", "Translate {language}."), "My prompt")
            ps.save("Alpha", "x")
            self.assertEqual(ps.names(), ["Alpha", "My prompt"])
            self.assertEqual(ps.read("My prompt"), "Translate {language}.")
            self.assertIsNone(ps.read("missing"))
            ps.save("My prompt", "changed")
            self.assertEqual(ps.read("My prompt"), "changed")
            self.assertEqual(ps.save('a/b:c', "t"), "a_b_c")
            ps.delete("Alpha")
            self.assertNotIn("Alpha", ps.names())

    def test_default_name_and_empty_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ps = keystore.PromptStore(tmp)
            for bad in ("Default", "default", "  ", "..."):
                with self.assertRaises(ValueError):
                    ps.save(bad, "x")


def E(source, count=1, first=0):
    e = Entry(source, count=count, seen={first})
    return e


class NextOrder(unittest.TestCase):
    def test_frontier_order_is_kept_and_other_sorts_work(self):
        rows = [E("B", 5, 1), E("A", 9, 2), E("C", 1, 3)]
        self.assertEqual([e.source for e in termlogic.arrange_next(rows, "", None, "first", False)], ["B", "A", "C"])
        self.assertEqual([e.source for e in termlogic.arrange_next(rows, "", None, "count", True)], ["A", "B", "C"])
        self.assertEqual([e.source for e in termlogic.arrange_next(rows, "a", None, "first", False)], ["A"])
        self.assertEqual(termlogic.default_order("next"), ("first", False))


if __name__ == "__main__":
    unittest.main()
