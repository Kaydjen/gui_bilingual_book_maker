"""Pure rules of the window shell (no Qt): the steps and their states in the header (window_spec 1.1-1.8), what the
close button does (14.24, 9.11, 14.6), the tray status lines and the time-left rounding (14.24), the window
geometry kept inside the visible screens (10.6, 10.8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

STEPS = ("books", "terms", "translate", "export")
LABELS = {"books": "Books", "terms": "Terms", "translate": "Translate", "export": "Export"}
SEP = " · "
DEFAULT_SIZE = (1100, 720)
MIN_SIZE = (820, 600)
REQUEST_CAP_S = 120                 # the HTTP timeout bounds how long the requests in flight can take (9.11)


def clean_screen(value, library_ready: bool = True) -> str:
    """The screen to open at start: the last one used (1.8, 10.6); Books while there is no library."""
    if not library_ready:
        return "books"
    return value if value in STEPS else "books"


def step_for_digit(n: int) -> str:
    """Ctrl+1..4 in path order (1.4); "" for any other digit."""
    return STEPS[n - 1] if 1 <= n <= len(STEPS) else ""


def context_line(series: str, book: str) -> str:
    """`series · book`; a part that is not there is left out; without a series the line is empty (1.3)."""
    if not series:
        return ""
    return SEP.join(p for p in (series, book) if p)


# ---------------------------------------------------------------- what the jobs are doing
@dataclass(frozen=True)
class RunInfo:
    """What the shell needs to know of the jobs. Today fake data; step 7 fills it from the RunSnapshot."""
    running: bool = False               # a job is translating now
    waiting: bool = False               # a job or the queue waits for the daily quota in the open window
    queued: int = 0                     # items of the queue that are not started
    failed: bool = False                # the job stopped on a problem
    needs_user: bool = False            # a job needs the user (red pulse on Translate, 7.16)
    terms_red: bool = False             # translation cannot start: the first chapter is blocked by terms (1.2)
    series: str = ""
    book: str = ""
    chapter: int = 0
    done: int = 0
    total: int = 0
    left_s: float | None = None         # measured seconds left, None while not known
    tomorrow: bool = False              # today's quota is not enough: it finishes tomorrow
    wake: str = ""                      # `09:01` while waiting for the quota
    verb: str = ""                      # the ONE job verb of zone 1 (7.6): Stop | Continue | Don't resume
    verb_enabled: bool = True
    reason: str = ""                    # why it failed: `Key invalid`

    @property
    def busy(self) -> bool:
        """Work that goes on without the window: a run, a wait for the quota, a queue that is not empty."""
        return self.running or self.waiting or self.queued > 0

    @property
    def has_job(self) -> bool:
        return bool(self.series) and (self.busy or self.failed)


def header_states(run: RunInfo) -> dict:
    """{"terms": "" | "red", "translate": "" | "wave" | "attention"} (1.2). The Translate word waves while any job
    runs, pulses red when a job needs the user; red wins."""
    translate = "attention" if (run.needs_user or run.failed) else ("wave" if run.running else "")
    return {"terms": "red" if run.terms_red else "", "translate": translate}


# ---------------------------------------------------------------- time left
def round_left(seconds) -> str:
    """`≈ 25 min` under an hour (whole minutes), `≈ 2 h 10 min` from one to three hours (to 10 min), `≈ 5 h` over
    three hours (whole hours). Empty when the time is not known."""
    if seconds is None or seconds < 0:
        return ""
    minutes = max(1, int(math.ceil(seconds / 60.0)))
    if minutes < 60:
        return "≈ %d min" % minutes
    if minutes <= 180:
        r = int(round(minutes / 10.0)) * 10
        h, m = divmod(r, 60)
        return "≈ %d h %d min" % (h, m) if m else "≈ %d h" % h
    return "≈ %d h" % int(round(minutes / 60.0))


def time_left_text(run: RunInfo) -> str:
    """`≈ 2 h 10 min left`, `≈ 6 h · finishes tomorrow`; empty when unknown."""
    t = round_left(run.left_s)
    if not t:
        return ""
    return "%s%s" % (t, " · finishes tomorrow") if run.tomorrow else "%s left" % t


def translate_tip(run: RunInfo, model: str = "", keys: int = 0, pace: int = 0):
    """The tooltip of the Translate step: series, book, chapters, model, keys in use, requests a minute (1.2, 11.5)."""
    if not run.has_job:
        return "Run the translation of the chosen chapters."
    facts = [("Series", run.series), ("Book", run.book)]
    if run.total:
        facts.append(("Chapters", "%d of %d" % (run.done, run.total)))
    if model:
        facts.append(("Model", model))
    if keys:
        facts.append(("Keys", str(keys)))
    if pace:
        facts.append(("Pace", "%d requests a minute" % pace))
    return ["%s translates here." % run.series if run.running else "The job of %s." % run.series, facts]


# ---------------------------------------------------------------- tray (14.24)
def tray_lines(run: RunInfo) -> list:
    """The status on top of the tray menu: [(text, kind)], kind bright | dim | red. The series name once."""
    if not run.has_job:
        return [("Nothing running", "dim")]
    lines = [(run.series, "bright")]
    progress = "%d of %d" % (run.done, run.total) if run.total else ""
    left = time_left_text(run)
    middle = SEP.join(p for p in (progress, left) if p)
    if middle:
        lines.append((middle, "dim"))
    if run.failed and run.reason:
        lines.append((run.reason, "red"))
    elif run.waiting and run.wake:
        lines.append(("Waits until %s" % run.wake, "dim"))
    return lines


def tray_tooltip(run: RunInfo) -> str:
    return SEP.join(t for t, _ in tray_lines(run))


def tray_actions(run: RunInfo) -> list:
    """The actions under the status: [(id, text, enabled)]. The job verb only when there is a job."""
    out = []
    if run.has_job and run.verb:
        out.append(("verb", run.verb, run.verb_enabled))
    out.append(("open", "Open", True))
    out.append(("quit", "Quit", True))
    return out


# ---------------------------------------------------------------- closing (14.24, 9.11, 14.6)
def close_decision(run: RunInfo, tray_available: bool, tray_seen: bool) -> str:
    """What the window's close button does: `quit` while idle; with work going on `hide` to the tray (`hide_first`
    when the first-time panel was never shown); without a tray the 9.11 / 14.6 panel (`panel`)."""
    if not run.busy:
        return "quit"
    if not tray_available:
        return "panel"
    return "hide" if tray_seen else "hide_first"


def quit_decision(run: RunInfo) -> str:
    """`Quit` of the tray menu: `quit` when idle, else the 9.11 / 14.6 panel (`panel`)."""
    return "panel" if run.busy else "quit"


def closing_panel(run: RunInfo) -> dict:
    """The text of the panel a quit during work opens. `kind` running (9.11, with a countdown) or waiting (14.6)."""
    if run.running:
        chapter = " · chapter %d" % run.chapter if run.chapter else ""
        return {"kind": "running", "title": "Finishing the current requests",
                "text": "Google is translating %s%s. The app closes as soon as the answers are saved, so this part "
                        "is not lost." % (run.series, chapter),
                "text2": "Everything translated before is already saved.",
                "cap": REQUEST_CAP_S, "close": "Close now", "action": ""}
    who = run.series or "The queue"
    until = " until %s" % run.wake if run.wake else ""
    return {"kind": "waiting", "title": "",
            "text": "%s waits for the daily quota%s. Closing the app stops the wait; continue from Translate later."
                    % (who, until),
            "text2": "", "cap": 0, "close": "Cancel", "action": "Close"}


def countdown_text(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return "up to %d:%02d" % divmod(seconds, 60)


# ---------------------------------------------------------------- window geometry (10.6, 10.8)
def _fit(v, lo, hi):
    return max(lo, min(hi, v))


def clamp_geometry(geo, screens, default=DEFAULT_SIZE, minimum=MIN_SIZE) -> dict:
    """The saved geometry {x, y, w, h, max} kept on the visible screens. `screens`: [(x, y, w, h)] of the available
    areas, the first is the primary one. A window whose title strip is on no screen (a monitor was unplugged) is
    centred on the primary screen; a window larger than its screen shrinks to it. Without a usable saved value the
    default size is centred."""
    if not screens:
        return {"x": 0, "y": 0, "w": default[0], "h": default[1], "max": False}
    px, py, pw, ph = screens[0]
    ok = isinstance(geo, dict) and all(isinstance(geo.get(k), int) and not isinstance(geo.get(k), bool)
                                       for k in ("x", "y", "w", "h"))
    maximized = bool(ok and geo.get("max") is True)
    w = geo["w"] if ok else default[0]
    h = geo["h"] if ok else default[1]
    x = geo["x"] if ok else None
    y = geo["y"] if ok else None
    home = None
    if ok:
        probes = ((x + w // 2, y + 18), (x + 60, y + 18))
        for sx, sy, sw, sh in screens:
            if any(sx <= qx < sx + sw and sy <= qy < sy + sh for qx, qy in probes):
                home = (sx, sy, sw, sh)
                break
    if home is None:
        home = (px, py, pw, ph)
        x = y = None
    sx, sy, sw, sh = home
    w = _fit(w, min(minimum[0], sw), sw)
    h = _fit(h, min(minimum[1], sh), sh)
    if x is None:
        x, y = sx + max(0, sw - w) // 2, sy + max(0, sh - h) // 3
    x = _fit(x, sx, sx + sw - w)
    y = _fit(y, sy, sy + sh - h)
    return {"x": x, "y": y, "w": w, "h": h, "max": maximized}
