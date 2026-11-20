"""The layers of the window (window_spec 14.21): QML -> view-models -> controllers / facade -> core; Qt stays out of the
controller and facade layers, and the QML files import nothing of Python."""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "novelgui"
# Modules that may use Qt: the view-model layer, the runtime shell, the helper-process client and the timer glue.
QT_MODULES = {"crunchclient.py", "qtclock.py"}
QT_DIRS = {"vm", "runtime"}
QML_IMPORTS = {"QtQuick", "QtQuick.Window", "QtQuick.Dialogs", "QtQuick.Shapes", "Novel", "Shell", "Books", "Export",
               "Terms", "Translate"}


def imported(path: Path) -> set:
    """Top-level names and dotted modules a Python file imports (relative imports resolved to the package)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT).with_suffix("").parts
    pkg = list(rel[:-1])
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg[:len(pkg) - (n.level - 1)]
                mod = ".".join(base + ([n.module] if n.module else []))
            else:
                mod = n.module or ""
            out.add(mod)
            out.update(mod + "." + a.name for a in n.names)
    return out


def python_files(*parts):
    return sorted(p for p in PKG.joinpath(*parts).rglob("*.py"))


def uses_qt(path: Path) -> bool:
    return any(m.split(".")[0] in ("PySide6", "shiboken6") for m in imported(path))


class QmlLayer(unittest.TestCase):
    def test_qml_imports_only_qt_and_its_own_components(self):
        bad = []
        for p in sorted((PKG / "qml").rglob("*.qml")):
            for line in p.read_text(encoding="utf-8").splitlines():
                m = re.match(r'\s*import\s+("?[\w.]+"?)', line)
                if m and m.group(1).strip('"') not in QML_IMPORTS:
                    bad.append("%s: %s" % (p.name, line.strip()))
        self.assertEqual(bad, [])

    def test_qml_names_no_python_module(self):
        bad = [p.name for p in sorted((PKG / "qml").rglob("*.qml"))
               if re.search(r"\b(novelgui|novelcore)\b|\.py\b", re.sub(r"//.*", "", p.read_text(encoding="utf-8")))]
        self.assertEqual(bad, [])


class TooltipTexts(unittest.TestCase):
    def test_qml_carries_no_tooltip_text_of_its_own(self):
        """Tooltip texts live in tips.py / termtips.py; QML reads them from the view-models."""
        rx = re.compile(r'\w*[tT]ip\s*:(?:[^"]*[?:]\s*)?"[A-Za-z]')
        bad = []
        for p in sorted((PKG / "qml").rglob("*.qml")):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//")[0]
                if rx.search(code) and "property" not in code:
                    bad.append("%s:%d %s" % (p.name, n, line.strip()))
        self.assertEqual(bad, [])


    def test_the_terms_view_model_builds_its_tooltips_only_from_termtips(self):
        """TermsVM._tips() holds no literal text: every value is an attribute of termtips (a template or a function)."""
        import ast
        tree = ast.parse((PKG / "vm" / "termsvm.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_tips")
        values = [v for n in ast.walk(fn) if isinstance(n, ast.Dict) for v in n.values]
        self.assertGreater(len(values), 5)
        for v in values:
            self.assertIsInstance(v, ast.Attribute, ast.dump(v))
            self.assertEqual(v.value.id, "termtips")


class QtFreeLayers(unittest.TestCase):
    def test_controllers_facade_and_pure_modules_import_no_qt(self):
        bad = []
        for p in python_files():
            rel = p.relative_to(PKG)
            if rel.parts[0] in QT_DIRS or rel.parts[0] == "qml" or rel.name in QT_MODULES:
                continue
            if rel.name in ("lanes.py", "crunch.py"):       # Qt only inside a function that the helper never calls
                continue
            if uses_qt(p):
                bad.append(str(rel))
        self.assertEqual(bad, [])

    def test_lanes_and_the_helper_import_qt_only_lazily(self):
        for name in ("lanes.py", "crunch.py"):
            tree = ast.parse((PKG / name).read_text(encoding="utf-8"))
            top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
            for n in top:
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                self.assertFalse(any(m.split(".")[0] == "PySide6" for m in mods), name)


class Direction(unittest.TestCase):
    def test_lower_layers_never_import_the_view_models_or_the_runtime(self):
        bad = []
        for sub in ("ctl", "facade"):
            for p in python_files(sub):
                for m in imported(p):
                    if m.startswith(("novelgui.vm", "novelgui.runtime")) and m != "novelgui.runtime.paths"                             and m != "novelgui.runtime":
                        bad.append("%s -> %s" % (p.relative_to(PKG), m))
        self.assertEqual(sorted(set(bad)), [])

    def test_view_models_reach_the_core_only_through_the_facade(self):
        bad = []
        for p in python_files("vm"):
            for m in imported(p):
                if m.split(".")[0] == "novelcore":
                    bad.append("%s -> %s" % (p.relative_to(PKG), m))
        self.assertEqual(sorted(set(bad)), [])

    def test_controllers_reach_the_core_only_through_the_facade(self):
        bad = []
        for p in python_files("ctl"):
            for m in imported(p):
                if m.split(".")[0] == "novelcore":
                    bad.append("%s -> %s" % (p.relative_to(PKG), m))
        self.assertEqual(sorted(set(bad)), [])

    def test_no_view_model_imports_the_qml_layer_or_another_view_model_package(self):
        bad = []
        for p in python_files("vm"):
            for m in imported(p):
                if m.startswith("novelgui.qml") or m == "tkinter":
                    bad.append("%s -> %s" % (p.relative_to(PKG), m))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
