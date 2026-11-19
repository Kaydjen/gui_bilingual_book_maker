"""Builds the view-models of the shell for the QML scenes (tests/qmlharness.py `vm=`) and for the scripted shell checks.

`make(data) -> (objects, extras)`: `objects` become context properties of the scene (appVm, settingsVm, logVm, frameVm,
shellVm), `extras` are callables the scene actions may run (`op: "py"`). Everything lives under a fresh temp folder given as
NOVELGUI_DATA; the tray and the notifier are the recording ones; a service address is used only when `data["api"]` names
the fake server.

data keys: failed_blocks [[chapter number, block, reason]], norun (the Translate runner is a stub, tests/translatedrive.py), library ("ready" | "first" | "missing"), keys, models, pace, keep_awake, screen, run (RunInfo fields), custom
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
    elif data.get("norun"):
        os.environ["NOVELGUI_API_BASE"] = "http://127.0.0.1:9"       # nothing listens: a request that left would fail loudly
    else:
        os.environ.pop("NOVELGUI_API_BASE", None)
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    state = data.get("library", "ready")
    lib = root / "Novel library"
    settings = {}
    if state == "ready":
        lib.mkdir()
        settings["library"] = str(lib)
        if data.get("series") is not None:
            from tests import libfixture
            libfixture.build(lib, data["series"])
        else:
            from tests import libfixture        # one small book: a series without books would show the red `Add book`
            libfixture.build(lib, [{"name": "Knights", "books": [{"stem": "Book 1", "chapters": 3, "paras": 1}]}])
            (lib / "Knights" / ".state").mkdir(exist_ok=True)
        for number, block, reason in data.get("failed_blocks", []):        # blocks that failed before the window opened
            from tests import translatedemo
            translatedemo.write_failed_block(lib / "Knights", "Book 1", translatedemo.position(number), block, reason)
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
    if data.get("select"):
        win["books_last"] = {"series": data["select"][0], "book": data["select"][1] if len(data["select"]) > 1 else ""}
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
    incoming = _incoming(root / "Incoming", data.get("incoming", []), lib)
    if data.get("scan_hold"):
        parts.books_vm.scan_hold_ms = int(data["scan_hold"])
    if data.get("norun"):
        parts.run.submit = lambda fn, **kw: None                    # the runner is never started; tests/translatedrive.py feeds events
    parts.terms_vm.mine_names = bool(data.get("mine", False))
    parts.terms_vm.auto_scan = bool(data.get("autoscan", False))
    shell = Shell()
    objects = {"shellVm": shell, "appVm": parts.app, "settingsVm": parts.settings_vm, "logVm": parts.log_vm,
               "frameVm": parts.frame, "booksVm": parts.books_vm, "addVm": parts.add_vm, "readerVm": parts.reader_vm,
               "termsVm": parts.terms_vm, "translateVm": parts.translate_vm}
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
        "incoming": lambda: incoming,
        "openAdd": lambda: parts.books_vm.addFiles(incoming),
        "do": lambda fn, series, *rest: getattr(parts.books_vm, fn)(str(lib / series), *rest),
        "doBook": lambda fn, *rest: getattr(parts.books_vm, fn)(*rest),
        "rename": lambda kind, series, stem="": parts.books_vm.startRename(kind, str(lib / series) if kind == "series" else stem),
        "read": lambda i: parts.books_vm.readChapter(i),
        "blocking": lambda n: (setattr(parts.terms_vm, "feed_blocking", False), parts.books_vm.set_blocking(n))[1],
        "folders": lambda: sorted(p.name for p in lib.iterdir()) if lib.exists() else [],
        "trash": lambda: sorted(str(p.relative_to(lib)) for p in (lib / ".deleted").rglob("*.epub")),
        "filesOf": lambda name: sorted(str(p.relative_to(lib / name)) for p in (lib / name / "books").glob("*")),
        "keys": lambda: keys,
        "terms": lambda fn, *a: getattr(parts.terms_vm, fn)(*a),
        "floatText": lambda: parts.terms_vm.float_text(),
        "suggest": lambda names: _suggest(parts, names),
        "glossaries": lambda: _glossaries(root / "Incoming"),
        "holdScan": lambda percent: parts.terms_vm.hold_scan(percent),
        "holdLoading": lambda: parts.terms_vm.hold_loading(),
        "holdImporting": lambda n, total, progress: parts.terms_vm.hold_importing(n, total, progress),
        "importGlossaries": lambda: parts.terms_vm.importPicked(_glossaries(root / "Incoming")),
        "exportTo": lambda: parts.terms_vm.exportPicked(str(root / "Incoming" / "terms-Knights.json")),
        "termsTrash": lambda: [p.name for p in (data_dir / "local" / "terms_history").rglob("*.json.gz")],
    }
    from tests import translatedrive
    extras.update(translatedrive.Drive(parts, lib, keys).extras())
    return objects, extras


def _suggest(parts, names) -> int:
    """Mined names without a rendering as suggestion rows: [[text, count, first chapter position]]."""
    from novelgui.ctl.termrows import Suggestion
    vm = parts.terms_vm
    vm.session.suggestions = [Suggestion(t, n, f) for t, n, f in names]
    vm.session.changed.notify("reset", ())
    return len(names)


def _glossaries(folder: Path) -> list:
    """Two glossary files: a (own, checked) and b (disagrees on one name)."""
    folder.mkdir(parents=True, exist_ok=True)
    a = {"Arthur": "Артур", "Camelot": "Камелот", "Dagonet": "Дагонет", "Bors": "Борс", "Percival": "Парсифаль",
         "Kay": "Кэй", "Bedivere": "Бедивер"}
    b = {"Dagonet": "Дагонэ", "Ector": "Эктор", "Pellinore": "Пеллинор"}
    out = []
    for name, data in (("glossary_a.json", a), ("glossary_b.json", b)):
        (folder / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out.append(str(folder / name))
    return out


def _incoming(folder: Path, specs, lib: Path) -> list:
    """Files to add: [{"name": "Night Market.epub", "kind": "ok" | "protected" | "fonts" | "bad" | "copy:<series>/<stem>"}]."""
    from tests import epubs
    out = []
    folder.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        path = folder / spec["name"]
        kind = spec.get("kind", "ok")
        if kind == "bad":
            path.write_bytes(b"this is not a zip file")
        elif kind == "protected":
            epubs.write_with_encryption(path, [(epubs.AES, "OEBPS/ch0.xhtml")])
        elif kind == "fonts":
            epubs.write_with_encryption(path, [(epubs.IDPF_FONT, "OEBPS/f.otf"), (epubs.ADOBE_FONT, "OEBPS/g.ttf")])
        elif kind.startswith("copy:"):
            series, stem = kind[5:].split("/")
            import shutil
            shutil.copyfile(lib / series / "books" / (stem + ".epub"), path)
        else:
            epubs.write_epub(path, ["<h1>Chapter 1 - %s</h1><p>Some words to read.</p>" % path.stem] +
                             ["<h1>Chapter %d - More</h1><p>Text %d.</p>" % (k, k) for k in range(2, 4)])
        out.append(str(path))
    return out


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
