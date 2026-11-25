"""Taps, focus and overlays (audit 1, classes 3 and 4): a tap that does one thing, a click through a message, the focus that goes
back to the list when an overlay closes, a whole field box that takes the click, a field that commits when any control is pressed.
Offscreen scenes (tests/qmlharness.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import exportscenes as es  # noqa: E402
from tests import qmlharness as qh  # noqa: E402
from tests import test_books_scenes as tb  # noqa: E402
from tests import test_terms_scenes as tt  # noqa: E402
from tests import translatescenes as ts  # noqa: E402

VM = "tests.shellfactory:make"
WAIT = {"op": "wait", "ms": 400}


def count(r, name):
    return len([v for k, v in r.events if k == name])


def key(k):
    return {"op": "key", "key": k}


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class Overlays(unittest.TestCase):
    def test_return_after_a_menu_closed_does_not_pick_again(self):
        acts = [WAIT, key("Down"), key("Return"), WAIT, key("Return"), key("Return"), WAIT]
        r = qh.scenario("Gallery", {"overlay": "menu"}, actions=acts, tag="menu_return")
        self.assertEqual(count(r, "menuPicked"), 1)

    def test_return_after_a_panel_closed_does_not_accept_it(self):
        acts = [WAIT, key("Escape"), WAIT, key("Return"), WAIT]
        r = qh.scenario("Gallery", {"overlay": "panel"}, actions=acts, tag="panel_return")
        self.assertEqual(count(r, "panelClosed"), 1)
        self.assertEqual(count(r, "panelAccepted"), 0)

    def test_the_arrows_move_the_list_at_once_after_a_drop_down_closes(self):
        acts = [WAIT, {"op": "clickAt", "x": 100, "y": 270}, {"op": "click", "name": "opener"}, WAIT, key("Escape"), WAIT, key("Down")]
        r = qh.scenario("Gallery", actions=acts, tag="dd_focus_back")
        self.assertEqual(count(r, "moveCursor"), 1, "the arrow went to the list, not to the closed drop-down")

    def test_the_arrows_move_the_list_at_once_after_a_panel_closes(self):
        acts = [WAIT, {"op": "clickAt", "x": 100, "y": 270}, {"op": "click", "name": "panelOpener"}, WAIT, key("Escape"), WAIT,
                key("Down")]
        r = qh.scenario("Gallery", actions=acts, tag="panel_focus_back")
        self.assertEqual(count(r, "moveCursor"), 1)

    def test_a_click_on_the_message_veil_does_not_reach_the_screen_below(self):
        acts = [WAIT, {"op": "click", "name": "opener"}, WAIT]
        r = qh.scenario("Gallery", {"overlay": "toast"}, actions=acts, tag="toast_eats")
        self.assertFalse(r.item("dropdown")["visible"], "the drop-down under the message did not open")
        self.assertTrue(r.item("toast")["visible"])

    def test_a_message_that_arrives_while_typing_leaves_the_field_focused(self):
        acts = [{"op": "click", "name": "fieldNormalInput"}, {"op": "type", "text": "ab"}, {"op": "wait", "ms": 1900},
                {"op": "dump", "name": "late"}]
        r = qh.scenario("Gallery", {"toastAfter": True}, actions=acts, tag="toast_focus")
        late = r.after["late"]
        self.assertTrue(late["toast"]["visible"])
        self.assertTrue(late["fieldNormalInput"]["activeFocus"], "the field keeps the keyboard")


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class Taps(unittest.TestCase):
    def test_dots_of_a_series_row_open_the_menu_and_do_not_switch_the_series(self):
        d = tb.lib(tb.knights(), *tb.others(), select=["Knights", "Book 1"])
        acts = [tb.WAIT, {"op": "py", "name": "attr", "args": ["booksVm", "currentSeries"]},
                {"op": "moveTo", "name": "seriesDots3"}, {"op": "wait", "ms": 300}, {"op": "click", "name": "seriesDots3"},
                {"op": "wait", "ms": 400}, {"op": "py", "name": "attr", "args": ["booksVm", "currentSeries"]}]
        r = qh.scenario("ShellScene", d, vm=VM, actions=acts, tag="dots_tap")
        before, after = [v for k, v in r.events if k == "attr"]
        self.assertTrue(r.item("booksMenuCard")["visible"], "the menu opened")
        self.assertEqual(after, before, "the open series did not change")

    def test_the_about_cell_takes_a_single_click_like_the_other_cells(self):
        acts = tt.base({"op": "click", "name": "termAbout_3"}, {"op": "wait", "ms": 300}, tt.py("floatText"))
        r = qh.scenario("ShellScene", tt.lib(), vm=VM, actions=acts, tag="about_single")
        self.assertTrue(r.item("termTable")["activeFocus"], "the list took the focus")
        self.assertTrue(r.item("termReader")["visible"], "the clicked term is the current one: the reader shows it")

    def test_the_about_cell_edits_on_a_double_click(self):
        acts = tt.base({"op": "dclick", "name": "termAbout_3"}, {"op": "wait", "ms": 500})
        r = qh.scenario("ShellScene", tt.lib(), vm=VM, actions=acts, tag="about_double")
        self.assertTrue(r.has("editAbout_3Input"))


def click(name, dx=0, dy=0):
    return {"op": "click", "name": name, "dx": dx, "dy": dy}


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class Fields(unittest.TestCase):
    def test_the_margin_of_a_field_in_a_row_focuses_the_input_and_leaves_the_row_alone(self):
        acts = es.base(es.py("ex_open", "2740-2759"), es.py("ex_state"), click("exFrom3", -28), {"op": "wait", "ms": 300},
                       {"op": "dump", "name": "d"}, es.py("ex_state"))
        r = qh.scenario("ShellScene", es.SCENES["pieces"][0], vm=VM, actions=acts, tag="field_margin")
        s1, s2 = [v for n, v in r.events if n == "ex_state"]
        self.assertTrue(r.after["d"]["exFrom3Input"]["activeFocus"])
        self.assertEqual(s2["ticked"], s1["ticked"], "the press did not toggle the piece")

    def test_the_whole_box_of_a_term_cell_editor_and_a_drop_down_filter_takes_the_click(self):
        acts = tt.base(tt.tv("beginEdit", 5, "about"), {"op": "wait", "ms": 600}, click("termList", 0, 0),
                       tt.tv("beginEdit", 5, "ren"), {"op": "wait", "ms": 600}, {"op": "dump", "name": "d"})
        r = qh.scenario("ShellScene", tt.lib(), vm=VM, actions=acts, tag="cell_box")
        self.assertTrue(r.after["d"]["editRen_5Input"]["activeFocus"])

    def test_typed_export_range_is_taken_when_a_bar_button_is_pressed(self):
        acts = es.base(es.py("ex_open", "2740-2759"), click("exFrom3Input"), {"op": "type", "text": "2750"},
                       click("exBarText0"), {"op": "wait", "ms": 1500}, {"op": "wait", "ms": 1500})
        r = qh.scenario("ShellScene", es.SCENES["pieces"][0], vm=VM, actions=acts, tag="field_bar")
        self.assertEqual(r.item("exFile")["text"], "Knights 2750-2759 ru.epub", "the export used the typed range")

    def test_a_rename_in_books_is_taken_when_another_control_is_pressed(self):
        d = tb.lib(tb.knights(), *tb.others(), select=["Knights", "Book 1"])
        acts = [tb.WAIT, {"op": "py", "name": "rename", "args": ["series", "Gamma"]}, {"op": "wait", "ms": 500},
                {"op": "type", "text": "Zeta"}, click("step_translate"), {"op": "wait", "ms": 800},
                {"op": "py", "name": "seriesTitle", "args": ["Gamma"]}]
        r = qh.scenario("ShellScene", d, vm=VM, actions=acts, tag="rename_press")
        self.assertEqual([v for n, v in r.events if n == "seriesTitle"][-1], "Zeta")

    def test_the_path_box_of_the_first_start_takes_a_click_at_its_edge(self):
        acts = [{"op": "wait", "ms": 700}, click("firstPath", -200), {"op": "wait", "ms": 300}, {"op": "dump", "name": "d"}]
        r = qh.scenario("ShellScene", {"library": "first"}, vm=VM, actions=acts, tag="first_box")
        self.assertTrue(r.after["d"]["firstPathInput"]["activeFocus"])

    def test_a_named_term_is_taken_when_the_slot_loses_the_focus(self):
        pre = [tt.WAIT, tt.sel(), tt.WAIT, tt.py("suggest", tt.names_found()), tt.tv("selectTab", "notconf"), tt.WAIT]
        first = qh.scenario("ShellScene", tt.lib(), vm=VM, actions=pre, tag="slot_find")
        row = next(i for i in range(60) if first.has("termSlot_%d" % i) and first.item("termSlot_%d" % i)["visible"])
        acts = pre + [click("termSlot_%d" % row), {"op": "type", "text": "Zed"}, click("termsBar", 120), {"op": "wait", "ms": 1200}]
        r = qh.scenario("ShellScene", tt.lib(), vm=VM, actions=acts, tag="slot_blur")
        self.assertEqual(first.item("tabCount_notconf")["text"], "43")
        self.assertEqual(r.item("tabCount_notconf")["text"], "42", "the typed name was taken when the focus left the slot")


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class Chips(unittest.TestCase):
    def test_a_double_click_on_a_chip_takes_it_and_opens_the_field_to_type_another(self):
        acts = tt.base({"op": "dclick", "name": "chip_ren_5_0"}, {"op": "wait", "ms": 800})
        r = qh.scenario("ShellScene", tt.lib(), vm=VM, actions=acts, tag="chip_double")
        self.assertTrue(r.has("editRen_5Input"), "the rendering became a field")

    def test_a_single_click_on_a_chip_takes_it_at_once(self):
        acts = tt.base({"op": "click", "name": "chip_ren_5_0"}, {"op": "wait", "ms": 800})
        r = qh.scenario("ShellScene", tt.lib(), vm=VM, actions=acts, tag="chip_single")
        self.assertFalse(r.has("editRen_5Input"))
        self.assertFalse(r.has("chip_ren_5_0") and r.item("chip_ren_5_0")["visible"], "the row is a plain value now")


if __name__ == "__main__":
    unittest.main()
