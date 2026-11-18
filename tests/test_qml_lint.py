"""Static checks over the QML files: house rules of the window (review_window_arch D6/D7) and a clean pyside6-qmllint run.

The rule checks are plain Python and run everywhere; the qmllint run is skipped when the tool is not installed (the system
Python has no PySide6).
"""

import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QML_ROOT = REPO / "novelgui" / "qml"
MAX_JS_LINES = 15
BANNED = ("ShaderEffect", "MultiEffect", "DropShadow", "GaussianBlur", "FastBlur", "RectangularGlow", "layer.enabled",
          "layer.effect")


def strip_noise(text: str) -> str:
    """The text with comments and string contents blanked out (same length, so positions stay valid)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(c + " " * (j - i - 1) + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def block_around(clean: str, pos: int) -> tuple:
    """(start, end) of the innermost { } block that contains pos."""
    depth, i = 0, pos
    while i >= 0:
        if clean[i] == "}":
            depth += 1
        elif clean[i] == "{":
            if depth == 0:
                break
            depth -= 1
        i -= 1
    start = i
    depth, j = 0, start
    while j < len(clean):
        if clean[j] == "{":
            depth += 1
        elif clean[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return start, j


def top_level_lines(clean: str, start: int, end: int) -> str:
    """The block's own text without its nested { } blocks."""
    out, depth = [], 0
    for ch in clean[start + 1:end]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def check_infinite(text: str) -> list:
    """Every looping animation must have `running:` bound to something with Visual.live (and a Timer that repeats, too)."""
    clean = strip_noise(text)
    problems = []
    for m in re.finditer(r"\bloops\s*:\s*(Animation\.Infinite|-1)", clean):
        s, e = block_around(clean, m.start())
        own = top_level_lines(clean, s, e)
        if not re.search(r"\brunning\s*:[^\n]*Visual\.live", own):
            problems.append("line %d: loops: Infinite without running bound to Visual.live" % (clean.count("\n", 0, m.start()) + 1))
    for m in re.finditer(r"\bTimer\s*\{", clean):
        s, e = block_around(clean, m.end() - 1)
        own = top_level_lines(clean, s, e)
        if re.search(r"\brepeat\s*:\s*true", own) and not re.search(r"\brunning\s*:[^\n]*Visual\.live", own):
            problems.append("line %d: repeating Timer without running bound to Visual.live" % (clean.count("\n", 0, m.start()) + 1))
    return problems


def check_banned(text: str) -> list:
    clean = strip_noise(text)
    return ["line %d: %s is not allowed (software scene graph, D7)" % (clean.count("\n", 0, m.start()) + 1, m.group(0))
            for m in re.finditer("|".join(re.escape(b) for b in BANNED), clean)]


def check_js_length(text: str, limit: int = MAX_JS_LINES) -> list:
    """`function` bodies and `=> { }` handler bodies of at most `limit` lines."""
    clean = strip_noise(text)
    problems = []
    for m in re.finditer(r"\bfunction\b[^{;]*\{|=>\s*\{", clean):
        s = m.end() - 1
        depth, j = 0, s
        while j < len(clean):
            if clean[j] == "{":
                depth += 1
            elif clean[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = [ln for ln in clean[s + 1:j].split("\n") if ln.strip()]
        if len(body) > limit:
            problems.append("line %d: JS function of %d lines (max %d)" % (clean.count("\n", 0, m.start()) + 1, len(body), limit))
    return problems


def qml_files() -> list:
    return sorted(QML_ROOT.rglob("*.qml"))


def find_qmllint():
    exe = "pyside6-qmllint.exe" if os.name == "nt" else "pyside6-qmllint"
    for base in (Path(sys.executable).parent, REPO / ".venv-window" / ("Scripts" if os.name == "nt" else "bin")):
        if (base / exe).exists():
            return str(base / exe)
    return shutil.which("pyside6-qmllint")


class RuleSamplesTest(unittest.TestCase):
    """The checks themselves: they must catch what they are for."""

    def test_infinite_without_binding_is_caught(self):
        bad = "Item { NumberAnimation { loops: Animation.Infinite; running: true } }"
        self.assertEqual(len(check_infinite(bad)), 1)
        none = "Item { RotationAnimator on rotation { loops: Animation.Infinite } }"
        self.assertEqual(len(check_infinite(none)), 1)
        other = "Item { NumberAnimation { loops: Animation.Infinite\n running: visible } }"
        self.assertEqual(len(check_infinite(other)), 1)

    def test_infinite_with_visual_live_passes(self):
        good = "Item { NumberAnimation { loops: Animation.Infinite; running: Visual.live && parent.visible } }"
        self.assertEqual(check_infinite(good), [])
        multi = "Item { SequentialAnimation {\n loops: Animation.Infinite\n running: Visual.live\n NumberAnimation { running: true } } }"
        self.assertEqual(check_infinite(multi), [])

    def test_binding_of_a_neighbour_does_not_count(self):
        text = "Item { A { running: Visual.live }\n B { loops: Animation.Infinite; running: true } }"
        self.assertEqual(len(check_infinite(text)), 1)

    def test_comments_and_strings_are_ignored(self):
        text = '// loops: Animation.Infinite\nItem { property string s: "loops: Animation.Infinite" }'
        self.assertEqual(check_infinite(text), [])

    def test_repeating_timer_needs_the_binding(self):
        self.assertEqual(len(check_infinite("Item { Timer { repeat: true; running: true } }")), 1)
        self.assertEqual(check_infinite("Item { Timer { repeat: true; running: Visual.live } }"), [])
        self.assertEqual(check_infinite("Item { Timer { interval: 600 } }"), [])

    def test_long_function_is_caught(self):
        body = "\n".join("        x += %d" % i for i in range(MAX_JS_LINES + 1))
        self.assertEqual(len(check_js_length("Item {\n    function f() {\n%s\n    }\n}" % body)), 1)
        self.assertEqual(len(check_js_length("Item {\n    onX: v => {\n%s\n    }\n}" % body)), 1)
        ok = "\n".join("        x += %d" % i for i in range(MAX_JS_LINES))
        self.assertEqual(check_js_length("Item {\n    function f() {\n%s\n    }\n}" % ok), [])

    def test_braces_in_strings_do_not_confuse(self):
        text = 'Item {\n    function f() {\n        return "}{"\n    }\n}'
        self.assertEqual(check_js_length(text), [])

    def test_banned_effects(self):
        self.assertEqual(len(check_banned("Item { MultiEffect { } }")), 1)
        self.assertEqual(len(check_banned("Item { layer.enabled: true }")), 1)
        self.assertEqual(check_banned("// ShaderEffect is out\nItem { }"), [])


class HouseRulesTest(unittest.TestCase):
    def test_files_found(self):
        names = {p.name for p in qml_files()}
        for must in ("Theme.qml", "Pill.qml", "DataList.qml", "Main.qml"):
            self.assertIn(must, names)

    def test_every_infinite_animation_is_bound_to_visual_live(self):
        problems = ["%s %s" % (p.name, m) for p in qml_files() for m in check_infinite(p.read_text(encoding="utf-8"))]
        self.assertEqual(problems, [])

    def test_js_functions_stay_short(self):
        problems = ["%s %s" % (p.name, m) for p in qml_files() for m in check_js_length(p.read_text(encoding="utf-8"))]
        self.assertEqual(problems, [])

    def test_no_effects(self):
        problems = ["%s %s" % (p.name, m) for p in qml_files() for m in check_banned(p.read_text(encoding="utf-8"))]
        self.assertEqual(problems, [])

    def test_qmldir_lists_every_component(self):
        listed = set(re.findall(r"^(?:singleton )?(\w+) \d+\.\d+ (\w+)\.qml$", (QML_ROOT / "Novel" / "qmldir").read_text(), re.M))
        for name, file in listed:
            self.assertEqual(name, file)
        have = {p.stem for p in (QML_ROOT / "Novel").glob("*.qml")}
        self.assertEqual(have, {n for n, _ in listed})


@unittest.skipUnless(find_qmllint(), "pyside6-qmllint is not installed")
class QmllintTest(unittest.TestCase):
    def test_zero_warnings(self):
        files = [str(p) for p in qml_files()]
        # `--import disable`: qmllint wrongly reports the singletons Focus / Tips / Visual of the Novel module as "not declared as
        # singleton in qmldir" (they are, and they work); every other category stays on.
        proc = subprocess.run([find_qmllint(), "--import", "disable", "-I", str(QML_ROOT)] + files, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=240, cwd=str(REPO))
        bad = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.startswith(("Warning:", "Error:"))]
        self.assertEqual(bad, [], "\n".join(bad[:20]))
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
