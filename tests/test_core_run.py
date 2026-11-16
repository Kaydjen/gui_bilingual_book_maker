import threading
import unittest
import zipfile
from pathlib import Path

from novelcore import check, export
from novelcore.pool import day_return
from tests.core_support import KEYS, MODEL, MODEL2, CoreCase, read_records
from tests.fake_api import fake_translate


def kinds(events, kind):
    return [e for e in events if e.kind == kind]


class RunBasicsTest(CoreCase):
    chapters = 10
    paras = 20
    per_request = 1
    api_args = {"rpm": 15}

    def test_three_keys_stay_under_rpm_and_order_is_kept(self):
        r, summary, events = self.run_all()
        self.assertEqual(self.count_done(), (200, 200))
        self.assertEqual(summary["requests"].get("minute", 0), 0)
        self.assertEqual(summary["blocks"]["ok"], 200)
        for k in range(3):
            self.assertGreater(len(self.api.requests(key=k)), 30)  # every key works
            self.assertLessEqual(self.api.max_in_window(k), 13)  # RPM 15 / 1.1
        self.assertTrue(self.requested_order_ok())
        self.assertEqual(len(kinds(events, "chapter_finished")), 10)
        self.assertEqual(kinds(events, "started")[0]["workers"], 10)  # 12 in flight at most, 10 chapters
        self.assertGreater((self.clock.now() - 1_760_000_000.0), 60 * 4)  # 200 requests need > 5 windows

    def test_jsonl_content_and_reload(self):
        self.run_all()
        files = sorted((self.series.path / "chapters").rglob("*.jsonl"))
        self.assertEqual(len(files), 10)
        recs = read_records(files[0])
        self.assertEqual([x["i"] for x in recs], list(range(20)))
        self.assertTrue(all(x["status"] == "ok" and x["model"] == MODEL and len(x["src_sha"]) == 40 for x in recs))
        self.assertEqual(recs[0]["text"], fake_translate("Chapter 0 paragraph 0 begins and keeps going for a while with some words."))
        self.assertEqual(self.count_done(), (200, 200))  # from a fresh Series object below
        from novelcore import Series
        self.series = Series.open(self.series.path)
        self.assertEqual(self.count_done(), (200, 200))

    def test_keys_never_reach_files_or_events(self):
        _, _, events = self.run_all()
        blob = self.files_text() + repr([(e.kind, e.data) for e in events])
        for k in KEYS:
            self.assertNotIn(k, blob)
        self.assertNotIn("SECRETSECRET", blob)


class StopAndResumeTest(CoreCase):
    chapters = 4
    paras = 8
    per_request = 2

    def test_restart_repeats_no_finished_block(self):
        from novelcore import gemini
        holder = {}
        calls = [0]
        lock = threading.Lock()

        def generate(*a, **kw):
            res = gemini.generate(*a, **kw)
            with lock:
                calls[0] += 1
                if calls[0] == 6:
                    holder["r"].stop()
            return res

        r = self.runner(generate=generate)
        holder["r"] = r
        summary = r.run()
        self.assertTrue(summary["stopped"])
        done, total = self.count_done()
        self.assertTrue(0 < done < total, (done, total))
        sent = len(self.api.log)
        r2 = self.runner()
        r2.run()
        self.assertEqual(self.count_done(), (32, 32))
        texts = [t for e in self.api.log for t in e["texts"]]
        self.assertEqual(len(texts), len(set(texts)), "a block was sent twice")
        self.assertGreater(len(self.api.log), sent)
        # a third run has nothing to do
        n = len(self.api.log)
        self.runner().run()
        self.assertEqual(len(self.api.log), n)


class QuotaTest(CoreCase):
    chapters = 3
    paras = 8
    per_request = 2
    api_args = {"rpm": 3, "retry_delay": 17}

    def test_minute_429_cools_pair_others_continue(self):
        r, summary, _ = self.run_all(in_flight=3, pace=24)
        self.assertEqual(self.count_done(), (24, 24))
        limited = self.api.requests(status=429)
        self.assertGreater(len(limited), 0)
        self.assertEqual(summary["requests"]["minute"], len(limited))
        for e in limited:
            later = [x["t"] for x in self.api.requests(key=e["key"]) if x["t"] > e["t"]]
            self.assertTrue(all(t >= e["t"] + 20 for t in later), "retryDelay 17 s + 3 s not respected")
        self.assertEqual(r.pool.rpm(MODEL), 3)  # learned from `limit: 3`
        self.assertTrue(all(self.api.requests(key=k) for k in range(3)))


class DayQuotaTest(CoreCase):
    chapters = 2
    paras = 6
    per_request = 3

    api_args = {"day_limit": {MODEL: 0}}

    def test_day_429_on_model_one_moves_to_model_two(self):
        r, summary, events = self.run_all(models=(MODEL, MODEL2))
        self.assertEqual(self.count_done(), (12, 12))
        self.assertLessEqual(len(self.api.requests(model=MODEL)), 6)  # only requests already in flight (6 workers)
        self.assertTrue(all(e["model"] == MODEL2 for e in self.api.requests(status=200)))
        recs = [x for f in (self.series.path / "chapters").rglob("*.jsonl") for x in read_records(f)]
        self.assertEqual({x["model"] for x in recs}, {MODEL2})
        self.assertEqual(summary["requests"]["day"], len(self.api.requests(model=MODEL)))
        self.assertTrue(any(e["state"] == "day" for e in map(lambda e: e.data, kinds(events, "pair"))))


class ExhaustedTest(CoreCase):
    chapters = 2
    paras = 6
    per_request = 2
    api_args = {"day_limit": 3}
    auto_clock = False

    def test_waiting_event_and_continuation_when_clock_advances(self):
        reset = day_return(self.clock.now())
        self.api.day_reset = reset
        r = self.runner(keys=KEYS[:1], shared_limit=False)  # a manual clock cannot pace sends
        r.start()
        waiting = None
        for _ in range(500):
            try:
                ev = r.events.get(timeout=0.02)
            except Exception:
                continue
            if ev.kind == "waiting":
                waiting = ev
                break
        self.assertIsNotNone(waiting, "no waiting event")
        self.assertEqual(waiting["until"], reset)
        self.assertEqual(waiting["reason"], "day")
        r.join(0.3)
        self.assertTrue(r._thread.is_alive(), "continued before the clock advanced")
        self.assertLess(self.count_done()[0], 12)
        self.clock.advance(reset - self.clock.now() + 1)
        r.join(20)
        self.assertFalse(r._thread.is_alive())
        self.assertEqual(self.count_done(), (12, 12))
        self.assertTrue(any(e.kind == "resumed" for e in r.drain()))
        after = [e for e in self.api.log if e["t"] >= reset]
        self.assertTrue(after and all(e["status"] == 200 for e in after))


class ServiceFaultTest(CoreCase):
    chapters = 1
    paras = 10
    per_request = 2
    api_args = {"unavailable_at": {2, 3, 4}}

    def test_503_backs_off_and_request_is_identical(self):
        r, summary, _ = self.run_all(keys=KEYS[:1], pace=120)  # the key's own limit (4.6 s apart) is the floor
        self.assertEqual(self.count_done(), (10, 10))
        self.assertEqual(summary["requests"]["unavailable"], 3)
        log = self.api.log
        self.assertEqual([e["status"] for e in log[:5]], [200, 503, 503, 503, 200])
        # backoff 2, 4, 8 seconds (+/- 25%, tested in test_core_limiter), but one key sends 13 a minute at most
        floor = 60 / 13
        for gap, base in zip((log[2]["t"] - log[1]["t"], log[3]["t"] - log[2]["t"], log[4]["t"] - log[3]["t"]),
                             (2, 4, 8)):
            self.assertGreaterEqual(gap, max(0.75 * base, floor) - 1e-6)
            self.assertLessEqual(gap, max(1.25 * base, floor) + 1e-6)
        self.assertEqual(log[1]["user"], log[2]["user"])
        self.assertEqual(log[1]["user"], log[4]["user"])
        self.assertTrue(self.requested_order_ok())
        self.assertEqual(summary["throttle"]["pauses"], 0)
        self.assertTrue(all(s["state"] == "ready" for s in r.pool.states()))


class DeadPairTest(CoreCase):
    chapters = 2
    paras = 6
    per_request = 2
    api_args = {"invalid_keys": {0}}

    def test_invalid_key_is_dead_after_one_request_and_run_continues(self):
        r, summary, _ = self.run_all()
        self.assertEqual(self.count_done(), (12, 12))
        self.assertEqual(len(self.api.requests(key=0)), 1)
        self.assertEqual(summary["requests"]["invalid_key"], 1)
        self.assertEqual(r.pool.states()[0]["state"], "dead")

    def test_all_dead_stops_with_error(self):
        self.api.invalid_keys = {0, 1, 2}
        r, summary, events = self.run_all()
        self.assertTrue(summary["error"])
        self.assertTrue(kinds(events, "error"))
        self.assertEqual(self.count_done()[0], 0)
        self.assertLessEqual(len(self.api.log), 6)  # only requests already in flight


class ModelMissingTest(CoreCase):
    chapters = 1
    paras = 4
    per_request = 4
    api_args = {"unknown_models": {MODEL}}

    def test_missing_model_is_dead_for_every_key(self):
        self.run_all(models=(MODEL, MODEL2))
        self.assertEqual(self.count_done(), (4, 4))
        self.assertEqual(len(self.api.requests(model=MODEL)), 1)


class BadAnswerTest(CoreCase):
    chapters = 1
    paras = 8
    alternate = True
    per_request = 4

    def finish(self, faults=None, fault_fn=None):
        self.api.faults = faults or {}
        self.api.fault_fn = fault_fn
        r, summary, events = self.run_all(keys=KEYS[:1])
        return r, summary, events

    def assert_all_correct(self):
        self.assertEqual(self.count_done(), (8, 8))
        for ch, blk in self.all_blocks():
            rec = self.series.chapter_log(self.book, ch).done(blk.index, blk.sha)
            self.assertEqual(rec["text"], fake_translate(blk.text))

    def test_each_kind_of_bad_answer_is_split_until_ok(self):
        for kind in ("empty", "max_tokens", "missing", "shift", "blank", "latin", "short", "garbage"):
            with self.subTest(kind=kind):
                for f in (self.series.path / "chapters").rglob("*.jsonl"):
                    f.unlink()
                self.series._logs.clear()
                self.series._sha = None
                before = len(self.api.log)
                self.finish(faults={before + 1: kind})
                self.assert_all_correct()
                sent = self.api.log[before:]
                self.assertGreater(len(sent), 2, "rejected group was not split")
                self.assertLessEqual(len(sent[1]["ids"]), 2)

    def test_persistent_failure_marks_only_that_block_failed(self):
        bad = "Chapter 0 line 5 "
        r, summary, events = self.finish(fault_fn=lambda e: "empty" if any(bad in t for t in e["texts"]) else None)
        self.assertEqual(self.count_done(), (7, 8))
        single = [e for e in self.api.log if len(e["ids"]) == 1 and bad in e["texts"][0]]
        self.assertEqual(len(single), 3)  # first try + 2 more
        failed = [x for f in (self.series.path / "chapters").rglob("*.jsonl") for x in read_records(f)
                  if x["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["reason"], "empty")
        self.assertEqual(summary["blocks"]["failed"], 1)
        self.assertEqual(len(kinds(events, "block_failed")), 1)
        ch = self.all_blocks()[5]
        self.assertIsNone(self.series.chapter_log(self.book, ch[0]).done(ch[1].index, ch[1].sha))
        # a rerun retries the failed block (and only it)
        n = len(self.api.log)
        self.runner(keys=KEYS[:1]).run()
        self.assertEqual(len(self.api.log) - n, 3)


class MarkupTest(CoreCase):
    chapters = 1
    paras = 4
    em_at = (1,)
    per_request = 4

    def stored(self):
        ch, blk = self.all_blocks()[1]
        return blk, self.series.chapter_log(self.book, ch).done(blk.index, blk.sha)

    def test_markers_kept(self):
        self.run_all(keys=KEYS[:1])
        blk, rec = self.stored()
        self.assertIn("<1>", rec["text"])
        self.assertEqual(rec["flags"], [])
        self.assertEqual(len(self.api.log), 1)

    def test_broken_markers_retry_once_then_ok(self):
        self.api.faults = {1: "nomarkers"}
        self.run_all(keys=KEYS[:1])
        blk, rec = self.stored()
        self.assertIn("<1>", rec["text"])
        self.assertEqual(rec["flags"], [])
        self.assertEqual([len(e["ids"]) for e in self.api.log], [4, 1])

    def test_markers_lost_twice_become_plain_text_with_flag(self):
        self.api.fault_fn = lambda e: "nomarkers"
        r, summary, _ = self.run_all(keys=KEYS[:1])
        blk, rec = self.stored()
        self.assertEqual(rec["flags"], ["markup"])
        self.assertNotIn("<1>", rec["text"])
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(summary["blocks"]["flagged"], 1)
        self.assertEqual(len(self.api.log), 2)  # one retry only
        self.assertEqual(self.count_done(), (4, 4))


class ContextAndTermsTest(CoreCase):
    chapters = 2
    paras = 6
    per_request = 2

    def test_context_is_last_three_finished_pairs_of_the_same_chapter(self):
        self.run_all(keys=KEYS[:1], in_flight=1)
        c0 = [e for e in self.api.log if e["texts"][0].startswith("Chapter 0")]
        self.assertNotIn("CONTEXT", c0[0]["user"])
        second = c0[1]["user"]
        self.assertIn("CONTEXT", second)
        ctx = second.split("\nTEXT")[0]
        self.assertIn("paragraph 0 ", ctx)
        self.assertIn("paragraph 1 ", ctx)
        third = c0[2]["user"].split("\nTEXT")[0]
        self.assertNotIn("paragraph 0 ", third.split("CONTEXT", 1)[1])
        self.assertIn("paragraph 3 ", third)
        self.assertNotIn("Chapter 1", third)  # nothing from another chapter

    def test_terms_hook(self):
        seen = []

        def terms(chapter, blocks):
            seen.append((chapter.index, len(blocks)))
            return ["Foxhound -> Лис"] if blocks[0].index == 2 else []

        self.run_all(keys=KEYS[:1], in_flight=1, terms_for=terms)
        with_terms = [e for e in self.api.log if "TERMS" in e["user"]]
        self.assertEqual(len(with_terms), 2)  # one per chapter, at block 2
        self.assertIn("Foxhound -> Лис", with_terms[0]["user"])
        self.assertTrue(seen)
        # and no TERMS section when the hook says nothing
        self.assertTrue(all("TERMS" not in e["user"] for e in self.api.log if e["texts"][0].endswith("words.") and "paragraph 0" in e["texts"][0]))


class SeriesWideReuseTest(CoreCase):
    chapters = 3
    paras = 4
    per_request = 4

    def test_same_chapter_in_another_book_is_not_translated_twice(self):
        from tests.core_support import build_epub
        self.run_all(keys=KEYS[:1])
        first = len(self.api.log)
        build_epub(self.dir / "Cut.epub", chapters=2, paras=4, first_chapter=1)  # chapters 1 and 2 again
        cut = self.series.add_book(self.dir / "Cut.epub")
        r = self.runner(keys=KEYS[:1], book=cut)
        summary = r.run()
        self.assertEqual(len(self.api.log), first)
        self.assertEqual(summary["blocks"]["reused"], 8)
        with self.series.open_book(cut) as b:
            rec = self.series.chapter_log(cut, b.chapters[0]).done(0, b.blocks(b.chapters[0])[0].sha)
        self.assertTrue(rec["reuse"])


class SampleTest(CoreCase):
    chapters = 3
    paras = 9
    per_request = 3

    def test_sample_writes_only_to_samples(self):
        r = self.runner(keys=KEYS[:1])
        summary = r.sample(1, blocks=5)
        self.assertFalse(summary["error"])
        self.assertEqual(list((self.series.path / "chapters").rglob("*")), [])
        files = list((self.series.path / "samples").rglob("*.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertEqual(len(read_records(files[0])), 5)
        self.assertEqual(len(self.api.log), 2)  # 3 + 2 blocks
        # again: a fresh sample, not a continuation, and still nothing in chapters/
        self.runner(keys=KEYS[:1]).sample(1, blocks=5)
        self.assertEqual(len(read_records(files[0])), 5)
        self.assertEqual(len(self.api.log), 4)
        self.assertEqual(list((self.series.path / "chapters").rglob("*")), [])


class ExportTest(CoreCase):
    chapters = 3
    paras = 5
    per_request = 5
    nav = True
    em_at = (2,)

    def test_toc_page_is_translated_but_not_counted(self):
        r, _, events = self.run_all(keys=KEYS[:1])
        self.assertEqual(kinds(events, "started")[0]["chapters"], 3)
        self.assertEqual(kinds(events, "started")[0]["pages"], 4)
        toc = [e for e in kinds(events, "chapter_finished") if e["toc"]]
        self.assertEqual(len(toc), 1)
        self.assertEqual(toc[0]["ok"], 3)
        self.assertEqual(self.count_done(), (18, 18))

    def test_export_both_modes_make_valid_epubs(self):
        self.run_all(keys=KEYS[:1])
        src = self.series.path / "books" / (self.book + ".epub")
        single = export(self.series, self.book, 0, None, "single", cut=False)
        both = export(self.series, self.book, 0, None, "bilingual", cut=False)
        for res in (single, both):
            self.assertTrue(res.path.exists() and res.path.parent == self.series.path / "out")
            self.assertEqual(res.problems, [])
            self.assertEqual(check(res.path, source=src), [])
            self.assertEqual((res.blocks, res.untranslated, res.fallbacks), (18, 0, []))
        with zipfile.ZipFile(single.path) as z:
            page = z.read("OEBPS/c1.xhtml").decode("utf-8")
            opf = z.read("OEBPS/content.opf").decode("utf-8")
        self.assertIn(fake_translate("Chapter 1 paragraph 0 begins"), page)
        self.assertNotIn("Chapter 1 paragraph 0", page)
        self.assertIn("<dc:language>ru</dc:language>", opf)
        with zipfile.ZipFile(both.path) as z:
            page = z.read("OEBPS/c1.xhtml").decode("utf-8")
        self.assertIn("Chapter 1 paragraph 0", page)
        self.assertIn(fake_translate("Chapter 1 paragraph 0 begins"), page)

    def test_partial_range_and_failed_blocks_stay_source(self):
        self.run_all(keys=KEYS[:1], first=1, last=2)
        res = export(self.series, self.book, 1, 2, "single")
        self.assertEqual(res.problems, [])
        self.assertEqual(res.untranslated, 0)
        wide = export(self.series, self.book, 0, 3, "single", cut=False)
        self.assertEqual(wide.untranslated, 3 + 5)  # nav (3 links) and chapter 2 untouched
        self.assertEqual(wide.problems, [])


class SelectionAndGateTest(CoreCase):
    chapters = 5
    paras = 4
    per_request = 2

    def test_list_selection_and_gate_prefix(self):
        r = self.runner(chapters=[3, 1, 1, 0], in_flight=1, gate=lambda i: 2 if i == 3 else 0)
        summary = r.run()
        events = r.drain()
        self.assertEqual(self.count_done()[0], 8)  # chapters 0 and 1
        self.assertEqual(summary["blocked"]["index"], 3)
        self.assertEqual(len(kinds(events, "terms")), 1)
        self.assertEqual(kinds(events, "started")[0]["selected"], 3)

    def test_sample_never_asks_the_gate(self):
        def gate(i):
            raise AssertionError("gate used by sample")

        summary = self.runner(gate=gate).sample(2, 4)
        self.assertIsNone(summary["blocked"])
        self.assertEqual(len(self.api.log) > 0, True)


if __name__ == "__main__":
    unittest.main()
