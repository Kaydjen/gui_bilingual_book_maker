"""Per-job working folders. The engine writes next to its input, so each (file, mode, language) gets its own
folder with a copy of the input; results are copied out afterwards."""
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

from . import langs
from .settings import data_dir

TEMP_BOOK = "_bilingual_temp"
META = ".prepared.json"
BR = re.compile(rb"<br\b[^>]*>(?![ \t\r\n])", re.I)
PRE = re.compile(rb"(<pre\b.*?</pre\s*>)", re.I | re.S)
PAGES = (".xhtml", ".html", ".htm")


def space_after_breaks(data):
    """A line break glues two words when the engine takes the text of a paragraph (`red,<br/>violets` reads
    `red,violets`): give every break a space. Text inside <pre> is left alone. Idempotent."""
    parts = PRE.split(data)
    for i in range(0, len(parts), 2):
        parts[i] = BR.sub(lambda m: m.group(0) + b" ", parts[i])
    return b"".join(parts)


def rewrite_members(path, transform):
    """Rewrite members of an EPUB in place: `transform(name, data)` returns the new bytes. Every other member, the member
    order and the way each is stored (the mimetype stays first and uncompressed) are kept. Returns the number of members
    that changed; the file is replaced only when the new archive reads back correctly."""
    tmp = Path(str(path) + ".new")
    changed = 0
    try:
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info)
                new = transform(info.filename, data)
                if new != data:
                    data, changed = new, changed + 1
                out = zipfile.ZipInfo(info.filename, info.date_time)
                out.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
                out.external_attr = info.external_attr
                out.create_system = info.create_system
                zout.writestr(out, data)
        if not changed:
            tmp.unlink()
            return 0
        with zipfile.ZipFile(path) as a, zipfile.ZipFile(tmp) as b:
            if b.testzip() is not None or [i.filename for i in a.infolist()] != [i.filename for i in b.infolist()]:
                raise zipfile.BadZipFile("rewritten archive differs")
        os.replace(tmp, path)
        return changed
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError):
        try:
            tmp.unlink()
        except OSError:
            pass
        return 0


def rewrite_epub(path):
    """Add the break spaces to the pages of an EPUB in place (see rewrite_members). Returns the pages that changed."""
    return rewrite_members(path, lambda name, data: space_after_breaks(data) if name.lower().endswith(PAGES) else data)


LANG_ATTR = re.compile(rb"(\s(?:xml:)?lang\s*=\s*)([\"'])([A-Za-z]{2,3})((?:[-_][A-Za-z0-9]+)*)\2")
DC_LANGUAGE = re.compile(rb"(<dc:language\b[^>]*>\s*)([A-Za-z]{2,3})((?:[-_][A-Za-z0-9]+)*)(\s*</dc:language>)")


def primary(tag):
    return re.split(r"[-_]", (tag or "").strip())[0].lower()


def source_languages(path):
    """The dc:language values of an EPUB (the first is the book's own language), lower case."""
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".opf"):
                    return [m.group(2).decode("ascii").lower() for m in DC_LANGUAGE.finditer(z.read(name))]
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError):
        pass
    return []


def relabel_language(data, source, target):
    """Declared language of one page, contents file or package: the `lang` / `xml:lang` attributes and the dc:language
    elements that name the source language (any region) are given the target tag. Other languages (a quoted French
    phrase) are left alone."""
    src, tag = primary(source), target.encode("ascii", "ignore")

    def attr(m):
        return m.group(0) if m.group(3).decode().lower() != src else m.group(1) + m.group(2) + tag + m.group(2)

    def element(m):
        return m.group(0) if m.group(2).decode().lower() != src else m.group(1) + tag + m.group(4)

    return DC_LANGUAGE.sub(element, LANG_ATTR.sub(attr, data))


def relabel_epub(path, source, target):
    """Single-translation copy for the reader: the text is in `target`, so the markup must not say `source` (a reading
    system hyphenates and speaks by that attribute). Returns the number of members changed."""
    if not source or not target or primary(source) == primary(target):
        return 0
    return rewrite_members(path, lambda name, data: relabel_language(data, source, target)
                           if name.lower().endswith(PAGES + (".opf", ".ncx")) else data)


def _safe(text, limit=40):
    s = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE).strip("._")
    return (s or "x")[:limit]


def _adopt(jobs_dir, prefix, new_name, lang):
    """A folder made before jobs were keyed by the language tag (`<prefix>Russian`, any spelling of the language) is
    renamed to the tag-keyed name once, so its checkpoint and log stay. Returns the directory name to use."""
    if (jobs_dir / new_name).exists() or not lang.tag or not jobs_dir.is_dir():
        return new_name
    found = []
    for d in jobs_dir.iterdir():
        if d.is_dir() and d.name.startswith(prefix) and d.name != new_name:
            old = langs.resolve(d.name[len(prefix):].replace("_", " "))
            if old.tag == lang.tag:
                found.append(d)
    if not found:
        return new_name
    old = max(found, key=lambda d: d.stat().st_mtime)
    try:
        old.rename(jobs_dir / new_name)
    except OSError:
        return old.name
    return new_name


class Job:
    """One (book, mode, target language) job. `lang` is a langs.Lang; the folder is keyed by its tag."""

    def __init__(self, source, mode, lang):
        self.source = Path(source)
        self.mode = mode
        self.lang = lang
        self.language = lang.name  # the display name used in the output file name
        digest = hashlib.sha1(str(self.source.resolve()).encode("utf-8")).hexdigest()[:8]
        prefix = "%s-%s-%s-" % (_safe(self.source.stem), digest, mode)
        jobs_dir = data_dir() / "jobs"
        name = _adopt(jobs_dir, prefix, prefix + _safe(lang.tag or lang.name, 20), lang)
        self.dir = jobs_dir / name
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

    @property
    def meta_path(self):
        return self.dir / META

    def meta(self):
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_meta(self, meta):
        try:
            self.meta_path.write_text(json.dumps(meta), encoding="utf-8")
        except OSError:
            pass

    def prepare(self):
        """Make the job's copy of the input. An EPUB copy gets a space after every line break, once: never when the job
        already has a checkpoint (the engine's saved paragraphs belong to the text as it was)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        st = self.source.stat()
        sig = [st.st_size, st.st_mtime_ns]
        meta = self.meta()
        fresh = not self.copy.is_file()
        if not fresh:
            if "src" in meta:
                fresh = meta["src"] != sig
            else:  # a copy made before this record existed: raw, and the same size as its source
                fresh = self.copy.stat().st_size != st.st_size
                meta = {"src": sig, "spaces": False, "tags": meta.get("tags")}
        if fresh:
            shutil.copy2(self.source, self.copy)
            meta = {"src": sig, "spaces": False, "tags": meta.get("tags")}
        if self.ext == ".epub" and not meta.get("spaces") and not self.has_cache():
            rewrite_epub(self.copy)
            meta["spaces"] = True
        self._write_meta(meta)

    def recorded_tags(self):
        """The --translate-tags value the job's checkpoint was written with: '' for the engine default, or None
        when nothing was recorded (a job from before the record: it ran with the engine default)."""
        tags = self.meta().get("tags")
        return tags if isinstance(tags, str) else None

    def record_tags(self, tags):
        meta = self.meta()
        meta["tags"] = tags or ""
        self._write_meta(meta)

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
    if job.ext == ".epub" and job.mode == "single" and job.lang.tag:
        # A bilingual book holds both languages in the same containers, so it keeps the engine's labels (its first
        # dc:language is already the target); a translation-only book has one language and is labelled with it.
        found = source_languages(job.copy)
        relabel_epub(tmp, found[0] if found else "", job.lang.tag)
    os.replace(tmp, dest)
    return dest
