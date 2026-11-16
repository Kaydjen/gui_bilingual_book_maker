"""Finding the terms of a base in text, and the lines that go into a translation request.

Matching is case-insensitive, word-bounded and longest-first. Variants that are not stored in `forms`:
a plural "s"/"es" after the term, a possessive 's / ’s (the apostrophe is not a word character), and a
leading "the" of the term itself being optional. The index is keyed by the first word of every spelling,
so a text is walked once with one dictionary lookup per word; there is no regex per term.
"""

from __future__ import annotations

import re
import threading
import time

from .htmlscan import strip_markers
from .profiles import get as get_profile
from .terms import FILE_NAME, Entry, TermBase, norm_key
from .translate import HEADING

_WORD = re.compile(r"\w+")
_NORMALISE = {ord(c): "'" for c in "’‘ʼ´`"}
_NORMALISE.update({ord(c): " " for c in "\n\r\t\x0b\x0c      "})
HEAD_TERMS = "Terms in this text (use these renderings exactly):"
HEAD_CHARACTERS = "Characters of this chapter (for gender agreement):"


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def gender_marks(tag: str) -> dict[str, str]:
    """Gender marks for a target tag (`ru`, `ru-RU`, `ru:Russian`), from the language profile."""
    profile = get_profile(tag)
    return profile.gender_marks if profile.send_gender else {}


def lowered(text: str) -> str:
    """Lower-cased text with straight apostrophes and single-character whitespace; same length as `text`."""
    t = text.translate(_NORMALISE)
    low = t.lower()
    if len(low) != len(t):  # a few letters lower-case to two characters; keep offsets
        low = "".join(c.lower() if len(c.lower()) == 1 else c for c in t)
    return low


def text_of(block) -> str:
    """Plain text of a block object or a string (markers removed)."""
    return strip_markers(block if isinstance(block, str) else block.text)


class Matcher:
    def __init__(self, base: TermBase):
        self.base = base
        self._rev = -1
        self._index: dict[str, list[tuple[str, int, Entry]]] = {}
        self.has_characters = False
        self._lock = threading.Lock()

    def _sync(self) -> dict:
        if self._rev != self.base.rev:
            with self._lock:
                if self._rev != self.base.rev:
                    self._build()
        return self._index

    def _build(self) -> None:
        index: dict[str, list[tuple[str, int, Entry]]] = {}
        seen: set[tuple[str, int]] = set()
        chars = False
        for e in self.base.sorted_entries():
            if e.type == "character" and e.tr:
                chars = True
            for sp in e.spellings():
                k = norm_key(sp)
                spell = [k]
                if k.startswith("the ") and len(k) > 4:
                    spell.append(k[4:])
                for s in spell:
                    m = _WORD.search(s)
                    if m is None or (s, id(e)) in seen:
                        continue
                    seen.add((s, id(e)))
                    tok = m.group()
                    keys = [tok]
                    if s.endswith(tok) and s[m.start():] == tok:  # a single word: its plural opens the same entry
                        keys += [tok + "s", tok + "es"]
                    for key in keys:
                        index.setdefault(key, []).append((s, m.start(), e))
        for lst in index.values():
            lst.sort(key=lambda it: (-len(it[0]), it[2].source))
        self._index = index
        self.has_characters = chars
        self._rev = self.base.rev

    def match(self, text: str) -> list[tuple[Entry, int, int]]:
        """Entries found in `text` as (entry, start, end), left to right, longest term first; a term that
        lies inside a longer match is not reported there (it still matches on its own elsewhere)."""
        index = self._sync()
        if not index or not text:
            return []
        low = lowered(text)
        n = len(low)
        out: list[tuple[Entry, int, int]] = []
        covered = 0
        for m in _WORD.finditer(low):
            s = m.start()
            if s < covered:
                continue
            cands = index.get(m.group())
            if not cands:
                continue
            for spelling, lead, entry in cands:
                b = s - lead
                if b < covered or not low.startswith(spelling, b):
                    continue
                e = b + len(spelling)
                if e < n and _is_word(spelling[-1]) and _is_word(low[e]):
                    if low.startswith("s", e) and (e + 1 >= n or not _is_word(low[e + 1])):
                        e += 1
                    elif low.startswith("es", e) and (e + 2 >= n or not _is_word(low[e + 2])):
                        e += 2
                    else:
                        continue
                out.append((entry, b, e))
                covered = e
                break
        return out

    def scan_chapter(self, blocks) -> dict[Entry, int]:
        """{entry: number of hits} over the blocks, in order of first appearance."""
        counts: dict[Entry, int] = {}
        if not self._sync():
            return counts
        for b in blocks:
            for entry, _s, _e in self.match(text_of(b)):
                counts[entry] = counts.get(entry, 0) + 1
        return counts


def scan_book(base: TermBase, book, first: int = 0, last: int | None = None, matcher: Matcher | None = None) -> dict:
    """Match the base against chapters first..last of `book` and update `seen`/`count` of the entries.
    Returns numbers: chapters, matched (distinct entries), hits, seconds, peak chapters per second."""
    matcher = matcher or Matcher(base)
    chapters = book.chapters
    hi = len(chapters) - 1 if last is None else min(last, len(chapters) - 1)
    t0 = time.perf_counter()
    done = hits = 0
    matched: set[int] = set()
    window: list[float] = []
    peak = 0.0
    for ch in chapters[max(first, 0):hi + 1]:
        if ch.is_toc:
            continue
        counts = matcher.scan_chapter(book.blocks(ch))
        for e, n in counts.items():
            base.record_seen(e, ch.index, n)
            matched.add(id(e))
            hits += n
        done += 1
        now = time.perf_counter()
        window.append(now)
        while window and window[0] < now - 1.0:
            window.pop(0)
        peak = max(peak, len(window))
    return {"chapters": done, "matched": len(matched), "hits": hits,
            "seconds": round(time.perf_counter() - t0, 3), "peak_chapters_per_second": peak}


class TermsHook:
    """The `terms_for(chapter, blocks) -> list[str]` hook of the runner, backed by a term base.

    The result may carry heading lines (marked with HEADING) that separate the two lists; the request
    builder turns them into one-line headings."""

    def __init__(self, base: TermBase, blocks_of=None):
        self.base = base
        self.matcher = Matcher(base)
        self.blocks_of = blocks_of  # chapter -> list of blocks; None = the chapter's own group only
        self._chars: dict[object, tuple[int, list[Entry]]] = {}
        self._lock = threading.Lock()

    def __call__(self, chapter, group) -> list[str]:
        whole = (lambda: self.blocks_of(chapter)) if self.blocks_of else None
        return self.lines_for(whole if whole else group, group, chapter_key=getattr(chapter, "index", None))

    def line(self, entry: Entry, hint: bool = True, only_mf: bool = False) -> str:
        gender = self.base.request_gender(entry)  # an open gender question is sent as unknown
        mark = gender_marks(self.base.tag).get(gender, "")
        if only_mf and gender not in ("male", "female"):
            mark = ""
        text = f"{entry.source} -> {entry.tr}" + (f" ({mark})" if mark else "")
        if hint and entry.hint and entry.note:
            text += f" - {entry.note}"
        return text

    def chapter_characters(self, chapter_blocks, key=None) -> list[Entry]:
        """Character entries (with a translation) found anywhere in the chapter, by first appearance."""
        self.matcher._sync()
        if not self.matcher.has_characters:
            return []
        with self._lock:
            hit = self._chars.get(key) if key is not None else None
            if hit is not None and hit[0] == self.base.rev:
                return hit[1]
        blocks = chapter_blocks() if callable(chapter_blocks) else chapter_blocks
        found = [e for e in self.matcher.scan_chapter(blocks) if e.type == "character" and e.tr]
        if key is not None:
            with self._lock:
                self._chars[key] = (self.base.rev, found)
        return found

    def lines_for(self, chapter_blocks, group_blocks, chapter_key=None) -> list[str]:
        """(a) one line per entry found in the group, (b) the characters of the whole chapter not listed in (a)."""
        group = [e for e in self.matcher.scan_chapter(group_blocks) if e.tr]
        listed = {id(e) for e in group}
        lines_a = [self.line(e) for e in group]
        lines_b = [self.line(e, hint=False, only_mf=True) for e in self.chapter_characters(chapter_blocks, chapter_key)
                   if id(e) not in listed]
        out: list[str] = []
        if lines_a:
            out += [HEADING + HEAD_TERMS] + lines_a
        if lines_b:
            out += [HEADING + HEAD_CHARACTERS] + lines_b
        return out


def hook_for_series(series, blocks_of=None) -> TermsHook | None:
    """A TermsHook when the series has a terms.json, else None (nothing changes without the file)."""
    path = series.path / FILE_NAME
    if not path.exists():
        return None
    return TermsHook(TermBase.load(path, series.target_tag), blocks_of)
