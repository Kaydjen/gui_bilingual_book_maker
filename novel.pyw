"""Double-click to start. Runs without a console window when opened with pythonw.

The window itself runs in the environment `.venv-window`, made on the first start (see novelgui/runtime/bootstrap.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from novelgui.runtime import bootstrap  # noqa: E402

sys.exit(bootstrap.launch(sys.argv[1:]))
