"""The Terms screen as scenarios (tests/qmlharness.py, offscreen + software): every state of the accepted mock-up (full/terms.js STATES)
at 100 % and 150 %, a few at the narrow 820 x 600 size. A real library with real EPUBs and a real terms.json behind the real
view-models (tests/shellfactory.py, tests/termsdemo.py). Asserts by objectName, one red per scene, at most one ambient animation; shots go
to NOVELGUI_SHOTS (default: the temp dir)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests import termsdemo as demo  # noqa: E402

RUN = qh.have_qt()
VM = "tests.shellfactory:make"
SCALES = (1.0, 1.5)
NARROW = (820, 600)
WAIT = {"op": "wait", "ms": 1600}
SHORT = {"op": "wait", "ms": 500}
RED = "#e5383b"
LONG = "The Legend of the Knights of the Round Table and the Lady of the Lake"


def lib(**kw):
    spec = demo.knights(**{k: kw.pop(k) for k in ("extra", "with_terms", "chapters", "ready", "unscanned", "chosen", "name")
                           if k in kw})
    data = {"library": "ready", "series": [spec], "select": [spec["name"], "Book 1"], "screen": "terms"}
    data.update(kw)
    return data


def sel(text=demo.SELECTION):
    return {"op": "call", "obj": "booksVm", "fn": "commitRange", "args": [text]}


def tv(fn, *args):
    return {"op": "call", "obj": "termsVm", "fn": fn, "args": list(args)}


def py(name, *args):
    return {"op": "py", "name": name, "args": list(args)}


def line():
    """Read the fact line of the floating element after the actions."""
    return py("floatText")


def event(r, name):
    """The last value an action recorded under `name`."""
    vals = [v for k, v in r.events if k == name]
    return vals[-1] if vals else None


def names_found():
    return [[t, n, demo.position(f)] for t, n, f in demo.SUGGESTED]


def tick(*rows):
    return [tv("rowPressed", i, True, False, False) for i in rows]


def base(*more):
    """Books load, the chapters 2697-2750 are selected (they decide Blocking), then `more`."""
    return [WAIT, sel(), WAIT] + list(more) + [line()]


@unittest.skipUnless(RUN, "PySide6 is not available")
class Scenes(unittest.TestCase):
    def go(self, name, data, actions=None, scales=SCALES, size=(1040, 720), **kw):
        tag = name + ("_narrow" if size == NARROW else "")
        return [qh.scenario("ShellScene", data, scale=k, vm=VM, actions=(actions or []), tag="terms_" + tag, size=size, **kw)
                for k in scales]

    def narrow(self, name, data, actions=None):
        return self.go(name, data, actions, scales=(1.0,), size=NARROW)

    def only_red(self, r, *inside):
        """The one red of a Terms scene: nowhere, or only inside the named elements."""
        img = r.image()
        total = qh.count_red(img)
        if not inside:
            self.assertEqual(total, 0, "no red on this screen")
            return
        got = [qh.count_red(img, self.grown(r.rect(n))) for n in inside]
        for n, c in zip(inside, got):
            self.assertGreater(c, 8, "the red thing is drawn: %s" % n)
        self.assertEqual(sum(got), total, "red only inside %s" % ", ".join(inside))

    @staticmethod
    def grown(rect, by=3):
        x, y, w, h = rect
        return (x - by, y - by, w + 2 * by, h + 2 * by)

    def rows(self, r):
        return r.item("termList")["count"]

    def slot_row(self, r):
        for i in range(60):
            if r.has("termSlot_%d" % i) and r.item("termSlot_%d" % i)["visible"]:
                return i
        self.fail("no slot row")

    # ------------------------------------------------------------ the three tabs
    def test_blocking(self):
        for r in self.go("blocking", lib(), base()):
            self.assertEqual(self.rows(r), 8)
            self.assertEqual(r.item("tabCount_blocking")["text"], "8")
            self.assertEqual(event(r, "floatText"), "Chapters 2697-2750 wait for 8 terms")
            self.assertEqual(r.item("termFloatBarText0")["text"], "Confirm 6 terms")
            self.assertNotEqual(r.item("termFloatBarText0")["color"], RED, "red only while translation waits")
            self.assertEqual(r.item("termSrc_0")["text"], "Gawain")
            self.assertTrue(r.item("chip_ren_5_0")["visible"], "Percival: two renderings side by side")
            self.assertTrue(r.item("chip_gender_1_1")["visible"], "Lot: м | ж")
            self.assertEqual(r.item("termHead_first")["text"], "↑ First")
            self.only_red(r)
            self.assertEqual(r.ambient, 0)
        self.narrow("blocking", lib(), base())

    def test_not_confirmed(self):
        acts = [WAIT, sel(), WAIT, py("suggest", names_found()), tv("selectTab", "notconf"), WAIT, line()]
        for r in self.go("notconf", lib(), acts):
            self.assertEqual(self.rows(r), 43)
            self.assertEqual(r.item("tabCount_notconf")["text"], "43")
            self.assertEqual(r.item("termFloatBarText0")["text"], "Confirm 36 terms")
            self.assertGreaterEqual(self.slot_row(r), 0, "a name without a rendering is an empty field")
            self.only_red(r)
            self.assertEqual(r.ambient, 0)
        self.narrow("notconf", lib(), acts)

    def test_waits_for_terms(self):
        data = dict(lib(), run={"terms_red": True})
        for r in self.go("waits", data, base()):
            self.assertEqual(r.item("termFloatBarText0")["color"], RED)
            self.assertEqual(event(r, "floatText"), "Chapters 2697-2750 wait for 8 terms")
            self.only_red(r, "step_terms", "termFloat")

    def test_blocking_done_goes_to_translate(self):
        for r in self.go("ready", lib(ready=True), base()):
            self.assertEqual(self.rows(r), 0)
            self.assertEqual(r.item("tabCount_blocking")["text"], "0")
            self.assertEqual(event(r, "floatText"), "Chapters 2697-2750 are ready")
            self.assertEqual(r.item("termFloatBarText0")["text"], "Translate ›")
            self.only_red(r)

    def test_no_chapters_selected(self):
        for r in self.go("nosel", lib(), [WAIT, line()]):
            self.assertEqual(r.item("tab_blocking")["color"], "#5a5a5a", "Blocking is dim")
            self.assertEqual(r.item("tabCount_blocking")["text"], "0")
            self.assertEqual(self.rows(r), 40)
            self.assertEqual(r.item("tab_notconf")["color"], "#f4f4f4", "Not confirmed opens")
            self.only_red(r)

    def test_type_filter(self):
        acts = [WAIT, sel(), WAIT, tv("selectTab", "notconf"), tv("pickTypeFilter", "character"), WAIT, line()]
        for r in self.go("typef", lib(), acts):
            self.assertEqual(r.item("termHead_typ")["text"], "Character ▾")
            self.assertEqual(r.item("termHead_typ")["color"], "#f4f4f4")
            self.assertEqual(r.item("tabCount_confirmed")["text"], "2", "counts follow the filter")
            self.assertEqual(self.rows(r), int(r.item("tabCount_notconf")["text"]))
            self.only_red(r)

    def test_long_series_name(self):
        for r in self.go("longname", lib(name=LONG), base()):
            short = qh.scenario("ShellScene", lib(), scale=r.scale, vm=VM, actions=base(), tag="terms_blocking")
            self.assertTrue(r.item("contextLine")["text"].startswith("The Legend"))
            self.assertEqual(r.rect("step_terms")[0], short.rect("step_terms")[0], "the steps never move")
            self.only_red(r)

    def test_search_open(self):
        acts = [WAIT, sel(), WAIT, tv("selectTab", "notconf"), tv("openSearch"), tv("setSearch", "gate"), WAIT, line()]
        for r in self.go("sopen", lib(), acts):
            self.assertTrue(r.item("searchInput")["visible"])
            self.assertTrue(r.item("searchClear")["visible"])
            self.assertEqual(self.rows(r), 1)
            self.assertFalse(r.item("searchZero")["visible"])
            self.only_red(r)

    def test_search_with_no_hit(self):
        acts = [WAIT, sel(), WAIT, tv("selectTab", "notconf"), tv("openSearch"), tv("setSearch", "Mordred"), WAIT, line()]
        for r in self.go("zero", lib(), acts):
            self.assertEqual(self.rows(r), 0)
            self.assertTrue(r.item("searchZero")["visible"])
            self.assertEqual(r.item("searchZero")["text"], "0")
            self.assertFalse(r.item("termFloat")["visible"])
            self.only_red(r)

    # ------------------------------------------------------------ the reader and the keys
    def test_term_selected_opens_the_reader(self):
        acts = base(tv("rowPressed", 0, False, False, False), WAIT)
        for r in self.go("one", lib(), acts):
            self.assertTrue(r.item("termReader")["visible"])
            self.assertEqual(r.item("readerTerm")["text"], "Gawain")
            self.assertEqual(r.item("readerChapter")["text"], "chapter 2697")
            self.assertEqual(r.item("readerCounter")["text"], "1 / 3")
            self.assertIn("Gawain", r.item("readerText")["rich"])
            self.assertIn("<u>", r.item("readerText")["rich"])
            self.assertGreater(r.item("termReader")["y"], r.item("termList")["y"] + 60, "the table keeps the rest of the height")
            self.only_red(r)
        self.narrow("one", lib(), acts)

    def test_no_reader_when_nothing_is_selected(self):
        for r in self.go("noreader", lib(), base()):
            self.assertFalse(r.item("termReader")["visible"])
            self.assertGreater(r.item("termList")["h"], 400, "the table runs the full height")

    def test_ticking_keeps_the_reader_and_turns_the_bar(self):
        acts = base(tv("selectTab", "notconf"), WAIT, *tick(1, 2, 3))
        for r in self.go("ticked", lib(), acts):
            self.assertEqual(r.item("termBarText0")["text"], "3 selected")
            self.assertEqual([r.item("termBarText%d" % k)["text"] for k in range(1, 5)], ["Confirm", "Merge", "Not a term", "Delete"])
            self.assertFalse(r.item("termFloat")["visible"])
            self.only_red(r)
        self.narrow("ticked", lib(), acts)

    def test_keyboard_focus_ring_in_the_table(self):
        acts = base({"op": "click", "name": "termSrc_1"}, {"op": "key", "key": "Down"}, SHORT)
        for r in self.go("focusrow", lib(), acts):
            self.assertTrue(r.item("termTable")["activeFocus"])
            self.assertTrue(r.item("termReader")["visible"], "the arrows open the reader")
            self.assertEqual(r.item("readerTerm")["text"], "Silver Spear")
            self.only_red(r)

    def test_keys_move_tick_and_edit(self):
        acts = base({"op": "click", "name": "termSrc_0"}, {"op": "key", "key": "Down"}, {"op": "key", "key": "Space"},
                    {"op": "key", "key": "Return"}, SHORT)
        r = self.go("keys", lib(), acts, scales=(1.0,))[0]
        self.assertTrue(r.has("editRen_1") and r.item("editRen_1")["visible"], "Enter edits the rendering of the cursor row")
        self.assertEqual(r.item("termBarText0")["text"], "1 selected", "Space ticked the row")

    # ------------------------------------------------------------ confirmed, deleted, language
    def test_confirmed_tab(self):
        for r in self.go("confirmed", lib(), base(tv("selectTab", "confirmed"), WAIT)):
            self.assertEqual(self.rows(r), 4)
            self.assertFalse(r.item("termFloat")["visible"])
            self.assertFalse(r.item("termBar")["visible"])
            self.only_red(r)

    def test_deleted_with_undo(self):
        acts = base(tv("selectTab", "notconf"), WAIT, *tick(2, 3)) + [tv("floatVerb", "delete"), WAIT, line()]
        for r in self.go("deleted", lib(), acts):
            self.assertEqual(self.rows(r), 38)
            self.assertEqual(event(r, "floatText"), "Deleted 2 terms")
            self.assertEqual(r.item("termFloatBarText0")["text"], "Undo")
            self.assertFalse(r.item("termBar")["visible"], "a message replaces the floating bar")
            self.only_red(r)

    def test_no_language(self):
        acts = base(tv("selectTab", "notconf"), WAIT)
        for r in self.go("nolang", lib(chosen=False), acts):
            self.assertEqual(r.item("termHead_ren")["text"], "To ▾")
            self.assertEqual(r.item("termHead_ren")["color"], RED)
            self.assertEqual(r.item("termRen_0")["text"], "—")
            self.assertEqual(r.item("termBarText0")["color"], "#5a5a5a", "Confirm is dim")
            self.only_red(r, "termHead_ren")
        self.narrow("nolang", lib(chosen=False), acts)

    def test_choosing_the_language_from_the_heading(self):
        acts = base({"op": "click", "name": "termHead_ren"}, SHORT)
        r = self.go("langlist", lib(chosen=False), acts, scales=(1.0,))[0]
        self.assertTrue(r.item("langDropCard")["visible"])
        self.assertEqual(r.item("langDropCard")["w"], 260)

    def test_empty_base(self):
        for r in self.go("empty", lib(with_terms=False), [WAIT, line()]):
            self.assertTrue(r.item("termsEmpty")["visible"])
            self.assertEqual(r.item("termsEmptyText")["text"], "No terms yet")
            self.assertNotEqual(r.item("importEmpty")["kind"], "accent", "terms are optional: Import is not red")
            self.only_red(r)
            self.assertEqual(r.ambient, 0)
        self.narrow("empty", lib(with_terms=False), [WAIT, line()])

    def test_empty_base_without_a_language(self):
        r = self.go("emptynolang", lib(with_terms=False, chosen=False), [WAIT, line()], scales=(1.0,))[0]
        self.assertEqual(r.item("importEmpty")["kind"], "off", "Import is dim while no language")
        self.only_red(r, "termHead_ren")

    # ------------------------------------------------------------ the scan and loading
    def test_book_scan(self):
        acts = base(tv("selectTab", "notconf"), tv("sortBy", "first"), py("holdScan", 40), WAIT)
        for r in self.go("scan", lib(unscanned=3), acts):
            self.assertEqual(r.item("tabCount_blocking")["text"], "…")
            self.assertEqual(r.item("tabCount_notconf")["text"], "…")
            self.assertEqual(r.item("tabCount_confirmed")["text"], "4", "Confirmed is not waiting for the scan")
            self.assertEqual(event(r, "floatText"), "Reading the book · 40 %")
            self.assertTrue(r.item("stepScan_Terms")["visible"], "the thin line under the word Terms")
            self.assertFalse(r.item("termFirst_0")["visible"], "First shimmers while the book is read")
            self.assertFalse(r.item("termBar")["visible"])
            self.only_red(r)
            self.assertLessEqual(r.ambient, 1)

    def test_book_scan_of_an_empty_base(self):
        acts = [WAIT, py("holdScan", 40), WAIT, line()]
        for r in self.go("scannew", lib(with_terms=False), acts):
            self.assertTrue(r.item("termSkeleton")["visible"], "grey rows instead of the Import centre")
            self.assertFalse(r.item("termsEmpty")["visible"])
            self.assertEqual(event(r, "floatText"), "Reading the book · 40 %")
            self.only_red(r)
            self.assertLessEqual(r.ambient, 1)

    def test_loading(self):
        for r in self.go("loading", lib(), [WAIT, py("holdLoading"), WAIT]):
            self.assertTrue(r.item("termSkeleton")["visible"])
            self.only_red(r)
            self.assertLessEqual(r.ambient, 1)

    # ------------------------------------------------------------ editing in place and the lists
    def test_a_cell_is_edited_in_place(self):
        acts = base(tv("beginEdit", 5, "ren"), WAIT)
        for r in self.go("edit", lib(), acts):
            self.assertTrue(r.item("editRen_5")["visible"])
            self.assertEqual(r.item("editRen_5Input")["text"], "Персиваль")
            self.assertTrue(r.item("editRen_5Input")["activeFocus"])
            self.only_red(r)

    def test_type_list_opens_at_once(self):
        acts = base({"op": "click", "name": "termType_5"}, SHORT)
        for r in self.go("typecell", lib(), acts):
            self.assertTrue(r.item("typeMenuCard")["visible"])
            self.assertEqual(r.item("menuItem10")["text"], "—  not known", "last in the list")
            self.assertEqual(r.item("menuItem0")["text"], "character")
            self.only_red(r)

    def test_gender_list(self):
        acts = base({"op": "click", "name": "termGender_2"}, SHORT)
        r = self.go("gendercell", lib(), acts, scales=(1.0,))[0]
        self.assertTrue(r.item("genderMenuCard")["visible"])
        self.assertEqual([r.item("menuItem%d" % k)["text"] for k in range(3)], ["м", "ж", "с"])

    # ------------------------------------------------------------ import and export
    def test_import_panel_one_decision_per_file(self):
        acts = base(py("importGlossaries"), WAIT)
        for r in self.go("ipanel", lib(), acts):
            self.assertTrue(r.item("importCard")["visible"])
            self.assertEqual(r.item("importName0")["text"], "glossary_a.json")
            self.assertEqual(r.item("importName1")["text"], "glossary_b.json")
            self.assertTrue(r.item("importGoes0")["text"].startswith("Confirmed"))
            self.assertEqual(r.item("importAction")["text"], "Import 6 terms")
            self.only_red(r)

    def test_importing_shows_only_the_dim_line_with_a_thin_progress(self):
        acts = base(py("holdImporting", 1, 2, 0.45), WAIT)
        for r in self.go("importing", lib(), acts):
            self.assertEqual(event(r, "floatText"), "Importing glossary_a.json, glossary_b.json · 1 of 2")
            self.assertFalse(r.item("termBar")["visible"])
            self.assertFalse(r.item("termFloatBar")["visible"], "no verbs while it runs")
            self.only_red(r)

    def test_imported_message(self):
        acts = base(py("importGlossaries"), WAIT, tv("runImport"), WAIT)
        for r in self.go("imported", lib(), acts):
            self.assertEqual(event(r, "floatText"), "Imported 6 terms · 5 confirmed · 0 not confirmed · 2 to choose")
            self.assertEqual(r.item("termFloatBarText0")["text"], "Show imported")
            self.only_red(r, "termFloat")

    def test_imported_filter_chip(self):
        acts = base(py("importGlossaries"), WAIT, tv("runImport"), WAIT, tv("showImported"), WAIT)
        for r in self.go("impfilter", lib(), acts):
            self.assertTrue(r.item("importedChip")["visible"])
            self.assertEqual(self.rows(r), 2)
            self.assertEqual(r.item("tabCount_notconf")["text"], "2")
            self.only_red(r)

    def test_glossary_saved(self):
        acts = base(py("exportTo"), WAIT)
        for r in self.go("saved", lib(), acts):
            self.assertEqual(event(r, "floatText"), "Saved terms-Knights.json")
            self.assertEqual(r.item("termFloatBarText0")["text"], "Show in folder")
            self.only_red(r)


if __name__ == "__main__":
    unittest.main()
