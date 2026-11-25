"""Library rules and disk operations of the Books step (window_spec 2, 4.3-4.5, 5.4, 13.5, 13.6)."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from novelcore.store import safe_name
from novelgui import addbook, busy, libraryops, libraryrules as rules, model
from novelgui.jobstate import JobView
from novelgui.settings import Settings
from novelgui.winstate import WinState

from tests.epubs import write_epub


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)


class NaturalSort(unittest.TestCase):
    def test_numbers_compare_as_numbers(self):
        names = ["Vol 10", "Vol 2", "vol 1", "Vol 21", "Vol 3b", "Vol 3a"]
        self.assertEqual(sorted(names, key=rules.natural_key),
                         ["vol 1", "Vol 2", "Vol 3a", "Vol 3b", "Vol 10", "Vol 21"])

    def test_names_without_digits_and_mixed(self):
        self.assertEqual(sorted(["b", "10", "a", "9"], key=rules.natural_key), ["9", "10", "a", "b"])


class FolderRules(Tmp):
    def test_default_path_prefers_documents(self):
        self.assertEqual(rules.default_library_path(self.root), self.root / "Novel library")
        (self.root / "Documents").mkdir()
        self.assertEqual(rules.default_library_path(self.root), self.root / "Documents" / "Novel library")

    def test_chooser_opens_at_the_parent_of_the_library(self):
        self.assertEqual(rules.chooser_start(self.root / "lib", self.root), str(self.root))
        self.assertEqual(rules.chooser_start(None, self.root), str(self.root))

    def test_series_folder_makes_its_parent_the_library(self):
        s = self.root / "lib" / "Saga"
        s.mkdir(parents=True)
        (s / "series.json").write_text("{}", encoding="utf-8")
        scan = rules.scan_folder(s)
        self.assertEqual((scan.kind, scan.library, scan.series), ("series", s.parent, s))

    def test_folder_of_epubs_offers_to_add_them(self):
        (self.root / "b.epub").write_bytes(b"x")
        (self.root / "a.epub").write_bytes(b"x")
        (self.root / "notes.txt").write_text("x")
        scan = rules.scan_folder(self.root)
        self.assertEqual(scan.kind, "epubs")
        self.assertEqual([p.name for p in scan.epubs], ["a.epub", "b.epub"])

    def test_library_with_series_wins_over_loose_epubs(self):
        (self.root / "x.epub").write_bytes(b"x")
        s = self.root / "Saga"
        s.mkdir()
        (s / "series.json").write_text("{}", encoding="utf-8")
        self.assertEqual(rules.scan_folder(self.root).kind, "library")

    def test_hidden_series_folder_is_not_a_series(self):
        s = self.root / ".deleted"
        s.mkdir()
        (s / "series.json").write_text("{}", encoding="utf-8")
        self.assertEqual(rules.scan_folder(self.root).kind, "library")

    def test_empty_new_and_file(self):
        self.assertEqual(rules.scan_folder(self.root).kind, "library")
        self.assertEqual(rules.scan_folder(self.root / "nope").kind, "new")
        f = self.root / "f.txt"
        f.write_text("x")
        self.assertEqual(rules.scan_folder(f).kind, "invalid")


class Probe(Tmp):
    def test_probe_leaves_nothing_behind(self):
        self.assertEqual(rules.probe_folder(self.root), "")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_probe_of_a_file(self):
        f = self.root / "f.txt"
        f.write_text("x")
        self.assertIn("file", rules.probe_folder(f))

    def test_probe_without_rights(self):
        with mock.patch.object(Path, "write_text", side_effect=PermissionError(13, "denied")):
            self.assertIn("permission", rules.probe_folder(self.root))

    def test_probe_missing_drive(self):
        self.assertIn("does not exist", rules.probe_folder(self.root / "no" / "such"))

    def test_prepare_creates_a_new_folder(self):
        created, problem = rules.prepare_library(self.root / "new" / "lib")
        self.assertEqual((created, problem), (True, ""))
        self.assertTrue((self.root / "new" / "lib").is_dir())

    def test_prepare_removes_what_it_created_when_the_probe_fails(self):
        target = self.root / "lib"
        with mock.patch.object(rules, "probe_folder", return_value="there is no permission to write there"):
            created, problem = rules.prepare_library(target)
        self.assertTrue(problem)
        self.assertFalse(created)
        self.assertFalse(target.exists())

    def test_prepare_under_a_file(self):
        f = self.root / "f.txt"
        f.write_text("x")
        created, problem = rules.prepare_library(f / "lib")
        self.assertTrue(problem)


class DeletedNames(Tmp):
    def test_stamp_format(self):
        self.assertRegex(rules.stamp(time.time()), r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d$")

    def test_series_path_and_clash(self):
        p = rules.deleted_series_path(self.root, "Saga", "2026-11-16_10-00-00")
        self.assertEqual(p, self.root / ".deleted" / "Saga-2026-11-16_10-00-00")
        p.mkdir(parents=True)
        p2 = rules.deleted_series_path(self.root, "Saga", "2026-11-16_10-00-00")
        self.assertEqual(p2.name, "Saga-2026-11-16_10-00-00 (2)")
        p2.mkdir()
        self.assertEqual(rules.deleted_series_path(self.root, "Saga", "2026-11-16_10-00-00").name,
                         "Saga-2026-11-16_10-00-00 (3)")

    def test_volume_path(self):
        p = rules.deleted_volume_path(self.root, "Saga", "Vol 1", "S")
        self.assertEqual(p, self.root / ".deleted" / "Saga" / "Vol 1-S")


class VolumeFiles(Tmp):
    def make(self, stem="Vol 1"):
        s = self.root / "Saga"
        for rel in ("samples/%s/a.jsonl" % stem, "chapters/%s/00000_c.jsonl" % stem,
                    ".state/frontier_%s.json" % stem, ".state/frontier_chunks_%s.json" % stem,
                    ".state/check_%s.json" % stem, ".state/chapters-%s.json" % stem,
                    ".state/ignore_%s.json" % stem, ".state/job.json", ".state/pool.json",
                    "books/%s.epub" % stem, "books/Other.epub", "chapters/Other/x.jsonl"):
            f = s / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
        return s

    def test_list_and_order(self):
        s = self.make()
        items = rules.volume_items(s, "Vol 1", safe_name, job_book="Vol 1")
        self.assertEqual(items, ["samples/Vol 1", "chapters/Vol 1", ".state/frontier_Vol 1.json",
                                 ".state/frontier_chunks_Vol 1.json", ".state/check_Vol 1.json",
                                 ".state/chapters-Vol 1.json", ".state/ignore_Vol 1.json", ".state/job.json",
                                 "books/Vol 1.epub"])
        self.assertEqual(items[-1], "books/Vol 1.epub")

    def test_job_record_of_another_book_stays(self):
        s = self.make()
        self.assertNotIn(".state/job.json", rules.volume_items(s, "Vol 1", safe_name, job_book="Other"))
        self.assertNotIn(".state/job.json", rules.volume_items(s, "Vol 1", safe_name, job_book=None))

    def test_only_existing_files_are_listed(self):
        s = self.root / "Saga"
        (s / "books").mkdir(parents=True)
        (s / "books" / "A.epub").write_text("x")
        self.assertEqual(rules.volume_items(s, "A", safe_name), ["books/A.epub"])


class AddBookRules(unittest.TestCase):
    def test_new_name_is_copied(self):
        self.assertEqual(addbook.plan_add("Vol 1", {}, "h", safe_name), addbook.AddPlan("copy", "Vol 1"))

    def test_same_name_same_content_is_a_duplicate(self):
        plan = addbook.plan_add("Vol 1", {"Vol 1": "h"}, "h", safe_name)
        self.assertEqual(plan, addbook.AddPlan("duplicate", "Vol 1"))

    def test_same_name_other_content_gets_a_number(self):
        self.assertEqual(addbook.plan_add("Vol 1", {"Vol 1": "a"}, "b", safe_name).name, "Vol 1 (2)")
        self.assertEqual(addbook.plan_add("Vol 1", {"Vol 1": "a", "Vol 1 (2)": "b"}, "c", safe_name).name,
                         "Vol 1 (3)")

    def test_a_numbered_copy_with_the_same_content_is_a_duplicate(self):
        plan = addbook.plan_add("Vol 1", {"Vol 1": "a", "Vol 1 (2)": "b"}, "b", safe_name)
        self.assertEqual(plan, addbook.AddPlan("duplicate", "Vol 1 (2)"))

    def test_names_compare_without_case(self):
        self.assertEqual(addbook.plan_add("vol 1", {"Vol 1": "a"}, "b", safe_name).name, "vol 1 (2)")

    def test_a_long_stem_keeps_the_whole_name_within_80(self):
        stem = "x" * 120
        first = addbook.plan_add(stem, {}, "a", safe_name).name
        self.assertEqual(len(first), 80)
        second = addbook.plan_add(stem, {first: "a"}, "b", safe_name).name
        self.assertEqual(second, "x" * 76 + " (2)")
        self.assertEqual(len(second), 80)
        third = addbook.plan_add(stem, {first: "a", second: "b"}, "c", safe_name).name
        self.assertEqual(len(third), 80)
        self.assertEqual(addbook.plan_add(stem, {first: "a"}, "a", safe_name).action, "duplicate")

    def test_series_name_problems(self):
        c = safe_name
        self.assertTrue(addbook.series_name_problem("  ", c, [], []))
        self.assertTrue(addbook.series_name_problem("Saga", c, ["saga"], []))               # folder exists
        self.assertTrue(addbook.series_name_problem("The: Saga", c, ["The_ Saga"], []))     # cleaned name collides
        self.assertTrue(addbook.series_name_problem("Epic", c, [], ["epic"]))               # shown name used
        self.assertEqual(addbook.series_name_problem("New", c, ["Saga"], ["Saga"]), "")

    def test_rename_problems(self):
        others = [("/a", "Alpha"), ("/b", "Beta")]
        self.assertEqual(addbook.rename_problem("Alpha", "/a", others), "")                 # its own name
        self.assertTrue(addbook.rename_problem("beta", "/a", others))
        self.assertTrue(addbook.rename_problem(" ", "/a", others))
        self.assertEqual(addbook.rename_problem("Gamma", "/a", others), "")


class Busy(unittest.TestCase):
    def test_job_states(self):
        self.assertEqual(busy.block_reason(JobView(state="running", book="V"), series_path="/s"), busy.RUNNING)
        self.assertEqual(busy.block_reason(JobView(state="waiting_quota", book="V"), series_path="/s"),
                         busy.WAITING)
        self.assertEqual(busy.block_reason(JobView(state="running", foreign=True, book="V"), series_path="/s"),
                         busy.ELSEWHERE)
        self.assertEqual(busy.block_reason(JobView(state="stopped", book="V"), series_path="/s"), "")
        self.assertEqual(busy.block_reason(JobView(), series_path="/s"), "")

    def test_a_job_on_another_volume_does_not_block_a_volume(self):
        v = JobView(state="running", book="Vol 2")
        self.assertEqual(busy.block_reason(v, series_path="/s", volume="Vol 1"), "")
        self.assertEqual(busy.block_reason(v, series_path="/s", volume="Vol 2"), busy.RUNNING)
        self.assertEqual(busy.block_reason(v, series_path="/s"), busy.RUNNING)

    def test_operations(self):
        ops = [("/s", "Vol 1")]
        self.assertEqual(busy.block_reason(None, ops, "/s", "Vol 1"), busy.OPERATION)
        self.assertEqual(busy.block_reason(None, ops, "/s", None), busy.OPERATION)
        self.assertEqual(busy.block_reason(None, ops, "/s", "Vol 2"), "")
        self.assertEqual(busy.block_reason(None, ops, "/other", None), "")
        self.assertEqual(busy.block_reason(None, [("/s", None)], "/s", "Vol 2"), busy.OPERATION)

    def test_extra_reasons_hook(self):
        self.assertEqual(busy.block_reason(None, extra=["", "queued"]), "queued")

    def test_library_change(self):
        self.assertEqual(busy.library_change_reason([JobView(), JobView(state="stopped")]), "")
        self.assertTrue(busy.library_change_reason([JobView(), JobView(state="waiting_quota")]))
        self.assertTrue(busy.library_change_reason([JobView(foreign=True)]))


class WinStateLibrary(Tmp):
    def test_volume_memory_and_forget(self):
        ws = WinState(Settings(self.root))
        ws.set_volume_selection("/s", "V1", [(0, 4), (9, 9)])
        ws.set_volume_selection("/s", "V2", [(1, 2)])
        ws.set_last_volume("/s", "V2")
        again = WinState(Settings(self.root))
        self.assertEqual(again.volume_selection("/s", "V1"), [[0, 4], [9, 9]])
        self.assertEqual(again.last_volume("/s"), "V2")
        again.clear_volume_selection("/s", "V2")
        self.assertIsNone(again.volume_selection("/s", "V2"))
        self.assertEqual(again.last_volume("/s"), "")
        self.assertEqual(again.volume_selection("/s", "V1"), [[0, 4], [9, 9]])
        again.forget_series("/s")
        self.assertIsNone(again.volume_selection("/s", "V1"))


# ---------------------------------------------------------------- disk operations
class Ops(Tmp):
    def setUp(self):
        super().setUp()
        self.lib = self.root / "lib"
        self.lib.mkdir()
        self.ext = self.root / "ext"
        self.ext.mkdir()

    def epub(self, name, pages=("<p>One</p>", "<p>Two</p>")):
        p = self.ext / name
        write_epub(p, list(pages))
        return p

    def tree(self, base=None):
        base = Path(base or self.lib)
        return sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*"))

    def make_series(self, name="Saga", volumes=("Vol 1",)):
        res = None
        for i, v in enumerate(volumes):
            f = self.epub(v + ".epub", ("<p>%s %d</p>" % (v, i),))
            res = libraryops.add_book(self.lib, f, "new" if i == 0 else "volume", res.series if res else None, name)
        return Path(res.series)


class AddBookOps(Ops):
    def test_new_series(self):
        f = self.epub("My Book.epub")
        r = libraryops.add_book(self.lib, f, "new", None, "My Saga")
        self.assertEqual((r.kind, r.volume), ("created", "My Book"))
        s = Path(r.series)
        self.assertEqual(s.name, "My Saga")
        data = json.loads((s / "series.json").read_text(encoding="utf-8"))
        self.assertIs(data["target_chosen"], False)
        self.assertEqual(data["name"], "My Saga")
        self.assertTrue((s / "books" / "My Book.epub").is_file())
        self.assertTrue(f.is_file(), "the original is never touched")
        self.assertEqual([p.name for p in (s / "books").iterdir()], ["My Book.epub"])

    def test_volume(self):
        s = self.make_series()
        r = libraryops.add_book(self.lib, self.epub("Vol 2.epub", ("<p>x2</p>",)), "volume", str(s))
        self.assertEqual((r.kind, r.volume), ("added", "Vol 2"))
        self.assertEqual(sorted(p.stem for p in (s / "books").glob("*.epub")), ["Vol 1", "Vol 2"])

    def test_same_file_twice_is_not_copied(self):
        s = self.make_series()
        again = self.ext / "Vol 1.epub"
        r = libraryops.add_book(self.lib, again, "volume", str(s))
        self.assertEqual((r.kind, r.volume), ("duplicate", "Vol 1"))
        self.assertEqual([p.name for p in (s / "books").iterdir()], ["Vol 1.epub"])

    def test_same_name_other_content_becomes_two(self):
        s = self.make_series()
        other = self.ext / "other"
        other.mkdir()
        write_epub(other / "Vol 1.epub", ["<p>different</p>", "<p>other</p>"])
        r = libraryops.add_book(self.lib, other / "Vol 1.epub", "volume", str(s))
        self.assertEqual((r.kind, r.volume), ("added", "Vol 1 (2)"))
        self.assertTrue((s / "books" / "Vol 1 (2).epub").is_file())
        r2 = libraryops.add_book(self.lib, other / "Vol 1.epub", "volume", str(s))
        self.assertEqual((r2.kind, r2.volume), ("duplicate", "Vol 1 (2)"))

    def test_long_stem(self):
        f = self.epub("x" * 120 + ".epub")
        r = libraryops.add_book(self.lib, f, "new", None, "Long")
        self.assertEqual(len(r.volume), 80)
        self.assertTrue((Path(r.series) / "books" / (r.volume + ".epub")).is_file())

    def test_unreadable_file_creates_nothing(self):
        bad = self.ext / "bad.epub"
        bad.write_text("not a zip")
        with self.assertRaises(libraryops.OpError) as cm:
            libraryops.add_book(self.lib, bad, "new", None, "Saga")
        self.assertIn("not an EPUB", str(cm.exception))
        self.assertEqual(self.tree(), [])

    def test_series_name_rules(self):
        self.make_series("Saga")
        f = self.epub("b.epub", ("<p>b</p>",))
        for name in ("Saga", "saga", "  "):
            with self.assertRaises(libraryops.OpError):
                libraryops.add_book(self.lib, f, "new", None, name)
        (self.lib / "Taken").mkdir()                       # a folder without series.json still counts
        with self.assertRaises(libraryops.OpError):
            libraryops.add_book(self.lib, f, "new", None, "Taken")
        s = self.make_series("Second", ("S1",))
        data = json.loads((s / "series.json").read_text(encoding="utf-8"))
        data["name"] = "Shown As"
        (s / "series.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(libraryops.OpError):
            libraryops.add_book(self.lib, f, "new", None, "shown as")

    def fail_at(self, target, attr, k):
        """Make the k-th call (1-based) of `target.attr` raise OSError."""
        calls = [0]
        real = getattr(target, attr)

        def wrapper(*a, **kw):
            calls[0] += 1
            if calls[0] == k:
                raise OSError(13, "injected failure")
            return real(*a, **kw)
        return mock.patch.object(target, attr, wrapper)

    def test_new_series_failure_at_every_step_leaves_nothing(self):
        for attr in ("makedirs", "copy", "replace", "create_series"):
            with self.subTest(step=attr):
                f = self.epub("n.epub", ("<p>n</p>",))
                with self.fail_at(libraryops.fs, attr, 1):
                    with self.assertRaises(libraryops.OpError) as cm:
                        libraryops.add_book(self.lib, f, "new", None, "Fresh")
                self.assertIn("Nothing was left", str(cm.exception))
                self.assertEqual(self.tree(), [], "library is empty again")
                self.assertEqual(model.list_series_task(None, self.lib), [])

    def test_volume_failure_never_shows_a_half_volume(self):
        s = self.make_series()
        before = self.tree()
        for attr in ("copy", "replace"):
            with self.subTest(step=attr):
                f = self.epub("Vol 2.epub", ("<p>v2</p>",))
                with self.fail_at(libraryops.fs, attr, 1):
                    with self.assertRaises(libraryops.OpError):
                        libraryops.add_book(self.lib, f, "volume", str(s))
                self.assertEqual(self.tree(), before)
                info = model.list_series_task(None, self.lib)[0]
                self.assertEqual(info.books, ("Vol 1",))


class RemoveOps(Ops):
    def fill(self, s, stem):
        for rel in ("samples/%s/a.jsonl" % stem, "chapters/%s/00000_c.jsonl" % stem,
                    ".state/frontier_%s.json" % stem, ".state/check_%s.json" % stem, ".state/job.json"):
            f = s / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(stem)
        (s / ".state" / "pool.json").write_text("{}")
        (s / "out").mkdir(exist_ok=True)
        (s / "out" / "done.epub").write_text("x")

    def test_remove_volume_moves_its_files_and_its_label(self):
        s = self.make_series("Saga", ("Vol 1", "Vol 2"))
        self.fill(s, "Vol 1")
        libraryops.rename_volume(s, "Vol 1", "First")
        before_other = (s / "books" / "Vol 2.epub").read_bytes()
        dest = libraryops.remove_volume(self.lib, s, "Vol 1", job_book="Vol 1", now=1.0)
        self.assertEqual(dest.parent, self.lib / ".deleted" / "Saga")
        self.assertFalse((s / "books" / "Vol 1.epub").exists())
        self.assertFalse((s / "chapters" / "Vol 1").exists())
        self.assertFalse((s / ".state" / "job.json").exists())
        self.assertTrue((s / ".state" / "pool.json").exists())
        self.assertTrue((s / "out" / "done.epub").exists())
        self.assertEqual((s / "books" / "Vol 2.epub").read_bytes(), before_other)
        self.assertTrue((dest / "books" / "Vol 1.epub").is_file())
        self.assertTrue((dest / "chapters" / "Vol 1" / "00000_c.jsonl").is_file())
        data = json.loads((s / "series.json").read_text(encoding="utf-8"))
        self.assertNotIn("Vol 1", data.get("volume_labels", {}))
        info = model.list_series_task(None, self.lib)[0]
        self.assertEqual(info.books, ("Vol 2",))

    def test_failure_at_each_step_puts_everything_back(self):
        s = self.make_series("Saga", ("Vol 1", "Vol 2"))
        self.fill(s, "Vol 1")
        libraryops.rename_volume(s, "Vol 1", "First")
        before = self.tree()
        series_json = (s / "series.json").read_text(encoding="utf-8")
        items = rules.volume_items(s, "Vol 1", safe_name, "Vol 1")
        steps = len(items)
        for k in range(1, steps + 1):                     # every move, then the series.json write
            with self.subTest(failing_move=k):
                real = libraryops.fs.replace
                n = [0]

                def flaky(src, dst, n=n, k=k, real=real):
                    n[0] += 1
                    if n[0] == k:
                        raise OSError(13, "injected failure")
                    return real(src, dst)
                with mock.patch.object(libraryops.fs, "replace", flaky):
                    with self.assertRaises(libraryops.OpError) as cm:
                        libraryops.remove_volume(self.lib, s, "Vol 1", job_book="Vol 1", now=2.0)
                self.assertIn("still in the series", str(cm.exception))
                self.assertEqual([p for p in self.tree() if ".deleted" not in p],
                                 [p for p in before if ".deleted" not in p])
                self.assertEqual((s / "series.json").read_text(encoding="utf-8"), series_json)
                self.assertEqual(model.list_series_task(None, self.lib)[0].books, ("Vol 1", "Vol 2"))
        with mock.patch.object(libraryops.fs, "update_series", side_effect=OSError(13, "injected failure")):
            with self.assertRaises(libraryops.OpError):
                libraryops.remove_volume(self.lib, s, "Vol 1", job_book="Vol 1", now=3.0)
        self.assertTrue((s / "books" / "Vol 1.epub").is_file(), "series.json failure moved the files back")
        self.assertTrue((s / "chapters" / "Vol 1" / "00000_c.jsonl").is_file())

    def test_delete_series_in_one_move(self):
        s = self.make_series()
        self.fill(s, "Vol 1")
        dest = libraryops.delete_series(self.lib, s, now=1.0)
        self.assertFalse(s.exists())
        self.assertTrue((dest / "books" / "Vol 1.epub").is_file())
        self.assertEqual(dest.parent, self.lib / ".deleted")
        self.assertEqual(model.list_series_task(None, self.lib), [], "the series list ignores .deleted")
        # the same name deleted again at the same second -> (2)
        s2 = self.make_series()
        dest2 = libraryops.delete_series(self.lib, s2, now=1.0)
        self.assertNotEqual(dest, dest2)
        self.assertTrue(dest2.name.endswith("(2)"))

    def test_delete_failure_leaves_the_series(self):
        s = self.make_series()
        before = self.tree()
        with mock.patch.object(libraryops.fs, "replace", side_effect=PermissionError(13, "in use")):
            with self.assertRaises(libraryops.OpError) as cm:
                libraryops.delete_series(self.lib, s)
        self.assertIn("still in the library", str(cm.exception))
        self.assertEqual([p for p in self.tree() if not p.startswith(".deleted")], before)


class RenameOps(Ops):
    def test_rename_series_changes_only_the_shown_name(self):
        s = self.make_series("Saga")
        libraryops.rename_series(s, "The Grand Saga")
        info = model.list_series_task(None, self.lib)[0]
        self.assertEqual((info.name, Path(info.path).name), ("The Grand Saga", "Saga"))

    def test_rename_volume_label_and_back(self):
        s = self.make_series("Saga", ("Vol 1",))
        libraryops.rename_volume(s, "Vol 1", "First")
        info = model.list_series_task(None, self.lib)[0]
        self.assertEqual((info.books, info.label_of("Vol 1")), (("Vol 1",), "First"))
        libraryops.rename_volume(s, "Vol 1", "")
        info = model.list_series_task(None, self.lib)[0]
        self.assertEqual(info.label_of("Vol 1"), "Vol 1")

    def test_a_failed_write_changes_nothing(self):
        s = self.make_series("Saga")
        with mock.patch.object(libraryops.fs, "update_series", side_effect=OSError(13, "read-only")):
            with self.assertRaises(libraryops.OpError):
                libraryops.rename_series(s, "X")
        self.assertEqual(model.list_series_task(None, self.lib)[0].name, "Saga")


class ListSeries(Ops):
    def test_natural_volume_order_hidden_folders_and_broken_series(self):
        s = self.make_series("Saga", ("Vol 10", "Vol 2", "Vol 1"))
        (self.lib / ".deleted" / "Old").mkdir(parents=True)
        (self.lib / ".deleted" / "Old" / "series.json").write_text("{}")
        (self.lib / ".hidden").mkdir()
        bad = self.lib / "Damaged"
        bad.mkdir()
        (bad / "series.json").write_text("{ not json", encoding="utf-8")
        infos = model.list_series_task(None, self.lib)
        by = {Path(i.path).name: i for i in infos}
        self.assertEqual(sorted(by), ["Damaged", "Saga"])
        self.assertEqual(by["Saga"].books, ("Vol 1", "Vol 2", "Vol 10"))
        self.assertEqual(by["Damaged"].broken, "series.json is damaged")
        self.assertEqual(by["Damaged"].books, ())
        self.assertEqual(by["Saga"].broken, "")


if __name__ == "__main__":
    unittest.main()
