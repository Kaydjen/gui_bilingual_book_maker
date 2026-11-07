import unittest

from bbm_gui.flagstate import FlagState

PRESETS = {"P": {"--api_format": "gemini", "--use_context": True, "--temperature": "0.4"}}


class DefaultsTest(unittest.TestCase):
    def test_nothing_to_restore_on_a_fresh_state(self):
        st = FlagState(PRESETS, "P")
        self.assertFalse(st.differs())
        self.assertFalse(st.reset_preset())

    def test_removed_and_changed_preset_flags_come_back(self):
        st = FlagState(PRESETS, "P", {"--api_format": None, "--use_context": None, "--temperature": "0.9"})
        self.assertTrue(st.differs())
        self.assertNotIn("--api_format", st.effective())
        self.assertTrue(st.reset_preset())
        self.assertFalse(st.differs())
        self.assertEqual(st.effective(), PRESETS["P"])
        self.assertEqual(st.to_json(), {})

    def test_flags_added_by_the_user_stay(self):
        st = FlagState(PRESETS, "P", {"--proxy": "http://127.0.0.1:7890", "--use_context": None})
        st.reset_preset()
        self.assertEqual(st.effective()["--proxy"], "http://127.0.0.1:7890")
        self.assertIn("--use_context", st.effective())
        self.assertTrue(not st.differs())


if __name__ == "__main__":
    unittest.main()
