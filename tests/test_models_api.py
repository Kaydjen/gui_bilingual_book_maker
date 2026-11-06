import unittest

from bbm_gui import models_api


def m(name, methods=("generateContent",)):
    return {"name": "models/" + name, "supportedGenerationMethods": list(methods)}


class UsableTest(unittest.TestCase):
    def test_filter_and_order(self):
        items = [m("gemini-3.1-flash-lite"), m("gemini-3.8-flash"), m("gemini-3.8-flash-tts"), m("gemini-2.5-flash-image"),
                 m("gemini-embedding-001", ("embedContent",)), m("gemma-4-31b-it"), m("gemini-3.8-live", ("bidiGenerateContent",)),
                 m("lyria-3.5"), m("gemini-3.5-flash-lite")]
        self.assertEqual(models_api.usable(items),
                         ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it"])


if __name__ == "__main__":
    unittest.main()
