"""Terms without Qt (unittest): the tabs, order and counts, the cells, `Confirm N`, the floating element, the `To` list (3.2),
gender codes (14.13), the glossary import plan, the term snapshots (14.11), the store commands (bulk change labels, Undo, Not a
term, merge, Import per file, export), and the keys of RowSelection for a table whose selection is the ticks (10.7)."""

import gzip
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novelcore.terms import TermBase, candidate  # noqa: E402
from novelgui.ctl import termrows as tr  # noqa: E402
from novelgui.ctl.termshistory import KEEP_DAYS, KEEP_OPS, TermsHistory, series_key  # noqa: E402
from novelgui.facade import terms as ft  # noqa: E402
from novelgui.vm.rowselection import RowSelection  # noqa: E402

TIPS = {"nolang": "n", "confirmTicked": "c", "merge": "m", "notATerm": "x", "scanning": "s", "goTranslate": "g",
        "confirmN": lambda n: "confirm %d" % n}


def row(key, status="new", tr_="x", first=1, count=1, questions=(), choices=(), typ="term", gender="unknown", source=None,
        note="", forms=()):
    return ft.TermRow(key, source or key.title(), tr_, typ, gender, status, count, first, tuple(questions), tuple(forms), note, "",
                      tuple(choices))


class TabTests(unittest.TestCase):
    def setUp(self):
        self.rows = [row("a", first=5), row("b", first=2), row("c", "confirmed"), row("d", first=9),
                     row("e", "confirmed", first=20, questions=("tr",), choices=(("tr", (("1", "in use"), ("2", "f.json"))),)),
                     tr.Suggestion("Brisen", 4, 7)]
        self.blocking = frozenset({"a", "b"})

    def keys(self, **kw):
        kw.setdefault("blocking", self.blocking)
        return [r.key for r in tr.arrange(self.rows, **kw)]

    def test_the_three_tabs(self):
        self.assertEqual(self.keys(tab="blocking"), ["b", "a"], "unconfirmed AND found in the selected chapters, by First")
        notconf = self.keys(tab="notconf")
        self.assertEqual(set(notconf), {"a", "b", "d", "e", "?brisen"}, "unconfirmed, names, confirmed with a choice")
        self.assertEqual(self.keys(tab="confirmed"), ["c"], "confirmed without an open question")

    def test_default_order_is_first_then_count(self):
        self.assertEqual(self.keys(tab="notconf"), ["b", "a", "?brisen", "d", "e"])
        rows = [row("x", first=3, count=1), row("y", first=3, count=9), row("z", first=None)]
        got = [r.key for r in tr.arrange(rows, "notconf", frozenset())]
        self.assertEqual(got, ["y", "x", "z"], "more frequent first, never found last")

    def test_counts_follow_type_and_import_filters_not_the_search(self):
        rows = [row("a", typ="place"), row("b", typ="character"), row("c", "confirmed", typ="place")]
        self.assertEqual(tr.counts(rows, frozenset({"a"})), {"blocking": 1, "notconf": 2, "confirmed": 1})
        self.assertEqual(tr.counts(rows, frozenset({"a"}), "place"), {"blocking": 1, "notconf": 1, "confirmed": 1})
        self.assertEqual(tr.counts(rows, frozenset(), "", {"b"}), {"blocking": 0, "notconf": 1, "confirmed": 0})

    def test_search_type_keep_and_imported(self):
        self.assertEqual(self.keys(tab="notconf", query="BRIS"), ["?brisen"])
        self.assertEqual(self.keys(tab="confirmed", keep={"a"}), ["c", "a"], "a row whose chip was clicked stays")
        self.assertEqual(self.keys(tab="notconf", imported={"d"}), ["d"])
        self.assertEqual(self.keys(tab="notconf", key="source")[0], "a")
        forms = [row("k", source="Kay", forms=("Sir Kay",))]
        self.assertEqual(len(tr.arrange(forms, "notconf", frozenset(), "sir kay")), 1, "other spellings are searched")

    def test_confirm_n_takes_rows_with_a_rendering_and_no_open_choice(self):
        rows = [row("a"), row("b", tr_=""), row("c", questions=("tr",)), row("d", "confirmed"), tr.Suggestion("N", 1, 1)]
        self.assertEqual([r.key for r in tr.confirmable(rows)], ["a"])
        self.assertTrue(tr.can_merge(rows[:2]))
        self.assertFalse(tr.can_merge(rows[:1]))
        self.assertFalse(tr.can_merge([rows[0], rows[4]]))


class CellTests(unittest.TestCase):
    def test_a_plain_row(self):
        r = row("a", typ="character", gender="female", tr_="Моргана", first=47, count=308, note="half-sister")
        cells = tr.model_row(r, [str(2650 + i) for i in range(200)])
        self.assertEqual(cells, ("A", "Моргана", "character", "ж", "2697" + tr.US + "308", "half-sister", ""))

    def test_gender_codes(self):
        self.assertEqual([tr.gender_short(g) for g in ("male", "female", "neuter", "plural", "unknown")], ["м", "ж", "с", "", ""])
        self.assertEqual([tr.gender_stored(c) for c in "мжс"], ["male", "female", "neuter"])
        self.assertEqual(tr.gender_stored("x"), "")
        self.assertEqual([c for _s, c, _w in tr.GENDER_CODES], ["м", "ж", "с"])

    def test_a_choice_is_its_values_joined_and_marked(self):
        r = row("p", questions=("tr", "gender"), choices=(("gender", (("male", "a.json"), ("female", "b.json"))),
                                                          ("tr", (("Персиваль", "a.json"), ("Парсифаль", "b.json")))))
        cells = tr.model_row(r)
        self.assertEqual(cells[1].split(tr.US), ["Персиваль", "Парсифаль"])
        self.assertEqual(cells[3].split(tr.US), ["м", "ж"])
        self.assertIn("r", cells[6])
        self.assertIn("g", cells[6])
        one = row("q", questions=("tr",), choices=(("tr", (("A", "x"),)),))
        self.assertEqual(tr.model_row(one)[1], one.tr, "one candidate is a value, not a choice")

    def test_a_name_is_a_slot_and_no_language_dims_the_rendering(self):
        s = tr.model_row(tr.Suggestion("Brisen", 9, 60))
        self.assertEqual((s[1], s[2], s[6]), ("", "", "s"))
        self.assertIn("n", tr.model_row(row("a"), (), True)[6])

    def test_first_is_the_chapter_number_the_user_reads(self):
        self.assertEqual(tr.number_text(["10", "20"], 1), "20")
        self.assertEqual(tr.number_text([], 4), "5")
        self.assertEqual(tr.number_text([], None), "")


class FloatTests(unittest.TestCase):
    def spec(self, **kw):
        a = dict(msg=None, ticked=0, tab="blocking", nolang=False, scanning=False, percent=0.0, blocking=8, waits=False,
                 chapters="2697-2750", confirm_n=6, searching=False, has_terms=True, loading=False, imported=False, tips=TIPS)
        a.update(kw)
        return tr.float_spec(**a)

    def text(self, spec):
        return "".join(p["text"] for p in spec["fact"])

    def test_blocking_line_and_confirm(self):
        s = self.spec()
        self.assertEqual(self.text(s), "Chapters 2697-2750 wait for 8 terms")
        self.assertEqual((s["verbs"][0]["text"], s["verbs"][0]["kind"]), ("Confirm 6 terms", "main"))
        self.assertEqual(self.spec(waits=True)["verbs"][0]["kind"], "accent", "red only while translation waits")
        self.assertEqual(self.spec(nolang=True)["verbs"][0]["kind"], "off")
        self.assertEqual(self.spec(searching=True)["verbs"], [], "no Confirm while a search narrows the list")
        self.assertEqual(self.spec(confirm_n=0)["verbs"], [])

    def test_ready_line_opens_translate(self):
        s = self.spec(blocking=0)
        self.assertEqual(self.text(s), "Chapters 2697-2750 are ready")
        self.assertEqual(s["verbs"][0]["id"], "translate")

    def test_other_tabs_and_nothing(self):
        self.assertEqual(self.spec(tab="notconf")["kind"], "confirm")
        self.assertEqual(self.spec(tab="notconf")["verbs"][0]["text"], "Confirm 6 terms")
        self.assertEqual(self.spec(tab="confirmed")["kind"], "")
        self.assertEqual(self.spec(has_terms=False)["kind"], "")
        self.assertEqual(self.spec(loading=True)["kind"], "")

    def test_ticked_bar(self):
        s = self.spec(ticked=3)
        self.assertEqual([v["text"] for v in s["verbs"]], ["3 selected", "Confirm", "Merge", "Not a term", "Delete"])
        self.assertEqual(s["verbs"][0]["kind"], "capt")
        self.assertEqual(self.spec(ticked=1)["verbs"][2]["kind"], "off", "Merge needs two")
        self.assertEqual([v["text"] for v in self.spec(ticked=2, tab="confirmed")["verbs"]],
                         ["2 selected", "Merge", "Not a term", "Delete"], "Confirm is absent on Confirmed")

    def test_scan_and_message_replace_the_rest(self):
        s = self.spec(scanning=True, percent=40)
        self.assertEqual(self.text(s), "Reading the book · 40 %")
        self.assertAlmostEqual(s["progress"], 0.4)
        m = self.spec(msg={"fact": tr.done_fact("Deleted", 2), "verbs": [{"text": "Undo", "id": "undo"}]}, ticked=2)
        self.assertEqual(self.text(m), "Deleted 2 terms")

    def test_message_texts(self):
        stats = {"added": 214, "confirmed": 213, "unconfirmed": 1, "choices": 3}
        parts = tr.import_fact(stats)
        self.assertEqual("".join(p["text"] for p in parts), "Imported 214 terms · 213 confirmed · 1 not confirmed · 3 to choose")
        self.assertEqual([p["text"] for p in parts if p["kind"] == "red"], ["3"], "the choices are the red")
        self.assertEqual("".join(p["text"] for p in tr.importing_fact(["a.json", "b.json"], 1, 2)), "Importing a.json, b.json · 1 of 2")
        self.assertEqual("".join(p["text"] for p in tr.saved_fact("terms-Knights.json")), "Saved terms-Knights.json")
        self.assertEqual(tr.plural(1), "1 term")


class LanguageListTests(unittest.TestCase):
    def entries(self, q="", current="", source="ja", locked=False):
        return tr.language_entries(q, current, source, locked, "later", "locked")

    def texts(self, items):
        return [e.get("text") or "[%s]" % e["group"] for e in items]

    def test_groups_and_the_dim_english(self):
        items = self.entries()
        self.assertEqual(self.texts(items)[:6], ["[TUNED]", "Russian", "[USABLE]", "Ukrainian", "Polish", "English"])
        eng = next(e for e in items if e.get("text") == "English")
        self.assertTrue(eng["off"])
        self.assertEqual(eng["tip"], "later")
        self.assertIn("English", [e["text"] for e in items if "text" in e][5:], "dim in OTHER too")

    def test_the_source_language_is_left_out_everywhere(self):
        self.assertNotIn("English", self.texts(self.entries(source="en")))
        self.assertNotIn("Japanese", self.texts(self.entries(source="ja")))
        self.assertIn("French", self.texts(self.entries(source="ja")))

    def test_current_value_and_lock(self):
        items = self.entries(current="ru:Russian", locked=True)
        self.assertTrue(next(e for e in items if e.get("text") == "Russian")["current"])
        off = {e["text"]: e["off"] for e in items if "text" in e}
        self.assertFalse(off["Russian"])
        self.assertTrue(off["Ukrainian"] and off["French"])
        self.assertEqual(next(e for e in items if e.get("text") == "Ukrainian")["tip"], "locked")

    def test_typing_filters_and_offers_a_new_name(self):
        self.assertEqual([e["text"] for e in self.entries("fr") if "text" in e], ["French"], "by tag too")
        self.assertEqual(self.entries("Klingon")[0], {"text": "+ Use Klingon", "id": "use:Klingon"})
        self.assertNotEqual(self.entries("French")[0].get("id"), "use:French")
        self.assertEqual([e["text"] for e in self.entries("zh") if "text" in e], ["Chinese"])

    def test_memory_keeps_only_valid_parts(self):
        got = tr.clean_memory({"tab": "notconf", "type": "place", "query": " a ", "sort": {"key": "count", "desc": True},
                               "widths": {"src": 20.0}}, ("place",))
        self.assertEqual((got["tab"], got["type"], got["sort"]["key"]), ("notconf", "place", "count"))
        self.assertEqual(tr.clean_memory({"tab": "next"}, ()), {}, "an old tab name is dropped")
        self.assertEqual(tr.clean_memory("junk", ()), {})


class ImportPlanTests(unittest.TestCase):
    def test_totals_after_the_import(self):
        files = [("a.json", 3, {"x": "1", "y": "2", "z": "3"}, True), ("b.json", 2, {"y": "9", "w": "4"}, False)]
        plan = tr.plan_import(files, {"x": "1"}, 5, 7)
        self.assertEqual(plan, {"terms": 3, "confirmed": 7, "unconfirmed": 8, "choices": 1})


def make_base(root: Path, entries) -> Path:
    base = TermBase(root / "terms.json", "ru")
    for src, tr_, status in entries:
        base.add(src, status=status, tr=tr_, seen=[1], count=2)
    base.save()
    return root / "terms.json"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="termstore-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        make_base(self.root, [("Gawain", "Гавейн", "new"), ("Lot", "Лот", "new"), ("Kay", "Кэй", "confirmed")])
        self.store = ft.TermStore(self.root, "ru")
        self.labels = []
        self.store.history = self.labels.append

    def cmd(self, op, *keys, **kw):
        return self.store.apply(ft.TermCommand(op, tuple(keys), **kw))

    def test_a_bulk_change_with_a_label_takes_a_snapshot_first(self):
        self.cmd("confirm", "gawain", "lot", label="Confirm 2 terms")
        self.assertEqual(self.labels, ["Confirm 2 terms"])
        self.cmd("confirm", "gawain")
        self.assertEqual(self.labels, ["Confirm 2 terms"], "a command without a label is a plain edit")
        self.cmd("set_field", "kay", field="tr", value="Кай")
        self.assertEqual(len(self.labels), 1)

    def test_delete_and_undo_and_not_a_term(self):
        res = self.cmd("delete", "gawain", "lot", label="Delete 2 terms")
        self.assertEqual(set(res.removed), {"gawain", "lot"})
        self.assertIsNone(self.store.row("gawain"))
        back = self.store.apply(ft.TermCommand("undo_delete", ()))
        self.assertEqual({r.key for r in back.rows}, {"gawain", "lot"})
        self.assertEqual(self.store.row("lot").tr, "Лот")
        self.cmd("dismiss", "lot", label="Not a term 1")
        self.assertIn("lot", self.store.dismissed())
        self.store.apply(ft.TermCommand("undo_delete", ()))
        self.assertNotIn("lot", self.store.dismissed(), "Undo takes the mark away too")
        self.assertIsNotNone(self.store.row("lot"))

    def test_dismiss_names_without_an_entry(self):
        self.store.apply(ft.TermCommand("dismiss_names", (), value="Brisen\nElaine", label="Not a term 2"))
        self.assertEqual(self.store.dismissed(), frozenset({"brisen", "elaine"}))
        self.assertEqual(self.labels, ["Not a term 2"])

    def test_merge_keeps_the_first(self):
        res = self.cmd("merge", "gawain", "lot", label="Merge 2 terms")
        self.assertEqual(res.removed, ("lot",))
        row_ = self.store.row("gawain")
        self.assertIn("Lot", row_.forms)
        self.assertEqual(self.cmd("merge", "gawain").error, "Pick two or more terms to merge.")

    def test_add_a_name_with_a_rendering(self):
        res = self.store.apply(ft.TermCommand("add", (), field="Brisen", value="Бризен"))
        self.assertEqual((res.rows[0].status, res.rows[0].tr), ("confirmed", "Бризен"))
        self.assertTrue(self.store.apply(ft.TermCommand("add", (), field="Brisen", value="X")).error, "a taken name is refused")
        self.assertTrue(self.store.apply(ft.TermCommand("add", (), field="Elaine", value="")).error)

    def test_blocking_keys_places_and_names(self):
        self.assertEqual(self.store.blocking_keys([1]), frozenset({"gawain", "lot"}), "unconfirmed and seen in the chapters")
        self.assertEqual(self.store.blocking_keys([2]), frozenset())
        self.assertEqual(self.store.blocking_keys([]), frozenset())
        self.assertEqual(self.store.chapters_of("kay"), (1,))
        self.assertEqual(self.store.names_of("kay"), ("Kay",))

    def test_import_per_file_and_choices(self):
        a, b = self.root / "a.json", self.root / "b.json"
        a.write_text(json.dumps({"Bors": "Борс", "Dagonet": "Дагонет", "Gawain": "Говейн"}, ensure_ascii=False), encoding="utf-8")
        b.write_text(json.dumps({"Dagonet": "Дагонэ", "Ector": "Эктор"}, ensure_ascii=False), encoding="utf-8")
        stats = self.store.import_glossaries([a, b], {"a.json": True, "b.json": False}, "Import 2 glossaries")
        self.assertEqual(self.labels, ["Import 2 glossaries"])
        self.assertEqual((stats["added"], stats["choices"], stats["confirmed"], stats["unconfirmed"]), (3, 2, 1, 1))
        self.assertEqual(self.store.row("bors").status, "confirmed")
        self.assertEqual(self.store.row("ector").status, "new", "a file that goes to Not confirmed")
        dag = self.store.row("dagonet")
        self.assertEqual([c[1] for c in dict(dag.choices)["tr"]], ["a.json", "b.json"], "each candidate names its file")
        self.assertEqual(set(stats["keys"]), {"bors", "dagonet", "ector", "gawain"})

    def test_export_is_plain_json(self):
        out = self.root / "out.json"
        self.assertEqual(self.store.export_to(out), 3)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["Kay"], "Кэй")

    def test_choices_travel_with_the_row(self):
        e = self.store.base.exact("Gawain")
        self.store.base.ask(e, "tr", [candidate("Гавейн", "a.json"), candidate("Говейн", "b.json")])
        row_ = self.store.row("gawain")
        self.assertEqual(dict(row_.choices)["tr"], (("Гавейн", "a.json"), ("Говейн", "b.json")))
        self.assertEqual(row_.questions, ("tr",))


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="termshist-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.now = [1_800_000_000.0]
        self.h = TermsHistory(self.root / "h", clock=lambda: self.now[0])

    def snap(self, text, label, kind="op", step=1.0):
        self.now[0] += step
        return self.h.snapshot(lambda p: Path(p).write_text(text, encoding="utf-8"), label, kind)

    def test_snapshot_is_a_compressed_copy_with_the_label(self):
        i = self.snap('{"a": "Ё"}', "Import 2 glossaries")
        self.assertEqual(self.h.read(i).decode("utf-8"), '{"a": "Ё"}')
        self.assertTrue((self.root / "h" / (i + ".json.gz")).exists())
        label = next(x for x in self.h.list() if x[0] == i)[2]
        self.assertEqual(label, "Import 2 glossaries")
        with gzip.open(self.root / "h" / (i + ".json.gz"), "rb") as f:
            self.assertEqual(f.read(), '{"a": "Ё"}'.encode("utf-8"))

    def test_one_daily_snapshot_with_the_first_change_of_a_day(self):
        self.snap("1", "one")
        self.snap("2", "two")
        kinds = [x[3] for x in self.h.list()]
        self.assertEqual(kinds.count("day"), 1)
        self.assertEqual(kinds.count("op"), 2)
        self.snap("3", "next day", step=86400 * 1.5)
        self.assertEqual([x[3] for x in self.h.list()].count("day"), 2)

    def test_the_caps(self):
        for n in range(KEEP_OPS + 7):
            self.snap(str(n), "op %d" % n)
        ops = [x for x in self.h.list() if x[3] == "op"]
        self.assertEqual(len(ops), KEEP_OPS)
        self.assertEqual(ops[0][2], "op %d" % (KEEP_OPS + 6), "newest first")
        for d in range(KEEP_DAYS + 5):
            self.snap("d", "day %d" % d, step=86400 * 1.2)
        self.assertEqual(len([x for x in self.h.list() if x[3] == "day"]), KEEP_DAYS)
        files = list((self.root / "h").glob("*.json.gz"))
        self.assertEqual(len(files), KEEP_OPS + KEEP_DAYS, "dropped snapshots are gone from the disk")

    def test_the_snapshot_before_a_restore_is_never_dropped(self):
        keep = self.snap("pre", "before Restore", "restore")
        for n in range(KEEP_OPS + 10):
            self.snap(str(n), "op %d" % n)
        self.assertEqual(self.h.read(keep), b"pre")
        self.assertIn("before Restore", [x[2] for x in self.h.list()])

    def test_an_unknown_id_and_a_damaged_index(self):
        with self.assertRaises(KeyError):
            self.h.read("nope")
        self.snap("1", "x")
        (self.root / "h" / "index.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.h.list(), [])

    def test_the_series_key_is_safe(self):
        self.assertEqual(series_key(Path("C:/lib/Knights of: the *Round*")), "Knights of_ the _Round_")
        self.assertEqual(series_key(Path("")), "series")


class TermsKeysTests(unittest.TestCase):
    """Keys of a table whose selection is the ticks and whose cursor opens the reader (10.7)."""

    def setUp(self):
        self.s = RowSelection()
        self.s.set_rows(["a", "b", "c", "d", "e"])

    def test_arrows_move_the_cursor_and_never_tick(self):
        self.s.move(1, select=False)
        self.assertEqual((self.s.cursor, self.s.selected()), ("b", []))
        self.s.move(2, select=False)
        self.assertEqual(self.s.cursor, "d")
        self.s.move(9, select=False)
        self.assertEqual(self.s.cursor, "e", "stops at the end")
        self.s.home(select=False)
        self.assertEqual(self.s.cursor, "a")
        self.s.end(select=False)
        self.assertEqual(self.s.cursor, "e")
        self.assertEqual(self.s.selected(), [])

    def test_space_ticks_the_cursor_row_and_moving_keeps_the_ticks(self):
        self.s.goto(1, select=False)
        self.assertTrue(self.s.toggle_cursor())
        self.s.move(2, select=False)
        self.assertEqual(self.s.selected(), ["b"])
        self.s.toggle_cursor()
        self.assertEqual(self.s.selected(), ["b", "d"])
        self.s.goto(1, select=False)
        self.s.toggle_cursor()
        self.assertEqual(self.s.selected(), ["d"])

    def test_a_click_on_the_body_points_and_keeps_the_ticks(self):
        self.s.click(0, ctrl=True)
        self.s.cursor = None
        self.assertTrue(self.s.point(3))
        self.assertEqual((self.s.cursor, self.s.selected()), ("d", ["a"]))
        self.assertFalse(self.s.point(3))
        self.assertFalse(self.s.point(99))

    def test_shift_range_and_select_all_and_positions(self):
        self.s.click(1, ctrl=True)
        self.s.click(3, shift=True)
        self.assertEqual(self.s.selected(), ["b", "c", "d"])
        self.assertEqual(self.s.positions(), {1, 2, 3})
        self.s.select_all()
        self.assertEqual(len(self.s.selected()), 5)
        self.s.clear()
        self.assertEqual((self.s.selected(), self.s.cursor), ([], None))

    def test_ticks_and_cursor_survive_a_new_arrangement(self):
        self.s.click(1, ctrl=True)
        self.s.goto(3, select=False)
        self.s.set_rows(["d", "b", "x"])
        self.assertEqual((self.s.selected(), self.s.cursor), (["b"], "d"))
        self.s.set_rows(["x"])
        self.assertEqual((self.s.selected(), self.s.cursor), ([], None))

    def test_the_old_behaviour_of_goto_is_unchanged(self):
        self.s.goto(2)
        self.assertEqual(self.s.selected(), ["c"])
        self.s.move(1, extend=True)
        self.assertEqual(self.s.selected(), ["c", "d"])


if __name__ == "__main__":
    unittest.main()
