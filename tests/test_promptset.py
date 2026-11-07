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


class LangTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BBM_GUI_DATA"] = self._tmp.name
        ps._lang_cache.clear()

    def tearDown(self):
        os.environ.pop("BBM_GUI_DATA", None)
        self._tmp.cleanup()

    def tpl(self, tag):
        return next(t for t in ps.templates() if t["tag"] == tag)

    def test_shipped_templates_have_tags(self):
        self.assertEqual(sorted(t["tag"] for t in ps.templates()), ["*", "pl", "ru", "uk"])

    def test_detect_by_template_hash_placeholder_and_letters(self):
        for tag in ("ru", "uk", "pl", "*"):
            self.assertEqual(ps.detect_lang(self.tpl(tag)["system"]), tag)
        for h, tid in ps.LEGACY.items():  # an old shipped text is recognised by its hash
            tag = next(t["tag"] for t in ps.templates() if t["id"] == tid)
            self.assertIn(tag, ("ru", "uk", "pl", "*"))
        self.assertEqual(ps.detect_lang("Translate to {language}.", "{text}"), "*")
        self.assertEqual(ps.detect_lang("Ты переводчик, не меняй э и ы", "{text}"), "ru")
        self.assertEqual(ps.detect_lang("Ти перекладач, їжак і ґанок", "{text}"), "uk")
        self.assertEqual(ps.detect_lang("Jesteś tłumaczem, zażółć", "{text}"), "pl")
        self.assertEqual(ps.detect_lang("Eres traductor, ¿qué más? ó", "{text}"), "?")
        self.assertEqual(ps.detect_lang("plain english", "{text}"), "?")

    def test_lang_is_saved_and_old_files_get_one(self):
        t = self.tpl("uk")
        s = ps.PromptSet("u", t["system"], t["user"], [], "Ukrainian", True, t["head"], t["hint"], "uk")
        path = s.save()
        self.assertEqual(json.loads((ps.prompts_dir() / "u.src.json").read_text(encoding="utf-8"))["lang"], "uk")
        self.assertEqual(ps.lang_of(path), "uk")
        side = ps.prompts_dir() / "u.src.json"  # a side file from before the field existed
        d = json.loads(side.read_text(encoding="utf-8"))
        del d["lang"]
        side.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        ps._lang_cache.clear()
        self.assertEqual(ps.PromptSet.open(path).lang, "uk")
        self.assertEqual(ps.lang_of(path), "uk")
        plain = Path(self._tmp.name) / "plain.json"  # a prompt file that is not ours
        plain.write_text(json.dumps({"system": "Ти перекладач їжак", "user": "{text}"}), encoding="utf-8")
        self.assertEqual(ps.lang_of(plain), "uk")

    def test_language_placeholder_makes_it_neutral(self):
        s = ps.PromptSet("n", "Translate into {language}", "{text}", [], "", True, "", "", "ru")
        self.assertEqual(ps.detect_lang(s.system, s.user), "*")

    def test_select_for_chain(self):
        remembered = {}
        ru = ps.select_for("ru", remembered)  # shipped template, created on the fly
        self.assertTrue(Path(ru).is_file())
        self.assertEqual(ps.lang_of(ru), "ru")
        self.assertEqual(ps.select_for("ru", {}), ru)  # reused, not duplicated
        uk = ps.select_for("uk", remembered)
        self.assertNotEqual(uk, ru)
        self.assertEqual(ps.lang_of(uk), "uk")
        de = ps.select_for("de", remembered)  # no template: neutral
        self.assertEqual(ps.lang_of(de), "*")
        self.assertEqual(ps.select_for(None, remembered), de)
        mine = ps.PromptSet("mine", "Ты переводчик ы", "{text}", [], "Russian", True, "", "", "ru").save()
        remembered["ru"] = str(mine)
        self.assertEqual(ps.select_for("ru", remembered), str(mine))  # the remembered one wins
        remembered["ru"] = str(uk)  # a remembered file of another language is ignored
        self.assertEqual(ps.select_for("ru", remembered), ru)
        remembered["ru"] = str(Path(self._tmp.name) / "gone.json")
        self.assertEqual(ps.select_for("ru", remembered), ru)

    def test_existing_file_with_a_template_name_is_not_overwritten(self):
        t = self.tpl("ru")
        other = ps.PromptSet(ps.safe_name(t["name"]), "Something else", "{text}", [], "", True, "", "", "?")
        other.save()
        path = ps.select_for("ru", {})
        self.assertNotEqual(Path(path).stem, ps.safe_name(t["name"]))
        self.assertIn("Something else", other.built_path.read_text(encoding="utf-8"))

    def test_templates_for(self):
        self.assertEqual(sorted(t["tag"] for t in ps.templates_for("ru")), ["*", "ru"])
        self.assertEqual([t["tag"] for t in ps.templates_for(None)], ["*"])
        self.assertEqual([t["tag"] for t in ps.templates_for("de")], ["*"])


if __name__ == "__main__":
    unittest.main()
