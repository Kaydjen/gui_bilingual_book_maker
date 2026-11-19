"""Builds libraries for the Books scenarios and tests: real series folders with real EPUBs and chapter logs.

spec of a series: {"name", "folder" (default: the name), "target" ("ru:Russian"), "books": [book], "broken": "text" (series.json
is written damaged), "labels": {stem: label}}; spec of a book: {"stem", "chapters": n, "start": first title number (default 1),
"titles": "numbered" | "named" (no numbers in the titles) | "mixed", "translated": k (the first k chapters fully translated), "done": [[first number, last number], ...] (chapters by title
number that are fully translated, any places: the pieces of Export),
"partly": index of a chapter with the first half of its blocks translated, "paras": paragraphs per chapter (default 3),
"missing": True (the series.json lists nothing, the file is simply absent: not built), "mentions": {title number: [names]} (the
paragraphs of that chapter name them one by one; the Terms scan and the reader find them)}.
A series spec may carry "terms": [term] for terms.json: {"src", "tr", "type", "gender" (stored: male | female | neuter |
unknown), "status" (new | confirmed), "note", "seen": [chapter positions], "count", "ask": ["tr" | "gender", [[value, file], ...]]}
and "dismissed": [names]; "chosen": False = the language is not chosen yet (3.1).
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
        names = (book.get("mentions") or {}).get(str(book.get("start", 1) + k)) or []
        paras = "".join(("<p>Paragraph %d of chapter %d, with a few words to translate%s.</p>" % (
            j + 1, k + 1, (", and %s was there" % names[j]) if j < len(names) else "")
            ) for j in range(int(book.get("paras", 3))))
        titles.append(chapter_title(book, k))
        pages.append("<h1>%s</h1>%s" % (titles[-1], paras))
    path.parent.mkdir(parents=True, exist_ok=True)
    epubs.write_epub(path, pages, titles=titles)


def write_logs(series_path: Path, book: dict) -> None:
    """Chapter logs for the translated chapters (ok lines carry the hash of the CURRENT block text)."""
    from novelcore import Book
    from novelgui.facade.books import log_file
    done, partly = int(book.get("translated", 0)), book.get("partly")
    start = int(book.get("start", 1))
    ks = set(range(done))
    for a, b in book.get("done", []):
        ks.update(range(int(a) - start, int(b) - start + 1))
    if not ks and partly is None:
        return
    bk = Book.open(series_path / "books" / (book["stem"] + ".epub"))
    try:
        for ch in bk.chapters:
            if ch.is_toc:
                continue
            k = ch.index - 1            # position among the real chapters (the first spine page is the contents)
            if k not in ks and k != partly:
                continue
            blocks = bk.blocks(ch)
            take = blocks if k in ks else blocks[:max(1, len(blocks) // 2)]
            f = log_file(series_path, book["stem"], ch.index, ch.href)
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "w", encoding="utf-8") as fh:
                for b in take:
                    fh.write(json.dumps({"i": b.index, "src_sha": b.sha, "text": "Translated: " + b.text[:60], "model": "m",
                                         "at": 1.0, "status": "ok", "flags": []}, ensure_ascii=False) + "\n")
    finally:
        bk.close()


def write_terms(series_path: Path, terms, tag: str, dismissed=()) -> None:
    """terms.json of a series from plain specs (see the module doc)."""
    from novelcore.terms import TermBase, candidate
    base = TermBase(series_path / "terms.json", tag)
    for t in terms:
        e = base.add(t["src"], status=t.get("status", "new"), tr=t.get("tr", ""), type=t.get("type", "term"),
                     gender=t.get("gender", "unknown"), note=t.get("note", ""), seen=t.get("seen"), count=t.get("count", 0))
        if t.get("ask"):
            field, values = t["ask"]
            base.ask(e, field, [candidate(v, w) for v, w in values])
    for name in dismissed:
        base.dismiss(name)
    base.save()


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
        if spec.get("chosen") is False:
            extra["target_chosen"] = False
        path = Path(fb.create_series_record(library, spec["name"], spec.get("target", "ru:Russian"), **extra))
        if path != folder and not folder.exists():
            path.rename(folder)
            path = folder
        for book in spec.get("books", []):
            write_book(path / "books" / (book["stem"] + ".epub"), book)
            write_logs(path, book)
        if spec.get("terms") is not None:
            write_terms(path, spec["terms"], str(spec.get("target", "ru:Russian")).split(":")[0], spec.get("dismissed", ()))
        out.append(path)
    return out
