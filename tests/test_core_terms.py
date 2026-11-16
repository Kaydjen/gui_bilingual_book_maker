"""Term base: file, add_found rules, matching, request lines, glossary import, gender vote, candidates.
All names and sentences here are invented."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

from novelcore.__main__ import main as cli_main
from novelcore.store import Series
from novelcore.termmatch import (HEAD_CHARACTERS, HEAD_TERMS, Matcher, TermsHook, gender_marks, hook_for_series,
                                 scan_book)
from novelcore.termmine import (apply_gender_vote, gender_question, gender_vote, mine_candidates, snippets,
                                vote_verdict)
from novelcore.terms import (Entry, TermBase, candidate, format_seen, import_glossary, norm_key, parse_seen)
from novelcore.translate import HEADING, build_user
from tests.core_support import CoreCase
from tests.test_core_epub import make_epub

Blk = namedtuple("Blk", "text")


def make_base(*specs) -> TermBase:
    base = TermBase(None, "ru")
    for source, fields in specs:
        base.add(source, **fields)
    return base


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)


# ------------------------------------------------------------------ file
class FileTest(TmpCase):
    def test_round_trip(self):
        base = TermBase(self.dir / "terms.json", "ru")
        base.add("Zorvak", type="character", gender="male", tr="Зорвак", note="the captain", hint=True,
                 forms=["Captain Z"], evidence="he drew his sword")
        e = base.add("Fire Pit", type="item", gender="female", tr="Огненная яма", status="new")
        e.seen = {1, 2, 3, 7}
        e.count = 9
        base.save()
        back = TermBase.load(base.path)
        self.assertEqual(back.tag, "ru")
        self.assertEqual([x.to_dict("ru") for x in back], [x.to_dict("ru") for x in base])
        z = back.exact("zorvak")
        self.assertEqual((z.tr, z.gender, z.hint, z.forms, z.status), ("Зорвак", "male", True, ["Captain Z"], "confirmed"))
        self.assertEqual(back.exact("Fire Pit").seen, {1, 2, 3, 7})

    def test_sorted_one_entry_per_line(self):
        base = TermBase(self.dir / "terms.json", "ru")
        for s in ("beta", "Alpha", "Gamma", "alphabet"):
            base.add(s, tr="x")
        base.save()
        lines = (self.dir / "terms.json").read_text(encoding="utf-8").split("\n")
        body = [ln for ln in lines if ln.startswith("{") and '"source"' in ln]
        self.assertEqual(len(body), 4)
        names = [json.loads(ln.rstrip(","))["source"] for ln in body]
        self.assertEqual(names, ["Alpha", "alphabet", "beta", "Gamma"])
        self.assertTrue(all("\n" not in ln for ln in body))
        json.loads("\n".join(lines))  # the whole file is valid JSON

    def test_seen_is_compact(self):
        self.assertEqual(format_seen({5, 1, 2, 3, 9, 10}), "1-3,5,9-10")
        self.assertEqual(parse_seen("1-3,5,9-10"), {1, 2, 3, 5, 9, 10})
        self.assertEqual(parse_seen([1, "4-5", "junk"]), {1, 4, 5})

    def test_atomic_write_leaves_no_temp_and_keeps_old_file_on_failure(self):
        base = TermBase(self.dir / "terms.json", "ru")
        base.add("Zorvak", tr="Зорвак")
        base.save()
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["terms.json"])
        before = (self.dir / "terms.json").read_text(encoding="utf-8")
        base.add("Mirelle", tr="Мирель")
        with mock.patch("novelcore.terms.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                base.save()
        self.assertEqual((self.dir / "terms.json").read_text(encoding="utf-8"), before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["terms.json"])

    def test_unknown_fields_are_kept(self):
        raw = {"version": 1, "target": "ru", "owner": {"a": 1}, "entries": [
            {"source": "Zorvak", "type": "character", "gender": "male", "ru": "Зорвак", "status": "new",
             "count": 2, "mood": "grim", "de": "Zorwak", "extra_obj": {"k": [1, 2]}}]}
        p = self.dir / "terms.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        base = TermBase.load(p)
        base.exact("Zorvak").count = 5
        base.save()
        again = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(again["owner"], {"a": 1})
        ent = again["entries"][0]
        self.assertEqual((ent["mood"], ent["de"], ent["extra_obj"], ent["count"], ent["ru"]),
                         ("grim", "Zorwak", {"k": [1, 2]}, 5, "Зорвак"))

    def test_missing_file_is_empty_and_damaged_file_raises(self):
        self.assertEqual(len(TermBase.load(self.dir / "none.json", "ru")), 0)
        p = self.dir / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            TermBase.load(p)
        self.assertEqual(p.read_text(encoding="utf-8"), "{not json")

    def test_odd_records_are_tolerated(self):
        p = self.dir / "t.json"
        p.write_text(json.dumps({"entries": [
            {"source": "Ok", "type": "bogus", "gender": "??", "status": "weird", "ru": "ок", "count": "x"},
            {"nosource": 1}, {"source": "ok"}, "junk"]}), encoding="utf-8")
        base = TermBase.load(p)
        e = base.exact("Ok")
        self.assertEqual((e.type, e.gender, e.status, e.count), ("term", "unknown", "new", 0))
        self.assertEqual(len(base), 1)
        self.assertEqual(len(base.warnings), 3)


# ------------------------------------------------------------------ editing
class EditTest(unittest.TestCase):
    def test_edit_confirms_and_checks(self):
        base = make_base(("Zorvak", dict(status="new", tr="Зор", type="character")))
        e = base.edit("zorvak", tr="Зорвак", gender="male")
        self.assertEqual((e.status, e.tr, e.gender), ("confirmed", "Зорвак", "male"))
        with self.assertRaises(ValueError):
            base.edit("Zorvak", gender="robot")
        with self.assertRaises(KeyError):
            base.edit("Nobody", tr="x")

    def test_rename_and_collision(self):
        base = make_base(("Alpha", {}), ("Beta", {}))
        base.edit("Alpha", source="Alfa")
        self.assertIsNotNone(base.exact("Alfa"))
        self.assertIsNone(base.exact("Alpha"))
        with self.assertRaises(ValueError):
            base.edit("Alfa", source="beta")

    def test_add_rejects_used_spelling(self):
        base = make_base(("Alpha", dict(forms=["Alf"])))
        with self.assertRaises(ValueError):
            base.add("alf")

    def test_delete_clears_alias_links(self):
        base = make_base(("Mirelle", {}), ("Ember", dict(same_as="Mirelle")))
        self.assertTrue(base.delete("mirelle"))
        self.assertEqual(base.exact("Ember").same_as, "")
        self.assertFalse(base.delete("Mirelle"))

    def test_merge(self):
        base = make_base(("Zorvak", dict(tr="Зорвак", forms=["Z"])), ("Zorvac", dict(forms=["Zorv"], gender="male", note="n")))
        a, b = base.exact("Zorvak"), base.exact("Zorvac")
        a.seen, a.count = {1, 2}, 3
        b.seen, b.count = {2, 5}, 4
        base.add("Ember", same_as="Zorvac")
        out = base.merge("Zorvak", "Zorvac")
        self.assertIs(out, a)
        self.assertNotIn("zorvac", base._entries)
        self.assertEqual(sorted(a.forms), ["Z", "Zorv", "Zorvac"])
        self.assertEqual((a.seen, a.count, a.gender, a.note), ({1, 2, 5}, 7, "male", "n"))
        self.assertIs(base.exact("Zorvac"), a)  # the old spelling now finds the merged entry
        self.assertEqual(base.exact("Ember").same_as, "Zorvak")

    def test_get_by_variants(self):
        base = make_base(("The Hollow King", dict(forms=["H. King"])), ("Wolf", {}))
        self.assertIs(base.get("hollow king's"), base.exact("The Hollow King"))
        self.assertIs(base.get("Hollow King’s"), base.exact("The Hollow King"))
        self.assertIs(base.get("the wolves"), None)
        self.assertIs(base.get("The Wolfs"), base.exact("Wolf"))
        self.assertIs(base.get("h. king"), base.exact("The Hollow King"))
        self.assertIsNone(base.get("Wolfgang"))


class AddFoundTest(unittest.TestCase):
    def setUp(self):
        self.base = make_base(
            ("Zorvak", dict(type="character", gender="male", tr="Зорвак", note="captain", status="confirmed")),
            ("Fire Pit", dict(type="item", gender="unknown", tr="Яма", status="new")),
            ("Ash Lord", dict(type="title", tr="Лорд", status="new")))

    def test_confirmed_is_never_changed(self):
        rep = self.base.add_found([{"source": "zorvak", "type": "item", "gender": "female", "ru": "Другой",
                                    "note": "other", "seen": "4-6", "count": 12, "status": "unsure",
                                    "forms": ["Zed"]}], "model")
        e = self.base.exact("Zorvak")
        self.assertEqual((e.tr, e.gender, e.type, e.note, e.status, e.forms), ("Зорвак", "male", "character", "captain", "confirmed", []))
        self.assertEqual((e.seen, e.count), ({4, 5, 6}, 12))  # only seen/count may grow
        self.assertEqual(rep.refused, [("Zorvak", "confirmed")])
        self.assertEqual((rep.added, rep.updated), ([], []))

    def test_new_entries_are_updated(self):
        rep = self.base.add_found([
            {"source": "Fire Pit", "ru": "Огненная яма", "gender": "female", "note": "a pit", "seen": [3]},
            {"source": "Ash Lord", "gender": "male", "ru": "Пепельный лорд", "status": "new"}], "model")
        pit, lord = self.base.exact("Fire Pit"), self.base.exact("Ash Lord")
        self.assertEqual((pit.tr, pit.gender, pit.note, pit.seen, pit.status), ("Огненная яма", "female", "a pit", {3}, "new"))
        self.assertEqual((lord.tr, lord.gender, lord.status), ("Пепельный лорд", "male", "new"))
        self.assertEqual(sorted(rep.updated), ["Ash Lord", "Fire Pit"])

    def test_nothing_changes_reports_nothing(self):
        rep = self.base.add_found([{"source": "Fire Pit", "ru": "Яма"}], "program")
        self.assertEqual((rep.added, rep.updated, rep.refused), ([], [], []))

    def test_add_new_entries_with_origin_and_never_confirmed(self):
        rep = self.base.add_found([
            {"source": "Mirelle", "type": "character", "gender": "female", "ru": "Мирель", "status": "confirmed"},
            {"source": "Vale", "type": "place", "ru": "",
             "questions": {"gender": [{"value": "female", "evidence": "she 3"}, {"value": "male"}]}},
            {"source": ""}, {"source": "Zed", "forms": ["Zorvak"]}], "program")
        self.assertEqual(rep.added, ["Mirelle", "Vale"])
        self.assertEqual(self.base.exact("Mirelle").status, "new")  # a proposal cannot confirm
        self.assertEqual(self.base.exact("Vale").questions,
                         {"gender": [{"value": "female", "evidence": "she 3"}, {"value": "male", "evidence": ""}]})
        self.assertEqual(self.base.exact("Mirelle").extra["origin"], "program")
        self.assertEqual([r[0] for r in rep.refused], ["", "Zed"])

    def test_variant_spelling_finds_the_existing_entry(self):
        rep = self.base.add_found([{"source": "Fire Pit's", "ru": "Жаровня"}], "model")
        self.assertEqual(rep.updated, ["Fire Pit"])
        self.assertEqual(len(self.base), 3)

    def test_locked_field_survives_a_model_pass(self):
        pit = self.base.exact("Fire Pit")
        self.base.ask(pit, "gender", [{"value": "female", "evidence": "she 3"}, {"value": "male", "evidence": "he 5"}])
        self.base.answer(pit, "gender", "neuter")
        rep = self.base.add_found([{"source": "Fire Pit", "gender": "male", "ru": "Новая яма",
                                    "questions": {"gender": [{"value": "male"}, {"value": "female"}]}}], "model")
        self.assertEqual((pit.gender, pit.tr, pit.questions), ("neuter", "Новая яма", {}))  # tr was not locked
        self.assertEqual(rep.updated, ["Fire Pit"])

    def test_changed_value_closes_the_old_question(self):
        pit = self.base.exact("Fire Pit")
        self.base.ask(pit, "tr", [candidate("Яма"), candidate("Жаровня")])
        self.base.add_found([{"source": "Fire Pit", "ru": "Костёр"}], "model")
        self.assertEqual((pit.tr, pit.questions), ("Костёр", {}))
        self.base.add_found([{"source": "Fire Pit", "ru": "Очаг", "questions": {"tr": [{"value": "Очаг"}, {"value": "Яма"}]}}], "model")
        self.assertEqual(list(pit.questions), ["tr"])

    def test_entry_objects_are_accepted_and_rev_moves(self):
        rev = self.base.rev
        rep = self.base.add_found([Entry("Mirelle", type="character", tr="Мирель")], "model")
        self.assertEqual(rep.added, ["Mirelle"])
        self.assertGreater(self.base.rev, rev)


# ------------------------------------------------------------------ matching
def found(base, text):
    return [(e.source, text[s:t]) for e, s, t in Matcher(base).match(text)]


class MatchTest(unittest.TestCase):
    def test_case_and_boundaries(self):
        base = make_base(("Ash", {}), ("Silver Order", {}))
        self.assertEqual(found(base, "The SILVER order met ash."), [("Silver Order", "SILVER order"), ("Ash", "ash")])
        self.assertEqual(found(base, "Ashen flash trash Ash_ 2Ash"), [])
        self.assertEqual(found(base, "(Ash), [ash]; \"ASH\"!"), [("Ash", "Ash"), ("Ash", "ash"), ("Ash", "ASH")])

    def test_plural_possessive_and_the(self):
        base = make_base(("Ash", {}), ("Wolf", {}), ("The Hollow King", {}), ("Hollow", {}))
        self.assertEqual(found(base, "Ashes and Ash's and Ash’s and Ashs"),
                         [("Ash", "Ashes"), ("Ash", "Ash"), ("Ash", "Ash"), ("Ash", "Ashs")])
        self.assertEqual(found(base, "wolves, Wolfs, the wolf"), [("Wolf", "Wolfs"), ("Wolf", "wolf")])
        self.assertEqual(found(base, "Hollow King's crown; the Hollow King"),
                         [("The Hollow King", "Hollow King"), ("The Hollow King", "the Hollow King")])
        self.assertEqual(found(base, "the Hollow Kingdom"), [("Hollow", "Hollow")])  # not inside a longer word

    def test_longest_first_and_part_still_matches_elsewhere(self):
        base = make_base(("Fire", {}), ("Fire Lance", {}), ("Lance", {}))
        self.assertEqual(found(base, "Fire Lance and fire, then a lance."),
                         [("Fire Lance", "Fire Lance"), ("Fire", "fire"), ("Lance", "lance")])

    def test_forms_and_apostrophes(self):
        base = make_base(("Dragon’s Rest", dict(forms=["The Rest"])), ("Zorvak", dict(forms=["Captain Z"])))
        self.assertEqual(found(base, "At Dragon's Rest, captain z met Zorvak."),
                         [("Dragon's Rest", "Dragon's Rest"), ("Zorvak", "captain z"), ("Zorvak", "Zorvak")])
        self.assertEqual(found(base, "Dragon’s Rest"), [("Dragon's Rest", "Dragon’s Rest")])

    def test_start_end_whitespace_and_punctuated_terms(self):
        base = make_base(("Foo", {}), ("Silver Order", {}), ("[Fireball]", {}))
        self.assertEqual(found(base, "Foo"), [("Foo", "Foo")])
        self.assertEqual(found(base, "x Foo"), [("Foo", "Foo")])
        self.assertEqual(found(base, "Foo bar Foo"), [("Foo", "Foo"), ("Foo", "Foo")])
        self.assertEqual(found(base, "silver\nOrder and Silver Order"),
                         [("Silver Order", "silver\nOrder"), ("Silver Order", "Silver Order")])
        self.assertEqual(found(base, "cast [Fireball]!"), [("[Fireball]", "[Fireball]")])

    def test_blocks_with_markers_and_scan_chapter(self):
        base = make_base(("Zorvak", {}), ("Mirelle", {}))
        blocks = [Blk("<1>Zorvak</1> met Mirelle."), Blk("Mirelle left."), "Zorvak<2/> stayed. Zorvak!"]
        counts = Matcher(base).scan_chapter(blocks)
        self.assertEqual([(e.source, n) for e, n in counts.items()], [("Zorvak", 3), ("Mirelle", 2)])

    def test_matcher_follows_the_base(self):
        base = make_base(("Zorvak", {}))
        m = Matcher(base)
        self.assertEqual(len(m.match("Zorvak and Mirelle")), 1)
        base.add("Mirelle")
        self.assertEqual(len(m.match("Zorvak and Mirelle")), 2)

    def test_seen_and_count_update_once_per_chapter(self):
        base = make_base(("Zorvak", {}))
        e = base.exact("Zorvak")
        self.assertTrue(base.record_seen(e, 4, 3))
        self.assertFalse(base.record_seen(e, 4, 3))
        base.record_seen(e, 5, 2)
        self.assertEqual((e.seen, e.count), ({4, 5}, 5))

    def test_performance_smoke(self):
        letters = "bdfgklmnprstvz"
        vowels = "aeiou"

        def word(i):
            n = i
            out = []
            for k in range(3):
                out.append(letters[n % len(letters)] + vowels[(n // 3) % len(vowels)])
                n //= 7
            return "".join(out).capitalize()

        names = sorted({f"{word(i)} {word(i * 31 + 5)}" for i in range(5000)})
        self.assertGreater(len(names), 4000)
        base = TermBase(None, "ru")
        for n in names:
            base.add(n, tr="x")
        pool = [word(i) for i in range(400)]
        blocks = []
        for b in range(2000):
            words = [pool[(b * 7 + j) % len(pool)].lower() for j in range(18)]
            if b % 3 == 0:
                words[5] = names[(b * 13) % len(names)]
            blocks.append(" ".join(words) + ".")
        m = Matcher(base)
        t0 = time.perf_counter()
        counts = m.scan_chapter(blocks)
        took = time.perf_counter() - t0
        self.assertGreater(len(counts), 100)
        self.assertLess(took, 5.0, f"scan took {took:.2f}s")


# ------------------------------------------------------------------ lines for the translator
def sample_base() -> TermBase:
    return make_base(
        ("Zorvak", dict(type="character", gender="male", tr="Зорвак", note="the captain", hint=True)),
        ("Mirelle", dict(type="character", gender="female", tr="Мирель", note="a healer")),
        ("Ember", dict(type="character", gender="unknown", tr="Эмбер", same_as="Mirelle", hint=True, note="her alias")),
        ("Fire Pit", dict(type="item", gender="female", tr="Огненная яма")),
        ("Hollow Vale", dict(type="place", tr="Полая Долина")),
        ("Corin", dict(type="character", gender="male", tr="Корин")),
        ("Nameless", dict(type="character", gender="male", tr="")),
    )


class LinesTest(unittest.TestCase):
    def setUp(self):
        self.hook = TermsHook(sample_base())

    def test_group_lines_marks_hint_and_headings(self):
        group = [Blk("Zorvak stood by the Fire Pit."), Blk("Hollow Vale was quiet.")]
        lines = self.hook.lines_for(group, group)
        self.assertEqual(lines, [
            HEADING + HEAD_TERMS,
            "Zorvak -> Зорвак (м) - the captain",
            "Fire Pit -> Огненная яма (ж)",
            "Hollow Vale -> Полая Долина",
        ])

    def test_alias_has_own_translation_and_inherited_gender(self):
        group = [Blk("Ember waved.")]
        self.assertEqual(self.hook.lines_for(group, group), [HEADING + HEAD_TERMS, "Ember -> Эмбер (ж) - her alias"])

    def test_chapter_characters_listed_once_and_not_repeated(self):
        group = [Blk("Zorvak stood by the Fire Pit.")]
        chapter = [Blk("Mirelle sighed."), *group, Blk("Corin and Zorvak left. Mirelle too. Ember too."),
                   Blk("Nameless came.")]
        lines = self.hook.lines_for(chapter, group)
        self.assertEqual(lines, [
            HEADING + HEAD_TERMS, "Zorvak -> Зорвак (м) - the captain", "Fire Pit -> Огненная яма (ж)",
            HEADING + HEAD_CHARACTERS, "Mirelle -> Мирель (ж)", "Corin -> Корин (м)", "Ember -> Эмбер (ж)"])

    def test_only_characters_part_and_no_hint_there(self):
        group = [Blk("It rained.")]
        chapter = [Blk("Ember watched."), *group, Blk("Zorvak slept.")]
        self.assertEqual(self.hook.lines_for(chapter, group),
                         [HEADING + HEAD_CHARACTERS, "Ember -> Эмбер (ж)", "Zorvak -> Зорвак (м)"])

    def test_nothing_found_gives_nothing(self):
        group = [Blk("It rained.")]
        self.assertEqual(self.hook.lines_for(group, group), [])

    def test_unknown_gender_character_has_no_mark(self):
        base = make_base(("Veil", dict(type="character", tr="Вуаль")))
        group = [Blk("Veil spoke.")]
        self.assertEqual(TermsHook(base).lines_for([Blk("Veil spoke. Veil left.")], group),
                         [HEADING + HEAD_TERMS, "Veil -> Вуаль"])

    def test_deterministic_order_of_first_appearance(self):
        group = [Blk("Fire Pit, then Zorvak, then Fire Pit again."), Blk("Hollow Vale.")]
        a = self.hook.lines_for(group, group)
        b = TermsHook(sample_base()).lines_for(group, group)
        self.assertEqual(a, b)
        self.assertEqual([ln.split(" ->")[0] for ln in a[1:]], ["Fire Pit", "Zorvak", "Hollow Vale"])

    def test_chapter_blocks_may_be_a_callable_called_once_per_chapter(self):
        calls = []

        def blocks():
            calls.append(1)
            return [Blk("Corin waits.")]

        group = [Blk("It rained.")]
        h = TermsHook(sample_base())
        h.lines_for(blocks, group, chapter_key=7)
        h.lines_for(blocks, group, chapter_key=7)
        self.assertEqual(len(calls), 1)

    def test_build_user_renders_headings(self):
        lines = self.hook.lines_for([Blk("Corin waits. Zorvak!")], [Blk("Zorvak!")])
        text = build_user(lines, [], [{"id": 1, "text": "Zorvak!"}])
        head, rest = text.split("\n\n", 1)
        self.assertTrue(head.startswith("TERMS\n" + HEAD_TERMS))
        self.assertIn("\n" + HEAD_CHARACTERS + "\nCorin -> Корин (м)", head)
        self.assertNotIn(HEADING, text)
        # a plain hook without headings keeps the old section header
        plain = build_user(["Foxhound -> Лис"], [], [{"id": 1, "text": "x"}])
        self.assertTrue(plain.startswith("TERMS (use these renderings exactly)\nFoxhound -> Лис"))


class RunnerTermsTest(CoreCase):
    chapters = 1
    per_request = 2

    def add_book(self):
        epub = self.dir / "Names.epub"
        body = "".join(f"<p>{t}</p>" for t in (
            "Zorvak greeted Mirelle at the gate today.", "The hall was quiet and very cold tonight.",
            "Mirelle said that she would stay a while longer.", "Nothing else happened in the hall after that."))
        make_epub(epub, {"c0.xhtml": body})
        return self.series.add_book(epub)

    def user_texts(self):
        return [e["user"] for e in self.api.log if e["user"]]

    def test_request_carries_the_lines_when_terms_json_exists(self):
        name = self.add_book()
        base = TermBase(self.series.path / "terms.json", "ru")
        base.add("Zorvak", type="character", gender="male", tr="Зорвак")
        base.add("Mirelle", type="character", gender="female", tr="Мирель")
        base.save()
        self.run_all(keys=self.keys[:1], in_flight=1, book=name)
        users = self.user_texts()
        self.assertEqual(len(users), 2)
        first, second = users
        self.assertIn("TERMS\n" + HEAD_TERMS + "\nZorvak -> Зорвак (м)\nMirelle -> Мирель (ж)", first)
        self.assertNotIn(HEAD_CHARACTERS, first)  # both already listed above
        self.assertIn(HEAD_TERMS + "\nMirelle -> Мирель (ж)", second)
        self.assertIn(HEAD_CHARACTERS + "\nZorvak -> Зорвак (м)", second)

    def test_request_unchanged_without_terms_json(self):
        name = self.add_book()
        self.run_all(keys=self.keys[:1], in_flight=1, book=name)
        users = self.user_texts()
        self.assertEqual(len(users), 2)
        self.assertTrue(all("TERMS" not in u for u in users))
        self.assertTrue(all(u.startswith("TEXT") or u.startswith("CONTEXT") for u in users))

    def test_hook_for_series(self):
        self.assertIsNone(hook_for_series(self.series))
        TermBase(self.series.path / "terms.json", "ru").save()
        self.assertIsInstance(hook_for_series(self.series), TermsHook)

    def test_scan_book_updates_seen_and_count(self):
        name = self.add_book()
        base = make_base(("Zorvak", {}), ("Mirelle", {}), ("Absent", {}))
        with self.series.open_book(name) as book:
            res = scan_book(base, book, 0, 0)
            again = scan_book(base, book, 0, 0)
        self.assertEqual((res["chapters"], res["matched"], res["hits"]), (1, 2, 3))
        self.assertEqual(again["hits"], 3)
        z, m, a = base.exact("Zorvak"), base.exact("Mirelle"), base.exact("Absent")
        self.assertEqual((z.count, m.count, a.count), (1, 2, 0))
        self.assertEqual((z.seen, a.seen), ({0}, set()))


# ------------------------------------------------------------------ glossary import
class ImportTest(TmpCase):
    def write(self, name, data):
        p = self.dir / name
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def test_priority_conflicts_and_apostrophes(self):
        f1 = self.write("g1.json", {"Fire Pit": "Яма", "Baz's Axe": "Топор База", "Only One": "Один"})
        f2 = self.write("g2.json", {"fire  pit": "Жаровня", "Baz’s Axe": "Топор База", "Second": "Второй", "Empty": ""})
        base = TermBase(None, "ru")
        rep = import_glossary(base, [f1, f2])
        self.assertEqual((rep.added, rep.same, rep.skipped), (4, 1, 1))
        self.assertEqual(len(rep.conflicts), 1)
        c = rep.conflicts[0]
        self.assertEqual((c.source, c.kept, c.ignored, c.kept_file, c.ignored_file), ("Fire Pit", "Яма", "Жаровня", "g1.json", "g2.json"))
        pit = base.exact("fire pit")
        self.assertEqual((pit.tr, pit.status, pit.type, pit.gender), ("Яма", "confirmed", "term", "unknown"))
        self.assertEqual(base.exact("Baz’s Axe").source, "Baz's Axe")  # stored with the straight apostrophe
        self.assertEqual(len(base), 4)
        self.assertEqual(pit.questions, {"tr": [candidate("Яма", "g1.json"), candidate("Жаровня", "g2.json")]})
        self.assertEqual([e.source for e in base.questioned()], ["Fire Pit"])  # exact duplicates ask nothing

    def test_earlier_file_is_shown_whatever_the_names(self):
        f1 = self.write("a.json", {"Fire Pit": "Яма"})
        f2 = self.write("b.json", {"Fire Pit": "Жаровня"})
        for order, want, other in (([f1, f2], "Яма", "Жаровня"), ([f2, f1], "Жаровня", "Яма")):
            base = TermBase(None, "ru")
            rep = import_glossary(base, order)
            self.assertEqual(base.exact("Fire Pit").tr, want)
            self.assertEqual(len(rep.conflicts), 1)
            self.assertEqual([c["value"] for c in base.exact("Fire Pit").questions["tr"]], [want, other])

    def test_three_files_and_answered_question(self):
        files = [self.write("a.json", {"Fire Pit": "Яма"}), self.write("b.json", {"Fire Pit": "Жаровня"}),
                 self.write("c.json", {"Fire Pit": "Жаровня"})]
        base = TermBase(None, "ru")
        rep = import_glossary(base, files)
        self.assertEqual(len(rep.conflicts), 2)
        self.assertEqual(base.exact("Fire Pit").questions["tr"],
                         [candidate("Яма", "a.json"), candidate("Жаровня", "b.json, c.json")])
        base.answer("Fire Pit", "tr", "Очаг")
        self.assertEqual(import_glossary(base, files).conflicts, [])  # the answer is not asked again
        self.assertEqual(base.exact("Fire Pit").tr, "Очаг")

    def test_question_survives_save_and_load(self):
        f1 = self.write("a.json", {"Fire Pit": "Яма"})
        f2 = self.write("b.json", {"Fire Pit": "Жаровня"})
        base = TermBase(self.dir / "terms.json", "ru")
        import_glossary(base, [f1, f2])
        base.save()
        back = TermBase.load(base.path)
        self.assertEqual(back.exact("Fire Pit").questions, base.exact("Fire Pit").questions)

    def test_exact_duplicates_are_silent_and_existing_base_entries_win(self):
        f1 = self.write("a.json", {"Fire Pit": "Яма"})
        f2 = self.write("b.json", {"FIRE PIT": "Яма", "Zorvak": "Зор"})
        base = make_base(("Zorvak", dict(tr="Зорвак")))
        rep = import_glossary(base, [f1, f2])
        self.assertEqual(rep.same, 1)
        self.assertEqual([c.source for c in rep.conflicts], ["Zorvak"])
        self.assertEqual(base.exact("Zorvak").tr, "Зорвак")
        self.assertEqual(base.exact("Zorvak").questions["tr"], [candidate("Зорвак", "base"), candidate("Зор", "b.json")])

    def test_bad_file_raises(self):
        p = self.write("list.json", ["a"])
        with self.assertRaises(ValueError):
            import_glossary(TermBase(None, "ru"), [p])


# ------------------------------------------------------------------ gender
class GenderTest(unittest.TestCase):
    def test_vote_counts_pronouns_after_mentions(self):
        text = "Zorvak drew his sword and he swung it.\nLater Mirelle smiled. She took her bag and thanked him."
        self.assertEqual(gender_vote("Zorvak", text), (2, 0))
        m, f = gender_vote("Mirelle", text)
        self.assertEqual(f, 2)
        self.assertEqual(gender_vote("Nobody", text), (0, 0))

    def test_window_limit_boundary_and_line_break(self):
        far = "Zorvak " + "x" * 130 + " he came."
        self.assertEqual(gender_vote("Zorvak", far), (0, 0))
        broken = "Zorvak walked.\nHe slept."
        self.assertEqual(gender_vote("Zorvak", broken), (0, 0))
        self.assertEqual(gender_vote("Zorvak", "Zorvak's hat, his own."), (1, 0))
        self.assertEqual(gender_vote("Zorvak", "Zorvakian said he did."), (0, 0))

    def test_pronouns_counted_once_and_spellings(self):
        text = "Zorvak and Captain Z waited; he sighed."
        self.assertEqual(gender_vote("Zorvak", text), (1, 0))
        self.assertEqual(gender_vote(["Zorvak", "Captain Z"], text), (1, 0))
        self.assertEqual(gender_vote("zorvak", "ZORVAK nodded. Her friend, hers, herself."), (0, 3))

    def test_verdict_thresholds(self):
        cases = {(0, 0): "unknown", (1, 0): "unknown", (0, 1): "unknown", (2, 0): "male", (0, 2): "female",
                 (1, 1): "unknown", (2, 1): "male", (3, 2): "unknown", (4, 2): "male", (2, 4): "female",
                 (5, 3): "unknown", (10, 1): "male"}
        for (m, f), want in cases.items():
            self.assertEqual(vote_verdict(m, f), want, (m, f))

    def test_question_rule(self):
        # the model's answer and the count disagree: both are candidates, each with its own count
        self.assertEqual(gender_question("male", 1, 4),
                         [candidate("male", "he 1"), candidate("female", "she 4")])
        self.assertEqual(gender_question("female", 5, 0),
                         [candidate("female", "she 0"), candidate("male", "he 5")])
        # agreement, or a count that cannot decide, asks nothing
        self.assertIsNone(gender_question("male", 4, 1))
        self.assertIsNone(gender_question("female", 0, 1))
        self.assertIsNone(gender_question("male", 0, 0))
        self.assertIsNone(gender_question("female", 2, 2))
        # the model said unknown: always a question
        self.assertEqual(gender_question("unknown", 5, 0), [candidate("unknown", "he 5 / she 0"), candidate("male", "he 5")])
        self.assertEqual(gender_question("unknown", 0, 0), [candidate("unknown", "he 0 / she 0")])
        self.assertEqual([c["value"] for c in gender_question("unknown", 2, 2)], ["unknown", "male", "female"])
        # a non-person gender of the model is not voted on
        self.assertIsNone(gender_question("neuter", 5, 0))

    def test_apply_raises_questions_only_on_disagreement_or_unknown(self):
        text = ("Zorvak drew his sword, he said.\nMirelle laughed. She took her bag.\n"
                "Corin looked up, and she smiled at Corin; her hand moved.\nVale grew.\nQuill nodded once.")
        props = [
            {"source": "Zorvak", "type": "character", "gender": "male"},
            {"source": "Mirelle", "type": "character", "gender": "male"},
            {"source": "Nolan", "type": "character", "gender": "male"},  # no pronouns at all: unmarked
            {"source": "Corin", "type": "character", "gender": "unknown"},
            {"source": "Vale", "type": "place", "gender": "neuter"},
            {"source": "Quill", "type": "character", "gender": "unknown", "evidence": "a quote"},
        ]
        marked = apply_gender_vote(props, text)
        self.assertEqual([p["source"] for p in marked], ["Mirelle", "Corin", "Quill"])
        by = {p["source"]: p for p in props}
        self.assertEqual(by["Mirelle"]["questions"]["gender"], [candidate("male", "he 0"), candidate("female", "she 2")])
        self.assertEqual(by["Corin"]["questions"]["gender"][:2], [candidate("unknown", "he 0 / she 2"), candidate("female", "she 2")])
        self.assertEqual(by["Quill"]["questions"]["gender"], [candidate("unknown", "he 0 / she 0")])
        self.assertFalse(by["Zorvak"]["questions"] or by["Nolan"]["questions"])
        self.assertEqual(by["Zorvak"]["evidence"], "pronouns he 2 / she 0")  # counts always recorded
        self.assertEqual(by["Nolan"]["evidence"], "pronouns he 0 / she 0")
        self.assertEqual(by["Quill"]["evidence"], "a quote; pronouns he 0 / she 0")
        self.assertNotIn("evidence", by["Vale"])
        self.assertNotIn("status", by["Mirelle"])

    def test_apply_on_entries_skips_locked_and_confirmed_and_clears_stale(self):
        text = "Mirelle laughed. She took her bag."
        ent = Entry("Mirelle", type="character", gender="male")
        self.assertEqual(apply_gender_vote([ent], text), [ent])
        self.assertEqual(ent.status, "new")
        ent.gender = "female"  # the model corrected itself on a later pass
        self.assertEqual(apply_gender_vote([ent], text), [])
        self.assertEqual(ent.questions, {})
        self.assertEqual(ent.evidence, "pronouns he 0 / she 2")
        apply_gender_vote([ent], text)
        self.assertEqual(ent.evidence, "pronouns he 0 / she 2")  # not stacked
        base = TermBase(None, "ru")
        e2 = base.add("Mirelle", type="character", gender="male", status="new")
        base.ask(e2, "gender", [candidate("male"), candidate("female")])
        base.answer(e2, "gender", "male")
        self.assertEqual(apply_gender_vote([e2], text), [])
        self.assertEqual(e2.evidence, "")
        done = Entry("Mirelle", type="character", gender="male", status="confirmed")
        self.assertEqual(apply_gender_vote([done], text), [])
        self.assertEqual(done.questions, {})


# ------------------------------------------------------------------ questions on the base
class QuestionTest(TmpCase):
    def make(self):
        base = TermBase(self.dir / "terms.json", "ru")
        base.add("Mirelle", type="character", gender="female", tr="Мирель", status="new")
        base.add("Zorvak", type="character", gender="male", tr="Зорвак", status="new")
        base.add("Vale", type="place", status="new")
        base.ask("Mirelle", "gender", [candidate("female", "she 3"), candidate("male", "he 5")])
        base.ask("Mirelle", "tr", [candidate("Мирель", "a.json"), candidate("Мирэль", "b.json")])
        return base

    def test_list_and_answer(self):
        base = self.make()
        self.assertEqual([e.source for e in base.questioned()], ["Mirelle"])
        e = base.answer("Mirelle", "gender", "male")  # any value answers, listed or not
        self.assertEqual((e.gender, sorted(e.questions), e.locked), ("male", ["tr"], {"gender"}))
        base.answer(e, "tr", "Мирэль")
        self.assertEqual((e.tr, e.questions, e.locked), ("Мирэль", {}, {"gender", "tr"}))
        self.assertEqual(base.questioned(), [])
        self.assertEqual(e.status, "new")  # answering does not confirm the rest of the entry
        with self.assertRaises(KeyError):
            base.answer(e, "gender", "female")
        with self.assertRaises(ValueError):
            base.ask(e, "note", [candidate("x")])

    def test_bad_answers(self):
        base = self.make()
        with self.assertRaises(ValueError):
            base.answer("Mirelle", "gender", "robot")
        with self.assertRaises(KeyError):
            base.answer("Nobody", "gender", "male")
        with self.assertRaises(ValueError):
            base.ask("Vale", "tr", [])
        self.assertEqual(sorted(base.exact("Mirelle").questions), ["gender", "tr"])

    def test_confirm_answers_with_the_shown_values(self):
        base = self.make()
        e = base.confirm("Mirelle")
        self.assertEqual((e.status, e.questions, e.gender, e.tr), ("confirmed", {}, "female", "Мирель"))
        again = self.make()
        again.edit("Mirelle", note="healer")  # an edit confirms as well
        self.assertEqual(again.exact("Mirelle").questions, {})

    def test_answered_field_is_not_touched_by_a_pass_and_survives_the_file(self):
        base = self.make()
        base.answer("Mirelle", "tr", "Мирэль")
        base.save()
        back = TermBase.load(base.path)
        e = back.exact("Mirelle")
        self.assertEqual((e.locked, sorted(e.questions)), ({"tr"}, ["gender"]))
        back.add_found([{"source": "Mirelle", "ru": "Мирелла", "gender": "female"}], "model")
        self.assertEqual((e.tr, e.gender, sorted(e.questions)), ("Мирэль", "female", ["gender"]))

    def test_file_format_and_order(self):
        base = self.make()
        base.save()
        lines = [ln for ln in (self.dir / "terms.json").read_text(encoding="utf-8").split("\n") if '"source"' in ln]
        self.assertEqual(len(lines), 3)
        line = json.loads(lines[0].rstrip(","))
        self.assertEqual(list(line)[:7], ["source", "type", "gender", "ru", "questions", "status", "count"])
        self.assertEqual(line["questions"]["gender"], [{"value": "female", "evidence": "she 3"},
                                                      {"value": "male", "evidence": "he 5"}])
        first = (self.dir / "terms.json").read_text(encoding="utf-8")
        TermBase.load(base.path).save()
        self.assertEqual((self.dir / "terms.json").read_text(encoding="utf-8"), first)  # load/save is stable

    def test_old_unsure_file_still_loads(self):
        p = self.dir / "old.json"
        p.write_text(json.dumps({"version": 1, "target": "ru", "entries": [
            {"source": "Mirelle", "type": "character", "gender": "female", "ru": "Мирель", "status": "unsure",
             "count": 2, "evidence": "she smiled"},
            {"source": "Corin", "type": "character", "gender": "male", "ru": "Корин", "status": "new", "unsure": True},
            {"source": "Vale", "type": "place", "ru": "Долина", "status": "new", "unsure": False}]},
            ensure_ascii=False), encoding="utf-8")
        base = TermBase.load(p)
        self.assertEqual(base.exact("Mirelle").questions, {"gender": [candidate("female", "she smiled")]})
        self.assertEqual(base.exact("Mirelle").status, "new")
        self.assertEqual(base.exact("Corin").questions, {"gender": [candidate("male")]})
        self.assertEqual(base.exact("Vale").questions, {})
        base.save()
        text = p.read_text(encoding="utf-8")
        self.assertNotIn("unsure", text.replace('"questions"', ""))

    def test_request_lines(self):
        base = TermBase(None, "ru")
        base.add("Mirelle", type="character", gender="female", tr="Мирель")
        base.add("Ember", type="character", gender="unknown", tr="Эмбер", same_as="Mirelle")
        base.add("Zorvak", type="character", gender="male", tr="Зорвак")
        base.ask("Mirelle", "gender", [candidate("female", "she 3"), candidate("male", "he 5")])
        base.ask("Zorvak", "tr", [candidate("Зорвак"), candidate("Зорваг")])
        hook = TermsHook(base)
        group = [Blk("Mirelle, Ember and Zorvak met.")]
        self.assertEqual(hook.lines_for(group, group),
                         [HEADING + HEAD_TERMS, "Mirelle -> Мирель", "Ember -> Эмбер", "Zorvak -> Зорвак (м)"])
        base.answer("Mirelle", "gender", "female")
        self.assertEqual(hook.lines_for(group, group)[1:3], ["Mirelle -> Мирель (ж)", "Ember -> Эмбер (ж)"])

    def test_cli_questions_are_ascii_safe(self):
        series = Series.create(self.dir / "lib", "s")
        self.make().save(series.path / "terms.json")
        raw = io.BytesIO()
        buf = io.TextIOWrapper(raw, encoding="ascii")  # a console that cannot print Cyrillic
        with contextlib.redirect_stdout(buf):
            cli_main(["terms", "questions", str(series.path)])
        buf.flush()
        out = raw.getvalue().decode("ascii")
        self.assertTrue(out.isascii())
        self.assertIn("Mirelle -> \\u041c", out)
        self.assertIn("gender: female [she 3] | male [he 5]", out)
        self.assertIn("1 entries with open questions", out)

    def test_gender_marks_per_language(self):
        self.assertEqual(gender_marks("ru")["female"], "ж")
        self.assertEqual(gender_marks("ru-RU")["male"], "м")
        self.assertEqual(gender_marks("fr")["female"], "female")
        self.assertEqual(gender_marks("")["male"], "male")
        base = TermBase(None, "fr")
        base.add("Mirelle", type="character", gender="female", tr="Mirelle")
        group = [Blk("Mirelle came.")]
        self.assertEqual(TermsHook(base).lines_for(group, group)[1], "Mirelle -> Mirelle (female)")


# ------------------------------------------------------------------ candidates
MINE_TEXT = (
    "The road was long. Then Tavrin Holt walked to the gate with Kelvara. "
    "They met Tavrin Holt again near Kelvara. Tavrin Holt's sword shone. "
    "He feared the Kelvaras and the Silver Order. The Silver Order watched. Later, the Silver Order's banner fell. "
    "Brann and Sela argued. He saw Brann and Sela again. She spoke with Sela and with Brann, and later Brann left. "
    "Chapter 12 began. Chapter 12 ended. In Chapter 12 again, Zim stood still. "
    "Marlow came. Marlow went. Marlow stayed. Suddenly Nobody spoke. "
    "The Order of the Pale Flame met. They praised the Order of the Pale Flame. "
    "He bowed to Holt twice, and to Holt again."
)


class MineTest(unittest.TestCase):
    def setUp(self):
        self.found = {c.term: c for c in mine_candidates(MINE_TEXT)}

    def test_multiword_runs_and_possessive_folded(self):
        self.assertEqual(self.found["Tavrin Holt"].count, 3)  # "Tavrin Holt's" folded in
        self.assertIn("Order of the Pale Flame", self.found)
        self.assertEqual(self.found["Order of the Pale Flame"].count, 2)

    def test_leading_the_dropped_and_plural_folded(self):
        self.assertIn("Silver Order", self.found)
        self.assertEqual(self.found["Silver Order"].count, 3)
        self.assertNotIn("The Silver Order", self.found)
        self.assertEqual(self.found["Kelvara"].count, 3)  # two plain + the plural
        self.assertNotIn("Kelvaras", self.found)

    def test_a_and_b_split_when_both_stand_alone(self):
        self.assertNotIn("Brann and Sela", self.found)
        self.assertIn("Brann", self.found)
        self.assertIn("Sela", self.found)

    def test_numbers_and_chapter_dropped_and_single_word_rules(self):
        self.assertFalse([t for t in self.found if "Chapter" in t or t.isdigit()])
        self.assertNotIn("Zim", self.found)  # one mention only
        self.assertNotIn("Marlow", self.found)  # always at a sentence start
        self.assertNotIn("Nobody", self.found)  # stop list

    def test_part_of_longer_name_only_when_standing_alone(self):
        self.assertNotIn("Tavrin", self.found)
        self.assertIn("Holt", self.found)  # "to Holt twice, and to Holt again"

    def test_sorted_by_count(self):
        counts = [c.count for c in mine_candidates(MINE_TEXT)]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_known_terms_are_removed_whatever_the_spelling(self):
        base = make_base(("Silver Order", {}), ("Kelvara", dict(forms=["Kel"])), ("Holt", {}))
        names = {c.term for c in mine_candidates(MINE_TEXT, base)}
        self.assertNotIn("Silver Order", names)
        self.assertNotIn("Kelvara", names)
        self.assertNotIn("Holt", names)
        self.assertIn("Tavrin Holt", names)

    def test_input_may_be_blocks(self):
        blocks = [Blk(p) for p in MINE_TEXT.split(". ")]
        self.assertTrue(mine_candidates(blocks))

    def test_snippets_on_demand(self):
        sn = snippets(MINE_TEXT, "Kelvara", k=3, width=20)
        self.assertTrue(1 <= len(sn) <= 3)
        self.assertTrue(all("Kelvara" in s and len(s) <= 20 * 2 + len("Kelvara") for s in sn))
        self.assertEqual(snippets(MINE_TEXT, "Nowhere"), [])


if __name__ == "__main__":
    unittest.main()
