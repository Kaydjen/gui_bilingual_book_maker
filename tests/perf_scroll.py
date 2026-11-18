"""Frames of a scrolling 3000-row list while the data lane does pure-Python work (run by test_window_perf).

usage: python tests/perf_scroll.py   ->  one JSON line {"idle": frames, "busy": frames, "work": loops, ...}
Offscreen + software backend; nothing is shown. The list is a ListView over a Python QAbstractListModel (every
delegate reads its roles through Python), scrolled by a 3 s animation, once idle and once with a busy lane.
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

from novelgui import lanes  # noqa: E402

N = 3000
BREATHE = os.environ.get("PERF_NO_BREATH") != "1"     # "1" = the control run: the same work without breaths
SCROLL_MS = 3000
QML = b"""
import QtQuick
Rectangle { width: 600; height: 800; color: "#111"
  property alias running: anim.running
  ListView { id: lv; objectName: "list"; anchors.fill: parent; model: rows; clip: true; reuseItems: true
    delegate: Rectangle { required property int index; required property string title
      required property int done; required property int total
      width: lv.width; height: 28; color: index % 2 ? "#181818" : "#1c1c1c"
      Text { x: 8; text: title; color: "#ddd"; font.pixelSize: 14 }
      Rectangle { x: 400; width: 150 * done / total; height: 6; y: 11; color: "#c33" } } }
  NumberAnimation { id: anim; target: lv; property: "contentY"; from: 0; to: 70000; duration: SCROLL_MS; running: false }
}""".replace(b"SCROLL_MS", str(SCROLL_MS).encode())


class Rows(QAbstractListModel):
    Title, Done, Total = Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3

    def __init__(self):
        super().__init__()
        self.titles = ["Chapter %d: some title of the chapter" % i for i in range(N)]
        self.done = [i % 50 for i in range(N)]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else N

    def roleNames(self):
        return {self.Title: b"title", self.Done: b"done", self.Total: b"total"}

    def data(self, idx, role=Qt.DisplayRole):
        r = idx.row()
        if role == self.Title:
            return self.titles[r]
        if role == self.Done:
            return self.done[r]
        if role == self.Total:
            return 50
        return None


def busy_task(stop):
    def work(ctx):
        s = loops = 0
        while not stop.is_set():
            for i in range(2000):           # pure Python, like term matching or arranging 20 000 rows
                s += i * i % 7
            loops += 1
            if BREATHE:
                ctx.breathe()
        return loops
    return work


def main():
    app = QGuiApplication([])
    ln = lanes.Lanes()
    switch = os.environ.get("PERF_SWITCH")
    if switch:
        sys.setswitchinterval(float(switch))      # e.g. 0.005: the breaths alone must carry the window
    rows = Rows()
    view = QQuickView()
    view.rootContext().setContextProperty("rows", rows)
    qml = Path(tempfile.gettempdir()) / ("perf_scroll_%d.qml" % os.getpid())
    qml.write_bytes(QML)
    view.setSource(QUrl.fromLocalFile(str(qml)))
    if view.errors():
        print(json.dumps({"error": [e.toString() for e in view.errors()]}))
        return 2
    view.resize(600, 800)
    view.show()
    frames = []
    view.frameSwapped.connect(lambda: frames.append(time.perf_counter()))
    root = view.rootObject()
    result = {}
    stop = threading.Event()
    loops = []

    def run(name, after):
        frames.clear()
        root.setProperty("running", True)           # the animation starts again from the top

        def end():
            result[name] = len(frames)
            after()
        QTimer.singleShot(SCROLL_MS + 200, end)

    def busy():
        ln.submit(busy_task(stop), on_result=loops.append, lane="data")
        QTimer.singleShot(150, lambda: run("busy", finish))

    def finish():
        stop.set()
        QTimer.singleShot(300, app.quit)

    QTimer.singleShot(500, lambda: run("idle", busy))
    app.exec()
    ln.close()
    qml.unlink()
    result["work"] = loops[0] if loops else -1
    result["switch"] = sys.getswitchinterval()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
