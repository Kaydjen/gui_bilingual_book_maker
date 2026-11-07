import json
import unittest
from pathlib import Path

from bbm_gui import engine, flagmenu
from bbm_gui.flagstate import FlagState

INV = Path(__file__).resolve().parent / "fixtures" / "inv_rt_v1.3.2.json"
PRESETS = {"P": {"--api_format": "gemini", "--temperature": "0.4", "--use_context": True,
                 "--translate-tags": "p,h1,h2,h3,h4,h5"}}


@unittest.skipUnless(INV.is_file(), "inventory fixture not available")
class MenuTest(unittest.TestCase):
    def setUp(self):
        self.inv = json.loads(INV.read_text(encoding="utf-8"))
        self.overlay = engine.load_overlay()

    def labels(self, **kw):
        return [r.head or r.label for r in flagmenu.rows(self.inv, self.overlay, **kw)]

    def ids(self, **kw):
        return [r.flag["id"] for r in flagmenu.rows(self.inv, self.overlay, **kw) if r.flag]

    def test_default_list_is_common_then_more(self):
        names = self.labels()
        self.assertEqual(names[0], "Test and tuning")
        self.assertLess(names.index("Book parts"), names.index("Output look"))
        self.assertLess(names.index("Output look"), names.index("Connection"))
        self.assertLess(names.index("Connection"), names.index("More"))
        self.assertNotIn("All flags", names)
        self.assertEqual(len(self.ids()), 17)

    def test_owned_and_companion_flags_are_never_offered(self):
        every = self.ids(show_all=True)
        for fid in ("--book_name", "--language", "--model", "--prompt", "--glossary", "--resume", "--interval",
                    "--block_size", "--accumulated_num", "--test_num", "--help", "--key", "--provider"):
            self.assertNotIn(fid, every)
        for fid in ("--quiet", "--pdf-parser", "--plan-classify", "--batch", "--proxy"):
            self.assertIn(fid, every)
        self.assertNotIn("--with-ocr", every)  # hidden by the engine

    def test_all_flags_carry_a_reason_and_engine_text(self):
        rows = {r.flag["id"]: r for r in flagmenu.rows(self.inv, self.overlay, show_all=True) if r.flag}
        self.assertEqual(rows["--pdf-parser"].reason, "PDF")
        self.assertEqual(rows["--plan-classify"].reason, "Plan mode")
        self.assertEqual(rows["--quiet"].reason, "Hides progress")
        self.assertEqual(rows["--batch"].reason, "Other API formats")
        self.assertEqual(rows["--temperature"].reason, "")
        self.assertTrue(rows["--quiet"].line.startswith("Suppress progress bars"))  # the engine's own text

    def test_unknown_future_flag_appears_under_all_flags(self):
        inv = json.loads(json.dumps(self.inv))
        inv["flags"].append({"id": "--shiny-new", "options": ["--shiny-new"], "action": "store", "nargs": None,
                             "type": "str", "choices": None, "default": None, "hidden": False, "order": 999,
                             "help": "does something shiny. More."})
        self.assertNotIn("--shiny-new", [r.flag["id"] for r in flagmenu.rows(inv, self.overlay) if r.flag])
        rows = [r for r in flagmenu.rows(inv, self.overlay, show_all=True) if r.flag and r.flag["id"] == "--shiny-new"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].line, "Does something shiny. More.")  # short: shown as it is

    def test_search_looks_through_every_flag(self):
        self.assertEqual(self.ids(query="temper"), ["--temperature"])
        self.assertIn("--pdf-parser", self.ids(query="parser"))
        self.assertIn("--proxy", self.ids(query="--proxy"))

    def test_editors_by_kind(self):
        spec = lambda fid: flagmenu.spec_of(next(f for f in self.inv["flags"] if f["id"] == fid), self.overlay)  # noqa: E731
        self.assertEqual((spec("--test").editor, spec("--test").suggest), ("int", ("10", "20", "50")))
        t = spec("--temperature")
        self.assertEqual((t.editor, t.lo, t.hi, t.step, t.default), ("float", 0.1, 2.0, 0.1, "1.0"))
        self.assertEqual(flagmenu.parse_value(t, "0")[0:2], ("bad", None))
        self.assertIn("blocked paragraph", flagmenu.parse_value(t, "0")[2])
        self.assertEqual(flagmenu.parse_value(t, "0.1")[0], "ok")
        self.assertEqual(flagmenu.parse_value(t, "2.5")[2], "0.1 - 2")
        self.assertEqual(spec("--translate-tags").editor, "csv")
        self.assertEqual(spec("--exclude_filelist").editor, "csv")
        self.assertEqual(spec("--translation_color").editor, "color")
        self.assertEqual(spec("--api_format").editor, "enum")
        self.assertIn("gemini", spec("--api_format").choices)
        self.assertEqual(spec("--use_context").editor, "toggle")  # on or off: no `session` on this route
        self.assertEqual(spec("--no_disclosure").editor, "toggle")
        self.assertEqual(spec("--proxy").editor, "text")
        self.assertEqual(spec("--pages").editor, "text")

    def test_chips_show_origin_and_hide_what_is_off(self):
        st = FlagState(PRESETS, "P")
        cs = {c.fid: c for c in flagmenu.chips(st, self.inv, self.overlay)}
        self.assertEqual({c.origin for c in cs.values()}, {"preset"})
        self.assertEqual(cs["--temperature"].text, "Temperature 0.4")
        self.assertEqual(cs["--use_context"].text, "Context")
        self.assertEqual(cs["--translate-tags"].text, "Tags to translate p,h1,h2 +3")
        st.set("--temperature", "0.9")
        st.remove("--use_context")
        st.set("--no_disclosure", False)
        st.set("--proxy", "http://127.0.0.1:7890")
        cs = {c.fid: c for c in flagmenu.chips(st, self.inv, self.overlay)}
        self.assertEqual((cs["--temperature"].origin, cs["--temperature"].text), ("user", "Temperature 0.9"))
        self.assertNotIn("--use_context", cs)
        self.assertEqual(cs["--no_disclosure"].text, "No credit line")
        self.assertEqual(cs["--proxy"].text, "Proxy http://127.0.0.1:7890")

    def test_chip_order_follows_the_engine(self):
        st = FlagState(PRESETS, "P")
        st.set("--proxy", "x")
        order = [c.fid for c in flagmenu.chips(st, self.inv, self.overlay)]
        ranks = {f["id"]: f["order"] for f in self.inv["flags"]}
        self.assertEqual(order, sorted(order, key=lambda f: ranks[f]))

    def test_an_empty_chip_lives_only_while_it_is_edited(self):
        st = FlagState(PRESETS, "P")
        st.set("--exclude_filelist", "")
        self.assertFalse([c for c in flagmenu.chips(st, self.inv, self.overlay) if c.fid == "--exclude_filelist"])
        shown = [c for c in flagmenu.chips(st, self.inv, self.overlay, editing="--exclude_filelist")]
        self.assertTrue([c for c in shown if c.fid == "--exclude_filelist"])

    def test_test_value_and_companion(self):
        st = FlagState(PRESETS, "P")
        st.set("--test", "10")
        st.set("--test_num", "3")  # a stray companion is never a chip of its own
        cs = [c.text for c in flagmenu.chips(st, self.inv, self.overlay)]
        self.assertIn("Test 10", cs)
        self.assertFalse([c for c in cs if "paragraphs" in c.lower()])

    def test_flags_the_engine_lacks_become_problem_chips(self):
        st = FlagState(PRESETS, "P", {"--gone": "5", "--flagless": True})
        bad = [c for c in flagmenu.chips(st, self.inv, self.overlay) if c.origin == "bad"]
        self.assertEqual([c.text for c in bad], ["--gone 5", "--flagless"])

    def test_no_inventory_no_chips(self):
        self.assertEqual(flagmenu.chips(FlagState(PRESETS, "P"), None, self.overlay), [])


class ParseValueTest(unittest.TestCase):
    def spec(self, editor, **kw):
        base = dict(fid="--x", kind="text", editor=editor, choices=(), lo=None, hi=None, step=1.0, suggest=(),
                    placeholder="", default="")
        base.update(kw)
        return flagmenu.Spec(**base)

    def test_numbers(self):
        s = self.spec("float", lo=0.0, hi=2.0, step=0.1)
        self.assertEqual(flagmenu.parse_value(s, "0,7"), ("ok", "0.7", ""))
        self.assertEqual(flagmenu.parse_value(s, "3")[0:3:2], ("bad", "0 - 2"))
        self.assertEqual(flagmenu.parse_value(s, "abc")[0], "bad")
        self.assertEqual(flagmenu.parse_value(s, "nan")[0], "bad")
        self.assertEqual(flagmenu.parse_value(s, " ")[0], "empty")
        i = self.spec("int", lo=1, hi=1000)
        self.assertEqual(flagmenu.parse_value(i, "10"), ("ok", "10", ""))
        self.assertEqual(flagmenu.parse_value(i, "2.5")[0], "bad")
        self.assertEqual(flagmenu.parse_value(i, "0")[0], "bad")

    def test_lists_colors_json(self):
        c = self.spec("csv")
        self.assertEqual(flagmenu.parse_value(c, "p, h1,,p\nh2"), ("ok", "p,h1,p\nh2".replace("\n", ",") if False else "p,h1,h2", ""))
        self.assertEqual(flagmenu.parse_value(self.spec("color"), "#1e90ff")[0], "ok")
        self.assertEqual(flagmenu.parse_value(self.spec("color"), "red")[0], "ok")
        self.assertEqual(flagmenu.parse_value(self.spec("color"), "#12")[0], "bad")
        self.assertEqual(flagmenu.parse_value(self.spec("json"), '{"a": 1}')[0], "ok")
        self.assertEqual(flagmenu.parse_value(self.spec("json"), "[1]")[0], "bad")
        self.assertEqual(flagmenu.parse_value(self.spec("multi"), 'a "b c"', )[1][0], "a")


if __name__ == "__main__":
    unittest.main()
