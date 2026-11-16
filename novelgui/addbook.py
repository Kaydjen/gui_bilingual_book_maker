"""Pure rules of Add book (window_spec 5.4, 13.5): the final volume name, the duplicate rule, and the checks of
a series name. No Tk, no core imports; the core's name cleaning is passed in as `clean`."""

from __future__ import annotations

from dataclasses import dataclass

MAX_NAME = 80           # the core cuts every file name part of a book to this many characters


@dataclass(frozen=True)
class AddPlan:
    action: str         # copy | duplicate
    name: str           # the volume name (file stem): where the copy goes, or the volume that already has the file


def volume_name(stem: str, n: int, clean) -> str:
    """The final name of the n-th try: `stem`, `stem (2)`, ... cut so the whole name stays within the 80
    characters the core keeps (a longer name would be cut again by the core and could meet another volume)."""
    if n <= 1:
        return clean(stem, MAX_NAME, "book")
    suffix = " (%d)" % n
    return clean(stem, MAX_NAME - len(suffix), "book") + suffix


def plan_add(stem: str, existing: dict, new_hash: str, clean) -> AddPlan:
    """What to do with a file called `stem` whose content hash is `new_hash`, in a series whose volumes are
    `existing` ({name: content hash}). The same name with the same content is a duplicate: nothing is copied.
    The same name with other content goes to `name (2)` (then `(3)` ...), unless that holds the same content."""
    taken = {k.lower(): (k, v) for k, v in existing.items()}
    n = 1
    while True:
        name = volume_name(stem, n, clean)
        hit = taken.get(name.lower())
        if hit is None:
            return AddPlan("copy", name)
        if hit[1] == new_hash:
            return AddPlan("duplicate", hit[0])
        n += 1


def series_name_problem(name: str, clean, folders, displays) -> str:
    """Why a new series cannot be called `name` ("" when it can): its folder exists already (the core would
    merge into it) or another series shows the same name. `folders` and `displays` are the names in use."""
    name = name.strip()
    if not name:
        return "Enter a name."
    folder = clean(name, MAX_NAME, "series").lower()
    if folder in {f.lower() for f in folders}:
        return "A folder with this name is already in the library."
    if name.lower() in {d.lower() for d in displays}:
        return "Another series already has this name."
    return ""


def rename_problem(name: str, own: str, others) -> str:
    """Why the series at `own` cannot be shown as `name`; `others` is a list of (path, display name)."""
    name = name.strip()
    if not name:
        return "Enter a name."
    for path, display in others:
        if path != own and display.lower() == name.lower():
            return "Another series already has this name."
    return ""
