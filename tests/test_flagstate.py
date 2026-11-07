import unittest

from bbm_gui import cmdbuild, flagrules
from bbm_gui.flagstate import FlagState

PRESETS = {
    "A": {"--api_format": "gemini", "--temperature": "0.4", "--use_context": True},
    "B": {"--api_format": "gemini"},
}


def inv(*specs):
    flags = []
    for i, (fid, action) in enumerate(specs):
        flags.append({"id": fid, "options": [fid], "action": action, "nargs": None, "type": None, "choices": None,
                      "default": None, "hidden": False, "order": i, "dest": fid.lstrip("-")})
    return {"flags": flags}


INV = inv(("--api_format", "store"), ("--temperature", "store"), ("--use_context", "store_true"),
          ("--test", "store_true"), ("--test_num", "store"), ("--proxy", "store"), ("--no_disclosure", "store_false"),
          ("--language", "store"), ("--translate-tags", "store"))


class FlagStateTest(unittest.TestCase):
    def test_preset_change_keeps_user_edit(self):
        st = FlagState(PRESETS, "A")
        st.set("--proxy", "http://x")
        st.set("--temperature", "0.9")
        st.set_preset("B")
        eff = st.effective()
        self.assertEqual(eff["--proxy"], "http://x")
        self.assertEqual(eff["--temperature"], "0.9")  # my value survives although B has no temperature
        self.assertNotIn("--use_context", eff)  # preset flags of A are gone with A

    def test_tombstone_hides_preset_flag_and_revert_restores(self):
        st = FlagState(PRESETS, "A")
        st.remove("--use_context")
        self.assertNotIn("--use_context", st.effective())
        self.assertEqual(st.origin("--use_context"), "hidden")
        st.revert("--use_context")
        self.assertTrue(st.effective()["--use_context"])
        st.set("--temperature", "0.9")
        self.assertEqual(st.origin("--temperature"), "user")
        st.set("--temperature", "0.4")  # same as the preset: no user entry left
        self.assertEqual(st.origin("--temperature"), "preset")
        self.assertEqual(st.user, {})

    def test_tombstone_survives_json_round_trip(self):
        st = FlagState(PRESETS, "A")
        st.remove("--temperature")
        again = FlagState.from_json(PRESETS, "A", st.to_json())
        self.assertNotIn("--temperature", again.effective())

    def test_transient_not_saved(self):
        st = FlagState(PRESETS, "A")
        st.set("--test", "5")
        st.set("--retranslate", True)
        st.set("--proxy", "p")
        self.assertEqual(st.to_json(), {"--proxy": "p"})

    def test_owned_flag_refused(self):
        st = FlagState(PRESETS, "A")
        self.assertFalse(st.set("--language", "German"))
        self.assertEqual(st.user, {})
        stale = FlagState(PRESETS, "A", {"--model": "x", "--proxy": "p"})  # old file with an owned flag
        self.assertEqual(stale.user, {"--proxy": "p"})
        self.assertEqual(st.effective({"--language": "Russian"})["--language"], "Russian")

    def test_owned_layer_wins(self):
        st = FlagState(PRESETS, "A", {"--proxy": "p"})
        self.assertEqual(st.effective({"--proxy": "q"})["--proxy"], "q")

    def test_custom_keeps_gemini_format(self):
        from bbm_gui import app

        self.assertEqual(app.PRESETS["Custom"], {"--api_format": "gemini", "--translate-tags": flagrules.DEFAULT_TAGS})


class ExtraMigrationTest(unittest.TestCase):
    def test_pairs_and_toggles(self):
        found, refused = cmdbuild.parse_extra("--proxy http://h:1 --use_context --no_disclosure --translate-tags=p,h1",
                                              INV, windows=False)
        self.assertEqual(found, {"--proxy": "http://h:1", "--use_context": True, "--no_disclosure": False,
                                 "--translate-tags": "p,h1"})
        self.assertEqual(refused, [])

    def test_owned_refused_with_its_value(self):
        found, refused = cmdbuild.parse_extra("--language German --proxy p --model=x stray", INV, windows=False)
        self.assertEqual(found, {"--proxy": "p"})
        self.assertEqual([r[0] for r in refused], ["--language", "--model", "stray"])
        self.assertEqual(refused[0][1], "Set in the main window")

    def test_windows_path_kept(self):
        found, _ = cmdbuild.parse_extra(r'--proxy "C:\Users\me\my dir\p.txt" --temperature 0.2', INV, windows=True)
        self.assertEqual(found["--proxy"], r"C:\Users\me\my dir\p.txt")
        found, _ = cmdbuild.parse_extra(r"--proxy C:\a\b", INV, windows=True)
        self.assertEqual(found["--proxy"], r"C:\a\b")

    def test_unknown_flag_kept(self):
        found, _ = cmdbuild.parse_extra("--future-flag 3 --other", INV, windows=False)
        self.assertEqual(found, {"--future-flag": "3", "--other": True})


class BuildArgvTest(unittest.TestCase):
    def test_test_companion(self):
        argv, dropped = cmdbuild.build_argv(INV, {"--test": "5"})
        self.assertEqual(argv, ["--test", "--test_num=5"])
        argv, dropped = cmdbuild.build_argv(INV, {"--test": True})
        self.assertEqual(argv, ["--test"])
        argv, dropped = cmdbuild.build_argv(INV, {"--test_num": "5"})
        self.assertEqual((argv, dropped), ([], ["--test_num"]))

    def test_unknown_flag_reported(self):
        argv, dropped = cmdbuild.build_argv(INV, {"--gone": "1", "--proxy": "p"})
        self.assertEqual((argv, dropped), (["--proxy=p"], ["--gone"]))

    def test_chips_survive_a_restart_exactly(self):
        """What the strip shows is rebuilt from the saved user layer: same chips, same origins; a test chip is gone."""
        from bbm_gui import flagmenu

        overlay = {"flag": {"--temperature": {"label": "Temperature"}}}
        st = FlagState(PRESETS, "A")
        st.set("--temperature", "0.9")
        st.remove("--use_context")
        st.set("--proxy", "http://x")
        st.set("--test", "5")
        st.set("--future", "1")
        before = flagmenu.chips(st, INV, overlay)
        again = FlagState.from_json(PRESETS, "A", st.to_json())
        after = flagmenu.chips(again, INV, overlay)
        self.assertEqual([c for c in before if c.fid != "--test"], after)
        self.assertEqual({c.fid: c.origin for c in after}["--future"], "bad")
        self.assertNotIn("--use_context", [c.fid for c in after])


if __name__ == "__main__":
    unittest.main()
