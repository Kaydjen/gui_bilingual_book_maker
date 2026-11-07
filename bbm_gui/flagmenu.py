"""What the flag panel and the chip strip show (no widgets): the flags on offer, the chips, and value parsing."""
import json
import math
import re
from typing import NamedTuple, Optional

from . import cmdbuild, flagdocs, flagrules

MENU_ORDER = ("Test and tuning", "Book parts", "Output look", "Connection")
REASON_GROUPS = ("PDF", "Plan mode")
HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
COLOR_NAME = re.compile(r"^[A-Za-z]+$")
VALUE_CUT = 3  # a list value shows this many items on a chip, then "+N"


def ov_of(overlay, fid):
    return (overlay or {}).get("flag", {}).get(fid, {})


def label_of(f, overlay):
    return ov_of(overlay, f["id"]).get("label") or f["id"].lstrip("-")


def offered(f):
    """A flag the user may pick: not hidden, not an alias, not set by the app, not the companion of another flag."""
    return not (f.get("hidden") or f.get("deprecated") or f.get("alias_of") or flagrules.is_owned(f["id"])
                or f["id"] in flagrules.COMPANIONS)


def reason_of(f, overlay):
    ov = ov_of(overlay, f["id"])
    if ov.get("reason"):
        return ov["reason"]
    for rule in (overlay or {}).get("group_rule", []):
        if re.search(rule["match"], f["id"]):
            return rule["group"] if rule["group"] in REASON_GROUPS else ""
    return ""


# ---------------------------------------------------------------------- list
class Row(NamedTuple):
    head: str               # a sub-head when set (then the rest is empty)
    flag: Optional[dict]
    label: str
    line: str
    reason: str


def rows(inv, overlay, show_all=False, query=""):
    """The list of the panel: Common (under sub-heads), More, and, with `show_all` or a search, the rest."""
    needle = (query or "").strip().lower()
    common, more, rest = {}, [], []
    for f in sorted((f for f in (inv or {}).get("flags", []) if offered(f)), key=lambda x: x.get("order", 0)):
        ov = ov_of(overlay, f["id"])
        doc = flagdocs.describe(f, ov)
        row = Row("", f, label_of(f, overlay), doc.about, reason_of(f, overlay))
        if needle and needle not in (row.label + " " + f["id"] + " " + row.line).lower():
            continue
        tier = ov.get("tier")
        if tier == "common":
            common.setdefault(ov.get("menu") or "Other", []).append(row)
        elif tier == "more":
            more.append(row)
        elif show_all or needle:
            rest.append(row)
    out = []
    for name in sorted(common, key=lambda n: (MENU_ORDER.index(n) if n in MENU_ORDER else len(MENU_ORDER), n)):
        out.append(Row(name, None, "", "", ""))
        out += common[name]
    if more:
        out.append(Row("More", None, "", "", ""))
        out += more
    if rest:
        out.append(Row("All flags", None, "", "", ""))
        out += rest
    return out


# ---------------------------------------------------------------------- one flag
class Spec(NamedTuple):
    fid: str
    kind: str            # the command builder's kind
    editor: str          # toggle int float enum csv color text file dir json multi secret combo
    choices: tuple
    lo: Optional[float]
    hi: Optional[float]
    step: float
    suggest: tuple
    placeholder: str
    default: str         # text for "Default ..."
    below: str = ""      # the reason shown in the field when a number is under the range


def _default_text(f, ov):
    if ov.get("default_label"):
        return ov["default_label"]
    d = f.get("default")
    if d is None or d == "" or isinstance(d, bool) or (isinstance(d, int) and d == 0 and f.get("type") == "int"):
        return ""  # (1.0 == True: a float default must not be taken for a switch)
    return str(d)


def spec_of(f, overlay):
    ov = ov_of(overlay, f["id"])
    kind = cmdbuild.kind_of(f, overlay)
    editor = ov.get("editor")
    if not editor:
        editor = {"toggle": "toggle", "toggle_inverted": "toggle", "optional_value": "enum", "enum": "enum",
                  "combo": "combo", "int": "int", "float": "float", "csv": "csv", "file": "file", "dir": "dir",
                  "json": "json", "multi": "multi", "secret": "secret"}.get(kind, "text")
    if ov.get("on_only"):
        editor = "toggle"
    choices = f.get("choices")
    choices = tuple(str(c) for c in choices[:40]) if isinstance(choices, list) else ()
    rng = ov.get("range") or (None, None)
    return Spec(f["id"], kind, editor, choices, rng[0], rng[1], float(ov.get("step") or 1),
                tuple(str(s) for s in ov.get("suggest", ())), ov.get("placeholder", ""), _default_text(f, ov),
                ov.get("below", ""))


def start_value(spec, f):
    """What a newly added flag starts with."""
    if spec.editor == "toggle":
        return False if spec.kind == "toggle_inverted" else True
    if spec.suggest and spec.editor in ("int", "float", "enum"):
        return spec.suggest[0]
    if spec.editor == "enum" and spec.choices:
        return spec.choices[0]
    return ""


def parse_value(spec, text):
    """(status, value, message). status: 'ok', 'empty' (nothing typed yet, nothing changes) or 'bad' (the last valid
    value stays). The message is the range or the reason shown next to the field."""
    t = (text or "").strip()
    if not t:
        return "empty", "", ""
    ed = spec.editor
    if ed in ("int", "float"):
        try:
            v = int(t) if ed == "int" else float(t.replace(",", "."))
        except ValueError:
            return "bad", None, "Whole number" if ed == "int" else "Number"
        if isinstance(v, float) and not math.isfinite(v):
            return "bad", None, "Number"
        if spec.below and spec.lo is not None and v < spec.lo:
            return "bad", None, spec.below
        if (spec.lo is not None and v < spec.lo) or (spec.hi is not None and v > spec.hi):
            return "bad", None, "%s - %s" % (_num(spec.lo), _num(spec.hi))
        return "ok", str(v) if ed == "int" else t.replace(",", "."), ""
    if ed == "csv":
        items = [x.strip() for x in re.split(r"[,\n]", t) if x.strip()]
        return ("ok", ",".join(dict.fromkeys(items)), "") if items else ("empty", "", "")
    if ed == "color":
        if HEX_COLOR.match(t) or COLOR_NAME.match(t):
            return "ok", t, ""
        return "bad", None, "#rrggbb or a name"
    if ed == "json":
        try:
            ok = isinstance(json.loads(t), dict)
        except ValueError:
            ok = False
        return ("ok", t, "") if ok else ("bad", None, "JSON object")
    if ed == "multi":
        return "ok", cmdbuild.split_extra(t), ""
    return "ok", t, ""


def _num(v):
    return "%g" % v if v is not None else "…"


def initial_text(value):
    if isinstance(value, list):
        return " ".join(value)
    return "" if value in (None, True, False) else str(value)


# ---------------------------------------------------------------------- chips
class Chip(NamedTuple):
    fid: str
    text: str
    origin: str   # preset, user or bad (a flag this engine does not have)


def active(kind, value):
    """Does the value switch the flag on? (A toggle holds True; an inverted one holds False when it is emitted.)"""
    if kind == "toggle_inverted":
        return value is False
    if kind == "toggle":
        return bool(value)
    return not (value is None or value is False or value == "" or value == [])


def value_text(spec, value):
    if spec.editor == "toggle" or value is True:
        return ""
    if isinstance(value, list):
        value = " ".join(value)
    value = str(value)
    if spec.editor == "csv":
        items = [x for x in value.split(",") if x]
        head = ",".join(items[:VALUE_CUT])
        return head + (" +%d" % (len(items) - VALUE_CUT) if len(items) > VALUE_CUT else "")
    return value if len(value) <= 24 else value[:23] + "…"


def chips(state, inv, overlay, editing=None):
    """Chips for every flag in effect, in the engine's order. `editing` keeps an empty chip while it is being filled."""
    byid = {f["id"]: f for f in (inv or {}).get("flags", [])}
    if not byid:
        return []
    eff = state.effective()
    known, other = [], []
    for fid, value in eff.items():
        if flagrules.is_owned(fid) or fid in flagrules.COMPANIONS:
            continue
        f = byid.get(fid)
        origin = "user" if state.origin(fid) == "user" else "preset"
        if f is None:
            other.append(Chip(fid, fid + (" " + initial_text(value) if initial_text(value) else ""), "bad"))
            continue
        spec = spec_of(f, overlay)
        if not active(spec.kind, value) and fid != editing:
            continue
        label = label_of(f, overlay)
        shown = value_text(spec, value)
        known.append((f.get("order", 0), Chip(fid, label + (" " + shown if shown else ""), origin)))
    known.sort(key=lambda t: t[0])
    return [c for _, c in known] + other
