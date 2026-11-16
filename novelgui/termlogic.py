"""Pure logic of the term list: filters, ordering, the search pattern of one term.

Works on core `Entry` objects (or anything with the same attributes); no Tk here.
"""

from __future__ import annotations

import re

GENDER_NAMES = ("male", "female", "neuter", "plural", "unknown")
FAR = 10 ** 9


def first_seen(entry) -> int | None:
    seen = getattr(entry, "seen", None)
    return min(seen) if seen else None


def n_questions(entries) -> int:
    return sum(1 for e in entries if e.questions)


def counts(entries) -> dict:
    """Numbers shown on the filter switch."""
    new = sum(1 for e in entries if e.status == "new")
    return {"new": new, "known": len(entries) - new, "questions": n_questions(entries)}


def passes(entry, tab: str, query: str = "", type_filter: str | None = None, in_selection=None) -> bool:
    """Filter of the table. tab: new | known | questions. `in_selection` is None (no restriction) or a set of
    entry ids that are matched in the selected chapters."""
    if tab == "questions":
        if not entry.questions:
            return False
    elif tab == "known":
        if entry.status == "new":
            return False
    elif tab == "new":
        if entry.status != "new":
            return False
    if type_filter and entry.type != type_filter:
        return False
    if in_selection is not None and id(entry) not in in_selection:
        return False
    q = query.strip().lower()
    if q:
        hay = [entry.source.lower(), (entry.tr or "").lower()] + [f.lower() for f in entry.forms]
        if not any(q in h for h in hay):
            return False
    return True


def sort_key(entry, key: str):
    if key == "count":
        return (entry.count, entry.source.lower())
    if key == "first":
        f = first_seen(entry)
        return (FAR if f is None else f, entry.source.lower())
    if key == "tr":
        return ((entry.tr or "").lower(), entry.source.lower())
    return (str(getattr(entry, key, "")).lower(), entry.source.lower())


def default_order(tab: str) -> tuple[str, bool]:
    """(column, descending): New starts with the terms that appear first in the book, then the more frequent."""
    return ("first", False) if tab in ("new", "next") else ("count", True)


def arrange_next(rows, query: str, type_filter, key: str, desc: bool) -> list:
    """Rows of the Next filter. `rows` already come in frontier order (first chapter, then count); that order
    is kept while the table is sorted by First ascending."""
    q = query.strip().lower()
    out = [e for e in rows if (not type_filter or e.type == type_filter) and
           (not q or q in e.source.lower() or q in (e.tr or "").lower())]
    if key == "first" and not desc:
        return out
    out.sort(key=lambda e: sort_key(e, key), reverse=desc)
    return out


def arrange(entries, tab: str, query: str, type_filter, key: str, desc: bool, in_selection=None) -> list:
    rows = [e for e in entries if passes(e, tab, query, type_filter, in_selection)]
    if key == "first" and tab == "new":
        # first chapter ascending, then the more frequent term first; terms never seen go last
        rows.sort(key=lambda e: (FAR if first_seen(e) is None else first_seen(e), -e.count, e.source.lower()),
                  reverse=desc)
    else:
        rows.sort(key=lambda e: sort_key(e, key), reverse=desc)
    return rows


def term_regex(entry) -> "re.Pattern":
    """Pattern of every spelling of a term: whole words, optional plural / possessive ending, either apostrophe."""
    names = sorted({entry.source, *entry.forms}, key=len, reverse=True)
    parts = []
    for n in names:
        n = n.strip()
        if n:
            parts.append(re.escape(n).replace("\\'", "['’]").replace("'", "['’]"))
    if not parts:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?<!\w)(?:%s)(?:['’]s|['’]|es|s)?(?!\w)" % "|".join(parts), re.I)


PRONOUNS = re.compile(r"\b(?:he|she|his|her|hers|him|himself|herself)\b", re.I)


def meta_line(entry, marks: dict) -> str:
    """The dim line at the top of the reader: other spellings, then the evidence of the open questions."""
    parts = []
    if entry.forms:
        parts.append("also: " + ", ".join(entry.forms))
    for field, cands in entry.questions.items():
        if field == "gender":
            ev = " · ".join(c["evidence"] for c in cands if c.get("evidence"))
            parts.append(("gender  " + ev).strip())
        else:
            parts.append(" · ".join("%s  %s" % (c["value"], c.get("evidence", "")) for c in cands))
    return "   ".join(parts)
