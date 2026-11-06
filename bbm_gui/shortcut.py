"""A desktop shortcut that starts the GUI without a console window."""
import os
import subprocess
import sys
from pathlib import Path

from . import icon
from .settings import data_dir

ROOT = Path(__file__).resolve().parent.parent
NAME = "Bilingual Book Maker"


def _windowless_python():
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.is_file() else exe)


def _desktop():
    if os.name == "nt":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = out.stdout.decode("utf-8", "replace").strip()
        return Path(text) if text else Path.home() / "Desktop"
    return Path.home() / "Desktop"


def create(folder=None):
    """Create the shortcut and return its path, or None where it is not supported."""
    folder = Path(folder) if folder else _desktop()
    folder.mkdir(parents=True, exist_ok=True)
    start = ROOT / "start.pyw"
    if os.name == "nt":
        ico = data_dir() / "icon.ico"
        ico.write_bytes(icon.ico_bytes())
        target = folder / (NAME + ".lnk")
        script = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
            "$s.TargetPath='%s';$s.Arguments='\"%s\"';$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()"
        ) % (str(target).replace("'", "''"), _windowless_python().replace("'", "''"), str(start).replace("'", "''"),
             str(ROOT).replace("'", "''"), str(ico).replace("'", "''"))
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
        return target
    if sys.platform.startswith("linux"):
        png = data_dir() / "icon.png"
        png.write_bytes(icon.png_bytes(128))
        target = folder / (NAME + ".desktop")
        target.write_text(
            "[Desktop Entry]\nType=Application\nName=%s\nExec=\"%s\" \"%s\"\nPath=%s\nIcon=%s\nTerminal=false\n"
            % (NAME, sys.executable, start, ROOT, png), encoding="utf-8")
        target.chmod(0o755)
        return target
    return None
