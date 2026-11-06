import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from bbm_gui import glossary as gl
from bbm_gui import promptset as ps

WORDS = re.compile(r"glossar|глосс|глосар|glosar", re.IGNORECASE)


class BlockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BBM_GUI_DATA"] = self._tmp.name

    def tearDown(self):
        os.environ.pop("BBM_GUI_DATA", None)
        self._tmp.cleanup()

    def build(self, t, entries, notes=True):
        return gl.build_prompt({"system": t["system"], "user": t["user"], "glossary_head": t["head"],
                                "glossary_notes_hint": t["hint"]}, entries, notes)

    def test_empty_glossary_has_no_glossary_words(self):
        for t in ps.templates():
            self.assertTrue(t["head"] and t["hint"], t["id"])
            for entries in ([], [gl.Entry("a", "")], [gl.Entry("", "b", "n")]):
                out = self.build(t, entries)
                self.assertEqual(set(out), {"system", "user"})
                self.assertIsNone(WORDS.search(out["system"]), (t["id"], WORDS.search(out["system"])))

    def test_block_and_hint(self):
        for t in ps.templates():
            plain = self.build(t, [gl.Entry("A", "B")])["system"]
            self.assertTrue(plain.endswith(t["head"].strip("\n") + "\n- A -> B"), t["id"])
            self.assertNotIn(t["hint"], plain)
            noted = self.build(t, [gl.Entry("A", "B", "n")])["system"]
            self.assertTrue(noted.endswith(t["head"].strip("\n") + "\n" + t["hint"] + "\n- A -> B (n)"), t["id"])
            off = self.build(t, [gl.Entry("A", "B", "n")], notes=False)["system"]
            self.assertNotIn(t["hint"], off)
            self.assertNotIn("(n)", off)
            # a note on a row that is not usable does not bring the hint
            self.assertNotIn(t["hint"], self.build(t, [gl.Entry("A", "B"), gl.Entry("C", "", "n")])["system"])

    def test_braces_survive_the_engine_format(self):
        for t in ps.templates():
            self.assertEqual(gl.check_system(t["system"] + t["head"] + t["hint"]), [], t["id"])
            s = self.build(t, [gl.Entry("{S}", "[С]", "{x}")])["system"]
            s.format(language="X", crlf="\n")  # must not raise

    def test_legacy_layout_unchanged(self):
        head = "T\nGLOSSARY\n"
        self.assertEqual(gl.build_system(head, [gl.Entry("a", "b")]), "T\nGLOSSARY\n- a -> b")
        self.assertEqual(gl.build_system(head, []), head)

    def test_blank_set_uses_neutral_block(self):
        head, hint = ps.default_block()
        self.assertIn("GLOSSARY", head)
        self.assertTrue(hint)

    def test_save_open_keeps_block_and_legacy_marker(self):
        head, hint = ps.default_block()
        s = ps.PromptSet("new", "SYS\n", "{text}", [gl.Entry("A", "B", "n")], "Russian", True, head, hint)
        built = json.loads(s.save().read_text(encoding="utf-8"))
        self.assertIn(head.strip("\n"), built["system"])
        again = ps.PromptSet.open(s.built_path)
        self.assertEqual((again.head, again.hint), (head, hint))
        legacy = ps.PromptSet("old", "SYS\nHEAD\n", "{text}", [gl.Entry("A", "B")])
        legacy.save()
        self.assertIsNone(ps.PromptSet.open(legacy.built_path).head)
        self.assertEqual(json.loads(legacy.built_path.read_text(encoding="utf-8"))["system"], "SYS\nHEAD\n- A -> B")

    def test_migration_of_shipped_old_text_only(self):
        t = next(x for x in ps.templates() if x["id"] == "neutral")
        old = t["system"] + "GLOSSARY (old wording)\n"
        saved = ps.LEGACY.copy()
        ps.LEGACY[hashlib.sha256(old.encode("utf-8")).hexdigest()] = "neutral"
        try:
            for system, moved in ((old, True), (old + "my edit\n", False)):
                s = ps.PromptSet("m", system, "{text}", [gl.Entry("A", "B")])
                s.save()
                src = ps.prompts_dir() / "m.src.json"
                # the saved side file of a legacy prompt has no block keys
                self.assertNotIn("glossary_head", json.loads(src.read_text(encoding="utf-8"))["template"])
                first = ps.PromptSet.open(s.built_path)
                self.assertEqual(first.head is not None, moved)
                self.assertEqual(first.system == t["system"], moved)
                first.save()
                second = ps.PromptSet.open(s.built_path)  # saving again changes nothing
                self.assertEqual((second.system, second.head, second.hint), (first.system, first.head, first.hint))
        finally:
            ps.LEGACY.clear()
            ps.LEGACY.update(saved)

    def test_legacy_ids_exist(self):
        ids = {t["id"] for t in ps.templates()}
        self.assertEqual(set(ps.LEGACY.values()), ids)


if __name__ == "__main__":
    unittest.main()
