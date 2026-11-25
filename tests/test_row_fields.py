"""A field inside a list row keeps its focus and the typed text when the view-model updates that row (the Export From / To fields
were the first to lose them): the rename field of a Books row and the cells of Terms edited in place. Offscreen scenes
(tests/qmlharness.py); the update is one `dataChanged` for the row, sent by the view-model's own model."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import qmlharness as qh  # noqa: E402
from tests import test_books_scenes as tb  # noqa: E402
from tests import test_terms_scenes as tt  # noqa: E402

VM = "tests.shellfactory:make"


def py(name, *args):
    return {"op": "py", "name": name, "args": list(args)}


@unittest.skipUnless(qh.have_qt(), "PySide6 is not available")
class RowFields(unittest.TestCase):
    def check(self, data, acts, field, typed, kind, touch):
        r = qh.scenario("ShellScene", data, vm=VM, actions=acts, tag="rowfield_" + kind)
        before, after = r.after["typed"][field], r.after["updated"][field]
        self.assertTrue(before["activeFocus"], "the field has the focus while typing")
        self.assertEqual(before["text"].endswith(typed), True, before["text"])
        self.assertTrue(after["visible"])
        self.assertTrue(after["activeFocus"], "the row update did not take the focus away")
        self.assertEqual(after["text"], before["text"], "the typed text survived the row update")
        self.assertTrue(dict(r.events)[touch], "the view-model updated the row")

    def test_the_rename_field_of_a_books_row(self):
        data = tb.lib(tb.knights(books=2), *tb.others(), select=["Knights", "Book 2"])
        acts = [tb.WAIT, py("rename", "book", "Knights", "Book 2"), {"op": "wait", "ms": 500},
                {"op": "type", "text": "Zz"}, {"op": "wait", "ms": 100}, {"op": "dump", "name": "typed"},
                py("touchSeriesRow", 0), {"op": "wait", "ms": 400}, {"op": "dump", "name": "updated"}]
        self.check(data, acts, "renameFieldInput", "Zz", "books", "touchSeriesRow")

    def test_a_term_cell_edited_in_place(self):
        for field_name, row in (("editRen_5Input", 5),):
            acts = tt.base(tt.tv("beginEdit", row, "ren"), tt.WAIT) + [
                {"op": "type", "text": "Zz"}, {"op": "wait", "ms": 100}, {"op": "dump", "name": "typed"},
                py("touchTermRow", row), {"op": "wait", "ms": 400}, {"op": "dump", "name": "updated"}]
            self.check(tt.lib(), acts, field_name, "Zz", "terms", "touchTermRow")

    def test_a_new_arrangement_of_the_table_keeps_the_cell_being_edited(self):
        """The session tells the view-model that rows changed (a scan, a confirmation elsewhere): the table is arranged again
        on the data lane and the model gets the new cells, which must not rebuild the row under the user's cursor."""
        for field_name, field in (("editRen_5Input", "ren"), ("editAbout_5Input", "about")):
            acts = tt.base(tt.tv("beginEdit", 5, field), tt.WAIT) + [
                {"op": "type", "text": "Zz"}, {"op": "wait", "ms": 100}, {"op": "dump", "name": "typed"},
                py("arrangeTerms"), {"op": "wait", "ms": 1500}, {"op": "dump", "name": "updated"}]
            self.check(tt.lib(), acts, field_name, "Zz", "terms_arrange_" + field, "arrangeTerms")

    def test_the_about_cell_edited_in_place(self):
        acts = tt.base(tt.tv("beginEdit", 5, "about"), tt.WAIT) + [
            {"op": "type", "text": "Zz"}, {"op": "wait", "ms": 100}, {"op": "dump", "name": "typed"},
            py("touchTermRow", 5), {"op": "wait", "ms": 400}, {"op": "dump", "name": "updated"}]
        self.check(tt.lib(), acts, "editAbout_5Input", "Zz", "terms_about", "touchTermRow")


if __name__ == "__main__":
    unittest.main()
