"""Term base of one series: <series>/terms.json.

One entry per name, item, skill, title ... with its translation into the target
language (stored under the target tag, e.g. "ru"), the gender needed for
agreement, a status and bookkeeping (chapters where it was seen, count).

The file is UTF-8 JSON with one entry per line, sorted by lower-cased source,
written atomically. Fields this module does not know are kept on save.
"""

from __future__ import annotations

import json
import os
import re
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

TYPES = ("character", "organization", "place", "item", "skill", "title", "class", "creature", "term")
GENDERS = ("male", "female", "neuter", "plural", "unknown")
STATUSES = ("confirmed", "new")
QUESTION_FIELDS = ("gender", "tr", "same_as")
FILE_NAME = "terms.json"
VERSION = 1

_KNOWN = {"source", "forms", "type", "gender", "note", "hint", "same_as", "questions", "locked", "status",
          "seen", "count", "evidence", "changed", "unsure"}
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "´": "'", "`": "'"})
_SPACES = re.compile(r"\s+")


def straight(text: str) -> str:
    """Curly apostrophes replaced by the straight one."""
    return str(text).translate(_APOSTROPHES)


def norm_key(text: str) -> str:
    """Comparison key of a spelling: straight apostrophes, single spaces, lower case."""
    return _SPACES.sub(" ", straight(text)).strip().lower()


def variants(key: str) -> list[str]:
    """The key itself and the forms it may be a derivative of: without a leading "the",
    without a possessive ending, without a plural ending. Most specific first."""
    bases = [key]
    if key.startswith("the ") and len(key) > 4:
        bases.append(key[4:])
    out: list[str] = []
    for b in bases:
        stack = [b]
        if b.endswith("'s") and len(b) > 2:
            stack.append(b[:-2])
        elif b.endswith("s'") and len(b) > 2:
            stack.append(b[:-1])
        elif b.endswith("'") and len(b) > 1:
            stack.append(b[:-1])
        for s in list(stack):
            if s.endswith("es") and len(s) > 3:
                stack.append(s[:-2])
            if s.endswith("s") and len(s) > 2:
                stack.append(s[:-1])
        for s in stack:
            if s not in out:
                out.append(s)
    return out


def format_seen(seen) -> str:
    """{1,2,3,7} -> "1-3,7"."""
    nums = sorted(set(seen))
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if j == i else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(parts)


def parse_seen(value) -> set[int]:
    """Inverse of format_seen; also accepts a list of numbers or range strings. Bad pieces are ignored."""
    out: set[int] = set()
    if isinstance(value, (list, tuple, set)):
        items = [str(v) for v in value]
    elif isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, int) and not isinstance(value, bool):
        items = [str(value)]
    else:
        return out
    for it in items:
        it = it.strip()
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", it)
        if not m:
            continue
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if hi >= lo and hi - lo <= 1_000_000:
            out.update(range(lo, hi + 1))
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def candidate(value, evidence: str = "") -> dict:
    """One answer option of a question: the value and a short note on where it comes from."""
    return {"value": str(value), "evidence": str(evidence or "")}


def clean_questions(raw) -> dict:
    """{field: [{value, evidence}]} from loose input (bare strings are accepted as values); empty lists and
    unreadable pieces are dropped, a value is listed once per field."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for field, cands in raw.items():
        if not isinstance(field, str) or not isinstance(cands, list):
            continue
        items: list[dict] = []
        for c in cands:
            if isinstance(c, str):
                c = {"value": c}
            if not isinstance(c, dict) or not isinstance(c.get("value"), str):
                continue
            ev = c.get("evidence", "")
            if all(i["value"] != c["value"] for i in items):
                items.append(candidate(c["value"], ev if isinstance(ev, str) else ""))
        if items:
            out[field] = items
    return out


class Entry:
    """One term. Identity-hashed so it can key a Counter.

    `questions` maps a field to the candidate values the program holds for it without a winner; the field
    itself shows the value in use. `locked` lists fields the user answered: a model pass leaves them alone."""

    def __init__(self, source: str, *, forms=None, type: str = "term", gender: str = "unknown", tr: str = "",
                 note: str = "", hint: bool = False, same_as: str = "", status: str = "new", seen=None,
                 count: int = 0, evidence: str = "", changed: str = "", questions=None, locked=None, extra=None):
        self.source = straight(str(source)).strip()
        self.forms = [straight(f).strip() for f in (forms or []) if str(f).strip()]
        self.type = type if type in TYPES else "term"
        self.gender = gender if gender in GENDERS else "unknown"
        self.tr = str(tr or "").strip()
        self.note = str(note or "").strip()
        self.hint = bool(hint)
        self.same_as = straight(str(same_as or "")).strip()
        self.status = status if status in STATUSES else "new"
        self.seen = set(seen or ())
        self.count = int(count or 0)
        self.evidence = str(evidence or "")
        self.changed = str(changed or "")
        self.questions = clean_questions(questions)
        self.locked = {f for f in (locked or ()) if isinstance(f, str) and f}
        self.extra = dict(extra or {})

    def spellings(self) -> list[str]:
        return [self.source] + self.forms

    @property
    def has_questions(self) -> bool:
        return bool(self.questions)

    @classmethod
    def from_dict(cls, d: dict, tag: str) -> "Entry":
        extra = {k: v for k, v in d.items() if k not in _KNOWN and k != tag}
        count = d.get("count", 0)
        forms = d.get("forms")
        questions = clean_questions(d.get("questions"))
        if (d.get("status") == "unsure" or d.get("unsure") is True) and "gender" not in questions:
            # files written before questions existed: the old mark becomes a gender question
            gender = d.get("gender", "unknown")
            ev = d.get("evidence", "")
            questions["gender"] = [candidate(gender if gender in GENDERS else "unknown", ev if isinstance(ev, str) else "")]
        locked = d.get("locked")
        return cls(
            str(d.get("source", "")),
            forms=forms if isinstance(forms, list) else [],
            type=d.get("type", "term"), gender=d.get("gender", "unknown"),
            tr=d.get(tag, "") if isinstance(d.get(tag, ""), str) else "",
            note=d.get("note", "") if isinstance(d.get("note", ""), str) else "",
            hint=d.get("hint", False), same_as=d.get("same_as", "") if isinstance(d.get("same_as", ""), str) else "",
            status=d.get("status", "new"), seen=parse_seen(d.get("seen")),
            count=count if isinstance(count, int) and not isinstance(count, bool) else 0,
            evidence=d.get("evidence", "") if isinstance(d.get("evidence", ""), str) else "",
            changed=d.get("changed", "") if isinstance(d.get("changed", ""), str) else "",
            questions=questions, locked=locked if isinstance(locked, list) else [], extra=extra)

    def to_dict(self, tag: str) -> dict:
        d: dict = {"source": self.source}
        if self.forms:
            d["forms"] = list(self.forms)
        d["type"] = self.type
        d["gender"] = self.gender
        d[tag] = self.tr
        if self.note:
            d["note"] = self.note
        if self.hint:
            d["hint"] = True
        if self.same_as:
            d["same_as"] = self.same_as
        if self.questions:
            d["questions"] = {f: [dict(c) for c in cs] for f, cs in sorted(self.questions.items())}
        if self.locked:
            d["locked"] = sorted(self.locked)
        d["status"] = self.status
        if self.seen:
            d["seen"] = format_seen(self.seen)
        d["count"] = self.count
        if self.evidence:
            d["evidence"] = self.evidence
        if self.changed:
            d["changed"] = self.changed
        for k, v in self.extra.items():
            if k not in d:
                d[k] = v
        return d

    def __repr__(self) -> str:
        return f"Entry({self.source!r}, {self.type}, {self.gender}, {self.status})"


FoundReport = namedtuple("FoundReport", "added updated refused")  # lists of sources; refused = [(source, reason)]
Conflict = namedtuple("Conflict", "source kept ignored kept_file ignored_file")
ImportReport = namedtuple("ImportReport", "added same conflicts skipped")  # counts, conflicts list


class TermBase:
    """The terms of one series. `rev` grows on every change (matchers rebuild when it moves)."""

    def __init__(self, path=None, tag: str = "ru"):
        self.path = Path(path) if path else None
        self.tag = tag
        self.meta: dict = {}
        self.rev = 0
        self.warnings: list[str] = []
        self._entries: dict[str, Entry] = {}  # norm_key(source) -> entry
        self._dismissed: set[str] = set()  # norm_key of spellings the owner called "not a term"
        self._index: dict[str, Entry] | None = None  # any exact spelling -> entry
        self._index_rev = -1

    # -- file -------------------------------------------------------------
    @classmethod
    def load(cls, path, tag: str | None = None) -> "TermBase":
        """Read a base; a missing file gives an empty one. A damaged file raises ValueError (never overwritten)."""
        p = Path(path)
        data = None
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"cannot read {p}: {exc}") from exc
        meta: dict = {}
        raw: list = []
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            meta = {k: v for k, v in data.items() if k != "entries"}
            raw = data.get("entries") if isinstance(data.get("entries"), list) else []
        use = tag or (meta.get("target") if isinstance(meta.get("target"), str) else "") or "ru"
        base = cls(p, use)
        listed = meta.pop("dismissed", None)
        if isinstance(listed, list):
            base._dismissed = {norm_key(s) for s in listed if isinstance(s, str) and norm_key(s)}
        base.meta = meta
        for d in raw:
            if not isinstance(d, dict) or not str(d.get("source", "")).strip():
                base.warnings.append("skipped a record without source")
                continue
            e = Entry.from_dict(d, use)
            key = norm_key(e.source)
            if key in base._entries:
                base.warnings.append(f"duplicate source skipped: {e.source}")
                continue
            base._entries[key] = e
        return base

    def save(self, path=None) -> None:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no path to save to")
        head = {"version": VERSION, "target": self.tag}
        head.update({k: v for k, v in self.meta.items() if k not in ("version", "target")})
        head["version"] = VERSION
        head["target"] = self.tag
        if self._dismissed:
            head["dismissed"] = sorted(self._dismissed)
        prefix = json.dumps(head, ensure_ascii=False)[:-1]  # without the closing brace
        lines = [json.dumps(e.to_dict(self.tag), ensure_ascii=False) for e in self.sorted_entries()]
        text = prefix + ', "entries": [\n' + ",\n".join(lines) + ("\n" if lines else "") + "]}\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()

    # -- reading ----------------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    def sorted_entries(self) -> list[Entry]:
        return sorted(self._entries.values(), key=lambda e: (norm_key(e.source), e.source))

    def __iter__(self):
        return iter(self.sorted_entries())

    def _spelling_index(self) -> dict[str, Entry]:
        if self._index is None or self._index_rev != self.rev:
            idx: dict[str, Entry] = {}
            for e in self._entries.values():  # sources first so a source beats another entry's form
                idx[norm_key(e.source)] = e
            for e in self._entries.values():
                for f in e.forms:
                    idx.setdefault(norm_key(f), e)
            for k, e in list(idx.items()):  # a stored leading "the" is optional
                if k.startswith("the ") and len(k) > 4:
                    idx.setdefault(k[4:], e)
            self._index, self._index_rev = idx, self.rev
        return self._index

    def exact(self, spelling: str) -> Entry | None:
        """The entry whose source or form equals `spelling` (case, apostrophes, spaces ignored)."""
        return self._spelling_index().get(norm_key(spelling))

    def get(self, spelling: str) -> Entry | None:
        """Entry by any spelling, including the automatic variants (plural, possessive, leading "the")."""
        idx = self._spelling_index()
        for k in variants(norm_key(spelling)):
            e = idx.get(k)
            if e is not None:
                return e
        return None

    def resolve_gender(self, entry: Entry) -> str:
        """Gender of an entry; an alias takes the gender of the entry it points to."""
        if entry.same_as:
            target = self.exact(entry.same_as)
            if target is not None and target is not entry:
                return target.gender
        return entry.gender

    def request_gender(self, entry: Entry) -> str:
        """Gender to send to the translator: `unknown` while the gender (of the entry, or of the entry an
        alias points to) is an open question."""
        if "gender" in entry.questions:
            return "unknown"
        if entry.same_as:
            target = self.exact(entry.same_as)
            if target is not None and target is not entry and "gender" in target.questions:
                return "unknown"
        return self.resolve_gender(entry)

    # -- questions --------------------------------------------------------
    def questioned(self) -> list[Entry]:
        """Entries with at least one open question, in file order."""
        return [e for e in self.sorted_entries() if e.questions]

    def _entry_of(self, entry) -> Entry:
        if isinstance(entry, Entry):
            return entry
        found = self.exact(entry)
        if found is None:
            raise KeyError(entry)
        return found

    def ask(self, entry, field: str, candidates) -> Entry:
        """Open (or replace) the question on `field` with the given candidates ({value, evidence} dicts)."""
        e = self._entry_of(entry)
        if field not in QUESTION_FIELDS:
            raise ValueError(f"no question on field {field!r}")
        cands = clean_questions({field: list(candidates)}).get(field)
        if not cands:
            raise ValueError("a question needs a candidate")
        e.questions[field] = cands
        self._touch(e)
        return e

    def answer(self, entry, field: str, value: str) -> Entry:
        """Set `field` to `value` (any value, not only a listed candidate), close its question and lock the
        field against model passes."""
        e = self._entry_of(entry)
        if field not in e.questions:
            raise KeyError(field)
        value = str(value).strip()
        if field == "gender":
            if value not in GENDERS:
                raise ValueError(f"bad gender {value!r}")
            e.gender = value
        elif field == "tr":
            e.tr = value
        elif field == "same_as":
            e.same_as = straight(value).strip()
        else:
            raise ValueError(f"cannot answer field {field!r}")
        del e.questions[field]
        e.locked.add(field)
        self._touch(e)
        return e

    def confirm(self, entry) -> Entry:
        """Accept the entry as shown: its open questions are answered with the values in use, status confirmed."""
        e = self._entry_of(entry)
        e.questions.clear()
        e.status = "confirmed"
        self._touch(e)
        return e

    # -- dismissed ("not a term") -------------------------------------------
    # Kept outside the entries: the matcher and the request lines only read entries, so a dismissed
    # spelling cannot reach a translation request.
    def dismissed(self) -> list[str]:
        """Normalised spellings the owner dismissed, sorted."""
        return sorted(self._dismissed)

    def is_dismissed(self, spelling: str) -> bool:
        """True when the spelling, or the form it may be a derivative of (plural, possessive, "the"), is dismissed."""
        if not self._dismissed:
            return False
        return any(k in self._dismissed for k in variants(norm_key(spelling)))

    def dismiss(self, spelling: str) -> bool:
        """Mark a spelling as "not a term". Returns False when it was already dismissed. An existing entry
        cannot be dismissed (delete it instead)."""
        key = norm_key(spelling)
        if not key:
            raise ValueError("empty spelling")
        if self.exact(spelling) is not None:
            raise ValueError(f"{spelling!r} is an entry")
        if key in self._dismissed:
            return False
        self._dismissed.add(key)
        self._touch()
        return True

    def restore(self, spelling: str) -> bool:
        """Undo dismiss(); False when the spelling was not dismissed."""
        key = norm_key(spelling)
        if key not in self._dismissed:
            return False
        self._dismissed.discard(key)
        self._touch()
        return True

    # -- changes ----------------------------------------------------------
    def _touch(self, entry: Entry | None = None) -> None:
        self.rev += 1
        if entry is not None:
            entry.changed = now_iso()

    def _register(self, entry: Entry) -> None:
        """Put a new entry in; the spelling index is extended in place (adding thousands stays cheap)."""
        idx = self._spelling_index()
        self._entries[norm_key(entry.source)] = entry
        for sp in entry.spellings():
            k = norm_key(sp)
            idx[k] = entry
            if k.startswith("the ") and len(k) > 4:
                idx.setdefault(k[4:], entry)
        self._touch(entry)
        self._index_rev = self.rev

    def _check_free(self, spellings, ignore: Entry | None = None) -> None:
        idx = self._spelling_index()
        for s in spellings:
            e = idx.get(norm_key(s))
            if e is not None and e is not ignore:
                raise ValueError(f"spelling already used by {e.source!r}: {s!r}")

    def add(self, source: str, *, status: str = "confirmed", **fields) -> Entry:
        """Add an entry by hand (default status confirmed). Fields: forms, type, gender, tr, note, hint, same_as ..."""
        entry = Entry(source, status=status, **fields)
        if not entry.source:
            raise ValueError("empty source")
        self._check_free(entry.spellings())
        self._register(entry)
        return entry

    def edit(self, current: str, /, **changes) -> Entry:
        """Change an entry as the user: sets status confirmed. Keys: source, forms, type, gender, tr, note,
        hint, same_as, evidence."""
        entry = self.exact(current)
        if entry is None:
            raise KeyError(current)
        allowed = {"source", "forms", "type", "gender", "tr", "note", "hint", "same_as", "evidence"}
        bad = set(changes) - allowed
        if bad:
            raise ValueError("cannot edit: " + ", ".join(sorted(bad)))
        if "type" in changes and changes["type"] not in TYPES:
            raise ValueError(f"bad type {changes['type']!r}")
        if "gender" in changes and changes["gender"] not in GENDERS:
            raise ValueError(f"bad gender {changes['gender']!r}")
        new_source = straight(changes.get("source", entry.source)).strip()
        new_forms = [straight(f).strip() for f in changes.get("forms", entry.forms) if str(f).strip()]
        if not new_source:
            raise ValueError("empty source")
        self._check_free([new_source] + new_forms, ignore=entry)
        del self._entries[norm_key(entry.source)]
        entry.source, entry.forms = new_source, new_forms
        for k in ("type", "gender", "note", "evidence"):
            if k in changes:
                setattr(entry, k, str(changes[k]).strip() if k in ("note", "evidence") else changes[k])
        if "tr" in changes:
            entry.tr = str(changes["tr"]).strip()
        if "hint" in changes:
            entry.hint = bool(changes["hint"])
        if "same_as" in changes:
            entry.same_as = straight(str(changes["same_as"])).strip()
        entry.questions.clear()  # an edit confirms the entry as shown
        entry.status = "confirmed"
        self._entries[norm_key(entry.source)] = entry
        self._touch(entry)
        return entry

    def delete(self, source: str) -> bool:
        entry = self.exact(source)
        if entry is None:
            return False
        del self._entries[norm_key(entry.source)]
        for e in self._entries.values():
            if e.same_as and norm_key(e.same_as) == norm_key(entry.source):
                e.same_as = ""
        self._touch()
        return True

    def merge(self, keep: str, other: str) -> Entry:
        """`other` disappears into `keep`: its spellings become forms, counts and seen are united, empty
        fields of `keep` are filled from it."""
        a, b = self.exact(keep), self.exact(other)
        if a is None or b is None:
            raise KeyError(keep if a is None else other)
        if a is b:
            return a
        del self._entries[norm_key(b.source)]
        have = {norm_key(s) for s in a.spellings()}
        for s in b.spellings():
            if norm_key(s) not in have:
                a.forms.append(s)
                have.add(norm_key(s))
        a.seen |= b.seen
        a.count += b.count
        if not a.tr:
            a.tr = b.tr
        if a.gender == "unknown":
            a.gender = b.gender
        if not a.note:
            a.note = b.note
        for field, cands in b.questions.items():
            a.questions.setdefault(field, cands)
        a.locked |= b.locked
        for e in self._entries.values():
            if e.same_as and norm_key(e.same_as) == norm_key(b.source):
                e.same_as = a.source
        self._touch(a)
        return a

    def record_seen(self, entry: Entry, chapter: int, hits: int) -> bool:
        """Note that `entry` occurs `hits` times in `chapter`. The count grows only the first time a chapter
        is recorded for the entry (so scanning twice does not double it). Returns True when something changed."""
        if hits <= 0 or chapter in entry.seen:
            return False
        entry.seen.add(chapter)
        entry.count += hits
        return True

    def add_found(self, proposals, origin: str) -> FoundReport:
        """Take entries proposed by a program or a model pass (dicts or Entry objects).

        A confirmed entry is never changed (only `seen` and `count` may grow). An existing new entry is
        updated from the non-empty fields of the proposal, except fields the user answered (`locked`). A
        proposal cannot confirm anything; it may carry `questions` ({field: [{value, evidence}]}), which
        replace the open question of that field. A changed value whose proposal brings no question closes the
        old question of that field. Returns (added, updated, refused) lists of sources."""
        added: list[str] = []
        updated: list[str] = []
        refused: list[tuple[str, str]] = []
        for prop in proposals:
            p = prop.to_dict(self.tag) if isinstance(prop, Entry) else dict(prop)
            source = straight(str(p.get("source", ""))).strip()
            if not source:
                refused.append(("", "empty source"))
                continue
            tr = p.get(self.tag, p.get("tr"))
            forms = [straight(f).strip() for f in (p.get("forms") or []) if str(f).strip()]
            seen = parse_seen(p.get("seen"))
            count = p.get("count") if isinstance(p.get("count"), int) else 0
            questions = clean_questions(p.get("questions"))
            existing = self.get(source)
            if existing is not None:
                grew = False
                if seen - existing.seen:
                    existing.seen |= seen
                    grew = True
                if count > existing.count:
                    existing.count = count
                    grew = True
                if existing.status == "confirmed":
                    refused.append((existing.source, "confirmed"))
                    continue
                changed = grew
                free = lambda f: f not in existing.locked  # noqa: E731
                if free("tr") and isinstance(tr, str) and tr.strip() and tr.strip() != existing.tr:
                    existing.tr, changed = tr.strip(), True
                    if "tr" not in questions:
                        existing.questions.pop("tr", None)
                if (free("gender") and p.get("gender") in GENDERS and p["gender"] != "unknown"
                        and p["gender"] != existing.gender):
                    existing.gender, changed = p["gender"], True
                    if "gender" not in questions:
                        existing.questions.pop("gender", None)
                if p.get("type") in TYPES and p["type"] != existing.type and not (p["type"] == "term" and existing.type != "term"):
                    existing.type, changed = p["type"], True
                if isinstance(p.get("note"), str) and p["note"].strip() and p["note"].strip() != existing.note:
                    existing.note, changed = p["note"].strip(), True
                if "hint" in p and bool(p["hint"]) != existing.hint:
                    existing.hint, changed = bool(p["hint"]), True
                if (free("same_as") and isinstance(p.get("same_as"), str) and p["same_as"].strip()
                        and p["same_as"] != existing.same_as):
                    existing.same_as, changed = straight(p["same_as"]).strip(), True
                    if "same_as" not in questions:
                        existing.questions.pop("same_as", None)
                if isinstance(p.get("evidence"), str) and p["evidence"] and p["evidence"] != existing.evidence:
                    existing.evidence, changed = p["evidence"], True
                have = {norm_key(s) for s in existing.spellings()}
                idx = self._spelling_index()
                for f in forms:
                    k = norm_key(f)
                    if k not in have and (idx.get(k) in (None, existing)):
                        existing.forms.append(f)
                        have.add(k)
                        changed = True
                for field, cands in questions.items():
                    if free(field) and existing.questions.get(field) != cands:
                        existing.questions[field], changed = cands, True
                if changed:
                    self._touch(existing)
                    updated.append(existing.source)
                continue
            try:
                self._check_free([source] + forms)
            except ValueError as exc:
                refused.append((source, str(exc)))
                continue
            entry = Entry(source, forms=forms, type=p.get("type", "term"), gender=p.get("gender", "unknown"),
                          tr=tr if isinstance(tr, str) else "", note=p.get("note", "") or "",
                          hint=p.get("hint", False), same_as=p.get("same_as", "") or "",
                          status="new", seen=seen, count=count, questions=questions,
                          evidence=p.get("evidence", "") or "", extra={"origin": origin})
            self._register(entry)
            added.append(entry.source)
        return FoundReport(added, updated, refused)


def import_glossary(base: TermBase, files) -> ImportReport:
    """Import plain {english: translation} JSON files, in priority order.

    New entries are `confirmed`, type `term`, gender `unknown`. The same source (case, apostrophes and
    spaces ignored) with a different translation in a later file (or already in the base) is a conflict:
    the first translation stays as the shown value, the entry gets a `tr` question listing every rendering
    with the file it came from, and the conflict is counted. Exact duplicates are silent. A rendering the
    user already answered is not asked again."""
    added = same = skipped = 0
    conflicts: list[Conflict] = []
    base_name = base.path.name if base.path else "base"
    origin: dict[str, str] = {}  # key -> file that supplied the shown translation
    for f in files:
        path = Path(f)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path.name}: not a JSON object")
        for src, tr in data.items():
            if not isinstance(src, str) or not isinstance(tr, str) or not src.strip() or not tr.strip():
                skipped += 1
                continue
            tr = tr.strip()
            existing = base.exact(src)
            if existing is None:
                base.add(src, status="confirmed", type="term", gender="unknown", tr=tr)
                origin[norm_key(src)] = path.name
                added += 1
            elif existing.tr == tr or "tr" in existing.locked:
                same += 1
            elif not existing.tr:
                existing.tr = tr
                base._touch(existing)
                origin[norm_key(src)] = path.name
                added += 1
            else:
                kept_file = origin.get(norm_key(existing.source), base_name)
                conflicts.append(Conflict(existing.source, existing.tr, tr, kept_file, path.name))
                cands = existing.questions.setdefault("tr", [candidate(existing.tr, kept_file)])
                for c in cands:
                    if c["value"] == tr:
                        if path.name not in c["evidence"].split(", "):
                            c["evidence"] = ", ".join(x for x in (c["evidence"], path.name) if x)
                        break
                else:
                    cands.append(candidate(tr, path.name))
                base._touch(existing)
    return ImportReport(added, same, conflicts, skipped)
