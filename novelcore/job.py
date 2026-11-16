"""One translation job per series: a record on disk, a process lock, resume.

<series>/.state/job.json    the current job: book, range, state, counters, last error, wake time
<series>/.state/run.lock    pid and start time of the process that works on the series
<series>/.state/pool.json   key/model pair states and the shared pause (see pool.py)

The record is advisory: the translations themselves live in the chapter logs, so a lost or damaged
record never loses work. A record in state `running` without a live lock holder is an interrupted job.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .run import Event, Runner, from_ranges, to_ranges
from .store import Series, atomic_write_text

RUNNING, WAITING_QUOTA, STOPPED, FINISHED = "running", "waiting_quota", "stopped", "finished"
WAITING_TERMS, FAILED = "waiting_terms", "failed"
STATES = (RUNNING, WAITING_QUOTA, STOPPED, FINISHED, WAITING_TERMS, FAILED)

STATE_DIR = ".state"
JOB_FILE = "job.json"
LOCK_FILE = "run.lock"
SAVE_EVERY = 3.0  # seconds (job clock) between saves caused by progress alone
LOCK_GRACE = 2.0  # a lock file this young with unreadable content is still being written


class SeriesBusy(RuntimeError):
    """Another process (or another job of this process) is working on the series."""


class JobError(RuntimeError):
    """There is no job to continue, or it cannot be continued."""


# -- process liveness (the only place with a Windows-only call) ---------------
def _win_open(pid: int):
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    return k32, handle, ctypes, wintypes


def _win_alive(pid: int) -> bool:
    k32, handle, ctypes, wintypes = _win_open(pid)
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = wintypes.DWORD()
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def _win_started(pid: int) -> float | None:
    """Epoch when the process was created, or None when unknown."""
    k32, handle, ctypes, wintypes = _win_open(pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return ticks / 1e7 - 11644473600.0
    finally:
        k32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists now."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _win_alive(pid)
        except (OSError, AttributeError, ValueError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _holder_alive(info: dict) -> bool:
    pid = info.get("pid")
    if not pid_alive(pid):
        return False
    started = info.get("started")
    if os.name == "nt" and isinstance(started, (int, float)):
        try:
            created = _win_started(pid)
        except (OSError, AttributeError, ValueError):
            created = None
        if created is not None and created > started + LOCK_GRACE:
            return False  # the pid belongs to a younger process: the old holder is gone
    return True


# -- the lock ------------------------------------------------------------------
def state_dir(series_path) -> Path:
    return Path(series_path) / STATE_DIR


def _read_lock(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def lock_holder(series_path) -> dict | None:
    """{pid, started} of the live process that holds the series, else None (no lock, or a stale one)."""
    info = _read_lock(state_dir(series_path) / LOCK_FILE)
    return info if info and _holder_alive(info) else None


class SeriesLock:
    def __init__(self, series_path, clock=time.time):
        self.dir = state_dir(series_path)
        self.path = self.dir / LOCK_FILE
        self.held = False
        self._now = clock

    def acquire(self) -> None:
        if self.held:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        for _ in range(5):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                info = _read_lock(self.path)
                if info is None:
                    try:
                        young = time.time() - self.path.stat().st_mtime < LOCK_GRACE
                    except OSError:
                        young = False
                    if young:
                        raise SeriesBusy(f"the series is being started by another process ({self.path})") from None
                elif _holder_alive(info):
                    raise SeriesBusy(f"the series is already being translated by process {info.get('pid')} "
                                     f"({self.path})") from None
                try:
                    self.path.unlink()  # stale: its process is gone
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    raise SeriesBusy(f"cannot take over the lock {self.path}: {exc}") from exc
                continue
            try:
                os.write(fd, json.dumps({"pid": os.getpid(), "started": time.time()}).encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            self.held = True
            return
        raise SeriesBusy(f"cannot take the lock {self.path}")

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        info = _read_lock(self.path)
        if info is None or info.get("pid") == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass


# -- the record ------------------------------------------------------------------
def read_job(series_path) -> dict | None:
    """The job record, or None when there is none or the file is damaged."""
    try:
        data = json.loads((state_dir(series_path) / JOB_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("state") not in STATES or not isinstance(data.get("book"), str):
        return None
    return data


def write_job(series_path, rec: dict) -> None:
    path = state_dir(series_path) / JOB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(rec, indent=1, ensure_ascii=False))


def _counts(rec: dict) -> tuple[int, int, int, int]:
    """(blocks done, blocks total, chapters done, chapters total) from the per-chapter figures."""
    chap = rec.get("chapter_blocks")
    done = total = full = 0
    if isinstance(chap, dict):
        for v in chap.values():
            if isinstance(v, list) and len(v) >= 2 and all(isinstance(x, int) for x in v[:2]):
                done += v[0]
                total += v[1]
                full += 1 if v[0] >= v[1] else 0
    chapters = rec.get("chapters_total")
    return done, total, full, chapters if isinstance(chapters, int) else len(chap or {})


def job_status(series_path) -> dict:
    """Cheap read for the window: no EPUB parsing, no pool. `job` is the record or None;
    `interrupted` is True for a `running` record whose process is gone; `running` is True while a live
    process works on the series. Progress is counted from the record: blocks of the chapters seen so far
    (a fresh job learns the totals chapter by chapter), chapters exact."""
    rec = read_job(series_path)
    holder = lock_holder(series_path)
    running = holder is not None and rec is not None and rec["state"] == RUNNING
    done, total, full, chapters = _counts(rec or {})
    return {"job": rec, "interrupted": bool(rec and rec["state"] == RUNNING and holder is None),
            "running": running, "pid": holder.get("pid") if holder else None,
            "blocks_done": done, "blocks_total": total, "chapters_done": full, "chapters_total": chapters,
            "blocks_failed": int(rec.get("blocks_failed") or 0) if rec else 0,
            "terms_pending": int(rec.get("terms_pending") or 0) if rec else 0,
            "blocked_chapter": rec.get("blocked_chapter") if rec else None}


def set_waiting_terms(series_path, count: int) -> dict:
    """Mark the job as waiting for `count` term questions (the rest of that flow is not built yet)."""
    if lock_holder(series_path):
        raise SeriesBusy("the series is being translated; stop it first")
    rec = read_job(series_path)
    if rec is None:
        raise JobError("no job in this series")
    rec.update(state=WAITING_TERMS, terms_pending=max(0, int(count)), wake_at=None, updated=time.time())
    write_job(series_path, rec)
    return rec


def default_gate(series, book_name):
    """The terms gate of the series from novelcore.frontier.gate_for, or None while there is none."""
    try:
        from . import frontier
    except ImportError as exc:
        if getattr(exc, "name", None) in (None, f"{__package__}.frontier"):
            return None
        raise  # the module exists but is broken: never run ungated by accident
    make = getattr(frontier, "gate_for", None)
    return make(series, book_name) if callable(make) else None


# -- the job -----------------------------------------------------------------------
class Job:
    """A Runner plus its record and lock. Same control surface as the Runner for the window:
    start() / stop() / join() / events / drain() / stats."""

    def __init__(self, series, book_name, keys, models, first=0, last=None, *, state_path=None,
                 save_every=SAVE_EVERY, resumed: dict | None = None, chapters=None, gate=None, **runner_kw):
        """`chapters`: a list of chapter indices instead of first..last (first/last then describe its
        extent in the record). `gate`: see Runner; None takes the terms frontier of the series when the
        module offers one, False means no gate."""
        self.series = series
        if state_path is None:
            state_path = series.path / STATE_DIR / "pool.json"
        runner_kw.setdefault("end_on_quota", True)
        if gate is None:
            gate = default_gate(series, book_name)
        self.runner = Runner(series, book_name, keys, models, first, last, state_path=state_path,
                             chapters=chapters, gate=gate, **runner_kw)
        self.clock = self.runner.clock
        self.chapters = self.runner.chapters
        if self.chapters is not None:
            first, last = (self.chapters[0], self.chapters[-1]) if self.chapters else (0, -1)
        self.book_name, self.first, self.last = book_name, first, last
        self.save_every = save_every
        self.lock = SeriesLock(series.path)
        self.runner.listener = self._on_event
        self._rec_lock = threading.RLock()
        self._prev = resumed
        self._rec: dict = {}
        self._saved_at = float("-inf")
        self._finalized = False
        self._thread: threading.Thread | None = None
        self.exception: BaseException | None = None

    # -- surface of the runner
    @property
    def events(self):
        return self.runner.events

    @property
    def stats(self):
        return self.runner.stats

    @property
    def error(self):
        return self.runner.error

    def drain(self) -> list[Event]:
        return self.runner.drain()

    def stop(self) -> None:
        """Finish the requests in flight, record them; the record then says `stopped`."""
        self.runner.stop()

    def join(self, timeout=None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # -- running
    def acquire(self) -> None:
        self.lock.acquire()

    def start(self) -> None:
        """Take the series (SeriesBusy at once if it is taken) and run in a thread."""
        self.acquire()
        self._thread = threading.Thread(target=self._thread_main, name="novelcore-job", daemon=True)
        self._thread.start()

    def run(self) -> dict:
        self.acquire()
        return self._body()

    def _thread_main(self) -> None:
        try:
            self._body()
        except BaseException as exc:  # recorded in the job; the window reads the record and events
            self.exception = exc

    def _body(self) -> dict:
        try:
            self._begin()
            return self.runner.run()
        except BaseException as exc:
            self._crashed(exc)
            raise
        finally:
            self.lock.release()

    # -- record
    def _begin(self) -> None:
        now = self.clock.now()
        prev = self._prev if self._prev and self._prev.get("book") == self.book_name else {}
        s = self.series
        self._rec = {
            "version": 1, "book": self.book_name, "first": self.first, "last": self.last,
            "chapters": to_ranges(self.chapters) if self.chapters is not None else None,
            "state": RUNNING, "per_request": s.per_request, "models": list(self.runner.models),
            "pace": self.runner.pace, "in_flight": self.runner.in_flight,
            "blocks_done": 0, "blocks_total": 0, "blocks_failed": 0,
            "chapters_total": len(self.chapters) if self.chapters is not None else prev.get("chapters_total"),
            "chapter_blocks": dict(prev.get("chapter_blocks") or {}),
            "created": prev.get("created") or now, "updated": now, "started": now, "pid": os.getpid(),
            "wake_at": None, "error": None, "terms_pending": 0, "blocked_chapter": None,
        }
        self._incomplete: set[str] = set()
        self._save(force=True)

    def _save(self, force: bool = False) -> None:
        with self._rec_lock:
            now = self.clock.now()
            if not force and now - self._saved_at < self.save_every:
                return
            rec = self._rec
            done, total, _, _ = _counts(rec)
            rec["blocks_done"], rec["blocks_total"], rec["updated"] = done, total, now
            rec["blocks_failed"] = sum(v[2] for v in rec["chapter_blocks"].values() if len(v) > 2)
            self._saved_at = now
            try:
                write_job(self.series.path, rec)
            except OSError:
                pass  # the record is advisory; a full disk is reported by the run itself

    def _on_event(self, ev: Event) -> None:
        k = ev.kind
        with self._rec_lock:
            rec = self._rec
            if not rec:
                return
            chap = rec["chapter_blocks"]
            if k == "started":
                rec["chapters_total"] = ev.get("selected", ev["pages"])
            elif k == "chapter_started":
                key = str(ev["index"])
                chap[key] = [(chap.get(key) or [0])[0], ev["blocks"], 0]
            elif k == "progress":
                chap[str(ev["index"])] = [ev["done"], ev["total"], ev["failed"]]
            elif k == "chapter_finished":
                chap[str(ev["index"])] = [ev["ok"], ev["blocks"], ev["failed"]]
                if not ev["complete"]:
                    self._incomplete.add(str(ev["index"]))
            elif k == "error":
                rec["error"] = ev["message"]
            elif k == "quota":
                rec["wake_at"] = ev["until"]
            elif k == "done":
                self._finalize()
                return
            else:
                return
            if k in ("error", "quota", "started"):
                self._save(force=True)
            else:
                self._save()

    def _finalize(self) -> None:
        with self._rec_lock:
            if self._finalized or not self._rec:
                return
            self._finalized = True
            r, rec = self.runner, self._rec
            if r.fatal == "disk":
                state = FAILED
            elif r.quota_until is not None:
                state, rec["wake_at"] = WAITING_QUOTA, r.quota_until
            elif r.fatal == "service":
                state = FAILED
            elif r.user_stopped and not self._everything_seen():
                state = STOPPED
            elif r.blocked:
                state = WAITING_TERMS
            else:
                state = FINISHED
            rec["state"] = state
            rec["error"] = r.error if state == FAILED else None
            if state == WAITING_TERMS:
                rec["terms_pending"], rec["blocked_chapter"] = r.blocked["terms"], r.blocked["index"]
                if r.blocked.get("error"):
                    rec["error"] = f"terms check failed: {r.blocked['error']}"
            else:
                rec["terms_pending"], rec["blocked_chapter"] = 0, None
            if state != WAITING_QUOTA:
                rec["wake_at"] = None
            self._save(force=True)
            self.lock.release()

    def _everything_seen(self) -> bool:
        rec = self._rec
        total = rec.get("chapters_total")
        return isinstance(total, int) and len(rec["chapter_blocks"]) >= total and not self._incomplete

    def _crashed(self, exc: BaseException) -> None:
        """The run could not even go on (a broken EPUB, a bug): record it and let the consumers end."""
        with self._rec_lock:
            if self._finalized:
                return
            if not self._rec:
                self._begin()
            self._finalized = True
            self._rec.update(state=FAILED, error=f"{exc.__class__.__name__}: {exc}", wake_at=None)
            self._save(force=True)
        self.runner._emit("error", {"message": self._rec["error"]})
        self.runner._emit("done", self.runner._summary())


def resume(series, keys, models=None, *, force: bool = False, **kw) -> Job:
    """A Job that continues the recorded job of the series: same book and range; finished blocks are
    skipped by the chapter logs. `series` is a Series or a path. Nothing starts until start()/run().
    A `finished` job is refused (JobError) unless `force`."""
    if not isinstance(series, Series):
        series = Series.open(series)
    rec = read_job(series.path)
    if rec is None:
        raise JobError("no job to continue in this series")
    if rec["state"] == FINISHED and not force:
        raise JobError("the job is finished")
    models = list(models or rec.get("models") or [])
    if not models:
        raise JobError("the record has no models; pass models")
    chapters = from_ranges(rec["chapters"]) if isinstance(rec.get("chapters"), list) else None
    return Job(series, rec["book"], keys, models, rec.get("first") or 0, rec.get("last"), resumed=rec,
               chapters=chapters, **kw)
