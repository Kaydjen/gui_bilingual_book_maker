"""Pure logic of the Export screen (ctl/exportrows.py, window_spec 8.1-8.7, 14.14): the pieces and the gap rows, the marks by priority,
the boxes, choosing, the ranges of a choice, the file name and the bar, the result texts. No Qt."""

import errno
import unittest
from types import SimpleNamespace

from novelgui.ctl import exportrows as er


def info(i, kind="none", title=None, toc=False, number="auto"):
    """A chapter as the scan leaves it: kind = translated | failed | none | partly."""
    t = "Chapter %d" % (i + 100) if title is None else title
    num = i + 100 if number == "auto" else number
    return SimpleNamespace(index=i, is_toc=toc, title=t, number=num, blocks=3, state=SimpleNamespace(kind="toc" if toc else kind))


def book(spec):
    """`spec` = a string of kinds, one letter per chapter: T translated, F failed, . not translated, C contents page."""
    names = {"T": "translated", "F": "failed", ".": "none", "p": "partly", "C": "toc"}
    return [info(i, names[c], toc=(c == "C"), number=None if c == "C" else "auto") for i, c in enumerate(spec)]


def build(spec, history=None, ticks=(), opened=(), live=None):
    infos = book(spec)
    kl = er.kinds(infos, live)
    nums = er.numbers(infos)
    gs = er.groups(kl, history or {})
    rows, refs = er.rows_of(gs, kl, nums, [i.title or "" for i in infos], set(ticks), set(opened))
    return infos, kl, nums, gs, rows, refs


class PiecesTest(unittest.TestCase):
    def test_consecutive_translated_chapters_are_one_piece_in_any_order(self):
        _i, _k, nums, gs, rows, _r = build("TTTT")
        self.assertEqual([(g.kind, g.first, g.last) for g in gs], [("piece", 0, 3)])
        self.assertEqual(rows[0][1], "100-103")

    def test_two_rows_only_with_untranslated_chapters_between(self):
        _i, _k, _n, gs, rows, _r = build("TT..TT")
        self.assertEqual([(g.kind, g.first, g.last) for g in gs], [("piece", 0, 1), ("gap", 2, 3), ("piece", 4, 5)])
        self.assertEqual([r[1] for r in rows], ["100-101", "102-103", "104-105"])

    def test_contents_pages_are_skipped_not_a_break(self):
        _i, _k, _n, gs, rows, _r = build("TCT")
        self.assertEqual([(g.kind, g.first, g.last, g.oks) for g in gs], [("piece", 0, 2, (0, 2))])
        _i, _k, _n, gs, _rows, _r = build("C..CT")
        self.assertEqual([(g.kind, g.first, g.last) for g in gs], [("gap", 1, 2), ("piece", 4, 4)])

    def test_a_failed_chapter_stays_in_its_piece_and_is_not_ticked(self):
        _i, _k, _n, gs, rows, _r = build("TTFTT")
        self.assertEqual(len(gs), 1)
        g = gs[0]
        self.assertEqual((g.oks, g.fails), ((0, 1, 3, 4), (2,)))
        self.assertEqual(rows[0][3:5], ("1 problem", "problem"))

    def test_a_run_of_failed_chapters_only_is_a_gap_row_with_the_problem_link(self):
        _i, _k, _n, gs, rows, _r = build("FF.")
        self.assertEqual([g.kind for g in gs], ["gap", "gap"])
        self.assertEqual(rows[0][3:6], ("2 problems", "problem", "none"))

    def test_the_export_history_splits_a_piece_into_rows(self):
        hist = {0: ("2026-11-03", "a.epub"), 1: ("2026-11-03", "a.epub"), 2: ("2026-11-12", "b.epub")}
        _i, _k, _n, gs, rows, _r = build("TTTTT", hist)
        self.assertEqual([(g.first, g.last, g.stamp and g.stamp[1]) for g in gs], [(0, 1, "a.epub"), (2, 2, "b.epub"), (3, 4, None)])
        self.assertEqual([r[3] for r in rows], ["exported", "exported", ""])
        self.assertEqual(rows[2][6], "", "a never exported piece is bright only when ticked")
        self.assertIn("old", rows[0][6].split(","))

    def test_a_failed_chapter_between_two_exports_joins_the_earlier_one(self):
        hist = {0: ("d", "a"), 2: ("e", "b")}
        _i, _k, _n, gs, _rows, _r = build("TFT", hist)
        self.assertEqual([(g.first, g.last, g.fails) for g in gs], [(0, 1, (1,)), (2, 2, ())])

    def test_the_running_jobs_chapters_are_one_row_and_finished_ones_join_the_piece(self):
        live = {3: (3, 3, 0), 4: (1, 3, 0), 5: (0, 3, 0)}
        _i, kl, _n, gs, rows, _r = build("TTT...", live=live)
        self.assertEqual(kl, ["ok", "ok", "ok", "ok", "run", "run"])
        self.assertEqual([(g.kind, g.first, g.last) for g in gs], [("piece", 0, 3), ("run", 4, 5)])
        self.assertEqual(rows[1][3:5], ("Translating", "wave"))
        self.assertEqual(rows[1][5], "none")

    def test_a_failed_block_of_the_run_makes_a_problem_at_once(self):
        _i, kl, _n, _gs, _rows, _r = build("T..", live={1: (1, 3, 1), 2: (0, 3, 0)})
        self.assertEqual(kl, ["ok", "fail", "run"])

    def test_an_unfinished_chapter_outside_the_run_is_a_gap(self):
        _i, kl, _n, _gs, _rows, _r = build("Tp.", live={2: (0, 3, 0)})
        self.assertEqual(kl, ["ok", "gap", "run"])

    def test_numbers_follow_the_titles_else_the_position(self):
        infos = [info(0, "translated", title="Prologue", number=None), info(1, "translated", title="Chapter 7", number=7)]
        self.assertEqual(er.numbers(infos), [1, 7])


class MarksAndBoxesTest(unittest.TestCase):
    def test_the_mark_priority(self):
        hist = {0: ("d", "f")}
        _i, _k, _n, gs, rows, _r = build("TFT", hist, ticks={0})
        self.assertEqual(rows[0][4], "problem", "problem beats part and exported")
        _i, _k, _n, gs, rows, _r = build("TTT", {0: ("d", "f"), 1: ("d", "f"), 2: ("d", "f")}, ticks={0})
        self.assertEqual(rows[0][3:5], ("1 of 3", "part"), "partly ticked beats exported")
        _i, _k, _n, gs, rows, _r = build("TTT", {0: ("d", "f"), 1: ("d", "f"), 2: ("d", "f")})
        self.assertEqual(rows[0][3:5], ("exported", "exported"))
        _i, _k, _n, gs, rows, _r = build("T.")
        self.assertEqual(rows[1][3:5], ("Translate ›", "go"))

    def test_thousands_of_chapters_read_with_a_space(self):
        self.assertEqual(er.sp(2749), "2 749")
        self.assertEqual(er.plural(1, "problem", "problems"), "1 problem")

    def test_boxes(self):
        _i, _k, _n, gs, rows, _r = build("TT.", ticks=set())
        self.assertEqual([r[5] for r in rows], ["empty", "none"])
        _i, _k, _n, gs, rows, _r = build("TT.", ticks={0})
        self.assertEqual(rows[0][5], "part")
        _i, _k, _n, gs, rows, _r = build("TT.", ticks={0, 1})
        self.assertEqual(rows[0][5], "on")

    def test_gap_rows_are_faint_and_a_row_between_two_ticked_pieces_is_hatched(self):
        _i, _k, _n, gs, rows, _r = build("TT.TT.TT", ticks={0, 1, 6, 7})
        self.assertEqual(rows[1][6], "faint,hatch")
        self.assertEqual(rows[2][6], "hatch", "an unticked piece between two ticked ones is hatched too")
        self.assertNotIn("hatch", rows[0][6])
        self.assertNotIn("hatch", rows[4][6])

    def test_an_opened_piece_lists_its_chapters_and_a_span_for_the_fields(self):
        _i, _k, _n, gs, rows, refs = build("TFTT.", ticks={0, 2}, opened={0})
        self.assertEqual(rows[0][6].split(","), ["sel", "open"])
        self.assertEqual(rows[0][7], "100|102", "the fields show the ticked part")
        self.assertEqual([r[0] for r in rows[1:5]], ["chapter"] * 4)
        self.assertEqual([r[5] for r in rows[1:5]], ["on", "none", "on", "empty"])
        self.assertEqual(rows[2][3:5], ("1 problem", "problem"))
        self.assertEqual(refs[:5], [0, -1, -2, -3, -4])

    def test_the_span_of_a_piece_with_nothing_ticked_is_the_whole_piece(self):
        _i, _k, nums, gs, _rows, _r = build("TTT")
        self.assertEqual(er.span_of(gs[0], set(), nums), "100|102")


class ChoosingTest(unittest.TestCase):
    def test_a_click_toggles_a_row_and_a_full_row_clears(self):
        self.assertEqual(er.toggled(set(), (1, 2, 3)), {1, 2, 3})
        self.assertEqual(er.toggled({1}, (1, 2, 3)), {1, 2, 3})
        self.assertEqual(er.toggled({1, 2, 3, 9}, (1, 2, 3)), {9})

    def test_shift_takes_every_translated_chapter_between_across_pieces(self):
        got = er.between({0}, [0, 1, 4, 5, 8], 0, 5)
        self.assertEqual(got, {0, 1, 4, 5})

    def test_the_head_box_counts_every_translated_chapter(self):
        every = [0, 1, 2]
        self.assertEqual(er.head_state(set(), every), "none")
        self.assertEqual(er.head_state({1}, every), "some")
        self.assertEqual(er.head_state({0, 1, 2}, every), "all")
        self.assertEqual(er.head_toggled(set(), every), {0, 1, 2})
        self.assertEqual(er.head_toggled({1}, every), {0, 1, 2})
        self.assertEqual(er.head_toggled({0, 1, 2}, every), set())

    def test_the_default_is_the_newest_piece_never_exported(self):
        hist = {0: ("d", "f"), 1: ("d", "f")}
        _i, _k, _n, gs, _rows, _r = build("TT..TT..TT", {0: hist[0], 1: hist[1], 8: ("e", "g"), 9: ("e", "g")})
        self.assertEqual(er.default_ticks(gs), {4, 5})
        _i, _k, _n, gs, _rows, _r = build("TT", {0: hist[0], 1: hist[1]})
        self.assertEqual(er.default_ticks(gs), set())
        _i, _k, _n, gs, _rows, _r = build("...")
        self.assertEqual(er.default_ticks(gs), set())

    def test_ranges_merge_across_contents_pages_and_failed_chapters(self):
        infos = book("TTCTFTT..T")
        kl, nums = er.kinds(infos), er.numbers(infos)
        ticks = {0, 1, 3, 5, 6, 9}
        rs = er.ranges(ticks, kl, nums)
        self.assertEqual(rs, [(100, 106), (109, 109)])
        self.assertEqual(er.range_text(rs), "100-106, 109")

    def test_the_summary(self):
        infos = book("TTT.T")
        kl, nums = er.kinds(infos), er.numbers(infos)
        self.assertEqual(er.summary(set(), kl, nums), ("", ""))
        self.assertEqual(er.summary({0, 1, 2, 4}, kl, nums), ("4 chapters", "· 100-102, 104"))
        self.assertEqual(er.summary({1}, kl, nums), ("1 chapter", "· 101"))


class NamesTest(unittest.TestCase):
    def test_file_names_list_the_ranges_and_the_language(self):
        self.assertEqual(er.file_name("Knights", [(2697, 2750)], "ru"), "Knights 2697-2750 ru.epub")
        self.assertEqual(er.file_name("Knights", [(1, 1200), (2697, 2750)], "ru"), "Knights 1-1200, 2697-2750 ru.epub")
        self.assertEqual(er.file_name("Knights", [(5, 5)], "ru", "en"), "Knights 5 ru+en.epub")

    def test_a_very_long_list_is_shortened(self):
        rs = [(i * 10, i * 10 + 1) for i in range(60)]
        name = er.file_name("Knights", rs, "ru")
        self.assertTrue(name.startswith("Knights 0-591 ru"), name)

    def test_buttons_name_the_languages(self):
        self.assertEqual(er.button_names("Russian", "English"), ("Export Russian", "Russian + English"))
        self.assertEqual(er.button_names("", "Original"), ("Export", "+ Original"))

    def test_the_bar(self):
        tips = ("one", "both")
        segs = er.segments(3, "", "Russian", "English", "", tips)
        self.assertEqual([(s["id"], s["text"], s["kind"], s["tip"]) for s in segs],
                         [("single", "Export Russian", "", "one"), ("bilingual", "Russian + English", "", "both")])
        segs = er.segments(0, "", "Russian", "English", "Tick at least one piece.", tips)
        self.assertEqual([(s["kind"], s["tip"]) for s in segs], [("off", "Tick at least one piece.")] * 2)
        segs = er.segments(3, "bilingual", "Russian", "English", "", tips)
        self.assertEqual([(s["text"], s["kind"], s["busy"]) for s in segs],
                         [("Export Russian", "off", False), ("Exporting…", "off", True)])


class ResultTest(unittest.TestCase):
    def test_the_result_line(self):
        self.assertEqual(er.result_texts(54, 900_000, 0), ("54 chapters · 0.9 MB", ""))
        self.assertEqual(er.result_texts(1, 4200, 2), ("1 chapter · 4 KB", "2 not translated yet, left out"))

    def test_errors_in_plain_words(self):
        self.assertEqual(er.error_text(OSError(errno.ENOSPC, "No space left on device")), "The disk is full. Free some space, then try again.")
        self.assertIn("cannot be written", er.error_text(PermissionError(13, "Permission denied")))
        self.assertEqual(er.error_text(RuntimeError("The helper process stopped unexpectedly (exit code 1).")), "The export stopped unexpectedly. Try again.")
        self.assertEqual(er.error_text(RuntimeError("boom\nline two")), "boom line two")


class GlowTest(unittest.TestCase):
    def test_all_translated_counts_a_chapter_the_run_has_just_finished(self):
        infos = book("T..T")
        self.assertTrue(er.all_translated(infos, [0, 3]))
        self.assertFalse(er.all_translated(infos, [0, 1]))
        self.assertFalse(er.all_translated(infos, []))
        self.assertTrue(er.all_translated(infos, [0, 1], {1: (3, 3, 0)}))
        self.assertFalse(er.all_translated(infos, [0, 1], {1: (2, 3, 0)}))
        self.assertFalse(er.all_translated(infos, [0, 1], {1: (3, 3, 1)}), "a failed block is not translated")


if __name__ == "__main__":
    unittest.main()
