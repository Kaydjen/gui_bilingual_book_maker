"""Operating-system calls live behind novelgui/platform.py and have a working fallback off Windows."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "novelgui"
WIN_ONLY = re.compile(r"windll|winreg|msvcrt|startfile|creationflags|LOCALAPPDATA|WinDLL")
ALLOWED = {PKG / "platform.py", PKG / "runtime" / "winframe.py"}


def sources():
    for p in sorted(PKG.rglob("*.py")):
        yield p, p.read_text(encoding="utf-8")


class Grep(unittest.TestCase):
    def test_windows_calls_stay_in_platform(self):
        hits = [str(p.relative_to(ROOT)) for p, text in sources() if p not in ALLOWED and WIN_ONLY.search(text)]
        self.assertEqual(hits, [])

    def test_no_toolkit_of_the_old_window_is_left(self):
        self.assertEqual([str(p.relative_to(ROOT)) for p, text in sources() if "tkinter" in text], [])

    def test_the_native_frame_is_imported_only_from_platform(self):
        users = [str(p.relative_to(ROOT)) for p, text in sources()
                 if p not in ALLOWED and re.search(r"\bwinframe\b", text) and "import" in text
                 and re.search(r"(from|import)\s+[.\w]*winframe|import\s+winframe", text)]
        self.assertEqual(users, [])
        self.assertIn("winframe", (PKG / "platform.py").read_text(encoding="utf-8"))


class Linux(unittest.TestCase):
    def setUp(self):
        from novelgui import platform
        self.p = platform
        patch = mock.patch.object(platform, "IS_WINDOWS", False)
        patch.start()
        self.addCleanup(patch.stop)

    def test_folders_follow_the_xdg_variables(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": tmp + "/d", "XDG_CONFIG_HOME": tmp + "/c"}):
            self.assertEqual(self.p.local_data_base(), Path(tmp + "/d"))
            self.assertEqual(self.p.config_base(), Path(tmp + "/c"))

    def test_no_windows_flags(self):
        for f in (self.p.no_window, self.p.new_console, self.p.detached):
            self.assertEqual(f(), {})

    def test_the_interpreter_of_an_environment(self):
        self.assertEqual(self.p.venv_python("/v", True), os.path.join("/v", "bin", "python"))
        self.assertEqual(self.p.windowed_python("/usr/bin/python3"), "/usr/bin/python3")
        self.assertEqual(self.p.console_python("/usr/bin/python3"), "/usr/bin/python3")

    def test_a_running_process_is_found(self):
        self.assertTrue(self.p.pid_alive(os.getpid()))
        self.assertFalse(self.p.pid_alive(0))

    def test_open_folder_asks_the_desktop(self):
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(subprocess, "Popen") as popen:
            self.assertTrue(self.p.open_folder("/tmp"))
            popen.assert_called_once_with(["xdg-open", "/tmp"])
            popen.reset_mock()
            self.assertTrue(self.p.reveal_file("/tmp/a.epub"))
            self.assertEqual(popen.call_args[0][0][0], "xdg-open")

    def test_the_rest_is_a_quiet_no_op(self):
        self.assertIsNone(self.p.keep_awake(True))
        self.assertFalse(self.p.flash_window(5))
        self.assertFalse(self.p.message_box("x"))
        self.assertIsNone(self.p.allow_set_foreground(5))
        self.assertIsNone(self.p.install_frame(None, None, None))


class Import(unittest.TestCase):
    def test_the_plain_modules_import_on_linux(self):
        """Every module without Qt imports with sys.platform set to linux."""
        mods = []
        for p, text in sources():
            if "PySide6" in text or p.name == "__main__.py":
                continue
            rel = p.relative_to(ROOT).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts.pop()
            mods.append(".".join(parts))
        code = ("import sys, importlib\nsys.platform = 'linux'\nbad = []\nfor m in %r:\n    try:\n"
                "        importlib.import_module(m)\n    except Exception as e:\n        bad.append('%%s: %%r' %% (m, e))\n"
                "print('\\n'.join(bad))\n") % (mods,)
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env,
                             timeout=120)
        self.assertEqual(out.stdout.strip(), "", out.stderr)


if __name__ == "__main__":
    unittest.main()
