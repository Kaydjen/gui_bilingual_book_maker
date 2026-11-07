import unittest

from bbm_gui import keypool as kp

DAY_AT = 10_000


class PoolTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(kp.parse("a, b;c\nd  a"), ["a", "b", "c", "d"])
        self.assertEqual(kp.parse(""), [])

    def test_model_major_order(self):
        p = kp.Pool(["k1", "k2"], ["m1", "m2"])
        self.assertEqual(p.pairs(), [("k1", "m1"), ("k2", "m1"), ("k1", "m2"), ("k2", "m2")])
        self.assertEqual(p.next_pair(0), ("k1", "m1"))
        p.record("k1", "m1", "day", None, 0, DAY_AT)
        self.assertEqual(p.next_pair(0), ("k2", "m1"))  # the same model on the next key first
        p.record("k2", "m1", "day", None, 0, DAY_AT)
        self.assertEqual(p.next_pair(0), ("k1", "m2"))

    def test_first_ready_again_after_recovery(self):
        p = kp.Pool(["k1", "k2"], ["m1"])
        p.record("k1", "m1", "minute", 20, 100, DAY_AT)
        self.assertEqual(p.next_pair(100), ("k2", "m1"))
        self.assertEqual(p.next_pair(100 + 23), ("k1", "m1"))  # back to the best pair when it has rested

    def test_minute_clamp(self):
        self.assertEqual(kp.minute_cooldown(None), 65)
        self.assertEqual(kp.minute_cooldown(1), 8)
        self.assertEqual(kp.minute_cooldown(20), 23)
        self.assertEqual(kp.minute_cooldown(500), 90)

    def test_states_and_times(self):
        p = kp.Pool(["k"], ["m"])
        self.assertEqual(p.record("k", "m", "minute", 38.92, 1000, DAY_AT), ("cool", 1000 + 41.92))
        self.assertEqual(p.record("k", "m", "day", None, 1000, DAY_AT), ("day", DAY_AT))
        self.assertEqual(p.record("k", "m", "zero", None, 1000, DAY_AT), ("dead", kp.FAR))
        self.assertEqual(p.record("k", "m", "notfound", None, 1000, DAY_AT), ("dead", kp.FAR))

    def test_unknown_and_busy_double_then_reset(self):
        p = kp.Pool(["k"], ["m"])
        got = [p.record("k", "m", "unknown" if i % 2 else "busy", None, 0, DAY_AT)[1] for i in range(6)]
        self.assertEqual(got, [120, 240, 480, 900, 900, 900])
        p.success("k", "m")
        self.assertEqual(p.record("k", "m", "busy", None, 0, DAY_AT)[1], 120)

    def test_hits_survive_purge_of_a_finished_cooldown(self):
        p = kp.Pool(["k"], ["m"])
        p.record("k", "m", "unknown", None, 0, DAY_AT)
        p.purge(500)
        self.assertEqual(p.record("k", "m", "unknown", None, 500, DAY_AT)[1], 500 + 240)

    def test_returns_after_reset(self):
        p = kp.Pool(["k1"], ["m1"])
        p.record("k1", "m1", "day", None, 0, 100)
        self.assertIsNone(p.next_pair(50))
        self.assertEqual(p.earliest_return(50), 100)
        self.assertEqual(p.earliest_kind(50), "day")
        self.assertEqual(p.next_pair(100), ("k1", "m1"))

    def test_bad_key_skipped_and_dead_pair_not_waited_for(self):
        p = kp.Pool(["k1", "k2"], ["m"])
        p.mark_bad("k1")
        self.assertEqual(p.next_pair(0), ("k2", "m"))
        self.assertEqual(p.state("k1", 0), ("bad", 0))
        p.record("k2", "m", "notfound", None, 0, DAY_AT)
        self.assertIsNone(p.next_pair(0))
        self.assertIsNone(p.earliest_return(0))  # nothing to wait for
        self.assertEqual(p.state("k2", 0), ("dead", 0))

    def test_key_states(self):
        p = kp.Pool(["k"], ["a", "b"])
        self.assertEqual(p.state("k", 0), ("ready", 0))
        p.record("k", "a", "minute", 20, 0, DAY_AT)
        self.assertEqual(p.state("k", 0), ("part", 23))
        p.record("k", "b", "day", None, 0, DAY_AT)
        self.assertEqual(p.state("k", 0), ("wait", 23))
        self.assertEqual(p.state("k", 30), ("part", DAY_AT))
        self.assertEqual(p.usable_keys(30), ["k"])
        p.record("k", "a", "day", None, 30, DAY_AT)
        self.assertEqual(p.state("k", 30), ("day", DAY_AT))
        self.assertEqual(p.usable_keys(30), [])

    def test_migration_of_old_marks(self):
        old = {"abc|m": 50 + 3600, "def|m": 50 + 120, "gone": 10}
        new = kp.migrate_spent(old, 50)
        self.assertEqual(new["abc|m"]["s"], "day")
        self.assertEqual(new["def|m"]["s"], "cool")
        self.assertNotIn("gone", new)

    def test_purge_drops_marks_of_removed_keys_and_models(self):
        p = kp.Pool(["k"], ["m"])
        p.record("k", "m", "notfound", None, 0, DAY_AT)
        states = dict(p.states)
        q = kp.Pool(["k"], ["m2"], states)
        q.purge(1)
        self.assertEqual(q.states, {})  # the model left the list: the mark goes with it
        r = kp.Pool(["k"], ["m"], states)
        r.purge(1)
        self.assertEqual(r.next_pair(1), None)

    def test_looks_like_key(self):
        self.assertTrue(kp.looks_like_key("AQ.Ab8RN6JWXT9Y-UAZLui_dMi57"))
        self.assertFalse(kp.looks_like_key("hello"))
        self.assertEqual(kp.mask("AIzaSyABCDEFGHIJKLMN"), "AIza…KLMN")


if __name__ == "__main__":
    unittest.main()
