"""Step 3: translate the selected chapters. Two zones, each with its own controls (window_spec 7.2a):

zone 1 is the job of THIS series (running or unfinished): Stop, Continue, the state chip; zone 2 is the selected
chapters: one start button whose label says what it will do and how far it reaches, `Review N terms`, `Sample`.
The queue sits under them. Every start goes through `app.runs.start` (runctl.py): this step only asks.
"""

from __future__ import annotations

import time
import tkinter as tk

from . import accent, header, jobqueue, langrules, pieces, startlabel, tips, zonestate
from . import chapterlogic as cl
from . import jobstate as js
from . import model
from .dialog import confirm, message
from .keystore import RESERVED
from .queue_view import QueueList
from .running_view import RunningTable, Row, build_rows, current_of
from .startlabel import StartFacts
from .step import Step
from .theme import ACCENT, BG, BRIGHT, DIM, FAINT, TEXT
from .tooltip import attach_tip
from .translate_parts import ProblemsPanel, PromptEditor, SamplePanel
from .widgets import DotsButton, Field, Pill, Segmented
from .zonestate import ZoneFacts

PER_REQUEST = (1, 5, 10)
TRACK = "#1c1c1c"


def _packed(w) -> bool:
    """Whether a widget is placed in its parent (`winfo_ismapped` is false for all of them while the step is hidden)."""
    return bool(w.winfo_manager())

BAR = "#d0d0d0"


class TranslateStep(Step):
    key = "translate"
    label = "Translate"

    def __init__(self, master, app):
        super().__init__(master, app)
        ui = self.ui
        f = ui.font
        self.gap = gap = int(ui.ls * 0.8)
        self.runs = app.runs
        self.view = js.JobView()
        self.terms_now = None
        self.problems: list = []
        self.problems_token = None
        self.checking = ""                  # series folder of a running check, "" = none
        self._jump = None                   # chapter the problem list should land on once it is loaded
        self.sample_info = None             # (series, book, chapter, blocks) of the sample shown
        self.sample_unrev = 0
        self.samples: dict = {}             # series folder -> (sample_info, unreviewed) kept until the next Sample
        self.pending_confirm = False
        self._terms_token = None
        self._tick_job = None
        self._book_job = None
        self._tick_n = 0
        self._quota = model.Quota()
        self._est = None
        self.owner = ""
        self.zone = zonestate.Zone1()
        self.start = startlabel.Start("none")
        self.run_rows: dict = {}            # chapter -> Row of the running screen
        self._run_key = None
        self._sample_blocks = 50

        # -- settings of the series
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(0, gap))
        tk.Label(top, text="Prompt", bg=BG, fg=DIM, font=f).pack(side="left", padx=(0, gap // 2))
        self.prompt_btn = Pill(top, "Default  ▾", self._open_prompts, f)
        self.prompt_btn.pack(side="left")
        self.edit_btn = Pill(top, "Edit", self._edit_prompt, f, kind="dim")
        self.edit_btn.pack(side="left", padx=(gap // 2, 0))
        self.to_btn = Pill(top, "To  ▾", self._open_language, f)
        self.to_btn.pack(side="left", padx=(gap, 0))
        self.per_seg = Segmented(top, f, self._per_request_picked)
        self.per_seg.set_items([(str(n), str(n), None) for n in PER_REQUEST], "5")
        self.per_seg.pack(side="right")
        tk.Label(top, text="Per request", bg=BG, fg=DIM, font=f).pack(side="right", padx=(0, gap // 2))
        attach_tip(self.prompt_btn, ui.tip, lambda e: self._lock_tip(tips.PROMPT_LIVE))
        attach_tip(self.edit_btn, ui.tip, lambda e: self._lock_tip((
            "Write or change a prompt. It is saved under its name and becomes the prompt of this series; while a "
            "translation runs it applies from the next chapter.", [("Saved in", "the app data folder")])))
        attach_tip(self.to_btn, ui.tip, lambda e: self._to_tip())
        attach_tip(self.per_seg, ui.tip, lambda e: tips.PER_REQUEST_LOCKED if self._per_locked()
                   else self._lock_tip(tips.PER_REQUEST))

        # -- zone 1: the job of this series
        self.zone1 = tk.Frame(self, bg=BG)
        z1 = tk.Frame(self.zone1, bg=BG)
        z1.pack(fill="x", pady=(0, gap))
        self.z1_btn = Pill(z1, "Continue", self._z1_clicked, f, kind="plain", padx=int(ui.ls * 1.6))
        self.z1_btn.pack(side="left")
        self.z1_btn2 = Pill(z1, "Settings", self._z1_second, f, kind="plain")
        self.z1_more = DotsButton(z1, int(ui.ls * 1.25), self._z1_more)
        self.z1_more.pack(side="right")
        self.chip = tk.Label(z1, text="", bg=BG, fg=DIM, font=f, anchor="e", cursor="arrow")
        self.chip.pack(side="right", padx=(0, gap))
        attach_tip(self.z1_btn, ui.tip, lambda e: self._z1_tip())
        attach_tip(self.z1_btn2, ui.tip, lambda e: self._z1_second_tip())
        attach_tip(self.z1_more, ui.tip, lambda e: tips.Z1_MORE)
        attach_tip(self.chip, ui.tip, lambda e: self._chip_tip())
        self.chip.bind("<Button-1>", lambda e: self._chip_clicked())

        # -- progress and numbers
        self.prog = tk.Frame(self, bg=BG)
        self.prog.pack(fill="x")
        pr = tk.Frame(self.prog, bg=BG)
        pr.pack(fill="x")
        self.numbers = tk.Label(pr, text="", bg=BG, fg=TEXT, font=f, anchor="w")
        self.numbers.pack(side="left")
        self.quota = tk.Label(pr, text="", bg=BG, fg=DIM, font=f, anchor="e")
        self.quota.pack(side="right")
        self.bar = tk.Canvas(self.prog, height=max(3, int(ui.ls * 0.2)), bg=BG, highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(int(ui.ls * 0.3), gap))
        self.bar.bind("<Configure>", lambda e: self._draw_bar())
        attach_tip(self.numbers, ui.tip, lambda e: (
            "Blocks and chapters of this job that are translated, out of all of them.",
            [("Comes from", "the translation logs"), ("You can edit", "no")]))
        attach_tip(self.quota, ui.tip, lambda e: self._quota_tip())

        # -- zone 2: the selected chapters
        act = tk.Frame(self, bg=BG)
        act.pack(fill="x", pady=(0, gap))
        self.act = act
        self.main_btn = Pill(act, "Translate", self._main_clicked, f, kind="plain", padx=int(ui.ls * 1.6))
        self.main_btn.pack(side="left")
        self.review_btn = Pill(act, "Review terms", self._review_clicked, f, kind="plain")
        self.sample_btn = Pill(act, "Sample", self._sample_clicked, f, kind="dim")
        self.sample_btn.pack(side="left", padx=(gap, 0))
        self.sample_n = Field(act, f, width=ui.cw * 6)
        self.sample_n.set("50")
        self.sample_n.pack(side="left", padx=(gap // 2, 0))
        self.check_btn = Pill(act, "Check", self._check_clicked, f, kind="dim")
        self.check_btn.pack(side="left", padx=(gap, 0))
        attach_tip(self.check_btn, ui.tip, lambda e: self._check_tip())
        attach_tip(self.main_btn, ui.tip, lambda e: self._main_tip())
        attach_tip(self.review_btn, ui.tip, lambda e: tips.fill(tips.REVIEW_TERMS, self.start.review))
        attach_tip(self.sample_btn, ui.tip, lambda e: self._sample_tip())
        attach_tip(self.sample_n.entry, ui.tip, lambda e: "How many blocks of the chapter to translate for the sample.")

        # -- content: queue, sample panes, the running screen, failed blocks
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.queue_list = QueueList(self, ui, app, place_opts={"before": self.content})
        self.sample = SamplePanel(self.content, ui, self._close_sample)
        self.running_table = RunningTable(self.content, ui)
        self.running_table.wire_tips()
        self.problems_panel = ProblemsPanel(self.content, ui, self._retry, self._keep, self._save_typed,
                                           self._ignore)

        self._tick_job = self.after(500, self._tick)
        self._update_controls()

    # ------------------------------------------------------------- the run, as the window sees it
    @property
    def running(self) -> bool:
        return self.runs.running

    @property
    def handle(self):
        return self.runs.run.handle if self.runs.run is not None else None

    @property
    def run_kind(self) -> str:
        return self.runs.run.kind if self.runs.run is not None else ""

    @property
    def stopping(self) -> bool:
        return bool(self.runs.run is not None and self.runs.run.stopping)

    def _path(self) -> str:
        return self.app.series.path if self.app.series is not None else ""

    def _run_here(self):
        """The running job when it is the job of the series shown, else None."""
        r = self.runs.run
        return r if (r is not None and r.kind == "job" and r.series == self._path()) else None

    # ------------------------------------------------------------- life
    def on_show(self):
        if self._book_job is not None:
            self.after_cancel(self._book_job)
            self._book_job = None
        self.refresh_all()

    def on_language(self):
        self._sync_settings()
        self._update_controls()

    def on_series(self):
        self._close_sample(keep=True)
        self.problems = []
        self.problems_panel.pack_forget()
        self._run_key = None
        self.refresh_all()
        kept = self.samples.get(self._path())
        if kept is not None and self.app.series is not None:
            self.sample_info, self.sample_unrev = kept
            self._show_sample_rows()

    def on_book(self):
        """The volume changed: the job and the numbers are read a moment later, so that the opening of a big volume
        does not hold the window (a series of 4000 chapters has other work to do in this turn)."""
        if self._book_job is None:
            self._book_job = self.after(25, self._book_now)

    def _book_now(self):
        self._book_job = None
        if self.winfo_exists():
            self.refresh_all()

    def on_selection(self):
        self._update_controls()
        self._refresh_numbers()
        self._refresh_quota()

    def on_infos(self):
        self._update_controls()

    def on_terms(self):
        self._update_controls()

    def refresh_all(self) -> None:
        s = self.app.series
        self.view = model.job_view(s.path) if s else js.JobView()
        self._sync_settings()
        self._check_terms()
        self._load_problems()
        self._update_controls()
        self._refresh_numbers()
        self._refresh_quota()
        self.app.refresh_dot()

    def shutdown(self):
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None

    # ------------------------------------------------------------- changes of the run (called by app.runs_changed)
    def on_runs(self, starting: bool, ended, tick: bool) -> None:
        if tick:
            return
        s = self.app.series
        if starting:
            r = self.runs.run
            if r is not None and r.kind == "job" and s is not None and r.series == s.path:
                self.view = js.JobView(state="running", book=r.book, chapters=tuple(r.chapters))
            self.terms_now = None
            if r is not None and r.kind == "sample":
                self._start_sample_pane(r)
        if ended is not None:
            if ended.kind == "job":
                if s is not None and ended.series == s.path:
                    self._touch_books(ended)
                    self.view = model.job_view(s.path)
                    books = self.app.steps.get("books")
                    if books is not None and self.app.book:
                        books.start_scan()
                    self._check_terms()
                    self._load_problems()
                self._run_key = None
            else:
                self._show_sample_rows()
        elif not starting and s is not None and not self.runs.running:
            self.view = model.job_view(s.path)
        self._update_controls()
        self._refresh_numbers()
        self._refresh_quota()
        self.app.refresh_dot()

    def on_progress(self, run) -> None:
        self._refresh_numbers()
        self._touch_books(run)
        self._update_run_rows(run)

    # ------------------------------------------------------------- settings row
    def _sync_settings(self):
        s = self.app.series
        lang = self.app.series_language()
        self.to_btn.set_text("To  ▾" if lang is None else "To %s  ▾" % langrules.label(lang, model.TARGETS))
        if s is None:
            self.prompt_btn.set_text("Default  ▾")
            return
        st = model.series_settings(s.path)
        name = str(st.get("prompt") or "default")
        self.prompt_btn.set_text(("Default" if name.lower() == RESERVED else name) + "  ▾")
        pr = st.get("per_request")
        self.per_seg.set_value(str(pr) if pr in PER_REQUEST else "5")

    def _open_language(self):
        b = self.to_btn
        if self.app.series is None or not b.enabled:
            return
        self.app.language_menu(b.winfo_rootx(), b.winfo_rooty() + b.h + 4, openers=(b,))

    def _language_busy(self) -> str:
        """Why `To` cannot be used now ("" when it can): this series runs, waits, or is queued."""
        s = self.app.series
        if s is None:
            return ""
        if self._run_here() is not None:
            return "A translation of this series is running."
        return self.app.language_block_reason(s.path, self.view)

    def _to_tip(self):
        why = self._language_busy()
        if why:
            return tips.TO_BUSY % why
        return tips.TO_EMPTY if self.app.series_language() is None else tips.TO_CHOSEN

    def _lock_tip(self, normal):
        """The tip of a control that may be disabled: it says why when it is."""
        if self.app.series is None:
            return "Choose a series on the Books step first."
        if self.view.foreign:
            return tips.START_ELSEWHERE
        return normal

    def _per_locked(self) -> bool:
        """`Per request` is read when a translation starts: locked while a job of this series runs."""
        return self._run_here() is not None

    def _per_request_picked(self, v):
        s = self.app.series
        if s is not None and not self._per_locked():
            model.save_series_setting(s.path, "per_request", int(v))
            self._refresh_quota()

    def _open_prompts(self):
        s = self.app.series
        if s is None:
            return
        names = self.app.prompts.names()
        items = ["Default"] + names
        b = self.prompt_btn
        root = self.ui.root
        x = b.winfo_rootx() - root.winfo_rootx()
        y = b.winfo_rooty() - root.winfo_rooty() + b.h + 4
        cur = self.prompt_btn.text.rsplit("  ", 1)[0]
        self.ui.popup.show(root, x, y, max(self.ui.cw * 24, b.w), items, cur if cur in items else "Default",
                           self._prompt_picked, openers=(b,))

    def _prompt_picked(self, item, nxt):
        s = self.app.series
        if s is None:
            return
        if item == "Default":
            model.apply_prompt(s.path, "default", None)
        else:
            text = self.app.prompts.read(item)
            if text is None:
                message(self.ui, "The prompt %s cannot be read." % item)
                return
            model.apply_prompt(s.path, item, text)
        self._sync_settings()

    def _edit_prompt(self):
        s = self.app.series
        if s is None:
            return
        st = model.series_settings(s.path)
        name = str(st.get("prompt") or "default")
        name = "" if name.lower() == RESERVED else name
        text = model.current_prompt_text(s.path)

        def taken(n):
            if n.lower() == RESERVED:
                return "Default cannot be replaced; choose another name."
            return ""

        def saved(n, t):
            try:
                clean = self.app.prompts.save(n, t)
            except (ValueError, OSError) as exc:
                message(self.ui, "The prompt was not saved: %s" % exc)
                return
            model.apply_prompt(s.path, clean, t)
            self._sync_settings()

        PromptEditor(self.ui, name, text, taken, saved, series=s.path)

    # ------------------------------------------------------------- state -> controls
    def _selection_indices(self) -> list:
        sel = self.app.selection
        if not sel or sel.book != self.app.book:
            return []
        return list(sel.indices)

    def _same_selection(self) -> bool:
        sel = self.app.selection
        v = self.view
        return bool(sel) and sel.book == v.book and set(sel.indices) == set(v.chapters)

    def _has_keys(self) -> bool:
        return bool(self.app.keystore.keys)

    def _language_ok(self) -> bool:
        """Start, Continue and Sample need the language of the series."""
        return self.app.series is None or self.app.series_language() is not None

    def _is_translated(self, i: int) -> bool:
        infos = self.app.infos
        return 0 <= i < len(infos) and pieces.kind_of(infos[i]) == pieces.OK

    def _job_reach(self) -> str:
        """The chapters `Continue` will cover: the chapters of the unfinished job that are not translated yet."""
        v = self.view
        if not v.chapters or v.book != self.app.book or not self.app.infos:
            return ""
        left = [i for i in v.chapters if not self._is_translated(i) and i < len(self.app.infos)
                and self.app.infos[i].is_toc is not True]
        return header.range_text(self.app.infos, left or list(v.chapters))

    def _zone_facts(self) -> ZoneFacts:
        runs = self.runs
        r = self._run_here()
        w = runs.sched.wait
        armed = w is not None and w.series == self._path()
        qw = runs.quota_wait()
        busy_other = (runs.job_running and r is None) or (qw is not None and qw[1] != self._path())
        return ZoneFacts(self.view, r is not None, bool(r and r.stopping), r.paused_until if r else None,
                         r.retry_until if r else None, time.time(), self.terms_now, self._has_keys(),
                         self._language_ok(), busy_other, armed, self._job_reach(), runs.queued(self._path()) is not None)

    def _start_facts(self) -> StartFacts:
        app, runs = self.app, self.runs
        s = app.series
        idx = self._selection_indices()
        blocked_at = app.terms_blocked_at if (idx and app.terms_n) else None
        first = later = False
        reach_idx = idx
        if blocked_at is not None and blocked_at in idx:
            before = [i for i in idx if i < blocked_at]
            if before:
                later, reach_idx = True, before
            else:
                first, reach_idx = True, []
        reach = header.range_text(app.infos, reach_idx) if reach_idx else ""
        translated = bool(idx) and all(self._is_translated(i) for i in idx)
        v = self.view
        r = self._run_here()
        w = runs.quota_wait()
        back = js.clock_text(w[0]) if w is not None else ""
        return StartFacts(
            has_series=s is not None and not s.broken, selected=bool(idx), reach=reach, first_blocked=first,
            later_blocked=later, review_n=app.terms_n or 0, translated=translated, keys=self._has_keys(),
            language=self._language_ok(), something_runs=runs.job_running, sample_runs=runs.run is not None
            and runs.run.kind == "sample", quota_waiting=w is not None, quota_back=back,
            own_unfinished=v.unfinished and r is None, own_running=r is not None,
            own_same=self._same_selection() and (v.unfinished or r is not None), foreign=v.foreign)

    def _update_controls(self):
        runs = self.runs
        z = self.zone = zonestate.zone1(self._zone_facts())
        st = self.start = startlabel.choose(self._start_facts())
        r = self._run_here()
        nprob = sum(1 for p in self.problems if not p.is_finding)       # findings are never the red thing
        # one red (window 1.7): keys, language, blocked first chapter, then the screen's own next thing
        cand = ""
        if z.visible and z.second == "review" and z.review_n:
            cand = "z1_review"
        elif z.visible and z.second == "settings":
            cand = "z1_settings"        # failed on a key or a model: the fix is in settings, not in Continue
        elif z.visible and z.action == "continue" and z.enabled:
            cand = "z1_continue"
        elif st.has_button and st.enabled and st.kind in ("translate", "replace") and nprob == 0:
            cand = "start"
        elif nprob > 0 and r is None:
            cand = "problems"
        facts = accent.Facts(self._has_keys(), self._language_ok(), st.kind == "review")
        top = accent.owner(facts, cand)
        self.owner = top
        to_kind = "accent" if top == accent.LANGUAGE else "plain"
        if self.to_btn.kind != to_kind:
            self.to_btn.kind = to_kind
            self.to_btn.draw()

        # zone 1
        if z.visible:
            if not _packed(self.zone1):
                self.zone1.pack(fill="x", before=self.prog)
            self.z1_btn.set_text(z.button or " ")
            self.z1_btn.kind = "accent" if top == "z1_continue" else "plain"
            self.z1_btn.set_enabled(z.enabled)
            self.z1_btn.draw()
            if z.button:
                if not _packed(self.z1_btn):
                    opts = {"before": self.z1_btn2} if _packed(self.z1_btn2) else {}
                    self.z1_btn.pack(side="left", **opts)
            elif _packed(self.z1_btn):
                self.z1_btn.pack_forget()
            if z.second:
                self.z1_btn2.set_text(z.second_text)
                self.z1_btn2.kind = "accent" if (top in ("z1_review", "z1_settings")
                                                 or (top == accent.TERMS and z.second == "review")) else "plain"
                self.z1_btn2.draw()
                if not _packed(self.z1_btn2):
                    self.z1_btn2.pack(side="left", padx=(self.gap // 2, 0))
            elif _packed(self.z1_btn2):
                self.z1_btn2.pack_forget()
            self.z1_more.set_enabled(z.discard and r is None)
            fg = TEXT if z.chip.kind in ("plain", "accent") else DIM      # the red is the button, never the chip
            self.chip.configure(text=z.chip.text, fg=fg, cursor="hand2" if z.chip.key == "terms" else "arrow")
        elif _packed(self.zone1):
            self.zone1.pack_forget()

        # zone 2
        if st.kind == "none" or (st.kind == "review" and not st.has_button):
            if _packed(self.main_btn):
                self.main_btn.pack_forget()
        else:
            if not _packed(self.main_btn):
                self.main_btn.pack(side="left", before=self.sample_btn)
            self.main_btn.set_text(st.text or "Translate")
            self.main_btn.kind = "accent" if ((st.kind == "add_keys" and top == accent.KEYS)
                                              or (top == "start" and st.enabled)) else "plain"
            self.main_btn.set_enabled(st.enabled)
            self.main_btn.draw()
        if st.review:
            self.review_btn.set_text("Review %d terms" % st.review)
            self.review_btn.kind = "accent" if top == accent.TERMS else "plain"
            self.review_btn.draw()
            if not _packed(self.review_btn):
                self.review_btn.pack(side="left", padx=(self.gap // 2, 0), before=self.sample_btn)
        elif _packed(self.review_btn):
            self.review_btn.pack_forget()

        sampling = runs.run is not None and runs.run.kind == "sample"
        idx = self._selection_indices()
        busy = runs.job_running or runs.quota_wait() is not None or self.view.foreign
        can_sample = bool(idx) and self._has_keys() and self._language_ok() and not busy
        n = self._sample_unreviewed(idx[0]) if idx else 0
        self.sample_btn.set_text("Stop" if sampling else ("Sample · %d unreviewed" % n if n > 0 else "Sample"))
        self.sample_btn.set_enabled(sampling and not runs.run.stopping or (not sampling and can_sample))
        self.sample_n.set_enabled(not runs.running and not self.view.foreign)

        mine = r is not None
        locked_foreign = self.view.foreign
        self.prompt_btn.set_enabled(self.app.series is not None and not locked_foreign)
        self.edit_btn.set_enabled(self.app.series is not None and not locked_foreign)
        self.to_btn.set_enabled(self.app.series is not None and not self._language_busy() and not locked_foreign)
        self.per_seg.set_enabled(self.app.series is not None and not mine and not locked_foreign)
        self.problems_panel.set_enabled(not mine and not locked_foreign and self._has_keys())
        self.check_btn.set_enabled(not self.checking and bool(self._checkable()) and not mine and not locked_foreign)
        self.problems_panel.set_accent(top == "problems")
        self.queue_list.refresh()
        self._show_content()

    def _sample_unreviewed(self, chapter: int) -> int:
        terms = self.app.steps.get("terms")
        if terms is None or not hasattr(terms, "unreviewed_in"):
            return 0
        try:
            return int(terms.unreviewed_in(chapter) or 0)
        except Exception:
            return 0

    def _show_content(self):
        r = self._run_here()
        if r is not None:
            self._ensure_run_rows(r)
            if not _packed(self.running_table):
                self.running_table.pack(fill="both", expand=True)
        elif _packed(self.running_table):
            self.running_table.pack_forget()
        if self.sample_info is not None:
            if not _packed(self.sample):
                opts = {"before": self.running_table if _packed(self.running_table)
                        else self.problems_panel} if (_packed(self.running_table)
                                                      or _packed(self.problems_panel)) else {}
                self.sample.pack(fill="both", expand=True, pady=(0, self.gap), **opts)
        else:
            self.sample.pack_forget()
        if self.problems and r is None:
            if not _packed(self.problems_panel):
                self.problems_panel.pack(fill="both", expand=True)
                if _packed(self.sample):
                    self.sample.pack_forget()
                    self.sample.pack(fill="both", expand=True, pady=(0, self.gap), before=self.problems_panel)
        else:
            self.problems_panel.pack_forget()

    # ------------------------------------------------------------- the running screen (7.9)
    def _ensure_run_rows(self, r) -> None:
        mine = self.app.series is not None and self.app.series.path == r.series and self.app.book == r.book
        infos = self.app.infos if mine else []
        key = (r.series, r.book, tuple(r.chapters), any(i.title for i in infos))     # titles arrive with the scan
        if key == self._run_key:
            return
        self._run_key = key

        def title(i):
            return (infos[i].title or "") if i < len(infos) else ""
        chapters = [i for i in r.chapters if not (i < len(infos) and infos[i].is_toc is True)]
        rows = build_rows(chapters, r.chap, title)
        self.run_rows = {x.index: x for x in rows}
        self.running_table.set_rows(rows)

    def _update_run_rows(self, r) -> None:
        if self._run_here() is None or not self.run_rows:
            return
        for i, (d, t, f) in r.chap.items():
            row = self.run_rows.get(i)
            if row is not None:
                row.done, row.total, row.failed = d, t, f
        rows = self.running_table.rows
        cur = current_of(rows)
        self.running_table.refresh()
        if cur:
            pos = self.running_table.pos.get(id(self.run_rows[cur[0]]))
            if pos is not None and pos != getattr(self, "_cur_pos", None):
                self._cur_pos = pos
                self.running_table.ensure_visible(pos)
                self.running_table.draw()

    # ------------------------------------------------------------- actions of zone 2
    def _main_clicked(self):
        st = self.start
        if not st.enabled:
            return
        k = st.kind
        if k == "add_keys":
            self.app.open_settings()
            panel = self.app.panel
            if panel is not None and hasattr(panel, "paste"):
                panel.paste.focus_set()
            return
        s = self.app.series
        idx = self._selection_indices()
        if s is None or not idx:
            return
        reach = header.range_text(self.app.infos, idx)
        if k == "translate":
            self._go_start(s.path, self.app.book, idx)
        elif k == "queue":
            self._go_queue(s.path, self.app.book, idx, reach, replace=False)
        elif k == "replace":
            confirm(self.ui, "Replace the unfinished job of %s with chapters %s? Translated chapters stay "
                    "translated." % (s.name, reach), "Replace", lambda: self._go_start(s.path, self.app.book, idx),
                    valid=lambda: self.view.unfinished)
        elif k == "queue_replace":
            confirm(self.ui, "Queue chapters %s of %s. When they start, the unfinished job of this series is "
                    "replaced; translated chapters stay translated." % (reach, s.name), "Queue",
                    lambda: self._go_queue(s.path, self.app.book, idx, reach, replace=True),
                    valid=lambda: self.view.unfinished)

    def _go_start(self, path: str, book: str, chapters, retry=()) -> None:
        why = self.runs.start(path, book, chapters, retry=retry)
        if why:
            message(self.ui, why)

    def _go_queue(self, path: str, book: str, chapters, reach: str, replace: bool, resume: bool = False,
                  retry=()) -> None:
        item = jobqueue.Item(path, book, jobqueue.spans_of(chapters), resume, replace, reach, tuple(retry))
        old = self.runs.queued(path)

        def put():
            self.runs.enqueue(item)
        if old is not None and old != item:
            info = self.app.series_info(path)
            confirm(self.ui, tips.QUEUE_REPLACE_CONFIRM % (info.name if info else "This series"), "Replace", put)
        else:
            put()

    def _review_clicked(self):
        self.app.show_terms_blockers()

    # ------------------------------------------------------------- actions of zone 1
    def _z1_clicked(self):
        z = self.zone
        if not z.enabled:
            return
        s = self.app.series
        if s is None:
            return
        if z.action == "stop":
            self.runs.stop()
        elif z.action == "continue":
            self._go_resume(s.path)
        elif z.action == "queue_continue":
            v = self.view
            self._go_queue(s.path, v.book, list(v.chapters), self._job_reach(), replace=False, resume=True)

    def _go_resume(self, path: str) -> None:
        why = self.runs.start(path, "", [], resume=True)
        if why:
            message(self.ui, why)

    def _z1_second(self):
        k = self.zone.second
        if k == "review":
            self.app.show_terms_blockers()
        elif k == "settings":
            self.app.open_settings()
        elif k == "stop_wait":
            self.runs.stop_wait()

    def _z1_more(self, e):
        if not self.zone.discard or self._run_here() is not None:
            return
        items, labels = ["discard"], {"discard": "Discard job"}
        root = self.ui.root

        def pick(k, nxt):
            self._discard_job()
        self.ui.menu.show(root, e.x_root - root.winfo_rootx(), e.y_root - root.winfo_rooty(), self.ui.cw * 18,
                          items, items[0], pick, labels=labels)

    def _discard_job(self):
        s = self.app.series
        if s is None:
            return
        path = s.path
        confirm(self.ui, tips.Z1_DISCARD_CONFIRM % s.name, "Discard", lambda: self._do_discard(path),
                valid=lambda: self.view.unfinished and self._path() == path and self._run_here() is None)

    def _do_discard(self, path: str):
        self.runs.discard(path)
        self.refresh_all()

    def _chip_clicked(self):
        if self.zone.chip.key == "terms":
            self.app.show_terms_blockers()

    # ------------------------------------------------------------- tooltips
    def _counts(self):
        """(blocks done, blocks total, chapters done, chapters total) of what is shown now."""
        r = self._run_here()
        if r is not None and r.chap:
            return self.runs.counts()
        v = self.view
        if v.state:
            return v.blocks_done, v.blocks_total, v.chapters_done, v.chapters_total
        idx = self._selection_indices()
        if idx and self.app.infos:
            infos = self.app.infos
            done = sum(min(infos[i].done, infos[i].blocks or 0) for i in idx)
            total = sum(infos[i].blocks or 0 for i in idx)
            full = sum(1 for i in idx if infos[i].blocks and infos[i].done >= infos[i].blocks)
            return done, total, full, len(idx)
        return 0, 0, 0, 0

    def _main_tip(self):
        st = self.start
        reach = header.range_text(self.app.infos, self._selection_indices())
        if st.kind == "add_keys":
            return tips.ADD_KEYS
        if st.why == "language":
            return tips.NEED_LANGUAGE
        if st.why == "selection":
            return tips.START_NEED_SELECTION
        if st.why == "done":
            return tips.START_DONE
        if st.why == "sample":
            return tips.START_SAMPLE_RUNS
        if st.why == "foreign":
            return tips.START_ELSEWHERE
        if st.kind == "queue":
            if st.quota_back:
                return tips.fill(tips.START_QUEUE_QUOTA, st.quota_back, st.quota_back, reach)
            return tips.fill(tips.START_QUEUE, reach)
        if st.kind == "replace":
            return tips.fill(tips.START_REPLACE, reach)
        if st.kind == "queue_replace":
            return tips.fill(tips.START_QUEUE_REPLACE, reach)
        return tips.fill(tips.START_TRANSLATE, reach)

    def _z1_tip(self):
        z = self.zone
        v = self.view
        if z.action == "stop":
            return tips.Z1_STOP
        if z.why == "keys":
            return tips.Z1_NO_KEYS
        if z.why == "language":
            return tips.NEED_LANGUAGE
        if z.why == "quota":
            auto = tips.Z1_WAIT_QUOTA_AUTO if z.second == "stop_wait" else ""
            tip = tips.fill(tips.Z1_WAIT_QUOTA, auto, js.clock_text(v.wake_at) if v.wake_at else "?")
            return tip
        if z.why == "terms":
            return tips.Z1_WAIT_TERMS
        if z.why == "foreign":
            return tips.Z1_ELSEWHERE
        done = "%s of %s blocks" % (js.fmt_count(self._counts()[0]), js.fmt_count(self._counts()[1]))
        if z.action == "queue_continue":
            return tips.fill(tips.Z1_QUEUE_CONTINUE, self._job_reach() or "-")
        return tips.fill(tips.Z1_CONTINUE, self._job_reach() or "-", done)

    def _z1_second_tip(self):
        k = self.zone.second
        if k == "review":
            return tips.fill(tips.REVIEW_TERMS, self.zone.review_n)
        if k == "settings":
            return tips.Z1_SETTINGS
        if k == "stop_wait":
            return tips.Z1_STOP_WAIT
        return None

    def _sample_tip(self):
        runs = self.runs
        if runs.run is not None and runs.run.kind == "sample":
            return tips.SAMPLE_STOP
        if not self._has_keys():
            return tips.ADD_KEYS
        if not self._language_ok():
            return tips.NEED_LANGUAGE
        if not self._selection_indices():
            return tips.START_NEED_SELECTION
        if runs.job_running or runs.quota_wait() is not None:
            return tips.SAMPLE_BUSY
        if self.view.foreign:
            return tips.START_ELSEWHERE
        idx = self._selection_indices()
        n = self._sample_unreviewed(idx[0]) if idx else 0
        return tips.fill(tips.SAMPLE_UNREVIEWED, n) if n > 0 else tips.SAMPLE

    def _chip_tip(self):
        c = self.zone.chip
        v = self.view
        if c.key == "wait":
            return ("The daily quota of every key is used up. Translating can continue at this time.",
                    [("Local time", js.clock_text(v.wake_at)), ("Resets at", "midnight Pacific time")])
        if c.key == "terms":
            return ("Chapters are translated only when every term in them is reviewed. Click to see the terms "
                    "that hold this job back.", [("Terms", str(js.terms_count(v, self.terms_now))),
                                                 ("Stopped at chapter",
                                                  str(cl.display_no(v.blocked_chapter)) if v.blocked_chapter is not None
                                                  else "?")])
        if c.key == "paused":
            r = self._run_here()
            return ("The service refused several requests, so sending is paused for a moment. It goes on by itself.",
                    [("Resumes in", js.countdown_text((r.paused_until if r else 0) - time.time()))])
        if c.key == "retrying":
            return tips.CHIP_RETRYING
        if c.key == "failed":
            f = self.zone.fault
            return tips.fill(tips.CHIP_FAILED, v.error or (f.text if f else "The job stopped on an error"))
        if c.key == "stopped":
            return "The job is not running. Continue picks up where it stopped."
        if c.key == "elsewhere":
            return "Another window or program works on this series."
        if c.key == "stopping":
            return "Finishing the requests in flight."
        return None

    def _quota_tip(self):
        q = self._quota
        cfg = self.app.run_config()
        pace = cfg.pace or model.default_pace()
        return ("Requests of the free daily quota that are left over all keys, and what the rest of this job needs "
                "at the pace set in the settings. One even rate is used for all keys. The quota starts again at "
                "midnight Pacific time.",
                [("Keys", str(q.keys)), ("Per key and day", str(q.per_key) if q.per_key else "?"),
                 ("Used today", js.fmt_count(q.used)), ("Pace", "%g a minute" % pace),
                 ("Comes from", "requests this app sent")])

    # ------------------------------------------------------------- numbers
    def _refresh_numbers(self):
        d, t, cd, ct = self._counts()
        if not t and not ct:
            self.numbers.configure(text="")
        else:
            self.numbers.configure(text="%s / %s blocks   %s / %s chapters" % (
                js.fmt_count(d), js.fmt_count(t), js.fmt_count(cd), js.fmt_count(ct)))
        self._draw_bar()

    def _draw_bar(self):
        c = self.bar
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        d, t, _a, _b = self._counts()
        c.create_rectangle(0, 0, w, h, fill=TRACK, outline="")
        if t:
            c.create_rectangle(0, 0, int(w * min(1.0, d / t)), h, fill=BAR, outline="")

    def _remaining(self) -> int:
        infos = self.app.infos
        v = self.view
        r = self._run_here()
        if r is not None and r.chap:
            return sum(max(0, t - d) for d, t, _f in r.chap.values())
        if v.unfinished and v.book == self.app.book and infos and v.chapters:
            return js.remaining_blocks(infos, v.chapters)[0]
        idx = self._selection_indices()
        if idx and infos:
            return js.remaining_blocks(infos, idx)[0]
        if v.unfinished:
            return max(0, v.blocks_total - v.blocks_done)
        return 0

    def _refresh_quota(self):
        s = self.app.series
        lib = self.app.library
        if s is None or lib is None:
            self.quota.configure(text="")
            return
        cfg = self.app.run_config()
        self._quota = q = model.quota_status(lib, cfg.keys, cfg.models, time.time()) if cfg.keys else model.Quota()
        per = model.series_settings(s.path).get("per_request") or 5
        est = js.estimate(self._remaining(), per, cfg.pace or model.default_pace(), q.left, q.capacity)
        self._est = est
        text = js.quota_text(est, q.left) if cfg.keys else ""
        if text:
            text += "  ·  resets %s" % js.clock_text(model.day_return(time.time()))
        self.quota.configure(text=text)

    # ------------------------------------------------------------- tick
    def _tick(self):
        if not self.winfo_exists():
            return
        self._tick_job = self.after(500, self._tick)
        runs = self.runs
        self._tick_n += 1
        s = self.app.series
        if self._run_here() is None and s is not None and self._tick_n % 6 == 0:
            v = model.job_view(s.path)      # another window or the quota clock may have changed the job
            if v != self.view:
                self.view = v
                self._update_controls()
                self._refresh_numbers()
                self.app.refresh_dot()
        if runs.running or self.view.state == "waiting_quota" or self.view.foreign or runs.sched.wait is not None:
            if self.view.foreign and s is not None:
                self.view = model.job_view(s.path)
            self._update_controls()
        if runs.running and int(time.time()) % 5 == 0:
            self._refresh_quota()

    def _touch_books(self, run):
        b = self.app.steps.get("books")
        if b is None or not run.chap or run.kind != "job":
            return
        if self.app.series is None or self.app.series.path != run.series or self.app.book != run.book:
            return
        infos = self.app.infos
        for i, (d, t, fl) in run.chap.items():
            if i < len(infos):
                infos[i].done, infos[i].failed = min(d, t), fl
                infos[i].log_sig = (-1, -1)
        b.table.refresh()
        self.app.infos_updated()

    # ------------------------------------------------------------- terms
    def _check_terms(self):
        """For a job that waits for terms: recount what blocks now (the owner may have reviewed them)."""
        v = self.view
        s = self.app.series
        if self._terms_token is not None:
            self._terms_token.cancel()
            self._terms_token = None
        self.terms_now = None
        if s is None or v.state != "waiting_terms" or v.blocked_chapter is None:
            return
        path, book, ch = s.path, v.book, v.blocked_chapter

        def done(n, path=path):
            if self.app.series is not None and self.app.series.path == path:
                self.terms_now = n
                self._update_controls()
                self.app.refresh_dot()

        self._terms_token = self.ui.worker.submit(lambda ctx: model.terms_blocking_task(ctx, path, book, ch),
                                                  on_result=done, on_error=lambda e: None, lane="search")

    # ------------------------------------------------------------- problems
    def _problem_chapters(self) -> list:
        """Chapters that may hold failed blocks: those of the job, those shown as problems already (a retry job
        covers fewer chapters than the first one), and those the chapter list counted failures in."""
        v = self.view
        out = set(v.chapters) | {p.chapter for p in self.problems}
        if v.book == self.app.book or not v.book:
            out |= {i for i, info in enumerate(self.app.infos) if info.failed}
        return sorted(out)

    def _load_problems(self):
        s = self.app.series
        if self.problems_token is not None:
            self.problems_token.cancel()
        if s is None or self._run_here() is not None:
            return
        chapters = self._problem_chapters()
        book = self.view.book or self.app.book
        if not book:
            self._set_problems([])
            return
        path = s.path
        self.problems_token = self.ui.worker.submit(
            lambda ctx: model.problems_task(ctx, path, book, chapters),
            on_result=lambda rows, p=path: self._set_problems(rows) if self.app.series and self.app.series.path == p
            else None, on_error=lambda e: None, lane="fast")

    def _set_problems(self, rows):
        self.problems = list(rows)
        self.problems_panel.set_problems(self.problems)
        self._update_controls()
        if self._jump is not None and self.problems:
            self._land(self._jump)
        self._jump = None

    def show_problem_at(self, chapter) -> None:
        """Export's `1 problem` link: the list lands on the first row of that chapter (the list is loaded again so
        that it is current)."""
        self._jump = chapter
        self._load_problems()

    def _land(self, chapter) -> None:
        rows = self.problems
        k = next((i for i, p in enumerate(rows) if p.chapter == chapter), None)
        if k is None and chapter is not None:
            k = next((i for i, p in enumerate(rows) if p.chapter >= chapter), None)
        if k is None:
            return
        self._show_content()
        self.update_idletasks()
        t = self.problems_panel.table
        t.select_index(k)
        t.ensure_visible(k)
        t.draw()

    def _retry(self, rows):
        """Translate blocks again: failed blocks and check findings go through the same start rules as the start
        button (window_spec 13.1, 13.2). A job that runs makes it a queue item; an unfinished job of this series on
        other chapters makes it a replace that asks first. The core marks findings only when the job really
        starts, so the chapters stay in Export while it waits."""
        s = self.app.series
        if not rows or s is None or self._run_here() is not None or self.view.foreign or not self._has_keys():
            return
        findings = [p for p in rows if p.is_finding]
        if findings and len(findings) != len(rows):
            return                                       # failed blocks and findings are separate runs
        marks = tuple(p.mark() for p in findings)
        chapters = sorted({p.chapter for p in rows})
        book = self.view.book or self.app.book
        path = s.path
        reach = header.range_text(self.app.infos, chapters) if book == self.app.book else ""
        v = self.view
        conflict = v.unfinished and set(v.chapters) != set(chapters)
        busy = self.runs.job_running or self.runs.quota_wait() is not None

        def go():
            if busy:
                self._go_queue(path, book, chapters, reach, replace=conflict, retry=marks)
            else:
                self._go_start(path, book, chapters, retry=marks)
        if not conflict:
            go()
        elif busy:
            confirm(self.ui, "Queue chapters %s of %s. When they start, the unfinished job of this series is "
                    "replaced; translated chapters stay translated." % (reach or "of the problems", s.name), "Queue",
                    go, valid=lambda: self.view.unfinished)
        else:
            confirm(self.ui, "Replace the unfinished job of %s with chapters %s? Translated chapters stay "
                    "translated." % (s.name, reach or "of the problems"), "Replace", go,
                    valid=lambda: self.view.unfinished)

    def _ignore(self, rows):
        s = self.app.series
        if not rows or s is None:
            return
        path, book = s.path, self.view.book or self.app.book
        self.ui.worker.submit(lambda ctx: model.ignore_task(ctx, path, book, rows),
                              on_result=lambda n: self._resolved() if self._path() == path else None,
                              on_error=lambda e: message(self.ui, "The choice could not be saved: %s" % e),
                              lane="bulk")

    # ------------------------------------------------------------- the check (7.10)
    def _checkable(self) -> list:
        """Chapters of the selection that have translated blocks."""
        infos = self.app.infos
        return [i for i in self._selection_indices() if 0 <= i < len(infos) and infos[i].done > 0
                and infos[i].is_toc is not True]

    def _check_tip(self):
        if self.checking:
            return "The check is reading the translated chapters."
        return ("Look for suspicious translations in the chosen chapters: text left in the source language, a "
                "length far off its chapter, terms not rendered as confirmed, broken markers. Findings are listed "
                "with the failed blocks; nothing is changed.",
                [("Applies to", "chosen chapters with translated blocks"), ("Uses", "no requests")])

    def _check_clicked(self):
        s = self.app.series
        chapters = self._checkable()
        if s is None or not chapters or self.checking or self._run_here() is not None:
            return
        path, book = s.path, self.app.book
        reach = header.range_text(self.app.infos, chapters)
        self.checking = path
        self.check_btn.set_text("Check 0/%d" % len(chapters))

        def progress(item):
            if item[0] == "check" and self.checking == path:
                self.check_btn.set_text("Check %d/%d" % (item[1], item[2]))

        def done(res):
            self.checking = ""
            self.check_btn.set_text("Check")
            if self._path() == path:
                self._load_problems()
                if not res["findings"] and not res["cancelled"]:
                    message(self.ui, "The check found nothing suspicious in chapters %s." % reach)
            self._update_controls()

        def failed(exc):
            self.checking = ""
            self.check_btn.set_text("Check")
            self._update_controls()
            message(self.ui, "The check stopped on an error: %s" % exc)
        self.ui.worker.submit(lambda ctx: model.check_task(ctx, path, book, chapters), on_item=progress,
                              on_result=done, on_error=failed, lane="bulk")
        self._update_controls()

    def _keep(self, rows):
        self._resolve(rows, "keep", "")

    def _save_typed(self, rows, text):
        self._resolve(rows, "manual", text)

    def _resolve(self, rows, action, typed):
        s = self.app.series
        if not rows or s is None or self._run_here() is not None or self.view.foreign:
            return
        book = self.view.book or self.app.book
        self.ui.worker.submit(lambda ctx: model.resolve_problems_task(ctx, s.path, book, rows, action, typed),
                              on_result=lambda n: self._resolved(), on_error=lambda e: message(
                                  self.ui, "The change could not be written: %s" % e), lane="bulk")

    def _resolved(self):
        self.view = model.job_view(self.app.series.path) if self.app.series else self.view
        b = self.app.steps.get("books")
        if b is not None and self.app.book:
            b.start_scan()
        self._load_problems()

    # ------------------------------------------------------------- sample (7.13)
    def _sample_clicked(self):
        runs = self.runs
        if runs.run is not None and runs.run.kind == "sample":
            runs.stop()
            return
        self._start_sample()

    def _start_sample(self):
        s = self.app.series
        idx = self._selection_indices()
        if (s is None or not idx or self.runs.running or self.view.foreign or not self._has_keys()
                or not self._language_ok()):
            return
        try:
            n = max(1, min(500, int(self.sample_n.get().strip() or "50")))
        except ValueError:
            n = 50
            self.sample_n.set("50")
        chapter, book = idx[0], self.app.book
        unrev = self._sample_unreviewed(chapter)
        self.sample_info = (s.path, book, chapter, n)
        self.sample_unrev = unrev
        why = self.runs.start_sample(s.path, book, chapter, n)
        if why:
            self.sample_info = None
            message(self.ui, why)
            return
        self.samples[s.path] = (self.sample_info, unrev)

    def _start_sample_pane(self, run) -> None:
        pass

    def _show_sample_rows(self):
        info = self.sample_info
        if info is None:
            return
        path, book, chapter, n = info
        try:
            rows = model.sample_rows(path, book, chapter, n)
        except Exception as exc:
            message(self.ui, "The sample cannot be shown: %s" % exc)
            self.sample_info = None
            self.samples.pop(path, None)
            return
        self._show_content()
        self.update_idletasks()
        s = self.app.series
        lang = model.target_label(model.series_language(s)) if s and model.series_language(s) else ""
        title = "Sample · %d terms unreviewed" % self.sample_unrev if self.sample_unrev > 0 else lang
        self.sample.set_rows(rows, title)

    def _close_sample(self, keep: bool = False):
        """Hide the sample panes. `keep`: only because another series was chosen (its sample stays remembered)."""
        if not keep and self.sample_info is not None:
            self.samples.pop(self.sample_info[0], None)
        self.sample_info = None
        self.sample.pack_forget()
