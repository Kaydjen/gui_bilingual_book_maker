"""Text for the engine's flags.

Layers: the engine's own help (cleaned, shortened) is the base and is always available. For the curated flags the
overlay holds one sentence ("Lets you ...") and one example; they are shown only while the engine's text they were
written against is unchanged (`seen` is a signature of that text, the type, the default and the choices). When the
engine moves, the entry switches itself off and the engine's text shows instead."""
import hashlib
import json
import re
from typing import NamedTuple

CHOICE_DUMP = re.compile(r",?\s*[Aa]vailable:?\s*\{[^}]*\}\.?")
BIG_BRACES = re.compile(r"\{[^}]{80,}\}")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z'\"(`-])")
ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.")
SHORT_MAX = 160  # shown as it is up to this length
SENTENCE_MAX = 200


class Doc(NamedTuple):
    about: str     # one line: ours when valid, else the engine's, shortened
    example: str   # ours only
    engine: str    # the engine's text, cleaned, in full
    ours: bool     # about/example are ours
    stale: bool    # an entry exists but the engine's text moved


def _dump(m):
    return "" if m.string[:m.start()].rstrip().endswith((".", "!", "?")) or not m.string[:m.start()].strip() else "."


def clean(text):
    """The engine's help without the dump of choices, on one line, first letter capital."""
    if not isinstance(text, str):
        return ""
    t = CHOICE_DUMP.sub(_dump, text)
    t = BIG_BRACES.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([.,;])", r"\1", t)
    return t[:1].upper() + t[1:]


def first_sentence(text):
    """Up to the first sentence end that is not an abbreviation."""
    start = 0
    for m in SENTENCE_END.finditer(text):
        head = text[start:m.start()]
        if head.lower().endswith(ABBREVIATIONS):
            continue
        return head
    return text


def short(text):
    """The one line shown in the list: as it is when short, else the first sentence, else cut at a clause."""
    c = clean(text)
    if not c or c.startswith(("--", "Ex:", "$")):
        return ""  # a command line is no description: label only, the full text stays in the detail
    if len(c) <= SHORT_MAX:
        return c
    first = first_sentence(c)
    if len(first) <= SENTENCE_MAX:
        return first
    cut = max(first.rfind(", ", 0, SHORT_MAX), first.rfind("; ", 0, SHORT_MAX), first.rfind(" (", 0, SHORT_MAX))
    return (first[:cut] if cut > 40 else first[:SHORT_MAX].rstrip()) + "…"


def signature(flag):
    """8 hex digits that change when the engine rewrites the first sentence, the type, the default or the choices."""
    raw = "|".join((first_sentence(clean(flag.get("help"))), str(flag.get("type")), repr(flag.get("default")),
                    json.dumps(flag.get("choices"), sort_keys=True, default=str)))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def describe(flag, ov):
    """ov: the overlay entry of the flag ({} if none)."""
    engine = clean(flag.get("help"))
    entry = bool(ov.get("about"))
    if entry and ov.get("seen") == signature(flag):
        return Doc(ov["about"], ov.get("example", ""), engine, True, False)
    return Doc(short(flag.get("help")), "", engine, False, entry)


def drift(inventory, overlay):
    """[(flag id, why)] for every curated entry whose engine text moved or whose flag is gone (empty when in step)."""
    byid = {f["id"]: f for f in (inventory or {}).get("flags", [])}
    out = []
    for fid, ov in sorted((overlay or {}).get("flag", {}).items()):
        if "seen" not in ov:
            continue
        f = byid.get(fid)
        if f is None:
            out.append((fid, "missing"))
        elif ov["seen"] != signature(f):
            out.append((fid, "changed"))
    return out
