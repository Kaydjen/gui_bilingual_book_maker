"""Wheel acceleration of the list scroll assist (novelgui/qml/Novel/ScrollAssist.qml) as scenarios (tests/qmlharness.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests.test_books_scenes import WAIT, knights, lib  # noqa: E402

RUN = qh.have_qt()
VM = "tests.shellfactory:make"
DATA = lib(knights(chapters=400, translated=0))


def notch(dy=-120):
    return {"op": "wheel", "name": "tableList", "dy": dy}


def wait(ms):
    return {"op": "wait", "ms": ms}


def dump(name):
    return {"op": "dump", "name": name}


def notches(n, gap, dy=-120):
    acts = []
    for _ in range(n):
        acts += [notch(dy), wait(gap)]
    return acts


@unittest.skipUnless(RUN, "PySide6 is not available")
class WheelScenes(unittest.TestCase):
    def run_acts(self, tag, acts):
        return qh.scenario("ShellScene", DATA, scale=1.0, vm=VM, actions=[WAIT] + acts, tag=tag)

    def y(self, r, name):
        return r.after[name]["tableList"]["contentY"]

    def test_one_notch_glides_a_short_way(self):
        r = self.run_acts("scroll_one", [notch(), wait(100), dump("mid"), wait(900), dump("end"), wait(200)])
        self.assertTrue(0 < self.y(r, "mid") < 24, "gliding, not jumping: %s" % self.y(r, "mid"))
        self.assertAlmostEqual(r.item("tableList")["contentY"], 24, delta=1)
        self.assertEqual(self.y(r, "end"), r.item("tableList")["contentY"], "the glide has stopped")

    def test_fast_streak_goes_far_slow_notches_do_not_accelerate(self):
        fast = self.run_acts("scroll_fast", notches(10, 10) + [wait(2000)])
        self.assertGreaterEqual(fast.item("tableList")["contentY"], 700)
        slow = self.run_acts("scroll_slow", notches(10, 400) + [wait(1000)])
        self.assertAlmostEqual(slow.item("tableList")["contentY"], 240, delta=1)

    def test_direction_change_turns_at_once(self):
        r = self.run_acts("scroll_turn", notches(5, 30) + [dump("before"), notch(1200), wait(1200)])
        self.assertLess(r.item("tableList")["contentY"], self.y(r, "before"))

    def test_end_of_list_clamps_exactly(self):
        r = self.run_acts("scroll_end", notches(60, 20, -240) + [wait(2000), dump("end"), wait(300)])
        lst = r.item("tableList")
        self.assertEqual(self.y(r, "end"), lst["contentY"], "no bounce")
        self.assertLess(lst["contentY"], lst["contentHeight"])
        again = self.run_acts("scroll_end2", notches(60, 20, -240) + [wait(2000), dump("end")] + notches(10, 20, -240) + [wait(1500)])
        self.assertEqual(again.item("tableList")["contentY"], lst["contentY"], "more notches at the end do not move it")


if __name__ == "__main__":
    unittest.main()
