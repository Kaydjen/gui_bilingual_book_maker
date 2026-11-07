"""Quality safeguards: empty answers, paragraphs left untranslated, what gets translated, line breaks."""
import importlib.util
import os
import pickle
import tempfile
import unittest
import zipfile
from pathlib import Path

from bbm_gui import engine, estimate, flagrules, jobs, langs, runner

try:
    from . import epubs
except ImportError:  # run from inside the tests folder
    import epubs

MARKER = engine.FAILURE_MARKER
EMPTY_1 = "Retry attempt %d due to AttributeError: 'NoneType' object has no attribute "
EMPTY_2 = "'strip' (rotating key)"
FAILED = "[Translation failed for this paragraph]"
FRAME = " 40%|####      | {n}/20 [00:05<00:07,  1.00s/it]"


def empty_attempts(mon, upto=7):
    guards = []
    for n in range(1, upto + 1):
        guards.append(mon.feed("out", "line", EMPTY_1 % n))
        guards.append(mon.feed("out", "line", EMPTY_2))
    return guards


def give_up(mon, n):
    """The engine gives up on a paragraph, prints the failure and advances the bar."""
    guard = mon.feed("out", "line", FAILED)
    mon.feed("err", "frame", FRAME.format(n=n))
    return guard


class EmptyAnswerTest(unittest.TestCase):
    def test_an_empty_answer_is_content_and_never_quota(self):
        mon = runner.Monitor()
        guards = empty_attempts(mon)
        self.assertEqual(set(guards), {None})  # not even at attempt 5: the engine's own seven attempts decide
        self.assertEqual({e.kind for e in mon.events}, {"content"})
        self.assertTrue(all(e.empty for e in mon.events))
        self.assertFalse(mon.quota)
        self.assertFalse(mon.key_error)

    def test_real_engine_output_of_a_prohibited_paragraph(self):
        """Lines the engine printed for a paragraph that the model answered with nothing (PROHIBITED_CONTENT, six
        retries, then the English paragraph with the marker): never quota, never a key hop, counted as blocked."""
        lines = (Path(__file__).parent / "fixtures" / "empty_prohibited.txt").read_text(encoding="utf-8").splitlines()
        mon = runner.Monitor()
        guards = []
        for line in lines:
            guards.append(mon.feed("err" if "it]" in line else "out", "frame" if "it]" in line else "line", line))
        guards.append(mon.flush())
        self.assertEqual(set(guards), {None})
        self.assertEqual({e.kind for e in mon.events}, {"content"})
        self.assertTrue(all(e.empty for e in mon.events))
        self.assertEqual(len(mon.events), 6)
        self.assertFalse(mon.quota)
        self.assertFalse(mon.key_error)
        self.assertEqual((mon.blocked, mon.failed, mon.n), (1, 1, 2))

    def test_other_content_errors_keep_the_old_guard(self):
        mon = runner.Monitor()
        self.assertEqual(mon.feed("out", "line", "Retry attempt 5 due to ConnectError: boom (rotating key)"), "failed")
        self.assertFalse(mon.events[-1].empty)

    def test_blocked_text_is_empty_too(self):
        ev = runner.classify_block("Retry attempt 2 due to ClientError: 400 prompt was blocked (switching model)", 2)
        self.assertEqual((ev.kind, ev.empty), ("content", True))
        ev = runner.classify_block("Retry attempt 2 due to ValueError: Invalid batch: 3 of 5", 2)
        self.assertEqual((ev.kind, ev.empty), ("content", True))

    def test_a_real_quota_text_is_not_mistaken_for_empty(self):
        ev = runner.classify_block("Retry attempt 1 due to ClientError: 429 RESOURCE_EXHAUSTED. PerDay limit: 20 blocked", 1)
        self.assertEqual(ev.kind, "day")

    def test_scattered_failures_go_on_and_are_counted(self):
        mon = runner.Monitor()
        guards = []
        for n in range(1, 13):
            if n % 3 == 0:  # every third paragraph is blocked
                empty_attempts(mon)
                guards.append(give_up(mon, n))
            else:
                mon.feed("err", "frame", FRAME.format(n=n))
        self.assertEqual(set(guards), {None})
        self.assertEqual(mon.blocked, 4)
        self.assertEqual(mon.failed, 4)

    def test_a_streak_stops_the_run(self):
        mon = runner.Monitor()
        guards = []
        for n in range(1, runner.BLOCK_STREAK + 1):
            empty_attempts(mon)
            guards.append(give_up(mon, n))
        self.assertEqual(guards[:-1], [None] * (runner.BLOCK_STREAK - 1))
        self.assertEqual(guards[-1], "blocked")
        self.assertFalse(mon.quota)

    def test_a_good_paragraph_breaks_the_streak(self):
        mon = runner.Monitor()
        for n in range(1, runner.BLOCK_STREAK):
            empty_attempts(mon)
            give_up(mon, n)
        mon.feed("err", "frame", FRAME.format(n=runner.BLOCK_STREAK))  # translated normally
        empty_attempts(mon)
        self.assertIsNone(give_up(mon, runner.BLOCK_STREAK + 1))

    def test_a_recovered_retry_is_not_a_failure(self):
        mon = runner.Monitor()
        empty_attempts(mon, 2)
        mon.feed("err", "frame", FRAME.format(n=1))
        self.assertEqual(mon.blocked, 0)
        self.assertEqual(mon.feed("out", "line", FAILED), "failed")  # a later failure without empty answers: old rule

    def test_a_plain_failure_still_stops(self):
        mon = runner.Monitor()
        self.assertEqual(mon.feed("out", "line", FAILED), "failed")

    def test_chips(self):
        mon = runner.Monitor()
        self.assertEqual(runner.classify(0, True, False, "blocked", mon, False), ("stopped", "Blocked"))
        mon.failed = 3
        self.assertEqual(runner.classify(0, False, False, None, _saved(mon), True), ("finished", ""))  # counted from the checkpoint

    def test_blocked_never_hops(self):
        from bbm_gui import app

        self.assertNotIn("blocked", app.HOP_GUARDS)


def _saved(mon):
    mon.saved = "x.epub"
    return mon


def checkpoint_tool():
    path = Path(engine.HELPERS) / "checkpoint.py"
    spec = importlib.util.spec_from_file_location("checkpoint_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CheckpointCountTest(unittest.TestCase):
    def setUp(self):
        self.tool = checkpoint_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "c.bin")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, items):
        with open(self.path, "wb") as f:
            pickle.dump({"translations": items, "job_ids": list(range(len(items))), "run_fingerprint": "x"}, f)

    def test_marker_and_empty_count_as_failed(self):
        self.write(["a", MARKER, "b", "", "  ", "c"])
        res = self.tool.inspect(self.path, MARKER)
        self.assertEqual((res["total"], res["failed"], res["first_failed"]), (6, 3, 1))

    def test_clean_checkpoint(self):
        self.write(["a", "b"])
        self.assertEqual(self.tool.inspect(self.path, MARKER)["failed"], 0)

    def test_repair_cuts_at_the_first_failure(self):
        self.write(["a", MARKER, "b", MARKER])
        res = self.tool.repair(self.path, MARKER, True)
        self.assertEqual((res["before"], res["after"]), (4, 1))
        self.assertEqual(self.tool.inspect(self.path, MARKER)["failed"], 0)

    def test_accepted_failures_are_passed(self):
        self.write(["a", MARKER, "b", MARKER, "c"])
        res = self.tool.repair(self.path, MARKER, True, accept=2)  # the first two were already tried again
        self.assertEqual(res["after"], 3)
        self.assertEqual(self.tool.inspect(self.path, MARKER)["failed"], 1)  # the one at index 1 stays, as a known failure


def build(path, pages):
    return epubs.write_epub(str(path), pages)


class TagsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rich = epubs.write_rich(os.path.join(self.tmp.name, "rich.epub"))
        self.tags = estimate.tag_list(flagrules.DEFAULT_TAGS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_tags_cover_the_text_blocks(self):
        counts, left = estimate.scan(self.rich, self.tags)
        # nav entry + h1, p, p, h2, li, p(in li), li(Apples), p(in blockquote), blockquote, th, th, td, p(in td),
        # figcaption, dt, dd: nested tags are not counted twice; "1234" is special text
        self.assertEqual(sum(counts), 17)
        self.assertEqual(left, 2)  # the division text and "Fruits" next to a nested list
        counts_p, left_p = estimate.scan(self.rich, ("p",))
        self.assertEqual(sum(counts_p), 5)
        self.assertGreater(left_p, left)

    def test_nested_tags_are_not_translated_twice(self):
        html = ("<ul><li><p>one</p></li></ul><blockquote><p>two</p></blockquote>"
                "<table><tr><td><p>three</p></td><td>four</td></tr></table>")
        self.assertEqual(estimate.count_html(html, self.tags), 4)
        self.assertEqual(estimate.uncovered_html(html, self.tags), 0)

    def test_quiet_when_everything_is_covered(self):
        self.assertEqual(estimate.uncovered_html("<h1>A</h1><p>B</p><p><i>C</i></p>", self.tags), 0)
        line = estimate.plan_line(10, 60, None, 0)
        self.assertNotIn("left", line)
        self.assertIn("3 blocks left as is", estimate.plan_line(10, 60, None, 3))

    def test_uncovered_counts_blocks_not_words(self):
        html = "<div>Words <b>bold</b> and <i>more</i> words</div><div>Other</div><head><title>T</title></head>"
        self.assertEqual(estimate.uncovered_html(html, self.tags), 2)

    def test_excluded_and_special_text_are_not_uncovered(self):
        html = "<div>12</div><div>...</div><div><sup>1</sup></div><script>var a;</script>"
        self.assertEqual(estimate.uncovered_html(html, self.tags), 0)

    def test_navigation_document_listing(self):
        self.assertEqual(estimate.nav_files(self.rich), ["nav.xhtml"])
        with_nav = estimate.scan(self.rich, self.tags, with_nav=True)[0]
        without = estimate.scan(self.rich, self.tags, with_nav=False)[0]
        self.assertEqual(sum(with_nav) - sum(without), 1)

    def test_tag_list(self):
        self.assertEqual(estimate.tag_list(""), ("p",))
        self.assertEqual(estimate.tag_list(None, ("sup", "code")), ("sup", "code"))
        self.assertEqual(estimate.tag_list(" p, h1 ,"), ("p", "h1"))


class BreakTest(unittest.TestCase):
    def test_every_break_gets_a_space(self):
        src = b"<p>red,<br/>violets<br>blue<br />x</p>"
        self.assertEqual(jobs.space_after_breaks(src), b"<p>red,<br/> violets<br> blue<br /> x</p>")

    def test_idempotent_and_pre_untouched(self):
        src = b"<p>a<br/>b</p><pre>l1<br/>l2</pre><p>c<br/>\nd</p>"
        once = jobs.space_after_breaks(src)
        self.assertEqual(once, b"<p>a<br/> b</p><pre>l1<br/>l2</pre><p>c<br/>\nd</p>")
        self.assertEqual(jobs.space_after_breaks(once), once)

    def test_other_tags_starting_with_br_are_left(self):
        self.assertEqual(jobs.space_after_breaks(b"<p><brand>x</brand></p>"), b"<p><brand>x</brand></p>")


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("BBM_GUI_DATA")
        os.environ["BBM_GUI_DATA"] = os.path.join(self.tmp.name, "data")
        self.book = Path(self.tmp.name) / "Verse.epub"
        build(self.book, ["<p>Roses are red,<br/>violets are blue.</p>", "<p>Plain</p>"])
        self.original = self.book.read_bytes()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("BBM_GUI_DATA", None)
        else:
            os.environ["BBM_GUI_DATA"] = self.old
        self.tmp.cleanup()

    def job(self):
        return jobs.Job(self.book, "single", langs.resolve("ru"))

    def page(self, path, name="OEBPS/ch0.xhtml"):
        with zipfile.ZipFile(path) as z:
            return z.read(name)

    def test_copy_is_fixed_and_the_original_is_not(self):
        job = self.job()
        job.prepare()
        self.assertIn(b"<br/> violets", self.page(job.copy))
        self.assertEqual(self.book.read_bytes(), self.original)
        self.assertNotIn(b"<br/> violets", self.page(self.book))

    def test_copy_stays_a_valid_epub(self):
        job = self.job()
        job.prepare()
        with zipfile.ZipFile(self.book) as a, zipfile.ZipFile(job.copy) as b:
            self.assertEqual([i.filename for i in a.infolist()], [i.filename for i in b.infolist()])
            self.assertIsNone(b.testzip())
            first = b.infolist()[0]
            self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
            for name in a.namelist():
                if name != "OEBPS/ch0.xhtml":
                    self.assertEqual(a.read(name), b.read(name))
            for i, j in zip(a.infolist(), b.infolist()):
                self.assertEqual(i.compress_type, j.compress_type)
        self.assertEqual(estimate.chapter_counts(str(job.copy)), [1, 1])

    def test_done_once(self):
        job = self.job()
        job.prepare()
        first = job.copy.read_bytes()
        mtime = job.copy.stat().st_mtime_ns
        job.prepare()
        self.assertEqual(job.copy.read_bytes(), first)
        self.assertEqual(job.copy.stat().st_mtime_ns, mtime)  # not even rewritten

    def test_a_job_with_a_checkpoint_is_never_changed(self):
        job = self.job()
        job.dir.mkdir(parents=True)
        import shutil

        shutil.copy2(self.book, job.copy)  # a copy made before the fix existed
        job.bin_path.write_bytes(b"checkpoint")
        job.prepare()
        self.assertEqual(job.copy.read_bytes(), self.original)
        job.prepare()
        self.assertEqual(job.copy.read_bytes(), self.original)
        job.bin_path.unlink()  # restart: the copy is raw and has no progress to protect
        job.prepare()
        self.assertIn(b"<br/> violets", self.page(job.copy))

    def test_a_changed_source_is_copied_again(self):
        job = self.job()
        job.prepare()
        build(self.book, ["<p>New<br/>text</p>"])
        job.prepare()
        self.assertIn(b"<br/> text", self.page(job.copy))

    def test_other_formats_are_copied_as_they_are(self):
        txt = Path(self.tmp.name) / "a.txt"
        txt.write_bytes(b"one<br/>two")
        job = jobs.Job(txt, "single", langs.resolve("ru"))
        job.prepare()
        self.assertEqual(job.copy.read_bytes(), b"one<br/>two")

    def test_tags_are_recorded_per_job(self):
        job = self.job()
        job.prepare()
        self.assertIsNone(job.recorded_tags())
        job.record_tags("p,h1")
        self.assertEqual(job.recorded_tags(), "p,h1")
        job.prepare()
        self.assertEqual(job.recorded_tags(), "p,h1")  # survives a prepare


if __name__ == "__main__":
    unittest.main()
