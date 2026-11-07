import unittest

from bbm_gui import prompts


class ShapeTest(unittest.TestCase):
    def test_check(self):
        self.assertEqual(prompts.check({"user": "{text}"}), [])
        self.assertEqual(prompts.check({"user": ""}), ["user"])
        self.assertEqual(prompts.check({"user": "no field"}), ["text"])
        self.assertEqual(prompts.check({"user": "{text} {x}"}), ["braces"])


if __name__ == "__main__":
    unittest.main()
