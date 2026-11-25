import unittest

from novelgui import termsmemory as tm

KEYS = ["source", "tr", "type", "count"]
TYPES = ["character", "place"]


class CleanTest(unittest.TestCase):
    def test_valid_state_passes(self):
        raw = {"tab": "known", "type": "place", "query": "ar", "sort": {"key": "count", "desc": True},
               "widths": {"source": 31, "tr": 20.5}}
        self.assertEqual(tm.clean(raw, KEYS, TYPES), {"tab": "known", "type": "place", "query": "ar",
                                                      "sort": {"key": "count", "desc": True},
                                                      "widths": {"source": 31.0, "tr": 20.5}})

    def test_broken_parts_are_dropped_one_by_one(self):
        raw = {"tab": 5, "type": "dragon", "query": 7, "sort": {"key": "nope", "desc": True},
               "widths": {"source": "wide", "tr": 9999, "type": 12, "x": True}}
        self.assertEqual(tm.clean(raw, KEYS, TYPES), {"widths": {"type": 12.0}})

    def test_not_a_dict(self):
        for raw in (None, [], "x", 3):
            self.assertEqual(tm.clean(raw, KEYS, TYPES), {})

    def test_sort_with_a_wrong_direction_type(self):
        self.assertEqual(tm.clean({"sort": {"key": "count", "desc": "yes"}}, KEYS, TYPES), {})

    def test_blank_query_is_not_kept(self):
        self.assertEqual(tm.clean({"query": "   "}, KEYS, TYPES), {})

    def test_default_sort_is_not_stored(self):
        self.assertIsNone(tm.sort_to_store("new", "first", False, ("first", False)))
        self.assertEqual(tm.sort_to_store("new", "source", True, ("first", False)), {"key": "source", "desc": True})
        self.assertIsNone(tm.sort_to_store("new", None, False, ("first", False)))


if __name__ == "__main__":
    unittest.main()
