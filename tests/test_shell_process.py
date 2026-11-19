"""The real main window, offscreen, with the recording tray: closing while a (fake) job runs hides the window to the tray and
the job goes on, the tray brings it back, closing while idle quits, Quit during a run opens the 9.11 panel, the first-time
panel appears once, the focus rescan hook fires on activation, no slot exception or QML warning (strict log). Skipped
without PySide6."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 is not available")
class RealWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", PYTHONUTF8="1", QT_QUICK_CONTROLS_STYLE="Basic",
                   PYTHONPATH=str(REPO))
        if sys.platform == "win32":
            env["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
        proc = subprocess.run([sys.executable, str(REPO / "tests" / "shellchild.py")], cwd=str(REPO), env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
        if not lines:
            raise AssertionError("no result (exit %s)\n%s\n%s" % (proc.returncode, proc.stdout[-1500:], proc.stderr[-1500:]))
        cls.out = json.loads(lines[-1])
        cls.steps = {s["name"]: s for s in cls.out["steps"]}

    def test_no_slot_exception_or_qml_warning(self):
        self.assertEqual(self.out["failures"], [])

    def test_start_shows_the_window_on_the_last_screen_and_the_tray(self):
        s = self.steps["start"]
        self.assertTrue(s["visible"])
        self.assertEqual(s["screen"], "translate")
        self.assertTrue(s["tray_visible"])
        self.assertEqual(s["tray_lines"], [["Nothing running", "dim"]])
        self.assertGreaterEqual(s["rescans"], 1)               # the focus rescan hook ran on activation (14.7)

    def test_first_close_during_a_run_asks_once(self):
        s = self.steps["close_first_time"]
        self.assertTrue(s["visible"])
        self.assertEqual(s["panel"], "trayFirst")
        self.assertTrue(s["running"])

    def test_hidden_window_the_run_goes_on_tray_shows_it_again(self):
        h = self.steps["hidden"]
        self.assertFalse(h["visible"])
        self.assertEqual(h["panel"], "")
        self.assertTrue(h["running"])
        self.assertEqual(h["tooltip"], "Knights · 12 of 54 · ≈ 2 h 10 min left")
        self.assertTrue(self.steps["shown_by_tray"]["visible"])
        self.assertTrue(self.steps["shown_by_tray"]["running"])

    def test_second_close_hides_without_the_panel(self):
        s = self.steps["close_again_hides_at_once"]
        self.assertFalse(s["visible"])
        self.assertEqual(s["panel"], "")
        self.assertEqual(s["events"], [])
        self.assertTrue(self.steps["opened_by_menu"]["visible"])

    def test_quit_from_the_tray_during_a_run_opens_the_panel(self):
        s = self.steps["quit_during_run"]
        self.assertTrue(s["visible"])
        self.assertEqual((s["panel"], s["panel_kind"], s["title"]), ("closing", "running", "Finishing the current requests"))
        self.assertEqual(s["events"], [])

    def test_close_when_idle_quits(self):
        s = self.steps["close_idle"]
        self.assertEqual(s["events"], ["exit"])


if __name__ == "__main__":
    unittest.main()
