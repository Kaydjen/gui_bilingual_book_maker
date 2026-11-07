import unittest

from bbm_gui import pace, runner


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def frame(n, total=100):
    return "  1%%|#     | %d/%d [00:01<01:00, 1.00s/it]" % (n, total)


class IntervalTest(unittest.TestCase):
    def test_table(self):
        # (1 + 0.10) * 60 / RPM - low latency, never below zero
        cases = {(1.0, 15): 3.4, (2.7, 15): 1.7, (5.0, 15): 0.0, (1.0, 5): 12.2, (2.7, 5): 10.5, (5.0, 5): 8.2,
                 (1.0, 30): 1.2, (2.7, 30): 0.0, (5.0, 30): 0.0}
        for (lat, rpm), want in cases.items():
            self.assertAlmostEqual(pace.interval(lat, rpm), want, places=6, msg=(lat, rpm))

    def test_text(self):
        self.assertEqual(pace.fmt_interval(pace.interval(2.7, 15)), "1.7")
        self.assertEqual(pace.fmt_interval(0.0), "0")
        self.assertEqual(pace.fmt_interval(0.04), "0")


class LimitsTest(unittest.TestCase):
    def test_shipped_table(self):
        self.assertEqual(pace.limits("gemini-3.1-flash-lite")[:2], (15, 500))
        self.assertEqual(pace.limits("gemini-3.5-flash-lite")[:2], (15, 500))
        self.assertEqual(pace.limits("gemini-3-flash")[:2], (5, 20))
        self.assertEqual(pace.limits("gemini-2.5-flash")[:2], (5, 20))

    def test_unknown_model_is_conservative(self):
        self.assertEqual(pace.limits("gemma-3-27b"), (10, None, "default"))

    def test_learned_value_wins(self):
        got = pace.limits("gemini-3.1-flash-lite", {"gemini-3.1-flash-lite": {"rpm": 12, "rpd": 300}})
        self.assertEqual(got, (12, 300, "learned"))

    def test_learn_from_events(self):
        stored = {}
        events = [runner.Event("minute", limit=15), runner.Event("day", limit=500), runner.Event("busy", limit=7),
                  runner.Event("minute", limit=None)]
        self.assertTrue(pace.learn(stored, "m", events))
        self.assertEqual(stored, {"m": {"rpm": 15, "rpd": 500}})
        self.assertFalse(pace.learn(stored, "m", events))


class LatencyTest(unittest.TestCase):
    def run_steps(self, steps):
        """steps: [(seconds since the last step, number of retry lines before it, progress step)]"""
        clock = Clock()
        mon = runner.Monitor(step=1, clock=clock)
        mon.feed("err", "frame", frame(0))
        n = 0
        for dt, retries, k in steps:
            clock.t += dt
            for i in range(retries):
                mon.feed("err", "line", "Retry attempt %d due to something (rotating key)" % (i + 1))
            n += k
            mon.feed("err", "frame", frame(n))
        return mon

    def test_typical_without_the_wait(self):
        mon = self.run_steps([(4.4, 0, 1)] * 6)
        self.assertAlmostEqual(pace.measured(mon.gaps, 1.7), 2.7, places=6)

    def test_typical_is_the_mean_not_the_median(self):
        # many short items and a few long ones: the median would promise a plan that is far too short
        gaps = [2.0] * 6 + [10.0] * 4
        self.assertAlmostEqual(pace.measured(gaps, 0.0), 5.2, places=6)

    def test_low_needs_enough_samples(self):
        self.assertIsNone(pace.measured_low([4.4] * 7, 1.0))
        self.assertAlmostEqual(pace.measured_low([4.4] * 8, 1.0), 3.4, places=6)

    def test_low_ignores_one_lucky_gap(self):
        gaps = [0.3] + [5.0] * 11
        self.assertAlmostEqual(pace.measured_low(gaps, 1.0), 4.0, places=6)

    def test_low_never_negative(self):
        self.assertEqual(pace.measured_low([0.5] * 10, 1.4), 0.0)

    def test_rate_never_exceeds_the_limit_whatever_the_latency(self):
        for rpm in (5, 10, 15, 30):
            for low in (0.0, 1.0, 4.0):
                wait = pace.interval(low, rpm)
                for real in (low, low + 0.5, low + 3, 10, 30):
                    self.assertLessEqual(60.0 / (real + wait), rpm / 1.1 + 1e-9, (rpm, low, real))

    def test_measured_gaps_to_interval_end_to_end(self):
        # lab: requests of 1-6 s; the low estimate (1.1 s) keeps the rate under 15 / 1.1 even for the 1.1 s requests
        gaps = [2.5] * 2 + [3.0] * 3 + [5.0] * 10
        low = pace.measured_low(gaps, 1.4)
        wait = pace.interval(low, 15)
        self.assertLessEqual(60.0 / (low + wait), 15 / 1.1 + 1e-9)

    def test_retry_gaps_are_ignored(self):
        mon = self.run_steps([(4.4, 0, 1), (30.0, 2, 1), (4.4, 0, 1), (4.4, 0, 1), (60.0, 1, 1), (4.4, 0, 1)])
        self.assertEqual(len(mon.gaps), 4)
        self.assertAlmostEqual(pace.measured(mon.gaps, 1.7), 2.7, places=6)

    def test_cached_paragraphs_are_ignored(self):
        mon = self.run_steps([(0.1, 0, 1)] * 5 + [(4.4, 0, 1)] * 3)
        self.assertEqual(len(mon.gaps), 3)

    def test_jump_larger_than_one_request_is_ignored(self):
        mon = self.run_steps([(4.4, 0, 40), (4.4, 0, 1), (4.4, 0, 1), (4.4, 0, 1)])
        self.assertEqual(len(mon.gaps), 3)

    def test_grouped_step(self):
        clock = Clock()
        mon = runner.Monitor(step=5, clock=clock)
        mon.feed("err", "frame", frame(0))
        for n in (5, 10, 15, 18):
            clock.t += 9.0
            mon.feed("err", "frame", frame(n))
        self.assertEqual(len(mon.gaps), 4)

    def test_needs_a_few_samples(self):
        self.assertIsNone(pace.measured([4.4, 4.4], 1.7))

    def test_average_is_stored_per_model_and_grouping(self):
        stored = {}
        pace.store_latency(stored, "m", 1, 2.0)
        pace.store_latency(stored, "m", 1, 4.0)
        pace.store_latency(stored, "m", 10, 12.0)
        self.assertEqual(stored["m"], {"l": 3.0, "n": 2})
        pace.store_latency(stored, "k", 1, 5.0, 1.0)
        pace.store_latency(stored, "k", 1, 5.0, 2.0)
        pace.store_latency(stored, "k", 1, 5.0, None)
        self.assertEqual(stored["k"]["lo"], 1.0)  # the smallest low estimate stays
        self.assertEqual(stored["m|10"]["l"], 12.0)
        self.assertEqual(pace.latency_of(stored, "m", 1), 3.0)
        self.assertEqual(pace.latency_of(stored, "other"), pace.DEFAULT_LATENCY)


class OwnedFlagsTest(unittest.TestCase):
    def test_measured_latency_reaches_the_flag(self):
        s = {"latency": {"gemini-3.1-flash-lite": {"l": 5.0, "lo": 2.7, "n": 3}}}
        self.assertEqual(pace.owned_flags("gemini-3.1-flash-lite", 1, s, (3, 13)), {"--interval": "1.7"})

    def test_typical_latency_does_not_shorten_the_interval(self):
        s = {"latency": {"gemini-3.1-flash-lite": {"l": 5.0, "n": 3}}}  # no low estimate stored
        self.assertEqual(pace.owned_flags("gemini-3.1-flash-lite", 1, s, (3, 13)), {"--interval": "4.4"})
        self.assertEqual(pace.owned_flags("unknown-model", 1, {}, (3, 13)), {"--interval": "6.6"})

    def test_block_size(self):
        self.assertEqual(pace.owned_flags("m", 10, {}, (3, 12))["--block_size"], "10")
        self.assertNotIn("--block_size", pace.owned_flags("m", 1, {}, (3, 12)))
        self.assertEqual(pace.owned_flags("m", 4, {}, (3, 12))["--block_size"], "4")
        self.assertNotIn("--block_size", pace.owned_flags("m", 0, {}, (3, 12)))
        self.assertNotIn("--block_size", pace.owned_flags("m", 500, {}, (3, 12)))
        self.assertNotIn("--block_size", pace.owned_flags("m", 10, {}, (3, 11)))

    def test_eta(self):
        self.assertEqual(pace.eta_seconds("1:03:20"), 3800)
        self.assertEqual(pace.eta_seconds("05:12"), 312)
        self.assertIsNone(pace.eta_seconds("?"))


if __name__ == "__main__":
    unittest.main()
