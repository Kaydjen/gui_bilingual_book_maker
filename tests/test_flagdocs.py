import json
import re
import unittest
from pathlib import Path

from bbm_gui import engine, flagdocs, flagrules

INV = Path(__file__).resolve().parent / "fixtures" / "inv_rt_v1.3.2.json"


def flag(help_text, **kw):
    f = {"id": "--x", "options": ["--x"], "action": "store", "type": "str", "default": None, "choices": None,
         "help": help_text, "hidden": False, "order": 0}
    f.update(kw)
    return f


class CleanTest(unittest.TestCase):
    def test_choice_dump_is_removed_with_its_comma(self):
        h = "wire format the endpoint speaks, available: {openai, anthropic, gemini}. Inferred from --api_base when omitted"
        self.assertEqual(flagdocs.clean(h), "Wire format the endpoint speaks. Inferred from --api_base when omitted")

    def test_trailing_dump_leaves_one_full_stop(self):
        h = "target language: a tag or a name. Available: {aa, ab, ac}"
        self.assertEqual(flagdocs.clean(h), "Target language: a tag or a name.")
        self.assertEqual(flagdocs.clean("a tag, available: {aa, ab}"), "A tag.")

    def test_huge_braces_go_and_white_space_collapses(self):
        h = "pick one {" + "x, " * 60 + "}\n   and   more"
        self.assertEqual(flagdocs.clean(h), "Pick one and more")
        self.assertEqual(flagdocs.clean(None), "")

    def test_the_real_language_text_is_short_after_cleaning(self):
        if not INV.is_file():
            self.skipTest("inventory fixture not available")
        lang = next(f for f in json.loads(INV.read_text(encoding="utf-8"))["flags"] if f["id"] == "--language")
        text = flagdocs.clean(lang["help"])
        self.assertLess(len(text), 400)
        self.assertNotIn("{", text)


class ShortTest(unittest.TestCase):
    def test_short_text_is_shown_as_it_is(self):
        self.assertEqual(flagdocs.short("use proxy like http://127.0.0.1:7890"), "Use proxy like http://127.0.0.1:7890")

    def test_long_text_gives_its_first_sentence(self):
        h = "Exclude content within specified HTML tags from translation, so that code stays as it is in the book. " \
            "Use comma to separate multiple tags. Default: sup,code. Example: --exclude-translate-tags code,pre"
        self.assertEqual(flagdocs.short(h), "Exclude content within specified HTML tags from translation, so that code stays "
                                            "as it is in the book.")

    def test_abbreviations_do_not_end_a_sentence(self):
        h = "endpoint to translate against, e.g. https://api.openai.com/v1, a gateway, or http://localhost:11434/v1 for " \
            "ollama. Defaults to the format's official host and is a rather long explanation indeed"
        self.assertTrue(flagdocs.short(h).endswith("for ollama."))

    def test_a_very_long_sentence_is_cut_at_a_clause(self):
        h = "one two three four five six seven eight nine ten, " * 8 + "end."
        out = flagdocs.short(h)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), flagdocs.SHORT_MAX + 1)

    def test_a_command_line_is_no_description(self):
        self.assertEqual(flagdocs.short('--retranslate "$translated_filepath" "file" "start"'), "")
        self.assertEqual(flagdocs.short('ex: --translation_style "color: #808080;"'), "")


class SignatureTest(unittest.TestCase):
    def test_signature_follows_first_sentence_type_default_choices(self):
        base = flag("Does a thing. Second sentence.", default=1)
        sig = flagdocs.signature(base)
        self.assertEqual(sig, flagdocs.signature(flag("Does a thing. A different second sentence, rewritten.", default=1)))
        for other in (flag("Does another thing. Second sentence.", default=1), flag("Does a thing.", default=2),
                      flag("Does a thing.", default=1, type="int"), flag("Does a thing.", default=1, choices=["a"])):
            self.assertNotEqual(sig, flagdocs.signature(other))


class DescribeTest(unittest.TestCase):
    def setUp(self):
        self.f = flag("Does a thing in a very particular way. More text.")
        self.ov = {"about": "Lets you do it.", "example": "you set 1, so it happens.", "seen": flagdocs.signature(self.f)}

    def test_matching_signature_shows_our_text(self):
        d = flagdocs.describe(self.f, self.ov)
        self.assertTrue(d.ours and not d.stale)
        self.assertEqual((d.about, d.example), ("Lets you do it.", "you set 1, so it happens."))
        self.assertIn("More text", d.engine)

    def test_changed_engine_text_switches_ours_off(self):
        moved = flag("Does a different thing entirely. More text.")
        d = flagdocs.describe(moved, self.ov)
        self.assertFalse(d.ours)
        self.assertTrue(d.stale)
        self.assertEqual(d.example, "")
        self.assertTrue(d.about.startswith("Does a different thing"))

    def test_flag_without_entry_shows_engine_text(self):
        d = flagdocs.describe(self.f, {})
        self.assertFalse(d.ours or d.stale)
        self.assertTrue(d.about.startswith("Does a thing"))


@unittest.skipUnless(INV.is_file(), "inventory fixture not available")
class OverlayTest(unittest.TestCase):
    def setUp(self):
        self.inv = json.loads(INV.read_text(encoding="utf-8"))
        self.overlay = engine.load_overlay()
        self.curated = {fid: ov for fid, ov in self.overlay["flag"].items() if "about" in ov}

    def test_no_drift_against_the_checked_engine(self):
        """Prints the entries to re-verify on an engine update; empty for the release the texts were written for."""
        self.assertEqual(flagdocs.drift(self.inv, self.overlay), [])

    def test_drift_lists_a_changed_or_missing_flag(self):
        inv = json.loads(json.dumps(self.inv))
        for f in inv["flags"]:
            if f["id"] == "--proxy":
                f["help"] = "route all traffic through this proxy server, which is what this flag does"
        inv["flags"] = [f for f in inv["flags"] if f["id"] != "--sentence_mode"]
        self.assertEqual(flagdocs.drift(inv, self.overlay), [("--proxy", "changed"), ("--sentence_mode", "missing")])

    def test_every_common_flag_has_our_text(self):
        for f in self.inv["flags"]:
            ov = self.overlay["flag"].get(f["id"], {})
            if ov.get("tier") == "common":
                for key in ("about", "example", "seen", "label", "menu"):
                    self.assertTrue(ov.get(key), "%s lacks %s" % (f["id"], key))

    def test_curated_flags_exist_and_are_never_owned(self):
        ids = {f["id"] for f in self.inv["flags"]}
        for fid, ov in self.overlay["flag"].items():
            if ov.get("tier"):
                self.assertIn(fid, ids)
                self.assertFalse(flagrules.is_owned(fid), fid)

    def test_texts_have_one_sentence_and_one_example(self):
        for fid, ov in self.curated.items():
            about, example = ov["about"], ov["example"]
            self.assertTrue(about.startswith("Lets you"), fid)
            self.assertEqual(len(re.findall(r"[.!?](?=\s+[A-Z]|$)", about)), 1, fid)
            self.assertTrue(example[0].islower() and example.endswith("."), fid)
            self.assertEqual(len(re.findall(r"[.!?](?=\s+[A-Z]|$)", example)), 1, fid)
            self.assertFalse(re.search(r"\b(click|type|press|enter|tick)\b", about + " " + example, re.I), fid)

    def test_texts_say_what_really_happens(self):
        ov = self.overlay["flag"]
        self.assertIn("translation-only", ov["--exclude_filelist"]["about"])  # the app adds the contents file itself
        self.assertIn("app's list", ov["--translate-tags"]["about"])  # the presets carry their own tag list
        temp = ov["--temperature"]["about"]
        self.assertNotIn("little effect", temp)  # measured: the flag changes the wording
        self.assertIn("blocked paragraph", temp)


if __name__ == "__main__":
    unittest.main()
