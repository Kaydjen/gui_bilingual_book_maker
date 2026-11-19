"""What the Export screen reads and writes besides the build itself (window_spec 8.7): the export history of a volume,
per chapter, and the names of the two languages. Plain functions of plain data, run on the data lane.

The history is the window's own record (`<series>/.state/exports_<book>.json`, later `decisions.json`, C23): it is not
parsed from the names in `out/`. One entry per chapter position: `[date, file name]`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import atomic
from . import books as fbooks

VERSION = 1
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def history_path(series_path, book: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", book)
    return Path(series_path) / ".state" / ("exports_%s.json" % safe)


def day_text(iso: str) -> str:
    """`2026-11-17` as `17 Nov`; the text itself when it is not a date."""
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return "%d %s" % (d, MONTHS[m - 1])
    except (ValueError, IndexError):
        return iso


def read_history(series_path, book: str) -> dict:
    """{position: (date, file)} of the exported chapters; {} when there is no record or it cannot be read."""
    try:
        data = json.loads(history_path(series_path, book).read_text(encoding="utf-8"))
        raw = data["chapters"] if data.get("v") == VERSION else {}
        return {int(k): (str(v[0]), str(v[1])) for k, v in raw.items()}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return {}


def history_task(ctx, series_path, book: str) -> dict:
    return read_history(series_path, book)


def add_history(series_path, book: str, positions, file: str, when: str = "") -> dict:
    """Record that these chapters went into `file` (today, or `when`); returns the whole history now."""
    got = read_history(series_path, book)
    stamp = when or time.strftime("%Y-%m-%d")
    for p in positions:
        got[int(p)] = (stamp, file)
    rows = {str(k): [d, f] for k, (d, f) in sorted(got.items())}
    atomic.write_text(history_path(series_path, book),
                      json.dumps({"v": VERSION, "chapters": rows}, ensure_ascii=False, separators=(",", ":")))
    return got


def context_task(ctx, series_path, book: str) -> dict:
    """The names the buttons and the file name need: the source language of the volume (13.11)."""
    src = fbooks.source_language(series_path, book)
    return {"source": src.name, "source_tag": src.tag}


def sweep_task(ctx, series_path) -> int:
    """Remove the `.part` leftovers of one series' `out` folder (a cancelled build); returns how many went."""
    n = 0
    for x in list((Path(series_path) / "out").glob("*" + fbooks.PART)):
        try:
            x.unlink()
            n += 1
        except OSError:
            pass
    return n
