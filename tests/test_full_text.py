"""Content the user needs but could not read, copy or open (audit 1, class 6) and the feedback of the copy buttons and of a
removed key (class 5, other 1): long names get a tooltip with the whole text only while they are cut, a message line never runs
past its pane, log lines wrap, text of the readers is selectable. Offscreen scenes (tests/qmlharness.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests import translatescenes as ts  # noqa: E402
from tests.translatescenes import tv  # noqa: E402

VM = "tests.shellfactory:make"
LONG = "ERROR request failed: " + "the service answered with a very long explanation of what went wrong " * 4


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class FullText(unittest.TestCase):
    def test_a_cut_text_has_a_tip_with_the_whole_text_and_a_whole_one_has_none(self):
        acts = [{"op": "wait", "ms": 300}, {"op": "moveTo", "name": "cutText"}, {"op": "wait", "ms": 1000}, {"op": "dump", "name": "cut"},
                {"op": "moveTo", "name": "shortText"}, {"op": "wait", "ms": 1000}, {"op": "dump", "name": "short"}]
        r = qh.scenario("Probes", actions=acts, tag="trunc")
        self.assertTrue(r.after["cut"]["tip"]["visible"])
        self.assertEqual(r.after["cut"]["tip"]["text"], "A name that is far too long")
        self.assertFalse(r.after["short"]["tip"]["visible"])

    def test_a_message_line_is_capped_at_its_pane(self):
        r = qh.scenario("Probes", actions=[{"op": "wait", "ms": 300}], tag="msgcap")
        line = r.item("messageLine")
        self.assertLessEqual(line["w"], 300 - 48 + 0.5)
        self.assertEqual(r.item("longMessage")["w"] <= 300, True)

    def test_text_of_a_reader_can_be_selected_with_the_mouse(self):
        acts = [{"op": "wait", "ms": 300}, {"op": "press", "x": 24, "y": 270}, {"op": "moveTo", "x": 140, "y": 270},
                {"op": "release", "x": 140, "y": 270}, {"op": "wait", "ms": 200}]
        r = qh.scenario("Probes", actions=acts, tag="select")
        self.assertGreater(len(r.item("readProbe")["selectedText"]), 5)

    def test_log_lines_wrap_instead_of_being_cut(self):
        log = [["short", "", 0], [LONG, "Knights", 1]]
        r = qh.scenario("LogScene", {"library": "ready", "keys": 1, "log": log}, vm=VM, tag="logwrap")
        self.assertLess(r.item("logLine0")["h"], 30)
        self.assertGreater(r.item("logLine1")["h"], 40, "the long line wraps into several")

    def test_log_copy_says_copied_for_a_moment(self):
        acts = [{"op": "wait", "ms": 300}, {"op": "click", "name": "logCopy"}, {"op": "wait", "ms": 200}, {"op": "dump", "name": "now"},
                {"op": "wait", "ms": 1700}, {"op": "dump", "name": "later"}]
        r = qh.scenario("LogScene", {"library": "ready", "keys": 1, "log": [["a line", "", 0]]}, vm=VM, actions=acts, tag="logcopy")
        self.assertEqual(r.after["now"]["logCopy"]["text"], "Copied")
        self.assertEqual(r.after["later"]["logCopy"]["text"], "Copy")
        self.assertEqual(r.after["later"]["logCopy"]["w"], r.after["now"]["logCopy"]["w"], "the pill keeps its width")


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class Lines(unittest.TestCase):
    def test_the_bottom_bar_stays_while_the_prompt_undo_line_shows_above_it(self):
        d, a = ts.SCENES["ready"]
        acts = a + [tv("promptEdit", True), tv("promptSave", "Short", "t {language}"), {"op": "wait", "ms": 600},
                    tv("deletePrompt", "Short"), {"op": "wait", "ms": 600}]
        r = qh.scenario("ShellScene", d, vm=VM, actions=acts, tag="undo_above_bar")
        self.assertTrue(r.item("trUndo")["visible"])
        self.assertTrue(r.item("trBar")["visible"], "the bar stays usable")
        undo, bar = r.item("trUndo"), r.item("trBar")
        self.assertLessEqual(undo["y"] + undo["h"], bar["y"] + 1, "the undo line is above the bar")

    def test_a_removed_key_has_an_undo_line(self):
        data = {"library": "ready", "keys": 2}
        acts = [{"op": "call", "obj": "appVm", "fn": "openSettings"}, {"op": "wait", "ms": 700}, {"op": "moveTo", "name": "keyRemove0"},
                {"op": "wait", "ms": 200}, {"op": "click", "name": "keyRemove0"}, {"op": "wait", "ms": 400}, {"op": "dump", "name": "gone"},
                {"op": "click", "name": "keyUndoBarText0"}, {"op": "wait", "ms": 400}, {"op": "dump", "name": "back"}]
        r = qh.scenario("ShellScene", data, vm=VM, actions=acts, tag="keyundo")
        self.assertEqual(r.after["gone"]["keyList"]["count"], 1)
        self.assertTrue(r.after["gone"]["keyUndo"]["visible"])
        self.assertEqual(r.after["back"]["keyList"]["count"], 2)
        self.assertFalse(r.after["back"]["keyUndo"]["visible"])


if __name__ == "__main__":
    unittest.main()
