"""Shared helpers for the novelcore tests: synthetic books, series, runner setup."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from novelcore import Runner, Series
from tests.fake_api import FakeApi, FakeClock
from tests.test_core_epub import make_epub

KEYS = [f"test-key-{i}-SECRETSECRET" for i in range(3)]
MODEL = "gemini-test-flash-lite"
MODEL2 = "gemini-other-flash-lite"


def paragraph(c: int, p: int, alternate: bool = False) -> str:
    base = f"Chapter {c} paragraph {p} begins and keeps going for a while with some words."
    if alternate:
        return base + " Extra words follow here to make the block much longer than its neighbour." * 3 \
            if p % 2 == 0 else f"Chapter {c} line {p} is short but long enough."
    return base


def chapter_body(c: int, paras: int, alternate: bool = False, em_at=()) -> str:
    out = []
    for p in range(paras):
        text = paragraph(c, p, alternate)
        if p in em_at:
            text = text.replace("keeps going", "<em>keeps going</em>").replace("is short", "<em>is short</em>")
        out.append(f"<p>{text}</p>")
    return "\n".join(out)


def build_epub(path, chapters=3, paras=6, alternate=False, em_at=(), nav=False, first_chapter=0):
    docs = {f"c{c}.xhtml": chapter_body(c, paras, alternate, em_at) for c in range(first_chapter, first_chapter + chapters)}
    nav_html = None
    if nav:
        items = "".join(f'<li><a href="{n}">Title of {n} for the contents</a></li>' for n in docs)
        nav_html = f"<nav><ol>{items}</ol></nav>"
    make_epub(path, docs, nav=nav_html)


class CoreCase(unittest.TestCase):
    """Temp dir, a series with one synthetic book, a fake API on a virtual clock."""

    chapters = 3
    paras = 6
    alternate = False
    em_at = ()
    nav = False
    per_request = 4
    api_args: dict = {}
    auto_clock = True
    keys = KEYS

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.clock = FakeClock(auto=self.auto_clock)
        self.api = FakeApi(self.keys, self.clock, **self.api_args).start()
        self.addCleanup(self.api.stop)
        epub = self.dir / "Book One.epub"
        build_epub(epub, self.chapters, self.paras, self.alternate, self.em_at, self.nav)
        self.series = Series.create(self.dir / "lib", "Test Series", "ru:Russian", per_request=self.per_request)
        self.book = self.series.add_book(epub)

    def runner(self, keys=None, models=(MODEL,), first=0, last=None, book=None, **kw):
        kw.setdefault("rpm", {m: 15 for m in models})
        keys = self.keys if keys is None else keys
        return Runner(self.series, book or self.book, keys, list(models), first, last, clock=self.clock,
                      base_url=self.api.base_url, **kw)

    def run_all(self, **kw):
        r = self.runner(**kw)
        summary = r.run()
        return r, summary, r.drain()

    def all_blocks(self):
        with self.series.open_book(self.book) as b:
            return [(ch, blk) for ch in b.chapters for blk in b.blocks(ch)]

    def count_done(self) -> tuple[int, int]:
        """(done blocks, total blocks) according to the stored logs."""
        done = total = 0
        with self.series.open_book(self.book) as b:
            for ch in b.chapters:
                log = self.series.chapter_log(self.book, ch)
                for blk in b.blocks(ch):
                    total += 1
                    done += 1 if log.done(blk.index, blk.sha) else 0
        return done, total

    def requested_order_ok(self) -> bool:
        """Per chapter, the first paragraph of each successful request never goes backwards."""
        seq: dict[int, list[int]] = {}
        for e in self.api.log:
            if e["status"] != 200 or not e["texts"]:
                continue
            m = re.match(r"Chapter (\d+) \w+ (\d+)", e["texts"][0])
            if m:
                seq.setdefault(int(m.group(1)), []).append(int(m.group(2)))
        return all(s == sorted(s) for s in seq.values())

    def files_text(self) -> str:
        parts = []
        for f in self.dir.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".jsonl", ".txt", ".tmp"):
                parts.append(f.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)


def read_records(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out
