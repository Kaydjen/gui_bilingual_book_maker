"""The panel for a start that failed: `Fatal.qml` on its own engine, never an empty window."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, QPointF, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # noqa: F401  (makes the engine hand out QQuickWindow objects)

QML_DIR = Path(__file__).resolve().parent.parent / "qml"
ENV_TEST_GRAB = "NOVELGUI_TEST_GRAB"        # test hook: write a PNG of the panel and a JSON report, then quit


class FatalInfo(QObject):
    def __init__(self, details: str, log_path, parent=None):
        super().__init__(parent)
        self.details = details
        self.log_path = Path(log_path)
        lines = [line.strip() for line in details.strip().splitlines() if line.strip()]
        self._first = lines[-1] if lines else "Unknown error"

    @Property(str, constant=True)
    def firstLine(self):
        return self._first

    @Slot()
    def copyDetails(self):
        QGuiApplication.clipboard().setText(self.details)

    @Slot()
    def openLog(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path)))

    @Slot()
    def quit(self):
        QGuiApplication.exit(1)


def show(details: str, log_path) -> int:
    """Run the panel until the user quits. The application object must exist. Returns the exit code."""
    info = FatalInfo(details, log_path)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("fatal", info)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Fatal.qml")))
    roots = engine.rootObjects()
    if not roots:
        return 1
    window = roots[0]
    window.show()
    grab = os.environ.get(ENV_TEST_GRAB)
    if grab:
        QTimer.singleShot(400, lambda: _test_grab(window, grab))
    code = QGuiApplication.exec()
    del engine
    return code if code else 1


def _test_grab(window, path: str) -> None:
    names = {}
    rects = {}
    for name in ("quitButton", "copyButton", "logButton", "fatalHeading", "fatalReason"):
        item = window.findChild(QObject, name)
        names[name] = None if item is None else str(item.property("text"))
        if item is not None:
            pos = item.mapToScene(QPointF(0, 0))
            rects[name] = [pos.x(), pos.y(), item.property("width"), item.property("height")]
    names["rects"] = rects
    try:
        window.grabWindow().save(path)
        Path(path).with_suffix(".json").write_text(json.dumps(names), encoding="utf-8")
    finally:
        QGuiApplication.exit(1)
