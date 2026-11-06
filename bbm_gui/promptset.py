"""A prompt set: template text + glossary, stored as small files and built into the prompt file the engine reads.

  glossaries/<name>.json    the glossary (GUI format: terms, translations, notes, target language)
  prompts/<name>.src.json   the template (system text ending with the glossary heading, user template)
  prompts/<name>.json       the built prompt: {"system", "user"}  <- this path goes to --prompt
"""
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
    """[(id, name, language, system, user)] of the shipped templates."""
    out = []
    for f in sorted(TEMPLATES.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append((f.stem, d.get("name", f.stem), d.get("language", ""), d.get("system", ""), d.get("user", "{text}")))
    return out


class PromptSet:
    def __init__(self, name="", system="", user="{text}", entries=None, language="", notes=True):
        self.name = name
        self.system = system
        self.user = user
        self.entries = list(entries or [])
        self.language = language
        self.notes = notes

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
            return cls(p.stem, tpl.get("system", ""), tpl.get("user", "{text}"), entries, language, d.get("notes", True))
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        system = data.get("system", "") if isinstance(data.get("system"), str) else ""
        head, entries = gl.split_prompt(system)
        return cls(safe_name(p.stem), head if entries else system, data.get("user", "{text}"), entries)

    def save(self):
        """Write the glossary, the template and the built prompt. Returns the path of the built prompt."""
        name = safe_name(self.name)
        self.name = name
        _write(glossaries_dir() / (name + ".json"), gl.to_file_text(self.entries, self.language))
        side = {"format": 1, "template": {"system": self.system, "user": self.user}, "glossary": name, "notes": self.notes}
        _write(prompts_dir() / (name + ".src.json"), json.dumps(side, ensure_ascii=False, indent=1) + "\n")
        built = gl.build_prompt({"system": self.system, "user": self.user}, self.entries, self.notes)
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
