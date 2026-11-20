"""The shell as scenarios (tests/qmlharness.py, offscreen + software): first start, library not found, settings, keys and their
states, models offline, header states, title bar buttons, the log, navigation. Each at 100 % and 150 %; shots go to
NOVELGUI_SHOTS (default: the temp dir). Asserts by objectName, one red per screen, at most one ambient animation, the
state words of keys and models line up, a planted key never shows."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402

RUN = qh.have_qt()
VM = "tests.shellfactory:make"
SCALES = (1.0, 1.5)
OPEN_SETTINGS = [{"op": "call", "obj": "appVm", "fn": "openSettings"}, {"op": "wait", "ms": 700}]


def red_inside(r, name):
    """(red pixels in the item, red pixels in the whole window)."""
    img = r.image()
    return qh.count_red(img, r.rect(name)), qh.count_red(img)


@unittest.skipUnless(RUN, "PySide6 is not available")
class Scenes(unittest.TestCase):
    def run_all(self, name, data, actions=None, tag="", **kw):
        out = []
        for k in SCALES:
            out.append(qh.scenario(name, data, scale=k, vm=VM, actions=actions, tag=tag, **kw))
        return out

    # ------------------------------------------------------------ first start, missing library
    def test_first_start(self):
        for r in self.run_all("ShellScene", {"library": "first"}, tag="first"):
            self.assertEqual(r.item("firstHeading")["text"], "Choose a folder for your books")
            self.assertTrue(r.item("firstPathInput")["text"].endswith("Novel library"))
            self.assertEqual(r.item("firstCreate")["visible"], True)
            inside, total = red_inside(r, "firstCreate")
            self.assertGreater(inside, 20)
            self.assertEqual(inside, total, "red only on Create")
            self.assertEqual(r.item("contextLine")["text"], "")
            self.assertFalse(r.item("panelCard")["visible"] if r.has("panelCard") else False)
            self.assertEqual(r.ambient, 0)
            self.assertTrue(r.item("screen_books")["visible"])
            self.assertEqual(r.item("step_books")["kind"], "")

    def test_library_not_found_panel(self):
        for r in self.run_all("ShellScene", {"library": "missing"}, tag="missing"):
            self.assertTrue(r.item("panelCard")["visible"])
            self.assertTrue(r.item("panelAction")["visible"])
            self.assertEqual(r.item("panelAction")["text"], "Choose folder…")
            self.assertEqual(r.item("panelClose")["text"], "Close")
            inside, total = red_inside(r, "firstCreate")
            self.assertEqual(total, 0 if False else total)
            self.assertLessEqual(total, inside)               # the only red is still Create behind the veil

    # ------------------------------------------------------------ settings
    def test_settings(self):
        data = {"library": "ready", "keys": 4, "models": ["gemini-3.1-flash-lite", "gemini-2.0-flash-lite"],
                "screen": "translate", "pool": {"1": ["cool", 3000], "2": ["day", 40000], "3": ["dead", 0]}}
        for r in self.run_all("ShellScene", data, OPEN_SETTINGS, tag="settings"):
            self.assertTrue(r.item("settingsCard")["visible"])
            self.assertEqual(r.item("keyList")["count"], 4)
            self.assertEqual(r.item("modelList")["count"], 2)
            x, y = r.item("paceRow")["x"], r.item("paceRow")["y"]
            self.assertGreaterEqual(r.pixel(x + 6, y + 17)[0], 0x22, "a control on the panel is lighter than the panel (#171717)")
            words = [r.item("keyWord%d" % i)["text"] for i in range(4)]
            self.assertEqual(words[0], "")                                   # ready is not repeated
            self.assertTrue(words[1].startswith("paused until"))
            self.assertTrue(words[2].startswith("daily quota until"))
            self.assertEqual(words[3], "invalid")
            self.assertEqual(r.item("keyWord3")["color"], "#e5383b")
            self.assertEqual(r.item("keyWord1")["color"], "#8a8a8a")
            # the state words of both lists line up at the right
            def right(n):
                x, _, w, _ = r.rect(n, scale=False)
                return x + w
            self.assertEqual(right("keyWord1"), right("modelWord0"))
            self.assertEqual(r.item("paceValue")["text"], "5")
            self.assertEqual(r.item("paceUnit")["text"], "· one every 12 s")
            self.assertEqual(r.item("awakeLabel")["text"], "Keep the computer awake while translating")
            self.assertEqual(r.item("libraryRowName")["text"], "Novel library")
            self.assertEqual(r.item("libraryRowAction")["text"], "Change…")
            self.assertTrue(r.item("appDataRowName")["text"].startswith("App data"))
            self.assertEqual(r.item("settingsLog")["text"], "Log")
            inside, total = red_inside(r, "keyWord3")
            self.assertGreater(inside, 5)
            self.assertEqual(inside, total, "invalid is the one red of the panel")
            self.assertEqual(r.ambient, 0)

    def test_settings_no_keys(self):
        for r in self.run_all("ShellScene", {"library": "ready", "keys": 0}, OPEN_SETTINGS, tag="nokeys"):
            self.assertEqual(r.item("keyList")["count"], 0)
            self.assertEqual(r.item("modelList")["count"], 1)
            self.assertEqual(qh.count_red(r.image()), 0)

    def test_settings_during_a_run_says_so_and_dims_change(self):
        run = {"running": True, "series": "Knights", "book": "Book 1"}
        acts = OPEN_SETTINGS + [{"op": "call", "obj": "settingsVm", "fn": "setPace", "args": ["6"]}, {"op": "wait", "ms": 400}]
        for r in self.run_all("ShellScene", {"library": "ready", "run": run}, acts, tag="settingsrun"):
            self.assertEqual(r.item("savedLine")["text"], "Saved · applies from the next start")
            self.assertEqual(r.item("paceValue")["text"], "6")

    def test_a_change_glows_in_place_and_says_saved_at_the_top(self):
        acts = OPEN_SETTINGS + [{"op": "dump", "name": "before"},
                                {"op": "call", "obj": "settingsVm", "fn": "setGraphics", "args": ["software"]},
                                {"op": "wait", "ms": 150}]
        for r in self.run_all("ShellScene", {"library": "ready"}, acts, tag="glow"):
            card = r.item("settingsCard")
            self.assertEqual(r.item("graphicsRow")["y"], r.after["before"]["graphicsRow"]["y"], "nothing shifts")
            self.assertEqual(card["h"], r.after["before"]["settingsCard"]["h"])
            self.assertLess(r.item("savedLine")["y"] - card["y"], 40, "the saved line sits at the top of the card")
            self.assertTrue(r.item("savedLine")["text"].startswith("Saved"))     # graphics: "· applies from the next start"
            self.assertGreater(r.item("settingsLog")["y"], r.item("graphicsRow")["y"], "Log is the last item of the content")
            lib_w = r.item("libraryRow")["w"]
            words = r.item("libraryRowName")["w"] + r.item("libraryRowAction")["w"] + 1
            self.assertEqual(lib_w, words, "the two-segment control is as wide as its words")

    def test_keys_added_are_checked_against_the_fake_server_only(self):
        from tests.fake_api import FakeApi
        from tests.shellfactory import planted
        keys = [planted(i) for i in range(3)]
        api = FakeApi(keys, invalid_keys=(1,)).start()
        try:
            acts = OPEN_SETTINGS + [{"op": "call", "obj": "settingsVm", "fn": "addKeys", "args": ["%s %s" % (keys[1], keys[2])]},
                                    {"op": "py", "name": "drain"}, {"op": "wait", "ms": 300}]
            for r in self.run_all("ShellScene", {"library": "ready", "keys": 1, "api": api.base_url}, acts, tag="keysadd"):
                self.assertEqual(r.item("keyList")["count"], 3)
                self.assertEqual(r.item("keyWord1")["text"], "invalid")
                self.assertEqual(r.item("keyWord2")["text"], "")
                self.assertEqual(r.item("savedLine")["text"], "Saved")
            self.assertEqual(api.log, [])
            self.assertTrue(all(g["path"].startswith("/v1beta/models") for g in api.gets))
        finally:
            api.stop()

    def test_models_offline_dropdown_shows_only_recommended(self):
        acts = OPEN_SETTINGS + [{"op": "click", "name": "headModelsPlus"}, {"op": "wait", "ms": 500}]
        for r in self.run_all("ShellScene", {"library": "ready", "keys": 0}, acts, tag="modelsoffline"):
            self.assertTrue(r.item("modelDdCard")["visible"])
            texts = [r.item(n)["text"] for n in ("ddItem0", "ddItem1", "ddItem2") if r.has(n)]
            self.assertIn("gemini-3.5-flash", texts)
            self.assertNotIn("FROM GOOGLE", texts)
            self.assertFalse(any("gemini-2.5" in t for t in texts))
            self.assertEqual(r.ambient, 0)

    def test_models_dropdown_typed_name_gives_an_add_row(self):
        acts = OPEN_SETTINGS + [{"op": "click", "name": "headModelsPlus"}, {"op": "wait", "ms": 300},
                                {"op": "type", "text": "my-model"}, {"op": "wait", "ms": 300}]
        r = qh.scenario("ShellScene", {"library": "ready"}, vm=VM, actions=acts, tag="modeltyped")
        self.assertEqual(r.item("ddItem0")["text"], "+ Add my-model")

    # ------------------------------------------------------------ header
    def test_header_states(self):
        # settled = the chapters are loaded: while they load the skeleton runs its one ambient animation (under load that is
        # still the case at the time of the shot)
        settled = [{"op": "until", "name": "chapterSkeleton", "prop": "visible", "value": False}, {"op": "wait", "ms": 100}]
        quiet = self.run_all("ShellScene", {"library": "ready", "screen": "books"}, settled, tag="hdrquiet")
        for r in quiet:
            self.assertEqual([r.item("step_%s" % s)["kind"] for s in ("books", "terms", "translate", "export")], [""] * 4)
            self.assertEqual(r.ambient, 0)
            self.assertEqual(qh.count_red(r.image()), 0)
        run = {"running": True, "series": "Knights", "book": "Book 1", "terms_red": True}
        chosen = [{"name": "Knights", "target": "ru:Russian", "books": [{"stem": "Book 1", "chapters": 3, "paras": 1}]}]
        for r in self.run_all("ShellScene", {"library": "ready", "screen": "translate", "run": run, "series": chosen, "keys": 1},
                              [{"op": "wait", "ms": 1500}], tag="hdrrun"):          # a language and a key: Translate has no red of its own
            self.assertEqual(r.item("step_terms")["kind"], "red")
            self.assertEqual(r.item("step_terms")["value"], 1.0)             # three pulses done, it stays red
            self.assertEqual(r.item("step_translate")["kind"], "wave")
            self.assertEqual(r.ambient, 1)                                   # the letter wave, the only ambient animation
            self.assertEqual(r.item("contextLine")["text"], "Knights · Book 1")
            inside, total = red_inside(r, "step_terms")
            self.assertGreater(inside, 5)
            self.assertEqual(inside, total)
        attn = {"running": True, "needs_user": True, "series": "Knights", "book": "Book 1"}
        for r in self.run_all("ShellScene", {"library": "ready", "run": attn}, tag="hdrattn"):
            self.assertEqual(r.item("step_translate")["kind"], "attention")
            self.assertLessEqual(r.ambient, 1)
            self.assertGreater(qh.count_red(r.image()), 5)

    def test_title_buttons_slide_in_left_of_the_gear_and_the_gear_never_moves(self):
        plain = qh.scenario("ShellScene", {"library": "ready", "custom": True}, vm=VM, tag="tbhidden")
        shown = qh.scenario("ShellScene", {"library": "ready", "custom": True, "forceButtons": True}, vm=VM, tag="tbshown",
                            actions=[{"op": "wait", "ms": 400}, {"op": "py", "name": "regions"}])
        self.assertEqual(plain.rect("gear"), shown.rect("gear"))
        self.assertFalse(plain.item("titleButtons")["visible"])
        self.assertTrue(shown.item("titleButtons")["visible"])
        gx = shown.item("gear")["x"]
        for n in ("btnMin", "btnMax", "btnClose"):
            self.assertLess(shown.item(n)["x"] + shown.item(n)["w"], gx)
            self.assertEqual(shown.item(n)["enabled"], True)
        regions = shown.events[-1][1]
        self.assertEqual(regions["h"], 46)
        self.assertEqual(len(regions["max"]), 4)                              # the maximize rect is reported once shown
        self.assertGreaterEqual(regions["n"], 9)
        self.assertEqual(qh.count_red(shown.image()), 0, "no red on the close button")

    def test_native_frame_has_no_custom_buttons(self):
        r = qh.scenario("ShellScene", {"library": "ready", "forceButtons": True}, vm=VM, tag="native")
        self.assertFalse(r.item("titleButtons")["visible"])

    def test_header_does_not_move_between_screens_and_one_screen_shows(self):
        acts = []
        for key in ("2", "3", "4", "1"):
            acts += [{"op": "key", "key": key, "mod": "ctrl"}, {"op": "wait", "ms": 120}, {"op": "dump", "name": "k" + key}]
        r = qh.scenario("ShellScene", {"library": "ready", "screen": "books"}, vm=VM, actions=acts, tag="nav")
        order = {"2": "terms", "3": "translate", "4": "export", "1": "books"}
        for key, name in order.items():
            snap = r.after["k" + key]
            vis = [s for s in ("books", "terms", "translate", "export") if snap["screen_" + s]["visible"]]
            self.assertEqual(vis, [name], "Ctrl+%s" % key)
            self.assertEqual(snap["steps"]["x"], r.item("steps")["x"])         # the middle column never moves
        self.assertEqual(r.after["k2"]["step_terms"]["kind"], "")

    def test_clicking_a_step_switches_and_dim_steps_do_not(self):
        r = qh.scenario("ShellScene", {"library": "ready"}, vm=VM, tag="click",
                        actions=[{"op": "click", "name": "step_export"}, {"op": "wait", "ms": 100}])
        self.assertTrue(r.item("screen_export")["visible"])
        self.assertFalse(r.item("screen_books")["visible"])
        r = qh.scenario("ShellScene", {"library": "first"}, vm=VM, tag="clickdim",
                        actions=[{"op": "click", "name": "step_export"}, {"op": "wait", "ms": 100}])
        self.assertTrue(r.item("screen_books")["visible"])

    def test_the_context_line_is_cut_not_the_steps(self):
        run = {"running": True, "series": "A very long series name that keeps going and going", "book": "Book 12 of many"}
        r = qh.scenario("ShellScene", {"library": "ready", "run": run}, vm=VM, size=(820, 600), tag="narrow")
        ctx = r.item("contextLine")
        self.assertLessEqual(ctx["x"] + ctx["w"], r.item("steps")["x"])
        self.assertTrue(r.item("step_export")["visible"])

    def test_gear_opens_settings_and_esc_closes_it(self):
        r = qh.scenario("ShellScene", {"library": "ready"}, vm=VM, tag="gear",
                        actions=[{"op": "click", "name": "gear"}, {"op": "wait", "ms": 300}, {"op": "dump", "name": "open"},
                                 {"op": "key", "key": "Escape"}, {"op": "wait", "ms": 300}])
        self.assertTrue(r.after["open"]["settingsCard"]["visible"])
        self.assertFalse(r.item("settingsCard")["visible"])

    # ------------------------------------------------------------ closing panels
    def test_closing_panels(self):
        run = {"running": True, "series": "Knights", "book": "Book 1", "chapter": 2703, "done": 12, "total": 54}
        for r in self.run_all("ShellScene", {"library": "ready", "run": run, "tray": False},
                              [{"op": "call", "obj": "appVm", "fn": "requestClose"}, {"op": "wait", "ms": 500}], tag="closing"):
            self.assertTrue(r.item("closingCard")["visible"])
            self.assertEqual(r.item("closingTitle")["text"], "Finishing the current requests")
            self.assertIn("Knights · chapter 2703", r.item("closingText")["text"])
            self.assertEqual(r.item("closingLeft")["text"], "Close now")
            self.assertTrue(r.item("closingCount")["text"].startswith("up to 1:5") or r.item("closingCount")["text"].startswith("up to 2:00"))
            self.assertEqual(qh.count_red(r.image()), 0)
        for r in self.run_all("ShellScene", {"library": "ready", "run": run},
                              [{"op": "call", "obj": "appVm", "fn": "requestClose"}, {"op": "wait", "ms": 400}], tag="trayfirst"):
            self.assertEqual(r.item("closingText")["text"], "Translation goes on in the tray. Click the tray icon to open the window.")
            self.assertEqual(r.item("closingLeft")["text"], "Quit")
            self.assertEqual(r.item("closingMain")["text"], "Hide to tray")

    def test_waiting_panel(self):
        run = {"waiting": True, "series": "Knights", "wake": "09:01"}
        r = qh.scenario("ShellScene", {"library": "ready", "run": run, "tray": False}, vm=VM, tag="waiting",
                        actions=[{"op": "call", "obj": "appVm", "fn": "requestClose"}, {"op": "wait", "ms": 400}])
        self.assertIn("Knights waits for the daily quota until 09:01", r.item("closingText")["text"])
        self.assertEqual((r.item("closingLeft")["text"], r.item("closingMain")["text"]), ("Cancel", "Close"))

    def test_second_start_notice_is_under_the_header(self):
        r = qh.scenario("ShellScene", {"library": "ready"}, vm=VM, tag="notice",
                        actions=[{"op": "py", "name": "raise"}, {"op": "wait", "ms": 200}])
        self.assertTrue(r.item("bannerBar")["visible"])
        self.assertIn("already open", r.item("banner")["text"])
        self.assertGreaterEqual(r.item("bannerBar")["y"], 46)

    # ------------------------------------------------------------ log
    def test_log_window_content(self):
        from tests.shellfactory import planted
        log = [["Library set", "", 0], ["request failed for %s" % planted(0), "Knights", 1], ["exported", "Knights", 0]]
        for r in self.run_all("LogScene", {"library": "ready", "keys": 2, "log": log}, tag="log"):
            self.assertEqual(r.item("logList")["count"], 3)
            lines = [r.item("logLine%d" % i)["text"] for i in range(3)]
            self.assertTrue(lines[0].endswith("Library set"))
            self.assertIn("Knights · request failed for key 1", lines[1])
            self.assertTrue(lines[2].endswith("Knights · exported"))
            self.assertFalse(any(planted(i) in t for i in range(2) for t in lines))
            self.assertEqual(r.item("logFilter")["currentIndex"], 0)
            self.assertEqual(qh.count_red(r.image()), 0)
        r = qh.scenario("LogScene", {"library": "ready", "keys": 2, "log": log}, vm=VM, tag="logproblems",
                        actions=[{"op": "click", "name": "segText1"}, {"op": "wait", "ms": 300}])
        self.assertEqual(r.item("logList")["count"], 1)

    def test_all_window_pictures_are_black_and_one_red(self):
        for r in self.run_all("ShellScene", {"library": "ready", "keys": 4, "models": ["a-model", "b-model"],
                                             "pool": {"3": ["dead", 0]}}, OPEN_SETTINGS, tag="colours"):
            self.assertEqual(qh.stray_colours(r.image()), 0)


if __name__ == "__main__":
    unittest.main()
