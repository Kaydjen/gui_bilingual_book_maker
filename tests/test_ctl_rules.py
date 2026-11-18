"""Controllers of the new window without Qt: write order rules a-e (review_window_arch 5.3), chapter state by
(index, source hash) (window_spec 14.12), run snapshots, the throttle, the time-left text, the state file, the
term and book sessions.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from novelcore import Series
from novelcore.terms import TermBase
from novelgui import chapterlogic as cl
from novelgui.ctl import eta, ordering
from novelgui.ctl.books import BooksSession, library_task
from novelgui.ctl.persistence import Persistence
from novelgui.ctl.runevents import URGENT, WAKE, ChapterProgress, RunEvents
from novelgui.ctl.session import Session
from novelgui.ctl.terms import TermsSession
from novelgui.ctl.throttle import Debounce, LeadingThrottle
from novelgui.facade import books as fbooks
from novelgui.facade import terms as fterms
from novelgui.lanes import PlainCtx, Want
from tests.ctl_support import Clock, PlainLanes
from tests.test_core_epub import make_epub

NOVELGUI = Path(__file__).resolve().parent.parent / "novelgui"


def chapters(n=3, paras=4, change=None):
    """{file: body}; `change=(chapter, paragraph)` gives that paragraph another text."""
    out = {}
    for c in range(n):
        ps = []
        for p in range(paras):
            text = "Chapter %d paragraph %d, where Arthur meets Merlin." % (c, p)
            if change == (c, p):
                text = "Chapter %d paragraph %d was rewritten by the author." % (c, p)
            ps.append("<p>%s</p>" % text)
        out["c%d.xhtml" % c] = "".join(ps)
    return out


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lib = self.root / "lib"
        self.lib.mkdir()
        self.lanes = PlainLanes()
        self.addCleanup(self.lanes.close)
        self.clock = Clock()

    def series(self, name="Alpha", **kw):
        s = Series.create(self.lib, name, "ru:Russian")
        ep = self.root / (name + ".epub")
        make_epub(ep, chapters(**kw))
        return s, s.add_book(ep)

    def terms(self, s, *sources):
        base = TermBase(s.path / "terms.json", "ru")
        for src in sources:
            base.add(src, status="new", tr="")
        base.save()

    def scan(self, s, stem):
        ctx = PlainCtx()
        fbooks.scan_chapters_task(ctx, str(s.path), stem, Want())
        fbooks.release_books_task(None)
        infos = {}
        for kind, rows in ctx.items:
            for i in rows:
                infos[i.index] = i
        return infos


# ---------------------------------------------------------------- write order
class RuleA_TermEdit(Library):
    def test_an_edit_shows_at_once_and_is_saved_once_after_the_debounce(self):
        s, _ = self.series()
        self.terms(s, "Arthur", "Merlin")
        ts = TermsSession(self.lanes.submit, self.clock.timer, snapshot_dir=self.root)
        seen = []
        ts.changed.add(lambda kind, keys: seen.append((kind, keys)))
        ts.open(s.path, "ru")
        self.lanes.settle()
        self.assertEqual(sorted(ts.rows), ["arthur", "merlin"])           # ids are entry keys
        ts.edit("arthur", "tr", "Артур")
        self.assertEqual(ts.rows["arthur"].tr, "Артур")                  # optimistic, before any lane ran
        self.assertEqual(seen[-1], ("rows", ("arthur",)))
        ts.edit("merlin", "tr", "Мерлин")
        self.lanes.settle()
        on_disk = json.loads((s.path / "terms.json").read_text(encoding="utf-8"))
        self.assertEqual([e.get("ru") for e in on_disk["entries"]], ["", ""])     # not saved yet
        self.assertTrue(ts.save_pending)
        self.clock.advance(0.4)
        self.assertTrue(ts.save_pending)                                  # each edit re-arms the debounce
        self.clock.advance(0.2)
        self.lanes.settle()
        on_disk = json.loads((s.path / "terms.json").read_text(encoding="utf-8"))
        self.assertEqual([e.get("ru") for e in on_disk["entries"]], ["Артур", "Мерлин"])
        self.assertEqual(ts.saves, 1)

    def test_a_refused_edit_puts_the_true_row_back(self):
        s, _ = self.series()
        self.terms(s, "Arthur")
        ts = TermsSession(self.lanes.submit, self.clock.timer)
        ts.open(s.path, "ru")
        self.lanes.settle()
        refused = []
        ts.rejected.add(lambda keys, why: refused.append((keys, why)))
        ts.edit("arthur", "gender", "robot")
        self.assertEqual(ts.rows["arthur"].gender, "robot")
        self.lanes.settle()
        self.assertEqual(ts.rows["arthur"].gender, "unknown")
        self.assertEqual(refused[0][0], ("arthur",))


class RuleB_BeforeBookWork(Library):
    def test_terms_saved_state_written_and_books_closed_before_the_work(self):
        s, stem = self.series()
        self.terms(s, "Arthur")
        ts = TermsSession(self.lanes.submit, self.clock.timer)
        ts.open(s.path, "ru")
        self.lanes.settle()
        state = Persistence(self.root / "data", timer=self.clock.timer)
        state.winstate.set("last", "x")
        book = fbooks.book_file(s.path, stem)
        for lane in self.lanes.lanes.lane_names:
            self.lanes.submit(lambda ctx: fbooks.open_book(book), lane=lane)
        ts.edit("arthur", "tr", "Артур")
        order = ordering.WriteOrder(self.lanes.submit, self.lanes.lanes.close_lane_books, flush_state=state.flush,
                                    flush_terms=ts.flush_terms)
        seen = {}

        def ready():
            seen["terms"] = json.loads((s.path / "terms.json").read_text(encoding="utf-8"))["entries"][0]["ru"]
            seen["state"] = json.loads(state.path.read_text(encoding="utf-8"))["win"]["last"]
            seen["handles"] = {k: v for k, v in fbooks.open_handles().items() if str(book) in v}
            book.rename(book.with_name("moved.epub"))           # Move: nothing holds the file
            seen["moved"] = True
        order.before_book_work(ready, s.path)
        self.lanes.settle()
        self.assertEqual(seen, {"terms": "Артур", "state": "x", "handles": {}, "moved": True})


class RuleC_NoChapterLogWrites(unittest.TestCase):
    def test_blocks_of_the_running_jobs_chapters_are_not_resolved(self):
        self.assertFalse(ordering.resolve_allowed("S", [3, 4, 5], "S", [5]))
        self.assertTrue(ordering.resolve_allowed("S", [3, 4, 5], "S", [6]))
        self.assertTrue(ordering.resolve_allowed("S", [3, 4, 5], "T", [5]))
        self.assertTrue(ordering.resolve_allowed("", [], "S", [5]))

    def test_only_the_resolve_task_appends_to_a_chapter_log_and_only_through_the_core(self):
        writers = []
        for f in NOVELGUI.rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            rel = f.relative_to(NOVELGUI).as_posix()
            if re.search(r"open\([^)]*\.jsonl[^)]*['\"]a", text):
                writers.append(rel + ": raw append")
            if re.search(r"chapter_log\([^)]*\)\.append\(", text):
                writers.append(rel)
        self.assertEqual(writers, ["facade/checks.py"])


class RuleD_SeriesJson(Library):
    def test_read_modify_write_on_the_data_lane_keeps_both_changes(self):
        s, _ = self.series()
        order = ordering.WriteOrder(self.lanes.submit, self.lanes.lanes.close_lane_books)
        order.update_series(s.path, lambda st: st.__setitem__("a", 1))
        order.update_series(s.path, lambda st: st.__setitem__("b", 2))
        self.assertTrue(order.own_write_in_progress(s.path))
        self.lanes.settle()
        self.assertFalse(order.own_write_in_progress(s.path))
        st = Series.open(s.path).settings
        self.assertEqual((st["a"], st["b"]), (1, 2))


class RuleE_ExportPart(Library):
    def test_export_goes_through_a_part_file_and_leftovers_are_swept(self):
        s, stem = self.series()
        out = s.path / "out"
        written = []

        def fake_export(series_path, book, indices, mode, out_path=None):
            written.append(Path(out_path).name)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"epub")
            return fbooks.ExportOutcome(str(out_path), Path(out_path).name, str(out), mode, 1)
        with mock.patch.object(fbooks, "export_selection", fake_export):
            res = fbooks.export_piece_task(PlainCtx(), s.path, stem, [0], "single", "Book 1-3.epub")
        self.assertEqual(written, ["Book 1-3.epub.part"])
        self.assertEqual((res.name, sorted(p.name for p in out.iterdir())), ("Book 1-3.epub", ["Book 1-3.epub"]))
        (out / "Book 4-9.epub.part").write_bytes(b"half")          # a crash in the middle of an export
        infos, views = library_task(PlainCtx(), self.lib)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["Book 1-3.epub"])
        self.assertEqual([i.name for i in infos], ["Alpha"])


# ---------------------------------------------------------------- chapter state by (index, hash)
class ChapterStateByHash(Library):
    def test_a_block_changed_by_the_author_is_not_counted_as_translated(self):
        s, stem = self.series()
        book = s.open_book(stem)
        for ch in book.chapters:
            s.chapter_log(stem, ch).append([{"i": b.index, "src_sha": b.sha, "status": "ok", "text": "x"}
                                            for b in book.blocks(ch)])
        book.close()
        infos = self.scan(s, stem)
        self.assertEqual([infos[i].state.kind for i in range(3)], ["translated"] * 3)
        # Update file: paragraph 2 of chapter 1 has a new text (same index, new hash); the old ok line stays
        ep = self.root / "v2.epub"
        make_epub(ep, chapters(change=(1, 2)))
        target = fbooks.book_file(s.path, stem)
        target.write_bytes(ep.read_bytes())
        infos = self.scan(s, stem)
        self.assertEqual([infos[i].state.kind for i in range(3)], ["translated", "partly", "translated"])
        self.assertEqual((infos[1].done, infos[1].blocks), (3, 4))
        # the old rule (latest record per index) would have called it translated
        log = s.chapter_log(stem, Series.open(s.path).open_book(stem).chapters[1]).path
        self.assertEqual(cl.count_log(json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()), (4, 0))
        fbooks.release_books_task(None)

    def test_count_by_hash_latest_record_of_the_block_decides(self):
        shas = ("aaa", "bbb", "ccc")
        recs = [{"i": 0, "src_sha": "aaa", "status": "failed"}, {"i": 0, "src_sha": "aaa", "status": "ok"},
                {"i": 1, "src_sha": "old", "status": "ok"}, {"i": 2, "src_sha": "ccc", "status": "failed"},
                {"i": 7, "src_sha": "zzz", "status": "ok"}]
        self.assertEqual(cl.count_log_by_hash(recs, shas), (1, 1))

    def test_the_cache_keeps_the_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            p = cl.cache_path(d, "b")
            info = cl.ChapterInfo(0, "a", "T", False, 2, (1, 1), 2, 0, ("aa", "bb"))
            cl.save_cache(p, (5, 6), [info])
            self.assertEqual(cl.load_cache(p, (5, 6))[0].shas, ("aa", "bb"))


# ---------------------------------------------------------------- run snapshots
def ev(kind, **data):
    return (kind, data)


class Snapshots(unittest.TestCase):
    def test_absolute_state_is_last_wins_per_chapter(self):
        r = RunEvents()
        self.assertEqual(r.feed(ev("progress", index=3, done=1, total=10, failed=0)), WAKE)
        for d in range(2, 9):
            self.assertEqual(r.feed(ev("progress", index=3, done=d, total=10, failed=0)), "")
        r.feed(ev("pair", label="k1", state="cool", until=5, reason="429"))
        r.feed(ev("pair", label="k1", state="ok", until=None, reason=""))
        snap = r.take()
        self.assertEqual(dict(snap.chap), {3: (8, 10, 0)})
        self.assertEqual(snap.changed, {3})
        self.assertEqual(snap.pairs["k1"][0], "ok")
        self.assertEqual(snap.edges, ())
        self.assertEqual(snap.totals, (8, 10, 0, 1))
        self.assertEqual(r.take().changed, frozenset())             # nothing new

    def test_edges_are_never_dropped_and_keep_their_order(self):
        r = RunEvents()
        r.feed(ev("paused", until=100))
        r.feed(ev("unpaused"))
        r.feed(ev("waiting", until=50, reason="cool"))
        r.feed(ev("block_failed", index=1, block=4))
        snap = r.take()
        self.assertEqual([k for k, _d in snap.edges], ["paused", "unpaused", "waiting", "block_failed"])
        self.assertEqual((snap.paused_until, snap.retry_until), (None, 50))
        self.assertEqual(r.take().edges, ())

    def test_terminal_events_are_urgent_and_carried_once(self):
        r = RunEvents()
        r.feed(ev("progress", index=0, done=1, total=2, failed=0))
        self.assertEqual(r.feed(ev("quota", until=9)), URGENT)
        self.assertEqual(r.feed(ev("error", message="boom")), URGENT)
        snap = r.take()
        self.assertEqual(snap.terminal[0], "error")
        self.assertEqual(snap.last_error, "boom")
        self.assertEqual([k for k, _d in snap.edges], ["error"])
        self.assertIsNone(r.take().terminal)

    def test_a_snapshot_is_immutable(self):
        r = RunEvents({0: (1, 2, 0)})
        snap = r.take()
        with self.assertRaises(TypeError):
            snap.chap[0] = (2, 2, 0)
        with self.assertRaises(Exception):
            snap.seq = 5

    def test_progress_table_applies_only_the_changed_rows_as_ranges(self):
        r = RunEvents()
        for i in (4, 5, 6, 9):
            r.feed(ev("progress", index=i, done=1, total=3, failed=0))
        t = ChapterProgress([None] * 12)
        self.assertEqual(t.apply(r.take()), [(4, 6), (9, 9)])
        self.assertEqual(t.rows[5], (1, 3, 0))


class Throttle(unittest.TestCase):
    def test_leading_edge_then_one_trailing_wake_per_gate(self):
        clock = Clock()
        wakes = []
        th = LeadingThrottle(clock.timer, lambda: wakes.append(clock.now), 100)
        th.mark()
        self.assertEqual(len(wakes), 1)                     # at once
        for _ in range(30):
            th.mark()
            clock.advance(0.002)
        self.assertEqual(len(wakes), 1)
        clock.advance(0.1)
        self.assertEqual(len(wakes), 2)                     # one trailing wake
        clock.advance(0.5)
        self.assertEqual(len(wakes), 2)                     # quiet: nothing
        th.mark()
        self.assertEqual(len(wakes), 3)

    def test_urgent_skips_the_gate(self):
        clock = Clock()
        wakes = []
        th = LeadingThrottle(clock.timer, lambda: wakes.append(1), 100)
        th.mark()
        th.mark(urgent=True)
        self.assertEqual(len(wakes), 2)

    def test_debounce_runs_once_after_the_last_poke(self):
        clock = Clock()
        runs = []
        d = Debounce(clock.timer, lambda: runs.append(clock.now), 500)
        for _ in range(5):
            d.poke()
            clock.advance(0.3)
        self.assertEqual(runs, [])
        clock.advance(0.3)
        self.assertEqual(len(runs), 1)
        d.poke()
        self.assertTrue(d.flush())
        self.assertEqual(len(runs), 2)


class TimeLeft(unittest.TestCase):
    def test_rounding(self):
        cases = [(0, "under a minute"), (59, "under a minute"), (61, "about 1 min"), (7 * 60 + 20, "about 7 min"),
                 (12 * 60, "about 10 min"), (38 * 60, "about 40 min"), (56 * 60, "about 55 min"),
                 (58 * 60, "about 1 h"), (85 * 60, "about 1.5 h"), (2 * 3600 + 10 * 60, "about 2 h"),
                 (3600 * 9.5, "about 9.5 h"), (3600 * 13.2, "about 13 h"), (3600 * 70, "about 3 days")]
        for seconds, text in cases:
            self.assertEqual(eta.human_left(seconds), text, seconds)
        self.assertEqual(eta.human_left(None), "")

    def test_estimate_from_the_measured_speed(self):
        self.assertIsNone(eta.time_left(2, 600, 100))           # too few blocks measured
        self.assertIsNone(eta.time_left(50, 10, 100))           # too short
        self.assertEqual(eta.time_left(60, 600, 120), 1200)     # 0.1 block/s
        self.assertEqual(eta.run_left(60, 600, 120), "about 20 min")
        self.assertEqual(eta.run_left(60, 600, 0), "under a minute")


# ---------------------------------------------------------------- the state file
class StateFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.clock = Clock()

    def test_debounced_trailing_write_and_equal_values_skipped(self):
        p = Persistence(self.folder, timer=self.clock.timer)
        for x in range(40):                                     # a window drag
            p.winstate.set("geometry", [x, 10, 800, 600])
            self.clock.advance(0.05)
        self.assertEqual(p.writes, 0)
        self.assertFalse(p.path.exists())
        self.clock.advance(0.5)
        self.assertEqual(p.writes, 1)
        self.assertEqual(json.loads(p.path.read_text(encoding="utf-8"))["win"]["geometry"], [39, 10, 800, 600])
        p.winstate.set("geometry", [39, 10, 800, 600])          # equal: nothing to do
        p.settings.set("x", 1)
        p.settings.set("x", 2)
        p.settings.set("x", 1)
        self.clock.advance(1)
        self.assertEqual(p.writes, 2)
        p.settings.data["y"] = 3
        p.settings.save()
        p.settings.data.pop("y")
        p.flush()                                               # same text as on disk: skipped
        self.assertEqual(p.writes, 2)

    def test_flush_writes_now_and_keeps_a_backup(self):
        p = Persistence(self.folder, timer=self.clock.timer)
        p.settings.set("library", "A")
        p.flush()
        p.settings.set("library", "B")
        p.flush()
        self.assertEqual(json.loads(p.path.read_text(encoding="utf-8"))["library"], "B")
        bak = p.path.with_name("settings.json.bak")
        self.assertEqual(json.loads(bak.read_text(encoding="utf-8"))["library"], "A")

    def test_a_damaged_file_goes_to_bad_and_the_backup_is_read(self):
        p = Persistence(self.folder, timer=self.clock.timer)
        p.settings.set("library", "A")
        p.flush()
        p.settings.set("library", "B")
        p.flush()
        p.path.write_text("{broken", encoding="utf-8")
        q = Persistence(self.folder, timer=self.clock.timer)
        self.assertTrue(q.settings.restored)
        self.assertEqual(q.settings.get("library"), "A")
        self.assertEqual(p.path.with_name("settings.json.bad").read_text(encoding="utf-8"), "{broken")
        q.flush()
        self.assertEqual(json.loads(q.path.read_text(encoding="utf-8"))["library"], "A")

    def test_damaged_without_backup_reads_empty(self):
        self.folder.mkdir(exist_ok=True)
        (self.folder / "settings.json").write_text("[1, 2", encoding="utf-8")
        q = Persistence(self.folder, timer=self.clock.timer)
        self.assertEqual(q.settings.data, {})
        self.assertTrue((self.folder / "settings.json.bad").exists())

    def test_writes_on_the_data_lane_never_go_back_in_time(self):
        lanes = PlainLanes()
        self.addCleanup(lanes.close)
        p = Persistence(self.folder, timer=self.clock.timer, submit=lanes.submit)
        p.settings.set("n", 1)
        p.flush()
        p.settings.set("n", 2)
        p.close()                                               # on this thread, while the lane may still write
        lanes.settle()
        self.assertEqual(json.loads(p.path.read_text(encoding="utf-8"))["n"], 2)


# ---------------------------------------------------------------- sessions
class Sessions(Library):
    def test_session_observers_see_series_book_selection(self):
        s = Session()
        seen = []
        s.changed.add(seen.append)
        s.set_series(fbooks.SeriesInfo("A", "/a", "ru:Russian", "ru", ("v1",)))
        s.set_book("v1")
        s.select([5, 3, 3])
        s.select([3, 5])
        self.assertEqual(seen, ["series", "book", "selection"])
        self.assertEqual(s.selection.indices, (3, 5))

    def test_books_session_fills_the_list_and_drops_a_superseded_scan(self):
        a, astem = self.series("Alpha", n=40)
        b, bstem = self.series("Beta", n=5)
        bs = BooksSession(self.lanes.submit)
        got = []
        bs.changed.add(lambda kind, payload: got.append(kind))
        bs.load_library(self.lib)
        self.lanes.settle()
        self.assertEqual([s.name for s in bs.series_list], ["Alpha", "Beta"])
        bs.open_book(a.path, astem)
        bs.open_book(b.path, bstem)                             # the user clicked on: the first scan is superseded
        self.lanes.settle()
        self.assertEqual(len(bs.infos), 5)
        self.assertTrue(all(i.blocks == 4 for i in bs.infos))
        self.assertIn("rows", got)

    def test_term_scan_on_a_snapshot_fills_seen_and_count(self):
        s, stem = self.series()
        self.terms(s, "Arthur", "Merlin", "Lancelot")
        ts = TermsSession(self.lanes.submit, self.clock.timer, snapshot_dir=self.root)
        ts.open(s.path, "ru")
        self.lanes.settle()
        done = []
        ts.scan_book(stem, on_done=done.append)
        ts.edit("arthur", "tr", "Артур")                        # an edit while the book is read
        self.lanes.settle()
        self.assertEqual(done, [2])
        self.assertEqual((ts.rows["arthur"].count, ts.rows["arthur"].first, ts.rows["arthur"].tr), (12, 0, "Артур"))
        self.assertEqual(ts.rows["lancelot"].count, 0)
        self.assertEqual(list(self.root.glob("terms-snapshot-*")), [])
        ts.flush_terms()
        self.lanes.settle()
        base = TermBase.load(s.path / "terms.json", "ru")
        self.assertEqual(sorted(base.get("Merlin").seen), [0, 1, 2])
        self.assertEqual(base.get("Arthur").tr, "Артур")

    def test_term_scan_result_shape(self):
        s, stem = self.series()
        self.terms(s, "Merlin")
        snap = self.root / "snap.json"
        TermBase.load(s.path / "terms.json", "ru").save(snap)
        found = fterms.term_scan_task(PlainCtx(), snap, "ru", s.path, stem)
        fbooks.release_books_task(None)
        self.assertEqual(found, {"merlin": [[0, 4], [1, 4], [2, 4]]})


if __name__ == "__main__":
    unittest.main()
