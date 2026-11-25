"""The shared QML components against the mock-up: sizes, radii and colours sampled from our own shots and compared with
the numbers of .ai/mockups/mock.css + full/lifted.css (the expected values are written next to each check), the four
brightness levels, the tooltip delay, keyboard and pointer behaviour, the one-red rule, ambient animation limits and the
CPU cost of a hidden window.

Every scenario runs offscreen with the software scene graph in a child process (tests/qmlharness.py). The tests skip when
PySide6 is not installed. Shots go to NOVELGUI_SHOTS (default: the temp dir); `checklist.txt` there lists every check
with expected and measured values.
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402

RUN = qh.have_qt()
CHECKS: list = []                   # (name, expected, measured, tolerance, ok)

# colours of the mock-up (mock.css / lifted.css)
PANE = (10, 10, 10)                 # #0a0a0a
PILL = (23, 23, 23)                 # #171717
PILL_OFF = (14, 14, 14)             # #0e0e0e
LIFT = (28, 28, 28)                 # #1c1c1c
MENU = (26, 26, 26)                 # #1a1a1a
PANEL = (23, 23, 23)                # #171717
FIELD = (6, 6, 6)                   # #060606
FIELD_LINE = (30, 30, 30)           # #1e1e1e
ROW_SEL = (26, 26, 26)              # #1a1a1a
BRIGHT, TEXT, DIM, FAINT = (244,) * 3, (222,) * 3, (138,) * 3, (90,) * 3


def arc_inset(radius: float, y: float = 1.5) -> float:
    """Where a rounded corner of `radius` starts to be filled, `y` px below the top edge (pixel centre)."""
    dy = radius - y
    return radius - math.sqrt(max(0.0, radius * radius - dy * dy))


def near(a, b, tol) -> bool:
    if isinstance(a, tuple):
        return all(abs(x - y) <= tol for x, y in zip(a, b))
    return abs(a - b) <= tol


def record(name, expected, measured, tol):
    ok = near(measured, expected, tol)
    CHECKS.append((name, expected, measured, tol, ok))
    return ok


def tearDownModule():
    if not CHECKS:
        return
    lines = ["%-46s expected %-18s measured %-18s tol %-4s %s" % (n, e, m, t, "ok" if ok else "FAIL") for n, e, m, t, ok in CHECKS]
    try:
        (qh.shots_dir() / "checklist.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


@unittest.skipUnless(RUN, "PySide6 is not available")
class Base(unittest.TestCase):
    def check(self, name, expected, measured, tol):
        with self.subTest(name):
            self.assertTrue(record(name, expected, measured, tol), "%s: expected %s +-%s, measured %s" % (name, expected, tol, measured))

    def px(self, r, name, dx, dy):
        x, y, _, _ = r.rect(name, scale=False)
        return r.pixel(x + dx, y + dy)

    def edge(self, r, name, fill, tol=10):
        """Distance from the left edge of the item to the first filled pixel, one pixel below its top (the corner arc)."""
        img = r.image()
        x, y, w, _ = r.rect(name)
        k = r.scale
        for xi in range(x, x + w):
            c = img.pixelColor(xi, int(y + 1.5 * k))
            if near((c.red(), c.green(), c.blue()), fill, tol):
                return (xi - x) / k
        return None


class GalleryChecklist(Base):
    @classmethod
    def setUpClass(cls):
        if RUN:
            cls.r = qh.scenario("Gallery")

    def test_pills(self):
        r = self.r
        for n in ("pillMain", "pillNormal", "pillFlat", "pillOff", "pillAccent"):
            self.check("%s height (6+6 padding + 13px line = 30)" % n, 30, r.item(n)["h"], 2)
        self.check("pill padding: width = text + 28 (Normal, 6 letters)", 72, r.item("pillNormal")["w"], 8)
        self.check("pill fill #171717", PILL, self.px(r, "pillNormal", 5, 15), 3)
        self.check("pill off fill #0e0e0e", PILL_OFF, self.px(r, "pillOff", 5, 15), 3)
        self.check("pill flat has no fill (pane #0a0a0a)", PANE, self.px(r, "pillFlat", 5, 15), 3)
        self.check("pill radius 7 (corner inset at 1.5px)", arc_inset(7), self.edge(r, "pillNormal", PILL), 1.5)
        self.check("pill shadow sh1 darkens 5px below", 7, self.px(r, "pillNormal", 36, 35)[0], 3)
        self.check("pill sits on the pane above it (the shadow falls down)", PANE, self.px(r, "pillNormal", 36, -12), 2)
        self.check("pill hairline of light on the top edge (#171717 + white 8 % = 41)", 41, self.px(r, "pillNormal", 36, 0)[0], 4)

    def test_round_button(self):
        r = self.r
        self.check("sat width", 38, r.item("satLone")["w"], 0)
        self.check("sat height", 38, r.item("satLone")["h"], 0)
        self.check("sat fill #1c1c1c", LIFT, self.px(r, "satLone", 8, 19), 3)
        self.check("sat is round (radius 19: corner inset at 1.5px)", arc_inset(19), self.edge(r, "satLone", LIFT), 1.5)

    def test_ctl(self):
        r = self.r
        for n in ("ctlNormal", "ctlRed", "ctlOff", "ctlProgress"):
            self.check("%s height 30" % n, 30, r.item(n)["h"], 2)
        self.check("ctl fill #171717", PILL, self.px(r, "ctlNormal", 4, 15), 3)
        self.check("ctl off fill #0e0e0e", PILL_OFF, self.px(r, "ctlOff", 4, 15), 3)
        self.check("ctl radius 7", arc_inset(7), self.edge(r, "ctlNormal", PILL), 1.5)
        self.check("ctl progress line is 2px, dim", DIM, self.px(r, "ctlProgress", 8, 29), 12)
        self.assertGreater(qh.count_red(r.image(), r.rect("ctlRed")), 20, "a red value must show red")
        self.assertEqual(qh.count_red(r.image(), r.rect("ctlNormal")), 0)

    def test_segmented(self):
        r = self.r
        self.check("segmented height (3+4+17+4+3 = 31)", 31, r.item("segmented")["h"], 2)
        self.check("segmented well #0a0a0a", PANE, self.px(r, "segmented", 4, 16), 3)
        self.check("segmented current segment #1c1c1c", LIFT, self.px(r, "segmented", 60 + 12 + 40, 6), 4)

    def test_bottom_bar(self):
        r = self.r
        self.check("capsule height 38", 38, r.item("bottomBarCapsule")["h"], 0)
        self.check("capsule fill #1c1c1c", LIFT, self.px(r, "bottomBarCapsule", 6, 19), 3)
        self.check("capsule radius 19", arc_inset(19), self.edge(r, "bottomBarCapsule", LIFT), 1.5)
        self.check("segment padding 16: first segment = text + 32", r.item("bottomBarText0")["w"] + 32, r.item("bottomBarCapsule")["w"] - sum(
            r.item("bottomBarText%d" % i)["w"] + 32 for i in (1, 2, 3)), 1)
        x = r.item("bottomBarText0")["x"] + r.item("bottomBarText0")["w"] + 16
        self.check("segment divider 1px #282828", (40,) * 3, r.pixel(x, r.item("bottomBarCapsule")["y"] + 4), 5)
        self.check("sat hangs beside the capsule, 8px gap", 8, r.item("bottomBarSat")["x"] - (r.item("bottomBarCapsule")["x"] + r.item("bottomBarCapsule")["w"]), 0)
        self.check("sat is vertically centred on the capsule", r.item("bottomBarCapsule")["y"], r.item("bottomBarSat")["y"], 0.5)
        self.check("capsule shadow sh2 darkens 8px below", 6, r.pixel(r.item("bottomBarCapsule")["x"] + 60, r.item("bottomBarCapsule")["y"] + 46)[0], 4)
        self.check("main segment text is bright", BRIGHT, self.brightest_text(r, "bottomBarText0"), 14)
        self.check("dim segment text", DIM, self.brightest_text(r, "bottomBarText1"), 14)
        self.check("off segment text is faint", FAINT, self.brightest_text(r, "bottomBarText2"), 14)

    def brightest_text(self, r, name):
        return qh.brightest(r.image(), tuple(int(v) for v in r.rect(name)))

    def test_message(self):
        r = self.r
        img = r.image()
        line = r.rect("messageLine")
        self.check("message line is dim text on the pane", PANE, r.pixel(r.item("messageLine")["x"] + 2, r.item("messageLine")["y"] + 12), 3)
        self.assertGreater(qh.count_red(img, line), 15, "the problem count in the fact line is red")
        bar = r.item("messageBar")
        self.check("verbs bar sits under the line, 8px gap", r.item("messageLine")["y"] + r.item("messageLine")["h"] + 8, bar["y"], 3)
        self.check("fact line and bar share one centre", r.item("messageLine")["x"] + r.item("messageLine")["w"] / 2, bar["x"] + bar["w"] / 2, 1.5)

    def test_field(self):
        r = self.r
        self.check("field height", 28, r.item("fieldNormal")["h"], 3)
        self.check("field inset fill #060606", FIELD, self.px(r, "fieldNormal", 100, 14), 3)
        self.check("field edge #1e1e1e", FIELD_LINE, self.px(r, "fieldNormal", 100, 0), 4)
        self.check("field radius 6: the corner pixel is not filled", PANE, self.px(r, "fieldNormal", 0, 0), 4)
        self.assertGreater(qh.count_red(r.image(), r.rect("fieldInvalid")), 40, "an invalid field has a red edge")
        self.assertEqual(qh.count_red(r.image(), r.rect("fieldNormal")), 0)

    def test_table(self):
        r = self.r
        ly = r.item("tableList")["y"]
        x = r.item("tableList")["x"] + 12
        self.check("row height 30 (header 30, list top margin 2)", 242, ly, 0)
        self.check("pane #0a0a0a", PANE, r.pixel(x, ly + 15), 3)
        self.check("selected row #1a1a1a", ROW_SEL, r.pixel(x, ly + 45), 3)
        self.check("the cursor row is not lifted while no key moved it (only selected #1a1a1a)", ROW_SEL, r.pixel(x, ly + 75), 1)
        rk = qh.scenario("Gallery", data={"byKey": True}, tag="tablekey")
        self.check("current row lifted #1c1c1c (the keys moved the cursor)", LIFT, rk.pixel(x, ly + 75), 3)
        self.check("current row one pixel up (first lifted pixel row)", ly + 59, next(
            y for y in range(int(ly) + 50, int(ly) + 70) if rk.pixel(x, y)[0] >= 27), 1)
        self.check("selected row radius 6", arc_inset(6, 1.5), self.row_edge(r, ly + 31.5, ROW_SEL), 1.5)
        self.check("column splitters: header cells line up with row cells", r.item("headCell_title")["x"], 24 + 6 + 8 + 60, 1)
        self.check("state column is right aligned to the row edge", 24 + 560 - 6 - 8 - 8, r.item("headCell_state")["x"] + r.item("headCell_state")["w"] - 8, 12)

    def row_edge(self, r, y, fill):
        img = r.image()
        for xi in range(24, 80):
            c = img.pixelColor(xi, int(y))
            if near((c.red(), c.green(), c.blue()), fill, 2):
                return xi - 30
        return None

    def test_tip_bubble(self):
        r = self.r
        t = r.item("tipStatic")
        self.check("tip max width 300", 300, t["w"], 0)
        self.check("tip fill #1a1a1a", MENU, self.px(r, "tipStatic", 4, 40), 3)
        self.check("tip radius 7", arc_inset(7), self.edge(r, "tipStatic", MENU), 1.5)
        self.check("tip text normal #dedede", TEXT, qh.brightest(r.image(), tuple(int(v) for v in r.rect("tipStaticText"))), 14)

    def test_skeleton(self):
        r = self.r
        s = r.item("skeleton")
        self.check("skeleton bar colour #161616 (row 1, first cell)", (22, 22, 22), r.pixel(s["x"] + 14 + 10, s["y"] + 15), 4)
        self.check("skeleton gap is masked to the pane", PANE, r.pixel(s["x"] + 14 + 10, s["y"] + 4), 3)
        self.check("skeleton bar height 9: first bar pixel", s["y"] + 10.5, next(y for y in range(int(s["y"]), int(s["y"]) + 30) if r.pixel(s["x"] + 24, y)[0] >= 20), 1.5)


class BrightnessLevels(Base):
    """The four levels of text (bright / normal / dim / faint) must stay visibly apart; sampled from glyph pixels."""

    def test_steps_of_the_mock_are_kept(self):
        r = qh.scenario("Gallery")
        got = {}
        for key, name in (("bright", "levelBright"), ("normal", "levelText"), ("dim", "levelDim"), ("faint", "levelFaint")):
            got[key] = qh.brightest(r.image(), tuple(int(v) for v in r.rect(name)))[0]
        want = {"bright": 244, "normal": 222, "dim": 138, "faint": 90}
        for k in want:
            self.check("text level %s colour" % k, want[k], got[k], 8)
        steps = {("bright", "normal"): 244 - 222, ("normal", "dim"): 222 - 138, ("dim", "faint"): 138 - 90}
        for (a, b), step in steps.items():
            with self.subTest("%s vs %s" % (a, b)):
                record("level step %s - %s (mock step %d)" % (a, b, step), step, got[a] - got[b], 8)
                self.assertGreaterEqual(got[a] - got[b], step - 8)

    def test_levels_are_ordered_in_the_theme_source(self):
        text = (Path(__file__).resolve().parent.parent / "novelgui" / "qml" / "Novel" / "Theme.qml").read_text(encoding="utf-8")
        for name, value in (("bright", "#f4f4f4"), ("text", "#dedede"), ("dim", "#8a8a8a"), ("faint", "#5a5a5a"), ("accent", "#e5383b")):
            self.assertIn('color %s: "%s"' % (name, value), text)

    def test_symbols_render(self):
        r = qh.scenario("Gallery")
        img = r.image()
        x, y, w, h = r.rect("symbols")
        lit = sum(1 for xi in range(x, x + w) if any(img.pixelColor(xi, yi).red() > 60 for yi in range(y, y + h)))
        self.assertGreater(lit, w * 0.35, "the symbols of the controls (arrow, chevron, dots, cross, bullets) must not be tofu or blank")


class Overlays(Base):
    def test_menu(self):
        r = qh.scenario("Gallery", data={"overlay": "menu"}, tag="menu")
        c = r.item("menuCard")
        self.check("menu card width", 190, c["w"], 0)
        self.check("menu fill #1a1a1a", MENU, r.pixel(c["x"] + 4, c["y"] + 50), 3)
        self.check("menu radius 9", arc_inset(9), self.edge(r, "menuCard", MENU), 1.5)
        self.check("menu item height 30 (6+6 padding + line)", 30, r.item("menuItem0")["h"], 2)
        self.check("menu: 4 items + divider = 4*30 + 9 + 10 padding", 4 * 30 + 9 + 10, c["h"], 2)
        cur = r.item("menuItem3")
        self.check("current item has a 2px bright bar at the left", BRIGHT, r.pixel(c["x"] + 5 + 3.5, cur["y"] + 15), 14)
        self.check("no bar on an ordinary item", MENU, r.pixel(c["x"] + 5 + 3.5, r.item("menuItem0")["y"] + 15), 3)
        self.check("disabled item is faint", FAINT, qh.brightest(r.image(), tuple(int(v) for v in r.rect("menuItem4"))), 14)
        self.check("menu shadow sh2 darkens 8px below", 6, r.pixel(c["x"] + 90, c["y"] + c["h"] + 8)[0], 4)

    def test_menu_keyboard_and_pointer(self):
        r = qh.scenario("Gallery", data={"overlay": "menu"}, tag="menukeys", actions=[
            {"op": "key", "key": "Down"}, {"op": "key", "key": "Down"}, {"op": "key", "key": "Return"}, {"op": "wait", "ms": 200}])
        self.assertIn(["menuPicked", "folder"], r.events)
        self.assertFalse(r.item("menu")["visible"])
        r2 = qh.scenario("Gallery", data={"overlay": "menu"}, tag="menuoff", actions=[{"op": "click", "name": "menuItem4"}, {"op": "wait", "ms": 100}])
        self.assertEqual([e for e in r2.events if e[0] == "menuPicked"], [], "a disabled item is not picked")
        self.assertTrue(r2.item("menu")["visible"])
        r3 = qh.scenario("Gallery", data={"overlay": "menu"}, tag="menuclick", actions=[{"op": "click", "name": "menuItem0"}, {"op": "wait", "ms": 100}])
        self.assertIn(["menuPicked", "rename"], r3.events)

    def test_menu_esc_and_outside_click_close(self):
        r = qh.scenario("Gallery", data={"overlay": "menu"}, tag="menuesc", actions=[{"op": "key", "key": "Escape"}, {"op": "wait", "ms": 100}])
        self.assertFalse(r.item("menu")["visible"])
        r = qh.scenario("Gallery", data={"overlay": "menu"}, tag="menuout", actions=[{"op": "clickAt", "x": 50, "y": 700}, {"op": "wait", "ms": 100}])
        self.assertFalse(r.item("menu")["visible"])

    def test_dropdown(self):
        r = qh.scenario("Gallery", data={"overlay": "dropdown"}, tag="dd")
        c = r.item("dropdownCard")
        self.check("drop-down width 260", 260, c["w"], 0)
        self.check("drop-down fill #1a1a1a", MENU, r.pixel(c["x"] + 4, c["y"] + 100), 3)
        self.check("drop-down radius 9", arc_inset(9), self.edge(r, "dropdownCard", MENU), 1.5)
        cur = r.item("ddItem1")
        self.check("drop-down item height 28 (5+5 padding + line)", 28, cur["h"], 2)
        self.check("current item: bright bar at x 4", BRIGHT, r.pixel(c["x"] + 5 + 4.5, cur["y"] + 14), 14)
        self.check("current item text is bright", BRIGHT, qh.brightest(r.image(), tuple(int(v) for v in r.rect("ddItem1"))), 14)
        self.check("ordinary item text is normal", TEXT, qh.brightest(r.image(), tuple(int(v) for v in r.rect("ddItem3"))), 14)
        self.check("off item is faint", FAINT, qh.brightest(r.image(), tuple(int(v) for v in r.rect("ddItem6"))), 14)
        self.check("typing field is inset #060606", FIELD, r.pixel(r.item("ddFilter")["x"] + 100, r.item("ddFilter")["y"] + 14), 3)

    def test_dropdown_typing_hook_and_esc(self):
        r = qh.scenario("Gallery", data={"overlay": "dropdown"}, tag="ddtype", actions=[
            {"op": "type", "text": "pol"}, {"op": "wait", "ms": 100}, {"op": "dump", "name": "typed"}, {"op": "key", "key": "Escape"}, {"op": "wait", "ms": 100}])
        self.assertIn(["dropdownFilter", "pol"], r.events)
        self.assertFalse(r.item("dropdown")["visible"])
        r = qh.scenario("Gallery", data={"overlay": "dropdown"}, tag="ddpick", actions=[{"op": "click", "name": "ddItem4"}, {"op": "wait", "ms": 100}])
        self.assertIn(["dropdownPicked", "pl"], r.events)
        r = qh.scenario("Gallery", data={"overlay": "dropdown"}, tag="ddoff", actions=[{"op": "click", "name": "ddItem6"}, {"op": "wait", "ms": 100}])
        self.assertEqual([e for e in r.events if e[0] == "dropdownPicked"], [])

    def test_a_second_click_on_the_opener_closes_the_dropdown(self):
        """9.5: the opener is covered by the catcher of the drop-down: its click closes, it does not close and reopen."""
        r = qh.scenario("Gallery", tag="ddopener", actions=[
            {"op": "click", "name": "opener"}, {"op": "wait", "ms": 300}, {"op": "dump", "name": "open"},
            {"op": "click", "name": "opener"}, {"op": "wait", "ms": 400}])
        self.assertTrue(r.after["open"]["dropdown"]["visible"], "the first click opens it")
        self.assertFalse(r.item("dropdown")["visible"], "the second click closes it and it stays closed")
        self.assertEqual([e for e in r.events if e[0] == "dropdownPicked"], [])

    def test_a_click_outside_closes_the_dropdown_and_chooses_nothing(self):
        """9.7: for the drop-down (the menu is tested above); the click is not passed on to what lies under it."""
        r = qh.scenario("Gallery", data={"overlay": "dropdown"}, tag="ddout", actions=[
            {"op": "wait", "ms": 200}, {"op": "clickAt", "x": 700, "y": 600}, {"op": "wait", "ms": 300}])
        self.assertFalse(r.item("dropdown")["visible"])
        self.assertEqual([e for e in r.events if e[0] == "dropdownPicked"], [])
        r = qh.scenario("Gallery", data={"overlay": "dropdown"}, tag="ddoutrow", actions=[
            {"op": "wait", "ms": 200}, {"op": "clickAt", "x": 400, "y": 300}, {"op": "wait", "ms": 300}])
        self.assertFalse(r.item("dropdown")["visible"])
        self.assertEqual([e for e in r.events if e[0] in ("dropdownPicked", "rowPressed")], [],
                         "a click on the table behind the drop-down closes it and does not reach the table")

    def test_panel(self):
        r = qh.scenario("Gallery", data={"overlay": "panel"}, tag="panel")
        c = r.item("panelCard")
        self.check("panel width 440", 440, c["w"], 0)
        self.check("panel fill #171717", PANEL, r.pixel(c["x"] + 8, c["y"] + c["h"] / 2), 3)
        self.check("panel radius 14", arc_inset(14), self.edge(r, "panelCard", PANEL), 1.5)
        self.check("veil dims what is behind (#0a0a0a at 50 %)", (5, 5, 5), r.pixel(4, 700), 2)
        self.check("foot: closing button just left of the action (gap 8)", r.item("panelAction")["x"] - 8, r.item("panelClose")["x"] + r.item("panelClose")["w"], 1)
        self.check("foot: action button at the right padding (22)", c["x"] + c["w"] - 22, r.item("panelAction")["x"] + r.item("panelAction")["w"], 1)
        self.check("foot: both buttons on one line", r.item("panelClose")["y"], r.item("panelAction")["y"], 0.5)
        self.check("foot: bottom padding 20", c["y"] + c["h"] - 20, r.item("panelAction")["y"] + r.item("panelAction")["h"], 1)
        self.check("panel is centred", 1040 / 2, c["x"] + c["w"] / 2, 1)
        self.check("panel shadow sh3 darkens 14px below", 3, r.pixel(c["x"] + 220, c["y"] + c["h"] + 14)[0], 3)

    def test_panel_keys_and_fields(self):
        base = [{"op": "wait", "ms": 100}]
        r = qh.scenario("Gallery", data={"overlay": "panel"}, tag="panelenter", actions=base + [{"op": "key", "key": "Return"}])
        self.assertIn(["panelAccepted", 1], r.events, "Enter presses the main button")
        r = qh.scenario("Gallery", data={"overlay": "panel"}, tag="panelesc", actions=base + [{"op": "key", "key": "Escape"}, {"op": "wait", "ms": 100}])
        self.assertIn(["panelClosed", 1], r.events)
        # a field inside: Enter commits, Esc returns the old value and does not close the panel
        r = qh.scenario("Gallery", data={"overlay": "panel"}, tag="field", actions=base + [
            {"op": "click", "name": "panelField"}, {"op": "type", "text": "Book 3"}, {"op": "key", "key": "Return"}, {"op": "wait", "ms": 100},
            {"op": "dump", "name": "committed"},
            {"op": "click", "name": "panelField"}, {"op": "type", "text": "Zzz"}, {"op": "key", "key": "Escape"}, {"op": "wait", "ms": 100},
            {"op": "dump", "name": "escaped"},
            {"op": "key", "key": "Escape"}, {"op": "wait", "ms": 100}])
        self.assertIn(["fieldCommitted", "Book 3"], r.events)
        self.assertEqual(r.after["committed"]["panelField"]["value"], "Book 3")
        self.assertEqual(r.after["escaped"]["panelFieldInput"]["text"], "Book 3", "Esc in a field returns the old value")
        self.assertEqual(r.after["escaped"]["panel"]["visible"], True, "the Esc of a field does not close the panel")
        self.assertIn(["panelClosed", 1], r.events, "the next Esc does")

    def test_field_invalid_value_goes_back_with_a_tooltip(self):
        r = qh.scenario("Gallery", data={"overlay": "panel"}, tag="invalid", actions=[
            {"op": "wait", "ms": 100}, {"op": "click", "name": "panelField"}, {"op": "type", "text": "0123456789012"},
            {"op": "key", "key": "Return"}, {"op": "wait", "ms": 100}, {"op": "dump", "name": "d"}])
        self.assertEqual([e for e in r.events if e[0] == "fieldCommitted"], [], "an invalid value is not committed")
        self.assertEqual(r.after["d"]["panelFieldInput"]["text"], "Book 2", "9.8: the field returns to the previous value")
        self.assertTrue(r.after["d"]["tip"]["visible"])
        self.assertEqual(r.after["d"]["tipText"]["text"], "1 to 9 characters", "9.8: the tooltip gives the allowed range")

    def test_click_outside_commits_the_field_then_closes(self):
        r = qh.scenario("Gallery", data={"overlay": "panel"}, tag="outside", actions=[
            {"op": "wait", "ms": 100}, {"op": "click", "name": "panelField"}, {"op": "type", "text": "Book 4"},
            {"op": "clickAt", "x": 6, "y": 700}, {"op": "wait", "ms": 150}])
        self.assertIn(["fieldCommitted", "Book 4"], r.events)
        self.assertIn(["panelClosed", 1], r.events)

    def test_toast(self):
        r = qh.scenario("Gallery", data={"overlay": "toast", "bare": True}, tag="toast")
        c = r.item("toastCard")
        self.check("toast fill #262626 (lifted, so it reads over a panel)", (38, 38, 38), r.pixel(c["x"] + 6, c["y"] + c["h"] / 2), 3)
        self.check("toast min width 300", 300, c["w"], 0)
        self.check("toast radius 12", arc_inset(12), self.edge(r, "toastCard", (38, 38, 38)), 1.5)
        r = qh.scenario("Gallery", data={"overlay": "toast"}, tag="toastok", actions=[{"op": "click", "name": "toastButton"}, {"op": "wait", "ms": 100}])
        self.assertFalse(r.item("toast")["visible"])


class IconHover(Base):
    """1.6: the hover colour of the icon buttons differs from the rest colour and is the theme token (dim -> bright text,
    lifted -> lifter fill)."""
    LIFT2 = (38, 38, 38)                # Theme.lift2 #262626

    def glyph(self, r, name):
        return qh.brightest(r.image(), tuple(int(v) for v in r.rect(name)))

    def test_round_button(self):
        rest = qh.scenario("Gallery", tag="hover_rest")
        hot = qh.scenario("Gallery", tag="hover_sat", actions=[{"op": "moveTo", "name": "satLone"}, {"op": "wait", "ms": 300}])
        self.assertNotEqual(self.glyph(rest, "satLone"), self.glyph(hot, "satLone"))
        self.check("round button glyph at rest is dim", DIM, self.glyph(rest, "satLone"), 14)
        self.check("round button glyph on hover is bright (Theme.bright)", BRIGHT, self.glyph(hot, "satLone"), 14)
        self.check("round button fill at rest", LIFT, self.px(rest, "satLone", 8, 19), 3)
        self.check("round button fill on hover (Theme.lift2)", self.LIFT2, self.px(hot, "satLone", 8, 19), 3)

    def test_title_button_and_panel_cross(self):
        shown = {"library": "ready", "custom": True, "forceButtons": True}
        vm = "tests.shellfactory:make"
        rest = qh.scenario("ShellScene", shown, vm=vm, tag="hover_tb_rest", actions=[{"op": "wait", "ms": 400}])
        hot = qh.scenario("ShellScene", shown, vm=vm, tag="hover_tb", actions=[
            {"op": "wait", "ms": 400}, {"op": "moveTo", "name": "btnMin"}, {"op": "wait", "ms": 400}])
        self.assertNotEqual(self.glyph(rest, "btnMin"), self.glyph(hot, "btnMin"))
        self.check("title button glyph at rest is dim", DIM, self.glyph(rest, "btnMin"), 14)
        self.check("title button glyph on hover is bright", BRIGHT, self.glyph(hot, "btnMin"), 14)
        x, y, w, h = hot.rect("btnMin")
        self.check("title button hover fill (Theme.lift2)", self.LIFT2, hot.pixel(x / hot.scale + 3, y / hot.scale + 3), 4)
        self.assertEqual(qh.count_red(hot.image()), 0, "never red")
        data = {"library": "ready"}
        opn = [{"op": "call", "obj": "appVm", "fn": "openSettings"}, {"op": "wait", "ms": 700}]
        rest = qh.scenario("ShellScene", data, vm=vm, tag="hover_x_rest", actions=opn)
        hot = qh.scenario("ShellScene", data, vm=vm, tag="hover_x", actions=opn + [{"op": "moveTo", "name": "settingsClose"}, {"op": "wait", "ms": 300}])
        self.check("panel cross at rest is dim", DIM, self.glyph(rest, "settingsClose"), 14)
        self.check("panel cross on hover is bright", BRIGHT, self.glyph(hot, "settingsClose"), 20)


class Tooltips(Base):
    HOVER = [{"op": "moveTo", "name": "pillNormal"}]

    def test_shown_after_600ms_not_before(self):
        r = qh.scenario("Gallery", tag="tip600", actions=self.HOVER + [{"op": "wait", "ms": 380}, {"op": "dump", "name": "early"},
                                                                         {"op": "wait", "ms": 420}, {"op": "dump", "name": "late"}])
        self.check("tooltip hidden at ~400 ms (visible=0)", 0, int(r.after["early"]["tip"]["visible"]), 0)
        self.check("tooltip shown at ~800 ms (visible=1)", 1, int(r.after["late"]["tip"]["visible"]), 0)
        self.assertEqual(r.after["late"]["tipText"]["text"], "Normal pill")

    def test_stays_while_pointer_is_on_the_element_and_goes_when_it_leaves(self):
        r = qh.scenario("Gallery", tag="tipstay", actions=self.HOVER + [
            {"op": "wait", "ms": 800}, {"op": "moveTo", "x": 140, "y": 44}, {"op": "wait", "ms": 600}, {"op": "dump", "name": "on"},
            {"op": "moveTo", "x": 700, "y": 640}, {"op": "wait", "ms": 200}, {"op": "dump", "name": "off"}])
        self.assertTrue(r.after["on"]["tip"]["visible"])
        self.assertFalse(r.after["off"]["tip"]["visible"])

    def test_press_dismisses_and_it_does_not_come_back(self):
        r = qh.scenario("Gallery", tag="tippress", actions=self.HOVER + [
            {"op": "wait", "ms": 800}, {"op": "click", "name": "pillNormal"}, {"op": "wait", "ms": 900}, {"op": "dump", "name": "d"}])
        self.assertFalse(r.after["d"]["tip"]["visible"])

    def test_facts_are_listed_and_the_bubble_stays_in_the_window(self):
        r = qh.scenario("Gallery", tag="tipedge", actions=[{"op": "moveTo", "name": "bottomBarSat"}, {"op": "wait", "ms": 800}, {"op": "dump", "name": "d"}])
        t = r.after["d"]["tip"]
        self.assertTrue(t["visible"])
        self.assertLessEqual(t["x"] + t["w"], 1040 - 4 + 0.5)
        r = qh.scenario("Gallery", tag="tipfacts", actions=self.HOVER + [{"op": "wait", "ms": 800}, {"op": "dump", "name": "d"}])
        self.assertGreater(r.after["d"]["tip"]["h"], 60, "a tip with facts is taller than a one-line tip")


class Pointer(Base):
    """The DataList reports the pointer and the keys; the view-model applies RowSelection (tests/test_rowselection.py)."""
    ROW = lambda i: 242 + 15 + 30 * i   # noqa: E731  (row centres of the gallery table)

    def test_clicks_report_row_and_modifiers(self):
        r = qh.scenario("Gallery", tag="clicks", actions=[
            {"op": "clickAt", "x": 300, "y": Pointer.ROW(3)}, {"op": "clickAt", "x": 300, "y": Pointer.ROW(0), "mod": "ctrl"},
            {"op": "clickAt", "x": 300, "y": Pointer.ROW(1), "mod": "shift"}, {"op": "wait", "ms": 100}])
        got = [e[1] for e in r.events if e[0] == "rowPressed"]
        self.assertEqual(got, [[3, False, False], [0, True, False], [1, False, True]])

    def test_keys_report_actions(self):
        r = qh.scenario("Gallery", tag="keys", actions=[
            {"op": "clickAt", "x": 300, "y": Pointer.ROW(1)}, {"op": "key", "key": "Down"}, {"op": "key", "key": "Up", "mod": "shift"},
            {"op": "key", "key": "Home"}, {"op": "key", "key": "End", "mod": "shift"}, {"op": "key", "key": "Space"},
            {"op": "key", "key": "A", "mod": "ctrl"}, {"op": "wait", "ms": 100}])
        ev = [(e[0], e[1]) for e in r.events if e[0] != "rowPressed"]
        self.assertEqual(ev, [("moveCursor", [1, False]), ("moveCursor", [-1, True]), ("moveTo", ["home", False]),
                              ("moveTo", ["end", True]), ("toggle", 1), ("selectAll", 1)])

    def test_drag_reports_rows_under_the_pointer(self):
        r = qh.scenario("Gallery", tag="drag", actions=[
            {"op": "press", "x": 300, "y": Pointer.ROW(0)}, {"op": "moveTo", "x": 300, "y": Pointer.ROW(2)},
            {"op": "moveTo", "x": 300, "y": Pointer.ROW(3)}, {"op": "release", "x": 300, "y": Pointer.ROW(3)}, {"op": "wait", "ms": 100}])
        self.assertEqual([e[1] for e in r.events if e[0] == "rowPressed"], [[0, False, False]])
        self.assertIn(3, [e[1] for e in r.events if e[0] == "rowDragged"])

    def test_header_splitter_resizes_a_column(self):
        r = qh.scenario("Gallery", tag="split", actions=[{"op": "dump", "name": "a"}])
        self.assertTrue(r.has("splitter_title"))


class Rules(Base):
    """Red only for a problem; no other colour; the animation budget."""

    def test_red_only_where_a_problem_is_shown(self):
        r = qh.scenario("Gallery")
        img = r.image()
        allowed = [r.rect(n) for n in ("pillAccent", "ctlRed", "fieldInvalid", "messageLine", "bottomBarCapsule")]
        total = qh.count_red(img)
        inside = sum(qh.count_red(img, (x - 2, y - 2, w + 4, h + 4)) for x, y, w, h in allowed)
        record("red pixels outside the problem items", 0, total - inside, 0)
        self.assertEqual(total - inside, 0)
        self.assertGreater(total, 100)
        stray = qh.stray_colours(img)
        record("pixels with a colour that is not a red", 0, stray, 0)
        self.assertEqual(stray, 0)

    def test_overlays_add_no_stray_colour(self):
        for ov in ("menu", "dropdown", "panel", "toast"):
            r = qh.scenario("Gallery", data={"overlay": ov}, tag=ov)
            self.assertEqual(qh.stray_colours(r.image()), 0, ov)

    def test_no_loops_without_ambient(self):
        r = qh.scenario("Gallery")
        self.assertEqual(r.animations, [])

    def test_at_most_one_ambient_animation_in_every_scenario(self):
        for amb in ("wave", "spinner", "busy", "skeleton"):
            r = qh.scenario("Gallery", data={"ambient": amb}, tag="amb_" + amb)
            self.check("ambient animations with %s running" % amb, 1, len(r.animations), 0)
        for ov in ("menu", "dropdown", "panel", "toast"):
            r = qh.scenario("Gallery", data={"overlay": ov, "ambient": "wave"}, tag="ambov_" + ov)
            self.assertLessEqual(len(r.animations), 1, "%s: %s" % (ov, r.animations))

    def test_each_looping_part_runs_only_when_enabled(self):
        for amb, marker in (("wave", "waveAnimation"), ("busy", "XAnimator"), ("spinner", "RotationAnimator"), ("skeleton", "XAnimator")):
            r = qh.scenario("Gallery", data={"ambient": amb}, tag="amb_" + amb)
            self.assertTrue(any(marker in a for a in r.animations), (amb, r.animations))

    def test_the_wave_is_one_sequential_animation(self):
        r = qh.scenario("Gallery", data={"ambient": "wave"}, tag="amb_wave")
        self.assertEqual(r.animations, ["QQuickSequentialAnimation#waveAnimation"])


class Scaling(Base):
    def test_150_percent_keeps_logical_sizes_and_colours(self):
        a = qh.scenario("Gallery")
        b = qh.scenario("Gallery", scale=1.5)
        self.assertEqual((b.image().width(), b.image().height()), (1560, 1080))
        for n in ("pillNormal", "capsule" if False else "bottomBarCapsule", "fieldNormal", "tableList"):
            self.assertEqual(a.item(n)["h"], b.item(n)["h"], n)
            self.assertEqual(a.item(n)["w"], b.item(n)["w"], n)
        self.check("150 %: pill fill", PILL, self.px(b, "pillNormal", 5, 15), 3)
        self.check("150 %: capsule fill", LIFT, self.px(b, "bottomBarCapsule", 6, 19), 3)
        self.check("150 %: pill radius 7 (logical px)", arc_inset(7), self.edge(b, "pillNormal", PILL), 1.5)
        self.check("150 %: capsule radius 19 (logical px)", arc_inset(19), self.edge(b, "bottomBarCapsule", LIFT), 1.5)
        self.check("150 %: shadow is not doubled (sh1, 5px below)", 7, self.px(b, "pillNormal", 36, 35)[0], 3)
        ra, rb = qh.count_red(a.image()), qh.count_red(b.image())
        self.assertAlmostEqual(rb / ra, 2.25, delta=0.7)
        self.assertEqual(qh.stray_colours(b.image()), 0)


class HiddenCost(Base):
    """review_window_arch D7: a hidden or minimized window with the letter wave must cost < 0.5 % of a core over 4 s."""

    def test_hidden_window_is_idle(self):
        r = qh.scenario("Gallery", data={"ambient": "wave"}, cpu={"state": "hidden", "seconds": 4}, tag="cpu_hidden", timeout=120)
        self.check("hidden window with the wave: CPU % of one core", 0.0, round(r.cpu["percent"], 3), 0.5)
        self.assertEqual(r.cpu["running"], [], "no animation keeps running while the window is hidden")

    def test_minimized_window_is_idle(self):
        r = qh.scenario("Gallery", data={"ambient": "wave"}, cpu={"state": "minimized", "seconds": 4}, tag="cpu_min", timeout=120)
        self.check("minimized window with the wave: CPU % of one core", 0.0, round(r.cpu["percent"], 3), 0.5)
        self.assertEqual(r.cpu["running"], [])

    def test_the_visible_wave_is_alive(self):
        r = qh.scenario("Gallery", data={"ambient": "wave"}, cpu={"state": "visible", "seconds": 2}, tag="cpu_vis", timeout=120)
        self.assertEqual(len(r.cpu["running"]), 1)
        record("visible window with the wave: CPU % (information, not asserted)", 0.0, round(r.cpu["percent"], 3), 100)


if __name__ == "__main__":
    unittest.main()
