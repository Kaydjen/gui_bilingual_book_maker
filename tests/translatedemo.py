"""Demo libraries and job records of the Translate screen for its tests and scenes: the series Knights (170 chapters
numbered 2650-2819, position 1 = number 2650; position 0 is the contents page) with a term base whose unconfirmed names
stand in chosen chapters (they hold those chapters back), the series Gamma and Delta as the other jobs of the queue, a
job record writer and the pool file of a dead key.
"""

from __future__ import annotations

import json
from pathlib import Path

FIRST_NUMBER = 2650
SELECTION = "2703-2750"


def position(number: int) -> int:
    return number - FIRST_NUMBER + 1


def knights(translated: int = 0, blocked=(), chosen: bool = True, chapters: int = 170, keep_terms: bool = True, paras: int = 3, done=(), **kw) -> dict:
    """`translated`: the first k chapters are translated. `blocked`: title numbers of chapters that mention an
    unconfirmed name (one name per chapter, `Name<number>`). Everything else in the base is confirmed. `done`: [first,
    last] title-number ranges that are fully translated (any places)."""
    mentions = {str(n): ["Name%d" % n] for n in blocked}
    terms = []
    for n in blocked:
        terms.append({"src": "Name%d" % n, "tr": "Имя%d" % n, "type": "character", "gender": "male", "status": "new",
                      "seen": [position(n)], "count": 3})
    spec = {"name": "Knights", "books": [{"stem": "Book 1", "chapters": chapters, "start": FIRST_NUMBER, "paras": paras,
                                         "translated": translated, "mentions": mentions, "done": [list(d) for d in done]}]}
    if keep_terms and terms:
        spec["terms"] = terms
    if not chosen:
        spec["chosen"] = False
    spec.update(kw)
    return spec


def other(name: str, chapters: int = 40, target: str = "uk:Ukrainian", **kw) -> dict:
    spec = {"name": name, "target": target, "books": [{"stem": "Book 2", "chapters": chapters, "start": 12, "paras": 3}]}
    spec.update(kw)
    return spec


def write_record(series_path, book: str, state: str, chapters, **kw) -> None:
    """The job record of a series as the core writes it (`chapters` = positions)."""
    from novelcore import job as core_job
    from novelcore.run import to_ranges
    chapters = sorted(chapters)
    rec = {"version": 1, "book": book, "first": chapters[0], "last": chapters[-1], "chapters": to_ranges(chapters),
           "state": state, "models": ["gemini-3.1-flash-lite"], "chapter_blocks": {}, "wake_at": None, "error": None,
           "terms_pending": 0, "blocked_chapter": None, "blocks_failed": 0, "chapters_total": len(chapters)}
    rec.update(kw)
    core_job.write_job(series_path, rec)


def write_dead_key(series_path, key: str, reason: str = "invalid key", model: str = "gemini-3.1-flash-lite") -> None:
    """The pool file of a series with one key/model pair held as dead."""
    from novelcore.pool import key_hash
    state = Path(series_path) / ".state"
    state.mkdir(parents=True, exist_ok=True)
    pairs = {"%s|%s" % (key_hash(key), model): {"state": "dead", "reason": reason}}
    (state / "pool.json").write_text(json.dumps({"pairs": pairs}), encoding="utf-8")


def write_failed_block(series_path, book: str, position_: int, block: int = 0, reason: str = "empty") -> None:
    """A failed record in the chapter log of one chapter (what a failed block leaves behind)."""
    from novelcore import Series
    series = Series.open(series_path)
    with series.open_book(book) as b:
        ch = b.chapters[position_]
        blk = b.blocks(ch)[block]
        series.chapter_log(book, ch).append([{"i": blk.index, "src_sha": blk.sha, "status": "failed", "reason": reason,
                                               "at": 1.0, "model": "m", "flags": []}])
