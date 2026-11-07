import unittest

from bbm_gui import langs

TABLE = {"en": "english", "ru": "russian", "zh-hans": "simplified chinese", "zh": "chinese", "uk": "ukrainian",
         "de": "german", "pt-br": "brazilian portuguese"}


def r(text):
    return langs.resolve(text, TABLE)


class ResolveTest(unittest.TestCase):
    def test_same_language_one_identity(self):
        for text in ("ru", "RU", "Russian", "russian", " russian "):
            lang = r(text)
            self.assertEqual((lang.tag, lang.name, lang.known), ("ru", "Russian", True), text)
            self.assertEqual(langs.engine_value(lang), "ru:Russian")

    def test_multi_word_and_script_tags(self):
        lang = r("zh-hans")
        self.assertEqual((lang.tag, lang.name), ("zh-hans", "Simplified Chinese"))
        self.assertEqual(langs.engine_value(lang), "zh-hans:Simplified Chinese")
        self.assertEqual(r("Simplified Chinese").tag, "zh-hans")
        self.assertEqual(r("chinese").tag, "zh")

    def test_pinned_pair(self):
        lang = r("xx:Klingon")
        self.assertEqual((lang.tag, lang.name, lang.known), ("xx", "Klingon", True))
        self.assertEqual(langs.engine_value(lang), "xx:Klingon")
        self.assertEqual(langs.engine_value(r("RU:Russian")), "ru:Russian")

    def test_unknown_text_is_passed_as_typed(self):
        lang = r("Russan")
        self.assertEqual((lang.tag, lang.name, lang.known), (None, "Russan", False))
        self.assertEqual(langs.engine_value(lang), "Russan")
        self.assertFalse(r("x:").known)

    def test_empty(self):
        for text in ("", "   ", None):
            self.assertFalse(r(text))
            self.assertIsNone(r(text).tag)

    def test_same_and_list(self):
        self.assertTrue(langs.same("ru", "Russian"))
        self.assertFalse(langs.same("Auto", "Russian"))
        self.assertFalse(langs.same("", ""))
        names = langs.display_list(TABLE)
        self.assertEqual(names[:3], ["Russian", "English", "Ukrainian"])  # favourites first, table order of FAVOURITES
        self.assertEqual(names[-1], "Simplified Chinese")
        self.assertEqual(len(names), len(set(names)))

    def test_engine_table_replaces_builtin(self):
        langs.use_table({"tlh": "klingon"}, {"tlhingan": "tlh"})
        try:
            self.assertEqual(langs.resolve("klingon").tag, "tlh")
            self.assertEqual(langs.resolve("Tlhingan").tag, "tlh")
            self.assertFalse(langs.resolve("Russian").known)
        finally:
            langs.use_table(None)
        self.assertEqual(langs.resolve("Russian").tag, "ru")


if __name__ == "__main__":
    unittest.main()
