"""Whether a series or the library may be changed now (window_spec 4.4, 13.6, 13.7). Pure: the caller hands in
what it knows. This is the one place that decides; later steps add the queue and the quota wait of the
window here, so every action that removes or moves something asks the same question.
"""

from __future__ import annotations

RUNNING = "A translation of this series is running."
WAITING = "A translation of this series is waiting for the daily quota."
ELSEWHERE = "Another program is working on this series."
OPERATION = "An export, a scan or an import of this series is in progress."


def op_conflicts(ops, series_path: str, volume: str | None) -> bool:
    """`ops` is a collection of (series path, volume or None); None means the whole series. An operation on
    the same series conflicts when either side names the whole series or both name the same volume."""
    for p, v in ops:
        if p == series_path and (v is None or volume is None or v == volume):
            return True
    return False


def block_reason(view, ops=(), series_path: str = "", volume: str | None = None, extra=()) -> str:
    """The reason (plain words, for a tooltip or a message) why the series, or one volume of it, cannot be
    deleted or removed now; "" when it can. `view` is a jobstate.JobView; `extra` holds further reasons
    already worked out by the caller."""
    if view is not None:
        on_volume = volume is None or not view.book or view.book == volume
        if view.foreign:
            return ELSEWHERE
        if view.state == "running" and on_volume:
            return RUNNING
        if view.state == "waiting_quota" and on_volume:
            return WAITING
    if op_conflicts(ops, series_path, volume):
        return OPERATION
    for r in extra:
        if r:
            return r
    return ""


def library_change_reason(views) -> str:
    """Why the library cannot be changed now: a job of any series runs or waits for the quota."""
    for v in views:
        if v is None:
            continue
        if v.foreign or v.state in ("running", "waiting_quota"):
            return "A translation is running or waiting for the daily quota. Stop it first."
    return ""
