"""The frameless title bar of window_spec 9.10, the part QML talks to.

`FrameModel` is the object QML sees as `frame`. QML reports the layout of the header (`setRegions`: the strip height,
the rectangles that take clicks, the maximize button) and shows the pointer facts the native side reports (`maxHot`,
`edgeHot`). On Windows `platform.install_frame` adds the native event filter (winframe.py) that answers
WM_NCHITTEST from those regions; elsewhere `custom` stays false and the system frame is used as it is.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot


class FrameModel(QObject):
    customChanged = Signal()
    maxHotChanged = Signal()
    edgeHotChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._custom = False
        self._max_hot = False
        self._edge_hot = False
        self.caption_h = 0.0
        self.clients: list = []          # [x, y, w, h] in logical pixels, window coordinates
        self.max_rect: list = []         # the maximize button, [] while it is hidden
        self.edge = 3.0                  # the top edge that reveals the buttons (logical px)

    @Property(bool, notify=customChanged)
    def custom(self):
        return self._custom

    def set_custom(self, on: bool) -> None:
        if self._custom != on:
            self._custom = on
            self.customChanged.emit()

    @Property(bool, notify=maxHotChanged)
    def maxHot(self):
        return self._max_hot

    @Property(bool, notify=edgeHotChanged)
    def edgeHot(self):
        return self._edge_hot

    def set_max_hot(self, on: bool) -> None:
        if self._max_hot != on:
            self._max_hot = on
            self.maxHotChanged.emit()

    def set_edge_hot(self, on: bool) -> None:
        if self._edge_hot != on:
            self._edge_hot = on
            self.edgeHotChanged.emit()

    @Slot(float, "QVariantList", "QVariantList")
    def setRegions(self, caption_h, clients, max_rect):
        self.caption_h = float(caption_h)
        self.clients = [[float(v) for v in r] for r in clients]
        self.max_rect = [float(v) for v in max_rect]

    # ---- the answer to a hit test, in logical pixels relative to the window (pure; the filter calls it)
    def classify(self, x: float, y: float, w: float, h: float, maximized: bool, grip: float) -> str:
        """`topleft` ... `bottom` for the resize edges (not while maximized), `max`, `caption` or `client`."""
        if not maximized:
            left, right, top, bottom = x < grip, x >= w - grip, y < grip, y >= h - grip
            if top and left:
                return "topleft"
            if top and right:
                return "topright"
            if bottom and left:
                return "bottomleft"
            if bottom and right:
                return "bottomright"
            if left:
                return "left"
            if right:
                return "right"
            if top:
                return "top"
            if bottom:
                return "bottom"
        if y < self.caption_h:
            if self._inside(self.max_rect, x, y):
                return "max"
            if any(self._inside(r, x, y) for r in self.clients):
                return "client"
            return "caption"
        return "client"

    @staticmethod
    def _inside(r, x, y) -> bool:
        return len(r) == 4 and r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]
