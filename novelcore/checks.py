"""Checks of finished translations, retry of listed blocks, and Kindle highlights.

check_chapter / check_range list suspicious blocks of translated chapters (kinds in KINDS); nothing is
changed. mark_for_retry turns listed blocks into pending ones by appending a `retry` record (the old
text is kept in `prev`), so a normal Job over their chapters translates exactly these blocks again;
restore_previous puts the old text back. The Kindle part (parse_clippings, locate_clips) follows the
documented "My Clippings.txt" layout and is UNVERIFIED against a real device file.

Record added by mark_for_retry (later lines win, so the block is no longer finished):
  {"i", "src_sha", "text": "", "model": "", "at", "status": "retry", "flags": [],
   "prev": <old text>, "prev_model", "prev_flags", "why": [kinds]}
"""

from __future__ import annotations

import inspect
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import profiles
from .htmlscan import MARKER_RE, strip_markers
from .store import Series, atomic_write_text, read_jsonl, safe_name
from .termmatch import Matcher
from .terms import FILE_NAME, TermBase

KINDS = ("leftover", "ratio", "term", "markup", "untranslated", "empty")
EXEMPT_FLAGS = frozenset({"manual", "kept"})

# leftover (non-Latin targets)
LEFTOVER_RUN = 2  # this many disallowed Latin words in one run flag the block (3 missed a 2-word name left in English)
LEFTOVER_SHARE = 0.25  # share of disallowed Latin words among all words
LEFTOVER_MIN_BAD = 2  # the share rule needs at least this many disallowed words
SENTENCE_WORDS = 12  # Latin targets: sentences of this length are judged on their own
MARKED_WORDS = 3  # a marked span of at most this many words may stay verbatim

# ratio (against the chapter's own median)
RATIO_LOW = 0.55
RATIO_HIGH = 1.8
RATIO_MIN_SRC = 40  # characters of the source (markers stripped)
RATIO_MIN_BLOCKS = 5  # blocks needed to trust the chapter median

# term (stem test)
STEM_MIN_WORD = 4  # words of this length or more are matched by a prefix
STEM_CUT = 3  # characters dropped from the end of such a word
STEM_MIN_PREFIX = 3
FLEETING = "ео"  # e, o (Cyrillic) before the last letter
STEM_SHORT_TAIL = 2  # a 3-letter word may carry this many extra letters (a declined short name); shorter ones: exact

UNTRANSLATED_MIN_WORDS = 4  # "longer than 3 words"
CHECK_MARKER_ORDER = True

UNITS = frozenset("""km cm mm kg mg ml kb mb gb tb hz khz mhz ghz lv lvl exp xp ok pc tv db fps mph kph
min hr sec st nd rd th lb lbs oz ft hp mp sp vs etc""".split())
_ROMAN = re.compile(r"^(?=[IVXLCDM])M*(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
_URL = re.compile(r"https?://\S+|www\.\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+", re.I)
_TOKEN = re.compile(r"[^\W_][\w'’\-]*")
_GAP_OK = re.compile(r"^[\s,;:'\"«»“”„‘’()\-–—]*$")
_SENT = re.compile(r"(?<=[.!?…])\s+")
_WS = re.compile(r"\s+")
_WORD = re.compile(r"\w+")
_SPAN = re.compile(r"<(\d+)>(.*?)</\1>", re.S)


# -- data ----------------------------------------------------------------------
@dataclass
class Finding:
    chapter: int
    title: str
    block: int
    src_sha: str
    kind: str
    detail: dict
    source: str
    text: str

    def key(self) -> tuple[int, int, str]:
        return (self.chapter, self.block, self.src_sha)


@dataclass
class ChapterReport:
    chapter: int
    title: str = ""
    blocks: int = 0
    checked: int = 0  # finished blocks that were examined
    missing: int = 0  # blocks without a finished record (failed and retry ones included)
    failed: int = 0  # of those: the latest record is `failed`
    retry: int = 0  # of those: the latest record is `retry`
    exempt: int = 0  # finished blocks flagged manual / kept
    findings: list = field(default_factory=list)


@dataclass
class Report:
    book: str = ""
    target: str = ""
    created: float = 0.0
    cancelled: bool = False
    chapters: dict = field(default_factory=dict)  # chapter index -> ChapterReport

    def findings(self, kind: str | None = None) -> list[Finding]:
        out = [f for c in self.chapters.values() for f in c.findings]
        return [f for f in out if kind is None or f.kind == kind]

    def counts(self) -> dict:
        n = {k: 0 for k in KINDS}
        for c in self.chapters.values():
            for f in c.findings:
                n[f.kind] = n.get(f.kind, 0) + 1
        return n

    def totals(self) -> dict:
        t = {"blocks": 0, "checked": 0, "missing": 0, "failed": 0, "retry": 0, "exempt": 0, "findings": 0}
        for c in self.chapters.values():
            for k in ("blocks", "checked", "missing", "failed", "retry", "exempt"):
                t[k] += getattr(c, k)
            t["findings"] += len(c.findings)
        return t

    def to_json(self) -> str:
        data = {"version": 1, "book": self.book, "target": self.target, "created": self.created,
                "cancelled": self.cancelled, "counts": self.counts(), "totals": self.totals(),
                "chapters": {str(i): asdict(c) for i, c in sorted(self.chapters.items())}}
        return json.dumps(data, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "Report":
        data = json.loads(text)
        rep = cls(data.get("book", ""), data.get("target", ""), data.get("created", 0.0), bool(data.get("cancelled")))
        for key, c in (data.get("chapters") or {}).items():
            found = [Finding(**f) for f in c.get("findings", [])]
            rep.chapters[int(key)] = ChapterReport(
                chapter=c["chapter"], title=c.get("title", ""), blocks=c.get("blocks", 0), checked=c.get("checked", 0),
                missing=c.get("missing", 0), failed=c.get("failed", 0), retry=c.get("retry", 0),
                exempt=c.get("exempt", 0), findings=found)
        return rep

    def path(self, series) -> Path:
        return report_path(series, self.book)

    def save(self, series) -> Path:
        path = self.path(series)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, self.to_json())
        return path

    @classmethod
    def load(cls, series, book: str) -> "Report | None":
        try:
            return cls.from_json(report_path(series, book).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def lines(self, ascii_only: bool = False, with_text: bool = True, limit: int | None = None,
              width: int = 140) -> list[str]:
        """Plain console lines: a summary, then one entry per finding (and its two texts)."""
        t = self.totals()
        out = [f"book {self.book}: {len(self.chapters)} chapters, {t['checked']} blocks checked, "
               f"{t['missing']} missing ({t['failed']} failed), {t['findings']} findings"
               + (" (cancelled)" if self.cancelled else ""),
               "kinds: " + ", ".join(f"{k} {v}" for k, v in self.counts().items())]
        n = 0
        for idx, c in sorted(self.chapters.items()):
            if not c.findings and not c.missing:
                continue
            out.append(f"chapter {idx} {c.title!r}: {len(c.findings)} findings, {c.missing} missing, {c.failed} failed")
            for f in c.findings:
                if limit is not None and n >= limit:
                    break
                n += 1
                det = " ".join(f"{k}={_short(str(v), 60)}" for k, v in f.detail.items())
                out.append(f"  #{f.block} [{f.kind}] {det}")
                if with_text:
                    out.append("    src: " + _short(_WS.sub(" ", f.source), width))
                    out.append("    tr:  " + _short(_WS.sub(" ", f.text), width))
        if ascii_only:
            out = [s.encode("ascii", "backslashreplace").decode("ascii") for s in out]
        return out


def report_path(series, book: str) -> Path:
    return Path(series.path) / ".state" / f"check_{safe_name(book, 80)}.json"


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 3] + "..."


# -- helpers ---------------------------------------------------------------------
def _norm_ws(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _words(s: str) -> list[str]:
    return _WORD.findall(s.lower().replace("ё", "е"))


def _is_latin(tok: str) -> bool:
    letters = [c for c in tok if c.isalpha()]
    return bool(letters) and all(c.isascii() or "À" <= c <= "ɏ" for c in letters)


def _short_ok(tok: str) -> bool:
    """A token that may stand in Latin letters inside a translation (abbreviation, unit, symbol-like)."""
    if any(c.isdigit() for c in tok):
        return True
    letters = [c for c in tok if c.isalpha()]
    if len(letters) == 1:
        return True
    if tok.isupper() and len(tok) <= 5:
        return True
    if len(tok) > 1 and tok[-1] == "s" and tok[:-1].isupper() and len(tok) <= 6:
        return True  # NPCs
    if _ROMAN.match(tok):
        return True
    if tok.lower() in UNITS:
        return True
    parts = [p for p in re.split(r"[-'’]", tok) if p]
    if len(parts) > 1:
        if len(parts[0]) == 1:
            return True  # S-rank, A-class
        return all(_short_ok(p) for p in parts)
    return False


def _latin_tokens(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _TOKEN.finditer(text):
        tok = m.group().rstrip("-'’")
        if tok:
            out.append((m.start(), m.start() + len(tok), tok))
    return out


def _marked_allowed(source: str, text: str) -> set[str]:
    """Latin tokens of short marked spans that the translation keeps verbatim (same marker, same text)."""
    tr = {m.group(1): m.group(2) for m in _SPAN.finditer(text)}
    ok: set[str] = set()
    for m in _SPAN.finditer(source):
        inner = m.group(2)
        if tr.get(m.group(1)) == inner and len(_words(strip_markers(inner))) <= MARKED_WORDS:
            ok.update(t.lower() for _s, _e, t in _latin_tokens(strip_markers(inner)))
    return ok


def leftover_latin(text: str, allowed=frozenset()) -> dict | None:
    """Detail of a run / share of disallowed Latin words in `text` (a non-Latin target), or None.
    `allowed`: lower-case Latin tokens that are fine in this block."""
    plain = _URL.sub(" ", strip_markers(text))
    toks = _latin_tokens(plain)
    words = [t for t in toks if any(c.isalpha() for c in t[2])]
    if not words:
        return None
    flags = []  # per token: None = not Latin, False = allowed Latin, True = disallowed Latin
    for _s, _e, t in toks:
        if not _is_latin(t):
            flags.append(None)
        else:
            flags.append(not (t.lower() in allowed or _short_ok(t)))
    bad_total = sum(1 for f in flags if f)
    if not bad_total:
        return None
    best = (0, 0, 0)  # bad count, first, last token
    i = 0
    n = len(toks)
    while i < n:
        if flags[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1] is not None and _GAP_OK.match(plain[toks[j][1]:toks[j + 1][0]]):
            j += 1
        bad = sum(1 for k in range(i, j + 1) if flags[k])
        if bad > best[0]:
            best = (bad, i, j)
        i = j + 1
    alpha = [k for k, t in enumerate(toks) if any(c.isalpha() for c in t[2])]
    share = bad_total / max(len(alpha), 1)
    rule = None
    if best[0] >= LEFTOVER_RUN:
        rule = "run"
    elif bad_total >= LEFTOVER_MIN_BAD and share > LEFTOVER_SHARE:
        rule = "share"
    if rule is None:
        return None
    first, last = (toks[best[1]][0], toks[best[2]][1]) if best[0] else (toks[0][0], toks[-1][1])
    if rule == "share" and best[0] < 2:
        bad_idx = [k for k, f in enumerate(flags) if f]
        first, last = toks[bad_idx[0]][0], toks[bad_idx[-1]][1]
    return {"rule": rule, "latin": bad_total, "words": len(alpha), "share": round(share, 2),
            "fragment": _short(plain[first:last], 80)}


def leftover_language(profile, text: str) -> dict | None:
    """Latin-script targets: the whole block, and each long sentence, judged by the profile."""
    plain = strip_markers(text)
    wrong = profile.wrong_language(plain)
    if wrong:
        return {"rule": wrong, "scope": "block", "fragment": _short(_norm_ws(plain), 80)}
    for sent in _SENT.split(plain):
        if len(_WORD.findall(sent)) >= SENTENCE_WORDS:
            wrong = profile.wrong_language(sent)
            if wrong:
                return {"rule": wrong, "scope": "sentence", "fragment": _short(_norm_ws(sent), 80)}
    return None


def term_misses(matches, text: str) -> list[tuple[str, str]]:
    """(source term, expected translation) of matched terms whose translation has no stem in `text`."""
    tw = _words(strip_markers(text))
    whole = set(tw)
    out = []
    for e in matches:
        need = _words(e.tr)
        if not need:
            continue
        for w in need:
            if len(w) >= STEM_MIN_WORD:
                pres = [w[:max(STEM_MIN_PREFIX, len(w) - STEM_CUT)]]
                if w[-2] in FLEETING:  # a vowel that drops out of the stem: узел -> узлов
                    alt = w[:-2] + w[-1]
                    pres.append(alt[:max(STEM_MIN_PREFIX, len(alt) - STEM_CUT)])
                present = any(x.startswith(pre) for x in tw for pre in pres)
            elif len(w) == 3:
                present = any(x.startswith(w) and len(x) <= 3 + STEM_SHORT_TAIL for x in tw)
            else:
                present = w in whole
            if not present:
                out.append((e.source, e.tr))
                break
    return out


def marker_issue(source: str, text: str) -> dict | None:
    s = [m.group(0) for m in MARKER_RE.finditer(source)]
    t = [m.group(0) for m in MARKER_RE.finditer(text)]
    if sorted(s) != sorted(t):
        return {"why": "count", "src": len(s), "tr": len(t)}
    if CHECK_MARKER_ORDER and s != t:
        return {"why": "order", "src": len(s), "tr": len(t)}
    return None


# -- checking ----------------------------------------------------------------------
class _Context:
    def __init__(self, series, base):
        self.tag = series.target_tag
        self.profile = profiles.get(self.tag)
        if base is None:
            path = Path(series.path) / FILE_NAME
            base = TermBase.load(path, self.tag) if path.exists() else None
        self.base = base
        self.matcher = Matcher(base) if base is not None and len(base) else None

    def matches(self, plain_source: str):
        if self.matcher is None:
            return []
        seen, out = set(), []
        for e, _s, _e in self.matcher.match(plain_source):
            if e.status == "confirmed" and e.tr and id(e) not in seen:
                seen.add(id(e))
                out.append(e)
        return out


def _name_of(book, book_name) -> str:
    return book_name or Path(book.path).stem


def _chapter_of(book, chapter):
    return book.chapters[chapter] if isinstance(chapter, int) else chapter


def _check_one(series, book, chapter, ctx: _Context, book_name: str) -> ChapterReport:
    log = series.chapter_log(book_name, chapter)
    blocks = book.blocks(chapter)
    rep = ChapterReport(chapter.index, chapter.title, blocks=len(blocks))
    if not log.path.exists():
        rep.missing = len(blocks)
        return rep
    rows = []  # (block, record)
    for b in blocks:
        rec = log.lookup(b.index, b.sha)
        if rec is not None and rec.get("status") == "ok":
            flags = set(rec.get("flags") or [])
            if flags & EXEMPT_FLAGS:
                rep.exempt += 1
            else:
                rows.append((b, rec))
        else:
            rep.missing += 1
            if rec is not None and rec.get("status") == "failed":
                rep.failed += 1
            elif rec is not None and rec.get("status") == "retry":
                rep.retry += 1
    rep.checked = len(rows) + rep.exempt
    ratios = []
    info = []
    for b, rec in rows:
        ps, pt = strip_markers(b.text), strip_markers(rec.get("text") or "")
        r = len(pt) / len(ps) if len(ps) > RATIO_MIN_SRC and pt.strip() else None
        info.append((ps, pt, r))
        if r is not None:
            ratios.append(r)
    median = statistics.median(ratios) if len(ratios) >= RATIO_MIN_BLOCKS else None
    for (b, rec), (ps, pt, r) in zip(rows, info):
        text = rec.get("text") or ""
        found: list[tuple[str, dict]] = []

        def add(kind, detail):
            found.append((kind, detail))

        if not text.strip():
            add("empty", {})
        else:
            matches = ctx.matches(ps)
            if ctx.profile.script is not None:
                allowed = _marked_allowed(b.text, text)
                for e in matches:
                    allowed.update(t.lower() for _s, _e, t in _latin_tokens(e.tr))
                d = leftover_latin(text, allowed)
                if d is None and len(ps) > 40 and ctx.profile.wrong_language(_URL.sub(" ", pt)) == "script":
                    d = {"rule": "script", "fragment": _short(_norm_ws(pt), 80)}
            else:
                d = leftover_language(ctx.profile, text)
            if d:
                add("leftover", d)
            if median is not None and r is not None and not (RATIO_LOW * median <= r <= RATIO_HIGH * median):
                add("ratio", {"ratio": round(r, 2), "median": round(median, 2)})
            miss = term_misses(matches, text)
            if miss:
                add("term", {"term": miss[0][0], "expected": miss[0][1], "missing": len(miss),
                             "all": " | ".join(f"{a} => {c}" for a, c in miss[:5])})
            if "markup" in (rec.get("flags") or []):
                add("markup", {"why": "flag"})
            else:
                mi = marker_issue(b.text, text)
                if mi:
                    add("markup", mi)
            if len(_words(ps)) >= UNTRANSLATED_MIN_WORDS and _norm_ws(ps) == _norm_ws(pt):
                add("untranslated", {"words": len(_words(ps))})
        for kind, detail in found:
            rep.findings.append(Finding(chapter.index, chapter.title, b.index, b.sha, kind, detail, b.text, text))
    return rep


def check_chapter(series, book, chapter, base=None, book_name=None) -> list[Finding]:
    """Findings of one chapter. `book` is an open Book (its file stem names the book unless `book_name`
    is given); `chapter` a Chapter or its index; `base` a TermBase (default: the series' terms.json)."""
    ch = _chapter_of(book, chapter)
    return _check_one(series, book, ch, _Context(series, base), _name_of(book, book_name)).findings


def check_range(series, book_name: str, chapters, progress=None, cancel=None, base=None) -> Report:
    """Check the chapter indices `chapters` of a book of the series. `progress(done, total, index)` is
    called after each chapter; `cancel` (callable or Event) is polled between chapters."""
    ctx = _Context(series, base)
    rep = Report(book_name, series.settings.get("target", ""), time.time())
    wanted = list(dict.fromkeys(int(c) for c in chapters))
    stop = (lambda: False) if cancel is None else (cancel.is_set if hasattr(cancel, "is_set") else cancel)
    with series.open_book(book_name) as book:
        for n, idx in enumerate(wanted):
            if stop():
                rep.cancelled = True
                break
            if 0 <= idx < len(book.chapters):
                rep.chapters[idx] = _check_one(series, book, book.chapters[idx], ctx, book_name)
            if progress:
                progress(n + 1, len(wanted), idx)
    return rep


# -- retry ---------------------------------------------------------------------------
def _pairs(items) -> dict[tuple[int, int, str], list[str]]:
    out: dict[tuple[int, int, str], list[str]] = {}
    for it in items:
        if isinstance(it, Finding):
            out.setdefault(it.key(), [])
            if it.kind not in out[it.key()]:
                out[it.key()].append(it.kind)
        else:
            c, i, sha = it
            out.setdefault((int(c), int(i), str(sha)), [])
    return out


def _refuse_if_busy(series) -> None:
    from . import job
    holder = job.lock_holder(series.path)
    if holder:
        raise job.SeriesBusy(f"the series is being translated by process {holder.get('pid')}; stop it first")


def mark_for_retry(series, book_name: str, items) -> dict:
    """Make the listed blocks pending again (see the module docstring). `items`: Findings or
    (chapter, block, src_sha) tuples. Returns {"chapters": sorted indices, "marked": n, "skipped": n}.
    Raises SeriesBusy while another process holds the series."""
    _refuse_if_busy(series)
    want = _pairs(items)
    by_chapter: dict[int, list] = {}
    for (c, i, sha), why in want.items():
        by_chapter.setdefault(c, []).append((i, sha, why))
    marked = skipped = 0
    chapters = []
    now = time.time()
    with series.open_book(book_name) as book:
        for c, entries in sorted(by_chapter.items()):
            if not 0 <= c < len(book.chapters):
                skipped += len(entries)
                continue
            log = series.chapter_log(book_name, book.chapters[c])
            recs = []
            for i, sha, why in entries:
                old = log.done(i, sha)
                if old is None:
                    skipped += 1
                    continue
                recs.append({"i": i, "src_sha": sha, "text": "", "model": "", "at": now, "status": "retry",
                             "flags": [], "prev": old.get("text", ""), "prev_model": old.get("model", ""),
                             "prev_flags": list(old.get("flags") or []), "why": list(why)})
            if recs:
                log.append(recs)
                marked += len(recs)
                chapters.append(c)
    return {"chapters": chapters, "marked": marked, "skipped": skipped}


def restore_previous(series, book_name: str, items) -> dict:
    """Put the text saved by mark_for_retry back as a finished record (also after a retry made it worse).
    The marker line is searched in the whole file, since the retry's own record replaced it in memory."""
    _refuse_if_busy(series)
    want = _pairs(items)
    by_chapter: dict[int, list] = {}
    for (c, i, sha) in want:
        by_chapter.setdefault(c, []).append((i, sha))
    restored = skipped = 0
    chapters = []
    now = time.time()
    with series.open_book(book_name) as book:
        for c, entries in sorted(by_chapter.items()):
            if not 0 <= c < len(book.chapters):
                skipped += len(entries)
                continue
            log = series.chapter_log(book_name, book.chapters[c])
            prev: dict[tuple[int, str], dict] = {}
            for rec in read_jsonl(log.path):
                if rec.get("status") == "retry" and "prev" in rec:
                    prev[(rec["i"], rec["src_sha"])] = rec
            recs = []
            for i, sha in entries:
                mark = prev.get((i, sha))
                cur = log.lookup(i, sha)
                if mark is None or (cur is not None and cur.get("status") == "ok" and cur.get("text") == mark["prev"]):
                    skipped += 1
                    continue
                recs.append({"i": i, "src_sha": sha, "text": mark["prev"], "model": mark.get("prev_model", ""),
                             "at": now, "status": "ok", "flags": list(mark.get("prev_flags") or []),
                             "restored": True})
            if recs:
                log.append(recs)
                restored += len(recs)
                chapters.append(c)
    return {"chapters": chapters, "restored": restored, "skipped": skipped}


def _no_reuse(series, shas) -> None:
    """Series.find_done hands back the OLD finished text of a retried block (the old `ok` line is still in
    the file and in the index), so the runner would reuse it at once. Hide these hashes on this Series
    object (see the report for the one-line change in store.py that makes this unnecessary)."""
    fresh = getattr(series, "_retry_shas", None)
    if fresh is None:
        fresh = series._retry_shas = set()
        orig = series.find_done
        series.find_done = lambda sha: None if sha in fresh else orig(sha)
    fresh.update(shas)


def retry(series, book_name: str, findings, keys, models, **job_kw):
    """Mark the listed blocks and return a (not started) Job over exactly their chapters."""
    from . import job
    info = mark_for_retry(series, book_name, findings)
    if not info["chapters"]:
        raise job.JobError("none of the listed blocks has a finished translation")
    _no_reuse(series, {k[2] for k in _pairs(findings)})
    params = inspect.signature(job.Job.__init__).parameters
    chapters = info["chapters"]
    if "gate" in params:
        job_kw.setdefault("gate", False)
    if "chapters" in params:
        job_kw["chapters"] = chapters
        return job.Job(series, book_name, keys, models, 0, None, **job_kw)
    # no `chapters=`: the whole first..last extent runs (other pending blocks in between are translated too)
    return job.Job(series, book_name, keys, models, min(chapters), max(chapters), **job_kw)


# -- Kindle highlights (UNVERIFIED against a real device file) -------------------------
@dataclass
class Clip:
    title: str
    author: str
    kind: str  # highlight | note | bookmark | other
    page: int | None
    location: str
    added: str
    text: str


_LOC = re.compile(r"(?:location|loc\.|место|позиция)\s+(\d+(?:\s*-\s*\d+)?)", re.I)
_PAGE = re.compile(r"(?:page|страниц\w*)\s+(\d+)", re.I)
_ADDED = re.compile(r"(?:added on|добавлено)[:\s]*(.+)$", re.I)
_KINDS = (("highlight", ("highlight", "выделен")),
          ("note", ("note", "заметк")),
          ("bookmark", ("bookmark", "закладк")))
_TITLE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def _clip_kind(meta: str) -> str:
    low = meta.lower()
    for name, words in _KINDS:
        if any(w in low for w in words):
            return name
    return "other"


def parse_clippings(path) -> list[Clip]:
    """Entries of a Kindle "My Clippings.txt": separated by a line of `==========`; first line the
    title (author in the last parentheses), second the metadata (kind, page, location, date), then a
    blank line and the text. UTF-8 with or without BOM; English and Russian wording."""
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    clips = []
    for part in re.split(r"^={5,}\s*$", raw, flags=re.M):
        lines = [ln.rstrip() for ln in part.strip("﻿\n ").split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        if len(lines) < 2:
            continue
        title_line = lines[0].strip().lstrip("﻿")
        meta = lines[1].strip()
        m = _TITLE.match(title_line)
        title, author = (m.group(1), m.group(2)) if m else (title_line, "")
        page = _PAGE.search(meta)
        loc = _LOC.search(meta)
        added = _ADDED.search(meta)
        text = "\n".join(lines[2:]).strip()
        clips.append(Clip(title, author, _clip_kind(meta), int(page.group(1)) if page else None,
                          re.sub(r"\s+", "", loc.group(1)) if loc else "", added.group(1).strip() if added else "", text))
    return clips


def _norm_clip(s: str) -> str:
    return _WS.sub(" ", s.replace(" ", " ").replace("­", "")).strip()


def locate_clips(series, book_name: str, clips, chapters=None, min_prefix: int = 30) -> list:
    """For each clip: (clip, chapter index, block index) of the translated block where its text starts, or
    None. A whole-clip match is preferred (it may run over neighbouring blocks of one chapter, which are
    joined with a space); else the longest prefix of at least `min_prefix` characters (the whole text
    when shorter). Only finished (`ok`) blocks are searched; text is whitespace-normalised."""
    folder = Path(series.path) / "chapters" / safe_name(book_name, 80)
    keep = None if chapters is None else {int(c) for c in chapters}
    docs = []  # (chapter, joined text, [(start offset, block index)])
    for f in sorted(folder.glob("*.jsonl")):
        m = re.match(r"(\d+)_", f.name)
        if not m or (keep is not None and int(m.group(1)) not in keep):
            continue
        latest = {}
        for rec in read_jsonl(f):
            latest[(rec["i"], rec["src_sha"])] = rec
        parts, starts, pos = [], [], 0
        for rec in sorted((r for r in latest.values() if r.get("status") == "ok"), key=lambda r: r["i"]):
            t = _norm_clip(strip_markers(rec.get("text") or ""))
            if not t:
                continue
            starts.append((pos, rec["i"]))
            parts.append(t)
            pos += len(t) + 1
        if parts:
            docs.append((int(m.group(1)), " ".join(parts), starts))

    def block_at(starts, offset):
        best = starts[0][1]
        for s, i in starts:
            if s <= offset:
                best = i
            else:
                break
        return best

    out = []
    for clip in clips:
        need = _norm_clip(clip.text)
        hit = None
        if need:
            for ch, text, starts in docs:
                at = text.find(need)
                if at >= 0:
                    hit = (ch, block_at(starts, at))
                    break
            if hit is None:
                floor = min(min_prefix, len(need))
                best = 0
                for ch, text, starts in docs:
                    if text.find(need[:floor]) < 0:
                        continue
                    lo, hi = floor, len(need)  # longest k with need[:k] in text
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        if text.find(need[:mid]) >= 0:
                            lo = mid
                        else:
                            hi = mid - 1
                    if lo > best:
                        best, hit = lo, (ch, block_at(starts, text.find(need[:lo])))
        out.append((clip, hit[0], hit[1]) if hit else None)
    return out
