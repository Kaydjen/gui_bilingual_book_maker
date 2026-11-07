import glob
import os
import unittest
from pathlib import Path

from bbm_gui import estimate

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample8.epub"


class HtmlTest(unittest.TestCase):
    def test_engine_rules(self):
        html = ("<html><body>"
                "<p>Hello</p><p>   </p><p>123</p><p>...</p><p>https://example.org/x</p>"
                "<p><sup>1</sup></p><p><code>x = 1</code></p><p>Text <sup>2</sup></p>"
                "<p>outer <p>inner</p></p><div><p>in div</p></div><p>a<br/>b</p>"
                "</body></html>")
        # Hello, "Text", the inner paragraph (the outer one has a nested paragraph), in div, a/b
        self.assertEqual(estimate.count_html(html), 5)

    def test_requests_never_cross_a_chapter(self):
        self.assertEqual(estimate.requests([8], 4), 2)
        self.assertEqual(estimate.requests([3, 3], 5), 2)
        self.assertEqual(estimate.requests([10, 7], 1), 17)

    def test_plan_line(self):
        self.assertEqual(estimate.plan_line(827, 3780, 2), "827 requests · ~1 h 03 · 2 days")
        self.assertEqual(estimate.plan_line(1, 10, None), "1 request · ~<1 min")
        self.assertEqual(estimate.days(827, 1000), 1)
        self.assertEqual(estimate.days(827, 500), 2)
        self.assertIsNone(estimate.days(827, None))


@unittest.skipUnless(SAMPLE.is_file(), "sample book not available")
class SampleTest(unittest.TestCase):
    def test_sample_has_eight_paragraphs(self):
        counts = estimate.chapter_counts(SAMPLE)
        self.assertEqual(sum(counts), 8)
        self.assertEqual(estimate.requests(counts, 4), 2)

    def test_unreadable_file(self):
        self.assertIsNone(estimate.chapter_counts(Path(__file__)))


class RichestBookTest(unittest.TestCase):
    def test_matches_the_engine_total(self):
        base = os.environ.get("LOCALAPPDATA")
        found = glob.glob(os.path.join(base or "", "bbm-gui", "jobs", "*Richest*", "The_Richest_Man_In_Babylon.epub"))
        if not found:
            self.skipTest("the owner's copy of the book is not on this machine")
        self.assertEqual(sum(estimate.chapter_counts(found[0])), 827)  # the total the engine's progress bar shows


if __name__ == "__main__":
    unittest.main()
