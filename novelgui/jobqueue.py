"""The queue of translations and the rules that move it on (window_spec 7.5, 13.3, 13.8). Pure: no Tk, no core.

An item names a series folder, a volume (the book's file stem) and the chapters; the prompt, the number of blocks
per request and the language are the series' own values when the item starts. One item per series.

The `Scheduler` decides what happens when a job ends or time passes; the window carries the decision out.
Nothing starts by itself after the app starts: a new scheduler is halted until the user acts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    series: str                 # series folder (identifies it, also after a rename)
    book: str                   # volume stem
    spans: tuple = ()           # ((first, last), ...) chapter positions, inclusive
    resume: bool = False        # continue the recorded job of the series instead of starting these chapters
    replace: bool = False       # the user confirmed replacing the series' unfinished job when queueing
    reach: str = ""             # the chapters as the list showed them when it was queued (`2697-2750`)
    retry: tuple = ()           # check findings to translate again: (chapter, block, source hash, text digest);
                                # the core marks them only when the item really starts (window_spec 13.1)

    def indices(self) -> list:
        out: list = []
        for a, b in self.spans:
            out.extend(range(a, b + 1))
        return out

    def to_dict(self) -> dict:
        return {"series": self.series, "book": self.book, "spans": [[a, b] for a, b in self.spans],
                "resume": self.resume, "replace": self.replace, "reach": self.reach,
                "retry": [list(m) for m in self.retry]}


def spans_of(indices) -> tuple:
    out: list = []
    for i in sorted(set(int(x) for x in indices)):
        if out and out[-1][1] == i - 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return tuple(out)


def item_from(d) -> Item | None:
    """An item from its stored form; anything malformed gives None."""
    if not isinstance(d, dict):
        return None
    series, book, spans = d.get("series"), d.get("book"), d.get("spans")
    if not isinstance(series, str) or not series or not isinstance(book, str) or not isinstance(spans, list):
        return None
    clean = []
    for p in spans:
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(x, int) and not isinstance(x, bool)
                                                                      for x in p)) or p[0] > p[1] or p[0] < 0:
            return None
        clean.append((p[0], p[1]))
    reach = d.get("reach")
    marks = []
    for m in d.get("retry") if isinstance(d.get("retry"), list) else []:
        if (isinstance(m, (list, tuple)) and len(m) == 4 and isinstance(m[0], int) and isinstance(m[1], int)
                and isinstance(m[2], str) and isinstance(m[3], str)):
            marks.append((m[0], m[1], m[2], m[3]))
    return Item(series, book, tuple(clean), d.get("resume") is True, d.get("replace") is True,
                reach if isinstance(reach, str) else "", tuple(marks))


class Queue:
    """The waiting items, in order, one per series."""

    def __init__(self, items=()):
        self.items: list = []
        for it in items:
            self.add(it)

    @classmethod
    def from_list(cls, data) -> "Queue":
        items = [item_from(d) for d in data] if isinstance(data, list) else []
        return cls([i for i in items if i is not None])

    def to_list(self) -> list:
        return [i.to_dict() for i in self.items]

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def get(self, series: str) -> Item | None:
        return next((i for i in self.items if i.series == series), None)

    def head(self) -> Item | None:
        return self.items[0] if self.items else None

    def add(self, item: Item) -> Item | None:
        """Queue an item. A series already queued gets its item replaced in place (the caller asked the user);
        the replaced item is returned."""
        for k, old in enumerate(self.items):
            if old.series == item.series:
                self.items[k] = item
                return old
        self.items.append(item)
        return None

    def remove(self, series: str) -> bool:
        n = len(self.items)
        self.items = [i for i in self.items if i.series != series]
        return len(self.items) != n

    def drop_volume(self, series: str, book: str) -> bool:
        n = len(self.items)
        self.items = [i for i in self.items if not (i.series == series and i.book == book)]
        return len(self.items) != n

    def move(self, series: str, delta: int) -> bool:
        for k, it in enumerate(self.items):
            if it.series == series:
                j = k + delta
                if not 0 <= j < len(self.items):
                    return False
                self.items[k], self.items[j] = self.items[j], self.items[k]
                return True
        return False

    def clear(self) -> None:
        self.items = []


@dataclass(frozen=True)
class Action:
    kind: str           # next (start the head item) | resume (continue the job of `series` after the quota wait)
    series: str = ""


@dataclass
class Wait:
    series: str
    wake_at: float


FINISHED, QUOTA, STOPPED, TERMS, FAILED = "finished", "quota", "stopped", "terms", "failed"


class Scheduler:
    """What the queue does next. `halted` is the short name of why it does not go on by itself ("" = it does);
    `why` says it in full. A new scheduler is halted: nothing starts after the app starts."""

    RESTART = "restart"

    def __init__(self, queue: Queue, clock=time.time):
        self.queue = queue
        self.clock = clock
        self.halted = self.RESTART
        self.why = ""
        self.wait: Wait | None = None

    # ---- events
    def user_started(self) -> None:
        """A job was started (by hand, by the queue or by the wake-up): the queue is live again."""
        self.halted, self.why = "", ""

    def job_ended(self, kind: str, series: str = "", wake_at: float | None = None, label: str = "",
                  why: str = "") -> Action | None:
        """A job ended in `kind`. `label` is the header word for a halt (`Terms 12`, `Failed`)."""
        if kind == FINISHED:
            self.wait = None
            if self.halted:
                return None
            return Action("next") if self.queue else None
        if kind == QUOTA and wake_at is not None:
            self.wait = Wait(series, wake_at)
            return None
        self.wait = None
        self.halted = label or {STOPPED: "Stopped", TERMS: "Terms", FAILED: "Failed"}.get(kind, "Stopped")
        self.why = why
        return None

    def tick(self, running: bool) -> Action | None:
        """Time passed. At the quota's return the job that stopped on it is continued (once)."""
        if running or self.wait is None:
            return None
        if self.clock() >= self.wait.wake_at:
            series, self.wait = self.wait.series, None
            return Action("resume", series)
        return None

    def cancel_wait(self, label: str = "Stopped") -> None:
        """Stop during a daily-quota wait: the job becomes stopped and the queue halts."""
        self.wait = None
        self.halted, self.why = label, ""

    def halt(self, label: str, why: str = "") -> None:
        """A start failed or the user stopped: nothing goes on until the user acts."""
        self.wait = None
        self.halted, self.why = label, why

    def continue_queue(self, running: bool) -> Action | None:
        if running or not self.queue:
            return None
        self.halted, self.why = "", ""
        return Action("next")

    def series_gone(self, series: str, book: str | None = None) -> None:
        """A series (or one volume) was deleted or removed: it leaves the queue, a wait on it ends."""
        if book is None:
            self.queue.remove(series)
        else:
            self.queue.drop_volume(series, book)
        if self.wait is not None and self.wait.series == series:
            self.wait = None

    # ---- what the header says while nothing runs
    def status(self) -> str:
        """`Wait 09:01`, a halt word or `Queue 2` after a restart while items wait, else "" (a job that stopped
        is named by its own record, not by the queue)."""
        if self.wait is not None:
            return "Wait " + time.strftime("%H:%M", time.localtime(self.wait.wake_at))
        if self.queue and self.halted:
            return "Queue %d" % len(self.queue) if self.halted == self.RESTART else self.halted
        return ""
