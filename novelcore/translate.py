"""Request building, answer validation and group splitting.

`ask(system, user, schema) -> Result` is supplied by the caller (it deals with
keys, quotas and waiting). Only content problems are handled here: an empty,
truncated, refused or implausible answer is a rejected group.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import profiles
from .gemini import BadRequest, EmptyAnswer, Truncated
from .htmlscan import markers_ok, strip_markers
from .profiles import script_share  # noqa: F401  (kept as a public name)

TEXT_HEADER = "TEXT"
MIN_CHECKED = 40  # language and length checks apply to sources longer than this
RATIO_MIN, RATIO_MAX = 0.4, 2.5
SINGLE_ATTEMPTS = 3  # first try + 2 more
CONTEXT_PAIRS = 3
HEADING = "# "  # a term line starting with this is a heading of a sub-list, not a term

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {"id": {"type": "INTEGER"}, "text": {"type": "STRING"}},
        "required": ["id", "text"],
        "propertyOrdering": ["id", "text"],
    },
}


class Stopped(Exception):
    """The run was asked to stop."""


class ServiceDown(Exception):
    """The service kept failing; nothing is recorded for the blocks involved."""


def build_user(terms, context, items) -> str:
    """User turn: TERMS (if any), CONTEXT (if any), TEXT."""
    parts = []
    if terms and any(t.startswith(HEADING) for t in terms):  # sub-lists carry their own one-line headings
        lines = [t[len(HEADING):] if t.startswith(HEADING) else t for t in terms]
        parts.append("TERMS\n" + "\n".join(lines))
    elif terms:
        parts.append("TERMS (use these renderings exactly)\n" + "\n".join(terms))
    if context:
        pairs = "\n\n".join(f"{src}\n=> {tr}" for src, tr in context)
        parts.append("CONTEXT (earlier text and its translation, for reference only; do not translate or repeat it)\n" + pairs)
    parts.append(
        f"{TEXT_HEADER} (translate every item; reply with a JSON list of {{id, text}} using the same ids; "
        "keep markers such as <1>...</1> and <2/> exactly, in the same places)\n"
        + json.dumps(items, ensure_ascii=False)
    )
    return "\n\n".join(parts)


def _parse(result, n: int):
    """{id: text} from a result, or a reason string when the shape is wrong."""
    data = result.json
    if not isinstance(data, list):
        return "format"
    out: dict[int, str] = {}
    for it in data:
        if not isinstance(it, dict):
            return "format"
        try:
            i = int(it.get("id"))
        except (TypeError, ValueError):
            return "format"
        text = it.get("text")
        if not isinstance(text, str):
            return "format"
        if i in out:
            return "duplicate"
        out[i] = text
    if any(i < 1 or i > n for i in out):
        return "extra"
    return out


def check_text(block, text: str, tag: str):
    """Reason why `text` is not an acceptable translation of `block`, or None."""
    if not text.strip():
        return "empty"
    plain_src = strip_markers(block.text)
    if len(plain_src) > MIN_CHECKED:
        plain = strip_markers(text)
        wrong = profiles.get(tag).wrong_language(plain)  # "script" / "language"
        if wrong:
            return wrong
        ratio = len(plain) / max(len(plain_src), 1)
        if not (RATIO_MIN <= ratio <= RATIO_MAX):
            return "length"
    return None


@dataclass
class Outcome:
    ok: int = 0
    failed: int = 0
    flagged: int = 0
    requests: int = 0


class GroupTranslator:
    """Translates pending blocks of one chapter, in order, with splitting on rejection."""

    def __init__(self, ask, system: str, tag: str, per_request: int = 5, terms_fn=None,
                 context_fn=None, stopped=None):
        self.ask = ask
        self.system = system
        self.tag = tag
        self.n = max(1, per_request)
        self.terms_fn = terms_fn
        self.context_fn = context_fn
        self.stopped = stopped or (lambda: False)
        self.out = Outcome()

    def run(self, blocks, on_ok, on_fail, on_commit=None) -> Outcome:
        """on_ok(block, text, flags) / on_fail(block, reason) are called as soon as a block is decided;
        on_commit() after each request's decisions (a place to write the batch out)."""
        self.on_ok, self.on_fail = on_ok, on_fail
        self.on_commit = on_commit or (lambda: None)
        for k in range(0, len(blocks), self.n):
            self._group(blocks[k:k + self.n], False)
        return self.out

    def _group(self, blocks, final_markup: bool, attempt: int = 1) -> None:
        if self.stopped():
            raise Stopped()
        items = [{"id": i + 1, "text": b.text} for i, b in enumerate(blocks)]
        terms = self.terms_fn(blocks) if self.terms_fn else []
        context = self.context_fn(blocks[0].index) if self.context_fn else []
        user = build_user(terms, context, items)
        self.out.requests += 1
        reason = None
        texts = None
        try:
            result = self.ask(self.system, user, SCHEMA)
        except (EmptyAnswer, Truncated, BadRequest) as exc:
            reason = exc.kind
        else:
            parsed = _parse(result, len(blocks))
            if isinstance(parsed, str):
                reason = parsed
            else:
                texts = parsed
                for i, b in enumerate(blocks):
                    text = texts.get(i + 1)
                    reason = "missing" if text is None else check_text(b, text, self.tag)
                    if reason:
                        break
        if reason is not None:
            self._reject(blocks, reason, final_markup, attempt)
            return
        bad = []
        for i, b in enumerate(blocks):
            text = texts[i + 1].strip()
            if markers_ok(b.markers, text):
                self.out.ok += 1
                self.on_ok(b, text, [])
            elif final_markup:
                self.out.ok += 1
                self.out.flagged += 1
                self.on_ok(b, strip_markers(text), ["markup"])
            else:
                bad.append(b)
        self.on_commit()
        if bad:
            self._group(bad, True)

    def _reject(self, blocks, reason: str, final_markup: bool, attempt: int) -> None:
        if len(blocks) > 1:
            half = (len(blocks) + 1) // 2
            self._group(blocks[:half], final_markup)
            self._group(blocks[half:], final_markup)
        elif attempt < SINGLE_ATTEMPTS:
            self._group(blocks, final_markup, attempt + 1)
        else:
            self.out.failed += 1
            self.on_fail(blocks[0], reason)
            self.on_commit()
