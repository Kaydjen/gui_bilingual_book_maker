"""Zone 1 of Translate: the strip of THIS series' running or unfinished job (window_spec 7.6, 7.7, 13.3, 13.4).

Pure. `zone1` says whether the strip is shown, its state chip, its one button (and the second control beside it)
and why a disabled button is disabled. A job that ended `finished` (also with failed blocks) has no strip: the
problem list owns its failed blocks.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import jobstate as js


@dataclass(frozen=True)
class Fault:
    text: str           # short reason for `Failed · <text>`
    kind: str           # key | model | service | disk | other


def fault_of(error: str, dead=()) -> Fault:
    """Classify why a job failed from its record's error text and the reasons of the pool's dead pairs."""
    e = (error or "").strip()
    low = e.lower()
    d = " ".join(str(x) for x in dead).lower()
    if "invalid key" in d:
        return Fault("key invalid", "key")
    if "model not found" in d:
        return Fault("model not found", "model")
    if "no usable key" in low or "api key" in low:
        return Fault("no usable key", "key")
    if "keeps failing" in low:
        return Fault("the service keeps failing", "service")
    if "keep being refused" in low:
        return Fault("requests keep being refused", "service")
    if "disk" in low or "no space" in low or "permission" in low:
        return Fault(e[:60] or "cannot write", "disk")
    return Fault((e.split("\n")[0][:60] or "stopped on an error"), "other")


@dataclass(frozen=True)
class ZoneFacts:
    view: js.JobView
    running_here: bool = False      # a job of this series runs in this window
    stopping: bool = False
    paused_until: float | None = None
    retry_until: float | None = None     # the runner's `waiting` event: a request is being repeated
    now: float = 0.0
    terms_now: int | None = None
    keys: bool = True
    language: bool = True
    another_busy: bool = False      # a job of another series runs, or some job waits for the daily quota
    auto_armed: bool = False        # this window will continue this job by itself when the quota returns
    reach: str = ""                 # the chapters `Continue` will cover, `2731-2750`
    queued_here: bool = False       # this series has a queue item


@dataclass(frozen=True)
class Zone1:
    visible: bool = False
    chip: js.Chip = js.Chip()
    button: str = ""
    action: str = ""            # stop | continue | queue_continue | ""
    enabled: bool = False
    why: str = ""               # keys | language | quota | terms | stopping | foreign
    second: str = ""            # review | settings | stop_wait | ""
    second_text: str = ""
    review_n: int = 0
    discard: bool = False
    fault: Fault | None = None


def continue_label(reach: str, queue: bool) -> str:
    base = "Queue continue" if queue else "Continue"
    return "%s %s" % (base, reach) if reach else base


def zone1(f: ZoneFacts) -> Zone1:
    v = f.view
    if f.running_here:
        if f.stopping:
            chip = js.Chip("Stopping", "dim", "stopping")
        elif f.paused_until is not None and f.paused_until > f.now:
            chip = js.Chip("Paused " + js.countdown_text(f.paused_until - f.now), "dim", "paused")
        elif f.retry_until is not None and f.retry_until > f.now:
            chip = js.Chip("Retrying", "dim", "retrying")
        else:
            chip = js.Chip()
        return Zone1(True, chip, "Stop", "stop", not f.stopping, "stopping" if f.stopping else "")
    if v.foreign:
        return Zone1(True, js.Chip("Running elsewhere", "dim", "elsewhere"), "", "", False, "foreign")
    if not v.unfinished:
        return Zone1(False)

    action = "queue_continue" if f.another_busy else "continue"
    button = continue_label(f.reach, f.another_busy)
    st = v.state
    fault = fault_of(v.error, v.dead) if st == "failed" else None
    enabled, why = True, ""
    second, second_text, review_n = "", "", 0
    chip = js.chip_for(v, False, False, None, f.now, f.terms_now)

    if st == "waiting_quota":
        back = v.wake_at is not None and f.now >= v.wake_at
        if not back:
            enabled, why = False, "quota"
        if f.auto_armed and not back:
            second, second_text = "stop_wait", "Stop"
    elif st == "waiting_terms":
        n = js.terms_count(v, f.terms_now)
        if n > 0:
            enabled, why = False, "terms"
            second, second_text, review_n = "review", "Review %d terms" % n, n
    elif st == "failed":
        chip = js.Chip("Failed · " + fault.text, "plain", "failed")
        if fault.kind in ("key", "model"):
            second, second_text = "settings", "Settings"
    if enabled and not f.keys:
        enabled, why = False, "keys"
    if enabled and not f.language:
        enabled, why = False, "language"
    return Zone1(True, chip, button, action, enabled, why, second, second_text, review_n, True, fault)
