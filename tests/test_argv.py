import json
import unittest
from pathlib import Path

from bbm_gui import app, cmdbuild, engine, flagmenu, flagrules, pace
from bbm_gui.flagstate import FlagState

INV = Path(__file__).resolve().parent / "fixtures" / "inv_rt_v1.3.2.json"


def argv_for(model, per_request=1, settings=None, version=(3, 13)):
    inv = json.loads(INV.read_text(encoding="utf-8"))
    state = FlagState(app.PRESETS, "Gemini free", None)
    owned = {"--book_name": "B.epub", "--language": "ru:Russian", "--single_translate": True,
             "--prompt": "p.json", "--model": model}
    owned.update(pace.owned_flags(model, per_request, settings or {}, version))
    return cmdbuild.build_argv(inv, state.effective(owned), engine.load_overlay(), mask=False)


@unittest.skipUnless(INV.is_file(), "inventory fixture not available")
class ArgvTest(unittest.TestCase):
    def test_default_setup_reaches_the_engine_unchanged(self):
        """Prompt, language, temperature and context are what they were; the interval is computed (unknown model: 10 per
        minute, nothing measured -> 1.1 * 6 = 6.6) and no block size is sent at one paragraph per request."""
        argv, dropped = argv_for("m1")
        self.assertEqual(argv, ["--book_name=B.epub", "--model=m1", "--api_format=gemini", "--language=ru:Russian",
                                "--translate-tags=" + flagrules.DEFAULT_TAGS,
                                "--prompt=p.json", "--single_translate", "--use_context", "--temperature=0.4",
                                "--interval=6.6"])
        self.assertEqual(dropped, [])

    def test_tags_are_an_ordinary_removable_flag(self):
        """The default tags ride in the preset layer: the user can change or switch them off, and nothing else moves."""
        inv = json.loads(INV.read_text(encoding="utf-8"))
        owned = {"--book_name": "B.epub"}
        for preset in ("Gemini free", "Custom"):
            st = FlagState(app.PRESETS, preset, None)
            argv, _ = cmdbuild.build_argv(inv, st.effective(owned), engine.load_overlay())
            self.assertIn("--translate-tags=" + flagrules.DEFAULT_TAGS, argv)
        st = FlagState(app.PRESETS, "Gemini free", None)
        st.set("--translate-tags", "p,h1")
        argv, _ = cmdbuild.build_argv(inv, st.effective(owned), engine.load_overlay())
        self.assertIn("--translate-tags=p,h1", argv)
        st.remove("--translate-tags")
        self.assertEqual(st.origin("--translate-tags"), "hidden")
        argv, _ = cmdbuild.build_argv(inv, st.effective(owned), engine.load_overlay())
        self.assertFalse([a for a in argv if a.startswith("--translate-tags")])  # the engine's own default (p) applies

    def test_the_default_tags_are_the_text_carrying_ones(self):
        tags = flagrules.DEFAULT_TAGS.split(",")
        for t in ("p", "h1", "h6", "li", "blockquote", "dt", "dd", "figcaption", "td", "th"):
            self.assertIn(t, tags)
        self.assertNotIn("div", tags)  # a division usually holds blocks that are translated on their own

    def test_known_model_gets_its_own_interval(self):
        argv, _ = argv_for("gemini-3.1-flash-lite")
        self.assertIn("--interval=4.4", argv)  # 1.1 * 60 / 15, nothing measured yet
        self.assertFalse([a for a in argv if a.startswith("--block_size")])

    def test_block_size_only_when_chosen(self):
        self.assertFalse([a for a in argv_for("m1", 1)[0] if a.startswith("--block_size")])
        argv, dropped = argv_for("m1", 5)
        self.assertIn("--block_size=5", argv)
        self.assertEqual(dropped, [])
        self.assertIn("--use_context", argv)  # grouping does not touch what the model is asked
        self.assertIn("--temperature=0.4", argv)

    def test_grouping_is_off_on_an_old_python(self):
        argv, _ = argv_for("m1", 10, version=(3, 11))
        self.assertFalse([a for a in argv if a.startswith("--block_size")])
        argv, _ = argv_for("m1", 10, version=None)
        self.assertFalse([a for a in argv if a.startswith("--block_size")])

    def test_a_hop_changes_only_the_model(self):
        first, _ = argv_for("m1")
        second, _ = argv_for("m2")
        diff = [(a, b) for a, b in zip(first, second) if a != b]
        self.assertEqual(diff, [("--model=m1", "--model=m2")])  # same table row, same interval
        self.assertEqual(len(first), len(second))

    def test_a_chip_edit_reaches_the_engine_exactly(self):
        """Add, edit and remove through the same functions the panel uses, then compare with the plain argv."""
        inv = json.loads(INV.read_text(encoding="utf-8"))
        overlay = engine.load_overlay()
        byid = {f["id"]: f for f in inv["flags"]}
        st = FlagState(app.PRESETS, "Gemini free", None)
        base, _ = cmdbuild.build_argv(inv, st.effective({"--book_name": "B.epub"}), overlay)

        def typed(fid, text):
            spec = flagmenu.spec_of(byid[fid], overlay)
            status, value, _ = flagmenu.parse_value(spec, text)
            self.assertEqual(status, "ok", fid)
            st.set(fid, value)

        spec = flagmenu.spec_of(byid["--test"], overlay)
        st.set("--test", flagmenu.start_value(spec, byid["--test"]))
        typed("--test", "5")
        typed("--temperature", "0.9")
        typed("--exclude_filelist", "cover.xhtml,nav.xhtml")
        typed("--translation_color", "#808080")
        typed("--proxy", "http://127.0.0.1:7890")
        st.set("--sentence_mode", flagmenu.start_value(flagmenu.spec_of(byid["--sentence_mode"], overlay), None))
        st.set("--no_disclosure", flagmenu.start_value(flagmenu.spec_of(byid["--no_disclosure"], overlay), None))
        argv, dropped = cmdbuild.build_argv(inv, st.effective({"--book_name": "B.epub"}), overlay)
        self.assertEqual(dropped, [])
        for want in ("--test", "--test_num=5", "--temperature=0.9", "--exclude_filelist=cover.xhtml,nav.xhtml",
                     "--translation_color=#808080", "--proxy=http://127.0.0.1:7890", "--sentence_mode", "--no_disclosure"):
            self.assertIn(want, argv)
        self.assertNotIn("--temperature=0.4", argv)
        self.assertEqual(argv.count("--test"), 1)
        # remove every edit again: the command is the preset's command, flag for flag
        for fid in ("--test", "--exclude_filelist", "--translation_color", "--proxy", "--sentence_mode", "--no_disclosure"):
            st.remove(fid)
        st.revert("--temperature")
        again, _ = cmdbuild.build_argv(inv, st.effective({"--book_name": "B.epub"}), overlay)
        self.assertEqual(again, base)

    def test_a_tombstone_and_its_return_are_exact(self):
        inv = json.loads(INV.read_text(encoding="utf-8"))
        overlay = engine.load_overlay()
        st = FlagState(app.PRESETS, "Gemini free", None)
        base, _ = cmdbuild.build_argv(inv, st.effective(), overlay)
        st.remove("--use_context")
        argv, _ = cmdbuild.build_argv(inv, st.effective(), overlay)
        self.assertEqual([a for a in base if a not in argv], ["--use_context"])
        st.revert("--use_context")
        self.assertEqual(cmdbuild.build_argv(inv, st.effective(), overlay)[0], base)


if __name__ == "__main__":
    unittest.main()
