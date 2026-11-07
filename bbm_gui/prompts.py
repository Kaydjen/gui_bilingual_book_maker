"""Prompt files: {"system": ..., "user": ...} with {text} in the user part."""
import json
import re
import string

from . import langs

ALLOWED_FIELDS = {"text", "language", "crlf"}
CYRILLIC = re.compile("[Ѐ-ӿ]")
CYRILLIC_TAGS = {"ru", "uk", "be", "bg", "sr", "mk", "kk", "ky", "mn", "tg"}


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def save(path, system, user):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"system": system, "user": user}, f, ensure_ascii=False, indent=2)


def check(data):
    """Short problem codes about the shape of the user part: user, text, braces."""
    user = data.get("user")
    if not isinstance(user, str) or not user.strip():
        return ["user"]
    problems = []
    try:
        fields = {name for _, name, _, _ in string.Formatter().parse(user) if name is not None}
        if "text" not in fields:
            problems.append("text")
        if fields - ALLOWED_FIELDS:
            problems.append("braces")
        else:
            user.format(text="x", language="y", crlf="")
    except (ValueError, KeyError, IndexError):
        problems.append("braces")
    return problems


def _same_tag(a, b):
    a, b = a.lower(), b.lower()
    return a == b or a == b.split("-")[0] or b == a.split("-")[0]


def check_language(prompt_lang, target, data=None):
    """['lang'] when the prompt is written for another language than the target. `target` is a langs.Lang (or text).

    A prompt with a recorded language ('ru', 'uk', ...) is compared by tag; '*' (it uses {language}) fits any target.
    '?' (language unknown) is judged by its letters over both parts, and only against a known target."""
    if isinstance(target, str):
        target = langs.resolve(target)
    if not target.known or not target.tag or prompt_lang == "*":
        return []
    if prompt_lang and prompt_lang != "?":
        return [] if _same_tag(prompt_lang, target.tag) else ["lang"]
    data = data or {}
    text = "%s %s" % (data.get("system") or "", data.get("user") or "")
    if "{language}" in text:
        return []
    from . import promptset

    seen = promptset.script_lang(text)
    if seen != "?":
        return [] if _same_tag(seen, target.tag) else ["lang"]
    if CYRILLIC.search(text) and target.tag.split("-")[0] not in CYRILLIC_TAGS:
        return ["lang"]
    return []
