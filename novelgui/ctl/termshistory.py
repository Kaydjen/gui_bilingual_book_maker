"""Snapshots of the term base before every bulk change (window_spec 14.11, core C17), kept by the window until the core
has its own `terms_history` (C17): in the LOCAL app data folder, keyed by the series, never in the library.

A snapshot is a gzip of the plain terms file with an operation label given by the window (Import, Confirm 8 terms,
Merge, Delete 3 terms, Not a term 2 ...). Kept: the last 30 operation snapshots and 14 daily ones (one per day, taken
with the first change of the day); the snapshots made just before a Restore are never dropped by the cap (audit 28).
Pure files and numbers, no Qt: the base is written by a callback, so the caller decides what "the base now" is.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from pathlib import Path

KEEP_OPS = 30
KEEP_DAYS = 14
KINDS = ("op", "day", "restore")
INDEX = "index.json"


def series_key(series_path) -> str:
    """The folder of one series under the history root: its folder name made safe (the series id waits for C23)."""
    name = Path(series_path).name or "series"
    return re.sub(r"[^\w.\- ]+", "_", name).strip(" .") or "series"


class TermsHistory:
    def __init__(self, folder, clock=time.time):
        self.folder = Path(folder)
        self.clock = clock

    # ------------------------------------------------------------- index
    def _read(self) -> list:
        try:
            raw = json.loads((self.folder / INDEX).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for r in raw if isinstance(raw, list) else []:
            if isinstance(r, dict) and isinstance(r.get("id"), str) and r.get("kind") in KINDS:
                out.append({"id": r["id"], "when": float(r.get("when", 0)), "label": str(r.get("label", "")),
                            "kind": r["kind"]})
        return out

    def _write(self, rows: list) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / (INDEX + ".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.folder / INDEX)

    def list(self) -> list:
        """[(id, when, label, kind)] newest first."""
        rows = sorted(self._read(), key=lambda r: (r["when"], r["id"]), reverse=True)
        return [(r["id"], r["when"], r["label"], r["kind"]) for r in rows]

    # ------------------------------------------------------------- taking and keeping
    def _day(self, t: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(t))

    def _store(self, write, kind: str, label: str, rows: list, now: float) -> dict:
        stamp = "%d-%s" % (int(now * 1000), kind)
        n = 0
        while any(r["id"] == stamp for r in rows):
            n += 1
            stamp = "%d-%s-%d" % (int(now * 1000), kind, n)
        self.folder.mkdir(parents=True, exist_ok=True)
        plain = self.folder / (stamp + ".tmp")
        write(plain)
        target = self.folder / (stamp + ".json.gz")
        with open(plain, "rb") as src, gzip.open(target, "wb", compresslevel=6) as dst:
            dst.write(src.read())
        plain.unlink()
        row = {"id": stamp, "when": now, "label": label, "kind": kind}
        rows.append(row)
        return row

    def snapshot(self, write, label: str, kind: str = "op") -> str:
        """Keep the base as it is now. `write(path)` writes the plain terms file to `path`. Returns the id."""
        now = self.clock()
        rows = self._read()
        row = self._store(write, kind if kind in KINDS else "op", label, rows, now)
        today = self._day(now)
        if kind != "restore" and not any(r["kind"] == "day" and self._day(r["when"]) == today for r in rows):
            self._store(write, "day", "daily", rows, now)
        self._prune(rows)
        self._write(rows)
        return row["id"]

    def _prune(self, rows: list) -> None:
        drop = []
        for kind, keep in (("op", KEEP_OPS), ("day", KEEP_DAYS)):
            mine = sorted((r for r in rows if r["kind"] == kind), key=lambda r: (r["when"], r["id"]), reverse=True)
            drop += mine[keep:]
        for r in drop:
            rows.remove(r)
            try:
                (self.folder / (r["id"] + ".json.gz")).unlink()
            except OSError:
                pass

    # ------------------------------------------------------------- reading back
    def read(self, snap_id: str) -> bytes:
        """The plain terms file of a snapshot; KeyError when it is not there (never a partial answer)."""
        if not any(r["id"] == snap_id for r in self._read()):
            raise KeyError(snap_id)
        try:
            with gzip.open(self.folder / (snap_id + ".json.gz"), "rb") as f:
                return f.read()
        except OSError as exc:
            raise KeyError(snap_id) from exc
