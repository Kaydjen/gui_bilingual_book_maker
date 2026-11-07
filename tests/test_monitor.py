import os
import unittest
from pathlib import Path

from bbm_gui import runner

FIX = Path(__file__).resolve().parent / "fixtures"


def lines(name):
    return (FIX / name).read_text(encoding="utf-8").split("\n")[:-1]


def feed_all(mon, texts, stream="out"):
    """Feed lines one by one; return the guards in order."""
    return [mon.feed(stream, "line", t) for t in texts]


def with_attempt(texts, n):
    return [texts[0].replace("Retry attempt 1", "Retry attempt %d" % n)] + texts[1:]


class ClassifyTest(unittest.TestCase):
    def test_real_day_block_wrapped(self):
        mon = runner.Monitor()
        out = feed_all(mon, lines("retry_day_429.txt"))
        self.assertEqual(out[:-1], [None] * (len(out) - 1))  # nothing before the block is complete
        self.assertEqual(out[-1], "quota")
        ev = mon.event
        self.assertEqual((ev.kind, ev.limit, ev.attempt), ("day", 500, 1))
        self.assertAlmostEqual(ev.delay, 15 * 3600 + 20 * 60 + 37.06, places=1)
        self.assertTrue(mon.daily)

    def test_real_day_block_on_one_line(self):
        mon = runner.Monitor()
        one = " ".join(t.strip() for t in lines("retry_day_429.txt"))
        self.assertEqual(mon.feed("out", "line", one), "quota")
        self.assertEqual(mon.event.kind, "day")

    def test_minute_block_policy(self):
        stop = runner.Monitor(policy=lambda ev: True)
        out = feed_all(stop, lines("retry_minute_429.txt"))
        self.assertEqual(out[-1], "quota")
        self.assertEqual((stop.event.kind, stop.event.limit), ("minute", 15))
        self.assertAlmostEqual(stop.event.delay, 38.92)
        self.assertFalse(stop.daily)
        wait = runner.Monitor(policy=lambda ev: False)
        self.assertIsNone(feed_all(wait, lines("retry_minute_429.txt"))[-1])
        late = runner.Monitor(policy=lambda ev: False)  # the engine's own back-off did not help
        self.assertEqual(feed_all(late, with_attempt(lines("retry_minute_429.txt"), runner.MINUTE_ATTEMPT))[-1], "quota")

    def test_busy_stops_at_guard_attempt(self):
        mon = runner.Monitor()
        self.assertIsNone(feed_all(mon, lines("retry_503.txt"))[-1])
        self.assertEqual(mon.event.kind, "busy")
        mon = runner.Monitor()
        self.assertEqual(feed_all(mon, with_attempt(lines("retry_503.txt"), runner.GUARD_ATTEMPT))[-1], "busy")

    def test_synthetic_kinds(self):
        gone = ["Retry attempt 1 due to ClientError: 404 NOT_FOUND. {'error': {'code': 404, 'message': 'models/x is no ",
                "longer available to new users.', 'status': 'NOT_FOUND'}} (switching model)"]
        mon = runner.Monitor()
        self.assertEqual(feed_all(mon, gone)[-1], "model")
        self.assertEqual(mon.event.kind, "notfound")
        bad = ["Retry attempt 1 due to ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': ",
               "'API key not valid. Please pass a valid API key.', 'status': 'INVALID_ARGUMENT'}} (rotating key)"]
        mon = runner.Monitor()
        self.assertEqual(feed_all(mon, bad)[-1], "key")
        self.assertTrue(mon.key_error)
        zero = ["Retry attempt 1 due to ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': ",
                "'Quota exceeded for metric: x, limit: 0, model: m', 'status': 'RESOURCE_EXHAUSTED'}} (rotating key)"]
        mon = runner.Monitor()
        self.assertEqual(feed_all(mon, zero)[-1], "quota")
        self.assertEqual(mon.event.kind, "zero")
        unk = ["Retry attempt %d due to ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': ",
               "'Something new', 'status': 'RESOURCE_EXHAUSTED'}} (rotating key)"]
        mon = runner.Monitor()
        self.assertIsNone(feed_all(mon, [unk[0] % 2, unk[1]])[-1])
        self.assertEqual(mon.event.kind, "unknown")
        mon = runner.Monitor()
        self.assertEqual(feed_all(mon, [unk[0] % runner.UNKNOWN_ATTEMPT, unk[1]])[-1], "quota")

    def test_content_error_is_one_line(self):
        mon = runner.Monitor()
        self.assertIsNone(mon.feed("out", "line", "Retry attempt 2 due to ValueError: empty response"))
        self.assertEqual(mon.event.kind, "content")
        self.assertEqual(mon.feed("out", "line", "Retry attempt 5 due to ValueError: empty response"), "failed")

    def test_other_stream_and_progress_do_not_end_a_block(self):
        mon = runner.Monitor(policy=lambda ev: False)
        texts = lines("retry_minute_429.txt")
        for t in texts[:5]:
            mon.feed("out", "line", t)
        mon.feed("err", "frame", " 40%|####      | 3/8 [00:05<00:07,  1.00s/it]")
        for t in texts[5:]:
            mon.feed("out", "line", t)
        self.assertEqual(mon.event.kind, "minute")
        self.assertEqual(mon.n, 3)

    def test_unterminated_block_closes_on_next_event(self):
        mon = runner.Monitor()
        texts = lines("retry_day_429.txt")[:-1]
        feed_all(mon, texts)
        self.assertIsNone(mon.event)
        self.assertEqual(mon.feed("out", "line", "translating 4/8"), "quota")
        self.assertEqual(mon.event.kind, "day")
        mon = runner.Monitor()
        feed_all(mon, texts)
        self.assertEqual(mon.flush(), "quota")

    def test_buffer_is_capped(self):
        mon = runner.Monitor()
        mon.feed("out", "line", "Retry attempt 1 due to ClientError: 429 RESOURCE_EXHAUSTED. {")
        guard = None
        for _ in range(300):
            guard = mon.feed("out", "line", "x" * 40) or guard
        self.assertIsNotNone(mon.event)
        self.assertEqual(mon.event.kind, "unknown")
        self.assertIsNone(guard)  # attempt 1 of an unknown 429

    def test_failed_line(self):
        mon = runner.Monitor()
        self.assertEqual(mon.feed("out", "line", "Translation failed for this paragraph"), "failed")
        self.assertEqual(mon.failed, 1)


class QualityGuardTest(unittest.TestCase):
    ENGINE_LAST_ATTEMPT = 7  # the engine caches the paragraph as failed when attempt 7 fails

    def test_every_stop_comes_before_the_engines_last_attempt(self):
        for limit in (runner.GUARD_ATTEMPT, runner.UNKNOWN_ATTEMPT, runner.MINUTE_ATTEMPT):
            self.assertLess(limit, self.ENGINE_LAST_ATTEMPT)

    def test_riding_out_is_for_short_waits_only(self):
        from bbm_gui import keypool

        self.assertLessEqual(keypool.minute_cooldown(7), 10)  # a 7 s delay (+3 s margin) is ridden out
        self.assertGreater(keypool.minute_cooldown(8), 10)  # anything longer stops the run

    def test_content_failures_stop_at_the_guard(self):
        mon = runner.Monitor()
        self.assertIsNone(mon.feed("out", "line", "Retry attempt 4 due to ValueError: empty"))
        self.assertEqual(mon.feed("out", "line", "Retry attempt 5 due to ValueError: empty"), "failed")


class ResetHookTest(unittest.TestCase):
    def test_env_replaces_the_pacific_midnight(self):
        old = os.environ.get("BBM_GUI_RESET_AT")
        try:
            os.environ["BBM_GUI_RESET_AT"] = "5000"
            self.assertEqual(runner.day_return(), 5000)
            del os.environ["BBM_GUI_RESET_AT"]
            self.assertGreater(runner.day_return(), 1e9)  # a real midnight plus the margin
        finally:
            if old is None:
                os.environ.pop("BBM_GUI_RESET_AT", None)
            else:
                os.environ["BBM_GUI_RESET_AT"] = old


if __name__ == "__main__":
    unittest.main()
