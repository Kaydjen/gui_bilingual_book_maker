"""Series folder: settings, source books and append-only translation logs.

<series>/
  series.json
  books/<file>.epub
  chapters/<book>/<chapter>.jsonl     one JSON line per block, appended and fsynced
  samples/<book>/<chapter>.jsonl      sample runs only
  out/                                exported EPUBs
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import threading
import time
from pathlib import Path

from . import profiles
from .epub import Book

DEFAULTS = {
    "version": 1,
    "name": "",
    "source_lang": "",
    "target": "ru:Russian",
    "prompt": "default",
    "naming_policy": "",
    "per_request": 5,
    "temperature": 1.0,
    "pace": None,  # None: not set (the runner falls back to its default of 5 a minute)
    "in_flight": None,  # None: not set (the runner falls back to 12)
}
NEWLINE = bytes([10])
_RESERVED ={"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def atomic_write_text(path, text: str) -> None:
    """Write `text` to `path` so that a reader (or a crash) sees the old file or the new one, never half:
    temp file in the same folder, flush + fsync, then os.replace (retried on Windows, where a reader
    can hold the target open for a moment)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 7:
                    raise
                time.sleep(0.02 * (attempt + 1))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def safe_name(text: str, maxlen: int = 60, fallback: str = "item") -> str:
    """A file name part that is valid on Windows and Linux."""
    s = _BAD.sub("_", str(text))
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = s[:maxlen].rstrip(" .")
    if not s:
        s = fallback
    if s.lower() in _RESERVED or s.split(".")[0].lower() in _RESERVED:
        s = "_" + s
    return s


def split_target(target: str) -> tuple[str, str]:
    """'ru:Russian' -> ('ru', 'Russian'); a bare name gives (name, name)."""
    tag, _, name = str(target).partition(":")
    tag = tag.strip()
    return tag, (name.strip() or tag)


def chapter_file_name(chapter) -> str:
    stem = posixpath.splitext(posixpath.basename(chapter.href))[0]
    return f"{chapter.index:05d}_{safe_name(stem, 50)}.jsonl"


class ChapterLog:
    """Append-only JSONL of one chapter. Later lines win; a torn last line is ignored."""

    def __init__(self, path: Path, on_ok=None, on_change=None):
        """`on_ok(rec)` sees every appended ok record; `on_change(path, rec, old)` every appended record
        (`old` is the block's previous latest record or None)."""
        self.path = Path(path)
        self._on_ok = on_ok
        self._on_change = on_change
        self._lock = threading.Lock()
        self._recs: dict[tuple[int, str], dict] | None = None

    def _load(self) -> dict:
        if self._recs is None:
            recs: dict[tuple[int, str], dict] = {}
            for rec in read_jsonl(self.path):
                recs[(rec["i"], rec["src_sha"])] = rec
            self._recs = recs
        return self._recs

    def lookup(self, index: int, sha: str):
        """Latest record of this block with this source hash, or None."""
        with self._lock:
            return self._load().get((index, sha))

    def done(self, index: int, sha: str):
        """The finished (status ok) record, or None. Failed blocks are never done."""
        rec = self.lookup(index, sha)
        return rec if rec and rec.get("status") == "ok" else None

    def records(self) -> list[dict]:
        with self._lock:
            return sorted(self._load().values(), key=lambda r: r["i"])

    def append(self, recs: list[dict]) -> None:
        if not recs:
            return
        lines = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in recs)
        with self._lock:
            loaded = self._load()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            prefix = b""
            size = self.path.stat().st_size if self.path.exists() else 0
            if size > 0:
                with open(self.path, "rb") as rd:
                    rd.seek(-1, os.SEEK_END)
                    if rd.read(1) != NEWLINE:
                        prefix = NEWLINE  # do not glue onto a torn line
            try:
                with open(self.path, "ab") as f:
                    f.write(prefix + lines.encode("utf-8"))
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                try:  # a failed write must leave no half batch behind
                    os.truncate(self.path, size)
                except OSError:
                    pass
                raise
            olds = []
            for r in recs:
                olds.append(loaded.get((r["i"], r["src_sha"])))
                loaded[(r["i"], r["src_sha"])] = r
        if self._on_change:
            for r, old in zip(recs, olds):
                self._on_change(self.path, r, old)
        if self._on_ok:
            for r in recs:
                if r.get("status") == "ok":
                    self._on_ok(r)

    def clear(self) -> None:
        with self._lock:
            self._recs = {}
            if self.path.exists():
                self.path.unlink()


def read_jsonl(path: Path):
    """Yield valid records of a JSONL file; damaged or foreign lines are skipped."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("i"), int) and isinstance(rec.get("src_sha"), str):
            yield rec


class Series:
    def __init__(self, path):
        self.path = Path(path)
        self.settings = dict(DEFAULTS)
        self._logs: dict[str, ChapterLog] = {}
        self._sha: dict[str, dict] | None = None
        self._pending: dict[str, set] = {}  # sha -> {(log path, block)} whose latest record is `retry`
        self._lock = threading.Lock()
        try:
            data = json.loads((self.path / "series.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FileNotFoundError(f"no series at {self.path}: {exc}") from exc
        if isinstance(data, dict):
            self.settings.update(data)

    # -- creating and opening -------------------------------------------
    @classmethod
    def create(cls, library, name: str, target: str = "ru:Russian", **settings) -> "Series":
        path = Path(library) / safe_name(name, 80, "series")
        path.mkdir(parents=True, exist_ok=True)
        for sub in ("books", "chapters", "samples", "out"):
            (path / sub).mkdir(exist_ok=True)
        if not (path / "series.json").exists():
            data = dict(DEFAULTS, name=name, target=target, **settings)
            (path / "series.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return cls(path)

    @classmethod
    def open(cls, path) -> "Series":
        return cls(path)

    def save_settings(self) -> None:
        atomic_write_text(self.path / "series.json", json.dumps(self.settings, indent=2, ensure_ascii=False))

    @property
    def target_tag(self) -> str:
        return split_target(self.settings["target"])[0]

    @property
    def target_name(self) -> str:
        return split_target(self.settings["target"])[1]

    @property
    def per_request(self) -> int:
        try:
            return max(1, int(self.settings.get("per_request") or 5))
        except (TypeError, ValueError):
            return 5

    # -- books ----------------------------------------------------------
    def add_book(self, epub_path) -> str:
        """Copy an EPUB into books/; returns the book name (file stem)."""
        src = Path(epub_path)
        name = safe_name(src.stem, 80, "book")
        dest = self.path / "books" / (name + ".epub")
        if not dest.exists():
            shutil.copyfile(src, dest)
        return name

    def book_names(self) -> list[str]:
        return sorted(p.stem for p in (self.path / "books").glob("*.epub"))

    def open_book(self, name: str | None = None) -> Book:
        names = self.book_names()
        if name is None:
            if len(names) != 1:
                raise ValueError("several books in the series: name one of " + ", ".join(names))
            name = names[0]
        if name not in names:
            raise ValueError(f"no such book: {name}")
        return Book.open(self.path / "books" / (name + ".epub"))

    # -- prompt ---------------------------------------------------------
    def prompt_text(self) -> str:
        """The system prompt template: <series>/prompt.txt if present, else the shipped one of the target."""
        own = self.path / "prompt.txt"
        if own.exists():
            return own.read_text(encoding="utf-8")
        return profiles.prompt_text(self.target_tag)

    def system_prompt(self) -> str:
        return self.prompt_text().replace("{language}", self.target_name)

    # -- logs -----------------------------------------------------------
    def chapter_log(self, book: str, chapter) -> ChapterLog:
        path = self.path / "chapters" / safe_name(book, 80) / chapter_file_name(chapter)
        return self._log(path, self._note_ok, self._note_change)

    def sample_log(self, book: str, chapter) -> ChapterLog:
        path = self.path / "samples" / safe_name(book, 80) / chapter_file_name(chapter)
        return self._log(path, None)

    def _log(self, path: Path, on_ok, on_change=None) -> ChapterLog:
        key = str(path)
        with self._lock:
            log = self._logs.get(key)
            if log is None:
                log = self._logs[key] = ChapterLog(path, on_ok, on_change)
            return log

    def _index(self) -> dict[str, dict]:
        """sha -> finished record. Per chapter log only the LATEST record of each (block, sha) counts, and
        only when it is ok; shas of blocks whose latest record is `retry` are kept in `_pending`."""
        with self._lock:
            if self._sha is None:
                idx: dict[str, dict] = {}
                pending: dict[str, set] = {}
                for f in sorted((self.path / "chapters").glob("*/*.jsonl")):
                    latest: dict[tuple[int, str], dict] = {}
                    for rec in read_jsonl(f):
                        latest[(rec["i"], rec["src_sha"])] = rec
                    for rec in latest.values():
                        if rec.get("status") == "ok":
                            idx[rec["src_sha"]] = rec
                        elif rec.get("status") == "retry":
                            pending.setdefault(rec["src_sha"], set()).add((str(f), rec["i"]))
                self._sha = idx
                self._pending = pending
            return self._sha

    def _note_ok(self, rec: dict) -> None:
        idx = self._index()
        with self._lock:
            idx[rec["src_sha"]] = rec

    def _note_change(self, path, rec: dict, old) -> None:
        """Keep the built index in step with an appended record (any status)."""
        idx = self._index()
        sha, mark = rec["src_sha"], (str(path), rec["i"])
        with self._lock:
            if rec.get("status") == "retry":
                self._pending.setdefault(sha, set()).add(mark)
            else:
                marks = self._pending.get(sha)
                if marks:
                    marks.discard(mark)
                    if not marks:
                        del self._pending[sha]
            if rec.get("status") != "ok" and old is not None and old.get("status") == "ok":
                cur = idx.get(sha)
                if cur is not None and cur.get("text") == old.get("text") and cur.get("at") == old.get("at"):
                    del idx[sha]  # the finished text of this block was replaced

    def find_done(self, sha: str):
        """A finished block with this source hash anywhere in the series, or None. A hash that has a
        pending `retry` block is never handed out: its old text is what is being replaced."""
        with self._lock:
            known = self._sha
        idx = known if known is not None else self._index()
        with self._lock:
            if sha in self._pending:
                return None
        return idx.get(sha)


def default_prompt() -> str:
    return (Path(__file__).parent / "prompts" / "default.txt").read_text(encoding="utf-8")
