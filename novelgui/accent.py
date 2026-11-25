"""Which one control of a screen carries the red (window_spec 1.7).

Several things can want the accent at once; exactly one gets it. The order is fixed:
1) no keys (`keys`), 2) no language chosen (`language`), 3) terms that block the first chapter (`terms`),
4) whatever the screen itself would have chosen (`candidate`, may be empty).
"""

from __future__ import annotations

from dataclasses import dataclass

KEYS = "keys"
LANGUAGE = "language"
TERMS = "terms"
NONE = ""


@dataclass(frozen=True)
class Facts:
    """What the screen knows: are there keys, is the language of the series chosen, does a term block the
    first chapter of the selection."""
    has_keys: bool = True
    language_chosen: bool = True
    first_blocked: bool = False


def owner(facts: Facts, candidate: str = NONE) -> str:
    """The name of the single element that gets the accent: `keys`, `language`, `terms`, or the screen's own
    `candidate` (empty = nobody)."""
    if not facts.has_keys:
        return KEYS
    if not facts.language_chosen:
        return LANGUAGE
    if facts.first_blocked:
        return TERMS
    return candidate or NONE


def gets_accent(name: str, facts: Facts, candidate: str = NONE) -> bool:
    """True when the element called `name` is the one that may be drawn in the accent colour."""
    return bool(name) and owner(facts, candidate) == name
