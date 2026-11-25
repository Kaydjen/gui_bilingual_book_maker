"""Start-up kit of the QML window: folders, instance name, log gate, notifier, single instance, markers, fatal panel.

The process tests start `python -m novelgui` offscreen with a temp NOVELGUI_DATA; they are skipped when PySide6 is
not importable (the system Python). The launcher tests are slow (they download the window library) and run only
with NOVELGUI_SLOW=1.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from novelgui.runtime import instance, log, notify, paths  # noqa: E402

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

SHOTS = Path(os.environ.get("NOVELGUI_SHOTS") or tempfile.gettempdir()) / ("%s-runtime" % datetime.date.today().isoformat())
ENV_KEYS = ("NOVELGUI_DATA", "NOVELGUI_API_BASE", "NOVELGUI_NOTIFY", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
            "XDG_DATA_HOME")


class EnvCase(unittest.TestCase):
    """Saves and restores the environment variables the runtime reads."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        for k in ENV_KEYS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()


class PathsTest(EnvCase):
    def test_with_override(self):
        os.environ["NOVELGUI_DATA"] = str(self.tmp)
        self.assertEqual(paths.settings_dir(), self.tmp)
        self.assertEqual(paths.local_dir(), self.tmp / "local")
        self.assertEqual(paths.logs_dir(), self.tmp / "local" / "logs")
        self.assertEqual(paths.lock_path(), self.tmp / "local" / "app.lock")

    def test_without_override(self):
        if sys.platform == "win32":
            os.environ["APPDATA"] = str(self.tmp / "roaming")
            os.environ["LOCALAPPDATA"] = str(self.tmp / "localapp")
            roaming, local = self.tmp / "roaming", self.tmp / "localapp"
        else:
            os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "cfg")
            os.environ["XDG_DATA_HOME"] = str(self.tmp / "share")
            roaming, local = self.tmp / "cfg", self.tmp / "share"
        self.assertEqual(paths.settings_dir(), roaming / "novelgui")
        self.assertEqual(paths.local_dir(), local / "novelgui")
        self.assertEqual(paths.logs_dir(), local / "novelgui" / "logs")

    def test_settings_data_dir_follows_paths(self):
        from novelgui import settings
        os.environ["NOVELGUI_DATA"] = str(self.tmp)
        self.assertEqual(settings.data_dir(), self.tmp)


class InstanceNameTest(EnvCase):
    def test_name_shape_and_stability(self):
        os.environ["NOVELGUI_DATA"] = str(self.tmp / "a")
        name = instance.instance_name()
        self.assertRegex(name, r"^novelgui-[A-Za-z0-9_-]+-[0-9a-f]{10}$")
        self.assertEqual(name, instance.instance_name())

    def test_differs_by_data_dir(self):
        os.environ["NOVELGUI_DATA"] = str(self.tmp / "a")
        a = instance.instance_name()
        os.environ["NOVELGUI_DATA"] = str(self.tmp / "b")
        self.assertNotEqual(a, instance.instance_name())

    def test_differs_by_api_base(self):
        os.environ["NOVELGUI_DATA"] = str(self.tmp / "a")
        a = instance.instance_name()
        os.environ["NOVELGUI_API_BASE"] = "http://127.0.0.1:18080"
        self.assertNotEqual(a, instance.instance_name())

    def test_lock_in_local_data(self):
        os.environ["NOVELGUI_DATA"] = str(self.tmp)
        self.assertEqual(instance.lock_path(), self.tmp / "local" / "app.lock")


class ErrorGateTest(unittest.TestCase):
    def test_three_in_full_then_one_count_line(self):
        now = [0.0]
        gate = log.ErrorGate(clock=lambda: now[0])
        results = [gate.note("tb")[0] for _ in range(6)]
        self.assertEqual(results, [True, True, True, False, False, False])
        self.assertEqual(gate.note("other")[0], True)
        now[0] = 11.0
        lines = gate.flush()
        self.assertEqual(len(lines), 1)
        self.assertIn("3", lines[0])
        self.assertTrue(gate.note("tb")[0])


class NotifierTest(EnvCase):
    def test_recording_under_data_override(self):
        os.environ["NOVELGUI_DATA"] = str(self.tmp)
        n = notify.make_notifier()
        self.assertIsInstance(n, notify.RecordingNotifier)
        n.toast("Knights", "54 chapters translated", "translate")
        n.flash()
        lines = [json.loads(x) for x in (self.tmp / "notify.log").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["kind"] for x in lines], ["toast", "flash"])
        self.assertEqual(lines[0]["route"], "translate")

    def test_real_when_asked(self):
        os.environ["NOVELGUI_DATA"] = str(self.tmp)
        os.environ["NOVELGUI_NOTIFY"] = "real"
        self.assertIsInstance(notify.make_notifier(), notify.RealNotifier)

    def test_real_without_override(self):
        self.assertIsInstance(notify.make_notifier(), notify.RealNotifier)


class LauncherPlainTest(unittest.TestCase):
    def test_shell_script_syntax(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash")
        r = subprocess.run([bash, "-n", str(REPO / "novel.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_not_ready_without_marker(self):
        from novelgui.runtime import bootstrap
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / bootstrap.REQUIREMENTS).write_text("x==1\n", encoding="utf-8")
            self.assertFalse(bootstrap.venv_ready(d))
            venv = Path(bootstrap.venv_dir(d))
            Path(bootstrap.venv_python(d)).parent.mkdir(parents=True)
            Path(bootstrap.venv_python(d)).write_text("", encoding="utf-8")
            (venv / bootstrap.MARKER).write_text("wrong", encoding="utf-8")
            self.assertFalse(bootstrap.venv_ready(d))
            (venv / bootstrap.MARKER).write_text(bootstrap.requirements_hash(d), encoding="utf-8")
            self.assertTrue(bootstrap.venv_ready(d))
            (Path(d) / bootstrap.REQUIREMENTS).write_text("x==2\n", encoding="utf-8")
            self.assertFalse(bootstrap.venv_ready(d))


# ---- process tests --------------------------------------------------------------------------------------------

HANG_HELPER = """
import os, sys
from PySide6.QtCore import QCoreApplication, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer
from novelgui.runtime import instance
app = QCoreApplication(["hang"])
path = str(instance.lock_path())
os.makedirs(os.path.dirname(path), exist_ok=True)
lock = QLockFile(path)
lock.setStaleLockTime(0)
assert lock.tryLock(0)
name = instance.instance_name()
QLocalServer.removeServer(name)
server = QLocalServer()
assert server.listen(name)
print("ready", flush=True)
QTimer.singleShot(40000, app.quit)
app.exec()
"""


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ProcessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        self.local = self.data / "local"
        self.msg = Path(self._tmp.name) / "messages.txt"
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            for s in (p.stdout, p.stderr):
                if s:
                    s.close()
        for _ in range(30):
            try:
                self._tmp.cleanup()
                break
            except PermissionError:
                time.sleep(0.2)

    def env(self, **extra):
        env = dict(os.environ)
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", PYTHONUTF8="1",
                   NOVELGUI_DATA=str(self.data), NOVELGUI_MESSAGE_FILE=str(self.msg))
        if sys.platform == "win32":
            env["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
        for k in ("NOVELGUI_API_BASE", "NOVELGUI_STRICT", "NOVELGUI_TEST_PLANT", "NOVELGUI_TEST_EXIT_AFTER",
                  "NOVELGUI_TEST_GRAB", "NOVELGUI_NOTIFY"):
            env.pop(k, None)
        env.update(extra)
        return env

    def start(self, args=(), **extra):
        p = subprocess.Popen([sys.executable, "-m", "novelgui", *args], cwd=str(REPO), env=self.env(**extra),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.procs.append(p)
        return p

    def log_text(self):
        try:
            return (self.local / "logs" / "novelgui.log").read_text(encoding="utf-8")
        except OSError:
            return ""

    def wait_for(self, cond, timeout=25.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.1)
        return False

    def wait_shown(self, proc, count=1):
        ok = self.wait_for(lambda: self.log_text().count("window shown") >= count or proc.poll() is not None)
        self.assertIsNone(proc.poll(), "the first instance died: %s" % self.log_text())
        self.assertTrue(ok, self.log_text())

    def test_second_start_raises_the_first(self):
        first = self.start()
        self.wait_shown(first)
        books = [str(Path(self._tmp.name) / "One.epub"), str(Path(self._tmp.name) / "two words.EPUB")]
        second = self.start(books + ["notes.txt"])
        self.assertEqual(second.wait(timeout=30), 0, second.stderr.read())
        self.assertTrue(self.wait_for(lambda: "raise request" in self.log_text()), self.log_text())
        text = self.log_text()
        for b in books:
            self.assertIn(b.replace("\\", "\\\\"), text)
        self.assertNotIn("notes.txt", text)
        self.assertIn("The app is already open. It runs in one window, so this one was brought back.", text)
        self.assertIsNone(first.poll())
        self.assertFalse(self.msg.exists())
        self.assertEqual(self.local.joinpath("logs").exists(), True)

    def test_hung_first_instance(self):
        helper = subprocess.Popen([sys.executable, "-c", HANG_HELPER], cwd=str(REPO), env=self.env(),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(helper)
        self.assertEqual(helper.stdout.readline().strip(), "ready", helper.stderr.read() if helper.poll() else "")
        t0 = time.monotonic()
        second = self.start()
        code = second.wait(timeout=30)
        took = time.monotonic() - t0
        self.assertEqual(code, 1)
        self.assertLess(took, 8.0)
        self.assertIn("The app is open but not answering.", self.msg.read_text(encoding="utf-8"))

    def test_slot_exception_is_logged_and_app_goes_on(self):
        first = self.start(NOVELGUI_TEST_PLANT="slot")
        self.wait_shown(first)
        self.assertTrue(self.wait_for(lambda: "Planted slot failure" in self.log_text()), self.log_text())
        self.assertIsNone(first.poll())
        second = self.start()
        self.assertEqual(second.wait(timeout=30), 0)
        self.assertTrue(self.wait_for(lambda: "raise request" in self.log_text()), self.log_text())
        self.assertIsNone(first.poll())

    def test_strict_mode_exits_on_slot_exception(self):
        first = self.start(NOVELGUI_TEST_PLANT="slot", NOVELGUI_STRICT="1")
        self.assertEqual(first.wait(timeout=30), 1)
        self.assertIn("STRICT", self.log_text())

    def test_startup_failure_shows_fatal_panel(self):
        SHOTS.mkdir(parents=True, exist_ok=True)
        png = SHOTS / "fatal.png"
        if png.exists():
            png.unlink()
        proc = self.start(NOVELGUI_TEST_PLANT="startup", NOVELGUI_TEST_GRAB=str(png))
        self.assertEqual(proc.wait(timeout=40), 1)
        report = json.loads(png.with_suffix(".json").read_text(encoding="utf-8"))
        png.with_suffix(".json").unlink()
        self.assertEqual(report["quitButton"], "Quit")
        self.assertEqual(report["copyButton"], "Copy details")
        self.assertEqual(report["logButton"], "Open log")
        self.assertEqual(report["fatalHeading"], "The app could not start")
        self.assertIn("Planted startup failure", report["fatalReason"])
        self.assertGreater(png.stat().st_size, 500)
        self.assert_buttons_are_ours(png, report["rects"])
        self.assertIn("Planted startup failure", self.log_text())
        self.assertFalse((self.local / "running.flag").exists())

    def assert_buttons_are_ours(self, png, rects):
        """The buttons are the window's own pills (dark fill, or none for a plain one), not the light grey of the stock style:
        a pixel inside every button and the window background are all dark."""
        from PySide6.QtGui import QImage
        img = QImage(str(png))
        self.assertFalse(img.isNull())
        for name in ("quitButton", "copyButton", "logButton"):
            x, y, w, h = rects[name]
            for dx in (4, w / 2):
                c = img.pixelColor(int(x + dx), int(y + 4))
                self.assertLess(max(c.red(), c.green(), c.blue()), 60, "%s is not dark: %s" % (name, c.name()))
        c = img.pixelColor(int(rects["quitButton"][0] + 4), int(rects["quitButton"][1] + 4))
        self.assertGreater(c.red(), 12, "the main button keeps its pill fill (#171717), not the bare window")

    def test_running_flag(self):
        first = self.start()
        self.wait_shown(first)
        flag = self.local / "running.flag"
        self.assertTrue(flag.exists())
        self.assertTrue(self.wait_for(lambda: not (self.local / "render.trial").exists()), "trial not cleared")
        first.kill()
        first.wait()
        self.assertTrue(flag.exists())
        again = self.start(NOVELGUI_TEST_EXIT_AFTER="2")
        self.assertEqual(again.wait(timeout=40), 0)
        self.assertIn("previous run did not end cleanly", self.log_text())
        self.assertFalse(flag.exists())

    def test_clean_exit_leaves_no_markers(self):
        proc = self.start(NOVELGUI_TEST_EXIT_AFTER="2")
        self.assertEqual(proc.wait(timeout=40), 0)
        self.assertFalse((self.local / "running.flag").exists())
        self.assertFalse((self.local / "render.trial").exists())
        self.assertNotIn("did not end cleanly", self.log_text())
        self.assertFalse((self.local / "app.lock").exists())

    def test_render_trial_forces_software(self):
        self.local.mkdir(parents=True)
        (self.local / "render.trial").write_text("1", encoding="utf-8")
        proc = self.start(NOVELGUI_TEST_EXIT_AFTER="2")
        self.assertEqual(proc.wait(timeout=40), 0)
        self.assertIn("an earlier start did not draw", self.log_text())
        self.assertFalse((self.local / "render.trial").exists())
        self.assertTrue((self.local / "render.software").exists())
        again = self.start(NOVELGUI_TEST_EXIT_AFTER="2")         # sticky: no new GPU trial
        self.assertEqual(again.wait(timeout=40), 0)
        self.assertEqual(self.log_text().count("an earlier start did not draw"), 2)

    def test_graphics_setting_software(self):
        self.data.mkdir(parents=True)
        (self.data / "settings.json").write_text(json.dumps({"graphics": "software"}), encoding="utf-8")
        proc = self.start(NOVELGUI_TEST_EXIT_AFTER="2")
        self.assertEqual(proc.wait(timeout=40), 0)
        self.assertIn("software renderer (setting)", self.log_text())

    def test_nothing_in_owner_folders(self):
        proc = self.start(NOVELGUI_TEST_EXIT_AFTER="1")
        self.assertEqual(proc.wait(timeout=40), 0)
        self.assertTrue((self.local / "logs" / "novelgui.log").exists())


# ---- launcher tests (slow) ------------------------------------------------------------------------------------

@unittest.skipUnless(os.environ.get("NOVELGUI_SLOW") == "1", "slow: set NOVELGUI_SLOW=1")
class LauncherVenvTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Папка с пробелом"
        (self.root / "novelgui" / "runtime").mkdir(parents=True)
        for name in ("novel.pyw", "novel.bat", "novel.sh", "requirements-window.txt"):
            shutil.copy(REPO / name, self.root / name)
        shutil.copy(REPO / "novelgui" / "__init__.py", self.root / "novelgui" / "__init__.py")
        shutil.copy(REPO / "novelgui" / "runtime" / "__init__.py", self.root / "novelgui" / "runtime" / "__init__.py")
        shutil.copy(REPO / "novelgui" / "runtime" / "bootstrap.py", self.root / "novelgui" / "runtime" / "bootstrap.py")
        self.msg = Path(self._tmp.name) / "messages.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def run_launcher(self, **extra):
        env = dict(os.environ, NOVELGUI_PREPARE_ONLY="1", NOVELGUI_MESSAGE_FILE=str(self.msg), PYTHONUTF8="1")
        env.update(extra)
        return subprocess.run([sys.executable, str(self.root / "novel.pyw")], cwd=str(self.root), env=env,
                               capture_output=True, text=True, timeout=500)

    def marker(self):
        return self.root / ".venv-window" / "novel.ready"

    def test_builds_then_rebuilds_on_bad_marker(self):
        from novelgui.runtime import bootstrap
        r = self.run_launcher()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        want = bootstrap.requirements_hash(str(self.root))
        self.assertEqual(self.marker().read_text(encoding="utf-8"), want)
        py = bootstrap.venv_python(str(self.root))
        ok = subprocess.run([py, "-c", "import PySide6.QtQuick"], capture_output=True)
        self.assertEqual(ok.returncode, 0)
        (self.root / ".venv-window" / "stray.txt").write_text("x", encoding="utf-8")
        self.marker().write_text("corrupt", encoding="utf-8")
        r = self.run_launcher()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.marker().read_text(encoding="utf-8"), want)
        self.assertFalse((self.root / ".venv-window" / "stray.txt").exists())

    def test_no_network_gives_plain_message(self):
        r = self.run_launcher(PIP_INDEX_URL="http://127.0.0.1:9/simple", PIP_RETRIES="0", PIP_TIMEOUT="3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Could not download the window library. Check the internet connection and start again.",
                      self.msg.read_text(encoding="utf-8"))
        self.assertFalse(self.marker().exists())


if __name__ == "__main__":
    unittest.main()
