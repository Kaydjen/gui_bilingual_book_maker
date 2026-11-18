"""Start-up kit of the launchers (novel.pyw, novel.sh): the window runs in its own virtual environment.

Standard library only, so any Python 3.8+ can import it. The environment `.venv-window` is made on the first start
with `pip install --require-hashes -r requirements-window.txt`; a ready marker holds the sha256 of that file.
A missing marker or another hash means a half-made or outdated environment: it is deleted and made again.
Environment variables: NOVELGUI_PREPARE_ONLY=1 makes the environment and stops (no window);
NOVELGUI_MESSAGE_FILE=<file> turns a message box into a line appended to that file (scripted checks).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

IS_WINDOWS = sys.platform == "win32"
VENV_NAME = ".venv-window"
REQUIREMENTS = "requirements-window.txt"
MARKER = "novel.ready"
MIN_PYTHON = (3, 11)
TITLE = "Novel"

MSG_PYTHON = "Python 3.11 or newer is required.\nhttps://www.python.org/downloads/"
MSG_DOWNLOAD = "Could not download the window library. Check the internet connection and start again."
MSG_XCB = "Install the package libxcb-cursor0 (sudo apt install libxcb-cursor0) and start again."
MSG_FIRST = "Novel - first start: downloading the window library, about a minute"
MSG_VENV ="Could not prepare the window environment. Start again; if it repeats, delete the folder %s."


def message(text: str) -> None:
    """A plain message: a box on Windows, stderr elsewhere, a line in NOVELGUI_MESSAGE_FILE when that is set."""
    path = os.environ.get("NOVELGUI_MESSAGE_FILE")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        return
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)
            return
        except (AttributeError, OSError):
            pass
    if sys.stderr is not None:
        try:
            sys.stderr.write(text + "\n")
        except (OSError, ValueError):
            pass


def root_dir() -> str:
    """The repository folder: three levels above this file (novelgui/runtime/bootstrap.py)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def venv_dir(root: str) -> str:
    return os.path.join(root, VENV_NAME)


def venv_python(root: str, windowed: bool = False) -> str:
    if IS_WINDOWS:
        return os.path.join(venv_dir(root), "Scripts", "pythonw.exe" if windowed else "python.exe")
    return os.path.join(venv_dir(root), "bin", "python")


def requirements_hash(root: str) -> str:
    with open(os.path.join(root, REQUIREMENTS), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def venv_ready(root: str) -> bool:
    """True when the environment exists and its marker holds the hash of the current requirements file."""
    try:
        with open(os.path.join(venv_dir(root), MARKER), encoding="utf-8") as f:
            marker = f.read().strip()
        return marker == requirements_hash(root) and os.path.isfile(venv_python(root))
    except OSError:
        return False


def _run_python(exe: str) -> tuple | None:
    try:
        out = subprocess.run([exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True,
                             text=True, timeout=30, creationflags=_no_window()).stdout.strip()
        major, minor = out.split(".")
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _no_window() -> int:
    return 0x08000000 if IS_WINDOWS else 0      # CREATE_NO_WINDOW


def find_python() -> str | None:
    """A Python 3.11+ to build the environment with: this one when it is new enough, else one found on the PC."""
    exe = sys.executable or ""
    if IS_WINDOWS and exe.lower().endswith("pythonw.exe"):
        console = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(console):
            exe = console
    if sys.version_info >= MIN_PYTHON and exe:
        return exe
    candidates = []
    if IS_WINDOWS:
        launcher = shutil.which("py")
        if launcher:
            for minor in range(15, MIN_PYTHON[1] - 1, -1):
                try:
                    out = subprocess.run([launcher, "-3.%d" % minor, "-c", "import sys;print(sys.executable)"],
                                         capture_output=True, text=True, timeout=30,
                                         creationflags=_no_window()).stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    continue
                if out and os.path.isfile(out):
                    candidates.append(out)
        candidates.append(shutil.which("python") or "")
    else:
        for minor in range(15, MIN_PYTHON[1] - 1, -1):
            candidates.append(shutil.which("python3.%d" % minor) or "")
        candidates += [shutil.which("python3") or "", shutil.which("python") or ""]
    for c in candidates:
        if c and (_run_python(c) or (0, 0)) >= MIN_PYTHON:
            return c
    return None


def has_xcb_cursor() -> bool:
    """Linux: the Qt xcb platform plugin needs libxcb-cursor.so.0. True when it is found or cannot be checked."""
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return "libxcb-cursor.so.0" in out


def make_venv(root: str) -> bool:
    """Delete any old environment and build a new one. False after a message to the user."""
    if sys.platform.startswith("linux") and not has_xcb_cursor():
        message(MSG_XCB)
        return False
    python = find_python()
    if python is None:
        message(MSG_PYTHON)
        return False
    target = venv_dir(root)
    shutil.rmtree(target, ignore_errors=True)
    if os.path.exists(target):          # a file in use: try once more the slow way
        shutil.rmtree(target, ignore_errors=True)
    log_path = os.path.join(tempfile.gettempdir(), "novel-window-setup.log")
    flags = _no_window()
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            made = subprocess.call([python, "-m", "venv", target], stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags)
            if made != 0:
                message(MSG_VENV % target)
                return False
            cmd = [venv_python(root), "-m", "pip", "install", "--disable-pip-version-check", "--require-hashes",
                   "-r", os.path.join(root, REQUIREMENTS)]
            if os.environ.get("NOVELGUI_MESSAGE_FILE"):          # scripted run: quiet, into the log
                pip = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, cwd=root)
            elif IS_WINDOWS:                                       # first start: show the download in a console
                pip = subprocess.call(["cmd", "/c", "title", MSG_FIRST, "&&"] + cmd,
                                      creationflags=0x00000010, cwd=root)     # CREATE_NEW_CONSOLE
            else:
                if sys.stderr is not None:
                    sys.stderr.write(MSG_FIRST + "\n")
                pip = subprocess.call(cmd, cwd=root)
    except OSError:
        message(MSG_VENV % target)
        return False
    if pip != 0:
        shutil.rmtree(target, ignore_errors=True)
        message(MSG_DOWNLOAD)
        return False
    with open(os.path.join(target, MARKER), "w", encoding="utf-8") as f:
        f.write(requirements_hash(root))
    return True


def ensure_venv(root: str) -> bool:
    return venv_ready(root) or make_venv(root)


def launch(argv, root: str | None = None) -> int:
    """Make sure the environment is ready, then run the window in it with the given arguments."""
    if sys.version_info < MIN_PYTHON and find_python() is None:
        message(MSG_PYTHON)
        return 1
    root = root or root_dir()
    if not ensure_venv(root):
        return 1
    if os.environ.get("NOVELGUI_PREPARE_ONLY") == "1":
        return 0
    cmd = [venv_python(root, windowed=True), "-m", "novelgui"] + list(argv)
    if IS_WINDOWS:
        try:
            subprocess.Popen(cmd, cwd=root, creationflags=0x00000008)      # DETACHED_PROCESS
        except OSError:
            message(MSG_VENV % venv_dir(root))
            return 1
        return 0
    os.chdir(root)
    os.execv(cmd[0], cmd)
    return 1
