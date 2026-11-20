"""Check findings in the problem list: the ignore list, what a finding still describes, the check task, and a retry
that waits in the queue without touching the logs until it really starts."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from novelcore import checks
from novelgui import findingrules as fr
from novelgui import jobqueue, model
from tests.test_core_checks import BOOK, Synth, long_src


class Ctx:
    cancelled = False

    def __init__(self):
        self.items = []

    def emit(self, item):
        self.items.append(item)


def bad(n=0):
    return "Он сказал: the quick brown fox jumps и ушёл домой надолго."


class Rules(unittest.TestCase):
    def test_labels_and_details(self):
        self.assertEqual(fr.label("ratio"), "length")
        self.assertEqual(fr.label("term"), "term")
        self.assertIn("0.4", fr.detail_text("ratio", {"ratio": 0.4, "median": 1.1}))
        self.assertIn("Zorg", fr.detail_text("term", {"term": "Zorg", "expected": "Зорг", "missing": 2}))
        self.assertIn("order", fr.detail_text("markup", {"why": "order", "src": 2, "tr": 2}))
        for kind in checks.KINDS:
            self.assertTrue(fr.label(kind))
            self.assertTrue(fr.KIND_TIPS[kind])

    def test_still_true_needs_the_same_translation(self):
        rec = {"status": "ok", "text": "перевод", "flags": []}
        key = fr.text_key("перевод")
        self.assertTrue(fr.still_true(rec, key))
        self.assertFalse(fr.still_true(dict(rec, text="другой"), key))
        self.assertFalse(fr.still_true(dict(rec, flags=["manual"]), key))
        self.assertFalse(fr.still_true(dict(rec, flags=["kept"]), key))
        self.assertFalse(fr.still_true(dict(rec, status="retry"), key))
        self.assertFalse(fr.still_true(None, key))

    def test_ignore_list_round_trip_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(fr.load_ignored(d, "Book"), set())
            self.assertEqual(fr.add_ignored(d, "Book", [(1, 2, "sha", "term", "k1")]), 1)
            self.assertEqual(fr.add_ignored(d, "Book", [(1, 2, "sha", "term", "k1"), (3, 4, "s2", "ratio", "k2")]), 1)
            got = fr.load_ignored(d, "Book")
            self.assertEqual(got, {(1, 2, "sha", "term", "k1"), (3, 4, "s2", "ratio", "k2")})
            self.assertEqual(fr.ignore_path(d, "Book").name, "ignore_Book.json")
            fr.ignore_path(d, "Book").write_text("not json", encoding="utf-8")
            self.assertEqual(fr.load_ignored(d, "Book"), set())

    def test_the_name_matches_the_files_the_library_removes_with_a_volume(self):
        from novelgui import libraryrules
        with tempfile.TemporaryDirectory() as d:
            p = fr.ignore_path(d, "My Volume 1")
            p.parent.mkdir(parents=True)
            p.write_text("{}", encoding="utf-8")
            items = libraryrules.volume_items(d, "My Volume 1", lambda t, n, f: t)
            self.assertIn(".state/" + p.name, items)


class Rows(Synth):
    def setUp(self):
        super().setUp()
        self.make([[long_src("1"), long_src("2"), long_src("3")]])
        self.put(0, 0, bad())
        self.put(0, 1, "Это нормальный перевод второго длинного предложения в этой главе.")
        self.put(0, 2, "", status="failed", reason="empty")

    def rows(self):
        return model.problems_task(Ctx(), str(self.series.path), BOOK, [0])

    def check(self):
        return model.check_task(Ctx(), str(self.series.path), BOOK, [0])

    def test_without_a_check_only_failed_blocks_are_listed(self):
        rows = self.rows()
        self.assertEqual([(p.block, p.kind) for p in rows], [(2, "failed")])

    def test_check_lists_the_finding_with_its_kind_and_text(self):
        res = self.check()
        self.assertEqual((res["findings"], res["chapters"], res["cancelled"]), (1, 1, False))
        rows = self.rows()
        self.assertEqual([(p.block, p.kind, p.reason) for p in rows], [(0, "leftover", "leftover"), (2, "failed", "empty")])
        f = rows[0]
        self.assertTrue(f.is_finding and not rows[1].is_finding)
        self.assertEqual(f.text, bad())
        self.assertIn("quick brown", f.detail)
        self.assertEqual(f.mark(), (0, 0, self.blocks[0][0].sha, fr.text_key(bad())))

    def test_ignore_hides_it_until_the_translation_changes(self):
        self.check()
        f = self.rows()[0]
        self.assertEqual(model.ignore_task(Ctx(), str(self.series.path), BOOK, [f]), 1)
        self.assertEqual([p.kind for p in self.rows()], ["failed"])
        self.assertTrue(fr.ignore_path(self.series.path, BOOK).exists())
        self.put(0, 0, "Он сказал: the lazy brown dog sleeps и ушёл домой надолго.")
        self.check()
        self.assertEqual([p.kind for p in self.rows()], ["leftover", "failed"])

    def test_a_typed_or_kept_block_leaves_the_list(self):
        self.check()
        f = self.rows()[0]
        model.resolve_problems_task(Ctx(), str(self.series.path), BOOK, [f], "manual", "Исправленный перевод.")
        self.assertEqual([p.kind for p in self.rows()], ["failed"])

    def test_a_second_check_keeps_the_findings_of_other_chapters(self):
        self.make([[long_src("1")], [long_src("2")]])
        self.put(0, 0, bad())
        self.put(1, 0, bad())
        path = str(self.series.path)
        model.check_task(Ctx(), path, BOOK, [0])
        model.check_task(Ctx(), path, BOOK, [1])
        rows = model.problems_task(Ctx(), path, BOOK, [])
        self.assertEqual([(p.chapter, p.kind) for p in rows], [(0, "leftover"), (1, "leftover")])

    def test_fresh_marks_drop_blocks_that_changed_after_the_check(self):
        self.check()
        f = self.rows()[0]
        series = type(self.series).open(self.series.path)
        self.assertEqual(model.fresh_marks(series, BOOK, [f.mark()]), [(0, 0, f.sha)])
        self.put(0, 0, "Исправлено вручную.", flags=["manual"])
        series = type(self.series).open(self.series.path)
        self.assertEqual(model.fresh_marks(series, BOOK, [f.mark()]), [])

    def test_progress_is_reported(self):
        ctx = Ctx()
        model.check_task(ctx, str(self.series.path), BOOK, [0])
        self.assertEqual(ctx.items, [("check", 1, 1)])


class RetryMarks(unittest.TestCase):
    def test_item_keeps_the_marks_through_the_saved_queue(self):
        marks = ((0, 1, "abc", "k1"), (1, 0, "def", "k2"))
        it = jobqueue.Item("p", "b", ((0, 1),), retry=marks)
        again = jobqueue.item_from(json.loads(json.dumps(it.to_dict())))
        self.assertEqual(again, it)
        self.assertEqual(again.retry, marks)
        old = jobqueue.item_from({"series": "p", "book": "b", "spans": [[0, 1]]})
        self.assertEqual(old.retry, ())
        bad = jobqueue.item_from({"series": "p", "book": "b", "spans": [[0, 1]], "retry": [[1, 2], "x", [0, 1, 2, 3]]})
        self.assertEqual(bad.retry, ())


if __name__ == "__main__":
    unittest.main()
