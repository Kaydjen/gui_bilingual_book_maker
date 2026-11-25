"""Marker files in the local data folder.

running.flag: written at start, removed at a clean exit; present at the next start = the last run did not end
cleanly. render.trial: written before the window is shown, removed at the first frame; present at the next start =
the graphics start did not finish, so render.software is written. render.software: sticky, every start uses the
software renderer until the user chooses Graphics: Auto in Settings (that removes it).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

RUNNING = "running.flag"
TRIAL = "render.trial"
SOFTWARE = "render.software"


class Markers:
    def __init__(self, folder):
        self.dir = Path(folder)

    def present(self, name: str) -> bool:
        return (self.dir / name).exists()

    def write(self, name: str) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / name).write_text("%d %d\n" % (os.getpid(), time.time()), encoding="utf-8")
        except OSError:
            pass

    def remove(self, name: str) -> None:
        try:
            (self.dir / name).unlink()
        except OSError:
            pass
