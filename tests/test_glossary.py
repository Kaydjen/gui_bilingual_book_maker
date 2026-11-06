import json, unittest
from bbm_gui.glossary import *

class T(unittest.TestCase):
    def test_json_shapes(self):
        self.assertEqual(from_json('{"A b": "В"}'), [Entry("A b", "В")])
        self.assertEqual(from_json('[{"term":"A","translation":"B","note":"он"}]'), [Entry("A", "B", "он")])
        e = [Entry("A", "B", "n")]
        self.assertEqual(from_json(to_file_text(e)), e)
        self.assertEqual(len(from_json('{"A":"1","A":"2"}')), 2)  # repeated key survives
        with self.assertRaises(ValueError): from_json('[1,2]')
        with self.assertRaises(ValueError): from_json('{"A": 3}')
    def test_text(self):
        self.assertEqual(from_text("- Shi Feng -> Ши Фэн # он\nBlackie → Блэки\n# c\n\n"),
                         [Entry("Shi Feng", "Ши Фэн", "он"), Entry("Blackie", "Блэки")])
        self.assertEqual(from_text("A\tB\tn\nC\tD"), [Entry("A", "B", "n"), Entry("C", "D")])
        self.assertEqual(from_text("A,B\nC,D"), [Entry("A", "B"), Entry("C", "D")])
        self.assertEqual(from_text("A;B\nC;D"), [Entry("A", "B"), Entry("C", "D")])
    def test_merge_rules(self):
        c = [Entry("a", "1"), Entry("b", "2"), Entry("c", "3")]
        i = [Entry("B", "22"), Entry("c", "3"), Entry("d", "4")]
        m, r = merge(c, i)
        self.assertEqual([(e.term, e.translation) for e in m], [("a", "1"), ("b", "22"), ("c", "3")])
        self.assertEqual(r, dict(matched=2, changed=1, kept=1, added=0, ignored=1))
        m, r = merge(c, i, union=True)
        self.assertEqual([e.term for e in m], ["a", "b", "c", "d"])
        m, _ = merge(c, i, prefer="current")
        self.assertEqual(m[1].translation, "2")
    def test_older(self):
        d = compare_with_older([Entry("Void", "Пустота")], {"v1": [Entry("void", "Сфера"), Entry("x", "y")]})
        self.assertEqual(d, [("Void", [("v1", "Сфера")], "Пустота")])
    def test_levenshtein(self):
        self.assertEqual(levenshtein("kitten", "sitting"), 3)
        self.assertEqual(levenshtein("abc", "abc"), 0)
        self.assertEqual(levenshtein("abcdef", "uvwxyz", 2), 3)
    def test_near(self):
        t = ["Flett", "Frett", "Lu Xingluo", "Lu Xinglou", "Ann", "Anne", "Shi Feng", "shi  feng"]
        got = {(i, j): d for d, i, j in near_duplicates(t)}
        self.assertEqual(got[(0, 1)], 1); self.assertEqual(got[(2, 3)], 2); self.assertEqual(got[(6, 7)], 0)
        self.assertNotIn((4, 5), got)  # shorter than min_len
        d = {(i, j): x for x, i, j in near_duplicates(["Island No. 3", "Island No. 7", "God's Domain", "God’s Domain"])}
        self.assertEqual(d, {(2, 3): 0})  # digits-only variants skipped, curly quote is a true duplicate
    def test_validate(self):
        r = validate([Entry("a", ""), Entry("A", "x"), Entry("a", "y"), Entry("{S}", "z"), Entry("#1", "q")])
        self.assertEqual(r["empty"], [0]); self.assertEqual(r["dup"], [0, 1, 2]); self.assertEqual(r["brace"], [3]); self.assertEqual(r["hash"], [4])
    def test_build(self):
        t = {"system": "Head {language}\nGLOSSARY:\n", "user": "{text}"}
        p = build_prompt(t, [Entry("{S}", "[С]"), Entry("Shi Feng", "Ши Фэн", "он"), Entry("x", "")])
        self.assertEqual(p["system"], "Head {language}\nGLOSSARY:\n- {{S}} -> [С]\n- Shi Feng -> Ши Фэн (он)")
        self.assertEqual(check_system(p["system"]), [])
        self.assertEqual(p["system"].format(language="Russian", crlf="\n").splitlines()[0], "Head Russian")
        self.assertEqual(check_system("a {x} {language}"), ["braces"])
        self.assertEqual(build_system("T", []), "T")
    def test_roundtrip_his_prompt(self):
        c = json.load(open(r"D:\_\prd\run\bilingual_book_maker\custom_prompt.json", encoding="utf-8"))
        s = c["system"]; at = s.index("\n- ", s.index("ГЛОССАРИЙ")) + 1; head = s[:at]
        ents = from_text(s[at:])
        self.assertEqual(build_system(head, ents), s)  # identical layout to convert_glossary.py
    def test_split_and_used(self):
        s = "Intro\nGLOSSARY:\n- A b -> В\n- C -> Д"
        head, ents = split_prompt(s)
        self.assertEqual((head, ents), ("Intro\nGLOSSARY:\n", [Entry("A b", "В"), Entry("C", "Д")]))
        self.assertEqual(build_system(head, ents), s)
        self.assertEqual(split_prompt("no list"), ("no list", []))
        u = used_in([Entry("Ann", "А"), Entry("Void Realm", "П"), Entry("God's Domain", "Б")], "Announcement. The void  realm of God’s Domain.")
        self.assertEqual([e.term for e in u], ["Void Realm", "God's Domain"])
    def test_file_meta(self):
        txt = to_file_text([Entry("a", "b")], "Russian")
        self.assertEqual(file_language(txt), "Russian")
        self.assertEqual(file_language('{"a":"b"}'), "")
        self.assertEqual(to_engine_txt([Entry("a", "b", "n"), Entry("c", "d")]), "a → b  # n\nc → d\n")
if __name__ == "__main__":
    unittest.main(verbosity=1)
