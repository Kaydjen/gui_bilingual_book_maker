"""Reads of the Translate screen: plain functions over the core (no Qt, no Tk). `*_task` functions take a lane
context first and run off the GUI thread (a lane thread or the helper process); arguments and results are plain data.
"""

from __future__ import annotations

from novelcore import Series
from novelcore import frontier as core_frontier

from . import books as fbooks
from . import quota as fquota
from . import run as frun


def gate_counts_task(ctx, series_path, book: str, positions) -> dict:
    """{chapter position: unreviewed terms that hold it back} for the positions that have any (the core's own gate,
    from the cached scan of the whole book). {} when the series has no term base."""
    series = Series.open(series_path)
    gate = core_frontier.gate_for(series, book) if frun.HAS_GATE_FOR else None
    if gate is None:
        return {}
    out = {}
    for i in positions:
        if ctx.cancelled:
            break
        try:
            n = int(gate(i))
        except Exception:
            continue
        if n > 0:
            out[i] = n
        ctx.breathe()
    return out


def job_task(ctx, series_path):
    """The job record of a series as the window shows it (cheap)."""
    return frun.job_view(series_path)


def quota_task(ctx, library, keys, models, now: float):
    """Today's requests left over all keys (the pool files of every series of the library)."""
    return fquota.quota_status(library, keys, models, now)


def series_task(ctx, series_path, book: str) -> dict:
    """What Translate needs of one series that is not in the chapter list: prompt name and text, requests per call,
    whether the language is locked (a block is translated or a term confirmed), the source language of the book."""
    st = fbooks.series_settings(series_path)
    translated, confirmed = fbooks.language_lock(series_path)
    src = fbooks.source_language(series_path, book) if book else None
    pr = st.get("per_request")
    return {"prompt": str(st.get("prompt") or "default"), "per_request": pr if pr in (1, 5, 10) else 5,
            "translated": translated, "confirmed": confirmed, "source": src.name if src else "",
            "source_tag": src.tag if src else ""}


def prompt_task(ctx, series_path) -> str:
    return fbooks.current_prompt_text(series_path)


def save_per_request_task(ctx, series_path, value: int) -> None:
    fbooks.save_series_setting(series_path, "per_request", int(value))
