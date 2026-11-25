"""Windows only: the native event filter of the frameless title bar (window_spec 9.10, probe .ai/notes/qml_probes.md (a)).

The window keeps WS_CAPTION / WS_THICKFRAME / the maximize box (so snap, Win+arrows, Alt+Tab, the shadow and the
Windows 11 snap-layout flyout stay); WM_NCCALCSIZE makes the client area the whole window, WM_NCHITTEST answers
from the regions QML reports: resize edges, the caption (empty header space), HTMAXBUTTON on the drawn maximize
button, client elsewhere. Hit tests arrive on the GUI thread and are answered in microseconds; a Python thread that
never lets go would delay them, which is why the runtime sets a 0.5 ms switch interval and every lane breathes.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

WM_NCCALCSIZE, WM_NCHITTEST, WM_NCMOUSELEAVE, WM_MOUSELEAVE = 0x0083, 0x0084, 0x02A2, 0x02A3
WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCLBUTTONDBLCLK = 0x00A1, 0x00A2, 0x00A3
WM_SYSCOMMAND, SC_MAXIMIZE, SC_RESTORE = 0x0112, 0xF030, 0xF120
HT = {"client": 1, "caption": 2, "max": 9, "left": 10, "right": 11, "top": 12, "topleft": 13, "topright": 14,
      "bottom": 15, "bottomleft": 16, "bottomright": 17}
GRIP = 6                                    # logical px of the resize edge

u32 = ctypes.WinDLL("user32", use_last_error=True)
u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]


class _NCP(ctypes.Structure):
    _fields_ = [("r0", RECT), ("r1", RECT), ("r2", RECT), ("pos", ctypes.c_void_p)]


class FrameFilter(QAbstractNativeEventFilter):
    def __init__(self, window, model):
        super().__init__()
        self.window = window
        self.model = model
        self.hwnd = int(window.winId())
        self.calls = 0

    def refresh_frame(self) -> None:
        u32.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, 0x0027)     # FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER

    def nativeEventFilter(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.hWnd != self.hwnd:
                return False, 0
            if msg.message == WM_NCCALCSIZE and msg.wParam:
                if u32.IsZoomed(self.hwnd):                    # maximized: the frame overhangs, keep to the work area
                    p = _NCP.from_address(msg.lParam)
                    f = u32.GetSystemMetrics(32) + u32.GetSystemMetrics(92)     # SIZEFRAME + PADDEDBORDER
                    p.r0.l += f
                    p.r0.t += f
                    p.r0.r -= f
                    p.r0.b -= f
                return True, 0
            if msg.message == WM_NCHITTEST:
                return True, self._hit(msg)
            # HTMAXBUTTON turns clicks on the drawn button into non-client clicks that QML never sees, and
            # DefWindowProc would run its classic button tracking: press and release are handled here.
            if msg.message in (WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK) and msg.wParam == HT["max"]:
                return True, 0
            if msg.message == WM_NCLBUTTONUP and msg.wParam == HT["max"]:
                # posted, as DefWindowProc does for its own button: the system command keeps the animation and snap state
                u32.PostMessageW(self.hwnd, WM_SYSCOMMAND, SC_RESTORE if u32.IsZoomed(self.hwnd) else SC_MAXIMIZE, 0)
                return True, 0
            if msg.message in (WM_NCMOUSELEAVE, WM_MOUSELEAVE):
                self.model.set_max_hot(False)
                self.model.set_edge_hot(False)
        except Exception:
            return False, 0
        return False, 0

    def _hit(self, msg) -> int:
        self.calls += 1
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        r = RECT()
        u32.GetWindowRect(self.hwnd, ctypes.byref(r))
        k = float(self.window.devicePixelRatio()) or 1.0
        zoomed = bool(u32.IsZoomed(self.hwnd))
        where = self.model.classify((x - r.l) / k, (y - r.t) / k, (r.r - r.l) / k, (r.b - r.t) / k, zoomed, GRIP)
        self.model.set_max_hot(where == "max")
        self.model.set_edge_hot(where in ("top", "topleft", "topright") or (zoomed and (y - r.t) / k < self.model.edge))
        return HT[where]
