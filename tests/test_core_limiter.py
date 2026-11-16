import json
import random
import tempfile
import unittest
from pathlib import Path

from novelcore import gemini
from novelcore.pool import COOL, DEFAULT_PACE, PROBING, READY, SHUT_LIMIT, THROTTLED, Pool, clean_pace
from novelcore.run import MAX_UNAVAILABLE, retry_delay
from tests.core_support import KEYS, MODEL, CoreCase
from tests.fake_api import FakeClock

KEYS8 = [f"test-key-{i}-SECRETSECRET" for i in range(8)]
M = "a-flash-lite"
START = 1_760_000_000.0


def window_peak(times, window=60.0, eps=1e-6) -> int:
    """Most sends in any half-open window of `window` seconds (eps absorbs float noise)."""
    ts = sorted(times)
    best, lo = 0, 0
    for hi, t in enumerate(ts):
        while ts[lo] <= t - window + eps:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


class PaceSetting(unittest.TestCase):
    def test_default_range_and_errors(self):
        self.assertEqual(DEFAULT_PACE, 5)
        self.assertEqual(clean_pace(None), 5)
        self.assertEqual((clean_pace(1), clean_pace("120"), clean_pace(7.5)), (1, 120, 7.5))
        for bad in (0, 0.5, 121, -3, "fast", float("nan"), []):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    clean_pace(bad)

    def test_pool_rejects_a_bad_pace(self):
        with self.assertRaises(ValueError):
            Pool(KEYS, (M,), FakeClock(auto=False), pace=200)


class FixedRateTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(start=START, auto=False)

    def pool(self, keys=KEYS8, pace=24, **kw):
        return Pool(keys, (M,), self.clock, pace=pace, **kw)

    def drive(self, p, seconds, step=0.1):
        """Ask for sends all the time; returns (times, key indexes)."""
        times, keys = [], []
        end = self.clock.now() + seconds
        while self.clock.now() < end:
            while True:
                got = p.acquire()
                if got.pair is None:
                    break
                times.append(self.clock.now())
                keys.append(got.pair.key_index)
            self.clock.advance(step)
        return times, keys

    def test_sends_are_evenly_spaced(self):
        p = self.pool()
        self.assertIsNotNone(p.acquire().pair)
        second = p.acquire()
        self.assertIsNone(second.pair)
        self.assertEqual(second.reason, "rate")
        self.assertAlmostEqual(second.until - self.clock.now(), 60 / 24)
        self.clock.advance(2.25)
        self.assertIsNone(p.acquire().pair)
        self.clock.advance(0.25)
        self.assertIsNotNone(p.acquire().pair)

    def test_no_catching_up_after_an_idle_gap(self):
        p = self.pool()
        p.acquire()
        self.clock.advance(1000)
        self.assertIsNotNone(p.acquire().pair)  # one send at once ...
        nxt = p.acquire()
        self.assertIsNone(nxt.pair)  # ... but not a second one for the time that was missed
        self.assertAlmostEqual(nxt.until - self.clock.now(), 2.5)
        self.clock.advance(2.5)
        self.assertIsNotNone(p.acquire().pair)
        self.assertIsNone(p.acquire().pair)

    def test_never_more_than_pace_in_a_minute_and_never_closer_than_the_gap(self):
        for pace in (6, 24, 60, 120):
            for keys in (1, 3, 8):
                with self.subTest(pace=pace, keys=keys):
                    self.clock = FakeClock(start=START, auto=False)
                    p = self.pool(keys=KEYS8[:keys], pace=pace)
                    eff = min(pace, keys * 13)  # a key is held to 15 / 1.1 = 13 a minute
                    times, _ = self.drive(p, 600, step=0.1)
                    self.assertLessEqual(window_peak(times), pace)
                    gaps = [b - a for a, b in zip(times, times[1:])]
                    self.assertGreaterEqual(min(gaps), 60 / eff - 1e-6)
                    self.assertGreater(len(times), 600 / 60 * eff * 0.9 - 2)  # and it is not slower than set

    def test_pace_is_held_through_idle_gaps(self):
        p = self.pool(pace=30)
        times = []
        for rest in (0, 500, 3, 0.5, 90):
            self.clock.advance(rest)
            for _ in range(40):
                t, _ = self.drive(p, 7, step=0.05)
                times += t
        self.assertLessEqual(window_peak(times), 30)
        self.assertGreaterEqual(min(b - a for a, b in zip(times, times[1:])), 2.0 - 1e-6)

    def test_pace_never_exceeds_the_per_key_limits_of_ready_pairs(self):
        p = self.pool(keys=KEYS8[:1], pace=120)  # one key: 13 a minute
        times, _ = self.drive(p, 300)
        self.assertGreaterEqual(min(b - a for a, b in zip(times, times[1:])), 60 / 13 - 1e-6)
        self.assertEqual(p.pace_info()["effective"], 13)
        q = self.pool(keys=KEYS8[:2], pace=24)  # two keys: 26 a minute, the set pace is lower
        self.assertEqual(q.pace_info()["effective"], 24)
        q.day_limit(q.pairs[0])  # one key is out for the day: the other one can take 13
        self.assertEqual(q.pace_info()["effective"], 13)

    def test_keys_are_used_in_turn(self):
        for n in (1, 3, 8):
            with self.subTest(keys=n):
                self.clock = FakeClock(start=START, auto=False)
                p = self.pool(keys=KEYS8[:n], pace=24)
                _, keys = self.drive(p, 300, step=0.25)
                counts = [keys.count(i) for i in range(n)]
                self.assertLessEqual(max(counts) - min(counts), 1, counts)

    def test_old_state_file_with_a_saved_rate_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.json"
            first = self.pool(state_path=path)
            first.day_limit(first.acquire().pair)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("rates", saved)
            for k in KEYS8:
                self.assertNotIn(k, path.read_text(encoding="utf-8"))
            saved["rates"] = {M: {"rate": 31.0, "at": self.clock.now() - 10}}  # the old adaptive limiter's field
            path.write_text(json.dumps(saved), encoding="utf-8")
            q = self.pool(state_path=path)
            self.assertEqual(q.states()[0]["state"], "day")  # the rest of the file still counts
            self.assertEqual(q.pace, 24)  # the saved rate has no effect
            self.assertIsNotNone(q.acquire().pair)


class ThrottleStateTest(unittest.TestCase):
    """The shared shut state, with a manual clock: every call below is one step of the story."""

    def setUp(self):
        self.clock = FakeClock(start=START, auto=False)
        self.p = Pool(KEYS8[:3], (M, "b-flash-lite"), self.clock, pace=24)

    def send(self):
        """One granted send (the clock moves past the limiter's gap first)."""
        self.clock.advance(2.5)
        got = self.p.acquire()
        self.assertIsNotNone(got.pair, got)
        return got

    def trip(self):
        """Three throttled answers in a row: the third starts the first pause, which is returned."""
        self.assertIsNone(self.p.throttled(self.send().ticket))
        self.assertIsNone(self.p.throttled(self.send().ticket))
        return self.p.throttled(self.send().ticket)

    def test_a_lone_throttled_answer_starts_no_pause(self):
        self.assertIsNone(self.p.throttled(self.send().ticket))
        self.assertEqual((self.p.pauses, self.p.retried, self.p.paused_seconds()), (0, 1, 0))
        self.assertIsNotNone(self.send().pair)  # sending goes on

    def test_three_of_the_last_eight_answers_start_a_pause(self):
        def feed(pattern):
            """T = throttled, o = ok, x = a 503 (no verdict); returns the pause the last T started."""
            pause = None
            for c in pattern:
                got = self.send()
                if c == "T":
                    pause = self.p.throttled(got.ticket)
                elif c == "o":
                    self.p.success(got.pair, got.ticket)
                else:
                    self.p.finish(got.ticket)
            return pause

        self.assertIsNone(feed("TooToooo" + "o" + "T"))  # the first T has left the last eight
        self.assertEqual(self.p.pauses, 0)
        self.setUp()
        self.assertEqual(feed("ToooTooT")["seconds"], 60)  # three of the last eight
        self.assertEqual(self.p.pauses, 1)

    def test_three_in_a_row_start_a_pause_and_503s_neither_reset_nor_feed_the_window(self):
        pause = None
        for _ in range(3):
            for _ in range(10):  # ten 503s between the answers
                self.p.finish(self.send().ticket)
            pause = self.p.throttled(self.send().ticket)
        self.assertEqual(pause["seconds"], 60)
        self.setUp()
        for _ in range(2):  # ok answers between the throttled ones break the row, not the window count
            self.assertIsNone(self.p.throttled(self.send().ticket))
            got = self.send()
            self.p.success(got.pair, got.ticket)
        self.assertEqual(self.p.throttled(self.send().ticket)["seconds"], 60)  # still 3 of the last 5

    def test_the_window_is_cleared_by_a_successful_probe(self):
        self.trip()
        self.clock.advance(60)
        probe = self.p.acquire()
        self.assertTrue(self.p.success(probe.pair, probe.ticket))
        self.assertIsNone(self.p.throttled(self.send().ticket))  # these two would have been the 4th and 5th
        self.assertIsNone(self.p.throttled(self.send().ticket))
        self.assertEqual(self.p.pauses, 1)
        self.assertEqual(self.p.throttled(self.send().ticket)["seconds"], 60)  # a third one: a new shut state

    def test_throttled_answer_pauses_every_pair_and_model(self):
        pause = self.trip()
        self.assertEqual(pause["seconds"], 60)
        self.assertEqual(self.p.pauses, 1)
        for _ in range(10):  # every pair of both models waits, whatever the time since the last send
            self.clock.advance(5)
            nxt = self.p.acquire()
            if self.clock.now() < pause["until"]:
                self.assertIsNone(nxt.pair)
                self.assertEqual((nxt.reason, nxt.until), (THROTTLED, pause["until"]))
        self.assertTrue(all(s["state"] == READY for s in self.p.states()))  # no pair is cooled

    def test_one_probe_after_sixty_seconds_then_doubling_to_the_cap(self):
        pause = self.trip()
        lengths = [pause["seconds"]]
        while True:
            self.clock.advance(pause["until"] - self.clock.now() - 0.1)
            self.assertIsNone(self.p.acquire().pair)  # a moment too early
            self.clock.advance(0.1)
            probe = self.p.acquire()
            self.assertTrue(probe.probe)
            self.assertEqual(self.p.pace_info()["phase"], PROBING)
            for _ in range(5):  # nobody else may send while the probe is out, however long it takes
                self.clock.advance(30)
                other = self.p.acquire()
                self.assertIsNone(other.pair)
                self.assertEqual(other.reason, THROTTLED)
            pause = self.p.throttled(probe.ticket)
            if pause["abort"]:
                break
            lengths.append(pause["seconds"])
        self.assertEqual(lengths, [60, 120, 240, 480, 900])
        self.assertEqual(sum(lengths), SHUT_LIMIT)

    def test_success_of_the_probe_resets_the_length(self):
        self.trip()
        self.clock.advance(60)
        probe = self.p.acquire()
        self.assertEqual(self.p.throttled(probe.ticket)["seconds"], 120)
        self.clock.advance(120)
        probe = self.p.acquire()
        self.assertTrue(probe.probe)
        self.assertTrue(self.p.success(probe.pair, probe.ticket))
        self.assertEqual(self.p.pace_info()["phase"], "open")
        nxt = self.send()  # normal pacing again, no probe
        self.assertFalse(nxt.probe)
        self.assertEqual(self.trip()["seconds"], 60)  # the next shut state starts over
        self.assertEqual(self.p.pauses, 3)

    def test_requests_in_flight_do_not_lengthen_the_pause(self):
        flying = [self.send() for _ in range(6)]
        self.assertIsNone(self.p.throttled(flying[0].ticket))
        self.assertIsNone(self.p.throttled(flying[1].ticket))
        first = self.p.throttled(flying[2].ticket)
        self.assertEqual(first["seconds"], 60)
        for g in flying[3:]:
            self.assertIsNone(self.p.throttled(g.ticket))  # answered after the pause began: no change
        self.assertEqual(self.p.pauses, 1)
        flying = flying[2:]  # (the first two are answered; the others are still the "old" ones below)
        self.clock.advance(60)
        probe = self.p.acquire()
        self.assertTrue(probe.probe)
        # an old one answers while the probe is out
        self.assertIsNone(self.p.throttled(flying[2].ticket))
        self.assertEqual(self.p.pace_info()["phase"], PROBING)
        self.assertFalse(self.p.success(flying[3].pair, flying[3].ticket))  # nor does an old success end it
        self.assertEqual(self.p.pace_info()["phase"], PROBING)
        self.assertEqual(self.p.throttled(probe.ticket)["seconds"], 120)  # one doubling per probe
        self.clock.advance(120)
        probe = self.p.acquire()
        self.assertIsNone(self.p.throttled(flying[1].ticket))
        self.assertTrue(self.p.success(probe.pair, probe.ticket))
        self.assertIsNone(self.p.throttled(flying[0].ticket))  # late, after recovery: still old news
        self.assertEqual(self.p.pace_info()["phase"], "open")

    def test_a_probe_without_a_verdict_hands_the_probe_on(self):
        self.trip()
        self.clock.advance(60)
        probe = self.p.acquire()
        self.assertTrue(probe.probe)
        self.p.finish(probe.ticket)  # a 503 or a timeout
        self.clock.advance(2.5)
        again = self.p.acquire()
        self.assertTrue(again.probe)
        self.assertNotEqual(again.ticket, probe.ticket)
        self.p.finish(probe.ticket)  # a late repeat of the old call changes nothing
        self.assertEqual(self.p.pace_info()["phase"], PROBING)

    def test_paused_seconds_and_stop_after_thirty_minutes(self):
        self.assertEqual(self.p.paused_seconds(), 0)
        pause = self.trip()
        self.clock.advance(25)
        self.assertEqual(self.p.paused_seconds(), 25)
        while not pause["abort"]:
            self.clock.advance(pause["until"] - self.clock.now())
            probe = self.p.acquire()
            pause = self.p.throttled(probe.ticket)
        self.assertEqual(self.p.paused_seconds(), SHUT_LIMIT)
        got = self.p.acquire()
        self.assertTrue(got.exhausted)
        self.assertIn("30 minutes", got.reason)
        self.assertEqual(self.p.pauses, 5)


class RetryDelayTest(unittest.TestCase):
    def test_sequence_cap_and_jitter(self):
        class Mid:
            def uniform(self, a, b):
                return (a + b) / 2

        self.assertEqual([retry_delay(n, Mid()) for n in range(1, 9)], [2, 4, 8, 16, 32, 60, 60, 60])
        rng = random.Random(7)
        for n, base in ((1, 2), (2, 4), (3, 8), (6, 60), (12, 60)):
            seen = [retry_delay(n, rng) for _ in range(500)]
            self.assertGreaterEqual(min(seen), base * 0.75)
            self.assertLessEqual(max(seen), base * 1.25)
            self.assertLess(min(seen), base * 0.85)  # the whole range is used
            self.assertGreater(max(seen), base * 1.15)


class PaceRunTest(CoreCase):
    chapters = 6
    paras = 10
    per_request = 1  # 60 requests
    keys = KEYS8

    def test_pace_and_spacing_hold_in_a_run_for_several_paces(self):
        for pace, n_keys in ((12, 1), (24, 3), (60, 8), (120, 8)):
            with self.subTest(pace=pace, keys=n_keys):
                self.tearDown_run()
                self.setUp()
                self.api.unavailable_at = {3, 4, 20}  # retries go through the limiter too
                r, summary, _ = self.run_all(keys=KEYS8[:n_keys], pace=pace, in_flight=12)
                self.assertEqual(self.count_done(), (60, 60))
                eff = min(pace, n_keys * 13)
                self.assertLessEqual(self.api.max_in_window(), pace)
                self.assertGreaterEqual(self.api.min_gap(), 60 / eff - 1e-6)
                self.assertEqual(summary["requests"]["unavailable"], 3)
                self.assertEqual(summary["throttle"]["pauses"], 0)

    def tearDown_run(self):
        self.api.stop()
        self._tmp.cleanup()

    def test_run_is_even_across_keys_and_the_default_pace_is_5(self):
        r, summary, events = self.run_all(in_flight=12)
        self.assertEqual(r.pace, 5)
        self.assertEqual(r.in_flight, 12)
        self.assertEqual(summary["pace"]["set"], 5)
        self.assertEqual([e["pace"] for e in events if e.kind == "started"], [5])
        counts = self.api.sends_per_key()
        self.assertEqual(sum(counts), 60)
        self.assertLessEqual(max(counts) - min(counts), 1)
        self.assertLessEqual(self.api.max_in_window(), 24)
        self.assertGreater(self.clock.now() - START, 60 * 59 / 24 - 1)  # 60 sends take about 2.5 minutes

    def test_pace_and_in_flight_come_from_the_series_settings_unless_given(self):
        self.series.settings.update({"pace": 30, "in_flight": 4})
        r = self.runner()
        self.assertEqual((r.pace, r.in_flight), (30, 4))
        r = self.runner(pace=18, in_flight=2)
        self.assertEqual((r.pace, r.in_flight), (18, 2))
        self.series.settings["pace"] = 500
        with self.assertRaises(ValueError):
            self.runner()

    def test_503_of_one_request_does_not_hold_the_others_back(self):
        self.api.unavailable_at = {1, 5}
        r, summary, _ = self.run_all(in_flight=6, pace=24)
        self.assertEqual(self.count_done(), (60, 60))
        self.assertEqual(summary["requests"]["unavailable"], 2)
        times = sorted(e["t"] for e in self.api.log)
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 60 / 24 + 1e-6)
        self.assertEqual(summary["throttle"], {"throttled": 0, "retried": 0, "pauses": 0, "paused_seconds": 0})
        retried = [e for e in self.api.log if e["status"] == 503]
        for e in retried:  # the same request came back and was answered
            self.assertTrue(any(x["status"] == 200 and x["user"] == e["user"] for x in self.api.log))

    def test_a_lone_throttled_answer_is_retried_without_a_pause(self):
        self.api.shut = [(START + 10, START + 10.1)]  # exactly one send falls in it
        r, summary, events = self.run_all(in_flight=6, pace=24)
        self.assertEqual(self.count_done(), (60, 60))
        refused = [e for e in self.api.log if e["status"] == 429]
        self.assertEqual(len(refused), 1)
        self.assertEqual(summary["throttle"], {"throttled": 1, "retried": 1, "pauses": 0, "paused_seconds": 0})
        self.assertEqual(summary["blocks"]["failed"], 0)
        self.assertFalse([e for e in events if e.kind == "paused"])
        # the same request was repeated after a 5 s backoff (+/- 25%) and answered
        again = [e for e in self.api.log if e["user"] == refused[0]["user"] and e["status"] == 200]
        self.assertEqual(len(again), 1)
        self.assertGreaterEqual(again[0]["t"] - refused[0]["t"], 3.75 - 1e-6)
        # the others kept going, and the pace held, retries included
        self.assertGreaterEqual(self.api.min_gap(), 2.5 - 1e-6)
        self.assertLessEqual(self.api.max_in_window(), 24)
        times = sorted(e["t"] for e in self.api.log)
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 2.5 + 1e-6)


class InFlightTest(CoreCase):
    chapters = 8
    paras = 4
    per_request = 4
    keys = KEYS8

    def test_never_more_requests_in_flight_than_the_cap(self):
        self.api.latency = 0.05
        r, summary, events = self.run_all(in_flight=3, shared_limit=False)  # no pacing: sends overlap
        self.assertEqual(self.count_done(), (32, 32))
        self.assertEqual([e["workers"] for e in events if e.kind == "started"], [3])
        self.assertLessEqual(self.api.max_in_flight, 3)
        self.assertGreaterEqual(self.api.max_in_flight, 2)

    def test_default_cap_is_twelve(self):
        self.assertEqual(self.runner().in_flight, 12)


class ShutRunTest(CoreCase):
    chapters = 4
    paras = 10
    per_request = 1
    keys = KEYS

    def test_shut_state_pauses_all_workers_and_the_run_goes_on_after_the_probe(self):
        self.api.shut = [(START + 10, START + 100)]
        r, summary, events = self.run_all(in_flight=4)
        self.assertEqual(self.count_done(), (40, 40))
        self.assertEqual(summary["blocks"]["failed"], 0)
        refused = [e for e in self.api.log if e["status"] == 429]
        # three refusals in a row start the pause; one probe is still refused
        self.assertEqual(len(refused), 4)
        self.assertEqual(summary["requests"]["throttled"], 4)
        self.assertEqual(summary["throttle"]["throttled"], 4)
        self.assertEqual(summary["throttle"]["retried"], 2)
        self.assertEqual(summary["throttle"]["pauses"], 2)
        a, b = refused[2], refused[3]
        self.assertTrue(all(not (a["t"] < e["t"] < a["t"] + 60) for e in self.api.log), "sent during pause 1")
        self.assertTrue(all(not (b["t"] < e["t"] < b["t"] + 120) for e in self.api.log), "sent during pause 2")
        self.assertGreaterEqual(b["t"] - a["t"], 60)
        self.assertGreaterEqual(summary["throttle"]["paused_seconds"], 180)
        self.assertLess(summary["throttle"]["paused_seconds"], 185)
        # a refused request came back unchanged and was answered
        self.assertTrue(any(e["status"] == 200 and e["user"] == a["user"] for e in self.api.log))
        kinds = [e.kind for e in events if e.kind in ("paused", "unpaused")]
        self.assertEqual(kinds, ["paused", "paused", "unpaused"])
        self.assertTrue(all(s["state"] == READY for s in r.pool.states()))

    def test_run_stops_after_thirty_minutes_of_pauses_and_can_be_resumed(self):
        self.api.shut = [(START + 5, START + 1e9)]
        r, summary, events = self.run_all(in_flight=4)
        self.assertIn("30 minutes", summary["error"])
        self.assertTrue(summary["stopped"])
        self.assertEqual(summary["requests"]["throttled"], 8)  # three refusals in a row and five probes
        self.assertEqual(summary["throttle"]["retried"], 2)
        self.assertEqual(summary["throttle"]["pauses"], 5)
        self.assertEqual(summary["throttle"]["paused_seconds"], SHUT_LIMIT)
        done, total = self.count_done()
        self.assertLess(done, total)
        self.assertEqual(summary["blocks"]["failed"], 0)  # a refusal fails no block
        sent = len(self.api.log)
        self.api.shut = []
        self.runner().run()
        self.assertEqual(self.count_done(), (40, 40))
        texts = [t for e in self.api.log if e["status"] == 200 for t in e["texts"]]
        self.assertEqual(len(texts), len(set(texts)), "a finished block was translated twice")
        self.assertGreater(len(self.api.log), sent)

    def test_debug_log_has_the_marks_and_the_pauses(self):
        import os
        path = self.dir / "debug.jsonl"
        os.environ["NOVELCORE_DEBUG_LOG"] = str(path)
        self.addCleanup(os.environ.pop, "NOVELCORE_DEBUG_LOG", None)
        self.api.shut = [(START + 10, START + 50)]
        self.run_all(in_flight=2)
        lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        sends = [x for x in lines if "status" in x]
        self.assertTrue(all("mark" in x and "ticket" in x for x in sends))
        self.assertEqual([x["event"] for x in lines if "event" in x], ["pause", "probe", "resume"])
        pause = next(x for x in lines if x.get("event") == "pause")
        self.assertEqual(pause["seconds"], 60)
        self.assertNotIn("SECRET", path.read_text(encoding="utf-8"))
        marks = sorted(x["mark"] for x in sends)
        self.assertGreaterEqual(min(b - a for a, b in zip(marks, marks[1:])), 2.5 - 1e-6)


class AllowanceTest(CoreCase):
    chapters = 12
    paras = 25
    per_request = 1
    keys = KEYS8
    api_args = {"bucket": {"capacity": 5, "per_minute": 30, "debt": 20}}

    def test_a_pace_below_the_allowance_is_never_throttled(self):
        r, summary, events = self.run_all(in_flight=16)
        self.assertEqual(self.count_done(), (300, 300))
        self.assertEqual(summary["requests"].get("throttled", 0), 0)
        self.assertEqual(summary["requests"].get("minute", 0), 0)
        self.assertNotIn(COOL, {e["state"] for e in events if e.kind == "pair"})
        self.assertLessEqual(self.api.max_in_window(), 24)
        self.assertTrue(self.requested_order_ok())


class OverrunTest(CoreCase):
    chapters = 4
    paras = 10
    per_request = 1
    keys = KEYS
    api_args = {"bucket": {"capacity": 3, "per_minute": 20, "debt": 5}}

    def test_a_pace_above_the_allowance_pauses_and_still_finishes(self):
        r, summary, events = self.run_all(pace=60, in_flight=4)
        self.assertEqual(self.count_done(), (40, 40))
        self.assertGreater(summary["throttle"]["pauses"], 0)
        self.assertEqual(summary["blocks"]["failed"], 0)
        self.assertGreater(summary["throttle"]["paused_seconds"], 0)
        self.assertTrue(self.requested_order_ok())


class QuotaNamed429Test(CoreCase):
    chapters = 3
    paras = 12
    per_request = 2
    api_args = {"rpm": 3, "retry_delay": 17}

    def test_quota_named_429_still_cools_only_its_pair(self):
        r, summary, events = self.run_all(in_flight=3, pace=24)
        self.assertEqual(self.count_done(), (36, 36))
        self.assertGreater(summary["requests"]["minute"], 0)
        self.assertEqual(summary["requests"].get("throttled", 0), 0)
        self.assertEqual(summary["throttle"]["pauses"], 0)
        self.assertIn(COOL, {e["state"] for e in events if e.kind == "pair"})
        self.assertEqual(r.pool.rpm(MODEL), 3)


class GiveUpTest(CoreCase):
    chapters = 1
    paras = 2
    per_request = 2

    def test_service_that_keeps_failing_stops_the_run_after_the_limit(self):
        self.api.unavailable_at = set(range(1, 100))
        r, summary, _ = self.run_all(keys=KEYS[:1])
        self.assertEqual(summary["requests"]["unavailable"], MAX_UNAVAILABLE)
        self.assertIn("keeps failing", summary["error"])
        self.assertEqual(summary["throttle"]["pauses"], 0)
        self.assertEqual(self.count_done()[0], 0)


class TimeoutTest(CoreCase):
    chapters = 1
    paras = 4
    per_request = 2

    def test_a_timeout_is_repeated_like_a_503_and_counted_apart(self):
        calls = [0]

        def generate(*a, **kw):
            calls[0] += 1
            if calls[0] == 1:
                raise gemini.TimedOut("network: TimeoutError")
            return gemini.generate(*a, **kw)

        r, summary, _ = self.run_all(keys=KEYS[:1], generate=generate)
        self.assertEqual(self.count_done(), (4, 4))
        self.assertEqual(summary["requests"]["timeout"], 1)
        self.assertEqual(summary["throttle"]["pauses"], 0)


if __name__ == "__main__":
    unittest.main()
