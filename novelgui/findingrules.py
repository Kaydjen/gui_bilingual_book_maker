"""Check findings in the problem list of Translate (window_spec 7.10). Pure: no Tk.

A finding is a translated block the checks of the core find suspicious (kinds in `novelcore.checks.KINDS`).
This module names the kinds, builds the key that tells whether a finding still describes the block as it is
now, and keeps the `Ignore` list of a volume in `<series>/.state/ignore_<stem>.json`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

LABELS = {
    "leftover": "leftover",
    "ratio": "length",
    "term": "term",
    "markup": "markup",
    "untranslated": "untranslated",
    "empty": "empty",
}

KIND_TIPS = {
    "leftover": "Part of the translation is still in the source language.",
    "ratio": "The translation is much shorter or longer than the original, compared with the rest of its chapter.",
    "term": "A confirmed term of the Terms list is not rendered as confirmed.",
    "markup": "The markers inside the paragraph (links, emphasis) do not match the original.",
    "untranslated": "The translation is the same as the original.",
    "empty": "The translation is empty.",
}


def label(kind: str) -> str:
    return LABELS.get(kind, kind)


def text_key(text: str) -> str:
    """Short digest of a translation: a finding is valid only while the block still has this text."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def detail_text(kind: str, detail) -> str:
    """The core's detail of one finding in plain words."""
    d = detail if isinstance(detail, dict) else {}
    if kind == "ratio":
        return "The translation is %s times as long as the original; typical in this chapter: %s." % (
            d.get("ratio", "?"), d.get("median", "?"))
    if kind == "term":
        return "%s should be rendered as %s (%s missing)." % (d.get("term", "?"), d.get("expected", "?"),
                                                              d.get("missing", 1))
    if kind == "leftover":
        return "Left in the source language: %s" % d.get("fragment", "")
    if kind == "markup":
        why = d.get("why")
        if why in ("count", "order"):
            return "The markers differ from the original (%s: %s in the original, %s in the translation)." % (
                "number" if why == "count" else "order", d.get("src", "?"), d.get("tr", "?"))
        return "The block was flagged for its markers."
    if kind == "untranslated":
        return "The block has %s words and is the same as the original." % d.get("words", "?")
    return KIND_TIPS.get(kind, "")


# ---------------------------------------------------------------- the ignore list
def ignore_path(series_path, book: str) -> Path:
    from novelcore.store import safe_name
    return Path(series_path) / ".state" / ("ignore_%s.json" % safe_name(book, 80))


def entry_key(chapter: int, block: int, sha: str, kind: str, tkey: str) -> tuple:
    return (int(chapter), int(block), str(sha), str(kind), str(tkey))


def load_ignored(series_path, book: str) -> set:
    try:
        data = json.loads(ignore_path(series_path, book).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out = set()
    items = data.get("ignored") if isinstance(data, dict) else None
    for it in items if isinstance(items, list) else []:
        try:
            if isinstance(it, list) and len(it) == 5:
                out.add(entry_key(*it))
        except (TypeError, ValueError):
            continue
    return out


def add_ignored(series_path, book: str, keys) -> int:
    """Remember findings as ignored; returns how many were new."""
    from novelcore.store import atomic_write_text
    have = load_ignored(series_path, book)
    new = {entry_key(*k) for k in keys} - have
    if not new:
        return 0
    path = ignore_path(series_path, book)
    path.parent.mkdir(parents=True, exist_ok=True)
    allk = sorted(have | new)
    atomic_write_text(path, json.dumps({"version": 1, "ignored": [list(k) for k in allk]},
                                       ensure_ascii=False, indent=1))
    return len(new)


# ---------------------------------------------------------------- is a finding still true
EXEMPT = frozenset({"manual", "kept"})


def still_true(rec, tkey: str) -> bool:
    """The block's latest record is the finished translation the finding was made on (not retried, typed over or
    kept since)."""
    if not isinstance(rec, dict) or rec.get("status") != "ok":
        return False
    if set(rec.get("flags") or []) & EXEMPT:
        return False
    return text_key(rec.get("text") or "") == tkey
