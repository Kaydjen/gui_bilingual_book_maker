"""Demo terms of the Knights series for the Terms scenarios and tests (the base of the mock-up full/terms.js, with real
files behind it): chapters 2650-2819 (170 chapters, position 1 = number 2650; position 0 is the contents page), terms.json
written through the core, the book text mentioning the names so a real scan finds them.

`n` = unconfirmed and found in the chapters 2697-2750 (they BLOCK those chapters), `u` = unconfirmed elsewhere, `k` =
confirmed; a choice is `ask`. Mined names without a rendering are not in the file: they are suggestions (`suggest`).
"""

from __future__ import annotations

FIRST_NUMBER = 2650
SELECTION = "2697-2750"

# source, rendering, type, gender (stored), first chapter NUMBER, count, about, status, ask
BASE = [
    ("Gawain", "Гавейн", "character", "male", 2697, 314, "a knight of the court", "n", None),
    ("Lot", "Лот", "character", "male", 2697, 124, "a knight of the court", "n",
     ("gender", [("male", "glossary_a.json"), ("female", "glossary_b.json")])),
    ("Silver Spear", "Серебряное Копьё", "item", "unknown", 2698, 21, "", "n", None),
    ("Moon Gate", "Лунные Врата", "place", "unknown", 2699, 12, "", "n", None),
    ("Morgana", "Моргана", "character", "female", 2701, 308, "half-sister of the king", "n", None),
    ("Percival", "Персиваль", "character", "male", 2703, 247, "", "n",
     ("tr", [("Персиваль", "glossary_a.json"), ("Парсифаль", "glossary_b.json")])),
    ("Cornwall", "Корнуолл", "place", "unknown", 2703, 110, "", "n", None),
    ("Order of the Round Table", "Орден Круглого Стола", "organization", "unknown", 2704, 69, "", "n", None),
    ("Tintagel", "Тинтагель", "place", "unknown", 2760, 63, "", "u", None),
    ("Lyonesse", "Лионесс", "place", "unknown", 2771, 53, "", "u", None),
    ("Lake Sisters", "Сёстры Озера", "organization", "unknown", 2790, 52, "", "u", None),
    ("Galahad", "Галахад", "character", "male", 2801, 11, "son of Lancelot", "u",
     ("tr", [("Галахад", "glossary_a.json"), ("Галаад", "glossary_b.json")])),
    ("Dragon Hall", "Драконий зал", "place", "unknown", 2803, 2, "", "u", None),
    ("Lancelot", "Ланселот", "character", "male", 2651, 1890, "first knight", "k", None),
    ("Arthur", "Артур", "character", "male", 2651, 2650, "the king", "k", None),
    ("Camelot", "Камелот", "place", "unknown", 2651, 980, "", "k", None),
    ("Excalibur", "Экскалибур", "item", "unknown", 2653, 140, "", "k", None),
    ("Merlin", "Мерлин", "character", "male", 2652, 760, "", "k", ("tr", [("Мерлин", "in use"), ("Мерлен", "glossary_b.json")])),
]
SUGGESTED = [("Brisen", 9, 2706), ("Elaine", 7, 2712), ("Corbenic", 4, 2731)]


def position(number: int) -> int:
    return number - FIRST_NUMBER + 1


def places(first: int) -> list:
    """The chapters (title numbers) a term is mentioned in: its first one and two later ones (the reader steps through them)."""
    return [first, first + 2, first + 5]


def terms(extra: int = 26, ready: bool = False, unscanned: int = 0) -> list:
    """Term specs for libfixture (`terms`): the mock's base plus `extra` unconfirmed names elsewhere in the book. `ready`: the
    terms that block 2697-2750 are confirmed. `unscanned`: every n-th term has no places yet (a scan is still to come)."""
    out = []
    for n, (src, tr, typ, gen, first, count, note, kind, ask) in enumerate(BASE):
        t = {"src": src, "tr": tr, "type": typ, "gender": gen, "note": note, "count": count,
             "seen": [position(x) for x in places(first)], "status": "confirmed" if kind == "k" or (ready and kind == "n") else "new"}
        if unscanned and n % unscanned == 0:
            t["seen"], t["count"] = [], 0
        if ready and kind == "n":
            ask = None
        if ask:
            t["ask"] = list(ask)
            if kind == "k":
                t["status"] = "confirmed"
        out.append(t)
    for i in range(extra):
        out.append({"src": "Name %d" % (i + 1), "tr": "Имя %d" % (i + 1), "type": "character",
                    "gender": "female" if i % 2 == 0 else "male", "count": 40 - i, "seen": [position(2810 + i % 9)],
                    "status": "new"})
    return out


def mentions() -> dict:
    out: dict = {}
    for src, _tr, _typ, _gen, first, *_rest in BASE:
        for n in places(first):
            out.setdefault(str(n), []).append(src)
    return out


def knights(extra: int = 26, chapters: int = 170, with_terms: bool = True, ready: bool = False, unscanned: int = 0, **kw) -> dict:
    spec = {"name": "Knights", "books": [{"stem": "Book 1", "chapters": chapters, "start": FIRST_NUMBER, "paras": 3,
                                         "mentions": mentions()}]}
    if with_terms:
        spec["terms"] = terms(extra, ready, unscanned)
    spec.update(kw)
    return spec
