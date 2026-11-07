"""A prompt set: template text + glossary, stored as small files and built into the prompt file the engine reads.

  glossaries/<name>.json    the glossary (GUI format: terms, translations, notes, target language)
  prompts/<name>.src.json   the template (system text, glossary head and notes hint, user template)
  prompts/<name>.json       the built prompt: {"system", "user"}  <- this path goes to --prompt
"""
import hashlib
import json
import os
import re
from pathlib import Path

from . import glossary as gl
from .settings import data_dir

TEMPLATES = Path(__file__).resolve().parent / "templates"


def _dir(name):
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def prompts_dir():
    return _dir("prompts")


def glossaries_dir():
    return _dir("glossaries")


def safe_name(text):
    s = re.sub(r"[^\w.-]+", "_", str(text), flags=re.UNICODE).strip("._")
    return s[:60] or "prompt"


def _write(path, text):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def templates():
    """[dict(id, name, language, system, user, head, hint)] of the shipped templates. head/hint are the glossary
    block that is appended to the system text only when the glossary has entries."""
    out = []
    for f in sorted(TEMPLATES.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": f.stem, "name": d.get("name", f.stem), "language": d.get("language", ""),
                    "tag": d.get("tag", "?"),
                    "system": d.get("system", ""), "user": d.get("user", "{text}"),
                    "head": d.get("glossary_head", ""), "hint": d.get("glossary_notes_hint", "")})
    return out


def default_block():
    """(head, hint) for a prompt that starts blank: the neutral template's glossary block."""
    for t in templates():
        if t["id"] == "neutral":
            return t["head"], t["hint"]
    return "", ""


# sha256 of the system texts the first versions shipped (they ended with the glossary wording). A saved prompt whose
# system text is byte-identical to one of them is moved to the current template; an edited one is left as it is.
LEGACY = {
    "ff49a13dc21c1dd55bcb9c7074f4fa740038c706ddf69a5ae9326cf83ac37f15": "ru_literary",
    "997dd866c1a4411189b95c0f0138d7a4dceca473208721daff2332d097fa0476": "uk_literary",
    "5731067dd8c53d6305c07f368669422e78ae996d6610377bc237066598b182d3": "pl_literary",
    "1256555363a606b00285cf22e2c53e98305a57a4fbf0afb5e4358f735db4ada2": "neutral",
}


NEUTRAL, UNKNOWN = "*", "?"  # prompt language: works for any target (uses {language}) / not known
_UK, _RU, _PL = re.compile("[іїєґІЇЄҐ]"), re.compile("[ёъыэЁЪЫЭ]"), re.compile("[ąęłńśźżĄĘŁŃŚŹŻ]")


def script_lang(text):
    """Language of a prompt text by its letters: 'uk', 'ru', 'pl' or '?'."""
    uk, ru, pl = len(_UK.findall(text)), len(_RU.findall(text)), len(_PL.findall(text))
    if not (uk or ru or pl):
        return UNKNOWN
    return max((uk, "uk"), (ru, "ru"), (pl, "pl"))[1]


def detect_lang(system, user=""):
    """The language a prompt without a recorded one is written for: a shipped template (also an old one, by hash),
    else '*' when it has {language}, else by letters."""
    tid = LEGACY.get(hashlib.sha256(system.encode("utf-8")).hexdigest())
    for t in templates():
        if t["id"] == tid or t["system"] == system:
            return t["tag"]
    if "{language}" in system or "{language}" in user:
        return NEUTRAL
    return script_lang(system + " " + user)


_lang_cache = {}


def lang_of(path):
    """Language of a prompt file: the recorded one for a prompt of ours, else detected from its text."""
    p = Path(path)
    try:
        key = (str(p), p.stat().st_mtime_ns)
    except OSError:
        return UNKNOWN
    if key in _lang_cache:
        return _lang_cache[key]
    side = prompts_dir() / (p.stem + ".src.json")
    lang = UNKNOWN
    try:
        if p.parent == prompts_dir() and side.is_file():
            d = json.loads(side.read_text(encoding="utf-8"))
            tpl = d.get("template", {})
            lang = d.get("lang") or detect_lang(tpl.get("system", ""), tpl.get("user", ""))
        else:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            lang = detect_lang(d.get("system", ""), d.get("user", "")) if isinstance(d, dict) else UNKNOWN
    except (OSError, ValueError, AttributeError):
        pass
    _lang_cache[key] = lang
    return lang


def templates_for(tag):
    """Shipped templates that fit a target language: its own and the neutral one."""
    return [t for t in templates() if t["tag"] in (tag, NEUTRAL)]


def ensure_template(t):
    """Path of the built prompt of a shipped template; created (empty glossary) when it does not exist yet. A file of
    that name that holds something else is not touched."""
    name = safe_name(t["name"])
    path = prompts_dir() / (name + ".json")
    if path.is_file() and lang_of(path) == t["tag"]:
        return str(path)
    if path.exists():
        name = safe_name("%s %s" % (t["name"], t["tag"]))
    ps = PromptSet(name, t["system"], t["user"], [], t["language"], True, t["head"], t["hint"], t["tag"])
    return str(ps.save())


def select_for(tag, remembered):
    """The prompt file for a target language: the one remembered for it, else the shipped template of that language,
    else the remembered neutral prompt, else the shipped neutral template."""
    def usable(path, want):
        return bool(path) and Path(path).is_file() and lang_of(path) == want

    remembered = remembered or {}
    if tag:
        if usable(remembered.get(tag), tag):
            return remembered[tag]
        for t in templates():
            if t["tag"] == tag:
                return ensure_template(t)
    if usable(remembered.get(NEUTRAL), NEUTRAL):
        return remembered[NEUTRAL]
    return ensure_template(next(t for t in templates() if t["tag"] == NEUTRAL))


def _migrate(system):
    """(system, head, hint) of the current template when `system` is an old shipped text, else None."""
    tid = LEGACY.get(hashlib.sha256(system.encode("utf-8")).hexdigest())
    for t in templates():
        if t["id"] == tid:
            return t["system"], t["head"], t["hint"]
    return None


class PromptSet:
    """head is None for a legacy prompt whose system text carries its own glossary heading (see glossary.build_system)."""

    def __init__(self, name="", system="", user="{text}", entries=None, language="", notes=True, head=None, hint="",
                 lang=""):
        self.name = name
        self.system = system
        self.user = user
        self.entries = list(entries or [])
        self.language = language
        self.notes = notes
        self.head = head
        self.hint = hint
        self.lang = lang  # '' = not decided yet (a new prompt), see detect_lang for the other values

    @property
    def built_path(self):
        return prompts_dir() / (safe_name(self.name) + ".json")

    @classmethod
    def open(cls, path):
        """Open a built prompt of ours (with its template and glossary) or migrate a plain prompt file whose
        system text ends with '- term -> translation' lines."""
        p = Path(path)
        side = prompts_dir() / (p.stem + ".src.json")
        if p.parent == prompts_dir() and side.is_file():
            d = json.loads(side.read_text(encoding="utf-8"))
            tpl = d.get("template", {})
            entries, language = [], ""
            gpath = glossaries_dir() / (str(d.get("glossary", p.stem)) + ".json")
            if gpath.is_file():
                text = gpath.read_text(encoding="utf-8-sig")
                entries, language = gl.from_json(text), gl.file_language(text)
            system = tpl.get("system", "")
            head, hint = tpl.get("glossary_head"), tpl.get("glossary_notes_hint", "")
            if head is None:
                moved = _migrate(system)
                if moved:
                    system, head, hint = moved
            lang = d.get("lang") or detect_lang(tpl.get("system", ""), tpl.get("user", ""))
            return cls(p.stem, system, tpl.get("user", "{text}"), entries, language, d.get("notes", True), head, hint,
                       lang)
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        system = data.get("system", "") if isinstance(data.get("system"), str) else ""
        head, entries = gl.split_prompt(system)
        user = data.get("user", "{text}")
        return cls(safe_name(p.stem), head if entries else system, user, entries, lang=detect_lang(system, user))

    def save(self):
        """Write the glossary, the template and the built prompt. Returns the path of the built prompt."""
        name = safe_name(self.name)
        self.name = name
        _write(glossaries_dir() / (name + ".json"), gl.to_file_text(self.entries, self.language))
        tpl = {"system": self.system, "user": self.user}
        if self.head is not None:
            tpl["glossary_head"] = self.head
            tpl["glossary_notes_hint"] = self.hint
        side = {"format": 1, "template": tpl, "glossary": name, "notes": self.notes,
                "lang": self.lang or detect_lang(self.system, self.user)}
        _write(prompts_dir() / (name + ".src.json"), json.dumps(side, ensure_ascii=False, indent=1) + "\n")
        built = gl.build_prompt(tpl, self.entries, self.notes)
        _write(self.built_path, json.dumps(built, ensure_ascii=False, indent=2))
        return self.built_path


def rebuild(path):
    """Rebuild the built prompt from its template and glossary when it is one of ours (called before a run so
    a glossary edit never leaves a stale file). Returns True when it was rebuilt."""
    p = Path(path)
    if p.parent != prompts_dir() or not (prompts_dir() / (p.stem + ".src.json")).is_file():
        return False
    PromptSet.open(p).save()
    return True
