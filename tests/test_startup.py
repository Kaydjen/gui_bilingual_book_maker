import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path


class StartupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BBM_GUI_DATA"] = self._tmp.name

    def tearDown(self):
        os.environ.pop("BBM_GUI_DATA", None)
        self._tmp.cleanup()

    def test_saved_known_language_prompt_without_memory(self):
        """A saved prompt that is a shipped template, with no prompt_by_lang, must not break the start."""
        from bbm_gui import app as appmod, promptset
        template = next(t for t in promptset.templates() if t["tag"] == "ru")
        path = promptset.ensure_template(template)
        (Path(self._tmp.name) / "settings.json").write_text(
            json.dumps({"prompt": path, "to": "Russian"}), encoding="utf-8")
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        root.withdraw()
        try:
            a = appmod.App(root)
            self.assertEqual(a.settings["prompt_by_lang"].get("ru"), path)
            root.update()
            a.root.after_cancel(a._save_job) if a._save_job else None
        finally:
            root.destroy()

    def test_resume_cache_warning_is_not_shown(self):
        from bbm_gui import app as appmod, runner
        line = ("Warning: the resume cache C:/jobs/Book-ab12-single-ru/.Book.temp.bin was written before runs recorded "
                "their language, prompt and model, so none of them can be checked. If this command differs from the one "
                "that wrote it, delete the cache instead of resuming.")
        self.assertTrue(runner.NOISE.search(line))
        self.assertFalse(runner.NOISE.search("Retry attempt 1 due to boom (rotating key)"))
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        root.withdraw()
        try:
            a = appmod.App(root)
            before = a.log.get("1.0", "end")
            a._on_output("out", "line", line)
            self.assertEqual(a.log.get("1.0", "end"), before)
            a._on_output("out", "line", "Some other engine line")
            self.assertIn("Some other engine line", a.log.get("1.0", "end"))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
