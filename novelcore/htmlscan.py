"""Offset-preserving block scanner for (X)HTML documents.

The document is never re-serialised: a tokenizer walks the decoded text and
reports, for every translatable block, the offsets of its inner content in
that text. Everything outside those spans can therefore stay byte-identical.
"""

from __future__ import annotations

import bisect
import hashlib
import html.entities
import re
from dataclasses import dataclass, field

LISTED = frozenset("p h1 h2 h3 h4 h5 h6 li blockquote dt dd figcaption td th".split())
INLINE = frozenset(
    "a abbr acronym b bdi bdo big cite code data del dfn em font i ins kbd mark q "
    "ruby rb rt rp rtc s samp small span strike strong sub sup time tt u var "
    "label nobr".split()
)
VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr image".split()
)
# Elements whose content is never text for translation; kept as one opaque item.
OPAQUE = frozenset("script style svg math head template".split())
# An open <p> is closed implicitly by these start tags.
_P_CLOSERS = frozenset(
    "p div ul ol dl table h1 h2 h3 h4 h5 h6 blockquote li dt dd figure pre hr "
    "section article aside header footer nav form".split()
)

TOKEN_RE = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<![^>]*>"
    r"|<(/?)([A-Za-z][^\s/>]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*)>",
    re.S,
)
BODY_RE = re.compile(r"<body\b[^>]*>", re.I)
ENTITY_RE = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
MARKER_RE = re.compile(r"<(/?)(\d+)(/?)>")
_WS = " \t\r\n\f"
_URL_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.I)
_ID_ATTR_RE = re.compile(r"""\s+id\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)


def unescape(raw: str) -> str:
    """Decode character references; only well-formed ones (with ';')."""

    def one(m: re.Match) -> str:
        ref = m.group(1)
        try:
            if ref[0] == "#":
                num = int(ref[2:], 16) if ref[1] in "xX" else int(ref[1:])
                return chr(num)
            return html.entities.html5.get(ref + ";", m.group(0))
        except (ValueError, OverflowError):
            return m.group(0)

    return ENTITY_RE.sub(one, raw) if "&" in raw else raw


def escape_text(text: str) -> str:
    """Escape &, < and > for use as element content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def strip_markers(text: str) -> str:
    """Remove numbered markers, keeping the text between them."""
    return MARKER_RE.sub("", text)


def markers_ok(markers: dict, text: str) -> bool:
    """True when `text` carries exactly the markers of a block, properly nested."""
    stack: list[int] = []
    seen: set[int] = set()
    for m in MARKER_RE.finditer(text):
        closing, num, selfclose = m.group(1) == "/", int(m.group(2)), m.group(3) == "/"
        if num not in markers or (closing and selfclose):
            return False
        pair = markers[num][1] != ""
        if selfclose:
            if pair or num in seen:
                return False
            seen.add(num)
        elif closing:
            if not stack or stack[-1] != num:
                return False
            stack.pop()
        else:
            if not pair or num in seen:
                return False
            seen.add(num)
            stack.append(num)
    return not stack and seen == set(markers)


@dataclass
class Block:
    """One translatable piece of a document.

    start/end: offsets of the block's inner content (trimmed of edge
    whitespace) in the decoded file text. For kind "element" the outer_*,
    open_end and close_start offsets describe the whole element; for kind
    "run" (a text run between <br> tags) they equal start/end.
    """

    index: int
    tag: str
    start: int
    end: int
    text: str
    markers: dict
    sha: str
    kind: str = "element"
    halves: frozenset = frozenset()
    outer_start: int = 0
    open_end: int = 0
    close_start: int = 0
    outer_end: int = 0


@dataclass
class Parsed:
    blocks: list
    uncovered: int
    total_chars: int
    link_chars: int
    link_count: int
    spans: list = field(default_factory=list)


class _Frame:
    __slots__ = ("name", "kind", "tag_start", "inner_start", "whole", "run", "pending", "dirty")

    def __init__(self, name, kind, tag_start=0, inner_start=0):
        self.name = name
        self.kind = kind  # "block" | "container" | "inline"
        self.tag_start = tag_start
        self.inner_start = inner_start
        self.whole = [] if kind == "block" else None
        self.run = []
        self.pending = []
        self.dirty = False


def _render(src: str, items: list) -> tuple[str, dict, frozenset]:
    """Turn collected items into (model text with markers, markers dict)."""
    parts: list[list] = []  # [kind, value]; kind "t" text, "m" marker
    markers: dict[int, list] = {}
    stack: list[tuple[str, int, int]] = []  # (name, number, parts index)
    halves: set[int] = set()  # markers that are one half of a tag pair cut by the block
    n = 0
    for kind, s, e, name in items:
        if kind == "t":
            parts.append(["t", re.sub(r"[ \t\r\n\f]+", " ", unescape(src[s:e]))])
        elif kind == "b":
            parts.append(["t", "\n"])
        elif kind == "v":
            n += 1
            markers[n] = [src[s:e], ""]
            parts.append(["m", f"<{n}/>"])
        elif kind == "o":
            n += 1
            markers[n] = [src[s:e], ""]
            stack.append((name, n, len(parts)))
            parts.append(["m", f"<{n}>"])
        else:  # close
            hit = None
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    hit = k
                    break
            if hit is None:
                n += 1
                markers[n] = [src[s:e], ""]
                halves.add(n)
                parts.append(["m", f"<{n}/>"])
                continue
            for _, num, idx in stack[hit + 1:]:  # opened inside, never closed
                parts[idx][1] = f"<{num}/>"
                halves.add(num)
            _, num, _ = stack[hit]
            del stack[hit:]
            markers[num][1] = src[s:e]
            parts.append(["m", f"</{num}>"])
    for _, num, idx in stack:
        parts[idx][1] = f"<{num}/>"
        halves.add(num)
    text = "".join(p[1] for p in parts)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r" {2,}", " ", text).strip(" ").strip("\n").strip(" ")
    return text, {k: tuple(v) for k, v in markers.items()}, frozenset(halves)


class _Scanner:
    def __init__(self, src: str):
        self.src = src
        self.root = _Frame("body", "container")
        self.stack: list[_Frame] = [self.root]
        self.blocks: list[Block] = []
        self.spans: list[tuple[int, int]] = []
        self.texts: list[tuple[int, int, bool]] = []
        self.a_depth = 0

    # -- helpers -------------------------------------------------------
    def _collector(self) -> _Frame:
        for f in reversed(self.stack):
            if f.kind != "inline":
                return f
        return self.root

    def _add(self, item) -> None:
        f = self._collector()
        if f.kind == "block":
            f.whole.append(item)
        f.run.append(item)

    def _flush(self, f: _Frame) -> None:
        if f.run:
            if f.kind == "block":
                f.pending.append(f.run)
            else:
                self._emit(f.run, f.name, "run")
            f.run = []

    def _blank(self, it) -> bool:
        if it[0] == "b":
            return True
        return it[0] == "t" and not self.src[it[1]:it[2]].strip(_WS)

    def _emit(self, items, tag, kind, outer=None) -> None:
        items = list(items)
        while items and self._blank(items[0]):
            items.pop(0)
        while items and self._blank(items[-1]):
            items.pop()
        if not items:
            return
        src = self.src
        s, e = items[0][1], items[-1][2]
        if items[0][0] == "t":
            raw = src[s:items[0][2]]
            s += len(raw) - len(raw.lstrip(_WS))
        if items[-1][0] == "t":
            raw = src[items[-1][1]:e]
            e -= len(raw) - len(raw.rstrip(_WS))
        text, markers, halves = _render(src, items)
        self.spans.append((s, e))
        plain = strip_markers(text)
        if not any(c.isalpha() for c in plain) or _URL_RE.match(plain.strip()):
            return
        b = Block(0, tag, s, e, text, markers, hashlib.sha1(text.encode("utf-8")).hexdigest(), kind, halves)
        if outer:
            b.outer_start, b.open_end, b.close_start, b.outer_end = outer
        else:
            b.outer_start = b.open_end = s
            b.close_start = b.outer_end = e
        self.blocks.append(b)

    def _close(self, f: _Frame, inner_end: int, end_tag_end: int | None) -> None:
        if f.kind == "inline":
            if f.name == "a":
                self.a_depth -= 1
            if end_tag_end is not None:
                self._add(("c", inner_end, end_tag_end, f.name))
        elif f.kind == "container":
            self._flush(f)
        elif not f.dirty:
            self._emit(f.whole, f.name, "element",
                       (f.tag_start, f.inner_start, inner_end,
                        end_tag_end if end_tag_end is not None else inner_end))
        else:
            self._flush(f)
            for items in f.pending:
                self._emit(items, f.name, "run")

    def _pop(self, upto: int, pos: int, end_tag_end: int | None) -> None:
        """Close frames above and including stack[upto]."""
        while len(self.stack) > upto:
            f = self.stack.pop()
            last = len(self.stack) == upto
            self._close(f, pos, end_tag_end if last else None)

    def _implied(self, name: str, pos: int) -> None:
        top = self.stack[-1]
        if top.kind != "block":
            return
        t = top.name
        if (
            (t == "p" and name in _P_CLOSERS)
            or (t == "li" and name == "li")
            or (t in ("dt", "dd") and name in ("dt", "dd"))
            or (t in ("td", "th") and name in ("td", "th", "tr"))
        ):
            self._pop(len(self.stack) - 1, pos, None)

    # -- main loop -----------------------------------------------------
    def run(self, pos: int) -> Parsed:
        src = self.src
        n = len(src)
        end_pos = n
        while True:
            m = TOKEN_RE.search(src, pos)
            text_end = m.start() if m else n
            if text_end > pos:
                self._text(pos, text_end)
            if not m:
                break
            s, e = m.start(), m.end()
            pos = e
            closing, name = m.group(1), (m.group(2) or "").lower()
            if not name:  # comment, CDATA, PI, doctype
                if tok_is_comment(src, s):
                    self._add(("v", s, e, "!"))
                continue
            if closing:
                if name == "body":
                    end_pos = s
                    break
                for k in range(len(self.stack) - 1, 0, -1):
                    if self.stack[k].name == name:
                        self._pop(k, s, e)
                        break
                continue
            selfclose = m.group(3).rstrip().endswith("/")
            if name in OPAQUE:
                if not selfclose:
                    cm = re.compile(r"</%s\s*>" % re.escape(name), re.I).search(src, e)
                    if cm:
                        e = pos = cm.end()
                self._add(("v", s, e, name))
                continue
            self._implied(name, s)
            if name == "br":
                f = self._collector()
                if f.kind == "block":
                    f.whole.append(("b", s, e, name))
                self._flush(f)
                continue
            if name in VOID or selfclose:
                self._add(("v", s, e, name))
                continue
            self._start(name, s, e)
        self._pop(1, end_pos, None)
        self._flush(self.root)
        return self._finish()

    def _start(self, name: str, s: int, e: int) -> None:
        f = self._collector()
        if f.kind == "block" or (name in INLINE and name not in LISTED):
            if name in LISTED and f.kind == "block":
                f.dirty = True
                self._flush(f)
                self.stack.append(_Frame(name, "block", s, e))
                return
            self._add(("o", s, e, name))
            if name == "a":
                self.a_depth += 1
            self.stack.append(_Frame(name, "inline", s, e))
            return
        self._flush(f)
        kind = "block" if name in LISTED else "container"
        self.stack.append(_Frame(name, kind, s, e))

    def _text(self, s: int, e: int) -> None:
        raw = self.src[s:e]
        stripped = raw.lstrip(_WS)
        if stripped.strip(_WS):
            chars = len(re.sub(r"\s+", "", unescape(raw)))
            self.texts.append((s + len(raw) - len(stripped), chars, self.a_depth > 0))
        self._add(("t", s, e, ""))

    def _finish(self) -> Parsed:
        blocks = sorted(self.blocks, key=lambda b: (b.start, b.end))
        for i, b in enumerate(blocks):
            b.index = i
        spans = sorted(self.spans)
        starts = [x[0] for x in spans]
        uncovered = total = link = links = 0
        for pos, chars, in_a in self.texts:
            total += chars
            if in_a:
                link += chars
                links += 1  # text pieces inside links, close to the link count
            k = bisect.bisect_right(starts, pos) - 1
            # nested spans are impossible, so only the nearest start can cover pos
            if not (k >= 0 and spans[k][0] <= pos < spans[k][1]):
                uncovered += chars
        return Parsed(blocks, uncovered, total, link, links, spans)


def tok_is_comment(src: str, s: int) -> bool:
    return src.startswith("<!--", s)


def scan(src: str) -> Parsed:
    """Scan a decoded (X)HTML document and return its blocks."""
    m = BODY_RE.search(src)
    return _Scanner(src).run(m.end() if m else 0)


def strip_id(open_tag: str) -> str:
    """Remove the id attribute from a start tag string."""
    return _ID_ATTR_RE.sub("", open_tag, count=1)


def to_html(block: Block, translated: str, copy: bool = False) -> tuple[str, bool]:
    """Turn translated text (with markers) into HTML for `block`.

    Rule: when the markers of the translation do not match the block's
    markers (missing, extra, mis-nested), all markers are dropped and the text
    is used as plain text. Returns (html, markers_were_valid). With copy=True
    (a bilingual copy next to the original) markers that are half of a tag
    pair cut by the block are left out, so the copy stays well-formed.
    """
    ok = True
    if block.markers:
        ok = markers_ok(block.markers, translated)
    elif MARKER_RE.search(translated):
        ok = False
    if not ok:
        translated = strip_markers(translated)
    elif copy and block.halves:
        translated = MARKER_RE.sub(
            lambda m: "" if int(m.group(2)) in block.halves else m.group(0), translated
        )
    out: list[str] = []
    pos = 0
    for m in MARKER_RE.finditer(translated):
        out.append(_plain_html(translated[pos:m.start()]))
        num = int(m.group(2))
        opener, closer = block.markers[num]
        out.append(closer if m.group(1) == "/" else opener)
        pos = m.end()
    out.append(_plain_html(translated[pos:]))
    return "".join(out), ok


def _plain_html(text: str) -> str:
    return escape_text(text).replace("\r\n", "\n").replace("\n", "<br/>")
