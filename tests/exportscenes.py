"""The Export scenes as data (used by tests/test_export_scenes.py and by the shot script): every state of the accepted mock-up
(full/export.js ST) and its panels as `name -> (data for tests/shellfactory.py, scene actions)`. A real library with real EPUBs, a real
export history and a real job record behind the real view-models; a run is fed the events a runner sends (tests/translatedrive.py).

The demo book: Knights, Book 1, 170 chapters numbered 2650-2819 (the mock-up's 1-2800 scaled down). Translated: 2650-2699 (exported
on 3 Nov), 2710-2759 (2710-2739 exported on 12 Nov, 2740-2759 new); untranslated: 2700-2709 and 2760-2819."""

from __future__ import annotations

from tests import translatedemo as demo
from tests.translatescenes import SHORT, WAIT, call, click, py

A = "Knights 2650-2699 ru.epub"
B = "Knights 2710-2739 ru.epub"
DONE = [[2650, 2699], [2710, 2759]]
EXPORTS = [["Knights", "Book 1", 2650, 2699, "2026-11-03", A], ["Knights", "Book 1", 2710, 2739, "2026-11-12", B]]
NEW = (2740, 2759)


def ev(fn, *args):
    return call("exportVm", fn, *args)


def go_export():
    return call("appVm", "go", "export")


def data(*specs, exports=EXPORTS, **kw):
    d = {"library": "ready", "series": list(specs) or [demo.knights(done=DONE)], "select": ["Knights", "Book 1"],
         "screen": "export", "keys": 1, "norun": True, "exports": list(exports)}
    d.update(kw)
    return d


def base(*more):
    """The window opens on Export, the book is read, then `more`."""
    return [WAIT, WAIT] + list(more) + [SHORT]


def tick(first, last):
    """The choice replaced by the chapters first..last (title numbers): through the rows, like the user."""
    return py("ex_tick", first, last)


def row(label):
    return py("ex_press", label)


SCENES = {
    "pieces": (data(), base()),
    "merge": (data(), base(py("ex_tick", 2710, 2759))),
    "apart": (data(), base(py("ex_tick", 2650, 2699, 2740, 2759))),
    "open": (data(), base(py("ex_open", "2740-2759"), py("ex_tick", 2740, 2745))),
    "problem": (data(demo.knights(done=[[2650, 2759]]), exports=[], failed_blocks=[[2721, 0, "empty"]]), base()),
    "running": (data(demo.knights(done=[[2650, 2689]]), exports=EXPORTS[:1][:0] + [["Knights", "Book 1", 2650, 2679, "2026-11-12", A]]),
                base(py("tr_begin", None, "Knights", "Book 1", [2690, 2719]), py("ex_progress_to", 2690, 2699))),
    "exporting": (data(), base(py("ex_hold_busy", "single"))),
    "ok": (data(), base(ev("act", "single"), WAIT, WAIT)),
    "nothing": (data(), base(py("ex_nothing_next"), ev("act", "single"), WAIT)),
    "okboth": (data(), base(ev("act", "bilingual"), WAIT, WAIT)),
    "error": (data(), base(py("ex_fail_next"), ev("act", "single"), WAIT)),
    "blocked": (data(demo.knights(done=DONE, blocked=[2703]), exports=EXPORTS), base(call("booksVm", "commitRange", "2703-2750"), WAIT)),
    "none": (data(demo.knights(), exports=[]), base()),
    "nolang": (data(demo.knights(done=DONE, chosen=False)), base()),
    "ready": (data(demo.knights(translated=170), exports=[]), base(call("booksVm", "commitRange", "2703-2750"), WAIT)),
}
