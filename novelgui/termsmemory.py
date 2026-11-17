"""What the Terms step remembers between sessions (window_spec 10.6): the tab, the type filter, the search text, the
sort and the column widths. Stored under one key of the window state; everything read back is checked, so an old or
hand-edited file never breaks the screen.

Column widths are kept in units of one digit width (VTable.widths_state), so they stay right when the system scale
changes.
"""

from __future__ import annotations

KEY = "terms"
TABS = ("next", "new", "known", "questions")
MIN_UNITS, MAX_UNITS = 5.0, 120.0


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def clean(raw, sort_keys, types) -> dict:
    """The stored dict with only valid parts: tab, type, query, sort ({key, desc}), widths ({column: units})."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    if raw.get("tab") in TABS:
        out["tab"] = raw["tab"]
    if raw.get("type") in types:
        out["type"] = raw["type"]
    if isinstance(raw.get("query"), str) and raw["query"].strip():
        out["query"] = raw["query"][:200]
    s = raw.get("sort")
    if isinstance(s, dict) and s.get("key") in sort_keys and isinstance(s.get("desc"), bool):
        out["sort"] = {"key": s["key"], "desc": s["desc"]}
    w = raw.get("widths")
    if isinstance(w, dict):
        ok = {k: float(v) for k, v in w.items() if isinstance(k, str) and _num(v) and MIN_UNITS <= v <= MAX_UNITS}
        if ok:
            out["widths"] = ok
    return out


def sort_to_store(tab: str, key, desc, default) -> dict | None:
    """The sort to remember: None while it is the default order of the tab (nothing to restore)."""
    if key is None or (key, desc) == tuple(default):
        return None
    return {"key": key, "desc": bool(desc)}
