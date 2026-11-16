import json
import tempfile
import unittest
from pathlib import Path

from novelcore.htmlscan import scan
from novelcore.store import ChapterLog, Series, chapter_file_name, safe_name, split_target
from novelcore.translate import (GroupTranslator, build_user, check_text, script_share)
from tests.core_support import build_epub


class Chap:
    def __init__(self, index, href):
        self.index, self.href = index, href


def rec(i, sha, status="ok", text="t", **kw):
    return dict({"i": i, "src_sha": sha, "text": text, "model": "m", "at": 1.0, "status": status}, **kw)


class SafeNameTest(unittest.TestCase):
    def test_windows_and_linux_safe(self):
        for raw in ['a:b*c?"d<e>f|g', "con", "NUL.txt", "trailing. ", "x/y\\z", "", "   ", "a" * 200, "tab\tname"]:
            s = safe_name(raw)
            self.assertTrue(s and len(s) <= 60, raw)
            self.assertFalse(set('<>:"/\\|?*\t') & set(s), raw)
            self.assertFalse(s.endswith((" ", ".")))
            self.assertNotIn(s.lower(), {"con", "nul"})

    def test_chapter_file_name_is_flat_and_ordered(self):
        name = chapter_file_name(Chap(7, "OEBPS/Text/ch:1?.xhtml"))
        self.assertTrue(name.startswith("00007_") and name.endswith(".jsonl"))
        self.assertNotIn("/", name)

    def test_split_target(self):
        self.assertEqual(split_target("ru:Russian"), ("ru", "Russian"))
        self.assertEqual(split_target("de"), ("de", "de"))


class ChapterLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "c" / "00001_x.jsonl"

    def test_roundtrip_later_wins_and_failed_is_not_done(self):
        log = ChapterLog(self.path)
        log.append([rec(0, "a", text="one"), rec(1, "b", status="failed", text="", reason="empty")])
        log.append([rec(0, "a", text="two")])
        again = ChapterLog(self.path)
        self.assertEqual(again.done(0, "a")["text"], "two")
        self.assertIsNone(again.done(1, "b"))
        self.assertEqual(again.lookup(1, "b")["reason"], "empty")
        self.assertIsNone(again.done(0, "other-sha"))
        log.append([rec(1, "b", text="fixed")])
        self.assertEqual(ChapterLog(self.path).done(1, "b")["text"], "fixed")

    def test_torn_last_line_is_dropped_and_not_glued(self):
        log = ChapterLog(self.path)
        log.append([rec(0, "a")])
        with open(self.path, "ab") as f:
            f.write(b'{"i": 1, "src_sha": "b", "te')
        again = ChapterLog(self.path)
        self.assertIsNone(again.done(1, "b"))
        again.append([rec(2, "c")])
        third = ChapterLog(self.path)
        self.assertIsNotNone(third.done(0, "a"))
        self.assertIsNotNone(third.done(2, "c"))

    def test_garbage_lines_are_skipped(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'\xff\xfe junk\n[1,2]\n{"x":1}\n' + json.dumps(rec(3, "z")).encode() + b"\n")
        self.assertEqual([r["i"] for r in ChapterLog(self.path).records()], [3])


class SeriesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_create_open_and_layout(self):
        s = Series.create(self.dir, "My: Series?", "ru:Russian")
        for sub in ("books", "chapters", "samples", "out"):
            self.assertTrue((s.path / sub).is_dir())
        self.assertEqual((s.target_tag, s.target_name, s.per_request), ("ru", "Russian", 5))
        s.settings["per_request"] = 10
        s.save_settings()
        self.assertEqual(Series.open(s.path).per_request, 10)
        self.assertIn("Russian", s.system_prompt())
        self.assertNotIn("{language}", s.system_prompt())

    def test_prompt_file_overrides_default(self):
        s = Series.create(self.dir, "S", "ru:Russian")
        (s.path / "prompt.txt").write_text("Translate into {language} now.", encoding="utf-8")
        self.assertEqual(s.system_prompt(), "Translate into Russian now.")

    def test_series_wide_lookup_by_sha(self):
        s = Series.create(self.dir, "S", "ru:Russian")
        ch_a, ch_b = Chap(0, "a.xhtml"), Chap(5, "b.xhtml")
        self.assertIsNone(s.find_done("sha1"))
        s.chapter_log("bookA", ch_a).append([rec(0, "sha1", text="done"), rec(1, "sha2", status="failed", text="")])
        self.assertEqual(s.find_done("sha1")["text"], "done")
        self.assertIsNone(s.find_done("sha2"))
        again = Series.open(s.path)  # rebuilt from disk
        self.assertEqual(again.find_done("sha1")["text"], "done")
        self.assertIsNone(again.find_done("sha2"))
        again.chapter_log("bookB", ch_b).append([rec(9, "sha3", text="later")])
        self.assertEqual(again.find_done("sha3")["text"], "later")

    def test_replaced_record_is_not_reused(self):
        s = Series.create(self.dir, "S", "ru:Russian")
        ch = Chap(0, "a.xhtml")
        log = s.chapter_log("bookA", ch)
        log.append([rec(0, "sha1", text="old", at=1.0), rec(1, "sha2", text="two")])
        self.assertEqual(s.find_done("sha1")["text"], "old")  # index is built
        log.append([rec(0, "sha1", status="failed", text="")])
        self.assertIsNone(s.find_done("sha1"))  # already-indexed series
        self.assertEqual(s.find_done("sha2")["text"], "two")
        self.assertIsNone(Series.open(s.path).find_done("sha1"))  # fresh series
        log.append([rec(0, "sha1", text="new", at=2.0)])
        self.assertEqual(s.find_done("sha1")["text"], "new")
        self.assertEqual(Series.open(s.path).find_done("sha1")["text"], "new")

    def test_pending_retry_hash_is_not_reused_until_finished(self):
        s = Series.create(self.dir, "S", "ru:Russian")
        a, b = s.chapter_log("bookA", Chap(0, "a.xhtml")), s.chapter_log("bookA", Chap(1, "b.xhtml"))
        a.append([rec(0, "sha1", text="old")])
        b.append([rec(4, "sha1", text="same hash elsewhere")])
        self.assertIsNotNone(s.find_done("sha1"))
        a.append([rec(0, "sha1", status="retry", text="", prev="old")])
        self.assertIsNone(s.find_done("sha1"))  # a block with this hash waits for its retry
        self.assertIsNone(Series.open(s.path).find_done("sha1"))
        a.append([rec(0, "sha1", text="again")])  # the retry finished
        self.assertIsNotNone(s.find_done("sha1"))
        self.assertIsNotNone(Series.open(s.path).find_done("sha1"))

    def test_samples_are_a_separate_tree(self):
        s = Series.create(self.dir, "S", "ru:Russian")
        s.sample_log("b", Chap(0, "a.xhtml")).append([rec(0, "x")])
        self.assertIsNone(s.find_done("x"))
        self.assertEqual(list((s.path / "chapters").rglob("*.jsonl")), [])
        self.assertEqual(len(list((s.path / "samples").rglob("*.jsonl"))), 1)

    def test_add_book_and_open(self):
        s = Series.create(self.dir, "S", "ru:Russian")
        build_epub(self.dir / "x y.epub", 2, 2)
        name = s.add_book(self.dir / "x y.epub")
        self.assertEqual(s.book_names(), [name])
        with s.open_book() as b:
            self.assertEqual(len(b.chapters), 2)


class TranslateUnitTest(unittest.TestCase):
    def blocks(self, *texts):
        html = "<body>" + "".join(f"<p>{t}</p>" for t in texts) + "</body>"
        return scan(html).blocks

    def test_script_share_and_unknown_tag(self):
        self.assertEqual(script_share("Привет мир", "ru"), 1.0)
        self.assertEqual(script_share("Hello мир", "uk-UA"), 3 / 8)
        self.assertIsNone(script_share("Hello", "de"))
        self.assertEqual(script_share("123 ...", "ru"), 1.0)

    def test_check_text_rules(self):
        short, long_ = self.blocks("Hi there", "x" * 10 + " word" * 20)
        self.assertEqual(check_text(short, "", "ru"), "empty")
        self.assertIsNone(check_text(short, "Hello", "ru"))  # short blocks skip script and length
        self.assertEqual(check_text(long_, "latin text " * 10, "ru"), "script")
        self.assertEqual(check_text(long_, "Да", "ru"), "length")
        self.assertEqual(check_text(long_, "я" * 400, "ru"), "length")
        self.assertIsNone(check_text(long_, "я" * 100, "ru"))
        self.assertIsNone(check_text(long_, "latin text " * 10, "de"))

    def test_build_user_sections(self):
        items = [{"id": 1, "text": "Hello"}]
        bare = build_user([], [], items)
        self.assertNotIn("TERMS", bare)
        self.assertNotIn("CONTEXT", bare)
        self.assertTrue(bare.startswith("TEXT"))
        full = build_user(["A -> Б"], [("src", "tr")], items)
        self.assertLess(full.index("TERMS"), full.index("CONTEXT"))
        self.assertLess(full.index("CONTEXT"), full.index("\nTEXT"))
        self.assertIn("A -> Б", full)
        self.assertIn('[{"id": 1, "text": "Hello"}]', full)

    def test_group_translator_counts_without_network(self):
        from novelcore.gemini import Result
        blocks = self.blocks("one two three four five six seven eight nine ten eleven", "short one here ok fine")

        def ask(system, user, schema):
            import json as j
            items = j.loads(user.rsplit("\n", 1)[1])
            return Result(text="", json=[{"id": it["id"], "text": "да " * 12} for it in items])

        got, failed = [], []
        out = GroupTranslator(ask, "sys", "ru", 5).run(blocks, lambda b, t, f: got.append((b.index, f)),
                                                       lambda b, r: failed.append(r))
        self.assertEqual((out.ok, out.failed, out.requests), (2, 0, 1))
        self.assertEqual([i for i, _ in got], [0, 1])


if __name__ == "__main__":
    unittest.main()
