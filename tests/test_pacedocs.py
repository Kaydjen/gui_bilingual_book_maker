import unittest

from bbm_gui import pace, pacedocs


class PaceDocsTest(unittest.TestCase):
    def test_every_entry_has_all_fields(self):
        for n in (1,) + tuple(pace.GROUPS):
            title, rows = pacedocs.sections(n)[1]
            self.assertEqual([f for f, _ in rows], list(pacedocs.FIELDS))
            self.assertTrue(all(text.strip() for _, text in rows), n)
        title, rows = pacedocs.sections(1)[0]
        self.assertEqual([f for f, _ in rows], list(pacedocs.FIELDS))

    def test_about_says_what_the_item_lets_the_user_do(self):
        for n in (1, 5, 10, 20):
            self.assertTrue(pacedocs.per_request(n)["About"].startswith("Lets you"), n)
        self.assertTrue(pacedocs.steady()["About"].startswith("Lets the app"))

    def test_numbers_follow_the_group_size(self):
        text = pacedocs.per_request(10)["Example"]
        self.assertIn("20 requests instead of 200", text)
        self.assertIn("5000 paragraphs", text)
        self.assertIn("20 requests instead of 200".replace("20", "40", 1), pacedocs.per_request(5)["Example"])

    def test_steady_example_matches_the_interval_formula(self):
        # 15 requests a minute, 3 s per request: 1.1 * 60 / 15 - 3 = 1.4 s, about 13.6 requests a minute
        self.assertAlmostEqual(pace.interval(3.0, 15), 1.4, places=2)
        self.assertEqual(round(60 / (3.0 + 1.4)), 14)
        self.assertIn("1.4 s", pacedocs.steady()["Example"])

    def test_the_untested_size_says_so(self):
        self.assertIn("not been tested", pacedocs.per_request(20)["Use when"])
        self.assertNotIn("measurable quality loss", pacedocs.per_request(20)["Risk"])


if __name__ == "__main__":
    unittest.main()
