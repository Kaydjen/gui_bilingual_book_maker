"""Frames of the REAL Terms table (Terms/TermsScreen.qml over the TermsVM and its TermModel) with 20,000 terms while the data lane does
pure-Python work (run by test_window_perf).

usage: python tests/perf_terms.py   ->  one JSON line {"idle": frames, "busy": frames, "work": loops, "rows": n, "reset_ms": ms (with the table attached)}
Offscreen + software backend; nothing is shown. The terms are written into a small library first; the table is scrolled for 3 s, once
idle and once with a busy lane that breathes (`ctx.breathe()`), like every in-process lane loop of the window.
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

from PySide6.QtCore import QCoreApplication, QPropertyAnimation, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickView  # noqa: E402

SCROLL_MS = 3000
ROWS = 20000
QML = b"""
import QtQuick
import Terms
TermsScreen { width: 1000; height: 800; terms: termsVm; app: appVm }
"""


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
    terms = [{"src": "Name %d" % i, "tr": "Имя %d" % i, "type": "character", "gender": "male", "count": 5 + i % 90,
              "seen": [1 + i % 9], "status": "new"} for i in range(ROWS)]
    objs, extras = shellfactory.make({"library": "ready", "screen": "terms", "series": [
        {"name": "Big", "books": [{"stem": "B", "chapters": 12, "paras": 1}], "terms": terms}]})
    vm = objs["termsVm"]
    view = QQuickView()
    view.engine().addImportPath(str(Path(__file__).resolve().parent.parent / "novelgui" / "qml"))
    for k, v in objs.items():
        view.rootContext().setContextProperty(k, v)
    qml = Path(os.environ.get("TEMP", ".")) / ("perf_terms_%d.qml" % os.getpid())
    qml.write_bytes(QML)
    view.setSource(QUrl.fromLocalFile(str(qml)))
    if view.errors():
        print(json.dumps({"error": [e.toString() for e in view.errors()]}))
        return 2
    view.resize(1000, 800)
    view.show()
    end = time.monotonic() + 120
    while time.monotonic() < end and not (vm.model.rowCount() >= ROWS - 5 and not vm._scanning):
        QCoreApplication.processEvents()
        time.sleep(0.01)
    rows = list(vm.model.rows)
    t0 = time.perf_counter()
    vm.model.set_rows(list(rows))
    reset_ms = (time.perf_counter() - t0) * 1000
    vm._push_selection()
    QCoreApplication.processEvents()
    frames = []
    view.frameSwapped.connect(lambda: frames.append(time.perf_counter()))
    listview = view.rootObject().findChild(QQuickItem, "termList")
    result = {"rows": vm.model.rowCount(), "reset_ms": round(reset_ms, 2)}
    stop = threading.Event()
    loops = []
    holder = {}

    def run(name, after):
        frames.clear()
        anim = QPropertyAnimation(listview, b"contentY")
        anim.setDuration(SCROLL_MS)
        anim.setStartValue(0)
        anim.setEndValue(60000)
        holder["anim"] = anim
        anim.start()
        QTimer.singleShot(SCROLL_MS + 200, lambda: (result.__setitem__(name, len(frames)), after()))

    def busy():
        from novelgui.lanes import Lanes
        holder["lanes"] = Lanes()
        holder["lanes"].submit(busy_task(stop), on_result=loops.append, lane="data")
        QTimer.singleShot(150, lambda: run("busy", finish))

    def finish():
        stop.set()
        QTimer.singleShot(300, app.quit)

    QTimer.singleShot(500, lambda: run("idle", busy))
    app.exec()
    if "lanes" in holder:
        holder["lanes"].close()
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
