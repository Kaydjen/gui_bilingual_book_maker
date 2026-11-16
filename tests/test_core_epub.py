import tempfile
import unittest
import zipfile
from pathlib import Path

from novelcore import Book, check, markers_ok

XHTML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head>\n'
    "<body>\n{body}\n</body></html>\n"
)
CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
    '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)


def make_epub(path, chapters, nav=None, ncx=None, extra=None, ids=None):
    """chapters: {filename: body html}. Spine order = dict order."""
    items = []
    spine = []
    for i, name in enumerate(chapters):
        items.append(f'<item id="c{i}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{i}"/>')
    if nav:
        items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        spine.insert(0, '<itemref idref="nav"/>')
    if ncx:
        items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    toc_attr = ' toc="ncx"' if ncx else ""
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book</dc:title>'
        "<dc:language>en</dc:language></metadata>"
        f"<manifest>{''.join(items)}</manifest>"
        f"<spine{toc_attr}>{''.join(spine)}</spine></package>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        for name, body in chapters.items():
            z.writestr("OEBPS/" + name, XHTML.replace("{body}", body).encode("utf-8"),
                       compress_type=zipfile.ZIP_DEFLATED)
        if nav:
            z.writestr("OEBPS/nav.xhtml", XHTML.replace("{body}", nav), compress_type=zipfile.ZIP_DEFLATED)
        if ncx:
            z.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in (extra or {}).items():
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


class EpubCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def build(self, chapters, **kw):
        p = self.dir / "src.epub"
        make_epub(p, chapters, **kw)
        book = Book.open(p)
        self.addCleanup(book.close)
        return book

    def read(self, path, name):
        with zipfile.ZipFile(path) as z:
            return z.read(name).decode("utf-8")


class TestBlocks(EpubCase):
    def test_plain_paragraphs(self):
        b = self.build({"a.xhtml": "<p>One.</p>\n<p>Two.</p>"})
        ch = b.chapters[0]
        blocks = b.blocks(ch)
        self.assertEqual([x.text for x in blocks], ["One.", "Two."])
        self.assertEqual(ch.href, "OEBPS/a.xhtml")
        text = b.read_text(ch)
        self.assertEqual(text[blocks[0].start:blocks[0].end], "One.")
        self.assertEqual(blocks[0].markers, {})
        self.assertEqual(len(blocks[0].sha), 40)

    def test_inline_markers_and_nesting(self):
        b = self.build({"a.xhtml": '<p>A <em class="x">bold <strong>deep</strong></em> and <a href="u">link</a>.</p>'})
        blk = b.blocks(b.chapters[0])[0]
        self.assertEqual(blk.text, "A <1>bold <2>deep</2></1> and <3>link</3>.")
        self.assertEqual(blk.markers[1], ('<em class="x">', "</em>"))
        self.assertEqual(blk.markers[3], ('<a href="u">', "</a>"))
        self.assertTrue(markers_ok(blk.markers, blk.text))

    def test_nested_blockquote_only_inner_p(self):
        b = self.build({"a.xhtml": "<blockquote>\n<p>Inner one.</p>\n<p>Inner two.</p>\n</blockquote>"})
        blocks = b.blocks(b.chapters[0])
        self.assertEqual([x.tag for x in blocks], ["p", "p"])

    def test_headings_li_td(self):
        body = ("<h1>Title</h1><ul><li>Item one</li><li>Item two</li></ul>"
                "<table><tr><td>Cell a</td><th>Head b</th></tr></table>")
        b = self.build({"a.xhtml": body})
        blocks = b.blocks(b.chapters[0])
        self.assertEqual([(x.tag, x.text) for x in blocks],
                         [("h1", "Title"), ("li", "Item one"), ("li", "Item two"),
                          ("td", "Cell a"), ("th", "Head b")])
        self.assertEqual([x.index for x in blocks], list(range(5)))

    def test_br_only_body(self):
        b = self.build({"a.xhtml": "First line.<br/>Second <em>line</em>.<br/><br/>Third.\n<br/>"})
        blocks = b.blocks(b.chapters[0])
        self.assertEqual([x.text for x in blocks], ["First line.", "Second <1>line</1>.", "Third."])
        self.assertTrue(all(x.kind == "run" for x in blocks))
        text = b.read_text(b.chapters[0])
        self.assertEqual(text[blocks[2].start:blocks[2].end], "Third.")

    def test_br_inside_p(self):
        b = self.build({"a.xhtml": "<p>Line one<br/>Line two</p>"})
        blocks = b.blocks(b.chapters[0])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, "Line one\nLine two")

    def test_entities(self):
        b = self.build({"a.xhtml": "<p>Tom &amp; Jerry&nbsp;said &#8212; &lt;hi&gt;</p>"})
        blk = b.blocks(b.chapters[0])[0]
        self.assertEqual(blk.text, "Tom & Jerry said — <hi>")

    def test_skip_rules(self):
        body = ("<p>123</p><p>...</p><p>https://example.com/x</p><p>  </p><p></p>"
                "<p>* * *</p><p>Real text.</p>")
        b = self.build({"a.xhtml": body})
        self.assertEqual([x.text for x in b.blocks(b.chapters[0])], ["Real text."])
        self.assertEqual(b.uncovered_text(b.chapters[0]), 0)

    def test_uncovered_text(self):
        b = self.build({"a.xhtml": "<p>Covered.</p><blockquote>Stray <p>Inner.</p></blockquote>"})
        ch = b.chapters[0]
        # the direct text of the blockquote becomes a run block, so nothing is left over
        self.assertEqual([x.text for x in b.blocks(ch)], ["Covered.", "Stray", "Inner."])
        b2 = self.build({"a.xhtml": "<p>Text</p><script>var x = 'not text';</script>"})
        self.assertEqual(b2.uncovered_text(b2.chapters[0]), 0)

    def test_offsets_do_not_move_text(self):
        body = "<p id='x'>  Padded  </p>\n<!-- c --><p>Next</p>"
        b = self.build({"a.xhtml": body})
        ch = b.chapters[0]
        text = b.read_text(ch)
        blk = b.blocks(ch)[0]
        self.assertEqual(text[blk.start:blk.end], "Padded")
        self.assertEqual(text[blk.outer_start:blk.open_end], "<p id='x'>")


class TestStructure(EpubCase):
    def test_toc_page_and_nav(self):
        links = "".join(f'<li><a href="c{i}.xhtml">Chapter {i}</a></li>' for i in range(30))
        book = self.build(
            {"toc.xhtml": f"<ul>{links}</ul>", "c1.xhtml": "<p>Story text goes on and on.</p>"},
            nav='<nav epub:type="toc"><ol><li><a href="c1.xhtml">First Chapter</a></li></ol></nav>',
        )
        flags = {c.href.rsplit("/", 1)[-1]: c.is_toc for c in book.chapters}
        self.assertEqual(flags, {"nav.xhtml": True, "toc.xhtml": True, "c1.xhtml": False})

    def test_titles_from_nav_ncx_heading_text(self):
        ncx = ('<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
               '<navPoint id="n"><navLabel><text>From NCX</text></navLabel>'
               '<content src="b.xhtml"/></navPoint></navMap></ncx>')
        book = self.build(
            {"a.xhtml": "<p>x</p>", "b.xhtml": "<h2>Ignored heading</h2><p>Body.</p>",
             "c.xhtml": "<h2>A <em>Heading</em></h2><p>Body.</p>", "d.xhtml": "<p>Just text.</p>"},
            nav='<nav epub:type="toc"><ol><li><a href="a.xhtml#top">From Nav</a></li></ol></nav>',
            ncx=ncx,
        )
        titles = {c.href.rsplit("/", 1)[-1]: c.title for c in book.chapters}
        self.assertEqual(titles["a.xhtml"], "From Nav")
        self.assertEqual(titles["b.xhtml"], "From NCX")
        self.assertEqual(titles["c.xhtml"], "A Heading")
        self.assertEqual(titles["d.xhtml"], "Just text.")

    def test_lazy_reading(self):
        book = self.build({"a.xhtml": "<p>One.</p>"})
        self.assertEqual(len(book._cache), 0)
        book.blocks(book.chapters[0])
        self.assertEqual(len(book._cache), 1)


class TestExport(EpubCase):
    BODY = ('<p id="p1">First <em>em</em> one.</p>\n<p>Second &amp; last.</p>\n'
            "Loose line<br/>Another loose.")

    def all_translations(self, book, fn=lambda t: t):
        return {(c.href, b.index): fn(b.text) for c in book.chapters for b in book.blocks(c)}

    def test_identity_single(self):
        book = self.build({"a.xhtml": self.BODY, "b.xhtml": "<p>Two.</p>"})
        out = self.dir / "out.epub"
        fallbacks = book.export(out, self.all_translations(book), "single")
        self.assertEqual(fallbacks, [])
        with zipfile.ZipFile(book.path) as a, zipfile.ZipFile(out) as b:
            self.assertEqual(a.namelist(), b.namelist())
            for n in a.namelist():
                self.assertEqual(a.read(n), b.read(n), n)
            self.assertEqual(b.infolist()[0].filename, "mimetype")
            self.assertEqual(b.infolist()[0].compress_type, zipfile.ZIP_STORED)

    def test_single_changes_only_spans(self):
        book = self.build({"a.xhtml": self.BODY, "b.xhtml": "<p>Two.</p>"})
        ch = book.chapters[0]
        blocks = book.blocks(ch)
        out = self.dir / "out.epub"
        book.export(out, {(ch.href, 0): "Первый <1>курс</1> раз.", (ch.href, 1): "Вторая & <последняя>"}, "single")
        new = self.read(out, ch.href)
        old = book.read_text(ch)
        self.assertIn('<p id="p1">Первый <em>курс</em> раз.</p>', new)
        self.assertIn("<p>Вторая &amp; &lt;последняя&gt;</p>", new)
        self.assertIn("Loose line<br/>Another loose.", new)  # untranslated stays
        # rebuilding the old text from the new one by swapping the spans gives back the source
        b0, b1 = blocks[0], blocks[1]
        rebuilt = new.replace('<p id="p1">Первый <em>курс</em> раз.</p>',
                              old[b0.outer_start:b0.outer_end]).replace(
            "<p>Вторая &amp; &lt;последняя&gt;</p>", old[b1.outer_start:b1.outer_end])
        self.assertEqual(rebuilt, old)
        self.assertEqual(self.read(out, "OEBPS/b.xhtml"), self.read(book.path, "OEBPS/b.xhtml"))

    def test_bilingual_copies_without_id(self):
        book = self.build({"a.xhtml": self.BODY})
        ch = book.chapters[0]
        tr = {(ch.href, 0): "Первый <1>курс</1>.", (ch.href, 2): "Свободная", (ch.href, 3): "Другая"}
        out = self.dir / "out.epub"
        book.export(out, tr, "bilingual")
        new = self.read(out, ch.href)
        self.assertIn('<p id="p1">First <em>em</em> one.</p><p>Первый <em>курс</em>.</p>', new)
        self.assertEqual(new.count('id="p1"'), 1)
        self.assertIn("Loose line<br/>Свободная<br/>Another loose.<br/>Другая", new)
        self.assertEqual(check(out, source=book.path), [])

    def test_markers_round_trip_and_fallback(self):
        book = self.build({"a.xhtml": "<p>A <em>b</em> <a href='x'>c</a><img src='i.png'/> d.</p>"})
        ch = book.chapters[0]
        blk = book.blocks(ch)[0]
        self.assertEqual(blk.text, "A <1>b</1> <2>c</2><3/> d.")
        out = self.dir / "o1.epub"
        self.assertEqual(book.export(out, {(ch.href, 0): blk.text}, "single"), [])
        self.assertIn("<p>A <em>b</em> <a href='x'>c</a><img src='i.png'/> d.</p>", self.read(out, ch.href))
        # a translation that lost a marker is written as plain text and reported
        out2 = self.dir / "o2.epub"
        bad = {(ch.href, 0): "А <1>б</1> в <2>г <3/> д"}
        self.assertEqual(book.export(out2, bad, "single"), [(ch.href, 0)])
        self.assertIn("<p>А б в г  д</p>", self.read(out2, ch.href))
        self.assertFalse(markers_ok(blk.markers, "A <1>b</2>"))
        self.assertFalse(markers_ok(blk.markers, "A <1>b</1> <2>c</2>"))

    def test_bilingual_copy_drops_cut_tag_halves(self):
        # <i> is opened in one br-run and closed in the next: the copies must stay well-formed
        book = self.build({"a.xhtml": "Start <i>one<br/>two</i> end."})
        ch = book.chapters[0]
        blocks = book.blocks(ch)
        self.assertEqual([b.text for b in blocks], ["Start <1/>one", "two<1/> end."])
        out = self.dir / "o.epub"
        book.export(out, {(ch.href, 0): "Начало <1/>раз", (ch.href, 1): "два<1/> конец."}, "bilingual")
        self.assertEqual(check(out), [])
        out2 = self.dir / "o2.epub"
        book.export(out2, {(ch.href, 0): "Начало <1/>раз", (ch.href, 1): "два<1/> конец."}, "single")
        self.assertEqual(check(out2), [])
        self.assertIn("Начало <i>раз<br/>два</i> конец.", self.read(out2, ch.href))

    def test_br_restored(self):
        book = self.build({"a.xhtml": "<p>Line one<br/>Line two</p>"})
        ch = book.chapters[0]
        out = self.dir / "o.epub"
        book.export(out, {(ch.href, 0): "Один\nДва"}, "single")
        self.assertIn("<p>Один<br/>Два</p>", self.read(out, ch.href))

    def test_lang_stamping(self):
        book = self.build({"a.xhtml": "<p>Hello.</p>"})
        ch = book.chapters[0]
        out = self.dir / "o.epub"
        book.export(out, {(ch.href, 0): "Привет."}, "single", lang="ru:Russian")
        self.assertIn("<dc:language>ru</dc:language>", self.read(out, "OEBPS/content.opf"))
        html = self.read(out, ch.href)
        self.assertIn('lang="ru"', html)
        self.assertIn('xml:lang="ru"', html)
        out2 = self.dir / "o2.epub"
        book.export(out2, {(ch.href, 0): "Привет."}, "bilingual", lang="ru")
        self.assertIn("<dc:language>en</dc:language>", self.read(out2, "OEBPS/content.opf"))

    def test_same_path_refused(self):
        book = self.build({"a.xhtml": "<p>Hello.</p>"})
        with self.assertRaises(ValueError):
            book.export(book.path, {}, "single")


class TestCheck(EpubCase):
    def test_clean_book(self):
        book = self.build({"a.xhtml": "<p>Hello.</p>"})
        self.assertEqual(check(book.path), [])

    def test_missing_manifest_file(self):
        p = self.dir / "src.epub"
        make_epub(p, {"a.xhtml": "<p>Hello.</p>"})
        broken = self.dir / "broken.epub"
        with zipfile.ZipFile(p) as a, zipfile.ZipFile(broken, "w") as b:
            for info in a.infolist():
                if info.filename != "OEBPS/a.xhtml":
                    b.writestr(info, a.read(info.filename))
        problems = check(broken)
        self.assertTrue(any("missing in zip" in x and "a.xhtml" in x for x in problems), problems)

    def test_not_well_formed_reported_unless_in_source(self):
        p = self.dir / "src.epub"
        make_epub(p, {"a.xhtml": "<p>Tom &nbsp; Jerry<br></p>"})
        self.assertTrue(any("not well-formed" in x for x in check(p)))
        self.assertEqual(check(p, source=p), [])

    def test_bad_mimetype_order(self):
        p = self.dir / "src.epub"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("x.txt", "x")
            z.writestr("mimetype", "application/epub+zip")
        self.assertTrue(any("mimetype" in x for x in check(p)))


if __name__ == "__main__":
    unittest.main()
