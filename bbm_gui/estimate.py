"""Plan estimate for an EPUB: how many paragraphs the engine will translate with the chosen tags, how many
requests that makes for a given grouping, how long it takes and how many days the daily quota needs.

The count follows the engine's own rules (nested paragraphs are skipped, ``sup``/``code`` are cut out, digits, white
space, punctuation and links are not translated) so that it equals the progress total the engine prints. It is
approximate in one respect only: the engine's other filters (file lists) are not known here."""
import math
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree

TAGS = ("p",)
EXCLUDED = ("sup", "code")
INLINE = frozenset("a abbr b bdi bdo big cite data dfn em font i kbd mark q ruby rt rp s samp small span strike strong sub "
                   "sup tt u var wbr".split())
SKIP = frozenset("head title style script svg math".split())  # their text is not the book's text
VOID = frozenset("area base br col embed hr img input keygen link meta param source track wbr".split())
URL = re.compile(r"(http[s]?://|www\.)+(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


class Node:
    __slots__ = ("name", "kids")

    def __init__(self, name):
        self.name = name
        self.kids = []


class Tree(HTMLParser):
    """A small element tree built the way an html.parser based soup builds it (no implied end tags)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("[document]")
        self.stack = [self.root]
        self.found = []  # every element in document order

    def handle_starttag(self, tag, attrs):
        node = Node(tag)
        self.stack[-1].kids.append(node)
        self.found.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag)
        self.stack[-1].kids.append(node)
        self.found.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].name == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def _text(node, skip=()):
    out = []
    for k in node.kids:
        if isinstance(k, str):
            out.append(k)
        elif k.name not in skip:
            out.append(_text(k, skip))
    return "".join(out)


def _has_nested(node, tags):
    for k in node.kids:
        if not isinstance(k, str) and (k.name in tags or _has_nested(k, tags)):
            return True
    return False


def _special(text):
    return text.isdigit() or text.isspace() or bool(URL.match(text.strip())) or all(c in PUNCT for c in text)


def count_html(content, tags=TAGS):
    """Paragraphs of one document that the engine would send."""
    tree = Tree()
    tree.feed(content)
    tree.close()
    n = 0
    for node in tree.found:
        if node.name not in tags or _has_nested(node, tags):
            continue
        text = _text(node, EXCLUDED)
        if not text or _special(text):
            continue
        rest = text.strip()
        if not rest or _special(rest):
            continue
        n += 1
    return n


def tag_list(value, default=TAGS):
    """The engine's --translate-tags text as a tuple of names (the engine's own default when empty)."""
    names = tuple(t.strip() for t in str(value or "").split(",") if t.strip())
    return names or tuple(default)


def uncovered_html(content, tags=TAGS, excluded=EXCLUDED):
    """Text blocks of one document that the chosen tags leave untouched: text that sits in no element the engine
    translates (a heading with the default tags, a division of its own, the words next to a nested list). Blocks are
    counted by the nearest non-inline element holding such text."""
    tree = Tree()
    tree.feed(content)
    tree.close()
    blocks = set()

    def walk(node, parents, covered):
        for k in node.kids:
            if isinstance(k, str):
                text = k.strip()
                if covered or not text or _special(text) or any(p.name in SKIP for p in parents):
                    continue
                for p in reversed(parents):
                    if p.name not in INLINE:
                        blocks.add(id(p))
                        break
                continue
            if k.name in excluded:
                continue
            leaf = k.name in tags and not _has_nested(k, tags)
            walk(k, parents + [k], covered or leaf)

    walk(tree.root, [tree.root], False)
    return len(blocks)


def _documents(zf, with_nav=True, relative=False):
    """Names of the book's documents in the archive (the xhtml items of the package). With `relative` the names are
    the manifest paths, which is how the engine names a file (--exclude_filelist)."""
    container = ElementTree.fromstring(zf.read("META-INF/container.xml"))
    opf_path = None
    for el in container.iter():
        if el.tag.endswith("rootfile"):
            opf_path = el.get("full-path")
            break
    if not opf_path:
        return []
    opf = ElementTree.fromstring(zf.read(opf_path))
    base = posixpath.dirname(opf_path)
    names = []
    for el in opf.iter():
        if not el.tag.endswith("}item") and el.tag != "item":
            continue
        if el.get("media-type") != "application/xhtml+xml":
            continue  # the navigation document is a page too: the engine translates its list items when `li` is chosen
        is_nav = "nav" in (el.get("properties") or "").split()
        if is_nav and not with_nav:
            continue
        href = unquote(el.get("href", ""))
        names.append(href if relative else posixpath.normpath(posixpath.join(base, href)))
    return names


def nav_files(path):
    """Manifest paths of the navigation documents of an EPUB ([] if unreadable)."""
    try:
        with zipfile.ZipFile(path) as zf:
            return [n for n in _documents(zf, True, True) if n not in _documents(zf, False, True)]
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return []


def document_files(path):
    """Names of the book's documents as the engine's file lists spell them (the manifest paths); [] if unreadable."""
    try:
        with zipfile.ZipFile(path) as zf:
            return list(dict.fromkeys(_documents(zf, True, True)))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return []


def scan(path, tags=TAGS, excluded=EXCLUDED, with_nav=True):
    """(paragraphs per document, uncovered text blocks) of an EPUB; documents with no paragraph are left out of the
    list. None if the file is not readable."""
    try:
        with zipfile.ZipFile(path) as zf:
            out = []
            left = 0
            for name in _documents(zf, with_nav):
                try:
                    raw = zf.read(name)
                except KeyError:
                    continue
                text = raw.decode("utf-8", "replace")
                n = count_html(text, tags)
                if n:
                    out.append(n)
                left += uncovered_html(text, tags, excluded)
            return out, left
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return None


def chapter_counts(path, tags=TAGS):
    """Paragraphs per document of an EPUB (documents with none are left out), or None if the file is not readable."""
    found = scan(path, tags)
    return found[0] if found else None


def requests(counts, per_request=1):
    """Requests for the chapters: a group never crosses a chapter."""
    b = max(int(per_request or 1), 1)
    return sum(math.ceil(n / b) for n in counts)


def days(n_requests, per_day):
    """Days the daily quota needs (None if the quota is not known)."""
    if not per_day:
        return None
    return max(1, math.ceil(n_requests / per_day))


def duration(seconds):
    """'~42 min' style text: hours and minutes below a day, '<1 min' for nothing."""
    m = int(round(seconds / 60.0))
    if m < 1:
        return "<1 min"
    if m < 60:
        return "%d min" % m
    h, m = divmod(m, 60)
    return "%d h %02d" % (h, m)


def plan_line(n_requests, seconds, n_days, uncovered=0):
    """'827 requests · ~1 h 03 · 2 days' (the time is approximate, the days appear when the quota is known). Text blocks
    the chosen tags leave out are named only when there are some."""
    parts = ["%d request%s" % (n_requests, "" if n_requests == 1 else "s"), "~" + duration(seconds)]
    if n_days:
        parts.append("%d day%s" % (n_days, "" if n_days == 1 else "s"))
    if uncovered:
        parts.append("%d block%s left as is" % (uncovered, "" if uncovered == 1 else "s"))
    return " · ".join(parts)
