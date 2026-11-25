"""Pure rules of the window shell (no Qt): steps and header states, the close decision, the tray status lines, the time-left
rounding, geometry clamping, the default library folder, the window log (keys never appear), the key check and Google's
model cache, the settings rules."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelgui import libraryrules  # noqa: E402
from novelgui.ctl import keycheck, settingsrules as sr, shellrules as sh, winlog  # noqa: E402
from tests.fake_api import FakeApi  # noqa: E402

RUN = dict(running=True, series="Knights", book="Book 1", done=12, total=54, left_s=7800, chapter=2703)


class StepsTest(unittest.TestCase):
    def test_digits_follow_the_path_order(self):
        self.assertEqual([sh.step_for_digit(i) for i in (1, 2, 3, 4)], ["books", "terms", "translate", "export"])
        self.assertEqual(sh.step_for_digit(5), "")
        self.assertEqual(sh.step_for_digit(0), "")

    def test_start_screen_is_the_last_one_used(self):
        self.assertEqual(sh.clean_screen("export", True), "export")
        self.assertEqual(sh.clean_screen("nonsense", True), "books")
        self.assertEqual(sh.clean_screen(None, True), "books")
        self.assertEqual(sh.clean_screen("export", False), "books")      # no library: Books

    def test_context_line(self):
        self.assertEqual(sh.context_line("Knights", "Book 1"), "Knights · Book 1")
        self.assertEqual(sh.context_line("Knights", ""), "Knights")
        self.assertEqual(sh.context_line("", "Book 1"), "")

    def test_header_states(self):
        self.assertEqual(sh.header_states(sh.RunInfo()), {"terms": "", "translate": ""})
        self.assertEqual(sh.header_states(sh.RunInfo(terms_red=True))["terms"], "red")
        self.assertEqual(sh.header_states(sh.RunInfo(running=True))["translate"], "wave")
        self.assertEqual(sh.header_states(sh.RunInfo(running=True, needs_user=True))["translate"], "attention")
        self.assertEqual(sh.header_states(sh.RunInfo(failed=True))["translate"], "attention")


class TimeLeftTest(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(sh.round_left(25 * 60), "≈ 25 min")
        self.assertEqual(sh.round_left(25 * 60 + 5), "≈ 26 min")
        self.assertEqual(sh.round_left(59 * 60), "≈ 59 min")
        self.assertEqual(sh.round_left(2 * 3600 + 7 * 60), "≈ 2 h 10 min")
        self.assertEqual(sh.round_left(3600), "≈ 1 h")
        self.assertEqual(sh.round_left(3 * 3600), "≈ 3 h")
        self.assertEqual(sh.round_left(5 * 3600 + 20 * 60), "≈ 5 h")
        self.assertEqual(sh.round_left(5 * 3600 + 40 * 60), "≈ 6 h")
        self.assertEqual(sh.round_left(None), "")

    def test_text(self):
        self.assertEqual(sh.time_left_text(sh.RunInfo(left_s=7800)), "≈ 2 h 10 min left")
        self.assertEqual(sh.time_left_text(sh.RunInfo(left_s=6 * 3600, tomorrow=True)), "≈ 6 h · finishes tomorrow")
        self.assertEqual(sh.time_left_text(sh.RunInfo()), "")


class TrayTest(unittest.TestCase):
    def test_idle(self):
        self.assertEqual(sh.tray_lines(sh.RunInfo()), [("Nothing running", "dim")])
        self.assertEqual([a[0] for a in sh.tray_actions(sh.RunInfo())], ["open", "quit"])

    def test_running_series_name_once(self):
        run = sh.RunInfo(verb="Stop", **RUN)
        self.assertEqual(sh.tray_lines(run), [("Knights", "bright"), ("12 of 54 · ≈ 2 h 10 min left", "dim")])
        self.assertEqual(sh.tray_actions(run), [("verb", "Stop", True), ("open", "Open", True), ("quit", "Quit", True)])
        self.assertEqual(sh.tray_tooltip(run), "Knights · 12 of 54 · ≈ 2 h 10 min left")
        self.assertEqual(sum(t.count("Knights") for t, _ in sh.tray_lines(run)), 1)

    def test_waiting_and_failed(self):
        wait = sh.RunInfo(waiting=True, series="Knights", done=12, total=54, left_s=3600, wake="09:01", verb="Don't resume")
        self.assertEqual(sh.tray_lines(wait)[-1], ("Waits until 09:01", "dim"))
        fail = sh.RunInfo(failed=True, series="Knights", done=12, total=54, reason="Key invalid", verb="Continue",
                          verb_enabled=False)
        self.assertEqual(sh.tray_lines(fail)[-1], ("Key invalid", "red"))
        self.assertEqual(sh.tray_actions(fail)[0], ("verb", "Continue", False))

    def test_translate_tip_names_series_model_keys_pace(self):
        tip = sh.translate_tip(sh.RunInfo(**RUN), model="gemini-3.1-flash-lite", keys=4, pace=5)
        facts = dict(tip[1])
        self.assertEqual(facts["Series"], "Knights")
        self.assertEqual(facts["Model"], "gemini-3.1-flash-lite")
        self.assertEqual(facts["Pace"], "5 requests a minute")


class CloseTest(unittest.TestCase):
    def test_idle_quits(self):
        self.assertEqual(sh.close_decision(sh.RunInfo(), True, False), "quit")
        self.assertEqual(sh.quit_decision(sh.RunInfo()), "quit")

    def test_work_hides_with_a_tray(self):
        run = sh.RunInfo(**RUN)
        self.assertEqual(sh.close_decision(run, True, True), "hide")
        self.assertEqual(sh.close_decision(run, True, False), "hide_first")
        self.assertEqual(sh.close_decision(run, False, True), "panel")
        self.assertEqual(sh.quit_decision(run), "panel")

    def test_a_wait_and_a_queue_count_as_work(self):
        self.assertTrue(sh.RunInfo(waiting=True).busy)
        self.assertTrue(sh.RunInfo(queued=2).busy)
        self.assertFalse(sh.RunInfo(failed=True).busy)

    def test_panels(self):
        p = sh.closing_panel(sh.RunInfo(**RUN))
        self.assertEqual(p["title"], "Finishing the current requests")
        self.assertIn("Knights · chapter 2703", p["text"])
        self.assertEqual((p["cap"], p["close"]), (120, "Close now"))
        w = sh.closing_panel(sh.RunInfo(waiting=True, series="Knights", wake="09:01"))
        self.assertEqual((w["close"], w["action"]), ("Cancel", "Close"))
        self.assertIn("Knights waits for the daily quota until 09:01", w["text"])
        self.assertEqual(sh.countdown_text(118), "up to 1:58")


class GeometryTest(unittest.TestCase):
    SCREENS = [(0, 0, 1920, 1040), (1920, 0, 1280, 1000)]

    def test_inside_is_kept(self):
        g = {"x": 100, "y": 80, "w": 1100, "h": 720, "max": False}
        self.assertEqual(sh.clamp_geometry(g, self.SCREENS), g)

    def test_second_screen_is_kept(self):
        g = {"x": 2000, "y": 50, "w": 1000, "h": 700, "max": False}
        self.assertEqual(sh.clamp_geometry(g, self.SCREENS), g)

    def test_unplugged_screen_goes_to_the_primary(self):
        g = {"x": 2000, "y": 50, "w": 1000, "h": 700, "max": False}
        out = sh.clamp_geometry(g, self.SCREENS[:1])
        self.assertTrue(0 <= out["x"] and out["x"] + out["w"] <= 1920)
        self.assertTrue(0 <= out["y"] and out["y"] + out["h"] <= 1040)
        self.assertEqual((out["w"], out["h"]), (1000, 700))

    def test_too_big_shrinks_and_too_small_grows(self):
        out = sh.clamp_geometry({"x": 0, "y": 0, "w": 5000, "h": 4000, "max": False}, self.SCREENS)
        self.assertEqual((out["w"], out["h"]), (1920, 1040))
        out = sh.clamp_geometry({"x": 10, "y": 10, "w": 100, "h": 100, "max": False}, self.SCREENS)
        self.assertEqual((out["w"], out["h"]), sh.MIN_SIZE)

    def test_nothing_saved_centres_the_default(self):
        out = sh.clamp_geometry(None, self.SCREENS)
        self.assertEqual((out["w"], out["h"]), sh.DEFAULT_SIZE)
        self.assertEqual(out["x"], (1920 - 1100) // 2)
        self.assertEqual(sh.clamp_geometry({"x": "a"}, self.SCREENS)["w"], sh.DEFAULT_SIZE[0])

    def test_maximized_flag_survives(self):
        self.assertTrue(sh.clamp_geometry({"x": 0, "y": 0, "w": 1000, "h": 700, "max": True}, self.SCREENS)["max"])


class DefaultLibraryTest(unittest.TestCase):
    def test_documents_unless_it_is_under_onedrive(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(libraryrules.default_library_path(home), home / "Novel library")
            (home / "Documents").mkdir()
            self.assertEqual(libraryrules.default_library_path(home), home / "Documents" / "Novel library")
            self.assertEqual(libraryrules.default_library_path(home, onedrive=str(home)), home / "Novel library")
            self.assertEqual(libraryrules.default_library_path(home, onedrive=str(home / "Other")),
                             home / "Documents" / "Novel library")


class WinLogTest(unittest.TestCase):
    KEY = "AIzaSyPlantedSecretKey0123456789abcdef"
    PLAIN = "planted-secret-token-0123456789"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_planted_key_never_appears(self):
        log = winlog.WindowLog(self.dir, keys=lambda: [self.PLAIN, self.KEY])
        log.add("request failed for %s: HTTP 400" % self.KEY, series="Knights", problem=True)
        log.add("sent with key=%s&x=1" % self.PLAIN)
        log.add("x-goog-api-key: %s" % "AIzaSyOtherUnknownKey01234567890123")
        log.add("the second key (%s) is invalid" % self.PLAIN)
        raw = (self.dir / winlog.FILE_NAME).read_text(encoding="utf-8")
        for secret in (self.KEY, self.PLAIN, "AIzaSyOtherUnknownKey01234567890123"):
            self.assertNotIn(secret, raw)
        self.assertIn("key 2", raw)                 # the known key by its place in the list
        self.assertIn("key 1", raw)

    def test_read_filter_and_order(self):
        log = winlog.WindowLog(self.dir)
        log.add("one", series="A", now=1000)
        log.add("two", problem=True, now=1001)
        log.add("three", series="B", now=1002)
        e = log.entries()
        self.assertEqual([x.text for x in e], ["one", "two", "three"])
        self.assertEqual([x.text for x in log.entries(problems_only=True)], ["two"])
        self.assertEqual([x.text for x in log.entries(limit=2)], ["two", "three"])
        self.assertTrue(e[0].line().endswith("A · one"))

    def test_tabs_and_new_lines_cannot_split_a_line(self):
        log = winlog.WindowLog(self.dir)
        log.add("a\tb\nc")
        self.assertEqual([x.text for x in log.entries()], ["a b c"])

    def test_rotation(self):
        log = winlog.WindowLog(self.dir)
        old = winlog.MAX_BYTES
        winlog.MAX_BYTES = 300
        try:
            for i in range(40):
                log.add("line %d with some padding text" % i)
        finally:
            winlog.MAX_BYTES = old
        self.assertTrue((self.dir / "window.log.1").exists())
        self.assertLess((self.dir / "window.log").stat().st_size, 1000)

    def test_listener_is_called(self):
        log = winlog.WindowLog(self.dir)
        calls = []
        log.listeners.append(lambda: calls.append(1))
        log.add("x")
        self.assertEqual(calls, [1])

    def test_details_text_scrubs_again(self):
        text = winlog.details_text("1.0", {"series": "Knights", "error": "bad %s" % self.KEY}, ["tail " + self.KEY],
                                   keys=[self.KEY])
        self.assertNotIn(self.KEY, text)
        self.assertIn("Series: Knights", text)
        self.assertIn("Novel 1.0", text)


class KeyCheckTest(unittest.TestCase):
    def setUp(self):
        self.keys = ["good-key-0000000000", "bad-key-00000000000", "region-key-000000000"]
        self.api = FakeApi(self.keys, invalid_keys=(1,), region_blocked=(2,)).start()
        self._saved = {k: os.environ.get(k) for k in ("NOVELGUI_DATA", "NOVELGUI_API_BASE")}

    def tearDown(self):
        self.api.stop()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_states_against_the_fake_server(self):
        self.assertEqual(keycheck.check_key(self.keys[0], self.api.base_url), "ready")
        self.assertEqual(keycheck.check_key(self.keys[1], self.api.base_url), "invalid")
        self.assertEqual(keycheck.check_key(self.keys[2], self.api.base_url), "no access")
        self.assertEqual([g["key"] for g in self.api.gets], [0, 1, 2])
        self.assertEqual(self.api.log, [])           # no translation request: the check costs no quota

    def test_no_connection(self):
        self.assertEqual(keycheck.check_key("k" * 20, "http://127.0.0.1:9", timeout=1), "no connection")

    def test_models_are_filtered(self):
        state, names = keycheck.fetch(self.keys[0], self.api.base_url)
        self.assertEqual(state, "ready")
        self.assertEqual(names, ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"])

    def test_the_real_service_is_never_asked_from_a_check(self):
        os.environ["NOVELGUI_DATA"] = "x"
        os.environ.pop("NOVELGUI_API_BASE", None)
        self.assertIsNone(keycheck.api_base())
        self.assertEqual(keycheck.fetch("k" * 20), ("no connection", []))
        os.environ["NOVELGUI_API_BASE"] = self.api.base_url + "/"
        self.assertEqual(keycheck.api_base(), self.api.base_url)
        os.environ.pop("NOVELGUI_DATA")
        os.environ.pop("NOVELGUI_API_BASE")
        self.assertEqual(keycheck.api_base(), keycheck.DEFAULT_BASE)

    def test_classify(self):
        body = json.dumps({"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid"}}).encode()
        self.assertEqual(keycheck.classify(400, body), "invalid")
        self.assertEqual(keycheck.classify(403, b"{}"), "invalid")
        self.assertEqual(keycheck.classify(429, b"{}"), "ready")
        self.assertEqual(keycheck.classify(503, b"{}"), "ready")

    def test_cache_once_a_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = keycheck.ModelCache(tmp)
            self.assertTrue(cache.due())
            cache.save(["a", "b"])
            self.assertFalse(cache.due())
            self.assertEqual(cache.load()[0], ["a", "b"])
            data = json.loads(cache.path.read_text(encoding="utf-8"))
            data["at"] = time.time() - 2 * 86400
            cache.path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(cache.due())


class SettingsRulesTest(unittest.TestCase):
    def test_pace(self):
        self.assertEqual([sr.clean_pace(x) for x in ("5", " 12 ", "1", "120")], [5, 12, 1, 120])
        self.assertEqual([sr.clean_pace(x) for x in ("0", "121", "x", "", "2.5")], [None] * 5)
        self.assertEqual(sr.pace_unit("5"), "one every 12 s")
        self.assertEqual(sr.pace_unit("7"), "one every 8.6 s")
        self.assertEqual(sr.pace_unit("999"), "1 to 120")

    def test_saved_line(self):
        self.assertEqual(sr.saved_line(False), "Saved")
        self.assertEqual(sr.saved_line(True), "Saved · applies from the next start")
        self.assertEqual(sr.keys_added_line(2), "2 keys added · checking…")
        self.assertEqual(sr.keys_added_line(1), "1 key added · checking…")

    def test_model_list_edits(self):
        self.assertEqual(sr.stored_models(None), [sr.DEFAULT_MODEL])
        self.assertEqual(sr.stored_models(["a", "a", " b ", 3]), ["a", "b"])
        self.assertEqual(sr.move_model(["a", "b", "c"], 1, -1), ["b", "a", "c"])
        self.assertEqual(sr.move_model(["a", "b"], 0, -1), ["a", "b"])
        self.assertEqual(sr.remove_model(["a"], 0), ["a"])
        self.assertEqual(sr.remove_model(["a", "b"], 0), ["b"])
        self.assertEqual(sr.rename_model(["a", "b"], 0, "c"), ["c", "b"])
        self.assertEqual(sr.rename_model(["a", "b"], 0, "b"), ["a", "b"])

    def test_dropdown_entries_offline_is_only_recommended(self):
        e = sr.model_entries(["gemini-3.1-flash-lite"], [])
        self.assertEqual([x.get("group") for x in e if "group" in x], ["RECOMMENDED"])
        self.assertEqual([x["text"] for x in e if "group" not in x], ["gemini-3.5-flash"])

    def test_dropdown_entries_with_google_and_typing(self):
        e = sr.model_entries(["gemini-3.1-flash-lite"], ["gemini-3.5-flash", "gemini-4-pro"])
        self.assertEqual([x.get("group") for x in e if "group" in x], ["RECOMMENDED", "FROM GOOGLE"])
        self.assertTrue([x for x in e if x.get("dim")][0]["text"] == "gemini-4-pro")
        typed = sr.model_entries(["gemini-3.1-flash-lite"], ["gemini-4-pro"], "my-model")
        self.assertEqual(typed[0]["text"], "+ Add my-model")
        self.assertEqual(sr.model_entries([], [], "gemini-4")[0]["text"], "+ Add gemini-4")
        exact = sr.model_entries([], ["gemini-4-pro"], "gemini-4-pro")
        self.assertNotIn(True, [x.get("add") for x in exact])

    def test_sizes(self):
        self.assertEqual([sr.size_text(n) for n in (0, 500, 2048, 3 * 1024 ** 2 + 400000, int(1.2 * 1024 ** 3))],
                         ["0 B", "500 B", "2 KB", "3.4 MB", "1.2 GB"])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a").write_bytes(b"x" * 10)
            (Path(tmp) / "d").mkdir()
            (Path(tmp) / "d" / "b").write_bytes(b"x" * 5)
            self.assertEqual(sr.folder_size(tmp), 15)
        self.assertEqual(sr.folder_size("no/such/folder"), 0)

    def test_library_label(self):
        self.assertEqual(sr.library_label(r"C:\Users\me\Novel library"), "Novel library")
        self.assertEqual(sr.library_label(""), "Not chosen")


if __name__ == "__main__":
    unittest.main()
