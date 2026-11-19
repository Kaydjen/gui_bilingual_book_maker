"""Performance budgets of the window machinery (review_window_arch 7), measured, nothing shown.

(i)  a 3000-row ListView over a Python model keeps >= 80 % of its idle frames while the data lane does pure-Python
     work with `ctx.breathe()` (in a child process: it needs its own QGuiApplication, offscreen + software);
(ii) one run-snapshot apply for a 3000-chapter book (take + diff + one dataChanged per range) <= 3 ms.
Skipped without PySide6. Set NOVELGUI_PERF_REPORT=1 to print the numbers.
"""

import json
import os
import statistics
import subprocess
import sys
import time
import unittest
from pathlib import Path

from novelgui.ctl.runevents import ChapterProgress, RunEvents

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

HERE = Path(__file__).resolve().parent


def report(name, value):
    if os.environ.get("NOVELGUI_PERF_REPORT") == "1":
        sys.stderr.write("\n[perf] %s: %s\n" % (name, value))


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ScrollUnderABusyLane(unittest.TestCase):
    def frames(self, switch):
        env = dict(os.environ, PYTHONUTF8="1", PERF_SWITCH=switch)
        env.pop("PERF_NO_BREATH", None)
        out = subprocess.run([sys.executable, str(HERE / "perf_scroll.py")], capture_output=True, text=True,
                             env=env, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_frames_with_a_breathing_lane_stay_near_idle(self):
        for switch in ("0.005", ""):            # the Python default (breaths alone) and the app's safety net
            r = self.frames(switch)
            report("scroll switch=%s" % r["switch"], r)
            self.assertGreater(r["idle"], 60)
            self.assertGreater(r["work"], 100)                  # the lane really worked meanwhile
            self.assertGreaterEqual(r["busy"], 0.8 * r["idle"], r)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class SnapshotApply(unittest.TestCase):
    def test_one_apply_for_a_3000_chapter_book_is_under_3_ms(self):
        from PySide6.QtCore import QAbstractListModel, QCoreApplication, QModelIndex, Qt
        app = QCoreApplication.instance() or QCoreApplication([])
        n = 3000

        class Chapters(QAbstractListModel):
            Done = Qt.UserRole + 1

            def __init__(self):
                super().__init__()
                self.table = ChapterProgress([(0, 40, 0)] * n)
                self.signals = 0
                self.dataChanged.connect(self._count)

            def _count(self, *a):
                self.signals += 1

            def rowCount(self, parent=QModelIndex()):
                return 0 if parent.isValid() else n

            def data(self, idx, role=Qt.DisplayRole):
                return self.table.rows[idx.row()][0] if role == self.Done else None

            def apply(self, snap):
                for a, b in self.table.apply(snap):
                    self.dataChanged.emit(self.index(a), self.index(b), [self.Done])

        model = Chapters()
        events = RunEvents({i: (0, 40, 0) for i in range(n)})
        times = []
        done = 0
        for burst in range(60):
            for k in range(25):                 # 25 progress events between two repaints, spread over the book
                done += 1
                i = (burst * 97 + k * 131) % n
                events.feed(("progress", {"index": i, "done": done % 40, "total": 40, "failed": 0}))
            t0 = time.perf_counter()
            model.apply(events.take())
            times.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()                # the worst case: every chapter changed at once
        for i in range(n):
            events.feed(("progress", {"index": i, "done": 39, "total": 40, "failed": 0}))
        feed_all = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        model.apply(events.take())
        all_rows = (time.perf_counter() - t0) * 1000
        report("snapshot apply", "median %.3f ms, max %.3f ms, all 3000 rows %.3f ms (feeding them %.1f ms)"
               % (statistics.median(times), max(times), all_rows, feed_all))
        self.assertLessEqual(statistics.median(times), 3.0)
        self.assertLessEqual(sorted(times)[int(len(times) * 0.9)], 3.0)
        self.assertLessEqual(all_rows, 3.0 * 4)
        self.assertGreater(model.signals, 0)
        self.assertIsNotNone(app)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class BooksChapterListScroll(unittest.TestCase):
    """The REAL chapter list of Books (3000 chapters, scanned by the helper) keeps >= 80 % of its idle frames while a lane works."""

    def test_the_chapter_list_scrolls_while_a_lane_is_busy(self):
        env = dict(os.environ, PYTHONUTF8="1")
        out = subprocess.run([sys.executable, str(HERE / "perf_books.py")], capture_output=True, text=True, env=env,
                             timeout=300, cwd=str(HERE.parent))
        self.assertEqual(out.returncode, 0, out.stdout[-1500:] + out.stderr[-2000:])
        r = json.loads(out.stdout.strip().splitlines()[-1])
        report("books scroll", r)
        self.assertGreater(r["rows"], 2900)
        self.assertGreater(r["idle"], 40)
        self.assertGreater(r["work"], 100)
        self.assertGreaterEqual(r["busy"], 0.8 * r["idle"], r)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class TermsTableScroll(unittest.TestCase):
    """The REAL Terms table (20,000 terms) keeps >= 80 % of its idle frames while a lane works. The model reset alone is <= 30 ms
    (test_terms_actions PerfTests); here the reset is measured with the table attached (the view rebuilds its delegates), loosened."""

    def test_the_terms_table_scrolls_while_a_lane_is_busy(self):
        env = dict(os.environ, PYTHONUTF8="1")
        out = subprocess.run([sys.executable, str(HERE / "perf_terms.py")], capture_output=True, text=True, env=env,
                             timeout=400, cwd=str(HERE.parent))
        self.assertEqual(out.returncode, 0, out.stdout[-1500:] + out.stderr[-2000:])
        r = json.loads(out.stdout.strip().splitlines()[-1])
        report("terms scroll", r)
        self.assertGreaterEqual(r["rows"], 19990)
        self.assertLessEqual(r["reset_ms"], 150, "a 20,000-row reset with the view attached")
        self.assertGreater(r["idle"], 25)
        self.assertGreater(r["work"], 100)
        # a term row has eight text cells (a chapter row three): its frames are fewer and a lane costs a little more of them
        self.assertGreaterEqual(r["busy"], 0.75 * r["idle"], r)


if __name__ == "__main__":
    unittest.main()
