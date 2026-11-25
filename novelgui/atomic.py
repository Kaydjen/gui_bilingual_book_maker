"""One way to write a file of the window: a reader (or a crash) sees the old file or the new one, never half.

tmp in the same folder -> write -> flush -> fsync -> os.replace (retried briefly on Windows, where a reader can
hold the target open for a moment). With `bak=True` the previous file is first copied to `<name>.bak`, so a
file that later reads as damaged can be taken back from there.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

from . import platform


def write_bytes(path, data: bytes, bak: bool = False) -> None:
    """Replace `path` with `data` atomically. Raises OSError when it cannot be written (the old file stays)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.%d.tmp" % (path.name, os.getpid(), threading.get_ident()))
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if bak and path.is_file():
            try:
                shutil.copyfile(path, path.with_name(path.name + ".bak"))
            except OSError:
                pass        # a missing backup never blocks the write itself
        replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_text(path, text: str, bak: bool = False) -> None:
    write_bytes(path, text.encode("utf-8"), bak=bak)


def try_write_text(path, text: str, bak: bool = False) -> bool:
    """`write_text` that answers False instead of raising."""
    try:
        write_text(path, text, bak=bak)
        return True
    except OSError:
        return False


def replace(src, dst, attempts: int = 8) -> None:
    """os.replace, retried on Windows while another reader holds the target for a moment."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if not platform.IS_WINDOWS or attempt == attempts - 1:
                raise
            time.sleep(0.02 * (attempt + 1))
