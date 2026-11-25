"""The Export screen as scenarios (tests/qmlharness.py, offscreen + software): every state of the accepted mock-up (full/export.js: pieces merge
apart open problem running exporting ok error blocked none) and its panels (the result, the error, no file) at 100 % and 150 %, a few at
the narrow 820 x 600, plus the clicks (a row, the head box, `▸`, the From - To fields, `Translate ›`, `1 problem`, Close, Esc) and the header
glow. A real library with real EPUBs, a real export history and a real helper process behind the real view-models; a run is fed the events a
runner sends. Asserts by objectName, red only where window_spec 7.16 says, at most one ambient animation, no QML warning; shots go to
NOVELGUI_SHOTS (default: the temp dir)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import exportscenes as es  # noqa: E402
from tests import qmlharness as qh  # noqa: E402
from tests import translatedemo as demo  # noqa: E402
from tests.translatescenes import SHORT, WAIT, call, click, py  # noqa: E402

RUN = qh.have_qt()
VM = "tests.shellfactory:make"
SCALES = (1.0, 1.5)
NARROW = (820, 600)
RED = "#e5383b"
BRIGHT, TEXT, DIM, FAINT = "#f4f4f4", "#dedede", "#8a8a8a", "#5a5a5a"


def state(r, k=-1):
    """The `ex_state` the scene read last (or the k-th)."""
    got = [v for n, v in r.events if n == "ex_state"]
    return got[k]


def marks(r):
    """{row: (text, colour)} of the marks that are shown."""
    out, i = {}, 0
    while r.has("exMark%d" % i):
        m = r.item("exMark%d" % i)
        if m["visible"] and m["text"]:
            out[i] = (m["text"], m["color"])
        i += 1
    return out


def ranges(r):
    out, i = [], 0
    while r.has("exRange%d" % i):
        out.append((r.item("exRange%d" % i)["text"], r.item("exRange%d" % i)["color"]) if r.item("exRange%d" % i)["visible"] else None)
        i += 1
    return out


def bar(r):
    out, k = [], 0
    while r.has("exBarText%d" % k):
        out.append((r.item("exBarText%d" % k)["text"], r.item("exBarText%d" % k)["color"]))
        k += 1
    return out if r.item("exBar")["visible"] else []


def summary(r):
    if not r.item("exSummary")["visible"]:
        return ""
    return r.item("exSummaryCount")["text"] + r.item("exSummaryRanges")["text"]


def rows(r):
    return r.item("exList")["count"]


def st():
    return py("ex_state")


@unittest.skipUnless(RUN, "PySide6 is not available")
class Scenes(unittest.TestCase):
    def go(self, name, scales=SCALES, size=(1040, 720), tag=None, actions=None, data_=None):
        d, a = es.SCENES[name]
        tag = tag or name + ("_narrow" if size == NARROW else "")
        return [qh.scenario("ShellScene", data_ or d, scale=k, vm=VM, actions=(actions if actions is not None else a), tag="export_" + tag,
                            size=size, timeout=150) for k in scales]

    def narrow(self, name):
        return self.go(name, scales=(1.0,), size=NARROW)

    def only_red(self, r, *inside, maybe=()):
        img = r.image()
        total = qh.count_red(img)
        if not inside and not maybe:
            self.assertEqual(total, 0, "no red in this state")
            return
        got = [qh.count_red(img, self.grown(r.rect(n))) for n in inside]
        for n, c in zip(inside, got):
            self.assertGreater(c, 8, "the red thing is drawn: %s" % n)
        more = [qh.count_red(img, self.grown(r.rect(n))) for n in maybe]
        self.assertEqual(sum(got) + sum(more), total, "red only inside %s" % ", ".join(inside + tuple(maybe)))

    @staticmethod
    def grown(rect, by=3):
        x, y, w, h = rect
        return (x - by, y - by, w + 2 * by, h + 2 * by)

    # ------------------------------------------------------------------------------------------------ the quiet states
    def test_pieces(self):
        for r in self.go("pieces"):
            self.assertEqual(rows(r), 5)
            self.assertEqual(ranges(r), [("2650-2699", DIM), ("2700-2709", FAINT), ("2710-2739", DIM), ("2740-2759", BRIGHT),
                                         ("2760-2819", FAINT)])
            self.assertEqual(marks(r), {0: ("exported", DIM), 1: ("Translate ›", TEXT), 2: ("exported", DIM), 4: ("Translate ›", TEXT)})
            self.assertEqual(r.item("exHeadBox")["visible"], True)
            self.assertEqual(summary(r), "20 chapters · 2740-2759")
            self.assertEqual(r.item("exSummaryCount")["color"], TEXT)
            self.assertEqual(r.item("exSummaryRanges")["color"], DIM)
            self.assertEqual(bar(r), [("Export Russian", DIM), ("Russian + English", DIM)])
            self.assertEqual(r.item("exBarText0")["w"] > 0 and r.item("exBarCapsule")["w"] > 300, True)
            self.assertEqual(r.item("step_export")["kind"], "", "nothing was chosen on Books")
            self.assertEqual(r.item("exSkeleton")["visible"], False)
            self.only_red(r)
            self.assertEqual(r.ambient, 0)
        self.narrow("pieces")

    def test_two_pieces_merged_and_apart(self):
        for r in self.go("merge"):
            self.assertEqual(summary(r), "50 chapters · 2710-2759")
            self.assertEqual([x[1] for x in ranges(r)[2:4]], [BRIGHT, BRIGHT])
            self.assertFalse(r.item("exHatch1")["visible"] if r.has("exHatch1") else False)
            self.only_red(r)
        for r in self.go("apart"):
            self.assertEqual(summary(r), "70 chapters · 2650-2699, 2740-2759")
            self.assertTrue(r.item("exHatch1")["visible"], "the gap between two ticked pieces is hatched")
            self.assertTrue(r.item("exHatch2")["visible"], "and so is the piece between them that is not in the file")
            self.assertFalse(r.item("exHatch0")["visible"])
            self.assertFalse(r.item("exHatch3")["visible"])
            self.assertEqual(ranges(r)[0], ("2650-2699", BRIGHT))
            self.only_red(r)
        self.narrow("apart")

    def test_an_opened_piece_has_two_fields_and_chapter_rows_with_boxes(self):
        for r in self.go("open"):
            self.assertTrue(r.item("exFrom3")["visible"] and r.item("exTo3")["visible"])
            self.assertEqual((r.item("exFrom3Input")["text"], r.item("exTo3Input")["text"]), ("2740", "2745"))
            self.assertEqual(marks(r)[3], ("6 of 20", BRIGHT))
            self.assertEqual(summary(r), "6 chapters · 2740-2745")
            self.assertEqual(r.item("exTw3")["text"], "▾")
            self.assertEqual(r.item("exRange4")["text"], "2740")
            self.assertEqual(r.item("exRange4")["color"], BRIGHT)
            self.assertEqual(r.item("exRange10")["color"], TEXT, "a chapter that is not ticked is normal")
            self.assertEqual(r.item("exTitle4")["text"], "Chapter 2740 - The Gate")
            self.assertEqual(r.item("exTitle4")["color"], DIM)
            self.only_red(r)
        self.narrow("open")

    def test_a_failed_chapter_is_a_red_link_and_not_in_the_file(self):
        for r in self.go("problem"):
            self.assertEqual(marks(r)[0], ("1 problem", RED))
            self.assertEqual(summary(r), "109 chapters · 2650-2759")
            self.assertEqual(ranges(r)[0], ("2650-2759", BRIGHT))
            self.only_red(r, "exMark0")
        self.narrow("problem")

    def test_the_running_job_is_one_row_and_its_done_chapters_join_the_piece(self):
        for r in self.go("running"):
            self.assertEqual(ranges(r)[:4], [("2650-2679", DIM), ("2680-2699", BRIGHT), ("2700-2719", FAINT), ("2720-2819", FAINT)])
            self.assertEqual(marks(r)[2], ("Translating", DIM))
            self.assertEqual(marks(r)[3], ("Translate ›", TEXT))
            self.assertFalse(r.item("exBox2")["visible"], "the job's row has no box")
            self.assertEqual(r.item("step_translate")["kind"], "wave")
            self.assertEqual(r.ambient, 1, "the header word is the one ambient animation: the row word stands still")
            self.only_red(r)
        self.narrow("running")

    def test_exporting_shows_progress_on_the_pressed_button(self):
        for r in self.go("exporting"):
            self.assertEqual(bar(r), [("Exporting…", FAINT), ("Russian + English", FAINT)])
            self.assertTrue(r.item("exBarSpin0")["visible"])
            self.assertFalse(r.item("exBarSpin1")["visible"])
            self.assertEqual(r.ambient, 1)
            self.only_red(r)

    def test_nothing_translated_is_one_gap_row_and_dim_buttons(self):
        for r in self.go("none"):
            self.assertEqual(rows(r), 1)
            self.assertEqual(marks(r), {0: ("Translate ›", TEXT)})
            self.assertEqual(ranges(r), [("2650-2819", FAINT)])
            self.assertFalse(r.item("exBox0")["visible"])
            self.assertEqual(bar(r), [("Export Russian", FAINT), ("Russian + English", FAINT)])
            self.assertEqual(summary(r), "")
            self.only_red(r)
        self.narrow("none")

    def test_no_language_the_buttons_are_dim(self):
        for r in self.go("nolang"):
            self.assertEqual(bar(r), [("Export", FAINT), ("+ English", FAINT)])
            self.only_red(r)

    def test_terms_red_in_the_header_does_not_touch_export(self):
        for r in self.go("blocked"):
            self.assertEqual(r.item("step_terms")["kind"], "red")
            self.assertEqual(bar(r), [("Export Russian", DIM), ("Russian + English", DIM)])
            self.only_red(r, maybe=("step_terms",))

    def test_export_glows_once_and_stays_bright_when_the_chosen_chapters_are_translated(self):
        for r in self.go("ready"):
            self.assertEqual(r.item("step_export")["kind"], "ready")
            self.assertEqual(r.item("step_export")["visible"], True)
            self.only_red(r)

    # ------------------------------------------------------------------------------------------------ panels
    def test_the_result_panel(self):
        for r in self.go("ok"):
            self.assertTrue(r.item("exCard")["visible"])
            self.assertEqual(r.item("exportPanelTitle")["text"], "Exported")
            self.assertEqual(r.item("exFile")["text"], "Knights 2740-2759 ru.epub")
            self.assertEqual(r.item("exFile")["color"], BRIGHT, "the user's data is bright")
            self.assertTrue(r.item("exFacts")["text"].startswith("20 chapters · "))
            self.assertEqual(r.item("exFacts")["color"], DIM)
            self.assertEqual((r.item("exClose")["text"], r.item("exAction")["text"]), ("Close", "Show in folder"))
            self.assertTrue(r.item("exClose")["x"] < r.item("exAction")["x"], "the closing button left, the action right")
            self.assertFalse(r.item("exLeft")["visible"])
            self.only_red(r)
        for r in self.go("okboth"):
            self.assertEqual(r.item("exFile")["text"], "Knights 2740-2759 ru+en.epub")
        self.narrow("ok")

    def test_the_error_panel(self):
        for r in self.go("error"):
            self.assertEqual(r.item("exportPanelTitle")["text"], "Export failed")
            self.assertEqual(r.item("exFile")["text"], "Nothing written")
            self.assertEqual(r.item("exFacts")["text"], "The disk is full. Free some space, then try again.")
            self.assertEqual((r.item("exClose")["text"], r.item("exAction")["text"]), ("Close", "Try again"))
            self.only_red(r)
        self.narrow("error")

    def test_no_file_written_has_only_close(self):
        for r in self.go("nothing"):
            self.assertEqual(r.item("exportPanelTitle")["text"], "No file was written")
            self.assertEqual(r.item("exFacts")["text"], "No chosen chapter is fully translated yet.")
            self.assertFalse(r.item("exAction")["visible"])
            self.assertEqual(r.item("exClose")["text"], "Close")
            self.assertFalse(r.item("exFile")["visible"])
            self.only_red(r)

    # ------------------------------------------------------------------------------------------------ clicks
    def test_a_click_on_a_row_toggles_it_and_ctrl_shift_work(self):
        acts = es.base(click("exRange0"), st(), {"op": "click", "name": "exRange2", "mod": "ctrl"}, st(),
                       {"op": "click", "name": "exRange0", "mod": "shift"}, st())
        r = self.go("pieces", scales=(1.0,), actions=acts, tag="click")[0]
        first, second, third = [v for n, v in r.events if n == "ex_state"]
        self.assertEqual(first["ticked"], list(range(2650, 2700)) + list(range(2740, 2760)))
        self.assertEqual(second["ticked"], list(range(2650, 2700)) + list(range(2710, 2760)))
        self.assertEqual(third["ticked"], second["ticked"], "Shift from the last click on the same row changes nothing more")
        self.assertEqual(third["selection"], [], "Books keeps its own selection")

    def test_the_head_box_and_the_arrow(self):
        acts = es.base(click("exHeadBox"), st(), click("exTw3"), st(), click("exHeadBox"), st(), click("exHeadBox"), st())
        r = self.go("pieces", scales=(1.0,), actions=acts, tag="head")[0]
        s1, s2, s3, s4 = [v for n, v in r.events if n == "ex_state"]
        self.assertEqual((s1["head"], len(s1["ticked"])), ("all", 100))
        self.assertEqual(s3["head"], "none")
        self.assertEqual(s4["head"], "all")
        self.assertTrue(r.item("exFrom3")["visible"], "the arrow opened the piece without toggling it")
        self.assertEqual(len(s2["ticked"]), 100)

    def test_a_part_of_an_opened_piece_can_be_typed_and_a_wrong_number_goes_back(self):
        acts = es.base(py("ex_open", "2740-2759"), click("exFrom3Input"), {"op": "type", "text": "2750"}, {"op": "key", "key": "Return"},
                       SHORT, st(), click("exTo3Input"), {"op": "type", "text": "9"}, {"op": "key", "key": "Return"}, SHORT, st())
        r = self.go("pieces", scales=(1.0,), actions=acts, tag="fields")[0]
        s1, s2 = [v for n, v in r.events if n == "ex_state"]
        self.assertEqual(s1["ticked"], list(range(2750, 2760)), "From 2750 keeps the end of the piece")
        self.assertEqual(s2["ticked"], s1["ticked"], "a number outside the piece is refused and the field goes back")
        self.assertEqual(r.item("exTo3Input")["text"], "2759")

    def test_translate_gap_row_selects_the_chapters_in_books_and_opens_translate(self):
        r = self.go("pieces", scales=(1.0,), actions=es.base(click("exMark1"), SHORT, st()), tag="gap")[0]
        s = state(r)
        self.assertEqual(s["screen"], "translate")
        self.assertEqual(s["selection"], list(range(demo.position(2700), demo.position(2709) + 1)))
        self.assertTrue(r.item("screen_translate")["visible"])

    def test_one_problem_opens_the_problems_of_translate_at_the_chapter(self):
        r = self.go("problem", scales=(1.0,), actions=es.base(click("exMark0"), SHORT, SHORT, st()), tag="problemclick")[0]
        s = state(r)
        self.assertEqual((s["screen"], s["tab"], s["problem_cursor"]), ("translate", "problems", 0))
        self.assertTrue(r.item("trProblemsTab")["visible"])

    def test_exported_shows_the_file_in_its_folder_and_changes_nothing_else(self):
        r = self.go("pieces", scales=(1.0,), actions=es.base(click("exMark0"), st()), tag="exportedclick")[0]
        self.assertEqual(state(r)["screen"], "export")

    def test_close_gives_the_exported_rows_their_mark(self):
        acts = es.base(call("exportVm", "act", "single"), WAIT, WAIT, st(), click("exClose"), SHORT, py("ex_rows"), st())
        r = self.go("pieces", scales=(1.0,), actions=acts, tag="close")[0]
        s_open, s_closed = [v for n, v in r.events if n == "ex_state"]
        self.assertEqual(s_open["panel"], "ok")
        self.assertEqual(s_closed["panel"], "")
        self.assertEqual(s_closed["appPanel"], "")
        self.assertEqual(marks(r)[3], ("exported", DIM))
        self.assertFalse(r.item("exCard")["visible"])
        self.assertEqual(r.item("exBarText0")["text"], "Export Russian")

    def test_a_real_export_through_the_helper_writes_the_file_and_leaves_no_part(self):
        acts = es.base(call("exportVm", "act", "single"), WAIT, WAIT, py("ex_out_files"), call("exportVm", "panelClose"), SHORT, py("ex_history"))
        r = self.go("pieces", scales=(1.0,), actions=acts, tag="real")[0]
        files = [v for n, v in r.events if n == "ex_out_files"][0]
        self.assertEqual(files, ["Knights 2740-2759 ru.epub"])
        hist = [v for n, v in r.events if n == "ex_history"][0]
        self.assertEqual(hist[str(demo.position(2750))][1], "Knights 2740-2759 ru.epub")

    def test_escape_stops_an_export(self):
        acts = es.base(py("ex_hold_busy", "single"), {"op": "key", "key": "Escape"}, SHORT, st())
        r = self.go("pieces", scales=(1.0,), actions=acts, tag="escape")[0]
        self.assertEqual(state(r)["busy"], "")
        self.assertEqual(bar(r), [("Export Russian", DIM), ("Russian + English", DIM)])

    def test_the_keyboard_moves_and_ticks(self):
        acts = es.base(click("exRange1"), {"op": "key", "key": "Down"}, {"op": "key", "key": "Space"}, st())
        r = self.go("pieces", scales=(1.0,), actions=acts, tag="keys")[0]
        self.assertEqual(state(r)["ticked"], list(range(2710, 2760)), "Down to the third row, Space ticks it")

    def test_the_glow_follows_the_choice_on_books(self):
        acts = [WAIT, WAIT, call("booksVm", "clearSelection"), WAIT, st()]
        r = self.go("ready", scales=(1.0,), actions=acts, tag="glowoff")[0]
        self.assertEqual(r.item("step_export")["kind"], "")
        self.assertEqual(state(r)["exportState"], "")


if __name__ == "__main__":
    unittest.main()
