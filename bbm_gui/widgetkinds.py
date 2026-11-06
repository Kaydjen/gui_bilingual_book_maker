"""Rule-based widget inference from an inventory flag record (works on runtime and AST inventories).
Kinds: toggle, toggle_inverted, text, int, float, enum, combo, file, dir, secret, multi,
       optional_value, json, csv, counter."""
import re

SECRET_TOKENS = {"key", "token", "secret", "password", "passwd"}
FILE_TYPE_HINT = re.compile(r"(file|path)", re.I)


def tokens(flag_id):
    return [t for t in re.split(r"[-_]+", flag_id.lstrip("-").lower()) if t]


def infer(f, heur=True):
    """Return (kind, reason). Uses only inventory fields + help text."""
    a, n, t, ch = f["action"], f.get("nargs"), f.get("type"), f.get("choices")
    h = f.get("help") if isinstance(f.get("help"), str) else ""
    tk = tokens(f["id"])
    if a == "store_true" or a == "store_const": return "toggle", "action"
    if a == "store_false": return "toggle_inverted", "action"
    if a == "count": return "counter", "action"
    if a == "help": return "toggle", "help"
    if isinstance(n, int) and n > 1: return "multi", "nargs=%d" % n
    if n in ("*", "+"): return "multi", "nargs=" + n
    if n == "?": return ("optional_value", "nargs=? choices") if ch else ("optional_value", "nargs=?")
    unres = isinstance(ch, (dict, list)) and "$unresolved" in str(ch)
    if ch:
        if unres: return "combo", "unresolved choices (free text allowed)"
        if f.get("choices_open"): return "combo", "open choices"
        return "enum", "choices"
    # free value kinds
    if t == "int": return "int", "type"
    if t == "float": return "float", "type"
    th = f.get("type_hint")      # AST-path stand-in for the runtime probe
    if th in ("int", "float"): return th, "ast validator body"
    if th == "path": return "file", "ast validator body"
    p = f.get("type_probe")
    if p:
        if p.get("int_ok") and not p.get("float_frac_ok") and not p.get("text_ok"): return "int", "probe"
        if p.get("float_frac_ok") and not p.get("text_ok"): return "float", "probe"
        if not p.get("int_ok") and not p.get("float_frac_ok") and t and FILE_TYPE_HINT.search(t): return "file", "type name"
    elif t and t not in ("str",):
        if re.search(r"(file|path)", t): return "file", "type name"
    if not heur: return "text", "structural-default"
    # string kinds: name / help text
    if set(tk) & SECRET_TOKENS: return "secret", "name token"
    if re.search(r"\bJSON object\b", h) or h.lower().startswith("json"): return "json", "help 'JSON object'"
    if tk and tk[-1] in ("file", "path", "name") and "book" in tk: return "file", "name book_name"
    if re.search(r"\ba path to\b|\bpath of\b|\bfile of\b", h): return "file", "help 'path'"
    if re.search(r"comma[- ]separated|use comma|with commas", h, re.I): return "csv", "help 'comma'"
    if re.search(r"example[^.]{0,40}[A-Za-z0-9]+,[A-Za-z0-9]+", h, re.I): return "csv", "help example a,b"
    return "text", "default"


def kind_with_overlay(f, ov):
    k, why = infer(f)
    o = ov.get("flag", {}).get(f["id"], {})
    if "widget" in o: return o["widget"], "overlay"
    return k, why
