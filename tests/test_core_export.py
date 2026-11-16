"""Cut export: only the selected chapters, with navigation, resources and title cut to match."""

import hashlib
import re
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from novelcore import Series, check, export
from novelcore.exporter import NothingToExport
from novelcore.store import ChapterLog

CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)
PAGE = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
    '<head><title>t</title><link rel="stylesheet" type="text/css" href="style/main.css"/></head>'
    "<body>\n%s\n</body></html>\n"
)
CHAPTERS = 6


def chapter_html(n: int) -> str:
    body = f"<h1>Chapter {n}</h1>\n<p>Body {n} one.</p>\n<p>Body {n} two.</p>"
    if n == 1:
        body += ('\n<p>See <a href="ch0.xhtml">back</a> and <a href="ch4.xhtml#x">ahead</a>, '
                 '<a href="ch1.xhtml">here</a> and <a href="http://example.com/">web</a>.</p>')
    if n == 2:
        body += '\n<div><img src="images/p2.png" alt=""/></div>'
    if n in (3, 4):
        body += '\n<div><img src="images/shared.png" alt=""/></div>'
    if n == 5:
        body += '\n<div><img src="images/orphan.png" alt=""/></div>'
    return body


def build_book(path, epub3=True, ncx=True, nav_in_spine=False, labels=None, nested=True):
    labels = labels or {}

    def lab(n):
        return labels.get(n, f"Chapter {n}")

    docs = {"cover.xhtml": '<div><img src="images/cover.jpg" alt=""/></div>'}
    links = "".join(f'<li><a href="ch{n}.xhtml">{lab(n)}</a></li>' for n in range(CHAPTERS)) * 2
    docs["toc1.xhtml"] = f"<ol>{links}</ol>"
    for n in range(CHAPTERS):
        docs[f"ch{n}.xhtml"] = chapter_html(n)
    items = ['<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
             '<item id="toc1" href="toc1.xhtml" media-type="application/xhtml+xml"/>']
    items += [f'<item id="ch{n}" href="ch{n}.xhtml" media-type="application/xhtml+xml"/>' for n in range(CHAPTERS)]
    items += [
        '<item id="css" href="style/main.css" media-type="text/css"/>',
        '<item id="css2" href="style/extra.css" media-type="text/css"/>',
        '<item id="font" href="fonts/f.ttf" media-type="font/ttf"/>',
        '<item id="bg" href="images/bg.png" media-type="image/png"/>',
        '<item id="hbg" href="images/h.png" media-type="image/png"/>',
        '<item id="p2" href="images/p2.png" media-type="image/png"/>',
        '<item id="shared" href="images/shared.png" media-type="image/png"/>',
        '<item id="orphan" href="images/orphan.png" media-type="image/png"/>',
        '<item id="unused" href="images/unused.png" media-type="image/png"/>',
        f'<item id="coverimg" href="images/cover.jpg" media-type="image/jpeg"{" properties=" + chr(34) + "cover-image" + chr(34) if epub3 else ""}/>',
    ]
    spine = ['<itemref idref="cover"/>']
    if epub3:
        items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        if nav_in_spine:
            spine.append('<itemref idref="nav"/>')
    if ncx:
        items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    spine.append('<itemref idref="toc1"/>')
    spine += [f'<itemref idref="ch{n}"/>' for n in range(CHAPTERS)]
    meta = "" if epub3 else '<meta name="cover" content="coverimg"/>'
    opf = (
        '<?xml version="1.0"?>'
        f'<package xmlns="http://www.idpf.org/2007/opf" version="{"3.0" if epub3 else "2.0"}" unique-identifier="id">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>\n'
        f"<dc:title>Long Novel</dc:title><dc:language>en</dc:language>{meta}</metadata>\n"
        f"<manifest>\n{chr(10).join(items)}\n</manifest>\n"
        f'<spine{" toc=" + chr(34) + "ncx" + chr(34) if ncx else ""}>\n{chr(10).join(spine)}\n</spine>\n'
        '<guide><reference type="cover" title="Cover" href="cover.xhtml"/>'
        '<reference type="text" title="Start" href="ch0.xhtml"/></guide>\n</package>'
    )
    if nested:
        nav_ol = (
            f'<li><span>Part One</span><ol><li><a href="ch0.xhtml">{lab(0)}</a></li>'
            f'<li><a href="ch1.xhtml">{lab(1)}</a></li></ol></li>\n'
            f'<li><a href="ch2.xhtml">{lab(2)}</a><ol><li><a href="ch3.xhtml">{lab(3)}</a></li></ol></li>\n'
            f'<li><a href="ch4.xhtml">{lab(4)}</a></li>\n<li><a href="ch5.xhtml">{lab(5)}</a></li>'
        )
        ncx_pts = (
            f'<navPoint id="p1" playOrder="1"><navLabel><text>Part One</text></navLabel><content src="ch0.xhtml"/>'
            f'<navPoint id="n0" playOrder="2"><navLabel><text>{lab(0)}</text></navLabel><content src="ch0.xhtml"/></navPoint>'
            f'<navPoint id="n1" playOrder="3"><navLabel><text>{lab(1)}</text></navLabel><content src="ch1.xhtml"/></navPoint>'
            "</navPoint>\n"
            f'<navPoint id="n2" playOrder="4"><navLabel><text>{lab(2)}</text></navLabel><content src="ch2.xhtml"/>'
            f'<navPoint id="n3" playOrder="5"><navLabel><text>{lab(3)}</text></navLabel><content src="ch3.xhtml"/></navPoint>'
            "</navPoint>\n"
            f'<navPoint id="n4" playOrder="6"><navLabel><text>{lab(4)}</text></navLabel><content src="ch4.xhtml"/></navPoint>\n'
            f'<navPoint id="n5" playOrder="7"><navLabel><text>{lab(5)}</text></navLabel><content src="ch5.xhtml"/></navPoint>'
        )
    else:
        nav_ol = "\n".join(f'<li><a href="ch{n}.xhtml">{lab(n)}</a></li>' for n in range(CHAPTERS))
        ncx_pts = "\n".join(
            f'<navPoint id="n{n}" playOrder="{n + 1}"><navLabel><text>{lab(n)}</text></navLabel>'
            f'<content src="ch{n}.xhtml"/></navPoint>' for n in range(CHAPTERS))
    nav = (
        '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Nav</title></head><body>'
        f'<nav epub:type="toc"><h2>Contents</h2><ol>\n{nav_ol}\n</ol></nav>\n'
        '<nav epub:type="landmarks"><ol><li><a epub:type="cover" href="cover.xhtml">Cover</a></li>'
        '<li><a epub:type="bodymatter" href="ch0.xhtml">Start</a></li></ol></nav></body></html>'
    )
    ncx_doc = (
        '<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        '<head><meta name="dtb:depth" content="2"/></head><docTitle><text>Long Novel</text></docTitle>'
        f"<navMap>\n{ncx_pts}\n</navMap></ncx>"
    )
    css = ('@import "extra.css";\n@font-face{font-family:F;src:url(../fonts/f.ttf)}\n'
           'body{background:url("../images/bg.png")}\n')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        for name, body in docs.items():
            z.writestr("OEBPS/" + name, PAGE % body, compress_type=zipfile.ZIP_DEFLATED)
        if epub3:
            z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        if ncx:
            z.writestr("OEBPS/toc.ncx", ncx_doc, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style/main.css", css)
        z.writestr("OEBPS/style/extra.css", "h1{background:url(../images/h.png)}")
        for name in ("fonts/f.ttf", "images/bg.png", "images/h.png", "images/p2.png", "images/shared.png",
                     "images/orphan.png", "images/unused.png", "images/cover.jpg"):
            z.writestr("OEBPS/" + name, b"\x00" + name.encode())


def translate(text: str, tag: str) -> str:
    if tag.startswith("h"):
        return text.replace("Chapter", "Глава")
    return "Абзац " + text.replace("Body", "Тело")


class ExportCase(unittest.TestCase):
    book_args: dict = {}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        epub = self.dir / "Long Novel.epub"
        build_book(epub, **self.book_args)
        self.series = Series.create(self.dir / "lib", "S", "ru:Russian")
        self.name = self.series.add_book(epub)
        with self.series.open_book(self.name) as b:
            self.ix = {c.href.split("/")[-1]: c.index for c in b.chapters}

    def write_logs(self, names, skip_blocks=(), only=None):
        """Finished translations for the documents `names`; `skip_blocks` = block numbers left out."""
        with self.series.open_book(self.name) as b:
            for n in names:
                ch = b.chapters[self.ix[n]]
                log = ChapterLog(self.series.chapter_log(self.name, ch).path)
                recs = []
                for blk in b.blocks(ch):
                    if blk.index in skip_blocks:
                        continue
                    recs.append({"i": blk.index, "src_sha": blk.sha, "status": "ok",
                                 "text": translate(blk.text, blk.tag)})
                log.append(recs)

    def chapter_files(self, nums):
        return [f"ch{n}.xhtml" for n in nums]

    def sel(self, nums):
        return [self.ix[f"ch{n}.xhtml"] for n in nums]

    def zread(self, path, name):
        with zipfile.ZipFile(path) as z:
            return z.read(name).decode("utf-8")

    def names(self, path):
        with zipfile.ZipFile(path) as z:
            return z.namelist()

    def spine(self, path):
        opf = self.zread(path, "OEBPS/content.opf")
        return re.findall(r'<itemref idref="([^"]+)"', opf)

    def nav_hrefs(self, path):
        """Targets of the table of contents (first nav element)."""
        toc = re.search(r"<nav [^>]*>.*?</nav>", self.zread(path, "OEBPS/nav.xhtml"), re.S).group(0)
        return re.findall(r'href="([^"]+)"', toc)

    def ncx_srcs(self, path):
        return re.findall(r'src="([^"]+)"', self.zread(path, "OEBPS/toc.ncx"))

    def run_export(self, nums, **kw):
        res = export(self.series, self.name, chapters=self.sel(nums), **kw)
        self.assertEqual(res.problems, [], res.problems)
        return res


class TestCutBasics(ExportCase):
    def setUp(self):
        super().setUp()
        self.write_logs(self.chapter_files(range(CHAPTERS)))

    def test_only_selected_chapters_and_what_they_need(self):
        res = self.run_export([1, 2])
        names = self.names(res.path)
        self.assertEqual(names[0], "mimetype")
        with zipfile.ZipFile(res.path) as z:
            self.assertEqual(z.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
        self.assertEqual(self.spine(res.path), ["cover", "ch1", "ch2"])
        for gone in ("ch0", "ch3", "ch4", "ch5", "toc1"):
            self.assertNotIn(f"OEBPS/{gone}.xhtml", names)
        for stay in ("ch1", "ch2", "cover"):
            self.assertIn(f"OEBPS/{stay}.xhtml", names)
        for stay in ("style/main.css", "style/extra.css", "fonts/f.ttf", "images/bg.png", "images/h.png",
                     "images/p2.png", "images/cover.jpg", "nav.xhtml", "toc.ncx"):
            self.assertIn("OEBPS/" + stay, names)
        for gone in ("images/shared.png", "images/orphan.png", "images/unused.png"):
            self.assertNotIn("OEBPS/" + gone, names)
        opf = self.zread(res.path, "OEBPS/content.opf")
        for gone in ("ch0", "ch3", "toc1", "shared", "orphan", "unused"):
            self.assertNotIn(f'id="{gone}"', opf)
        self.assertEqual(res.kept, self.sel([1, 2]))
        self.assertEqual(res.spine_items, 3)
        self.assertEqual(res.bytes_written, res.path.stat().st_size)
        self.assertTrue(res.cut)

    def test_shared_image_kept_once_for_either_chapter(self):
        res = self.run_export([3])
        names = self.names(res.path)
        self.assertIn("OEBPS/images/shared.png", names)
        self.assertEqual(names.count("OEBPS/images/shared.png"), 1)
        self.assertNotIn("OEBPS/images/p2.png", names)

    def test_navigation_cut_and_translated(self):
        res = self.run_export([1, 2, 3])
        nav = self.zread(res.path, "OEBPS/nav.xhtml")
        ET.fromstring(nav)
        self.assertEqual(self.nav_hrefs(res.path), ["ch1.xhtml", "ch2.xhtml", "ch3.xhtml"])
        self.assertIn(">Глава 1</a>", nav)
        self.assertIn(">Глава 3</a>", nav)
        self.assertNotIn("Chapter", nav)
        self.assertNotIn("Start", nav)  # landmark to a dropped chapter
        self.assertIn("Part One", nav)  # parent of a kept child stays
        ncx = self.zread(res.path, "OEBPS/toc.ncx")
        ET.fromstring(ncx)
        self.assertEqual(self.ncx_srcs(res.path), ["ch1.xhtml", "ch1.xhtml", "ch2.xhtml", "ch3.xhtml"])
        self.assertEqual(re.findall(r'playOrder="(\d+)"', ncx), ["1", "2", "3", "4"])
        self.assertIn("<text>Глава 2</text>", ncx)
        self.assertNotIn("<text>Chapter", ncx)
        self.assertEqual(res.toc_untranslated, [])

    def test_landmarks_keep_cover_entry(self):
        res = self.run_export([1])
        nav = self.zread(res.path, "OEBPS/nav.xhtml")
        self.assertIn('href="cover.xhtml"', nav)
        self.assertNotIn('href="ch0.xhtml"', nav)
        opf = self.zread(res.path, "OEBPS/content.opf")
        self.assertIn('href="cover.xhtml"', opf)
        self.assertNotIn('href="ch0.xhtml"', opf)

    def test_parent_with_dropped_link_becomes_plain_label(self):
        res = self.run_export([3])
        nav = self.zread(res.path, "OEBPS/nav.xhtml")
        self.assertEqual(self.nav_hrefs(res.path), ["ch3.xhtml"])
        self.assertIn("<span>Chapter 2</span>", nav)
        ncx = self.zread(res.path, "OEBPS/toc.ncx")
        self.assertEqual(self.ncx_srcs(res.path), ["ch3.xhtml", "ch3.xhtml"])
        self.assertEqual(re.findall(r'playOrder="(\d+)"', ncx), ["1", "2"])

    def test_title_and_links_report(self):
        res = self.run_export([1, 2])
        opf = self.zread(res.path, "OEBPS/content.opf")
        self.assertIn("<dc:title>Long Novel (Chapter 1 - Chapter 2)</dc:title>", opf)
        self.assertIn("<dc:language>ru</dc:language>", opf)
        self.assertEqual(res.dropped_links, 2)  # ch1 -> ch0 and ch4; self and web links are fine
        page = self.zread(res.path, "OEBPS/ch1.xhtml")
        self.assertIn('href="ch0.xhtml"', page)  # text and link left alone
        ET.fromstring(page)
        self.assertIn('lang="ru"', page)

    def title_of(self, res):
        return re.search(r"<dc:title>(.*?)</dc:title>", self.zread(res.path, "OEBPS/content.opf")).group(1)

    def test_long_labels_title_uses_printed_numbers_not_positions(self):
        # printed numbers 21.. differ from the spine positions on purpose
        self.use_long_labels({n: f"Chapter {n + 20} - a very long title that goes on and on" for n in range(CHAPTERS)})
        self.assertNotEqual(self.sel([1])[0], 21)
        res = self.run_export([1, 2])
        self.assertEqual(self.title_of(res), "Long Novel (21-22)")
        res = self.run_export([0, 2, 5])
        self.assertEqual(self.title_of(res), "Long Novel (20-25, 3 chapters)")
        res = self.run_export([3])
        self.assertEqual(self.title_of(res), "Long Novel (23)")
        # the file name keeps spine positions
        self.assertIn(f"_{self.sel([3])[0]}-{self.sel([3])[0]}.epub", res.path.name)

    def test_title_number_rules(self):
        self.use_long_labels({
            1: "Vol 2 Chapter 15: a very long title that goes on and on",
            2: "ГЛАВА 16. Очень длинное название которое тянется и тянется",
            3: "Prologue to something rather long, 7 items, and then more words",
            4: "Rozdział 18 - a very long title that goes on and on and on"})
        self.assertEqual(self.title_of(self.run_export([1, 2])), "Long Novel (15-16)")
        # the first integer when no chapter word is there
        self.assertEqual(self.title_of(self.run_export([3, 4])), "Long Novel (7-18)")

    def test_title_without_readable_number_gives_the_count_only(self):
        self.use_long_labels({n: f"Prologue and then the story goes on for number {chr(97 + n)}" + " x" * 8
                              for n in range(CHAPTERS)})
        self.assertEqual(self.title_of(self.run_export([1, 2])), "Long Novel (2 chapters)")
        self.assertEqual(self.title_of(self.run_export([0, 2, 5])), "Long Novel (3 chapters)")
        # one end unreadable is enough
        self.use_long_labels({1: "Chapter 5 - a very long title that goes on and on", 2: "The end of the very long story goes on"})
        self.assertEqual(self.title_of(self.run_export([1, 2])), "Long Novel (2 chapters)")
        self.assertNotIn("chapters 1", self.title_of(self.run_export([1, 2])))

    def use_long_labels(self, long=None):
        """Rebuild the series with long chapter labels."""
        long = long or {n: f"Chapter {n} - a very long title that goes on and on" for n in range(CHAPTERS)}
        epub = self.dir / "Long Novel.epub"
        build_book(epub, labels=long)
        (self.series.path / "books" / "Long Novel.epub").write_bytes(epub.read_bytes())

    def test_noncontiguous_selection_and_file_name(self):
        res = self.run_export([0, 2, 5])
        self.assertEqual(res.kept, self.sel([0, 2, 5]))
        self.assertEqual(self.spine(res.path), ["cover", "ch0", "ch2", "ch5"])
        first, last = self.sel([0])[0], self.sel([5])[0]
        self.assertIn(f"_{first}-{last}_3ch.epub", res.path.name)
        opf = self.zread(res.path, "OEBPS/content.opf")
        self.assertIn("3 chapters", opf)
        self.assertEqual(self.nav_hrefs(res.path), ["ch0.xhtml", "ch2.xhtml", "ch5.xhtml"])

    def test_contiguous_name_has_no_count(self):
        res = self.run_export([1, 2])
        a, b = self.sel([1])[0], self.sel([2])[0]
        self.assertTrue(res.path.name.endswith(f"_{a}-{b}.epub"), res.path.name)

    def test_range_drops_toc_page_explicit_selection_keeps_it(self):
        a, b = self.ix["cover.xhtml"], self.ix["ch1.xhtml"]
        res = export(self.series, self.name, a, b)
        self.assertNotIn("toc1", self.spine(res.path))
        self.assertEqual(res.problems, [])
        self.write_logs(["toc1.xhtml"])
        res2 = export(self.series, self.name, chapters=[self.ix["toc1.xhtml"], self.ix["ch1.xhtml"]])
        self.assertEqual(self.spine(res2.path), ["cover", "toc1", "ch1"])
        self.assertEqual(res2.problems, [])

    def test_source_untouched_and_no_part_files(self):
        src = self.series.path / "books" / "Long Novel.epub"
        before = hashlib.sha256(src.read_bytes()).hexdigest()
        res = self.run_export([2])
        self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), before)
        self.assertEqual([p.name for p in res.path.parent.iterdir()], [res.path.name])

    def test_escape_in_translated_label(self):
        with self.series.open_book(self.name) as b:
            ch = b.chapters[self.ix["ch4.xhtml"]]
            log = ChapterLog(self.series.chapter_log(self.name, ch).path)
            head = b.blocks(ch)[0]
            log.append([{"i": head.index, "src_sha": head.sha, "status": "ok", "text": "Тайна <&> \"X\""}])
        res = self.run_export([4])
        nav = self.zread(res.path, "OEBPS/nav.xhtml")
        ET.fromstring(nav)
        self.assertIn("Тайна &lt;&amp;&gt; \"X\"</a>", nav)
        ET.fromstring(self.zread(res.path, "OEBPS/toc.ncx"))

    def test_bilingual_toc_has_only_translation(self):
        res = self.run_export([1, 2], mode="bilingual")
        nav = self.zread(res.path, "OEBPS/nav.xhtml")
        self.assertIn(">Глава 1</a>", nav)
        self.assertNotIn("Chapter", nav)
        page = self.zread(res.path, "OEBPS/ch1.xhtml")
        self.assertIn("Chapter 1", page)
        self.assertIn("Глава 1", page)
        self.assertNotIn('lang="ru"', page)

    def test_whole_book_mode_still_available(self):
        res = export(self.series, self.name, 0, None, "single", cut=False)
        self.assertFalse(res.cut)
        self.assertEqual(res.problems, [])
        self.assertIn("OEBPS/ch5.xhtml", self.names(res.path))
        self.assertIn("OEBPS/toc1.xhtml", self.names(res.path))


class TestTocLabels(ExportCase):
    book_args = {"labels": {2: "Prologue", 3: "Chapter 3"}}

    def test_label_not_in_heading_stays_and_is_listed(self):
        self.write_logs(self.chapter_files(range(CHAPTERS)))
        res = self.run_export([1, 2, 3])
        nav = self.zread(res.path, "OEBPS/nav.xhtml")
        self.assertIn(">Prologue</a>", nav)
        self.assertIn(">Глава 3</a>", nav)
        self.assertEqual(res.toc_untranslated, self.sel([2]))

    def test_label_found_in_ordinary_block(self):
        # TOC label equals a whole paragraph instead of the heading
        self.write_logs(self.chapter_files(range(CHAPTERS)))
        epub = self.dir / "Long Novel.epub"
        build_book(epub, labels={2: "Body 2 one."})
        (self.series.path / "books" / "Long Novel.epub").write_bytes(epub.read_bytes())
        res = self.run_export([2])
        self.assertIn(">Абзац Тело 2 one.</a>", self.zread(res.path, "OEBPS/nav.xhtml"))
        self.assertEqual(res.toc_untranslated, [])


class TestVariants(ExportCase):
    book_args = {"epub3": False}

    def test_epub2_with_ncx_only(self):
        self.write_logs(self.chapter_files(range(CHAPTERS)))
        res = self.run_export([4, 5])
        names = self.names(res.path)
        self.assertNotIn("OEBPS/nav.xhtml", names)
        self.assertEqual(self.spine(res.path), ["cover", "ch4", "ch5"])
        self.assertIn("OEBPS/images/cover.jpg", names)  # meta name="cover"
        ncx = self.zread(res.path, "OEBPS/toc.ncx")
        self.assertEqual(self.ncx_srcs(res.path), ["ch4.xhtml", "ch5.xhtml"])
        self.assertIn("<text>Глава 4</text>", ncx)
        self.assertEqual(re.findall(r'playOrder="(\d+)"', ncx), ["1", "2"])
        self.assertIn("(Chapter 4 - Chapter 5)", self.zread(res.path, "OEBPS/content.opf"))
        self.assertIn("(Chapter 4 - Chapter 5)", ncx)


class TestFlat(ExportCase):
    book_args = {"nested": False, "nav_in_spine": True}

    def test_flat_toc_and_nav_in_spine_dropped(self):
        self.write_logs(self.chapter_files(range(CHAPTERS)))
        res = self.run_export([0, 1])
        self.assertEqual(self.spine(res.path), ["cover", "ch0", "ch1"])
        self.assertIn("OEBPS/nav.xhtml", self.names(res.path))
        self.assertEqual(self.nav_hrefs(res.path), ["ch0.xhtml", "ch1.xhtml"])


class TestSkipping(ExportCase):
    def test_partial_chapter_is_skipped_and_listed(self):
        self.write_logs(self.chapter_files([0, 1, 3]))
        self.write_logs(["ch2.xhtml"], skip_blocks=(1, 2))
        res = self.run_export([0, 1, 2, 3])
        self.assertEqual(res.kept, self.sel([0, 1, 3]))
        self.assertEqual([(s.index, s.title, s.missing) for s in res.skipped],
                         [(self.ix["ch2.xhtml"], "Chapter 2", 2)])
        self.assertEqual(res.untranslated, 2)
        self.assertNotIn("OEBPS/ch2.xhtml", self.names(res.path))
        self.assertNotIn("ch2.xhtml", self.zread(res.path, "OEBPS/nav.xhtml"))
        self.assertIn("_3ch.epub", res.path.name)

    def test_nothing_translated_raises_and_writes_nothing(self):
        out = self.series.path / "out"
        with self.assertRaises(NothingToExport):
            export(self.series, self.name, chapters=self.sel([1, 2]))
        self.assertEqual(list(out.iterdir()), [])
        self.write_logs(["ch1.xhtml"], skip_blocks=(0,))
        with self.assertRaises(NothingToExport) as cm:
            export(self.series, self.name, chapters=self.sel([1]))
        self.assertIn("1 missing", str(cm.exception))
        self.assertEqual(list(out.iterdir()), [])

    def test_empty_selection_raises(self):
        with self.assertRaises(NothingToExport):
            export(self.series, self.name, chapters=[])

    def test_failed_record_counts_as_missing(self):
        self.write_logs(self.chapter_files([1]))
        with self.series.open_book(self.name) as b:
            ch = b.chapters[self.ix["ch1.xhtml"]]
            blk = b.blocks(ch)[1]
            ChapterLog(self.series.chapter_log(self.name, ch).path).append(
                [{"i": blk.index, "src_sha": blk.sha, "status": "failed", "reason": "x"}])
        with self.assertRaises(NothingToExport):
            export(self.series, self.name, chapters=self.sel([1]))


class TestWhileTranslating(ExportCase):
    def test_export_while_log_is_appended(self):
        self.write_logs(self.chapter_files([1]))
        self.write_logs(["ch2.xhtml"], skip_blocks=(1, 2))
        with self.series.open_book(self.name) as b:
            ch = b.chapters[self.ix["ch2.xhtml"]]
            blocks = b.blocks(ch)
            path = self.series.chapter_log(self.name, ch).path
        late = [{"i": x.index, "src_sha": x.sha, "status": "ok", "text": translate(x.text, x.tag)}
                for x in blocks if x.index in (1, 2)]
        with open(path, "ab") as f:
            f.write(b'{"i": 2, "src_sha": "ab')  # a torn last line from a crashed or running writer
        stop = threading.Event()

        def writer():
            log = ChapterLog(path)
            for rec in late:
                time.sleep(0.02)
                log.append([rec])
            stop.set()

        t = threading.Thread(target=writer)
        t.start()
        results = []
        n = 0
        while not stop.is_set() or n < 3:
            res = export(self.series, self.name, chapters=self.sel([1, 2]), out_path=self.dir / f"o{n}.epub")
            results.append(res)
            n += 1
            if n > 200:
                break
        t.join()
        results.append(export(self.series, self.name, chapters=self.sel([1, 2]), out_path=self.dir / "last.epub"))
        for res in results:
            self.assertEqual(res.problems, [])
            if self.ix["ch2.xhtml"] in res.kept:
                self.assertNotIn("Body 2", self.zread(res.path, "OEBPS/ch2.xhtml"))
            else:
                self.assertNotIn("OEBPS/ch2.xhtml", self.names(res.path))
        self.assertEqual(results[-1].kept, self.sel([1, 2]))
        self.assertEqual(results[0].kept[0], self.sel([1])[0])
        self.assertEqual([p.name for p in self.dir.iterdir() if p.suffix == ".part"], [])


class TestStrictCheck(ExportCase):
    def test_check_reports_cut_problems(self):
        self.write_logs(self.chapter_files([1, 2]))
        res = self.run_export([1])
        self.assertEqual(check(res.path, strict=True), [])
        bad = self.dir / "bad.epub"
        with zipfile.ZipFile(res.path) as src, zipfile.ZipFile(bad, "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "OEBPS/style/extra.css":
                    continue
                if info.filename == "OEBPS/nav.xhtml":
                    data = data.replace(b'href="ch1.xhtml"', b'href="ch9.xhtml"')
                if info.filename == "OEBPS/ch1.xhtml":
                    data = data.replace(b"</body>", b"<p></body>")
                dst.writestr(info, data)
            dst.writestr("OEBPS/stray.txt", "x")
        text = "\n".join(check(bad, strict=True))
        self.assertIn("extra.css", text)
        self.assertIn("file not in manifest: OEBPS/stray.txt", text)
        self.assertIn("navigation target missing", text)
        self.assertIn("not well-formed: OEBPS/ch1.xhtml", text)


if __name__ == "__main__":
    unittest.main()
