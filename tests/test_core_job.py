import contextlib
import errno
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from novelcore import Series, gemini
from novelcore import __main__ as cli
from novelcore.job import (FAILED, FINISHED, RUNNING, STOPPED, WAITING_QUOTA, WAITING_TERMS, Job, JobError,
                           SeriesBusy, SeriesLock, job_status, lock_holder, pid_alive, read_job, resume,
                           set_waiting_terms, state_dir, write_job)
from novelcore.pool import DAY, Pool, QuotaExhausted, clean_pace, day_return
from novelcore.run import Runner, from_ranges, to_ranges
from novelcore.store import ChapterLog, atomic_write_text
from tests.core_support import KEYS, MODEL, CoreCase
from tests.fake_api import FakeClock

ROOT = Path(__file__).resolve().parents[1]
START = 1_760_000_000.0


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def write_lock(series_path, pid: int, started: float | None = None) -> Path:
    path = state_dir(series_path) / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "started": started or time.time()}), encoding="utf-8")
    return path


class JobCase(CoreCase):
    api_args = {"poll_interval": 0.02}  # a quick server shutdown after each test

    def job(self, keys=None, models=(MODEL,), first=0, last=None, **kw):
        kw.setdefault("rpm", {m: 15 for m in models})
        kw.setdefault("gate", False)  # these tests are about the job, not about reviewed terms
        return Job(self.series, self.book, keys or self.keys, list(models), first, last, clock=self.clock,
                   base_url=self.api.base_url, **kw)

    def lock_path(self) -> Path:
        return state_dir(self.series.path) / "run.lock"

    def stopping_generate(self, holder, after: int, seen: threading.Event):
        calls = [0]
        lock = threading.Lock()

        def generate(*a, **kw):
            res = gemini.generate(*a, **kw)
            with lock:
                calls[0] += 1
                if calls[0] == after:
                    seen.set()
            return res

        return generate

    def ok_records(self):
        recs = []
        for f in (self.series.path / "chapters").rglob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r["status"] == "ok":
                    recs.append((str(f), r["i"], r["src_sha"]))
        return recs


class RecordTest(JobCase):
    chapters = 4
    paras = 8
    per_request = 2

    def test_no_record_and_damaged_record_read_as_no_job(self):
        st = job_status(self.series.path)
        self.assertIsNone(st["job"])
        self.assertFalse(st["interrupted"])
        (state_dir(self.series.path)).mkdir(parents=True, exist_ok=True)
        (state_dir(self.series.path) / "job.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(read_job(self.series.path))
        (state_dir(self.series.path) / "job.json").write_text('{"state": "bogus", "book": "x"}', encoding="utf-8")
        self.assertIsNone(job_status(self.series.path)["job"])
        (state_dir(self.series.path) / "job.json").write_bytes(b"")
        self.assertIsNone(read_job(self.series.path))

    def test_record_of_a_finished_run(self):
        job = self.job(first=1, last=3)
        summary = job.run()
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], FINISHED)
        self.assertEqual((rec["book"], rec["first"], rec["last"]), (self.book, 1, 3))
        self.assertEqual(rec["models"], [MODEL])
        self.assertEqual(rec["per_request"], 2)
        self.assertEqual((rec["blocks_done"], rec["blocks_total"]), (24, 24))
        self.assertEqual(summary["blocks"]["ok"], 24)
        self.assertGreaterEqual(rec["updated"], rec["created"])
        self.assertIsNone(rec["error"])
        self.assertIsNone(rec["wake_at"])
        st = job_status(self.series.path)
        self.assertFalse(st["interrupted"])
        self.assertFalse(st["running"])
        self.assertEqual((st["blocks_done"], st["blocks_total"], st["chapters_done"], st["chapters_total"]),
                         (24, 24, 3, 3))
        self.assertFalse(self.lock_path().exists())
        self.assertEqual([p.name for p in state_dir(self.series.path).glob("*.tmp")], [])
        self.assertEqual(read_job(self.series.path)["version"], 1)

    def test_running_record_without_a_process_is_interrupted(self):
        write_job(self.series.path, {"version": 1, "book": self.book, "first": 0, "last": None, "state": RUNNING,
                                     "chapter_blocks": {"0": [3, 8, 0]}, "chapters_total": 4})
        st = job_status(self.series.path)
        self.assertTrue(st["interrupted"])
        self.assertFalse(st["running"])
        self.assertEqual((st["blocks_done"], st["blocks_total"]), (3, 8))
        write_lock(self.series.path, dead_pid())
        self.assertTrue(job_status(self.series.path)["interrupted"])
        write_lock(self.series.path, os.getpid())
        st = job_status(self.series.path)
        self.assertFalse(st["interrupted"])
        self.assertTrue(st["running"])
        self.assertEqual(st["pid"], os.getpid())

    def test_running_record_while_the_job_works(self):
        seen = threading.Event()
        gate = threading.Event()
        calls = [0]

        def generate(*a, **kw):
            res = gemini.generate(*a, **kw)
            calls[0] += 1
            if calls[0] == 3:
                seen.set()
                gate.wait(10)
            return res

        job = self.job(generate=generate, save_every=0.0)
        job.start()
        try:
            self.assertTrue(seen.wait(10))
            st = job_status(self.series.path)
            self.assertEqual(st["job"]["state"], RUNNING)
            self.assertTrue(st["running"])
            self.assertFalse(st["interrupted"])
            self.assertEqual(st["chapters_total"], 4)
        finally:
            gate.set()
        job.join(20)
        self.assertEqual(read_job(self.series.path)["state"], FINISHED)

    def test_waiting_terms_state_with_a_count(self):
        self.job().run()
        rec = set_waiting_terms(self.series.path, 7)
        self.assertEqual((rec["state"], rec["terms_pending"]), (WAITING_TERMS, 7))
        self.assertEqual(read_job(self.series.path)["terms_pending"], 7)
        self.assertFalse(job_status(self.series.path)["interrupted"])
        write_lock(self.series.path, os.getpid())
        with self.assertRaises(SeriesBusy):
            set_waiting_terms(self.series.path, 1)
        self.lock_path().unlink()
        # nothing to mark without a record
        os.unlink(state_dir(self.series.path) / "job.json")
        with self.assertRaises(JobError):
            set_waiting_terms(self.series.path, 1)

    def test_a_broken_run_is_recorded_as_failed(self):
        job = Job(self.series, "No Such Book", self.keys, [MODEL], clock=self.clock, base_url=self.api.base_url)
        with self.assertRaises(ValueError):
            job.run()
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], FAILED)
        self.assertIn("No Such Book", rec["error"])
        self.assertFalse(self.lock_path().exists())
        kinds = [e.kind for e in job.drain()]
        self.assertEqual(kinds[-2:], ["error", "done"])


class AtomicWriteTest(unittest.TestCase):
    def test_flush_fsync_then_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.json"
            order = []
            real_fsync, real_replace = os.fsync, os.replace
            with mock.patch("os.fsync", side_effect=lambda fd: (order.append("fsync"), real_fsync(fd))[1]), \
                    mock.patch("os.replace", side_effect=lambda a, b: (order.append("replace"), real_replace(a, b))[1]):
                atomic_write_text(target, "one")
            self.assertEqual(order, ["fsync", "replace"])
            self.assertEqual(target.read_text(encoding="utf-8"), "one")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["a.json"])

    def test_failure_keeps_the_old_file_and_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.json"
            atomic_write_text(target, "old")
            with mock.patch("os.fsync", side_effect=OSError(errno.ENOSPC, "no space")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new")
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["a.json"])

    @unittest.skipUnless(os.name == "nt", "the retry is for Windows")
    def test_replace_is_retried_on_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.json"
            real, fails = os.replace, [2]

            def flaky(a, b):
                if fails[0]:
                    fails[0] -= 1
                    raise PermissionError(13, "in use")
                return real(a, b)

            with mock.patch("os.replace", side_effect=flaky):
                atomic_write_text(target, "x")
            self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_series_settings_use_the_atomic_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            series = Series.create(tmp, "S")
            order = []
            real_fsync, real_replace = os.fsync, os.replace
            with mock.patch("os.fsync", side_effect=lambda fd: (order.append("fsync"), real_fsync(fd))[1]), \
                    mock.patch("os.replace", side_effect=lambda a, b: (order.append("replace"), real_replace(a, b))[1]):
                series.settings["per_request"] = 7
                series.save_settings()
            self.assertEqual(order, ["fsync", "replace"])
            self.assertEqual(Series.open(series.path).per_request, 7)
            self.assertEqual([p.name for p in series.path.glob("*.tmp")] + [p.name for p in series.path.glob(".*.tmp")], [])


class SettingsDefaultsTest(JobCase):
    def test_pace_and_in_flight_default_to_not_set(self):
        self.assertIsNone(self.series.settings["pace"])
        self.assertIsNone(self.series.settings["in_flight"])
        self.assertEqual(clean_pace(None), 24)
        r = self.runner()
        self.assertEqual((r.pace, r.in_flight), (24, 12))
        self.series.settings.update(pace=30, in_flight=5)
        self.series.save_settings()
        r2 = self.runner()
        self.assertEqual((r2.pace, r2.in_flight), (30, 5))
        reopened = Series.open(self.series.path)
        self.assertEqual((reopened.settings["pace"], reopened.settings["in_flight"]), (30, 5))
        r3 = self.runner(pace=60, in_flight=2)  # arguments win over the series
        self.assertEqual((r3.pace, r3.in_flight), (60, 2))

    def test_old_series_json_without_the_keys_loads(self):
        data = json.loads((self.series.path / "series.json").read_text(encoding="utf-8"))
        data.pop("pace")
        data.pop("in_flight")
        (self.series.path / "series.json").write_text(json.dumps(data), encoding="utf-8")
        s = Series.open(self.series.path)
        self.assertIsNone(s.settings["pace"])


class LockTest(JobCase):
    chapters = 2
    paras = 4
    per_request = 2

    def test_pid_alive(self):
        self.assertTrue(pid_alive(os.getpid()))
        self.assertFalse(pid_alive(dead_pid()))
        self.assertFalse(pid_alive(0))
        self.assertFalse(pid_alive(-5))

    def test_second_job_on_the_same_series_is_refused(self):
        first = self.job()
        first.acquire()
        self.assertEqual(lock_holder(self.series.path)["pid"], os.getpid())
        second = self.job()
        with self.assertRaises(SeriesBusy) as cm:
            second.start()
        self.assertIn(str(os.getpid()), str(cm.exception))
        with self.assertRaises(SeriesBusy):
            second.run()
        self.assertEqual(self.api.log, [])  # nothing was sent
        first.lock.release()
        self.assertIsNone(lock_holder(self.series.path))
        second.run()  # now free
        self.assertEqual(self.count_done(), (8, 8))

    def test_stale_lock_is_taken_over_and_released(self):
        write_lock(self.series.path, dead_pid())
        self.assertIsNone(lock_holder(self.series.path))
        self.job().run()
        self.assertFalse(self.lock_path().exists())
        self.assertEqual(read_job(self.series.path)["state"], FINISHED)

    def test_unreadable_old_lock_is_stale_but_a_fresh_one_is_not(self):
        path = self.lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        with self.assertRaises(SeriesBusy):  # just created: its owner may still be writing it
            SeriesLock(self.series.path).acquire()
        old = time.time() - 60
        os.utime(path, (old, old))
        lock = SeriesLock(self.series.path)
        lock.acquire()
        self.assertTrue(lock.held)
        lock.release()
        self.assertFalse(path.exists())

    def test_release_does_not_remove_a_lock_of_another_process(self):
        lock = SeriesLock(self.series.path)
        lock.acquire()
        write_lock(self.series.path, os.getpid() + 100000)
        lock.release()
        self.assertTrue(self.lock_path().exists())

    @unittest.skipUnless(os.name == "nt", "process creation time is read on Windows")
    def test_pid_reused_by_a_younger_process_is_stale(self):
        write_lock(self.series.path, os.getpid(), started=1.0)  # this process is younger than the lock
        self.assertIsNone(lock_holder(self.series.path))
        write_lock(self.series.path, os.getpid())
        self.assertIsNotNone(lock_holder(self.series.path))

    def test_lock_released_after_stop(self):
        seen = threading.Event()
        job = self.job(generate=self.stopping_generate(None, 1, seen))
        job.start()
        self.assertTrue(seen.wait(10))
        job.stop()
        job.join(20)
        self.assertFalse(self.lock_path().exists())


class ResumeTest(JobCase):
    chapters = 4
    paras = 8
    per_request = 2

    def run_and_stop(self, after=6, **kw):
        seen = threading.Event()
        job = self.job(generate=self.stopping_generate(None, after, seen), **kw)
        job.start()
        self.assertTrue(seen.wait(20))
        job.stop()
        job.join(20)
        self.assertFalse(job._thread.is_alive())
        return job

    def test_stop_then_resume_repeats_no_block(self):
        job = self.run_and_stop()
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], STOPPED)
        self.assertFalse(self.lock_path().exists())
        done, total = self.count_done()
        self.assertTrue(0 < done < total, (done, total))
        st = job_status(self.series.path)
        self.assertFalse(st["interrupted"])
        self.assertEqual((st["blocks_total"], st["chapters_total"]), (32, 4))
        self.assertTrue(0 < st["blocks_done"] < 32)
        sent = len(self.api.log)
        job2 = resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15})
        summary = job2.run()
        self.assertEqual(self.count_done(), (32, 32))
        rec2 = read_job(self.series.path)
        self.assertEqual(rec2["state"], FINISHED)
        self.assertEqual(rec2["created"], rec["created"])
        self.assertEqual((rec2["blocks_done"], rec2["blocks_total"]), (32, 32))
        texts = [t for e in self.api.log for t in e["texts"]]
        self.assertEqual(len(texts), len(set(texts)), "a block was sent twice")
        self.assertEqual(len(self.api.log), 16)  # 32 blocks, 2 per request, each asked once
        self.assertGreater(len(self.api.log), sent)
        self.assertEqual(summary["blocks"]["ok"], len(self.ok_records()) - done)  # this run did the rest
        self.assertEqual(len(self.ok_records()), len(set(self.ok_records())))
        # a finished job has nothing to resume
        with self.assertRaises(JobError):
            resume(self.series, self.keys)

    def test_resume_without_a_record_or_with_a_range(self):
        with self.assertRaises(JobError):
            resume(self.series, self.keys)
        job = self.job(first=1, last=2)
        seen = threading.Event()
        job.runner.requester.generate = self.stopping_generate(None, 2, seen)
        job.start()
        self.assertTrue(seen.wait(20))
        job.stop()
        job.join(20)
        again = resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15})
        self.assertEqual((again.first, again.last, again.book_name), (1, 2, self.book))
        self.assertEqual(again.runner.models, [MODEL])
        again.run()
        done = {i for _, i, _ in self.ok_records()}
        self.assertEqual(len(self.ok_records()), 16)  # chapters 1 and 2 only
        self.assertEqual(done, set(range(8)))
        self.assertFalse((self.series.path / "chapters" / self.book / "00000_c0.jsonl").exists())

    def test_crash_left_a_running_record_and_a_stale_lock(self):
        self.run_and_stop(after=5)
        before = self.count_done()[0]
        rec = read_job(self.series.path)
        rec["state"] = RUNNING  # as if the process had died instead of stopping
        write_job(self.series.path, rec)
        write_lock(self.series.path, dead_pid())
        st = job_status(self.series.path)
        self.assertTrue(st["interrupted"])
        log_len = len(self.api.log)
        resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15}).run()
        self.assertEqual(self.count_done(), (32, 32))
        self.assertGreater(len(self.api.log), log_len)
        self.assertEqual(read_job(self.series.path)["state"], FINISHED)
        self.assertFalse(self.lock_path().exists())
        self.assertGreater(before, 0)
        texts = [t for e in self.api.log for t in e["texts"]]
        self.assertEqual(len(texts), len(set(texts)))


class HardKillTest(JobCase):
    chapters = 4
    paras = 8
    per_request = 2
    api_args = {"latency": 0.25, "poll_interval": 0.02}

    CHILD = (
        "import json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from novelcore import Series\n"
        "from novelcore.job import Job\n"
        "series = Series.open(sys.argv[2])\n"
        "Job(series, sys.argv[3], json.loads(sys.argv[5]), [sys.argv[6]], pace=120, base_url=sys.argv[4],\n"
        "    rpm={sys.argv[6]: 120}).run()\n"
    )

    def test_killed_process_is_resumed_without_repeats(self):
        child = self.dir / "child.py"
        child.write_text(self.CHILD, encoding="utf-8")
        env = dict(os.environ, PYTHONUTF8="1")
        proc = subprocess.Popen([sys.executable, str(child), str(ROOT), str(self.series.path), self.book,
                                 self.api.base_url, json.dumps(self.keys), MODEL], env=env)
        try:
            deadline = time.time() + 30
            while len(self.api.log) < 4 and time.time() < deadline and proc.poll() is None:
                time.sleep(0.02)
            self.assertIsNone(proc.poll(), "the child ended before it could be killed")
            proc.kill()
        finally:
            proc.kill()
            proc.wait(10)
        time.sleep(0.5)  # requests in flight at the kill are still answered by the fake server
        sent = len(self.api.log)
        self.assertTrue(self.lock_path().exists(), "a hard kill leaves the lock behind")
        series = Series.open(self.series.path)
        st = job_status(series.path)
        self.assertTrue(st["interrupted"])
        self.assertEqual(st["job"]["state"], RUNNING)
        by_sha = {blk.sha: blk.text for _, blk in self.all_blocks()}
        done_before = {sha for _, _, sha in self.ok_records()}
        self.assertTrue(0 < len(done_before) < 32, len(done_before))
        job = resume(series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15})
        job.run()
        after = [t for e in self.api.log[sent:] for t in e["texts"]]
        self.assertFalse(set(after) & {by_sha[s] for s in done_before}, "a finished block was sent again")
        self.assertEqual(len(after), len(set(after)))
        recs = self.ok_records()
        self.assertEqual(len(recs), 32)
        self.assertEqual(len(recs), len(set(recs)), "a block has two finished records")
        self.assertEqual(Series.open(self.series.path).find_done(next(iter(done_before)))["status"], "ok")
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], FINISHED)
        self.assertFalse(self.lock_path().exists())
        self.assertEqual(job_status(self.series.path)["interrupted"], False)


class PoolStateTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(start=START, auto=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "pool.json"

    def pool(self, **kw):
        kw.setdefault("shared_limit", False)
        return Pool(KEYS, (MODEL,), self.clock, self.path, **kw)

    def test_day_exhausted_pairs_stay_unusable_until_the_reset(self):
        p = self.pool()
        for _ in KEYS:
            p.day_limit(p.acquire().pair)
        reset = day_return(START)
        got = p.acquire()
        self.assertTrue(got.all_day)
        self.assertIsNone(got.pair)
        self.assertEqual(got.until, reset)
        self.clock.advance(3600 * 5)  # a restart a few hours later
        q = self.pool()
        got = q.acquire()
        self.assertIsNone(got.pair)
        self.assertTrue(got.all_day)
        self.assertEqual((got.reason, got.until), (DAY, reset))
        self.assertEqual({s["state"] for s in q.states()}, {DAY})
        self.clock.advance(reset - self.clock.now() + 1)
        r = self.pool()
        self.assertIsNotNone(r.acquire().pair)
        self.assertEqual({s["state"] for s in r.states()}, {"ready"})

    def test_some_pairs_ready_is_not_all_day(self):
        p = self.pool()
        p.day_limit(p.acquire().pair)
        q = self.pool()
        self.assertIsNotNone(q.acquire().pair)
        self.assertFalse(q.acquire().all_day)

    def dense_throttle(self, p):
        pause = None
        for _ in range(3):
            got = p.acquire()
            pause = p.throttled(got.ticket)
        self.assertIsNotNone(pause)
        return pause

    def test_pause_is_saved_and_honoured_after_a_restart(self):
        p = self.pool()
        pause = self.dense_throttle(p)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["shut"]["until"], pause["until"])
        self.clock.advance(10)
        q = self.pool()
        got = q.acquire()
        self.assertIsNone(got.pair)
        self.assertEqual((got.reason, got.until), ("throttled", pause["until"]))
        self.clock.advance(pause["until"] - self.clock.now() + 0.5)
        probe = q.acquire()
        self.assertTrue(probe.probe)
        self.assertEqual(q.acquire().reason, "throttled")  # everybody else waits for the probe
        self.assertTrue(q.success(probe.pair, probe.ticket))
        self.assertNotIn("shut", json.loads(self.path.read_text(encoding="utf-8")))
        self.assertIsNotNone(self.pool().acquire().pair)

    def test_pause_that_ended_while_the_app_was_closed_still_sends_one_probe(self):
        p = self.pool()
        pause = self.dense_throttle(p)
        self.clock.advance(pause["seconds"] + 3600)
        q = self.pool()
        got = q.acquire()
        self.assertTrue(got.probe)
        self.assertEqual(q.acquire().reason, "throttled")
        # the probe is throttled again: the pause doubles
        again = q.throttled(got.ticket)
        self.assertEqual(again["seconds"], pause["seconds"] * 2)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["shut"]["until"], again["until"])

    def test_damaged_shut_record_is_ignored(self):
        p = self.pool()
        p.day_limit(p.acquire().pair)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        saved["shut"] = {"until": "soon"}
        self.path.write_text(json.dumps(saved), encoding="utf-8")
        q = self.pool()
        self.assertEqual(q.states()[0]["state"], DAY)
        self.assertIsNotNone(q.acquire().pair)

    def test_state_file_is_written_atomically(self):
        p = self.pool()
        with mock.patch("os.fsync") as fsync:
            p.day_limit(p.acquire().pair)
        self.assertTrue(fsync.called)
        self.assertEqual([x.name for x in self.path.parent.iterdir()], ["pool.json"])


class DiskFullTest(JobCase):
    chapters = 3
    paras = 8
    per_request = 2

    def failing_append(self, fail_from: int, exc: OSError):
        real = ChapterLog.append
        calls = [0]
        lock = threading.Lock()

        def append(log, recs):
            if not recs:
                return real(log, recs)
            with lock:
                calls[0] += 1
                n = calls[0]
            if n >= fail_from:
                raise exc
            return real(log, recs)

        return mock.patch.object(ChapterLog, "append", append)

    def test_disk_full_stops_the_run_cleanly(self):
        job = self.job()
        with self.failing_append(3, OSError(errno.ENOSPC, "No space left on device")):
            summary = job.run()
        events = job.drain()
        errors = [e for e in events if e.kind == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["message"], "disk full")
        self.assertEqual(events[-1].kind, "done")
        rec = read_job(self.series.path)
        self.assertEqual((rec["state"], rec["error"]), (FAILED, "disk full"))
        self.assertFalse(self.lock_path().exists())
        done, total = self.count_done()
        self.assertTrue(0 < done < total)
        self.assertEqual(summary["blocks"]["ok"], done, "unwritten blocks must not count as done")
        self.assertEqual(summary["fatal"], "disk")
        self.assertEqual(len(self.ok_records()), done)
        # the space is back: the job continues and finishes
        resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15}).run()
        self.assertEqual(self.count_done(), (24, 24))
        self.assertEqual(read_job(self.series.path)["state"], FINISHED)

    def test_any_other_write_error_gives_its_text(self):
        job = self.job()
        with self.failing_append(1, OSError(errno.EIO, "Input/output error")):
            summary = job.run()
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], FAILED)
        self.assertIn("Input/output error", rec["error"])
        self.assertEqual(summary["blocks"]["ok"], 0)
        self.assertEqual(self.count_done()[0], 0)
        self.assertFalse(self.lock_path().exists())

    def test_runner_alone_reports_the_error_too(self):
        r = self.runner()
        with self.failing_append(1, OSError(errno.ENOSPC, "full")):
            summary = r.run()
        self.assertEqual(summary["error"], "disk full")
        self.assertEqual([e.kind for e in r.drain() if e.kind == "error"], ["error"])

    def test_failed_append_leaves_no_partial_batch(self):
        log = ChapterLog(Path(self.dir) / "c.jsonl")
        rec = lambda i: {"i": i, "src_sha": f"s{i}", "text": "t", "status": "ok"}
        log.append([rec(0)])
        size = log.path.stat().st_size
        with mock.patch("os.fsync", side_effect=OSError(errno.ENOSPC, "full")):
            with self.assertRaises(OSError):
                log.append([rec(1), rec(2)])
        self.assertEqual(log.path.stat().st_size, size)
        self.assertIsNone(log.lookup(1, "s1"))
        self.assertIsNotNone(log.done(0, "s0"))
        log.append([rec(1)])
        self.assertEqual([r["i"] for r in ChapterLog(log.path).records()], [0, 1])


class QuotaWaitTest(JobCase):
    chapters = 3
    paras = 6
    per_request = 3
    api_args = {"day_limit": 0, "poll_interval": 0.02}

    def test_all_pairs_out_for_the_day_ends_the_process_work(self):
        job = self.job()
        started = self.clock.now()
        summary = job.run()
        events = job.drain()
        reset = day_return(started)
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], WAITING_QUOTA)
        self.assertEqual(rec["wake_at"], reset)
        self.assertIsNone(rec["error"])
        self.assertEqual(summary["quota_until"], reset)
        self.assertEqual(len([e for e in events if e.kind == "quota"]), 1)
        self.assertFalse([e for e in events if e.kind == "waiting"])
        self.assertLess(self.clock.now() - started, 60)  # it did not sit out the day
        self.assertFalse(self.lock_path().exists())
        st = job_status(self.series.path)
        self.assertFalse(st["interrupted"])
        self.assertEqual(st["job"]["wake_at"], reset)
        sent = len(self.api.log)
        self.assertLessEqual(sent, 3 * 3)
        # a restart before the reset sends nothing and stays in the same state
        again = resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15})
        again.run()
        self.assertEqual(len(self.api.log), sent)
        rec2 = read_job(self.series.path)
        self.assertEqual((rec2["state"], rec2["wake_at"]), (WAITING_QUOTA, reset))
        # after the reset, with quota again, one call continues to the end
        self.clock.advance(reset - self.clock.now() + 1)
        self.api.day_limit = None
        resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15}).run()
        self.assertEqual(self.count_done(), (18, 18))
        rec3 = read_job(self.series.path)
        self.assertEqual((rec3["state"], rec3["wake_at"]), (FINISHED, None))

    def test_a_plain_runner_still_waits_inside_the_process(self):
        r = self.runner()
        self.assertFalse(r.requester.end_on_quota)
        job = self.job()
        self.assertTrue(job.runner.requester.end_on_quota)

    def test_requester_raises_only_when_every_pair_is_day_exhausted(self):
        r = Runner(self.series, self.book, self.keys, [MODEL], clock=self.clock, base_url=self.api.base_url,
                   end_on_quota=True, rpm={MODEL: 15}, shared_limit=False)
        for p in r.pool.pairs[:-1]:
            r.pool.day_limit(p)
        self.assertIsNotNone(r.pool.acquire().pair)  # one pair is left
        r.pool.day_limit(r.pool.pairs[-1])
        with self.assertRaises(QuotaExhausted) as cm:
            r.requester("s", "u", {})
        self.assertEqual(cm.exception.until, day_return(self.clock.now()))


class CliTest(JobCase):
    chapters = 2
    paras = 4
    per_request = 2

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cli.main(list(argv))
            except SystemExit as exc:
                return str(exc.code), out.getvalue()
        return "", out.getvalue()

    def keys_file(self) -> str:
        path = self.dir / "keys.json"
        path.write_text(json.dumps({"keys": self.keys}), encoding="utf-8")
        return str(path)

    def test_job_command(self):
        _, out = self.run_cli("job", str(self.series.path))
        self.assertIn("no job", out)
        self.job().run()
        _, out = self.run_cli("job", str(self.series.path))
        self.assertIn("finished", out)
        self.assertIn("blocks 8/8", out)
        rec = read_job(self.series.path)
        rec["state"] = RUNNING
        write_job(self.series.path, rec)
        _, out = self.run_cli("job", str(self.series.path))
        self.assertIn("interrupted", out)

    def test_translate_and_resume_commands_go_through_the_job(self):
        def make_job(*a, **kw):
            return Job(*a, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15}, **kw)

        def make_resume(*a, **kw):
            return resume(*a, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15}, **kw)

        with mock.patch.object(cli, "Job", make_job), mock.patch.object(cli, "resume", make_resume):
            code, out = self.run_cli("resume", str(self.series.path), "--keys", self.keys_file())
            self.assertIn("no job", code)
            code, out = self.run_cli("translate", str(self.series.path), "0", "0", "--keys", self.keys_file(),
                                     "--models", MODEL)
            self.assertIn("done:", out)
            self.assertEqual(read_job(self.series.path)["state"], FINISHED)
            code, out = self.run_cli("resume", str(self.series.path), "--keys", self.keys_file())
            self.assertIn("finished", code)
            rec = read_job(self.series.path)
            rec["state"] = RUNNING
            write_job(self.series.path, rec)
            code, out = self.run_cli("resume", str(self.series.path), "--keys", self.keys_file())
            self.assertIn("done:", out)
            self.assertEqual(read_job(self.series.path)["state"], FINISHED)
            self.assertEqual(self.count_done()[0], 4)  # only chapter 0 was asked for

    def test_translate_refuses_a_busy_series(self):
        write_lock(self.series.path, os.getpid())
        with mock.patch.object(cli, "Job", lambda *a, **kw: Job(*a, clock=self.clock, base_url=self.api.base_url,
                                                                rpm={MODEL: 15}, **kw)):
            code, _ = self.run_cli("translate", str(self.series.path), "0", "1", "--keys", self.keys_file())
        self.assertIn("already being translated", code)
        self.assertEqual(self.api.log, [])


def requested_chapters(api) -> list[int]:
    """Chapter numbers of the successful requests, in the order they arrived."""
    out = []
    for e in api.log:
        if e["status"] == 200 and e["texts"]:
            m = re.match(r"Chapter (\d+) ", e["texts"][0])
            if m:
                out.append(int(m.group(1)))
    return out


class SelectionListTest(JobCase):
    chapters = 6
    paras = 4
    per_request = 2

    def test_range_helpers(self):
        self.assertEqual(to_ranges(list(range(2729, 2784)) + [2790]), [[2729, 2783], [2790, 2790]])
        self.assertEqual(to_ranges([5, 3, 3, 4, 9, -2]), [[3, 5], [9, 9]])
        self.assertEqual(from_ranges([[2, 3], [7, 7]]), [2, 3, 7])
        self.assertEqual(from_ranges([[2, 3], "x", [1], None]), [2, 3])
        self.assertEqual(to_ranges([]), [])

    def test_order_duplicates_gaps_and_out_of_range(self):
        job = self.job(chapters=[4, 0, 4, 2, 99, -1], in_flight=1)
        summary = job.run()
        self.assertEqual(self.count_done(), (12, 24))
        self.assertEqual(requested_chapters(self.api), [0, 0, 2, 2, 4, 4])  # ascending, one worker
        rec = read_job(self.series.path)
        self.assertEqual(rec["chapters"], [[0, 0], [2, 2], [4, 4], [99, 99]])  # the record keeps what was asked
        self.assertEqual((rec["first"], rec["last"]), (0, 99))
        self.assertEqual(rec["state"], FINISHED)
        self.assertEqual(rec["chapters_total"], 3)  # 99 was dropped when the book was opened
        self.assertEqual(summary["blocks"]["ok"], 12)
        started = [e for e in job.drain() if e.kind == "started"][0]
        self.assertEqual((started["pages"], started["chapters"]), (3, 3))

    def test_total_is_exact_before_the_first_request(self):
        job = self.job(chapters=[5, 1, 1, 3])
        job.acquire()
        try:
            job._begin()
        finally:
            job.lock.release()
        st = job_status(self.series.path)
        self.assertEqual(st["chapters_total"], 3)
        self.assertEqual(st["job"]["chapters"], [[1, 1], [3, 3], [5, 5]])
        self.assertEqual(self.api.log, [])

    def test_resume_restores_the_list(self):
        seen = threading.Event()
        job = self.job(chapters=[1, 2, 4], in_flight=1)
        job.runner.requester.generate = self.stopping_generate(None, 3, seen)
        job.start()
        self.assertTrue(seen.wait(20))
        job.stop()
        job.join(20)
        self.assertEqual(read_job(self.series.path)["state"], STOPPED)
        again = resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15},
                       gate=False)
        self.assertEqual(again.chapters, [1, 2, 4])
        again.run()
        self.assertEqual(self.count_done(), (12, 24))
        self.assertEqual(set(requested_chapters(self.api)), {1, 2, 4})
        texts = [t for e in self.api.log for t in e["texts"]]
        self.assertEqual(len(texts), len(set(texts)))
        self.assertEqual(read_job(self.series.path)["chapters"], [[1, 2], [4, 4]])

    def test_old_record_with_only_a_range_still_resumes(self):
        write_job(self.series.path, {"version": 1, "book": self.book, "first": 2, "last": 3, "state": STOPPED,
                                     "chapter_blocks": {}, "chapters_total": 2, "models": [MODEL]})
        again = resume(self.series, self.keys, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15},
                       gate=False)
        self.assertIsNone(again.chapters)
        again.run()
        self.assertEqual(sorted(set(requested_chapters(self.api))), [2, 3])
        self.assertIsNone(read_job(self.series.path)["chapters"])

    def test_empty_selection_runs_nothing(self):
        self.job(chapters=[]).run()
        self.assertEqual(self.api.log, [])
        rec = read_job(self.series.path)
        self.assertEqual((rec["state"], rec["chapters"]), (FINISHED, []))
        self.assertEqual(resume(self.series, self.keys, force=True, gate=False).chapters, [])


class GateTest(JobCase):
    chapters = 6
    paras = 4
    per_request = 2

    def blocked_from(self, n, terms=5, **extra):
        table = {i: terms for i in range(n, 6)}
        table.update(extra)
        return lambda i: table.get(i, 0)

    def test_prefix_is_translated_and_the_job_waits_for_terms(self):
        job = self.job(gate=self.blocked_from(3), in_flight=1)
        summary = job.run()
        events = job.drain()
        self.assertEqual(requested_chapters(self.api), [0, 0, 1, 1, 2, 2])  # 3 chapters x 2 requests
        self.assertEqual(self.count_done()[0], 12)
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], WAITING_TERMS)
        self.assertEqual((rec["terms_pending"], rec["blocked_chapter"]), (5, 3))
        self.assertIsNone(rec["error"])
        self.assertEqual(rec["chapters_total"], 6)  # the whole selection, not the prefix
        self.assertEqual(summary["blocked"]["index"], 3)
        self.assertEqual(summary["blocked"]["terms"], 5)
        self.assertTrue(summary["blocked"]["title"])
        ev = [e for e in events if e.kind == "terms"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].data, summary["blocked"])
        self.assertEqual([e.kind for e in events][-2:], ["terms", "done"])
        started = [e for e in events if e.kind == "started"][0]
        self.assertEqual((started["pages"], started["selected"]), (3, 6))
        st = job_status(self.series.path)
        self.assertEqual((st["terms_pending"], st["blocked_chapter"], st["chapters_total"]), (5, 3, 6))
        self.assertFalse(st["interrupted"])
        self.assertFalse(self.lock_path().exists())

    def test_without_a_gate_nothing_changes(self):
        summary = self.job(gate=False).run()
        self.assertIsNone(summary["blocked"])
        self.assertEqual(self.count_done(), (24, 24))
        rec = read_job(self.series.path)
        self.assertEqual((rec["state"], rec["terms_pending"], rec["blocked_chapter"]), (FINISHED, 0, None))
        st = job_status(self.series.path)
        self.assertEqual((st["terms_pending"], st["blocked_chapter"]), (0, None))

    def test_first_chapter_blocked_sends_nothing(self):
        job = self.job(gate=lambda i: 2)
        summary = job.run()
        self.assertEqual(self.api.log, [])
        rec = read_job(self.series.path)
        self.assertEqual((rec["state"], rec["terms_pending"], rec["blocked_chapter"]), (WAITING_TERMS, 2, 0))
        self.assertEqual(summary["blocked"]["index"], 0)
        self.assertEqual([e.kind for e in job.drain()][-2:], ["terms", "done"])

    def test_gate_walks_the_selection_list_in_ascending_order(self):
        seen = []

        def gate(i):
            seen.append(i)
            return 4 if i == 4 else 0

        job = self.job(gate=gate, chapters=[5, 4, 1, 0])
        job.run()
        self.assertEqual(seen, [0, 1, 4])  # stops at the first blocked one
        self.assertEqual(sorted(set(requested_chapters(self.api))), [0, 1])
        self.assertEqual(read_job(self.series.path)["blocked_chapter"], 4)

    def test_finished_chapters_never_block(self):
        self.job().run()  # everything translated
        self.assertEqual(self.count_done(), (24, 24))
        sent = len(self.api.log)
        summary = self.job(gate=lambda i: 9).run()
        self.assertIsNone(summary["blocked"])
        self.assertEqual(len(self.api.log), sent)
        self.assertEqual(read_job(self.series.path)["state"], FINISHED)

    def test_finished_chapter_inside_the_walk_is_passed(self):
        self.job(chapters=[1, 2]).run()  # chapters 1 and 2 done
        sent = len(self.api.log)
        seen = []

        def gate(i):
            seen.append(i)
            return {1: 7, 2: 7, 4: 3}.get(i, 0)

        summary = self.job(gate=gate, in_flight=1).run()
        self.assertEqual(seen, [0, 1, 2, 3, 4])
        self.assertEqual(summary["blocked"]["index"], 4)
        new = [e for e in self.api.log[sent:] if e["status"] == 200]
        self.assertEqual(len(new), 4)  # chapters 0 and 3, two requests each
        self.assertEqual(self.count_done()[0], 16)

    def test_partly_translated_chapter_still_blocks(self):
        seen = threading.Event()
        job = self.job(chapters=[0], in_flight=1)
        job.runner.requester.generate = self.stopping_generate(None, 1, seen)
        job.start()
        self.assertTrue(seen.wait(20))
        job.stop()
        job.join(20)
        done = self.count_done()[0]
        self.assertTrue(0 < done < 4, done)
        sent = len(self.api.log)
        summary = self.job(gate=lambda i: 1, chapters=[0, 1]).run()
        self.assertEqual(summary["blocked"]["index"], 0)
        self.assertEqual(len(self.api.log), sent)

    def test_gate_that_raises_is_blocked_not_allowed(self):
        def gate(i):
            if i == 2:
                raise RuntimeError("terms file is damaged")
            return 0

        summary = self.job(gate=gate, in_flight=1).run()
        self.assertEqual(summary["blocked"]["index"], 2)
        self.assertEqual(summary["blocked"]["terms"], -1)
        self.assertIn("terms file is damaged", summary["blocked"]["error"])
        rec = read_job(self.series.path)
        self.assertEqual((rec["state"], rec["terms_pending"], rec["blocked_chapter"]), (WAITING_TERMS, -1, 2))
        self.assertIn("terms file is damaged", rec["error"])
        self.assertEqual(sorted(set(requested_chapters(self.api))), [0, 1])
        self.assertEqual(job_status(self.series.path)["terms_pending"], -1)

    def test_resume_after_the_gate_opens_goes_to_the_end(self):
        self.job(gate=self.blocked_from(2), in_flight=1).run()
        self.assertEqual(read_job(self.series.path)["state"], WAITING_TERMS)
        self.assertEqual(self.count_done()[0], 8)
        sent = len(self.api.log)
        kw = dict(clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15})
        # reviewed up to chapter 3: the next stop is chapter 4
        resume(self.series, self.keys, gate=self.blocked_from(4, terms=2), **kw).run()
        rec = read_job(self.series.path)
        self.assertEqual((rec["state"], rec["terms_pending"], rec["blocked_chapter"]), (WAITING_TERMS, 2, 4))
        self.assertEqual(self.count_done()[0], 16)
        # everything reviewed
        resume(self.series, self.keys, gate=lambda i: 0, **kw).run()
        rec = read_job(self.series.path)
        self.assertEqual((rec["state"], rec["terms_pending"], rec["blocked_chapter"]), (FINISHED, 0, None))
        self.assertEqual(self.count_done(), (24, 24))
        texts = [t for e in self.api.log for t in e["texts"]]
        self.assertEqual(len(texts), len(set(texts)))
        self.assertGreater(len(self.api.log), sent)
        with self.assertRaises(JobError):
            resume(self.series, self.keys)

    def test_stop_wins_over_the_gate(self):
        seen = threading.Event()
        job = self.job(gate=self.blocked_from(4), in_flight=1)
        job.runner.requester.generate = self.stopping_generate(None, 2, seen)
        job.start()
        self.assertTrue(seen.wait(20))
        job.stop()
        job.join(20)
        self.assertEqual(read_job(self.series.path)["state"], STOPPED)
        self.assertEqual(read_job(self.series.path)["terms_pending"], 0)

    def test_failure_wins_over_the_gate(self):
        self.api.invalid_keys = {0, 1, 2}
        summary = self.job(gate=self.blocked_from(3)).run()
        self.assertEqual(summary["blocked"]["index"], 3)  # still reported
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], FAILED)
        self.assertEqual((rec["terms_pending"], rec["blocked_chapter"]), (0, None))

    def test_default_gate_comes_from_the_frontier_module(self):
        import types

        import novelcore

        calls = []
        fake = types.ModuleType("novelcore.frontier")
        fake.gate_for = lambda series, book: calls.append((series, book)) or (lambda i: 1)
        with mock.patch.dict(sys.modules, {"novelcore.frontier": fake}), \
                mock.patch.object(novelcore, "frontier", fake, create=True):
            gated = Job(self.series, self.book, self.keys, [MODEL], clock=self.clock, base_url=self.api.base_url)
            self.assertIsNotNone(gated.runner.gate)
            self.assertEqual(calls, [(self.series, self.book)])
            off = Job(self.series, self.book, self.keys, [MODEL], gate=False, clock=self.clock,
                      base_url=self.api.base_url)
            self.assertIsNone(off.runner.gate)
            summary = gated.run()
        self.assertEqual(summary["blocked"]["index"], 0)
        self.assertEqual(self.api.log, [])
        # a module without the function, and no module at all: no gate
        bare = types.ModuleType("novelcore.frontier")
        with mock.patch.dict(sys.modules, {"novelcore.frontier": bare}), \
                mock.patch.object(novelcore, "frontier", bare, create=True):
            self.assertIsNone(Job(self.series, self.book, self.keys, [MODEL]).runner.gate)
        with mock.patch.dict(sys.modules, {"novelcore.frontier": None}), mock.patch.dict(vars(novelcore)):
            vars(novelcore).pop("frontier", None)
            self.assertIsNone(Job(self.series, self.book, self.keys, [MODEL]).runner.gate)


class GateQuotaTest(JobCase):
    chapters = 4
    paras = 4
    per_request = 2
    api_args = {"day_limit": 0, "poll_interval": 0.02}

    def test_quota_wins_over_the_gate(self):
        summary = self.job(gate=lambda i: 2 if i >= 2 else 0).run()
        rec = read_job(self.series.path)
        self.assertEqual(rec["state"], WAITING_QUOTA)
        self.assertEqual((rec["terms_pending"], rec["blocked_chapter"]), (0, None))
        self.assertEqual(summary["blocked"]["index"], 2)
        self.assertIsNotNone(rec["wake_at"])


class GateCliTest(JobCase):
    chapters = 3
    paras = 4
    per_request = 2

    run_cli = CliTest.run_cli
    keys_file = CliTest.keys_file

    def patched(self, **inject):
        def make_job(*a, **kw):
            for k, v in inject.items():
                kw.setdefault(k, v)
            self.seen_kw = kw
            return Job(*a, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15}, **kw)

        def make_resume(*a, **kw):
            for k, v in inject.items():
                kw.setdefault(k, v)
            self.seen_kw = kw
            return resume(*a, clock=self.clock, base_url=self.api.base_url, rpm={MODEL: 15}, **kw)

        return mock.patch.multiple(cli, Job=make_job, resume=make_resume)

    def test_chapters_option_and_argument_errors(self):
        with self.patched(gate=False):
            code, out = self.run_cli("translate", str(self.series.path), "--chapters", "2,0", "--keys",
                                     self.keys_file(), "--models", MODEL)
        self.assertIn("done:", out)
        self.assertEqual(sorted(set(requested_chapters(self.api))), [0, 2])
        self.assertEqual(read_job(self.series.path)["chapters"], [[0, 0], [2, 2]])
        _, out = self.run_cli("job", str(self.series.path))
        self.assertIn("chapters 0,2", out)
        keys = self.keys_file()
        series = str(self.series.path)
        for argv, text in ((("translate", series, "--keys", keys), "first and last"),
                           (("translate", series, "1", "--keys", keys), "both"),
                           (("translate", series, "0", "1", "--chapters", "1", "--keys", keys), "not both"),
                           (("translate", series, "--chapters", "3-1", "--keys", keys), "bad chapter range")):
            code, _ = self.run_cli(*argv)
            self.assertIn(text, code)
        self.assertEqual(cli.parse_chapters("5,7-9,12,7"), [5, 7, 8, 9, 12])

    def test_range_form_still_works(self):
        with self.patched(gate=False):
            _, out = self.run_cli("translate", str(self.series.path), "0", "1", "--keys", self.keys_file(),
                                  "--models", MODEL)
        self.assertIn("done:", out)
        self.assertEqual(sorted(set(requested_chapters(self.api))), [0, 1])
        self.assertIsNone(read_job(self.series.path)["chapters"])

    def test_terms_line_and_no_gate_flag(self):
        with self.patched(gate=lambda i: 3 if i >= 1 else 0):
            _, out = self.run_cli("translate", str(self.series.path), "0", "2", "--keys", self.keys_file(),
                                  "--models", MODEL)
            self.assertRegex(out, r"waiting for terms: chapter 1 \(.+\): 3 unreviewed")
            self.assertEqual(read_job(self.series.path)["state"], WAITING_TERMS)
            _, out = self.run_cli("job", str(self.series.path))
            self.assertIn("waiting for terms: chapter 1: 3 unreviewed", out)
            sent = len(self.api.log)
            self.assertEqual(sorted(set(requested_chapters(self.api))), [0])
            # --no-gate must override what the patch injects: the CLI passes gate=False itself
            _, out = self.run_cli("resume", str(self.series.path), "--keys", self.keys_file(), "--no-gate")
            self.assertIs(self.seen_kw["gate"], False)
            self.assertNotIn("waiting for terms", out)
            self.assertGreater(len(self.api.log), sent)
        self.assertEqual(read_job(self.series.path)["state"], FINISHED)
        self.assertEqual(self.count_done(), (12, 12))

    def test_no_gate_on_translate(self):
        with self.patched(gate="unset"):
            self.run_cli("translate", str(self.series.path), "0", "0", "--keys", self.keys_file(),
                         "--models", MODEL, "--no-gate")
            self.assertIs(self.seen_kw["gate"], False)

    def test_export_options_and_nothing_to_export(self):
        code, out = self.run_cli("export", str(self.series.path), "--chapters", "0,1")
        self.assertEqual(code, "1")
        self.assertIn("no selected chapter is fully translated", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(list((self.series.path / "out").glob("*.epub*")), [])
        self.job(chapters=[0, 2]).run()
        code, out = self.run_cli("export", str(self.series.path), "--chapters", "0-2")
        self.assertEqual(code, "")
        self.assertIn("kept 2 chapters, skipped 1 not fully translated", out)
        self.assertIn("skipped chapter 1", out)
        code, out = self.run_cli("export", str(self.series.path), "0", "2")
        self.assertIn("kept 2 chapters", out)
        code, out = self.run_cli("export", str(self.series.path), "--whole")
        self.assertEqual(code, "")
        self.assertNotIn("kept", out)
        self.assertIn(" 4 untranslated", out)  # chapter 1 stays in the source language
        code, _ = self.run_cli("export", str(self.series.path), "0", "--chapters", "1")
        self.assertIn("not both", code)


class SeriesPromptTest(JobCase):
    def test_shipped_prompt_follows_the_target_tag(self):
        from novelcore import profiles
        from novelcore.store import default_prompt

        self.assertEqual(self.series.prompt_text(), default_prompt())  # ru: the same text as before
        for tag, name in (("uk", "Ukrainian"), ("pl", "Polish")):
            series = Series.create(self.dir / "lib", f"S {tag}", f"{tag}:{name}")
            self.assertEqual(series.prompt_text(), profiles.prompt_text(tag))
            self.assertIn(name, series.system_prompt())
        own = self.dir / "lib" / "S uk" / "prompt.txt"
        own.write_text("own {language}", encoding="utf-8")
        self.assertEqual(Series.open(own.parent).prompt_text(), "own {language}")


if __name__ == "__main__":
    unittest.main()
