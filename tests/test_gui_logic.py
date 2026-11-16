import json
import tempfile
import unittest
from pathlib import Path

from novelgui import chapterlogic as cl
from novelgui import model
from novelgui import selection, termlogic
from novelgui.settings import Settings
from novelcore.terms import Entry


class TitleNumbers(unittest.TestCase):
    def test_title_number(self):
        self.assertEqual(cl.title_number("Chapter 2729 - Chapter 1027"), 2729)
        self.assertEqual(cl.title_number("Глава 12. Начало"), 12)
        self.assertEqual(cl.title_number("Prologue 7 and 9"), 7)
        self.assertIsNone(cl.title_number("Epilogue"))
        self.assertIsNone(cl.title_number(""))

    def test_pieces(self):
        self.assertEqual(cl.parse_pieces("2729-2783"), [(2729, 2783)])
        self.assertEqual(cl.parse_pieces("5, 10-12"), [(5, 5), (10, 12)])
        self.assertEqual(cl.parse_pieces("9-3"), [(3, 9)])
        self.assertIsNone(cl.parse_pieces("abc"))

    def test_select_by_title_numbers(self):
        numbers = [None, None, 1, 2, 3, 4, 5]          # two contents pages first
        toc = [True, True] + [False] * 5
        r = cl.select_by_numbers("2-4", numbers, toc)
        self.assertEqual(r.indices, (3, 4, 5))
        self.assertFalse(r.by_position)

    def test_repeated_number_falls_back_to_position(self):
        numbers = [1, 2, 2, 3, 4]
        toc = [False] * 5
        r = cl.select_by_numbers("2-3", numbers, toc)
        self.assertTrue(r.by_position)
        self.assertEqual(r.indices, (1, 2, 3))      # typed 2 = shown number 2 = index 1

    def test_missing_number_and_errors(self):
        numbers = [1, 2, 3]
        toc = [False] * 3
        self.assertEqual(cl.select_by_numbers("1-2", numbers, toc).indices, (0, 1))
        self.assertTrue(cl.select_by_numbers("50", numbers, toc).error)
        self.assertTrue(cl.select_by_numbers("x", numbers, toc).error)

    def test_toc_never_selected(self):
        numbers = [None, None, 2]
        toc = [True, False, False]
        r = cl.select_by_numbers("1-2", numbers, toc)
        self.assertNotIn(0, r.indices)
        self.assertEqual(r.indices, (1, 2))

    def test_display_numbers_are_one_based(self):
        self.assertEqual(cl.display_no(0), 1)
        self.assertEqual(cl.from_display(cl.display_no(41)), 41)
        r = cl.select_by_numbers("3-4", [None] * 6, [False] * 6)
        self.assertEqual(r.indices, (2, 3))
        self.assertIn("3 to 4", r.note)
        self.assertEqual(cl.select_by_numbers("0", [None] * 6, [False] * 6).error, "no such chapter: 0")


class States(unittest.TestCase):
    def test_count_log_last_wins(self):
        recs = [{"i": 0, "status": "failed"}, {"i": 0, "status": "ok"}, {"i": 1, "status": "failed"}]
        self.assertEqual(cl.count_log(recs), (1, 1))

    def test_kinds(self):
        self.assertEqual(cl.chapter_state(True, 5, 0, 0).kind, "toc")
        self.assertEqual(cl.chapter_state(False, None, 0, 0).kind, "unknown")
        self.assertEqual(cl.chapter_state(False, 10, 0, 0).kind, "none")
        self.assertEqual(cl.chapter_state(False, 10, 4, 0).kind, "partly")
        self.assertEqual(cl.chapter_state(False, 10, 10, 0).kind, "translated")
        st = cl.chapter_state(False, 10, 6, 2)
        self.assertEqual(st.kind, "failed")
        self.assertAlmostEqual(st.fraction, 0.6)

    def test_cache_roundtrip_and_invalidation(self):
        with tempfile.TemporaryDirectory() as d:
            p = cl.cache_path(d, "Book: one")
            infos = [cl.ChapterInfo(0, "a.xhtml", "T", False, 7, (10, 20), 3, 1), cl.ChapterInfo(1, "b.xhtml")]
            self.assertTrue(cl.save_cache(p, (100, 5), infos))
            got = cl.load_cache(p, (100, 5))
            self.assertEqual(got[0].blocks, 7)
            self.assertEqual(got[0].done, 3)
            self.assertIsNone(got[1].blocks)
            self.assertIsNone(cl.load_cache(p, (101, 5)))     # book file size changed
            self.assertIsNone(cl.load_cache(p, (100, 6)))     # book mtime changed
            self.assertTrue(cl.log_changed(got[0], (10, 21)))
            self.assertFalse(cl.log_changed(got[0], (10, 20)))
            p.write_text("{broken", encoding="utf-8")
            self.assertIsNone(cl.load_cache(p, (100, 5)))

    def test_selection_size(self):
        infos = [cl.ChapterInfo(i, blocks=10 if i != 2 else None) for i in range(4)]
        self.assertEqual(cl.selection_size(infos, (0, 1, 2)), (3, 20, False))


class SelectionModel(unittest.TestCase):
    def test_make_and_spans(self):
        s = selection.make("b", [5, 3, 4, 9, 3])
        self.assertEqual(s.indices, (3, 4, 5, 9))
        self.assertEqual(s.spans(), [(3, 5), (9, 9)])
        self.assertEqual(len(s), 4)
        self.assertFalse(selection.Selection())

    def test_summary(self):
        s = selection.make("b", [1, 2])
        self.assertEqual(selection.summary(s, 2, 1204), "2 chapters · 1 204 blocks")
        self.assertEqual(selection.summary(selection.Selection(), 0, 0), "")
        self.assertIn("+", selection.summary(s, 2, 10, complete=False))


class SettingsFile(unittest.TestCase):
    def test_roundtrip_and_damaged(self):
        with tempfile.TemporaryDirectory() as d:
            s = Settings(d)
            s.set("library", "x")
            self.assertEqual(Settings(d).get("library"), "x")
            (Path(d) / "settings.json").write_text("{nope", encoding="utf-8")
            s2 = Settings(d)
            self.assertTrue(s2.damaged)
            self.assertEqual(s2.data, {})
            s2.set("a", 1)
            self.assertEqual(Settings(d).get("a"), 1)
            (Path(d) / "settings.json").write_text("[1]", encoding="utf-8")
            self.assertTrue(Settings(d).damaged)

    def test_get_float_clamps(self):
        with tempfile.TemporaryDirectory() as d:
            s = Settings(d)
            s.set("f", 9)
            self.assertEqual(s.get_float("f", 0.3, 0.1, 0.7), 0.7)
            s.set("f", "x")
            self.assertEqual(s.get_float("f", 0.3, 0.1, 0.7), 0.3)


def E(source, status="new", count=0, seen=(), tr="", questions=None, forms=(), type="term"):
    return Entry(source, status=status, count=count, seen=set(seen), tr=tr, questions=questions, forms=list(forms),
                 type=type)


class TermLists(unittest.TestCase):
    def setUp(self):
        self.q = {"gender": [{"value": "male", "evidence": ""}]}
        self.es = [E("Beta", count=5, seen=[4]), E("Alpha", count=9, seen=[4]), E("Gamma", count=1, seen=[2]),
                   E("Delta", "confirmed", count=7), E("Eps", questions=self.q, count=3, seen=[9])]

    def test_filters_and_counts(self):
        self.assertEqual(termlogic.counts(self.es), {"new": 4, "known": 1, "questions": 1})
        names = lambda tab: [e.source for e in termlogic.arrange(self.es, tab, "", None, "count", True)]
        self.assertEqual(names("known"), ["Delta"])
        self.assertEqual(names("questions"), ["Eps"])
        self.assertEqual(len(names("new")), 4)

    def test_new_default_order_first_chapter_then_count(self):
        key, desc = termlogic.default_order("new")
        rows = termlogic.arrange(self.es, "new", "", None, key, desc)
        self.assertEqual([e.source for e in rows], ["Gamma", "Alpha", "Beta", "Eps"])

    def test_known_order_by_count(self):
        self.assertEqual(termlogic.default_order("known"), ("count", True))

    def test_search_type_and_selection(self):
        es = self.es
        self.assertEqual([e.source for e in termlogic.arrange(es, "new", "alp", None, "count", True)], ["Alpha"])
        es[0].type = "place"
        self.assertEqual([e.source for e in termlogic.arrange(es, "new", "", "place", "count", True)], ["Beta"])
        ids = {id(es[1])}
        self.assertEqual([e.source for e in termlogic.arrange(es, "new", "", None, "count", True, ids)], ["Alpha"])

    def test_regex_and_marks(self):
        rx = termlogic.term_regex(E("Lake Sister", forms=["Lady of the Lake"]))
        self.assertTrue(rx.search("the Lake Sisters came"))
        self.assertTrue(rx.search("lady of the lake’s hand"))
        self.assertFalse(rx.search("Lake Sisterhood"))
        self.assertEqual(model.gender_marks("ru:Russian")["female"], "ж")
        self.assertEqual(model.gender_marks("pl")["female"], "ż")
        self.assertEqual(model.gender_marks("de")["female"], "female")
        self.assertEqual(model.gender_marks("de")["unknown"], "?")
        self.assertEqual(model.target_label("uk:Ukrainian"), "Ukrainian")
        self.assertEqual(model.target_label("ru:Russian"), "Russian")


if __name__ == "__main__":
    unittest.main()

