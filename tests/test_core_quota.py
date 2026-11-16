"""Requests sent per key and Pacific day: counting, persistence, reset at Pacific midnight."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from novelcore.pool import Pool, key_hash, pacific_day, read_day_exhausted, read_day_usage
from tests.fake_api import FakeClock

KEYS = [f"quota-key-{i}-SECRETSECRET" for i in range(3)]
M = "a-flash-lite"
START = 1_760_000_000.0  # 2025-10-09 08:53 UTC, mid-morning Pacific


def pool(clock, path=None, keys=KEYS, models=(M,), pace=120):
    return Pool(keys, models, clock, state_path=path, pace=pace)


def send(p, clock, n):
    got = []
    for _ in range(n):
        a = p.acquire()
        while a.pair is None:
            clock.advance(max(0.01, (a.until or clock.now()) - clock.now()))
            a = p.acquire()
        got.append(a.pair)
        p.finish(a.ticket)
    return got


class CountingTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(start=START, auto=False)

    def test_counts_per_key_hash_and_model(self):
        p = pool(self.clock)
        picked = send(p, self.clock, 6)
        usage = p.day_usage()
        self.assertEqual(sum(sum(m.values()) for m in usage.values()), 6)
        self.assertEqual(set(usage), {key_hash(k) for k in KEYS})
        for kh, per in usage.items():
            self.assertEqual(per[M], sum(1 for x in picked if x.khash == kh))
        self.assertEqual(set(usage[key_hash(KEYS[0])]), {M})

    def test_two_models_count_apart(self):
        p = pool(self.clock, models=("a-flash-lite", "b-flash-lite"))
        send(p, self.clock, 3)
        self.assertEqual(set(m for per in p.day_usage().values() for m in per), {"a-flash-lite"})

    def test_state_file_holds_hashes_only_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.json"
            p = pool(self.clock, path)
            send(p, self.clock, 5)
            text = path.read_text(encoding="utf-8")
            for k in KEYS:
                self.assertNotIn(k, text)
            self.assertEqual(json.loads(text)["usage"]["day"], pacific_day(START))
            q = pool(self.clock, path)
            self.assertEqual(q.day_usage(), p.day_usage())
            send(q, self.clock, 2)
            self.assertEqual(sum(sum(m.values()) for m in q.day_usage().values()), 7)
            self.assertEqual(read_day_usage(path, self.clock.now()), q.day_usage())

    def test_reset_at_pacific_midnight(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.json"
            p = pool(self.clock, path)
            send(p, self.clock, 4)
            self.assertEqual(sum(sum(m.values()) for m in p.day_usage().values()), 4)
            self.clock.advance(24 * 3600)  # the next Pacific day
            self.assertEqual(p.day_usage(), {})
            self.assertEqual(read_day_usage(path, self.clock.now()), {})  # a stale file counts nothing
            send(p, self.clock, 1)
            self.assertEqual(sum(sum(m.values()) for m in p.day_usage().values()), 1)
            self.assertEqual(pool(self.clock, path).day_usage(), p.day_usage())

    def test_pacific_day_changes_at_pacific_midnight(self):
        # 2025-10-09 07:00 UTC is 00:00 PDT of the 9th; one second earlier is still the 8th
        mid = dt.datetime(2025, 10, 9, 7, 0, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(pacific_day(mid - 1), "2025-10-08")
        self.assertEqual(pacific_day(mid), "2025-10-09")
        # winter time: 08:00 UTC
        mid = dt.datetime(2025, 12, 9, 8, 0, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(pacific_day(mid - 1), "2025-12-08")
        self.assertEqual(pacific_day(mid), "2025-12-09")

    def test_missing_or_damaged_file_reads_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.json"
            self.assertEqual(read_day_usage(path, START), {})
            self.assertEqual(read_day_exhausted(path, START), set())
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(read_day_usage(path, START), {})
            path.write_text(json.dumps({"usage": {"day": pacific_day(START), "used": {"k": {"m": "x"}}}}))
            self.assertEqual(read_day_usage(path, START), {"k": {}})

    def test_exhausted_pairs_are_listed_until_they_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.json"
            p = pool(self.clock, path)
            a = p.acquire()
            until = p.day_limit(a.pair)
            name = f"{a.pair.khash}|{M}"
            self.assertEqual(read_day_exhausted(path, self.clock.now()), {name})
            self.assertEqual(read_day_exhausted(path, until + 1), set())


if __name__ == "__main__":
    unittest.main()
