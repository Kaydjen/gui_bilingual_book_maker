"""The changed states of the second audit round as pictures at 100 % and 150 % (shots go to NOVELGUI_SHOTS); each scene is also
checked for the things a picture shows at once: no warning, one red at most, black + one red."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests import test_sample_next as sn  # noqa: E402
from tests import test_terms_scenes as tt  # noqa: E402
from tests import translatescenes as ts  # noqa: E402
from tests.translatescenes import tv  # noqa: E402

VM = "tests.shellfactory:make"
LOG = [["a short line", "", 0], ["ERROR request failed: " + "the service gave a long answer " * 8, "Knights", 1]]


def scenes():
    d, a = sn.sample_scene(120)
    yield "sample_next", "ShellScene", d, a, {"vm": VM}
    d2, a2 = ts.SCENES["ready"]
    yield "prompt_undo", "ShellScene", d2, a2 + [tv("promptEdit", True), tv("promptSave", "Short", "t {language}"), {"op": "wait", "ms": 600},
                                                 tv("deletePrompt", "Short"), {"op": "wait", "ms": 600}], {"vm": VM}
    yield "log_wrap_copied", "LogScene", {"library": "ready", "keys": 1, "log": LOG}, [{"op": "wait", "ms": 300}, {"op": "click", "name": "logCopy"},
                                                                                       {"op": "wait", "ms": 200}], {"vm": VM}
    yield "on_panel_menu", "OnPanel", {"menu": True}, [{"op": "wait", "ms": 500}], {}
    yield "on_panel_toast", "OnPanel", {"toast": True}, [{"op": "wait", "ms": 500}], {}
    yield "probes", "Probes", {}, [{"op": "wait", "ms": 300}], {}
    yield "chips_ticked", "ShellScene", tt.lib(), tt.base(*tt.tick(5)), {"vm": VM}
    yield "key_undo", "ShellScene", {"library": "ready", "keys": 2}, [
        {"op": "call", "obj": "appVm", "fn": "openSettings"}, {"op": "wait", "ms": 700}, {"op": "moveTo", "name": "keyRemove0"},
        {"op": "wait", "ms": 200}, {"op": "click", "name": "keyRemove0"}, {"op": "wait", "ms": 500}], {"vm": VM}


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class Shots(unittest.TestCase):
    def test_changed_states_at_both_scales(self):
        for tag, scene, data, acts, kw in scenes():
            for scale in (1.0, 1.5):
                with self.subTest("%s %d%%" % (tag, scale * 100)):
                    r = qh.scenario(scene, data, scale=scale, actions=acts, tag="r1b_" + tag, **kw)
                    self.assertTrue(r.shots["main"].exists())
                    self.assertEqual(qh.stray_colours(r.image()), 0, "black and one red only")


if __name__ == "__main__":
    unittest.main()
