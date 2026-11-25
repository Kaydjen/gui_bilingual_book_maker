"""The disk work of the Books step, run on the worker thread (window_spec 2.3, 4.4, 5.4, 13.5, 13.6).

Every operation runs its steps in a fixed order, so a failure halfway leaves a library that is still valid:
- Add book: check the file, copy it to `books/<name>.part`, rename it to `.epub`; a new series gets its
  series.json LAST, so a broken copy never shows as a volume and a half-made series never shows as a series;
- Remove volume: move the files of the volume into one dated `.deleted` folder, the book file last, then edit
  series.json; a failure moves everything back;
- Delete series: the whole folder moves in one step.

All writes go through `fs`, so a check can make any step fail. An operation raises `OpError` whose text says
what happened and what is where now.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import addbook, libraryrules as rules, model

VOLUME_LABELS = "volume_labels"


class OpError(Exception):
    """A failure with a message for the user."""


class _Fs:
    """The steps that write. A check replaces one of them to make it fail at step k."""

    def copy(self, src, dst):
        shutil.copyfile(src, dst)

    def replace(self, src, dst):
        os.replace(src, dst)

    def makedirs(self, path):
        os.makedirs(path, exist_ok=True)

    def remove_tree(self, path):
        shutil.rmtree(path, ignore_errors=True)

    def remove_file(self, path):
        try:
            os.unlink(path)
        except OSError:
            pass

    def create_series(self, library, name, target, **settings):
        return model.create_series_record(library, name, target, **settings)

    def update_series(self, series_path, fn):
        model.update_series_settings(series_path, fn)


fs = _Fs()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def reason(exc: BaseException) -> str:
    return rules.explain_oserror(exc) if isinstance(exc, OSError) else (str(exc) or type(exc).__name__)


@dataclass
class AddResult:
    kind: str           # created | added | duplicate
    series: str         # series folder
    volume: str         # volume name (file stem)


# ---------------------------------------------------------------- Add book
def _volume_hashes(series_path) -> dict:
    out = {}
    for p in sorted((Path(series_path) / "books").glob("*.epub")):
        try:
            out[p.stem] = sha256_file(p)
        except OSError:
            out[p.stem] = ""
    return out


def _copy_in(src: Path, books: Path, name: str) -> Path:
    part = books / (name + ".part")
    final = books / (name + ".epub")
    try:
        fs.copy(src, part)
        fs.replace(part, final)
    except BaseException:
        fs.remove_file(part)
        raise
    return final


def add_book(library, epub, mode: str, series_path: str | None = None, name: str = "") -> AddResult:
    """Add `epub` as a volume of `series_path` (mode `volume`) or as the first book of a new series called
    `name` (mode `new`). The original file is never touched."""
    src = Path(epub)
    try:
        model.check_epub(src)
    except ValueError as exc:
        raise OpError("%s cannot be added: %s. Nothing was created." % (src.name, exc)) from None
    try:
        new_hash = sha256_file(src)
    except OSError as exc:
        raise OpError("%s cannot be read: %s. Nothing was created." % (src.name, reason(exc))) from None
    lib = Path(library)
    if mode == "volume":
        sp = Path(series_path)
        try:
            plan = addbook.plan_add(src.stem, _volume_hashes(sp), new_hash, model.clean_name)
            if plan.action == "duplicate":
                return AddResult("duplicate", str(sp), plan.name)
            _copy_in(src, sp / "books", plan.name)
        except OSError as exc:
            raise OpError("The book could not be added: %s. The series was not changed." % reason(exc)) from None
        return AddResult("added", str(sp), plan.name)
    # a new series
    infos = model.list_series_task(None, lib)
    problem = addbook.series_name_problem(name, model.clean_name, [Path(i.path).name for i in infos] + _folders(lib),
                                          [i.name for i in infos])
    if problem:
        raise OpError(problem)
    folder = lib / model.clean_name(name.strip(), 80, "series")
    stem = addbook.plan_add(src.stem, {}, new_hash, model.clean_name).name
    try:
        fs.makedirs(folder / "books")
        _copy_in(src, folder / "books", stem)
        fs.create_series(lib, name.strip(), model.TARGETS[0][0], target_chosen=False)     # series.json LAST
    except BaseException as exc:
        fs.remove_tree(folder)
        if isinstance(exc, (OSError, ValueError)):
            raise OpError("The series could not be created: %s. Nothing was left in the library." % reason(exc)) from None
        raise
    return AddResult("created", str(folder), stem)


def _folders(lib: Path) -> list:
    try:
        return [p.name for p in lib.iterdir() if p.is_dir()]
    except OSError:
        return []


# ---------------------------------------------------------------- rename
def rename_series(series_path, new_name: str) -> None:
    """The name shown in the list; the folder keeps its name."""
    new_name = new_name.strip()
    try:
        fs.update_series(series_path, lambda s: s.__setitem__("name", new_name))
    except (OSError, ValueError) as exc:
        raise OpError("The series could not be renamed: %s. Its name did not change." % reason(exc)) from None


def rename_volume(series_path, stem: str, label: str) -> None:
    """The label shown for a volume; the file keeps its name. An empty label brings the file name back."""
    label = label.strip()

    def edit(s):
        labels = dict(s.get(VOLUME_LABELS) or {}) if isinstance(s.get(VOLUME_LABELS), dict) else {}
        if label and label != stem:
            labels[stem] = label
        else:
            labels.pop(stem, None)
        s[VOLUME_LABELS] = labels
    try:
        fs.update_series(series_path, edit)
    except (OSError, ValueError) as exc:
        raise OpError("The volume could not be renamed: %s. Its name did not change." % reason(exc)) from None


# ---------------------------------------------------------------- remove and delete
def delete_series(library, series_path, now: float | None = None) -> Path:
    """Move the whole series folder to <library>/.deleted/<folder>-<stamp> in one step."""
    sp = Path(series_path)
    dest = rules.deleted_series_path(library, sp.name, rules.stamp(now))
    try:
        fs.makedirs(dest.parent)
        fs.replace(sp, dest)
    except OSError as exc:
        raise OpError("The series could not be deleted: %s. It is still in the library, unchanged." % reason(exc)) \
            from None
    return dest


def remove_volume(library, series_path, stem: str, job_book: str | None = None, now: float | None = None) -> Path:
    """Move the files of one volume to <library>/.deleted/<series folder>/<stem>-<stamp>, the book file last,
    then drop its label from series.json. On a failure everything moved so far goes back."""
    sp = Path(series_path)
    items = rules.volume_items(sp, stem, model.clean_name, job_book)
    dest = rules.deleted_volume_path(library, sp.name, stem, rules.stamp(now))
    moved: list[str] = []
    try:
        for rel in items:
            target = dest / rel
            fs.makedirs(target.parent)
            fs.replace(sp / rel, target)
            moved.append(rel)

        def edit(s):
            labels = s.get(VOLUME_LABELS)
            if isinstance(labels, dict) and stem in labels:
                labels = dict(labels)
                labels.pop(stem)
                s[VOLUME_LABELS] = labels
        fs.update_series(sp, edit)
    except (OSError, ValueError) as exc:
        left = []
        for rel in reversed(moved):
            try:
                fs.makedirs((sp / rel).parent)
                fs.replace(dest / rel, sp / rel)
            except OSError:
                left.append(rel)
        if left:
            raise OpError("The volume could not be removed: %s. Some of its files are in %s; the volume is "
                          "still in the series." % (reason(exc), dest)) from None
        fs.remove_tree(dest)
        raise OpError("The volume could not be removed: %s. Nothing was changed; the volume is still in the "
                      "series." % reason(exc)) from None
    return dest
