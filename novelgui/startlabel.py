"""Zone 2 of Translate: the one start button and what stands beside it (window_spec 7.3, 7.4, 13.8).

The label is always a verb plus the chapters it will really cover. Pure: the caller hands in what it knows.

kind: translate | queue | replace | queue_replace | none | review | add_keys
`review` and `none` have no start button of their own (`text` is empty); `review` shows only `Review N terms`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StartFacts:
    has_series: bool = True
    selected: bool = True           # the chapter selection is not empty
    reach: str = ""                 # the chapters the job will really cover, as `2697-2730` ("" = not known)
    first_blocked: bool = False     # the first chosen chapter has unreviewed terms
    later_blocked: bool = False     # a later chosen chapter has them: the reach is shortened
    review_n: int = 0               # unreviewed terms that hold the job back
    translated: bool = False        # the selection is translated completely already
    keys: bool = True
    language: bool = True
    something_runs: bool = False    # a job of any series runs now (or another program works on a series)
    sample_runs: bool = False
    quota_waiting: bool = False     # some job waits for the daily quota
    quota_back: str = ""            # local time the quota returns, `09:01`
    own_unfinished: bool = False    # this series has a stopped / interrupted / waiting / failed job (not running)
    own_running: bool = False       # this series' job runs in this window
    own_same: bool = False          # the selection is exactly the chapters of that job
    foreign: bool = False           # another program works on this series


@dataclass(frozen=True)
class Start:
    kind: str
    text: str = ""
    enabled: bool = False
    why: str = ""               # tooltip key when disabled: selection | language | done | sample | foreign
    review: int = 0             # `Review N terms` beside the button (0 = none)
    confirm: bool = False       # a click confirms replacing the unfinished job at once
    queue: bool = False         # a click adds a queue item instead of starting
    quota_back: str = ""        # for the tooltip of `Add to queue` while the quota is used up

    @property
    def has_button(self) -> bool:
        return bool(self.text)


def label(verb: str, reach: str) -> str:
    return "%s · %s" % (verb, reach) if reach else verb


def choose(f: StartFacts) -> Start:
    """The start button of the selected chapters."""
    if not f.has_series or not f.selected:
        return Start("translate", "Translate", False, "selection")
    if not f.keys:
        return Start("add_keys", "Add keys", True)
    if f.own_same and (f.own_unfinished or f.own_running):
        return Start("none")                    # zone 1 continues that job
    if f.first_blocked and f.review_n:
        return Start("review", "", False, review=f.review_n)
    review = f.review_n if f.later_blocked else 0
    queued = f.something_runs or f.quota_waiting
    replace = f.own_unfinished and not f.own_running
    if queued:
        kind = "queue_replace" if replace else "queue"
        text = label("Queue · replace job" if replace else "Add to queue", f.reach)
    elif replace:
        kind, text = "replace", label("Replace job", f.reach)
    else:
        kind, text = "translate", label("Translate", f.reach)
    why = ""
    if f.foreign:
        why = "foreign"
    elif not f.language:
        why = "language"
    elif f.sample_runs:
        why = "sample"
    elif f.translated:
        why = "done"
    return Start(kind, text, not why, why, review, confirm=replace, queue=queued,
                 quota_back=f.quota_back if f.quota_waiting else "")
