"""The Terms view-model with a real library behind it (QCoreApplication, real lanes, the real helper process): the table model
(QAbstractItemModelTester, QSignalSpy), the three tabs and their numbers, the Blocking count fed to Books, the search, the type
filter, edits in place, choices (chips), Confirm N, bulk changes with snapshots and Undo, Import / Export, the language, the
reader's places and RowSelection keys. Skipped without PySide6."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

from tests import termsdemo  # noqa: E402

KEEP: list = []


def pump(cond, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            QCoreApplication.processEvents()
            return True
        time.sleep(0.005)
    return False


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class Base(unittest.TestCase):
    specs = None
    select = "2697-2750"

    @classmethod
    def setUpClass(cls):
        cls.qapp = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="novelterms-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.lib = self.root / "Novel library"
        self.lib.mkdir()
        from tests import libfixture
        libfixture.build(self.lib, self.specs or [termsdemo.knights()])
        self.make()

    def make(self):
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        os.environ["NOVELGUI_DATA"] = str(data)
        os.environ.pop("NOVELGUI_NOTIFY", None)
        os.environ.pop("NOVELGUI_TRAY", None)
        win = {"books_last": {"series": "Knights", "book": "Book 1"}, "screen": "terms"}
        (data / "settings.json").write_text(json.dumps({"library": str(self.lib), "win": win}), encoding="utf-8")
        from novelgui.runtime import notify, tray as trays
        from novelgui.runtime.assemble import Parts
        parts = Parts(settings_dir=data, local=data / "local", tray=trays.RecordingTray(data, available=False))
        parts.notifier = notify.RecordingNotifier(data)
        parts.app.notifier = parts.notifier
        self.parts, self.books, self.app, self.terms = parts, parts.books_vm, parts.app, parts.terms_vm
        self.terms.mine_names = False
        KEEP.append(parts)
        self.addCleanup(parts.close)
        self.assertTrue(pump(lambda: self.books.view == "chapters" and not self.books.session.scanning), "books did not settle")
        if self.select:
            self.assertTrue(self.books.commitRange(self.select))
        self.settle()

    def settle(self, rows=True):
        ok = pump(lambda: self.terms._loaded and not self.terms._loading and not self.terms._scanning
                  and not self.terms._arrange_t.isActive() and not self.terms._recount_t.isActive()
                  and not self.terms._sync_t.isActive() and self.terms.lanes.idle() and (not rows or self.terms.count >= 0))
        self.assertTrue(ok, "the terms did not settle")
        pump(lambda: False, 0.15)
        pump(lambda: self.terms.lanes.idle() and not self.terms._arrange_t.isActive(), 5)

    def names(self):
        return [r[0] for r in self.terms.model.rows]

    def wait(self, cond, what="condition"):
        self.assertTrue(pump(cond), "timed out: " + what)


class TableTests(Base):
    def test_blocking_tab_lists_the_unconfirmed_terms_of_the_selection(self):
        t = self.terms
        self.assertEqual(t.tab, "blocking")
        self.assertEqual(self.names()[:3], ["Gawain", "Lot", "Silver Spear"])
        self.assertEqual(len(self.names()), 8)
        self.assertEqual(self.books.blocking_terms, 8, "the number Books shows as `Review 8 terms`")
        self.assertEqual(t.blockingCount, 8)

    def test_model_passes_the_item_model_tester(self):
        QAbstractItemModelTester(self.terms.model, QAbstractItemModelTester.FailureReportingMode.Fatal)
        self.terms.selectTab("notconf")
        self.settle()
        self.assertGreater(self.terms.count, 8)

    def test_tabs_and_counts(self):
        t = self.terms
        counts = {x["id"]: x["count"] for x in t.tabList}
        self.assertEqual(counts, {"blocking": "8", "notconf": "40", "confirmed": "4"})
        t.selectTab("confirmed")
        self.settle()
        self.assertEqual(set(self.names()), {"Lancelot", "Arthur", "Camelot", "Excalibur"})

    def test_a_confirmed_term_with_a_second_rendering_is_a_choice_in_not_confirmed(self):
        t = self.terms
        t.selectTab("notconf")
        self.settle()
        i = self.names().index("Merlin")
        row = t.model.row(i)
        self.assertIn("r", row[6])
        self.assertEqual(row[1].split("\x1f"), ["Мерлин", "Мерлен"])

    def test_no_selection_makes_blocking_dim_and_opens_not_confirmed(self):
        self.books.clearSelection()
        self.settle()
        t = self.terms
        self.assertEqual(t.tab, "notconf")
        self.assertTrue(t.tabList[0]["dim"])
        self.assertEqual(self.books.blocking_terms, 0)
        t.selectTab("blocking")
        self.assertEqual(t.tab, "notconf", "a dim tab does not open")

    def test_sorted_by_first_and_search_and_type_filter(self):
        t = self.terms
        t.selectTab("notconf")
        self.settle()
        firsts = [r[4].split("\x1f")[0] for r in t.model.rows]
        self.assertEqual(firsts, sorted(firsts, key=int))
        t.setSearch("gate")
        self.wait(lambda: t.count == 1 and self.names() == ["Moon Gate"], "search")
        self.assertFalse(t.searchZero)
        t.setSearch("zzz")
        self.wait(lambda: t.count == 0, "no hit")
        self.assertTrue(t.searchZero)
        t.closeSearch()
        t.pickTypeFilter("place")
        self.wait(lambda: t.count > 0 and all(r[2] == "place" for r in t.model.rows), "type filter")
        counts = {x["id"]: x["count"] for x in t.tabList}
        self.assertEqual(counts["confirmed"], "1", "counts follow the type filter")

    def test_search_is_debounced_on_the_lane(self):
        t = self.terms
        t.selectTab("notconf")
        self.settle()
        before = t.arranges
        for text in ("g", "ga", "gaw", "gawa", "gawai", "gawain"):
            t.setSearch(text)
        self.wait(lambda: self.names() == ["Gawain"], "search")
        self.assertLessEqual(t.arranges - before, 2, "typing fast arranges once or twice, not per key")


if __name__ == "__main__":
    unittest.main()
