"""The view-model of the Translate screen (window_spec 7.1-7.16, 9.2, 9.12, 13.1-13.4, 13.8, 13.12, 14.1, 14.15).

Rules live in ctl/ (translateplan: bar segments, row words, Time pill, Queue rows, tabs; runcontrol: the ONE start path;
runinfo: the shell's view of the jobs) and in the facade; this object is the glue: plain data to Qt properties and three
list models, the user's intents back to RunControl. Reads (job record, quota, prompt, language lock, terms gate,
problems) run off the GUI thread on the data lane or in the helper process; nothing polls: RunControl's snapshots and
events drive every update; the one timer of its own is a single-shot second that runs only while a row shows a
counting word (`Retrying 0:12`, `Paused 0:42`).

The interface for the QML screen is written down in .ai/notes/translate_vm_api.md.
"""

from __future__ import annotations

import dataclasses
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .. import busy, langrules, tips
from .. import jobqueue as jq
from .. import jobstate as js
from .. import startlabel as sl
from ..ctl import bookrows, eta, ordering
from ..ctl import translateplan as tp
from ..ctl.runinfo import run_info
from ..ctl.shellrules import round_left
from ..facade import books as fbooks
from ..facade import checks as fchecks
from ..facade import quota as fquota
from ..facade import run as frun
from ..facade import translate as ftr
from ..keystore import PromptStore
from .translatemodel import ChapterRows, ProblemRows, QueueRows

SYNC_MS = 40
COUNT_MS = 1000
SAMPLE_BLOCKS = tp.SAMPLE_BLOCKS
RESERVED = "default"
REACH_STARTS = ("translate", "queue", "replace", "queue_replace")


def _tip(value):
    """A tips.py tuple as the list the QML tooltip takes."""
    return [value[0], [list(f) for f in value[1]]] if isinstance(value, tuple) else value


def _seg(s: tp.Segment, tip: str = "") -> dict:
    return {"id": s.id, "text": s.text, "tone": s.tone, "enabled": s.enabled, "tip": tip}


class TranslateVM(QObject):
    viewChanged = Signal()
    topChanged = Signal()
    timeChanged = Signal()
    tabsChanged = Signal()
    barChanged = Signal()
    problemsChanged = Signal()
    editorChanged = Signal()
    queueChanged = Signal()
    sampleChanged = Signal()
    panelChanged = Signal()
    scrollRequested = Signal(int)           # a row number of the chapter list (the current / stopped chapter)
    checkChanged = Signal()
    openFolderRequested = Signal(str)
    promptDeleted = Signal(str)             # a prompt was deleted: the screen shows `Deleted <name>` with Undo
    runTouched = Signal()                   # the run changed (a state or a throttled snapshot): Export's `Translating` row

    def __init__(self, app, lanes, books, crunch=None, terms=None, parent=None):
        super().__init__(parent)
        self.app, self.lanes, self.books, self.crunch, self.terms = app, lanes, books, crunch, terms
        self.rc = None
        self.prompts = PromptStore(app.settings.folder)
        self.chapter_rows = ChapterRows(self)
        self.problem_rows = ProblemRows(self)
        self.queue_rows = QueueRows(self)
        self.order = ordering.WriteOrder(
            lanes.submit, lanes.close_lane_books, flush_state=app.flush,
            flush_terms=(terms.session.flush_terms if terms is not None else None),
            release_helper=(crunch.release if crunch is not None else None))
        self._path = self._book = ""
        self._info = None
        self._positions: tuple = ()             # the selection (chapter positions)
        self._rows_pos: list = []               # positions shown in the chapter list, by row
        self._row_of: dict = {}
        self._job = js.JobView()
        self._series = {"prompt": "default", "per_request": 5, "translated": False, "confirmed": False, "source": "",
                        "source_tag": ""}
        self._quota = fquota.Quota()
        self._gate: dict = {}
        self._gate_done: set = set()
        self._gate_ready = False
        self._problems: list = []
        self._problems_ready = False
        self._tab = "chapters"
        self._reach = tp.Reach()
        self._cur = None                        # position of the current / stopped chapter
        self._cur_word = tp.Word()
        self._samples: dict = {}                # series path -> {"chapter", "title", "rows", "unreviewed", "pending"}
        self._tracked = ("", None)              # (series path, JobView) behind the header's state
        self._panel = ""
        self._panel_data: dict = {}
        self._panel_valid = None
        self._pending_start = False
        self._checking = False
        self._check_pct = 0.0
        self._check_token = None
        self._prompt_trash = None               # (name, text) of the prompt deleted last (Undo)
        self._last_info_key = None
        self._lang_ready = False
        self._start_facts_cached = sl.choose(sl.StartFacts(has_series=False))
        self._infos_ver = 0                     # bumped whenever the chapter scan changes the infos
        self._translated_cache = (-1, frozenset())
        self._ctx_base = None                   # what every row of one build shares; dropped when a fact changes
        self._run_order = (None, [], 0)         # (run, its chapters in order, how many are complete: a pointer)
        self._run_reach = (None, "")
        self._queued_reach: dict = {}
        self._panel_ok = None
        self._prompt_orig = ("", "")
        self._top: dict = {}
        self._time: dict = {"visible": False}
        self._tabs_list: list = []
        self._bar_list: list = []
        self._more = False
        self._sync_t = self._timer(SYNC_MS, self._sync)
        self._count_t = self._timer(COUNT_MS, self._countdown)
        for sig in (books.viewChanged, books.selectionChanged, books.seriesChanged, books.chaptersChanged):
            sig.connect(self._sync_later)
        books.session.changed.add(self._on_books)
        app.screenChanged.connect(self._screen_changed)
        app.rescanRequested.connect(self._rescanned)
        app.panelChanged.connect(self._app_panel_changed)
        self._sync()

    def _timer(self, ms, fn) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(ms)
        t.timeout.connect(fn)
        return t

    def attach(self, rc) -> None:
        """The RunControl this view-model is the sink of (Parts builds both)."""
        self.rc = rc
        self._push_info()
        self._recompute()

    def run_config(self):
        """What a start needs: keys, models, pace (settings) and the service address (a test hook)."""
        from .. import settings as app_settings
        from ..ctl import settingsrules as sr
        s = self.app.settings
        try:
            pace = frun.clean_pace(s.get("pace"))
        except (ValueError, TypeError):
            pace = None
        return frun.RunConfig(list(self.rc.keys()), sr.stored_models(s.get("models")), pace, app_settings.api_base())

    def models(self) -> list:
        from ..ctl import settingsrules as sr
        return sr.stored_models(self.app.settings.get("models"))

    # ------------------------------------------------------------- properties of the whole screen
    @Property(QObject, constant=True)
    def chapters(self):
        return self.chapter_rows

    @Property(QObject, constant=True)
    def problemsModel(self):
        return self.problem_rows

    @Property(QObject, constant=True)
    def queueModel(self):
        return self.queue_rows

    @Property(str, notify=viewChanged)
    def view(self):
        """none (no series or book) | loading | ready | broken."""
        v = self.books.view
        if v in ("empty", "nobooks", "missing", "loading") or not self._path:
            return "none" if v != "loading" else "loading"
        if v == "broken":
            return "broken"
        return "ready" if self.books.session.infos or not self.books.chaptersLoading else "loading"

    @Property("QVariantMap", constant=True)
    def tips(self):
        t = tips
        return {"noSeries": t.TR_NO_SERIES, "from": t.TR_FROM, "prompt": t.TR_PROMPT,
                "promptDelete": t.TR_PROMPT_DELETE, "keysHead": t.TR_KEYS_HEAD, "queueUp": t.TR_QUEUE_UP,
                "queueDown": t.TR_QUEUE_DOWN, "queueRemove": t.TR_QUEUE_X, "queueStop": t.TR_QUEUE_STOP,
                "problemRetry": t.TR_PROBLEM["retry"], "problemKeep": t.TR_PROBLEM["keep"],
                "problemIgnore": t.TR_PROBLEM["ignore"], "problemSave": t.TR_PROBLEM["save"],
                "promptText": "The instructions sent with every request. {language} is replaced by the series language.",
                "promptNothing": "Nothing changed yet.", "problemFailed": t.TR_PROBLEM["failed"],
                "problemBusy": t.TR_PROBLEM["busy"], "dontResume": t.TR_BAR["dont_resume"] % "the return time",
                "more": t.TR_BAR["more"], "readOff": t.READ_OFF}

    # ------------------------------------------------------------- following Books
    def _sync_later(self, *a) -> None:
        self._sync_t.start(SYNC_MS)

    def _on_books(self, kind, payload=None) -> None:
        self._infos_ver += 1
        self._ctx_base = None
        if kind == "rows":
            self._rows_scanned(payload)
        elif kind == "skeleton":
            self._sync_later()
        elif kind == "scanned":
            self._load_problems()
            self._sync_later()

    def _screen_changed(self) -> None:
        self._push_info()                       # the red of Terms follows the screen the user is on
        if self.app.screen != "translate":
            return
        self._gate_done = set()
        self._gate_ready = False
        self._sync_later()
        if self.terms is not None and self.terms.session.save_pending:
            self.terms.session.flush_terms(lambda _w=None: self._after_terms_saved())
        else:
            self._after_terms_saved()

    def _after_terms_saved(self) -> None:
        self._load_series()
        self._load_gate()

    def _rescanned(self) -> None:
        if self.app.screen == "translate":
            self._load_series(job_only=True)

    def _sync(self) -> None:
        path, book, idx, _rng, _numbers = self.books.terms_context()
        info = self.books.info() if path else None
        if info is not None and info.broken:
            info = None
        key = (path, book if info is not None else "")
        changed = key != (self._path, self._book)
        self._path, self._book, self._info = key[0], key[1], info
        self._positions = tuple(idx)
        if changed:
            self._reset_series()
            if self._path and self._book:
                self._load_series()
                self._load_problems()
        self._load_gate()
        self._rebuild_rows()
        self._recompute()
        self.viewChanged.emit()

    def _reset_series(self) -> None:
        self._job = js.JobView()
        self._series = {"prompt": "default", "per_request": 5, "translated": False, "confirmed": False, "source": "",
                        "source_tag": ""}
        self._gate, self._gate_done, self._gate_ready = {}, set(), False
        self._problems, self._problems_ready = [], False
        self._lang_ready = False
        self._tab = "chapters"
        self._close_panel(cancel=True)
        self.problem_rows.set_rows([])
        self.editorChanged.emit()

    # ------------------------------------------------------------- reads off the GUI thread
    def _key(self):
        return (self._path, self._book)

    def _load_series(self, job_only: bool = False) -> None:
        path, book, key = self._path, self._book, self._key()
        if not path:
            return
        lib = self.books.library
        keys, models = (list(self.rc.keys()) if self.rc else []), self.models()
        now = time.time()

        def got_job(job):
            if self._key() == key:
                self._job = job
                self._after_job()
            self._tracked = (path, job) if self._tracked_wanted(path) else self._tracked
            self._push_info()

        self.lanes.submit(lambda ctx: ftr.job_task(ctx, path), on_result=got_job, on_error=lambda e: None, lane="data",
                          group="translate-job")
        if lib:
            self.lanes.submit(lambda ctx: ftr.quota_task(ctx, lib, keys, models, now), on_result=self._got_quota,
                              on_error=lambda e: None, lane="data", group="translate-quota")
        self._load_waits()
        if job_only:
            return

        def got_series(res):
            if self._key() != key:
                return
            self._series = res
            self._lang_ready = True
            self._recompute()
            self.topChanged.emit()

        if book:
            self.lanes.submit(lambda ctx: ftr.series_task(ctx, path, book), on_result=got_series,
                              on_error=lambda e: None, lane="data", group="translate-series")

    def _load_waits(self) -> None:
        """Saved jobs of the library that wait for the daily quota (a new start is then offered as a queue item, and the
        Sample stays dim). Read once per call off the GUI thread; the control keeps the latest wake-up."""
        rc = self.rc
        paths = [i.path for i in self.books.infos if not i.broken]
        if rc is None or not paths:
            return

        def work(ctx):
            out = []
            for p in paths:
                try:
                    out.append((p, frun.job_view(p)))
                except Exception:
                    continue
            return out

        def done(views):
            rc.note_waiting(views)
            self._recompute()

        self.lanes.submit(work, on_result=done, on_error=lambda e: None, lane="data", group="translate-waits")

    def _tracked_wanted(self, path: str) -> bool:
        return self.rc is not None and self.rc.tracked_series() == path

    def _got_quota(self, q) -> None:
        self._quota = q
        self._recompute()

    def _after_job(self) -> None:
        self._rebuild_rows()
        self._recompute()
        self._validate_panel()

    def _load_gate(self) -> None:
        """The unreviewed terms of the chapters still to translate in the selection (the core's own gate)."""
        if not self._path or not self._book:
            return
        infos = self.books.session.infos
        todo = [i for i in self._positions if i < len(infos) and infos[i].state.kind != "translated"
                and infos[i].is_toc is not True]
        missing = [i for i in todo if i not in self._gate_done]
        if not missing:
            self._gate_ready = True
            return
        self._gate_ready = False
        key, path, book = self._key(), self._path, self._book

        def done(res):
            if self._key() != key:
                return
            got = {int(k): int(v) for k, v in (res or {}).items()}
            self._gate.update(got)
            self._gate_done.update(missing)
            for i in missing:
                if i not in got:
                    self._gate.pop(i, None)
            self._gate_ready = all(i in self._gate_done for i in todo)
            self._rebuild_rows()
            self._recompute()
            self._push_info()

        def failed(exc):
            if self._key() == key:
                self._gate_done.update(missing)
                self._gate_ready = True
                self._recompute()

        if self.crunch is not None:
            self.crunch.submit("gate", {"series_path": path, "book": book, "positions": missing}, on_result=done,
                               on_error=failed, group="translate-gate")
        else:
            self.lanes.submit(lambda ctx: ftr.gate_counts_task(ctx, path, book, missing), on_result=done,
                              on_error=failed, lane="read", group="translate-gate")

    def _load_problems(self) -> None:
        """Failed blocks of the chapters the scan marked, and the saved check findings of the volume."""
        path, book, key = self._path, self._book, self._key()
        if not path or not book:
            return
        infos = self.books.session.infos
        chapters = [i.index for i in infos if i.failed]
        done = lambda rows: self._got_problems(key, rows)          # noqa: E731
        args = {"series_path": path, "book": book, "chapters": chapters}
        if self.crunch is not None:
            self.crunch.submit("problems", args, on_result=done, on_error=lambda e: done([]), group="translate-problems")
        else:
            self.lanes.submit(lambda ctx: fchecks.problems_task(ctx, path, book, chapters), on_result=done,
                              on_error=lambda e: done([]), lane="read", group="translate-problems")

    def _got_problems(self, key, rows) -> None:
        if self._key() != key:
            return
        self._problems = list(rows or [])
        self._problems_ready = True
        infos = self.books.session.infos
        self.problem_rows.set_rows([self._problem_row(p, infos) for p in self._problems])
        if self._tab == "problems" and not self._problems:
            self._tab = "chapters"
        self._rebuild_rows()
        self._recompute()
        self.problemsChanged.emit()
        self.editorChanged.emit()

    def _problem_row(self, p, infos) -> tuple:
        n = bookrows.shown_numbers([infos[p.chapter]])[0] if 0 <= p.chapter < len(infos) else p.chapter + 1
        title = p.title or ("Chapter %d" % n)
        return (str(n), title, str(p.block), p.source, p.reason, p.kind, p.detail)

    # ------------------------------------------------------------- the state of this series' job
    def _own_running(self) -> bool:
        rc = self.rc
        return bool(rc and rc.job_running and rc.runs_series(self._path))

    def _own_run(self):
        return self.rc.run if self._own_running() else None

    def _wake(self):
        """The time the daily quota returns for this series' job: the window's wait or the saved record."""
        rc = self.rc
        w = rc.sched.wait if rc else None
        if w is not None and w.series == self._path:
            return w.wake_at
        v = self._job
        if v.state == "waiting_quota" and v.wake_at is not None:
            return v.wake_at
        return None

    def _terms_now(self) -> int:
        v = self._job
        if v.state != "waiting_terms":
            return 0
        pos = v.blocked_chapter
        if pos is not None and self._gate_ready and pos in self._gate_done:
            return self._gate.get(pos, 0)
        return v.terms_pending

    def _job_state(self) -> str:
        """running | waiting_terms | waiting_quota | stopped | interrupted | failed | "" for this series' job."""
        if self._own_running():
            return "running"
        v = self._job
        if not v.unfinished or v.foreign:
            return ""
        now = self.rc.clock() if self.rc else time.time()
        if v.state == "waiting_quota":
            wake = self._wake()
            return "waiting_quota" if wake is not None and wake > now else "stopped"
        if v.state == "waiting_terms":
            return "waiting_terms" if self._terms_now() > 0 else "stopped"
        return v.state

    def _error_kind(self) -> str:
        v = self._job
        if v.state != "failed":
            return ""
        return tp.error_kind(v.error, v.dead)

    def _translated(self) -> frozenset:
        ver, got = self._translated_cache
        if ver != self._infos_ver:
            got = frozenset(i.index for i in self.books.session.infos if i.state.kind == "translated")
            self._translated_cache = (self._infos_ver, got)
        return got

    def _other(self) -> tuple:
        """(name, percent) of the job of ANOTHER series that runs or waits for the quota here, else ("", 0)."""
        rc = self.rc
        if rc is None:
            return "", 0
        if rc.job_running and not rc.runs_series(self._path):
            return rc.run.name, rc.percent() or 0
        w = rc.quota_wait()
        if w is not None and w[1] != self._path:
            return self._name_of(w[1]), 0
        return "", 0

    def _name_of(self, path: str) -> str:
        info = self.books.info(path)
        return info.name if info is not None else str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

    # ------------------------------------------------------------- the chapter rows
    def _job_positions(self) -> list:
        v = self._job
        return list(v.chapters) if (v.unfinished or v.foreign) and v.book == self._book else []

    def _shown_positions(self) -> list:
        infos = self.books.session.infos
        pos = [i for i in self._positions if i < len(infos) and infos[i].is_toc is not True]
        if not pos:
            run = self._own_run()
            pos = [i for i in (sorted(run.chapters) if run and run.book == self._book else self._job_positions())
                   if i < len(infos) and infos[i].is_toc is not True]
        return pos

    def _current_pos(self):
        run = self._own_run()
        if run is not None and run.book == self._book:
            chap = run.chap
            if self._run_order[0] is not run or len(self._run_order[1]) != len(chap):
                self._run_order = (run, sorted(chap), 0)
            _r, order, k = self._run_order
            while k < len(order) and not (chap[order[k]][1] and chap[order[k]][0] < chap[order[k]][1]):
                k += 1                                   # a chapter that is complete stays complete: the pointer only moves on
            self._run_order = (run, order, k)
            return order[k] if k < len(order) else None
        v = self._job
        if not (v.unfinished or v.foreign) or v.book != self._book:
            return None
        if v.state == "waiting_terms" and v.blocked_chapter is not None:
            return v.blocked_chapter
        tr = self._translated()
        left = [i for i in v.chapters if i not in tr]
        return left[0] if left else None

    def _rebuild_rows(self) -> None:
        self._ctx_base = None
        pos = self._shown_positions()
        self._cur = self._current_pos()
        self._cur_word = tp.Word()
        same = pos == self._rows_pos
        self._rows_pos = pos
        self._row_of = {p: k for k, p in enumerate(pos)}
        ctx = self._row_context()
        rows = [self._row(p, ctx) for p in pos]
        if same and len(self.chapter_rows):
            self.chapter_rows.replace({k: r for k, r in enumerate(rows)})
        else:
            self.chapter_rows.set_rows(rows)
        self._arm_count()

    def _row_context(self) -> dict:
        """What every row of this build shares. The facts part is made once until a fact changes; the live part (the
        run, its table, the clock) is looked up at each call."""
        base = self._ctx_base
        if base is None:
            problems: dict = {}
            for p in self._problems:
                problems[p.chapter] = problems.get(p.chapter, 0) + 1
            reach = tp.split_reach(self._positions, self._translated(), self._gate) if self._gate_ready else tp.Reach(
                tuple(self._positions))
            v = self._job
            base = self._ctx_base = {
                "infos": self.books.session.infos, "problems": problems, "reach": reach, "state": self._job_state(),
                "kind": self._error_kind(), "wake": self._wake(), "foreign": v.foreign,
                "first": self._rows_pos[0] if self._rows_pos else None,
                "hold": v.blocked_chapter if v.state == "waiting_terms" else None}
        run = self._own_run()
        return dict(base, run=run, chap=run.chap if run is not None else None,
                    now=self.rc.clock() if self.rc else time.time())

    def _row(self, pos: int, ctx: dict | None = None) -> tuple:
        ctx = ctx or self._row_context()
        infos = ctx["infos"]
        info = infos[pos]
        live = ctx["chap"].get(pos) if ctx["chap"] is not None else None
        if live is not None:
            done, total, failed = live
        else:
            done, total, failed = info.done, info.blocks or 0, info.failed
        fraction = min(1.0, done / total) if total else 0.0
        failed_f = min(1.0, failed / total) if total else 0.0
        translated = bool(total) and done >= total and not failed
        current = pos == self._cur
        run = ctx["run"]
        word = self._word(pos, ctx, current, translated, run)
        reach = ctx["reach"]
        beyond = reach.blocked_at is not None and pos > reach.blocked_at and not translated
        flags = []
        if translated:
            flags.append("translated")
        if beyond:
            flags.append("beyond")
        if current and run is not None:
            flags.append("live")
        if word.click:
            flags.append(word.click)
        if info.is_toc is True:
            flags.append("toc")
        title = info.title or ("Contents" if info.is_toc else "")
        no = str(bookrows.shown_numbers([info])[0])
        return (no, title, fraction, failed_f, word.text, word.tone, current, ",".join(flags))

    def _word(self, pos: int, ctx: dict, current: bool, translated: bool, run) -> tp.Word:
        word = tp.row_word(self._word_facts(pos, ctx, current, translated, run), ctx["now"])
        if current:
            self._cur_word = word
        return word

    def _word_facts(self, pos: int, ctx: dict, current: bool, translated: bool, run) -> tp.RowFacts:
        terms = 0 if translated else self._gate.get(pos, 0)
        if ctx["foreign"] and not current and pos == ctx["first"] and self._cur not in self._row_of:
            current = True                      # the other program works on chapters this list does not show
        reach = ctx["reach"]
        holds = (pos == reach.blocked_at and reach.first) or pos == ctx["hold"]
        f = tp.RowFacts(job_state="running" if run is not None else ctx["state"], current=current,
                        error_kind=ctx["kind"], wake_at=ctx["wake"], terms=terms, terms_holds=holds,
                        foreign=ctx["foreign"], problems=ctx["problems"].get(pos, 0), running=run is not None)
        if run is not None and current:
            f = dataclasses.replace(f, retry_until=run.retry_until, paused_until=run.paused_until,
                                    stopping=run.stopping)
        return f

    def _rows_scanned(self, spans) -> None:
        """Rows of the chapter scan arrived: the shown rows among them are made again, one change per run of rows."""
        infos = self.books.session.infos
        ctx = None
        updates: dict = {}
        for a, b in spans or ():
            for i in range(a, b + 1):
                k = self._row_of.get(i)
                if k is not None and i < len(infos):
                    ctx = ctx or self._row_context()
                    updates[k] = self._row(i, ctx)
        if updates:
            self.chapter_rows.replace(updates)
        if spans:
            self._sync_later()

    # ------------------------------------------------------------- computing the controls
    def _recompute(self) -> None:
        self._ctx_base = None
        self._reach = tp.split_reach(self._positions, self._translated(), self._gate) if self._gate_ready else \
            tp.Reach(tuple(self._positions))
        self._compute_top()
        self._compute_time()
        self._compute_tabs()
        self._compute_bar()
        self._compute_queue()
        self._arm_count()
        self._push_info()
        self.viewChanged.emit()

    def _language(self) -> str:
        return (fbooks.series_language(self._info) or "") if self._info is not None else ""

    def _keys_n(self) -> int:
        return len(list(self.rc.keys())) if self.rc else 0

    def _reach_text(self, positions=None) -> str:
        infos = self.books.session.infos
        pos = self._reach.positions if positions is None else positions
        pos = [i for i in pos if 0 <= i < len(infos)]
        return bookrows.range_text(infos, pos) if pos else ""

    def _selection_text(self) -> str:
        return bookrows.range_text(self.books.session.infos, self._positions) if self._positions else ""

    def _language_lock(self) -> str:
        """Why `To` cannot be used now ("" = it can): the job of the series runs or is queued here or elsewhere, or a
        block is translated / a term confirmed already."""
        if self._info is None:
            return "Choose a series on Books first."
        extra = []
        rc = self.rc
        if rc is not None and rc.queued(self._path) is not None:
            extra.append("This series is waiting in the queue; the language is read when it starts.")
        why = busy.language_reason(self._job, extra)
        if not why and self._own_running():
            why = busy.RUNNING
        if why:
            return why
        if self._language():
            return langrules.lock_reason(self._series["translated"], self._series["confirmed"])
        return ""

    def _compute_top(self) -> None:
        has = self._info is not None and bool(self._book)
        lang = self._language()
        lock = self._language_lock() if has else ""
        name = str(self._series["prompt"])
        pname = "Default" if name.lower() == RESERVED else name
        keys = self._keys_n()
        job_runs = bool(self.rc and (self.rc.run is not None and self.rc.run.kind == "job"))
        waiting = bool(self.rc and self.rc.quota_wait() is not None)
        enabled, why = tp.sample_enabled(job_runs, waiting, keys > 0, bool(lang))
        if not self._positions:
            enabled, why = False, why or "selection"
        run = self.rc.run if self.rc else None
        sampling = bool(run is not None and run.kind == "sample")
        unrev = self._gate.get(self._positions[0], 0) if self._positions and self._gate_ready else 0
        if sampling:
            done, total = run.sample
            text = "Sample %d / %d" % (done, total or SAMPLE_BLOCKS)
            stip = tips.TR_SAMPLE_RUNNING % (done, total or SAMPLE_BLOCKS)
            enabled = True
            pct = (done / total) if total else 0.0
        else:
            text = tp.sample_label(unrev)
            pct = 0.0
            stip = tips.TR_SAMPLE_OFF.get(why, "") if not enabled else tips.TR_SAMPLE % SAMPLE_BLOCKS
            if enabled and unrev:
                stip = tips.TR_SAMPLE_UNREVIEWED % unrev
        if lock:
            tto = tips.TO_BUSY % lock if lock not in (langrules.TRANSLATED, langrules.CONFIRMED) else lock
            if self._own_running():
                tto = tips.TR_TO_LOCKED_RUN
        else:
            tto = _tip(tips.TO_EMPTY if not lang else tips.TO_CHOSEN)
        top = {"has": has, "toText": langrules.split(lang)[1] if lang else "language", "toRed": has and not lang,
               "toEnabled": has and not lock, "toTip": tto, "fromText": ("From %s" % self._series["source"])
               if self._series["source"] else "", "fromTip": tips.TR_FROM,
               "promptName": pname, "promptEnabled": has and not self._job.foreign, "promptTip": tips.TR_PROMPT,
               "editEnabled": has and not self._job.foreign, "editTip": tips.TR_PROMPT_EDIT % pname,
               "sampleText": text, "sampleEnabled": has and enabled and not self._job.foreign, "sampleTip": stip,
               "sampling": sampling, "samplePercent": pct, "languageRed": has and not lang}
        if top != self._top:
            self._top = top
            self.topChanged.emit()

    def _pace(self) -> int:
        try:
            return int(frun.clean_pace(self.app.settings.get("pace")) or frun.default_pace())
        except (ValueError, TypeError):
            return int(frun.default_pace())

    def _left_s(self):
        run = self._own_run()
        if run is None:
            return None
        bdone, btotal, _c, _n = self.rc.counts()
        return eta.time_left(bdone - run.done_at_start, self.rc.clock() - run.started, btotal - bdone)

    def _compute_time(self) -> None:
        rc = self.rc
        infos = self.books.session.infos
        run = self._own_run()
        positions = self._reach.positions or tuple(self._positions)
        if not positions and self._job_state() in ("stopped", "interrupted", "failed", "waiting_terms",
                                                   "waiting_quota"):
            positions = tuple(self._job_positions())
        if run is not None:
            bdone, btotal, _c, _n = rc.counts()
            remaining, complete, positions = max(0, btotal - bdone), True, ()
        else:
            remaining, complete = js.remaining_blocks(infos, positions)
        per = int(self._series["per_request"])
        pace = self._pace()
        q = self._quota
        reach = self._reach_text(positions) if positions else ""
        left = self._left_s()
        renew = fquota.renew_at(rc.clock() if rc else time.time())
        pill = tp.time_pill(remaining if (complete or run is not None) else 0, per, float(pace), q.left, q.keys, reach,
                            run is not None, left, renew, q.capacity, wake_at=self._wake() if run is None else None)
        if not self._info or not self._book:
            pill = tp.TimePill()
        late = "finishes tomorrow" in pill.text
        pop = {"heading": ("This job (from the next start)" if pill.locked else pill.heading),
               "locked": pill.locked, "lockTip": tips.TR_TIME_LOCKED,
               "options": [{"per": o.per, "text": o.text, "time": o.time, "untested": o.untested,
                            "selected": o.selected, "tip": tips.TR_PER[o.per]} for o in pill.options],
               "keysText": "API keys · %d" % pill.keys, "keysTip": tips.TR_KEYS_HEAD,
               "leftText": pill.left_text, "leftLabel": "Requests left today",
               "leftTip": tips.TR_LEFT % ("1 key" if pill.keys == 1 else "%d keys" % pill.keys), "meter": pill.meter, "renew": pill.renew}
        data = {"visible": pill.visible, "text": pill.text, "late": late,
                "tip": tips.TR_TIME_RUNNING if pill.locked else tips.TR_TIME % (reach or "2703-2750"), "pop": pop}
        if data != self._time:
            self._time = data
            self.timeChanged.emit()

    def _problem_counts(self) -> tuple:
        n = len(self._problems)
        failed = any(p.kind == "failed" for p in self._problems)
        return n, failed

    def _compute_tabs(self) -> None:
        n, failed = self._problem_counts()
        other, _pct = self._other()
        rc = self.rc
        row_one = bool(rc and (rc.job_running or rc.sched.wait is not None))
        queue_n = tp.queue_count(len(rc.queue_items()) if rc else 0, row_one)
        # F7: another series runs or waits, or items are queued; this series' own quota wait alone is not a queue
        visible = tp.queue_tab_visible(bool(other), False, len(rc.queue) if rc else 0,
                                       bool(rc and rc.job_running))
        samp = self._samples.get(self._path)
        run = rc.run if rc else None
        unrev = samp["unreviewed"] if samp else 0
        lst = tp.tabs(n, failed, queue_n, visible, samp is not None or bool(run and run.kind == "sample"), unrev)
        tabs = [{"id": i, "text": t, "tone": tone, "tip": (tips.TR_TAB_RED % sum(
            1 for p in self._problems if p.kind == "failed") if i == "problems" and tone == "red" else tips.TR_TAB[i])}
                for i, t, tone in lst]
        if self._tab not in [t["id"] for t in tabs] and tabs:
            self._tab = "chapters"
        if not tabs:
            self._tab = "chapters"
        if tabs != self._tabs_list:
            self._tabs_list = tabs
            self.tabsChanged.emit()

    def _start_facts(self) -> sl.StartFacts:
        rc = self.rc
        v = self._job
        run_here = self._own_running()
        w = rc.quota_wait() if rc else None
        positions = set(self._positions)
        own_unfinished = v.unfinished and not run_here
        run = rc.run if rc else None
        job_book, job_ch = (run.book, set(run.chapters)) if run_here else (v.book, set(v.chapters))
        reach = set(self._reach.positions)
        same = bool(positions) and job_book == self._book and (positions == job_ch or (bool(reach) and reach == job_ch))
        translated = bool(positions) and positions <= self._translated()
        r = self._reach
        return sl.StartFacts(
            has_series=self._info is not None and bool(self._book), selected=bool(positions),
            reach=self._reach_text(), first_blocked=r.first, later_blocked=r.later, review_n=r.terms,
            translated=translated, keys=self._keys_n() > 0, language=bool(self._language()),
            something_runs=bool(rc and rc.job_running), sample_runs=bool(run is not None and run.kind == "sample"),
            quota_waiting=w is not None, quota_back=js.clock_text(w[0]) if w is not None else "",
            own_unfinished=own_unfinished, own_running=run_here, own_same=same and (v.unfinished or run_here),
            foreign=v.foreign)

    def _bar_facts(self) -> tp.BarFacts:
        rc = self.rc
        start = self._start_facts_cached
        if not self._gate_ready and start.enabled and start.kind in REACH_STARTS:
            start = dataclasses.replace(start, enabled=False, why="scan")
        other, _p = self._other()
        state = self._job_state()
        run = self._own_run()
        tr = self._translated()
        infos = self.books.session.infos
        job_left = tp.job_left(self._job_positions(), tr, lambda i: i < len(infos) and infos[i].is_toc is True)
        checkable = [i for i in self._positions if i < len(infos) and (infos[i].done or infos[i].failed)]
        translated = bool(self._positions) and set(self._positions) <= tr
        return tp.BarFacts(
            start=start, tab=self._tab, job_state=state,
            job_reach=self._reach_text(job_left) if state and state != "running" else "",
            job_terms=self._terms_now() if state == "waiting_terms" else 0, another_runs=bool(other),
            foreign=self._job.foreign, keys=self._keys_n() > 0, first_blocked=self._reach.first,
            language=bool(self._language()), translated=translated, reach=self._selection_text(),
            check_reach=self._reach_text(checkable) if checkable else "",
            queue_restart=self._queue_restart() or self._queue_stuck(), running_series=other, error_kind=self._error_kind(), stopping=bool(run and run.stopping))

    def _queue_restart(self) -> bool:
        rc = self.rc
        return bool(rc and len(rc.queue) and rc.sched.halted == jq.Scheduler.RESTART)

    def _queue_stuck(self) -> bool:
        """The queue stopped at an item that cannot start: `Continue queue` goes on from it once it is fixed."""
        rc = self.rc
        return bool(rc and len(rc.queue) and rc.run is None and rc.sched.wait is None
                    and rc.sched.halted not in ("", jq.Scheduler.RESTART))

    def _compute_bar(self) -> None:
        if self._info is None or not self._book:
            segs, bar = [], []
        else:
            self._start_facts_cached = sl.choose(self._start_facts())
            segs = tp.bar_segments(self._bar_facts())
            bar = [_seg(s, self._seg_tip(s)) for s in segs if s.id != "more"]
        more = any(s.id == "more" for s in segs)
        if self._checking and self._tab == "problems":
            bar = [{"id": "checking", "text": "Checking %s · %d %%" % (self._reach_text(), round(self._check_pct * 100)),
                    "tone": "dim", "enabled": False, "tip": tips.TR_BAR["check"]}]
        if bar != self._bar_list or more != self._more:
            self._bar_list, self._more = bar, more
            self.barChanged.emit()

    def _seg_tip(self, s: tp.Segment) -> str:
        t = tips
        reach = self._reach_text()
        st = self._start_facts_cached
        if s.id == "stop":
            return t.TR_BAR["stop"]
        if s.id == "stopping":
            return t.TR_BAR["stopping"]
        if s.id == "dont_resume":
            wake = self._wake()
            return t.TR_BAR["dont_resume"] % (js.clock_text(wake) if wake else "the return time")
        if s.id in ("settings", "open_folder", "check", "continue_queue"):
            return t.TR_BAR[s.id]
        if s.id == "review":
            return t.REVIEW_TERMS[0]
        if s.id == "add_keys":
            return t.ADD_KEYS
        if s.id == "continue":
            if not s.enabled:
                return t.TR_CONTINUE_KEYS
            other, _p = self._other()
            job_left = self._reach_text(tp.job_left(self._job_positions(), self._translated()))
            if other:
                return t.TR_CONTINUE_AFTER % (other, "chapter %s" % job_left.split("-")[0].split(",")[0])
            return t.TR_CONTINUE % job_left
        if s.id in REACH_STARTS:
            if st.why == "scan":
                return t.TR_START_WAIT
            if not s.enabled:
                return {"selection": t.START_NEED_SELECTION, "language": t.TR_START_NEED_LANGUAGE,
                        "done": t.START_DONE, "sample": t.START_SAMPLE_RUNS, "foreign": t.START_ELSEWHERE}.get(st.why, "")
            return self._start_tip(st, reach)
        return ""

    def _start_tip(self, st, reach: str) -> str:
        t = tips
        if st.kind == "queue":
            other, pct = self._other()
            rc = self.rc
            names = [self._name_of(i.series) for i in (rc.queue_items() if rc else [])]
            after = [other] if other else []
            if st.quota_back and not other:
                return t.START_QUEUE_QUOTA[0] % st.quota_back
            return tp.add_to_queue_tip(other, pct, after + names, self._queue_end_estimate())
        if st.kind == "replace":
            return t.START_REPLACE[0]
        if st.kind == "queue_replace":
            return t.START_QUEUE_REPLACE[0]
        return t.START_TRANSLATE[0]

    def _queue_end_estimate(self):
        """When a job queued now would start: after the running job (the sizes of the queued items are not known
        here, so only the running job counts); None while nothing is measured."""
        left = self._left_s()
        rc = self.rc
        return rc.clock() + left if rc is not None and left is not None else None

    # ------------------------------------------------------------- the countdown words
    def _arm_count(self) -> None:
        w = self._cur_word
        if w.key in ("retrying", "paused") and self._cur in self._row_of:
            if not self._count_t.isActive():
                self._count_t.start(COUNT_MS)
        else:
            self._count_t.stop()

    def _countdown(self) -> None:
        k = self._row_of.get(self._cur)
        if k is not None:
            self.chapter_rows.replace({k: self._row(self._cur)})
        self._arm_count()

    # ------------------------------------------------------------- properties read by the screen
    @Property("QVariantMap", notify=topChanged)
    def top(self):
        return self._top

    @Property("QVariantMap", notify=timeChanged)
    def time(self):
        return self._time

    @Property("QVariantList", notify=tabsChanged)
    def tabs(self):
        return self._tabs_list

    @Property(str, notify=tabsChanged)
    def tab(self):
        return self._tab

    @Property("QVariantList", notify=barChanged)
    def bar(self):
        return self._bar_list

    @Property(bool, notify=barChanged)
    def moreVisible(self):
        return self._more

    @Property(str, notify=viewChanged)
    def selectionText(self):
        return self._selection_text()

    @Property(int, notify=viewChanged)
    def unreviewed(self):
        return self._reach.terms

    @Property(bool, notify=viewChanged)
    def foreign(self):
        return self._job.foreign

    @Property(int, notify=viewChanged)
    def currentRow(self):
        return self._row_of.get(self._cur, -1)

    @Slot(str)
    def setTab(self, tab: str) -> None:
        if tab in [t["id"] for t in self._tabs_list] or tab == "chapters":
            self._tab = tab
            self._compute_bar()
            self.tabsChanged.emit()
            self.editorChanged.emit()

    @Slot()
    def headerClicked(self) -> None:
        """The header word Translate (F7): another series runs or waits -> the Queue tab, else scroll to the
        current chapter."""
        other, _p = self._other()
        if tp.header_click(bool(other), self._own_running()) == "queue" and any(
                t["id"] == "queue" for t in self._tabs_list):
            self.setTab("queue")
        else:
            self.setTab("chapters")
            k = self._row_of.get(self._cur, -1)
            if k >= 0:
                self.scrollRequested.emit(k)

    @Slot(int)
    def wordClicked(self, row: int) -> None:
        flags = self.chapter_rows.row(row)[7] if self.chapter_rows.row(row) else ""
        if "terms" in flags.split(","):
            self._review()
        elif "problems" in flags.split(","):
            self.setTab("problems")

    @Slot(int, result="QVariant")
    def wordTip(self, row: int):
        r = self.chapter_rows.row(row)
        pos = self._rows_pos[row] if 0 <= row < len(self._rows_pos) else None
        if not r or pos is None or not r[4]:
            return ""
        ctx = self._row_context()
        w = tp.row_word(self._word_facts(pos, ctx, pos == self._cur, "translated" in r[7].split(","), ctx["run"]),
                        ctx["now"])
        t = tips.TR_WORDS.get(w.key, "")
        if w.key == "resumes":
            wake = self._wake()
            return t % (js.clock_text(wake) if wake else "")
        if w.key == "terms":
            return t % self._gate.get(pos, 0)
        return t

    @Slot(int)
    def readRow(self, row: int) -> None:
        """A translated row opens the reader (Reader tab of Books, 7.16)."""
        if 0 <= row < len(self._rows_pos) and "translated" in self.chapter_rows.row(row)[7].split(","):
            self.books.readChapter(self._rows_pos[row])

    @Slot(int, int)
    def visibleRows(self, first: int, last: int) -> None:
        """The rows the list shows now (the chapter scan serves them first)."""
        if 0 <= first < len(self._rows_pos):
            a = self._rows_pos[first]
            b = self._rows_pos[min(last, len(self._rows_pos) - 1)]
            self.books.visibleRows(a, b)

    # ------------------------------------------------------------- the sink of RunControl
    def runs_changed(self, starting: bool = False, ended=None, tick: bool = False) -> None:
        self._rebuild_rows()
        self._recompute()
        if ended is not None:
            self._ended(ended)
        elif starting:
            self._load_series(job_only=True)
        self._validate_panel()
        self.runTouched.emit()

    def run_progress(self, run) -> None:
        """A throttled snapshot of the running job (at most every 100 ms): the changed rows of the shown chapters,
        one change per run of neighbours, and the few words that move with it."""
        if run.kind == "sample":
            self._compute_top()
            return
        snap = run.snapshot
        if snap is None:
            return
        if run.series == self._path and run.book == self._book:
            old = self._cur
            self._cur = self._current_pos()
            ctx = self._row_context()
            updates: dict = {}
            for i in set(snap.changed) | ({old, self._cur} - {None}):
                k = self._row_of.get(i)
                if k is not None and 0 <= i < len(ctx["infos"]):
                    updates[k] = self._row(i, ctx)
            if updates:
                self.chapter_rows.replace(updates)
            if self._cur != old and self._cur in self._row_of:
                self.scrollRequested.emit(self._row_of[self._cur])
            if snap.edges:
                self._arm_count()
        self._compute_time()
        self._compute_queue()
        self._push_info()
        self.runTouched.emit()

    def message(self, text: str) -> None:
        self.app.message = text

    def closed(self) -> None:
        self.app.run_closed()

    # ------------------------------------------------------------- the end of a run: toasts, reads
    def _ended(self, run) -> None:
        series, name = run.series, run.name
        if run.kind != "job":
            self._sample_ended(run)
            return
        user_stop = run.user_stop
        path, key = self._path, self._key()

        def got(view):
            if self._tracked_wanted(series) or series == self._path:
                self._tracked = (series, view)
            if series == path and self._key() == key:
                self._job = view
            if not user_stop and not self.rc.closing:
                self._announce(name, series, view)
            self._load_series(job_only=True)
            self._gate_done = set()
            self.books.refresh_book()
            self._load_gate()
            self._load_problems()
            self._after_job()
            self._push_info()

        self.lanes.submit(lambda ctx: ftr.job_task(ctx, series), on_result=got, on_error=lambda e: None, lane="data",
                          group="translate-ended")

    def _announce(self, name: str, series: str, view) -> None:
        if view.state == "finished":
            if self.rc.run is not None or (self.rc.queue and not self.rc.sched.halted):
                return                          # the queue goes on: the toast comes when it has ended
            n = view.chapters_total or len(view.chapters)
            self.app.announce("finished", name, "%s · %d chapters translated" % (name, n))
        elif view.state == "failed":
            kind = tp.error_kind(view.error, view.dead)
            if kind in ("key", "model"):
                self.app.announce("key", name, "%s stopped: %s" % (name, "key invalid" if kind == "key"
                                                                      else "model not found"))
            else:
                self.app.announce("failed", name, "%s stopped: %s" % (name, js_short(view.error)))

    def _push_info(self) -> None:
        rc = self.rc
        if rc is None:
            return
        path = rc.tracked_series()
        view = self._tracked[1] if self._tracked[0] == path else (self._job if path == self._path else None)
        blocked = self._reach.first and bool(self._positions) and self.app.screen in ("translate", "export")   # Export shows it too (mock)
        info = run_info(rc, terms_blocked=blocked, view=view)
        key = (dataclasses.replace(info, left_s=None), round_left(info.left_s))
        if key != self._last_info_key:
            self._last_info_key = key
            self.app.set_run_info(info)

    # ------------------------------------------------------------- the queue tab
    def _queue_facts(self, item):
        info = self.books.info(item.series)
        name = info.name if info is not None else self._name_of(item.series)
        book = bookrows.book_label(info, item.book) if info is not None else item.book
        lang = langrules.split(fbooks.series_language(info) or "")[1] if info is not None and fbooks.series_language(
            info) else ""
        return tp.QueueFacts(item.series, name, book, item.reach or "", lang, 0)

    def _queue_rows_data(self):
        rc = self.rc
        if rc is None:
            return None
        now = rc.clock()
        left = self._left_s() if rc.job_running else None
        per = int(self._series["per_request"])
        pace = self._pace()
        running = None
        percent = 0
        wake = None
        if rc.job_running:
            r = rc.run
            running = tp.QueueFacts(r.series, r.name, bookrows.book_label(self.books.info(r.series), r.book)
                                    if self.books.info(r.series) else r.book, self._reach_of_run(r), self._lang_of(r.series))
            percent = rc.percent() or 0
        else:
            w = rc.sched.wait
            if w is not None:
                info = self.books.info(w.series)
                running = tp.QueueFacts(w.series, self._name_of(w.series), "", "", self._lang_of(w.series))
                wake = w.wake_at
        for i in rc.queue_items():
            if i.reach:
                self._queued_reach[(i.series, i.book)] = i.reach
        items = [self._queue_facts(i) for i in rc.queue_items()]
        rows = tp.queue_rows(running, percent, left, items, self._queue_restart(), wake, now, 60.0 / max(1, pace) / max(1, per))
        return rows

    def _reach_of_run(self, r) -> str:
        if self._run_reach[0] is r:
            return self._run_reach[1]
        info = self.books.session.infos
        text = ""
        if r.series == self._path and r.book == self._book and info:
            text = bookrows.range_text(info, [c for c in r.chapters if c < len(info)])
        else:                                   # another series: the reach its queue item showed (none for a plain start)
            text = self._queued_reach.get((r.series, r.book), "")
        self._run_reach = (r, text)
        return text

    def _lang_of(self, series: str) -> str:
        info = self.books.info(series)
        target = fbooks.series_language(info) if info is not None else None
        return langrules.split(target)[1] if target else ""

    def _compute_queue(self) -> None:
        rows = self._queue_rows_data() or []
        rc = self.rc
        stuck = ""
        if rc is not None and rc.run is None and rc.sched.wait is None and rc.sched.halted not in ("", jq.Scheduler.RESTART):
            stuck = rc.sched.why
        head = 1 if rows and rows[0].running else 0
        data = []
        for k, r in enumerate(rows):
            flags = ",".join(f for f, on in (("running", r.running), ("up", r.up), ("down", r.down),
                                             ("wait", r.dont_resume), ("stuck", bool(stuck) and k == head)) if on)
            why = stuck if "stuck" in flags else ""
            tip = tips.TR_QUEUE_WHY % (why, r.name) if why else (
                tips.TR_WORDS["resumes"] % r.start if r.dont_resume else r.tip)
            data.append((r.series, r.start, r.name, r.detail, r.percent if r.running else -1, flags, why, tip))
        if data != self.queue_rows.rows:
            self.queue_rows.set_rows(data)
            self.queueChanged.emit()

    @Property(bool, notify=queueChanged)
    def queueRestart(self):
        return self._queue_restart()

    @Slot(int)
    def queueUp(self, row: int) -> None:
        self._queue_move(row, -1)

    @Slot(int)
    def queueDown(self, row: int) -> None:
        self._queue_move(row, 1)

    def _queue_series(self, row: int) -> str:
        r = self.queue_rows.row(row)
        return r[0] if r and "running" not in r[5] else ""

    def _queue_move(self, row: int, delta: int) -> None:
        s = self._queue_series(row)
        if s and self.rc:
            self.rc.move(s, delta)

    @Slot(int)
    def queueRemove(self, row: int) -> None:
        s = self._queue_series(row)
        if s and self.rc:
            self.rc.dequeue(s)

    @Slot()
    def queueStop(self) -> None:
        if self.rc:
            self.rc.stop()

    @Slot()
    def queueDontResume(self) -> None:
        self._dont_resume()

    @Slot(int)
    def queueOpen(self, row: int) -> None:
        """A series name of the Queue tab opens that series on Translate."""
        r = self.queue_rows.row(row)
        if r:
            self.books.selectSeries(r[0])
            self._tab = "chapters"

    # ------------------------------------------------------------- starting: every start goes through RunControl
    @Slot(str)
    def act(self, seg_id: str) -> None:
        """A segment of the bottom bar."""
        h = {"translate": self._start_selection, "queue": self._queue_selection, "replace": self._ask_replace,
             "queue_replace": self._ask_replace, "review": self._review, "add_keys": self.app.openSettings,
             "stop": self._stop, "continue": self._continue, "dont_resume": self._dont_resume,
             "settings": self.app.openSettings, "check": self.check, "continue_queue": self._continue_queue,
             "open_folder": self._open_folder}.get(seg_id)
        if h is not None:
            h()

    def _stop(self) -> None:
        if self.rc:
            self.rc.stop()

    def _continue_queue(self) -> None:
        if self.rc:
            self.rc.continue_queue()

    def _open_folder(self) -> None:
        self.openFolderRequested.emit(self._path)

    def _review(self) -> None:
        if self.terms is not None:
            self.terms.selectTab("blocking")
        self.app.go("terms")

    def _start_positions(self) -> list:
        """The chapters a start covers: the reach when terms hold a later chapter back."""
        return list(self._reach.positions or self._positions)

    def _start_selection(self) -> None:
        st = self._start_facts_cached
        if not st.enabled:
            return
        self._go_start(self._path, self._book, self._start_positions())

    def _go_start(self, path: str, book: str, chapters, retry=()) -> None:
        """Rule (b) first (terms saved, state written, every book closed), then the one start path."""
        if self._pending_start or self.rc is None:
            return
        self._pending_start = True

        def ready():
            self._pending_start = False
            why = self.rc.start(path, book, list(chapters), retry=tuple(retry))
            if why:
                self.app.message = why

        self.order.before_book_work(ready, folder=path)

    def _item(self, positions, resume=False, replace=False, retry=()) -> jq.Item:
        reach = bookrows.range_text(self.books.session.infos, positions) if positions else ""
        return jq.Item(self._path, self._book, jq.spans_of(positions), resume, replace, reach, tuple(retry))

    def _queue_selection(self) -> None:
        if not self._start_facts_cached.enabled:
            return
        self._enqueue(self._item(list(self._positions)))

    def _enqueue(self, item: jq.Item) -> None:
        rc = self.rc
        old = rc.queued(item.series)
        if old is not None and old != item:
            self._open_panel("replaceItem", self._replace_item_data(old, item), valid=lambda s=item.series:
                             rc.queued(s) is not None, ok=lambda: rc.enqueue(item))
        else:
            rc.enqueue(item)

    def _ask_replace(self) -> None:
        st = self._start_facts_cached
        if not st.enabled:
            return
        positions = self._start_positions()
        queue = st.kind == "queue_replace"
        v = self._job
        path, book = self._path, self._book
        item = self._item(list(self._positions), replace=True) if queue else None
        self._open_panel("queueReplace" if queue else "replace", self._replace_data(queue, v, positions),
                         valid=lambda: self._job.unfinished and self._path == path and self._book == book and
                         not self._own_running(),
                         ok=(lambda: self._enqueue(item)) if queue else (lambda: self._go_start(path, book, positions)))

    def _continue(self) -> None:
        rc = self.rc
        seg = next((s for s in tp.bar_segments(self._bar_facts()) if s.id == "continue"), None)
        if seg is None or not seg.enabled:
            return
        other, _p = self._other()
        if other or rc.job_running:
            v = self._job
            self._enqueue(jq.Item(self._path, v.book, jq.spans_of(v.chapters), True, False,
                                  self._reach_text(tp.job_left(self._job_positions(), self._translated()))))
            return
        self._go_resume()

    def _go_resume(self) -> None:
        if self._pending_start or self.rc is None:
            return
        self._pending_start = True
        path = self._path

        def ready():
            self._pending_start = False
            why = self.rc.start(path, "", [], resume=True)
            if why:
                self.app.message = why

        self.order.before_book_work(ready, folder=path)

    def _dont_resume(self) -> None:
        """`Don't resume`: the job stays stopped; the window's wait ends, or the saved record is rewritten."""
        rc = self.rc
        if rc is None:
            return
        w = rc.sched.wait
        if w is not None:
            rc.stop_wait()
            self._load_series(job_only=True)
            return
        path = self._path
        def done(_ok):
            if rc.waiting_elsewhere is not None and rc.waiting_elsewhere[1] == path:
                rc.waiting_elsewhere = None
            self._load_series(job_only=True)
            self._recompute()

        self.lanes.submit(lambda ctx: frun.set_job_state(path, "stopped"), on_result=done, on_error=lambda e: None,
                          lane="data")

    # ------------------------------------------------------------- job menu (the ••• beside the bar)
    @Slot(result="QVariantList")
    def moreItems(self):
        items = [{"id": "discard", "text": "Discard job"}]
        if self._job_state() == "failed":
            items.append({"id": "details", "text": "Copy details"})
        return items

    @Slot(str)
    def moreAct(self, item_id: str) -> None:
        if item_id == "discard":
            self._ask_discard()
        elif item_id == "details":
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(self._job.error or self.rc.last_start_error)

    def _ask_discard(self) -> None:
        v = self._job
        if not v.unfinished or self._own_running():
            return
        path = self._path
        self._open_panel("discard", self._discard_data(v), valid=lambda: self._job.unfinished and self._path == path
                         and not self._own_running(), ok=lambda: self._discard(path))

    def _discard(self, path: str) -> None:
        self.rc.discard(path)
        self._load_series(job_only=True)

    # ------------------------------------------------------------- panels (9.12, 13.12)
    @Property(str, notify=panelChanged)
    def panel(self):
        return self._panel

    @Property("QVariantMap", notify=panelChanged)
    def panelData(self):
        return self._panel_data

    def _parts(self, *items) -> list:
        """Lines of a panel: a part is (text, bright); a `\\n` part starts a new line."""
        return [{"text": t, "bright": b} for t, b in items]

    def _replace_data(self, queue: bool, view, positions) -> dict:
        infos = self.books.session.infos
        name = self._info.name if self._info else ""
        job_reach = self._reach_text(tp.job_left(self._job_positions(), self._translated()))
        new = bookrows.range_text(infos, positions) if positions else self._selection_text()
        head = "Queue and replace the job?" if queue else "Replace the job?"
        lines = [(name, True), (" has an unfinished job: chapters %s are not translated yet. " % job_reach, False),
                 ("The new job translates %s instead; %s can be started again later." % (new, job_reach), False),
                 ("\n", False), ("Everything translated stays.", False)]
        return {"title": head, "parts": self._parts(*lines), "ok": "Queue" if queue else "Replace job",
                "cancel": "Cancel"}

    def _replace_item_data(self, old, item) -> dict:
        name = self._name_of(item.series)
        book = bookrows.book_label(self.books.info(item.series), item.book) if self.books.info(item.series) else item.book
        lines = [("The queue already has ", False), (name, True), (" · %s · %s. It becomes " % (book, old.reach), False),
                 (name, True), (" · %s · %s." % (book, item.reach), False)]
        return {"title": "Replace the queued item?", "parts": self._parts(*lines), "ok": "Replace", "cancel": "Cancel"}

    def _discard_data(self, v) -> dict:
        name = self._info.name if self._info else ""
        book = bookrows.book_label(self._info, v.book) if self._info and v.book else v.book
        reach = self._reach_text(tp.job_left(self._job_positions(), self._translated()))
        done = len(v.chapters) - len(tp.job_left(self._job_positions(), self._translated())) if v.chapters else 0
        kept = max(0, v.chapters_done or done)
        if kept == 0:
            tail = "Nothing is translated yet."
        elif kept == 1:
            tail = "The 1 chapter translated so far stays."
        else:
            tail = "The %d chapters translated so far stay." % kept
        lines = [(name, True), (" · %s · %s will not be continued. " % (book, reach), False), (tail, False)]
        return {"title": "Discard the job?", "parts": self._parts(*lines), "ok": "Discard", "cancel": "Cancel"}

    def _open_panel(self, name: str, data: dict, valid=None, ok=None) -> None:
        self._panel, self._panel_data = name, data
        self._panel_valid, self._panel_ok = valid, ok
        self.app.show_panel("translate", {"kind": name})
        self.panelChanged.emit()

    def _close_panel(self, cancel: bool = True) -> None:
        if not self._panel:
            return
        self._panel, self._panel_data, self._panel_valid, self._panel_ok = "", {}, None, None
        if self.app.panel == "translate":
            self.app.closePanel()
        self.panelChanged.emit()

    def _validate_panel(self) -> None:
        """13.12: a confirmation whose subject changed underneath closes itself as Cancel."""
        if self._panel and self._panel not in ("prompt",) and self._panel_valid is not None and not self._panel_valid():
            self._close_panel()

    @Slot()
    def panelOk(self) -> None:
        ok = self._panel_ok
        valid = self._panel_valid
        if self._panel == "prompt":
            return
        self._close_panel()
        if ok is not None and (valid is None or valid()):
            ok()

    @Slot()
    def panelCancel(self) -> None:
        if self._panel == "prompt":
            return
        self._close_panel()

    def _app_panel_changed(self) -> None:
        """Esc or a click outside closed the shell's panel: ours is gone with it."""
        if self._panel and self.app.panel != "translate":
            if self._panel == "prompt":
                self.promptClosed(self._draft_name, self._draft_text, True)
            self._panel, self._panel_data, self._panel_valid, self._panel_ok = "", {}, None, None
            self.panelChanged.emit()

    # ------------------------------------------------------------- the top row: To, Prompt, Per request
    @Slot(str, result="QVariantList")
    def languageEntries(self, query: str) -> list:
        from ..ctl import termrows as tr
        from .. import termtips
        lock = self._language_lock() if self._language() else ""
        locked = bool(lock) and self._language() != ""
        return tr.language_entries(query, self._language(), self._series.get("source_tag", ""), locked,
                                   termtips.ENGLISH_LATER, langrules.lock_reason(self._series["translated"],
                                                                                 self._series["confirmed"]))

    @Slot(str)
    def chooseLanguage(self, target: str) -> None:
        if self._info is None or self._language_lock():
            return
        if target.startswith("use:"):
            target = self._typed_language(target[4:])
        if not target or target == self._language():
            return
        path = self._path

        def done(_r):
            self.books.reload(then=lambda infos: self._sync())

        self.lanes.submit(lambda ctx: fbooks.set_series_language(path, target), on_result=done,
                          on_error=lambda exc: setattr(self.app, "message", "The language could not be saved: %s." % exc),
                          lane="data")

    def _typed_language(self, text: str) -> str:
        text = text.strip()
        if ":" not in text:
            tag = next((t for t, n in langrules.NAMES.items() if n.lower() == text.lower()), "")
            if not tag:
                self.app.message = langrules.FORMAT_HELP
                return ""
            text = "%s:%s" % (tag, langrules.NAMES[tag])
        try:
            return langrules.parse_other(text)
        except ValueError as exc:
            self.app.message = str(exc)
            return ""

    @Slot(int)
    def setPerRequest(self, n: int) -> None:
        """1 | 5 | 10 per request, locked while this series translates (applies from the next start)."""
        if n not in tp.PER_REQUEST or self._own_running() or not self._path:
            return
        path = self._path
        self._series = dict(self._series, per_request=n)
        self._compute_time()
        self.lanes.submit(lambda ctx: ftr.save_per_request_task(ctx, path, n), on_error=lambda e: None, lane="data")

    @Slot()
    def openKeys(self) -> None:
        self.app.openSettings()

    # ---- prompts
    @Slot(result="QVariantList")
    def promptEntries(self):
        cur = str(self._series["prompt"])
        names = [n for n in self.prompts.names() if n.lower() != RESERVED]
        out = [{"id": "default", "text": "Default", "current": cur.lower() == RESERVED, "deletable": False}]
        out += [{"id": n, "text": n, "current": n == cur, "deletable": True} for n in names]
        out.append({"id": "+new", "text": "+ New prompt", "current": False, "deletable": False})
        return out

    @Slot(str)
    def choosePrompt(self, name: str) -> None:
        if not self._path or self._job.foreign:
            return
        if name == "+new":
            self.promptEdit(True)
            return
        path = self._path
        text = None if name == "default" else self.prompts.read(name)
        if name != "default" and text is None:
            self.app.message = "The prompt %s cannot be read." % name
            return
        self._series = dict(self._series, prompt=name)
        self._compute_top()
        self.lanes.submit(lambda ctx: fbooks.apply_prompt(path, name, text), on_error=lambda e: None, lane="data")

    @Slot(str)
    def deletePrompt(self, name: str) -> None:
        text = self.prompts.read(name)
        if text is None or name.lower() == RESERVED:
            return
        self.prompts.delete(name)
        self._prompt_trash = (name, text)
        if str(self._series["prompt"]) == name:
            self.choosePrompt("default")
        self.promptDeleted.emit(name)
        self.topChanged.emit()

    @Slot()
    def undoPromptDelete(self) -> None:
        if self._prompt_trash:
            name, text = self._prompt_trash
            self._prompt_trash = None
            try:
                self.prompts.save(name, text)
            except (ValueError, OSError):
                pass
            self.topChanged.emit()

    _draft_name = ""
    _draft_text = ""

    @Slot(bool)
    def promptEdit(self, fresh: bool = False) -> None:
        """The prompt editor of this series; unsaved text from the last time is kept as a draft (9.2)."""
        if not self._path or self._panel:
            return
        name = "" if fresh else str(self._series["prompt"])
        name = "" if name.lower() == RESERVED else name
        path = self._path
        text = "" if fresh else fbooks.current_prompt_text(path)
        draft = self.app.win.prompt_draft(path)
        orig = (name, text)
        if draft is not None and draft != orig:
            name, text = draft
        self._draft_name, self._draft_text, self._prompt_orig = name, text, orig
        self._open_panel("prompt", {"title": "Prompt", "name": name, "text": text, "draft": draft is not None and draft != orig,
                                    "error": self._prompt_error(name), "ok": "Save", "cancel": "Cancel"})

    def _prompt_error(self, name: str) -> str:
        name = name.strip()
        if not name:
            return "Give the prompt a name."
        if name.lower() == RESERVED:
            return "Default is the name of the shipped prompt. Choose another name."
        return ""

    @Slot(str, str, result=str)
    def promptChanged(self, name: str, text: str) -> str:
        """The editor's fields changed; returns why Save is dim ("" = it can save)."""
        self._draft_name, self._draft_text = name, text
        return self._prompt_error(name)

    @Slot(str, str)
    def promptSave(self, name: str, text: str) -> None:
        if self._prompt_error(name) or not self._path:
            return
        try:
            clean = self.prompts.save(name.strip(), text)
        except (ValueError, OSError) as exc:
            self.app.message = "The prompt was not saved: %s" % exc
            return
        path = self._path
        self.app.win.clear_prompt_draft(path)
        self._series = dict(self._series, prompt=clean)
        self._finish_prompt()
        self.lanes.submit(lambda ctx: fbooks.apply_prompt(path, clean, text), on_error=lambda e: None, lane="data")
        self._compute_top()

    @Slot(str, str, bool)
    def promptClosed(self, name: str, text: str, keep: bool) -> None:
        """Cancel throws the edit away; Esc and a click outside keep it as a draft (9.2)."""
        if self._panel != "prompt" and not keep:
            return
        path = self._path
        if path:
            if keep and (name, text) != getattr(self, "_prompt_orig", ("", "")):
                self.app.win.set_prompt_draft(path, name, text)
            else:
                self.app.win.clear_prompt_draft(path)
        if self._panel == "prompt":
            self._finish_prompt()

    def _finish_prompt(self) -> None:
        self._panel, self._panel_data, self._panel_valid, self._panel_ok = "", {}, None, None
        if self.app.panel == "translate":
            self.app.closePanel()
        self.panelChanged.emit()

    # ------------------------------------------------------------- the Sample
    @Slot()
    def sample(self) -> None:
        rc = self.rc
        if rc is None:
            return
        run = rc.run
        if run is not None and run.kind == "sample":
            rc.stop()
            return
        if not self._top.get("sampleEnabled") or not self._positions:
            return
        chapter = min(self._positions)
        path, book = self._path, self._book
        self._samples[path] = {"chapter": chapter, "title": "", "rows": [], "unreviewed": self._gate.get(chapter, 0),
                               "pending": True}
        why = rc.start_sample(path, book, chapter, SAMPLE_BLOCKS)
        if why:
            self._samples.pop(path, None)
            self.app.message = why
            return
        self._tab = "sample"
        self._compute_tabs()
        self.sampleChanged.emit()
        self.tabsChanged.emit()

    def _sample_ended(self, run) -> None:
        s = self._samples.get(run.series)
        if s is None:
            self._compute_top()
            return
        path, book, chapter = run.series, run.book, s["chapter"]

        def got(rows):
            cur = self._samples.get(path)
            if cur is None:
                return
            cur["rows"] = [{"src": a, "tr": b or "", "failed": bool(c)} for a, b, c in rows]
            cur["pending"] = False
            self._compute_tabs()
            self.sampleChanged.emit()
            self.tabsChanged.emit()

        def failed(exc):
            self._samples.pop(path, None)
            self._compute_tabs()
            self.tabsChanged.emit()
            self.sampleChanged.emit()

        self.lanes.submit(lambda ctx: frun.sample_rows(path, book, chapter, SAMPLE_BLOCKS), on_result=got,
                          on_error=failed, lane="read")
        self._compute_top()

    @Property("QVariantMap", notify=sampleChanged)
    def sampleResult(self):
        s = self._samples.get(self._path)
        if s is None:
            return {"open": False}
        infos = self.books.session.infos
        n = bookrows.shown_numbers([infos[s["chapter"]]])[0] if s["chapter"] < len(infos) else s["chapter"] + 1
        title = "Sample" if not s["unreviewed"] else "Sample · %d %s unreviewed" % (
            s["unreviewed"], "term" if s["unreviewed"] == 1 else "terms")
        run = self.rc.run if self.rc else None
        busy_now = bool(run is not None and run.kind == "sample")
        return {"open": True, "title": title, "sub": "chapter %s · first %d blocks" % (n, SAMPLE_BLOCKS),
                "rows": s["rows"], "pending": s["pending"] or busy_now,
                "unreviewedTip": tips.TR_SAMPLE_UNREVIEWED % s["unreviewed"] if s["unreviewed"] else ""}

    # ------------------------------------------------------------- Problems: the row editor, Check
    @Property(int, notify=problemsChanged)
    def problemCount(self):
        return len(self._problems)

    @Property("QVariantMap", notify=editorChanged)
    def editor(self):
        i = self.problem_rows.cursor
        if not 0 <= i < len(self._problems):
            return {"open": False}
        p = self._problems[i]
        infos = self.books.session.infos
        return {"open": True, "index": i, "source": p.source, "text": p.text if p.is_finding else "",
                "reason": p.reason, "detail": p.detail, "finding": p.is_finding,
                "reasonTip": tips.TR_PROBLEM["failed"] if not p.is_finding else p.detail,
                "canResolve": self._can_resolve(p)}

    def _can_resolve(self, p) -> bool:
        run = self._own_run()
        return ordering.resolve_allowed(run.series if run else "", run.chapters if run else (), self._path, [p.chapter])

    @Slot(int)
    def selectProblem(self, row: int) -> None:
        self.problem_rows.set_cursor(-1 if row == self.problem_rows.cursor else row)
        self.editorChanged.emit()

    def _row_problem(self):
        i = self.problem_rows.cursor
        return self._problems[i] if 0 <= i < len(self._problems) else None

    @Slot()
    def retryProblem(self) -> None:
        """Translate the block again: it goes through the start rules (a job of this series asks first, one that runs
        elsewhere queues)."""
        p = self._row_problem()
        if p is None or self.rc is None:
            return
        mark = p.mark() if p.is_finding else None
        marks = (mark,) if mark else ()
        positions = [p.chapter]
        rc, path, book = self.rc, self._path, self._book
        if rc.job_running or rc.quota_wait() is not None:
            self._enqueue(self._item(positions, replace=self._job.unfinished, retry=marks))
        elif self._job.unfinished:
            self._open_panel("replace", self._replace_data(False, self._job, positions),
                             valid=lambda: self._job.unfinished and self._path == path,
                             ok=lambda: self._go_start(path, book, positions, marks))
        else:
            self._go_start(path, book, positions, marks)

    @Slot()
    def keepProblem(self) -> None:
        self._resolve("keep", "")

    @Slot(str)
    def saveProblem(self, text: str) -> None:
        if text.strip():
            self._resolve("manual", text)

    def _resolve(self, action: str, typed: str) -> None:
        p = self._row_problem()
        if p is None or not self._can_resolve(p):
            return
        path, book = self._path, self._book
        self.lanes.submit(lambda ctx: fchecks.resolve_problems_task(ctx, path, book, [p], action, typed),
                          on_result=lambda n: self._resolved(), on_error=lambda e: setattr(
                              self.app, "message", "The block could not be saved: %s." % e), lane="data")

    def _resolved(self) -> None:
        self.books.refresh_book()
        self._load_problems()

    @Slot()
    def ignoreProblem(self) -> None:
        p = self._row_problem()
        if p is None or not p.is_finding:
            return
        path, book = self._path, self._book
        self.lanes.submit(lambda ctx: fchecks.ignore_task(ctx, path, book, [p]), on_result=lambda n: self._load_problems(),
                          on_error=lambda e: None, lane="data")

    @Slot()
    def check(self) -> None:
        """`Check a-b`: the core's checks over the selected chapters that have a translation; findings join the list."""
        infos = self.books.session.infos
        chapters = [i for i in self._positions if i < len(infos) and (infos[i].done or infos[i].failed)]
        if not chapters or self._checking:
            return
        path, book, key = self._path, self._book, self._key()
        self._checking, self._check_pct = True, 0.0
        self._compute_bar()
        self.checkChanged.emit()

        def item(it):
            if it and it[0] == "check" and it[2]:
                self._check_pct = it[1] / it[2]
                self._compute_bar()

        def done(_r):
            self._checking = False
            self._compute_bar()
            self.checkChanged.emit()
            if self._key() == key:
                self._load_problems()

        def failed(exc):
            self._checking = False
            self._compute_bar()
            self.app.message = "The check could not run: %s." % exc

        def go():
            if self.crunch is not None:
                self._check_token = self.crunch.submit("check", {"series_path": path, "book": book, "chapters": chapters},
                                                       on_result=done, on_error=failed, on_item=item)
            else:
                self.lanes.submit(lambda ctx: fchecks.check_task(ctx, path, book, chapters), on_result=done,
                                  on_error=failed, on_item=item, lane="read")

        self.order.before_book_work(go, folder=path)

    @Property(bool, notify=checkChanged)
    def checking(self):
        return self._checking

    @Property(float, notify=checkChanged)
    def checkPercent(self):
        return self._check_pct

    @Slot(int)
    def showProblemAt(self, position: int) -> None:
        """A jump from Export (`1 problem`) lands on the Problems tab at that chapter."""
        self.setTab("problems") if self._problems else None
        for k, p in enumerate(self._problems):
            if p.chapter == position:
                self.problem_rows.set_cursor(k)
                self.editorChanged.emit()
                return

    # ------------------------------------------------------------- closing and the end
    @Slot()
    def stopForClose(self) -> None:
        """The window is closing while a run goes on (9.11): RunControl stops it and calls `closed()` when the requests
        in flight have ended (or after the cap)."""
        rc = self.rc
        if rc is not None and (rc.run is not None or rc.sched.wait is not None):
            rc.shutdown()

    def shutdown(self) -> None:
        for t in (self._sync_t, self._count_t):
            t.stop()


def js_short(text: str, n: int = 80) -> str:
    return js.shorten(text, n) if text else "an error"
