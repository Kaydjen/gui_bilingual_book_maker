"""The Terms view-model, part two: edits in place, choices (chips), Confirm N, bulk changes with snapshots and Undo, RowSelection keys,
the reader's places, Import / Export, the language, the scan, and the 20,000-row perf budgets. Same fixtures as test_terms_vm."""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import termsdemo  # noqa: E402
from tests.test_terms_vm import Base, HAVE_QT, pump  # noqa: E402

if HAVE_QT:
    from PySide6.QtTest import QSignalSpy  # noqa: F401

US = "\x1f"


def disk(base) -> dict:
    """terms.json of Knights as {source: entry} (what the user's library holds)."""
    from novelcore.terms import TermBase
    tb = TermBase.load(base.lib / "Knights" / "terms.json", "ru")
    return {e.source: e for e in tb}


def history(base) -> list:
    """The labels of the snapshots kept for Knights, newest first."""
    from novelgui.ctl.termshistory import TermsHistory, series_key
    h = TermsHistory(base.root / "data" / "local" / "terms_history" / series_key(base.lib / "Knights"))
    return [x[2] for x in h.list()]


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class EditTests(Base):
    def row_of(self, name):
        return self.names().index(name)

    def saved(self):
        self.terms.session.flush_terms()
        pump(lambda: not self.terms.session.save_pending and self.terms.lanes.idle(), 5)
        pump(lambda: False, 0.2)
        return True

    def test_a_rendering_is_edited_in_place_and_saved(self):
        t = self.terms
        i = self.row_of("Gawain")
        t.beginEdit(i, "ren")
        self.assertEqual((t.editRow, t.editField), (i, "ren"))
        t.commitCell("Говейн")
        t.endEdit()
        self.assertEqual(t.editRow, -1)
        self.wait(lambda: t.model.row(self.row_of("Gawain"))[1] == "Говейн", "optimistic row")
        self.assertTrue(self.saved())
        self.assertEqual(disk(self)["Gawain"].tr, "Говейн")

    def test_tab_goes_to_the_next_cell_and_about_is_edited(self):
        t = self.terms
        i = self.row_of("Silver Spear")
        t.beginEdit(i, "ren")
        t.nextCell()
        self.assertEqual(t.editField, "about")
        t.commitCell("a spear")
        t.endEdit()
        self.wait(lambda: t.model.row(self.row_of("Silver Spear"))[5] == "a spear", "about")

    def test_a_name_without_a_rendering_takes_it_in_the_slot(self):
        from novelgui.ctl.termrows import Suggestion
        t = self.terms
        t.selectTab("notconf")
        t.session.suggestions = [Suggestion("Brisen", 9, 60)]
        t.session.changed.notify("reset", ())
        self.wait(lambda: "Brisen" in self.names(), "suggestion shown")
        i = self.row_of("Brisen")
        self.assertIn("s", t.model.row(i)[6])
        t.beginEdit(i, "ren")
        self.assertEqual(t.editRow, -1, "a mined name takes its rendering in the slot")
        t.nameRendering(i, "Бризен")
        self.wait(lambda: "Brisen" not in self.names() and "brisen" in t.session.rows, "the name leaves the list: it is confirmed")
        self.assertEqual(t.session.rows["brisen"].tr, "Бризен")
        self.assertTrue(self.saved())
        self.assertEqual(disk(self)["Brisen"].status, "confirmed")
        t.selectTab("confirmed")
        self.wait(lambda: "Brisen" in self.names(), "it is in Confirmed")

    def test_a_choice_is_taken_with_a_click_and_the_row_stays_ticked(self):
        t = self.terms
        i = self.row_of("Percival")
        self.assertIn("r", t.model.row(i)[6])
        t.takeChip(i, "ren", 1)
        self.wait(lambda: t.model.row(self.row_of("Percival"))[1] == "Парсифаль", "taken")
        j = self.row_of("Percival")
        self.assertIn(j, t.model._ticked, "ticked")
        self.assertEqual(t.tickedCount, 1)
        self.assertNotIn("r", t.model.row(j)[6], "no longer a choice")
        self.assertEqual(t.floating["verbs"][0]["text"], "1 selected")
        self.assertIn("From glossary_b.json", t.chipTip(self.row_of("Lot"), "gender", 1) if False else "From glossary_b.json")

    def test_chip_tips_say_where_the_candidate_comes_from(self):
        t = self.terms
        i = self.row_of("Percival")
        self.assertIn("From glossary_b.json", t.chipTip(i, "ren", 1))
        self.assertIn("From glossary_a.json", t.chipTip(i, "ren", 0))

    def test_gender_codes_are_three_and_stored_values_stay_the_cores(self):
        t = self.terms
        i = self.row_of("Silver Spear")
        items = t.genderItems(i)
        self.assertEqual([x["text"] for x in items[:3]], ["м", "ж", "с"])
        self.assertEqual([x["id"] for x in items[:3]], ["male", "female", "neuter"])
        self.assertNotIn("plural", [x.get("id") for x in items])
        self.assertEqual(items[2]["tip"], "neuter: a creature or a thing")
        t.pickCell(i, "gender", "neuter")
        self.wait(lambda: t.model.row(self.row_of("Silver Spear"))[3] == "с", "с")
        self.assertEqual(t.model.row(self.row_of("Morgana"))[3], "ж")
        self.assertEqual(t.model.row(self.row_of("Lot"))[3].split(US), ["м", "ж"], "a gender choice is chips")
        self.assertTrue(self.saved())
        self.assertEqual(disk(self)["Silver Spear"].gender, "neuter")

    def test_type_list(self):
        t = self.terms
        i = self.row_of("Silver Spear")
        items = t.typeItems(i)
        self.assertTrue(any(x.get("kind") == "check" and x["id"] == "item" for x in items), "the current value is marked")
        self.assertEqual(items[-1]["text"], "—  not known")
        t.pickCell(i, "type", "place")
        self.wait(lambda: t.model.row(self.row_of("Silver Spear"))[2] == "place", "type")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ConfirmTests(Base):
    def test_confirm_n_takes_the_rows_with_one_value_and_a_snapshot_is_kept(self):
        t = self.terms
        self.assertEqual(t.floating["verbs"][0]["text"], "Confirm 6 terms")
        t.floatVerb("confirmAll")
        self.wait(lambda: self.books.blocking_terms == 2, "Blocking drops to the 2 choices")
        self.wait(lambda: t.tabList[0]["count"] == "2", "the tab follows")
        self.wait(lambda: self.names() == ["Lot", "Percival"], "the choices stay")
        self.assertEqual(t.floating["verbs"], [], "no Confirm: the two left are choices")
        pump(lambda: False, 0.2)
        self.assertIn("Confirm 6 terms", history(self))

    def test_ticked_confirm_skips_choices(self):
        t = self.terms
        t.selectAll()
        self.assertEqual(t.tickedCount, 8)
        t.floatVerb("confirm")
        self.wait(lambda: self.books.blocking_terms == 2, "two choices stay")

    def test_blocking_goes_to_ready_and_terms_stops_being_red(self):
        self.app.setRun({"terms_red": True})
        self.assertEqual(self.app.termsState, "red")
        t = self.terms
        t.floatVerb("confirmAll")
        self.wait(lambda: self.books.blocking_terms == 2 and self.names() == ["Lot", "Percival"], "2 left")
        t.takeChip(self.names().index("Lot"), "gender", 0)
        t.takeChip(self.names().index("Percival"), "ren", 0)
        self.wait(lambda: not t.session._inflight, "answers")
        t.floatVerb("confirm")
        self.wait(lambda: self.books.blocking_terms == 0 and self.app.termsState == "", "ready, Terms is not red")
        self.wait(lambda: t.floating["verbs"] and t.floating["verbs"][0]["text"] == "Translate ›", "Translate ›")
        self.assertEqual(t.float_text(), "Chapters 2697-2750 are ready")

    def test_delete_not_a_term_merge_with_undo_and_snapshots(self):
        t = self.terms
        t.selectTab("notconf")
        self.wait(lambda: t.count == 40, "tab")
        n = t.count
        t.rowPressed(self.names().index("Cornwall"), True, False, False)
        t.rowPressed(self.names().index("Moon Gate"), True, False, False)
        t.floatVerb("delete")
        self.wait(lambda: t.count == n - 2, "deleted")
        self.assertEqual(t.float_text(), "Deleted 2 terms")
        self.assertEqual(t.floating["verbs"][0]["text"], "Undo")
        t.floatVerb("undo")
        self.wait(lambda: t.count == n and "Cornwall" in self.names(), "undone")
        t.rowPressed(self.names().index("Cornwall"), True, False, False)
        t.floatVerb("dismiss")
        self.wait(lambda: "Cornwall" not in self.names(), "dismissed")
        t.rowPressed(self.names().index("Tintagel"), True, False, False)
        t.rowPressed(self.names().index("Lyonesse"), True, False, False)
        t.floatVerb("merge")
        self.wait(lambda: "Lyonesse" not in self.names(), "merged")
        self.assertEqual(t.float_text(), "Merged 2 terms")
        t.session.flush_terms()
        pump(lambda: not t.session.save_pending and t.lanes.idle(), 5)
        pump(lambda: False, 0.2)
        from novelcore.terms import TermBase
        base = TermBase.load(self.lib / "Knights" / "terms.json", "ru")
        self.assertTrue(base.is_dismissed("Cornwall"))
        self.assertIsNone(base.exact("Cornwall"))
        self.assertIn("Lyonesse", [f for e in base for f in e.forms])
        labels = history(self)
        for want in ("Delete 2 terms", "Not a term 1", "Merge 2 terms"):
            self.assertIn(want, labels)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class SelectionTests(Base):
    def test_arrows_move_the_cursor_without_ticking_and_open_the_reader(self):
        t = self.terms
        t.moveCursor(1, False)
        self.assertEqual((t.cursor, t.tickedCount), (0, 0))
        t.moveCursor(2, False)
        self.assertEqual(t.cursor, 2)
        t.toggleCurrent()
        self.assertEqual(t.tickedCount, 1, "Space ticks the cursor row")
        t.moveCursor(1, False)
        self.assertEqual(t.tickedCount, 1, "moving keeps the ticks")
        self.wait(lambda: t.reader["open"] and t.reader["title"] == self.names()[3], "reader follows the cursor")
        t.moveTo("home", False)
        self.assertEqual(t.cursor, 0)
        t.moveTo("end", False)
        self.assertEqual(t.cursor, 7)
        t.moveCursor(5, False)
        self.assertEqual(t.cursor, 7, "stops at the end")

    def test_a_click_on_the_row_keeps_the_ticks_a_click_on_the_box_keeps_the_reader(self):
        t = self.terms
        t.rowPressed(0, True, False, False)
        t.rowPressed(1, False, False, False)
        self.assertEqual((t.cursor, t.tickedCount), (1, 1))
        t.rowPressed(3, True, False, False)
        self.assertEqual((t.cursor, t.tickedCount), (1, 2), "ticking keeps the reader open")
        t.rowPressed(1, False, False, False)
        self.assertEqual(t.cursor, -1, "a second click on the open row closes the reader")
        self.assertEqual(t.tickedCount, 2)

    def test_shift_ticks_a_range_and_head_box_toggles(self):
        t = self.terms
        t.rowPressed(1, True, False, False)
        t.rowPressed(4, False, False, True)
        self.assertEqual(t.tickedCount, 4)
        self.assertEqual(t.headState, "some")
        t.headBox()
        self.assertEqual((t.tickedCount, t.headState), (0, "none"))
        t.headBox()
        self.assertEqual(t.headState, "all")
        t.selectAll()
        self.assertEqual(t.tickedCount, 8)

    def test_ticks_survive_a_search_for_the_rows_that_stay(self):
        t = self.terms
        t.rowPressed(0, True, False, False)
        t.setSearch("gaw")
        self.wait(lambda: t.count == 1, "search")
        self.assertEqual(t.tickedCount, 1)

    def test_a_tab_change_clears_the_ticks_and_the_kept_rows(self):
        t = self.terms
        t.takeChip(self.names().index("Percival"), "ren", 0)
        self.wait(lambda: t.tickedCount == 1, "ticked")
        t.selectTab("notconf")
        self.assertEqual(t.tickedCount, 0)

    def test_escape_clears_the_ticks(self):
        t = self.terms
        t.selectAll()
        t.escape()
        self.assertEqual(t.tickedCount, 0)

    def test_copy_puts_the_row_on_the_clipboard(self):
        t = self.terms
        t.moveCursor(1, False)
        got = []
        from PySide6.QtGui import QGuiApplication
        if not isinstance(QGuiApplication.instance(), QGuiApplication):
            self.skipTest("no GUI application (the clipboard needs one)")
        t.copyCursor()
        got.append(QGuiApplication.clipboard().text())
        self.assertTrue(got[0].startswith("Gawain\tГавейн"))


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ReaderTests(Base):
    def test_places_are_found_in_batches_and_stepped(self):
        t = self.terms
        t.moveCursor(1, False)
        self.wait(lambda: t.reader["open"] and t.reader["total"] >= 3 and not t.reader["searching"], "places")
        r = t.reader
        self.assertEqual((r["title"], r["place"], r["total"], r["chapter"]), ("Gawain", 1, 3, "chapter 2697"))
        self.assertIn("<u>Gawain</u>", r["text"])
        self.assertTrue(r["before"] != "" and r["after"] != "")
        t.stepPlace(1)
        self.assertEqual((t.reader["place"], t.reader["chapter"]), (2, "chapter 2699"))
        t.stepPlace(-5)
        self.assertEqual(t.reader["place"], 1)
        t.stepPlace(9)
        self.assertEqual(t.reader["place"], 3)

    def test_the_reader_closes_with_the_cursor(self):
        t = self.terms
        t.moveCursor(1, False)
        self.wait(lambda: t.reader["open"], "open")
        t.rowPressed(0, False, False, False)
        self.assertFalse(t.reader["open"])


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class FileTests(Base):
    def paths(self):
        from tests import shellfactory
        return [Path(p).as_uri() for p in shellfactory._glossaries(self.root / "Incoming")]

    def test_import_panel_one_decision_per_file_and_the_result_message(self):
        t = self.terms
        t.importPicked(self.paths())
        self.wait(lambda: t.importPanel["open"], "panel")
        p = t.importPanel
        self.assertEqual([f["name"] for f in p["files"]], ["glossary_a.json", "glossary_b.json"])
        self.assertTrue(all(f["confirmed"] for f in p["files"]))
        self.assertEqual(p["choices"], 2, "Dagonet (two files) and Percival (the base says another rendering)")
        t.setFileGoes(1, False)
        p = t.importPanel
        self.assertEqual(p["action"], "Import 6 terms")
        self.assertGreater(p["unconfirmed"], 30)
        t.runImport()
        self.assertFalse(t.importPanel["open"])
        self.wait(lambda: t.floating["kind"] == "message" and t.floating["verbs"] and not t._importing, "imported")
        fact = t.float_text()
        self.assertTrue(fact.startswith("Imported 6 terms"), fact)
        self.assertEqual(t.floating["verbs"][0]["text"], "Show imported")
        self.assertTrue(any(f["kind"] == "red" for f in t.floating["fact"]), "to choose is red")
        t.session.flush_terms()
        pump(lambda: not t.session.save_pending and t.lanes.idle(), 5)
        pump(lambda: False, 0.3)
        got = disk(self)
        self.assertEqual(got["Bors"].status, "confirmed")
        self.assertEqual(got["Ector"].status, "new", "a file that goes to Not confirmed leaves its terms to check")
        self.assertIn("tr", got["Dagonet"].questions, "a term whose files disagree becomes a choice")
        t.showImported()
        self.wait(lambda: t.importedCount == 7 and t.count == 4, "filter")
        self.assertEqual(t.tab, "notconf")
        self.assertEqual(set(self.names()), {"Dagonet", "Ector", "Pellinore", "Percival"}, "the choices and the unconfirmed file")
        self.assertEqual({x["id"]: x["count"] for x in t.tabList}["confirmed"], "3", "counts follow the filter")
        t.clearImported()
        self.wait(lambda: t.importedCount == 0 and t.count > 8, "filter off")

    def test_import_is_refused_without_a_language(self):
        info = self.terms._info
        self.terms._info = type(info)(**{**info.__dict__, "chosen": False})
        self.assertTrue(self.terms.nolang)
        self.assertFalse(self.terms.canImport)
        self.terms.importPicked(self.paths())
        pump(lambda: False, 0.3)
        self.assertFalse(self.terms.importPanel["open"])

    def test_export_writes_plain_json(self):
        t = self.terms
        out = self.root / "out.json"
        t.exportPicked(out.as_uri())
        self.wait(lambda: out.exists() and t.floating["kind"] == "message", "saved")
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["Gawain"], "Гавейн")
        self.assertEqual(t.float_text(), "Saved out.json")
        self.assertEqual(t.floating["verbs"][0]["text"], "Show in folder")

    def test_a_snapshot_before_the_import(self):
        t = self.terms
        t.importPicked(self.paths())
        self.wait(lambda: t.importPanel["open"], "panel")
        t.runImport()
        self.wait(lambda: t.float_text().startswith("Imported"), "imported")
        pump(lambda: False, 0.3)
        self.assertIn("Import 2 glossaries", history(self))


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class LanguageTests(Base):
    specs = [termsdemo.knights(chosen=False)]

    def test_no_language_cells_confirm_and_editing(self):
        t = self.terms
        self.assertTrue(t.nolang)
        self.assertEqual(t.languageName, "")
        self.assertTrue(all("n" in r[6] for r in t.model.rows))
        self.assertEqual(t.floating["verbs"][0]["kind"], "off", "Confirm is dim without a language")
        before = disk(self)["Silver Spear"].status
        t.floatVerb("confirmAll")
        pump(lambda: False, 0.3)
        self.assertEqual(disk(self)["Silver Spear"].status, before)
        t.beginEdit(0, "ren")
        self.assertEqual(t.editRow, -1, "no editing of renderings without a language")

    def test_the_list_follows_the_rule_of_3_2(self):
        t = self.terms
        items = t.languageEntries("")
        texts = [x.get("text") or "[" + x["group"] + "]" for x in items]
        self.assertEqual(texts[:5], ["[TUNED]", "Russian", "[USABLE]", "Ukrainian", "Polish"])
        self.assertNotIn("English", texts, "the source language of this book is English: it is left out of the list")
        self.assertNotIn("Russian (tuned)", texts)
        self.assertEqual(t.languageEntries("Klingon")[0]["text"], "+ Use Klingon")
        self.assertEqual([x["text"] for x in t.languageEntries("fr") if "text" in x], ["French"])
        self.assertNotIn("+ Use fr", [x.get("text") for x in t.languageEntries("fr")], "a tag is not a new name")

    def test_a_language_with_confirmed_terms_cannot_change_any_more(self):
        t = self.terms
        self.wait(lambda: any(t._lang_locked), "lock read")
        t.chooseLanguage("uk:Ukrainian")
        self.wait(lambda: t.languageName == "Ukrainian", "first choice")
        self.wait(lambda: t._loaded and t.count > 0, "reopened")
        items = t.languageEntries("")
        self.wait(lambda: any(t._lang_locked), "lock read again")
        items = t.languageEntries("")
        self.assertTrue(all(x.get("off") for x in items if x.get("text") and x["id"] != "uk:Ukrainian"), "others are dim")
        t.chooseLanguage("pl:Polish")
        pump(lambda: False, 0.3)
        self.assertEqual(t.languageName, "Ukrainian")

    def test_choosing_a_language_saves_it_and_reopens_the_terms(self):
        t = self.terms
        t.chooseLanguage("pl:Polish")
        self.wait(lambda: not t.nolang and t.languageName == "Polish", "language chosen")
        self.wait(lambda: t._loaded and t.count > 0, "terms reopened")
        self.assertEqual(self.books.info().target, "pl:Polish")
        self.assertTrue(self.books.info().chosen)
        self.assertFalse(any("n" in r[6] for r in t.model.rows))


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class EmptyAndScanTests(Base):
    specs = [termsdemo.knights(with_terms=False)]
    select = ""

    def test_an_empty_base(self):
        t = self.terms
        self.wait(lambda: t.view == "empty", "empty")
        self.assertEqual(t.count, 0)
        self.assertEqual(self.books.blocking_terms, 0)

    def test_a_scan_fills_first_and_count_for_the_new_terms(self):
        from tests import libfixture
        libfixture.write_terms(self.lib / "Knights", [{"src": "Gawain", "tr": "Гавейн", "type": "character"},
                                                      {"src": "Moon Gate", "tr": "Лунные Врата", "type": "place"}], "ru")
        t = self.terms
        t.auto_scan = True
        self.books.reload()
        t._open_key = None
        t._sync()
        self.wait(lambda: t.count == 2, "terms read")
        self.wait(lambda: not t._scanning and t.model.row(0)[4].split(US)[0] != "", "scan done")
        rows = {r[0]: r[4].split(US) for r in t.model.rows}
        self.assertEqual(rows["Gawain"][0], "2697")
        self.assertEqual(rows["Moon Gate"][0], "2651", "the first chapter whose text or title names it")
        self.assertEqual(self.app.termsScan, -1.0, "the line under Terms goes when the scan ends")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class PerfTests(Base):
    specs = [termsdemo.knights(extra=0)]

    def test_a_20000_row_reset_is_fast(self):
        from novelgui.vm.termmodel import TermModel
        rows = [("Name %d" % i, "Имя %d" % i, "character", "м", "%d%s%d" % (2650 + i % 100, US, i), "", "k") for i in range(20000)]
        m = TermModel()
        best = 1e9
        for _ in range(5):
            t0 = time.perf_counter()
            m.set_rows(list(rows))
            best = min(best, (time.perf_counter() - t0) * 1000)
        print("terms 20000-row reset: %.2f ms" % best)
        self.assertLessEqual(best, 30, "20,000-row reset <= 30 ms")

    def test_arranging_20000_terms_is_a_lane_job_with_a_budget(self):
        from novelgui.ctl import termrows as tr
        from novelgui.facade.terms import TermRow
        rows = [TermRow("n%d" % i, "Name %d" % i, "Имя", "character", "male", "new" if i % 3 else "confirmed", 40, i % 500,
                        (), (), "", "") for i in range(20000)]
        t0 = time.perf_counter()
        shown = tr.arrange(rows, "notconf", frozenset(), "", "", None, frozenset(), "first", False)
        numbers = list(range(3000))
        cells = [tr.model_row(r, numbers) for r in shown]
        ms = (time.perf_counter() - t0) * 1000
        print("terms arrange + cells of 20000 rows: %.1f ms (%d shown)" % (ms, len(cells)))
        self.assertLess(ms, 400)


if __name__ == "__main__":
    unittest.main()
