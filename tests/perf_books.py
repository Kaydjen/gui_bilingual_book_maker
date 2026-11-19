"""Frames of the REAL chapter list (Books/ChapterList.qml over the BooksVM and its ChapterModel) of a 3000-chapter book while the
data lane does pure-Python work (run by test_window_perf).

usage: python tests/perf_books.py   ->  one JSON line {"idle": frames, "busy": frames, "work": loops, "rows": n}
Offscreen + software backend; nothing is shown. The book is scanned first (the list is full), then scrolled for 3 s, once idle and
once with a busy lane that breathes (`ctx.breathe()`), like every in-process lane loop of the window.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

SCROLL_MS = 3000
QML = b"""
import QtQuick
import Books
ChapterList { width: 800; height: 800; books: booksVm
  property alias running: anim.running
  NumberAnimation { id: anim; target: list; property: "contentY"; from: 0; to: 80000; duration: SCROLL_MS; running: false } }
""".replace(b"SCROLL_MS", str(SCROLL_MS).encode())


def busy_task(stop):
    def work(ctx):
        s = loops = 0
        while not stop.is_set():
            for i in range(2000):
                s += i * i % 7
            loops += 1
            ctx.breathe()
        return loops
    return work


def main():
    app = QGuiApplication([])
    from tests import shellfactory
    objs, extras = shellfactory.make({"library": "ready", "series": [
        {"name": "Big", "books": [{"stem": "B", "chapters": 3000, "paras": 1}]}]})
    books = objs["booksVm"]
    view = QQuickView()
    view.engine().addImportPath(str(Path(__file__).resolve().parent.parent / "novelgui" / "qml"))
    for k, v in objs.items():
        view.rootContext().setContextProperty(k, v)
    qml = Path(os.environ.get("TEMP", ".")) / ("perf_books_%d.qml" % os.getpid())
    qml.write_bytes(QML)
    view.setSource(QUrl.fromLocalFile(str(qml)))
    if view.errors():
        print(json.dumps({"error": [e.toString() for e in view.errors()]}))
        return 2
    view.resize(800, 800)
    view.show()
    end = time.monotonic() + 180
    while time.monotonic() < end and not (books.chapter_model.rowCount() > 2900 and not books.session.scanning):
        QCoreApplication.processEvents()
        time.sleep(0.01)
    books.chapter_model.flush()
    frames = []
    view.frameSwapped.connect(lambda: frames.append(time.perf_counter()))
    root = view.rootObject()
    result = {"rows": books.chapter_model.rowCount()}
    stop = threading.Event()
    loops = []
    ln = None

    def run(name, after):
        frames.clear()
        root.setProperty("running", False)
        root.setProperty("running", True)
        QTimer.singleShot(SCROLL_MS + 200, lambda: (result.__setitem__(name, len(frames)), after()))

    def busy():
        from novelgui.lanes import Lanes
        nonlocal ln
        ln = Lanes()
        ln.submit(busy_task(stop), on_result=loops.append, lane="data")
        QTimer.singleShot(150, lambda: run("busy", finish))

    def finish():
        stop.set()
        QTimer.singleShot(300, app.quit)

    QTimer.singleShot(500, lambda: run("idle", busy))
    app.exec()
    if ln is not None:
        ln.close()
    extras["__close"]()
    try:
        qml.unlink()
    except OSError:
        pass
    result["work"] = loops[0] if loops else -1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
