"""Performance budgets of the Translate screen (review_window_arch 7, window_spec 14.21), measured, nothing shown: a
3000-chapter selection reaches the list in <= 1.2 s, a progress tick sends ONE dataChanged for ONE row, and one run-snapshot
handler (the throttled `run_progress`) takes <= 3 ms. Set NOVELGUI_PERF_REPORT=1 to print the numbers."""

import os
import statistics
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import test_translate_vm as T  # noqa: E402
from tests import translatedemo as demo  # noqa: E402

if T.HAVE_QT:
    from PySide6.QtTest import QSignalSpy

N = 3000


def report(name, value):
    if os.environ.get("NOVELGUI_PERF_REPORT") == "1":
        sys.stderr.write("\n[perf] %s: %s\n" % (name, value))


@unittest.skipUnless(T.HAVE_QT, "PySide6 is not installed")
class Big(T.Base):
    specs = [demo.knights(chapters=N, paras=1)]
    select = ""

    def test_the_first_rows_of_3000_chapters_come_within_1_2_s(self):
        best = None
        for _ in range(2):                                  # a user's own app on this PC adds noise: the better of two
            self.books.clearSelection()
            self.settle()
            t0 = time.perf_counter()
            self.books.selectAll()
            ok = T.pump(lambda: len(self.vm.chapters) == N and self.vm.chapters.row(0) != (), 10)
            took = time.perf_counter() - t0
            self.assertTrue(ok)
            best = took if best is None else min(best, took)
        report("3000 rows first rows (s)", round(best, 3))
        self.assertLess(best, 1.2)
        self.assertEqual(self.vm.chapters.row(0)[0], "2650")

    def test_a_tick_changes_one_row_and_the_handler_is_under_3_ms(self):
        vm = self.vm
        self.books.selectAll()
        self.settle()
        self.assertEqual(len(vm.chapters), N)
        run = self.begin()
        spy = QSignalSpy(vm.chapters.dataChanged)
        spans = []
        for k in range(1, 41):
            self.feed(run, "progress", index=1, done=k % 3, total=3, failed=0)
            t0 = time.perf_counter()
            self.rc._flush_progress()
            spans.append((time.perf_counter() - t0) * 1000)
        report("run_progress ms (median / max)", (round(statistics.median(spans), 2), round(max(spans), 2)))
        self.assertEqual(spy.count(), 40)               # one signal per tick, each for the one row that moved
        for k in range(spy.count()):
            a = spy.at(k)
            self.assertEqual((a[0].row(), a[1].row()), (0, 0))
        self.assertLess(statistics.median(spans), 3.0)


if __name__ == "__main__":
    unittest.main()
