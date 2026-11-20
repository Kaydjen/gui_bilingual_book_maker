"""Time from the creation of the QML engine to the first frame of the REAL main window (Main.qml with every view-model, a library with
one small book), run by test_window_perf.

usage: python tests/perf_shell.py   ->  one JSON line {"first_frame_s": seconds}
Offscreen + software backend; nothing is shown. The imports are done before the clock starts (they are the interpreter's, not the
window's); the window file, the view-models and the first painted frame are measured.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from novelgui.runtime import assemble, tray as trays  # noqa: E402
from novelgui.runtime import shell as shellmod  # noqa: E402
from tests import libfixture  # noqa: E402


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="novelfirst-"))
    data = root / "data"
    data.mkdir()
    lib = root / "Novel library"
    lib.mkdir()
    libfixture.build(lib, [{"name": "Knights", "books": [{"stem": "Book 1", "chapters": 3, "paras": 1}]}])
    (data / "settings.json").write_text(json.dumps({"library": str(lib)}), encoding="utf-8")
    os.environ["NOVELGUI_DATA"] = str(data)
    os.environ.pop("NOVELGUI_API_BASE", None)
    app = QApplication(["perf"])
    shell = shellmod.Shell()
    parts = assemble.Parts(settings_dir=data, local=data / "local", tray=trays.RecordingTray(data, available=True))
    seen = []
    t0 = time.perf_counter()
    engine = QQmlApplicationEngine()
    window, parts = assemble.create_window(app, engine, shell, parts)
    window.frameSwapped.connect(lambda: seen.append(time.perf_counter() - t0) if not seen else None)
    window.show()
    end = time.perf_counter() + 20
    while not seen and time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)
    parts.close()
    print(json.dumps({"first_frame_s": seen[0] if seen else None}))
    return 0 if seen else 1


if __name__ == "__main__":
    sys.exit(main())
