"""Builds the view-models of the shell for the QML scenes (tests/qmlharness.py `vm=`) and for the scripted shell checks.

`make(data) -> (objects, extras)`: `objects` become context properties of the scene (appVm, settingsVm, logVm, frameVm,
shellVm), `extras` are callables the scene actions may run (`op: "py"`). Everything lives under a fresh temp folder given as
NOVELGUI_DATA; the tray and the notifier are the recording ones; a service address is used only when `data["api"]` names
the fake server.

data keys: library ("ready" | "first" | "missing"), keys, models, pace, keep_awake, screen, run (RunInfo fields), custom
(bool: the custom frame), edge (bool), forceButtons, log [[text, series, problem]], pool {"<key index>": [kind, +seconds]},
tray (bool: the tray exists), tray_seen, api.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

KEY_FMT = "AIzaTestKey%02d" + "x" * 22


def planted(i: int) -> str:
    return KEY_FMT % i


def make(data):
    root = Path(tempfile.mkdtemp(prefix="novelshell-"))
    os.environ["NOVELGUI_DATA"] = str(root / "data")
    os.environ.pop("NOVELGUI_NOTIFY", None)
    os.environ.pop("NOVELGUI_TRAY", None)
    if data.get("api"):
        os.environ["NOVELGUI_API_BASE"] = data["api"]
    else:
        os.environ.pop("NOVELGUI_API_BASE", None)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    state = data.get("library", "ready")
    lib = root / "Novel library"
    settings = {}
    if state == "ready":
        lib.mkdir()
        series = lib / "Knights"
        (series / ".state").mkdir(parents=True)
        (series / "series.json").write_text("{}", encoding="utf-8")
        settings["library"] = str(lib)
    elif state == "missing":
        settings["library"] = str(root / "Gone" / "Novel library")
    n_keys = int(data.get("keys", 0))
    keys = [planted(i) for i in range(n_keys)]
    if keys:
        (data_dir / "keys.json").write_text(json.dumps({"version": 1, "keys": keys}), encoding="utf-8")
    if data.get("models"):
        settings["models"] = data["models"]
    if data.get("pace"):
        settings["pace"] = data["pace"]
    if data.get("keep_awake"):
        settings["keep_awake"] = True
    win = {}
    if data.get("screen"):
        win["screen"] = data["screen"]
    if data.get("tray_seen"):
        win["tray_seen"] = True
    if win:
        settings["win"] = win
    (data_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    if state == "ready" and data.get("pool"):
        from novelcore.pool import key_hash
        pairs = {}
        for idx, (kind, secs) in data["pool"].items():
            h = key_hash(keys[int(idx)])
            model = (data.get("models") or ["gemini-3.1-flash-lite"])[0]
            if kind == "dead":
                pairs["%s|%s" % (h, model)] = {"state": "dead", "reason": "invalid key"}
            else:
                pairs["%s|%s" % (h, model)] = {"state": kind, "until": time.time() + secs}
        (lib / "Knights" / ".state" / "pool.json").write_text(json.dumps({"pairs": pairs}), encoding="utf-8")

    from novelgui.runtime import tray as trays
    from novelgui.runtime.assemble import Parts
    from novelgui.runtime.shell import Shell
    tray = trays.RecordingTray(data_dir, available=data.get("tray", True))
    parts = Parts(settings_dir=data_dir, local=data_dir / "local", tray=tray)
    from novelgui.runtime import notify
    parts.notifier = notify.RecordingNotifier(data_dir)
    parts.app.notifier = parts.notifier
    for text, series, problem in data.get("log", []):
        parts.winlog.add(text, series, bool(problem))
    if data.get("custom"):
        parts.frame.set_custom(True)
    if data.get("edge"):
        parts.frame.set_edge_hot(True)
    if data.get("run"):
        parts.app.setRun(data["run"])
    shell = Shell()
    objects = {"shellVm": shell, "appVm": parts.app, "settingsVm": parts.settings_vm, "logVm": parts.log_vm,
               "frameVm": parts.frame}
    extras = {
        "__close": parts.close,
        "tray": lambda: {"lines": parts.tray.lines, "actions": parts.tray.actions, "tooltip": parts.tray.tooltip,
                         "alert": parts.tray.alert},
        "notify": lambda: _lines(data_dir / "notify.log"),
        "logtext": lambda: (data_dir / "local" / "window.log").read_text(encoding="utf-8")
        if (data_dir / "local" / "window.log").exists() else "",
        "settings": lambda: json.loads((data_dir / "settings.json").read_text(encoding="utf-8")),
        "keysfile": lambda: (data_dir / "keys.json").read_text(encoding="utf-8")
        if (data_dir / "keys.json").exists() else "",
        "drain": lambda: _drain(parts),
        "regions": lambda: {"h": parts.frame.caption_h, "n": len(parts.frame.clients), "max": parts.frame.max_rect},
        "raise": lambda: shell.handle_raise([]),
        "library": lambda: str(lib),
        "keys": lambda: keys,
    }
    return objects, extras


def _lines(path: Path) -> list:
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def _drain(parts) -> bool:
    """Wait (pumping events) until the lanes have nothing left; True when they went idle."""
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + 8
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if parts.lanes.idle():
            QCoreApplication.processEvents()
            return True
        time.sleep(0.02)
    return False
