"""Pure logic of the Translate screen (window_spec 7.16): the bottom bar segments, the state word of a chapter row,
the Time pill and popover, the Queue tab rows, the Sample label. No Qt, no Tk, no clock of its own.

Tones: `main` (bright, bold), `normal`, `dim`, `red` (a problem the user must act on; the only accent).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .. import jobstate as js
from .. import startlabel as sl

UNFINISHED = js.UNFINISHED
PER_REQUEST = (1, 5, 10)
UNTESTED = {10: True}            # the 10 per request choice is not tested yet (7.16)
DAILY_TOTAL = 4000               # default of the tests only: the window passes Quota.capacity (keys x daily limit)
SAMPLE_BLOCKS = 50


# ---------------------------------------------------------------- bottom bar
@dataclass(frozen=True)
class Segment:
    id: str                    # translate | queue | replace | review | add_keys | stop | continue | dont_resume |
                               # settings | more | retranslate | check | continue_queue | continue_after
    text: str
    tone: str = "normal"
    enabled: bool = True
    why: str = ""              # tooltip key for a disabled segment


@dataclass(frozen=True)
class BarFacts:
    start: sl.Start
    tab: str = "chapters"            # chapters | problems | queue | sample
    job_state: str = ""              # state of THIS series' job: running | stopped | interrupted | waiting_quota |
                                     # waiting_terms | failed | finished | ""
    job_reach: str = ""              # chapters of that job, `2730-2750` (what Continue covers)
    job_terms: int = 0               # unreviewed terms that hold that job
    another_runs: bool = False       # another series runs (this window)
    foreign: bool = False            # busy elsewhere on this PC
    keys: bool = True
    first_blocked: bool = False
    language: bool = True
    namescan: bool = False           # the name scan of the book is not done
    translated: bool = False
    reach: str = ""                  # reach of the selection
    check_reach: str = ""            # for the Problems tab `Check a-b`
    queue_restart: bool = False      # the queue was restored after a restart and waits for `Continue queue`
    running_series: str = ""         # name of the running job of another series
    continue_enabled: bool = True
    error_kind: str = ""             # of a failed job: key | model | nopair | disk | service | shut | crash | ""
    stopping: bool = False           # Stop was pressed, the requests in flight finish


def bar_segments(f: BarFacts) -> list:
    """The bottom bar by state: at most two parts, this series' job then the selection (7.16)."""
    if f.foreign:
        return []
    if f.tab == "queue" and f.queue_restart:
        return [Segment("continue_queue", "Continue queue", "main")]
    if f.tab == "problems":
        return [Segment("check", "Check %s" % f.check_reach if f.check_reach else "Check", "main",
                        bool(f.check_reach))]
    job: list = []
    state = f.job_state
    if state == "running":
        job = [Segment("stopping", "Stopping…", "dim", False, "stopping")] if f.stopping else [
            Segment("stop", "Stop", "main")]
    elif state == "waiting_terms":
        job = [Segment("review", "Review %d %s" % (f.job_terms, "term" if f.job_terms == 1 else "terms"), "red"), Segment("more", "•••", "dim")]
    elif state == "waiting_quota":
        job = [Segment("dont_resume", "Don't resume", "main")]
    elif state in ("stopped", "interrupted", "failed"):
        verb = "Continue %s" % f.job_reach if f.job_reach else "Continue"
        if f.another_runs:
            verb = "Continue after %s · %s" % (f.running_series, f.job_reach) if f.running_series else verb
        job = []
        if state == "failed":
            if f.error_kind == "disk":
                job = [Segment("open_folder", "Open folder", "red")]
            elif f.error_kind in ("key", "model", "nopair", ""):
                job = [Segment("settings", "Settings", "red")]
        job += [Segment("continue", verb, "main", f.keys and f.continue_enabled,
                        "" if f.keys else "keys"), Segment("more", "•••", "dim")]
    st = f.start
    sel: list = []
    if state == "waiting_terms" or state == "waiting_quota":
        pass
    elif not f.keys and not job:
        sel = [Segment("add_keys", "Add keys", "red")]
    elif st.kind == "none":
        pass
    elif st.kind == "review":
        sel = [Segment("review", "Review %d %s" % (st.review, "term" if st.review == 1 else "terms"), "red")]
    elif st.has_button:
        text = st.text
        if f.translated and st.kind == "translate" and not st.enabled:
            text = sl.label("Retranslate", f.reach)
        if state in ("stopped", "interrupted", "failed") and st.kind in ("replace", "queue_replace"):
            text = st.text                       # `+ Replace job · a-b` is the second part
        tone = "main" if not job and st.enabled else ("normal" if st.enabled else "dim")
        sel = [Segment(st.kind, text, tone, st.enabled, st.why)]
    return job + sel


# ---------------------------------------------------------------- row state words
@dataclass(frozen=True)
class Word:
    text: str = ""
    tone: str = "dim"          # bright | red | dim
    key: str = ""              # tooltip key: stopped | key | model | resumes | retrying | paused | terms | busy | problems
    click: str = ""            # "" | terms | problems


@dataclass(frozen=True)
class RowFacts:
    job_state: str = ""
    current: bool = False            # the chapter the job works on / stopped at
    error_kind: str = ""             # key | model | ""
    wake_at: float | None = None
    retry_until: float | None = None
    paused_until: float | None = None
    stopping: bool = False
    terms: int = 0                   # unreviewed terms of this chapter
    terms_holds: bool = False        # they hold the job or the first chapter (red)
    foreign: bool = False
    problems: int = 0
    running: bool = False


def countdown(seconds: float) -> str:
    return js.countdown_text(seconds)


def row_word(r: RowFacts, now: float) -> Word:
    """The state word a chapter row carries (7.16): one word per row, the most urgent first."""
    if r.foreign and r.current:
        return Word("Busy elsewhere on this PC", "dim", "busy")
    if r.current:
        if r.running and r.stopping:
            return Word("Stopping", "dim", "stopping")
        if r.job_state == "failed":
            if r.error_kind == "model":
                return Word("Model not found", "red", "model")
            if r.error_kind == "key":
                return Word("Key invalid", "red", "key")
            if r.error_kind == "disk":
                return Word("Disk is full", "red", "disk")
            return Word("Stopped", "bright", r.error_kind if r.error_kind in ("nopair", "service", "shut", "crash")
                        else "stopped")
        if r.job_state in ("stopped", "interrupted"):
            return Word("Stopped", "bright", "stopped")
        if r.job_state == "waiting_quota" and r.wake_at is not None and r.wake_at > now:
            return Word("Resumes " + js.clock_text(r.wake_at), "dim", "resumes")
        if r.running and r.paused_until is not None and r.paused_until > now:
            return Word("Paused " + countdown(r.paused_until - now), "dim", "paused")
        if r.running and r.retry_until is not None and r.retry_until > now:
            return Word("Retrying " + countdown(r.retry_until - now), "dim", "retrying")
    if r.terms:
        return Word("%d %s" % (r.terms, "term" if r.terms == 1 else "terms"), "red" if r.terms_holds else "dim", "terms",
                    "terms")
    if r.problems:
        return Word("%d %s" % (r.problems, "problem" if r.problems == 1 else "problems"), "dim", "problems",
                    "problems")
    return Word()


# ---------------------------------------------------------------- Time pill and popover
def renew_text(renew_at: float | None) -> str:
    """`Renew at 09:01`; renew_at = the epoch the daily quota returns (facade.quota.renew_at, the core's own rule)."""
    return "Renew at " + js.clock_text(renew_at) if renew_at else ""


def spaced(n: int) -> str:
    return js.fmt_count(n)


def duration(seconds: float) -> str:
    """`1 h 13 min`, `6 h 04 min`, `45 min`, `2 d` (7.16)."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return "under a minute" if s else "0 min"
    return js.fmt_duration(s)


@dataclass(frozen=True)
class TimeOption:
    per: int
    text: str                  # `1 paragraph per request`
    time: str                  # `≈ 3 h 10 min`
    untested: bool
    selected: bool


@dataclass(frozen=True)
class TimePill:
    visible: bool = False
    text: str = ""             # `≈ 1 h 13 min` | `≈ 6 h 04 min · finishes tomorrow` | `≈ 1 h 03 min left`
    heading: str = ""          # `Chapters 2703-2750`
    options: tuple = ()
    locked: bool = False
    keys: int = 0
    left: int | None = None
    total: int = DAILY_TOTAL
    meter: float = 0.0         # 0..1
    renew: str = ""
    left_text: str = ""        # `1 491 / 4 000`


def time_pill(remaining_blocks: int, per_request: int, pace: float, left_today: int | None, keys: int,
              reach: str, running: bool, left_seconds: float | None, renew_at: float | None,
              total: int | None = None) -> TimePill:
    """`Time` pill and popover data. Hidden when nothing is left to translate (and no job runs). `total`: the
    requests a full day allows over all keys (Quota.capacity); None = the default."""
    if remaining_blocks <= 0 and not running:
        return TimePill()
    total = DAILY_TOTAL if total is None else int(total)
    options = []
    est_selected = None
    for per in PER_REQUEST:
        e = js.estimate(remaining_blocks, per, pace, left_today, total if keys else None)
        txt = "≈ " + duration(e.seconds)
        options.append(TimeOption(per, "%d %s per request" % (per, "paragraph" if per == 1 else "paragraphs"),
                                  txt, bool(UNTESTED.get(per)), per == per_request))
        if per == per_request:
            est_selected = e
    if running and left_seconds is not None:
        text = "≈ %s left" % duration(left_seconds)
    else:
        e = est_selected
        text = "≈ " + duration(e.seconds)
        if e.days > 1:
            text += " · finishes tomorrow"
    meter = 0.0 if not left_today or not total else min(1.0, left_today / total)
    return TimePill(True, text, "Chapters %s" % reach if reach else "Chapters", tuple(options), running, keys,
                    left_today, total, meter, renew_text(renew_at),
                    "%s / %s" % (spaced(left_today) if left_today is not None else "?", spaced(total)))


# ---------------------------------------------------------------- Queue tab
@dataclass(frozen=True)
class QueueRow:
    series: str
    start: str                 # now | ≈ 14:20 | next | then | 09:01
    name: str
    detail: str                # `Book 2 · 12-40 · Ukrainian`
    running: bool = False
    percent: int = 0
    up: bool = False
    down: bool = False
    dont_resume: bool = False  # the head row in a quota wait
    tip: str = ""


@dataclass(frozen=True)
class QueueFacts:
    series: str
    name: str
    book: str
    reach: str
    language: str = ""
    blocks: int = 0            # blocks left to translate, for the clock estimate


def queue_rows(running: QueueFacts | None, percent: int, left_seconds: float | None, items: list,
               restart: bool, quota_wake: float | None, now: float, pace_seconds_per_block: float = 0.0) -> list:
    """Rows of the Queue tab: the running job first, then the queued items (7.16 F7). `items` are QueueFacts in
    queue order. After a restart the start column reads `next` / `then`."""
    rows: list = []
    elapsed = left_seconds or 0.0
    if running is not None:
        quota = quota_wake is not None and quota_wake > now
        rows.append(QueueRow(running.series, js.clock_text(quota_wake) if quota else "now", running.name,
                             _detail(running), True, percent, dont_resume=quota,
                             tip=_tip_row(running)))
        if quota:
            elapsed = quota_wake - now
    for i, it in enumerate(items):
        if restart:
            start = "next" if i == 0 else "then"
        else:
            start = "≈ " + js.clock_text(now + elapsed)
        elapsed += it.blocks * pace_seconds_per_block
        rows.append(QueueRow(it.series, start, it.name, _detail(it), False, 0, up=i > 0,
                             down=i < len(items) - 1, tip=_tip_row(it)))
    return rows


def _detail(f: QueueFacts) -> str:
    return " · ".join(p for p in (f.book, f.reach, f.language) if p)


def _tip_row(f: QueueFacts) -> str:
    return "%s · %s" % (f.name, _detail(f))


def add_to_queue_tip(running_name: str, percent: int, after: list, starts: float | None) -> str:
    """The plain sentence of F7 for the `Add to queue` tooltip."""
    head = "Another series is translating now: %s, %d %% done." % (running_name, percent) if running_name else \
        "A job waits for the daily quota."
    if after:
        names = after[0] if len(after) == 1 else ", ".join(after[:-1]) + " and " + after[-1]
        tail = " This job waits in the queue after %s" % names
    else:
        tail = " This job waits in the queue"
    if starts is not None:
        tail += " and starts at about %s" % js.clock_text(starts)
    return head + tail + "."


def queue_tab_visible(another_runs: bool, waiting: bool, items: int, running: bool) -> bool:
    """The `Queue N` tab shows whenever another series runs or waits or the queue has items (F7)."""
    return another_runs or waiting or items > 0


def queue_count(items: int, running_other: bool) -> int:
    return items + (1 if running_other else 0)


# ---------------------------------------------------------------- tabs, sample, header click
def tabs(problems: int, failed: bool, queue_n: int, queue_visible: bool, sample: bool, unreviewed: int = 0) -> list:
    """[(id, text, tone)]: Chapters always; the others only when there is something (7.16)."""
    out = [("chapters", "Chapters", "normal")]
    if problems:
        out.append(("problems", "Problems %d" % problems, "red" if failed else "normal"))
    if queue_visible:
        out.append(("queue", "Queue %d" % queue_n, "normal"))
    if sample:
        out.append(("sample", "Sample" + (" · %d %s unreviewed" % (unreviewed, "term" if unreviewed == 1 else "terms")
                                           if unreviewed else ""), "normal"))
    return out if len(out) > 1 else []


def sample_label(unreviewed: int) -> str:
    return "Sample · %d unreviewed" % unreviewed if unreviewed else "Sample"


def sample_enabled(job_runs: bool, waiting: bool, keys: bool, language: bool) -> tuple:
    """(enabled, why) of the Sample pill: dim while any job runs or waits, without keys or language."""
    if job_runs or waiting:
        return False, "running"
    if not keys:
        return False, "keys"
    if not language:
        return False, "language"
    return True, ""


def header_click(another_runs_or_waits: bool, own: bool) -> str:
    """`queue` (open Translate on the Queue tab) or `scroll` (scroll the list to the current chapter) (F7)."""
    return "queue" if another_runs_or_waits and not own else "scroll"


# ---------------------------------------------------------------- why a job failed (14.15, until core C6)
def error_kind(error: str, dead=()) -> str:
    """The cause of a failed job from the record's text and the dead key/model pairs of the pool (the core has no
    `reason_kind` until C6): key | model | disk | service | shut | crash | "" (unknown)."""
    text = (error or "").lower()
    reasons = " ".join(dead or ()).lower()
    if "invalid key" in reasons or "invalid key" in text or "key invalid" in text or "api key not valid" in text:
        return "key"
    if "model not found" in reasons or "model not found" in text:
        return "model"
    if "no usable" in text:
        return "nopair"
    if "disk" in text or "no space" in text or "oserror" in text:
        return "disk"
    if "keeps failing" in text:
        return "service"
    if "shut" in text or "refused every request" in text:
        return "shut"
    if text:
        return "crash"
    return ""


def needs_user(job_state: str, kind: str) -> bool:
    """A job that needs the user: it failed on a key or a model the user must fix (7.16: the red pulse)."""
    return job_state == "failed" and kind in ("key", "model")


# ---------------------------------------------------------------- the reach of a selection (7.3)
@dataclass(frozen=True)
class Reach:
    positions: tuple = ()          # the chapters a start really covers
    blocked_at: int | None = None  # the first chapter to translate that has unreviewed terms
    first: bool = False            # ... and it is the first one to translate: nothing can start
    later: bool = False            # ... a later one: the reach is shortened, `Review N terms` sits beside it
    terms: int = 0                 # unreviewed terms of that chapter


def split_reach(selection, translated, gate) -> Reach:
    """`selection`: chapter positions; `translated`: positions that are translated completely; `gate`: {position:
    unreviewed terms}. Only chapters still to translate can be blocked (a translated one is left alone)."""
    sel = sorted(selection)
    todo = [i for i in sel if i not in translated]
    blocked = next((i for i in todo if gate.get(i, 0) > 0), None)
    if blocked is None:
        return Reach(tuple(sel))
    first = not any(i < blocked for i in todo)
    return Reach(() if first else tuple(i for i in sel if i < blocked), blocked, first, not first, gate[blocked])


def job_left(job_chapters, translated, is_toc=lambda i: False) -> list:
    """The chapters of an unfinished job that are not translated yet (what Continue covers); all of them when none
    is left to do."""
    left = [i for i in job_chapters if i not in translated and not is_toc(i)]
    return left or list(job_chapters)
