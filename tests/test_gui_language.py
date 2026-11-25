"""The target and source language of a series (window_spec 3.1-3.5, 7.12, 13.11)."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from novelcore import Series
from novelcore.terms import FILE_NAME as TERMS_FILE
from novelcore.terms import TermBase
from novelgui import busy, langrules, model
from novelgui.jobstate import JobView


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def info(self, path):
        return [i for i in model.list_series_task(None, self.root) if i.path == str(path)][0]


class Reader(Tmp):
    def test_absent_flag_counts_as_chosen(self):
        s = Series.create(self.root, "Old", "ru:Russian")
        self.assertEqual(model.series_language(self.info(s.path)), "ru:Russian")

    def test_false_flag_means_not_chosen(self):
        s = Series.create(self.root, "New", "ru:Russian", target_chosen=False)
        info = self.info(s.path)
        self.assertIsNone(model.series_language(info))
        self.assertFalse(info.chosen)

    def test_no_series_and_empty_target(self):
        self.assertIsNone(model.series_language(None))
        s = Series.create(self.root, "Empty", "")
        self.assertIsNone(model.series_language(self.info(s.path)))


class Writer(Tmp):
    def test_set_writes_target_and_flag_once(self):
        s = Series.create(self.root, "New", "ru:Russian", target_chosen=False)
        model.set_series_language(s.path, "de:German")
        data = json.loads((s.path / "series.json").read_text(encoding="utf-8"))
        self.assertEqual((data["target"], data["target_chosen"]), ("de:German", True))
        info = self.info(s.path)
        self.assertEqual(model.series_language(info), "de:German")
        self.assertEqual(info.tag, "de")

    def test_with_language_matches_what_the_list_reads(self):
        s = Series.create(self.root, "New", "ru:Russian", target_chosen=False)
        before = self.info(s.path)
        model.set_series_language(s.path, "pl:Polish")
        self.assertEqual(model.with_language(before, "pl:Polish"), self.info(s.path))

    def test_empty_tag_refused(self):
        s = Series.create(self.root, "New", "ru:Russian")
        with self.assertRaises(ValueError):
            model.set_series_language(s.path, ":x")


class Lock(Tmp):
    def test_nothing_done_is_free(self):
        s = Series.create(self.root, "S", "ru:Russian")
        self.assertEqual(model.language_lock(s.path), (False, False))

    def test_confirmed_term_locks(self):
        s = Series.create(self.root, "S", "ru:Russian")
        base = TermBase.load(s.path / TERMS_FILE, "ru")
        base.add("Arthur", status="new", tr="Артур")
        base.add("Merlin", status="confirmed", tr="Мерлин")
        base.save()
        self.assertEqual(model.language_lock(s.path), (False, True))

    def test_only_new_terms_do_not_lock(self):
        s = Series.create(self.root, "S", "ru:Russian")
        base = TermBase.load(s.path / TERMS_FILE, "ru")
        base.add("Arthur", status="new", tr="Артур")
        base.save()
        self.assertEqual(model.language_lock(s.path), (False, False))

    def test_translated_block_locks_failed_does_not(self):
        s = Series.create(self.root, "S", "ru:Russian")
        d = s.path / "chapters" / "book"
        d.mkdir(parents=True)
        (d / "0001.jsonl").write_text(json.dumps({"i": 0, "src_sha": "a", "status": "failed"}) + "\n")
        self.assertEqual(model.language_lock(s.path)[0], False)
        (d / "0002.jsonl").write_text(json.dumps({"i": 0, "src_sha": "a", "text": "x", "status": "ok"}) + "\n")
        self.assertEqual(model.language_lock(s.path)[0], True)

    def test_reasons(self):
        self.assertEqual(langrules.lock_reason(False, False), "")
        self.assertTrue(langrules.lock_reason(True, False))
        self.assertTrue(langrules.lock_reason(False, True))


class Menu(unittest.TestCase):
    T = model.TARGETS

    def test_free_list_has_everything_enabled(self):
        items, dim = langrules.menu(None, self.T, False)
        self.assertEqual(items, ["ru:Russian", "uk:Ukrainian", "pl:Polish", langrules.OTHER])
        self.assertEqual(dim, [])

    def test_locked_list_dims_all_but_current(self):
        items, dim = langrules.menu("uk:Ukrainian", self.T, True)
        self.assertEqual(sorted(dim), sorted(["ru:Russian", "pl:Polish", langrules.OTHER]))
        self.assertNotIn("uk:Ukrainian", dim)

    def test_a_language_set_by_hand_is_listed(self):
        items, dim = langrules.menu("de:German", self.T, True)
        self.assertEqual(items[0], "de:German")
        self.assertNotIn("de:German", dim)

    def test_labels(self):
        self.assertEqual(langrules.label("ru:Russian", self.T), "Russian")
        self.assertEqual(langrules.label("de:German", self.T), "German")
        self.assertEqual(langrules.label("de", self.T), "de")


class Other(unittest.TestCase):
    def test_good(self):
        self.assertEqual(langrules.parse_other(" DE : German "), "de:German")
        self.assertEqual(langrules.parse_other("pt-BR:Brazilian Portuguese"), "pt-br:Brazilian Portuguese")

    def test_bad(self):
        for text in ("", "German", "de", "d:German", "deutsch:German", "de:", "de:12", "de:" + "x" * 41, ":German"):
            self.assertTrue(langrules.problem_other(text), text)
            with self.assertRaises(ValueError):
                langrules.parse_other(text)


class Busy(unittest.TestCase):
    def test_running_waiting_elsewhere_block(self):
        for v in (JobView(state="running"), JobView(state="waiting_quota"), JobView(foreign=True)):
            self.assertTrue(busy.language_reason(v))

    def test_stopped_and_none_do_not(self):
        self.assertEqual(busy.language_reason(JobView(state="stopped")), "")
        self.assertEqual(busy.language_reason(None), "")

    def test_extra_reason_comes_through(self):
        self.assertEqual(busy.language_reason(None, ["queued"]), "queued")


OPF = '<package><metadata xmlns:dc="x"><dc:language>%s</dc:language></metadata></package>'


class Source(Tmp):
    def test_dc_language(self):
        self.assertEqual(langrules.dc_language(OPF % "en-US"), "en")
        self.assertEqual(langrules.dc_language(OPF % "JA"), "ja")
        self.assertEqual(langrules.dc_language(OPF % "und"), "")
        self.assertEqual(langrules.dc_language("<package/>"), "")

    def test_order_book_then_series_then_original(self):
        self.assertEqual(langrules.source_language("ja", "en"), langrules.SourceLang("Japanese", "ja"))
        self.assertEqual(langrules.source_language("", "en"), langrules.SourceLang("English", "en"))
        self.assertEqual(langrules.source_language("", "ko:Korean"), langrules.SourceLang("Korean", "ko"))
        self.assertEqual(langrules.source_language("", ""), langrules.FALLBACK)
        self.assertEqual((langrules.FALLBACK.name, langrules.FALLBACK.tag), ("Original", "src"))
        self.assertEqual(langrules.source_language("xx", "").name, "XX")

    def test_book_file_language_through_the_model(self):
        s = Series.create(self.root, "S", "ru:Russian")
        p = s.path / "books" / "b.epub"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("META-INF/container.xml",
                       '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>')
            z.writestr("OEBPS/c.opf", OPF % "fr")
        self.assertEqual(model.source_language(s.path, "b"), langrules.SourceLang("French", "fr"))
        (s.path / "books" / "none.epub").write_bytes(b"not a zip")
        self.assertEqual(model.source_language(s.path, "none"), langrules.FALLBACK)
        s.settings["source_lang"] = "en"
        s.save_settings()
        self.assertEqual(model.source_language(s.path, "none"), langrules.SourceLang("English", "en"))


if __name__ == "__main__":
    unittest.main()
