"""Failed blocks and check findings: plain functions over the core (no Qt, no Tk).

`resolve_problems_task` is the only place of the window that appends to a chapter log, and only through the
core's `ChapterLog` (window_spec 14.18; `ctl.ordering.resolve_allowed` refuses chapters of the running job).
"""

from __future__ import annotations

import time

from novelcore import Series
from novelcore import checks as core_checks
from novelcore.htmlscan import strip_markers
from novelcore.store import ChapterLog, read_jsonl

from .. import chapterlogic as cl
from .. import findingrules
from ..jobstate import Problem, assemble_problems, kept_record, manual_record

# ---------------------------------------------------------------- failed blocks
def problems_task(ctx, series_path, book: str, chapters) -> list:
    """Failed blocks of the given chapters (latest record of the block is not ok) and the check findings of the
    volume that still describe their block and are not ignored."""
    series = Series.open(series_path)
    out = []
    with series.open_book(book) as b:
        for i in chapters:
            if ctx.cancelled or i >= len(b.chapters):
                break
            ch = b.chapters[i]
            path = series.chapter_log(book, ch).path
            if not path.exists() or cl.count_log(read_jsonl(path))[1] == 0:
                continue
            log = ChapterLog(path)
            blocks = [(blk.index, blk.sha, " ".join(strip_markers(blk.text).split())) for blk in b.blocks(ch)]
            out.extend(assemble_problems(i, ch.title or "", blocks, log.lookup))
        if not ctx.cancelled:
            out.extend(finding_rows(series, b, book))
    return sorted(out, key=lambda p: (p.chapter, p.block, p.kind != "failed"))


def finding_rows(series, b, book: str) -> list:
    """Problem rows of the saved check report of a volume (see check_task), minus ignored and outdated ones."""
    rep = core_checks.Report.load(series, book)
    if rep is None:
        return []
    ignored = findingrules.load_ignored(series.path, book)
    logs: dict = {}
    out = []
    for idx, cr in sorted(rep.chapters.items()):
        if not 0 <= idx < len(b.chapters):
            continue
        for f in cr.findings:
            tkey = findingrules.text_key(f.text)
            if findingrules.entry_key(f.chapter, f.block, f.src_sha, f.kind, tkey) in ignored:
                continue
            log = logs.get(idx)
            if log is None:
                log = logs[idx] = ChapterLog(series.chapter_log(book, b.chapters[idx]).path)
            if not findingrules.still_true(log.lookup(f.block, f.src_sha), tkey):
                continue
            out.append(Problem(f.chapter, f.title or b.chapters[idx].title or "", f.block, f.src_sha,
                               " ".join(strip_markers(f.source).split()), findingrules.label(f.kind), f.kind,
                               f.text, tkey, findingrules.detail_text(f.kind, f.detail)))
    return out


def fresh_marks(series, book: str, marks) -> list:
    """The retry marks whose block still has the translation the finding was made on: a block typed over,
    kept or retranslated since the check is left alone. Returns (chapter, block, source hash) tuples."""
    out = []
    with series.open_book(book) as b:
        for c, i, sha, tkey in marks:
            if not 0 <= c < len(b.chapters):
                continue
            log = ChapterLog(series.chapter_log(book, b.chapters[c]).path)
            if findingrules.still_true(log.lookup(i, sha), tkey):
                out.append((c, i, sha))
    return out


def check_task(ctx, series_path, book: str, chapters) -> dict:
    """Run the core's checks over `chapters` of a volume and save the result in the series (the earlier results of
    other chapters stay). Emits ("check", done, total). Returns {"findings": n, "chapters": n, "cancelled": bool}."""
    series = Series.open(series_path)
    rep = core_checks.check_range(series, book, list(chapters), progress=lambda d, t, i: ctx.emit(("check", d, t)),
                                  cancel=lambda: ctx.cancelled)
    old = core_checks.Report.load(series, book)
    if old is not None:
        for i, cr in rep.chapters.items():
            old.chapters[i] = cr
        old.created = rep.created
        old.target = rep.target
        rep_all = old
    else:
        rep_all = rep
    rep_all.cancelled = rep.cancelled
    rep_all.save(series)
    return {"findings": sum(len(c.findings) for c in rep.chapters.values()), "chapters": len(rep.chapters),
            "cancelled": rep.cancelled}


def ignore_task(ctx, series_path, book: str, rows) -> int:
    """Remember findings as ignored (they stay hidden until the block's translation changes)."""
    return findingrules.add_ignored(series_path, book, [(p.chapter, p.block, p.sha, p.kind, p.tkey) for p in rows])


def resolve_problems_task(ctx, series_path, book: str, problems, action: str, typed: str = "") -> int:
    """Keep the original text (`keep`) or a typed translation (`manual`) for failed blocks; appends ok records
    to the chapter logs through the core's ChapterLog. Returns the number of blocks written."""
    series = Series.open(series_path)
    now = time.time()
    done = 0
    by_chapter: dict = {}
    for p in problems:
        by_chapter.setdefault(p.chapter, []).append(p)
    with series.open_book(book) as b:
        for i, items in by_chapter.items():
            ch = b.chapters[i]
            texts = {blk.index: blk.text for blk in b.blocks(ch)}
            recs = []
            for p in items:
                if action == "keep":
                    recs.append(kept_record(p.block, p.sha, texts.get(p.block, p.source), now))
                elif typed.strip():
                    recs.append(manual_record(p.block, p.sha, typed, now))
            series.chapter_log(book, ch).append(recs)
            done += len(recs)
    return done

