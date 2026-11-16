"""Reviewed frontier: scan, caches, dismissed list, per-chapter guard, frontier. All names are invented."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from novelcore import frontier as fm
from novelcore.frontier import (KIND_CANDIDATE, KIND_NEW, KIND_QUESTION, NO_FILTERS, Filters, Frontier, NotScanned,
                                gate_for, reduce_candidate, scan)
from novelcore.store import Series
from novelcore.termmatch import TermsHook
from novelcore.terms import TermBase, candidate
from tests.test_core_epub import make_epub

BODIES = {
    "c0.xhtml": "<p>The hero fought the Iron Wolf near Silver Lake.</p>",
    "c1.xhtml": "<p>Later the hero fought the Iron Wolf again, and Iron Wolf lost.</p>",
    "c2.xhtml": "<p>Nothing special happens here at all today.</p>",
    "c3.xhtml": "<p>The hero visited Dark Tower with Mira Vale.</p>",
    "c4.xhtml": "<p>Then the hero fought the Iron Wolf near Dark Tower.</p>",
}


def nav_for(names):
    return "<nav><ol>" + "".join(f'<li><a href="{n}">Title of {n}</a></li>' for n in names) + "</ol></nav>"


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.epub = self.dir / "Book.epub"
        make_epub(self.epub, BODIES, nav=nav_for(BODIES))  # nav first in the spine: chapter 0 is a TOC page
        self.state = self.dir / ".state"
        self.base = TermBase(self.dir / "terms.json", "ru")

    def fr(self, base=None, filters=NO_FILTERS) -> Frontier:
        return Frontier(base or self.base, self.epub, self.state, filters)

    def texts(self, fr, first=0, last=None):
        return [it.text for it in fr.blocking_terms(first, last)]


class ScanTest(Case):
    def test_totals_first_chapter_ranges_and_toc(self):
        fr = self.fr()
        rep = fr.scan()
        self.assertEqual((rep.source, rep.chapters), ("book", 6))
        self.assertEqual(rep.read, 6)
        terms = fr.terms()
        wolf = terms["iron wolf"]
        self.assertEqual((wolf.kind, wolf.count, wolf.first, wolf.chapters), (KIND_CANDIDATE, 4, 1, "1-2,5"))
        self.assertEqual(terms["silver lake"].chapters, "1")
        self.assertEqual(fr.check_chapter(0), 0)  # the TOC page never blocks
        self.assertEqual(fr.check_chapter(3), 0)  # nothing happens there

    def test_progress_and_cancel(self):
        calls = []
        fr = self.fr()
        fr.scan(progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls[-1], (6, 6))
        ev = threading.Event()
        ev.set()
        fr2 = Frontier(self.base, self.epub, self.dir / "other", NO_FILTERS)
        rep = fr2.scan(cancel=ev)
        self.assertTrue(rep.cancelled)
        with self.assertRaises(NotScanned):
            fr2.check_chapter(1)

    def test_cancel_keeps_finished_chapters(self):
        ev = threading.Event()
        seen = []

        def progress(done, total):
            seen.append(done)
            ev.set()

        # progress fires every 10 chapters or at the last one, so cancel through a counting callable
        n = {"i": 0}

        def cancel():
            n["i"] += 1
            return n["i"] > 3

        fr = Frontier(self.base, self.epub, self.state, NO_FILTERS)
        rep = fr.scan(cancel=cancel)
        self.assertTrue(rep.cancelled)
        self.assertTrue(fr.chunks_path.exists())
        fr2 = Frontier(self.base, self.epub, self.state, NO_FILTERS)
        rep2 = fr2.scan()
        self.assertFalse(rep2.cancelled)
        self.assertLess(rep2.read, 6)
        self.assertEqual(fr2.check_chapter(1), 2)

    def test_scan_function_with_base(self):
        fr = scan(self.base, self.epub, state_dir=self.state, filters=NO_FILTERS)
        self.assertEqual(fr.check_chapter(1), 2)
        with self.assertRaises(ValueError):
            scan(self.base, self.epub)

    def test_empty_base_candidates_only(self):
        fr = self.fr()
        fr.scan()
        info = fr.frontier(0)
        self.assertEqual((info.chapter, info.count), (1, 2))

    def test_only_confirmed_entries(self):
        self.base.add("Iron Wolf", type="creature", tr="x")
        self.base.add("Silver Lake", type="place", tr="y")
        fr = self.fr()
        fr.scan()
        self.assertEqual(self.texts(fr), ["Dark Tower", "Mira Vale"])
        self.assertEqual(fr.frontier(0).chapter, 4)
        self.assertEqual(fr.terms()["iron wolf"].kind, fm.KIND_KNOWN)


class KindsTest(Case):
    def test_kinds_and_confirmed_question_does_not_block(self):
        a = self.base.add("Iron Wolf", status="new", tr="x")
        b = self.base.add("Silver Lake", status="new", tr="y")
        self.base.ask(b, "tr", [candidate("y"), candidate("z")])
        c = self.base.add("Dark Tower", status="confirmed", tr="w")
        self.base.ask(c, "tr", [candidate("w"), candidate("v")])
        fr = self.fr()
        fr.scan()
        kinds = {it.text: it.kind for c in range(6) for it in fr.unreviewed(c)}
        self.assertEqual(kinds["Iron Wolf"], KIND_NEW)
        self.assertEqual(kinds["Silver Lake"], KIND_QUESTION)
        self.assertNotIn("Dark Tower", kinds)
        self.assertIn("Mira Vale", kinds)
        self.assertEqual([(i.text, i.count) for i in fr.unreviewed(2)], [("Iron Wolf", 2)])

    def test_confirm_moves_frontier_without_reading_book(self):
        self.base.add("Iron Wolf", status="new", tr="x")
        fr = self.fr()
        fr.scan()
        self.assertEqual(fr.frontier(0).chapter, 1)  # Iron Wolf only; Silver Lake is a candidate too
        self.base.confirm("Iron Wolf")
        self.base.add("Silver Lake", tr="y")
        self.base.save()
        rep = fr.scan()  # a new spelling: matches are redone
        self.assertEqual(rep.source, "book")
        self.assertEqual(fr.frontier(0).chapter, 4)
        self.base.dismiss("Dark Tower")
        self.base.dismiss("Mira Vale")
        rep = self.fr().scan()
        self.assertEqual(rep.source, "chunks")
        self.assertEqual(rep.read, 0)
        fr3 = self.fr()
        fr3.scan()
        self.assertIsNone(fr3.frontier(0).chapter)
        self.assertEqual(fr3.allowed(0), [1, 2, 3, 4, 5])


class CacheTest(Case):
    def test_warm_and_invalidation(self):
        self.base.save()
        self.fr().scan()
        self.assertTrue((self.state / "frontier_Book.json").exists())
        self.assertEqual(self.fr().scan().source, "answer")
        # terms.json edited (file stat and digest change)
        self.base.add("Iron Wolf", status="new", tr="x")
        self.base.save()
        rep = self.fr().scan()
        self.assertEqual(rep.source, "book")
        # status only: answer invalid, chunks reused
        self.base.confirm("Iron Wolf")
        self.base.save()
        rep = self.fr().scan()
        self.assertEqual((rep.source, rep.read), ("chunks", 0))
        # dismissed list
        self.base.dismiss("Mira Vale")
        self.base.save()
        self.assertEqual(self.fr().scan().source, "chunks")
        self.assertEqual(self.fr().scan().source, "answer")
        # other filters
        self.assertEqual(self.fr(filters=Filters()).scan().source, "chunks")
        # the book file changed
        make_epub(self.epub, dict(BODIES, **{"c2.xhtml": "<p>Plain text.</p>"}), nav=nav_for(BODIES))
        os.utime(self.epub, (1, 1))
        rep = self.fr().scan()
        self.assertEqual((rep.source, rep.read), ("book", 6))

    def test_unsaved_change_is_not_served_from_cache(self):
        self.base.save()
        self.fr().scan()
        self.base.dismiss("Dark Tower")  # in memory only: the file did not change
        fr = self.fr()
        self.assertNotEqual(fr.scan().source, "answer")
        self.assertNotIn("Dark Tower", self.texts(fr))

    def test_damaged_cache_is_ignored_and_files_are_atomic(self):
        fr = self.fr()
        fr.scan()
        fr.answer_path.write_text("{broken", encoding="utf-8")
        fr.chunks_path.write_text("[1]", encoding="utf-8")
        fr2 = self.fr()
        self.assertEqual(fr2.scan().source, "book")
        self.assertEqual([p.name for p in self.state.iterdir() if p.name.endswith(".tmp")], [])
        json.loads(fr2.answer_path.read_text(encoding="utf-8"))

    def test_base_edit_after_scan_is_seen_by_the_guard(self):
        fr = self.fr()
        fr.scan()
        self.assertEqual(fr.check_chapter(1), 2)
        self.base.dismiss("Silver Lake")  # in memory, same object: cheap recompute from the chunks
        self.assertEqual(fr.check_chapter(1), 1)
        self.assertFalse(fr.stale)
        self.base.add("Dark Tower", status="new", tr="x")  # a new spelling: matches are stale until scan()
        fr.check_chapter(4)
        self.assertTrue(fr.stale)
        fr.scan()
        self.assertFalse(fr.stale)
        self.assertEqual({i.text: i.kind for i in fr.unreviewed(4)}["Dark Tower"], KIND_NEW)


class DismissedTest(Case):
    def test_round_trip_and_old_files(self):
        old = self.dir / "old.json"
        old.write_text(json.dumps({"version": 1, "target": "ru", "entries": [
            {"source": "Zed", "type": "term", "gender": "unknown", "ru": "З", "status": "confirmed", "count": 0}]}),
            encoding="utf-8")
        b = TermBase.load(old)
        self.assertEqual((len(b), b.dismissed()), (1, []))
        self.assertTrue(b.dismiss("Iron Wolf"))
        self.assertFalse(b.dismiss("iron  wolf"))
        b.save()
        back = TermBase.load(old)
        self.assertEqual(back.dismissed(), ["iron wolf"])
        self.assertTrue(back.is_dismissed("Iron Wolves") or back.is_dismissed("Iron Wolf's"))
        self.assertNotIn("dismissed", back.meta)
        self.assertEqual(len(back), 1)
        self.assertTrue(back.restore("Iron Wolf"))
        back.save()
        self.assertEqual(TermBase.load(old).dismissed(), [])
        self.assertNotIn("dismissed", json.loads(old.read_text(encoding="utf-8")))
        with self.assertRaises(ValueError):
            back.dismiss("Zed")

    def test_rev_moves(self):
        r = self.base.rev
        self.base.dismiss("Foo Bar")
        self.assertGreater(self.base.rev, r)

    def test_dismissed_never_reaches_the_translator(self):
        self.base.add("Silver Lake", tr="Серебряное озеро")
        self.base.dismiss("Iron Wolf")
        hook = TermsHook(self.base)
        lines = hook(None, [type("B", (), {"text": "The Iron Wolf swam in Silver Lake."})()])
        joined = "\n".join(lines)
        self.assertIn("Silver Lake", joined)
        self.assertNotIn("Iron Wolf", joined)
        self.base.save()
        self.assertNotIn("Iron Wolf", "\n".join(TermsHook(TermBase.load(self.base.path))(
            None, [type("B", (), {"text": "Iron Wolf"})()])))

    def test_dismiss_stops_blocking_and_persists(self):
        fr = self.fr()
        fr.scan()
        self.assertEqual(fr.check_chapter(1), 2)
        self.assertTrue(fr.dismiss("Iron Wolf"))
        self.assertEqual(fr.check_chapter(2), 0)
        self.assertEqual(fr.check_chapter(1), 1)
        fr2 = self.fr(TermBase.load(self.base.path))
        fr2.scan()
        self.assertEqual(fr2.check_chapter(2), 0)
        fr2.restore("Iron Wolf")
        self.assertEqual(fr2.check_chapter(2), 1)


class FrontierTest(Case):
    def test_frontier_allowed_blocking(self):
        fr = self.fr()
        fr.scan()
        info = fr.frontier(0, 5)
        self.assertEqual((info.chapter, info.count, info.total, info.capped), (1, 2, 4, False))
        self.assertEqual(fr.allowed(0, 5), [])
        self.assertEqual(fr.allowed(2, 2), [])
        self.assertEqual(fr.frontier(3, 5).chapter, 4)
        blk = fr.blocking_terms(0, 5)
        self.assertEqual([i.text for i in blk], ["Iron Wolf", "Silver Lake", "Dark Tower", "Mira Vale"])
        self.assertEqual((blk[0].first, blk[0].count, blk[0].chapters), (1, 4, "1-2,5"))
        self.assertEqual(set(self.texts(fr, 5, 5)), {"Iron Wolf", "Dark Tower"})
        self.assertEqual([i.text for i in fr.blocking_terms(0, 5, limit=1)], ["Iron Wolf"])
        self.assertTrue(fr.frontier(0, 5, limit=2).capped)
        self.assertEqual(fr.frontier(5, 2).chapter, None)

    def test_allowed_skips_toc_and_stops_at_frontier(self):
        self.base.add("Iron Wolf", tr="x")
        self.base.add("Silver Lake", tr="y")
        fr = self.fr()
        fr.scan()
        self.assertEqual(fr.allowed(0, 5), [1, 2, 3])
        self.assertEqual(fr.frontier(0, 5).chapter, 4)

    def test_requires_scan(self):
        with self.assertRaises(NotScanned):
            self.fr().frontier(0)

    def test_check_chapter_threads(self):
        fr = self.fr()
        fr.scan()
        errors = []

        def work(n):
            try:
                for i in range(200):
                    got = fr.check_chapter(i % 6)
                    if got < 0:
                        errors.append(got)
                    if n == 0 and i == 50:
                        self.base.dismiss("Mira Vale")
                    if n == 1 and i == 80:
                        self.base.restore("Mira Vale")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class FilterTest(Case):
    def base_with(self, *confirmed):
        b = TermBase(None, "ru")
        for s in confirmed:
            b.add(s, tr="x")
        return b

    def test_named_constants(self):
        self.assertEqual((fm.MIN_BOOK_COUNT, fm.MAX_WORDS, fm.STRIP_NUMBERS, fm.STRIP_KNOWN_EDGES, fm.DROP_STOP_SINGLES),
                         (2, 5, True, True, True))
        self.assertIsInstance(fm.LOWER_RATIO, float)
        self.assertGreaterEqual(fm.MIN_BOOK_CHAPTERS, 1)

    def test_min_book_count(self):
        fr = self.fr(filters=Filters(min_book_count=2, min_book_mid=0, min_book_chapters=1, lower_ratio=0))
        fr.scan()
        self.assertEqual(self.texts(fr), ["Iron Wolf", "Dark Tower"])
        fr = self.fr(filters=Filters(min_book_count=2, min_book_mid=1, min_book_chapters=1, lower_ratio=0))
        fr.scan()
        self.assertEqual(len(self.texts(fr)), 4)  # all of them stand in mid-sentence

    def test_min_book_chapters(self):
        fr = self.fr(filters=Filters(min_book_count=0, min_book_chapters=2, lower_ratio=0))
        fr.scan()
        self.assertEqual(self.texts(fr), ["Iron Wolf", "Dark Tower"])

    def test_reduce_numbers_and_edges(self):
        base = self.base_with("Shi Feng")
        f = Filters()
        self.assertEqual(reduce_candidate("5 Kobold Chieftain", base, f), "Kobold Chieftain")
        self.assertEqual(reduce_candidate("Agility 70", base, f), "Agility")
        self.assertEqual(reduce_candidate("Shi Feng's Novice Sword", base, f), "Novice Sword")
        self.assertIsNone(reduce_candidate("Shi Feng and Shi Feng", base, f))
        self.assertIsNone(reduce_candidate("Shi Feng", base, f))
        off = Filters(strip_numbers=False, strip_known_edges=False)
        self.assertEqual(reduce_candidate("Agility 70", base, off), "Agility 70")
        self.assertEqual(reduce_candidate("Shi Feng's Novice Sword", base, off), "Shi Feng's Novice Sword")

    def test_max_words_and_stop_singles(self):
        base = self.base_with()
        self.assertIsNone(reduce_candidate("A B C D E F", base, Filters()))
        self.assertEqual(reduce_candidate("Alpha Beta Gamma Delta Omega", base, Filters()), "Alpha Beta Gamma Delta Omega")
        self.assertIsNone(reduce_candidate("Suddenly", base, Filters()))
        self.assertEqual(reduce_candidate("Suddenly", base, Filters(drop_stop_singles=False)), "Suddenly")
        base.dismiss("Zork Bar")
        self.assertIsNone(reduce_candidate("Zork Bar", base, Filters()))

    def test_lower_ratio(self):
        body = {"c0.xhtml": "<p>She felt tired. He felt cold. We felt warm. Then Felt came. Then Felt left. Felt!</p>"
                            "<p>They met Zorvak. Then Zorvak and Zorvak spoke. They saw Zorvak again.</p>"}
        epub = self.dir / "Low.epub"
        make_epub(epub, body)
        fr = Frontier(self.base, epub, self.dir / "s2", Filters(min_book_count=0, lower_ratio=1.0))
        fr.scan()
        got = [i.text for i in fr.blocking_terms(0)]
        self.assertNotIn("Felt", got)
        fr = Frontier(self.base, epub, self.dir / "s3", Filters(min_book_count=0, lower_ratio=0))
        fr.scan()
        self.assertIn("Zorvak", [i.text for i in fr.blocking_terms(0)])


class SeriesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        epub = self.dir / "Book.epub"
        make_epub(epub, BODIES)
        self.series = Series.create(self.dir / "lib", "S", "ru:Russian")
        self.series.add_book(epub)

    def test_gate_none_without_terms_file(self):
        self.assertIsNone(gate_for(self.series, "Book"))

    def test_gate_scans_on_first_use(self):
        base = TermBase(self.series.path / "terms.json", "ru")
        base.add("Silver Lake", tr="x", status="new")
        base.save()
        gate = gate_for(self.series, "Book", filters=NO_FILTERS, candidates=True)
        self.assertIsNotNone(gate)
        self.assertEqual(gate(0), 2)  # Silver Lake (entry) and Iron Wolf (candidate)
        self.assertEqual(gate(2), 0)
        results = []
        threads = [threading.Thread(target=lambda: results.append(gate(1))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(set(results), {1})
        self.assertTrue((self.series.path / ".state").is_dir())

    def make_terms(self, *entries):
        base = TermBase(self.series.path / "terms.json", "ru")
        for source, status, question in entries:
            e = base.add(source, status=status, tr="x")
            if question:
                base.ask(e, "tr", [candidate("x"), candidate("y")])
        base.save()
        return base

    def test_constant_is_honoured_and_off_by_default(self):
        self.assertFalse(fm.GATE_CANDIDATES)
        self.make_terms(("Silver Lake", "new", False))
        self.assertFalse(gate_for(self.series, "Book", filters=NO_FILTERS).candidates)
        old = fm.GATE_CANDIDATES
        fm.GATE_CANDIDATES = True
        try:
            gate = gate_for(self.series, "Book", filters=NO_FILTERS)
            self.assertTrue(gate.candidates)
            self.assertEqual(gate(0), 2)
        finally:
            fm.GATE_CANDIDATES = old

    def test_gate_without_candidates_blocks_on_unconfirmed_entries_only(self):
        self.make_terms(("Silver Lake", "new", False), ("Dark Tower", "new", True), ("Iron Wolf", "confirmed", True))
        gate = gate_for(self.series, "Book", filters=NO_FILTERS)
        self.assertEqual(gate(0), 1)  # Silver Lake; Iron Wolf is confirmed (its question does not block); Mira Vale ignored
        self.assertEqual(gate(1), 0)  # only a confirmed entry and a candidate-free chapter
        self.assertEqual(gate(3), 1)  # Dark Tower, an unconfirmed entry with a question
        self.assertEqual(gate(4), 1)
        kinds = {i.kind for c in range(5) for i in gate.frontier.unreviewed(c, candidates=False)}
        self.assertEqual(kinds, {KIND_NEW, KIND_QUESTION})

    def test_gate_answers_zero_without_scanning_when_all_confirmed(self):
        self.make_terms(("Silver Lake", "confirmed", True))
        gate = gate_for(self.series, "Book")
        self.assertEqual([gate(i) for i in range(5)], [0] * 5)
        self.assertIsNone(gate.frontier._d)
        self.assertFalse((self.series.path / ".state").exists())

    def test_gate_sees_a_new_unconfirmed_entry(self):
        base = self.make_terms(("Silver Lake", "confirmed", False))
        gate = gate_for(self.series, "Book", filters=NO_FILTERS)
        self.assertEqual(gate(1), 0)
        gate.frontier.base.add("Dark Tower", status="new", tr="x")
        self.assertEqual(gate(3), 1)
        gate.frontier.base.confirm("Dark Tower")
        self.assertEqual(gate(3), 0)

    def test_entries_only_scan_skips_mining_and_refuses_candidate_views(self):
        base = self.make_terms(("Silver Lake", "new", False))
        fr = Frontier.for_series(self.series, filters=NO_FILTERS)
        fr.scan(mine=False)
        self.assertEqual(fr.check_chapter(0, candidates=False), 1)
        with self.assertRaises(NotScanned):
            fr.check_chapter(0)
        rows = json.loads(fr.chunks_path.read_text(encoding="utf-8"))["rows"]
        self.assertTrue(all("c" not in r for r in rows.values()))
        self.assertEqual(Frontier.for_series(self.series, filters=NO_FILTERS).scan(mine=False).source, "answer")
        rep = fr.scan()  # mining is added; the matches are reused
        self.assertEqual(rep.source, "book")
        self.assertEqual(fr.check_chapter(0), 2)
        self.assertEqual(fr.check_chapter(0, candidates=False), 1)

    def test_candidate_switch_on_the_views(self):
        base = TermBase(None, "ru")
        base.add("Silver Lake", status="new", tr="x")
        epub = self.dir / "Book.epub"
        fr = Frontier(base, epub, self.dir / "st", NO_FILTERS)
        fr.scan()
        self.assertEqual(fr.check_chapter(0), 2)
        self.assertEqual(fr.check_chapter(0, candidates=False), 1)
        self.assertEqual(fr.frontier(1, 4).chapter, 1)
        self.assertEqual(fr.frontier(1, 4, candidates=False).chapter, None)
        self.assertEqual(fr.frontier(0, 4, candidates=False).chapter, 0)
        self.assertEqual(fr.allowed(0, 4, candidates=False), [])
        self.assertEqual(fr.allowed(1, 4, candidates=False), [1, 2, 3, 4])
        self.assertEqual([i.text for i in fr.blocking_terms(0, 4, candidates=False)], ["Silver Lake"])
        self.assertEqual(len(fr.blocking_terms(0, 4)), 4)

    def test_for_series_picks_the_only_book(self):
        (self.series.path / "terms.json").write_text('{"version":1,"target":"ru","entries":[]}', encoding="utf-8")
        fr = Frontier.for_series(self.series, filters=NO_FILTERS)
        fr.scan()
        self.assertEqual(fr.frontier(0).chapter, 0)


if __name__ == "__main__":
    unittest.main()
