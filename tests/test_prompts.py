import unittest

from bbm_gui import langs, prompts

TABLE = {"ru": "russian", "uk": "ukrainian", "pl": "polish", "de": "german", "en": "english"}
# (system, user) of a prompt per language; the letters are what the heuristic looks at
TEXT = {
    "ru": ("Ты профессиональный переводчик. Не меняй э и ъ.", "Переведи эти тексты: {text}"),
    "uk": ("Ти перекладач. Їжак, ґанок, і.", "Переклади їжака: {text}"),
    "pl": ("Jesteś tłumaczem. Zażółć gęślą jaźń.", "Przetłumacz: {text}"),
    "*": ("Translate into {language}.", "{text}"),
}


def lang(text):
    return langs.resolve(text, TABLE)


class CheckLanguageTest(unittest.TestCase):
    def test_recorded_language_matrix(self):
        targets = {"ru": "Russian", "uk": "Ukrainian", "pl": "Polish", "de": "German"}
        for prompt in ("ru", "uk", "pl", "*"):
            for tag, name in targets.items():
                bad = prompt not in ("*", tag)
                self.assertEqual(prompts.check_language(prompt, lang(name)), ["lang"] if bad else [],
                                 (prompt, name))

    def test_unknown_target_never_blocks(self):
        for prompt in ("ru", "uk", "pl", "*", "?"):
            self.assertEqual(prompts.check_language(prompt, lang("Klingon"), {"system": "Ти їжак", "user": "{text}"}), [])
            self.assertEqual(prompts.check_language(prompt, lang("")), [])

    def test_heuristic_for_unknown_prompt_language_covers_both_parts(self):
        targets = {"ru": "Russian", "uk": "Ukrainian", "pl": "Polish", "de": "German"}
        for written in ("ru", "uk", "pl"):
            system, user = TEXT[written]
            for tag, name in targets.items():
                bad = written != tag
                for data in ({"system": system, "user": "{text}"}, {"system": "", "user": user + " {text}"}):
                    # only one part carries the letters; the other one is neutral
                    self.assertEqual(prompts.check_language("?", lang(name), data), ["lang"] if bad else [],
                                     (written, name, data))

    def test_heuristic_skips_text_with_placeholder_and_plain_cyrillic(self):
        self.assertEqual(prompts.check_language("?", lang("German"), {"system": "Ты {language} ы", "user": "{text}"}), [])
        # Cyrillic without a distinguishing letter: fine for a Cyrillic target, blocked for German
        data = {"system": "Привет мир", "user": "{text}"}
        self.assertEqual(prompts.check_language("?", lang("Russian"), data), [])
        self.assertEqual(prompts.check_language("?", lang("German"), data), ["lang"])
        self.assertEqual(prompts.check_language("?", lang("German"), {"system": "plain english", "user": "{text}"}), [])

    def test_text_accepts_a_string_target(self):
        self.assertEqual(prompts.check_language("uk", "Russian"), ["lang"])
        self.assertEqual(prompts.check_language("ru", "ru"), [])

    def test_regional_tags(self):
        self.assertEqual(prompts.check_language("pt", langs.Lang("pt-br", "Brazilian Portuguese", True)), [])
        self.assertEqual(prompts.check_language("zh-hans", langs.Lang("zh", "Chinese", True)), [])


class ShapeTest(unittest.TestCase):
    def test_check(self):
        self.assertEqual(prompts.check({"user": "{text}"}), [])
        self.assertEqual(prompts.check({"user": ""}), ["user"])
        self.assertEqual(prompts.check({"user": "no field"}), ["text"])
        self.assertEqual(prompts.check({"user": "{text} {x}"}), ["braces"])


if __name__ == "__main__":
    unittest.main()
