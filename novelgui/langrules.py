"""Target and source language rules of the window (window_spec 3.1-3.4, 13.11). Pure: no Tk, no core imports.

A series has at most one target language until the core knows several (core_changes C1). The language is
chosen on Translate (`To`) or in the Terms column heading; it is changeable only while nothing depends on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OTHER = "Other…"

TRANSLATED = ("The language cannot change any more: blocks are already translated into it, and the confirmed "
              "terms are written in it.")
CONFIRMED = ("The language cannot change any more: terms are already confirmed in it.")

_TAG = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?")
_NAME = re.compile(r"[^\W\d_][^\W\d_ '\-]*(?:[ '\-][^\W\d_]+)*")
FORMAT_HELP = "Type the language as tag:Name, for example de:German."


def split(target: str) -> tuple[str, str]:
    """`ru:Russian` -> (`ru`, `Russian`); a bare tag gives the tag twice (the core's own rule)."""
    tag, sep, name = str(target or "").partition(":")
    tag = tag.strip()
    return tag, (name.strip() if sep and name.strip() else tag)


def problem_other(text: str) -> str:
    """Why `text` is not a language written as `tag:Name` ("" when it is)."""
    text = (text or "").strip()
    if not text:
        return FORMAT_HELP
    tag, sep, name = text.partition(":")
    tag, name = tag.strip(), name.strip()
    if not sep:
        return "The tag is missing. " + FORMAT_HELP
    if not _TAG.fullmatch(tag.lower()):
        return "The tag is the short code of the language, two or three letters (de, fr, ja). " + FORMAT_HELP
    if not name or len(name) > 40 or not _NAME.fullmatch(name):
        return "The name is missing or has odd characters. " + FORMAT_HELP
    return ""


def parse_other(text: str) -> str:
    """`de:German` -> `de:German` (tag lower-cased, name trimmed). ValueError with the reason when it is not
    one."""
    why = problem_other(text)
    if why:
        raise ValueError(why)
    tag, _sep, name = text.strip().partition(":")
    return "%s:%s" % (tag.strip().lower(), name.strip())


def lock_reason(translated: bool, confirmed: bool) -> str:
    """Why the language of a series cannot change ("" when it can): a block is translated, or a term is
    confirmed."""
    if translated:
        return TRANSLATED
    if confirmed:
        return CONFIRMED
    return ""


def menu(current: str | None, targets, locked: bool) -> tuple[list, list]:
    """The items of the `To` list and those that are dim. `targets` is ((target, name), ...). While the language
    is locked every other language and `Other…` are dim; the current one stays pickable (it changes nothing)."""
    items = [t for t, _n in targets]
    if current and current not in items:
        items.insert(0, current)        # a language set by hand earlier, or by the core before this window
    items.append(OTHER)
    disabled = [i for i in items if locked and i != current]
    return items, disabled


def label(target: str, targets=()) -> str:
    """The name shown for a target: the listed name, else the part after the colon."""
    for t, name in targets:
        if t == target:
            return name
    return split(target)[1]


# ---------------------------------------------------------------- source language (names of exports, 13.11)
@dataclass(frozen=True)
class SourceLang:
    name: str
    tag: str


FALLBACK = SourceLang("Original", "src")

NAMES = {"en": "English", "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "ru": "Russian", "uk": "Ukrainian",
         "pl": "Polish", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
         "nl": "Dutch", "cs": "Czech", "tr": "Turkish", "vi": "Vietnamese", "th": "Thai", "id": "Indonesian"}

_LANG_EL = re.compile(r"<(?:\w+:)?language\b[^>]*>(.*?)</(?:\w+:)?language>", re.S | re.I)


def dc_language(opf_text: str) -> str:
    """The first `dc:language` of a package document, as a lower-case primary tag (`en-US` -> `en`); ""
    when there is none or it says nothing (`und`, `mul`, `zxx`)."""
    for m in _LANG_EL.finditer(opf_text or ""):
        tag = m.group(1).strip().lower().replace("_", "-").split("-")[0]
        if tag and tag not in ("und", "mul", "zxx") and re.fullmatch(r"[a-z]{2,3}", tag):
            return tag
    return ""


def source_language(book_tag: str, series_source: str) -> SourceLang:
    """The source language for file names and Export buttons: the book's dc:language, else the series'
    `source_lang`, else `Original` / `src`."""
    for raw in (book_tag, series_source):
        tag, name = split(raw)
        tag = tag.lower().split("-")[0]
        if tag and re.fullmatch(r"[a-z]{2,3}", tag):
            known = NAMES.get(tag)
            given = name if name and name.lower() != tag.lower() else ""
            return SourceLang(given or known or tag.upper(), tag)
    return FALLBACK
