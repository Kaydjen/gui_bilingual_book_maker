"""Target-language profiles: lookup, Russian byte-identity, gender marks, answer-language checks, runs."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from novelcore import Series, profiles
from novelcore.profiles import get, looks_like
from novelcore.termmatch import TermsHook, gender_marks
from novelcore.terms import TermBase
from novelcore.translate import GroupTranslator, build_user, check_text, script_share
from tests.core_support import KEYS, CoreCase, build_epub

PROMPTS = Path(profiles.__file__).parent / "prompts"


class Blk:
    def __init__(self, text, index=0):
        self.text = text
        self.index = index
        self.markers = {}


def long_source(n=60):
    return Blk("word " * n)


# the Russian checks as they were before profiles existed (reference for the byte-identity tests)
def old_script_share(text, tag="ru"):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum(1 for c in letters if "Ѐ" <= c <= "ԯ") / len(letters)


def old_reason(src, text):
    if not text.strip():
        return "empty"
    if len(src) > 40:
        if old_script_share(text) < 0.5:
            return "script"
        ratio = len(text) / max(len(src), 1)
        if not (0.4 <= ratio <= 2.5):
            return "length"
    return None


class LookupTest(unittest.TestCase):
    def test_known_tags_and_spellings(self):
        for tag in ("ru", "RU", "ru-RU", "ru_RU", "ru:Russian", " ru "):
            self.assertEqual(get(tag).tag, "ru", tag)
        self.assertEqual(get("uk:Ukrainian").tag, "uk")
        self.assertEqual(get("pl-PL").tag, "pl")
        self.assertEqual(get("ru").name, "Russian")
        self.assertEqual(get("uk").name, "Ukrainian")
        self.assertEqual(get("pl").name, "Polish")

    def test_unknown_and_odd_input(self):
        self.assertEqual(get("pt_BR").tag, "pt")
        self.assertEqual(get("pt_BR").prompt, "default.txt")
        self.assertEqual(get("").tag, "")
        self.assertEqual(get(None).tag, "")
        self.assertEqual(get(":Foo").tag, "")
        g = get("de", "German")
        self.assertEqual((g.tag, g.name), ("de", "German"))
        self.assertEqual(g.gender_marks["female"], "female")
        self.assertIsNone(g.script)
        self.assertEqual(get("ja").script, "han_kana")
        self.assertEqual(get("el").script, "greek")

    def test_every_prompt_file_exists_and_keeps_the_language_slot(self):
        for tag in ("ru", "uk", "pl", "de", ""):
            text = get(tag).prompt_text()
            self.assertIn("{language}", text)
            self.assertNotIn("{language}", get(tag).system_prompt("X"))


class RussianUnchangedTest(unittest.TestCase):
    def test_system_prompt_is_the_default_with_the_language_replaced(self):
        raw = (PROMPTS / "default.txt").read_bytes().decode("utf-8")
        self.assertEqual(get("ru").prompt, "default.txt")
        self.assertEqual(get("ru").system_prompt("Russian"), raw.replace("{language}", "Russian"))
        self.assertEqual(profiles.prompt_text("ru-RU"), raw)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            s = Series.create(Path(d) / "lib", "S", "ru:Russian")
            self.assertEqual(s.system_prompt().encode("utf-8"), raw.replace("{language}", "Russian").encode("utf-8"))

    def test_other_prompts_differ_only_by_the_typography_line(self):
        raw = (PROMPTS / "default.txt").read_text(encoding="utf-8")
        for tag in ("uk", "pl"):
            p = get(tag)
            text = p.prompt_text()
            self.assertIn(p.typography, text)
            self.assertEqual(text.replace(p.typography + "\n", "", 1), raw)

    def test_terms_lines_unchanged(self):
        base = TermBase(None, "ru")
        base.add("Mirelle", type="character", gender="female", tr="Мирель")
        base.add("Holt", type="character", gender="male", tr="Холт")
        base.add("Axes", forms=["Axe"], type="item", gender="plural", tr="Топоры")
        base.add("Crown", type="item", gender="neuter", tr="Корона")
        base.add("Gate", type="place", gender="unknown", tr="Врата")
        hook = TermsHook(base)
        g = [Blk("Mirelle and Holt took the Axes. The Crown fell at the Gate.")]
        self.assertEqual(hook.lines_for(g, g), [
            "# Terms in this text (use these renderings exactly):",
            "Mirelle -> Мирель (ж)", "Holt -> Холт (м)", "Axes -> Топоры (мн)", "Crown -> Корона (ср)",
            "Gate -> Врата"])
        self.assertEqual(gender_marks("ru"), {"male": "м", "female": "ж", "neuter": "ср", "plural": "мн"})

    def test_request_text_is_identical(self):
        sent = []

        def ask(system, user, schema):
            sent.append((system, user))
            raise AssertionError("not needed")

        terms = ["# Terms in this text (use these renderings exactly):", "Mirelle -> Мирель (ж)"]
        user = build_user(terms, [("src", "тр")], [{"id": 1, "text": "Mirelle came."}])
        self.assertEqual(user.split("\n")[0], "TERMS")
        self.assertIn("Mirelle -> Мирель (ж)", user)
        gt = GroupTranslator(ask, get("ru").system_prompt("Russian"), "ru")
        self.assertEqual(gt.system, (PROMPTS / "default.txt").read_text(encoding="utf-8").replace("{language}", "Russian"))

    def test_acceptance_matches_the_old_rules(self):
        src_long = "x" * 10 + " word" * 20
        answers = ["", "  ", "Привет, мир! " * 10, "Hello world, this is plain Latin text. " * 5, "Да", "я" * 400, "я" * 100,
                   "Hello мир " * 12, "Смесь mixed Смесь mixed Смесь mixed Смесь", "123 456 789 000 111 222 333 444 555 666 777",
                   "«Я» — сказал он. " * 8, "ё" * 120]
        for src in ("Hi there", src_long):
            for ans in answers:
                for tag in ("ru", "ru-RU", "ru:Russian"):
                    self.assertEqual(check_text(Blk(src), ans, tag), old_reason(src, ans), (src[:10], ans[:20], tag))
        for ans in answers:
            self.assertEqual(script_share(ans, "ru"), old_script_share(ans))
        self.assertEqual(script_share("Hello мир", "uk-UA"), 3 / 8)
        self.assertIsNone(script_share("Hello", "de"))


class GenderMarksTest(unittest.TestCase):
    def lines(self, tag, tr):
        base = TermBase(None, tag)
        base.add("Mirelle", type="character", gender="female", tr=tr[0])
        base.add("Holt", type="character", gender="male", tr=tr[1])
        base.add("Crown", type="item", gender="neuter", tr=tr[2])
        base.add("Axes", forms=["Axe"], type="item", gender="plural", tr=tr[3])
        g = [Blk("Mirelle and Holt took the Axes and the Crown.")]
        return TermsHook(base).lines_for(g, g)[1:]

    def test_three_languages_and_generic(self):
        self.assertEqual(self.lines("ru", ("Мирель", "Холт", "Корона", "Топоры")),
                         ["Mirelle -> Мирель (ж)", "Holt -> Холт (м)", "Axes -> Топоры (мн)", "Crown -> Корона (ср)"])
        self.assertEqual(self.lines("uk", ("Мірель", "Холт", "Корона", "Сокири")),
                         ["Mirelle -> Мірель (ж)", "Holt -> Холт (ч)", "Axes -> Сокири (мн)", "Crown -> Корона (с)"])
        self.assertEqual(self.lines("pl", ("Mirella", "Holt", "Korona", "Topory")),
                         ["Mirelle -> Mirella (ż)", "Holt -> Holt (m)", "Axes -> Topory (lm)", "Crown -> Korona (n)"])
        self.assertEqual(self.lines("de", ("Mirelle", "Holt", "Krone", "Äxte"))[0], "Mirelle -> Mirelle (female)")
        self.assertEqual(gender_marks("pl:Polish")["female"], "ż")
        self.assertEqual(gender_marks("")["male"], "male")


PL_OK = [
    "Wczoraj wieczorem poszedłem do domu i długo myślałem o tym, co powiedziała mi matka przed wyjazdem.",
    "— Nie wiem, czy to dobry pomysł — powiedziała Mirella, patrząc na Tavrina Holta z niepokojem.",
    "Rycerz podniósł miecz i ruszył w stronę bramy, a za nim szli wszyscy pozostali wojownicy.",
    "Nie wiem jak to zrobic ale musze sprobowac bo inaczej wszyscy zginiemy w tej wiosce przed rana.",
    "Wtedy do pokoju weszla Kelvara i powiedziala ze nikt nie zostanie w tym miejscu na noc.",
    "Stał przed bramą Cold Shadow Academy i patrzył na tłum uczniów, którzy czekali na ceremonię otwarcia.",
    "— Jesteś pewien? — zapytał Holt. — Tak, jestem pewien, że to była ona, i nie zmienię zdania.",
    "Nazywał się Tom the Brave, ale wszyscy w wiosce wołali na niego po prostu Tomek, bo był bardzo mały.",
    "[Poziom 5] Siła: 12, Zwinność: 9, Inteligencja: 14. Punkty życia: 120/120. Mana: 45/60. Premia: +3.",
    "Napis na ścianie głosił: the end of the road, ale nikt z nas nie rozumiał, co to znaczy naprawdę.",
    "Była noc i padał deszcz, a on szedł sam przez las, nie oglądając się za siebie ani razu.",
    "Mirelle powiedziała Holtowi, że nie pójdzie z nimi, bo las jest ciemny i nikt nie wie, co tam na nich czeka.",
    "Kiedy Tavrin Holt dotarł do wioski, słońce już zachodziło, a w oknach domów paliły się pierwsze światła.",
    "To był pierwszy raz, kiedy zobaczył morze, i długo nie mógł oderwać od niego wzroku.",
    "Dostałeś 500 punktów doświadczenia. Twoja siła wzrosła o dwa, a umiejętność ma teraz piąty poziom.",
    "Wielki Smok z Północy, znany także jako the Black Dragon, spał w swojej jaskini od trzystu lat.",
    "Zaklęcie Cold Shadow Strike zadało przeciwnikowi ogromne obrażenia i zmusiło go do odwrotu.",
]
PL_SHORT_OK = [
    "Tak.", "Nie wiem.", "Mirelle and Holt", "The Black Dragon of the North", "12 34 56 78 90 12 34 56 78 90 12 34 56",
    "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16", "Von Strauss i Holt", "***", "He said it was fine.",
]
EN_BAD = [
    "He walked to the gate and looked at the people who were waiting for him with their swords in hand.",
    "\"I don't know if this is a good idea,\" she said, looking at the old man with a worried face and his hat.",
    "The road was long and the night was cold, but they had to reach the village before the sun was up.",
    "Mirelle said that she would not go with them, because the forest was dark and nobody knew what was there.",
    "It was the first time that he had seen the sea, and he could not take his eyes from it for a long time.",
    "Łukasz said that he had seen the dragon from the hill, and that it was much larger than the castle was.",
    "You have gained 500 experience points. Your strength has increased by two, and the skill is now level five.",
    "\"Where have you been?\" asked Holt. \"I have been looking for you all night, and they said that you were gone.\"",
]


class PolishDetectorTest(unittest.TestCase):
    def test_polish_is_never_rejected(self):
        pl = get("pl")
        for t in PL_OK + PL_SHORT_OK:
            self.assertIsNone(pl.wrong_language(t), t)

    def test_clearly_english_long_blocks_are_rejected(self):
        pl = get("pl")
        for t in EN_BAD:
            self.assertEqual(pl.wrong_language(t), "language", t)

    def test_sample_count(self):
        self.assertGreaterEqual(len(PL_OK) + len(PL_SHORT_OK) + len(EN_BAD), 25)

    def test_check_text_uses_the_detector_only_for_long_sources(self):
        long_src = Blk("The road was long and the night was cold, but they had to reach the village in time.")
        self.assertEqual(check_text(long_src, EN_BAD[2], "pl"), "language")
        self.assertIsNone(check_text(long_src, PL_OK[10], "pl-PL"))
        short_src = Blk("Mirelle and Holt")
        self.assertIsNone(check_text(short_src, "Mirelle and Holt", "pl"))
        # a short answer to a long source: not an English leftover (too few tokens), the length rule decides
        self.assertIsNone(check_text(long_src, "Von Strauss i Holt przybyli o świcie z Zachodu.", "pl"))

    def test_generic_latin_target_rejects_only_clear_english(self):
        de = get("de")
        self.assertEqual(de.wrong_language(EN_BAD[2]), "language")
        self.assertIsNone(de.wrong_language("Der Weg war lang und die Nacht war kalt, aber sie mussten das Dorf erreichen."))
        self.assertIsNone(de.wrong_language("latin text " * 10))
        self.assertIsNone(get("fr").wrong_language("La route était longue et la nuit était froide, mais ils devaient arriver."))
        self.assertIsNone(get("es").wrong_language("El camino era largo y la noche era fría, pero tenían que llegar al pueblo."))
        self.assertIsNone(get("nl").wrong_language("De weg was lang en de nacht was koud, maar ze moesten het dorp bereiken."))

    def test_script_targets(self):
        self.assertEqual(get("uk").wrong_language(EN_BAD[0]), "script")
        self.assertIsNone(get("uk").wrong_language("Дорога була довга, а ніч холодна, але вони мусили дійти до села."))
        self.assertEqual(get("ja").wrong_language(EN_BAD[0]), "script")
        self.assertIsNone(get("ja").wrong_language("道は長く、夜は寒かったが、彼らは村に着かなければならなかった。"))
        self.assertIsNone(get("zh").wrong_language("路很长，夜很冷，但他们必须赶到村子。"))
        self.assertIsNone(get("ko").wrong_language("길은 멀고 밤은 추웠지만 그들은 마을에 도착해야 했다."))
        self.assertEqual(get("ko").wrong_language(EN_BAD[0]), "script")


class LooksLikeTest(unittest.TestCase):
    UK = ("Дорога була довга, а ніч холодна, але вони мусили дійти до села ще до світанку. "
          "Їхній провідник знав усі стежки в цьому лісі, і ніхто не сумнівався в його словах. "
          "Ґанок старого будинку скрипів під ногами, а єдине вікно світилося тьмяним світлом.")
    RU = ("Дорога была долгой, а ночь холодной, но они должны были добраться до деревни до рассвета. "
          "Их проводник знал все тропы в этом лесу, и никто не сомневался в его словах. "
          "Крыльцо старого дома скрипело под ногами, а единственное окно светилось тусклым светом, ёлки.")

    def test_uk_and_ru(self):
        self.assertTrue(looks_like("uk", self.UK))
        self.assertFalse(looks_like("uk", self.RU))
        self.assertTrue(looks_like("ru", self.RU))
        self.assertFalse(looks_like("ru", self.UK))
        self.assertTrue(looks_like("ru-RU", self.RU))

    def test_none_when_unsure(self):
        self.assertIsNone(looks_like("uk", "Привіт"))
        self.assertIsNone(looks_like("pl", self.UK))
        self.assertIsNone(looks_like("", self.UK))


def parts(text):
    m = re.match(r"Chapter (\d+) paragraph (\d+)", text)
    return (m.group(1), m.group(2)) if m else ("0", "0")


def fake_uk(text):
    c, p = parts(text)
    return f"Розділ {c}, абзац {p}: розповідь триває ще деякий час, і в ній кілька слів."


def fake_pl(text):
    c, p = parts(text)
    return f"Rozdział {c}, akapit {p}: opowieść trwa jeszcze dość długo i jest w niej kilka słów."


class EndToEndBase(CoreCase):
    chapters = 2
    paras = 6
    per_request = 4
    target = "uk:Ukrainian"
    fake = staticmethod(fake_uk)

    def setUp(self):
        self.api_args = {"translate": self.fake}
        super().setUp()
        epub = self.dir / "Book Two.epub"
        build_epub(epub, self.chapters, self.paras)
        self.series = Series.create(self.dir / "lib2", "Other", self.target, per_request=self.per_request)
        self.book = self.series.add_book(epub)

    def stored(self):
        out = []
        for ch, blk in self.all_blocks():
            rec = self.series.chapter_log(self.book, ch).done(blk.index, blk.sha)
            out.append(rec["text"] if rec else None)
        return out


class UkrainianRunTest(EndToEndBase):
    def test_runs_and_accepts_ukrainian(self):
        self.run_all(keys=KEYS[:1])
        self.assertEqual(self.count_done(), (12, 12))
        self.assertTrue(all(t.startswith("Розділ") for t in self.stored()))
        self.assertEqual(self.series.target_tag, "uk")
        self.assertIn("Ukrainian", self.series.system_prompt())

    def test_english_echo_is_rejected_and_retried(self):
        self.api.faults = {1: "latin"}
        self.run_all(keys=KEYS[:1])
        self.assertEqual(self.count_done(), (12, 12))
        self.assertGreater(len(self.api.log), 3)  # the first group was split
        self.assertTrue(all(t.startswith("Розділ") for t in self.stored()))


class PolishRunTest(EndToEndBase):
    target = "pl:Polish"
    fake = staticmethod(fake_pl)

    def test_runs_and_accepts_polish(self):
        self.run_all(keys=KEYS[:1])
        self.assertEqual(self.count_done(), (12, 12))
        self.assertTrue(all(t.startswith("Rozdział") for t in self.stored()))

    def test_english_echo_of_a_long_block_is_rejected(self):
        self.api.faults = {1: "latin"}
        self.run_all(keys=KEYS[:1])
        self.assertEqual(self.count_done(), (12, 12))
        self.assertGreater(len(self.api.log), 3)
        self.assertTrue(all(t.startswith("Rozdział") for t in self.stored()))

    def test_short_polish_block_with_a_foreign_name_is_accepted(self):
        src = Blk("Chapter 3: the arrival of the Count at Drakenhold")
        self.assertIsNone(check_text(src, "Rozdział 3: przybycie hrabiego do Drakenhold", "pl:Polish"))


if __name__ == "__main__":
    unittest.main()
