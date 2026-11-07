import os
import tempfile
import unittest
from pathlib import Path

from bbm_gui import jobs, langs


class JobIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = os.environ.get("BBM_GUI_DATA")
        os.environ["BBM_GUI_DATA"] = self.tmp.name
        self.book = Path(self.tmp.name) / "The Book.epub"
        self.book.write_bytes(b"x")

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("BBM_GUI_DATA", None)
        else:
            os.environ["BBM_GUI_DATA"] = self.old_env
        self.tmp.cleanup()

    def job(self, to, mode="single"):
        return jobs.Job(self.book, mode, langs.resolve(to))

    def test_spellings_give_one_folder(self):
        dirs = {self.job(t).dir for t in ("ru", "RU", "Russian", "russian", "ru:Russian")}
        self.assertEqual(len(dirs), 1)
        self.assertTrue(dirs.pop().name.endswith("-single-ru"))
        self.assertNotEqual(self.job("ru").dir, self.job("ru", "bilingual").dir)
        self.assertNotEqual(self.job("ru").dir, self.job("uk").dir)

    def test_output_name_keeps_display_name(self):
        self.assertEqual(self.job("ru").language, "Russian")
        self.assertEqual(jobs.target_name(None, self.book, self.job("ru").language, "single"), "The Book_Russian_translation")

    def test_old_folder_is_adopted_with_its_checkpoint(self):
        probe = self.job("ru")
        prefix = probe.dir.name[:-len("ru")]
        old = probe.dir.parent / (prefix + "Russian")
        old.mkdir(parents=True)
        (old / ".The Book.temp.bin").write_bytes(b"checkpoint")
        (old / "run.log").write_text("log", encoding="utf-8")
        job = self.job("russian")
        self.assertEqual(job.dir.name, prefix + "ru")
        self.assertFalse(old.exists())
        self.assertEqual((job.dir / ".The Book.temp.bin").read_bytes(), b"checkpoint")
        self.assertTrue((job.dir / "run.log").is_file())
        self.assertEqual(self.job("Russian").dir, job.dir)  # the second call changes nothing

    def test_adoption_skips_other_languages_and_modes(self):
        probe = self.job("ru")
        prefix = probe.dir.name[:-len("ru")]
        other = probe.dir.parent / (prefix + "Ukrainian")
        other.mkdir(parents=True)
        bi = probe.dir.parent / (probe.dir.name.replace("-single-", "-bilingual-")[:-2] + "Russian")
        bi.mkdir()
        job = self.job("ru")
        self.assertEqual(job.dir.name, prefix + "ru")
        self.assertTrue(other.exists() and bi.exists())

    def test_unknown_language_keeps_its_typed_name(self):
        self.assertTrue(self.job("Klingon").dir.name.endswith("-single-Klingon"))


if __name__ == "__main__":
    unittest.main()
