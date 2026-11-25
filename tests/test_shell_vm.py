"""The view-models of the shell with QCoreApplication, QSignalSpy and QAbstractItemModelTester: AppVM (library states,
folder rules, steps and their persistence, closing and the tray, notifications, the focus-rescan hook, window memory),
SettingsVM (keys with the check on add against the FAKE server, models, pace, awake, graphics), LogVM, the frame model.
Skipped without PySide6."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from novelgui import keystore
    from novelgui.ctl import shellrules as sr
    from novelgui.ctl.winlog import WindowLog
    from novelgui.lanes import Lanes
    from novelgui.runtime import markers, notify, tray as trays
    from novelgui.runtime.frame import FrameModel
    from novelgui.settings import Settings
    from novelgui.vm.appvm import AppVM
    from novelgui.vm.logvm import LogVM
    from novelgui.vm.settingsvm import SettingsVM
    from tests.fake_api import FakeApi

KEYS = ["AIzaTestKey0000000000000000%02d" % i for i in range(4)]


class FakeClipboard:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


@unittest.skipUnless(HAVE_QT, "PySide6 is not available")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("NOVELGUI_DATA", "NOVELGUI_API_BASE")}
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.local = self.data / "local"
        os.environ["NOVELGUI_DATA"] = str(self.data)
        os.environ.pop("NOVELGUI_API_BASE", None)
        self.lib = self.root / "Novel library"
        self.events = []

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for _ in range(30):
            try:
                self._tmp.cleanup()
                break
            except PermissionError:
                time.sleep(0.1)

    def spin(self, ms=50):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.005)

    def wait_for(self, cond, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QCoreApplication.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    def make_app(self, settings=None, tray=True, home=None):
        self.data.mkdir(parents=True, exist_ok=True)
        if settings is not None:
            (self.data / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        self.settings = Settings(self.data)
        self.winlog = WindowLog(self.local)
        self.tray = trays.RecordingTray(self.data) if tray else None
        self.notifier = notify.RecordingNotifier(self.data)
        vm = AppVM(self.settings, self.winlog, self.tray, self.notifier, home=home or self.root)
        vm.hide_window = lambda: self.events.append("hide")
        vm.show_window = lambda: self.events.append("show")
        vm.exit_app = lambda: self.events.append("exit")
        self.app = vm
        return vm


class AppLibraryTest(Base):
    def test_first_start_without_a_library(self):
        vm = self.make_app({})
        self.assertEqual(vm.libraryState, "first")
        self.assertTrue(vm.stepsDim)
        self.assertEqual(vm.libraryPath, "")
        self.assertTrue(vm.defaultPath.endswith("Novel library"))

    def test_saved_library_is_ready_and_a_gone_one_is_missing(self):
        self.lib.mkdir()
        self.assertEqual(self.make_app({"library": str(self.lib)}).libraryState, "ready")
        self.assertEqual(self.make_app({"library": str(self.root / "gone")}).libraryState, "missing")

    def test_create_a_new_folder(self):
        vm = self.make_app({})
        spy = QSignalSpy(vm.libraryChanged)
        vm.useFolder(str(self.lib))
        self.assertTrue(self.lib.is_dir())
        self.assertFalse((self.lib / ".novel-write-probe").exists())
        self.assertEqual(vm.libraryState, "ready")
        self.assertEqual(self.settings.get("library"), str(self.lib))
        self.assertEqual(spy.count(), 1)
        self.assertFalse(vm.stepsDim)

    def test_a_series_folder_makes_its_parent_the_library(self):
        series = self.lib / "Knights"
        series.mkdir(parents=True)
        (series / "series.json").write_text("{}", encoding="utf-8")
        vm = self.make_app({})
        vm.useFolder(str(series))
        self.assertEqual(vm.libraryPath, str(self.lib))

    def test_a_folder_of_epubs_offers_them(self):
        self.lib.mkdir()
        (self.lib / "a.epub").write_bytes(b"x")
        vm = self.make_app({})
        spy = QSignalSpy(vm.addBooksRequested)
        vm.useFolder(str(self.lib))
        self.assertEqual(vm.libraryState, "ready")
        self.assertEqual(spy.count(), 1)
        self.assertTrue(spy.at(0)[0][0].endswith("a.epub"))

    def test_a_folder_that_cannot_be_written_says_why_and_changes_nothing(self):
        vm = self.make_app({})
        blocker = self.root / "file.txt"
        blocker.write_text("x", encoding="utf-8")
        vm.useFolder(str(blocker / "sub"))                  # a part of the path is a file
        self.assertEqual(vm.libraryState, "first")
        self.assertIsNone(self.settings.get("library"))
        self.assertIn("cannot be used", vm.message)
        self.assertTrue(any("cannot be used" in e.text and e.problem for e in self.winlog.entries()))
        vm.useFolder(str(blocker))                          # the path is a file
        self.assertIn("the path is a file", vm.message)

    def test_a_failed_change_keeps_the_old_library(self):
        self.lib.mkdir()
        vm = self.make_app({"library": str(self.lib)})
        blocker = self.root / "file.txt"
        blocker.write_text("x", encoding="utf-8")
        vm.useFolder(str(blocker / "sub"))
        self.assertEqual(vm.libraryPath, str(self.lib))
        self.assertEqual(vm.libraryState, "ready")

    def test_folder_dialog_answer(self):
        vm = self.make_app({})
        spy = QSignalSpy(vm.pickedChanged)
        vm.folderChosen(Path(self.root / "Picked").as_uri())
        self.assertEqual(vm.pickedPath, str(self.root / "Picked"))
        self.assertEqual(spy.count(), 1)
        self.assertEqual(vm.libraryState, "first")           # on the first-start block it only fills the field
        self.lib.mkdir()
        vm2 = self.make_app({"library": str(self.root / "gone")})
        vm2.folderChosen(str(self.lib))                      # elsewhere the folder is used at once
        self.assertEqual(vm2.libraryPath, str(self.lib))

    def test_change_is_refused_during_a_run(self):
        self.lib.mkdir()
        vm = self.make_app({"library": str(self.lib)})
        spy = QSignalSpy(vm.folderDialogRequested)
        vm.setRun({"running": True, "series": "Knights"})
        vm.changeLibrary()
        self.assertEqual(spy.count(), 0)
        vm.setRun({})
        vm.changeLibrary()
        self.assertEqual(spy.count(), 1)


class AppStepsTest(Base):
    def ready(self, **extra):
        self.lib.mkdir(exist_ok=True)
        return self.make_app(dict({"library": str(self.lib)}, **extra))

    def test_opens_on_the_last_screen_used(self):
        vm = self.ready(win={"screen": "export"})
        self.assertEqual(vm.screen, "export")
        vm.go("terms")
        self.assertEqual(Settings(self.data).get("win")["screen"], "terms")
        self.assertEqual(self.make_app(None).screen, "terms")        # the next start reads the same file

    def test_books_while_there_is_no_library(self):
        vm = self.make_app({"win": {"screen": "export"}})
        self.assertEqual(vm.screen, "books")
        vm.go("terms")
        self.assertEqual(vm.screen, "books")                 # the steps are dim: no switch

    def test_exactly_one_screen_and_the_signal(self):
        vm = self.ready()
        spy = QSignalSpy(vm.screenChanged)
        vm.goDigit(3)
        vm.goDigit(3)
        vm.goDigit(9)
        self.assertEqual(vm.screen, "translate")
        self.assertEqual(spy.count(), 1)
        vm.go("nonsense")
        self.assertEqual(vm.screen, "translate")

    def test_no_switch_while_a_panel_or_settings_is_open(self):
        vm = self.ready()
        vm.openSettings()
        vm.goDigit(2)
        self.assertEqual(vm.screen, "books")
        vm.closeSettings()
        vm.go("terms")
        self.assertEqual(vm.screen, "terms")

    def test_nothing_starts_by_itself(self):
        vm = self.ready()
        self.assertFalse(vm.busy)
        self.assertEqual(vm.translateState, "")
        self.assertEqual(vm.run, sr.RunInfo())

    def test_header_states_follow_the_run(self):
        vm = self.ready()
        spy = QSignalSpy(vm.runChanged)
        vm.setRun({"running": True, "series": "Knights", "book": "Book 1", "terms_red": True, "bogus": 1})
        self.assertEqual((vm.termsState, vm.translateState), ("red", "wave"))
        self.assertEqual(vm.contextLine, "Knights · Book 1")
        vm.setRun({"running": True, "needs_user": True, "series": "Knights"})
        self.assertEqual((vm.termsState, vm.translateState), ("", "attention"))
        self.assertEqual(spy.count(), 2)

    def test_context_line_is_empty_without_a_library(self):
        vm = self.make_app({})
        vm.setRun({"running": True, "series": "Knights"})
        self.assertEqual(vm.contextLine, "")

    def test_tips_are_plain_data(self):
        vm = self.ready()
        t = vm.tips
        self.assertEqual(t["max"], "Maximize")
        self.assertEqual(t["restore"], "Restore")
        json.dumps(t)


class AppClosingTest(Base):
    def ready(self, tray=True, **win):
        self.lib.mkdir(exist_ok=True)
        return self.make_app({"library": str(self.lib), "win": win}, tray=tray)

    RUN = {"running": True, "series": "Knights", "book": "Book 1", "done": 12, "total": 54, "left_s": 7800, "chapter": 2703,
           "verb": "Stop"}

    def test_the_tray_icon_is_shown_while_the_app_runs(self):
        self.ready()
        self.assertTrue(self.tray.visible)
        self.assertEqual(self.tray.lines, [("Nothing running", "dim")])

    def test_close_when_idle_quits(self):
        vm = self.ready()
        spy = QSignalSpy(vm.stopRequested)
        vm.requestClose()
        self.assertEqual(self.events, ["exit"])
        self.assertEqual(spy.count(), 0)

    def test_close_during_work_hides_to_the_tray_the_first_time_after_the_panel(self):
        vm = self.ready()
        vm.setRun(self.RUN)
        vm.requestClose()
        self.assertEqual(vm.panel, "trayFirst")
        self.assertEqual(self.events, [])
        vm.hideToTray()
        self.assertEqual(self.events, ["hide"])
        self.assertEqual(vm.panel, "")
        self.assertTrue(Settings(self.data).get("win")["tray_seen"])
        vm.requestClose()                                    # never asked again
        self.assertEqual(self.events, ["hide", "hide"])
        self.assertEqual(vm.panel, "")

    def test_close_during_a_wait_or_a_queue_hides_too(self):
        vm = self.ready(tray_seen=True)
        vm.setRun({"waiting": True, "series": "Knights", "wake": "09:01"})
        vm.requestClose()
        self.assertEqual(self.events, ["hide"])
        self.events.clear()
        vm.setRun({"queued": 2, "series": "Knights"})
        vm.requestClose()
        self.assertEqual(self.events, ["hide"])

    def test_without_a_tray_the_panel_of_9_11_opens(self):
        vm = self.ready(tray=False)
        vm.setRun(self.RUN)
        vm.requestClose()
        self.assertEqual(vm.panel, "closing")
        self.assertEqual(vm.panelData["title"], "Finishing the current requests")
        self.assertEqual(self.events, [])
        vm.setRun({"waiting": True, "series": "Knights", "wake": "09:01"})
        vm.closePanel()
        vm.requestClose()
        self.assertEqual(vm.panelData["close"], "Cancel")
        self.assertEqual(vm.panelData["action"], "Close")

    def test_quit_now_tells_the_run_to_stop_then_exits(self):
        vm = self.ready()
        vm.setRun(self.RUN)
        stop = QSignalSpy(vm.stopRequested)
        vm.quitNow()
        self.assertEqual((stop.count(), self.events), (1, ["exit"]))

    def test_tray_activate_toggles_the_window(self):
        vm = self.ready()
        visible = [True]
        vm.window_visible = lambda: visible[0]
        self.tray.activate()
        self.assertEqual(self.events, ["hide"])
        visible[0] = False
        self.tray.activate()
        self.assertEqual(self.events, ["hide", "show"])

    def test_tray_quit_idle_quits_and_during_a_run_opens_the_panel(self):
        vm = self.ready()
        self.tray.trigger("quit")
        self.assertEqual(self.events, ["exit"])
        self.events.clear()
        vm.setRun(self.RUN)
        self.tray.trigger("quit")
        self.assertEqual(self.events, ["show"])
        self.assertEqual((vm.panel, vm.panelData["kind"]), ("closing", "running"))

    def test_tray_open_and_verb(self):
        vm = self.ready()
        verbs = QSignalSpy(vm.verbRequested)
        vm.setRun(self.RUN)
        self.tray.trigger("open")
        self.tray.trigger("verb")
        self.assertEqual(self.events, ["show"])
        self.assertEqual(verbs.at(0)[0], "Stop")
        vm.setRun(dict(self.RUN, verb="Continue", verb_enabled=False))
        self.tray.trigger("verb")                            # disabled in the window, disabled here
        self.assertEqual(verbs.count(), 1)

    def test_tray_menu_follows_the_run(self):
        vm = self.ready()
        vm.setRun(self.RUN)
        self.assertEqual(self.tray.lines[0], ("Knights", "bright"))
        self.assertEqual(self.tray.tooltip, "Knights · 12 of 54 · ≈ 2 h 10 min left")
        self.assertFalse(self.tray.alert)
        vm.setRun({"failed": True, "series": "Knights", "reason": "Key invalid"})
        self.assertTrue(self.tray.alert)

    def test_toast_click_routes(self):
        vm = self.ready()
        vm.bring_forward("settings")
        self.assertTrue(vm.settingsOpen)
        vm.closeSettings()
        vm.bring_forward("translate")
        self.assertEqual(vm.screen, "translate")
        vm.bring_forward("details")
        self.assertTrue(vm.logOpen)
        self.assertEqual(self.events.count("show"), 3)


class AppNoticeTest(Base):
    def setUp(self):
        super().setUp()
        self.lib.mkdir()
        self.vm = self.make_app({"library": str(self.lib)})

    def toasts(self):
        p = self.data / "notify.log"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def test_toast_and_flash_only_while_the_window_is_not_active(self):
        self.vm.window_active = lambda: True
        self.vm.announce("finished", "Knights", "Knights · 54 chapters translated")
        self.assertEqual(self.toasts(), [])
        self.vm.window_active = lambda: False
        self.vm.announce("finished", "Knights", "Knights · 54 chapters translated")
        self.vm.announce("failed", "Knights", "Knights stopped: key invalid")
        self.vm.announce("key", "Knights", "A key stopped working: invalid")
        rows = self.toasts()
        self.assertEqual([r["kind"] for r in rows], ["toast", "flash"] * 3)
        self.assertEqual([r["route"] for r in rows if r["kind"] == "toast"], ["translate", "translate", "settings"])
        self.assertEqual(rows[0]["text"], "Knights · 54 chapters translated")

    def test_everything_is_in_the_log(self):
        self.vm.window_active = lambda: True
        self.vm.announce("failed", "Knights", "Knights stopped: key invalid")
        e = self.winlog.entries()
        self.assertEqual((e[-1].series, e[-1].problem), ("Knights", True))

    def test_a_runtime_toast_comes_only_when_inactive(self):
        self.vm.window_active = lambda: True
        self.vm.runtimeToast("Something went wrong", "Details", "details")
        self.assertEqual(self.toasts(), [])
        self.vm.window_active = lambda: False
        self.vm.runtimeToast("Something went wrong", "Details", "details")
        self.assertEqual(self.toasts()[0]["route"], "details")


class AppRescanTest(Base):
    def test_activation_asks_for_a_rescan_unless_blocked(self):
        self.lib.mkdir()
        vm = self.make_app({"library": str(self.lib)})
        calls = []
        vm.rescan = lambda: calls.append(1)
        spy = QSignalSpy(vm.rescanRequested)
        vm.windowActivated()
        self.assertEqual((len(calls), spy.count(), vm.rescan_calls), (1, 1, 1))
        vm.openSettings()
        vm.windowActivated()                                # a panel is open
        vm.closeSettings()
        vm.setRun({"running": True, "series": "Knights"})
        vm.windowActivated()                                # a job writes
        self.assertEqual(len(calls), 1)
        vm.setRun({})
        vm.windowActivated()
        self.assertEqual(len(calls), 2)

    def test_no_rescan_without_a_library(self):
        vm = self.make_app({})
        calls = []
        vm.rescan = lambda: calls.append(1)
        vm.windowActivated()
        self.assertEqual(calls, [])


class AppGeometryTest(Base):
    def test_geometry_is_kept_after_a_pause_and_restored_clamped(self):
        self.lib.mkdir()
        vm = self.make_app({"library": str(self.lib)})
        vm.geometryChanged(120, 90, 1000, 700, False)
        self.assertIsNone(Settings(self.data).get("win", {}).get("geometry"))       # debounced
        vm.flush()
        self.assertEqual(Settings(self.data).get("win")["geometry"], {"x": 120, "y": 90, "w": 1000, "h": 700, "max": False})
        again = self.make_app({"library": str(self.lib), "win": Settings(self.data).get("win")})
        self.assertEqual(again.startGeometry([[0, 0, 1920, 1040]]), {"x": 120, "y": 90, "w": 1000, "h": 700, "max": False})
        out = again.startGeometry([[0, 0, 800, 600]])                              # a smaller screen now
        self.assertTrue(out["w"] <= 800 and out["h"] <= 600 and out["x"] >= 0)

    def test_a_maximized_window_keeps_its_restored_size(self):
        self.lib.mkdir()
        vm = self.make_app({"library": str(self.lib)})
        vm.geometryChanged(120, 90, 1000, 700, False)
        vm.flush()
        vm.geometryChanged(0, 0, 1920, 1040, True)
        vm.flush()
        g = Settings(self.data).get("win")["geometry"]
        self.assertEqual((g["w"], g["h"], g["max"]), (1000, 700, True))

    def test_the_timer_writes_by_itself(self):
        self.lib.mkdir()
        vm = self.make_app({"library": str(self.lib)})
        vm.geometryChanged(10, 20, 900, 600, False)
        self.assertTrue(self.wait_for(lambda: (Settings(self.data).get("win") or {}).get("geometry") is not None, 3))


class FrameModelTest(Base):
    def test_hit_classes(self):
        f = FrameModel()
        f.setRegions(46, [[16, 10, 120, 28], [500, 9, 60, 28], [1000, 6, 34, 34]], [900, 6, 38, 32])
        c = lambda x, y, maxi=False: f.classify(x, y, 1040, 720, maxi, 6)      # noqa: E731
        self.assertEqual(c(300, 20), "caption")
        self.assertEqual(c(520, 20), "client")                 # a step
        self.assertEqual(c(30, 20), "client")                  # the context line
        self.assertEqual(c(910, 20), "max")
        self.assertEqual(c(300, 100), "client")
        self.assertEqual((c(2, 300), c(1038, 300), c(300, 2), c(300, 718)), ("left", "right", "top", "bottom"))
        self.assertEqual((c(2, 2), c(1038, 2), c(2, 718), c(1038, 718)), ("topleft", "topright", "bottomleft", "bottomright"))
        self.assertEqual(c(300, 2, True), "caption")           # maximized: no resize edges
        f.setRegions(46, [], [])                                # the buttons are hidden: no maximize hit, a click goes through
        self.assertEqual(c(910, 20), "caption")

    def test_pointer_facts(self):
        f = FrameModel()
        a, b = QSignalSpy(f.maxHotChanged), QSignalSpy(f.edgeHotChanged)
        f.set_max_hot(True)
        f.set_max_hot(True)
        f.set_edge_hot(True)
        self.assertEqual((a.count(), b.count(), f.maxHot, f.edgeHot), (1, 1, True, True))
        f.set_custom(True)
        self.assertTrue(f.custom)


class FakeServerCase(Base):
    def setUp(self):
        super().setUp()
        self.api = FakeApi(KEYS, invalid_keys=(1,)).start()
        os.environ["NOVELGUI_API_BASE"] = self.api.base_url
        self.lib.mkdir()
        self.lanes = Lanes()

    def tearDown(self):
        self.lanes.close()
        self.api.stop()
        super().tearDown()

    def make_settings(self, keys=(), settings=None):
        self.data.mkdir(parents=True, exist_ok=True)
        if keys:
            (self.data / "keys.json").write_text(json.dumps({"version": 1, "keys": list(keys)}), encoding="utf-8")
        app = self.make_app(dict({"library": str(self.lib)}, **(settings or {})))
        self.ks = keystore.KeyStore(self.data)
        self.winlog = WindowLog(self.local, keys=lambda: list(self.ks.keys))
        app.log = self.winlog
        vm = SettingsVM(app, self.ks, self.lanes, self.local)
        self.vm = vm
        return vm


class SettingsKeysTest(FakeServerCase):
    def test_models_obey_the_item_model_contract(self):
        vm = self.make_settings(KEYS[:2])
        QAbstractItemModelTester(vm.keys, QAbstractItemModelTester.FailureReportingMode.Fatal)
        QAbstractItemModelTester(vm.modelRows, QAbstractItemModelTester.FailureReportingMode.Fatal)
        self.assertEqual(vm.keys.rowCount(), 2)
        self.assertEqual(vm.modelRows.rowCount(), 1)

    def test_keys_are_masked(self):
        vm = self.make_settings(KEYS[:1])
        masked = vm.keys.data(vm.keys.index(0, 0), vm.keys.MASKED)
        self.assertTrue(masked.endswith(KEYS[0][-4:]))
        self.assertNotIn(KEYS[0][:8], masked)

    def test_adding_keys_checks_each_one_with_the_free_call(self):
        vm = self.make_settings()
        spy = QSignalSpy(vm.savedChanged)
        n = vm.addKeys("%s\n%s, %s  short" % (KEYS[0], KEYS[1], KEYS[2]))
        self.assertEqual(n, 3)
        self.assertEqual(vm.saved, "3 keys added · checking…")
        self.assertTrue(self.wait_for(lambda: vm.saved == "Saved"), vm.saved)
        rows = {vm.keys.data(vm.keys.index(i, 0), vm.keys.MASKED)[-4:]: (vm.keys.data(vm.keys.index(i, 0), vm.keys.WORD),
                                                                          vm.keys.data(vm.keys.index(i, 0), vm.keys.RED))
                for i in range(3)}
        self.assertEqual(rows[KEYS[0][-4:]], ("", False))              # ready is not repeated on every row
        self.assertEqual(rows[KEYS[1][-4:]], ("invalid", True))        # the one red
        self.assertEqual(rows[KEYS[2][-4:]], ("", False))
        self.assertEqual(sorted(g["key"] for g in self.api.gets), [0, 1, 2])
        self.assertEqual(self.api.log, [])                             # no translation request, no quota used
        self.assertGreaterEqual(spy.count(), 2)
        self.assertEqual(json.loads((self.data / "keys.json").read_text(encoding="utf-8"))["keys"], KEYS[:3])

    def test_the_invalid_state_has_its_plain_tooltip(self):
        vm = self.make_settings()
        vm.addKeys(KEYS[1])
        self.assertTrue(self.wait_for(lambda: vm.saved == "Saved"))
        self.assertIn("Google does not accept this key", vm.keys.data(vm.keys.index(0, 0), vm.keys.TIP))

    def test_nothing_is_checked_at_start(self):
        self.make_settings(KEYS)
        self.spin(200)
        self.assertEqual(self.api.gets, [])

    def test_pasting_nothing_new_changes_nothing(self):
        vm = self.make_settings(KEYS[:1])
        self.assertEqual(vm.addKeys(KEYS[0]), 0)
        self.assertEqual(vm.addKeys("short"), 0)
        self.assertEqual(vm.saved, "")

    def test_remove_a_key(self):
        vm = self.make_settings(KEYS[:2])
        vm.removeKey(0)
        self.assertEqual(self.ks.keys, KEYS[1:2])
        self.assertEqual(vm.saved, "Saved")

    def test_states_from_the_pool_files(self):
        from novelcore.pool import key_hash
        state = self.lib / "Knights" / ".state"
        state.mkdir(parents=True)
        model = "gemini-3.1-flash-lite"
        pairs = {"%s|%s" % (key_hash(KEYS[1]), model): {"state": "cool", "until": time.time() + 3000},
                 "%s|%s" % (key_hash(KEYS[2]), model): {"state": "day", "until": time.time() + 30000},
                 "%s|%s" % (key_hash(KEYS[3]), model): {"state": "dead", "reason": "invalid key"}}
        (state / "pool.json").write_text(json.dumps({"pairs": pairs}), encoding="utf-8")
        vm = self.make_settings(KEYS)
        vm.refreshStates()
        self.assertTrue(self.wait_for(lambda: vm.keys.data(vm.keys.index(3, 0), vm.keys.RED) is True))
        words = [vm.keys.data(vm.keys.index(i, 0), vm.keys.WORD) for i in range(4)]
        self.assertEqual(words[0], "")
        self.assertTrue(words[1].startswith("paused until"))
        self.assertTrue(words[2].startswith("daily quota until"))
        self.assertEqual(words[3], "invalid")

    def test_a_planted_key_never_reaches_the_log(self):
        vm = self.make_settings()
        vm.addKeys(KEYS[1] + " " + KEYS[0])
        self.assertTrue(self.wait_for(lambda: vm.saved == "Saved"))
        vm.removeKey(0)
        raw = (self.local / "window.log").read_text(encoding="utf-8")
        for k in KEYS:
            self.assertNotIn(k, raw)
        self.app.log.add("something about %s" % KEYS[0], problem=True)
        self.assertNotIn(KEYS[0], (self.local / "window.log").read_text(encoding="utf-8"))
        log = LogVM(self.winlog, keys=lambda: list(self.ks.keys), clipboard=FakeClipboard())
        log.reload()
        for k in KEYS:
            self.assertNotIn(k, log.text())


class SettingsOthersTest(FakeServerCase):
    def test_models_edit_and_persist(self):
        vm = self.make_settings(settings={"models": ["a-model", "b-model"]})
        vm.addModel("c-model")
        vm.addModel("c-model")
        self.assertEqual(self.settings.get("models"), ["a-model", "b-model", "c-model"])
        vm.moveModel(2, -1)
        vm.renameModel(0, "z-model")
        self.assertEqual(self.settings.get("models"), ["z-model", "c-model", "b-model"])
        row = lambda i, role: vm.modelRows.data(vm.modelRows.index(i, 0), role)      # noqa: E731
        self.assertEqual((row(0, vm.modelRows.UP), row(0, vm.modelRows.DOWN)), (False, True))
        self.assertEqual((row(2, vm.modelRows.UP), row(2, vm.modelRows.DOWN)), (True, False))
        vm.removeModel(1)
        vm.removeModel(0)
        vm.removeModel(0)                                    # the last one stays, a message says why
        self.assertEqual(self.settings.get("models"), ["b-model"])
        self.assertIn("last model", self.app.message)
        self.assertEqual(self.vm.saved, "Saved")

    def test_a_model_the_pool_holds_as_not_found(self):
        from novelcore.pool import key_hash
        state = self.lib / "Knights" / ".state"
        state.mkdir(parents=True)
        (state / "pool.json").write_text(json.dumps({"pairs": {"%s|old-model" % key_hash(KEYS[0]):
                                                               {"state": "dead", "reason": "model not found"}}}), encoding="utf-8")
        vm = self.make_settings(KEYS[:1], {"models": ["gemini-3.1-flash-lite", "old-model"]})
        vm.refreshStates()
        self.assertTrue(self.wait_for(lambda: vm.modelRows.data(vm.modelRows.index(1, 0), vm.modelRows.WORD) == "not found"))
        self.assertEqual(vm.modelRows.data(vm.modelRows.index(0, 0), vm.modelRows.WORD), "")

    def test_the_dropdown_offline_or_without_keys_is_only_recommended(self):
        vm = self.make_settings()
        vm.loadGoogle()
        self.spin(100)
        groups = [e["group"] for e in vm.modelEntries("") if "group" in e]
        self.assertEqual(groups, ["RECOMMENDED"])
        self.assertEqual(self.api.gets, [])

    def test_google_list_is_read_once_a_day_with_a_ready_key(self):
        vm = self.make_settings(KEYS[:1])
        spy = QSignalSpy(vm.googleChanged)
        vm.loadGoogle()
        self.assertTrue(self.wait_for(lambda: spy.count() >= 1))
        groups = [e["group"] for e in vm.modelEntries("") if "group" in e]
        self.assertEqual(groups, ["RECOMMENDED", "FROM GOOGLE"])
        self.assertEqual(len(self.api.gets), 1)
        vm.loadGoogle()
        self.spin(150)
        self.assertEqual(len(self.api.gets), 1)                          # cached for a day

    def test_pace(self):
        vm = self.make_settings(settings={"pace": 8})
        self.assertEqual((vm.pace, vm.paceUnit), ("8", "one every 7.5 s"))
        self.assertFalse(vm.setPace("0"))
        self.assertFalse(vm.setPace("121"))
        self.assertFalse(vm.setPace("abc"))
        self.assertEqual(self.settings.get("pace"), 8)
        glow = QSignalSpy(vm.glow)
        self.assertTrue(vm.setPace("12"))
        self.assertEqual((self.settings.get("pace"), vm.pace, glow.at(0)[0]), (12, "12", "pace"))
        self.assertEqual(vm.unitFor("12"), "one every 5 s")
        self.assertEqual(vm.unitFor("500"), "1 to 120")

    def test_saved_line_during_a_run(self):
        vm = self.make_settings()
        self.app.setRun({"running": True, "series": "Knights"})
        vm.setPace("6")
        self.assertEqual(vm.saved, "Saved · applies from the next start")
        self.assertTrue(vm.running)

    def test_saved_line_goes_after_a_while(self):
        vm = self.make_settings()
        vm.setPace("6")
        self.assertEqual(vm.saved, "Saved")
        self.assertTrue(self.wait_for(lambda: vm.saved == "", 5))

    def test_keep_awake_is_stored_on_windows_only(self):
        vm = self.make_settings()
        vm.setKeepAwake(True)
        from novelgui import platform
        self.assertEqual(self.settings.get("keep_awake"), True if platform.IS_WINDOWS else None)
        self.assertEqual(vm.awakeAvailable, platform.IS_WINDOWS)
        if not platform.IS_WINDOWS:
            self.assertEqual(vm.awakeTip, "Not available on this system yet")

    def test_library_row(self):
        vm = self.make_settings()
        self.assertEqual(vm.libraryName, "Novel library")
        self.assertEqual(vm.libraryTip[0], str(self.lib))
        spy = QSignalSpy(self.app.folderDialogRequested)
        vm.changeLibrary()
        self.assertEqual(spy.count(), 1)
        self.app.setRun({"running": True, "series": "Knights"})
        self.assertTrue(vm.running)
        self.assertIn("A job is running", vm.changeTip)
        vm.changeLibrary()
        self.assertEqual(spy.count(), 1)

    def test_app_data_size_is_measured_on_a_lane(self):
        vm = self.make_settings()
        self.local.mkdir(parents=True, exist_ok=True)
        (self.local / "x.bin").write_bytes(b"x" * 3000)
        vm.measureAppData()
        self.assertTrue(self.wait_for(lambda: vm.appDataText != ""))
        self.assertIn("KB", vm.appDataText)

    def test_graphics_auto_releases_a_stuck_software_start(self):
        vm = self.make_settings()
        marks = markers.Markers(self.local)
        marks.write(markers.SOFTWARE)
        vm.setGraphics("software")
        self.assertEqual((vm.graphics, self.settings.get("graphics")), ("software", "software"))
        self.assertTrue(marks.present(markers.SOFTWARE))
        vm.setGraphics("auto")
        self.assertFalse(marks.present(markers.SOFTWARE))
        self.assertEqual(vm.graphics, "auto")
        vm.setGraphics("nonsense")
        self.assertEqual(vm.graphics, "auto")


class LogVMTest(Base):
    def test_lines_filter_copy_and_the_model_contract(self):
        self.data.mkdir(parents=True)
        log = WindowLog(self.local)
        clip = FakeClipboard()
        vm = LogVM(log, clipboard=clip)
        QAbstractItemModelTester(vm.model, QAbstractItemModelTester.FailureReportingMode.Fatal)
        log.add("opened", series="Knights", now=1000)
        log.add("failed", series="Knights", problem=True, now=1001)
        self.assertTrue(self.wait_for(lambda: vm.model.rowCount() == 2))
        vm.setFilter(1)
        self.assertEqual(vm.model.rowCount(), 1)
        vm.setFilter(0)
        vm.copy()
        self.assertEqual(clip.text.count("\n"), 1)
        self.assertIn("Knights · failed", clip.text)

    def test_copy_details(self):
        self.data.mkdir(parents=True)
        log = WindowLog(self.local, keys=lambda: [KEYS[0]])
        clip = FakeClipboard()
        vm = LogVM(log, keys=lambda: [KEYS[0]], clipboard=clip)
        log.add("started", series="Knights")
        vm.copyDetails("1.0", {"series": "Knights", "book": "Book 1", "error": "key %s invalid" % KEYS[0]})
        self.assertIn("Series: Knights", clip.text)
        self.assertNotIn(KEYS[0], clip.text)


if __name__ == "__main__":
    unittest.main()
