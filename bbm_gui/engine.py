"""Engine discovery: where it is, which Python runs it, and its flag inventory."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

HELPERS = Path(__file__).resolve().parent / "helpers"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAILURE_MARKER = "[Translation unavailable]"


def is_engine(root):
    p = Path(root or "")
    return (p / "make_book.py").is_file() and (p / "book_maker" / "cli.py").is_file()


def venv_python(root):
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python", "venv/Scripts/python.exe", "venv/bin/python"):
        p = Path(root) / rel
        if p.is_file():
            return str(p)
    return None


def guess_python(root):
    """The Python for an engine folder: its own virtual environment, else the Python running the GUI."""
    return venv_python(root) or shutil.which("python") or sys.executable


def child_env(extra=None):
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "COLUMNS": "4000"})  # a wide console keeps a retry block on one line
    if extra:
        env.update(extra)
    return env


def python_version(python, timeout=20):
    """(major, minor) of the engine's interpreter, or None if it cannot be asked."""
    try:
        proc = _run([python, "-I", "-B", "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], timeout)
        major, minor = proc.stdout.decode("ascii", "replace").strip().split(".")
        return int(major), int(minor)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def engine_key(root, python):
    h = hashlib.sha256()
    h.update(str(python).encode("utf-8"))
    for f in sorted(Path(root, "book_maker").rglob("*.py")):
        h.update(str(f.relative_to(root)).encode("utf-8"))
        h.update(f.read_bytes())
    h.update((HELPERS / "inventory.py").read_bytes())
    return h.hexdigest()[:20]


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW, env=child_env())


def _parse(proc):
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("flags") else None


def load_inventory(root, python, cache_dir, timeout=90):
    """Return (inventory, note). The runtime helper runs under the engine's Python; the result is cached per
    engine contents and interpreter. If it fails, the flags are read from the source without running it."""
    key = engine_key(root, python)
    cache = Path(cache_dir) / ("inventory-%s.json" % key)
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8")), "cached"
        except ValueError:
            pass
    note = ""
    try:
        proc = _run([python, "-I", "-B", str(HELPERS / "inventory.py"), "runtime", str(root)], timeout)
        inv = _parse(proc)
        if inv:
            cache.write_text(json.dumps(inv), encoding="utf-8")
            return inv, "runtime"
        note = (proc.stderr or proc.stdout)[-300:].decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as e:
        note = str(e)
    try:
        cli = str(Path(root, "book_maker", "cli.py"))
        proc = _run([sys.executable, "-I", "-B", str(HELPERS / "inventory.py"), "ast", cli], 30)
        inv = _parse(proc)
        if inv:
            return inv, "source (%s)" % (note or "engine could not be started")
    except (OSError, subprocess.SubprocessError):
        pass
    return None, note or "no flags found"


class Capabilities:
    def __init__(self, inv):
        self.ids = {f["id"] for f in (inv or {}).get("flags", [])}

    def has(self, flag):
        return flag in self.ids

    @property
    def modern(self):
        return "--api_format" in self.ids


def load_overlay():
    with open(Path(__file__).resolve().parent / "overlay.toml", "rb") as f:
        return tomllib.load(f)
