import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from novelcore import gemini
from novelcore.pool import (COOL, DAY, DEAD, READY, Pool, day_return, default_rpm)
from tests.fake_api import FakeApi, FakeClock

KEYS = ["key-aaaa-1111", "key-bbbb-2222", "key-cccc-3333"]
SCHEMA = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"id": {"type": "INTEGER"}}}}


def body(status, message, details=None, code=None):
    return json.dumps({"error": {"code": code or 0, "message": message, "status": status,
                                 "details": details or []}}).encode()


def quota(quota_id, value, retry=None):
    d = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
          "violations": [{"quotaId": quota_id, "quotaValue": str(value)}]}]
    if retry:
        d.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry})
    return d


class ClassifyTest(unittest.TestCase):
    def test_minute_limit_with_retry_and_limit(self):
        e = gemini.classify_http(429, body("RESOURCE_EXHAUSTED", "x",
                                           quota("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", 15, "17s")))
        self.assertIsInstance(e, gemini.MinuteLimit)
        self.assertEqual((e.retry_after, e.limit), (17.0, 15))

    def test_day_limit_wins_over_minute(self):
        e = gemini.classify_http(429, body("RESOURCE_EXHAUSTED", "x",
                                           quota("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 500)))
        self.assertIsInstance(e, gemini.DayLimit)
        self.assertEqual(e.limit, 500)

    def test_limit_read_from_message_when_no_details(self):
        e = gemini.classify_http(429, body("RESOURCE_EXHAUSTED", "Quota exceeded per minute, limit: 5"))
        self.assertIsInstance(e, gemini.MinuteLimit)
        self.assertEqual(e.limit, 5)

    def test_429_with_details_but_no_quota_is_minute_unknown(self):
        e = gemini.classify_http(429, body("RESOURCE_EXHAUSTED", "busy", [{"@type": "x.Help"}]))
        self.assertIsInstance(e, gemini.MinuteLimit)
        self.assertTrue(e.unknown)

    def test_429_without_details_is_throttled(self):
        for raw in (body("RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota)."), b"not json"):
            e = gemini.classify_http(429, raw)
            self.assertIsInstance(e, gemini.Throttled)
            self.assertEqual(e.kind, "throttled")
        # a quota-named 429 stays what it was
        named = gemini.classify_http(429, body("RESOURCE_EXHAUSTED", "x", quota("GenerateRequestsPerMinutePerProjectPerModel", 15)))
        self.assertIsInstance(named, gemini.MinuteLimit)

    def test_other_statuses(self):
        self.assertIsInstance(gemini.classify_http(503, body("UNAVAILABLE", "busy")), gemini.Unavailable)
        self.assertIsInstance(gemini.classify_http(500, b""), gemini.Unavailable)
        self.assertIsInstance(gemini.classify_http(404, body("NOT_FOUND", "no")), gemini.ModelNotFound)
        self.assertIsInstance(gemini.classify_http(403, body("PERMISSION_DENIED", "no")), gemini.InvalidKey)
        self.assertIsInstance(gemini.classify_http(401, b""), gemini.InvalidKey)
        invalid = body("INVALID_ARGUMENT", "API key not valid.",
                       [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}])
        self.assertIsInstance(gemini.classify_http(400, invalid), gemini.InvalidKey)
        self.assertIsInstance(gemini.classify_http(400, body("INVALID_ARGUMENT", "bad field")), gemini.BadRequest)


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi(KEYS, FakeClock(auto=False), unknown_models={"gone"}, invalid_keys={2},
                           faults={2: "empty", 3: "max_tokens", 4: "garbage"}).start()
        self.addCleanup(self.api.stop)

    def call(self, model="m-flash", key=KEYS[0], **kw):
        user = 'TEXT (x)\n[{"id": 1, "text": "Hello there"}]'
        return gemini.generate(model, key, "SYS", user, SCHEMA, kw.pop("temperature", 0.7),
                               self.api.base_url, kw.pop("timeout", 10))

    def test_request_shape_and_result(self):
        res = self.call()
        self.assertEqual(res.finish, "STOP")
        self.assertEqual(res.json[0]["id"], 1)
        self.assertEqual(res.usage["promptTokenCount"], 10)
        req = self.api.log[0]["body"]
        cfg = req["generationConfig"]
        self.assertEqual(cfg["responseMimeType"], "application/json")
        self.assertEqual(cfg["maxOutputTokens"], 65536)
        self.assertEqual(cfg["temperature"], 0.7)
        self.assertNotIn("topK", cfg)
        self.assertEqual(req["systemInstruction"]["parts"][0]["text"], "SYS")
        cats = {s["category"]: s["threshold"] for s in req["safetySettings"]}
        self.assertEqual(len(cats), 4)
        self.assertEqual(set(cats.values()), {"BLOCK_NONE"})

    def test_errors_are_typed(self):
        self.call()
        with self.assertRaises(gemini.EmptyAnswer):
            self.call()
        with self.assertRaises(gemini.Truncated):
            self.call()
        self.assertIsNone(self.call().json)  # not JSON: kept as text, json None
        with self.assertRaises(gemini.ModelNotFound):
            self.call(model="gone")
        with self.assertRaises(gemini.InvalidKey):
            self.call(key=KEYS[2])
        with self.assertRaises(gemini.InvalidKey):
            self.call(key="unknown-key-zzzz")

    def test_network_failure_is_unavailable(self):
        self.api.stop()
        with self.assertRaises(gemini.Unavailable):
            self.call(timeout=2)
        self.api = FakeApi(KEYS, FakeClock(auto=False)).start()  # for cleanup

    def test_read_timeout_is_its_own_kind_of_unavailable(self):
        slow = FakeApi(KEYS, FakeClock(auto=False), latency=1.0).start()
        self.addCleanup(slow.stop)
        with self.assertRaises(gemini.TimedOut) as ctx:
            gemini.generate("m-flash", KEYS[0], "SYS", 'TEXT (x)\n[{"id": 1, "text": "Hi"}]', SCHEMA, 0.7,
                            slow.base_url, 0.2)
        self.assertIsInstance(ctx.exception, gemini.Unavailable)
        self.assertEqual(ctx.exception.kind, "timeout")

    def test_base_from_environment(self):
        import os
        old = os.environ.get("NOVELCORE_API_BASE")
        os.environ["NOVELCORE_API_BASE"] = "http://example.invalid/"
        try:
            self.assertEqual(gemini.default_base(), "http://example.invalid/")
        finally:
            if old is None:
                del os.environ["NOVELCORE_API_BASE"]
            else:
                os.environ["NOVELCORE_API_BASE"] = old

    def test_prompt_block_and_empty_text(self):
        with self.assertRaises(gemini.EmptyAnswer):
            gemini.parse_response(json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode())
        with self.assertRaises(gemini.EmptyAnswer):
            gemini.parse_response(json.dumps({"candidates": [{"finishReason": "SAFETY"}]}).encode())
        with self.assertRaises(gemini.EmptyAnswer):
            gemini.parse_response(json.dumps(
                {"candidates": [{"content": {"parts": [{"text": " "}]}, "finishReason": "STOP"}]}).encode())


class PoolTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(start=1_760_000_000.0, auto=False)
        self.events = []

    def pool(self, models=("a-flash-lite",), keys=KEYS, **kw):
        kw.setdefault("shared_limit", False)
        return Pool(keys, models, self.clock, on_change=lambda *a: self.events.append(a), **kw)

    def test_rpm_table(self):
        self.assertEqual((default_rpm("gemini-3.1-flash-lite"), default_rpm("gemini-3.5-flash"),
                          default_rpm("gemma-x")), (15, 5, 10))

    def test_window_is_rpm_over_1_1_and_slides(self):
        p = self.pool(keys=KEYS[:1])
        got = [p.acquire() for _ in range(13)]
        self.assertTrue(all(g.pair for g in got))
        full = p.acquire()
        self.assertIsNone(full.pair)
        self.assertEqual(full.reason, "rate")
        self.assertAlmostEqual(full.until, got[0].pair.window[0] + 60.0)
        self.clock.advance(60.5)
        self.assertIsNotNone(p.acquire().pair)

    def test_spreads_over_keys_and_is_model_major(self):
        p = self.pool(models=("a-flash-lite", "b-flash-lite"))
        used = {p.acquire().pair.key_index for _ in range(3)}
        self.assertEqual(used, {0, 1, 2})
        for _ in range(3 * 13 - 3):
            self.assertEqual(p.acquire().pair.model, "a-flash-lite")
        self.assertIsNone(p.acquire().pair)  # waits instead of leaving the first model

    def test_minute_limit_cools_clamped_and_learns(self):
        p = self.pool(keys=KEYS[:2])
        pair = p.acquire().pair
        until = p.minute_limit(pair, 17, 4)
        self.assertEqual(until, self.clock.now() + 20)
        self.assertEqual(p.rpm("a-flash-lite"), 4)
        other = p.acquire().pair
        self.assertEqual(other.key_index, 1)
        self.assertEqual(p.minute_limit(other, 1) - self.clock.now(), 8)  # clamped up
        self.assertEqual(p.minute_limit(other, 500) - self.clock.now(), 90)  # clamped down, the longer kept
        self.clock.advance(91)
        self.assertEqual(p.states()[0]["state"], READY)

    def test_day_limit_and_next_model(self):
        p = self.pool(models=("a-flash-lite", "b-flash-lite"), keys=KEYS[:2])
        for _ in range(2):
            p.day_limit(p.acquire().pair)
        nxt = p.acquire().pair
        self.assertEqual(nxt.model, "b-flash-lite")
        self.assertTrue(any(e[1] == DAY for e in self.events))

    def test_day_return_is_pacific_midnight_plus_margin(self):
        winter = dt.datetime(2025, 12, 5, 12, 0, tzinfo=dt.timezone.utc).timestamp()  # 04:00 PST
        self.assertEqual(day_return(winter), dt.datetime(2025, 12, 6, 8, 1, tzinfo=dt.timezone.utc).timestamp())
        summer = dt.datetime(2025, 7, 5, 12, 0, tzinfo=dt.timezone.utc).timestamp()  # 05:00 PDT
        self.assertEqual(day_return(summer), dt.datetime(2025, 7, 6, 7, 1, tzinfo=dt.timezone.utc).timestamp())

    def test_least_recently_used_key_goes_first(self):
        p = self.pool()
        order = [p.acquire().pair.key_index for _ in range(7)]
        self.assertEqual(order, [0, 1, 2, 0, 1, 2, 0])
        p.dead(p.pairs[1], "invalid key")
        self.assertEqual([p.acquire().pair.key_index for _ in range(4)], [2, 0, 2, 0])

    def test_dead_and_exhausted(self):
        p = self.pool(keys=KEYS[:2])
        p.dead(p.acquire().pair, "invalid key")
        self.assertEqual(p.acquire().pair.key_index, 1)
        p.dead_model("a-flash-lite", "model not found")
        res = p.acquire()
        self.assertTrue(res.exhausted)
        p.revive_dead()
        self.assertIsNotNone(p.acquire().pair)

    def test_waits_for_earliest_return(self):
        p = self.pool(keys=KEYS[:2])
        a, b = p.acquire().pair, p.acquire().pair
        p.minute_limit(a, 30)
        self.clock.advance(5)
        p.minute_limit(b, 10)
        res = p.acquire()
        self.assertIsNone(res.pair)
        self.assertEqual(res.reason, COOL)
        self.assertEqual(res.until, min(x.until for x in p.pairs))

    def test_state_file_roundtrip_without_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pool.json"
            p = self.pool(state_path=path)
            p.day_limit(p.acquire().pair)
            p.minute_limit(p.acquire().pair, 30, 7)
            p.dead(p.acquire().pair, "invalid key")
            text = path.read_text(encoding="utf-8")
            for k in KEYS:
                self.assertNotIn(k, text)
            q = self.pool(state_path=path)
            self.assertEqual([s["state"] for s in q.states()], [DAY, COOL, DEAD])
            self.assertEqual(q.rpm("a-flash-lite"), 7)
            self.clock.advance(100)
            q2 = self.pool(state_path=path)  # the cooldown is over, the day mark and dead stay
            self.assertEqual([s["state"] for s in q2.states()], [DAY, READY, DEAD])
            q3 = self.pool(keys=["other-key"], state_path=path)  # other keys are not affected
            self.assertEqual(q3.states()[0]["state"], READY)


if __name__ == "__main__":
    unittest.main()
