"""EPUB reading, block extraction, export and structural checks."""

from __future__ import annotations

import copy
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

from .htmlscan import Block, Parsed, escape_text, scan, strip_id, strip_markers, to_html, unescape

XHTML_TYPES = ("application/xhtml+xml", "text/html")
NCX_TYPE = "application/x-dtbncx+xml"


class EpubError(Exception):
    """The file is not a usable EPUB."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _decode(data: bytes) -> tuple[str, str]:
    """Decode a document; returns (text, encoding) so export can re-encode it."""
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def _resolve(base_dir: str, href: str) -> str:
    href = unquote(href.split("#", 1)[0].split("?", 1)[0])
    return posixpath.normpath(posixpath.join(base_dir, href)) if href else ""


class _Package:
    """Parsed container.xml + OPF."""

    def __init__(self, zf: zipfile.ZipFile):
        names = set(zf.namelist())
        if "META-INF/container.xml" not in names:
            raise EpubError("META-INF/container.xml is missing")
        try:
            root = ET.fromstring(zf.read("META-INF/container.xml"))
        except ET.ParseError as exc:
            raise EpubError(f"container.xml is not well-formed: {exc}") from exc
        self.opf_path = ""
        for el in root.iter():
            if _local(el.tag) == "rootfile" and el.get("full-path"):
                self.opf_path = unquote(el.get("full-path"))
                break
        if self.opf_path not in names:
            raise EpubError("OPF file named by container.xml is missing")
        self.base = posixpath.dirname(self.opf_path)
        try:
            opf = ET.fromstring(zf.read(self.opf_path))
        except ET.ParseError as exc:
            raise EpubError(f"OPF is not well-formed: {exc}") from exc
        self.manifest: dict[str, dict] = {}
        self.spine: list[str] = []
        self.toc_id = ""
        for el in opf.iter():
            name = _local(el.tag)
            if name == "item" and el.get("id") is not None:
                self.manifest[el.get("id")] = {
                    "href": _resolve(self.base, el.get("href", "")),
                    "type": el.get("media-type", ""),
                    "props": (el.get("properties") or "").split(),
                }
            elif name == "itemref" and el.get("idref") is not None:
                self.spine.append(el.get("idref"))
            elif name == "spine":
                self.toc_id = el.get("toc") or ""


def _is_doc(item: dict) -> bool:
    return item["type"] in XHTML_TYPES or item["href"].lower().endswith((".xhtml", ".html", ".htm"))


class Chapter:
    """A spine document. Identified by href; title is for display only."""

    def __init__(self, book: "Book", index: int, href: str, idref: str, is_nav: bool):
        self._book = book
        self.index = index
        self.href = href
        self.idref = idref
        self._is_nav = is_nav
        self._title: str | None = None
        self._is_toc: bool | None = None

    @property
    def title(self) -> str:
        if self._title is None:
            self._title = self._book._title_of(self)
        return self._title

    @property
    def is_toc(self) -> bool:
        """The EPUB nav document, or a document that is mostly links."""
        if self._is_toc is None:
            if self._is_nav:
                self._is_toc = True
            else:
                p = self._book._parsed(self)
                self._is_toc = p.link_count >= 10 and p.link_chars >= 0.6 * max(p.total_chars, 1)
        return self._is_toc

    def __repr__(self) -> str:
        return f"Chapter({self.index}, {self.href!r})"


class Book:
    """An opened EPUB. Chapter files are read only when asked."""

    def __init__(self, path):
        self.path = str(path)
        try:
            self._zip = zipfile.ZipFile(self.path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise EpubError(f"cannot open {self.path}: {exc}") from exc
        self._pkg = _Package(self._zip)
        self._cache: OrderedDict[str, tuple[str, str, Parsed]] = OrderedDict()
        self._labels: dict[str, str] | None = None
        names = set(self._zip.namelist())
        self.chapters: list[Chapter] = []
        for idref in self._pkg.spine:
            item = self._pkg.manifest.get(idref)
            if item is None or item["href"] not in names or not _is_doc(item):
                continue
            self.chapters.append(
                Chapter(self, len(self.chapters), item["href"], idref, "nav" in item["props"])
            )

    @classmethod
    def open(cls, path) -> "Book":
        return cls(path)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "Book":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- reading -------------------------------------------------------
    def _parsed(self, chapter: Chapter) -> Parsed:
        return self._load(chapter.href)[2]

    def _load(self, href: str) -> tuple[str, str, Parsed]:
        hit = self._cache.get(href)
        if hit is not None:
            self._cache.move_to_end(href)
            return hit
        text, enc = _decode(self._zip.read(href))
        hit = (text, enc, scan(text))
        self._cache[href] = hit
        while len(self._cache) > 6:
            self._cache.popitem(last=False)
        return hit

    def read_text(self, chapter: Chapter) -> str:
        """Decoded text of the chapter file (block offsets refer to it)."""
        return self._load(chapter.href)[0]

    def blocks(self, chapter: Chapter) -> list[Block]:
        return self._parsed(chapter).blocks

    def uncovered_text(self, chapter: Chapter) -> int:
        """Non-whitespace body characters outside every block (stay untranslated)."""
        return self._parsed(chapter).uncovered

    # -- titles --------------------------------------------------------
    def _nav_labels(self) -> dict[str, str]:
        if self._labels is not None:
            return self._labels
        labels: dict[str, str] = {}
        pkg = self._pkg
        for item in pkg.manifest.values():
            if "nav" in item["props"] and item["href"] in self._zip.namelist():
                self._labels_from_nav(item["href"], labels)
        ncx = pkg.manifest.get(pkg.toc_id) or next(
            (i for i in pkg.manifest.values() if i["type"] == NCX_TYPE), None
        )
        if ncx and ncx["href"] in self._zip.namelist():
            self._labels_from_ncx(ncx["href"], labels)
        self._labels = labels
        return labels

    def _labels_from_nav(self, href: str, labels: dict) -> None:
        text, _ = _decode(self._zip.read(href))
        base = posixpath.dirname(href)
        navs = re.findall(r"<nav\b[^>]*>.*?</nav>", text, re.S | re.I)
        pick = next((n for n in navs if re.search(r"epub:type\s*=\s*[\"'][^\"']*toc", n[:300])), None)
        scope = pick or (navs[0] if navs else text)
        for m in re.finditer(r"""<a\b[^>]*?\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')[^>]*>(.*?)</a>""",
                             scope, re.S | re.I):
            target = _resolve(base, m.group(1) or m.group(2) or "")
            label = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", m.group(3)))).strip()
            if target and label:
                labels.setdefault(target, label)

    def _labels_from_ncx(self, href: str, labels: dict) -> None:
        try:
            root = ET.fromstring(self._zip.read(href))
        except ET.ParseError:
            return
        base = posixpath.dirname(href)
        for point in root.iter():
            if _local(point.tag) != "navPoint":
                continue
            label = target = ""
            for el in point:
                if _local(el.tag) == "navLabel":
                    label = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
                elif _local(el.tag) == "content":
                    target = _resolve(base, el.get("src", ""))
            if target and label:
                labels.setdefault(target, label)

    def _title_of(self, chapter: Chapter) -> str:
        label = self._nav_labels().get(chapter.href)
        if label:
            return label
        blocks = self.blocks(chapter)
        pick = next((b for b in blocks if b.tag in ("h1", "h2", "h3", "h4", "h5", "h6")), None)
        if pick is None and blocks:
            pick = blocks[0]
        if pick is None:
            return ""
        return strip_markers(pick.text).split("\n", 1)[0][:100]

    # -- export --------------------------------------------------------
    def export(self, out_path, translations: dict, mode: str, lang: str | None = None) -> list:
        """Write a new EPUB.

        translations: {(href, block index): translated text with markers}.
        mode "single" replaces block content; "bilingual" inserts a translated
        copy after each original. Blocks without a (non-empty) translation are
        left as they are. Returns the keys whose markers did not match and
        were written as plain text (rule: invalid markers => plain text).
        """
        if mode not in ("single", "bilingual"):
            raise ValueError("mode must be 'single' or 'bilingual'")
        if Path(out_path).resolve() == Path(self.path).resolve():
            raise ValueError("output must differ from the source file")
        by_href: dict[str, dict[int, str]] = {}
        for (href, idx), text in translations.items():
            if text and text.strip(" \t\r\n"):
                by_href.setdefault(href, {})[idx] = text
        lang_tag = lang.split(":", 1)[0] if lang else None
        fallbacks: list = []
        with zipfile.ZipFile(out_path, "w") as out:
            for info in self._zip.infolist():
                data = self._zip.read(info.filename)
                if info.filename in by_href:
                    data = self._apply(info.filename, by_href[info.filename], mode, lang_tag, fallbacks)
                elif mode == "single" and lang_tag and info.filename == self._pkg.opf_path:
                    data = _stamp_opf(data, lang_tag)
                out.writestr(copy.copy(info), data, compress_type=info.compress_type)
        return fallbacks

    # -- cut export ----------------------------------------------------
    def export_cut(self, out_path, translations: dict, mode: str, lang: str | None = None,
                   keep=()) -> "CutReport":
        """Write a new EPUB holding only the chapters `keep` (spine positions) and what they need.

        The OPF, the navigation document and the NCX are edited as text (entries
        of dropped documents removed, labels replaced by translated headings);
        chapter documents go through the same replacement as export().
        """
        if mode not in ("single", "bilingual"):
            raise ValueError("mode must be 'single' or 'bilingual'")
        if Path(out_path).resolve() == Path(self.path).resolve():
            raise ValueError("output must differ from the source file")
        pkg = self._pkg
        names = set(self._zip.namelist())
        kept = sorted({i for i in keep if 0 <= i < len(self.chapters)})
        if not kept:
            raise ValueError("no chapters to keep")
        chosen = {self.chapters[i].href: self.chapters[i] for i in kept}
        by_href: dict[str, dict[int, str]] = {}
        for (href, idx), text in translations.items():
            if href in chosen and text and text.strip(" \t\r\n"):
                by_href.setdefault(href, {})[idx] = text
        lang_tag = lang.split(":", 1)[0] if lang else None

        opf_text, opf_enc = _decode(self._zip.read(pkg.opf_path))
        extra_docs = self._cover_page(opf_text)
        doc_hrefs = set(chosen) | extra_docs
        nav_hrefs = {i["href"] for i in pkg.manifest.values() if "nav" in i["props"] and i["href"] in names}
        ncx = pkg.manifest.get(pkg.toc_id) or next(
            (i for i in pkg.manifest.values() if i["type"] == NCX_TYPE), None)
        ncx_href = ncx["href"] if ncx and ncx["href"] in names else ""
        keep_files = self._closure(doc_hrefs, nav_hrefs, ncx_href, opf_text, names)
        keep_files |= doc_hrefs
        doc_items = {i["href"] for i in pkg.manifest.values() if _is_doc(i)}
        dropped_links = 0
        for href in doc_hrefs:
            for link in _scan_refs(self._load(href)[0], posixpath.dirname(href))[0]:
                if link in doc_items and link not in keep_files:
                    dropped_links += 1

        kept_ids = {iid for iid, it in pkg.manifest.items() if it["href"] in keep_files}
        state = _TocState()

        def relabel(target: str, inner: str):
            ch = chosen.get(target)
            if ch is None:
                return None
            label = _norm(unescape(re.sub(r"<[^>]+>", "", inner)))
            if not label:
                return None
            tr = self._heading_translation(ch, label, by_href.get(target, {}))
            if tr:
                state.ok.add(ch.index)
                return escape_text(tr)
            state.bad.add(ch.index)
            return None

        suffix = self._range_suffix(kept)
        spine_ids = {iid for iid, it in pkg.manifest.items() if it["href"] in doc_hrefs}
        new_opf = _cut_opf(opf_text, pkg, kept_ids, spine_ids, keep_files, suffix)
        if mode == "single" and lang_tag:
            new_opf = _stamp_opf(new_opf.encode("utf-8"), lang_tag).decode("utf-8")
        entries = [(self.chapters[i].href, self.chapters[i].title) for i in kept]
        fallbacks: list = []
        written: list[str] = []
        with zipfile.ZipFile(out_path, "w") as out:
            infos = sorted(self._zip.infolist(), key=lambda x: x.filename != "mimetype")
            for info in infos:
                name = info.filename
                if name.endswith("/"):
                    continue
                if name == pkg.opf_path:
                    data = new_opf.encode(opf_enc, errors="xmlcharrefreplace")
                elif name in keep_files or name == "mimetype" or name.startswith("META-INF/"):
                    data = self._zip.read(name)
                    if name in by_href:
                        data = self._apply(name, by_href[name], mode, lang_tag, fallbacks)
                    if name in nav_hrefs:
                        data = _cut_nav(data, name, keep_files, relabel, entries)
                    elif name == ncx_href:
                        data = _cut_ncx(data, name, keep_files, relabel, entries, suffix)
                else:
                    continue
                out.writestr(copy.copy(info), data, compress_type=info.compress_type)
                written.append(name)
        spine = sum(1 for r in _ITEMREF_RE.finditer(new_opf))
        return CutReport(fallbacks, kept, sorted(state.bad),
                         dropped_links, spine, written)

    def _cover_page(self, opf_text: str) -> set[str]:
        """Spine documents that belong to the cover: the guide's cover entry (else an image-only first page)."""
        pkg = self._pkg
        spine_docs = {c.href for c in self.chapters}
        found: set[str] = set()
        for m in _REFERENCE_RE.finditer(opf_text):
            if (_attr(m.group(0), "type") or "").lower() == "cover":
                href = _resolve(pkg.base, _attr(m.group(0), "href") or "")
                if href in spine_docs:
                    found.add(href)
        if not found and self.chapters:
            first = self.chapters[0]
            if not self.blocks(first) and re.search(r"<(?:img|image)\b", self.read_text(first), re.I):
                found.add(first.href)
        return found

    def _closure(self, docs: set, nav_hrefs: set, ncx_href: str, opf_text: str, names: set) -> set[str]:
        """Every file the kept documents need: styles, fonts, images, the cover image, nav, NCX."""
        pkg = self._pkg
        in_manifest = {i["href"]: i for i in pkg.manifest.values()}
        keep: set[str] = set(nav_hrefs)
        if ncx_href:
            keep.add(ncx_href)
        for it in pkg.manifest.values():
            if "cover-image" in it["props"]:
                keep.add(it["href"])
        for m in re.finditer(r"<(?:\w+:)?meta\b[^>]*>", opf_text):
            if (_attr(m.group(0), "name") or "").lower() == "cover":
                it = pkg.manifest.get(_attr(m.group(0), "content") or "")
                if it:
                    keep.add(it["href"])
        queue = list(docs | nav_hrefs)
        scanned: set[str] = set()
        while queue:
            href = queue.pop()
            if href in scanned or href not in names:
                continue
            scanned.add(href)
            item = in_manifest.get(href)
            typ = item["type"] if item else ""
            low = href.lower()
            if not (_is_doc({"type": typ, "href": href}) or typ in ("text/css", "image/svg+xml")
                    or low.endswith((".css", ".svg"))):
                continue
            text = _decode(self._zip.read(href))[0]
            _, resources = _scan_refs(text, posixpath.dirname(href), css=low.endswith(".css") or typ == "text/css")
            for res in resources:
                it = in_manifest.get(res)
                if it is None or res not in names or _is_doc(it):
                    continue
                keep.add(res)
                queue.append(res)
        return {h for h in keep if h in names}

    def _range_suffix(self, kept: list[int]) -> str:
        first, last = self.chapters[kept[0]], self.chapters[kept[-1]]
        la, lb = _norm_keep(first.title), _norm_keep(last.title)
        count = f"{len(kept)} chapters" if len(kept) != 1 else "1 chapter"
        if first is last:
            na = printed_number(first.title)
            span = la if 0 < len(la) <= 40 else (str(na) if na is not None else count)
        else:
            if 0 < len(la) <= 24 and 0 < len(lb) <= 24:
                span = f"{la} - {lb}"
            else:
                # the numbers printed in the labels, never spine positions
                na, nb = printed_number(first.title), printed_number(last.title)
                if na is None or nb is None or na >= nb:
                    return " (" + count + ")"
                span = f"{na}-{nb}"
            if len(kept) != last.index - first.index + 1:
                span += f", {count}"
        return " (" + escape_text(span) + ")"

    def _heading_translation(self, chapter: Chapter, label: str, trans: dict) -> str | None:
        """Translation of the chapter's heading that carries `label` (normalised), or None."""
        def tr(b: Block):
            t = _norm_keep(strip_markers(trans.get(b.index, "")))
            return t or None

        blocks = self.blocks(chapter)
        for b in blocks:
            if b.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                s = _norm(strip_markers(b.text))
                if s and (s == label or label in s) and tr(b):
                    return tr(b)
        for b in blocks:
            if _norm(strip_markers(b.text)) == label and tr(b):
                return tr(b)
        return None

    def _apply(self, href, trans, mode, lang_tag, fallbacks) -> bytes:
        text, enc, parsed = self._load(href)
        edits: list[tuple[int, int, str]] = []
        for b in parsed.blocks:
            tr = trans.get(b.index)
            if tr is None:
                continue
            tr = tr.strip(" \t\r\n")
            if mode == "single" and tr == b.text:
                continue  # unchanged text: keep the original bytes (markup, entities)
            body, ok = to_html(b, tr, copy=(mode == "bilingual"))
            if not ok:
                fallbacks.append((href, b.index))
            if mode == "single":
                edits.append((b.start, b.end, body))
            elif b.kind == "element":
                opener = strip_id(text[b.outer_start:b.open_end])
                edits.append((b.outer_end, b.outer_end, opener + body + text[b.close_start:b.outer_end]))
            else:
                edits.append((b.end, b.end, "<br/>" + body))
        for start, end, rep in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
            text = text[:start] + rep + text[end:]
        if mode == "single" and lang_tag:
            text = _stamp_html_lang(text, lang_tag)
        return text.encode(enc, errors="xmlcharrefreplace")


def _stamp_opf(data: bytes, tag: str) -> bytes:
    text, enc = _decode(data)
    pat = re.compile(r"(<(?:\w+:)?language\b[^>]*>)(.*?)(</(?:\w+:)?language>)", re.S)
    if pat.search(text):
        text = pat.sub(lambda m: m.group(1) + tag + m.group(3), text, count=1)
    else:
        text = re.sub(r"</(?:\w+:)?metadata>", lambda m: f"<dc:language>{tag}</dc:language>{m.group(0)}",
                      text, count=1)
    return text.encode(enc, errors="xmlcharrefreplace")


def _stamp_html_lang(text: str, tag: str) -> str:
    m = re.search(r"<html\b[^>]*>", text, re.I)
    if not m:
        return text
    head = m.group(0)
    xhtml = "xmlns=" in head

    def setattr_(h: str, name: str) -> str:
        pat = re.compile(r"(\s%s\s*=\s*)(?:\"[^\"]*\"|'[^']*')" % re.escape(name), re.I)
        if pat.search(h):
            return pat.sub(lambda mm: f'{mm.group(1)}"{tag}"', h, count=1)
        return h[:-1].rstrip("/").rstrip() + f' {name}="{tag}"' + ("/>" if h.endswith("/>") else ">")

    new = setattr_(head, "lang")
    if xhtml or re.search(r"\sxml:lang\s*=", head):
        new = setattr_(new, "xml:lang")
    return text[:m.start()] + new + text[m.end():]


# -- cut export helpers ----------------------------------------------------
@dataclass
class CutReport:
    fallbacks: list
    kept: list  # chapter indices written
    toc_untranslated: list  # chapter indices whose TOC label stayed as in the source
    dropped_links: int  # links inside kept documents that point to dropped documents
    spine_items: int
    files: list  # zip entries written, in order


class _TocState:
    def __init__(self):
        self.ok: set[int] = set()
        self.bad: set[int] = set()


_TAG_ATTRS = r"""(?:"[^"]*"|'[^']*'|[^>"'])*"""
_ITEM_RE = re.compile(r"<(?:\w+:)?item\b%s>(?:\s*</(?:\w+:)?item\s*>)?" % _TAG_ATTRS)
_ITEMREF_RE = re.compile(r"<(?:\w+:)?itemref\b%s>(?:\s*</(?:\w+:)?itemref\s*>)?" % _TAG_ATTRS)
_REFERENCE_RE = re.compile(r"<(?:\w+:)?reference\b%s>(?:\s*</(?:\w+:)?reference\s*>)?" % _TAG_ATTRS)
_GUIDE_RE = re.compile(r"[ \t]*<(?:\w+:)?guide\b[^>]*>\s*</(?:\w+:)?guide\s*>[ \t]*(?:\r?\n)?")
_ATTR_RE = re.compile(r"""(?<![\w:.-])([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_TAG_RE = re.compile(r"<([A-Za-z][\w:.-]*)\b(%s)>" % _TAG_ATTRS)
_CSS_URL_RE = re.compile(
    r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s"']*))\s*\)|@import\s+(?:"([^"]*)"|'([^']*)')""", re.I)
_SCHEME_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")
_WS_RE = re.compile(r"\s+")


def _attr(tag: str, name: str) -> str | None:
    for m in _ATTR_RE.finditer(tag):
        if m.group(1).lower() == name:
            return unescape(m.group(2) if m.group(2) is not None else m.group(3))
    return None


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().casefold()


def _norm_keep(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


_AFTER_WORD_RE = re.compile(r"(?:chapter|глава|розділ|rozdział)\D*?(\d+)", re.I)


def printed_number(label: str) -> int | None:
    """The chapter number a label prints: the first integer after the word Chapter / Глава / Розділ /
    Rozdział, else the first integer in the label, else None."""
    m = _AFTER_WORD_RE.search(label) or re.search(r"\d+", label)
    if m is None:
        return None
    try:
        return int(m.group(m.lastindex or 0))
    except ValueError:
        return None


def _local_target(base: str, ref: str) -> str | None:
    """Zip path of a relative reference; "" for a fragment-only one; None for an external one."""
    ref = (ref or "").strip()
    if _SCHEME_RE.match(ref):
        return None
    return _resolve(base, ref)


def _scan_refs(text: str, base: str, css: bool = False) -> tuple[list[str], list[str]]:
    """(targets of <a href>, other referenced files) of a document or style sheet, as zip paths."""
    links: list[str] = []
    res: list[str] = []
    if not css:
        for m in _TAG_RE.finditer(text):
            name = m.group(1).lower().rsplit(":", 1)[-1]
            for am in _ATTR_RE.finditer(m.group(2)):
                key = am.group(1).lower()
                if key not in ("src", "href", "xlink:href", "poster", "data"):
                    continue
                target = _local_target(base, unescape(am.group(2) if am.group(2) is not None else am.group(3)))
                if not target:
                    continue
                if name == "a" and key in ("href", "xlink:href"):
                    links.append(target)
                else:
                    res.append(target)
    for m in _CSS_URL_RE.finditer(text):
        ref = next((g for g in m.groups() if g), "")
        target = _local_target(base, unescape(ref))
        if target:
            res.append(target)
    return links, res


class _Node:
    __slots__ = ("name", "open", "parts", "close")

    def __init__(self, name="", open_="", close=""):
        self.name = name
        self.open = open_
        self.parts: list = []
        self.close = close


def _build_tree(text: str, tag_re) -> "_Node | None":
    """Nest the tags matched by `tag_re` (groups: closing slash, name); None when they do not balance."""
    root = _Node()
    stack = [root]
    pos = 0
    for m in tag_re.finditer(text):
        if m.start() > pos:
            stack[-1].parts.append(text[pos:m.start()])
        pos = m.end()
        name = m.group(2).lower()
        if m.group(0).endswith("/>"):
            stack[-1].parts.append(m.group(0))
        elif not m.group(1):
            node = _Node(name, m.group(0))
            stack[-1].parts.append(node)
            stack.append(node)
        else:
            if len(stack) < 2 or stack[-1].name != name:
                return None
            stack[-1].close = m.group(0)
            stack.pop()
    if len(stack) != 1:
        return None
    if pos < len(text):
        root.parts.append(text[pos:])
    return root


def _render_tree(node: "_Node") -> str:
    return node.open + "".join(p if isinstance(p, str) else _render_tree(p) for p in node.parts) + node.close


def _dropped(base: str, ref: str, keep: set) -> bool:
    """True for a local reference to a file that is not in the cut book."""
    target = _local_target(base, ref)
    return bool(target) and target not in keep


def _cut_opf(text: str, pkg, kept_ids: set, spine_ids: set, keep_files: set, suffix: str) -> str:
    def drop(pattern, test):
        nonlocal text
        text = pattern.sub(lambda m: "" if test(m.group(0)) else m.group(0), text)

    drop(_ITEM_RE, lambda t: (_attr(t, "id") or "") not in kept_ids)
    drop(_ITEMREF_RE, lambda t: (_attr(t, "idref") or "") not in spine_ids)
    drop(_REFERENCE_RE, lambda t: _dropped(pkg.base, _attr(t, "href") or "", keep_files))
    text = _GUIDE_RE.sub("", text)
    text = re.sub(r"\n[ \t]*(?=\n)", "", text)
    pat = re.compile(r"(<(?:\w+:)?title\b[^>]*>)(.*?)(</(?:\w+:)?title\s*>)", re.S)
    return pat.sub(lambda m: m.group(1) + m.group(2) + suffix + m.group(3), text, count=1)


_NAV_TAG_RE = re.compile(r"<(/?)(ol|ul|li)\b%s>" % _TAG_ATTRS, re.I)
_A_RE = re.compile(r"<a\b(%s)>(.*?)</a\s*>" % _TAG_ATTRS, re.S | re.I)
_NAV_EL_RE = re.compile(r"<nav\b(%s)>(.*?)</nav\s*>" % _TAG_ATTRS, re.S | re.I)


def _cut_nav(data: bytes, name: str, keep: set, relabel, entries: list) -> bytes:
    text, enc = _decode(data)
    base = posixpath.dirname(name)
    navs = list(_NAV_EL_RE.finditer(text))
    typed = [bool(re.search(r"\btoc\b", _attr("<nav" + m.group(1) + ">", "epub:type") or "")) for m in navs]
    toc_at = typed.index(True) if True in typed else 0

    labels_on = [False]

    def fix_anchors(s: str):
        kept = anchors = 0

        def one(m):
            nonlocal kept, anchors
            anchors += 1
            href = _attr("<a " + m.group(1) + ">", "href") or ""
            if _dropped(base, href, keep):
                return "<span>" + m.group(2) + "</span>"
            kept += 1
            target = _local_target(base, href)
            new = relabel(target, m.group(2)) if target and labels_on[0] else None
            return m.group(0) if new is None else "<a" + m.group(1) + ">" + new + "</a>"

        return _A_RE.sub(one, s), kept

    def filter_list(node: _Node) -> bool:
        parts, alive = [], False
        for p in node.parts:
            if isinstance(p, str):
                parts.append(p)
            elif p.name == "li":
                if filter_li(p):
                    parts.append(p)
                    alive = True
            elif filter_list(p):
                parts.append(p)
                alive = True
        node.parts = parts
        return alive

    def filter_li(li: _Node) -> bool:
        kept, child, parts = 0, False, []
        for p in li.parts:
            if isinstance(p, str):
                p, k = fix_anchors(p)
                kept += k
                parts.append(p)
            elif filter_list(p):
                child = True
                parts.append(p)
        li.parts = parts
        return bool(kept) or child

    def rebuild(m, idx: int) -> str:
        labels_on[0] = idx == toc_at
        root = _build_tree(m.group(2), _NAV_TAG_RE)
        if root is None:
            return m.group(0)
        alive = filter_list(root)
        if not alive and idx != toc_at:
            return ""
        inner = _render_tree(root)
        if not alive:
            items = "".join(
                f'<li><a href="{_rel_href(base, h)}">{escape_text(t)}</a></li>' for h, t in entries)
            inner = f"\n<ol>{items}</ol>\n"
        return "<nav" + m.group(1) + ">" + inner + "</nav>"

    out, pos = [], 0
    for idx, m in enumerate(navs):
        out.append(text[pos:m.start()])
        out.append(rebuild(m, idx))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out).encode(enc, errors="xmlcharrefreplace")


def _rel_href(base: str, target: str) -> str:
    return quote(posixpath.relpath(target, base or "."), safe="/")


_NCX_TAG_RE = re.compile(r"<(/?)(navPoint)\b%s>" % _TAG_ATTRS)
_SRC_RE = re.compile(r"""(<content\b[^>]*?\bsrc\s*=\s*)(?:"([^"]*)"|'([^']*)')""")
_NAV_TEXT_RE = re.compile(r"(<navLabel\b[^>]*>\s*<text\b[^>]*>)(.*?)(</text>)", re.S)


def _cut_ncx(data: bytes, name: str, keep: set, relabel, entries: list, suffix: str) -> bytes:
    text, enc = _decode(data)
    base = posixpath.dirname(name)
    root = _build_tree(text, _NCX_TAG_RE)
    if root is None:
        return data

    def own_src(node: _Node) -> str | None:
        for p in node.parts:
            if isinstance(p, str):
                m = _SRC_RE.search(p)
                if m:
                    return m.group(2) if m.group(2) is not None else m.group(3)
        return None

    def filter_point(node: _Node) -> bool:
        parts, child = [], False
        for p in node.parts:
            if isinstance(p, str):
                parts.append(p)
            elif filter_point(p):
                child = True
                parts.append(p)
        node.parts = parts
        src = own_src(node)
        own = src is not None and not _dropped(base, src, keep)
        if own:
            target = _local_target(base, src)
            for i, p in enumerate(node.parts):
                if isinstance(p, str) and target:
                    node.parts[i] = _NAV_TEXT_RE.sub(
                        lambda m: m.group(1) + (relabel(target, m.group(2)) or m.group(2)) + m.group(3), p, count=1)
        elif child:
            first = next(_SRC_RE.search(_render_tree(p)) for p in node.parts if isinstance(p, _Node))
            new_src = first.group(2) if first.group(2) is not None else first.group(3)
            for i, p in enumerate(node.parts):
                if isinstance(p, str) and _SRC_RE.search(p):
                    node.parts[i] = _SRC_RE.sub(lambda m: m.group(1) + '"' + new_src + '"', p, count=1)
                    break
        return own or child

    alive = False
    parts = []
    for p in root.parts:
        if isinstance(p, str):
            parts.append(p)
        elif filter_point(p):
            parts.append(p)
            alive = True
    root.parts = parts
    out = _render_tree(root)
    if not alive:
        pts = "".join(
            f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{escape_text(t)}</text></navLabel>'
            f'<content src="{_rel_href(base, h)}"/></navPoint>' for i, (h, t) in enumerate(entries, 1))
        out = re.sub(r"</navMap\s*>", lambda m: pts + m.group(0), out, count=1)

    def target_gone(m):
        src = _SRC_RE.search(m.group(0))
        s = (src.group(2) if src.group(2) is not None else src.group(3)) if src else None
        return "" if s is not None and _dropped(base, s, keep) else m.group(0)

    out = re.sub(r"<(pageTarget|navTarget)\b[^>]*>.*?</\1\s*>", target_gone, out, flags=re.S)
    out = re.sub(r"[ \t]*<(pageList|navList)\b[^>]*>(?:(?!<pageTarget|<navTarget).)*?</\1\s*>[ \t]*(?:\r?\n)?",
                 "", out, flags=re.S)
    counter = iter(range(1, 10 ** 9))
    out = re.sub(r"""(\bplayOrder\s*=\s*)(?:"\d*"|'\d*')""", lambda m: f'{m.group(1)}"{next(counter)}"', out)
    out = re.sub(r"(<docTitle\b[^>]*>\s*<text\b[^>]*>)(.*?)(</text>)",
                 lambda m: m.group(1) + m.group(2) + suffix + m.group(3), out, count=1, flags=re.S)
    return out.encode(enc, errors="xmlcharrefreplace")


def check(path, source=None, strict: bool = False) -> list[str]:
    """Structural problems of an EPUB (empty list = fine).

    When `source` is given, documents that are already not well-formed in the
    source are not reported again.
    """
    problems: list[str] = []
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return [f"not a zip file: {exc}"]
    with zf:
        infos = zf.infolist()
        if not infos or infos[0].filename != "mimetype":
            problems.append("mimetype is not the first entry")
        else:
            if infos[0].compress_type != zipfile.ZIP_STORED:
                problems.append("mimetype is compressed")
            if zf.read("mimetype").strip() != b"application/epub+zip":
                problems.append("mimetype has a wrong value")
        try:
            pkg = _Package(zf)
        except EpubError as exc:
            problems.append(str(exc))
            return problems
        names = set(zf.namelist())
        for iid, item in pkg.manifest.items():
            if item["href"] not in names:
                problems.append(f"manifest item {iid} missing in zip: {item['href']}")
        for idref in pkg.spine:
            if idref not in pkg.manifest:
                problems.append(f"spine idref not in manifest: {idref}")
        broken_in_source: set[str] = set()
        if source is not None:
            try:
                with zipfile.ZipFile(source) as sz:
                    for item in pkg.manifest.values():
                        if item["type"] == "application/xhtml+xml" and item["href"] in sz.namelist():
                            try:
                                ET.fromstring(sz.read(item["href"]))
                            except ET.ParseError:
                                broken_in_source.add(item["href"])
            except (zipfile.BadZipFile, OSError):
                pass
        for idref in pkg.spine:
            item = pkg.manifest.get(idref)
            if not item or item["type"] != "application/xhtml+xml" or item["href"] not in names:
                continue
            try:
                ET.fromstring(zf.read(item["href"]))
            except ET.ParseError as exc:
                if item["href"] not in broken_in_source:
                    problems.append(f"not well-formed: {item['href']}: {exc}")
        if strict:
            problems.extend(_strict_problems(zf, pkg, names, broken_in_source))
    return problems


def _strict_problems(zf, pkg, names: set, broken_in_source: set) -> list[str]:
    """Extra checks for a cut export: the zip and the manifest agree, every navigation target exists."""
    problems: list[str] = []
    listed = {item["href"] for item in pkg.manifest.values()}
    for name in sorted(names):
        if name.endswith("/") or name == "mimetype" or name.startswith("META-INF/") or name == pkg.opf_path:
            continue
        if name not in listed:
            problems.append(f"file not in manifest: {name}")
    seen_spine = set()
    for idref in pkg.spine:
        if idref in seen_spine:
            problems.append(f"spine idref twice: {idref}")
        seen_spine.add(idref)
    for item in pkg.manifest.values():
        href = item["href"]
        if href not in names:
            continue
        if _is_doc(item) and item["type"] == "application/xhtml+xml" and href not in broken_in_source:
            try:
                ET.fromstring(zf.read(href))
            except ET.ParseError as exc:
                problems.append(f"not well-formed: {href}: {exc}")
        base = posixpath.dirname(href)
        if "nav" in item["props"]:
            text = _decode(zf.read(href))[0]
            for nav in _NAV_EL_RE.finditer(text):
                for a in _A_RE.finditer(nav.group(2)):
                    _check_target(problems, names, base, _attr("<a " + a.group(1) + ">", "href") or "", href)
        elif item["type"] == NCX_TYPE:
            text = _decode(zf.read(href))[0]
            for m in _SRC_RE.finditer(text):
                _check_target(problems, names, base, m.group(2) if m.group(2) is not None else m.group(3), href)
    return problems


def _check_target(problems: list, names: set, base: str, ref: str, owner: str) -> None:
    target = _local_target(base, ref)
    if target and target not in names:
        problems.append(f"navigation target missing: {owner} -> {ref}")
