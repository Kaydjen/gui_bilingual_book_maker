"""Reviewed frontier: a chapter may be translated only when every term found in it is reviewed.

A term is reviewed when it is a confirmed entry of the base, or when the owner dismissed it ("not a term").
Terms found in a chapter, offline:
  (a) base entries matched in the chapter whose status is not `confirmed`   (kinds entry-new, entry-question)
  (b) capitalised candidates mined from the text (termmine) that are neither in the base nor dismissed
      (kind candidate), after the conservative filters of `Filters`.
A confirmed entry with an open question does not block. An unconfirmed entry blocks, with or without question.

Two caches live in <series>/.state/:
  frontier_chunks_<book>.json  per chapter: mined candidates and matched entries (keyed by the book file;
                               the matches also by the spellings of the base, so confirming or dismissing
                               never makes the EPUB be read again)
  frontier_<book>.json         the derived answer (keyed by the book file, terms.json, its content digest,
                               the dismissed list and the filters)
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import threading
import time
from collections import Counter, namedtuple
from dataclasses import dataclass, fields
from pathlib import Path

from .epub import Book
from .store import atomic_write_text, safe_name
from .termmatch import Matcher, text_of
from .termmine import STOP, mine_candidates
from .terms import FILE_NAME, TermBase, format_seen, norm_key, parse_seen

KIND_NEW = "entry-new"
KIND_QUESTION = "entry-question"
KIND_CANDIDATE = "candidate"
KIND_KNOWN = "entry-confirmed"  # never blocks; listed in terms() only
BLOCKING = (KIND_NEW, KIND_QUESTION, KIND_CANDIDATE)

CACHE_VERSION = 2
# A job is gated only by unconfirmed base entries until the model extraction supplies the candidates:
# candidates start to block (set True) once that extraction exists. Mined candidates are suggestions meanwhile.
GATE_CANDIDATES = False
STATE_DIR = ".state"

# Filters of the mined candidates (all applied on book-wide totals, after the per-chapter mining).
MIN_BOOK_COUNT = 2      # a candidate blocks only if seen at least this often in the whole book (a term met once
                        # cannot be rendered inconsistently) ...
MIN_BOOK_MID = 0        # ... or, when this is above 0, at least this often in the middle of a sentence
MIN_BOOK_CHAPTERS = 1   # seen in at least this many chapters (2 = a term confined to one chapter does not block)
LOWER_RATIO = 1.0       # a single word is a common word, not a term, when its lower-case form occurs at least
                        # this many times per mid-sentence capitalised use (0 = off)
MAX_WORDS = 5           # longer runs are sentences glued together, not names
STRIP_NUMBERS = True    # "5 Kobold Chieftain" and "Agility 70" are judged as "Kobold Chieftain" and "Agility"
STRIP_KNOWN_EDGES = True  # a confirmed entry (or number, connector) at either end is cut off; nothing left = covered
DROP_STOP_SINGLES = True  # a single word of termmine's stop list is not a term

_CONNECTORS = {"of", "the", "and", "in", "to", "no."}
_LOWER_WORD = re.compile(r"(?<![A-Za-z])[a-z]+(?![A-Za-z])")


@dataclass(frozen=True)
class Filters:
    min_book_count: int = MIN_BOOK_COUNT
    min_book_mid: int = MIN_BOOK_MID
    min_book_chapters: int = MIN_BOOK_CHAPTERS
    lower_ratio: float = LOWER_RATIO
    max_words: int = MAX_WORDS
    strip_numbers: bool = STRIP_NUMBERS
    strip_known_edges: bool = STRIP_KNOWN_EDGES
    drop_stop_singles: bool = DROP_STOP_SINGLES

    def digest(self) -> str:
        return hashlib.sha1(repr([getattr(self, f.name) for f in fields(self)]).encode()).hexdigest()[:12]


NO_FILTERS = Filters(min_book_count=0, min_book_mid=0, min_book_chapters=1, lower_ratio=0, max_words=99, strip_numbers=False,
                     strip_known_edges=False, drop_stop_singles=False)

# text: shown term; kind: one of the KIND_ values; count: hits (in the chapter, or in the asked range);
# first: first chapter index (overall, or inside the asked range); chapters: ranges like "3-5,9"
Item = namedtuple("Item", "text kind count first chapters")
FrontierInfo = namedtuple("FrontierInfo", "chapter count total capped")  # chapter None = nothing blocks
ScanReport = namedtuple("ScanReport", "chapters read matched seconds cancelled source")


class NotScanned(RuntimeError):
    """Asked before any scan or cache load: the frontier is unknown, so nothing may be called allowed."""


def _stat(path) -> list[int]:
    try:
        st = Path(path).stat()
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return [-1, -1]


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def spelling_signature(base: TermBase) -> str:
    """Digest of every spelling of every entry: what the per-chapter matches depend on."""
    keys = sorted(norm_key(s) for e in base.sorted_entries() for s in e.spellings())
    return _sha("\n".join(keys))


def base_digest(base: TermBase) -> str:
    """Digest of what decides blocking: spellings, status, open questions."""
    rows = [f"{e.source}\t{e.status}\t{int(bool(e.questions))}\t" + "|".join(e.forms) for e in base.sorted_entries()]
    return _sha("\n".join(rows))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def _cancelled(cancel) -> bool:
    if cancel is None:
        return False
    return bool(cancel.is_set() if hasattr(cancel, "is_set") else cancel())


def _is_number(word: str) -> bool:
    return word.isdigit()


def reduce_candidate(term: str, base: TermBase, flt: Filters) -> str | None:
    """The part of a mined candidate that still needs review, or None when nothing does."""
    if base.get(term) is not None or base.is_dismissed(term):
        return None
    words = term.split(" ")
    if flt.strip_numbers or flt.strip_known_edges:
        while words:
            head, tail = words[0], words[-1]
            if flt.strip_numbers and (_is_number(head) or head.lower() in _CONNECTORS):
                words = words[1:]
                continue
            if flt.strip_numbers and (_is_number(tail) or tail.lower() in _CONNECTORS):
                words = words[:-1]
                continue
            if flt.strip_known_edges:
                cut = False
                for j in range(len(words), 0, -1):
                    e = base.get(" ".join(words[:j]))
                    if e is not None and e.status == "confirmed":
                        words, cut = words[j:], True
                        break
                if cut:
                    continue
                for i in range(len(words)):
                    e = base.get(" ".join(words[i:]))
                    if e is not None and e.status == "confirmed":
                        words, cut = words[:i], True
                        break
                if cut:
                    continue
            break
    if not words or len(words) > flt.max_words:
        return None
    out = " ".join(words)
    if len(out) < 3:
        return None
    if len(words) == 1 and flt.drop_stop_singles and words[0] in STOP:
        return None
    if out != term and (base.get(out) is not None or base.is_dismissed(out)):
        return None
    return out


class _Derived:
    """Immutable answer for one state of the base. Replaced as a whole, never edited."""

    def __init__(self, nchap, toc, items, by_chapter, rev, terms=None, mined=True):
        self.mined = mined  # False: built without the candidate mining (entries only)
        self.nchap = nchap
        self.toc = toc  # frozenset of chapter indices that are TOC pages
        self.items = items  # list of (text, kind, total, first, ranges); blocking items only unless terms given
        self.by_chapter = by_chapter  # chapter -> tuple of (item id, count), count descending
        self.order = sorted(by_chapter)
        self.rev = rev
        self.terms = terms  # {key: Item} of everything found, or None when loaded from the answer cache


class Frontier:
    def __init__(self, base: TermBase, book_path, state_dir, filters: Filters | None = None, book_name: str | None = None):
        self.base = base
        self.book_path = Path(book_path)
        self.state_dir = Path(state_dir)
        self.filters = filters or Filters()
        self.book_name = safe_name(book_name or self.book_path.stem, 80, "book")
        self._lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._d: _Derived | None = None
        self._chunks: dict | None = None  # {"msig", "toc", "nchap", "rows": {idx: {"c":..., "m":...}}}
        self._raw: dict | None = None  # raw candidate totals {term: [count, mid]}
        self._stale = False
        self._sig_memo: list = [None, ""]
        self.last_report: ScanReport | None = None

    @classmethod
    def for_series(cls, series, book: str | None = None, base: TermBase | None = None, filters: Filters | None = None):
        names = series.book_names()
        if book is None:
            if len(names) != 1:
                raise ValueError("several books in the series: name one of " + ", ".join(names))
            book = names[0]
        if base is None:
            base = TermBase.load(series.path / FILE_NAME, series.target_tag)
        return cls(base, series.path / "books" / (book + ".epub"), series.path / STATE_DIR, filters, book)

    # -- cache files --------------------------------------------------------
    @property
    def chunks_path(self) -> Path:
        return self.state_dir / f"frontier_chunks_{self.book_name}.json"

    @property
    def answer_path(self) -> Path:
        return self.state_dir / f"frontier_{self.book_name}.json"

    def _answer_key(self) -> dict:
        terms_path = self.base.path
        return {"v": CACHE_VERSION, "book": _stat(self.book_path),
                "terms": _stat(terms_path) if terms_path else [-1, -1],
                "digest": base_digest(self.base), "dismissed": _sha("\n".join(self.base.dismissed())),
                "filters": self.filters.digest()}

    def _read_json(self, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("v") == CACHE_VERSION else None

    def _load_chunks(self) -> dict | None:
        data = self._read_json(self.chunks_path)
        if not data or data.get("book") != _stat(self.book_path) or not isinstance(data.get("rows"), dict):
            return None
        rows = {}
        for k, v in data["rows"].items():
            try:
                rows[int(k)] = v
            except ValueError:
                return None
        return {"msig": data.get("msig", ""), "toc": set(data.get("toc", [])), "nchap": int(data.get("nchap", 0)),
                "rows": rows}

    def _save_chunks(self) -> None:
        ch = self._chunks
        data = {"v": CACHE_VERSION, "book": _stat(self.book_path), "msig": ch["msig"], "nchap": ch["nchap"],
                "toc": sorted(ch["toc"]), "rows": {str(i): r for i, r in sorted(ch["rows"].items())}}
        _write(self.chunks_path, data)

    def _save_answer(self, d: _Derived) -> None:
        data = dict(self._answer_key())
        data.update({"mined": d.mined, "nchap": d.nchap, "toc": format_seen(d.toc), "items": [list(r) for r in d.items],
                     "by_chapter": {str(c): [list(p) for p in v] for c, v in sorted(d.by_chapter.items())}})
        _write(self.answer_path, data)

    def _load_answer(self, mine: bool = True) -> _Derived | None:
        data = self._read_json(self.answer_path)
        if not data:
            return None
        key = self._answer_key()
        if any(data.get(k) != v for k, v in key.items()):
            return None
        if mine and not data.get("mined", True):
            return None
        try:
            items = [tuple(r) for r in data["items"]]
            by_chapter = {int(c): tuple(tuple(p) for p in v) for c, v in data["by_chapter"].items()}
            return _Derived(int(data["nchap"]), frozenset(parse_seen(data["toc"])), items, by_chapter, self.base.rev,
                            mined=bool(data.get("mined", True)))
        except (KeyError, TypeError, ValueError):
            return None

    # -- scanning -----------------------------------------------------------
    def scan(self, progress=None, cancel=None, force: bool = False, mine: bool = True) -> ScanReport:
        """Bring the answer up to date and return what was done. `progress(done, total)` is called while the
        book is read; `cancel` is an Event or a callable: a cancelled scan keeps the chapters it did (the next
        scan continues) and leaves the previous answer in place. mine=False skips the candidate mining (only the
        base entries are matched): faster, and enough for a gate that ignores candidates. Safe from a worker thread."""
        with self._scan_lock:
            t0 = time.perf_counter()
            if (not force and self._d is not None and self._d.rev == self.base.rev and not self._stale
                    and (self._d.mined or not mine)):
                return self._report(0, 0, t0, False, "memory")
            if not force:
                d = self._load_answer(mine)
                if d is not None:
                    with self._lock:
                        self._d, self._stale = d, False
                    return self._report(0, 0, t0, False, "answer")
            msig = self._sig()
            chunks = self._chunks if (self._chunks is not None and not force) else (None if force else self._load_chunks())
            if chunks is None:
                chunks = {"msig": msig, "toc": set(), "nchap": 0, "rows": {}}
            if chunks["msig"] != msig:  # spellings changed: matches are stale, mined candidates are not
                for r in chunks["rows"].values():
                    r.pop("m", None)
                chunks["msig"] = msig
            self._chunks = chunks
            entries = len(self.base) > 0
            todo = None
            read = matched = 0
            cancelled = False
            if chunks["nchap"] <= 0 or any(
                    i not in chunks["toc"] and (i not in chunks["rows"] or (mine and "c" not in chunks["rows"][i])
                                                or (entries and "m" not in chunks["rows"][i]))
                    for i in range(chunks["nchap"])):
                todo = True
            if todo:
                read, matched, cancelled = self._read_book(chunks, progress, cancel, entries, mine)
            self._raw = None
            if cancelled:
                self._save_chunks()
                return self._report(read, matched, t0, True, "book")
            if todo:
                self._save_chunks()
            self._raw = None
            d = self._derive()
            with self._lock:
                self._d, self._stale = d, False
            self._save_answer(d)
            return self._report(read, matched, t0, False, "book" if todo else "chunks")

    def _report(self, read, matched, t0, cancelled, source) -> ScanReport:
        n = self._d.nchap if self._d else 0
        self.last_report = ScanReport(n, read, matched, round(time.perf_counter() - t0, 3), cancelled, source)
        return self.last_report

    def _read_book(self, chunks, progress, cancel, entries, mine=True):
        matcher = Matcher(self.base) if entries else None
        read = matched = 0
        with Book.open(self.book_path) as book:
            chapters = book.chapters
            chunks["nchap"] = len(chapters)
            total = len(chapters)
            for pos, ch in enumerate(chapters):
                if _cancelled(cancel):
                    return read, matched, True
                i = ch.index
                row = chunks["rows"].get(i)
                if i in chunks["toc"] or (row is not None and ("c" in row or not mine) and (not entries or "m" in row)):
                    continue
                if ch.is_toc:
                    chunks["toc"].add(i)
                    chunks["rows"].pop(i, None)
                else:
                    row = row or {}
                    blocks = book.blocks(ch)
                    if mine and "c" not in row:
                        texts = [text_of(b) for b in blocks]
                        found = mine_candidates(texts, None)
                        low = Counter(_LOWER_WORD.findall(" ".join(texts))) if found else Counter()
                        row["c"] = [[c.term, c.count, c.mid,
                                     0 if " " in c.term else low.get(c.term.lower(), 0) + low.get(c.term.lower() + "s", 0)]
                                    for c in found]
                    if entries and "m" not in row:
                        hits = matcher.scan_chapter(blocks)
                        row["m"] = {norm_key(e.source): n for e, n in hits.items()}
                        matched += len(hits)
                    elif "m" not in row:
                        row["m"] = {}
                    chunks["rows"][i] = row
                read += 1
                if progress is not None and (read % 10 == 0 or pos == total - 1):
                    progress(pos + 1, total)
        return read, matched, False

    # -- deriving the answer (cheap: no EPUB) -------------------------------------
    def _raw_totals(self) -> dict:
        if self._raw is None:
            raw: dict[str, list[int]] = {}  # term -> [count, mid, lower-case uses, chapters]
            for row in self._chunks["rows"].values():
                for term, n, mid, lc in row.get("c", ()):
                    a = raw.get(term)
                    if a is None:
                        raw[term] = [n, mid, lc, 1]
                    else:
                        a[0] += n
                        a[1] += mid
                        a[2] += lc
                        a[3] += 1
            self._raw = raw
        return self._raw

    def _derive(self) -> _Derived:
        base, flt, chunks = self.base, self.filters, self._chunks
        rev = base.rev
        # 1. mined candidates: raw term -> reduced term, book totals per reduced key, filter
        rmap: dict[str, str] = {}
        totals: dict[str, list] = {}
        names: dict[str, Counter] = {}
        for term, (n, mid, lc, nch) in self._raw_totals().items():
            red = reduce_candidate(term, base, flt)
            if red is None:
                continue
            k = norm_key(red)
            rmap[term] = k
            t = totals.setdefault(k, [0, 0, 0, 0])
            t[0] += n
            t[1] += mid
            t[2] += lc
            t[3] += nch
            names.setdefault(k, Counter())[red] += n
        keep = {k for k, (n, mid, lc, nch) in totals.items()
                if (n >= flt.min_book_count or (flt.min_book_mid > 0 and mid >= flt.min_book_mid))
                and nch >= flt.min_book_chapters
                and not (flt.lower_ratio > 0 and " " not in k and lc >= flt.lower_ratio * max(mid, 1))}
        # 2. matched entries
        entry_kind: dict[str, tuple[str, str]] = {}  # key -> (kind, shown source)
        for e in base.sorted_entries():
            kind = KIND_KNOWN if e.status == "confirmed" else (KIND_QUESTION if e.questions else KIND_NEW)
            entry_kind[norm_key(e.source)] = (kind, e.source)
        # 3. one pass over the chapters
        ids: dict[str, int] = {}
        meta: list[list] = []  # per id: [text, kind, total, first, chapters list]
        by_chapter: dict[int, list] = {}
        for i in sorted(chunks["rows"]):
            row = chunks["rows"][i]
            here: dict[str, int] = {}
            for term, n, _mid, _lc in row.get("c", ()):
                k = rmap.get(term)
                if k is not None and k in keep:
                    here[k] = here.get(k, 0) + n
            hits: dict[str, tuple] = {}
            for key, n in row.get("m", {}).items():
                got = entry_kind.get(key)
                if got is not None:
                    hits[key] = (got, n)
            for k, n in here.items():
                self._note(ids, meta, by_chapter, "c:" + k, (KIND_CANDIDATE, names[k].most_common(1)[0][0]), n, i)
            for key, (got, n) in hits.items():
                self._note(ids, meta, by_chapter, "e:" + key, got, n, i)
        items = [(m[0], m[1], m[2], m[3], format_seen(m[4])) for m in meta]
        terms = {norm_key(r[0]): Item(*r) for r in items}
        # only blocking items are kept in by_chapter; the table keeps all, the answer cache only the blocking ones
        mined = chunks["nchap"] > 0 and all("c" in r for r in chunks["rows"].values()) and             len(chunks["rows"]) + len(chunks["toc"]) >= chunks["nchap"]
        return _Derived(chunks["nchap"], frozenset(chunks["toc"]), items,
                        {c: tuple(sorted(v, key=lambda p: (-p[1], p[0]))) for c, v in by_chapter.items()}, rev, terms,
                        mined)

    @staticmethod
    def _note(ids, meta, by_chapter, key, kind_text, n, chapter) -> None:
        kind, text = kind_text
        i = ids.get(key)
        if i is None:
            i = ids[key] = len(meta)
            meta.append([text, kind, 0, chapter, []])
        m = meta[i]
        m[2] += n
        m[4].append(chapter)
        if kind != KIND_KNOWN:
            by_chapter.setdefault(chapter, []).append((i, n))

    # -- reading the answer -----------------------------------------------------
    def _state(self) -> _Derived:
        d = self._d
        if d is None:
            raise NotScanned("scan() or a cache load is needed first")
        if d.rev != self.base.rev:
            with self._lock:
                d = self._d
                if d.rev != self.base.rev:
                    d = self._refresh_locked(d)
        return d

    def _refresh_locked(self, old: _Derived) -> _Derived:
        """The base changed after the last scan: recompute the cheap part from the chunks when they are at hand."""
        if self._chunks is None:
            self._chunks = self._load_chunks()
        if self._chunks is None:
            self._stale = True
            return old
        if self._chunks["msig"] != self._sig():
            self._stale = True  # spellings changed: matches need an EPUB pass (scan()); candidates are still current
        d = self._derive()
        self._d = d
        return d

    def _sig(self) -> str:
        memo = self._sig_memo
        if memo[0] != self.base.rev:
            memo[:] = [self.base.rev, spelling_signature(self.base)]
        return memo[1]

    @property
    def stale(self) -> bool:
        """True when the spellings of the base changed since the matches were made: scan() again."""
        d = self._d
        if d is None:
            return True
        if self._chunks is not None and self._chunks["msig"] != self._sig():
            return True
        return self._stale

    def terms(self) -> dict[str, Item]:
        """Every term found, by normalised key: total count, first chapter, chapter ranges. Entries of any
        status (confirmed ones as kind entry-confirmed) and candidates that survive the filters. Empty when the
        answer was loaded from its cache (only the blocking terms are kept there)."""
        d = self._state()
        if d.terms is not None:
            return dict(d.terms)
        return {norm_key(t[0]): Item(*t) for t in d.items}

    def _view(self, candidates: bool) -> _Derived:
        d = self._state()
        if candidates and not d.mined:
            raise NotScanned("candidates need a scan with mining (scan(mine=True))")
        return d

    @staticmethod
    def _rows(d: _Derived, chapter: int, candidates: bool):
        row = d.by_chapter.get(chapter, ())
        if candidates or not row:
            return row
        return tuple(p for p in row if d.items[p[0]][1] != KIND_CANDIDATE)

    def unreviewed(self, chapter: int, candidates: bool = True) -> list[Item]:
        """What blocks one chapter: items (text, kind, count in the chapter), most frequent first.
        candidates=False leaves the mined candidates out (base entries only)."""
        d = self._view(candidates)
        return [Item(d.items[i][0], d.items[i][1], n, d.items[i][3], d.items[i][4])
                for i, n in self._rows(d, chapter, candidates)]

    def check_chapter(self, chapter: int, candidates: bool = True) -> int:
        """Number of unreviewed items in one chapter; 0 = the chapter may be translated. Cheap, thread-safe.
        Raises NotScanned before the first scan (an unknown frontier is not an open one)."""
        d = self._view(candidates)
        return len(self._rows(d, chapter, candidates))

    def _bounds(self, d: _Derived, first: int, last: int | None) -> tuple[int, int]:
        hi = d.nchap - 1 if last is None else min(last, d.nchap - 1)
        return max(first, 0), hi

    def frontier(self, first: int = 0, last: int | None = None, limit: int = 1000,
                 candidates: bool = True) -> FrontierInfo:
        """The first chapter of first..last with unreviewed items (None = none), how many items it has, and how
        many distinct unreviewed items the whole range holds (counted up to `limit`; capped=True then)."""
        d = self._view(candidates)
        lo, hi = self._bounds(d, first, last)
        pos = bisect.bisect_left(d.order, lo)
        chapter = count = None
        seen: set[int] = set()
        capped = False
        while pos < len(d.order) and d.order[pos] <= hi:
            c = d.order[pos]
            row = self._rows(d, c, candidates)
            pos += 1
            if not row:
                continue
            if chapter is None:
                chapter, count = c, len(row)
            seen.update(i for i, _n in row)
            if len(seen) >= limit:
                capped = True
                break
        return FrontierInfo(chapter, count or 0, min(len(seen), limit), capped)

    def allowed(self, first: int = 0, last: int | None = None, candidates: bool = True) -> list[int]:
        """Translatable chapter indices of first..last that come before the frontier (TOC pages left out)."""
        d = self._view(candidates)
        lo, hi = self._bounds(d, first, last)
        info = self.frontier(lo, hi, limit=1, candidates=candidates)
        stop = hi + 1 if info.chapter is None else info.chapter
        return [c for c in range(lo, stop) if c not in d.toc]

    def blocking_terms(self, first: int = 0, last: int | None = None, limit: int | None = None,
                       candidates: bool = True) -> list[Item]:
        """Distinct unreviewed items of first..last, by first chapter inside the range, then count descending
        (count and chapters are those inside the range): the list the owner reviews next."""
        d = self._view(candidates)
        lo, hi = self._bounds(d, first, last)
        acc: dict[int, list] = {}
        pos = bisect.bisect_left(d.order, lo)
        while pos < len(d.order) and d.order[pos] <= hi:
            c = d.order[pos]
            pos += 1
            for i, n in self._rows(d, c, candidates):
                a = acc.get(i)
                if a is None:
                    acc[i] = [c, n, [c]]
                else:
                    a[1] += n
                    a[2].append(c)
        out = [Item(d.items[i][0], d.items[i][1], a[1], a[0], format_seen(a[2])) for i, a in acc.items()]
        out.sort(key=lambda it: (it.first, -it.count, it.text))
        return out[:limit] if limit else out

    # -- the owner's answers --------------------------------------------------
    def dismiss(self, term: str, save: bool = True) -> bool:
        """"Not a term": the candidate stops blocking. Saves terms.json unless asked not to."""
        changed = self.base.dismiss(term)
        if changed and save and self.base.path:
            self.base.save()
        return changed

    def restore(self, term: str, save: bool = True) -> bool:
        changed = self.base.restore(term)
        if changed and save and self.base.path:
            self.base.save()
        return changed


def scan(source, book=None, *, state_dir=None, base=None, filters=None, progress=None, cancel=None,
         force: bool = False) -> Frontier:
    """Scan a whole book and return the Frontier holding the answer.

    `source` is a Series (`book` = book name or None for the only one) or a TermBase (`book` = path of the
    EPUB, `state_dir` required). Walks every non-TOC chapter once; see Frontier.scan for the caches."""
    if hasattr(source, "book_names"):
        fr = Frontier.for_series(source, book, base, filters)
    else:
        if book is None or state_dir is None:
            raise ValueError("a term base needs the EPUB path and a state folder")
        fr = Frontier(source, book, state_dir, filters)
    fr.scan(progress=progress, cancel=cancel, force=force)
    return fr


def gate_for(series, book_name: str | None = None, filters=None, candidates: bool | None = None):
    """A `gate(chapter_index) -> int` for the job runner: the number of unreviewed items of a chapter
    (0 = may be translated). None when the series has no terms.json (such a series is not gated).

    `candidates=None` takes GATE_CANDIDATES; with candidates off only unconfirmed base entries count. In that
    mode a base without unconfirmed entries answers 0 at once, and otherwise only the entries are matched
    (no candidate mining). The first call builds the scan (or loads its cache); later calls read the cache.
    Thread-safe."""
    if not (Path(series.path) / FILE_NAME).exists():
        return None
    use = GATE_CANDIDATES if candidates is None else bool(candidates)
    fr = Frontier.for_series(series, book_name, filters=filters)
    memo = {"rev": None, "open": False}

    def has_open() -> bool:
        rev = fr.base.rev
        if memo["rev"] != rev:
            memo["open"] = any(e.status != "confirmed" for e in fr.base.sorted_entries())
            memo["rev"] = rev
        return memo["open"]

    def gate(chapter_index: int) -> int:
        if not use and not has_open():
            return 0
        if fr._d is None or fr.stale or (use and not fr._d.mined):
            fr.scan(mine=use)
        return fr.check_chapter(chapter_index, use)

    gate.frontier = fr
    gate.candidates = use
    return gate
