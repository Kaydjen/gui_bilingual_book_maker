"""Pure logic of the Translate step: what the main button says, which chip shows, who owns the accent,
the estimate of a run, the quota numbers and the list of failed blocks. No Tk, no core imports."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

UNFINISHED = ("stopped", "interrupted", "waiting_quota", "waiting_terms", "failed")


@dataclass
class JobView:
    """What the window knows about the job of a series (built from the job record)."""
    state: str = ""               # "" none, running, interrupted, stopped, waiting_quota, waiting_terms, failed, finished
    book: str = ""
    chapters: tuple = ()          # chapter indices of the job
    blocks_done: int = 0
    blocks_total: int = 0
    chapters_done: int = 0
    chapters_total: int = 0
    blocks_failed: int = 0
    terms_pending: int = 0
    blocked_chapter: int | None = None
    wake_at: float | None = None
    error: str = ""
    foreign: bool = False         # a live process other than this window works on the series
    dead: tuple = ()              # reasons of the key/model pairs the pool holds as dead (`invalid key`, ...)

    @property
    def unfinished(self) -> bool:
        return self.state in UNFINISHED


@dataclass(frozen=True)
class Action:
    label: str          # Run | Stop | Continue
    enabled: bool
    new_run: bool = False   # the second, non-accent control `New run` is shown


def main_action(view: JobView, running: bool, stopping: bool, has_selection: bool, same_selection: bool,
                now: float, terms_now: int | None = None) -> Action:
    """The one main button. `running`: a run of this window is active. `terms_now`: unreviewed terms now
    (None = unknown, the record's count is used)."""
    if running:
        return Action("Stop", not stopping)
    if view.foreign:
        return Action("Run", False)
    if view.unfinished:
        if view.state == "waiting_quota":
            ok = view.wake_at is not None and now >= view.wake_at
        elif view.state == "waiting_terms":
            ok = (view.terms_pending if terms_now is None else terms_now) == 0
        else:
            ok = True
        return Action("Continue", ok, new_run=has_selection and not same_selection)
    return Action("Run", has_selection)


def terms_count(view: JobView, terms_now: int | None) -> int:
    if view.state != "waiting_terms":
        return 0
    return view.terms_pending if terms_now is None else terms_now


@dataclass(frozen=True)
class Chip:
    text: str = ""
    kind: str = "dim"      # dim | plain | accent
    key: str = ""          # for the tooltip: wait | terms | paused | stopped | failed | done | stopping | elsewhere


def clock_text(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def countdown_text(seconds: float) -> str:
    s = max(0, int(math.ceil(seconds)))
    return "%d:%02d" % (s // 60, s % 60)


def chip_for(view: JobView, running: bool, stopping: bool, paused_until: float | None, now: float,
             terms_now: int | None = None) -> Chip:
    if stopping:
        return Chip("Stopping", "dim", "stopping")
    if running:
        if paused_until is not None and paused_until > now:
            return Chip("Paused " + countdown_text(paused_until - now), "dim", "paused")
        return Chip()
    if view.foreign:
        return Chip("Running elsewhere", "dim", "elsewhere")
    st = view.state
    if st == "waiting_quota":
        if view.wake_at is not None and now < view.wake_at:
            return Chip("Wait " + clock_text(view.wake_at), "dim", "wait")
        return Chip("Stopped", "plain", "stopped")
    if st == "waiting_terms":
        n = terms_count(view, terms_now)
        return Chip("Terms %d" % n, "accent", "terms") if n > 0 else Chip("Stopped", "plain", "stopped")
    if st in ("stopped", "interrupted"):
        return Chip("Stopped", "plain", "stopped")
    if st == "failed":
        return Chip("Failed", "plain", "failed")
    if st == "finished":
        # a job that ended with failed blocks is not done for the user: the problem count says it
        return Chip("Done", "plain", "done") if view.blocks_failed == 0 else Chip()
    return Chip()


def accent_owner(action: Action, chip: Chip, problems: int, running: bool) -> str:
    """One accent per screen: the terms chip, else the button (Run / Continue when it is the next thing),
    else the problem count."""
    if chip.key == "terms" and chip.kind == "accent":
        return "terms"
    if action.label in ("Run", "Continue") and action.enabled and (action.label == "Continue" or problems == 0):
        return "action"
    if problems > 0 and not running:
        return "problems"
    return ""


# ---------------------------------------------------------------- numbers
def fmt_count(n: int) -> str:
    return format(int(n), ",").replace(",", " ")


def fmt_duration(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    if s < 60:
        return "%d s" % s
    m = s // 60
    if m < 60:
        return "%d min" % m
    h, m = divmod(m, 60)
    if h < 48:
        return "%d h %02d min" % (h, m)
    return "%d d" % round(h / 24)


@dataclass(frozen=True)
class Estimate:
    requests: int
    seconds: float
    days: int                 # days the daily quota needs (0 = nothing to do, 1 = today is enough)
    left: int | None


def estimate(remaining_blocks: int, per_request: int, pace: float, left_today: int | None,
             per_day: int | None) -> Estimate:
    """Requests needed = remaining blocks / blocks per request; time at the pace (requests a minute in
    total); days by the daily quota."""
    per_request = max(1, int(per_request))
    requests = math.ceil(max(0, remaining_blocks) / per_request)
    seconds = requests * 60.0 / pace if pace and pace > 0 else 0.0
    if requests == 0:
        days = 0
    elif left_today is None or requests <= left_today:
        days = 1
    elif per_day and per_day > 0:
        days = 1 + math.ceil((requests - left_today) / per_day)
    else:
        days = 0
    return Estimate(requests, seconds, days, left_today)


def remaining_blocks(infos, indices) -> tuple[int, bool]:
    """(blocks still to translate in the chapters, complete) from the chapter list of the Books step."""
    total, complete = 0, True
    for i in indices:
        if i >= len(infos):
            continue
        info = infos[i]
        if info.blocks is None:
            complete = False
        else:
            total += max(0, info.blocks - info.done)
    return total, complete


def quota_text(est: Estimate | None, left: int | None) -> str:
    """The dim numbers line: left today, requests needed, time, days."""
    parts = ["%s left today" % (fmt_count(left) if left is not None else "?")]
    if est is not None and est.requests:
        parts.append("%s %s" % (fmt_count(est.requests), "request" if est.requests == 1 else "requests"))
        parts.append(fmt_duration(est.seconds))
        if est.days > 1:
            parts.append("%d days" % est.days)
    return "  ·  ".join(parts)


# ---------------------------------------------------------------- problems
@dataclass(frozen=True)
class Problem:
    chapter: int
    title: str
    block: int
    sha: str
    source: str
    reason: str


def assemble_problems(chapter: int, title: str, blocks, lookup) -> list[Problem]:
    """Failed blocks of one chapter. `blocks`: (index, sha, source text) in order; `lookup(index, sha)` gives the
    latest record of the block or None. A block is a problem when its latest record is not ok."""
    out = []
    for index, sha, text in blocks:
        rec = lookup(index, sha)
        if rec is not None and rec.get("status") != "ok":
            out.append(Problem(chapter, title, index, sha, text, str(rec.get("reason") or "failed")))
    return out


def shorten(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def kept_record(index: int, sha: str, source_text: str, now: float) -> dict:
    return {"i": index, "src_sha": sha, "text": source_text, "model": "", "at": now, "status": "ok",
            "flags": ["kept"]}


def manual_record(index: int, sha: str, typed: str, now: float) -> dict:
    return {"i": index, "src_sha": sha, "text": typed.strip(), "model": "", "at": now, "status": "ok",
            "flags": ["manual"]}
