import unittest

from novelgui import keynav


class ReadingOrderTest(unittest.TestCase):
    def test_rows_then_columns(self):
        boxes = [("c", 300, 10, 20), ("a", 10, 12, 20), ("d", 20, 60, 20), ("b", 150, 8, 20), ("e", 200, 62, 20)]
        self.assertEqual(keynav.reading_order(boxes), ["a", "b", "c", "d", "e"])

    def test_a_taller_control_shares_the_row_of_its_neighbours(self):
        boxes = [("field", 10, 0, 30), ("btn", 200, 4, 22), ("below", 10, 80, 22)]
        self.assertEqual(keynav.reading_order(boxes), ["field", "btn", "below"])

    def test_empty(self):
        self.assertEqual(keynav.reading_order([]), [])

    def test_step_wraps_both_ways(self):
        order = ["a", "b", "c"]
        self.assertEqual(keynav.step(order, "a", 1), "b")
        self.assertEqual(keynav.step(order, "c", 1), "a")
        self.assertEqual(keynav.step(order, "a", -1), "c")

    def test_step_from_outside_the_order(self):
        order = ["a", "b"]
        self.assertEqual(keynav.step(order, None, 1), "a")
        self.assertEqual(keynav.step(order, "zzz", -1), "b")
        self.assertIsNone(keynav.step([], "a", 1))


if __name__ == "__main__":
    unittest.main()
