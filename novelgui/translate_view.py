"""Step 3: run the translation of the selected chapters, watch it, deal with the blocks that failed."""

from __future__ import annotations

import time
import tkinter as tk

from . import chapterlogic as cl
from . import jobstate as js
from . import model, platform
from .dialog import confirm, message
from .keystore import RESERVED
from .step import Step
from .theme import ACCENT, BG, BRIGHT, DIM, FAINT, S2, S4, TEXT
from .tooltip import attach_tip
from .translate_parts import ProblemsPanel, PromptEditor, SamplePanel
from .widgets import Field, Pill, Segmented

PER_REQUEST = (1, 5, 10)
TRACK = "#1c1c1c"
BAR = "#d0d0d0"


class TranslateStep(Step):
    key = "translate"
    label = "Translate"

    def __init__(self, master, app):
        super().__init__(master, app)
        ui = self.ui
        f = ui.font
        self.gap = gap = int(ui.ls * 0.8)
        self.view = js.JobView()
        self.handle = None
        self.run_kind = ""             # "" | job | sample
        self.stopping = False
        self.closing = False
        self.paused_until = None
        self.terms_now = None
        self.chap: dict = {}           # chapter -> [done, total, failed] of the job being watched
        self.chap_dirty = False
        self.problems: list = []
        self.problems_token = None
        self.sample_info = None
        self.last_error = ""
        self.pending_confirm = False
        self._terms_token = None
        self._tick_job = None
        self._tick_n = 0
        self._quota = model.Quota()
        self._est = None
        self.owner = ""

        # -- settings of the series
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(0, gap))
        tk.Label(top, text="Prompt", bg=BG, fg=DIM, font=f).pack(side="left", padx=(0, gap // 2))
        self.prompt_btn = Pill(top, "Default  ▾", self._open_prompts, f)
        self.prompt_btn.pack(side="left")
        self.edit_btn = Pill(top, "Edit", self._edit_prompt, f, kind="dim")
        self.edit_btn.pack(side="left", padx=(gap // 2, 0))
        self.per_seg = Segmented(top, f, self._per_request_picked)
        self.per_seg.set_items([(str(n), str(n), None) for n in PER_REQUEST], "5")
        self.per_seg.pack(side="right")
        tk.Label(top, text="Per request", bg=BG, fg=DIM, font=f).pack(side="right", padx=(0, gap // 2))
        attach_tip(self.prompt_btn, ui.tip, lambda e: (
            "The instructions the translator gets with every request. Default is the shipped one.",
            [("Applies to", "this series"), ("Saved in", "the series folder")]))
        attach_tip(self.edit_btn, ui.tip, lambda e: (
            "Write or change a prompt. It is saved under its name and becomes the prompt of this series.",
            [("Saved in", "the app data folder")]))
        attach_tip(self.per_seg, ui.tip, lambda e: (
            "How many blocks travel in one request. More blocks per request mean fewer requests of the daily "
            "quota; every block is checked on its own either way.",
            [("Choices", "1, 5 or 10"), ("Applies to", "this series"), ("Changes", "at once")]))

        # -- the action row
        act = tk.Frame(self, bg=BG)
        act.pack(fill="x", pady=(0, gap))
        self.main_btn = Pill(act, "Run", self._main_clicked, f, kind="plain", padx=int(ui.ls * 1.6))
        self.main_btn.pack(side="left")
        self.new_btn = Pill(act, "New run", self._new_run, f)
        self.sample_btn = Pill(act, "Sample", self._start_sample, f, kind="dim")
        self.sample_btn.pack(side="left", padx=(gap, 0))
        self.sample_n = Field(act, f, width=ui.cw * 6)
        self.sample_n.set("50")
        self.sample_n.pack(side="left", padx=(gap // 2, 0))
        self.chip = tk.Label(act, text="", bg=BG, fg=DIM, font=f, anchor="e", cursor="arrow")
        self.chip.pack(side="right")
        self.chip.bind("<Button-1>", lambda e: self._chip_clicked())
        attach_tip(self.main_btn, ui.tip, lambda e: self._main_tip())
        attach_tip(self.new_btn, ui.tip, lambda e: (
            "Start the selected chapters as a new job instead of continuing the unfinished one. Translated blocks "
            "are kept.", [("Replaces", "the unfinished job"), ("Keeps", "translated blocks")]))
        attach_tip(self.sample_btn, ui.tip, lambda e: (
            "Translate the first blocks of the first selected chapter to see how it reads. Nothing is added to "
            "the book, and the terms check does not apply.",
            [("Blocks", "the number on the right"), ("Uses", "requests of today"), ("Saved", "no")]))
        attach_tip(self.sample_n.entry, ui.tip, lambda e: "How many blocks of the chapter to translate for the sample.")
        attach_tip(self.chip, ui.tip, lambda e: self._chip_tip())

        # -- progress and numbers
        pr = tk.Frame(self, bg=BG)
        pr.pack(fill="x")
        self.numbers = tk.Label(pr, text="", bg=BG, fg=TEXT, font=f, anchor="w")
        self.numbers.pack(side="left")
        self.quota = tk.Label(pr, text="", bg=BG, fg=DIM, font=f, anchor="e")
        self.quota.pack(side="right")
        self.bar = tk.Canvas(self, height=max(3, int(ui.ls * 0.2)), bg=BG, highlightthickness=0, bd=0)
        self.bar.pack(fill="x", pady=(int(ui.ls * 0.3), gap))
        self.bar.bind("<Configure>", lambda e: self._draw_bar())
        attach_tip(self.numbers, ui.tip, lambda e: (
            "Blocks and chapters of this job that are translated, out of all of them.",
            [("Comes from", "the translation logs"), ("You can edit", "no")]))
        attach_tip(self.quota, ui.tip, lambda e: self._quota_tip())

        # -- content: sample panes, failed blocks
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True)
        self.sample = SamplePanel(self.content, ui, self._close_sample)
        self.problems_panel = ProblemsPanel(self.content, ui, self._retry, self._keep, self._save_typed)

        self._tick_job = self.after(500, self._tick)
        self._update_controls()

    # ------------------------------------------------------------- life
    def on_show(self):
        self.refresh_all()

    def on_series(self):
        self.sample_info = None
        self.sample.pack_forget()
        self.problems = []
        self.problems_panel.pack_forget()
        self.chap = {}
        self.refresh_all()

    def on_book(self):
        self.refresh_all()

    def on_selection(self):
        self._update_controls()
        self._refresh_numbers()
        self._refresh_quota()

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
        """The window is closing: stop a run, wait for it, with a visible Stopping state."""
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None
        if self.handle is None:
            return
        self.closing = True
        self.stopping = True
        self.handle.stop()
        self._update_controls()
        end = time.time() + 60
        root = self.ui.root
        while not self.handle.finished.is_set() and time.time() < end:
            try:
                root.update()
            except tk.TclError:
                break
            time.sleep(0.02)
        platform.keep_awake(False)

    @property
    def running(self) -> bool:
        return self.handle is not None

    # ------------------------------------------------------------- settings row
    def _sync_settings(self):
        s = self.app.series
        if s is None:
            self.prompt_btn.set_text("Default  ▾")
            return
        st = model.series_settings(s.path)
        name = str(st.get("prompt") or "default")
        self.prompt_btn.set_text(("Default" if name.lower() == RESERVED else name) + "  ▾")
        pr = st.get("per_request")
        self.per_seg.set_value(str(pr) if pr in PER_REQUEST else "5")

    def _per_request_picked(self, v):
        s = self.app.series
        if s is not None and not self.running:
            model.save_series_setting(s.path, "per_request", int(v))
            self._refresh_quota()

    def _open_prompts(self):
        s = self.app.series
        if s is None or self.running:
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
        if s is None or self.running:
            return
        st = model.series_settings(s.path)
        name = str(st.get("prompt") or "default")
        name = "" if name.lower() == RESERVED else name
        text = model.current_prompt_text(s.path)
        existing = self.app.prompts.names()

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

        del existing
        PromptEditor(self.ui, name, text, taken, saved)

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

    def _action(self) -> js.Action:
        has_sel = bool(self._selection_indices()) and self._has_keys()
        a = js.main_action(self.view, self.running and self.run_kind in ("job", "sample"), self.stopping, has_sel,
                           self._same_selection(), time.time(), self.terms_now)
        if a.label == "Continue" and not self._has_keys():
            a = js.Action("Continue", False, a.new_run)
        return a

    def _chip(self) -> js.Chip:
        return js.chip_for(self.view, self.running, self.stopping, self.paused_until, time.time(), self.terms_now)

    def _update_controls(self):
        a = self._action()
        chip = self._chip()
        nprob = len(self.problems)
        owner = js.accent_owner(a, chip, nprob, self.running)
        self.owner = owner
        m = self.main_btn
        m.kind = "accent" if owner == "action" and a.label != "Stop" else "plain"
        m.set_text(a.label)
        m.set_enabled(a.enabled)
        m.draw()
        show_new = a.new_run and not self.running
        if show_new and not self.new_btn.winfo_ismapped():
            self.new_btn.pack(side="left", padx=(self.gap // 2, 0), after=self.main_btn)
        elif not show_new and self.new_btn.winfo_ismapped():
            self.new_btn.pack_forget()
        idle = not self.running and not self.view.foreign and self.app.series is not None
        self.prompt_btn.set_enabled(idle)
        self.edit_btn.set_enabled(idle)
        self.per_seg.set_enabled(idle)
        self.sample_btn.set_enabled(idle and bool(self._selection_indices()) and self._has_keys())
        self.sample_n.set_enabled(idle)
        self.problems_panel.set_enabled(idle and self._has_keys())
        self.problems_panel.set_accent(owner == "problems")
        text = chip.text
        fg = {"accent": ACCENT, "plain": TEXT}.get(chip.kind, DIM)
        self.chip.configure(text=text, fg=fg, cursor="hand2" if chip.key == "terms" else "arrow")
        self._show_content()

    def _show_content(self):
        if self.sample_info is not None:
            if not self.sample.winfo_ismapped():
                opts = {"before": self.problems_panel} if self.problems_panel.winfo_ismapped() else {}
                self.sample.pack(fill="both", expand=True, pady=(0, self.gap), **opts)
        else:
            self.sample.pack_forget()
        if self.problems:
            if not self.problems_panel.winfo_ismapped():
                self.problems_panel.pack(fill="both", expand=True)
                if self.sample.winfo_ismapped():
                    self.sample.pack_forget()
                    self.sample.pack(fill="both", expand=True, pady=(0, self.gap), before=self.problems_panel)
        else:
            self.problems_panel.pack_forget()

    # ------------------------------------------------------------- tooltips
    def _main_tip(self):
        a = self._action()
        v = self.view
        if a.label == "Stop":
            return ("Finish the requests in flight, record them and stop. Nothing is lost; Continue picks up "
                    "where it stopped.", [("Saved", "every finished block")])
        if not self._has_keys():
            return "Add an API key in the settings (the gear in the header) to translate."
        if a.label == "Continue":
            if v.state == "waiting_quota" and not a.enabled:
                return ("The daily quota of every key is used up. The job continues after the quota returns.",
                        [("Returns at", js.clock_text(v.wake_at) if v.wake_at else "?"), ("Saved", "yes")])
            if v.state == "waiting_terms" and not a.enabled:
                return ("Chapters stop at the first one with terms that nobody has reviewed. Review them on "
                        "the Terms step first.", [("Next step", "Terms")])
            return ("Continue the unfinished job: same book, same chapters. Translated blocks are skipped.",
                    [("Book", v.book), ("Done", "%s of %s blocks" % (js.fmt_count(self._counts()[0]),
                                                                  js.fmt_count(self._counts()[1])))])
        if v.foreign:
            return "Another window is translating this series. Wait for it to finish."
        return ("Translate the selected chapters in order. It stops at the first chapter with terms that are not "
                "reviewed yet.", [("Chapters", str(len(self._selection_indices()))), ("Starts", "when you click")])

    def _chip_tip(self):
        c = self._chip()
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
            return ("The service refused several requests, so sending is paused for a moment. It goes on by itself.",
                    [("Resumes in", js.countdown_text((self.paused_until or 0) - time.time()))])
        if c.key == "failed":
            return (v.error or self.last_error or "The job stopped on an error.", [("Next", "Continue tries again")])
        if c.key == "done":
            return "Every chapter of the job has been processed."
        if c.key == "stopped":
            return "The job is not running. Continue picks up where it stopped."
        if c.key == "elsewhere":
            return "Another window works on this series."
        if c.key == "stopping":
            return "Finishing the requests in flight."
        return None

    def _quota_tip(self):
        q = self._quota
        cfg = self.app.run_config()
        pace = cfg.pace or model.default_pace()
        return ("Requests of the free daily quota that are left over all keys, and what the rest of this job needs "
                "at the pace set in the settings. One even rate is used for all keys.",
                [("Keys", str(q.keys)), ("Per key and day", str(q.per_key) if q.per_key else "?"),
                 ("Used today", js.fmt_count(q.used)), ("Pace", "%g a minute" % pace),
                 ("Comes from", "requests this app sent")])

    # ------------------------------------------------------------- numbers
    def _counts(self):
        """(blocks done, blocks total, chapters done, chapters total) of what is shown now."""
        if self.chap:
            done = sum(min(d, t) for d, t, _f in self.chap.values())
            total = sum(t for _d, t, _f in self.chap.values())
            full = sum(1 for d, t, _f in self.chap.values() if t and d >= t)
            return done, total, full, len(self.chap)
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
        if self.chap:
            return sum(max(0, t - d) for d, t, _f in self.chap.values())
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
        self.quota.configure(text=js.quota_text(est, q.left) if cfg.keys else "")

    # ------------------------------------------------------------- tick
    def _tick(self):
        if not self.winfo_exists() or self.closing:
            return
        self._tick_job = self.after(500, self._tick)
        if self.paused_until is not None and self.paused_until <= time.time():
            self.paused_until = None
        self._tick_n += 1
        if not self.running and self.app.series is not None and self._tick_n % 6 == 0:
            v = model.job_view(self.app.series.path)     # another window may have started or ended a job
            if v != self.view:
                self.view = v
                self._update_controls()
                self._refresh_numbers()
                self.app.refresh_dot()
        if self.chap_dirty:
            self.chap_dirty = False
            self._refresh_numbers()
            self._touch_books()
        if self.running or self.view.state == "waiting_quota" or self.view.foreign:
            if self.view.foreign:
                self.view = model.job_view(self.app.series.path) if self.app.series else self.view
            self._update_controls()
        if self.running and int(time.time()) % 5 == 0:
            self._refresh_quota()

    def _touch_books(self):
        b = self.app.steps.get("books")
        if b is None or not self.chap or self.app.book != self.view.book and self.run_kind != "job":
            return
        infos = self.app.infos
        for i, (d, t, fl) in self.chap.items():
            if i < len(infos):
                infos[i].done, infos[i].failed = min(d, t), fl
                infos[i].log_sig = (-1, -1)
        b.table.refresh()

    # ------------------------------------------------------------- running
    def _config(self):
        return self.app.run_config()

    def _main_clicked(self):
        a = self._action()
        if not a.enabled:
            return
        if a.label == "Stop":
            self._stop()
        elif a.label == "Continue":
            self._start_job(resume=True)
        else:
            self._start_job(resume=False)

    def _new_run(self):
        if not self._selection_indices():
            return
        if self.view.unfinished:
            confirm(self.ui, "Start the selected chapters as a new job? The unfinished job will be replaced; "
                    "translated blocks stay.", "New run", lambda: self._start_job(resume=False))
        else:
            self._start_job(resume=False)

    def _start_job(self, resume: bool):
        s = self.app.series
        if s is None or self.running or self.view.foreign or not self._has_keys():
            return
        cfg = self._config()
        if resume:
            book, chapters = self.view.book, list(self.view.chapters)
        else:
            book, chapters = self.app.book, self._selection_indices()
        if not chapters and not resume:
            return
        self._begin_run("job", book, chapters)
        handle = self.handle
        self.ui.worker.submit(
            lambda ctx: model.run_task(ctx, handle, s.path, book, chapters, cfg, resume),
            on_item=lambda item, h=handle: self._on_item(h, item), on_result=lambda r, h=handle: self._run_done(h, r),
            on_error=lambda exc, h=handle: self._run_failed(h, exc), lane="run")

    def _begin_run(self, kind: str, book: str, chapters):
        self.handle = model.RunHandle()
        self.run_kind = kind
        self.stopping = False
        self.paused_until = None
        self.last_error = ""
        self.terms_now = None
        self.chap = {}
        if kind == "job":
            infos = self.app.infos if book == self.app.book else []
            for i in chapters:
                if i < len(infos) and infos[i].is_toc is not True and infos[i].blocks is not None:
                    self.chap[i] = [min(infos[i].done, infos[i].blocks), infos[i].blocks, infos[i].failed]
            if self.sample_info is not None:
                self._close_sample()
        if self.app.settings.get("keep_awake"):
            platform.keep_awake(True)
        self.view = js.JobView(state="running", book=book, chapters=tuple(chapters))
        self._update_controls()
        self._refresh_numbers()

    def _stop(self):
        if self.handle is not None and not self.stopping:
            self.stopping = True
            self.handle.stop()
            self._update_controls()

    def _on_item(self, handle, item):
        if handle is not self.handle:
            return
        kind = item[0]
        if kind == "busy":
            self.last_error = item[1]
            message(self.ui, "This series is already being translated: %s" % item[1])
            return
        if kind != "event":
            return
        ev = item[1]
        k, data = ev.kind, ev.data
        if self.run_kind == "sample":
            if k == "error":
                self.last_error = str(data.get("message", ""))
            return
        if k == "chapter_started":
            i = data["index"]
            if not data.get("toc"):
                prev = self.chap.get(i)
                self.chap[i] = [prev[0] if prev else 0, data["blocks"], prev[2] if prev else 0]
                self.chap_dirty = True
        elif k == "progress":
            self.chap[data["index"]] = [data["done"], data["total"], data["failed"]]
            self.chap_dirty = True
        elif k == "chapter_finished":
            if not data.get("toc"):
                self.chap[data["index"]] = [data["ok"], data["blocks"], data["failed"]]
                self.chap_dirty = True
        elif k == "paused":
            if not data.get("abort"):
                self.paused_until = data.get("until")
        elif k == "unpaused":
            self.paused_until = None
        elif k == "error":
            self.last_error = str(data.get("message", ""))

    def _run_failed(self, handle, exc):
        if handle is self.handle:
            self.last_error = "%s: %s" % (exc.__class__.__name__, exc)
            self._run_done(handle, None)
            message(self.ui, "The run stopped on an error: %s" % exc)

    def _run_done(self, handle, result):
        if handle is not self.handle:
            return
        kind = self.run_kind
        self.handle = None
        self.run_kind = ""
        self.stopping = False
        self.paused_until = None
        platform.keep_awake(False)
        s = self.app.series
        if kind == "job":
            self._touch_books()
            self.chap = {}
            self.view = model.job_view(s.path) if s else js.JobView()
            b = self.app.steps.get("books")
            if b is not None and self.app.book:
                b.start_scan()
            self._check_terms()
            self._load_problems()
        elif kind == "sample":
            self._show_sample_rows()
        self._update_controls()
        self._refresh_numbers()
        self._refresh_quota()
        self.app.refresh_dot()

    # ------------------------------------------------------------- terms
    def _chip_clicked(self):
        if self._chip().key == "terms":
            self.app.show_terms_blockers()

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
        if s is None or self.running:
            return
        chapters = self._problem_chapters()
        book = self.view.book or self.app.book
        if not chapters or not book:
            self._set_problems([])
            return
        path = s.path
        if self.view.book and self.view.book == self.app.book and self.app.infos:
            infos = self.app.infos
            if not any(i < len(infos) and infos[i].failed for i in chapters) and not self.problems:
                pass
        self.problems_token = self.ui.worker.submit(
            lambda ctx: model.problems_task(ctx, path, book, chapters),
            on_result=lambda rows, p=path: self._set_problems(rows) if self.app.series and self.app.series.path == p
            else None, on_error=lambda e: None, lane="fast")

    def _set_problems(self, rows):
        self.problems = list(rows)
        self.problems_panel.set_problems(self.problems)
        self._update_controls()

    def _retry(self, rows):
        if not rows or self.running or self.view.foreign or not self._has_keys():
            return
        chapters = sorted({p.chapter for p in rows})
        s = self.app.series
        book = self.view.book or self.app.book
        cfg = self._config()
        self._begin_run("job", book, chapters)
        handle = self.handle
        self.ui.worker.submit(
            lambda ctx: model.run_task(ctx, handle, s.path, book, chapters, cfg, False),
            on_item=lambda item, h=handle: self._on_item(h, item), on_result=lambda r, h=handle: self._run_done(h, r),
            on_error=lambda exc, h=handle: self._run_failed(h, exc), lane="run")

    def _keep(self, rows):
        self._resolve(rows, "keep", "")

    def _save_typed(self, rows, text):
        self._resolve(rows, "manual", text)

    def _resolve(self, rows, action, typed):
        s = self.app.series
        if not rows or s is None or self.running or self.view.foreign:
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

    # ------------------------------------------------------------- sample
    def _start_sample(self):
        s = self.app.series
        idx = self._selection_indices()
        if s is None or not idx or self.running or self.view.foreign or not self._has_keys():
            return
        try:
            n = max(1, min(500, int(self.sample_n.get().strip() or "50")))
        except ValueError:
            n = 50
            self.sample_n.set("50")
        chapter, book, cfg = idx[0], self.app.book, self._config()
        self._begin_run("sample", book, [chapter])
        self.sample_info = (s.path, book, chapter, n)
        handle = self.handle
        self.ui.worker.submit(
            lambda ctx: model.sample_task(ctx, handle, s.path, book, chapter, n, cfg),
            on_item=lambda item, h=handle: self._on_item(h, item), on_result=lambda r, h=handle: self._run_done(h, r),
            on_error=lambda exc, h=handle: self._run_failed(h, exc), lane="run")

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
            return
        self._show_content()
        self.update_idletasks()
        s = self.app.series
        self.sample.set_rows(rows, model.target_label(s.target) if s else "")

    def _close_sample(self):
        self.sample_info = None
        self.sample.pack_forget()
