"""What the window reads and writes of a run through novelgui.model (stage 3 step 5): dead pairs, job record
states, today's quota with the series that were moved to .deleted."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from novelcore import job as core_job
from novelcore.pool import Pool, key_hash
from novelgui import model

KEYS = ["key-a-" + "x" * 20, "key-b-" + "y" * 20]
MODELS = ["gemini-3.1-flash-lite"]


def record(state="failed", **kw):
    rec = {"version": 1, "book": "b", "first": 0, "last": 2, "chapters": [[0, 2]], "state": state, "models": MODELS,
           "chapter_blocks": {}, "wake_at": None, "error": None, "terms_pending": 0, "blocked_chapter": None,
           "blocks_failed": 0, "chapters_total": 3}
    rec.update(kw)
    return rec


class DeadPairs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".state").mkdir()
        self.state = self.root / ".state" / "pool.json"

    def kill(self, reason):
        pool = Pool(KEYS, MODELS, state_path=self.state)
        for p in pool.pairs:
            pool.dead(p, reason)

    def test_dead_reasons_are_read_from_the_pool_file(self):
        self.assertEqual(model.dead_reasons(self.root), ())
        self.kill("invalid key")
        self.assertEqual(model.dead_reasons(self.root), ("invalid key",))

    def test_a_failed_job_view_carries_them(self):
        core_job.write_job(self.root, record("failed", error="no usable key/model pair is left"))
        self.kill("model not found")
        v = model.job_view(self.root)
        self.assertEqual((v.state, v.dead), ("failed", ("model not found",)))
        core_job.write_job(self.root, record("stopped"))
        self.assertEqual(model.job_view(self.root).dead, ())

    def test_revive_gives_the_pairs_another_chance_and_keeps_the_file(self):
        self.kill("invalid key")
        model.revive_dead_pairs(self.root, KEYS, MODELS)
        self.assertEqual(model.dead_reasons(self.root), ())
        pool = Pool(KEYS, MODELS, state_path=self.state)
        self.assertTrue(all(p.state != "dead" for p in pool.pairs))

    def test_revive_without_keys_does_nothing(self):
        self.kill("invalid key")
        model.revive_dead_pairs(self.root, [], MODELS)
        self.assertEqual(model.dead_reasons(self.root), ("invalid key",))


class JobRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_stop_the_wait(self):
        core_job.write_job(self.root, record("waiting_quota", wake_at=time.time() + 100))
        self.assertTrue(model.set_job_state(self.root, "stopped"))
        v = model.job_view(self.root)
        self.assertEqual((v.state, v.wake_at), ("stopped", None))

    def test_discard_closes_the_job_and_keeps_the_book_and_chapters(self):
        core_job.write_job(self.root, record("failed", error="boom"))
        self.assertTrue(model.set_job_state(self.root, "finished"))
        rec = core_job.read_job(self.root)
        self.assertEqual((rec["state"], rec["error"], rec["book"], rec["chapters"]), ("finished", None, "b", [[0, 2]]))
        self.assertFalse(model.job_view(self.root).unfinished)

    def test_no_record_no_change(self):
        self.assertFalse(model.set_job_state(self.root, "stopped"))


class QuotaOfTheDay(unittest.TestCase):
    def test_series_moved_to_deleted_still_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp)
            for rel in ("A", ".deleted/B-2026-11-16_10-00-00"):
                state = lib / rel / ".state"
                state.mkdir(parents=True)
                pool = Pool(KEYS, MODELS, state_path=state / "pool.json")
                pool._used = {key_hash(KEYS[0]): {MODELS[0]: 40}}
                pool._day = pool._day
                pool._save()
            q = model.quota_status(lib, KEYS, MODELS, time.time())
            self.assertEqual(q.used, 80)
            self.assertEqual(q.left, 2 * 500 - 80)


if __name__ == "__main__":
    unittest.main()
