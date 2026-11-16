import json
import tempfile
import unittest
from pathlib import Path

from novelgui import accent
from novelgui.settings import Settings
from novelgui.winstate import WinState


class WinStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.settings = Settings(self.folder)
        self.ws = WinState(self.settings)

    def reload(self):
        return WinState(Settings(self.folder))

    def test_defaults_and_types(self):
        self.assertEqual(self.ws.get_int("n", 7), 7)
        self.ws.set("n", 3)
        self.assertEqual(self.ws.get_int("n", 7), 3)
        self.assertEqual(self.ws.get_str("n", "x"), "x")          # wrong type reads as default
        self.ws.set("b", True)
        self.assertEqual(self.ws.get_int("b", 9), 9)              # bool is not an int
        self.assertTrue(self.ws.get_bool("b"))

    def test_persists_in_the_settings_file_under_one_key(self):
        self.ws.set("queue", [{"a": 1}])
        self.assertEqual(self.reload().get_list("queue"), [{"a": 1}])
        raw = json.loads((self.folder / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(list(raw), ["win"])

    def test_other_settings_untouched(self):
        self.settings.set("pace", 5)
        self.ws.set("x", 1)
        self.assertEqual(Settings(self.folder).get("pace"), 5)

    def test_get_returns_a_copy(self):
        self.ws.set("l", [1, 2])
        got = self.ws.get_list("l")
        got.append(3)
        self.assertEqual(self.ws.get_list("l"), [1, 2])

    def test_delete(self):
        self.ws.set("k", 1)
        self.ws.delete("k")
        self.assertEqual(self.reload().get("k", "gone"), "gone")

    def test_scoped_values(self):
        self.ws.set_in("t", "series-a", 1)
        self.ws.set_in("t", "series-b", 2)
        r = self.reload()
        self.assertEqual(r.get_in("t", "series-a"), 1)
        self.assertEqual(r.get_in("t", "series-b"), 2)
        self.assertIsNone(r.get_in("t", "series-c"))
        r.delete_in("t", "series-a")
        self.assertIsNone(self.reload().get_in("t", "series-a"))

    def test_prompt_draft_round_trip(self):
        self.assertIsNone(self.ws.prompt_draft("s"))
        self.ws.set_prompt_draft("s", "Mine", "Translate {language}")
        self.assertEqual(self.reload().prompt_draft("s"), ("Mine", "Translate {language}"))
        self.assertIsNone(self.reload().prompt_draft("other"))
        self.ws.clear_prompt_draft("s")
        self.assertIsNone(self.reload().prompt_draft("s"))

    def test_volume_selection(self):
        self.ws.set_volume_selection("s", "v1", [(1, 5), (8, 8)])
        self.ws.set_volume_selection("s", "v2", [(3, 4)])
        r = self.reload()
        self.assertEqual(r.volume_selection("s", "v1"), [[1, 5], [8, 8]])
        self.assertEqual(r.volume_selection("s", "v2"), [[3, 4]])
        self.assertIsNone(r.volume_selection("s", "v3"))

    def test_damaged_value_is_ignored(self):
        self.ws.set("selection", {"s": {"v": [[1, "x"]]}})
        self.assertIsNone(self.ws.volume_selection("s", "v"))
        self.ws.set("prompt_draft", {"s": {"name": 5, "text": "t"}})
        self.assertIsNone(self.ws.prompt_draft("s"))

    def test_write_failure_is_reported(self):
        blocker = self.folder / "file"
        blocker.write_text("x")
        bad = WinState(Settings(blocker / "inside"))
        self.assertFalse(bad.set("k", 1))
        self.assertEqual(bad.get_int("k"), 1)                     # kept in memory


class AccentTest(unittest.TestCase):
    def test_priority(self):
        F = accent.Facts
        self.assertEqual(accent.owner(F(has_keys=False, language_chosen=False, first_blocked=True), "run"), "keys")
        self.assertEqual(accent.owner(F(has_keys=True, language_chosen=False, first_blocked=True), "run"), "language")
        self.assertEqual(accent.owner(F(first_blocked=True), "run"), "terms")
        self.assertEqual(accent.owner(F(), "run"), "run")
        self.assertEqual(accent.owner(F()), "")

    def test_only_one_name_wins(self):
        f = accent.Facts(has_keys=False)
        names = ["keys", "language", "terms", "run"]
        self.assertEqual([n for n in names if accent.gets_accent(n, f, "run")], ["keys"])
        self.assertFalse(accent.gets_accent("", accent.Facts(), ""))


if __name__ == "__main__":
    unittest.main()
