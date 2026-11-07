"""Prompt files: {"system": ..., "user": ...} with {text} in the user part."""
import json
import string

ALLOWED_FIELDS = {"text", "language", "crlf"}


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
