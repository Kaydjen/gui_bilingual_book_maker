"""Download and install the latest engine release into the GUI's own data folder (own virtual environment)."""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from .settings import data_dir

PYPI = "https://pypi.org/pypi/bbook_maker/json"
ARCHIVE = "https://github.com/yihong0618/bilingual_book_maker/archive/refs/tags/v%s.zip"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PREFERRED = [(3, 13), (3, 12), (3, 14), (3, 11), (3, 10)]  # batch mode of the Gemini route needs 3.12+


def engines_dir():
    d = data_dir() / "engines"
    d.mkdir(parents=True, exist_ok=True)
    return d


def current():
    """The installed engine: {"version", "root", "python"} or None."""
    try:
        info = json.loads((engines_dir() / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if Path(info.get("root", "")).is_dir() and Path(info.get("python", "")).is_file():
        return info
    return None


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "bbm-gui"})
    return urllib.request.urlopen(req, timeout=timeout)


def latest_version():
    with _get(PYPI) as r:
        return json.load(r)["info"]["version"]


def _probe(path):
    try:
        out = subprocess.run(
            [path, "-c", "import sys, venv, ensurepip; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True, timeout=30, creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"(\d+) (\d+)", out.stdout.decode("utf-8", "replace"))
    return (int(m.group(1)), int(m.group(2))) if out.returncode == 0 and m else None


def find_python():
    """The best Python for a new engine environment: (path, (major, minor)) or None."""
    found = {}
    cands = []
    if os.name == "nt":
        try:
            out = subprocess.run(["py", "-0p"], capture_output=True, timeout=20, creationflags=NO_WINDOW)
            for line in out.stdout.decode("utf-8", "replace").splitlines():
                m = re.search(r"([A-Za-z]:\\.*python\.exe)", line)
                if m:
                    cands.append(m.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
    for name in ("python3.13", "python3.12", "python3.14", "python3.11", "python3", "python"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    cands.append(sys.executable)
    for p in cands:
        if p in found:
            continue
        found[p] = _probe(p)
    ok = [(v, p) for p, v in found.items() if v and v >= (3, 10)]
    for want in PREFERRED:
        for v, p in ok:
            if v == want:
                return p, v
    return (ok[0][1], ok[0][0]) if ok else None


def _stream(cmd, cwd, log):
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                            env=dict(os.environ, PYTHONUTF8="1", PIP_DISABLE_PIP_VERSION_CHECK="1"))
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            log(line)
    return proc.wait()


def install(version, log):
    """Install engine `version`. Returns the info dict; raises RuntimeError with a short reason on failure."""
    target = engines_dir() / version
    src = target / "src"
    venv = target / "venv"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    py = find_python()
    if not py:
        raise RuntimeError("Python 3.10+ not found")
    log("Python %d.%d: %s" % (py[1][0], py[1][1], py[0]))
    log("Downloading engine %s" % version)
    zpath = target / "engine.zip"
    try:
        with _get(ARCHIVE % version, timeout=60) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
    except OSError as e:
        raise RuntimeError("download failed: %s" % e)
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        top = names[0].split("/")[0]
        z.extractall(target)
    os.replace(target / top, src)
    zpath.unlink()
    if not (src / "make_book.py").is_file():
        raise RuntimeError("archive has no make_book.py")
    log("Creating environment")
    if _stream([py[0], "-m", "venv", str(venv)], str(target), log) != 0:
        raise RuntimeError("could not create the environment")
    vpy = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    req = src / "requirements.txt"
    log("Installing packages")
    cmd = [str(vpy), "-m", "pip", "install", "--no-input", "-r", str(req)]
    if _stream(cmd, str(src), log) != 0:
        raise RuntimeError("package installation failed")
    info = {"version": version, "root": str(src), "python": str(vpy)}
    (engines_dir() / "current.json").write_text(json.dumps(info), encoding="utf-8")
    log("Engine %s ready" % version)
    return info
