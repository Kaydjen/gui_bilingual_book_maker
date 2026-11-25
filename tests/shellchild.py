"""Child process of tests/test_shell_process.py: the REAL main window (Main.qml with every view-model, built by
runtime/assemble.py) offscreen with a recording tray, driven through a fake run. Prints one JSON line with what happened."""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    root = Path(tempfile.mkdtemp(prefix="novelshell-child-"))
    data = root / "data"
    lib = root / "Novel library"
    (lib / "Knights").mkdir(parents=True)
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"library": str(lib), "win": {"screen": "translate"}}), encoding="utf-8")
    os.environ["NOVELGUI_DATA"] = str(data)
    os.environ.pop("NOVELGUI_API_BASE", None)

    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from novelgui.runtime import assemble, log as rtlog, paths, tray as trays
    from novelgui.runtime.shell import Shell

    rt = rtlog.RuntimeLog(paths.logs_dir(), strict=True)
    rt.install()
    app = QApplication(["novel-test"])
    app.setQuitOnLastWindowClosed(False)
    engine = QQmlApplicationEngine()
    shell = Shell()
    parts = assemble.Parts(settings_dir=data, local=data / "local", tray=trays.RecordingTray(data))
    window, parts = assemble.create_window(app, engine, shell, parts)
    vm, tray = parts.app, parts.tray
    events = []
    vm.exit_app = lambda: events.append("exit")
    window.show()

    def spin(ms):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)

    out = {"steps": []}

    def snap(name, **extra):
        out["steps"].append(dict(name=name, visible=window.isVisible(), panel=vm.panel, events=list(events),
                                 running=vm.run.running, screen=vm.screen, **extra))

    run = {"running": True, "series": "Knights", "book": "Book 1", "done": 12, "total": 54, "left_s": 7800,
           "chapter": 2703, "verb": "Stop"}
    spin(900)
    snap("start", rescans=vm.rescan_calls, tray_visible=tray.visible, tray_lines=tray.lines)
    vm.setRun(run)
    window.close()                                  # the window's own close button path (onClosing)
    spin(300)
    snap("close_first_time")
    vm.hideToTray()
    spin(200)
    snap("hidden", tray_alert=tray.alert, tooltip=tray.tooltip)
    tray.activate()
    spin(300)
    snap("shown_by_tray")
    window.close()
    spin(200)
    snap("close_again_hides_at_once")
    tray.trigger("open")
    spin(200)
    snap("opened_by_menu")
    tray.trigger("quit")
    spin(300)
    snap("quit_during_run", panel_kind=vm.panelData.get("kind"), title=vm.panelData.get("title"))
    vm.closePanel()
    vm.setRun({})
    window.close()
    spin(300)
    snap("close_idle")
    out["failures"] = rt.failures
    out["notify"] = [json.loads(x) for x in (data / "notify.log").read_text(encoding="utf-8").splitlines()] \
        if (data / "notify.log").exists() else []
    parts.close()
    print(json.dumps(out), flush=True)
    # A normal tear-down, as boot does: os._exit with a live QApplication hangs in ExitProcess on Windows about half the time.
    del window
    del engine
    app.processEvents()


if __name__ == "__main__":
    main()
