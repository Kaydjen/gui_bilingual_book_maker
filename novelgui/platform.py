"""The only module with operating-system specific calls (all guarded, no-ops off Windows)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
APP_DIR = "novelgui"

_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_CONSOLE = 0x00000010
_DETACHED_PROCESS = 0x00000008


def config_base() -> Path:
    """The per-user folder for settings (Windows %APPDATA%, elsewhere $XDG_CONFIG_HOME or ~/.config)."""
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def local_data_base() -> Path:
    """The per-user folder for local data (Windows %LOCALAPPDATA%, elsewhere $XDG_DATA_HOME or ~/.local/share)."""
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def no_window() -> dict:
    """Extra `subprocess` arguments for a child process that must not open a console window ({} elsewhere)."""
    return {"creationflags": _CREATE_NO_WINDOW} if IS_WINDOWS else {}


def new_console() -> dict:
    """Extra `subprocess` arguments for a child process that shows its own console ({} elsewhere)."""
    return {"creationflags": _CREATE_NEW_CONSOLE} if IS_WINDOWS else {}


def detached() -> dict:
    """Extra `subprocess` arguments for a child process that lives on its own after the parent ends ({} elsewhere)."""
    return {"creationflags": _DETACHED_PROCESS} if IS_WINDOWS else {}


def venv_python(venv: str, windowed: bool = False) -> str:
    """The interpreter inside a virtual environment folder; `windowed` picks pythonw on Windows (no console)."""
    if IS_WINDOWS:
        return os.path.join(venv, "Scripts", "pythonw.exe" if windowed else "python.exe")
    return os.path.join(venv, "bin", "python")


def console_python(exe: str) -> str:
    """The console twin of a windowed interpreter (pythonw -> python) when it exists, else the same path."""
    if IS_WINDOWS and exe.lower().endswith("pythonw.exe"):
        console = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(console):
            return console
    return exe


def windowed_python(exe: str) -> str:
    """The windowed twin of a console interpreter (python -> pythonw) when it exists, else the same path."""
    if IS_WINDOWS and os.path.basename(exe).lower() == "python.exe":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(w):
            return w
    return exe


def pid_alive(pid: int) -> bool:
    """True when a process with this id is running (or exists but is not ours to ask)."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            k32.CloseHandle.argtypes = (wintypes.HANDLE,)
            h = k32.OpenProcess(0x00100000 | 0x1000, False, pid)     # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
            if not h:
                return ctypes.get_last_error() == 5                  # access denied: it exists
            try:
                return k32.WaitForSingleObject(h, 0) == 0x102        # WAIT_TIMEOUT: still running
            finally:
                k32.CloseHandle(h)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def open_folder(path) -> bool:
    """Show a folder in the file manager."""
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False


def reveal_file(path) -> bool:
    """Show a file in the file manager with the file selected (Linux: its folder)."""
    p = Path(path)
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,%s" % p])
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
            return True
    except Exception:
        return False
    return open_folder(p.parent)


def keep_awake(on: bool) -> None:
    """Ask Windows not to sleep while a translation runs (cleared with on=False). No-op elsewhere.
    The request belongs to the calling thread, so call it from the window's thread both times."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)  # ES_CONTINUOUS [| ES_SYSTEM_REQUIRED]
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def allow_set_foreground(pid: int) -> None:
    """Let the process with this id take the foreground (a second start hands it to the first window)."""
    if not IS_WINDOWS or not pid:
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
    except Exception:
        pass


def flash_window(hwnd: int) -> bool:
    """Flash the taskbar button until the window is active (FlashWindowEx). False off Windows or on failure."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x3 | 0xC, 0, 0)   # FLASHW_ALL | FLASHW_TIMERNOFG
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        return True
    except Exception:
        return False


def message_box(text: str, title: str = "Novel") -> bool:
    """A modal error box on Windows. False elsewhere (the caller falls back to stderr)."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
        return True
    except Exception:
        return False


def install_frame(app, window, model):
    """The frameless title bar (window_spec 9.10): on Windows the native event filter of runtime/winframe.py is
    installed and `model.custom` turns true; the returned object must be kept alive. Elsewhere (Linux: the native
    frame) nothing happens and None comes back."""
    if not IS_WINDOWS:
        return None
    try:
        if app.platformName() != "windows":          # offscreen and other Qt platforms have no native window
            return None
        from .runtime import winframe
        flt = winframe.FrameFilter(window, model)
        app.installNativeEventFilter(flt)
        model.set_custom(True)
        flt.refresh_frame()
        return flt
    except Exception:
        return None
