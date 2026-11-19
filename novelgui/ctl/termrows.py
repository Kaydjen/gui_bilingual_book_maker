"""The Terms screen as plain rows and rules (window_spec 6.1-6.7, 9.12, 14.13): which tab a term belongs to, the order, the
counts, the cells as strings made once, `Confirm N`, the fact line, the language list of the `To` heading.

Pure (no Qt, no core imports): the view-model only turns these tuples into Qt roles. Rows are `facade.terms.TermRow`
(or anything with the same attributes), always keyed by `row.key` (the entry's normalised source), never by `id()`.
A mined name without a rendering is a row with status `suggest` and a key that starts with `?`.
"""

from __future__ import annotations

from ..termlogic import FAR

TABS = ("blocking", "notconf", "confirmed")
TAB_LABELS = {"blocking": "Blocking", "notconf": "Not confirmed", "confirmed": "Confirmed"}
SORTS = ("source", "tr", "type", "gender", "first", "count", "note")
SORT_COLUMNS = {"src": "source", "ren": "tr", "typ": "type", "gen": "gender", "first": "first", "count": "count",
                "about": "note"}
SUGGEST = "suggest"
US = "\x1f"                         # separates the values of a choice inside one cell string

# 14.13: three codes; stored values stay the core's. `plural` is never offered.
GENDER_CODES = (("male", "м", "masculine"), ("female", "ж", "feminine"), ("neuter", "с", "neuter"))
_SHORT = {s: c for s, c, _w in GENDER_CODES}
_STORED = {c: s for s, c, _w in GENDER_CODES}


def gender_short(stored: str) -> str:
    return _SHORT.get(stored, "")


def gender_stored(code: str) -> str:
    return _STORED.get(code, "")


def suggestion_key(text: str) -> str:
    return "?" + " ".join(str(text).lower().split())


def is_suggestion(row) -> bool:
    return row.status == SUGGEST


class Suggestion:
    """A mined name as a row (the same attributes as `TermRow`)."""
    __slots__ = ("key", "source", "tr", "type", "gender", "status", "count", "first", "questions", "forms", "note",
                 "same_as", "choices")

    def __init__(self, text: str, count: int, first: int):
        self.key, self.source, self.tr, self.type, self.gender = suggestion_key(text), text, "", "", ""
        self.status, self.count, self.first = SUGGEST, int(count), int(first)
        self.questions, self.forms, self.note, self.same_as, self.choices = (), (), "", "", ()


# ---------------------------------------------------------------- tabs, filters, order
def in_tab(row, tab: str, blocking) -> bool:
    if tab == "blocking":
        return row.status == "new" and row.key in blocking
    if tab == "notconf":
        return row.status in ("new", SUGGEST) or bool(row.questions)
    return row.status == "confirmed" and not row.questions


def matches(row, q: str) -> bool:
    return (q in row.source.lower() or q in (row.tr or "").lower() or q in (row.note or "").lower()
            or any(q in f.lower() for f in row.forms))


def sort_key(row, key: str):
    if key == "first":
        return (FAR if row.first is None else row.first, -row.count, row.source.lower())
    if key == "count":
        return (row.count, row.source.lower())
    return (str(getattr(row, key, "") or "").lower(), row.source.lower())


def arrange(rows, tab: str, blocking=frozenset(), query: str = "", type_filter: str = "", imported=None,
            keep=frozenset(), key: str = "first", desc: bool = False) -> list:
    """The rows of one tab in order. `keep`: rows whose chip was clicked stay in the list until Confirm or a tab change
    (F6); `imported`: the keys of the last import, or None for no filter."""
    q = query.strip().lower()
    out = []
    for r in rows:
        if not (in_tab(r, tab, blocking) or r.key in keep):
            continue
        if (type_filter and r.type != type_filter) or (imported is not None and r.key not in imported):
            continue
        if q and not matches(r, q):
            continue
        out.append(r)
    out.sort(key=lambda r: sort_key(r, key), reverse=desc)
    return out


def counts(rows, blocking=frozenset(), type_filter: str = "", imported=None) -> dict:
    """The numbers on the tabs: they follow the type filter and the Imported filter, not the search."""
    out = {t: 0 for t in TABS}
    for r in rows:
        if (type_filter and r.type != type_filter) or (imported is not None and r.key not in imported):
            continue
        for t in TABS:
            if in_tab(r, t, blocking):
                out[t] += 1
    return out


def confirmable(rows) -> list:
    """The rows `Confirm N terms` takes: a rendering, no open choice, not yet confirmed, not a mined name."""
    return [r for r in rows if r.status == "new" and r.tr and not r.questions]


def can_merge(rows) -> bool:
    return len(rows) >= 2 and all(r.status != SUGGEST for r in rows)


# ---------------------------------------------------------------- cells
def choice_of(row, field: str) -> tuple:
    """((value, where it comes from), ...) when the row has an open question on `field`, else ()."""
    for f, cands in getattr(row, "choices", ()):
        if f == field and len(cands) > 1:
            return cands
    return ()


def number_text(numbers, first) -> str:
    """The chapter number the user reads for a position (`numbers` = the shown numbers of the book), "" when unknown."""
    if first is None:
        return ""
    return str(numbers[first]) if 0 <= first < len(numbers) else str(first + 1)


def model_row(row, numbers=(), nolang: bool = False) -> tuple:
    """(source, rendering, type, gender, first + count, about, flags): the strings of one table row. A choice is its
    values joined by US. flags: s suggestion, r / g the rendering / gender is a choice, k confirmed."""
    flags = ""
    ren = row.tr
    tr_choice = choice_of(row, "tr")
    if is_suggestion(row):
        flags += "s"
        ren = ""
    elif tr_choice:
        flags += "r"
        ren = US.join(v for v, _w in tr_choice)
    gen = gender_short(row.gender)
    g_choice = choice_of(row, "gender")
    if g_choice:
        flags += "g"
        gen = US.join(gender_short(v) or v for v, _w in g_choice)
    if row.status == "confirmed":
        flags += "k"
    if nolang:
        flags += "n"
    return (row.source, ren, row.type if row.status != SUGGEST else "", gen,
            number_text(numbers, row.first) + US + (str(row.count) if row.count else ""), row.note or "", flags)


# ---------------------------------------------------------------- the floating spot
def plural(n: int, word: str = "term") -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def wait_fact(chapters: str, n: int) -> list:
    """`Chapters 2697-2750 wait for 8 terms` as the parts of a Message line."""
    return [{"text": "Chapters ", "kind": ""}, {"text": chapters, "kind": "n"}, {"text": " wait for ", "kind": ""},
            {"text": plural(n), "kind": "n"}]


def ready_fact(chapters: str) -> list:
    return [{"text": "Chapters ", "kind": ""}, {"text": chapters, "kind": "n"}, {"text": " are ready", "kind": ""}]


def import_fact(stats: dict) -> list:
    """`Imported 214 terms · 213 confirmed · 1 not confirmed · 3 to choose` (the 3 red: a problem to act on)."""
    sep = {"text": " · ", "kind": ""}
    out = [{"text": "Imported ", "kind": ""}, {"text": plural(stats["added"]), "kind": "n"}]
    out += [sep, {"text": str(stats["confirmed"]), "kind": "n"}, {"text": " confirmed", "kind": ""}]
    out += [sep, {"text": str(stats["unconfirmed"]), "kind": "n"}, {"text": " not confirmed", "kind": ""}]
    if stats.get("choices"):
        out += [sep, {"text": str(stats["choices"]), "kind": "red"}, {"text": " to choose", "kind": ""}]
    return out


def importing_fact(names, n: int, total: int) -> list:
    return [{"text": "Importing ", "kind": ""}, {"text": ", ".join(names), "kind": "n"},
            {"text": " · %d of %d" % (n, total), "kind": ""}]


def done_fact(word: str, n: int) -> list:
    return [{"text": word + " ", "kind": ""}, {"text": plural(n), "kind": "n"}]


def saved_fact(name: str) -> list:
    return [{"text": "Saved ", "kind": ""}, {"text": name, "kind": "n"}]


def plan_import(files, base_tr: dict, base_confirmed: int, base_unconfirmed: int) -> dict:
    """What the Import panel shows before it runs. `files` = [(name, terms, {key: rendering}, goes_confirmed)];
    `base_tr` = {key: rendering} of the base. Returns the Confirmed / Not confirmed totals after the import and the
    number of terms that will need a choice."""
    seen = dict(base_tr)
    conf, unconf, choices, total = base_confirmed, base_unconfirmed, 0, 0
    for _name, _n, terms, goes in files:
        for k, tr in terms.items():
            if k not in seen:
                seen[k] = tr
                total += 1
                if goes:
                    conf += 1
                else:
                    unconf += 1
            elif seen[k] != tr:
                choices += 1
    return {"terms": total, "confirmed": conf, "unconfirmed": unconf, "choices": choices}


# ---------------------------------------------------------------- the `To` heading list (3.2, 9.12)
TUNED = (("ru:Russian", "Russian"),)
USABLE = (("uk:Ukrainian", "Ukrainian"), ("pl:Polish", "Polish"))
ENGLISH = ("en:English", "English")
OTHER_LANGS = (("Chinese", "zh"), ("Czech", "cs"), ("Dutch", "nl"), ("English", "en"), ("French", "fr"), ("German", "de"), ("Italian", "it"),
               ("Japanese", "ja"), ("Korean", "ko"), ("Portuguese", "pt"), ("Spanish", "es"), ("Turkish", "tr"),
               ("Vietnamese", "vi"))


def _entry(target: str, name: str, current: str, tag: str = "", off: bool = False, tip: str = "") -> dict:
    e = {"text": name, "id": target, "current": target == current, "off": off}
    if tag:
        e["note"] = tag
    if tip:
        e["tip"] = tip
    return e


def language_entries(query: str, current: str, source_tag: str, locked: bool, english_tip: str, locked_tip: str) -> list:
    """The items of the `To` drop-down: TUNED (Russian), USABLE (Ukrainian, Polish, English dim), OTHER (shipped names with
    their tag, English dim too); the source language is left out of every group; a typed name that is not in the list
    becomes `+ Use <name>` (the first row). While the language is locked every other one is dim (3.6)."""
    raw = (query or "").strip()
    q = raw.lower()
    src = (source_tag or "").lower()
    out: list = []

    def keep(target: str, name: str, tag: str) -> bool:
        return tag.lower() != src and (not q or q in name.lower() or q == tag.lower())

    def one(target, name, tag="", dim=False):
        if not keep(target, name, tag or target.split(":")[0]):
            return None
        off = dim or (locked and target != current)
        return _entry(target, name, current, tag, off, english_tip if dim else (locked_tip if off else ""))

    groups = (("TUNED", [one(t, n) for t, n in TUNED]),
              ("USABLE", [one(t, n) for t, n in USABLE] + [one(ENGLISH[0], ENGLISH[1], dim=True)]),
              ("OTHER", [one("%s:%s" % (tag, name), name, tag, dim=tag == "en") for name, tag in OTHER_LANGS]))
    for title, items in groups:
        items = [i for i in items if i]
        if items:
            out.append({"group": title})
            out += items
    names = {e["text"].lower() for e in out if "text" in e} | {e.get("note", "") for e in out}
    if raw and q not in names and not locked and q != src:
        out.insert(0, {"text": "+ Use " + raw, "id": "use:" + raw})
    return out


# ---------------------------------------------------------------- window memory (10.6)
def clean_memory(raw, types) -> dict:
    """The stored Terms state with only valid parts: tab (blocking | notconf | confirmed), type, query, sort, widths."""
    from ..termsmemory import clean
    out = clean(raw, SORTS, types)
    if isinstance(raw, dict) and raw.get("tab") in TABS:
        out["tab"] = raw["tab"]
    elif "tab" in out:
        out.pop("tab")
    return out


# ---------------------------------------------------------------- what floats at the bottom (6.7, 9.12)
def _verb(text: str, vid: str, kind: str = "main", tip="") -> dict:
    return {"text": text, "id": vid, "kind": kind, "tip": tip}


def float_spec(msg, ticked: int, tab: str, nolang: bool, scanning: bool, percent: float, blocking: int, waits: bool,
               chapters: str, confirm_n: int, searching: bool, has_terms: bool, loading: bool, imported: bool,
               tips: dict) -> dict:
    """The one element at the bottom of the table, as plain data: a message of the last action (it replaces the rest), the
    bar of the ticked rows, `Reading the book · 40 %`, the fact line of the Blocking tab, or `Confirm N terms`.
    kind: "" | message | ticked | scan | blocking | confirm. `fact` = Message parts, `verbs` = bar segments."""
    none = {"kind": "", "fact": [], "verbs": [], "progress": -1}
    if msg:
        return {"kind": "message", "fact": msg["fact"], "verbs": msg.get("verbs", []), "progress": msg.get("progress", -1)}
    if ticked:
        off = "off" if nolang else "main"
        verbs = [_verb("%d selected" % ticked, "", "capt")]
        if tab != "confirmed":
            verbs.append(_verb("Confirm", "confirm", off, tips["nolang"] if nolang else tips["confirmTicked"]))
        verbs += [_verb("Merge", "merge", "" if ticked > 1 else "off", tips["merge"]),
                  _verb("Not a term", "dismiss", "", tips["notATerm"]), _verb("Delete", "delete", "")]
        return {"kind": "ticked", "fact": [], "verbs": verbs, "progress": -1}
    if scanning:
        return {"kind": "scan", "tip": tips["scanning"], "progress": max(0.0, percent / 100.0),
                "fact": [{"text": "Reading the book", "kind": ""}, {"text": " · %d %%" % round(percent), "kind": ""}],
                "verbs": []}
    if loading or not has_terms:
        return none
    can = confirm_n and not searching
    if tab == "blocking":
        if imported:
            return none
        if not blocking:
            return {"kind": "blocking", "fact": ready_fact(chapters),
                    "verbs": [_verb("Translate ›", "translate", "main", tips["goTranslate"])], "progress": -1}
        verbs = [_verb("Confirm %s" % plural(confirm_n), "confirmAll",
                       "off" if nolang else ("accent" if waits else "main"),
                       tips["nolang"] if nolang else tips["confirmN"](confirm_n))] if can else []
        return {"kind": "blocking", "fact": wait_fact(chapters, blocking), "verbs": verbs, "progress": -1}
    if tab != "confirmed" and can:
        return {"kind": "confirm", "fact": [], "progress": -1,
                "verbs": [_verb("Confirm %s" % plural(confirm_n), "confirmAll", "off" if nolang else "main",
                                tips["nolang"] if nolang else tips["confirmN"](confirm_n))]}
    return none
