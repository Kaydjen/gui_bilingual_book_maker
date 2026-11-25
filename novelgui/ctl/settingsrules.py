"""Pure rules of the settings panel (window_spec 11, 11.7): pace, the model list and the add-a-model drop-down, the
saved line, the size of the app data folder. No Qt.
"""

from __future__ import annotations

import os
from pathlib import Path

PACE_MIN, PACE_MAX, PACE_DEFAULT = 1, 120, 5
DEFAULT_MODEL = "gemini-3.1-flash-lite"
RECOMMENDED = (("gemini-3.1-flash-lite", "500 a day"), ("gemini-3.5-flash", "20 a day"))
SAVED = "Saved"
SAVED_RUN = "Saved · applies from the next start"


def clean_pace(text):
    """The pace typed (whole requests a minute), or None when it is not a number from 1 to 120."""
    try:
        value = int(str(text).strip())
    except ValueError:
        return None
    return value if PACE_MIN <= value <= PACE_MAX else None


def pace_unit(text) -> str:
    """The dim part of the pace row, recomputed while typing: `one every 12 s`, `one every 90 s`, `1 to 120`."""
    p = clean_pace(text)
    if p is None:
        return "1 to 120"
    s = 60.0 / p
    return "one every %s s" % (("%d" % s) if abs(s - round(s)) < 0.05 else ("%.1f" % s))


def saved_line(running: bool, extra: str = "") -> str:
    """The foot's dim fact line: `Saved`, during a run `Saved · applies from the next start`; `extra` replaces it
    while a longer fact stands (`2 keys added · checking…`)."""
    return extra or (SAVED_RUN if running else SAVED)


def keys_added_line(n: int) -> str:
    return "%d %s added · checking…" % (n, "key" if n == 1 else "keys")


def stored_models(raw) -> list:
    out = []
    for m in raw if isinstance(raw, list) else []:
        if isinstance(m, str) and m.strip() and m.strip() not in out:
            out.append(m.strip())
    return out or [DEFAULT_MODEL]


def move_model(models, index: int, delta: int) -> list:
    """The list with the model at `index` moved by `delta` (the arrows of a row); unchanged at the ends."""
    j = index + delta
    if not (0 <= index < len(models) and 0 <= j < len(models)):
        return list(models)
    out = list(models)
    out[index], out[j] = out[j], out[index]
    return out


def remove_model(models, index: int) -> list:
    """The last model cannot be removed: a job needs one."""
    if len(models) <= 1 or not (0 <= index < len(models)):
        return list(models)
    return [m for i, m in enumerate(models) if i != index]


def rename_model(models, index: int, name: str) -> list:
    name = name.strip()
    if not name or not (0 <= index < len(models)) or (name in models and models.index(name) != index):
        return list(models)
    out = list(models)
    out[index] = name
    return out


def model_entries(models, google, typed: str = "") -> list:
    """The rows of the add-a-model drop-down (11.7): a first row `+ Add <name>` for a typed name that is in no list,
    the group RECOMMENDED (with the limit per key) and the group FROM GOOGLE (dim); models already in use and names
    that do not match the typed text are left out; an empty group has no heading. Rows: {group} | {text, id, note,
    dim, add}."""
    t = typed.strip().lower()
    have = set(models)
    shown = [m for m, _ in RECOMMENDED] + list(google)
    out: list = []
    if typed.strip() and typed.strip().lower() not in {s.lower() for s in shown} and typed.strip() not in have:
        out.append({"text": "+ Add " + typed.strip(), "id": typed.strip(), "add": True})
    rec = [{"text": m, "id": m, "note": lim} for m, lim in RECOMMENDED if m not in have and t in m.lower()]
    rec_names = {m for m, _ in RECOMMENDED}
    goo = [{"text": m, "id": m, "dim": True} for m in google if m not in have and m not in rec_names and t in m.lower()]
    if rec:
        out.append({"group": "RECOMMENDED"})
        out.extend(rec)
    if goo:
        out.append({"group": "FROM GOOGLE"})
        out.extend(goo)
    return out


def folder_size(path) -> int:
    """Bytes under a folder (0 when it is missing); unreadable entries are skipped."""
    total = 0
    for root, _dirs, files in os.walk(str(path), onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def size_text(n: int) -> str:
    """`0 B`, `12 KB`, `3.4 MB`, `1.2 GB`."""
    if n < 1024:
        return "%d B" % n
    for unit, k in (("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3)):
        if n < k * 1024 or unit == "GB":
            v = n / k
            return ("%d %s" % (round(v), unit)) if v >= 100 or unit == "KB" else ("%.1f %s" % (v, unit))
    return "%d B" % n


def library_label(path) -> str:
    """The name on the Library control: the folder's name."""
    p = Path(str(path)) if path else None
    return (p.name or str(p)) if p else "Not chosen"
