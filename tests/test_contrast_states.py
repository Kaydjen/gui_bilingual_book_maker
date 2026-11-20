"""Controls on a surface of nearly their own colour (audit 1, class 2) and rows that look current without a key (class 1):
each state the audit named is read back as a colour, offscreen (tests/qmlharness.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests import test_terms_scenes as tt  # noqa: E402
from tests import translatescenes as ts  # noqa: E402

VM = "tests.shellfactory:make"
HOVER_CLOSE = [{"op": "wait", "ms": 500}, {"op": "moveTo", "name": "panelClose"}, {"op": "wait", "ms": 300}]


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class OnPanel(unittest.TestCase):
    def test_a_flat_button_on_a_panel_hovers_one_step_lighter_than_the_card(self):
        r = qh.scenario("OnPanel", actions=HOVER_CLOSE, tag="flat_hover")
        self.assertEqual(r.item("panelCloseFill")["color"], "#262626")      # Theme.pillOnPanel on the card #171717

    def test_a_flat_button_on_a_hovered_row_stands_out_from_the_row(self):
        r = qh.scenario("FlatRow", actions=[{"op": "wait", "ms": 300}, {"op": "moveTo", "name": "rowFlat"},
                                            {"op": "wait", "ms": 300}], tag="flat_row_hover")
        self.assertEqual(r.item("rowFlatFill")["color"], "#222222")         # Theme.menuOnPanel on the row hover #121212

    def test_a_flat_button_at_rest_has_no_fill(self):
        r = qh.scenario("OnPanel", actions=[{"op": "wait", "ms": 500}], tag="flat_rest")
        self.assertEqual(r.item("panelCloseFill")["color"], "#000000")

    def test_a_list_opened_over_a_panel_is_lighter_than_the_card(self):
        r = qh.scenario("OnPanel", {"menu": True}, actions=[{"op": "wait", "ms": 500}], tag="menu_over")
        self.assertEqual(r.item("menuCard")["color"], "#222222")

    def test_a_tooltip_over_a_panel_is_lighter_than_the_card(self):
        acts = [{"op": "wait", "ms": 500}, {"op": "moveTo", "name": "inTip"}, {"op": "wait", "ms": 1000}]
        r = qh.scenario("OnPanel", actions=acts, tag="tip_over")
        self.assertTrue(r.item("tip")["visible"])
        self.assertEqual(r.item("tip")["color"], "#222222")

    def test_the_message_card_is_lifted_and_its_button_stands_out(self):
        r = qh.scenario("OnPanel", {"toast": True}, actions=[{"op": "wait", "ms": 500}], tag="toast_over")
        self.assertEqual(r.item("toastCard")["color"], "#262626")
        self.assertEqual(r.item("toastButtonFill")["color"], "#303030")

    def test_the_on_track_of_a_switch_is_lighter_than_the_off_track(self):
        r = qh.scenario("OnPanel", actions=[{"op": "wait", "ms": 500}], tag="switch")
        self.assertEqual(r.item("swOnTrack")["color"], "#2a2a2a")
        self.assertEqual(r.item("swOffTrack")["color"], "#0c0c0c")


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class Rows(unittest.TestCase):
    def test_a_chip_on_a_ticked_row_is_one_step_lighter(self):
        plain = qh.scenario("ShellScene", tt.lib(), scale=1.0, vm=VM, actions=tt.base(), tag="chip_plain")
        ticked = qh.scenario("ShellScene", tt.lib(), scale=1.0, vm=VM, actions=tt.base(*tt.tick(5)), tag="chip_ticked")
        self.assertEqual(plain.item("chip_ren_5_0")["color"], "#1c1c1c")
        self.assertEqual(ticked.item("chip_ren_5_0")["color"], "#262626")

    def test_the_time_popover_rings_are_readable(self):
        d, a = ts.SCENES["timepop"]
        r = qh.scenario("ShellScene", d, vm=VM, actions=a, tag="timering")
        ring = r.item("timeRing0")          # the option that is not chosen: its ring is Theme.dim #8a8a8a, not #2e2e2e
        x, y = ring["x"], ring["y"] + ring["h"] / 2
        self.assertGreater(max(r.pixel(x + dx, y)[0] for dx in (0.2, 0.7)), 110)

    def test_a_clicked_chapter_row_of_translate_is_not_left_selected(self):
        d, a = ts.SCENES["ready"]
        acts = a + [{"op": "click", "name": "trTitle2"}, {"op": "moveTo", "name": "trTop"}, {"op": "wait", "ms": 300}]
        r = qh.scenario("ShellScene", d, vm=VM, actions=acts, tag="trrow_click")
        t = r.item("trTitle2")
        self.assertEqual(r.pixel(t["x"] - 2, t["y"] + 15), (10, 10, 10), "the click only feeds Read: no row stays selected")

    def test_the_translate_cursor_row_shows_while_the_keys_move_it(self):
        d, a = ts.SCENES["ready"]
        acts = a + [{"op": "click", "name": "trTitle2"}, {"op": "key", "key": "Down"}, {"op": "moveTo", "name": "trTop"},
                    {"op": "wait", "ms": 300}]
        r = qh.scenario("ShellScene", d, vm=VM, actions=acts, tag="trrow_key")
        t = r.item("trTitle3")
        self.assertEqual(r.pixel(t["x"] - 2, t["y"] + 15), (26, 26, 26))


if __name__ == "__main__":
    unittest.main()
