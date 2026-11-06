import unittest

from bbm_gui import keypool as kp


class PoolTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(kp.parse("a, b;c\nd  a"), ["a", "b", "c", "d"])
        self.assertEqual(kp.parse(""), [])

    def test_key_by_key_order(self):
        p = kp.Pool(["k1", "k2"], ["m1", "m2"])
        self.assertEqual(p.next_pair(0), ("k1", "m1"))
        p.mark("k1", "m1", 100)
        self.assertEqual(p.next_pair(0), ("k1", "m2"))
        p.mark("k1", "m2", 100)
        self.assertEqual(p.next_pair(0), ("k2", "m1"))

    def test_returns_after_reset(self):
        p = kp.Pool(["k1"], ["m1"])
        p.mark("k1", "m1", 100)
        self.assertIsNone(p.next_pair(50))
        self.assertEqual(p.earliest_return(50), 100)
        self.assertEqual(p.next_pair(100), ("k1", "m1"))

    def test_bad_key_skipped(self):
        p = kp.Pool(["k1", "k2"], ["m"])
        p.mark_bad("k1")
        self.assertEqual(p.next_pair(0), ("k2", "m"))
        p.mark("k2", "m", 10)
        self.assertIsNone(p.next_pair(0))
        self.assertEqual(p.earliest_return(0), 10)
        self.assertEqual(p.state("k1", 0), ("bad", 0))

    def test_states(self):
        p = kp.Pool(["k"], ["a", "b"])
        self.assertEqual(p.state("k", 0), ("ready", 0))
        p.mark("k", "a", 70)
        self.assertEqual(p.state("k", 0), ("part", 70))
        p.mark("k", "b", 50)
        self.assertEqual(p.state("k", 0), ("used", 50))
        self.assertEqual(p.usable_keys(0), [])

    def test_purge_and_mask(self):
        p = kp.Pool(["k"], ["m"], {kp.fingerprint("k") + "|m": 5})
        p.purge(10)
        self.assertEqual(p.spent, {})
        self.assertEqual(kp.mask("AIzaSyABCDEFGHIJKLMN"), "AIza…KLMN")


if __name__ == "__main__":
    unittest.main()
