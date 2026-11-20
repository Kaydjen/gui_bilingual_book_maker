"""Sample `Next 50`: the facade shim (the sample log is kept and grows by the next 50 blocks, nothing goes anywhere but the fake
server), the view-model (rows append, a cancel keeps what is done, a new Sample clears) and the pill of the Sample tab
(shown, hidden at the end of the chapter, disabled while a job runs)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests import test_translate_vm as ttv  # noqa: E402
from tests import translatedemo as demo  # noqa: E402
from tests import translatescenes as ts  # noqa: E402
from tests.core_support import KEYS, CoreCase, read_records  # noqa: E402
from tests.translatescenes import py  # noqa: E402

VM = "tests.shellfactory:make"


class Ctx:
    def emit(self, item):
        pass


class SampleShim(CoreCase):
    chapters = 2
    paras = 120
    per_request = 10

    def sample(self, blocks, keep):
        from novelgui.facade import run as frun
        cfg = frun.RunConfig(keys=KEYS[:1], models=["gemini-3.1-flash-lite"], pace=120, base_url=self.api.base_url)
        handle = frun.RunHandle()
        return frun.sample_task(Ctx(), handle, self.series.path, self.book, 1, blocks, cfg, keep)

    def log(self):
        files = list((self.series.path / "samples").rglob("*.jsonl"))
        self.assertEqual(len(files), 1)
        return read_records(files[0])

    def test_next_50_keeps_the_first_50_and_adds_the_next_50(self):
        self.sample(50, False)
        first = self.log()
        self.assertEqual([r["i"] for r in first], list(range(50)))
        requests = len(self.api.log)
        self.assertEqual(requests, 5)
        self.sample(50, True)
        second = self.log()
        self.assertEqual([r["i"] for r in second], list(range(100)))
        self.assertEqual(second[:50], first, "the first 50 are the very same records: nothing was translated again")
        self.assertEqual(len(self.api.log) - requests, 5, "only the new blocks were asked for")
        self.assertEqual(list((self.series.path / "chapters").rglob("*")), [], "a sample never writes to chapters/")

    def test_the_end_of_the_chapter_stops_it(self):
        self.sample(50, False)
        self.sample(50, True)
        self.sample(100, True)
        self.assertEqual(len(self.log()), 120)
        self.sample(120, True)
        self.assertEqual(len(self.log()), 120, "nothing left to add")

    def test_a_plain_sample_clears_as_before(self):
        self.sample(50, False)
        self.sample(50, True)
        self.sample(50, False)
        self.assertEqual(len(self.log()), 50)

    def test_only_the_fake_server_is_used(self):
        self.sample(50, False)
        self.sample(50, True)
        self.assertTrue(all(g["status"] in (200, 429) for g in self.api.log))
        self.assertTrue(self.api.base_url.startswith("http://127.0.0.1"))


class SampleVm(ttv.Base):
    specs = [demo.knights(chapters=10, paras=120)]
    select = "2651-2654"

    def write(self, count, number=2651):
        from novelcore import Series
        series = Series.open(self.path)
        with series.open_book("Book 1") as b:
            ch = b.chapters[demo.position(number)]
            recs = [{"i": blk.index, "src_sha": blk.sha, "status": "ok", "text": "T%d" % blk.index, "at": 1.0, "model": "m",
                     "flags": []} for blk in b.blocks(ch)[:count]]
            series.sample_log("Book 1", ch).append(recs)

    def finish(self):
        self.rc._done(self.rc.run, {"stopped": False})
        self.assertTrue(ttv.pump(lambda: not self.vm.sampleResult["pending"]))

    def first_sample(self):
        self.vm.sample()
        self.assertTrue(ttv.pump(lambda: self.rc.run is not None))
        self.write(50)
        self.finish()

    def test_next_50_appends_and_keeps_the_rows_shown(self):
        vm = self.vm
        self.first_sample()
        r = vm.sampleResult
        self.assertEqual(len(r["rows"]), 50)
        self.assertTrue(r["more"] and r["nextEnabled"])
        first = list(r["rows"])
        with mock.patch("novelgui.facade.run.sample_task") as task:
            vm.sampleNext()
            self.assertTrue(ttv.pump(lambda: self.rc.run is not None))
            self.started[-1].fn(None)
        args = task.call_args.args
        self.assertEqual((args[5], args[7]), (50, True), "from 50 blocks on, keeping the log")
        self.assertTrue(vm.sampleResult["pending"])
        self.assertFalse(vm.sampleResult["more"], "no second press while it runs")
        self.assertEqual(vm.sampleResult["rows"], first, "the rows already shown stay while the next ones are made")
        self.write(100)
        self.finish()
        r = vm.sampleResult
        self.assertEqual(len(r["rows"]), 100)
        self.assertEqual(r["rows"][:50], first)
        self.assertEqual(r["sub"], "chapter 2651 · first 100 blocks")
        self.assertTrue(r["more"])

    def test_a_cancel_keeps_what_is_done(self):
        vm = self.vm
        self.first_sample()
        vm.sampleNext()
        self.assertTrue(ttv.pump(lambda: self.rc.run is not None))
        self.write(70)
        self.finish()
        r = vm.sampleResult
        self.assertEqual(len(r["rows"]), 70)
        self.assertEqual(vm._samples[self.path]["n"], 70, "the next press goes on from what is done")
        self.assertTrue(r["more"])

    def test_the_pill_is_gone_at_the_end_of_the_chapter(self):
        vm = self.vm
        self.first_sample()
        for done in (100, 1000):
            vm.sampleNext()
            self.assertTrue(ttv.pump(lambda: self.rc.run is not None))
            self.write(done)
            self.finish()
        r = vm.sampleResult
        self.assertEqual(len(r["rows"]), vm._samples[self.path]["total"], "every block of the chapter is shown")
        self.assertFalse(r["more"])

    def test_a_new_sample_clears_the_old_one(self):
        vm = self.vm
        self.first_sample()
        vm.sampleNext()
        self.assertTrue(ttv.pump(lambda: self.rc.run is not None))
        self.write(100)
        self.finish()
        with mock.patch("novelgui.facade.run.sample_task") as task:
            vm.sample()
            self.assertTrue(ttv.pump(lambda: self.rc.run is not None))
            self.started[-1].fn(None)
        self.assertEqual((task.call_args.args[5], task.call_args.args[7]), (50, False))
        self.assertEqual(vm._samples[self.path]["n"], 50)

    def test_next_is_refused_while_a_job_runs(self):
        vm = self.vm
        self.first_sample()
        self.begin()
        self.assertFalse(vm.sampleResult["nextEnabled"])
        self.assertIn("one at a time", vm.sampleResult["nextTip"])
        run = self.rc.run
        vm.sampleNext()
        self.assertIs(self.rc.run, run, "nothing was started")


def pill(r):
    return r.item("sampleNext")


def sample_scene(paras, *more):
    spec = demo.knights(chapters=10, paras=paras)
    return (ts.data(spec),
            ts.base(py("tr_sample_start"), py("tr_sample_write", 2651, ["T%d" % i for i in range(50)]), py("tr_sample_end"),
                    *more, text="2651-2654"))


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class SamplePill(unittest.TestCase):
    def test_the_pill_is_shown_after_a_finished_sample_with_its_tip(self):
        d, a = sample_scene(120)
        r = qh.scenario("ShellScene", d, vm=VM, actions=a, tag="next_shown")
        self.assertTrue(pill(r)["visible"])
        self.assertEqual(pill(r)["text"], "Next 50")
        self.assertEqual(pill(r)["kind"], "flat")
        self.assertEqual(r.item("sampleList")["count"], 50)

    def test_the_pill_is_hidden_when_the_chapter_has_no_more_blocks(self):
        d, a = sample_scene(30)
        r = qh.scenario("ShellScene", d, vm=VM, actions=a, tag="next_end")
        self.assertFalse(pill(r)["visible"])

    def test_the_pill_is_disabled_while_a_job_runs_and_says_why(self):
        d, a = sample_scene(120, py("tr_begin", list(range(1, 5)), "Knights", "Book 1"), py("tr_progress", 2651, 1))
        acts = a + [{"op": "moveTo", "name": "sampleNext"}, {"op": "wait", "ms": 1000}, {"op": "dump", "name": "tip"}]
        r = qh.scenario("ShellScene", d, vm=VM, actions=acts, tag="next_job")
        self.assertTrue(pill(r)["visible"])
        self.assertEqual(pill(r)["kind"], "off")
        self.assertIn("one at a time", r.after["tip"]["tip"]["text"])

    def test_a_click_adds_50_and_the_list_stays_where_it_was(self):
        d, a = sample_scene(120)
        acts = a + [{"op": "wheel", "name": "sampleList", "dy": -240}, {"op": "wait", "ms": 600}, {"op": "dump", "name": "before"},
                    {"op": "click", "name": "sampleNext"}, {"op": "wait", "ms": 600},
                    py("tr_sample_write", 2651, ["T%d" % i for i in range(100)]), py("tr_sample_end"), {"op": "wait", "ms": 600}]
        r = qh.scenario("ShellScene", d, vm=VM, actions=acts, tag="next_click")
        self.assertEqual(r.item("sampleList")["count"], 100)
        before = r.after["before"]["sampleList"]["contentY"]
        self.assertGreater(before, 0)
        self.assertAlmostEqual(r.item("sampleList")["contentY"], before, delta=1)


if __name__ == "__main__":
    unittest.main()
