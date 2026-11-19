"""Add book as plain data (window_spec 5.1-5.4, 9.11, 13.5, 14.7): the series guessed from a file name, the rows of the
panel, the checks run off the GUI thread (readable, protected, already in the library) and the copy itself.

No Qt. `prepare_task` and `add_task` take a lane context first (`breathe()` in their loops) and plain data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from .. import libraryops as ops, protected
from ..facade import books as fbooks
from ..libraryrules import natural_key

_TAIL = re.compile(r"[\s_.,:;\-–—]*(?:book|vol(?:ume)?\.?|part|pt\.?|v|том|книга|часть)?[\s._-]*\d+\s*$", re.I)
_NOISE = re.compile(r"[\s_]+")


def guess_series(stem: str, names) -> tuple:
    """(series name, matched) for a file stem: the stem without its book number; `matched` is the display name of an
    existing series when one fits (the same name, or a series name that starts the stem at a word edge)."""
    base = _NOISE.sub(" ", stem).strip()
    cut = _TAIL.sub("", base).strip(" -–—_.,:;") or base
    by_lower = {n.lower(): n for n in names}
    for cand in (base, cut):
        if cand.lower() in by_lower:
            return by_lower[cand.lower()], True
    starts = [n for n in names if cut.lower().startswith(n.lower() + " ") or cut.lower().startswith(n.lower() + "-")]
    if len(starts) == 1:
        return starts[0], True
    return cut, False


@dataclass(frozen=True)
class AddRow:
    path: str
    name: str                   # the file name shown
    series: str = ""            # the series box: a display name of the library or a new name
    new: bool = False           # the name is not in the library: a new series
    label: str = ""             # the label the file will really get (`Book 3`)
    state: str = "ok"           # ok | protected | unreadable | checking
    note: str = ""              # shown in the third column when it is not the label (`protected`, the reason)
    update: bool = False        # looks like a newer version of a book (14.3; not built yet)
    stem: str = ""

    @property
    def addable(self) -> bool:
        return self.state == "ok"


def make_rows(files, infos) -> list:
    """Rows for the checked files (`files`: dicts of `prepare_task`); labels are assigned over all of them."""
    names = [i.name for i in infos if not i.broken]
    rows = []
    for f in files:
        series, matched = guess_series(Path(f["path"]).stem, names)
        rows.append(AddRow(f["path"], Path(f["path"]).name, series, not matched, "", f["state"], f.get("note", ""),
                           False, Path(f["path"]).stem))
    return assign_labels(rows, infos)


def assign_labels(rows, infos) -> list:
    """The label of every addable row by the natural order of the file names of its series (new rows of one new series
    follow each other: Book 1, Book 2)."""
    by_name = {i.name.lower(): i for i in infos if not i.broken}
    groups: dict = {}
    for r in rows:
        if r.addable:
            groups.setdefault(r.series.strip().lower(), []).append(r)
    out = {}
    for key, members in groups.items():
        info = by_name.get(key)
        existing = list(info.books) if info is not None else []
        added = sorted({m.stem for m in members}, key=natural_key)
        order = sorted(set(existing) | set(added), key=natural_key)
        for m in members:
            out[id(m)] = "Book %d" % (order.index(m.stem) + 1)
    return [replace(r, label=out.get(id(r), ""), new=_is_new(r, by_name)) for r in rows]


def _is_new(row, by_name) -> bool:
    return row.series.strip().lower() not in by_name


def title_for(count: int) -> str:
    return "Add book" if count == 1 else "Add %d books" % count


def action_text(rows) -> str:
    n = sum(1 for r in rows if r.addable and r.series.strip())
    return "Add book" if n == 1 else "Add %d books" % n


def series_entries(infos, typed: str, current_new: str = "") -> list:
    """The drop-down of a row: a typed new name first as `+ New series <name>`, then the series of the library that match
    what is typed, with their book counts (5.3)."""
    t = typed.strip()
    out = []
    names = [i for i in infos if not i.broken]
    first = t or current_new.strip()
    if first and first.lower() not in {i.name.lower() for i in names}:
        out.append({"text": "+ New series %s" % first, "id": first})
    for i in names:
        if not t or t.lower() in i.name.lower():
            n = len(i.books)
            out.append({"text": i.name, "id": i.name, "note": "%d %s" % (n, "book" if n == 1 else "books")})
    # an exact name goes first: Enter in the drop-down takes the first entry
    out.sort(key=lambda e: 0 if t and e["id"].lower() == t.lower() else 1)
    return out


# ---------------------------------------------------------------- off the GUI thread
_hash_cache: dict = {}


def _sha(path) -> str:
    p = Path(path)
    key = (str(p), p.stat().st_size, p.stat().st_mtime_ns)
    if key not in _hash_cache:
        _hash_cache[key] = ops.sha256_file(p)
    return _hash_cache[key]


def library_hashes(ctx, library) -> dict:
    """{hash: (series path, stem)} of every book of the library (cached by size and mtime)."""
    out = {}
    root = Path(library)
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return out
    for f in folders:
        for b in sorted((f / "books").glob("*.epub")):
            try:
                out.setdefault(_sha(b), (str(f), b.stem))
            except OSError:
                continue
            if ctx is not None:
                ctx.breathe()
    return out


def check_file(path) -> tuple:
    """(state, note): `ok`, `protected`, or `unreadable` with the reason in plain words."""
    p = Path(path)
    if not p.is_file():
        return "unreadable", "the file is gone"
    try:
        fbooks.check_epub(p)
    except ValueError as exc:
        return "unreadable", str(exc)
    try:
        if protected.is_protected(p):
            return "protected", "protected"
    except Exception:
        return "unreadable", "it cannot be read as an EPUB"
    return "ok", ""


def prepare_task(ctx, library, paths) -> list:
    """The files the user gave, checked: readable (the core's reader), protected, already in the library (hash compared
    with every book BEFORE the panel, 4.7). Returns dicts {path, state, note, dup: (series path, stem) | None}."""
    hashes = None
    out = []
    for path in paths:
        if ctx.cancelled:
            break
        state, note = check_file(path)
        dup = None
        if state == "ok":
            if hashes is None:
                hashes = library_hashes(ctx, library)
            dup = hashes.get(_sha(path))
        out.append({"path": str(path), "state": state, "note": note, "dup": dup})
        ctx.breathe()
    return out


def add_task(ctx, library, items) -> list:
    """Copy the files in. `items`: dicts {path, series (display name), new (bool)}. Several files of one new series: the
    first creates it, the others join it. Returns one dict per item: {path, ok, kind, series, volume, error}."""
    created: dict = {}
    out = []
    for it in items:
        if ctx.cancelled:
            break
        name = it["series"].strip()
        res = {"path": it["path"], "ok": False, "kind": "", "series": "", "volume": "", "error": ""}
        try:
            infos = fbooks.list_series_task(None, library)
            known = {i.name.lower(): i for i in infos if not i.broken}
            target = created.get(name.lower()) or (known[name.lower()].path if name.lower() in known else "")
            if target:
                r = ops.add_book(library, it["path"], "volume", target)
            else:
                r = ops.add_book(library, it["path"], "new", name=name)
                created[name.lower()] = r.series
            res.update(ok=True, kind=r.kind, series=r.series, volume=r.volume)
        except ops.OpError as exc:
            res["error"] = str(exc)
        except Exception as exc:                # an unexpected failure is reported, the rest goes on
            res["error"] = "%s cannot be added: %s." % (Path(it["path"]).name, ops.reason(exc))
        out.append(res)
        ctx.emit(res)
        ctx.breathe()
    return out


def summary(results, skipped_protected) -> str:
    """The sentence of the message after Add: what was added, and (14.7) the protected files that were left out."""
    done = [r for r in results if r["ok"] and r["kind"] != "duplicate"]
    parts = []
    if len(done) == 1:
        r = done[0]
        parts.append("Added %s" % r["volume"])
    elif done:
        parts.append("Added %d books" % len(done))
    if skipped_protected:
        parts.append("Protected files were not added: %s. Use a copy without protection." % ", ".join(skipped_protected))
    return " · ".join(parts)
