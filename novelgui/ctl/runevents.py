"""Runner events folded into immutable snapshots (review_window_arch D9).

`RunEvents.feed(event)` runs on any thread (the run relay); `take()` on the GUI thread returns a `RunSnapshot`.
Classes of events:
1. absolute state (`progress`, `chapter_started`, `chapter_finished`, `pair`): last wins per key;
2. edges (`block_failed`, `error`, `paused`, `unpaused`, `waiting`, `resumed`): never dropped, queued into the
   next snapshot in order (their effect on the state is applied too);
3. terminal (`done`, `error`, `quota`, `terms`): `feed` answers "urgent", the GUI flushes at once.
`feed` answers "wake" only for the first event after a `take` (the GUI needs one wake per batch), "" otherwise.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import MappingProxyType

ABSOLUTE = frozenset({"progress", "chapter_started", "chapter_finished", "pair"})
EDGES = frozenset({"block_failed", "error", "paused", "unpaused", "waiting", "resumed"})
TERMINAL = frozenset({"done", "error", "quota", "terms"})
WAKE, URGENT = "wake", "urgent"
_EMPTY = MappingProxyType({})


@dataclass(frozen=True)
class RunSnapshot:
    seq: int = 0
    chap: object = field(default_factory=lambda: _EMPTY)    # read-only {chapter: (done, total, failed)}
    changed: frozenset = frozenset()   # chapters whose numbers changed since the previous snapshot
    paused_until: float | None = None
    retry_until: float | None = None
    last_error: str = ""
    pairs: object = field(default_factory=lambda: _EMPTY)   # read-only {label: (state, until, reason)}
    edges: tuple = ()                  # ((kind, data), ...) since the previous snapshot, in order
    terminal: tuple | None = None      # (kind, data) of the last terminal event seen, once
    totals: tuple = (0, 0, 0, 0)       # (blocks done, blocks total, chapters full, chapters)

    @property
    def percent(self) -> int:
        done, total = self.totals[0], self.totals[1]
        return int(done * 100 / total) if total else 0


def _kind_data(ev):
    if isinstance(ev, tuple):
        return ev[0], ev[1]
    return ev.kind, ev.data


class RunEvents:
    def __init__(self, chap=None):
        self._lock = threading.Lock()
        self._chap: dict = {int(k): tuple(v) for k, v in (chap or {}).items()}
        self._changed: set = set()
        self._pairs: dict = {}
        self._edges: list = []
        self._terminal = None
        self.paused_until = None
        self.retry_until = None
        self.last_error = ""
        self._dirty = False
        self._seq = 0
        self._sums = self._recount()

    def _recount(self) -> list:
        done = total = full = 0
        for d, t, _f in self._chap.values():
            done += min(d, t)
            total += t
            full += 1 if t and d >= t else 0
        return [done, total, full]

    def _set(self, i: int, row: tuple) -> None:
        old = self._chap.get(i)
        if old == row:
            return
        s = self._sums
        if old is not None:
            s[0] -= min(old[0], old[1])
            s[1] -= old[1]
            s[2] -= 1 if old[1] and old[0] >= old[1] else 0
        s[0] += min(row[0], row[1])
        s[1] += row[1]
        s[2] += 1 if row[1] and row[0] >= row[1] else 0
        self._chap[i] = row
        self._changed.add(i)

    # ------------------------------------------------------------- any thread
    def feed(self, ev) -> str:
        k, data = _kind_data(ev)
        data = data or {}
        with self._lock:
            if k == "chapter_started":
                if not data.get("toc"):
                    i = int(data["index"])
                    prev = self._chap.get(i)
                    self._set(i, (prev[0] if prev else 0, int(data["blocks"]), prev[2] if prev else 0))
            elif k == "progress":
                self._set(int(data["index"]), (int(data["done"]), int(data["total"]), int(data["failed"])))
            elif k == "chapter_finished":
                if not data.get("toc"):
                    self._set(int(data["index"]), (int(data["ok"]), int(data["blocks"]), int(data["failed"])))
            elif k == "pair":
                self._pairs[str(data.get("label", ""))] = (data.get("state"), data.get("until"), data.get("reason"))
            elif k == "paused":
                if not data.get("abort"):
                    self.paused_until = data.get("until")
            elif k == "unpaused":
                self.paused_until = None
            elif k == "waiting":
                self.retry_until = data.get("until")
            elif k == "resumed":
                self.retry_until = None
            if k == "error":
                self.last_error = str(data.get("message", ""))
            if k in EDGES:
                self._edges.append((k, dict(data)))
            if k in TERMINAL:
                self._terminal = (k, dict(data))
            first = not self._dirty
            self._dirty = True
        if k in TERMINAL:
            return URGENT
        return WAKE if first else ""

    def note_error(self, text: str) -> None:
        with self._lock:
            self.last_error = text

    # ------------------------------------------------------------- live reads (GUI thread)
    def chap(self) -> dict:
        with self._lock:
            return dict(self._chap)

    def chap_view(self):
        """The live table, read-only (cheap; for counts on the GUI thread)."""
        return MappingProxyType(self._chap)

    def totals(self) -> tuple:
        with self._lock:
            return self._sums[0], self._sums[1], self._sums[2], len(self._chap)

    @property
    def dirty(self) -> bool:
        return self._dirty

    def take(self) -> RunSnapshot:
        with self._lock:
            self._seq += 1
            snap = RunSnapshot(self._seq, MappingProxyType(dict(self._chap)), frozenset(self._changed),
                               self.paused_until, self.retry_until, self.last_error,
                               MappingProxyType(dict(self._pairs)), tuple(self._edges), self._terminal,
                               (self._sums[0], self._sums[1], self._sums[2], len(self._chap)))
            self._changed = set()
            self._edges = []
            self._terminal = None
            self._dirty = False
        return snap


@dataclass
class ChapterProgress:
    """The GUI-side table a chapter list shows, diff-applied from snapshots: `apply` returns the changed row
    ranges [(first, last)] so a list model sends one `dataChanged` per range."""
    rows: list = field(default_factory=list)       # [[done, total, failed] | None] per chapter position

    def apply(self, snap: RunSnapshot) -> list:
        rows = self.rows
        n = len(rows)
        changed = sorted(i for i in snap.changed if 0 <= i < n)
        chap = snap.chap
        for i in changed:
            rows[i] = chap[i]
        out: list = []
        for i in changed:
            if out and out[-1][1] == i - 1:
                out[-1][1] = i
            else:
                out.append([i, i])
        return [tuple(r) for r in out]
