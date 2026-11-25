"""Pure rules of the library folder (window_spec 2.2, 2.3, 4.3, 4.4, 13.6): which folder becomes the library,
the write probe, `.deleted` names, the files of a volume, natural sort. No Tk and no core imports; the few
functions that touch the disk use only the standard library and take the paths as arguments.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import chapterlogic as cl

DELETED = ".deleted"
LIBRARY_NAME = "Novel library"
PROBE_NAME = ".novel-write-probe"
SERIES_FILE = "series.json"


# ---------------------------------------------------------------- natural sort
_DIGITS = re.compile(r"(\d+)")


def natural_key(text: str) -> tuple:
    """Sort key where numbers compare as numbers: `Vol 2` before `Vol 10`."""
    parts = _DIGITS.split(str(text))
    return tuple(int(p) if i % 2 else p.lower() for i, p in enumerate(parts)) + (str(text),)


# ---------------------------------------------------------------- first start and folder choice
def default_library_path(home) -> Path:
    """`Novel library` in Documents when the user has one, else in the home folder."""
    home = Path(home)
    docs = home / "Documents"
    return (docs if docs.is_dir() else home) / LIBRARY_NAME


def chooser_start(library, home) -> str:
    """Where the folder chooser opens: the parent of the current library, else of the default one."""
    if library:
        return str(Path(library).parent)
    return str(default_library_path(home).parent)


@dataclass(frozen=True)
class FolderScan:
    kind: str                   # series | library | epubs | new | invalid
    library: Path               # the folder that becomes the library
    series: Path | None = None  # the folder to select afterwards (kind series)
    epubs: tuple = ()           # the loose .epub files found (kind epubs)


def scan_folder(path) -> FolderScan:
    """What a chosen folder is (2.2): a series itself (its parent becomes the library and it is selected), a
    folder of loose EPUB files with no series (offer to add them), a library, or a new / empty folder."""
    p = Path(path)
    if not p.exists():
        return FolderScan("new", p)
    if not p.is_dir():
        return FolderScan("invalid", p)
    if (p / SERIES_FILE).is_file():
        return FolderScan("series", p.parent, p)
    try:
        children = sorted(p.iterdir(), key=lambda c: natural_key(c.name))
    except OSError:
        return FolderScan("invalid", p)
    for c in children:
        if c.is_dir() and not c.name.startswith(".") and (c / SERIES_FILE).is_file():
            return FolderScan("library", p)
    epubs = tuple(c for c in children if c.is_file() and c.suffix.lower() == ".epub")
    if epubs:
        return FolderScan("epubs", p, epubs=epubs)
    return FolderScan("library", p)


def explain_oserror(exc: BaseException) -> str:
    """A write failure in plain words."""
    if isinstance(exc, PermissionError):
        return "there is no permission to write there"
    if isinstance(exc, FileNotFoundError):
        return "the folder or the drive does not exist"
    if isinstance(exc, NotADirectoryError):
        return "a part of the path is a file, not a folder"
    if isinstance(exc, FileExistsError):
        return "a file with this name is in the way"
    text = getattr(exc, "strerror", None) or str(exc)
    return text[:1].lower() + text[1:] if text else "unknown error"


def probe_folder(path) -> str:
    """Write and delete a small file in the folder. Returns "" when it works, else the reason in plain words
    (the folder must exist)."""
    p = Path(path)
    if p.exists() and not p.is_dir():
        return "the path is a file, not a folder"
    probe = p / PROBE_NAME
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return explain_oserror(exc)
    return ""


def prepare_library(path) -> tuple[bool, str]:
    """Create the folder when it is new and probe it. Returns (created_now, problem); a folder this call
    created is removed again when it cannot be used."""
    p = Path(path)
    created = False
    if not p.exists():
        try:
            p.mkdir(parents=True)
        except OSError as exc:
            return False, explain_oserror(exc)
        created = True
    problem = probe_folder(p)
    if problem and created:
        try:
            p.rmdir()
        except OSError:
            pass
        created = False
    return created, problem


# ---------------------------------------------------------------- .deleted
def stamp(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(time.time() if now is None else now))


def free_name(parent, name: str, exists=os.path.exists) -> str:
    """`name`, or `name (2)`, `name (3)` when taken."""
    n = 1
    cand = name
    while exists(Path(parent) / cand):
        n += 1
        cand = "%s (%d)" % (name, n)
    return cand


def deleted_series_path(library, folder: str, when: str, exists=os.path.exists) -> Path:
    """<library>/.deleted/<folder>-<stamp> for a deleted series."""
    base = Path(library) / DELETED
    return base / free_name(base, "%s-%s" % (folder, when), exists)


def deleted_volume_path(library, series_folder: str, stem: str, when: str, exists=os.path.exists) -> Path:
    """<library>/.deleted/<series folder>/<stem>-<stamp> for a removed volume."""
    base = Path(library) / DELETED / series_folder
    return base / free_name(base, "%s-%s" % (stem, when), exists)


# ---------------------------------------------------------------- the files of a volume
def volume_items(series_path, stem: str, clean, job_book: str | None = None, exists=os.path.exists) -> list[str]:
    """Paths, relative to the series folder and with `/`, that belong to one volume, in the order they are
    moved: samples, chapter logs, the `.state` files of the stem, and the book file LAST (a volume exists
    as long as its .epub is in books/). Only what exists is listed."""
    s = Path(series_path)
    c = clean(stem, 80, "book")
    rel = [
        "samples/" + c,
        "chapters/" + c,
        ".state/frontier_%s.json" % c,
        ".state/frontier_chunks_%s.json" % c,
        ".state/check_%s.json" % c,
        ".state/" + cl.cache_path(s, stem).name,
        ".state/ignore_%s.json" % c,
    ]
    if job_book is not None and job_book in (stem, c):
        rel.append(".state/job.json")
    rel.append("books/%s.epub" % stem)
    seen: set[str] = set()
    out = []
    for r in rel:
        if r not in seen and exists(s / r):
            seen.add(r)
            out.append(r)
    return out
