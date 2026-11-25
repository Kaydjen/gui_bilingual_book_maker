"""Harness for QML scenes: `scenario(name, data=..., scale=...)` loads tests/qmlscenes/<name>.qml offscreen with the
software scene graph and hands back what a test needs: PNG shots, a structural dump of every item that has an objectName,
the running infinite animations, the QML warnings and Python exceptions (any of them fails the scenario).

Every scenario runs in a child process (`python -m tests.qmlharness ...`) because QT_SCALE_FACTOR must be set before the
application exists and because a crash of one scene must not take the test run with it. Nothing is shown on the desktop:
QT_QPA_PLATFORM=offscreen. Shots go to NOVELGUI_SHOTS (default: the temp dir), never into the repository.

Action `until` ({"op": "until", "name", "prop", "value", "ms"}) waits for a property of a named item to take a value.

Scene contract: the scene is a QML file whose root is an Item; it sees `fake` (the dict given as `data`) and `rec`
(`rec.record(name, value)` stores an event the test can read back in `Result.events`).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCENES = Path(__file__).resolve().parent / "qmlscenes"
QML_ROOT = REPO / "novelgui" / "qml"
ENV_SHOTS = "NOVELGUI_SHOTS"

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


def qt_python() -> str:
    """The interpreter that runs the scenes: this one, when it has PySide6 (the tests skip otherwise)."""
    return sys.executable if HAVE_QT else ""


def have_qt() -> bool:
    return HAVE_QT


def shots_dir() -> Path:
    base = os.environ.get(ENV_SHOTS) or tempfile.gettempdir()
    path = Path(base) / ("%s-qml" % datetime.date.today().isoformat())
    path.mkdir(parents=True, exist_ok=True)
    return path


class HarnessError(AssertionError):
    pass


class Result:
    def __init__(self, raw: dict, out: Path):
        self.raw = raw
        self.scene = raw["scene"]
        self.scale = raw["scale"]
        self.warnings = raw["warnings"]
        self.errors = raw["errors"]
        self.items = raw["items"]
        self.animations = raw["animations"]
        self.events = raw["events"]
        self.cpu = raw.get("cpu")
        self.shots = {k: out / v for k, v in raw["shots"].items()}
        self.after = raw.get("after", {})        # item dumps taken after each action that asked for one

    def item(self, name: str) -> dict:
        try:
            return self.items[name]
        except KeyError:
            raise KeyError("no item %r in scene %s (have %d named items)" % (name, self.scene, len(self.items))) from None

    def has(self, name: str) -> bool:
        return name in self.items

    def rect(self, name: str, scale: bool = True) -> tuple:
        """(x, y, w, h) of an item in window pixels (device pixels of the shot when `scale`)."""
        it = self.item(name)
        k = self.scale if scale else 1.0
        return (round(it["x"] * k), round(it["y"] * k), round(it["w"] * k), round(it["h"] * k))

    def image(self, name: str = "main"):
        from PySide6.QtGui import QImage
        img = QImage(str(self.shots[name]))
        if img.isNull():
            raise HarnessError("shot %s unreadable" % self.shots[name])
        return img

    def pixel(self, x: float, y: float, name: str = "main") -> tuple:
        """RGB of the shot at logical (x, y)."""
        img = self.image(name)
        c = img.pixelColor(int(round(x * self.scale)), int(round(y * self.scale)))
        return (c.red(), c.green(), c.blue())

    @property
    def ambient(self) -> int:
        return len(self.animations)


def _key(name, data, scale, size, actions, cpu, vm) -> str:
    blob = json.dumps([name, data, scale, size, actions, cpu, vm], sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()[:10]


_CACHE: dict = {}


def scenario(name: str, data: dict | None = None, scale: float = 1.0, size=(1040, 720), actions=None, cpu=None,
             tag: str = "", timeout: int = 90, vm: str = "") -> Result:
    """Run tests/qmlscenes/<name>.qml. Raises HarnessError on any QML warning, Python exception or crash."""
    py = qt_python()
    if not py:
        raise HarnessError("PySide6 is not available")
    data = data or {}
    key = _key(name, data, scale, list(size), actions, cpu, vm)
    if key in _CACHE:
        return _CACHE[key]
    out = shots_dir()
    stem = "%s%s_%d" % (name, ("_" + tag) if tag else "", round(scale * 100))
    req = {"scene": name, "data": data, "scale": scale, "size": list(size), "actions": actions or [], "cpu": cpu,
           "out": str(out), "stem": stem, "vm": vm}
    env = dict(os.environ)
    env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QPA_FONTDIR=r"C:\Windows\Fonts",
               PYTHONUTF8="1", QT_QUICK_CONTROLS_STYLE="Basic")
    if os.name != "nt":
        env.pop("QT_QPA_FONTDIR", None)
    env["QT_SCALE_FACTOR"] = str(scale)
    env.pop("QT_ENABLE_HIGHDPI_SCALING", None)
    result_path = out / (stem + ".json")
    if result_path.exists():
        result_path.unlink()
    proc = subprocess.run([py, "-m", "tests.qmlharness", "--child", json.dumps(req)], cwd=str(REPO), env={**env, "PYTHONPATH": str(REPO)},
                          capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    if not result_path.exists():
        raise HarnessError("scene %s produced no result (exit %s)\n%s\n%s" % (name, proc.returncode, proc.stdout[-1500:], proc.stderr[-1500:]))
    res = Result(json.loads(result_path.read_text(encoding="utf-8")), out)
    problems = res.warnings + res.errors
    if problems or proc.returncode != 0:
        raise HarnessError("scene %s: %d warning(s) / error(s), exit %s:\n%s" % (name, len(problems), proc.returncode, "\n".join(problems[:12])))
    _CACHE[key] = res
    return res


# ---------------------------------------------------------------- pixel helpers (parent side)

def is_red(c: tuple) -> bool:
    r, g, b = c
    return r >= 120 and r - max(g, b) >= 70


def colour_cast(c: tuple) -> int:
    return max(c) - min(c)


def count_red(img, rect=None) -> int:
    """Pixels of the one accent red (anti-aliased edges included) in the image or in rect (x, y, w, h)."""
    x0, y0, w, h = rect if rect else (0, 0, img.width(), img.height())
    n = 0
    for y in range(max(0, y0), min(img.height(), y0 + h)):
        for x in range(max(0, x0), min(img.width(), x0 + w)):
            c = img.pixelColor(x, y)
            if is_red((c.red(), c.green(), c.blue())):
                n += 1
    return n


def stray_colours(img, tolerance: int = 24) -> int:
    """Pixels that carry a colour cast but are not a shade of red: the window is black + one red, nothing else."""
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            if max(r, g, b) - min(r, g, b) > tolerance and not (r >= max(g, b)):
                n += 1
    return n


def brightest(img, rect) -> tuple:
    """RGB of the brightest pixel of a rect (x, y, w, h): the solid core of a glyph stem."""
    x0, y0, w, h = rect
    best, bl = (0, 0, 0), -1
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            c = img.pixelColor(x, y)
            lum = c.red() + c.green() + c.blue()
            if lum > bl:
                best, bl = (c.red(), c.green(), c.blue()), lum
    return best


# ---------------------------------------------------------------- child side

def _child(req: dict) -> int:
    import traceback
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer, QUrl, Slot, qInstallMessageHandler, QtMsgType
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    warnings: list = []
    errors: list = []
    events: list = []

    def handler(mode, ctx, message):
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            warnings.append("%s (%s:%s)" % (message, (ctx.file or "").replace("\\", "/").rsplit("/", 1)[-1], ctx.line))

    qInstallMessageHandler(handler)

    def hook(tp, val, tb):
        errors.append("".join(traceback.format_exception(tp, val, tb)))

    sys.excepthook = hook

    class Rec(QObject):
        @Slot(str, "QVariant")
        def record(self, name, value):
            events.append([name, value])

    app = QGuiApplication(["harness"])
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_ROOT))
    rec = Rec()
    ctx = engine.rootContext()
    vmobjs: dict = {}
    extras: dict = {}
    if req.get("vm"):
        import importlib
        mod, _, fn = req["vm"].partition(":")
        vmobjs, extras = getattr(importlib.import_module(mod), fn)(req["data"])
        for k, v in vmobjs.items():
            ctx.setContextProperty(k, v)
    ctx.setContextProperty("fake", req["data"])
    ctx.setContextProperty("rec", rec)
    ctx.setContextProperty("harnessScene", QUrl.fromLocalFile(str(SCENES / (req["scene"] + ".qml"))).toString())
    engine.load(QUrl.fromLocalFile(str(SCENES / "_Frame.qml")))
    if not engine.rootObjects():
        errors.append("the frame window did not load")
        return _finish(req, warnings, errors, events, {}, {}, [], None)
    view = engine.rootObjects()[0]
    w, h = req["size"]
    view.setWidth(w)
    view.setHeight(h)
    view.show()
    root = view.contentItem()

    def children(o):
        kids = list(o.children())
        if isinstance(o, QQuickItem):
            kids += [c for c in o.childItems() if c not in kids]
        return kids

    def walk(o):
        stack = [o]
        seen = set()
        keep = []                       # wrappers stay alive so id() is unique for the walk
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            keep.append(cur)
            yield cur
            stack.extend(children(cur))

    def val(v):
        if hasattr(v, "name") and callable(v.name) and hasattr(v, "red"):
            return v.name()
        if isinstance(v, (str, int, float, bool)) or v is None:
            return v
        return str(v)

    def dump():
        items = {}
        for o in walk(root):
            nm = o.objectName()
            if not nm:
                continue
            d = {}
            if isinstance(o, QQuickItem):
                p = o.mapToScene(QPointF(0, 0))
                d.update(x=p.x(), y=p.y(), w=o.width(), h=o.height(), visible=o.isVisible(), opacity=o.opacity())
            for prop in ("text", "color", "radius", "running", "enabled", "currentIndex", "value", "selected", "current",
                         "contentY", "contentHeight", "count", "kind", "activeFocus", "live", "checked", "settled", "fraction", "auto",
                         "cursorPosition", "plain", "rich", "selectedText"):
                v = o.property(prop)
                if v is not None:
                    d[prop] = val(v)
            items[nm] = d
        return items

    def infinite():
        out = []
        for o in walk(root):
            if o.property("running") is True and o.property("loops") == -1:
                out.append("%s#%s" % (o.metaObject().className(), o.objectName()))
        return out

    def find(name):
        for o in walk(root):
            if o.objectName() == name:
                return o
        raise KeyError(name)

    def center(name):
        o = find(name)
        p = o.mapToScene(QPointF(o.width() / 2, o.height() / 2))
        return QPoint(int(round(p.x())), int(round(p.y())))

    def spin(ms, step=0.01):
        end = time.perf_counter() + ms / 1000.0
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(step)

    shots: dict = {}
    after: dict = {}

    def shoot(name):
        img = view.grabWindow()
        fn = "%s_%s.png" % (req["stem"], name)
        img.save(str(Path(req["out"]) / fn))
        shots[name] = fn

    mods = {"ctrl": Qt.ControlModifier, "shift": Qt.ShiftModifier, "": Qt.NoModifier}
    keys = {n: getattr(Qt, "Key_" + n) for n in ("Escape", "Return", "Tab", "Down", "Up", "Space", "Home", "End", "A", "Delete", "F2", "1", "2", "3", "4")}

    dragging: dict = {}

    def drag(op, a):
        """A file drag over the window, delivered as Qt's own drag events (what the platform plugin hands over after the OS
        said `drag over` / `drop`): urls come from the extras function `a["from"]`."""
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
        if op == "dragEnter":
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(p) for p in extras[a["from"]]()])
            dragging["mime"] = mime
        pos = QPoint(a.get("x", 300), a.get("y", 300))
        args = (pos, Qt.CopyAction, dragging.get("mime"), Qt.LeftButton, Qt.NoModifier)
        if op == "dragLeave":
            QGuiApplication.sendEvent(view, QDragLeaveEvent())
            return
        cls = {"dragEnter": QDragEnterEvent, "dragMove": QDragMoveEvent, "drop": QDropEvent}[op]
        ev = cls(pos if op != "drop" else QPointF(pos), *args[1:]) if op == "drop" else cls(*args)
        QGuiApplication.sendEvent(view, ev)
        events.append([op + "Accepted", ev.isAccepted()])

    def act(a):
        op = a["op"]
        if op == "wait":
            spin(a["ms"])
        elif op == "until":
            # wait for a real condition instead of a time: the item's property equals the value (or `ms` pass, default 8 s;
            # the test then asserts what it needs and fails on its own terms)
            end = time.perf_counter() + a.get("ms", 8000) / 1000.0
            while time.perf_counter() < end and find(a["name"]).property(a["prop"]) != a["value"]:
                spin(30)
        elif op == "click":
            QTest.mouseClick(view, Qt.RightButton if a.get("button") == "right" else Qt.LeftButton, mods[a.get("mod", "")],
                             center(a["name"]) + QPoint(a.get("dx", 0), a.get("dy", 0)))
        elif op == "dclick":
            QTest.mouseDClick(view, Qt.LeftButton, mods[a.get("mod", "")], center(a["name"]))
        elif op == "clickAt":
            QTest.mouseClick(view, Qt.RightButton if a.get("button") == "right" else Qt.LeftButton, mods[a.get("mod", "")],
                             QPoint(a["x"], a["y"]))
        elif op == "press":
            QTest.mousePress(view, Qt.LeftButton, mods[a.get("mod", "")], center(a["name"]) if "name" in a else QPoint(a["x"], a["y"]))
        elif op == "moveTo":
            QTest.mouseMove(view, center(a["name"]) if "name" in a else QPoint(a["x"], a["y"]))
        elif op == "release":
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, center(a["name"]) if "name" in a else QPoint(a["x"], a["y"]))
        elif op == "wheel":
            from PySide6.QtGui import QWheelEvent
            pos = QPointF(center(a["name"]))
            ev = QWheelEvent(pos, QPointF(view.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, a["dy"]),
                             Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            QGuiApplication.sendEvent(view, ev)
        elif op in ("midPress", "midMove", "midRelease"):
            pos = center(a["name"]) + QPoint(0, a.get("dy", 0))
            if op == "midPress":
                QTest.mousePress(view, Qt.MiddleButton, Qt.NoModifier, pos)
            elif op == "midMove":
                QTest.mouseMove(view, pos)
            else:
                QTest.mouseRelease(view, Qt.MiddleButton, Qt.NoModifier, pos)
        elif op == "key":
            QTest.keyClick(view, keys[a["key"]], mods[a.get("mod", "")])
        elif op == "type":
            for ch in a["text"]:
                key = {" ": Qt.Key_Space, "-": Qt.Key_Minus, ".": Qt.Key_Period}.get(ch) or getattr(Qt, "Key_" + ch.upper())
                mod = Qt.ShiftModifier if ch.isupper() else Qt.NoModifier
                for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                    QGuiApplication.sendEvent(view, QKeyEvent(kind, key, mod, ch))
        elif op == "set":
            find(a["name"]).setProperty(a["prop"], a["value"])
        elif op == "call":
            getattr(vmobjs[a["obj"]], a["fn"])(*a.get("args", []))
        elif op == "py":
            events.append([a["name"], extras[a["name"]](*a.get("args", []))])
        elif op == "get":
            events.append([a["obj"] + "." + a["prop"], getattr(vmobjs[a["obj"]], a["prop"])()])
        elif op in ("dragEnter", "dragMove", "dragLeave", "drop"):
            drag(op, a)
        elif op == "shot":
            shoot(a["name"])
        elif op == "dump":
            after[a["name"]] = dump()
        elif op == "hide":
            view.setVisible(False)
        elif op == "minimize":
            view.showMinimized()
        elif op == "show":
            view.show()
        else:
            raise ValueError("unknown action %r" % op)
        app.processEvents()

    cpu = None
    final = {"items": {}, "anims": []}

    def run():
        nonlocal cpu
        try:
            spin(900)
            for a in req["actions"]:
                act(a)
            spin(250)
            shoot("main")
            final["items"], final["anims"] = dump(), infinite()
            if req["cpu"]:
                c = req["cpu"]
                if c["state"] == "hidden":
                    view.setVisible(False)
                elif c["state"] == "minimized":
                    view.showMinimized()
                spin(600)
                t0, w0 = time.process_time(), time.perf_counter()
                spin(int(c["seconds"] * 1000), step=0.05)
                used, wall = time.process_time() - t0, time.perf_counter() - w0
                cpu = {"percent": used / wall * 100.0, "cpu_s": used, "wall_s": wall, "state": c["state"], "running": infinite()}
        except Exception:
            errors.append(traceback.format_exc())
        app.quit()

    QTimer.singleShot(0, run)
    app.exec()
    items, anims = final["items"], final["anims"]
    if cpu:
        anims = cpu["running"] if cpu["state"] != "visible" else anims
    if "__close" in extras:
        extras["__close"]()
    return _finish(req, warnings, errors, events, items, after, anims, cpu, shots)


def _finish(req, warnings, errors, events, items, after, anims, cpu, shots=None) -> int:
    raw = {"scene": req["scene"], "scale": req["scale"], "warnings": warnings, "errors": errors, "events": events,
           "items": items, "after": after, "animations": anims, "cpu": cpu, "shots": shots or {}}
    (Path(req["out"]) / (req["stem"] + ".json")).write_text(json.dumps(raw, default=str), encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        sys.exit(_child(json.loads(sys.argv[2])))
    print(__doc__)
