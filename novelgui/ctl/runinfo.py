"""The shell's RunInfo built from the real RunControl (window_spec 1.2, 7.16, 9.11, 14.24). Pure: reads the
control, never changes it. The header word, the red pulses, the closing panel and the tray lines all read it.

`view` is the JobView of the tracked series (what the Translate view-model already read off the GUI thread); without
it the record is read from disk by the control, as the old header did.
"""

from __future__ import annotations

import time

from .. import chapterlogic as cl
from . import eta, translateplan as tp
from .shellrules import RunInfo

_UNSET = object()
FAILED_WORDS = {"key": "Key invalid", "model": "Model not found"}


def run_info(rc, terms_blocked: bool = False, now: float | None = None, view=_UNSET) -> RunInfo:
    """`terms_blocked`: translating cannot start on the open series because its first chapter has unreviewed terms
    (the Translate screen knows; the control does not)."""
    now = rc.clock() if now is None else now
    r = rc.run
    job = r is not None and r.kind == "job"
    wait = rc.quota_wait()
    ind = "" if job else (rc.indicator() if view is _UNSET else rc.indicator(view))
    failed = (not job) and ind == "Failed"
    waiting_terms = (not job) and ind.startswith("Terms")
    kind = ""
    if failed and view is not _UNSET and view is not None:
        kind = tp.error_kind(view.error, view.dead)
    elif failed and view is _UNSET:
        kind = tp.error_kind(getattr(rc, "last_start_error", ""))
    needs = failed and (view is _UNSET or kind in ("key", "model"))
    # a failure the user cannot fix (the service keeps failing) is a stopped job: no red pulse, no red tray line
    info = dict(running=job, waiting=wait is not None and not job, queued=len(rc.queue), failed=needs,
                needs_user=needs, terms_red=terms_blocked or waiting_terms)
    if job:
        bdone, btotal, cdone, ctotal = rc.counts()
        left = eta.time_left(bdone - r.done_at_start, now - r.started, btotal - bdone)
        info.update(series=r.name, book=r.book, done=cdone, total=ctotal, left_s=left, chapter=_chapter(rc, r),
                    verb="Stop", verb_enabled=not r.stopping)
    elif wait is not None:
        at, series = wait
        info.update(series=_name(series), wake=_clock(at), verb="Don't resume")
    elif failed or ind:
        series = rc.indicator_series()
        reason = FAILED_WORDS.get(kind) or (_short(view.error) if view not in (_UNSET, None) and view.error else "")
        info.update(series=_name(series), verb="Continue",
                    reason=(reason or getattr(rc, "last_start_error", "")) if needs else "")
    return RunInfo(**info)


def _chapter(rc, run) -> int:
    """The number the user reads for the chapter being translated (the first one of the job not complete yet)."""
    chap = run.chap
    i = min((k for k in chap if chap[k][1] and chap[k][0] < chap[k][1]), default=None)
    if i is None:
        return 0
    series, book, infos = rc.view()
    if series == run.series and book == run.book and i < len(infos):
        n = cl.title_number(infos[i].title or "")
        if n is not None:
            return n
    return cl.display_no(i)


def _short(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _clock(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def _name(series_path: str) -> str:
    return series_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
