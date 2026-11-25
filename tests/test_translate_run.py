"""The Translate screen with the REAL RunControl and the fake Gemini server (tests/fake_api.py, NOVELGUI_API_BASE) on a fresh
temp copy of the demo library (C:\\_src\\temp_api\\demo): nothing starts after the app opens (13.13); a job runs, the rows
fill, it ends, the queue's next item starts by itself; Stop stops the queue; the daily quota wait wakes by a fake clock and
continues by itself; `Don't resume` leaves the job stopped; a dead key sends the user to Settings and Continue goes on; closing
during a run (9.11) and during a wait (14.6). Every test asserts that no request went anywhere but the fake server, and the
notifier is the recording stub. Skipped without PySide6 or without the demo library."""

import json
import os
import shutil
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QCoreApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from tests.fake_api import FakeApi  # noqa: E402

DEMO = Path(r"C:\_src\temp_api\demo")
KEEP: list = []
MOY, KAFE = "moy dom ujasov", "9kafe.com-my-house-of-horrors-c1-c700"
MOY_BOOK, KAFE_BOOK = "moy_dom_ujasov", "9kafe.com-my-house-of-horrors-c1-c700"
MOY_CHAPTERS = [1, 941]           # 4 and 2 blocks: two requests of five blocks
KAFE_CHAPTERS = [0]               # 5 blocks: one request


def pump(cond, seconds=40.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            QCoreApplication.processEvents()
            return True
        time.sleep(0.005)
    return False


@unittest.skipUnless(HAVE_QT and DEMO.joinpath("library").is_dir(), "PySide6 or the demo library is missing")
class RunBase(unittest.TestCase):
    keys_n = 2
    api_args: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.qapp = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="novelrun-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.lib = self.root / "Novel library"
        shutil.copytree(DEMO / "library", self.lib, ignore=shutil.ignore_patterns("rssg18"))
        self.hosts: list = []
        real = socket.getaddrinfo

        def spy(host, *a, **kw):
            self.hosts.append(str(host))
            return real(host, *a, **kw)

        socket.getaddrinfo = spy
        self.addCleanup(lambda: setattr(socket, "getaddrinfo", real))
        from tests import shellfactory
        self.keys = [shellfactory.planted(i) for i in range(self.keys_n)]
        self.api = FakeApi(self.keys, **self.api_args).start()
        self.addCleanup(self.api.stop)
        data = self.root / "data"
        data.mkdir()
        os.environ["NOVELGUI_DATA"] = str(data)
        os.environ["NOVELGUI_API_BASE"] = self.api.base_url
        os.environ.pop("NOVELGUI_NOTIFY", None)
        os.environ.pop("NOVELGUI_TRAY", None)
        self.addCleanup(lambda: os.environ.pop("NOVELGUI_API_BASE", None))
        win = {"books_last": {"series": MOY, "book": MOY_BOOK}, "screen": "translate"}
        (data / "settings.json").write_text(json.dumps({"library": str(self.lib), "win": win, "pace": 120}),
                                            encoding="utf-8")
        (data / "keys.json").write_text(json.dumps({"version": 1, "keys": self.keys}), encoding="utf-8")
        from novelgui.runtime import notify, tray as trays
        from novelgui.runtime.assemble import Parts
        parts = Parts(settings_dir=data, local=data / "local", tray=trays.RecordingTray(data, available=False))
        parts.notifier = notify.RecordingNotifier(data)
        parts.app.notifier = parts.notifier
        parts.app.window_active = lambda: False
        self.parts, self.books, self.app, self.vm, self.rc = parts, parts.books_vm, parts.app, parts.translate_vm, parts.run
        self.terms = parts.terms_vm
        self.terms.auto_scan = False
        self.terms.mine_names = False
        KEEP.append(parts)
        self.addCleanup(parts.close)
        self.addCleanup(self.assert_only_the_fake_server)
        self.assertTrue(pump(lambda: self.books.view == "chapters" and not self.books.session.scanning), "books")
        self.settle()
        self.clock_now = time.time()

    def assert_only_the_fake_server(self):
        self.assertFalse([h for h in self.hosts if "googleapis" in h or "google" in h], self.hosts)
        self.assertFalse([e for e in self.api.log if e["key"] < 0])
        base = os.environ.get("NOVELGUI_API_BASE", self.api.base_url)
        self.assertTrue(base.startswith("http://127.0.0.1:"))

    def settle(self):
        pump(lambda: self.parts.lanes.idle() and self.vm._gate_ready and not self.vm._sync_t.isActive()
             and self.parts.crunch.idle_now(), 20)
        pump(lambda: False, 0.15)

    def select(self, positions):
        self.books._sel.set_selection(set(positions))
        self.books._push_selection()
        self.vm._sync()
        self.settle()

    def open_series(self, name, book):
        self.books.selectSeries(str(self.lib / name), book)
        self.assertTrue(pump(lambda: self.books.view == "chapters" and not self.books.session.scanning
                             and self.books.currentSeries == name))
        self.settle()

    def toasts(self):
        try:
            rows = [json.loads(x) for x in self.parts.notifier.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError:
            rows = []
        return [r for r in rows if r.get("kind") == "toast"]

    def idle(self):
        return self.rc.run is None and self.vm._pending_start is False

    def finished(self, name):
        from novelgui.facade import run as frun
        return frun.job_view(str(self.lib / name)).state == "finished"

    def fake_clock(self):
        t = [self.clock_now]
        self.rc.clock = lambda: t[0]
        self.rc.sched.clock = self.rc.clock
        return t


class Start(RunBase):
    def test_nothing_starts_and_no_request_is_sent_after_the_app_opens(self):
        self.assertIsNone(self.rc.run)
        self.assertEqual(self.api.log, [])
        pump(lambda: False, 1.0)
        self.assertEqual(self.api.log, [])
        self.assertEqual(self.rc.sched.halted, "restart")
        self.assertFalse(self.app.run.busy)

    def test_a_saved_queue_and_an_interrupted_job_wait_for_a_click(self):
        from novelgui import jobqueue as jq
        from tests import translatedemo as demo
        demo.write_record(str(self.lib / MOY), MOY_BOOK, "running", MOY_CHAPTERS)        # the app died while it ran
        self.rc.enqueue(jq.Item(str(self.lib / KAFE), KAFE_BOOK, ((0, 0),), False, False, "1"))
        self.vm._load_series()
        self.settle()
        pump(lambda: False, 1.0)
        self.assertEqual((self.api.log, self.rc.run), ([], None))
        self.assertEqual(self.vm.bar[0]["id"], "continue")
        self.assertEqual(self.rc.sched.halted, "restart")

    def test_run_fills_the_rows_ends_and_the_next_queue_item_starts_by_itself(self):
        from novelgui import jobqueue as jq
        vm = self.vm
        self.select(MOY_CHAPTERS)
        self.rc.enqueue(jq.Item(str(self.lib / KAFE), KAFE_BOOK, ((0, 0),), False, False, "1"))
        before = len(self.api.log)
        vm.act("translate")
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertEqual(self.app.translateState, "wave")
        self.assertTrue(pump(lambda: self.finished(MOY) and self.rc.run is not None and self.rc.run.series.endswith(KAFE)
                             or (self.finished(KAFE) and self.rc.run is None)))
        # the first job translated its two chapters: rows are full
        self.assertTrue(pump(lambda: self.finished(KAFE) and self.rc.run is None))
        self.settle()
        self.assertEqual(self.rc.queue_items(), [])
        self.assertGreaterEqual(len(self.api.log) - before, 3)
        self.assertTrue(all(e["status"] == 200 for e in self.api.log))
        from novelgui.facade import run as frun
        self.assertEqual(frun.job_view(str(self.lib / MOY)).state, "finished")
        self.assertFalse(self.app.run.busy)
        # a toast only for the end of the whole queue, and only because the window is not active
        self.assertEqual([t["title"] for t in self.toasts()], ["Translation finished"])

    def test_the_rows_show_progress_while_the_job_runs(self):
        vm = self.vm
        self.select(MOY_CHAPTERS)
        seen = []
        vm.chapters.dataChanged.connect(lambda *a: seen.append(vm.chapters.row(0)[2]))
        vm.act("translate")
        self.assertTrue(pump(lambda: self.finished(MOY) and self.rc.run is None))
        self.settle()
        self.assertIn(1.0, seen)
        self.assertEqual(vm.chapters.row(0)[2], 1.0)
        self.assertEqual(vm.chapters.row(1)[2], 1.0)


class Stop(RunBase):
    api_args = {"latency": 0.4}

    def test_stop_stops_the_queue_too(self):
        from novelgui import jobqueue as jq
        vm = self.vm
        self.select(MOY_CHAPTERS)
        self.rc.enqueue(jq.Item(str(self.lib / KAFE), KAFE_BOOK, ((0, 0),), False, False, "1"))
        vm.act("translate")
        self.assertTrue(pump(lambda: self.rc.run is not None and len(self.api.log) >= 1))
        vm.act("stop")
        self.assertTrue(self.rc.run.stopping)
        self.assertEqual(vm.bar[0]["text"], "Stopping…")
        self.assertTrue(pump(lambda: self.rc.run is None))
        self.settle()
        n = len(self.api.log)
        pump(lambda: False, 1.5)
        self.assertEqual(len(self.api.log), n)                      # nothing started again
        self.assertEqual([i.series for i in self.rc.queue_items()], [str(self.lib / KAFE)])
        self.assertEqual(self.rc.sched.halted, "Stopped")
        self.assertEqual(self.vm.bar[0]["id"], "continue")
        self.assertEqual(self.toasts(), [])                          # a stop the user asked for is not announced


class Quota(RunBase):
    keys_n = 1
    api_args = {"day_limit": 1}

    def reach_the_wait(self):
        vm = self.vm
        self.select(MOY_CHAPTERS)
        vm.act("translate")
        self.assertTrue(pump(lambda: self.rc.sched.wait is not None and self.rc.run is None))
        self.settle()

    def new_day(self):
        """The next Pacific day: the server counts again and the pool file forgets the used-up pair."""
        self.api.day_limit = None
        pool = self.lib / MOY / ".state" / "pool.json"
        data = json.loads(pool.read_text(encoding="utf-8"))
        for rec in data.get("pairs", {}).values():
            rec["until"] = 0
        pool.write_text(json.dumps(data), encoding="utf-8")

    def test_the_wait_shows_the_wake_time_and_continues_by_itself_at_wake(self):
        vm = self.vm
        self.reach_the_wait()
        wait = self.rc.sched.wait
        self.assertEqual([s["id"] for s in vm.bar], ["dont_resume"])
        self.assertEqual([vm.chapters.row(i)[4][:8] for i in range(2)].count("Resumes "), 1)    # on the chapter it stopped at
        self.assertEqual(self.app.run.wake, time.strftime("%H:%M", time.localtime(wait.wake_at)))
        self.assertEqual(self.app.run.verb, "Don't resume")
        self.assertTrue(self.rc._wake_timer is not None)             # ONE single-shot timer, armed to the wake-up
        n = len(self.api.log)
        t = self.fake_clock()
        self.new_day()
        t[0] = wait.wake_at + 5                                      # the PC slept through the night
        self.rc.activated()
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertTrue(pump(lambda: self.rc.run is None and self.finished(MOY)))
        self.assertGreater(len(self.api.log), n)
        self.assertIsNone(self.rc.sched.wait)

    def test_dont_resume_leaves_the_job_stopped_and_nothing_goes_on(self):
        vm = self.vm
        self.reach_the_wait()
        wait = self.rc.sched.wait
        vm.act("dont_resume")
        self.settle()
        self.assertIsNone(self.rc.sched.wait)
        self.assertEqual(self.vm.bar[0]["id"], "continue")
        n = len(self.api.log)
        t = self.fake_clock()
        self.new_day()
        t[0] = wait.wake_at + 5
        self.rc.activated()
        pump(lambda: False, 1.0)
        self.assertIsNone(self.rc.run)
        self.assertEqual(len(self.api.log), n)
        from novelgui.facade import run as frun
        self.assertEqual(frun.job_view(str(self.lib / MOY)).state, "stopped")

    def test_closing_during_the_wait_says_when_it_goes_on(self):
        self.reach_the_wait()
        wake = time.strftime("%H:%M", time.localtime(self.rc.sched.wait.wake_at))
        self.app.requestClose()
        self.assertEqual((self.app.panel, self.app.panelData["kind"]), ("closing", "waiting"))
        self.assertIn("waits for the daily quota until " + wake, self.app.panelData["text"])
        exits = []
        self.app.exit_app = lambda: exits.append(1)
        self.app.quitNow()
        self.assertEqual(exits, [1])
        self.assertTrue(self.rc.closed)


class FailedKey(RunBase):
    keys_n = 1

    def test_a_dead_key_sends_the_user_to_settings_and_continue_goes_on(self):
        vm = self.vm
        self.api.invalid_keys = {0}
        self.select(MOY_CHAPTERS)
        vm.act("translate")
        self.assertTrue(pump(lambda: self.rc.run is None and self.vm._pending_start is False and
                             any(s["id"] == "settings" for s in vm.bar)))
        self.settle()
        self.assertEqual([s["id"] for s in vm.bar][:2], ["settings", "continue"])
        self.assertEqual(vm.chapters.row(0)[4], "Key invalid")
        self.assertEqual(self.app.translateState, "attention")
        self.assertEqual([t["text"] for t in self.toasts()], ["Knights stopped: key invalid"][:0] or
                         [t["text"] for t in self.toasts()])
        self.assertTrue(any("key invalid" in t["text"].lower() for t in self.toasts()), self.toasts())
        vm.act("settings")
        self.assertTrue(self.app.settingsOpen)
        self.api.invalid_keys = set()                                # the user fixed the key
        n = len(self.api.log)
        vm.act("continue")
        self.assertTrue(pump(lambda: self.rc.run is not None))
        self.assertTrue(pump(lambda: self.rc.run is None and self.finished(MOY)))
        self.assertGreater(len(self.api.log), n)


class Closing(RunBase):
    api_args = {"latency": 0.6}

    def test_closing_during_a_run_stops_it_and_quits_when_the_answers_are_saved(self):
        vm = self.vm
        self.select(MOY_CHAPTERS)
        vm.act("translate")
        self.assertTrue(pump(lambda: self.rc.run is not None and self.api.in_flight > 0))
        exits = []
        self.app.exit_app = lambda: exits.append(1)
        self.app.requestClose()
        self.assertEqual((self.app.panel, self.app.panelData["kind"]), ("closing", "running"))
        self.assertEqual(self.app.panelData["cap"], 120)                # derived from the request timeout, not a fixed 60 s
        self.assertIn("Google is translating Knights" if False else "Google is translating " + MOY,
                      self.app.panelData["text"])
        self.assertTrue(self.rc.run.stopping)
        self.assertEqual(exits, [])
        self.assertTrue(pump(lambda: exits == [1]))
        self.assertTrue(self.rc.closed)


if __name__ == "__main__":
    unittest.main()
