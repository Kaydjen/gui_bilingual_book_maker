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
    choices: tuple = ()         # ((field, ((value, where it comes from), ...)), ...): the open questions with their candidates


def row_of(e) -> TermRow:
    choices = tuple((f, tuple((str(c.get("value", "")), str(c.get("evidence", ""))) for c in cands))
                    for f, cands in sorted(e.questions.items()))
    return TermRow(entry_key(e), e.source, e.tr, e.type, e.gender, e.status, e.count,
                   min(e.seen) if e.seen else None, tuple(sorted(e.questions)), tuple(e.forms), e.note, e.same_as,
                   choices)


@dataclass(frozen=True)
class TermCommand:
    """An edit of the term base. `op`: set_field | confirm | unconfirm | delete | keep."""
    op: str
    keys: tuple
    field: str = ""
    value: str = ""
    label: str = ""             # the operation name of a BULK change: a snapshot of the base is taken first (14.11)


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
        self.history = None                 # fn(label): snapshot the base before a bulk change (window side, C17)
        self._trash: list = []              # [(entries, dismissed sources)] of the last Delete / Not a term

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
        if cmd.op in ("add", "undo_delete", "dismiss_names"):
            return self._apply_new(cmd)
        entries = [self._entry(k) for k in cmd.keys]
        missing = tuple(k for k, e in zip(cmd.keys, entries) if e is None)
        entries = [e for e in entries if e is not None]
        if not entries:
            return CommandResult((), missing, "The term is gone.")
        base = self.base
        if cmd.op in ("confirm", "unconfirm", "merge"):
            self._snapshot_before(cmd)
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
        elif cmd.op in ("delete", "dismiss"):
            return self._remove(cmd, entries, missing)
        elif cmd.op == "merge":
            return self._merge(entries, missing)
        else:
            return CommandResult((), missing, "Unknown command.")
        return CommandResult(tuple(row_of(e) for e in entries), missing)

    def _snapshot_before(self, cmd: TermCommand) -> None:
        if cmd.label and self.history is not None:
            self.history(cmd.label)

    def _remove(self, cmd: TermCommand, entries, missing) -> CommandResult:
        """Delete (Undo available) or Not a term (the same, plus: never suggested again)."""
        self._snapshot_before(cmd)
        kept, dismissed, gone = [], [], []
        for e in entries:
            kept.append(e)
            if self.base.delete(e.source):
                gone.append(entry_key(e))
                if cmd.op == "dismiss" and self.base.dismiss(e.source):
                    dismissed.append(e.source)
        self._trash = [(kept, dismissed)]
        self.dirty = self.dirty or bool(gone)
        return CommandResult((), missing + tuple(gone))

    def _merge(self, entries, missing) -> CommandResult:
        """The first entry keeps; the others become its other spellings."""
        if len(entries) < 2:
            return CommandResult(tuple(row_of(e) for e in entries), missing, "Pick two or more terms to merge.")
        keep, gone = entries[0], []
        for o in entries[1:]:
            self.base.merge(keep.source, o.source)
            gone.append(entry_key(o))
        self.dirty = True
        return CommandResult((row_of(keep),), missing + tuple(gone))

    def _apply_new(self, cmd: TermCommand) -> CommandResult:
        """`add`: a mined name the user gave a rendering (a confirmed entry); `undo_delete`: the last removal back."""
        if cmd.op == "add":
            text, tr = cmd.field.strip(), cmd.value.strip()
            if not text or not tr:
                return CommandResult((), (), "A rendering is needed.")
            try:
                e = self.base.add(text, status="confirmed", tr=tr)
            except ValueError as exc:
                return CommandResult((), (), str(exc))
            self.dirty = True
            return CommandResult((row_of(e),))
        if cmd.op == "dismiss_names":
            self._snapshot_before(cmd)
            for name in cmd.value.split("\n"):
                try:
                    self.dirty = self.base.dismiss(name) or self.dirty
                except ValueError:
                    continue
            return CommandResult(())
        back = []
        for entries, dismissed in self._trash:
            for src in dismissed:
                self.base.restore(src)
            for e in entries:
                try:
                    back.append(row_of(self.base.add(
                        e.source, status=e.status, forms=e.forms, type=e.type, gender=e.gender, tr=e.tr, note=e.note,
                        hint=e.hint, same_as=e.same_as, seen=e.seen, count=e.count, evidence=e.evidence,
                        changed=e.changed, questions=e.questions, locked=e.locked, extra=e.extra)))
                except ValueError:
                    continue
        self._trash = []
        self.dirty = self.dirty or bool(back)
        return CommandResult(tuple(back))

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

    # -- questions of the screen, answered from the base (data lane)
    def blocking_keys(self, chapters) -> frozenset:
        """Keys of the unconfirmed entries that occur in one of the chapters (what stops translating them)."""
        want = set(chapters)
        if not want:
            return frozenset()
        return frozenset(entry_key(e) for e in self.base if e.status == "new" and not want.isdisjoint(e.seen))

    def chapters_of(self, key: str) -> tuple:
        e = self._entry(key)
        return tuple(sorted(e.seen)) if e is not None else ()

    def names_of(self, key: str) -> tuple:
        e = self._entry(key)
        return tuple(e.spellings()) if e is not None else ()

    def dismissed(self) -> frozenset:
        return frozenset(self.base.dismissed())

    def import_glossaries(self, files, confirmed: dict, label: str = "Import", progress=None) -> dict:
        """Add the terms of glossary files (only adds, 6.4), one file at a time. `confirmed` {file name: bool}: a file
        that goes to `Not confirmed` leaves its NEW terms unconfirmed. Returns {keys, added, confirmed, unconfirmed,
        choices, same}; `keys` = the entries this import touched."""
        if self.history is not None:
            self.history(label)
        base, origin = self.base, {}
        before = {entry_key(e): (e.tr, repr(e.questions.get("tr"))) for e in base}
        stats = {"added": 0, "same": 0, "choices": 0, "confirmed": 0, "unconfirmed": 0}
        orig = set(before)
        for n, f in enumerate(files, 1):
            if progress is not None:
                progress(n, len(files), Path(f).name)
            rep = import_glossary(base, [Path(f)])
            stats["added"] += rep.added
            stats["same"] += rep.same
            stats["choices"] += len(rep.conflicts)
            self._note_origin(origin, before, orig, Path(f).name)
        by_name = {Path(f).name: bool(confirmed.get(Path(f).name, True)) for f in files}
        fresh = {k for k in origin if k not in orig}
        for k, name in origin.items():
            e = self._entry(k)
            if e is None or e.questions or k not in fresh:
                continue
            if by_name.get(name, True):
                stats["confirmed"] += 1
            else:
                e.status = "new"
                base._touch(e)
                stats["unconfirmed"] += 1
        self.dirty = True
        stats["keys"] = tuple(sorted(origin))
        return stats

    def _note_origin(self, origin: dict, before: dict, orig: set, name: str) -> None:
        """After one file: which entries it added or changed (a new entry, another rendering, a question that grew), and the
        file named in a question that says the base (`terms.json`) instead of the file the rendering came from."""
        for e in self.base:
            k = entry_key(e)
            sig = (e.tr, repr(e.questions.get("tr")))
            if before.get(k) != sig:
                origin.setdefault(k, name)
        for e in self.base:
            k = entry_key(e)
            for c in e.questions.get("tr", ()):
                if c.get("evidence") == self.base.path.name and k in origin and k not in orig:
                    c["evidence"] = origin[k]
        for e in self.base:
            before.setdefault(entry_key(e), (e.tr, repr(e.questions.get("tr"))))

    def export_to(self, path) -> int:
        """The glossary as plain {source: rendering} JSON (9.12): the entries that have a rendering."""
        import json
        data = {e.source: e.tr for e in self.base.sorted_entries() if e.tr}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return len(data)


def read_glossary_task(ctx, files) -> list:
    """[(file name, terms, {key: rendering})] of glossary JSON files for the Import panel; a bad file raises."""
    import json
    out = []
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("%s: not a JSON object" % Path(f).name)
        ok = {norm_key(k): v.strip() for k, v in data.items() if isinstance(k, str) and isinstance(v, str)
              and k.strip() and v.strip()}
        out.append((Path(f).name, len(ok), ok))
    return out


def term_names_task(ctx, series_path, book_name: str) -> list:
    """Names the offline scan found that are not in the base: [(text, count, first chapter)]. They only suggest
    until the model pass exists (core C3); no rendering yet."""
    series = Series.open(series_path)
    fr = core_frontier.Frontier.for_series(series, book_name)
    fr.scan(progress=lambda d, t: ctx.emit(("scan", d, t)), cancel=lambda: ctx.cancelled, mine=True)
    ctx.breathe()
    return sorted(((it.text, int(it.count), int(it.first)) for it in fr.terms().values()
                   if it.kind == core_frontier.KIND_CANDIDATE), key=lambda t: (t[2], -t[1], t[0].lower()))


def term_places_task(ctx, series_path, book_name: str, names, chapters=None, context: int = 1) -> int:
    """Paragraphs of the book that mention a term (any of `names`), found in small batches that are emitted as they
    come: [(chapter, block, mentions, [paragraph before], paragraph, [paragraph after])]. Only `chapters` are read
    when given (the places the scan noted), else the whole book. Returns how many paragraphs were found."""
    from novelcore.htmlscan import strip_markers
    from ..termlogic import term_regex
    names = [n for n in names if n]
    if not names:
        return 0
    pattern = term_regex(SimpleNamespace(source=names[0], forms=names[1:]))
    book = open_book(book_file(series_path, book_name))
    chs = book.chapters
    order = sorted(i for i in chapters if 0 <= i < len(chs)) if chapters else range(len(chs))
    found, batch, last = 0, [], time.perf_counter()
    for i in order:
        if ctx.cancelled:
            return found
        try:
            if not chapters and chs[i].is_toc:
                continue
            texts = [(b.index, strip_markers(b.text)) for b in book.blocks(chs[i])]
        except Exception:
            continue
        for k, (bi, text) in enumerate(texts):
            n = len(pattern.findall(text))
            if n:
                batch.append((i, bi, n, [t for _b, t in texts[max(0, k - context):k]], text,
                              [t for _b, t in texts[k + 1:k + 1 + context]]))
        ctx.breathe()
        now = time.perf_counter()
        if batch and (len(batch) >= 8 or now - last > 0.1):
            found += len(batch)
            ctx.emit(batch)
            batch, last = [], now
    if batch:
        found += len(batch)
        ctx.emit(batch)
    return found


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
