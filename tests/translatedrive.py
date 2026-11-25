"""Drives the Translate screen's states in a scene (tests/shellfactory.py registers `Drive.extras()` as the scene's `py` actions):
the REAL RunControl, view-models and lanes of the window, but its runner is not started (`data["norun"]`: `submit` is a stub and
the service address points at a port nobody listens on), so a run state is reached by feeding the events the runner would send,
exactly as tests/test_translate_vm.py does. Plain JSON arguments only (a scene action carries nothing else)."""

from __future__ import annotations

import time
from pathlib import Path

from tests import translatedemo as demo


def settle(parts, seconds: float = 8.0) -> None:
    """Pump events until the lanes, the helper process and the screen's own timers are quiet."""
    from PySide6.QtCore import QCoreApplication
    vm = parts.translate_vm
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if parts.lanes.idle() and not vm._sync_t.isActive() and parts.crunch.idle_now():
            QCoreApplication.processEvents()
            break
        time.sleep(0.01)
    end = time.monotonic() + 0.15
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


class Drive:
    def __init__(self, parts, lib: Path, keys: list):
        self.parts, self.lib, self.keys = parts, Path(lib), keys
        self.rc, self.vm, self.app, self.books = parts.run, parts.translate_vm, parts.app, parts.books_vm
        self.run = None

    @property
    def path(self) -> str:
        return str(self.lib / "Knights")

    def settle(self) -> bool:
        settle(self.parts)
        return True

    # ---- a job that runs in this window
    def begin(self, positions=None, series="Knights", book="Book 1", numbers=None) -> bool:
        from novelgui.ctl import runcontrol
        rc = self.rc
        path = str(self.lib / series)
        if numbers:
            positions = list(range(demo.position(numbers[0]), demo.position(numbers[1]) + 1))
        elif positions is not None:
            positions = list(positions)
        else:
            positions = list(self.books.terms_context()[2])
        run = runcontrol.Run("job", path, series, book, positions, False, rc.clock)
        rc._prepare_chap(run)
        rc.run = run
        rc.last_series = path
        rc.sched.user_started()
        rc._changed()
        self.vm.runs_changed(starting=True)
        self.run = run
        self.settle()
        return True

    def feed(self, kind: str, data=None) -> bool:
        self.run.events.feed((kind, dict(data or {})))
        return True

    def progress(self, number: int, done: int, total: int = 3, failed: int = 0) -> bool:
        self.feed("progress", {"index": demo.position(number), "done": done, "total": total, "failed": failed})
        self.rc._flush_progress()
        self.settle()
        return True

    def retry_wait(self, seconds: int) -> bool:
        self.feed("waiting", {"until": self.rc.clock() + seconds, "reason": "503"})
        return True

    def pause_wait(self, seconds: int) -> bool:
        self.feed("paused", {"until": self.rc.clock() + seconds})
        return True

    def stop(self) -> bool:
        self.vm.act("stop")
        return True

    def end(self, state: str = "stopped", numbers=None, **rec) -> bool:
        run = self.run
        positions = range(demo.position(numbers[0]), demo.position(numbers[1]) + 1) if numbers else run.chapters
        demo.write_record(run.series, run.book, state, positions, **rec)
        self.rc._done(run, {"stopped": False})
        self.settle()
        return True

    # ---- records on disk
    def record(self, state: str, first: int, last: int, extra=None) -> bool:
        """A job record of the chapters first..last (title numbers) in this state; `extra` = more fields of the record
        (`seconds` of a quota wait, `blocked` = title number of the chapter that waits for terms, `series`, `book`)."""
        kw = dict(extra or {})
        series, book = kw.pop("series", "Knights"), kw.pop("book", "Book 1")
        if state == "waiting_quota":
            kw["wake_at"] = time.time() + kw.pop("seconds", 3600)
        if "blocked" in kw:
            kw["blocked_chapter"] = demo.position(kw.pop("blocked"))
        demo.write_record(str(self.lib / series), book, state, range(demo.position(first), demo.position(last) + 1), **kw)
        self.vm._load_series()
        self.settle()
        return True

    def hold_check(self, percent: int) -> bool:
        """The look of a running check (the check itself runs in the helper process and ends too fast to be shot)."""
        self.vm._checking, self.vm._check_pct = True, percent / 100.0
        self.vm._compute_bar()
        self.vm.checkChanged.emit()
        return True

    def dead_key(self) -> bool:
        demo.write_dead_key(self.path, self.keys[0])
        return True

    def foreign(self) -> bool:
        from novelgui.facade import run as frun
        real = frun.job_view

        def other(path):
            v = real(path)
            return v if Path(path).name != "Knights" else type(v)("running", "Book 1", tuple(range(1, 30)), foreign=True)

        frun.job_view = other
        self.vm._load_series(job_only=True)
        self.settle()
        return True

    # ---- the queue
    def enqueue(self, series: str, book: str, first: int, last: int, reach: str) -> bool:
        from novelgui import jobqueue as jq
        self.rc.enqueue(jq.Item(str(self.lib / series), book, ((first, last),), False, False, reach))
        self.settle()
        return True

    def quota_wait(self, series: str, seconds: int) -> bool:
        from novelgui import jobqueue as jq
        self.rc.sched.user_started()
        self.rc.sched.wait = jq.Wait(str(self.lib / series), self.rc.clock() + seconds)
        self.vm._recompute()
        self.settle()
        return True

    def stuck(self, series: str, book: str) -> bool:
        from novelgui import jobqueue as jq
        from PySide6.QtCore import QCoreApplication
        self.rc.enqueue(jq.Item(str(self.lib / series), book, ((1, 5),), False, False, "x"))
        self.rc.continue_queue()
        end = time.monotonic() + 8
        while time.monotonic() < end and self.rc.sched.halted != "Stopped":
            QCoreApplication.processEvents()
            time.sleep(0.01)
        self.vm._recompute()
        self.settle()
        return True

    # ---- the sample
    def sample_start(self) -> bool:
        self.vm.sample()
        self.settle()
        return True

    def sample_progress(self, done: int, total: int = 50) -> bool:
        self.rc.run.sample = (done, total)
        self.rc._flush_progress()
        return True

    def sample_write(self, number: int, texts) -> bool:
        """The answers of a sample of one chapter (what the run would have written to the sample log): the first blocks get
        these translations, a null leaves a block unanswered."""
        from novelcore import Series
        series = Series.open(self.path)
        pos = demo.position(number)
        with series.open_book("Book 1") as b:
            ch = b.chapters[pos]
            recs = [{"i": blk.index, "src_sha": blk.sha, "status": "ok", "text": t, "at": 1.0, "model": "m", "flags": []}
                    for blk, t in zip(b.blocks(ch), texts) if t]
            series.sample_log("Book 1", ch).append(recs)
        return True

    def sample_end(self) -> bool:
        from PySide6.QtCore import QCoreApplication
        self.rc._done(self.rc.run, {"stopped": False})
        end = time.monotonic() + 8
        while time.monotonic() < end and self.vm.sampleResult.get("pending", True):
            QCoreApplication.processEvents()
            time.sleep(0.01)
        self.settle()
        return True

    def extras(self) -> dict:
        names = ("settle", "begin", "feed", "progress", "retry_wait", "pause_wait", "stop", "end", "record", "dead_key",
                 "hold_check", "foreign", "enqueue", "quota_wait", "stuck", "sample_start", "sample_progress", "sample_write", "sample_end")
        return {"tr_" + n: getattr(self, n) for n in names}
