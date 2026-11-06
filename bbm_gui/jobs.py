"""Per-job working folders. The engine writes next to its input, so each (file, mode, language) gets its own
folder with a copy of the input; results are copied out afterwards."""
import hashlib
import os
import re
import shutil
from pathlib import Path

from .settings import data_dir

TEMP_BOOK = "_bilingual_temp"


def _safe(text, limit=40):
    s = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE).strip("._")
    return (s or "x")[:limit]


class Job:
    def __init__(self, source, mode, language):
        self.source = Path(source)
        self.mode = mode
        self.language = language
        digest = hashlib.sha1(str(self.source.resolve()).encode("utf-8")).hexdigest()[:8]
        name = "%s-%s-%s-%s" % (_safe(self.source.stem), digest, mode, _safe(language, 20))
        self.dir = data_dir() / "jobs" / name
        self.copy = self.dir / self.source.name
        self.log_path = self.dir / "run.log"

    @property
    def ext(self):
        return self.source.suffix.lower()

    @property
    def bin_path(self):
        return self.dir / (".%s.temp.bin" % self.source.stem)

    @property
    def out_path(self):
        ext = ".epub" if self.ext == ".pdf" else self.ext
        return self.dir / ("%s_bilingual%s" % (self.source.stem, ext))

    def prepare(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.copy.is_file() or self.copy.stat().st_size != self.source.stat().st_size:
            shutil.copy2(self.source, self.copy)

    def has_cache(self):
        try:
            return self.bin_path.is_file() and self.bin_path.stat().st_size > 0
        except OSError:
            return False

    def has_result(self):
        try:
            return self.out_path.is_file() and self.out_path.stat().st_size > 0
        except OSError:
            return False

    def restart(self):
        """Forget progress: remove the checkpoint, the recovery book and the previous result."""
        temp = self.dir / ("%s%s%s" % (self.source.stem, TEMP_BOOK, self.out_path.suffix))
        for p in (self.bin_path, self.out_path, temp):
            try:
                p.unlink()
            except OSError:
                pass


def target_name(pattern, source, language, mode):
    mode_word = "translation" if mode == "single" else "bilingual"
    try:
        name = (pattern or "{stem}_{lang}_{mode}").format(stem=Path(source).stem, lang=_safe(language, 20), mode=mode_word)
    except (KeyError, IndexError, ValueError):
        name = "%s_%s_%s" % (Path(source).stem, _safe(language, 20), mode_word)
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or Path(source).stem


def unique_path(folder, name, ext):
    p = Path(folder) / (name + ext)
    n = 2
    while p.exists():
        p = Path(folder) / ("%s (%d)%s" % (name, n, ext))
        n += 1
    return p


def deliver(job, folder, name):
    """Copy the finished book to its destination under a name that does not exist yet."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    dest = unique_path(folder, name, job.out_path.suffix)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copy2(job.out_path, tmp)
    os.replace(tmp, dest)
    return dest
