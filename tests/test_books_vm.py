"""The Books view-models with a real library behind them (QCoreApplication, real lanes, the real helper process): the list models
(QAbstractItemModelTester, QSignalSpy), the 2783-chapter demo book (first rows <= 1.2 s, the whole list in <= 60 batches),
selection and typing, delete / remove with Undo, rename and `name taken`, move, Add (copy to `.part`, rename last), a dropped
file, protected books refused. Skipped without PySide6."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

KEEP: list = []         # the parts of finished tests stay alive: a lane thread may still post to a pump

DEMO = Path(r"C:\_src\temp_api\demo\library")


def pump(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            QCoreApplication.processEvents()
            return True
        time.sleep(0.005)
    return False


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class Base(unittest.TestCase):
    specs = [{"name": "Knights", "books": [{"stem": "Book 1", "chapters": 30, "start": 1, "translated": 5},
                                           {"stem": "Book 2", "chapters": 12, "start": 31}]},
             {"name": "Gamma", "books": [{"stem": "Gamma", "chapters": 8}]}]

    @classmethod
    def setUpClass(cls):
        cls.qapp = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="novelbvm-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.lib = self.root / "Novel library"
        self.lib.mkdir()
        self.build()
        self.make()

    def build(self):
        from tests import libfixture
        libfixture.build(self.lib, self.specs)

    def make(self, select=("Knights", "Book 1")):
        self.parts_for(select)
        self.settle()

    def parts_for(self, select):
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        os.environ["NOVELGUI_DATA"] = str(data)
        os.environ.pop("NOVELGUI_NOTIFY", None)
        os.environ.pop("NOVELGUI_TRAY", None)
        win = {"books_last": {"series": select[0], "book": select[1]}} if select else {}
        (data / "settings.json").write_text(json.dumps({"library": str(self.lib), "win": win}), encoding="utf-8")
        from novelgui.runtime import notify, tray as trays
        from novelgui.runtime.assemble import Parts
        parts = Parts(settings_dir=data, local=data / "local", tray=trays.RecordingTray(data, available=False))
        parts.notifier = notify.RecordingNotifier(data)
        parts.app.notifier = parts.notifier
        self.parts, self.books, self.app, self.add = parts, parts.books_vm, parts.app, parts.add_vm
        KEEP.append(parts)
        self.addCleanup(parts.close)

    def settle(self, view="chapters"):
        self.assertTrue(pump(lambda: self.books.view == view and not self.books.session.scanning and self.books._loaded
                             and not self.books._loading_library),
                        "the books screen did not settle (%s)" % self.books.view)

    def names(self):
        return [r[2] for r in self.books.series_model.rows]

    def idle(self):
        self.assertTrue(pump(lambda: self.parts.lanes.idle() and not self.books._busy_ops))
        QCoreApplication.processEvents()


class Models(Base):
    def test_models_pass_the_model_tester(self):
        QAbstractItemModelTester(self.books.chapter_model, QAbstractItemModelTester.FailureReportingMode.Fatal)
        QAbstractItemModelTester(self.books.series_model, QAbstractItemModelTester.FailureReportingMode.Fatal)
        QAbstractItemModelTester(self.add.model, QAbstractItemModelTester.FailureReportingMode.Fatal)
        self.books.selectBook(str(self.lib / "Knights"), "Book 2")
        self.settle()
        self.assertEqual(self.books.chapterCount, 13)           # 12 chapters + the contents page

    def test_chapter_model_has_at_most_eight_roles(self):
        self.assertLessEqual(len(self.books.chapter_model.roleNames()), 8)

    def test_first_start_state(self):
        self.assertEqual(self.books.currentSeries, "Knights")
        self.assertEqual(self.books.currentBook, "Book 1")
        self.assertEqual(self.names(), ["Gamma", "Knights", "Book 1", "Book 2"])


class Selection(Base):
    def test_click_toggles_and_shift_takes_a_range(self):
        b = self.books
        b.rowPressed(3, False, False)
        b.rowPressed(5, False, False)
        self.assertEqual(b.selectedCount, 2)
        b.rowPressed(8, False, True)                            # shift: from the anchor (5) to 8
        self.assertEqual(b.chapter_model.selected, {5, 6, 7, 8})
        b.rowPressed(6, False, False)
        self.assertEqual(b.chapter_model.selected, {5, 7, 8})
        self.assertEqual(b.headState, "some")
        b.headBox()
        self.assertEqual(b.selectedCount, 0)
        b.headBox()
        self.assertEqual(b.headState, "all")
        self.assertNotIn(0, b.chapter_model.selected, "the contents page is never selected")
        self.assertEqual(b.selectedCount, 30)

    def test_typing_a_range(self):
        b = self.books
        self.assertTrue(b.commitRange("4-8"))
        self.assertEqual((b.capsuleCount, b.capsuleRange, b.nextText), ("5 chapters", "4-8", "Translate ›"))
        self.assertTrue(b.commitRange("5, 9-12"))
        self.assertEqual((b.capsuleCount, b.capsuleRange), ("5 chapters", "5, 9-12"))
        self.assertTrue(b.commitRange("12-9"))
        self.assertEqual(b.capsuleRange, "9-12")
        spy = QSignalSpy(b.rangeRejected)
        self.assertFalse(b.commitRange("abc"))
        self.assertEqual(spy.count(), 1)
        self.assertEqual(b.capsuleRange, "9-12", "a wrong value keeps the selection")
        self.assertFalse(b.commitRange("500-600"))
        b.beginTyping("1")
        self.assertTrue(b.typing)
        self.assertEqual(b.capsuleCount, "1 chapter")
        b.typingEdited("1-3")
        self.assertEqual(b.capsuleCount, "3 chapters")
        b.cancelTyping()
        self.assertFalse(b.typing)
        self.assertEqual(b.capsuleRange, "9-12", "Esc restores")

    def test_the_selection_is_remembered_per_book(self):
        b = self.books
        b.commitRange("3-6")
        b.selectBook(str(self.lib / "Knights"), "Book 2")
        self.settle()
        self.assertEqual(b.selectedCount, 0)
        b.commitRange("32-33")
        b.selectBook(str(self.lib / "Knights"), "Book 1")
        self.settle()
        self.assertEqual(b.capsuleRange, "3-6")

    def test_next_step_follows_the_selection(self):
        b = self.books
        b.commitRange("1-3")                                    # the first five real chapters are translated
        self.assertEqual(b.nextKind, "export")
        b.commitRange("4-8")
        self.assertEqual(b.nextKind, "translate")
        b.set_blocking(12)
        self.assertEqual((b.nextKind, b.nextText), ("review", "Review 12 terms ›"))
        b.goNext()
        self.assertEqual(self.app.screen, "terms")


class Operations(Base):
    def test_delete_series_with_undo(self):
        b = self.books
        sp = str(self.lib / "Gamma")
        b.deleteSeries(sp)
        self.idle()
        self.settle()
        self.assertNotIn("Gamma", self.names())
        self.assertEqual(b.notice["fact"][0]["text"], "Deleted ")
        self.assertEqual(b.notice["verbs"][0]["text"], "Undo")
        self.assertEqual(len(list((self.lib / ".deleted").rglob("Gamma.epub"))), 1)
        b.undo()
        self.idle()
        self.settle()
        self.assertIn("Gamma", self.names())
        self.assertEqual(b.notice, {})
        self.assertTrue((self.lib / "Gamma" / "books" / "Gamma.epub").exists())

    def test_deleting_the_selected_series_selects_a_neighbour(self):
        b = self.books
        b.deleteSeries(str(self.lib / "Knights"))
        self.idle()
        self.settle()
        self.assertEqual(b.currentSeries, "Gamma")
        self.assertEqual(b.view, "chapters")

    def test_remove_book_with_undo(self):
        b = self.books
        b.removeBook(str(self.lib / "Knights"), "Book 2")
        self.idle()
        self.assertTrue(pump(lambda: self.books.notice.get("fact") is not None))
        self.settle()
        self.assertEqual("".join(p["text"] for p in b.notice["fact"]), "Removed Knights · Book 2")
        self.assertFalse((self.lib / "Knights" / "books" / "Book 2.epub").exists())
        b.undo()
        self.idle()
        self.settle()
        self.assertTrue((self.lib / "Knights" / "books" / "Book 2.epub").exists())
        self.assertEqual(self.names(), ["Gamma", "Knights", "Book 1", "Book 2"])

    def test_the_next_action_clears_the_undo_message(self):
        b = self.books
        b.deleteSeries(str(self.lib / "Gamma"))
        self.idle()
        self.settle()
        self.assertTrue(b.notice)
        b.pickRow(0)
        self.assertEqual(b.notice, {})

    def test_no_delete_while_the_series_runs(self):
        self.app.setRun({"running": True, "series": "Gamma", "book": "Gamma"})
        self.books.deleteSeries(str(self.lib / "Gamma"))
        self.books.removeBook(str(self.lib / "Gamma"), "Gamma")
        self.idle()
        self.assertTrue((self.lib / "Gamma" / "books" / "Gamma.epub").exists())
        items = self.books.menuFor(0)
        self.assertEqual([i["kind"] for i in items if i.get("id", "").startswith("delete")], ["off"])
        self.app.setRun({"running": True, "series": "Knights", "book": "Book 1"})
        self.books.deleteSeries(str(self.lib / "Gamma"))
        self.idle()
        self.assertFalse((self.lib / "Gamma").exists(), "another series is not blocked (4.6)")

    def test_rename_series_and_name_taken(self):
        b = self.books
        b.startRename("series", str(self.lib / "Gamma"))
        self.assertEqual((b.editKind, b.editValue), ("series", "Gamma"))
        spy = QSignalSpy(b.renameRejected)
        self.assertFalse(b.commitRename("knights"))
        self.assertEqual(spy.count(), 1)
        self.assertEqual(b.editKind, "series", "the field stays open")
        self.assertTrue(b.commitRename("Delta"))
        self.idle()
        self.settle()
        self.assertIn("Delta", self.names())
        self.assertTrue((self.lib / "Gamma").exists(), "the folder keeps its name")

    def test_rename_a_book_and_the_label_order(self):
        b = self.books
        b.startRename("book", "Book 2")
        self.assertEqual(b.editValue, "Book 2")
        self.assertTrue(b.commitRename("Finale"))
        self.idle()
        self.settle()
        self.assertEqual(self.names(), ["Gamma", "Knights", "Book 1", "Finale"])
        b.startRename("book", "Book 1")
        self.assertFalse(b.commitRename("finale"))

    def test_menus_name_their_object(self):
        b = self.books
        rows = b.series_model.rows
        book_row = next(i for i, r in enumerate(rows) if r[0] == "book" and r[1] == "Book 2")
        texts = [i["text"] for i in b.menuFor(book_row)]
        self.assertEqual(texts, ["Rename Book 2", "Remove Book 2", "Move Book 2 to series…", "Update file…"])
        k = next(i for i, r in enumerate(rows) if r[1].endswith("Knights") and r[0] == "series")
        self.assertEqual([i["text"] for i in b.menuFor(k)], ["Rename series", "Open folder", "Delete series"])
        g = next(i for i, r in enumerate(rows) if r[1].endswith("Gamma"))
        texts = [i.get("text") for i in b.menuFor(g)]
        self.assertEqual(texts, ["Rename series", "Open folder", "Delete series", "", "Rename Book 1", "Remove Book 1",
                                 "Move Book 1 to series…", "Update file…"])

    def test_move_is_off_for_a_translated_book_and_moves_the_other(self):
        b = self.books
        rows = b.series_model.rows
        r1 = next(i for i, r in enumerate(rows) if r[0] == "book" and r[1] == "Book 1")
        r2 = next(i for i, r in enumerate(rows) if r[0] == "book" and r[1] == "Book 2")
        kind = lambda items: next(i for i in items if i["id"].startswith("move"))["kind"]
        self.assertEqual(kind(b.menuFor(r1)), "off")
        self.assertEqual(kind(b.menuFor(r2)), "")
        b.menuPicked(r2, "move:Book 2")
        self.assertTrue(b.moveOpen)
        self.assertEqual([t["text"] for t in b.moveTargets], ["Gamma"])
        b.moveBook(str(self.lib / "Gamma"))
        self.idle()
        self.settle()
        self.assertEqual("".join(p["text"] for p in b.notice["fact"]), "Moved Book 2 to Gamma")
        self.assertTrue((self.lib / "Gamma" / "books" / "Book 2.epub").exists())
        self.assertEqual(b.currentSeries, "Gamma")

    def test_open_books_are_closed_before_a_move(self):
        from novelgui.facade import books as fb
        b = self.books
        b.deleteSeries(str(self.lib / "Knights"))               # the scan holds Book 1 open; deleting must still work
        self.idle()
        self.assertFalse((self.lib / "Knights").exists())
        self.assertEqual(fb.open_handles().get("lane-data", []), [])


class AddBooks(Base):
    def files(self, *kinds):
        from tests import epubs
        out = []
        for name, kind in kinds:
            p = self.root / name
            if kind == "ok":
                epubs.write_epub(p, ["<h1>Chapter 1</h1><p>One.</p>", "<h1>Chapter 2</h1><p>Two.</p>"])
            elif kind == "protected":
                epubs.write_with_encryption(p, [(epubs.AES, "OEBPS/ch0.xhtml")])
            elif kind == "fonts":
                epubs.write_with_encryption(p, [(epubs.IDPF_FONT, "a.otf")])
            elif kind == "bad":
                p.write_bytes(b"junk")
            out.append(str(p))
        return out

    def open_panel(self, paths):
        self.add.open_files(paths)
        self.assertTrue(pump(lambda: self.add.isOpen or (not self.add.checking and self.parts.lanes.idle())))

    def test_panel_for_several_files_and_adding(self):
        paths = self.files(("Gamma - Book 2.epub", "ok"), ("Iron Crown 1.epub", "ok"), ("Iron Crown 2.epub", "ok"))
        self.open_panel(paths)
        self.assertTrue(self.add.isOpen)
        self.assertEqual(self.app.panel, "add")
        self.assertEqual((self.add.title, self.add.actionText), ("Add 3 books", "Add 3 books"))
        rows = self.add.model.rows
        self.assertEqual([(r.series, r.new, r.label) for r in rows],
                         [("Gamma", False, "Book 2"), ("Iron Crown", True, "Book 1"), ("Iron Crown", True, "Book 2")])
        self.add.leaveOut(0)
        self.assertEqual(self.add.title, "Add 2 books")
        self.add.setSeries(1, "Gamma")
        self.assertEqual([(r.series, r.label) for r in self.add.model.rows], [("Iron Crown", "Book 1"), ("Gamma", "Book 2")])
        self.add.accept()
        self.assertFalse(self.add.isOpen)
        self.assertTrue(self.books.adding)
        self.assertTrue(pump(lambda: not self.books.adding and self.parts.lanes.idle()))
        self.settle()
        self.assertEqual(list(self.lib.rglob("*.part")), [])
        self.assertTrue((self.lib / "Iron Crown" / "books" / "Iron Crown 1.epub").exists())
        self.assertTrue((self.lib / "Gamma" / "books" / "Iron Crown 2.epub").exists())
        self.assertEqual(self.app.panel, "")

    def test_one_file_uses_the_same_panel(self):
        self.open_panel(self.files(("Night Market.epub", "ok")))
        self.assertEqual(self.add.title, "Add book")
        self.assertEqual((self.add.model.rows[0].series, self.add.model.rows[0].new), ("Night Market", True))
        self.add.accept()
        self.assertTrue(pump(lambda: not self.books.adding and self.parts.lanes.idle()))
        self.settle()
        self.assertEqual(self.books.currentSeries, "Night Market")
        self.assertEqual("".join(p["text"] for p in self.books.notice["fact"]), "Added Night Market")

    def test_protected_is_left_out_and_named_afterwards(self):
        self.open_panel(self.files(("Good.epub", "ok"), ("Locked.epub", "protected"), ("Fonts.epub", "fonts")))
        states = [(r.name, r.state) for r in self.add.model.rows]
        self.assertEqual(states, [("Good.epub", "ok"), ("Locked.epub", "protected"), ("Fonts.epub", "ok")])
        self.assertEqual(self.add.actionText, "Add 2 books")
        self.add.accept()
        self.assertTrue(pump(lambda: not self.books.adding and self.parts.lanes.idle()))
        self.settle()
        text = "".join(p["text"] for p in self.books.notice["fact"])
        self.assertEqual(text, "Added 2 books · Protected files were not added: Locked.epub. Use a copy without protection.")
        self.assertFalse((self.lib / "Locked").exists())

    def test_a_single_unreadable_file_is_a_message_and_creates_nothing(self):
        self.open_panel(self.files(("Junk.epub", "bad")))
        self.assertFalse(self.add.isOpen)
        self.assertIn("Junk.epub cannot be added: it is not an EPUB file", self.app.message)
        self.assertIn("Nothing was created", self.app.message)
        self.assertNotIn("Junk", self.names())

    def test_a_copy_of_a_book_in_the_library_selects_it_and_opens_no_panel(self):
        dup = self.root / "again.epub"
        shutil.copyfile(self.lib / "Gamma" / "books" / "Gamma.epub", dup)
        self.open_panel([str(dup)])
        self.assertFalse(self.add.isOpen)
        self.assertTrue(pump(lambda: self.books.currentSeries == "Gamma" and self.books.view == "chapters"))
        text = "".join(p["text"] for p in self.books.notice["fact"])
        self.assertEqual(text, "Already in Gamma · Book 1")

    def test_a_drop_and_the_second_start_open_the_same_panel(self):
        paths = self.files(("Dropped.epub", "ok"), ("notes.txt", "bad"))
        urls = [QUrl.fromLocalFile(p) for p in paths]
        self.assertEqual(self.books.epubCount(urls), 1)
        self.books.dropped(urls)
        self.assertTrue(pump(lambda: self.add.isOpen))
        self.add.close()
        self.assertEqual(self.app.panel, "")
        spy = QSignalSpy(self.app.addBooksRequested)
        self.app.addBooksRequested.emit([paths[0]])
        self.assertEqual(spy.count(), 1)
        self.assertTrue(pump(lambda: self.add.isOpen))
        self.assertEqual(self.add.title, "Add book")


class BigBook(Base):
    """The 2783-chapter demo book `rssg18` (a fresh copy of the demo library; skipped when the demo data is not there)."""

    specs = []
    cold = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The app imports these before its window shows: a budget for the first rows must not pay for them, or
        # whichever big-book test runs first in the process fails.
        from novelgui.runtime import assemble, notify, tray  # noqa: F401

    def build(self):
        if not (DEMO / "rssg18").is_dir():
            self.skipTest("the demo library is not on this PC")
        shutil.copytree(DEMO / "rssg18", self.lib / "rssg18")
        if self.cold:
            for f in (self.lib / "rssg18" / ".state").glob("chapters-*.json"):
                f.unlink()

    def make(self, select=("rssg18", "RSSG")):
        t0 = time.monotonic()
        self.parts_for(select)
        model = self.books.chapter_model
        self.batches = []
        self.first = None
        model.dataChanged.connect(lambda *a: self.batches.append(1))
        model.modelReset.connect(lambda: self.batches.append(1))
        pump(lambda: model.rowCount() > 1000, 40)
        self.first = time.monotonic() - t0

    def finish(self):
        self.assertTrue(pump(lambda: not self.books.session.scanning, 240), "the scan did not finish")
        self.books.chapter_model.flush()
        self.assertGreater(self.books.chapter_model.rowCount(), 2700)
        self.assertLessEqual(len(self.batches), 60, "%d batches" % len(self.batches))

    def test_warm_cache_first_rows_and_the_list_in_at_most_60_batches(self):
        self.assertLess(self.first, 1.2, "first rows: %.2f s (library load included)" % self.first)
        self.finish()


class BigBookCold(BigBook):
    cold = True
    test_warm_cache_first_rows_and_the_list_in_at_most_60_batches = None

    def test_first_rows_within_1_2_s_and_the_list_in_at_most_60_batches(self):
        self.assertLess(self.first, 1.2, "first rows: %.2f s (helper start, titles, library load included)" % self.first)
        self.finish()
        self.assertNotEqual(self.books.chapter_model.kind_of(5), "")


if __name__ == "__main__":
    unittest.main()
