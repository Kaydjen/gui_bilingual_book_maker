"""The term base and the terms frontier: plain functions over the core (no Qt, no Tk).

Two ways of holding a base live here. `TermsDoc` is the base of the Tk window (mutated on its thread). The new
window keeps ONE `TermStore` per series on the data lane: rows leave it as frozen `TermRow` snapshots keyed by the
entry key (the core's `norm_key` of the source, stable across threads and processes), edits arrive as commands.
Heavy reading of the book (`term_scan_task`) works on a SNAPSHOT file of terms.json and returns
{entry_key: [[chapter, hits], ...]}; the owner applies it to the live base.
"""

from __future__ import annotations

import difflib
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from novelcore import Series
from novelcore import frontier as core_frontier
from novelcore.termmatch import Matcher, scan_book
from novelcore.terms import FILE_NAME as TERMS_FILE
from novelcore.terms import TYPES, TermBase, import_glossary, norm_key

from .books import book_file, open_book

GENDERS = ("male", "female", "neuter", "plural", "unknown")


# ---------------------------------------------------------------- terms
class TermsDoc:
    """The term base of one series with saving after every change."""

    def __init__(self, series_path, tag: str):
        self.series_path = Path(series_path)
        self.path = self.series_path / TERMS_FILE
        self.tag = tag
        self.base = TermBase.load(self.path, tag)
        self.save_ms = 0.0
        self.saves = 0

    def entries(self) -> list:
        return self.base.sorted_entries()

    def save(self) -> None:
        t0 = time.perf_counter()
        self.base.save()
        self.save_ms = (time.perf_counter() - t0) * 1000
        self.saves += 1

    # -- single changes ----------------------------------------------------
    def set_field(self, entry, field: str, value: str) -> bool:
        """The user typed or chose a value: the field is kept against model passes, its question is closed,
        the entry's status is left as it is. Returns True when something changed."""
        value = str(value).strip()
        had_q = field in entry.questions
        old = getattr(entry, field)
        if old == value and not had_q:
            return False
        if field == "type" and value not in TYPES:
            return False
        if field == "gender" and value not in GENDERS:
            return False
        setattr(entry, field, value)
        entry.questions.pop(field, None)
        entry.locked.add(field)
        self.base._touch(entry)
        self.save()
        return True

    def answer_same_as(self, entry, value: str) -> None:
        self.base.answer(entry, "same_as", value)
        self.save()

    def confirm(self, entries) -> None:
        for e in entries:
            self.base.confirm(e)
        self.save()

    def unconfirm(self, entries) -> None:
        for e in entries:
            e.status = "new"
            self.base._touch(e)
        self.save()

    def keep(self, entries, field: str) -> None:
        """Quick answer of a question: keep the value in use."""
        for e in entries:
            if field in e.questions:
                value = {"gender": e.gender, "tr": e.tr, "same_as": e.same_as}[field]
                self.base.answer(e, field, value)
        self.save()

    def delete(self, entries) -> list:
        gone = []
        for e in entries:
            if self.base.delete(e.source):
                gone.append(e)
        self.save()
        return gone

    def restore(self, gone) -> list:
        back = []
        for e in gone:
            try:
                back.append(self.base.add(
                    e.source, status=e.status, forms=e.forms, type=e.type, gender=e.gender, tr=e.tr, note=e.note,
                    hint=e.hint, same_as=e.same_as, seen=e.seen, count=e.count, evidence=e.evidence,
                    changed=e.changed, questions=e.questions, locked=e.locked, extra=e.extra))
            except ValueError:
                continue
        self.save()
        return back

    def merge(self, keep, others) -> object:
        for o in others:
            self.base.merge(keep.source, o.source)
        self.save()
        return keep

    def similar(self, entry, n: int = 10) -> list:
        key = entry.source.lower()
        others = [e for e in self.base.sorted_entries() if e is not entry]
        others.sort(key=lambda e: -difflib.SequenceMatcher(None, key, e.source.lower()).ratio())
        return others[:n]

    # -- files ---------------------------------------------------------------
    def import_files(self, files):
        rep = import_glossary(self.base, [Path(f) for f in files])
        self.save()
        return rep

    def export_file(self, path) -> None:
        self.base.save(path)


def load_terms_task(ctx, series_path, tag: str) -> TermsDoc:
    return TermsDoc(series_path, tag)


def fill_seen_task(ctx, doc: TermsDoc, series_path, book_name: str) -> int:
    """After a glossary import: read the open book and note, for every term of the base, how often and in which
    chapters it occurs (the core's scan_book fills `seen` and `count`), then save the base. Returns the number of
    chapters read. Raises what reading the book raises (the window shows it)."""
    book = open_book(book_file(series_path, book_name))
    for attempt in range(3):
        try:
            rep = scan_book(doc.base, book)
            break
        except RuntimeError:        # the base changed under the scan: try again
            time.sleep(0.05)
    else:
        return 0
    doc.save()
    return int(rep.get("chapters", 0))


def terms_in_selection_task(ctx, doc: TermsDoc, series_path, book_name: str, indices) -> set:
    """Ids of the entries that are found in the selected chapters."""
    if not indices:
        return set()
    book = open_book(book_file(series_path, book_name))
    for attempt in range(3):
        try:
            matcher = Matcher(doc.base)
            found: set[int] = set()
            for i in indices:
                if ctx.cancelled:
                    return found
                ch = book.chapters[i]
                if ch.is_toc:
                    continue
                for e in matcher.scan_chapter(book.blocks(ch)):
                    found.add(id(e))
            return found
        except RuntimeError:        # the base changed under the scan: try again
            time.sleep(0.05)
    return set()


def terms_blocking_task(ctx, series_path, book: str, chapter: int) -> int:
    """Unreviewed terms that hold back one chapter now (from the cached scan of the whole book)."""
    series = Series.open(series_path)
    use = gate_candidates()
    fr = core_frontier.Frontier.for_series(series, book)
    fr.scan(cancel=lambda: ctx.cancelled, mine=use)
    return fr.check_chapter(chapter, candidates=use)


# ---------------------------------------------------------------- the terms frontier
def make_frontier(doc: "TermsDoc", series_path, book: str):
    """The whole-book frontier over the base of the terms screen (shared, so a change shows at once)."""
    return core_frontier.Frontier(doc.base, book_file(series_path, book), Path(series_path) / ".state",
                                  book_name=book)


def frontier_scan_task(ctx, fr, force: bool = False):
    """Scan the book (cached under .state); emits (done, total). Cancelled with the token."""
    fr.scan(progress=lambda d, t: ctx.emit((d, t)), cancel=lambda: ctx.cancelled, force=force)
    return fr


def frontier_ready(fr) -> bool:
    return fr is not None and fr._d is not None


def gate_candidates() -> bool:
    """Whether mined names hold a job back (the core decides; read live)."""
    return bool(core_frontier.GATE_CANDIDATES)


def next_items(fr, indices) -> list:
    """Unreviewed items of the chapters: objects with text, kind, count, first, candidate, blocking.
    Blocking items first (frontier order: first chapter, then count), then the suggestions. Candidates are mined
    names that are not in the base; they block only while the core gates on them."""
    acc: dict = {}
    for c in sorted(indices):
        for it in fr.unreviewed(c, candidates=True):
            key = (it.kind == core_frontier.KIND_CANDIDATE, it.text.lower())
            a = acc.get(key)
            if a is None:
                acc[key] = [it.text, it.kind, it.count, c]
            else:
                a[2] += it.count
    gate = gate_candidates()
    out = [SimpleNamespace(text=a[0], kind=a[1], count=a[2], first=a[3],
                           candidate=a[1] == core_frontier.KIND_CANDIDATE,
                           blocking=gate or a[1] != core_frontier.KIND_CANDIDATE) for a in acc.values()]
    out.sort(key=lambda it: (not it.blocking, it.first, -it.count, it.text.lower()))
    return out


def first_blocked(fr, indices) -> bool:
    """True when the first chapter of the selection has an unreviewed item that holds the job back (the
    translation cannot start at all). Needs a scanned frontier."""
    idx = sorted(indices)
    if not idx or not frontier_ready(fr):
        return False
    gate = gate_candidates()
    return any(gate or it.kind != core_frontier.KIND_CANDIDATE for it in fr.unreviewed(idx[0], candidates=True))


def blocked_at(fr, indices, translated=lambda i: False):
    """The first chapter of the selection that an unreviewed item holds back (the run translates the chapters
    before it and then stops), or None. A chapter that is translated completely never blocks. Needs a scanned
    frontier."""
    if not frontier_ready(fr):
        return None
    gate = gate_candidates()
    for c in sorted(indices):
        if translated(c):
            continue
        if any(gate or it.kind != core_frontier.KIND_CANDIDATE for it in fr.unreviewed(c, candidates=True)):
            return c
    return None


def chapter_unreviewed(fr, chapter: int):
    """Unreviewed items that hold back one chapter, or None while the frontier is not scanned."""
    if not frontier_ready(fr):
        return None
    gate = gate_candidates()
    return sum(1 for it in fr.unreviewed(chapter, candidates=True) if gate or it.kind != core_frontier.KIND_CANDIDATE)


def _doc_add_confirmed(self, source: str, tr: str, count: int = 0, first=None):
    """A mined candidate the user translated: becomes a confirmed entry."""
    e = self.base.add(source, status="confirmed", tr=str(tr).strip(), count=count,
                      seen={first} if first is not None else None)
    self.save()
    return e


TermsDoc.add_confirmed = _doc_add_confirmed


def new_candidate(text: str, count: int, first: int):
    """A row for a mined name that is not in the base (shown with an empty translation)."""
    from novelcore.terms import Entry
    e = Entry(text, status="new", tr="", count=count, seen={first})
    e.cand = True
    e.suggest = False
    return e



# ---------------------------------------------------------------- the new window: one owner, plain rows
def entry_key(entry) -> str:
    """The stable id of an entry: the core's comparison key of its source (never `id(entry)`)."""
    return norm_key(entry.source)


@dataclass(frozen=True)
class TermRow:
    """One entry as a screen sees it: immutable, keyed by `key`."""
    key: str
    source: str
    tr: str
    type: str
    gender: str
    status: str
    count: int
    first: int | None           # first chapter it was seen in
    questions: tuple            # fields with an open question
    forms: tuple
    note: str
    same_as: str


def row_of(e) -> TermRow:
    return TermRow(entry_key(e), e.source, e.tr, e.type, e.gender, e.status, e.count,
                   min(e.seen) if e.seen else None, tuple(sorted(e.questions)), tuple(e.forms), e.note, e.same_as)


@dataclass(frozen=True)
class TermCommand:
    """An edit of the term base. `op`: set_field | confirm | unconfirm | delete | keep."""
    op: str
    keys: tuple
    field: str = ""
    value: str = ""


@dataclass(frozen=True)
class CommandResult:
    rows: tuple = ()            # rows as they are now (changed or untouched: the truth for an optimistic screen)
    removed: tuple = ()         # keys that are gone
    error: str = ""             # why the command was refused ("" = applied)


class TermStore:
    """The live term base of one series. Lives on the data lane: every method runs on that thread only."""

    def __init__(self, series_path, tag: str):
        self.series_path = Path(series_path)
        self.path = self.series_path / TERMS_FILE
        self.tag = tag
        self.base = TermBase.load(self.path, tag)
        self.dirty = False
        self.saves = 0

    def _entry(self, key: str):
        table = getattr(self.base, "_entries", None)
        if isinstance(table, dict):
            return table.get(key)
        return next((e for e in self.base if entry_key(e) == key), None)

    def rows(self, breathe=None) -> tuple:
        out = []
        for e in self.base.sorted_entries():
            out.append(row_of(e))
            if breathe is not None:
                breathe()
        return tuple(out)

    def row(self, key: str) -> TermRow | None:
        e = self._entry(key)
        return row_of(e) if e is not None else None

    def apply(self, cmd: TermCommand) -> CommandResult:
        entries = [self._entry(k) for k in cmd.keys]
        missing = tuple(k for k, e in zip(cmd.keys, entries) if e is None)
        entries = [e for e in entries if e is not None]
        if not entries:
            return CommandResult((), missing, "The term is gone.")
        base = self.base
        if cmd.op == "set_field":
            value = str(cmd.value).strip()
            if cmd.field not in ("tr", "type", "gender", "note", "same_as"):
                return CommandResult(tuple(row_of(e) for e in entries), missing, "This field cannot be changed.")
            if (cmd.field == "type" and value not in TYPES) or (cmd.field == "gender" and value not in GENDERS):
                return CommandResult(tuple(row_of(e) for e in entries), missing, "Not a valid value.")
            for e in entries:
                if getattr(e, cmd.field) == value and cmd.field not in e.questions:
                    continue
                setattr(e, cmd.field, value)
                e.questions.pop(cmd.field, None)
                e.locked.add(cmd.field)
                base._touch(e)
                self.dirty = True
        elif cmd.op == "confirm":
            for e in entries:
                base.confirm(e)
            self.dirty = True
        elif cmd.op == "unconfirm":
            for e in entries:
                e.status = "new"
                base._touch(e)
            self.dirty = True
        elif cmd.op == "keep":
            for e in entries:
                if cmd.field in e.questions:
                    base.answer(e, cmd.field, {"gender": e.gender, "tr": e.tr, "same_as": e.same_as}[cmd.field])
            self.dirty = True
        elif cmd.op == "delete":
            gone = tuple(entry_key(e) for e in entries if base.delete(e.source))
            self.dirty = self.dirty or bool(gone)
            return CommandResult((), missing + gone)
        else:
            return CommandResult((), missing, "Unknown command.")
        return CommandResult(tuple(row_of(e) for e in entries), missing)

    def save(self) -> bool:
        """Write terms.json (the core's atomic save) when something changed. True when it wrote."""
        if not self.dirty:
            return False
        self.base.save()
        self.dirty = False
        self.saves += 1
        return True

    def snapshot(self, path) -> str:
        """Write the base as it is now to `path` (for the helper process); returns the path."""
        self.base.save(Path(path))
        return str(path)

    def apply_scan(self, found: dict) -> int:
        """Apply a `term_scan_task` result ({key: [[chapter, hits], ...]}): `seen` and `count` grow. Returns how
        many entries changed; an entry deleted since the snapshot is skipped."""
        n = 0
        for key, pairs in found.items():
            e = self._entry(key)
            if e is None:
                continue
            changed = False
            for ch, hits in pairs:
                changed = self.base.record_seen(e, int(ch), int(hits)) or changed
            if changed:
                n += 1
        if n:
            self.dirty = True
        return n


def term_scan_task(ctx, snapshot_path, tag: str, series_path, book_name: str, chapters=None) -> dict:
    """Read a book against a SNAPSHOT of the term base: {entry_key: [[chapter, hits], ...]}. Nothing is written;
    the owner of the base applies the result (`TermStore.apply_scan`). `chapters`: positions to read (None = all
    but contents pages). Emits ("scan", done, total)."""
    base = TermBase.load(Path(snapshot_path), tag)
    matcher = Matcher(base)
    book = open_book(book_file(series_path, book_name))
    chs = book.chapters
    order = range(len(chs)) if chapters is None else sorted(i for i in set(chapters) if 0 <= i < len(chs))
    total = len(order)
    out: dict = {}
    last = time.perf_counter()
    for done, i in enumerate(order, 1):
        if ctx.cancelled:
            break
        ch = chs[i]
        if ch.is_toc:
            continue
        for e, hits in matcher.scan_chapter(book.blocks(ch)).items():
            out.setdefault(entry_key(e), []).append([i, hits])
        ctx.breathe()
        now = time.perf_counter()
        if now - last > 0.2:
            ctx.emit(("scan", done, total))
            last = now
    return out


def term_keys_in_chapters_task(ctx, snapshot_path, tag: str, series_path, book_name: str, chapters) -> list:
    """Keys of the entries found in the given chapters (Terms filter `In selection`), from a snapshot."""
    found = term_scan_task(ctx, snapshot_path, tag, series_path, book_name, chapters)
    return sorted(found)
