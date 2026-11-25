"""The pure side of Books and Add book (no Qt): the protected-book check on generated EPUBs, series guessing, the rows and labels
of the Add panel, series / book rows, the capsule texts, Undo of a delete and a remove, moving a book, the add task."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelgui import chapterlogic as cl, libraryops as ops, protected  # noqa: E402
from novelgui.ctl import addplan, bookrows  # noqa: E402
from novelgui.facade import books as fb  # noqa: E402
from novelgui.lanes import PlainCtx  # noqa: E402
from tests import epubs, libfixture  # noqa: E402


class Tmp(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="novelbooks-"))
        self.lib = self.root / "lib"
        self.lib.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def build(self, *specs):
        return libfixture.build(self.lib, list(specs))

    def infos(self):
        return fb.list_series_task(None, self.lib)


class ProtectedBooks(Tmp):
    def test_plain_epub_is_readable(self):
        p = epubs.write_epub(self.root / "a.epub", ["<p>x</p>"])
        self.assertEqual(protected.encrypted_non_fonts(p), [])

    def test_fonts_only_are_accepted(self):
        p = epubs.write_with_encryption(self.root / "f.epub", [(epubs.IDPF_FONT, "OEBPS/a.otf"), (epubs.ADOBE_FONT, "OEBPS/b.ttf")])
        self.assertFalse(protected.is_protected(p))

    def test_a_font_encrypted_with_another_algorithm_is_still_a_font(self):
        p = epubs.write_with_encryption(self.root / "f2.epub", [(epubs.AES, "OEBPS/fonts/a%20b.woff")])
        self.assertFalse(protected.is_protected(p))

    def test_text_encrypted_is_refused(self):
        p = epubs.write_with_encryption(self.root / "d.epub", [(epubs.AES, "OEBPS/ch0.xhtml")])
        self.assertEqual(protected.encrypted_non_fonts(p), ["OEBPS/ch0.xhtml"])

    def test_fonts_and_text_together_are_refused(self):
        p = epubs.write_with_encryption(self.root / "m.epub", [(epubs.IDPF_FONT, "a.otf"), (epubs.AES, "OEBPS/ch0.xhtml")])
        self.assertTrue(protected.is_protected(p))

    def test_an_unreadable_encryption_file_counts_as_protection(self):
        import zipfile
        p = epubs.write_epub(self.root / "x.epub", ["<p>x</p>"], {"META-INF/encryption.xml": "<broken"})
        self.assertTrue(protected.is_protected(p))
        self.assertTrue(zipfile.is_zipfile(p))

    def test_check_file_states(self):
        good = epubs.write_epub(self.root / "g.epub", ["<h1>One</h1><p>x</p>"])
        locked = epubs.write_with_encryption(self.root / "l.epub", [(epubs.AES, "OEBPS/ch0.xhtml")])
        junk = self.root / "j.epub"
        junk.write_bytes(b"nope")
        self.assertEqual(addplan.check_file(good)[0], "ok")
        self.assertEqual(addplan.check_file(locked), ("protected", "protected"))
        state, note = addplan.check_file(junk)
        self.assertEqual(state, "unreadable")
        self.assertIn("not an EPUB", note)
        self.assertEqual(addplan.check_file(self.root / "none.epub")[0], "unreadable")


class Guessing(unittest.TestCase):
    NAMES = ["Knights", "Night Watch", "Gamma"]

    def test_names(self):
        g = addplan.guess_series
        self.assertEqual(g("Night Watch - Book 2", self.NAMES), ("Night Watch", True))
        self.assertEqual(g("Knights of the Lake - Book 2", self.NAMES), ("Knights", True))
        self.assertEqual(g("The Iron Crown - Book 1", self.NAMES), ("The Iron Crown", False))
        self.assertEqual(g("night_watch_3", self.NAMES), ("Night Watch", True))
        self.assertEqual(g("Gamma", self.NAMES), ("Gamma", True))
        self.assertEqual(g("Night Market", self.NAMES), ("Night Market", False))
        self.assertEqual(g("Vol. 3", []), ("Vol. 3", False))

    def test_entries_put_a_new_name_first(self):
        class I:
            def __init__(self, n, b):
                self.name, self.books, self.broken = n, b, ""
        infos = [I("Knights", ("a", "b")), I("Gamma", ("c",))]
        e = addplan.series_entries(infos, "Iron")
        self.assertEqual(e[0], {"text": "+ New series Iron", "id": "Iron"})
        self.assertEqual(len(e), 1)
        e = addplan.series_entries(infos, "")
        self.assertEqual([x["text"] for x in e], ["Knights", "Gamma"])
        self.assertEqual(e[0]["note"], "2 books")
        self.assertEqual(addplan.series_entries(infos, "knights")[0]["text"], "Knights")


class AddRows(Tmp):
    def test_labels_by_natural_order_of_file_names(self):
        self.build({"name": "Knights", "books": [{"stem": "Knights 1", "chapters": 3}, {"stem": "Knights 10", "chapters": 3}]})
        infos = self.infos()
        files = [{"path": str(self.root / "Knights 2.epub"), "state": "ok"},
                 {"path": str(self.root / "Iron - Book 2.epub"), "state": "ok"},
                 {"path": str(self.root / "Iron - Book 1.epub"), "state": "ok"},
                 {"path": str(self.root / "Locked.epub"), "state": "protected", "note": "protected"}]
        rows = addplan.make_rows(files, infos)
        self.assertEqual([r.series for r in rows[:3]], ["Knights", "Iron", "Iron"])
        self.assertEqual([r.new for r in rows[:3]], [False, True, True])
        self.assertEqual(rows[0].label, "Book 2")                       # Knights 1, Knights 2, Knights 10
        self.assertEqual([rows[1].label, rows[2].label], ["Book 2", "Book 1"])
        self.assertEqual(rows[3].label, "")
        self.assertEqual(addplan.action_text(rows), "Add 3 books")
        self.assertEqual(addplan.title_for(1), "Add book")
        self.assertEqual(addplan.title_for(4), "Add 4 books")

    def test_changing_the_series_relabels(self):
        self.build({"name": "Knights", "books": [{"stem": "A", "chapters": 3}]})
        rows = addplan.make_rows([{"path": str(self.root / "B.epub"), "state": "ok"}], self.infos())
        from dataclasses import replace
        again = addplan.assign_labels([replace(rows[0], series="Knights")], self.infos())
        self.assertEqual((again[0].new, again[0].label), (False, "Book 2"))
        again = addplan.assign_labels([replace(rows[0], series="Brand new")], self.infos())
        self.assertEqual((again[0].new, again[0].label), (True, "Book 1"))


class Rows(Tmp):
    def test_series_rows_and_books(self):
        self.build({"name": "Knights", "labels": {"Book 3": "Finale"},
                    "books": [{"stem": "Book %d" % i, "chapters": 3} for i in (1, 2, 3)]},
                   {"name": "Gamma", "books": [{"stem": "G", "chapters": 3}]},
                   {"name": "Many", "books": [{"stem": "M1", "chapters": 3}, {"stem": "M2", "chapters": 3}]},
                   {"name": "Bad", "broken": "{"})
        infos = self.infos()
        k = next(i for i in infos if i.name == "Knights")
        rows = bookrows.series_rows(infos, k.path, "Book 2")
        kinds = [(r[0], r[2], r[5]) for r in rows]
        self.assertIn(("series", "Knights", "parent"), kinds)
        self.assertIn(("book", "Book 2", "selected"), kinds)
        self.assertIn(("book", "Finale", ""), kinds)                    # the user's label stays
        many = next(r for r in rows if r[2] == "Many")
        self.assertEqual(many[4], 2)                                    # a closed series with 2+ books shows the count
        bad = next(r for r in rows if r[2] == "Bad")
        self.assertEqual((bad[5], bad[3]), ("broken", ""))
        self.assertEqual(next(r for r in bookrows.series_rows(infos, bad[1], "") if r[2] == "Bad")[5], "brokenSelected")
        self.assertEqual(bookrows.series_rows(infos, k.path, "Book 1", ("series", k.path))[0][6] or
                         any(r[6] for r in bookrows.series_rows(infos, k.path, "Book 1", ("series", k.path))), True)
        self.assertEqual(bookrows.book_label(k, "Book 1"), "Book 1")
        self.assertEqual(bookrows.pick_book(k, "nope"), "Book 1")

    def test_capsule_texts(self):
        infos = [cl.ChapterInfo(i, "h%d" % i, "Chapter %d - X" % (i + 2650), False, 4, (0, 0), 4 if i < 5 else 0, 0)
                 for i in range(20)]
        self.assertEqual(bookrows.range_text(infos, [3, 4, 5, 6]), "2653-2656")
        self.assertEqual(bookrows.range_text(infos, [5, 9, 10, 11, 12]), "2655, 2659-2662")
        self.assertEqual(bookrows.count_text(1), "1 chapter")
        self.assertEqual(bookrows.count_text(54), "54 chapters")
        self.assertEqual(bookrows.next_step(infos, [0, 1, 2]), ("export", "Export ›"))
        self.assertEqual(bookrows.next_step(infos, [0, 7]), ("translate", "Translate ›"))
        self.assertEqual(bookrows.next_step(infos, [0, 7], 12), ("review", "Review 12 terms ›"))
        self.assertEqual(bookrows.next_step(infos, [], 12), ("translate", "Translate ›"))
        self.assertTrue(bookrows.titles_numbered(infos))
        self.assertEqual(bookrows.first_open(infos), 5)

    def test_no_column_rule(self):
        named = [cl.ChapterInfo(i, "h", "Title %c" % (65 + i), False, 1) for i in range(5)]
        self.assertFalse(bookrows.titles_numbered(named))
        shuffled = [cl.ChapterInfo(i, "h", "Chapter %d" % n, False, 1) for i, n in enumerate([5, 3, 9, 1])]
        self.assertFalse(bookrows.titles_numbered(shuffled))

    def test_chapter_row_strings(self):
        done = cl.ChapterInfo(3, "h", "Chapter 4", False, 10, (0, 0), 10, 0)
        part = cl.ChapterInfo(4, "h", "Chapter 5", False, 10, (0, 0), 4, 0)
        self.assertEqual(bookrows.chapter_row(done), ("4", "Chapter 4", "translated", "translated", 1.0, 0.0))
        self.assertEqual(bookrows.chapter_row(part)[3:5], ("4 / 10", 0.4))
        toc = cl.ChapterInfo(0, "h", None, True, 0)
        self.assertEqual(bookrows.chapter_row(toc)[1:3], ("Contents", "toc"))


class DeleteRemoveUndo(Tmp):
    def setUp(self):
        super().setUp()
        self.build({"name": "Knights", "labels": {"Book 2": "Second"},
                    "books": [{"stem": "Book 1", "chapters": 5, "translated": 2}, {"stem": "Book 2", "chapters": 4}]},
                   {"name": "Gamma", "books": [{"stem": "G", "chapters": 3}]})

    def test_delete_series_goes_to_the_trash_and_comes_back(self):
        sp = self.lib / "Knights"
        dest = ops.delete_series(self.lib, sp)
        self.assertFalse(sp.exists())
        self.assertTrue((dest / "books" / "Book 1.epub").exists())
        self.assertEqual([i.name for i in self.infos()], ["Gamma"])          # the series list knows nothing of the trash
        now = ops.restore_series(self.lib, sp, dest)
        self.assertEqual(now, sp)
        self.assertEqual(sorted(i.name for i in self.infos()), ["Gamma", "Knights"])
        self.assertTrue((sp / "chapters").exists())

    def test_undo_series_when_the_name_is_taken_meanwhile(self):
        sp = self.lib / "Knights"
        dest = ops.delete_series(self.lib, sp)
        self.build({"name": "Knights", "books": [{"stem": "New", "chapters": 3}]})
        now = ops.restore_series(self.lib, sp, dest)
        self.assertEqual(now.name, "Knights (2)")

    def test_remove_book_and_undo_bring_everything_back(self):
        sp = self.lib / "Knights"
        before = sorted(str(p.relative_to(sp)) for p in sp.rglob("*") if p.is_file() and ".state" not in p.parts)
        dest = ops.remove_volume(self.lib, sp, "Book 1")
        self.assertFalse((sp / "books" / "Book 1.epub").exists())
        self.assertFalse((sp / "chapters" / "Book 1").exists())
        stems = ops.restore_volume(sp, dest)
        self.assertEqual(stems, ["Book 1"])
        after = sorted(str(p.relative_to(sp)) for p in sp.rglob("*") if p.is_file() and ".state" not in p.parts)
        self.assertEqual(after, before)
        self.assertFalse(dest.exists())

    def test_undo_a_removed_book_refuses_when_a_book_of_that_name_is_back(self):
        sp = self.lib / "Knights"
        dest = ops.remove_volume(self.lib, sp, "Book 2")
        shutil.copyfile(self.lib / "Gamma" / "books" / "G.epub", sp / "books" / "Book 2.epub")
        with self.assertRaises(ops.OpError):
            ops.restore_volume(sp, dest)
        self.assertTrue(dest.exists())

    def test_move_a_book_with_nothing_translated(self):
        new = ops.move_volume(self.lib / "Knights", "Book 2", self.lib / "Gamma")
        self.assertEqual(new, "Book 2")
        self.assertTrue((self.lib / "Gamma" / "books" / "Book 2.epub").exists())
        self.assertFalse((self.lib / "Knights" / "books" / "Book 2.epub").exists())
        labels = dict(next(i for i in self.infos() if i.name == "Knights").labels)
        self.assertNotIn("Book 2", labels)

    def test_move_refuses_a_translated_book(self):
        self.assertTrue(ops.has_translation(self.lib / "Knights", "Book 1"))
        with self.assertRaises(ops.OpError):
            ops.move_volume(self.lib / "Knights", "Book 1", self.lib / "Gamma")
        self.assertTrue((self.lib / "Knights" / "books" / "Book 1.epub").exists())

    def test_move_to_a_series_with_the_same_name_numbers_it(self):
        shutil.copyfile(self.lib / "Gamma" / "books" / "G.epub", self.lib / "Gamma" / "books" / "Book 2.epub")
        new = ops.move_volume(self.lib / "Knights", "Book 2", self.lib / "Gamma")
        self.assertEqual(new, "Book 2 (2)")


class AddTask(Tmp):
    def test_add_creates_and_joins_and_skips_nothing_half_made(self):
        self.build({"name": "Knights", "books": [{"stem": "Knights 1", "chapters": 3}]})
        a = epubs.write_epub(self.root / "Iron 1.epub", ["<h1>One</h1><p>x</p>"])
        b = epubs.write_epub(self.root / "Iron 2.epub", ["<h1>Two</h1><p>y</p>"])
        c = epubs.write_epub(self.root / "Knights 2.epub", ["<h1>K2</h1><p>z</p>"])
        items = [{"path": str(a), "series": "Iron", "new": True}, {"path": str(b), "series": "Iron", "new": True},
                 {"path": str(c), "series": "Knights", "new": False}]
        res = addplan.add_task(PlainCtx(), self.lib, items)
        self.assertEqual([r["ok"] for r in res], [True, True, True])
        self.assertEqual([r["kind"] for r in res], ["created", "added", "added"])
        infos = {i.name: i for i in self.infos()}
        self.assertEqual(infos["Iron"].books, ("Iron 1", "Iron 2"))
        self.assertEqual(infos["Knights"].books, ("Knights 1", "Knights 2"))
        self.assertTrue(a.exists(), "the original is never touched")
        self.assertEqual(list(self.lib.rglob("*.part")), [])

    def test_a_failure_of_one_file_does_not_stop_the_others(self):
        good = epubs.write_epub(self.root / "Good.epub", ["<h1>One</h1><p>x</p>"])
        bad = self.root / "Bad.epub"
        bad.write_bytes(b"junk")
        res = addplan.add_task(PlainCtx(), self.lib, [{"path": str(bad), "series": "Bad", "new": True},
                                                       {"path": str(good), "series": "Good", "new": True}])
        self.assertFalse(res[0]["ok"])
        self.assertIn("Nothing was created", res[0]["error"])
        self.assertTrue(res[1]["ok"])
        self.assertEqual([i.name for i in self.infos()], ["Good"])

    def test_the_hash_check_finds_a_copy_before_the_panel(self):
        self.build({"name": "Knights", "books": [{"stem": "Book 1", "chapters": 3}]})
        shutil.copyfile(self.lib / "Knights" / "books" / "Book 1.epub", self.root / "Same.epub")
        new = epubs.write_epub(self.root / "New.epub", ["<h1>N</h1><p>n</p>"])
        out = addplan.prepare_task(PlainCtx(), self.lib, [self.root / "Same.epub", new])
        self.assertEqual(out[0]["dup"], (str(self.lib / "Knights"), "Book 1"))
        self.assertIsNone(out[1]["dup"])
        self.assertEqual([o["state"] for o in out], ["ok", "ok"])

    def test_summary(self):
        ok = {"ok": True, "kind": "added", "volume": "Book 2", "path": "x"}
        self.assertEqual(addplan.summary([ok], []), "Added Book 2")
        self.assertEqual(addplan.summary([ok, ok], []), "Added 2 books")
        self.assertEqual(addplan.summary([ok], ["Locked.epub"]),
                         "Added Book 2 · Protected files were not added: Locked.epub. Use a copy without protection.")
        self.assertEqual(addplan.summary([], ["L.epub"]),
                         "Protected files were not added: L.epub. Use a copy without protection.")


if __name__ == "__main__":
    unittest.main()
