import os
import tempfile
import types
import unittest

from bbm_gui import glossary as gl
from bbm_gui import langs, promptset


class SaveNameTest(unittest.TestCase):
    """PromptWindow._free_save_name: a prompt and glossary of the same name that was not opened here is not overwritten."""

    def setUp(self):
        from bbm_gui import prompt_win

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BBM_GUI_DATA"] = self._tmp.name
        self.cls = prompt_win.PromptWindow

    def tearDown(self):
        os.environ.pop("BBM_GUI_DATA", None)
        self._tmp.cleanup()

    def window(self, opened=None):
        w = types.SimpleNamespace()
        if opened:
            w._path = opened
        w._taken = lambda name: self.cls._taken(w, name)
        return w

    def save(self, name):
        return promptset.PromptSet(name, "own system", "{text}", [gl.Entry("a", "b")], "Polish", True, "", "", "pl").save()

    def test_free_name_is_kept(self):
        self.assertEqual(self.cls._free_save_name(self.window(), "mine"), "mine")

    def test_taken_name_gets_a_suffix_unless_it_is_the_open_prompt(self):
        mine = self.save("prompt")
        self.assertEqual(self.cls._free_save_name(self.window(), "prompt"), "prompt_2")
        self.save("prompt_2")
        self.assertEqual(self.cls._free_save_name(self.window(), "prompt"), "prompt_3")
        self.assertEqual(self.cls._free_save_name(self.window(str(mine)), "prompt"), "prompt")
        other = self.save("other")
        self.assertEqual(self.cls._free_save_name(self.window(str(other)), "prompt"), "prompt_3")
        (promptset.glossaries_dir() / "lonely.json").write_text("{}", encoding="utf-8")  # a glossary alone counts
        self.assertEqual(self.cls._free_save_name(self.window(), "lonely"), "lonely_2")


class BusyGuardTest(unittest.TestCase):
    """App: nothing is swapped, and nothing continues by itself with a problem, while a job is in progress."""

    def stub(self, **kw):
        from bbm_gui import app

        s = types.SimpleNamespace(runner=types.SimpleNamespace(running=False), waiting=False, _switching=False,
                                  prompt_path=types.SimpleNamespace(get=lambda: "p.json"), _run_job="J")
        s.__dict__.update(kw)
        s._busy_with_job = lambda: app.App._busy_with_job(s)
        return s

    def test_language_follows_the_prompt_only_when_nothing_runs(self):
        from bbm_gui import app

        for field in ("running", "waiting", "_switching"):
            s = self.stub(to_var=types.SimpleNamespace(set=lambda v: self.fail("To must not move"), get=lambda: "Polish"),
                          _fixed_language=lambda: langs.resolve("Russian"))
            if field == "running":
                s.runner.running = True
            else:
                setattr(s, field, True)
            app.App._sync_language(s)

    def test_auto_continue_needs_the_same_checks_as_a_manual_run(self):
        from bbm_gui import app

        job, log = types.SimpleNamespace(dir="J"), []
        common = dict(log_append=lambda *a: log.append(a), _set_chip=lambda *a: log.append(a), _refresh=lambda: None)
        s = self.stub(waiting=True, _switching=True, state="waiting", _problems=lambda: ["text"], _lang_problems=lambda: [],
                      **common)
        self.assertFalse(app.App._may_continue(s, job))
        self.assertEqual((s.waiting, s._switching, s.state), (False, False, "stopped"))
        self.assertIn(("Prompt", "accent"), log)
        ok = self.stub(_problems=lambda: [], _lang_problems=lambda: [], **common)
        self.assertTrue(app.App._may_continue(ok, job))
        self.assertFalse(app.App._may_continue(ok, types.SimpleNamespace(dir="other")))
        same = self.stub(_problems=lambda: [], _lang_problems=lambda: ["same"], **common)
        self.assertFalse(app.App._may_continue(same, job))


if __name__ == "__main__":
    unittest.main()
