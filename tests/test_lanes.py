"""The lanes of the new window: serial order, independence, cancel, generations, breathing, book handles.

Most tests use the plain `ManualPump` (no Qt); the last class runs the real Qt pump on a QCoreApplication and is
skipped when PySide6 is not installed.
"""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from novelgui import lanes
from novelgui.facade import books as fbooks
from tests.test_core_epub import make_epub

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


def drain_until(pump, pred, timeout=5.0):
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            raise AssertionError("timed out")
        pump.drain(timeout=0.02)


class Base(unittest.TestCase):
    def setUp(self):
        self.pump = lanes.ManualPump()
        self.lanes = lanes.Lanes(self.pump)
        self.addCleanup(self.lanes.close)

    def settle(self):
        drain_until(self.pump, self.lanes.idle)


class Order(Base):
    def test_a_serial_lane_runs_and_answers_in_submission_order(self):
        ran, answered = [], []
        for i in range(60):
            self.lanes.submit(lambda ctx, i=i: (ran.append(i), time.sleep(0.0005 * (i % 3)), i)[2],
                              on_result=answered.append, lane="data")
        self.settle()
        self.assertEqual(ran, list(range(60)))
        self.assertEqual(answered, list(range(60)))

    def test_items_arrive_before_the_result_and_in_order(self):
        got = []
        self.lanes.submit(lambda ctx: [ctx.emit(i) for i in range(5)] and "end",
                          on_item=lambda x: got.append(("item", x)), on_result=lambda r: got.append(("result", r)))
        self.settle()
        self.assertEqual(got, [("item", i) for i in range(5)] + [("result", "end")])

    def test_a_busy_lane_does_not_hold_the_other(self):
        gate = threading.Event()
        got = []
        self.lanes.submit(lambda ctx: gate.wait(5), on_result=lambda r: got.append("data"), lane="data")
        self.lanes.submit(lambda ctx: "read", on_result=got.append, lane="read")
        drain_until(self.pump, lambda: got == ["read"])
        gate.set()
        self.settle()
        self.assertEqual(got, ["read", "data"])

    def test_the_run_lane_is_a_thread_per_task(self):
        gate = threading.Event()
        got = []
        self.lanes.submit(lambda ctx: gate.wait(5), on_result=lambda r: got.append(1), lane="run")
        self.lanes.submit(lambda ctx: 2, on_result=got.append, lane="run")
        drain_until(self.pump, lambda: got == [2])
        gate.set()
        self.settle()

    def test_an_error_reaches_on_error_with_its_traceback(self):
        errs = []
        self.lanes.submit(lambda ctx: 1 / 0, on_error=errs.append)
        self.settle()
        self.assertIsInstance(errs[0], ZeroDivisionError)
        self.assertIn("ZeroDivisionError", errs[0].__traceback_text__)


class CancelAndGenerations(Base):
    def test_cancel_before_the_start_skips_the_task(self):
        gate = threading.Event()
        ran = []
        self.lanes.submit(lambda ctx: gate.wait(5), lane="data")
        tok = self.lanes.submit(lambda ctx: ran.append(1), on_result=ran.append, lane="data")
        tok.cancel()
        gate.set()
        self.settle()
        self.assertEqual(ran, [])

    def test_cancel_while_running_stops_the_loop_and_drops_the_reply(self):
        started = threading.Event()
        got = []

        def work(ctx):
            started.set()
            n = 0
            while not ctx.cancelled:
                n += 1
                ctx.emit(n)
                time.sleep(0.001)
            return "late"
        tok = self.lanes.submit(work, on_item=lambda x: None, on_result=got.append)
        started.wait(5)
        tok.cancel()
        self.settle()
        self.assertEqual(got, [])

    def test_a_superseded_tasks_late_reply_is_dropped(self):
        release = threading.Event()
        got = []

        def old(ctx):
            ctx.emit("old item")
            release.wait(5)
            return "old"
        self.lanes.submit(old, on_item=got.append, on_result=got.append, lane="read", group="chapters")
        drain_until(self.pump, lambda: got == ["old item"])
        self.assertEqual(self.lanes.generation("chapters"), 1)
        # a second book is opened: the first scan is superseded even if it ignores its token
        self.lanes.submit(lambda ctx: (ctx.emit("new item"), "new")[1], on_item=got.append, on_result=got.append,
                          lane="data", group="chapters")
        self.assertEqual(self.lanes.generation("chapters"), 2)
        drain_until(self.pump, lambda: got[-1:] == ["new"])
        release.set()
        self.settle()
        self.assertEqual(got, ["old item", "new item", "new"])

    def test_a_late_error_of_a_superseded_task_is_dropped_too(self):
        release = threading.Event()
        errs = []

        def old(ctx):
            release.wait(5)
            raise RuntimeError("late")
        self.lanes.submit(old, on_error=errs.append, lane="read", group="g")
        self.lanes.submit(lambda ctx: None, lane="data", group="g")
        release.set()
        self.settle()
        self.assertEqual(errs, [])


class Breathing(unittest.TestCase):
    def test_breathe_sleeps_one_ms_per_three_ms_of_work(self):
        ctx = lanes.Ctx(lambda *a: None, 1, lanes.Token())
        sleeps = []
        real = time.sleep
        lanes.time.sleep = lambda s: (sleeps.append(s), real(s))
        try:
            end = time.perf_counter() + 0.05
            calls = 0
            while time.perf_counter() < end:
                ctx.breathe()
                calls += 1
        finally:
            lanes.time.sleep = real
        self.assertGreater(calls, len(sleeps))
        self.assertGreaterEqual(len(sleeps), 5)
        self.assertLessEqual(len(sleeps), 50 // 3 + 2)
        self.assertTrue(all(s == lanes.BREATH for s in sleeps))


class BookHandles(Base):
    def test_close_lane_books_reaches_every_serial_lane(self):
        with tempfile.TemporaryDirectory() as d:
            series = Path(d) / "S"
            (series / "books").mkdir(parents=True)
            make_epub(series / "books" / "v1.epub", {"c0.xhtml": "<p>One two three.</p>"})
            path = fbooks.book_file(series, "v1")
            for lane in self.lanes.lane_names:
                self.lanes.submit(lambda ctx: len(fbooks.open_book(path).chapters), lane=lane)
            self.settle()
            held = {k for k, v in fbooks.open_handles().items() if str(path) in v}
            self.assertEqual(held, set(self.lanes.thread_names()))
            done = []
            self.lanes.close_lane_books(series, done.append)
            drain_until(self.pump, lambda: done)
            self.assertEqual(done, [len(self.lanes.lane_names)])
            held = {k for k, v in fbooks.open_handles().items() if str(path) in v}
            self.assertEqual(held, set())
            path.rename(path.with_name("moved.epub"))           # no handle blocks a move on Windows


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class QtPump(unittest.TestCase):
    def test_replies_arrive_on_the_gui_thread_through_the_event_loop(self):
        from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
        app = QCoreApplication.instance() or QCoreApplication([])
        ln = lanes.Lanes()
        self.addCleanup(ln.close)
        got = []
        for i in range(20):
            ln.submit(lambda ctx, i=i: (ctx.emit(i), i * 10)[1],
                      on_item=lambda x: got.append(("item", x, threading.current_thread() is threading.main_thread())),
                      on_result=lambda r: got.append(("result", r)), lane="data" if i % 2 else "read")
        loop = QEventLoop()
        end = time.monotonic() + 5
        while not ln.idle() and time.monotonic() < end:
            QTimer.singleShot(10, loop.quit)
            loop.exec()
        self.assertTrue(ln.idle())
        self.assertTrue(all(g[2] for g in got if g[0] == "item"))
        self.assertEqual(sorted(r for k, r, *_ in got if k == "result"), [i * 10 for i in range(20)])
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
