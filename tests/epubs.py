"""Builds small EPUB files for tests (standard library only)."""
import zipfile

CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)

OPF = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>'
    "<dc:title>T</dc:title><dc:language>en</dc:language></metadata><manifest>"
    '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>%s</manifest>'
    '<spine>%s</spine></package>'
)

NAV = (
    '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Nav</title></head><body>'
    '<nav epub:type="toc"><ol><li><a href="ch0.xhtml">One</a></li></ol></nav></body></html>'
)

PAGE = (
    '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head>'
    "<body>%s</body></html>"
)

RICH = (
    "<h1>The Winter Road</h1>"
    "<p>The old man walked slowly along the river.</p>"
    "<p>Roses are red,<br/>violets are <i>blue</i>,<br />sugar is sweet.</p>"
    "<h2>A Short List</h2>"
    "<ul><li>Bread and salt for the road</li>"
    "<li><p>A candle in a paper lantern</p></li>"
    "<li>Fruits<ul><li>Apples from the cellar</li></ul></li></ul>"
    "<blockquote><p>He who walks in winter remembers the summer.</p></blockquote>"
    "<blockquote>A plain quotation without a paragraph.</blockquote>"
    "<table><tr><th>Month</th><th>Debt</th></tr>"
    "<tr><td>January</td><td><p>Twelve silver coins</p></td></tr></table>"
    "<figure><img src=\"x.png\" alt=\"\"/><figcaption>The river in December.</figcaption></figure>"
    "<dl><dt>Frost</dt><dd>The cold that comes before snow.</dd></dl>"
    "<div>A text block that sits directly in a division.</div>"
    "<p>1234</p>"
)


def write_epub(path, pages):
    """pages: list of body HTML strings, one chapter each. The mimetype member comes first and is stored."""
    items = "".join(
        '<item id="c%d" href="ch%d.xhtml" media-type="application/xhtml+xml"/>' % (i, i) for i in range(len(pages))
    )
    spine = '<itemref idref="nav"/>' + "".join('<itemref idref="c%d"/>' % i for i in range(len(pages)))
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", OPF % (items, spine), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/nav.xhtml", NAV, compress_type=zipfile.ZIP_DEFLATED)
        for i, body in enumerate(pages):
            zf.writestr("OEBPS/ch%d.xhtml" % i, PAGE % body, compress_type=zipfile.ZIP_DEFLATED)
    return path


def write_rich(path):
    return write_epub(path, [RICH])
