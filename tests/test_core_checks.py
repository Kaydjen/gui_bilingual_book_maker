import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from novelcore import Series, checks
from novelcore.checks import Finding, Report
from novelcore.job import SeriesBusy, state_dir
from novelcore.store import read_jsonl
from novelcore.terms import TermBase
from tests.core_support import KEYS, MODEL, CoreCase
from tests.test_core_epub import make_epub

BOOK = "Synth"


def cyr(n: int) -> str:
    return ("слово " * (n // 6 + 2))[:n].strip() or "с"


def long_src(tag: str = "a") -> str:
    return f"This is a rather long source sentence number {tag} that has enough characters in it."


class Synth(unittest.TestCase):
    """A series with hand-written translations: every record is put in the log by the test."""

    target = "ru:Russian"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def make(self, chapters, target=None, terms=None):
        """chapters: list of lists of paragraph html. terms: list of (source, tr[, status])."""
        docs = {f"c{n}.xhtml": "\n".join(f"<p>{p}</p>" for p in paras) for n, paras in enumerate(chapters)}
        self._n = getattr(self, "_n", 0) + 1
        root = self.dir / f"s{self._n}"
        root.mkdir()
        epub = root / f"{BOOK}.epub"
        make_epub(epub, docs)
        self.series = Series.create(root / "lib", "S", target or self.target)
        self.series.add_book(epub)
        if terms:
            base = TermBase(self.series.path / "terms.json", self.series.target_tag)
            for t in terms:
                base.add(t[0], status=t[2] if len(t) > 2 else "confirmed", tr=t[1])
            base.save()
        with self.series.open_book(BOOK) as b:
            self.blocks = {c.index: list(b.blocks(c)) for c in b.chapters}
        return self.series

    def put(self, ch, i, text, flags=None, status="ok", **extra):
        blk = self.blocks[ch][i]
        with self.series.open_book(BOOK) as b:
            log = self.series.chapter_log(BOOK, b.chapters[ch])
            rec = {"i": i, "src_sha": blk.sha, "text": text, "model": "m", "at": 1.0, "status": status,
                   "flags": list(flags or [])}
            rec.update(extra)
            log.append([rec])

    def fill(self, ch, texts):
        for i, t in enumerate(texts):
            self.put(ch, i, t)

    def check(self, ch=0):
        return checks.check_range(self.series, BOOK, [ch])

    def kinds(self, ch=0):
        return sorted((f.block, f.kind) for f in self.check(ch).findings())


class LeftoverRu(Synth):
    def test_run_of_english_words_is_flagged(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "Он сказал: the quick brown fox jumps и ушёл домой надолго.")
        f = self.check().findings("leftover")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].detail["rule"], "run")
        self.assertIn("quick brown", f[0].detail["fragment"])

    def test_share_rule(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "Он, Cold Shadow, пришёл.")  # a two-word name left in English: a run of 2
        f = self.check().findings("leftover")
        self.assertEqual([x.detail["rule"] for x in f], ["run"])
        self.put(0, 0, "Он, Cold, потом Shadow пришёл.")  # not adjacent: two Latin words out of five
        f = self.check().findings("leftover")
        self.assertEqual([x.detail["rule"] for x in f], ["share"])

    def test_one_stray_word_is_not_flagged(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "Он взял меч, который назывался Excalibur, и пошёл дальше по дороге вместе с друзьями.")
        self.assertEqual(self.check().findings("leftover"), [])

    def test_short_tokens_are_allowed(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "У него было 100 HP и 50 MP, а ещё Lv5, ранг S-rank, глава XVIII, герои из NPC и VIP, путь 5 km.")
        self.assertEqual(self.check().findings("leftover"), [])

    def test_url_and_email_are_ignored(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "Пишите нам на help.desk@example.com или заходите на https://www.example.com/the/long/path сегодня же.")
        self.assertEqual(self.check().findings("leftover"), [])

    def test_term_translation_in_latin_is_allowed(self):
        self.make([[long_src("1")]], terms=[("Long source", "Long Source Code Base")])
        self.put(0, 0, "Это Long Source Code Base, очень длинное предложение про настоящее место.")
        self.assertEqual(self.check().findings("leftover"), [])

    def test_marked_span_kept_verbatim_is_allowed(self):
        self.make([["Open the <em>Skill Tree Menu</em> now and look at it carefully, friend."]])
        self.assertIn("<1>", self.blocks[0][0].text)
        self.put(0, 0, "Откройте <1>Skill Tree Menu</1> сейчас и внимательно посмотрите на него, друг.")
        self.assertEqual(self.check().findings("leftover"), [])
        self.put(0, 0, "Откройте <1>Skill Tree Menu</1> сейчас and look at it carefully my dear friend.")
        self.assertEqual(len(self.check().findings("leftover")), 1)  # the verbatim span is fine, the rest is not

    def test_marked_long_span_is_not_allowed(self):
        self.make([["She said <em>this is a long sentence in italics</em> to him and left the room."]])
        self.put(0, 0, "Она сказала <1>this is a long sentence in italics</1> ему и вышла из комнаты.")
        self.assertEqual(len(self.check().findings("leftover")), 1)

    def test_script_share(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "The whole answer was left in English by the model and nothing was translated at all.")
        self.assertEqual(len(self.check().findings("leftover")), 1)


class LeftoverPl(Synth):
    target = "pl:Polish"

    def test_english_block(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "He said that she had not been there with them when the others were gone from the house.")
        f = self.check().findings("leftover")
        self.assertEqual((len(f), f[0].detail["scope"]), (1, "block"))

    def test_english_sentence_inside_polish_block(self):
        self.make([[long_src("1")]])
        pol = ("On powiedział, że wszystko jest w porządku i że nie ma się czym martwić, bo to było tylko "
               "nieporozumienie między nimi. ")
        eng = "She said that they had not been there with the others when the whole thing was over and done."
        self.put(0, 0, pol + eng)
        f = self.check().findings("leftover")
        self.assertEqual((len(f), f[0].detail["scope"]), (1, "sentence"))
        self.assertIn("She said", f[0].detail["fragment"])

    def test_polish_is_clean(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "On powiedział, że wszystko jest w porządku i że nie ma się czym martwić, bo to było "
                       "tylko nieporozumienie między nimi.")
        self.assertEqual(self.check().findings("leftover"), [])


class RatioCase(Synth):
    def test_outlier_against_chapter_median(self):
        paras = [long_src(str(n)) for n in range(8)]
        self.make([paras])
        for i, p in enumerate(paras):
            self.put(0, i, cyr(len(p) if i != 3 else 12))
        f = self.check().findings("ratio")
        self.assertEqual([x.block for x in f], [3])
        self.assertAlmostEqual(f[0].detail["median"], 1.0, places=1)

    def test_long_outlier(self):
        paras = [long_src(str(n)) for n in range(8)]
        self.make([paras])
        for i, p in enumerate(paras):
            self.put(0, i, cyr(len(p) * (3 if i == 5 else 1)))
        self.assertEqual([x.block for x in self.check().findings("ratio")], [5])

    def test_short_source_and_small_chapter_are_not_judged(self):
        paras = ["Short one.", "Another short.", "Third short line."] + [long_src(str(n)) for n in range(3)]
        self.make([paras])
        for i, p in enumerate(paras):
            self.put(0, i, cyr(len(p) * 4 if i < 3 else len(p)))
        self.assertEqual(self.check().findings("ratio"), [])  # only 3 blocks over 40 characters: no median

    def test_short_sources_do_not_count(self):
        paras = [long_src(str(n)) for n in range(6)] + ["Yes sir, I will.", "No."]
        self.make([paras])
        for i, p in enumerate(paras):
            self.put(0, i, cyr(len(p)) if i < 6 else cyr(len(p) * 5))
        self.assertEqual(self.check().findings("ratio"), [])


class TermCase(Synth):
    def run_case(self, src, terms, translated):
        self.make([[src]], terms=terms)
        self.put(0, 0, translated)
        return self.check().findings("term")

    def test_missing_translation(self):
        f = self.run_case("Then Shi Feng turned his head and looked at the tall wall behind him for a while.",
                          [("Shi Feng", "Ши Фэн")], "Тогда он повернул голову и долго смотрел на высокую стену позади.")
        self.assertEqual((len(f), f[0].detail["term"], f[0].detail["expected"]), (1, "Shi Feng", "Ши Фэн"))

    def test_declined_forms_pass(self):
        src = "Then Shi Feng turned his head and looked at the tall Resource Nodes behind him for a while."
        for tr in ("Тогда Ши Фэн повернул голову и посмотрел на высокие Узлы Ресурсов позади.",
                   "Тогда Ши Фэна заметили у Узлов Ресурсов, а он смотрел на высокую стену позади."):
            self.assertEqual(self.run_case(src, [("Shi Feng", "Ши Фэн"), ("Resource Node", "Узел Ресурсов")], tr), [], tr)

    def test_one_word_of_two_missing(self):
        f = self.run_case("The Resource Node was far away from the old road where they had met before.",
                          [("Resource Node", "Узел Ресурсов")], "Узел был далеко от старой дороги, где они встретились.")
        self.assertEqual(len(f), 1)

    def test_unconfirmed_and_empty_translation_are_skipped(self):
        src = "Then Shi Feng turned his head and looked at the tall wall behind him for a while."
        self.assertEqual(self.run_case(src, [("Shi Feng", "Ши Фэн", "new")], "Он посмотрел на высокую стену позади."), [])
        self.assertEqual(self.run_case(src, [("Shi Feng", "")], "Он посмотрел на высокую стену позади."), [])

    def test_term_absent_from_source_is_not_checked(self):
        self.assertEqual(self.run_case("Nobody was at home on that long and quiet evening in the late autumn.",
                                       [("Shi Feng", "Ши Фэн")], "Никого не было дома тем долгим вечером."), [])

    def test_fleeting_vowel_and_short_words(self):
        src = "The Resource Node and the Iron Man were far away from the old road where they had met."
        ok = "Узлов Ресурсов и Железный Человек были далеко от старой дороги, где они встретились."
        self.assertEqual(self.run_case(src, [("Resource Node", "Узел Ресурсов")], ok), [])
        # a two-letter word must be there as a whole word
        f = self.run_case("Then Ye Li came back to the hall of the old house in the evening light.",
                          [("Ye Li", "Е Ли")], "Потом Е Лиан вернулся в зал старого дома.")
        self.assertEqual(len(f), 1)

    def test_pronoun_replacement_is_a_known_false_alarm(self):
        f = self.run_case("Then Shi Feng turned his head and looked at the tall wall behind him for a while.",
                          [("Shi Feng", "Ши Фэн")], "Тогда он повернул голову.")
        self.assertEqual(len(f), 1)  # documented: the check cannot tell a pronoun from a missed term


class MarkupCase(Synth):
    SRC = "Open the <em>Skill Tree</em> now and look at the <b>big</b> picture with your own eyes."

    def test_flag_count_order_and_clean(self):
        self.make([[self.SRC]] * 1)
        t = self.blocks[0][0].text
        self.assertIn("<1>Skill Tree</1>", t)
        self.put(0, 0, "Откройте <1>Древо навыков</1> сейчас и взгляните на <2>большую</2> картину своими глазами.")
        self.assertEqual(self.check().findings("markup"), [])
        self.put(0, 0, "Откройте Древо навыков сейчас и взгляните на большую картину своими глазами.", flags=["markup"])
        f = self.check().findings("markup")
        self.assertEqual(f[0].detail, {"why": "flag"})
        self.put(0, 0, "Откройте <1>Древо навыков</1> сейчас и взгляните на большую картину своими глазами.")
        self.assertEqual(self.check().findings("markup")[0].detail["why"], "count")
        self.put(0, 0, "Откройте <2>Древо навыков</2> сейчас и взгляните на <1>большую</1> картину своими глазами.")
        self.assertEqual(self.check().findings("markup")[0].detail["why"], "order")


class OtherKinds(Synth):
    def test_untranslated(self):
        s = "Zero Wing is the name of the guild that the story follows."
        self.make([[s, "Yes, sir."]])
        self.put(0, 0, "  " + s.replace(" ", "  ") + " ")
        self.put(0, 1, "Yes, sir.")
        f = self.check().findings("untranslated")
        self.assertEqual([x.block for x in f], [0])  # the 2-word block is not judged

    def test_empty(self):
        self.make([[long_src("1"), long_src("2")]])
        self.put(0, 0, "   ")
        self.put(0, 1, "Это нормальный перевод, но он совсем другой.")
        r = self.check()
        self.assertEqual([(f.block, f.kind) for f in r.findings()], [(0, "empty")])

    def test_exemptions(self):
        s = "Zero Wing is the name of the guild that the story follows."
        self.make([[s, s, s]], terms=[("Zero Wing", "Нулевое Крыло")])
        self.put(0, 0, s, flags=["kept"])
        self.put(0, 1, "", flags=["manual"])
        self.put(0, 2, s)
        r = self.check()
        self.assertEqual({f.block for f in r.findings()}, {2})
        self.assertEqual((r.chapters[0].exempt, r.chapters[0].checked), (2, 3))

    def test_missing_failed_retry(self):
        self.make([[long_src(str(n)) for n in range(5)]])
        self.put(0, 0, "Это нормальный перевод, но он совсем другой.")
        self.put(0, 1, "", status="failed", reason="x")
        self.put(0, 2, "", status="retry", prev="x")
        r = self.check()
        c = r.chapters[0]
        self.assertEqual((c.blocks, c.checked, c.missing, c.failed, c.retry), (5, 1, 4, 1, 1))
        self.assertEqual(r.findings(), [])

    def test_check_chapter_matches_range(self):
        self.make([[long_src("1")]])
        self.put(0, 0, "   ")
        with self.series.open_book(BOOK) as b:
            f = checks.check_chapter(self.series, b, 0)
        self.assertEqual([x.kind for x in f], ["empty"])

    def test_progress_and_cancel(self):
        self.make([[long_src("1")], [long_src("2")], [long_src("3")]])
        seen = []
        r = checks.check_range(self.series, BOOK, [0, 1, 2], progress=lambda d, t, i: seen.append((d, t, i)))
        self.assertEqual(seen, [(1, 3, 0), (2, 3, 1), (3, 3, 2)])
        calls = []
        r = checks.check_range(self.series, BOOK, [0, 1, 2], cancel=lambda: calls.append(1) or len(calls) > 1)
        self.assertTrue(r.cancelled)
        self.assertEqual(list(r.chapters), [0])


class ReportCase(Synth):
    def test_round_trip_save_load_lines(self):
        self.make([[long_src("1"), long_src("2")]])
        self.put(0, 0, "   ")
        self.put(0, 1, "Он, Cold Shadow, пришёл.")
        r = self.check()
        again = Report.from_json(r.to_json())
        self.assertEqual(again.to_json(), r.to_json())
        self.assertEqual(again.counts()["empty"], 1)
        self.assertIsInstance(again.findings()[0], Finding)
        path = r.save(self.series)
        self.assertEqual(path, self.series.path / ".state" / f"check_{BOOK}.json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["counts"]["leftover"], 1)
        self.assertEqual(Report.load(self.series, BOOK).to_json(), r.to_json())
        self.assertIsNone(Report.load(self.series, "Nope"))
        text = "\n".join(r.lines(ascii_only=True))
        self.assertTrue(text.isascii())
        self.assertIn("[leftover]", text)
        self.assertFalse("\n".join(r.lines()).isascii())


class RetryDirect(Synth):
    def setUp(self):
        super().setUp()
        self.make([[long_src("0"), long_src("1"), long_src("2")], [long_src("3"), long_src("4")]])
        for ch in (0, 1):
            self.fill(ch, [f"Перевод номер {ch}-{i} достаточно длинный для проверки." for i in range(len(self.blocks[ch]))])

    def pairs(self, *items):
        return [(c, i, self.blocks[c][i].sha) for c, i in items]

    def test_mark_writes_retry_records_and_restore_undoes(self):
        info = checks.mark_for_retry(self.series, BOOK, self.pairs((0, 1), (1, 0), (1, 1)) + [(0, 1, "stale")])
        self.assertEqual((info["chapters"], info["marked"], info["skipped"]), ([0, 1], 3, 1))
        log = self.series.chapter_log(BOOK, self._chapter(0))
        self.assertIsNone(log.done(1, self.blocks[0][1].sha))
        self.assertEqual(log.lookup(1, self.blocks[0][1].sha)["status"], "retry")
        raw = [r for r in read_jsonl(log.path) if r["status"] == "retry"]
        self.assertEqual(raw[0]["prev"], "Перевод номер 0-1 достаточно длинный для проверки.")
        self.assertEqual(raw[0]["why"], [])
        # marking again does nothing: the block is not finished
        again = checks.mark_for_retry(self.series, BOOK, self.pairs((0, 1)))
        self.assertEqual((again["marked"], again["skipped"]), (0, 1))
        res = checks.restore_previous(self.series, BOOK, self.pairs((0, 1), (1, 0)))
        self.assertEqual((res["restored"], res["chapters"]), (2, [0, 1]))
        rec = log.done(1, self.blocks[0][1].sha)
        self.assertEqual(rec["text"], raw[0]["prev"])
        self.assertTrue(rec["restored"])
        self.assertEqual(checks.restore_previous(self.series, BOOK, self.pairs((0, 1)))["restored"], 0)

    def test_findings_carry_their_kinds(self):
        self.put(0, 0, "   ")
        f = self.check(0).findings()
        checks.mark_for_retry(self.series, BOOK, f)
        log = self.series.chapter_log(BOOK, self._chapter(0))
        self.assertEqual([r["why"] for r in read_jsonl(log.path) if r["status"] == "retry"], [["empty"]])

    def test_refused_while_series_is_held(self):
        path = state_dir(self.series.path) / "run.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}), encoding="utf-8")
        with self.assertRaises(SeriesBusy):
            checks.mark_for_retry(self.series, BOOK, self.pairs((0, 0)))
        with self.assertRaises(SeriesBusy):
            checks.restore_previous(self.series, BOOK, self.pairs((0, 0)))
        log = self.series.chapter_log(BOOK, self._chapter(0))
        self.assertTrue(all(r["status"] == "ok" for r in read_jsonl(log.path)))

    def _chapter(self, n):
        with self.series.open_book(BOOK) as b:
            return b.chapters[n]


class RetryRun(CoreCase):
    """The marked blocks are translated again by a normal Job, and only they."""

    api_args = {"poll_interval": 0.02}
    chapters = 3
    paras = 6
    per_request = 6

    def job_kw(self):
        return dict(clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15})

    def translate_all(self):
        from novelcore.job import Job
        Job(self.series, self.book, self.keys, [MODEL], gate=False, **self.job_kw()).run()
        self.assertEqual(self.count_done(), (18, 18))

    def pairs(self, *items):
        return [(c, i, self.blocks_of(c)[i].sha) for c, i in items]

    def blocks_of(self, c):
        with self.series.open_book(self.book) as b:
            return list(b.blocks(b.chapters[c]))

    def test_plain_job_over_fresh_series_translates_marked_blocks_anew(self):
        # the series index no longer hands out the old text of a block that is pending a retry, so a plain
        # Job in another process (a fresh Series) sends the request itself
        self.translate_all()
        info = checks.mark_for_retry(self.series, self.book, self.pairs((0, 1), (2, 3)))
        self.assertEqual(info["marked"], 2)
        n0 = len(self.api.log)
        from novelcore.job import Job
        fresh = Series.open(self.series.path)
        Job(fresh, self.book, self.keys, [MODEL], gate=False, **self.job_kw()).run()
        sent = [t for e in self.api.log[n0:] for t in e["texts"]]
        self.assertEqual(sorted(sent), sorted(self.blocks_of(c)[i].text for c, i in ((0, 1), (2, 3))))
        with fresh.open_book(self.book) as b:
            rec = fresh.chapter_log(self.book, b.chapters[0]).done(1, self.blocks_of(0)[1].sha)
        self.assertFalse(rec.get("reuse"))

    def test_restore_makes_the_text_reusable_again(self):
        self.translate_all()
        sel = self.pairs((0, 1))
        checks.mark_for_retry(self.series, self.book, sel)
        sha = sel[0][2]
        self.assertIsNone(Series.open(self.series.path).find_done(sha))
        self.assertIsNone(self.series.find_done(sha))
        checks.restore_previous(self.series, self.book, sel)
        self.assertIsNotNone(Series.open(self.series.path).find_done(sha))
        self.assertIsNotNone(self.series.find_done(sha))

    def test_retry_translates_exactly_the_marked_blocks(self):
        self.translate_all()
        sel = [(0, 1), (0, 4), (2, 3)]
        with self.series.open_book(self.book) as b:  # an older, different text for the blocks to be retried
            for c, i in sel:
                self.series.chapter_log(self.book, b.chapters[c]).append(
                    [{"i": i, "src_sha": self.blocks_of(c)[i].sha, "text": f"Старый вариант {c}-{i}", "model": "old",
                      "at": 1.0, "status": "ok", "flags": []}])
        first = len(self.api.log)
        job = checks.retry(self.series, self.book, self.pairs(*sel), self.keys, [MODEL], **self.job_kw())
        self.assertEqual(job.chapters, [0, 2])
        job.run()
        sent = [t for e in self.api.log[first:] for t in e["texts"]]
        want = [self.blocks_of(c)[i].text for c, i in sel]
        self.assertEqual(sorted(sent), sorted(want))
        self.assertEqual(len(self.api.log) - first, 2)  # one request per chapter (6 per request)
        self.assertEqual(self.count_done(), (18, 18))
        with self.series.open_book(self.book) as b:
            for c, i in sel:
                rec = self.series.chapter_log(self.book, b.chapters[c]).done(i, self.blocks_of(c)[i].sha)
                self.assertFalse(rec.get("reuse"))
                self.assertGreater(rec["at"], 0)
        # restore still finds the old text, though the retry's own record replaced the marker in memory
        res = checks.restore_previous(self.series, self.book, self.pairs(*sel))
        self.assertEqual(res["restored"], 3)
        with self.series.open_book(self.book) as b:
            rec = self.series.chapter_log(self.book, b.chapters[0]).done(1, self.blocks_of(0)[1].sha)
        self.assertEqual(rec["text"], "Старый вариант 0-1")

    def test_nothing_to_retry_raises(self):
        from novelcore.job import JobError
        self.translate_all()
        with self.assertRaises(JobError):
            checks.retry(self.series, self.book, [(0, 0, "no such sha")], self.keys, [MODEL], **self.job_kw())


class Clippings(unittest.TestCase):
    EN = ("﻿My Novel (Some Author)\r\n"
          "- Your Highlight on page 12 | location 345-346 | Added on Friday, 14 November 2026 10:20:30\r\n"
          "\r\n"
          "Первый выделенный текст.\r\n"
          "==========\r\n"
          "My Novel (Some Author)\r\n"
          "- Your Note on Location 400 | Added on Friday, 14 November 2026 10:25:30\r\n"
          "\r\n"
          "check this\r\n"
          "==========\r\n"
          "My Novel (Some Author)\r\n"
          "- Your Bookmark at location 500 | Added on Friday, 14 November 2026 10:26:30\r\n"
          "\r\n"
          "\r\n"
          "==========\r\n")
    RU = ("Мой роман (Автор Автор)\n"
          "- Ваш выделенный отрывок на странице 7 | Место 100-101 | Добавлено: пятница, 14 ноября 2026 г. 10:20:30\n"
          "\n"
          "Второй выделенный текст,\nс переносом.\n"
          "==========\n")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name, text):
        p = self.dir / name
        p.write_bytes(text.encode("utf-8"))
        return p

    def test_english_with_bom(self):
        clips = checks.parse_clippings(self.write("en.txt", self.EN))
        self.assertEqual([c.kind for c in clips], ["highlight", "note", "bookmark"])
        c = clips[0]
        self.assertEqual((c.title, c.author, c.page, c.location), ("My Novel", "Some Author", 12, "345-346"))
        self.assertTrue(c.added.startswith("Friday, 14 November 2026"))
        self.assertEqual(c.text, "Первый выделенный текст.")
        self.assertEqual((clips[1].page, clips[1].location, clips[1].text), (None, "400", "check this"))
        self.assertEqual(clips[2].text, "")

    def test_russian(self):
        clips = checks.parse_clippings(self.write("ru.txt", self.RU))
        self.assertEqual(len(clips), 1)
        c = clips[0]
        self.assertEqual((c.kind, c.title, c.author, c.page, c.location), ("highlight", "Мой роман", "Автор Автор", 7, "100-101"))
        self.assertTrue(c.added.startswith("пятница"))
        self.assertEqual(c.text, "Второй выделенный текст,\nс переносом.")

    def test_locate(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        docs = {"c0.xhtml": "<p>One.</p>\n<p>Первый абзац перевода идёт здесь и заканчивается вот так.</p>\n"
                            "<p>А второй абзац начинается тут, <em>с курсивом</em> и продолжается дальше.</p>",
                "c1.xhtml": "<p>Two.</p>\n<p>Совсем другая глава с отдельным текстом.</p>"}
        epub = Path(tmp.name) / "B.epub"
        make_epub(epub, docs)
        series = Series.create(Path(tmp.name) / "lib", "S", "ru:Russian")
        name = series.add_book(epub)
        with series.open_book(name) as b:
            for ch in b.chapters:
                log = series.chapter_log(name, ch)
                blocks = b.blocks(ch)
                tr = {"One.": "Раз.", "Two.": "Два."}
                texts = [tr.get(x.text) or x.text for x in blocks]
                log.append([{"i": x.index, "src_sha": x.sha, "text": t, "model": "m",
                             "at": 1.0, "status": "ok", "flags": []} for x, t in zip(blocks, texts)])
        # make the second chapter's blocks "translated" (the stored text of untranslated ones equals the source)
        one = checks.Clip("B", "", "highlight", 1, "1", "", "Первый   абзац перевода\nидёт здесь")
        span = checks.Clip("B", "", "highlight", 1, "1", "", "заканчивается вот так. А второй абзац начинается тут, с курсивом и")
        lost = checks.Clip("B", "", "highlight", 1, "1", "", "Этого текста нет в книге ни в одной главе")
        tail = checks.Clip("B", "", "highlight", 1, "1", "", "Совсем другая глава с отдельным текстом. И дальше чужой хвост")
        empty = checks.Clip("B", "", "bookmark", None, "5", "", "")
        res = checks.locate_clips(series, name, [one, span, lost, tail, empty])
        self.assertEqual(res[0][1:], (0, 1))
        self.assertEqual(res[1][1:], (0, 1))  # starts in block 1 and runs into block 2
        self.assertIsNone(res[2])
        self.assertEqual(res[3][1:], (1, 1))  # longest prefix
        self.assertIsNone(res[4])
        only1 = checks.locate_clips(series, name, [one], chapters=[1])
        self.assertEqual(only1, [None])


if __name__ == "__main__":
    unittest.main()
