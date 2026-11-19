"""Start of the window: `main(argv) -> int`.

Order: switch interval, folders, instance name and lock, log hooks, single instance, graphics choice, the Qt
application, the QML shell, running.flag, event loop, clean-up. A failure while building the window shows the
fatal panel instead of an empty window.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from . import instance, log, markers, paths

MESSAGE_NOT_ANSWERING = "The app is open but not answering."
ENV_PLANT = "NOVELGUI_TEST_PLANT"           # test hook: "slot" or "startup"
ENV_EXIT_AFTER = "NOVELGUI_TEST_EXIT_AFTER"  # test hook: quit cleanly after this many seconds
QML_MAIN = Path(__file__).resolve().parent.parent / "qml" / "Main.qml"


def epub_paths(argv) -> list:
    return [os.path.abspath(a) for a in argv if a.lower().endswith(".epub")]


def graphics_setting(settings_dir: Path) -> str:
    try:
        data = json.loads((settings_dir / "settings.json").read_text(encoding="utf-8"))
        value = data.get("graphics") if isinstance(data, dict) else None
    except (OSError, ValueError):
        value = None
    return value if value in ("auto", "software") else "auto"


def say(text: str) -> None:
    """The message function: a box on Windows, stderr elsewhere, a line in NOVELGUI_MESSAGE_FILE when set."""
    path = os.environ.get("NOVELGUI_MESSAGE_FILE")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        return
    from .. import platform
    if not platform.message_box(text):
        try:
            sys.stderr.write(text + "\n")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv=None) -> int:
    sys.setswitchinterval(0.0005)
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
    argv = list(sys.argv[1:] if argv is None else argv)
    local = paths.local_dir()
    name = instance.instance_name()
    lock_path = instance.lock_path()
    rt = log.RuntimeLog(paths.logs_dir())
    rt.install()
    try:
        return _run(argv, rt, local, name, lock_path)
    except Exception:
        rt.on_exception(*sys.exc_info())
        return 1
    finally:
        rt.close()


def _run(argv, rt, local, name, lock_path) -> int:
    from . import single
    lock = single.InstanceLock(lock_path)
    if not lock.acquire():
        result = single.forward(name, epub_paths(argv))
        if result == single.FORWARDED:
            return 0
        rt.info("second start: no answer from the running instance")
        say(MESSAGE_NOT_ANSWERING)
        return 1
    try:
        return _first(argv, rt, local, name)
    finally:
        lock.release()


def _first(argv, rt, local, name) -> int:
    marks = markers.Markers(local)
    unclean = marks.present(markers.RUNNING)
    if unclean:
        rt.info("previous run did not end cleanly")
    setting = graphics_setting(paths.settings_dir())
    trial_left = marks.present(markers.TRIAL)
    if trial_left:                      # the GPU start did not draw last time: stay on software until the user
        marks.write(markers.SOFTWARE)   # picks Graphics: Auto again in Settings (a crashing driver must not alternate)
    stuck = marks.present(markers.SOFTWARE)
    software = setting == "software" or stuck
    if software:
        os.environ["QT_QUICK_BACKEND"] = "software"
        rt.info("graphics: software renderer (%s)", "setting" if setting == "software" else "an earlier start did not draw")

    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from . import assemble, fatal, shell as shellmod, single

    app = QApplication(["novel"])           # QApplication: the tray icon and its menu are widgets
    app.setApplicationName("Novel")
    app.setQuitOnLastWindowClosed(False)    # a window hidden to the tray must not end the app
    sh = shellmod.Shell(previous_unclean=unclean, graphics_fallback=trial_left)
    rt.exit_handler = sh.exitRequested.emit
    sh.exitRequested.connect(app.exit, Qt.ConnectionType.QueuedConnection)
    rt.toast_handler = sh.request_toast
    flush = QTimer()
    flush.setInterval(5000)
    flush.timeout.connect(lambda: [log.logger.error(t) for t in rt.gate.flush()])
    flush.start()

    server = single.InstanceServer(name, sh.handle_raise)
    if not server.listen():
        rt.info("could not listen for a second start: %s", server.error_text())

    marks.write(markers.RUNNING)
    engine = None
    try:
        if os.environ.get(ENV_PLANT) == "startup":
            raise RuntimeError("Planted startup failure")
        engine = QQmlApplicationEngine()
        loaded = []
        engine.objectCreationFailed.connect(lambda url: loaded.append(url.toString()))
        window, parts = assemble.create_window(app, engine, sh)
        sh.window = window
        sh.toastRequested.connect(parts.app.runtimeToast)
        if not software and setting != "software":
            marks.write(markers.TRIAL)
        _remove_trial_at_first_frame(window, marks)
        window.show()
    except Exception:
        details = traceback.format_exc()
        log.logger.error("Start failed\n%s", details)
        engine = None
        server.close()
        code = fatal.show(details, rt.path)
        marks.remove(markers.TRIAL)
        marks.remove(markers.RUNNING)
        return code

    if os.environ.get(ENV_PLANT) == "slot":
        QTimer.singleShot(300, _planted_slot)
    exit_after = os.environ.get(ENV_EXIT_AFTER)
    if exit_after:
        QTimer.singleShot(int(float(exit_after) * 1000), app.quit)
    epubs = epub_paths(argv)
    if epubs:
        QTimer.singleShot(0, lambda: (log.logger.info("start paths: %s", epubs), sh.addBooksRequested.emit(epubs)))
    log.logger.info("window shown (pid %d, instance %s)", os.getpid(), name)

    code = app.exec()
    server.close()
    parts.close()
    del engine
    marks.remove(markers.RUNNING)
    log.logger.info("clean exit (code %d)", code)
    if rt.failures:
        return 1
    return code


def _remove_trial_at_first_frame(window, marks) -> None:
    done = []

    def first_frame():
        if not done:
            done.append(1)
            marks.remove(markers.TRIAL)

    window.frameSwapped.connect(first_frame)


def _planted_slot() -> None:
    raise RuntimeError("Planted slot failure")
