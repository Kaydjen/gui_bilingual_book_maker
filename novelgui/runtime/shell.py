"""The Python object the QML shell sees as `shell`: start-up facts, the second-start banner, request signals."""

from __future__ import annotations

import os

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QWindow
from PySide6.QtQuick import QQuickWindow  # noqa: F401  (the engine then hands out QQuickWindow objects)

from . import log

BANNER_TEXT = "The app is already open. It runs in one window, so this one was brought back."
BANNER_MS = 5000
ENV_TEST_GRAB = "NOVELGUI_TEST_GRAB_RAISE"


class Shell(QObject):
    bannerVisibleChanged = Signal()
    addBooksRequested = Signal(list)
    toastRequested = Signal(str, str, str)
    exitRequested = Signal(int)

    def __init__(self, previous_unclean=False, graphics_fallback=False, parent=None):
        super().__init__(parent)
        self.window = None
        self._previous_unclean = bool(previous_unclean)
        self._graphics_fallback = bool(graphics_fallback)
        self._banner = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(BANNER_MS)
        self._timer.timeout.connect(self._hide_banner)

    @Property(str, constant=True)
    def bannerText(self):
        return BANNER_TEXT

    @Property(bool, notify=bannerVisibleChanged)
    def bannerVisible(self):
        return self._banner

    @Property(bool, constant=True)
    def previousUnclean(self):
        return self._previous_unclean

    @Property(bool, constant=True)
    def graphicsFallback(self):
        return self._graphics_fallback

    def _set_banner(self, on: bool) -> None:
        if self._banner != on:
            self._banner = on
            self.bannerVisibleChanged.emit()

    def _hide_banner(self) -> None:
        self._set_banner(False)

    def bring_to_front(self) -> None:
        w = self.window
        if w is None:
            return
        if w.visibility() == QWindow.Visibility.Minimized:
            w.showNormal()
        else:
            w.show()
        w.raise_()
        w.requestActivate()

    def handle_raise(self, paths: list) -> None:
        """A second start asked for this window: bring it back, show the banner, pass the books on."""
        self.bring_to_front()
        self._set_banner(True)
        self._timer.start()
        banner = self.window.findChild(QObject, "banner") if self.window is not None else None
        shown = banner.property("text") if banner is not None else ""
        log.logger.info("raise request: paths=%s banner=%r", list(paths), shown)
        if paths:
            self.addBooksRequested.emit(list(paths))
        grab = os.environ.get(ENV_TEST_GRAB)
        if grab and self.window is not None:
            QTimer.singleShot(700, lambda: self._test_grab(grab))

    def _test_grab(self, path: str) -> None:
        """Test hook: a picture of this window only, and whether it is the active one."""
        w = self.window
        w.grabWindow().save(path)
        log.logger.info("grabbed %s active=%s visibility=%s", path, w.isActive(), w.visibility().name)

    @Slot(str, str, str)
    def request_toast(self, title, text, route):
        self.toastRequested.emit(title, text, route)
