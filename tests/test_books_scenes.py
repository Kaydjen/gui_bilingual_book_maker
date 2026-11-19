"""The Books screen, the Add book panel and the Reader as scenarios (tests/qmlharness.py, offscreen + software): every state of the
accepted mock-up (full_v1 books/*), each at 100 % and 150 %, a few also at the narrow 820 x 600 size. Real libraries with real EPUBs
(tests/libfixture.py) behind the real view-models (tests/shellfactory.py). Asserts by objectName, one red per screen, at most one
ambient animation; shots go to NOVELGUI_SHOTS (default: the temp dir)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402

RUN = qh.have_qt()
VM = "tests.shellfactory:make"
SCALES = (1.0, 1.5)
NARROW = (820, 600)
WAIT = {"op": "wait", "ms": 1500}


def knights(books=1, chapters=110, start=2650, translated=47, **extra):
    stems = ["Book %d" % (i + 1) for i in range(books)]
    return dict({"name": "Knights", "books": [{"stem": s, "chapters": chapters if books == 1 else 40 + 5 * i,
                                              "start": start if books == 1 else 1 + 40 * i,
                                              "translated": translated if (books == 1 or i == 0) else 0}
                                             for i, s in enumerate(stems)]}, **extra)


def others():
    return [{"name": "Night Watch", "books": [{"stem": "Night Watch", "chapters": 25}]},
            {"name": "Gamma", "target": "uk:Ukrainian", "books": [{"stem": "Gamma", "chapters": 30}]},
            {"name": "The Long Road", "target": "pl:Polish", "books": [{"stem": "Long Road", "chapters": 20}]}]


def lib(*series, **kw):
    d = {"library": "ready", "series": list(series), "select": ["Knights", ""]}
    d.update(kw)
    return d


def sel(text):
    return {"op": "call", "obj": "booksVm", "fn": "commitRange", "args": [text]}


def do(fn, series, *rest):
    return {"op": "py", "name": "do", "args": [fn, series, *rest]}


def plain(html):
    """The text of a Message line (it is styled text)."""
    import re
    return re.sub(r"<[^>]+>", "", html).replace("&amp;", "&").replace("&lt;", "<")


def red(r, name):
    img = r.image()
    return qh.count_red(img, r.rect(name)), qh.count_red(img)


@unittest.skipUnless(RUN, "PySide6 is not available")
class Scenes(unittest.TestCase):
    def go(self, name, data, actions=None, scales=SCALES, size=(1040, 720), **kw):
        tag = name + ("_narrow" if size == NARROW else "")
        return [qh.scenario("ShellScene", data, scale=k, vm=VM, actions=(actions or []), tag=tag, size=size, **kw)
                for k in scales]

    def narrow(self, name, data, actions=None):
        return self.go(name, data, actions, scales=(1.0,), size=NARROW)

    def one_red(self, r, inside=None):
        n, total = red(r, inside) if inside else (0, qh.count_red(r.image()))
        self.assertLessEqual(total, 600 if not inside else total)
        if inside:
            self.assertGreater(n, 20)
            self.assertEqual(n, total, "red only inside %s" % inside)
        else:
            self.assertEqual(total, 0, "no red on this screen")

    # ------------------------------------------------------------ the library and its series
    def test_empty_library(self):
        for r in self.go("empty", {"library": "ready", "series": []}, [WAIT]):
            self.assertEqual(r.item("booksScreen")["visible"], True)
            self.assertTrue(r.item("addBookRed")["visible"])
            self.assertFalse(r.item("plusButton")["visible"])
            self.assertFalse(r.item("capsule")["visible"])
            self.one_red(r, "addBookRed")
            self.assertEqual(r.ambient, 0)
        self.narrow("empty", {"library": "ready", "series": []}, [WAIT])

    def test_one_book_nothing_selected(self):
        for r in self.go("one", lib(knights(), *others()), [WAIT]):
            self.assertEqual(r.item("seriesList")["count"], 4)
            self.assertTrue(r.item("plusButton")["visible"])
            self.assertFalse(r.item("capsule")["visible"], "nothing selected: no capsule")
            self.assertGreater(r.item("tableList")["contentY"], 400, "opens at the first untranslated chapter")
            self.assertFalse(r.has("headNo") and r.item("headNo")["visible"], "titles carry numbers: no No. column")
            self.one_red(r)
            self.assertTrue(r.item("contextLine")["text"].startswith("Knights"), "the chosen series in the header (1.3)")
        self.narrow("one", lib(knights(), *others()), [WAIT])

    def test_one_piece_selected(self):
        for r in self.go("piece", lib(knights(), *others()), [WAIT, sel("2697-2750")]):
            self.assertTrue(r.item("capsule")["visible"])
            self.assertEqual(r.item("capsuleCount")["text"], "54 chapters")
            self.assertEqual(r.item("capsuleRange")["text"], "2697-2750")
            self.assertEqual(r.item("capsuleNext")["text"], "Translate ›")
            self.assertEqual(r.item("headBox")["visible"], True)
            self.one_red(r)

    def test_selected_terms_block(self):
        acts = [WAIT, sel("2697-2750"), {"op": "py", "name": "blocking", "args": [12]}, {"op": "wait", "ms": 200}]
        for r in self.go("pieceblock", lib(knights(), *others()), acts):
            self.assertEqual(r.item("capsuleNext")["text"], "Review 12 terms ›")
            self.assertEqual(r.item("capsuleNext")["color"], "#e5383b")
            self.one_red(r, "capsuleNext")

    def test_selected_all_translated_goes_to_export(self):
        for r in self.go("piecedone", lib(knights(), *others()), [WAIT, sel("2660-2690")]):
            self.assertEqual(r.item("capsuleCount")["text"], "31 chapters")
            self.assertEqual(r.item("capsuleNext")["text"], "Export ›")

    def test_typing_a_range(self):
        acts = [WAIT, sel("2697-2750"), {"op": "call", "obj": "booksVm", "fn": "beginTyping", "args": ["2697-2720"]},
                {"op": "wait", "ms": 300}]
        for r in self.go("typing", lib(knights(), *others()), acts):
            self.assertTrue(r.item("capsuleField")["visible"])
            self.assertEqual(r.item("capsuleInput")["text"], "2697-2720")
            self.assertEqual(r.item("capsuleCount")["text"], "24 chapters")
            self.assertEqual(r.item("capsuleNext")["color"], "#5a5a5a", "the next step is faint while typing")

    def test_a_digit_on_the_focused_list_opens_the_range_field(self):
        acts = [WAIT, {"op": "clickAt", "x": 600, "y": 200}, {"op": "wait", "ms": 200}, {"op": "key", "key": "Escape"},
                {"op": "type", "text": "9"}, {"op": "wait", "ms": 300}]
        for r in self.go("digitkey", lib(knights(), *others()), acts):
            self.assertTrue(r.item("capsuleField")["visible"])
            self.assertEqual(r.item("capsuleInput")["text"], "9")
            self.assertTrue(r.item("capsuleInput")["activeFocus"])

    def test_everything_works_while_a_job_runs(self):
        run = {"running": True, "series": "Gamma", "book": "Gamma", "done": 3, "total": 20, "chapter": 4, "verb": "Stop"}
        acts = [WAIT, sel("2697-2750")]
        for r in self.go("running", lib(knights(), *others(), run=run), acts):
            self.assertEqual(r.item("capsuleCount")["text"], "54 chapters")
            self.assertEqual(r.item("capsuleNext")["text"], "Translate ›")
            self.assertTrue(r.item("plusButton")["visible"])
            self.assertEqual(r.item("step_translate")["kind"], "wave")
            self.assertEqual(r.ambient, 1, "the letter wave is the only ambient animation")

    def test_typing_with_nothing_selected(self):
        acts = [WAIT, {"op": "call", "obj": "booksVm", "fn": "beginTyping", "args": ["99999"]}, {"op": "wait", "ms": 300}]
        for r in self.go("digit", lib(knights(), *others()), acts):
            self.assertTrue(r.item("capsule")["visible"])
            self.assertEqual(r.item("capsuleInput")["text"], "99999")
            self.assertEqual(r.item("capsuleCount")["text"], "0 chapters")

    def test_several_pieces(self):
        for r in self.go("pieces", lib(knights(chapters=30, start=1, translated=6), *others()), [WAIT, sel("5, 9-12")]):
            self.assertEqual(r.item("capsuleCount")["text"], "5 chapters")
            self.assertEqual(r.item("capsuleRange")["text"], "5, 9-12")
        self.narrow("pieces", lib(knights(chapters=30, start=1, translated=6), *others()), [WAIT, sel("5, 9-12")])

    def test_several_books(self):
        data = lib(knights(books=3), {"name": "Night Watch", "books": [{"stem": "NW %d" % i, "chapters": 25} for i in (1, 2, 3)]},
                   others()[1], select=["Knights", "Book 2"])
        for r in self.go("vols", data, [WAIT, sel("1-15")]):
            self.assertEqual(r.item("seriesList")["count"], 3 + 3)          # 3 series + the 3 books of the open one
        self.narrow("vols", data, [WAIT])

    def test_series_without_books(self):
        data = lib(knights(), {"name": "Iron Crown", "books": []}, select=["Iron Crown", ""])
        for r in self.go("novol", data, [WAIT]):
            self.assertTrue(r.item("noBooks")["visible"])
            self.assertEqual(r.item("noBooksText")["text"], "No book in this series yet")
            self.one_red(r, "addBookNoBooks")

    def test_damaged_series(self):
        data = lib(knights(), {"name": "Damaged", "broken": "{ not json"}, select=["Damaged", ""])
        for r in self.go("broken", data, [WAIT]):
            self.assertTrue(r.item("unavailable")["visible"])
            self.assertEqual(r.item("unavailableTitle")["text"], "This series cannot be opened")
            self.assertEqual(r.item("unavailableReason")["text"], "series.json is damaged")
            self.assertTrue(r.item("openFolder")["visible"])
            self.one_red(r)

    def test_titles_without_numbers(self):
        data = lib({"name": "Night Watch", "books": [{"stem": "NW", "chapters": 24, "titles": "named", "translated": 3}]},
                   others()[1], select=["Night Watch", ""])
        for r in self.go("named", data, [WAIT, sel("4-9")]):
            self.assertTrue(r.item("headNo")["visible"])
            self.assertEqual(r.item("capsuleCount")["text"], "6 chapters")

    def test_long_lists_fade(self):
        many = [{"name": "Series %02d" % i, "books": [{"stem": "S%d" % i, "chapters": 12}]} for i in range(1, 35)]
        data = lib(knights(chapters=400, start=1, translated=100), *many)
        acts = [WAIT, {"op": "set", "name": "seriesList", "prop": "contentY", "value": 120}, {"op": "wait", "ms": 400}]
        for r in self.go("long", data, acts):
            self.assertEqual(r.item("fadeBottom")["opacity"], 1.0)
            self.assertEqual(r.item("fadeTop")["opacity"], 1.0)

    def test_chapters_loading(self):
        data = lib(knights(chapters=300, start=1, translated=0), scan_hold=60000)
        for r in self.go("loading", data, [{"op": "wait", "ms": 900}]):
            self.assertTrue(r.item("chapterSkeleton")["visible"])
            self.assertEqual(r.ambient, 1, "one shimmer")

    def test_adding_a_book_shows_a_spinner(self):
        acts = [WAIT, {"op": "py", "name": "doBook", "args": ["set_adding", True]}, {"op": "wait", "ms": 200}]
        for r in self.go("adding", lib(knights(), *others()), acts):
            self.assertTrue(r.item("addSpinner")["visible"])
            self.assertTrue(r.item("plusButton")["visible"])

    def test_drop_frame(self):
        acts = [WAIT, {"op": "set", "name": "dropFrame", "prop": "count", "value": 3}, {"op": "wait", "ms": 200}]
        for r in self.go("drop", lib(knights(), *others()), acts):
            self.assertEqual(r.item("dropText")["text"], "Add 3 books")
            self.assertTrue(r.item("dropOutline")["visible"])

    def test_files_dragged_over_the_window_and_dropped(self):
        files = [{"name": "A - Book 1.epub"}, {"name": "B - Book 1.epub"}, {"name": "notes.txt"}]
        enter = [WAIT, {"op": "dragEnter", "from": "incoming", "x": 500, "y": 300}, {"op": "wait", "ms": 300}]
        for r in self.go("dragover", self.add_data(files[:2]), enter):
            self.assertTrue(r.item("dropOutline")["visible"])
            self.assertEqual(r.item("dropText")["text"], "Add 2 books")
            self.assertEqual(dict(r.events)["dragEnterAccepted"], True)
        drop = enter + [{"op": "drop", "from": "incoming", "x": 500, "y": 300}, {"op": "wait", "ms": 1500}]
        for r in self.go("dropped", self.add_data(files[:2]), drop):
            self.assertFalse(r.item("dropOutline")["visible"])
            self.assertTrue(r.item("addCard")["visible"])
            self.assertEqual(r.item("addRows")["count"], 2)
        # anywhere in the window: also on the Translate screen
        acts = [WAIT, {"op": "call", "obj": "appVm", "fn": "go", "args": ["translate"]},
                {"op": "dragEnter", "from": "incoming", "x": 500, "y": 300}, {"op": "drop", "from": "incoming", "x": 500, "y": 300},
                {"op": "wait", "ms": 1500}]
        for r in self.go("droppedelsewhere", self.add_data(files[:1]), acts):
            self.assertTrue(r.item("addCard")["visible"])
            self.assertEqual(r.item("addRows")["count"], 1)

    # ------------------------------------------------------------ the Add panel
    def add_data(self, files, **kw):
        return lib(knights(), *others(), incoming=files, **kw)

    def test_add_several(self):
        files = [{"name": "Night Watch - Book 2.epub"}, {"name": "The Iron Crown - Book 1.epub"},
                 {"name": "The Iron Crown - Book 2.epub"}, {"name": "Knights - Book 2.epub"}]
        acts = [WAIT, {"op": "py", "name": "openAdd"}, {"op": "wait", "ms": 1200}]
        for r in self.go("epubs", self.add_data(files), acts):
            self.assertTrue(r.item("addCard")["visible"])
            self.assertEqual(r.item("addRows")["count"], 4)
            self.assertEqual([r.item("addSeriesText%d" % i)["text"] for i in range(4)],
                             ["Night Watch", "+ The Iron Crown", "+ The Iron Crown", "Knights"])
            self.assertEqual([r.item("addLabel%d" % i)["text"] for i in range(4)], ["Book 2", "Book 1", "Book 2", "Book 2"])
            self.assertEqual(r.item("addAction")["text"], "Add 4 books")
            self.assertEqual(r.item("addClose")["text"], "Cancel")
            self.one_red(r)
        self.narrow("epubs", self.add_data(files), acts)

    def test_add_series_dropdown(self):
        files = [{"name": "Night Watch - Book 2.epub"}, {"name": "The Iron Crown - Book 1.epub"}]
        acts = [WAIT, {"op": "py", "name": "openAdd"}, {"op": "wait", "ms": 1200}, {"op": "click", "name": "addSeries1"},
                {"op": "wait", "ms": 400}]
        for r in self.go("epubpick", self.add_data(files), acts):
            self.assertTrue(r.item("seriesPickerCard")["visible"])
            self.assertEqual(r.item("ddItem0")["text"], "+ New series The Iron Crown")
            self.assertEqual(r.item("ddItem1")["text"], "Gamma")
            self.assertEqual(r.item("ddList")["count"], 5)

    def test_add_series_enter_takes_the_typed_name(self):
        files = [{"name": "Night Watch - Book 2.epub"}, {"name": "The Iron Crown - Book 1.epub"}]
        open_pick = [WAIT, {"op": "py", "name": "openAdd"}, {"op": "wait", "ms": 1200}, {"op": "click", "name": "addSeries1"},
                     {"op": "wait", "ms": 300}]
        new = open_pick + [{"op": "type", "text": "Iron"}, {"op": "wait", "ms": 200}, {"op": "key", "key": "Return"},
                           {"op": "wait", "ms": 300}]
        for r in self.go("epubenter", self.add_data(files), new, scales=(1.0,)):
            self.assertFalse(r.item("seriesPickerCard")["visible"])
            self.assertEqual(r.item("addSeriesText1")["text"], "+ Iron")
        known = open_pick + [{"op": "type", "text": "gamma"}, {"op": "wait", "ms": 200}, {"op": "key", "key": "Return"},
                             {"op": "wait", "ms": 300}]
        for r in self.go("epubenterknown", self.add_data(files), known, scales=(1.0,)):
            self.assertEqual(r.item("addSeriesText1")["text"], "Gamma", "an existing name, not a new series")

    def test_wheel_glides_and_middle_button_scrolls(self):
        data = lib(knights(chapters=400, translated=0))
        wheel = [WAIT, {"op": "wheel", "name": "tableList", "dy": -240}, {"op": "wait", "ms": 1000}]
        for r in self.go("wheel", data, wheel, scales=(1.0,)):
            self.assertAlmostEqual(r.item("tableList")["contentY"], 120, delta=1, msg="two notches = 2 x 60 px")
        mid = [WAIT, {"op": "midPress", "name": "tableList"}, {"op": "midMove", "name": "tableList", "dy": 120},
               {"op": "wait", "ms": 500}, {"op": "dump", "name": "during"}, {"op": "midRelease", "name": "tableList", "dy": 120},
               {"op": "wait", "ms": 200}]
        for r in self.go("midscroll", data, mid, scales=(1.0,)):
            self.assertTrue(r.after["during"]["tableScroll"]["auto"])
            self.assertGreater(r.after["during"]["tableList"]["contentY"], 300)
            self.assertFalse(r.item("tableScroll")["auto"], "a long press ends with the release")

    def test_add_one_new_series(self):
        acts = [WAIT, {"op": "py", "name": "openAdd"}, {"op": "wait", "ms": 1200}]
        for r in self.go("addnew", self.add_data([{"name": "Night Market.epub"}]), acts):
            self.assertTrue(r.item("addCard")["visible"])
            self.assertEqual(r.item("addSeriesText0")["text"], "+ Night Market")
            self.assertEqual(r.item("addLabel0")["text"], "Book 1")
            self.assertEqual(r.item("addAction")["text"], "Add book")

    def test_add_one_to_a_series_by_file_name(self):
        acts = [WAIT, {"op": "py", "name": "openAdd"}, {"op": "wait", "ms": 1200}]
        for r in self.go("addvol", self.add_data([{"name": "Knights of the Lake - Book 2.epub"}]), acts,):
            self.assertEqual(r.item("addSeriesText0")["text"], "Knights")
            self.assertEqual(r.item("addLabel0")["text"], "Book 2")

    def test_already_in_the_library(self):
        files = [{"name": "Knights - copy.epub", "kind": "copy:Knights/Book 1"}]
        acts = [WAIT, {"op": "py", "name": "openAdd"}, {"op": "wait", "ms": 1500}]
        for r in self.go("dup", self.add_data(files), acts):
            self.assertFalse(r.item("addCard")["visible"], "no Add panel for a file that is already there")
            self.assertTrue(r.item("notice")["visible"])
            self.assertEqual(plain(r.item("messageText")["text"]), "Already in Knights · Book 1")

    def test_protected_and_unreadable_rows(self):
        files = [{"name": "Good.epub"}, {"name": "Locked.epub", "kind": "protected"}, {"name": "Fonts.epub", "kind": "fonts"},
                 {"name": "Broken.epub", "kind": "bad"}]
        acts = [WAIT, {"op": "py", "name": "openAdd"}, {"op": "wait", "ms": 1500}]
        for r in self.go("addprot", self.add_data(files), acts):
            notes = [r.item("addLabel%d" % i)["text"] for i in range(4)]
            self.assertEqual(notes[0], "Book 1")
            self.assertEqual(notes[1], "protected")
            self.assertEqual(notes[2], "Book 1")                    # fonts only: accepted
            self.assertIn("not an EPUB", notes[3])
            self.assertEqual(r.item("addAction")["text"], "Add 2 books")

    # ------------------------------------------------------------ delete, remove, rename, move
    def test_delete_series_and_undo(self):
        acts = [WAIT, do("deleteSeries", "Night Watch"), {"op": "wait", "ms": 1500}, {"op": "py", "name": "folders"}]
        for r in self.go("confirm", lib(knights(books=2), *others()), acts):
            self.assertTrue(r.item("notice")["visible"])
            self.assertEqual(plain(r.item("messageText")["text"]), "Deleted Night Watch")
            self.assertEqual(r.item("noticeBarText0")["text"], "Undo")
            names = dict((k, v) for k, v in r.events)["folders"]
            self.assertNotIn("Night Watch", names)
            self.assertIn(".deleted", names)

    def test_remove_book_and_undo(self):
        acts = [WAIT, do("removeBook", "Knights", "Book 2"), {"op": "wait", "ms": 1500}]
        for r in self.go("remove", lib(knights(books=2), *others(), select=["Knights", "Book 2"]), acts):
            self.assertEqual(plain(r.item("messageText")["text"]), "Removed Knights · Book 2")
            self.assertEqual(r.item("noticeBarText0")["text"], "Undo")

    def test_rename_series(self):
        acts = [WAIT, {"op": "py", "name": "rename", "args": ["series", "Knights"]}, {"op": "wait", "ms": 500}]
        for r in self.go("rename", lib(knights(books=2), *others()), acts):
            self.assertTrue(r.item("renameField")["visible"])
            self.assertEqual(r.item("renameFieldInput")["text"], "Knights")
            self.assertTrue(r.item("renameFieldInput")["activeFocus"])

    def test_rename_name_taken(self):
        acts = [WAIT, {"op": "py", "name": "rename", "args": ["series", "Knights"]}, {"op": "wait", "ms": 300},
                {"op": "set", "name": "renameFieldInput", "prop": "text", "value": "Night Watch"},
                {"op": "key", "key": "Return"}, {"op": "wait", "ms": 300}]
        for r in self.go("taken", lib(knights(books=2), *others()), acts):
            self.assertTrue(r.item("renameField")["visible"], "the field stays open")
            self.assertEqual(r.item("renameFieldInput")["text"], "Night Watch")
            self.assertEqual(r.item("seriesName")["text"] in ("Knights", "Gamma", "Night Watch", "The Long Road"), True)

    def test_rename_a_book(self):
        acts = [WAIT, {"op": "py", "name": "rename", "args": ["book", "Knights", "Book 2"]}, {"op": "wait", "ms": 500}]
        for r in self.go("vrename", lib(knights(books=2), *others(), select=["Knights", "Book 2"]), acts):
            self.assertTrue(r.item("renameField")["visible"])
            self.assertEqual(r.item("renameFieldInput")["text"], "Book 2")

    def test_move_a_book_panel(self):
        acts = [WAIT, {"op": "py", "name": "doBook", "args": ["openMove", "Book 3"]}, {"op": "wait", "ms": 500}]
        for r in self.go("move", lib(knights(books=3), *others(), select=["Knights", "Book 3"]), acts):
            self.assertTrue(r.item("moveCard")["visible"])
            self.assertEqual(r.item("moveRows")["count"], 3)
            self.assertEqual(r.item("moveAction")["text"], "Move")

    # ------------------------------------------------------------ the Reader tab (14.2)
    def test_reader_of_a_translated_chapter(self):
        acts = [WAIT, {"op": "py", "name": "read", "args": [4]}, {"op": "wait", "ms": 1200}]
        for r in self.go("reader", lib(knights(), *others()), acts):
            self.assertTrue(r.item("screen_translate")["visible"])
            self.assertTrue(r.item("readerScreen")["visible"])
            self.assertEqual(r.item("readerTabText")["text"], "Reader · 2653")
            self.assertEqual(r.item("readerTitle")["text"], "Chapter 2653 - Lyonesse")
            self.assertEqual(r.item("readerPairs")["count"], 4)
            self.assertTrue(r.item("readerTarget")["text"].startswith("Translated:"))
            self.assertEqual(r.item("readerVersion")["text"], "r1 ▾")
            self.assertEqual(r.item("step_translate")["kind"], "")
            self.one_red(r)
        self.narrow("reader", lib(knights(), *others()), acts)

    def test_reader_of_an_untranslated_chapter_shows_dashes_and_closes(self):
        acts = [WAIT, {"op": "py", "name": "read", "args": [90]}, {"op": "wait", "ms": 1200}]
        for r in self.go("readerempty", lib(knights(), *others()), acts):
            self.assertEqual(r.item("readerTarget")["text"], "—")
        acts = acts + [{"op": "click", "name": "readerClose"}, {"op": "wait", "ms": 300}]
        for r in self.go("readerclosed", lib(knights(), *others()), acts):
            self.assertFalse(r.item("readerScreen")["visible"])


if __name__ == "__main__":
    unittest.main()
