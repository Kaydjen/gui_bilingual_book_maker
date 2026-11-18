"""The helper process `python -m novelgui.crunch` and its GUI-side client.

Without Qt: the wire format, the task functions called in-process, the child driven over pipes by this test
(batches, errors, cancel, idle exit, parent check, no PySide6). With PySide6: `CrunchClient` on QProcess (scan,
cancel = kill + restart, a crash reported, a dead GUI process, a package path with spaces and Cyrillic letters).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from novelcore import Series
from novelgui import chapterlogic as cl
from novelgui import crunch, wire
from novelgui.facade import books as fbooks
from novelgui.jobstate import Problem
from novelgui.lanes import PlainCtx, Want
from tests.test_core_epub import make_epub

ROOT = Path(__file__).resolve().parent.parent

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


def make_series(root: Path, chapters: int = 6, paras: int = 3, name="Alpha"):
    lib = root / "lib"
    lib.mkdir(exist_ok=True)
    s = Series.create(lib, name, "ru:Russian")
    ep = root / (name + ".epub")
    make_epub(ep, {"c%d.xhtml" % i: "".join("<p>Chapter %d paragraph %d has some words in it.</p>" % (i, p)
                                            for p in range(paras)) for i in range(chapters)})
    return str(s.path), s.add_book(ep)


def child_env(root=ROOT):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONUTF8"] = "1"
    return env


class Wire(unittest.TestCase):
    def test_plain_data_round_trips(self):
        info = cl.ChapterInfo(3, "c3.xhtml", "Глава 3", False, 7, (10, 20), 5, 1)
        prob = Problem(1, "T", 2, "abc", "src", "Failed", "failed", "", "", "")
        data = {"rows": (info, prob), "set": {1, 2}, "map": {1: "a", (2, 3): "b"}, "__x": 1,
                "rx": re.compile("abc", re.I), "list": [1, None, True, 2.5, "é"]}
        back = wire.loads(wire.dumps(data))
        self.assertEqual(back, data)
        self.assertIsInstance(back["rows"], tuple)
        self.assertTrue(wire.dumps(data).isascii())

    def test_a_live_object_is_refused(self):
        with self.assertRaises(TypeError):
            wire.dumps({"x": object()})
        with self.assertRaises(ValueError):
            wire.loads(json.dumps({"__c": "os:PathLike", "f": {}}))


class TasksInProcess(unittest.TestCase):
    def test_the_child_tasks_are_the_facade_functions(self):
        with tempfile.TemporaryDirectory() as d:
            path, stem = make_series(Path(d))
            ctx = PlainCtx()
            res = crunch.run_task_here("scan_book", ctx, {"series_path": path, "book": stem})
            direct = PlainCtx()
            fbooks.scan_chapters_task(direct, path, stem, Want())
            self.assertEqual(res["chapters"], 6)
            self.assertEqual(ctx.items[0][0], "skeleton")
            self.assertEqual([i.blocks for kind, rows in ctx.items[1:] for i in rows],
                             [i.blocks for kind, rows in direct.items[1:] for i in rows] or [3] * 6)
            self.assertTrue(all(i.shas is None for kind, rows in ctx.items for i in rows))
            fbooks.release_books_task(None)


class ChildOverPipes(unittest.TestCase):
    """The child process driven by this test over its pipes (no Qt involved)."""

    def start(self, *args):
        p = subprocess.Popen([sys.executable, "-m", "novelgui.crunch", *args], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=child_env(), cwd=str(ROOT))
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close(), p.stdin.close()))
        hello = wire.loads(p.stdout.readline())
        self.assertGreater(hello["hello"]["pid"], 0)       # a venv launcher may stand between: not p.pid
        return p

    def send(self, p, msg):
        p.stdin.write(wire.dumps(msg))
        p.stdin.flush()

    def until(self, p, tid):
        out = []
        while True:
            line = p.stdout.readline()
            self.assertTrue(line, "the helper closed its output")
            msg = wire.loads(line)
            out.append(msg)
            if msg.get("id") == tid and ("result" in msg or "error" in msg):
                return out

    def test_scan_batches_result_error_and_no_pyside(self):
        with tempfile.TemporaryDirectory() as d:
            path, stem = make_series(Path(d), chapters=120)
            p = self.start()
            self.send(p, {"id": 1, "task": "scan_book", "args": {"series_path": path, "book": stem}})
            out = self.until(p, 1)
            items = [it for m in out if "item" in m for it in m["item"]]
            self.assertTrue(all(len(m["item"]) <= crunch.BATCH_ROWS for m in out if "item" in m))
            self.assertEqual(items[0][0], "skeleton")
            rows = [i for kind, batch in items[1:] for i in batch]
            self.assertEqual(sorted(i.index for i in rows), list(range(120)))
            self.assertIsInstance(rows[0], cl.ChapterInfo)
            self.assertEqual(out[-1]["result"]["chapters"], 120)
            self.send(p, {"id": 2, "task": "scan_book", "args": {"series_path": path, "book": "missing"}})
            err = self.until(p, 2)[-1]
            self.assertIn("error", err)
            self.assertTrue(err["trace"])
            self.send(p, {"id": 3, "task": "ping", "args": {}})
            self.assertFalse(self.until(p, 3)[-1]["result"]["pyside"])
            p.stdin.close()
            self.assertEqual(p.wait(5), 0)                      # its book handles go with it

    def test_cancel_line_stops_a_task(self):
        p = self.start()
        self.send(p, {"id": 5, "task": "ping", "args": {"wait": 30}})
        time.sleep(0.2)
        t0 = time.monotonic()
        self.send(p, {"cancel": 5})
        self.until(p, 5)
        self.assertLess(time.monotonic() - t0, 5)

    def test_it_exits_after_the_idle_time(self):
        p = self.start("--idle", "0.5")
        self.assertEqual(wire.loads(p.stdout.readline()), {"bye": "idle"})
        self.assertEqual(p.wait(5), 0)

    def test_it_exits_when_stdin_closes(self):
        p = self.start()
        p.stdin.close()
        self.assertEqual(p.wait(5), 0)

    def test_it_exits_when_the_parent_dies_even_with_stdin_open(self):
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: (parent.kill(), parent.wait()))
        p = self.start("--parent", str(parent.pid))
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        parent.kill()
        parent.wait()
        self.assertEqual(p.wait(10), 0)

    def test_the_child_import_list_has_no_pyside(self):
        code = ("import sys, novelgui.crunch, novelgui.facade.books, novelgui.facade.terms, novelgui.facade.run, "
                "novelgui.facade.checks, novelgui.facade.quota, novelgui.model, novelgui.ctl.runcontrol, "
                "novelgui.ctl.persistence, novelgui.ctl.terms, novelgui.ctl.books, novelgui.ctl.ordering; "
                "print(any(m.split('.')[0] == 'PySide6' for m in sys.modules))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=child_env(),
                             cwd=str(ROOT), timeout=60)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class Client(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def client(self, **kw):
        from novelgui.crunchclient import CrunchClient
        c = CrunchClient(python=sys.executable, **kw)
        self.addCleanup(c.close)
        return c

    def spin(self, pred, timeout=20.0):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        end = time.monotonic() + timeout
        while not pred():
            if time.monotonic() > end:
                raise AssertionError("timed out")
            QTimer.singleShot(10, loop.quit)
            loop.exec()

    def test_scan_through_the_client(self):
        path, stem = make_series(self.root, chapters=30)
        c = self.client()
        items, res = [], []
        c.submit("scan_book", {"series_path": path, "book": stem}, on_item=items.append, on_result=res.append)
        self.spin(lambda: res)
        self.assertEqual(res[0]["chapters"], 30)
        self.assertEqual(items[0][0], "skeleton")
        self.assertIsInstance(items[1][1][0], cl.ChapterInfo)
        self.assertEqual(c.starts, 1)

    def test_killed_mid_scan_reports_an_error_and_restarts_on_next_use(self):
        path, stem = make_series(self.root, chapters=1500, paras=4)
        c = self.client()
        items, errs, res = [], [], []
        c.submit("scan_book", {"series_path": path, "book": stem}, on_item=items.append, on_result=res.append,
                 on_error=errs.append)
        self.spin(lambda: items)
        os.kill(c.child_pid, 9)                     # a crash from outside, mid-scan
        self.spin(lambda: errs or res)
        self.assertEqual(res, [])
        self.assertIn("stopped unexpectedly", str(errs[0]))
        first = c.child_pid
        pong = []
        c.submit("ping", {}, on_result=pong.append)
        self.spin(lambda: pong)
        self.assertEqual(c.starts, 2)
        self.assertNotEqual(pong[0]["pid"], first)

    def test_cancel_kills_and_the_waiting_tasks_still_run(self):
        c = self.client()
        got = []
        tok = c.submit("ping", {"wait": 30}, on_result=lambda r: got.append("slow"), on_error=got.append)
        c.submit("ping", {}, on_result=lambda r: got.append(("next", r["pid"])))
        self.spin(lambda: c.child_pid)
        first = c.child_pid
        tok.cancel()
        self.spin(lambda: got)
        self.assertEqual(got[0][0], "next")
        self.assertNotEqual(got[0][1], first)
        self.assertEqual(c.starts, 2)

    def test_cancel_mid_scan_lets_go_of_the_book_file(self):
        path, stem = make_series(self.root, chapters=1500, paras=4)
        c = self.client()
        items, res = [], []
        tok = c.submit("scan_book", {"series_path": path, "book": stem}, on_item=items.append, on_result=res.append)
        self.spin(lambda: items)
        tok.cancel()
        book = fbooks.book_file(path, stem)
        moved = []

        def try_move():
            try:
                book.rename(book.with_name("moved.epub"))
                moved.append(True)
            except OSError:
                pass
            return bool(moved)
        self.spin(try_move, timeout=5)
        self.assertEqual(res, [])

    def test_a_superseded_scan_never_reports(self):
        path, stem = make_series(self.root, chapters=800, paras=4)
        c = self.client()
        got = []
        c.submit("scan_book", {"series_path": path, "book": stem}, on_item=lambda x: got.append("old item"),
                 on_result=lambda r: got.append("old"), group="chapters")
        self.spin(lambda: got)
        c.submit("ping", {}, on_result=lambda r: got.append("new"), group="chapters")
        self.spin(lambda: "new" in got)
        self.assertEqual([g for g in got if g != "old item"], ["new"])

    def test_the_helper_exits_when_the_gui_process_dies(self):
        script = self.root / "gui_side.py"
        script.write_text(
            "import sys, time\n"
            "from PySide6.QtCore import QCoreApplication\n"
            "from novelgui.crunchclient import CrunchClient\n"
            "app = QCoreApplication([])\n"
            "c = CrunchClient(python=sys.executable)\n"
            "c.submit('ping', {}, on_result=lambda r: (print(r['pid'], flush=True)))\n"
            "app.exec()\n", encoding="utf-8")
        gui = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True,
                               env=child_env(), cwd=str(ROOT))
        self.addCleanup(lambda: (gui.kill(), gui.wait()))
        child = int(gui.stdout.readline())
        self.assertTrue(crunch.pid_alive(child))
        gui.kill()
        gui.wait()
        end = time.monotonic() + 10
        while crunch.pid_alive(child) and time.monotonic() < end:
            time.sleep(0.1)
        self.assertFalse(crunch.pid_alive(child))

    def test_a_package_path_with_spaces_and_cyrillic_letters(self):
        where = self.root / "папка с пробелами" / "app dir"
        for pkg in ("novelgui", "novelcore"):
            shutil.copytree(ROOT / pkg, where / pkg, ignore=shutil.ignore_patterns("__pycache__"))
        lib = self.root / "библиотека книг"
        lib.mkdir()
        path, stem = make_series(lib, chapters=5)
        c = self.client(package_root=where)
        pong, res = [], []
        c.submit("ping", {}, on_result=pong.append)
        c.submit("scan_book", {"series_path": path, "book": stem}, on_result=res.append)
        self.spin(lambda: pong and res)
        self.assertEqual(Path(pong[0]["package"]).resolve(), (where / "novelgui").resolve())
        self.assertFalse(pong[0]["pyside"])
        self.assertEqual(res[0]["chapters"], 5)


if __name__ == "__main__":
    unittest.main()
