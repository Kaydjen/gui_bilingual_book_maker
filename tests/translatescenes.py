"""The Translate scenes as data (used by tests/test_translate_scenes.py and by the shot script): every state of the accepted mock-up
(full/translate.js SC) and its panels as `name -> (data for tests/shellfactory.py, scene actions)`. A real library with real EPUBs
and a real job record behind the real view-models; the runner is a stub that is fed the events a run sends (tests/translatedrive.py)."""

from __future__ import annotations

from tests import translatedemo as demo

WAIT = {"op": "wait", "ms": 1600}
SHORT = {"op": "wait", "ms": 500}
SEL = demo.SELECTION


def py(name, *args):
    return {"op": "py", "name": name, "args": list(args)}


def call(obj, fn, *args):
    return {"op": "call", "obj": obj, "fn": fn, "args": list(args)}


def tv(fn, *args):
    return call("translateVm", fn, *args)


def click(name):
    return {"op": "click", "name": name}


def sel(text=SEL):
    return call("booksVm", "commitRange", text)


def data(*specs, **kw):
    d = {"library": "ready", "series": list(specs) or [demo.knights()], "select": ["Knights", "Book 1"],
         "screen": "translate", "keys": 1, "norun": True}
    d.update(kw)
    return d


def base(*more, text=SEL):
    """Books load, the chapters are selected, then `more`."""
    return [WAIT, sel(text), WAIT] + list(more) + [SHORT]


def rng(a, b):
    return list(range(demo.position(a), demo.position(b) + 1))


GAMMA = demo.other("Gamma")
DELTA = demo.other("Delta", target="pl:Polish")
QUEUE = [py("tr_enqueue", "Delta", "Book 2", 1, 5, "12-16")]
SAMPLE = ["Глава 2703 - Клятва", "Абзац 1 главы, с несколькими словами для перевода, и Имя2703 было там.",
          "Абзац 2 главы, с несколькими словами для перевода.", None]
FAILED = [[2699, 1, "empty"], [2702, 0, "refused"], [2711, 2, "empty"]]


def running(extra=()):
    return base(py("tr_begin"), py("tr_progress", 2703, 1), *extra)


def stopped(first=2730, last=2750, text="2730-2750", *more):
    return base(py("tr_record", "stopped", first, last), *more, text=text)


SCENES = {
    "ready": (data(), base()),
    "nokeys": (data(keys=0), base()),
    "nolang": (data(demo.knights(chosen=False)), base()),
    "reach": (data(demo.knights(blocked=[2731])), base(text="2725-2740")),
    "first": (data(demo.knights(blocked=[2703])), base()),
    "alldone": (data(demo.knights(translated=170)), base()),
    "running": (data(), running()),
    "retry": (data(), running([py("tr_retry_wait", 12), py("tr_progress", 2703, 1)])),
    "paused": (data(), running([py("tr_pause_wait", 42), py("tr_progress", 2703, 1)])),
    "stopping": (data(), running([py("tr_stop")])),
    "other": (data(demo.knights(), GAMMA), base(py("tr_begin", list(range(1, 20)), "Gamma", "Book 2"))),
    "stopped": (data(demo.knights(translated=0)), stopped()),
    "replace": (data(), stopped(2730, 2750, "2800-2819")),
    "terms": (data(demo.knights(blocked=[2731])),
              base(py("tr_record", "waiting_terms", 2730, 2750, {"terms_pending": 12, "blocked": 2731}), text="2730-2750")),
    "quota": (data(), base(py("tr_record", "waiting_quota", 2730, 2750, {"seconds": 3600}), text="2730-2750")),
    "failed": (data(), base(py("tr_dead_key"), py("tr_record", "failed", 2730, 2750, {"error": "no usable key/model pair is left"}),
                            text="2730-2750")),
    "elsewhere": (data(), base(py("tr_foreign"))),
    "problems": (data(demo.knights(translated=0), failed_blocks=FAILED), base(tv("setTab", "problems"))),
    "problem1": (data(demo.knights(translated=0), failed_blocks=FAILED), base(tv("setTab", "problems"), tv("selectProblem", 0))),
    "queue": (data(demo.knights(), GAMMA, DELTA),
              base(py("tr_begin", list(range(1, 20)), "Gamma", "Book 2"), py("tr_enqueue", "Delta", "Book 2", 1, 5, "12-16"),
                   tv("setTab", "queue"))),
    "restart": (data(demo.knights(), GAMMA, DELTA),
                base(py("tr_enqueue", "Gamma", "Book 2", 1, 10, "12-21"), py("tr_enqueue", "Delta", "Book 2", 1, 5, "12-16"),
                     tv("setTab", "queue"))),
    "qwait": (data(demo.knights(), GAMMA, DELTA),
              base(py("tr_quota_wait", "Gamma", 3600), py("tr_enqueue", "Delta", "Book 2", 1, 5, "12-16"), tv("setTab", "queue"))),
    "qstuck": (data(demo.knights(), GAMMA, DELTA), base(py("tr_stuck", "Delta", "Book 9"), tv("setTab", "queue"))),
    "sample": (data(demo.knights(blocked=[2703, 2704])),
               base(py("tr_sample_start"), py("tr_sample_write", 2703, SAMPLE), py("tr_sample_end"))),
    "sampling": (data(demo.knights(blocked=[2703, 2704])),
                 base(py("tr_sample_start"), py("tr_sample_progress", 12))),
    "checking": (data(demo.knights(translated=0), failed_blocks=FAILED), base(tv("setTab", "problems"), py("tr_hold_check", 40))),
    "replacepanel": (data(), stopped(2730, 2750, "2800-2819", tv("act", "replace"))),
    "discardpanel": (data(demo.knights(translated=0)), stopped(2730, 2750, "2730-2750", tv("moreAct", "discard"))),
    "itempanel": (data(demo.knights(), GAMMA),
                  base(py("tr_begin", list(range(1, 20)), "Gamma", "Book 2"), py("tr_enqueue", "Knights", "Book 1", 2, 5, "2651-2654"),
                       tv("act", "queue"))),
    "promptpanel": (data(), base(tv("promptEdit", True))),
    "promptdefault": (data(), base(tv("promptEdit", False))),
    "promptcopy": (data(), base(tv("promptEdit", False), tv("promptCopyDefault"))),
    "promptdraft": (data(), base(tv("promptEdit", True), tv("promptChanged", "Literary", "my text {language}"),
                                 tv("promptClosed", "Literary", "my text {language}", True), tv("promptEdit", True))),
    "langdrop": (data(demo.knights(chosen=False)), base(click("trTo"))),
    "timepop": (data(), base(click("trTime"))),
    "promptdrop": (data(), base(click("trPrompt"))),
    "closerun": (data(tray=False), running([call("appVm", "requestClose")])),
    "closeruntray": (data(), running([call("appVm", "requestClose")])),
    "closewait": (data(tray=False), base(py("tr_quota_wait", "Knights", 3600), call("appVm", "requestClose"))),
    "closewaittray": (data(), base(py("tr_quota_wait", "Knights", 3600), call("appVm", "requestClose"))),
}
