"""Builds libraries for the Books scenarios and tests: real series folders with real EPUBs and chapter logs.

spec of a series: {"name", "folder" (default: the name), "target" ("ru:Russian"), "books": [book], "broken": "text" (series.json
is written damaged), "labels": {stem: label}}; spec of a book: {"stem", "chapters": n, "start": first title number (default 1),
"titles": "numbered" | "named" (no numbers in the titles) | "mixed", "translated": k (the first k chapters fully translated),
"partly": index of a chapter with the first half of its blocks translated, "paras": paragraphs per chapter (default 3),
"missing": True (the series.json lists nothing, the file is simply absent: not built)}.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests import epubs

NAMES = ["Prologue", "The Grey Harbour", "A Letter Without a Seal", "Salt and Iron", "The Night Market", "Under the Bridge",
         "Old Debts", "The Lantern Keeper", "Rain on Stone", "Two Roads", "The Quiet Hour", "Ashes", "The Glass Tower",
         "A Borrowed Name", "Low Tide", "The Last Ferry", "Northern Lights", "What the River Knew", "Embers",
         "The Long Way Home", "Crossing", "Silent Bells", "The Archive", "Dawn"]
PLACES = ["Silver Spear", "Moon Gate", "Tintagel", "Lyonesse", "Dragon Hall", "The Oath", "The Gate", "Percival", "Cornwall",
          "Low Tide", "The Lake", "Morgana"]


def chapter_title(book: dict, k: int) -> str:
    kind = book.get("titles", "numbered")
    n = book.get("start", 1) + k
    if kind == "named":
        return NAMES[k % len(NAMES)] + ("" if k < len(NAMES) else " %c" % (65 + k // len(NAMES)))
    return "Chapter %d - %s" % (n, PLACES[k % len(PLACES)])


def write_book(path: Path, book: dict) -> None:
    pages, titles = [], []
    for k in range(int(book.get("chapters", 10))):
        paras = "".join("<p>Paragraph %d of chapter %d, with a few words to translate.</p>" % (j + 1, k + 1)
                        for j in range(int(book.get("paras", 3))))
        titles.append(chapter_title(book, k))
        pages.append("<h1>%s</h1>%s" % (titles[-1], paras))
    path.parent.mkdir(parents=True, exist_ok=True)
    epubs.write_epub(path, pages, titles=titles)


def write_logs(series_path: Path, book: dict) -> None:
    """Chapter logs for the translated chapters (ok lines carry the hash of the CURRENT block text)."""
    from novelcore import Book
    from novelgui.facade.books import log_file
    done, partly = int(book.get("translated", 0)), book.get("partly")
    if not done and partly is None:
        return
    bk = Book.open(series_path / "books" / (book["stem"] + ".epub"))
    try:
        for ch in bk.chapters:
            if ch.is_toc:
                continue
            k = ch.index - 1            # position among the real chapters (the first spine page is the contents)
            if k >= done and k != partly:
                continue
            blocks = bk.blocks(ch)
            take = blocks if k < done else blocks[:max(1, len(blocks) // 2)]
            f = log_file(series_path, book["stem"], ch.index, ch.href)
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "w", encoding="utf-8") as fh:
                for b in take:
                    fh.write(json.dumps({"i": b.index, "src_sha": b.sha, "text": "Translated: " + b.text[:60], "model": "m",
                                         "at": 1.0, "status": "ok", "flags": []}, ensure_ascii=False) + "\n")
    finally:
        bk.close()


def build(library: Path, specs) -> list:
    """Create the series of `specs` in `library`; returns the series folders."""
    from novelgui.facade import books as fb
    out = []
    for spec in specs:
        folder = library / spec.get("folder", spec["name"])
        if spec.get("broken"):
            folder.mkdir(parents=True)
            (folder / "series.json").write_text(spec["broken"], encoding="utf-8")
            out.append(folder)
            continue
        extra = {}
        if spec.get("labels"):
            extra["volume_labels"] = dict(spec["labels"])
        path = Path(fb.create_series_record(library, spec["name"], spec.get("target", "ru:Russian"), **extra))
        if path != folder and not folder.exists():
            path.rename(folder)
            path = folder
        for book in spec.get("books", []):
            write_book(path / "books" / (book["stem"] + ".epub"), book)
            write_logs(path, book)
        out.append(path)
    return out
