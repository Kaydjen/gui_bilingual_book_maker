"""The Export view-model with a real library behind it (QCoreApplication, real lanes, the real helper process): the pieces of the demo
book, the choice as on Books (box, row, Shift, head box, an opened piece, the From - To fields), the marks and their tooltips, the bar
and the names of the buttons, a REAL export through the helper (`.part`, the rename, the history, the result panel, `Try again`,
cancel), the running job's chapters joining the pieces live, `Translate ›`, `1 problem`, and the header glow. The model runs under
QAbstractItemModelTester. Skipped without PySide6."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from tests import exportscenes as es  # noqa: E402
from tests import translatedemo as demo  # noqa: E402

KEEP: list = []
NEVER = "http://127.0.0.1:9"


def pump(cond, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            QCoreApplication.processEvents()
            return True
        time.sleep(0.005)
    return False


def pos(n):
    return demo.position(n)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class Base(unittest.TestCase):
    specs = None
    exports = es.EXPORTS
    failed = ()
    select = None
    keys = 1
    screen = "export"

    @classmethod
    def setUpClass(cls):
        cls.qapp = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="novelex-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.lib = self.root / "Novel library"
        self.lib.mkdir()
        from tests import libfixture
        libfixture.build(self.lib, self.specs or [demo.knights(done=es.DONE)])
        for series, book, first, last, iso, file in self.exports:
            from novelgui.facade import exports as fex
            fex.add_history(self.lib / series, book, range(pos(first), pos(last) + 1), file, iso)
        for number, block, reason in self.failed:
            demo.write_failed_block(self.lib / "Knights", "Book 1", pos(number), block, reason)
        self.make()

    def make(self):
        from tests import shellfactory
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        os.environ["NOVELGUI_DATA"] = str(data)
        os.environ["NOVELGUI_API_BASE"] = NEVER
        os.environ.pop("NOVELGUI_NOTIFY", None)
        os.environ.pop("NOVELGUI_TRAY", None)
        self.addCleanup(lambda: os.environ.pop("NOVELGUI_API_BASE", None))
        win = {"books_last": {"series": "Knights", "book": "Book 1"}, "screen": self.screen}
        (data / "settings.json").write_text(json.dumps({"library": str(self.lib), "win": win}), encoding="utf-8")
        keys = [shellfactory.planted(i) for i in range(self.keys)]
        if keys:
            (data / "keys.json").write_text(json.dumps({"version": 1, "keys": keys}), encoding="utf-8")
        from novelgui.runtime import notify, tray as trays
        from novelgui.runtime.assemble import Parts
        parts = Parts(settings_dir=data, local=data / "local", tray=trays.RecordingTray(data, available=False))
        parts.notifier = notify.RecordingNotifier(data)
        parts.app.notifier = parts.notifier
        self.parts, self.books, self.app, self.vm = parts, parts.books_vm, parts.app, parts.export_vm
        self.tr, self.rc = parts.translate_vm, parts.run
        self.started: list = []
        self.rc.submit = lambda fn, **kw: self.started.append(SimpleNamespace(fn=fn, **kw))
        self.tr.mine_names = False
        parts.terms_vm.mine_names = False
        parts.terms_vm.auto_scan = False
        self.revealed: list = []
        self.vm.reveal = self.revealed.append
        KEEP.append(parts)
        self.addCleanup(parts.close)
        self.model_test = QAbstractItemModelTester(self.vm.rows, QAbstractItemModelTester.FailureReportingMode.Fatal)
        if self.select:
            self.assertTrue(pump(lambda: self.books.view == "chapters" and not self.books.session.scanning))
            self.assertTrue(self.books.commitRange(self.select))
        self.settle()

    def settle(self, ms=0.15):
        vm = self.vm
        self.assertTrue(pump(lambda: vm.view == "ready" and self.parts.lanes.idle() and not vm._sync_t.isActive()
                             and self.parts.crunch.idle_now()), "the Export screen did not settle: %s" % vm.view)
        pump(lambda: False, ms)

    @property
    def path(self):
        return self.lib / "Knights"

    def labels(self):
        return [r[1] for r in self.vm.rows.rows]

    def row(self, label):
        for i, r in enumerate(self.vm.rows.rows):
            if r[1] == label and r[0] != "chapter":
                return i
        raise KeyError("%s in %s" % (label, self.labels()))

    def press(self, label, ctrl=False, shift=False):
        self.vm.rowPressed(self.row(label), ctrl, shift)

    def ticked_numbers(self):
        return sorted(p + demo.FIRST_NUMBER - 1 for p in self.vm._ticks)

    def run_export(self, mode="single", seconds=30):
        self.vm.act(mode)
        self.assertTrue(pump(lambda: self.vm.panel != "", seconds), "the export did not end")
        return self.vm.panelData

    def out_files(self):
        out = self.path / "out"
        return sorted(p.name for p in out.glob("*")) if out.exists() else []


class Pieces(Base):
    def test_the_rows_are_the_map_of_the_volume(self):
        vm = self.vm
        self.assertEqual(vm.view, "ready")
        self.assertEqual(self.labels(), ["2650-2699", "2700-2709", "2710-2739", "2740-2759", "2760-2819"])
        rows = vm.rows.rows
        self.assertEqual([r[0] for r in rows], ["piece", "gap", "piece", "piece", "gap"])
        self.assertEqual([(r[3], r[4]) for r in rows], [("exported", "exported"), ("Translate ›", "go"), ("exported", "exported"),
                                                         ("", ""), ("Translate ›", "go")])
        self.assertEqual([r[5] for r in rows], ["empty", "none", "empty", "on", "none"])

    def test_the_default_choice_is_the_newest_piece_never_exported(self):
        vm = self.vm
        self.assertEqual(self.ticked_numbers(), list(range(2740, 2760)))
        self.assertEqual((vm.summaryCount, vm.summaryRanges), ("20 chapters", "· 2740-2759"))
        self.assertEqual(vm.headState, "some")

    def test_the_model_is_a_clean_model(self):
        self.assertEqual(self.vm.rows.rowCount(), 5)
        self.assertEqual(self.vm.rows.roleNames()[256 + 5], b"markKind")

    def test_export_reads_nothing_from_books_and_changes_nothing_there(self):
        self.assertEqual(self.books.terms_context()[2], ())
        self.press("2650-2699")
        self.assertEqual(self.books.terms_context()[2], (), "ticking on Export leaves the Books selection alone")


class Choosing(Base):
    def test_a_click_toggles_a_piece_and_ctrl_does_the_same(self):
        self.press("2710-2739")
        self.assertEqual(self.ticked_numbers(), list(range(2710, 2760)))
        self.assertEqual((self.vm.summaryCount, self.vm.summaryRanges), ("50 chapters", "· 2710-2759"))
        self.press("2710-2739", ctrl=True)
        self.assertEqual(self.ticked_numbers(), list(range(2740, 2760)))
        self.assertEqual(self.vm.cursor, self.vm.rows.rows.index(self.vm.rows.row(self.row("2710-2739"))))

    def test_shift_takes_every_translated_chapter_between_across_a_gap(self):
        self.press("2650-2699")
        self.press("2740-2759", shift=True)
        want = list(range(2650, 2700)) + list(range(2710, 2760))
        self.assertEqual(self.ticked_numbers(), want)
        self.assertEqual(self.vm.summaryRanges, "· 2650-2699, 2710-2759")
        rows = self.vm.rows.rows
        self.assertIn("hatch", rows[self.row("2700-2709")][6].split(","), "what lies between is hatched")

    def test_the_head_box_is_all_or_none(self):
        vm = self.vm
        vm.headBox()
        self.assertEqual((vm.headState, vm.ticked), ("all", 100))
        vm.headBox()
        self.assertEqual((vm.headState, vm.ticked), ("none", 0))
        self.assertEqual((vm.summaryCount, vm.summaryRanges), ("", ""))
        self.assertTrue(all(s["kind"] == "off" for s in vm.bar))
        self.assertEqual(vm.bar[0]["tip"], "Tick at least one piece.")
        vm.headBox()
        self.assertEqual(vm.headState, "all")

    def test_a_gap_row_is_not_a_choice(self):
        before = set(self.vm._ticks)
        self.press("2700-2709")
        self.assertEqual(set(self.vm._ticks), before)

    def test_an_opened_piece_lists_its_chapters_and_a_part_of_it_can_be_chosen(self):
        vm = self.vm
        vm.toggleOpen(self.row("2740-2759"))
        rows = vm.rows.rows
        i = self.row("2740-2759")
        self.assertEqual(rows[i][6].split(","), ["sel", "open"])
        self.assertEqual(rows[i][7], "2740|2759")
        self.assertEqual([r[0] for r in rows[i + 1:i + 21]], ["chapter"] * 20)
        self.assertEqual(rows[i + 1][1:3], ("2740", "Chapter 2740 - The Gate"))
        vm.rowPressed(i + 1, False, False)                           # a chapter row toggles that chapter
        self.assertEqual(vm.ticked, 19)
        self.assertEqual(vm.rows.rows[i][3:5], ("19 of 20", "part"))
        self.assertEqual(vm.rows.rows[i][5], "part")
        vm.rowPressed(i + 5, False, True)                            # Shift: everything from the last click to this chapter
        self.assertEqual(vm.ticked, 20)
        vm.toggleOpen(i)
        self.assertEqual(self.labels()[-2:], ["2740-2759", "2760-2819"])
        self.assertEqual(len(vm.rows.rows), 5)

    def test_typing_a_part_of_an_opened_piece(self):
        vm = self.vm
        i = self.row("2740-2759")
        vm.toggleOpen(i)
        self.assertTrue(vm.setSpan(i, "2745", "2750"))
        self.assertEqual(self.ticked_numbers(), list(range(2745, 2751)))
        self.assertEqual(vm.rows.rows[i][7], "2745|2750")
        self.assertTrue(vm.setSpan(i, "2755", "2742"), "From > To is swapped")
        self.assertEqual(self.ticked_numbers(), list(range(2742, 2756)))
        before = set(vm._ticks)
        self.assertFalse(vm.setSpan(i, "2700", "2745"), "outside the piece: the field flashes and goes back")
        self.assertFalse(vm.setSpan(i, "abc", "2745"))
        self.assertFalse(vm.setSpan(i, "", ""))
        self.assertEqual(set(vm._ticks), before)

    def test_the_keyboard_walks_the_rows_and_space_ticks(self):
        vm = self.vm
        vm.moveCursor(1)
        self.assertEqual(vm.cursor, 0)
        vm.moveCursor(1)
        vm.moveCursor(1)
        vm.toggleCurrent()
        self.assertEqual(self.ticked_numbers(), list(range(2710, 2760)))
        vm.moveTo("end")
        self.assertEqual(vm.cursor, 4)
        vm.moveTo("home")
        vm.activateRow(0)                                            # Enter opens a piece
        self.assertIn("open", vm.rows.rows[0][6])
        vm.moveCursor(-100)
        self.assertEqual(vm.cursor, 0)

    def test_the_default_stays_while_nothing_was_touched_and_the_user_choice_stays_after(self):
        vm = self.vm
        self.assertFalse(vm._touched)
        self.press("2650-2699")
        self.assertTrue(vm._touched)
        self.app.go("books")
        self.app.go("export")
        pump(lambda: False, 0.2)
        self.assertEqual(self.ticked_numbers(), list(range(2650, 2700)) + list(range(2740, 2760)))


class Marks(Base):
    def test_tooltips_of_the_marks(self):
        vm = self.vm
        exported = vm.markTip(self.row("2650-2699"))
        self.assertEqual(exported[0], "Exported on 3 Nov.")
        self.assertEqual(exported[1][0], ["File", es.A])
        gap = vm.markTip(self.row("2700-2709"))
        self.assertEqual(gap[0], "Not translated yet.")
        self.assertEqual(vm.markTip(self.row("2740-2759")), "", "a never exported piece has no mark")
        i = self.row("2740-2759")
        vm.rowPressed(self.row("2740-2759"), False, False)
        vm.toggleOpen(i)
        vm.rowPressed(i + 1, False, False)
        self.assertEqual(vm.markTip(i), "1 of the 20 translated chapters of this piece are ticked.")

    def test_exported_opens_the_file_in_its_folder(self):
        self.vm.markClicked(self.row("2650-2699"))
        self.assertEqual(self.revealed, [str(self.path / "out" / es.A)])

    def test_translate_gap_row_makes_the_chapters_the_books_selection_and_opens_translate(self):
        self.vm.markClicked(self.row("2700-2709"))
        self.assertEqual(self.app.screen, "translate")
        self.assertEqual(self.books.terms_context()[2], tuple(range(pos(2700), pos(2709) + 1)))
        self.settle()

    def test_every_tip_the_screen_reads_exists(self):
        keys = "head open from to box summary noBook problemChapter gap busy".split()
        self.assertEqual([k for k in keys if not self.vm.tips.get(k)], [])


class Problems(Base):
    specs = [demo.knights(done=[[2650, 2759]])]
    exports = ()
    failed = [(2721, 0, "empty")]

    def test_a_failed_chapter_stays_in_the_piece_and_is_left_out_of_the_file(self):
        vm = self.vm
        self.assertEqual(self.labels(), ["2650-2759", "2760-2819"])
        row = vm.rows.rows[0]
        self.assertEqual((row[3], row[4]), ("1 problem", "problem"))
        self.assertEqual(vm.ticked, 109)
        self.assertNotIn(pos(2721), vm._ticks)
        self.assertEqual((vm.summaryCount, vm.summaryRanges), ("109 chapters", "· 2650-2759"), "a failed chapter does not split the range")
        tip = vm.markTip(0)
        self.assertEqual(tip[0], "A block of chapter 2721 is not translated, so the chapter is left out of the file.")

    def test_the_link_opens_the_problems_of_translate_at_that_chapter(self):
        self.settle()
        self.vm.markClicked(0)
        self.assertEqual(self.app.screen, "translate")
        self.assertTrue(pump(lambda: self.tr.tab == "problems"), "Translate shows its problems")
        self.assertEqual(self.tr.problem_rows.cursor, 0)

    def test_an_opened_piece_shows_the_chapter_in_red_and_without_a_box(self):
        vm = self.vm
        vm.toggleOpen(0)
        rows = vm.rows.rows
        k = next(i for i, r in enumerate(rows) if r[0] == "chapter" and r[4] == "problem")
        self.assertEqual((rows[k][1], rows[k][3], rows[k][5]), ("2721", "1 problem", "none"))
        vm.rowPressed(k, False, False)
        self.assertNotIn(pos(2721), vm._ticks)
        self.assertEqual(vm.markTip(k), vm.tips["problemChapter"])


class NothingTranslated(Base):
    specs = [demo.knights()]
    exports = ()

    def test_one_gap_row_and_both_buttons_dim(self):
        vm = self.vm
        self.assertEqual(self.labels(), ["2650-2819"])
        self.assertEqual((vm.rows.rows[0][3], vm.rows.rows[0][5]), ("Translate ›", "none"))
        self.assertEqual([s["kind"] for s in vm.bar], ["off", "off"])
        self.assertEqual(vm.bar[0]["tip"], "Nothing translated in this volume yet.")
        self.assertEqual(vm.headState, "none")
        self.assertEqual(vm.summaryCount, "")


class NoLanguage(Base):
    specs = [demo.knights(done=es.DONE, chosen=False)]

    def test_the_buttons_say_why_they_are_dim(self):
        vm = self.vm
        self.assertEqual([s["text"] for s in vm.bar], ["Export", "+ English"])
        self.assertEqual([s["kind"] for s in vm.bar], ["off", "off"])
        self.assertIn("language", vm.bar[0]["tip"])
        vm.act("single")
        pump(lambda: False, 0.2)
        self.assertEqual(self.out_files(), [])


class Bar(Base):
    def test_the_buttons_name_the_languages_and_state_what_they_do(self):
        vm = self.vm
        self.assertEqual([(s["id"], s["text"], s["kind"]) for s in vm.bar],
                         [("single", "Export Russian", ""), ("bilingual", "Russian + English", "")])
        tip = vm.bar[0]["tip"]
        self.assertEqual(tip[0], "Export the Russian translation of the ticked chapters as one EPUB.")
        self.assertEqual(tip[1], [["Folder", "Knights/out"]])
        self.assertEqual(vm.bar[1]["tip"][0], "Export the same chapters in Russian and English: each Russian paragraph followed by its English original.")

    def test_a_series_in_another_language_changes_the_names(self):
        from novelgui.facade import books as fbooks
        fbooks.set_series_language(str(self.path), "uk:Ukrainian")
        self.vm.books.rescan()
        self.assertTrue(pump(lambda: self.vm.bar[0]["text"] == "Export Ukrainian"))
        self.assertEqual(self.vm.bar[1]["text"], "Ukrainian + English")


class RealExport(Base):
    def test_the_file_is_written_through_the_helper_and_no_part_is_left(self):
        vm = self.vm
        data = self.run_export("single")
        self.assertEqual(vm.panel, "ok")
        self.assertEqual(data["title"], "Exported")
        self.assertEqual(data["file"], "Knights 2740-2759 ru.epub")
        self.assertTrue(data["facts"].startswith("20 chapters · "), data["facts"])
        self.assertEqual(self.out_files(), ["Knights 2740-2759 ru.epub"], "no .part is left")
        self.assertEqual(vm.busy, "")
        self.assertEqual([s["kind"] for s in vm.bar], ["", ""])
        import zipfile
        with zipfile.ZipFile(self.path / "out" / data["file"]) as z:
            self.assertIsNone(z.testzip())

    def test_after_close_the_exported_rows_get_the_mark_and_the_history_is_saved(self):
        vm = self.vm
        self.run_export("single")
        self.assertTrue(pump(lambda: vm._pending_hist is not None))
        self.assertEqual(vm.rows.rows[self.row("2740-2759")][3], "", "the mark comes after Close")
        vm.panelClose()
        self.assertEqual(vm.panel, "")
        self.assertEqual(self.app.panel, "")
        i = self.row("2740-2759")
        self.assertEqual((vm.rows.rows[i][3], vm.rows.rows[i][4]), ("exported", "exported"))
        from novelgui.facade import exports as fex
        got = fex.read_history(self.path, "Book 1")
        self.assertEqual(got[pos(2750)][1], "Knights 2740-2759 ru.epub")
        self.assertEqual(vm.ticked, 20, "the choice stays")

    def test_show_in_folder_reveals_the_file(self):
        vm = self.vm
        data = self.run_export("single")
        vm.panelOk()
        self.assertEqual(self.revealed, [str(self.path / "out" / data["file"])])
        self.assertEqual(vm.panel, "")

    def test_the_bilingual_file_names_both_languages_and_a_second_export_never_overwrites(self):
        vm = self.vm
        d1 = self.run_export("bilingual")
        self.assertEqual(d1["file"], "Knights 2740-2759 ru+en.epub")
        vm.panelClose()
        d2 = self.run_export("bilingual")
        self.assertEqual(d2["file"], "Knights 2740-2759 ru+en (2).epub")
        self.assertEqual(self.out_files(), ["Knights 2740-2759 ru+en (2).epub", "Knights 2740-2759 ru+en.epub"])
        vm.panelClose()

    def test_several_pieces_go_into_one_file_named_by_its_ranges(self):
        vm = self.vm
        self.press("2650-2699")
        data = self.run_export("single")
        self.assertEqual(data["file"], "Knights 2650-2699, 2740-2759 ru.epub")
        self.assertTrue(data["facts"].startswith("70 chapters"))
        vm.panelClose()

    def test_the_choice_is_taken_at_the_press(self):
        vm = self.vm
        vm.act("single")
        self.assertEqual(vm.busy, "single")
        self.assertEqual([(s["text"], s["kind"], s["busy"]) for s in vm.bar],
                         [("Exporting…", "off", True), ("Russian + English", "off", False)])
        vm.act("bilingual")                                           # a click during the export changes nothing
        vm.headBox()                                                  # the choice may change; the running build keeps its own
        self.assertTrue(pump(lambda: vm.panel != ""))
        self.assertEqual(vm.panelData["file"], "Knights 2740-2759 ru.epub")
        vm.panelClose()

    def test_it_works_during_a_run(self):
        run = self.begin(range(pos(2760), pos(2780)))
        self.settle()
        self.assertTrue(vm_running(self.vm))
        data = self.run_export("single")
        self.assertEqual(data["title"], "Exported")
        self.assertEqual(self.vm.panel, "ok")
        self.rc.run = None
        del run

    def begin(self, positions):
        from novelgui.ctl import runcontrol
        rc = self.rc
        run = runcontrol.Run("job", str(self.path), "Knights", "Book 1", list(positions), False, rc.clock)
        rc._prepare_chap(run)
        rc.run = run
        rc.last_series = str(self.path)
        rc.sched.user_started()
        rc._changed()
        self.tr.runs_changed(starting=True)
        return run


def vm_running(vm):
    return vm.running


class PartFile(Base):
    """The `.part` rule, in this process (the helper runs the same function): the file is written as `<name>.part` and renamed."""

    def test_the_replace_path_is_taken_with_a_part_file_that_is_gone_afterwards(self):
        from novelgui import atomic
        seen = []
        real = atomic.replace

        def watch(src, dst, *a, **kw):
            seen.append((Path(src).name, Path(dst).name, Path(src).exists()))
            return real(src, dst, *a, **kw)

        self.vm.crunch = None                                         # the lane runs the same facade function in this process
        with mock.patch.object(atomic, "replace", watch):
            data = self.run_export("single")
        self.assertEqual(data["file"], "Knights 2740-2759 ru.epub")
        self.assertIn(("Knights 2740-2759 ru.epub.part", "Knights 2740-2759 ru.epub", True), seen)
        self.assertEqual(self.out_files(), ["Knights 2740-2759 ru.epub"])
        self.vm.panelClose()


class Failure(Base):
    def test_a_failed_export_says_why_leaves_no_file_and_try_again_works(self):
        from novelgui.facade import books as fbooks
        import errno
        vm = self.vm
        real = fbooks.export_piece_task

        def full(ctx, *a, **kw):
            raise OSError(errno.ENOSPC, "No space left on device")

        vm.crunch = None
        with mock.patch.object(fbooks, "export_piece_task", full):
            data = self.run_export("single")
            self.assertEqual((vm.panel, data["title"], data["file"]), ("error", "Export failed", "Nothing written"))
            self.assertEqual(data["facts"], "The disk is full. Free some space, then try again.")
            self.assertEqual(vm.busy, "")
        self.assertEqual(self.out_files(), [])
        with mock.patch.object(fbooks, "export_piece_task", real):
            vm.panelOk()                                              # Try again: the same choice, the same name
            self.assertTrue(pump(lambda: vm.panel == "ok"))
        self.assertEqual(vm.panelData["file"], "Knights 2740-2759 ru.epub")
        self.assertEqual(self.out_files(), ["Knights 2740-2759 ru.epub"])
        vm.panelClose()

    def test_a_dead_helper_is_a_plain_message(self):
        vm = self.vm
        data = None
        vm.act("single")
        self.assertTrue(pump(lambda: vm._token is not None))
        vm.crunch._proc.kill()                                        # nothing but the helper dying under the export
        self.assertTrue(pump(lambda: vm.panel != "", 30))
        data = vm.panelData
        self.assertEqual(vm.panel, "error")
        self.assertEqual(data["facts"], "The export stopped unexpectedly. Try again.")
        self.assertEqual(self.out_files(), [])
        vm.panelOk()
        self.assertTrue(pump(lambda: vm.panel == "ok", 30))
        vm.panelClose()


class Cancel(Base):
    def test_cancel_kills_the_build_sweeps_the_leftovers_and_the_next_export_works(self):
        vm = self.vm
        out = self.path / "out"
        out.mkdir(exist_ok=True)
        vm.act("single")
        self.assertTrue(pump(lambda: vm._token is not None))
        (out / "Knights 2740-2759 ru.epub.part").write_bytes(b"half")            # what a killed build leaves behind
        (out / "Knights 2740-2759 ru.epub.x1.part").write_bytes(b"half")
        vm.cancelExport()
        self.assertEqual(vm.busy, "")
        self.assertTrue(pump(lambda: not list(out.glob("*.part")) and self.parts.lanes.idle(), 10), "the leftovers were swept")
        pump(lambda: False, 0.5)
        self.assertEqual(self.out_files(), [], "a cancelled export leaves no file")
        self.assertEqual(vm.panel, "", "and says nothing")
        self.assertEqual([s["kind"] for s in vm.bar], ["", ""])
        data = self.run_export("single")                              # the helper starts again for the next use
        self.assertEqual(data["title"], "Exported")
        vm.panelClose()

    def test_another_book_cancels_the_running_export(self):
        vm = self.vm
        vm.act("single")
        self.assertTrue(pump(lambda: vm._token is not None))
        vm._reset_series()
        self.assertEqual(vm.busy, "")
        pump(lambda: False, 0.5)
        self.assertEqual(self.out_files(), [])


class Protected(Base):
    def test_another_tasks_cancel_never_kills_a_build_in_flight(self):
        vm, crunch = self.vm, self.vm.crunch
        crunch.submit("ping", {"wait": 0.8}, group="other")
        self.assertTrue(pump(lambda: crunch.child_pid > 0))
        vm.act("single")
        self.assertTrue(pump(lambda: vm._token is not None))
        starts = crunch.starts
        crunch.submit("ping", {}, group="other")                     # supersedes the first: normally the helper is killed and restarted
        pump(lambda: False, 0.3)
        self.assertEqual(crunch.starts, starts, "the helper was not killed while the export was in flight")
        self.assertTrue(pump(lambda: vm.panel == "ok", 30))
        self.assertEqual(self.out_files(), ["Knights 2740-2759 ru.epub"], "written once")
        vm.panelClose()


class OnceOnly(Base):
    def test_a_task_submitted_to_a_cold_helper_is_sent_once(self):
        vm = self.vm
        sent = []
        real = vm.crunch._send
        vm.crunch._send = lambda t: (sent.append(t.task), real(t))[1]      # the helper starts inside submit: `started` may fire at once
        self.parts.crunch.release()
        data = self.run_export("single")
        self.assertEqual(sent.count("export"), 1)
        self.assertEqual(self.out_files(), [data["file"]], "one build, one file")
        vm.panelClose()


class LiveRun(Base):
    specs = [demo.knights(done=[[2650, 2689]])]
    exports = [["Knights", "Book 1", 2650, 2679, "2026-11-12", es.A]]

    def begin(self, a, b):
        from novelgui.ctl import runcontrol
        rc = self.rc
        run = runcontrol.Run("job", str(self.path), "Knights", "Book 1", list(range(pos(a), pos(b) + 1)), False, rc.clock)
        rc._prepare_chap(run)
        rc.run = run
        rc.last_series = str(self.path)
        rc.sched.user_started()
        rc._changed()
        self.tr.runs_changed(starting=True)
        self.settle()
        return run

    def progress(self, run, number, done, total=3):
        run.events.feed(("progress", {"index": pos(number), "done": done, "total": total, "failed": 0}))
        self.rc._flush_progress()
        pump(lambda: False, 0.25)

    def test_the_jobs_remaining_chapters_are_one_row_and_done_ones_join_the_piece_above(self):
        vm = self.vm
        self.assertEqual(self.labels(), ["2650-2679", "2680-2689", "2690-2819"])
        run = self.begin(2690, 2719)
        self.assertEqual(self.labels(), ["2650-2679", "2680-2689", "2690-2719", "2720-2819"])
        rows = vm.rows.rows
        self.assertEqual((rows[2][0], rows[2][3], rows[2][4], rows[2][5]), ("run", "Translating", "wave", "none"))
        self.assertEqual((rows[3][3], rows[3][4]), ("Translate ›", "go"))
        self.assertTrue(vm.running)
        for n in range(2690, 2695):
            self.progress(run, n, 3)
        self.assertEqual(self.labels(), ["2650-2679", "2680-2694", "2695-2719", "2720-2819"], "the piece grows live")
        self.progress(run, 2695, 1)
        tip = vm.markTip(2)
        self.assertEqual(tip[0], "Chapter 2695 is being written · 33 %.")
        self.assertEqual(tip[1][0][0], "Done")
        self.progress(run, 2695, 3)
        self.assertEqual(vm.markTip(2)[0], "Chapter 2696 is being written · 0 %.")
        self.assertEqual(vm.rows.rows[1][3], "", "the new piece has no mark")
        self.assertEqual(vm.ticked, 16, "the default choice follows the piece while it is untouched")
        self.rc.run = None
        self.tr.runs_changed(ended=run)
        self.settle()

    def test_a_chapter_the_job_cannot_finish_is_a_problem_at_once(self):
        vm = self.vm
        run = self.begin(2690, 2699)
        run.events.feed(("progress", {"index": pos(2690), "done": 1, "total": 3, "failed": 1}))
        self.rc._flush_progress()
        pump(lambda: False, 0.25)
        self.assertEqual([r[3] for r in vm.rows.rows if r[4] == "problem"], ["1 problem"])
        self.rc.run = None
        self.tr.runs_changed(ended=run)

    def test_the_header_word_export_glows_when_the_chosen_chapters_are_done(self):
        self.assertEqual(self.app.exportState, "")
        self.assertTrue(self.books.commitRange("2685-2692"))
        self.settle()
        self.assertEqual(self.app.exportState, "")
        run = self.begin(2690, 2692)
        for n in (2690, 2691):
            self.progress(run, n, 3)
        self.assertEqual(self.app.exportState, "")
        self.progress(run, 2692, 3)
        self.assertEqual(self.app.exportState, "ready", "ready from the run's own counts, before the books are read again")
        self.assertTrue(self.books.commitRange("2685-2700"))
        self.assertTrue(pump(lambda: self.app.exportState == ""))
        self.rc.run = None


class Glow(Base):
    specs = [demo.knights(translated=170)]
    exports = ()
    select = "2703-2750"

    def test_ready_while_the_selection_is_translated_and_not_otherwise(self):
        self.assertEqual(self.app.exportState, "ready")
        self.assertEqual(self.app.tips["exportReady"][0], "The chosen chapters are translated: ready to export.")
        self.books.clearSelection()
        self.assertTrue(pump(lambda: self.app.exportState == ""))


class Glow2(Base):
    specs = [demo.knights(translated=20)]
    exports = ()
    select = "2703-2750"

    def test_not_ready_while_a_chosen_chapter_is_not_translated(self):
        self.assertEqual(self.app.exportState, "")


class OtherBook(Base):
    def test_the_choice_resets_with_the_book_and_the_screen_follows_books(self):
        vm = self.vm
        self.press("2650-2699")
        self.assertTrue(vm._touched)
        vm._reset_series()
        self.assertEqual((vm.ticked, vm._touched), (0, False))


class Terms(Base):
    specs = [demo.knights(done=es.DONE, blocked=[2703])]
    select = "2703-2750"

    def test_terms_pulses_red_in_the_header_while_export_is_unaffected(self):
        self.settle()
        self.assertTrue(pump(lambda: self.app.termsState == "red", 10), "the first chapter of the selection waits for terms")
        self.assertEqual([s["kind"] for s in self.vm.bar], ["", ""], "export is not affected")


if __name__ == "__main__":
    unittest.main()
