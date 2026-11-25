import json
import tempfile
import time
import unittest
from pathlib import Path

from novelgui import keystates as ks
from novelgui import model

NOW = 1_000_000.0
M = "gemini-3.1-flash-lite"


def pair(h, m=M):
    return "%s|%s" % (h, m)


class MergeTest(unittest.TestCase):
    def merge(self, tables, hashes=("a", "b"), models=(M,)):
        return ks.merge_pairs(tables, list(hashes), list(models), NOW)

    def test_ready_when_nothing_is_recorded(self):
        st, missing = self.merge([])
        self.assertEqual(st["a"].kind, ks.READY)
        self.assertEqual(missing, set())

    def test_worst_state_wins_over_series(self):
        t1 = {pair("a"): {"state": "cool", "until": NOW + 60, "reason": "minute"}}
        t2 = {pair("a"): {"state": "day", "until": NOW + 3600, "reason": "day"}}
        t3 = {pair("a"): {"state": "dead", "until": 0, "reason": "invalid key"}}
        self.assertEqual(self.merge([t1])[0]["a"].kind, ks.PAUSED)
        self.assertEqual(self.merge([t1, t2])[0]["a"].kind, ks.DAY)
        self.assertEqual(self.merge([t1, t2, t3])[0]["a"].kind, ks.INVALID)
        self.assertEqual(self.merge([t3, t2, t1])[0]["a"].kind, ks.INVALID)
        self.assertEqual(self.merge([t1, t2, t3])[0]["b"].kind, ks.READY)

    def test_latest_until_wins_between_equal_kinds(self):
        a = {pair("a"): {"state": "day", "until": NOW + 100}}
        b = {pair("a"): {"state": "day", "until": NOW + 900}}
        self.assertEqual(self.merge([a, b])[0]["a"].until, NOW + 900)
        self.assertEqual(self.merge([b, a])[0]["a"].until, NOW + 900)

    def test_expired_records_do_not_count(self):
        t = {pair("a"): {"state": "day", "until": NOW - 1}, pair("b"): {"state": "cool", "until": NOW}}
        st, _ = self.merge([t])
        self.assertEqual((st["a"].kind, st["b"].kind), (ks.READY, ks.READY))

    def test_model_not_found_is_a_model_fact_not_a_key_fact(self):
        t = {pair("a"): {"state": "dead", "reason": "model not found"},
             pair("a", "other"): {"state": "dead", "reason": "model not found"}}
        st, missing = self.merge([t])
        self.assertEqual(missing, {M})                      # only models asked about
        self.assertEqual(st["a"].kind, ks.READY)

    def test_foreign_keys_models_and_junk_are_ignored(self):
        t = {pair("zzz"): {"state": "dead", "reason": "invalid key"}, "nobar": {"state": "dead"},
             pair("a", "other"): {"state": "dead", "reason": "invalid key"}, pair("b"): "junk"}
        st, _ = self.merge([t, None, "x"])
        self.assertEqual({v.kind for v in st.values()}, {ks.READY})

    def test_texts(self):
        self.assertEqual(ks.text(ks.KeyState()), "ready")
        self.assertEqual(ks.text(ks.KeyState(ks.INVALID)), "invalid")
        hhmm = time.strftime("%H:%M", time.localtime(NOW + 60))
        self.assertEqual(ks.text(ks.KeyState(ks.PAUSED, NOW + 60)), "paused until " + hhmm)
        self.assertEqual(ks.text(ks.KeyState(ks.DAY, NOW + 60)), "daily quota until " + hhmm)


class ReadFilesTest(unittest.TestCase):
    def test_reads_every_series_pool_file(self):
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d)
            from novelcore.pool import key_hash
            key = "k" * 30
            h = key_hash(key)
            for name, rec in (("One", {"state": "dead", "reason": "invalid key"}),
                              ("Two", None), ("Three", {"state": "dead", "reason": "model not found"})):
                st = lib / name / ".state"
                st.mkdir(parents=True)
                if rec is not None:
                    (st / "pool.json").write_text(json.dumps({"pairs": {pair(h): rec}}), encoding="utf-8")
            (lib / ".deleted" / "Old" / ".state").mkdir(parents=True)
            (lib / ".deleted" / "Old" / ".state" / "pool.json").write_text("{}", encoding="utf-8")
            states, missing = model.key_states(lib, [key], [M], time.time())
            self.assertEqual(states[key].kind, ks.INVALID)
            self.assertEqual(missing, {M})


if __name__ == "__main__":
    unittest.main()
