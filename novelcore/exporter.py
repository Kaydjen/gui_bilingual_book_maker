"""Export stored translations of a series into an EPUB."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .epub import check
from .store import ChapterLog, safe_name


class NothingToExport(Exception):
    """No selected chapter is fully translated (or the selection is empty)."""


@dataclass
class Skipped:
    index: int  # chapter position in the book
    title: str
    missing: int  # blocks without a finished translation


@dataclass
class ExportResult:
    path: Path
    mode: str
    blocks: int = 0  # translated blocks written
    untranslated: int = 0  # blocks of the selection without a finished translation (skipped chapters included)
    fallbacks: list = field(default_factory=list)  # blocks whose markers did not fit (written as plain text)
    problems: list = field(default_factory=list)  # structural problems found by check()
    cut: bool = False  # only the selected chapters were written
    kept: list = field(default_factory=list)  # chapter indices written (cut export)
    skipped: list = field(default_factory=list)  # Skipped: selected chapters that are not fully translated
    toc_untranslated: list = field(default_factory=list)  # kept chapters whose TOC label stayed in the source language
    dropped_links: int = 0  # links in kept chapters that point to chapters not in the file
    bytes_written: int = 0
    spine_items: int = 0


def _fresh_log(series, book_name, chapter) -> ChapterLog:
    """A log read from disk now: no cache shared with a running translation."""
    return ChapterLog(series.chapter_log(book_name, chapter).path)


def _collect(series, book, book_name, chapters):
    """({(href, block): text} of the finished blocks, missing block count) for the given chapters."""
    translations: dict = {}
    missing = 0
    for ch in chapters:
        log = _fresh_log(series, book_name, ch)
        for b in book.blocks(ch):
            rec = log.done(b.index, b.sha) if log.path.exists() else None
            if rec is None:
                missing += 1
            else:
                translations[(ch.href, b.index)] = rec["text"]
    return translations, missing


def export(series, book_name, first=0, last=None, mode="single", out_path=None,
           chapters=None, cut=True) -> ExportResult:
    """Build an EPUB from the stored translations.

    Selection: `chapters` (chapter indices, any order, may skip) or the range first..last
    (inclusive; last None = to the end). Table-of-contents pages inside a range are not
    selected; listing one in `chapters` selects it.

    cut=True (default): the file holds only the selected chapters that are fully
    translated (others are listed in `skipped`) plus what they need; navigation and title
    are cut to match. NothingToExport is raised, and no file written, when none qualifies.
    cut=False: the whole book is written; blocks without a finished translation stay in
    the source language.
    """
    with series.open_book(book_name) as book:
        n = len(book.chapters)
        if chapters is not None:
            picked = sorted({int(i) for i in chapters if 0 <= int(i) < n})
        else:
            hi = n - 1 if last is None else min(last, n - 1)
            picked = list(range(max(first, 0), hi + 1))
            if cut:
                picked = [i for i in picked if not book.chapters[i].is_toc]
        if not cut:
            return _export_whole(series, book, book_name, picked or [], mode, out_path, first, last)
        return _export_cut(series, book, book_name, picked, mode, out_path)


def _export_whole(series, book, book_name, picked, mode, out_path, first, last) -> ExportResult:
    n = len(book.chapters)
    hi = n - 1 if last is None else min(last, n - 1)
    translations, missing = _collect(series, book, book_name, [book.chapters[i] for i in picked])
    if out_path is None:
        stem = f"{safe_name(book_name, 60)}_{series.target_tag}_{mode}_{max(first, 0)}-{hi}.epub"
        out_path = series.path / "out" / stem
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fallbacks = book.export(out_path, translations, mode, lang=series.settings["target"])
    problems = check(out_path, source=book.path)
    return ExportResult(out_path, mode, len(translations), missing, fallbacks, problems,
                        bytes_written=out_path.stat().st_size)


def _export_cut(series, book, book_name, picked, mode, out_path) -> ExportResult:
    translations: dict = {}
    skipped: list[Skipped] = []
    kept: list[int] = []
    missing = 0
    for i in picked:
        ch = book.chapters[i]
        trans, miss = _collect(series, book, book_name, [ch])
        missing += miss
        if miss:
            skipped.append(Skipped(ch.index, ch.title, miss))
        else:
            kept.append(i)
            translations.update(trans)
    if not kept:
        detail = "; ".join(f"{s.index}: {s.missing} missing" for s in skipped[:5])
        raise NothingToExport("no selected chapter is fully translated" + (f" ({detail})" if detail else ""))
    if out_path is None:
        a, b = kept[0], kept[-1]
        count = "" if len(kept) == b - a + 1 else f"_{len(kept)}ch"
        stem = f"{safe_name(book_name, 60)}_{series.target_tag}_{mode}_{a}-{b}{count}.epub"
        out_path = series.path / "out" / stem
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=out_path.name + ".", suffix=".part", dir=out_path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        report = book.export_cut(tmp, translations, mode, lang=series.settings["target"], keep=kept)
        problems = check(tmp, source=book.path, strict=True)
        size = tmp.stat().st_size
        os.replace(tmp, out_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return ExportResult(out_path, mode, len(translations), missing, report.fallbacks, problems, True,
                        report.kept, skipped, report.toc_untranslated, report.dropped_links, size,
                        report.spine_items)
