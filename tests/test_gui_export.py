"""The header and the Export step's pure logic (window_spec 1.1-1.4, 8.1-8.5): pieces, number to position mapping,
file names, the context line."""
import tempfile
import unittest
from pathlib import Path

from novelgui import chapterlogic as cl, pieces


def info(i, kind="translated", title=None, blocks=10):
    """A ChapterInfo of the given state kind: translated | none | partly | failed | toc | unknown."""
    if title is None:
        title = "Chapter %d - X" % (i + 1)
    done, failed, toc = 0, 0, False
    if kind == "translated":
        done = blocks
    elif kind == "partly":
        done = blocks // 2
    elif kind == "failed":
        done, failed = blocks - 2, 2
    elif kind == "toc":
        toc = True
    if kind == "unknown":
        return cl.ChapterInfo(i, "c%d" % i, title, None, None)
    return cl.ChapterInfo(i, "c%d" % i, title, toc, blocks, (1, 1), done, failed)


def book(kinds, offset=0):
    return [info(i, k, "Chapter %d - X" % (i + 1 + offset)) for i, k in enumerate(kinds)]


class Pieces(unittest.TestCase):
    def test_two_runs_with_a_gap_are_two_pieces(self):
        ps = pieces.compute(book(["translated"] * 3 + ["none"] + ["translated"] * 2))
        self.assertEqual([(p.first, p.last, p.label) for p in ps], [(0, 2, "1-3"), (4, 5, "5-6")])

    def test_one_to_fifty_and_fifty_one_to_hundred_is_one_piece(self):
        # translated in any order: only the states matter
        ps = pieces.compute(book(["translated"] * 100))
        self.assertEqual(len(ps), 1)
        self.assertEqual((ps[0].label, ps[0].done, ps[0].total, ps[0].detail()), ("1-100", 100, 100, ""))

    def test_contents_pages_are_skipped_not_a_break(self):
        ps = pieces.compute(book(["toc", "translated", "translated", "toc", "translated", "toc"]))
        self.assertEqual([(p.first, p.last, p.done, p.total) for p in ps], [(1, 4, 3, 3)])

    def test_a_problem_inside_does_not_split_the_piece(self):
        kinds = ["translated"] * 3 + ["failed"] + ["translated"] * 50
        ps = pieces.compute(book(kinds, offset=2696))
        self.assertEqual(len(ps), 1)
        p = ps[0]
        self.assertEqual((p.done, p.total, p.problems, p.problem_at), (53, 54, 1, (3,)))
        self.assertEqual(p.detail(), "53 of 54 · 1 problem")
        self.assertEqual(p.label, "2697-2750")

    def test_problems_plural(self):
        ps = pieces.compute(book(["translated", "failed", "failed", "translated"]))
        self.assertEqual(ps[0].detail(), "2 of 4 · 2 problems")

    def test_failed_chapters_at_the_edges_are_not_in_the_piece(self):
        ps = pieces.compute(book(["failed", "translated", "translated", "failed"]))
        self.assertEqual([(p.first, p.last, p.problems) for p in ps], [(1, 2, 0)])

    def test_only_failed_chapters_make_no_piece(self):
        self.assertEqual(pieces.compute(book(["failed", "failed"])), [])

    def test_partly_unknown_and_none_break_a_run(self):
        ps = pieces.compute(book(["translated", "partly", "translated", "unknown", "translated"]))
        self.assertEqual([p.label for p in ps], ["1", "3", "5"])

    def test_the_chapter_being_written_is_left_out_and_the_piece_grows(self):
        infos = book(["translated", "translated", "partly", "none"])
        self.assertEqual(pieces.compute(infos)[0].label, "1-2")
        infos[2].done = infos[2].blocks                    # the job finished it
        self.assertEqual(pieces.compute(infos)[0].label, "1-3")

    def test_nothing_translated_is_an_empty_list(self):
        self.assertEqual(pieces.compute(book(["none"] * 5)), [])
        self.assertEqual(pieces.compute([]), [])

    def test_no_title_number_falls_back_to_the_position(self):
        infos = [info(i, "translated", "Prologue" if i == 0 else "Interlude") for i in range(3)]
        ps = pieces.compute(infos)
        self.assertEqual((ps[0].first_no, ps[0].last_no), (1, 3))

    def test_a_single_chapter_piece_label(self):
        self.assertEqual(pieces.compute(book(["none", "translated", "none"]))[0].label, "2")


class Mapping(unittest.TestCase):
    def test_title_numbers_map_to_positions(self):
        infos = book(["translated"] * 5, offset=2696)       # titles Chapter 2697 .. 2701
        self.assertEqual(pieces.positions_for(infos, 2698, 2700), ((1, 2, 3), False))

    def test_reversed_pair_is_swapped(self):
        infos = book(["translated"] * 5, offset=10)
        self.assertEqual(pieces.positions_for(infos, 14, 12)[0], (1, 2, 3))

    def test_missing_numbers_are_absent_and_toc_is_never_taken(self):
        infos = [info(0, "toc", "Contents"), info(1, "translated", "Chapter 5 - A"),
                 info(2, "translated", "Chapter 7 - B")]
        self.assertEqual(pieces.positions_for(infos, 5, 9)[0], (1, 2))

    def test_numbers_without_titles_are_positions(self):
        infos = [info(i, "translated", "Prologue") for i in range(4)]
        pos, by_position = pieces.positions_for(infos, 2, 3)
        self.assertEqual((pos, by_position), ((1, 2), True))

    def test_kept_positions_are_the_fully_translated_ones(self):
        infos = book(["translated", "failed", "partly", "translated"])
        self.assertEqual(pieces.kept_positions(infos, (0, 1, 2, 3)), [0, 3])

    def test_the_pair_names_a_piece(self):
        ps = pieces.compute(book(["translated"] * 3 + ["none"] + ["translated"] * 2))
        self.assertEqual(pieces.piece_at(ps, 5, 6).first, 4)
        self.assertIsNone(pieces.piece_at(ps, 1, 6))

    def test_parse_number(self):
        self.assertEqual(pieces.parse_number(" 12 "), 12)
        self.assertIsNone(pieces.parse_number("1-2"))
        self.assertIsNone(pieces.parse_number(""))


class Names(unittest.TestCase):
    def test_file_names(self):
        self.assertEqual(pieces.file_name("Epic", 2697, 2750, "ru"), "Epic 2697-2750 ru.epub")
        self.assertEqual(pieces.file_name("Epic", 2697, 2750, "ru", "en"), "Epic 2697-2750 ru+en.epub")
        self.assertEqual(pieces.file_name("Epic", 5, 5, "ru"), "Epic 5 ru.epub")

    def test_a_taken_name_gets_a_number_and_nothing_is_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            first = pieces.unique_path(d, "Epic 1-2 ru.epub")
            self.assertEqual(first.name, "Epic 1-2 ru.epub")
            first.write_text("a")
            second = pieces.unique_path(d, "Epic 1-2 ru.epub")
            self.assertEqual(second.name, "Epic 1-2 ru (2).epub")
            second.write_text("b")
            self.assertEqual(pieces.unique_path(d, "Epic 1-2 ru.epub").name, "Epic 1-2 ru (3).epub")
            self.assertEqual(first.read_text(), "a")

    def test_result_line(self):
        self.assertEqual(pieces.result_line(54, 3, 2_400_000), ("54 chapters", "3 not translated yet, left out",
                                                               "2.4 MB"))
        self.assertEqual(pieces.result_line(1, 0, 900), ("1 chapter", "", "1 KB"))


if __name__ == "__main__":
    unittest.main()
