"""Thin developer entry: python -m novelcore <command> ..."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from pathlib import Path

from .exporter import NothingToExport, export
from .job import Job, JobError, SeriesBusy, job_status, resume
from .pool import clean_pace
from .run import Runner
from .store import Series
from .termmatch import scan_book
from .termmine import mine_candidates
from .terms import FILE_NAME, TermBase, import_glossary

DEFAULT_MODELS = "gemini-3.1-flash-lite"


def load_keys(path) -> list[str]:
    text = Path(path).read_text(encoding="utf-8").strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        data = data.get("keys")
    if isinstance(data, list):
        keys = [str(k).strip() for k in data]
    else:
        keys = [ln.strip() for ln in text.splitlines()]
    return [k for k in keys if k and not k.startswith("#")]


def _book_name(series: Series, args) -> str:
    name = getattr(args, "book", None)
    if name:
        return name
    names = series.book_names()
    if len(names) != 1:
        sys.exit("several books: use --book " + " | ".join(names))
    return names[0]


def _keys(args) -> list[str]:
    keys = load_keys(args.keys)[:getattr(args, "use_keys", None) or None]
    if not keys:
        sys.exit("no keys found")
    return keys


def parse_chapters(text: str) -> list[int]:
    """'5,7-9,12' -> [5, 7, 8, 9, 12]."""
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        a, sep, b = part.partition("-")
        try:
            lo, hi = int(a), int(b) if sep else int(a)
        except ValueError:
            raise ValueError(f"bad chapter list item {part!r}") from None
        if hi < lo or lo < 0:
            raise ValueError(f"bad chapter range {part!r}")
        out.extend(range(lo, hi + 1))
    if not out:
        raise ValueError("empty chapter list")
    return sorted(set(out))


def _selection(a):
    """(first, last, chapters) from `first last` or --chapters; None everywhere when neither is given."""
    spec = getattr(a, "chapters", None)
    first, last = getattr(a, "first", None), getattr(a, "last", None)
    if spec is not None:
        if first is not None or last is not None:
            sys.exit("give either first and last or --chapters, not both")
        try:
            return 0, None, parse_chapters(spec)
        except ValueError as exc:
            sys.exit(str(exc))
    if (first is None) != (last is None):
        sys.exit("give both first and last")
    return first, last, None


def _job(series: Series, args, first: int, last: int | None, chapters=None) -> Job:
    keys = _keys(args)
    print(f"{len(keys)} keys, models: {args.models}")
    extra = {"gate": False} if getattr(args, "no_gate", False) else {}
    if chapters is not None:
        extra["chapters"] = chapters
    return Job(series, _book_name(series, args), keys, args.models.split(","), first, last,
               in_flight=getattr(args, "in_flight", None), pace=getattr(args, "pace", None), **extra)


def _runner(series: Series, args, first: int, last: int | None) -> Runner:
    keys = _keys(args)
    print(f"{len(keys)} keys, models: {args.models}")
    state = series.path / ".state" / "pool.json"
    return Runner(series, _book_name(series, args), keys, args.models.split(","), first, last,
                  in_flight=getattr(args, "in_flight", None), state_path=state,
                  pace=getattr(args, "pace", None))


def _pace(text: str) -> float:
    try:
        return clean_pace(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _stamp(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


def _consume(runner) -> None:
    """Run a Runner or a Job and print its events until it is done."""
    try:
        runner.start()
    except SeriesBusy as exc:
        sys.exit(str(exc))
    try:
        while True:
            try:
                ev = runner.events.get(timeout=0.5)
            except queue.Empty:
                continue
            k = ev.kind
            if k == "started":
                print(f"{ev['chapters']} chapters ({ev['pages']} pages), {ev['workers']} workers"
                      + (f", pace {ev['pace']:g}/min" if ev.get("pace") else ""))
            elif k == "paused":
                note = ev["abort"] or f"no sending for {ev['seconds']:g} s, until {_stamp(ev['until'])}"
                print("throttled: " + note, flush=True)
            elif k == "unpaused":
                print("sending again", flush=True)
            elif k == "chapter_finished":
                tag = "toc " if ev["toc"] else ""
                print(f"{tag}chapter {ev['index']}: ok {ev['ok']}/{ev['blocks']} failed {ev['failed']} "
                      f"flagged {ev['flagged']} requests {ev['requests']}"
                      + ("" if ev["complete"] else " INCOMPLETE"), flush=True)
            elif k == "waiting":
                print(f"waiting until {_stamp(ev['until'])} ({ev['reason']})", flush=True)
            elif k == "resumed":
                print("resumed", flush=True)
            elif k == "terms":
                n = ev["terms"]
                _say(f"waiting for terms: chapter {ev['index']} ({ev['title']}): "
                     + (f"{n} unreviewed" if n >= 0 else f"unknown number unreviewed ({ev.get('error', '')})"),
                     flush=True)
            elif k == "error":
                print("error:", ev["message"], flush=True)
            elif k == "quota":
                print(f"daily quota used up; continue after {_stamp(ev['until'])}", flush=True)
            elif k == "block_failed":
                print(f"  block {ev['block']} of chapter {ev['index']} failed: {ev['reason']}", flush=True)
            elif k == "done":
                print("done:", json.dumps(ev.data, sort_keys=True))
                break
    except KeyboardInterrupt:
        print("stopping after the requests in flight ...")
        runner.stop()
        runner.join()
    print(f"peak requests per minute: {runner.stats.peak_per_minute()}")


def cmd_new(a) -> None:
    series = Series.create(a.library, a.series, a.to)
    name = series.add_book(a.book)
    print(f"series at {series.path}; book {name}")


def cmd_chapters(a) -> None:
    series = Series.open(a.series_dir)
    name = _book_name(series, a)
    with series.open_book(name) as book:
        for ch in book.chapters:
            blocks = book.blocks(ch)
            log = series.chapter_log(name, ch)
            done = sum(1 for b in blocks if log.done(b.index, b.sha)) if log.path.exists() else 0
            print(f"{ch.index:5d} {'T' if ch.is_toc else ' '} {done:4d}/{len(blocks):<4d} {ch.title[:60]}")


def cmd_status(a) -> None:
    series = Series.open(a.series_dir)
    name = _book_name(series, a)
    total = done = failed = chapters = finished = 0
    with series.open_book(name) as book:
        for ch in book.chapters:
            blocks = book.blocks(ch)
            total += len(blocks)
            log = series.chapter_log(name, ch)
            if not log.path.exists():
                continue
            d = sum(1 for b in blocks if log.done(b.index, b.sha))
            f = sum(1 for b in blocks if (r := log.lookup(b.index, b.sha)) and r.get("status") == "failed")
            done += d
            failed += f
            if not ch.is_toc:
                chapters += 1
                finished += 1 if d == len(blocks) else 0
    print(f"book {name}: blocks done {done}/{total}, failed {failed}; chapters touched {chapters}, finished {finished}")


def cmd_sample(a) -> None:
    series = Series.open(a.series_dir)
    runner = _runner(series, a, a.chapter, a.chapter)
    summary = runner.sample(a.chapter, a.blocks)
    print("sample:", json.dumps(summary, sort_keys=True))


def cmd_translate(a) -> None:
    series = Series.open(a.series_dir)
    first, last, chapters = _selection(a)
    if first is None and chapters is None:
        sys.exit("give first and last, or --chapters")
    _consume(_job(series, a, first, last, chapters))


def cmd_job(a) -> None:
    st = job_status(a.series_dir)
    rec = st["job"]
    if rec is None:
        print("no job")
        return
    state = "interrupted" if st["interrupted"] else rec["state"]
    if isinstance(rec.get("chapters"), list):
        span = ",".join(str(a) if a == b else f"{a}-{b}" for a, b in rec["chapters"]) or "none"
    else:
        span = f"{rec['first']}..{rec['last'] if rec['last'] is not None else 'end'}"
    print(f"book {rec['book']}, chapters {span}: {state}")
    print(f"blocks {st['blocks_done']}/{st['blocks_total']}, failed {st['blocks_failed']}; "
          f"chapters {st['chapters_done']}/{st['chapters_total']}")
    if rec.get("wake_at"):
        print("continue after", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec["wake_at"])))
    if rec.get("error"):
        print("error:", rec["error"])
    if rec["state"] == "waiting_terms":
        n = rec.get("terms_pending")
        print(f"waiting for terms: chapter {rec.get('blocked_chapter')}: "
              + (f"{n} unreviewed" if isinstance(n, int) and n >= 0 else "unknown number unreviewed"))
    elif rec.get("terms_pending"):
        print("terms to answer:", rec["terms_pending"])


def cmd_resume(a) -> None:
    models = a.models.split(",") if a.models else None
    try:
        extra = {"gate": False} if getattr(a, "no_gate", False) else {}
        job = resume(Series.open(a.series_dir), _keys(a), models, in_flight=getattr(a, "in_flight", None),
                     pace=getattr(a, "pace", None), **extra)
    except JobError as exc:
        sys.exit(str(exc))
    _consume(job)


def cmd_export(a) -> None:
    series = Series.open(a.series_dir)
    first, last, chapters = _selection(a)
    try:
        res = export(series, _book_name(series, a), first if first is not None else 0, last, a.mode,
                     chapters=chapters, cut=not a.whole)
    except NothingToExport as exc:
        print(str(exc))
        sys.exit(1)
    print(f"{res.path}: {res.blocks} blocks, {res.untranslated} untranslated, "
          f"{len(res.fallbacks)} markup fallbacks, {len(res.problems)} problems")
    if res.cut:
        print(f"kept {len(res.kept)} chapters, skipped {len(res.skipped)} not fully translated")
        for s in res.skipped[:20]:
            _say(f"  skipped chapter {s.index} ({s.title}): {s.missing} blocks missing")
    for p in res.problems[:20]:
        print("  problem:", p)


def _terms(series: Series) -> TermBase:
    return TermBase.load(series.path / FILE_NAME, series.target_tag)


def cmd_terms_import(a) -> None:
    series = Series.open(a.series_dir)
    base = _terms(series)
    rep = import_glossary(base, a.files)
    base.save()
    print(f"{len(base)} entries; added {rep.added}, same {rep.same}, skipped {rep.skipped}, "
          f"conflicts {len(rep.conflicts)}")
    for c in rep.conflicts[:20]:
        _say(f"  conflict ({c.kept_file} kept over {c.ignored_file}): {c.source}")


def _say(text: str, flush: bool = False) -> None:
    """Print without failing on a console that cannot show some characters (they are escaped)."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    print(text.encode(enc, "backslashreplace").decode(enc), flush=flush)


def cmd_terms_list(a) -> None:
    base = _terms(Series.open(a.series_dir))
    shown = 0
    for e in base:
        if (a.new and e.status != "new") or (a.questions and not e.questions):
            continue
        shown += 1
        flag = f" ?{','.join(sorted(e.questions))}" if e.questions else ""
        _say(f"{e.status:9s} {e.type:12s} {e.gender:8s} {e.count:5d}  {e.source} -> {e.tr}{flag}")
    print(f"{shown} of {len(base)} entries")


def cmd_terms_questions(a) -> None:
    base = _terms(Series.open(a.series_dir))
    open_ones = base.questioned()
    for e in open_ones:
        _say(f"{e.source} -> {e.tr} ({e.gender})")
        for field, cands in sorted(e.questions.items()):
            shown = " | ".join(f"{c['value']} [{c['evidence']}]" if c["evidence"] else c["value"] for c in cands)
            _say(f"  {field}: {shown}")
    print(f"{len(open_ones)} entries with open questions")


def cmd_terms_scan(a) -> None:
    series = Series.open(a.series_dir)
    base = _terms(series)
    with series.open_book(_book_name(series, a)) as book:
        res = scan_book(base, book, a.first, a.last)
    base.save()
    print(json.dumps(res, sort_keys=True))


def cmd_terms_candidates(a) -> None:
    series = Series.open(a.series_dir)
    base = _terms(series)
    texts = []
    with series.open_book(_book_name(series, a)) as book:
        for ch in book.chapters[max(a.first, 0):a.last + 1]:
            if not ch.is_toc:
                texts.extend(b.text for b in book.blocks(ch))
    found = mine_candidates(texts, base)
    print(f"{len(found)} candidates")
    for c in found[:20]:
        print(f"{c.count:5d}  {c.term}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="novelcore")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.set_defaults(fn=fn)
        return p

    p = add("new", cmd_new)
    p.add_argument("library")
    p.add_argument("series")
    p.add_argument("book")
    p.add_argument("--to", default="ru:Russian")

    p = add("chapters", cmd_chapters)
    p.add_argument("series_dir")
    p.add_argument("--book")

    p = add("status", cmd_status)
    p.add_argument("series_dir")
    p.add_argument("--book")

    def keys_args(p):
        p.add_argument("--keys", required=True, help="JSON {\"keys\": [...]} or one key per line")
        p.add_argument("--models", default=DEFAULT_MODELS)
        p.add_argument("--use-keys", type=int, help="use only the first N keys")
        p.add_argument("--pace", type=_pace, help="requests per minute in total (1-120; default: series "
                       "setting `pace`, else 24)")
        p.add_argument("--book")

    p = add("sample", cmd_sample)
    p.add_argument("series_dir")
    p.add_argument("chapter", type=int)
    p.add_argument("--blocks", type=int, default=50)
    keys_args(p)

    p = add("translate", cmd_translate)
    p.add_argument("series_dir")
    p.add_argument("first", type=int, nargs="?")
    p.add_argument("last", type=int, nargs="?")
    p.add_argument("--chapters", help="chapter indices, e.g. 5,7-9,12 (instead of first last)")
    p.add_argument("--no-gate", action="store_true", help="translate even chapters with unreviewed terms")
    p.add_argument("--in-flight", type=int)
    keys_args(p)

    p = add("job", cmd_job)
    p.add_argument("series_dir")

    p = add("resume", cmd_resume)
    p.add_argument("series_dir")
    p.add_argument("--in-flight", type=int)
    p.add_argument("--no-gate", action="store_true", help="translate even chapters with unreviewed terms")
    keys_args(p)
    p.set_defaults(models=None)

    p = add("export", cmd_export)
    p.add_argument("series_dir")
    p.add_argument("first", type=int, nargs="?")
    p.add_argument("last", type=int, nargs="?")
    p.add_argument("--chapters", help="chapter indices, e.g. 5,7-9,12 (instead of first last)")
    p.add_argument("--whole", action="store_true", help="write the whole book (untranslated blocks stay as they are)")
    p.add_argument("--mode", choices=("single", "bilingual"), default="single")
    p.add_argument("--book")

    terms = add("terms", None, help="term base tools").add_subparsers(dest="terms_cmd", required=True)

    def tadd(name, fn):
        p = terms.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("series_dir")
        return p

    p = tadd("import", cmd_terms_import)
    p.add_argument("files", nargs="+")
    p = tadd("list", cmd_terms_list)
    p.add_argument("--new", action="store_true")
    p.add_argument("--questions", action="store_true")
    p = tadd("questions", cmd_terms_questions)
    for name, fn in (("scan", cmd_terms_scan), ("candidates", cmd_terms_candidates)):
        p = tadd(name, fn)
        p.add_argument("first", type=int)
        p.add_argument("last", type=int)
        p.add_argument("--book")

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
