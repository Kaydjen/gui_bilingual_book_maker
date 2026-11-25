"""The only module with operating-system specific calls (all guarded, no-ops off Windows)."""

from __future__ import annotations

import struct
import sys
import zlib

IS_WINDOWS = sys.platform == "win32"
# Virtual-key codes of Ctrl+<letter> shortcuts, the same on every keyboard layout.
KEYCODES = {86: "paste", 67: "copy", 88: "cut", 65: "all", 70: "find", 90: "undo"}


def enable_dpi() -> None:
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def dark_titlebar(win) -> None:
    """Dark caption colours (Windows 10/11)."""
    if not IS_WINDOWS:
        return
    try:
        from ctypes import byref, c_int, windll
        win.update_idletasks()
        hwnd = windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        for attr, val in ((20, 1), (19, 1), (35, 0x000000), (36, 0xDEDEDE), (34, 0x1A1A1A)):
            windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, byref(c_int(val)), 4)
    except Exception:
        pass


def default_data_dir():
    """The settings folder of the program (the one place that builds it is runtime/paths.py)."""
    from .runtime import paths
    return paths.default_settings_dir()


def write_png(path, w: int, h: int, rgb: bytes) -> None:
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def print_window(title: str, path) -> tuple[int, int]:
    """Save the window with exactly this title to a PNG with PrintWindow (never a screen capture).
    Returns (width, height); raises RuntimeError when the window is not found or off Windows."""
    if not IS_WINDOWS:
        raise RuntimeError("PrintWindow needs Windows")
    import ctypes
    from ctypes import wintypes
    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
    u32.FindWindowW.restype = wintypes.HWND
    u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u32.GetDC.restype = wintypes.HDC
    u32.GetDC.argtypes = [wintypes.HWND]
    u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    g32.CreateCompatibleDC.restype = wintypes.HDC
    g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    g32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    g32.SelectObject.restype = wintypes.HGDIOBJ
    g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g32.DeleteDC.argtypes = [wintypes.HDC]
    g32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                              ctypes.c_void_p, wintypes.UINT]

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    hwnd = u32.FindWindowW(None, title)
    if not hwnd:
        raise RuntimeError("window not found by title")
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    sdc = u32.GetDC(None)
    mdc = g32.CreateCompatibleDC(sdc)
    bmp = g32.CreateCompatibleBitmap(sdc, w, h)
    old = g32.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 2)
    bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = (ctypes.c_ubyte * (w * h * 4))()
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g32.SelectObject(mdc, old)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(None, sdc)
    bgra = bytes(buf)
    rgb = bytearray(w * h * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    write_png(path, w, h, bytes(rgb))
    return w, h


def window_handle(win) -> int:
    """The top-level window handle of a Tk window (0 off Windows)."""
    if not IS_WINDOWS:
        return 0
    try:
        from ctypes import windll
        win.update_idletasks()
        return int(windll.user32.GetParent(win.winfo_id()) or win.winfo_id())
    except Exception:
        return 0


def raise_window(hwnd: int) -> bool:
    """Bring the window with this handle to the front (restored when minimised). False when it is gone."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        from ctypes import windll
        u32 = windll.user32
        if not u32.IsWindow(hwnd):
            return False
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)         # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def open_folder(path) -> bool:
    """Show a folder in the file manager."""
    import os
    import subprocess
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
    import subprocess
    from pathlib import Path
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
