import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from bbm_gui import jobs, langs

try:
    from . import epubs
except ImportError:
    import epubs

HTML_EN = ('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" dir="ltr"><body lang="en-GB">'
           '<p>x <span lang="fr">bon</span> <a hreflang="en" href="a">a</a> data-lang="en"</p></body></html>')


def members(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


class RelabelTest(unittest.TestCase):
    def test_source_language_attributes_become_the_target(self):
        out = jobs.relabel_language(HTML_EN.encode(), "en", "ru").decode()
        self.assertIn('xml:lang="ru"', out)
        self.assertIn('lang="ru"', out)
        self.assertNotIn("en-GB", out)  # a region of the source language is the source language
        self.assertIn('lang="fr"', out)  # another language stays
        self.assertIn('hreflang="en"', out)  # not a language declaration of the markup
        self.assertIn('data-lang="en"', out)

    def test_package_language(self):
        opf = b'<package xml:lang="en"><metadata><dc:language>en</dc:language><dc:language>de</dc:language></metadata></package>'
        out = jobs.relabel_language(opf, "en", "uk").decode()
        self.assertIn("<dc:language>uk</dc:language><dc:language>de</dc:language>", out)
        self.assertIn('xml:lang="uk"', out)

    def test_same_language_is_not_touched(self):
        with tempfile.TemporaryDirectory() as d:
            path = epubs.write_epub(Path(d) / "a.epub", ["<p>One</p>"])
            self.assertEqual(jobs.relabel_epub(path, "en", "en-US"), 0)


class DeliverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BBM_GUI_DATA"] = self.tmp.name
        self.root = Path(self.tmp.name)
        self.book = self.root / "Book.epub"
        epubs.write_epub(self.book, ["<p>One</p>"])
        # a source page that declares English, as the lab book did
        with zipfile.ZipFile(self.book) as z:
            data = {i.filename: z.read(i) for i in z.infolist()}
        data["OEBPS/ch0.xhtml"] = HTML_EN.encode()
        self.write(self.book, data)

    def tearDown(self):
        os.environ.pop("BBM_GUI_DATA", None)
        self.tmp.cleanup()

    @staticmethod
    def write(path, data):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), data.pop("mimetype", b"application/epub+zip"),
                       compress_type=zipfile.ZIP_STORED)
            for name, blob in data.items():
                z.writestr(name, blob, compress_type=zipfile.ZIP_DEFLATED)

    def make_job(self, mode):
        job = jobs.Job(self.book, mode, langs.resolve("ru"))
        job.prepare()
        shutil.copy2(job.copy, job.out_path)  # the engine's result keeps the source labels
        return job

    def test_translation_only_copy_is_labelled_with_the_target(self):
        job = self.make_job("single")
        before = job.out_path.read_bytes()
        dest = jobs.deliver(job, self.root / "out", "Book_ru")
        got = members(dest)
        self.assertIn(b'xml:lang="ru"', got["OEBPS/ch0.xhtml"])
        self.assertIn(b"<dc:language>ru</dc:language>", got["OEBPS/content.opf"])
        self.assertEqual(job.out_path.read_bytes(), before)  # the job's own file is not touched
        self.assertEqual(self.book.read_bytes(), jobs.Path(self.book).read_bytes())
        self.assertIn(b'xml:lang="en"', members(job.copy)["OEBPS/ch0.xhtml"])
        names = list(zipfile.ZipFile(dest).namelist())
        self.assertEqual(names[0], "mimetype")
        self.assertEqual(zipfile.ZipFile(dest).getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
        self.assertIsNone(zipfile.ZipFile(dest).testzip())
        old = members(job.out_path)
        for name, blob in got.items():  # nothing else changed
            if name not in ("OEBPS/ch0.xhtml", "OEBPS/content.opf"):
                self.assertEqual(blob, old[name], name)

    def test_bilingual_copy_keeps_the_engine_labels(self):
        job = self.make_job("bilingual")
        dest = jobs.deliver(job, self.root / "out", "Book_ru")
        self.assertEqual(dest.read_bytes(), job.out_path.read_bytes())

    def test_source_language_is_read_from_the_package(self):
        self.assertEqual(jobs.source_languages(self.book), ["en"])


if __name__ == "__main__":
    unittest.main()
