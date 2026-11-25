"""RowSelection: the selection rules of vtable.py (click / shift / ctrl / drag / keys), pure Python."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelgui.vm.rowselection import RowSelection  # noqa: E402


def make(n=10, selectable=None):
    s = RowSelection(selectable)
    s.set_rows(["r%d" % i for i in range(n)])
    return s


class ClickTest(unittest.TestCase):
    def test_click_selects_one_and_sets_cursor_and_anchor(self):
        s = make()
        s.click(3)
        self.assertEqual(s.selected(), ["r3"])
        self.assertEqual((s.cursor, s.anchor), ("r3", "r3"))
        s.click(5)
        self.assertEqual(s.selected(), ["r5"])

    def test_shift_click_selects_range_from_anchor(self):
        s = make()
        s.click(2)
        s.click(5, shift=True)
        self.assertEqual(s.selected(), ["r2", "r3", "r4", "r5"])
        self.assertEqual(s.anchor, "r2")
        self.assertEqual(s.cursor, "r5")
        s.click(0, shift=True)              # the range follows the anchor, it does not grow
        self.assertEqual(s.selected(), ["r0", "r1", "r2"])

    def test_shift_click_without_anchor_selects_one(self):
        s = make()
        s.click(4, shift=True)
        self.assertEqual(s.selected(), ["r4"])

    def test_ctrl_click_toggles_and_moves_anchor(self):
        s = make()
        s.click(1)
        s.click(4, ctrl=True)
        self.assertEqual(s.selected(), ["r1", "r4"])
        s.click(4, ctrl=True)
        self.assertEqual(s.selected(), ["r1"])
        self.assertEqual(s.anchor, "r4")
        s.click(7, shift=True)              # range from the ctrl anchor replaces the selection
        self.assertEqual(s.selected(), ["r4", "r5", "r6", "r7"])

    def test_outside_rows_is_ignored(self):
        s = make()
        self.assertFalse(s.click(-1))
        self.assertFalse(s.click(99))
        self.assertEqual(s.selected(), [])

    def test_unselectable_rows(self):
        s = make(selectable=lambda r: r != "r3")
        s.click(1)
        self.assertFalse(s.click(3))        # a plain click on it does nothing
        self.assertEqual(s.selected(), ["r1"])
        s.click(5, shift=True)              # ranges skip it
        self.assertEqual(s.selected(), ["r1", "r2", "r4", "r5"])
        s.click(3, ctrl=True)               # ctrl moves the cursor but cannot select it
        self.assertEqual(s.cursor, "r3")
        self.assertNotIn("r3", s.ids)
        s.select_all()
        self.assertEqual(len(s.selected()), 9)

    def test_drag_selects_from_anchor(self):
        s = make()
        s.click(2)
        s.drag(6)
        self.assertEqual(s.selected(), ["r2", "r3", "r4", "r5", "r6"])
        s.drag(4)
        self.assertEqual(s.selected(), ["r2", "r3", "r4"])
        self.assertEqual(s.cursor, "r4")

    def test_drag_without_anchor_does_nothing(self):
        s = make()
        self.assertFalse(s.drag(3))
        self.assertEqual(s.selected(), [])

    def test_context_press(self):
        s = make()
        s.click(1)
        s.click(3, shift=True)
        s.context(2)                        # inside the selection: kept, cursor moves
        self.assertEqual(s.selected(), ["r1", "r2", "r3"])
        self.assertEqual(s.cursor, "r2")
        s.context(7)                        # outside: becomes the selection
        self.assertEqual(s.selected(), ["r7"])


class KeyTest(unittest.TestCase):
    def test_arrows_move_one_row_and_select_it(self):
        s = make()
        s.move(1)                           # no cursor: starts from row 0, goes to row 1
        self.assertEqual(s.selected(), ["r1"])
        s.move(1)
        s.move(-1)
        self.assertEqual(s.selected(), ["r1"])
        self.assertEqual(s.cursor, "r1")

    def test_arrows_clamp(self):
        s = make(3)
        s.move(-5)
        self.assertEqual(s.cursor, "r0")
        s.move(50)
        self.assertEqual(s.cursor, "r2")

    def test_shift_arrows_extend_from_anchor(self):
        s = make()
        s.click(4)
        s.move(1, extend=True)
        s.move(1, extend=True)
        self.assertEqual(s.selected(), ["r4", "r5", "r6"])
        s.move(-3, extend=True)
        self.assertEqual(s.selected(), ["r3", "r4"])

    def test_page_keys_are_moves_by_a_page(self):
        s = make(50)
        s.click(10)
        s.move(12)
        self.assertEqual(s.cursor, "r22")
        s.move(-12, extend=True)
        self.assertEqual(s.selected(), ["r%d" % i for i in range(10, 23)])   # the anchor moved with the plain jump

    def test_home_end(self):
        s = make()
        s.click(5)
        s.home()
        self.assertEqual(s.selected(), ["r0"])
        s.end()
        self.assertEqual(s.selected(), ["r9"])
        s.home(extend=True)
        self.assertEqual(len(s.selected()), 10)

    def test_select_all_keeps_cursor(self):
        s = make()
        s.click(3)
        s.select_all()
        self.assertEqual(len(s.selected()), 10)
        self.assertEqual(s.cursor, "r3")
        self.assertEqual(s.anchor, "r0")

    def test_select_all_sets_cursor_when_none(self):
        s = make()
        s.select_all()
        self.assertEqual(s.cursor, "r0")

    def test_space_toggles_the_cursor_row(self):
        s = make()
        s.click(2)
        self.assertTrue(s.toggle_cursor())
        self.assertEqual(s.selected(), [])
        self.assertTrue(s.toggle_cursor())
        self.assertEqual(s.selected(), ["r2"])

    def test_space_without_cursor_does_nothing(self):
        s = make()
        self.assertFalse(s.toggle_cursor())

    def test_empty_list_is_safe(self):
        s = make(0)
        s.move(1)
        s.home()
        s.end()
        s.select_all()
        self.assertEqual(s.selected(), [])
        self.assertIsNone(s.cursor)


class RowsTest(unittest.TestCase):
    def test_selection_survives_a_new_order(self):
        s = make()
        s.click(2)
        s.click(4, ctrl=True)
        s.set_rows(["r9", "r4", "r2", "r0"])
        self.assertEqual(s.selected(), ["r4", "r2"])
        self.assertEqual(s.cursor, "r4")
        self.assertEqual(s.cursor_index, 1)

    def test_gone_rows_leave_the_selection(self):
        s = make()
        s.click(2)
        s.click(5, shift=True)
        s.set_rows(["r0", "r1", "r4"])
        self.assertEqual(s.selected(), ["r4"])
        self.assertIsNone(s.cursor)
        self.assertIsNone(s.anchor)

    def test_set_selection(self):
        s = make()
        s.set_selection(["r6", "r2", "nope"])
        self.assertEqual(s.selected(), ["r2", "r6"])
        self.assertEqual(s.cursor, "r2")
        s.set_selection([])
        self.assertIsNone(s.cursor)


if __name__ == "__main__":
    unittest.main()
