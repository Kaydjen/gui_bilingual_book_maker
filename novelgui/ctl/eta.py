"""Time left of a run: measured speed of this run -> remaining blocks -> a rounded human value.

It feeds the Translate `Time` pill and the tray line. Pure functions: no clock of their own.
"""

from __future__ import annotations

import math

MIN_BLOCKS = 3          # fewer blocks done in this run: no estimate yet
MIN_SECONDS = 20.0      # shorter than this: no estimate yet


def time_left(done_in_run: int, active_seconds: float, remaining: int) -> float | None:
    """Seconds left at the speed measured in this run; None while too little is measured. `active_seconds`
    is the run's working time (waits for the daily quota left out); `remaining` blocks still to translate."""
    if remaining <= 0:
        return 0.0
    if done_in_run < MIN_BLOCKS or active_seconds < MIN_SECONDS:
        return None
    speed = done_in_run / active_seconds
    return remaining / speed if speed > 0 else None


def human_left(seconds: float | None) -> str:
    """`under a minute`, `about 7 min`, `about 40 min`, `about 1.5 h`, `about 2 h`, `about 13 h`, `about 3 days`;
    "" when unknown."""
    if seconds is None or seconds < 0 or math.isnan(seconds):
        return ""
    if seconds < 60:
        return "under a minute"
    minutes = seconds / 60
    if minutes < 10:
        return "about %d min" % max(1, round(minutes))
    if minutes < 57.5:
        return "about %d min" % (5 * round(minutes / 5))
    hours = minutes / 60
    if hours < 9.75:
        half = round(hours * 2) / 2
        return "about %s h" % (("%d" % half) if half == int(half) else ("%.1f" % half))
    if hours < 47.5:
        return "about %d h" % round(hours)
    return "about %d days" % round(hours / 24)


def run_left(done_in_run: int, active_seconds: float, remaining: int) -> str:
    """`human_left(time_left(...))`: the text of the `Time` pill ("" while unknown)."""
    return human_left(time_left(done_in_run, active_seconds, remaining))
