"""Double-click to start. Runs without a console window when opened with pythonw."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _fail(text):
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "Bilingual Book Maker", 0x10)
            return
        except (AttributeError, OSError):
            pass
    sys.stderr.write(text + "\n")


if sys.version_info < (3, 11):
    _fail("Python 3.11 or newer is required.\nhttps://www.python.org/downloads/")
else:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        _fail("This Python has no tkinter.\nReinstall Python and keep \"tcl/tk\" ticked "
              "(Linux: install the python3-tk package).")
    else:
        from bbm_gui.app import main

        main(sys.argv[1:])
