"""Glossary logic for the GUI: import/export, merge, near-duplicate search, validation and prompt building.

Pure functions, standard library only (Python 3.11+). A glossary is an ordered list of Entry values.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

FORMAT = 1


@dataclass(frozen=True)
class Entry:
    term: str
    translation: str
    note: str = ""


def norm(text: str) -> str:
    """Collapse runs of whitespace and strip the ends."""
    return " ".join(str(text).split())


_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"'})
_DIGITS = re.compile(r"\d+")


def key(term: str) -> str:
    """Identity of a term: lower-case (as the engine does), single spaces, typographic quotes made plain."""
    return norm(term).translate(_QUOTES).lower()


# ---------------------------------------------------------------- import / export

def _pairs_to_entries(pairs):
    return [Entry(norm(t), norm(v)) for t, v in pairs if norm(t) or norm(v)]


class _Obj(list):
    """A JSON object kept as a list of (key, value) pairs, so repeated keys survive."""


def from_json(text: str) -> list[Entry]:
    """Read {"term": "translation"}, a list of {"term","translation","note"}, or the GUI's own file.

    Raises ValueError for any other shape. A repeated key inside a plain object is kept (json.load would
    silently keep only the last one), so validate() can report it.
    """
    data = json.loads(text, object_pairs_hook=_Obj)
    if isinstance(data, _Obj):
        top = dict(data)
        if isinstance(top.get("entries"), list):
            rows = top["entries"]
        elif all(isinstance(v, str) for _, v in data):
            return _pairs_to_entries(data)
        else:
            raise ValueError("shape")
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError("shape")
    out = []
    for row in rows:
        r = dict(row) if isinstance(row, _Obj) else {}
        if not isinstance(r.get("term"), str):
            raise ValueError("shape")
        out.append(Entry(norm(r["term"]), norm(str(r.get("translation", ""))), norm(str(r.get("note", "")))))
    return out


_ARROW = re.compile(r"\s*(?:->|→|=>)\s*")


def from_text(text: str) -> list[Entry]:
    """Read pasted text: `term -> translation # note` lines, or TSV/CSV rows (term, translation[, note]).

    Blank lines and lines starting with '#' are skipped. Lines that fit no format are skipped, and
    validate() reports their absence indirectly (empty translations); callers may compare line counts.
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    out = []
    if any("\t" in ln for ln in lines):
        for ln in lines:
            cols = ln.split("\t")
            if len(cols) >= 2:
                out.append(Entry(norm(cols[0]), norm(cols[1]), norm(cols[2]) if len(cols) > 2 else ""))
        return out
    if any(_ARROW.search(ln) for ln in lines):
        for ln in lines:
            body, _, note = ln.partition(" #")
            parts = _ARROW.split(body.lstrip("-* \t"), maxsplit=1)
            if len(parts) == 2:
                out.append(Entry(norm(parts[0]), norm(parts[1]), norm(note)))
        return out
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        return out
    for cols in csv.reader(io.StringIO("\n".join(lines)), dialect):
        if len(cols) >= 2:
            out.append(Entry(norm(cols[0]), norm(cols[1]), norm(cols[2]) if len(cols) > 2 else ""))
    return out


def load(path) -> list[Entry]:
    """Load a .json or text/csv/tsv glossary file (UTF-8, BOM tolerated)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    if Path(path).suffix.lower() == ".json":
        return from_json(text)
    return from_text(text)


def to_file_text(entries, language: str = "") -> str:
    """The GUI's own on-disk format (keeps notes and the target language):
    {"format": 1, "language": "Russian", "entries": [{"term", "translation", "note"?}, ...]}."""
    rows = [{"term": e.term, "translation": e.translation, **({"note": e.note} if e.note else {})} for e in entries]
    return json.dumps({"format": FORMAT, "language": language, "entries": rows}, ensure_ascii=False, indent=1) + "\n"


def file_language(text: str) -> str:
    """The target language stored in a GUI glossary file, or '' (plain files carry none)."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    return str(data.get("language", "")) if isinstance(data, dict) else ""


def to_engine_txt(entries) -> str:
    """The engine's own --glossary text format ('term → translation  # note'); only some routes read it."""
    return "".join(f"{e.term} → {e.translation}" + (f"  # {e.note}" if e.note else "") + "\n" for e in entries)


def to_plain_json(entries) -> str:
    """Export in the user's classic shape {"term": "translation"}; notes are dropped, later duplicates lose."""
    return json.dumps({e.term: e.translation for e in entries}, ensure_ascii=False, indent=4) + "\n"


def to_tsv(entries) -> str:
    return "".join(f"{e.term}\t{e.translation}\t{e.note}\n" if e.note else f"{e.term}\t{e.translation}\n" for e in entries)


# ---------------------------------------------------------------- merge

def diff_rows(current, incoming):
    """Rows for the import table: (status, current_entry|None, incoming_entry|None).

    status: 'same' (both, same translation), 'diff' (both, different translation), 'new' (only incoming),
    'own' (only current). Order: current's order first, then incoming's new terms in their order.
    """
    inc = {key(e.term): e for e in incoming}
    seen, rows = set(), []
    for c in current:
        k = key(c.term)
        i = inc.get(k)
        seen.add(k)
        if i is None:
            rows.append(("own", c, None))
        else:
            rows.append(("same" if norm(i.translation) == norm(c.translation) else "diff", c, i))
    rows += [("new", None, e) for k, e in inc.items() if k not in seen]
    return rows


def merge(current, incoming, union: bool = False, prefer: str = "incoming"):
    """Merge `incoming` into `current`. Defaults reproduce the user's merge_glossaries.py.

    - term in both: the incoming translation wins (prefer="incoming") or the current one (prefer="current");
      a non-empty note is taken from whichever side wins, else the other side's note is kept.
    - term only in current: kept, in its position.
    - term only in incoming: added at the end only when union is True.
    Returns (entries, report) where report counts 'matched', 'changed', 'kept', 'added', 'ignored'.
    """
    out, rep = [], dict(matched=0, changed=0, kept=0, added=0, ignored=0)
    for status, c, i in diff_rows(current, incoming):
        if status == "own":
            out.append(c)
            rep["kept"] += 1
        elif status in ("same", "diff"):
            rep["matched"] += 1
            win, lose = (i, c) if prefer == "incoming" else (c, i)
            if status == "diff" and win is i:
                rep["changed"] += 1
            out.append(replace(win, term=c.term, note=win.note or lose.note))
        elif union:
            out.append(i)
            rep["added"] += 1
        else:
            rep["ignored"] += 1
    return out, rep


def compare_with_older(current, older_by_name):
    """Names that drifted: [(term, [(older_name, older_translation), ...], current_translation)].

    Only terms present in `current` and in at least one older glossary with a different translation.
    """
    cur = {key(e.term): e for e in current}
    drift = {}
    for name, entries in older_by_name.items():
        for o in entries:
            c = cur.get(key(o.term))
            if c is not None and norm(c.translation) != norm(o.translation):
                drift.setdefault(key(o.term), (c.term, c.translation, []))[2].append((name, o.translation))
    return [(t, olds, tr) for t, tr, olds in drift.values()]


# ---------------------------------------------------------------- near duplicates

def levenshtein(a: str, b: str, limit: int | None = None) -> int:
    """Edit distance; stops early and returns limit + 1 once the distance must exceed `limit`."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if limit is not None and len(a) - len(b) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        if limit is not None and min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def near_duplicates(texts, max_dist: int = 2, min_len: int = 4):
    """Pairs of different strings within `max_dist` edits: [(dist, i, j)] sorted by distance, then position.

    Strings shorter than `min_len` are skipped. The allowed distance is also capped at a quarter of the
    shorter string, so 'Elder Roc' and 'Elder Roe' (1 edit) match but two unrelated 5-letter names do not.
    Comparison ignores case, extra spaces and curly quotes; pairs that differ only in digits are skipped; identical normalised strings give distance 0 (a true duplicate).
    """
    keys = [key(t) for t in texts]
    masks = [_DIGITS.sub("#", k) for k in keys]
    sets = [set(k) for k in keys]
    out = []
    for i in range(len(keys)):
        a = keys[i]
        for j in range(i + 1, len(keys)):
            b = keys[j]
            shortest = min(len(a), len(b))
            if shortest < min_len:
                continue
            lim = min(max_dist, shortest // 4)
            # cheap filters first: length gap, then characters in only one string (each edit changes at most two)
            if abs(len(a) - len(b)) > lim or len(sets[i] ^ sets[j]) > 2 * lim:
                continue
            if a != b and masks[i] == masks[j]:
                continue  # 'Island No. 3' / 'Island No. 7': a numbered series, not a typo
            d = levenshtein(a, b, lim)
            if d <= lim:
                out.append((d, i, j))
    out.sort()
    return out


def find_similar(entries, field: str = "term", max_dist: int = 2):
    """near_duplicates over 'term' or 'translation'; returns [(dist, Entry, Entry)]. Exact equals are included."""
    texts = [getattr(e, field) for e in entries]
    return [(d, entries[i], entries[j]) for d, i, j in near_duplicates(texts, max_dist)]


# ---------------------------------------------------------------- validation

def validate(entries):
    """Short problem codes with the rows they concern: {'empty': [i], 'dup': [i], 'brace': [i], 'hash': [i]}.

    empty: a side is empty. dup: a term repeated (case/space-insensitive; the engine keeps the last one).
    brace: '{' or '}' in a line (escaped by build_system, reported so the user knows). hash: '#' starts
    a comment in the engine's own --glossary file format, so such a line would be cut there.
    """
    res = {"empty": [], "dup": [], "brace": [], "hash": []}
    seen = {}
    for n, e in enumerate(entries):
        if not e.term or not e.translation:
            res["empty"].append(n)
        k = key(e.term)
        if k in seen:
            res["dup"] += [seen[k]] if seen[k] not in res["dup"] else []
            res["dup"].append(n)
        else:
            seen[k] = n
        if re.search(r"[{}]", e.term + e.translation + e.note):
            res["brace"].append(n)
        if "#" in e.term + e.translation:
            res["hash"].append(n)
    return {k: v for k, v in res.items() if v}


def check_system(system: str):
    """Problems in the system text of a prompt: ['braces'] when a lone brace would stop {language} working.

    The engine runs str.format on the system text; any failure returns the text unchanged, so a stray
    '{x}' next to '{language}' leaves '{language}' unreplaced. '{{' and '}}' are fine.
    """
    try:
        system.format(language="x", crlf="\n")
        return []
    except (KeyError, IndexError, ValueError):
        return ["braces"]


# ---------------------------------------------------------------- build prompt

def escape_braces(text: str) -> str:
    """Make text safe inside a system prompt that the engine passes through str.format."""
    return text.replace("{", "{{").replace("}", "}}")


def glossary_lines(entries, with_notes: bool = True) -> str:
    """'- term -> translation (note)' per entry, empty rows skipped, braces escaped."""
    lines = []
    for e in entries:
        if not e.term or not e.translation:
            continue
        line = f"- {e.term} -> {e.translation}"
        if with_notes and e.note:
            line += f" ({e.note})"
        lines.append(escape_braces(line))
    return "\n".join(lines)


def _has_note(entries) -> bool:
    return any(e.term and e.translation and e.note for e in entries)


def build_system(template_system: str, entries, with_notes: bool = True, head=None, hint: str = "") -> str:
    """Template text + the glossary block, the block only when there is at least one usable entry.

    head is None  -> legacy template that ends with its own glossary heading: the lines follow it at once
                     (same layout as the user's convert_glossary.py); with no entries it is returned unchanged.
    head is a str -> the template has no glossary wording: a blank line, the head, the notes hint (only when
                     some usable entry has a note and notes are on), then the lines.
    """
    lines = glossary_lines(entries, with_notes)
    if not lines:
        return template_system
    if head is None:
        return template_system.rstrip("\n") + "\n" + lines
    parts = [head.strip("\n")]
    if with_notes and hint and _has_note(entries):
        parts.append(hint.strip("\n"))
    parts.append(lines)
    return template_system.rstrip("\n") + "\n\n" + "\n".join(p for p in parts if p)


def build_prompt(template: dict, entries, with_notes: bool = True) -> dict:
    """The engine's prompt object: {"system", "user"} (plus "style" when the template has one)."""
    out = dict(template)
    head = out.pop("glossary_head", None)
    hint = out.pop("glossary_notes_hint", "")
    out["system"] = build_system(template.get("system", ""), entries, with_notes, head, hint)
    return out


_LINE = re.compile(r"^- (?P<t>.+?) -> (?P<v>.+)$")


def split_prompt(system: str):
    """Split a system text that ends with '- term -> translation' lines into (head, entries).

    `head` keeps everything up to and including the line before the first line of the final run, so that
    build_system(head, entries) gives back the original text. Returns (system, []) when there is no such run.
    """
    lines = system.split("\n")
    start = len(lines)
    while start > 0 and _LINE.match(lines[start - 1]):
        start -= 1
    if start == len(lines):
        return system, []
    entries = [Entry(m["t"], m["v"]) for m in map(_LINE.match, lines[start:])]
    return "\n".join(lines[:start]) + "\n", entries


def used_in(entries, text: str):
    """Entries whose term occurs in `text` as a whole word (case-insensitive); keeps their order."""
    hay = text.translate(_QUOTES)
    out = []
    for e in entries:
        pat = r"(?<!\w)" + re.escape(key(e.term)).replace(r"\ ", r"\s+") + r"(?!\w)"
        if re.search(pat, hay, re.IGNORECASE):
            out.append(e)
    return out
