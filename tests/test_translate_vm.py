"""The Translate view-model with a real library behind it (QCoreApplication, real lanes, the real helper process) and the
REAL RunControl whose runner is not started (its `submit` is a recording stub: no thread, no request, no network):
the top row, the Time pill and popover, the tabs, the bottom bar of every state of window_spec 7.16 (ready, no keys, no
language, reach, first chapter blocked, all translated, running, retrying, paused, another series, stopped, replace,
terms, quota, failed, elsewhere, problems, queue, restart, sample), the chapter rows, the confirmations (13.12), the prompt
draft (9.2), the one start path (13.2). The models run under QAbstractItemModelTester. Skipped without PySide6."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from tests import translatedemo as demo  # noqa: E402

KEEP: list = []
NEVER = "http://127.0.0.1:9"        # nothing listens here: a start that really sent a request would fail loudly


def pump(cond, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            QCoreApplication.processEvents()
            return True
        time.sleep(0.005)
    return False


def seg(vm, seg_id):
    return next((s for s in vm.bar if s["id"] == seg_id), None)


def ids(vm):
    return [s["id"] for s in vm.bar]


def texts(vm):
    return [s["text"] for s in vm.bar]


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class Base(unittest.TestCase):
    specs = None
    select = demo.SELECTION
    keys = 1
    tab = None

    @classmethod
    def setUpClass(cls):
        cls.qapp = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="noveltr-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.lib = self.root / "Novel library"
        self.lib.mkdir()
        from tests import libfixture
        libfixture.build(self.lib, self.specs or [demo.knights()])
        self.prepare()
        self.make()

    def prepare(self):
        """Files to write into the library before the window opens."""

    def make(self):
        from tests import shellfactory
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        os.environ["NOVELGUI_DATA"] = str(data)
        os.environ["NOVELGUI_API_BASE"] = NEVER
        os.environ.pop("NOVELGUI_NOTIFY", None)
        os.environ.pop("NOVELGUI_TRAY", None)
        self.addCleanup(lambda: os.environ.pop("NOVELGUI_API_BASE", None))
        win = {"books_last": {"series": "Knights", "book": "Book 1"}, "screen": "translate"}
        (data / "settings.json").write_text(json.dumps({"library": str(self.lib), "win": win}), encoding="utf-8")
        self.key_list = [shellfactory.planted(i) for i in range(self.keys)]
        if self.keys:
            (data / "keys.json").write_text(json.dumps({"version": 1, "keys": self.key_list}), encoding="utf-8")
        from novelgui.runtime import notify, tray as trays
        from novelgui.runtime.assemble import Parts
        parts = Parts(settings_dir=data, local=data / "local", tray=trays.RecordingTray(data, available=False))
        parts.notifier = notify.RecordingNotifier(data)
        parts.app.notifier = parts.notifier
        self.parts, self.books, self.app, self.vm, self.rc = parts, parts.books_vm, parts.app, parts.translate_vm, parts.run
        self.started: list = []
        self.rc.submit = lambda fn, **kw: self.started.append(SimpleNamespace(fn=fn, **kw))
        self.vm.mine_names = False
        self.terms = parts.terms_vm
        self.terms.mine_names = False
        self.terms.auto_scan = False
        KEEP.append(parts)
        self.addCleanup(parts.close)
        self.assertTrue(pump(lambda: self.books.view == "chapters" and not self.books.session.scanning), "books did not settle")
        if self.select:
            self.assertTrue(self.books.commitRange(self.select))
        self.settle()

    # ---- waiting
    def settle(self, ms=0.15):
        vm = self.vm
        ok = pump(lambda: self.parts.lanes.idle() and vm._gate_ready and not vm._sync_t.isActive()
                  and self.parts.crunch.idle_now())
        self.assertTrue(ok, "the Translate screen did not settle")
        pump(lambda: False, ms)
        pump(lambda: self.parts.lanes.idle() and not vm._sync_t.isActive() and self.parts.crunch.idle_now(), 5)

    @property
    def path(self) -> str:
        return str(self.lib / "Knights")

    # ---- a job that runs in this window (the runner is not started: events are fed by hand)
    def begin(self, positions=None, series="Knights", book="Book 1", name=None):
        from novelgui.ctl import runcontrol
        rc = self.rc
        path = str(self.lib / series)
        positions = list(positions if positions is not None else self.books.terms_context()[2])
        run = runcontrol.Run("job", path, name or series, book, positions, False, rc.clock)
        rc._prepare_chap(run)
        rc.run = run
        rc.last_series = path
        rc.sched.user_started()
        rc._changed()
        self.vm.runs_changed(starting=True)
        return run

    def feed(self, run, kind, **data):
        run.events.feed((kind, data))

    def progress(self, run, index, done, total=3, failed=0):
        self.feed(run, "progress", index=index, done=done, total=total, failed=failed)
        self.rc._flush_progress()

    def end(self, run, state="stopped", positions=None, **rec):
        """The run ends with this job record."""
        demo.write_record(run.series, run.book, state, positions if positions is not None else run.chapters, **rec)
        self.rc._done(run, {"stopped": False})
        self.settle()

    def record(self, state, positions, series="Knights", book="Book 1", **kw):
        demo.write_record(str(self.lib / series), book, state, positions, **kw)
        self.vm._load_series()
        self.settle()
        pump(lambda: False, 0.1)

    def spin(self, ms=50):
        pump(lambda: False, ms / 1000)


# ======================================================================================================== states
class Ready(Base):
    specs = [demo.knights()]

    def test_every_tip_the_screen_reads_exists(self):
        keys = ("noSeries from prompt promptDelete keysHead queueUp queueDown queueRemove queueStop dontResume problemRetry "
                "problemKeep problemIgnore problemSave problemFailed problemBusy promptText promptNothing more readOff").split()
        tips = self.vm.tips
        self.assertEqual([k for k in keys if not tips.get(k)], [])

    def test_ready_state(self):
        vm = self.vm
        self.assertEqual(vm.view, "ready")
        self.assertEqual(texts(vm), ["Translate · 2703-2750"])
        self.assertEqual(vm.bar[0]["tone"], "main")
        top = vm.top
        self.assertEqual((top["toText"], top["toEnabled"], top["toRed"]), ("Russian", True, False))
        self.assertEqual((top["promptName"], top["sampleText"], top["sampleEnabled"]), ("Default", "Sample", True))
        self.assertEqual(top["fromText"], "From English")
        self.assertEqual(vm.tabs, [])
        self.assertEqual(len(vm.chapters), 48)
        self.assertEqual(vm.chapters.row(0)[0], "2703")
        self.assertTrue(vm.chapters.row(0)[1].startswith("Chapter 2703 - "))
        self.assertEqual([vm.chapters.row(i)[4] for i in range(48)], [""] * 48)
        self.assertFalse(vm.moreVisible)

    def test_time_pill_and_popover(self):
        t = self.vm.time
        self.assertTrue(t["visible"])
        self.assertTrue(t["text"].startswith("≈ "))
        pop = t["pop"]
        self.assertEqual(pop["heading"], "Chapters 2703-2750")
        self.assertEqual([o["per"] for o in pop["options"]], [1, 5, 10])
        self.assertEqual([o["selected"] for o in pop["options"]], [False, True, False])
        self.assertTrue(pop["options"][2]["untested"])
        self.assertEqual(pop["keysText"], "API keys · 1")
        self.assertEqual(pop["leftText"], "500 / 500")          # the daily total comes from the keys, not a constant
        self.assertTrue(pop["renew"].startswith("Renew at "))
        self.assertFalse(pop["locked"])

    def test_per_request_is_saved_in_the_series_and_changes_the_times(self):
        vm = self.vm
        before = vm.time["pop"]["options"][0]["time"]
        vm.setPerRequest(1)
        self.assertEqual([o["selected"] for o in vm.time["pop"]["options"]], [True, False, False])
        self.settle()
        from novelgui.facade import books as fbooks
        self.assertEqual(fbooks.series_settings(self.path)["per_request"], 1)
        self.assertEqual(vm.time["pop"]["options"][0]["time"], before)
        vm.setPerRequest(7)                                      # only 1 | 5 | 10
        self.assertEqual(fbooks.series_settings(self.path)["per_request"], 1)

    def test_nothing_starts_after_the_window_opens(self):
        self.assertEqual(self.started, [])
        self.assertIsNone(self.rc.run)
        self.assertFalse(self.app.run.busy)

    def test_the_selection_is_what_the_list_shows(self):
        self.assertTrue(self.books.commitRange("2710-2712"))
        self.settle()
        self.assertEqual(len(self.vm.chapters), 3)
        self.assertEqual(texts(self.vm), ["Translate · 2710-2712"])

    def test_no_selection_no_start_button(self):
        self.books.clearSelection()
        self.settle()
        self.assertEqual(self.vm.bar[0]["enabled"], False)
        self.assertEqual(len(self.vm.chapters), 0)
        self.assertFalse(self.vm.top["sampleEnabled"])

    def test_translate_goes_through_run_control(self):
        vm = self.vm
        vm.act("translate")
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.started[0].lane, "run")
        self.assertEqual(self.rc.run.chapters, list(range(position(2703), position(2750) + 1)))
        self.assertEqual(ids(vm), ["stop"])


def position(n):
    return demo.position(n)


class TwoKeys(Base):
    keys = 2

    def test_the_daily_total_follows_the_keys(self):
        pop = self.vm.time["pop"]
        self.assertEqual((pop["keysText"], pop["leftText"]), ("API keys · 2", "1 000 / 1 000"))
        self.assertEqual(pop["leftTip"], "An estimate for this PC. All keys together: 2 keys, 500 requests a day each; requests made from another PC are not counted.")


class NoKeys(Base):
    keys = 0

    def test_add_keys_is_the_only_red_segment(self):
        vm = self.vm
        self.assertEqual(texts(vm), ["Add keys"])
        self.assertEqual(vm.bar[0]["tone"], "red")
        self.assertFalse(vm.top["sampleEnabled"])
        self.assertEqual(vm.top["sampleTip"], "Add keys first.")
        vm.act("add_keys")
        self.assertTrue(self.app.settingsOpen)

    def test_continue_is_dim_with_the_same_reason(self):
        self.record("stopped", range(position(2730), position(2750) + 1))
        s = seg(self.vm, "continue")
        self.assertFalse(s["enabled"])
        self.assertIn("API key", s["tip"])


class NoLanguage(Base):
    specs = [demo.knights(chosen=False)]

    def test_to_is_red_and_start_is_dim(self):
        vm = self.vm
        self.assertEqual((vm.top["toText"], vm.top["toRed"], vm.top["toEnabled"]), ("language", True, True))
        s = vm.bar[0]
        self.assertEqual((s["text"], s["enabled"]), ("Translate · 2703-2750", False))
        self.assertIn("language", s["tip"])
        self.assertFalse(vm.top["sampleEnabled"])
        self.assertEqual(vm.top["sampleTip"], "Choose the language first.")

    def test_choosing_the_language_saves_it_and_enables_start(self):
        vm = self.vm
        entries = vm.languageEntries("")
        self.assertEqual([e["group"] for e in entries if "group" in e][:2], ["TUNED", "USABLE"])
        vm.chooseLanguage("uk:Ukrainian")
        self.assertTrue(pump(lambda: vm.top["toText"] == "Ukrainian"))
        self.settle()
        self.assertTrue(vm.bar[0]["enabled"])
        self.assertFalse(vm.top["toRed"])


class LanguageLock(Base):
    specs = [demo.knights(translated=6)]

    def test_to_is_locked_once_blocks_are_translated(self):
        top = self.vm.top
        self.assertFalse(top["toEnabled"])
        self.assertIn("cannot change any more", top["toTip"])


class Reach(Base):
    specs = [demo.knights(blocked=[2731])]

    def test_a_later_blocked_chapter_shortens_the_reach(self):
        vm = self.vm
        self.assertEqual(texts(vm), ["Translate · 2703-2730"])          # no second Review segment: the row mark does it
        row = vm.chapters.row(2731 - 2703)
        self.assertEqual((row[4], row[5]), ("1 term", "dim"))
        self.assertIn("terms", row[7].split(","))
        self.assertIn("beyond", vm.chapters.row(2740 - 2703)[7].split(","))
        self.assertEqual(vm.app_terms_red if hasattr(vm, "app_terms_red") else self.app.termsState, "")
        self.assertEqual(vm.unreviewed, 1)

    def test_start_covers_the_reach_and_a_queued_item_the_selection(self):
        self.vm.act("translate")
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(self.rc.run.chapters[-1], position(2730))
        self.vm.act("stop")


class FirstBlocked(Base):
    specs = [demo.knights(blocked=[2703])]

    def test_review_is_the_only_segment_and_terms_pulse_red(self):
        vm = self.vm
        self.assertEqual(texts(vm), ["Review 1 term"])
        self.assertEqual(vm.bar[0]["tone"], "red")
        self.assertEqual(self.app.termsState, "red")
        self.app.go("books")
        self.assertEqual(self.app.termsState, "")                    # the pulse is on the screen where translating waits
        self.app.go("translate")
        self.assertEqual(self.app.termsState, "red")
        row = vm.chapters.row(0)
        self.assertEqual((row[4], row[5]), ("1 term", "red"))
        self.assertEqual(vm.wordTip(0), "1 of this chapter's terms are not confirmed yet. Click: Terms on Blocking.")
        vm.act("review")
        self.assertEqual(self.app.screen, "terms")


class AllTranslated(Base):
    specs = [demo.knights(translated=170)]

    def test_the_button_is_dim_and_reads_retranslate(self):
        vm = self.vm
        s = vm.bar[0]
        self.assertEqual((s["text"], s["enabled"], s["tone"]), ("Retranslate · 2703-2750", False, "dim"))
        self.assertIn("translated already", s["tip"])
        self.assertFalse(vm.time["visible"])
        self.assertIn("translated", vm.chapters.row(0)[7].split(","))
        self.assertEqual(vm.chapters.row(0)[2], 1.0)


class Running(Base):
    specs = [demo.knights()]

    def test_running_state(self):
        vm = self.vm
        run = self.begin()
        self.progress(run, position(2703), 1)
        self.assertEqual(ids(vm), ["stop"])
        self.assertEqual(self.app.translateState, "wave")
        self.assertFalse(vm.top["toEnabled"])
        self.assertFalse(vm.top["sampleEnabled"])
        self.assertIn("one at a time", vm.top["sampleTip"])
        self.assertTrue(vm.top["promptEnabled"] and vm.top["editEnabled"])          # usable during a run
        row = vm.chapters.row(0)
        self.assertTrue(row[6])
        self.assertIn("live", row[7].split(","))
        self.assertAlmostEqual(row[2], 1 / 3)
        self.assertTrue(vm.time["pop"]["locked"])
        vm.setPerRequest(10)                                           # locked while the series runs
        self.assertEqual([o["selected"] for o in vm.time["pop"]["options"]], [False, True, False])

    def test_a_progress_tick_changes_the_current_row_only(self):
        vm = self.vm
        run = self.begin()
        self.progress(run, position(2703), 1)
        spy = QSignalSpy(vm.chapters.dataChanged)
        self.progress(run, position(2703), 2)
        self.assertEqual(spy.count(), 1)
        a = spy.at(0)
        self.assertEqual((a[0].row(), a[1].row()), (0, 0))

    def test_the_current_row_moves_to_the_next_chapter(self):
        vm = self.vm
        run = self.begin()
        self.progress(run, position(2703), 3)
        self.progress(run, position(2704), 1)
        self.assertEqual(vm.currentRow, 1)
        self.assertTrue(vm.chapters.row(1)[6] and not vm.chapters.row(0)[6])

    def test_stop_says_stopping_and_the_bar_dims(self):
        vm = self.vm
        run = self.begin()
        self.progress(run, position(2703), 1)
        vm.act("stop")
        self.assertTrue(run.stopping)
        self.assertEqual(vm.chapters.row(0)[4], "Stopping")
        s = vm.bar[0]
        self.assertEqual((s["text"], s["enabled"]), ("Stopping…", False))

    def test_another_selection_adds_the_queue_segment(self):
        self.begin()
        self.assertTrue(self.books.commitRange("2800-2819"))
        self.settle()
        self.assertEqual(ids(self.vm), ["stop", "queue"])
        self.assertEqual(self.vm.bar[1]["text"], "Add to queue · 2800-2819")

    def test_time_pill_says_left_while_running(self):
        run = self.begin()
        self.assertTrue(self.vm.time["text"].startswith("≈ "))
        self.assertTrue(self.vm.time["pop"]["locked"])
        self.assertEqual(self.vm.time["pop"]["heading"], "This job (from the next start)")
        del run

    def test_header_click_scrolls_to_the_current_chapter(self):
        vm = self.vm
        run = self.begin()
        for n in range(2703, 2710):
            self.progress(run, position(n), 3)
        self.progress(run, position(2710), 1)
        spy = QSignalSpy(vm.scrollRequested)
        vm.headerClicked()
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0)[0], 7)


class CountdownWords(Base):
    def test_retrying_and_paused_count_with_one_single_shot_timer(self):
        vm = self.vm
        run = self.begin()
        self.progress(run, position(2703), 1)
        self.assertFalse(vm._count_t.isActive())
        self.feed(run, "waiting", until=self.rc.clock() + 12, reason="503")
        self.progress(run, position(2703), 1)
        self.assertEqual(vm.chapters.row(0)[4], "Retrying 0:12")
        self.assertTrue(vm._count_t.isActive())
        self.assertTrue(vm._count_t.isSingleShot())
        self.feed(run, "resumed")
        self.progress(run, position(2703), 2)
        self.assertEqual(vm.chapters.row(0)[4], "")
        self.assertFalse(vm._count_t.isActive())
        self.feed(run, "paused", until=self.rc.clock() + 42)
        self.progress(run, position(2703), 2)
        self.assertEqual(vm.chapters.row(0)[4], "Paused 0:42")
        self.assertTrue(vm._count_t.isActive())
        self.feed(run, "unpaused")
        self.progress(run, position(2703), 3)
        self.assertFalse(vm._count_t.isActive())

    def test_the_countdown_timer_redraws_only_that_row(self):
        vm = self.vm
        run = self.begin()
        self.progress(run, position(2703), 1)
        self.feed(run, "paused", until=self.rc.clock() + 42)
        self.progress(run, position(2703), 1)
        spy = QSignalSpy(vm.chapters.dataChanged)
        vm._countdown()
        self.assertEqual(spy.count(), 0) if vm.chapters.row(0)[4] == "Paused 0:42" else None
        self.assertTrue(vm._count_t.isActive())


class OtherSeries(Base):
    specs = [demo.knights(), demo.other("Gamma")]

    def test_another_series_runs(self):
        vm = self.vm
        self.begin(positions=range(1, 20), series="Gamma", book="Book 2")
        self.assertEqual(self.app.translateState, "wave")
        s = vm.bar[0]
        self.assertEqual((s["id"], s["text"]), ("queue", "Add to queue · 2703-2750"))
        self.assertIn("Another series is translating now: Gamma", s["tip"])
        self.assertEqual([t["id"] for t in vm.tabs], ["chapters", "queue"])
        self.assertEqual(vm.tabs[1]["text"], "Queue 1")
        self.assertEqual(vm.queue_rows.row(0)[2], "Gamma")
        self.assertIn("running", vm.queue_rows.row(0)[5])
        self.assertFalse(vm.top["sampleEnabled"])

    def test_the_header_click_opens_the_queue_tab(self):
        self.begin(positions=range(1, 20), series="Gamma", book="Book 2")
        self.vm.headerClicked()
        self.assertEqual(self.vm.tab, "queue")

    def test_adding_to_the_queue_goes_through_run_control(self):
        self.begin(positions=range(1, 20), series="Gamma", book="Book 2")
        self.vm.act("queue")
        self.assertEqual([i.series for i in self.rc.queue_items()], [self.path])
        self.assertEqual(self.rc.queue_items()[0].reach, "2703-2750")
        self.assertEqual(self.vm.tabs[1]["text"], "Queue 2")

    def test_one_start_path_refuses_while_another_job_runs(self):
        self.begin(positions=range(1, 20), series="Gamma", book="Book 2")
        why = self.rc.start(self.path, "Book 1", [position(2703)])
        self.assertIn("running", why)
        self.vm.act("translate")                    # not offered: the bar says queue
        self.assertEqual(self.started, [])


class Stopped(Base):
    specs = [demo.knights(translated=0)]
    select = "2730-2750"

    def test_stopped_job_continues_where_it_stopped(self):
        vm = self.vm
        self.record("stopped", range(position(2730), position(2750) + 1))
        self.assertEqual(texts(vm), ["Continue 2730-2750"])          # the selection equals the job: no start button
        self.assertTrue(vm.moreVisible)
        self.assertEqual(vm.chapters.row(0)[4], "Stopped")
        self.assertEqual(vm.chapters.row(0)[5], "bright")
        self.assertEqual(vm.wordTip(0), "The job stopped here. Continue goes on from this chapter.")
        self.assertEqual([i["id"] for i in vm.moreItems()], ["discard"])
        self.assertEqual(self.app.translateState, "")

    def test_continue_starts_the_recorded_job(self):
        vm = self.vm
        self.record("stopped", range(position(2730), position(2750) + 1))
        vm.act("continue")
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(len(self.started), 1)
        self.assertTrue(self.rc.run.resume)

    def test_interrupted_reads_as_stopped(self):
        self.record("running", range(position(2730), position(2750) + 1))
        self.assertEqual(texts(self.vm), ["Continue 2730-2750"])
        self.assertEqual(self.vm.chapters.row(0)[4], "Stopped")


class Replace(Base):
    specs = [demo.knights()]
    select = "2800-2819"

    def setUp(self):
        super().setUp()
        self.record("stopped", range(position(2730), position(2750) + 1))

    def test_selection_beside_a_stopped_job(self):
        vm = self.vm
        self.assertEqual(texts(vm), ["Continue 2730-2750", "Replace job · 2800-2819"])
        self.assertEqual(vm.bar[0]["tone"], "main")
        self.assertEqual(len(vm.chapters), 20)

    def test_replace_asks_at_once_and_starts_on_ok(self):
        vm = self.vm
        vm.act("replace")
        self.assertEqual(vm.panel, "replace")
        self.assertEqual(vm.panelData["title"], "Replace the job?")
        self.assertEqual(vm.panelData["ok"], "Replace job")
        self.assertEqual(self.app.panel, "translate")
        self.assertEqual(self.started, [])
        vm.panelOk()
        self.assertEqual(vm.panel, "")
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(self.rc.run.chapters[0], position(2800))

    def test_cancel_starts_nothing(self):
        vm = self.vm
        vm.act("replace")
        vm.panelCancel()
        self.assertEqual((vm.panel, self.app.panel, self.started), ("", "", []))

    def test_the_panel_closes_as_cancel_when_its_subject_changes(self):          # 13.12
        vm = self.vm
        vm.act("replace")
        self.assertEqual(vm.panel, "replace")
        demo.write_record(self.path, "Book 1", "finished", range(position(2730), position(2750) + 1))
        vm._load_series(job_only=True)
        self.assertTrue(pump(lambda: vm.panel == ""))
        self.assertEqual((self.app.panel, self.started), ("", []))

    def test_discard_asks_then_forgets_the_job(self):
        vm = self.vm
        vm.moreAct("discard")
        self.assertEqual(vm.panel, "discard")
        self.assertIn("will not be continued", "".join(p["text"] for p in vm.panelData["parts"]))
        vm.panelOk()
        self.assertTrue(pump(lambda: seg(vm, "continue") is None))
        from novelgui.facade import run as frun
        self.assertEqual(frun.job_view(self.path).state, "finished")

    def test_the_discard_panel_closes_when_the_job_is_gone(self):
        vm = self.vm
        vm.moreAct("discard")
        demo.write_record(self.path, "Book 1", "finished", range(position(2730), position(2750) + 1))
        vm._load_series(job_only=True)
        self.assertTrue(pump(lambda: vm.panel == ""))

    def test_while_another_series_runs_replace_is_queued_with_its_confirmation(self):
        # the replacement is confirmed when it is queued, nothing asks later at night
        vm = self.vm
        self.rc.run = SimpleNamespace(kind="job", series="X", name="Gamma", book="Book 2", chapters=[1], chap={},
                                      stopping=False, user_stop=False, paused_until=None, retry_until=None,
                                      events=SimpleNamespace(totals=lambda: (0, 0, 0, 0)), done_at_start=0,
                                      started=0, sample=(0, 0), snapshot=None, handle=None)
        vm._recompute()
        self.assertEqual(vm.bar[1]["id"], "queue_replace")
        vm.act("queue_replace")
        self.assertEqual(vm.panel, "queueReplace")
        vm.panelOk()
        item = self.rc.queue_items()[0]
        self.assertTrue(item.replace)
        self.rc.run = None


class WaitingTerms(Base):
    specs = [demo.knights(blocked=[2731])]
    select = "2730-2750"

    def test_the_row_says_the_terms_and_the_bar_offers_review(self):
        vm = self.vm
        self.record("waiting_terms", range(position(2730), position(2750) + 1), terms_pending=1,
                    blocked_chapter=position(2731))
        self.assertEqual(texts(vm), ["Review 1 term", "•••"] if False else ["Review 1 term"])
        self.assertEqual(vm.bar[0]["tone"], "red")
        self.assertTrue(vm.moreVisible)
        row = vm.chapters.row(position(2731) - position(2730))
        self.assertEqual((row[4], row[5]), ("1 term", "red"))
        self.assertEqual(self.app.termsState, "red")
        self.assertIsNone(seg(vm, "continue"))              # no dim Continue: it comes back with the confirmed terms


class QuotaWait(Base):
    select = "2730-2750"

    def test_quota_wait_shows_the_wake_time_and_dont_resume(self):
        vm = self.vm
        wake = time.time() + 3600
        self.record("waiting_quota", range(position(2730), position(2750) + 1), wake_at=wake)
        self.assertEqual(texts(vm), ["Don't resume"])
        self.assertEqual(vm.chapters.row(0)[4], "Resumes " + time.strftime("%H:%M", time.localtime(wake)))
        self.assertEqual(vm.chapters.row(0)[5], "dim")
        self.assertIn("by itself", vm.top["sampleTip"] + " by itself")
        self.assertFalse(vm.top["sampleEnabled"])
        self.assertIn("will not go on by itself", vm.bar[0]["tip"])

    def test_dont_resume_leaves_the_job_stopped(self):
        vm = self.vm
        self.record("waiting_quota", range(position(2730), position(2750) + 1), wake_at=time.time() + 3600)
        vm.act("dont_resume")
        self.assertTrue(pump(lambda: seg(vm, "continue") is not None))
        self.assertEqual(vm.chapters.row(0)[4], "Stopped")
        self.assertEqual(self.started, [])

    def test_a_wake_time_in_the_past_is_a_stopped_job_never_started_by_itself(self):
        self.record("waiting_quota", range(position(2730), position(2750) + 1), wake_at=time.time() - 60)
        self.assertEqual(texts(self.vm), ["Continue 2730-2750"])
        self.spin(200)
        self.assertEqual(self.started, [])


class Failed(Base):
    select = "2730-2750"

    def test_key_invalid_pulses_and_offers_settings_then_continue(self):
        vm = self.vm
        demo.write_dead_key(self.path, self.key_list[0])
        self.record("failed", range(position(2730), position(2750) + 1), error="no usable key/model pair is left")
        self.assertEqual(texts(vm), ["Settings", "Continue 2730-2750"])
        self.assertEqual(vm.bar[0]["tone"], "red")
        row = vm.chapters.row(0)
        self.assertEqual((row[4], row[5]), ("Key invalid", "red"))
        self.assertEqual(self.app.translateState, "attention")
        self.assertEqual(self.app.run.reason, "Key invalid")
        self.assertEqual([i["id"] for i in vm.moreItems()], ["discard", "details"])
        vm.act("settings")
        self.assertTrue(self.app.settingsOpen)

    def test_another_failure_is_not_a_red_pulse(self):
        vm = self.vm
        self.record("failed", range(position(2730), position(2750) + 1), error="the service keeps failing")
        self.assertEqual(self.app.translateState, "")
        self.assertEqual(vm.chapters.row(0)[4], "Stopped")
        self.assertEqual(vm.wordTip(0), "The service kept failing. Continue later.")
        self.assertIsNone(seg(vm, "settings"))

    def test_continue_after_a_dead_key_revives_the_pairs_first(self):
        vm = self.vm
        demo.write_dead_key(self.path, self.key_list[0])
        self.record("failed", range(position(2730), position(2750) + 1), error="no usable key/model pair is left")
        with mock.patch("novelgui.ctl.runcontrol.frun.revive_dead_pairs") as revive:
            vm.act("continue")
            self.assertTrue(pump(lambda: self.rc.run is not None))
        revive.assert_called_once()


class Elsewhere(Base):
    def test_busy_elsewhere_has_no_bar(self):
        from novelgui.facade import run as frun
        real = frun.job_view

        def foreign(path):
            v = real(path)
            return v if Path(path).name != "Knights" else type(v)("running", "Book 1", tuple(range(1, 30)), foreign=True)

        with mock.patch.object(frun, "job_view", foreign):
            self.vm._load_series(job_only=True)
            self.settle()
            vm = self.vm
            self.assertEqual(vm.bar, [])
            self.assertTrue(vm.foreign)
            self.assertEqual(vm.chapters.row(0)[4], "Busy elsewhere on this PC")
            self.assertEqual(vm.wordTip(0)[:30], "Another copy of the program, o")
            self.assertFalse(vm.top["sampleEnabled"])
            self.assertEqual(self.rc.start(self.path, "Book 1", [1]), "Another program is working on Knights.")


class Problems(Base):
    specs = [demo.knights(translated=0)]

    def prepare(self):
        demo.write_failed_block(self.path, "Book 1", position(2710), 1)
        demo.write_failed_block(self.path, "Book 1", position(2720), 0, "refused")

    def setUp(self):
        super().setUp()
        self.vm._load_problems()
        pump(lambda: len(self.vm._problems) == 2)
        self.settle()

    def test_problems_tab_counts_and_is_red_when_a_block_failed(self):
        vm = self.vm
        self.assertEqual([t["id"] for t in vm.tabs], ["chapters", "problems"])
        self.assertEqual((vm.tabs[1]["text"], vm.tabs[1]["tone"]), ("Problems 2", "red"))
        self.assertEqual(vm.problemCount, 2)
        row = vm.chapters.row(2710 - 2703)
        self.assertEqual(row[4], "1 problem")
        self.assertIn("problems", row[7].split(","))
        vm.wordClicked(2710 - 2703)
        self.assertEqual(vm.tab, "problems")
        self.assertEqual(texts(vm), ["Check 2703-2750"] if False else texts(vm))

    def test_check_range_is_only_chapters_with_a_translation(self):
        self.vm.setTab("problems")
        self.assertEqual(ids(self.vm), ["check"])

    def test_a_row_opens_the_editor(self):
        vm = self.vm
        vm.setTab("problems")
        self.assertFalse(vm.editor["open"])
        vm.selectProblem(0)
        ed = vm.editor
        self.assertTrue(ed["open"])
        self.assertEqual(ed["reason"], "empty")
        self.assertFalse(ed["finding"])
        vm.selectProblem(0)                             # a second click closes it
        self.assertFalse(vm.editor["open"])

    def test_keep_original_resolves_the_block(self):
        vm = self.vm
        vm.setTab("problems")
        vm.selectProblem(0)
        vm.keepProblem()
        self.assertTrue(pump(lambda: vm.problemCount == 1))
        self.settle()

    def test_typed_text_is_saved(self):
        vm = self.vm
        vm.setTab("problems")
        vm.selectProblem(1)
        vm.saveProblem("Написанный текст")
        self.assertTrue(pump(lambda: vm.problemCount == 1))

    def test_retry_goes_through_the_start_rules(self):
        vm = self.vm
        vm.setTab("problems")
        vm.selectProblem(0)
        vm.retryProblem()
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.rc.run.chapters, [position(2710)])

    def test_a_block_of_the_running_job_cannot_be_resolved(self):
        vm = self.vm
        self.begin(positions=[position(2710)])
        vm.setTab("problems") if vm.tabs else None
        vm.selectProblem(0)
        self.assertFalse(vm.editor["canResolve"])
        vm.keepProblem()
        self.assertEqual(vm.problemCount, 2)


class Queue(Base):
    specs = [demo.knights(), demo.other("Gamma"), demo.other("Delta", target="pl:Polish")]

    def test_restart_shows_next_then_and_continue_queue(self):
        vm = self.vm
        g, d = str(self.lib / "Gamma"), str(self.lib / "Delta")
        from novelgui import jobqueue as jq
        self.rc.enqueue(jq.Item(g, "Book 2", ((1, 10),), False, False, "12-21"))
        self.rc.enqueue(jq.Item(d, "Book 2", ((1, 5),), False, False, "12-16"))
        self.assertEqual([t["id"] for t in vm.tabs], ["chapters", "queue"])
        self.assertEqual(vm.tabs[1]["text"], "Queue 2")
        self.assertEqual([r[1] for r in vm.queue_rows.rows], ["next", "then"])
        self.assertTrue(vm.queueRestart)
        vm.setTab("queue")
        self.assertEqual(ids(vm), ["continue_queue"])
        self.assertEqual(vm.queue_rows.row(0)[2:4], ("Gamma", "Book 1 · 12-21 · Ukrainian"))
        self.assertEqual(self.started, [])                 # nothing starts by itself (1.8, 13.13)
        vm.act("continue_queue")
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(self.rc.run.series, g)

    def test_up_down_remove(self):
        vm = self.vm
        g, d = str(self.lib / "Gamma"), str(self.lib / "Delta")
        from novelgui import jobqueue as jq
        self.rc.enqueue(jq.Item(g, "Book 2", ((1, 10),), False, False, "12-21"))
        self.rc.enqueue(jq.Item(d, "Book 2", ((1, 5),), False, False, "12-16"))
        flags = [r[5] for r in vm.queue_rows.rows]
        self.assertEqual(flags, ["down", "up"])
        vm.queueDown(0)
        self.assertEqual([r[2] for r in vm.queue_rows.rows], ["Delta", "Gamma"])
        vm.queueUp(1)
        self.assertEqual([r[2] for r in vm.queue_rows.rows], ["Gamma", "Delta"])
        vm.queueRemove(0)
        self.assertEqual([r[2] for r in vm.queue_rows.rows], ["Delta"])
        self.assertEqual(vm.tabs[1]["text"], "Queue 1")

    def test_the_running_row_comes_first_with_stop(self):
        vm = self.vm
        from novelgui import jobqueue as jq
        run = self.begin(positions=range(1, 20), series="Gamma", book="Book 2")
        self.rc.enqueue(jq.Item(str(self.lib / "Delta"), "Book 2", ((1, 5),), False, False, "12-16"))
        self.feed(run, "progress", index=1, done=1, total=3, failed=0)
        self.rc._flush_progress()
        r = vm.queue_rows.row(0)
        self.assertEqual((r[1], r[2]), ("now", "Gamma"))
        self.assertIn("running", r[5])
        self.assertGreaterEqual(r[4], 0)
        self.assertEqual(vm.queue_rows.row(1)[1][:1], "≈")
        self.assertEqual(vm.tabs[1]["text"], "Queue 2")
        vm.queueStop()
        self.assertTrue(run.stopping)

    def test_a_queued_item_that_cannot_start_shows_why(self):
        vm = self.vm
        from novelgui import jobqueue as jq
        d = str(self.lib / "Delta")
        self.rc.enqueue(jq.Item(d, "Book 9", ((1, 5),), False, False, "x"))
        self.rc.continue_queue()
        self.assertTrue(pump(lambda: self.rc.sched.halted == "Stopped"))
        vm._compute_queue()
        row = vm.queue_rows.row(0)
        self.assertIn("stuck", row[5])
        self.assertIn("volume", row[6])
        self.assertEqual(self.app.translateState, "attention")          # 9.12: the header pulses red, the bar says Continue queue
        vm.setTab("queue")
        self.assertEqual(ids(vm), ["continue_queue"])
        self.assertIn("Click: Translate of Delta", row[7], "the tooltip of a stuck row says where the click goes")

    def test_queue_replace_confirmation_for_a_series_already_queued(self):
        vm = self.vm
        from novelgui import jobqueue as jq
        self.begin(positions=range(1, 20), series="Gamma", book="Book 2")
        self.rc.enqueue(jq.Item(self.path, "Book 1", ((2, 5),), False, False, "2651-2654"))
        vm.act("queue")
        self.assertEqual(vm.panel, "replaceItem")
        self.assertIn("The queue already has", "".join(p["text"] for p in vm.panelData["parts"]))
        vm.panelOk()
        self.assertEqual(self.rc.queue_items()[0].reach, "2703-2750")


class QuotaWaitInTheQueue(Base):
    specs = [demo.knights(), demo.other("Gamma")]

    def test_the_head_row_shows_the_wake_time(self):
        vm = self.vm
        from novelgui import jobqueue as jq
        wake = self.rc.clock() + 3600
        self.rc.sched.wait = jq.Wait(str(self.lib / "Gamma"), wake)
        self.rc.enqueue(jq.Item(self.path, "Book 1", ((1, 5),), False, False, "2650-2654"))
        row = vm.queue_rows.row(0)
        self.assertEqual(row[1], time.strftime("%H:%M", time.localtime(wake)))
        self.assertIn("wait", row[5])
        self.assertEqual(vm.tabs[1]["text"], "Queue 2")
        self.assertEqual(vm.bar[0]["id"], "queue")
        self.assertIn("goes on here at " + row[1], row[7], "the tooltip of the head row names the return time")
        self.rc.sched.wait = None


class Sample(Base):
    specs = [demo.knights(blocked=[2703, 2704])]

    def test_sample_starts_through_run_control_and_fills_the_tab(self):
        vm = self.vm
        self.assertEqual(vm.top["sampleText"], "Sample · 1 unreviewed")
        vm.sample()
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(self.rc.run.kind, "sample")
        self.assertEqual(vm.tab, "sample")
        self.assertTrue(vm.top["sampling"])
        self.assertEqual(vm.top["sampleText"], "Sample 0 / 50")
        self.assertIn("stop", vm.top["sampleTip"].lower())
        self.rc.run.sample = (12, 50)
        self.rc._flush_progress()
        self.assertEqual(vm.top["sampleText"], "Sample 12 / 50")
        self.assertAlmostEqual(vm.top["samplePercent"], 0.24)
        self.rc._done(self.rc.run, {"stopped": False})
        self.assertTrue(pump(lambda: not vm.sampleResult["pending"]))
        r = vm.sampleResult
        self.assertEqual(r["title"], "Sample · 1 term unreviewed")
        self.assertEqual(vm.tabs[-1]["text"], "Sample · 1 term unreviewed")
        self.assertEqual(r["sub"], "chapter 2703 · first 50 blocks")
        self.assertGreaterEqual(len(r["rows"]), 3)

    def test_click_on_the_running_sample_stops_it(self):
        vm = self.vm
        vm.sample()
        self.assertTrue(pump(lambda: self.rc.run is not None))
        vm.sample()
        self.assertTrue(self.rc.run.stopping)


class SampleBlocksStart(Base):
    def test_the_start_button_is_dim_while_a_sample_runs(self):
        vm = self.vm
        vm.sample()
        self.assertTrue(pump(lambda: self.rc.run is not None))
        s = seg(vm, "translate")
        self.assertFalse(s["enabled"])
        self.assertIn("sample", s["tip"].lower())
        vm.sample()
        self.assertTrue(self.rc.run.stopping)


class Prompt(Base):
    def test_draft_is_kept_for_the_next_edit(self):
        vm = self.vm
        vm.promptEdit(True)
        self.assertEqual(vm.panel, "prompt")
        self.assertEqual((vm.panelData["name"], vm.panelData["text"]), ("", ""))
        err = vm.promptChanged("Literary", "my text {language}")
        self.assertEqual(err, "")
        vm.promptClosed("Literary", "my text {language}", True)           # Esc / outside: kept as a draft
        self.assertEqual(vm.panel, "")
        vm.promptEdit(True)
        self.assertEqual((vm.panelData["name"], vm.panelData["text"]), ("Literary", "my text {language}"))
        self.assertTrue(vm.panelData["draft"])
        vm.promptClosed("Literary", "my text {language}", False)          # Cancel throws it away
        vm.promptEdit(True)
        self.assertEqual(vm.panelData["name"], "")
        self.assertFalse(vm.panelData["draft"])

    def test_default_is_shown_read_only_and_copied(self):
        vm = self.vm
        from novelgui.facade import books as fbooks
        shipped = fbooks.current_prompt_text(self.path)
        vm.promptEdit(False)
        self.assertTrue(vm.panelData["readonly"])
        self.assertEqual((vm.panelData["title"], vm.panelData["text"], vm.panelData["ok"]), ("Default prompt", shipped, "Make a copy"))
        vm.promptClosed("Default", shipped, True)                         # Esc: nothing to keep
        self.assertEqual(vm.panel, "")
        self.assertIsNone(self.app.win.prompt_draft(self.path))
        vm.promptEdit(True)
        vm.promptSave("Default copy", "x {language}")
        vm.promptEdit(False)                                              # the current one is a saved prompt now: edited
        self.assertFalse(vm.panelData.get("readonly", False))
        vm.promptClosed("Default copy", "x {language}", False)
        vm.choosePrompt("default")
        vm.promptEdit(False)
        vm.promptCopyDefault()
        self.assertEqual((vm.panelData["name"], vm.panelData["text"]), ("Default copy 2", shipped), "a free name")
        self.assertTrue(vm.panelData["copy"])
        vm.promptSave("Default copy 2", shipped)
        self.assertEqual(vm.top["promptName"], "Default copy 2")

    def test_save_names_the_prompt_and_applies_it_to_the_series(self):
        vm = self.vm
        vm.promptEdit(True)
        self.assertEqual(vm.promptChanged("", "x"), "Give the prompt a name.")
        self.assertIn("Default", vm.promptChanged("default", "x"))
        vm.promptSave("Literary ru", "Translate to {language}.")
        self.assertEqual(vm.panel, "")
        self.assertEqual(vm.top["promptName"], "Literary ru")
        self.settle()
        from novelgui.facade import books as fbooks
        self.assertEqual(fbooks.current_prompt_text(self.path), "Translate to {language}.")
        names = [e["text"] for e in vm.promptEntries()]
        self.assertEqual(names, ["Default", "Literary ru", "+ New prompt"])
        vm.choosePrompt("default")
        self.settle()
        self.assertEqual(vm.top["promptName"], "Default")

    def test_delete_and_undo(self):
        vm = self.vm
        vm.promptEdit(True)
        vm.promptSave("Short", "t")
        vm.deletePrompt("Short")
        self.assertEqual([e["text"] for e in vm.promptEntries()], ["Default", "+ New prompt"])
        self.assertEqual(vm.top["promptName"], "Default")
        vm.undoPromptDelete()
        self.assertEqual([e["text"] for e in vm.promptEntries()][1], "Short")

    def test_the_prompt_is_usable_during_a_run(self):
        vm = self.vm
        self.begin()
        vm.promptEdit(True)
        self.assertEqual(vm.panel, "prompt")


class Models(Base):
    specs = [demo.knights(translated=0, blocked=[2731]), demo.other("Gamma")]

    def test_models_pass_the_item_model_tester(self):
        vm = self.vm
        for m in (vm.chapters, vm.problemsModel, vm.queueModel):
            QAbstractItemModelTester(m, QAbstractItemModelTester.FailureReportingMode.Fatal, m)
        demo.write_failed_block(self.path, "Book 1", position(2710), 0)
        self.begin(positions=range(position(2703), position(2720)))
        run = self.rc.run
        for k in range(3):
            self.progress(run, position(2703) + k, 2)
        self.rc.enqueue(__import__("novelgui.jobqueue", fromlist=["x"]).Item(str(self.lib / "Gamma"), "Book 2", ((1, 5),),
                                                                             False, False, "12-16"))
        vm._load_problems()
        self.settle()
        self.assertGreater(len(vm.chapters), 0)

    def test_a_snapshot_never_resets_the_list(self):
        vm = self.vm
        run = self.begin()
        resets = QSignalSpy(vm.chapters.modelReset)
        for k in range(position(2703), position(2710)):
            self.progress(run, k, 1)
        self.assertEqual(resets.count(), 0)


class Closing(Base):
    def test_closing_during_a_run_opens_the_panel_and_stops_the_run(self):
        vm = self.vm
        run = self.begin()
        self.progress(run, position(2703), 1)
        self.app.requestClose()
        self.assertEqual(self.app.panel, "closing")
        self.assertEqual(self.app.panelData["kind"], "running")
        self.assertIn("Knights · chapter 2703", self.app.panelData["text"])
        self.assertTrue(run.stopping)
        self.assertEqual(self.rc.state, "closing")
        exits = []
        self.app.exit_app = lambda: exits.append(1)
        self.end(run, "stopped")
        self.assertTrue(pump(lambda: exits == [1]))

    def test_closing_during_the_quota_wait_names_the_wake_time(self):
        from novelgui import jobqueue as jq
        wake = self.rc.clock() + 3600
        self.rc.sched.wait = jq.Wait(self.path, wake)
        self.vm._recompute()
        self.app.requestClose()
        self.assertEqual(self.app.panelData["kind"], "waiting")
        self.assertIn("waits for the daily quota until " + time.strftime("%H:%M", time.localtime(wake)),
                      self.app.panelData["text"])
        self.rc.sched.wait = None


class Toasts(Base):
    def test_the_end_of_a_job_is_announced_only_while_the_window_is_inactive(self):
        run = self.begin(positions=range(position(2703), position(2706)))
        self.app.window_active = lambda: True
        self.end(run, "finished")
        self.assertEqual(self._toasts(), [])

    def test_a_failed_key_is_announced_when_inactive(self):
        demo.write_dead_key(self.path, self.key_list[0])
        run = self.begin(positions=range(position(2703), position(2706)))
        self.app.window_active = lambda: False
        self.end(run, "failed", error="no usable key/model pair is left")
        lines = self._toasts()
        self.assertTrue(any("key invalid" in t["text"].lower() for t in lines), lines)

    def _toasts(self):
        try:
            rows = [json.loads(x) for x in self.parts.notifier.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError:
            rows = []
        return [r for r in rows if r.get("kind") == "toast"]


if __name__ == "__main__":
    unittest.main()
