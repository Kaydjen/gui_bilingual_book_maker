"""The program half of term extraction: gender vote by pronouns, and candidate mining.

Candidates are runs of capitalised words found in the text and normalised; a model pass (later) judges
them. Snippets for that pass are produced on demand and never stored.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .htmlscan import strip_markers
from .terms import Entry, TermBase, candidate, norm_key, straight

# ---------------------------------------------------------------- gender vote
WINDOW = 120
_MALE = re.compile(r"\b(?:he|his|him|himself)\b")
_FEMALE = re.compile(r"\b(?:she|her|hers|herself)\b")
MIN_HITS = 2


def _joined(text) -> str:
    if isinstance(text, str):
        return text
    return "\n".join(strip_markers(t) if isinstance(t, str) else strip_markers(t.text) for t in text)


def gender_vote(name, text) -> tuple[int, int]:
    """(male_hits, female_hits): he/his/him/himself and she/her/hers/herself within 120 characters after
    each mention of `name` (one spelling or a list of them), not crossing a line break. A pronoun that lies
    in the windows of several mentions is counted once. `text` is a string or an iterable of blocks/strings."""
    names = [name] if isinstance(name, str) else list(name)
    low = straight(_joined(text)).lower()
    male: set[int] = set()
    female: set[int] = set()
    for nm in names:
        key = norm_key(nm)
        if not key:
            continue
        pos = low.find(key)
        while pos != -1:
            end = pos + len(key)
            before_ok = pos == 0 or not (low[pos - 1].isalnum() or low[pos - 1] == "_")
            after_ok = end >= len(low) or not (low[end].isalnum() or low[end] == "_")
            if before_ok and after_ok:
                stop = min(len(low), end + WINDOW)
                nl = low.find("\n", end, stop)
                if nl != -1:
                    stop = nl
                window = low[end:stop]
                for m in _MALE.finditer(window):
                    male.add(end + m.start())
                for m in _FEMALE.finditer(window):
                    female.add(end + m.start())
            pos = low.find(key, pos + 1)
    return len(male), len(female)


def vote_verdict(male: int, female: int) -> str:
    """male / female / unknown: unknown below 2 hits in total, or when neither side has twice the other."""
    if male + female < MIN_HITS:
        return "unknown"
    if male >= 2 * female:
        return "male"
    if female >= 2 * male:
        return "female"
    return "unknown"


def _own_count(value: str, male: int, female: int) -> str:
    """The count that speaks for `value`: `he 5` for male, `she 3` for female, both otherwise."""
    if value == "male":
        return f"he {male}"
    if value == "female":
        return f"she {female}"
    return f"he {male} / she {female}"


def gender_question(model: str, male: int, female: int) -> list[dict] | None:
    """The gender candidates to ask about, or None when there is nothing to ask.

    A question is raised only when the model's gender and the he/she count disagree (the count has enough
    pronouns and points the other way), or when the model itself answered unknown. A count without enough
    pronouns leaves a male/female answer of the model unmarked. Candidates: the model's value and the count's
    value, each with its own count as evidence; when the model said unknown and the count is no help, the
    sides that have any hits are offered."""
    verdict = vote_verdict(male, female)
    if model in ("male", "female"):
        if verdict in ("male", "female") and verdict != model:
            return [candidate(model, _own_count(model, male, female)),
                    candidate(verdict, _own_count(verdict, male, female))]
        return None
    if model != "unknown":
        return None
    out = [candidate("unknown", _own_count("unknown", male, female))]
    if verdict != "unknown":
        out.append(candidate(verdict, _own_count(verdict, male, female)))
    else:
        out += [candidate(v, _own_count(v, male, female)) for v, n in (("male", male), ("female", female)) if n]
    return out


def _evidence_with(old: str, note: str) -> str:
    """`note` added to an evidence string once; a note of an earlier vote is replaced."""
    kept = [part for part in (old or "").split("; ") if part and not part.startswith("pronouns ")]
    return "; ".join(kept + [note])


def apply_gender_vote(entries, text) -> list:
    """Vote on proposed character entries (Entry objects or dicts) and raise `gender` questions by the rule
    of gender_question. The counts always go into `evidence`. An entry that is confirmed or whose gender was
    answered is left alone. A stale gender question of an entry that now needs none is removed. Returns the
    entries that carry a question after the vote."""
    body = _joined(text)
    marked = []
    for e in entries:
        is_entry = isinstance(e, Entry)
        get = (lambda k, d=None: getattr(e, k, d)) if is_entry else (lambda k, d=None: e.get(k, d))
        if get("type") != "character" or get("status") == "confirmed":
            continue
        if "gender" in (e.locked if is_entry else (e.get("locked") or ())):
            continue
        names = [get("source")] + list(get("forms") or [])
        male, female = gender_vote(names, body)
        cands = gender_question(get("gender", "unknown"), male, female)
        evidence = _evidence_with(get("evidence", ""), f"pronouns he {male} / she {female}")
        if is_entry:
            e.evidence = evidence
            questions = e.questions
        else:
            e["evidence"] = evidence
            questions = e.setdefault("questions", {})
        if cands:
            questions["gender"] = cands
            marked.append(e)
        else:
            questions.pop("gender", None)
    return marked


# ---------------------------------------------------------------- candidates
_WORD = r"[A-Z][A-Za-z]*(?:'s|-[A-Za-z]+)*"
_JOIN = r"(?: (?:(?:of|the|and|in|No\.|to) ){1,2})| "
_RUN = re.compile(r"\b%s(?:(?:%s)(?:%s|\d+))*" % (_WORD, _JOIN, _WORD))
_CONNECTORS = ("of", "the", "and", "in", "to", "No.")
STOP = set("""The A An He She It They We You I His Her Its Their Our Your My This That These Those There Here Then When
While After Before If But And Or So As At In On Of To For From With Without By However Although Though Since Because Not No
Yes Now Still Even Just Only Also What Who Why How Where Which Once Suddenly Meanwhile Moreover Instead Otherwise Hence Thus
Indeed Naturally Currently Originally Normally Unfortunately Fortunately Immediately Chapter Tier Level Rank Mr Miss Sir Is Are
Was Were Do Does Did Can Could Will Would Should May Might Must Let Every Each All Both Some Many Most Other Another
Such Very Too Well Oh Ah Haha Hmm Alright Okay Sure Please Thank Thanks Everyone Someone Anyone Nobody Nothing Something
Despite During Until Unless Whether Either Neither Rather Perhaps Maybe Especially Furthermore Besides Anyway
Afterward Shortly Soon Later Earlier Right Good Great""".split())
_SENTENCE_END = ".!?\"'\n"
SNIPPET_WIDTH = 110


@dataclass
class Candidate:
    term: str
    count: int
    mid: int  # occurrences in the middle of a sentence (not after a full stop, quote or line start)


def _trim(words: list[str]) -> list[str]:
    while words and words[0] in STOP:
        words = words[1:]
    while words and (words[-1] in STOP or words[-1] in _CONNECTORS):
        words = words[:-1]
    return words


def _is_number_like(term: str) -> bool:
    words = term.split(" ")
    if all(re.fullmatch(r"\d+", w) or w in _CONNECTORS for w in words):
        return True
    return bool(re.match(r"Chapter \d+", term))


def _fold_possessive(term: str) -> str:
    return term[:-2] if term.endswith("'s") and len(term) > 4 else term


def _alone(part: str, cnt: Counter):
    """The counted term that `part` stands for (leading "the" dropped, plural folded), or None."""
    if part.startswith("the "):
        part = part[4:]
    if part in cnt:
        return part
    for suffix in ("es", "s"):
        if part.endswith(suffix) and part[:-len(suffix)] in cnt:
            return part[:-len(suffix)]
    return None


def mine_candidates(text, base: TermBase | None = None) -> list[Candidate]:
    """Candidate terms of `text` (a string or an iterable of blocks/strings), most frequent first.

    Kept: multi-word runs seen at least twice or once in mid-sentence; single words seen in mid-sentence at
    least twice. Normalised: possessive and plural folded into the base form, leading "the" dropped, "A and B"
    split when A and B stand alone too, numbers and "Chapter N" dropped, a part of a longer name only
    when it stands alone. Candidates the base already knows (any spelling) are removed."""
    body = straight(_joined(text))
    cnt: Counter = Counter()
    mid: Counter = Counter()
    for m in _RUN.finditer(body):
        words = _trim(m.group(0).split(" "))
        if not words:
            continue
        term = " ".join(words)
        if len(term) < 3 or _is_number_like(term):
            continue
        cnt[term] += 1
        prev = body[max(0, m.start() - 2):m.start()]
        if prev and prev[-1] == " " and prev[0] not in _SENTENCE_END:
            mid[term] += 1

    # possessive onto the base form
    for term in list(cnt):
        folded = _fold_possessive(term)
        if folded != term:
            cnt[folded] += cnt.pop(term)
            mid[folded] += mid.pop(term, 0)

    # plural onto the singular when the singular stands in the text too
    for term in sorted(cnt, key=len, reverse=True):
        if term not in cnt:
            continue
        for suffix in ("es", "s"):
            if term.endswith(suffix) and len(term) - len(suffix) >= 3:
                single = term[:-len(suffix)]
                if single in cnt:
                    cnt[single] += cnt.pop(term)
                    mid[single] += mid.pop(term, 0)
                    break

    # "A and B" -> A, B when both stand alone
    for term in list(cnt):
        if " and " not in term:
            continue
        parts = [_alone(p, cnt) for p in term.split(" and ")]
        if len(parts) >= 2 and all(p is not None and p != term for p in parts):
            n, k = cnt.pop(term), mid.pop(term, 0)
            for p in parts:
                cnt[p] += n
                mid[p] += k

    out: list[Candidate] = []
    for term, n in cnt.items():
        multi = " " in term
        if (multi and (n >= 2 or mid[term] >= 1)) or (not multi and mid[term] >= 2):
            if base is not None and base.get(term) is not None:
                continue
            out.append(Candidate(term, n, mid[term]))
    out.sort(key=lambda c: (-c.count, c.term))
    return out


def snippets(text, term: str, k: int = 3, width: int = SNIPPET_WIDTH) -> list[str]:
    """Up to `k` pieces of text around the mentions of `term` (about `width` characters each side),
    spread over the text; made on demand."""
    body = straight(_joined(text))
    hits = [m.start() for m in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", body)]
    if not hits:
        return []
    step = max(1, len(hits) // k)
    out = []
    for pos in hits[::step][:k]:
        out.append(body[max(0, pos - width):pos + len(term) + width].replace("\n", " "))
    return out
