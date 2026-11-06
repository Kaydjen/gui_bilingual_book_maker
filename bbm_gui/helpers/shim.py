"""Launcher for the engine CLI. It runs under the engine's own Python and is never copied into the engine.

usage: shim.py -- <engine arguments...>      (the ENGINE_DIR environment variable names the engine folder)

The engine runs in this process. A line "STOP" on stdin, or the end of stdin (the GUI is gone),
raises KeyboardInterrupt in the main thread, which is how the engine saves its progress.
"""
import _thread
import os
import runpy
import signal
import sys
import threading

sys.dont_write_bytecode = True  # keep the engine folder free of __pycache__

args = sys.argv[1:]
if args and args[0] == "--":
    args = args[1:]
engine_dir = os.environ["ENGINE_DIR"]


def _interrupt():
    if os.name == "nt":
        _thread.interrupt_main()
    else:
        signal.pthread_kill(threading.main_thread().ident, signal.SIGINT)


def _watch_stdin():
    for line in sys.stdin:
        if line.strip() == "STOP":
            _interrupt()
            return
    _interrupt()  # stdin closed: the GUI exited, behave like Stop


if os.name != "nt":
    signal.signal(signal.SIGINT, signal.default_int_handler)  # undo an inherited SIG_IGN
threading.Thread(target=_watch_stdin, daemon=True).start()
sys.path.insert(0, engine_dir)
sys.argv = [os.path.join(engine_dir, "make_book.py")] + args
runpy.run_path(os.path.join(engine_dir, "make_book.py"), run_name="__main__")
