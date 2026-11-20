"""Panels in the smallest window (window_spec 9.1, 10.8): every panel of the window opened at the minimum size
(Theme.minWidth x Theme.minHeight = 820 x 600) at 150 % stays inside the window; the largest panel is found by measuring them
all; a panel whose content does not fit scrolls inside. Offscreen, software scene graph (tests/qmlharness.py)."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import exportscenes as es  # noqa: E402
from tests import qmlharness as qh  # noqa: E402
from tests import test_books_scenes as tb  # noqa: E402
from tests import translatescenes as ts  # noqa: E402

RUN = qh.have_qt()
VM = "tests.shellfactory:make"
THEME = Path(__file__).resolve().parent.parent / "novelgui" / "qml" / "Novel" / "Theme.qml"


def theme_min() -> tuple:
    text = THEME.read_text(encoding="utf-8")
    return tuple(int(re.search(r"int %s: (\d+)" % n, text).group(1)) for n in ("minWidth", "minHeight"))


MIN = theme_min()
OPEN_SETTINGS = [{"op": "call", "obj": "appVm", "fn": "openSettings"}, {"op": "wait", "ms": 700}]
RUNNING = {"running": True, "series": "Knights", "book": "Book 1", "chapter": 2703, "done": 12, "total": 54}
FILES = [{"name": "A - Book %d.epub" % i} for i in range(1, 7)]
DROP = [tb.WAIT, {"op": "dragEnter", "from": "incoming", "x": 500, "y": 300},
        {"op": "drop", "from": "incoming", "x": 500, "y": 300}, {"op": "wait", "ms": 1500}]
SETTINGS = {"library": "ready", "keys": 4, "models": ["gemini-3.1-flash-lite", "gemini-2.0-flash-lite"],
            "screen": "translate", "pool": {"1": ["cool", 3000], "2": ["day", 40000], "3": ["dead", 0]}}
SETTINGS_MANY = dict(SETTINGS, keys=10, models=["m-%d" % i for i in range(6)], pool={})

# card object name -> (scene data, actions)
PANELS = {
    "addCard": (tb.lib(tb.knights(), *tb.others(), incoming=FILES), DROP),
    "moveCard": (tb.lib(tb.knights(books=3), *tb.others(), select=["Knights", "Book 3"]),
                 [tb.WAIT, {"op": "py", "name": "doBook", "args": ["openMove", "Book 3"]}, {"op": "wait", "ms": 500}]),
    "jobCard": ts.SCENES["replacepanel"],
    "jobCard2": ts.SCENES["discardpanel"],
    "jobCard3": ts.SCENES["itempanel"],
    "promptCard": ts.SCENES["promptpanel"],
    "exCard": es.SCENES["ok"],
    "exCard2": es.SCENES["error"],
    "settingsCard": (SETTINGS, OPEN_SETTINGS),
    "settingsCard2": (SETTINGS_MANY, OPEN_SETTINGS),
    "closingCard": ({"library": "ready", "run": RUNNING, "tray": False},
                    [{"op": "call", "obj": "appVm", "fn": "requestClose"}, {"op": "wait", "ms": 500}]),
    "panelCard": ({"library": "missing"}, [{"op": "wait", "ms": 600}]),
}


def importing():
    from tests import test_terms_scenes as tt
    return (tt.lib(), tt.base(tt.py("importGlossaries"), tt.WAIT))


def open_panel(name):
    data, acts = importing() if name == "importCard" else PANELS[name]
    card = name.rstrip("23")
    return card, qh.scenario("ShellScene", data, scale=1.5, vm=VM, actions=acts, size=MIN, tag="min_" + name)


@unittest.skipUnless(RUN, "PySide6 is not available")
class SmallWindow(unittest.TestCase):
    NAMES = list(PANELS) + ["importCard"]
    LISTS = ("settingsCard", "settingsCard2")     # keys and models are lists: the card is cut to the window and scrolls inside

    def test_the_minimum_size_is_the_documented_one(self):
        self.assertEqual(MIN, (820, 600))

    def test_every_panel_stays_inside_the_minimum_window_at_150_percent(self):
        for name in self.NAMES:
            card, r = open_panel(name)
            with self.subTest(name):
                c = r.item(card)
                self.assertTrue(c["visible"], card)
                self.assertGreaterEqual(c["x"], 0)
                self.assertGreaterEqual(c["y"], 0)
                self.assertLessEqual(c["x"] + c["w"], MIN[0] + 0.5)
                self.assertLessEqual(c["y"] + c["h"], MIN[1] + 0.5)
                self.assertEqual(r.image().width(), round(MIN[0] * 1.5))

    def test_the_minimum_window_fits_the_largest_panel(self):
        """The panels are measured at 150 % in the minimum window: none is squeezed (its card is not cut to the window
        height minus the margins) and the largest one still leaves its margin."""
        sizes = {}
        for name in self.NAMES:
            card, r = open_panel(name)
            c = r.item(card)
            sizes[name] = (c["w"], c["h"])
            if name in self.LISTS:
                self.assertEqual(c["h"], MIN[1] - 2 * 20, "%s fills the window and scrolls inside" % name)
                continue
            with self.subTest(name):
                cut = MIN[1] - 2 * 20
                self.assertLess(c["h"], cut, "%s is as tall as the window allows (%s): it would scroll" % (name, c["h"]))
        largest = max((n for n in sizes if n not in self.LISTS), key=lambda n: sizes[n][1])
        w, h = sizes[largest]
        print("largest panel %s: %.0f x %.0f of the minimum window %d x %d" % (largest, w, h, MIN[0], MIN[1]))
        self.assertLessEqual(w, MIN[0] - 40)
        self.assertLessEqual(h, MIN[1] - 40)

    def test_settings_scrolls_to_its_last_row_in_the_minimum_window(self):
        for name in ("settingsCard", "settingsCard2"):
            data, acts = PANELS[name]
            acts = acts + [{"op": "wheel", "name": "settingsCard", "dy": -6000}, {"op": "wait", "ms": 600}]
            r = qh.scenario("ShellScene", data, scale=1.5, vm=VM, actions=acts, size=MIN, tag="min_scroll_" + name)
            c, last = r.item("settingsCard"), r.item("settingsLog")
            with self.subTest(name):
                self.assertLessEqual(last["y"] + last["h"], c["y"] + c["h"] + 0.5, "the last row (Log) can be reached")
                self.assertGreaterEqual(last["y"], c["y"])

    def test_a_panel_with_more_content_than_the_window_scrolls_inside(self):
        acts = [{"op": "wait", "ms": 300}, {"op": "dump", "name": "before"},
                {"op": "wheel", "name": "panelCardBody", "dy": -600}, {"op": "wait", "ms": 500}]
        r = qh.scenario("Gallery", {"overlay": "panel", "tall": True}, scale=1.5, size=MIN, actions=acts, tag="tall")
        c = r.item("panelCard")
        self.assertLessEqual(c["y"] + c["h"], MIN[1] - 20 + 0.5, "the card keeps its margin")
        self.assertGreaterEqual(c["y"], 19.5)
        self.assertEqual(r.after["before"]["panelCardBody"]["contentY"], 0)
        self.assertGreater(r.item("panelCardBody")["contentY"], 0, "the content scrolls")
        foot = r.item("panelAction")
        self.assertLessEqual(foot["y"] + foot["h"], c["y"] + c["h"], "the foot buttons stay inside the card")


@unittest.skipUnless(RUN, "PySide6 is not available")
class TwoHundredPercent(unittest.TestCase):
    """10.8: one scene of every screen at 200 %: it loads without a QML warning or a Python error (the harness fails on
    both) and its key objects lie inside the window."""

    def screens(self):
        from tests import test_terms_scenes as tt
        return {
            "books": (tb.lib(tb.knights(), *tb.others()), [tb.WAIT], ("seriesList", "tableList", "step_books")),
            "terms": (tt.lib(), tt.base(), ("termList", "termFloat", "step_terms")),
            "translate": (ts.SCENES["ready"][0], ts.SCENES["ready"][1], ("trToValue", "trSampleValue", "step_translate")),
            "export": (es.SCENES["pieces"][0], es.SCENES["pieces"][1], ("exList", "exSummary", "step_export")),
            "settings": (SETTINGS, OPEN_SETTINGS, ("settingsCard", "keyList")),
        }

    def test_every_screen_at_200_percent(self):
        for name, (data, acts, keys) in self.screens().items():
            r = qh.scenario("ShellScene", data, scale=2.0, vm=VM, actions=acts, tag="x200_" + name)
            with self.subTest(name):
                self.assertEqual((r.image().width(), r.image().height()), (2080, 1440))
                for k in keys:
                    it = r.item(k)
                    self.assertTrue(it["visible"], k)
                    self.assertGreaterEqual(it["x"], 0, k)
                    self.assertGreaterEqual(it["y"], 0, k)
                    self.assertLessEqual(it["x"] + it["w"], 1040 + 0.5, k)
                    self.assertLessEqual(it["y"] + it["h"], 720 + 0.5, k)
                self.assertLessEqual(r.ambient, 1)


if __name__ == "__main__":
    unittest.main()
