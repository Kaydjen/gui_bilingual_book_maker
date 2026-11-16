"""Pieces of the Translate step: the prompt editor, the side-by-side sample panes, the list of failed blocks."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import chapterlogic as cl
from . import findingrules, jobstate
from .dialog import Modal
from .theme import ACCENT, BG, BRIGHT, DIM, FAINT, LINE, S1, S2, S4, TEXT
from .tooltip import attach_tip
from .vtable import Col, VTable
from .widgets import Field, Pill


def dark_text(master, ui, height: int = 3, editable: bool = True, bg=S1, **kw) -> tk.Text:
    pad = int(ui.ls * 0.5)
    t = tk.Text(master, bg=bg, fg=TEXT if editable else DIM, font=ui.font, bd=0, relief="flat", highlightthickness=1,
                highlightbackground=LINE, highlightcolor=S4, wrap="word", height=height, padx=pad,
                pady=int(ui.ls * 0.3), insertbackground=BRIGHT, insertwidth=2, selectbackground=S4,
                selectforeground="#ffffff", undo=editable, **kw)
    return t


def set_text(t: tk.Text, text: str) -> None:
    state = str(t.cget("state"))
    t.configure(state="normal")
    t.delete("1.0", "end")
    t.insert("1.0", text)
    t.configure(state=state)


# ---------------------------------------------------------------- prompt editor
class PromptEditor(Modal):
    """Name and text of a prompt. Save stores it in the prompt library and hands (name, text) to `on_save`."""

    def __init__(self, ui, name: str, text: str, taken, on_save, series: str = ""):
        super().__init__(ui)
        self.on_save = on_save
        self.taken = taken          # callable(name) -> error text or ""
        self.series = series        # key of the unsaved draft (the series folder); empty = no draft
        self.orig = (name, text)
        self._finished = False
        draft = ui.winstate.prompt_draft(series) if series else None
        if draft is not None and draft != self.orig:
            name, text = draft
        f = ui.font
        pad, gap = self.pad, int(ui.ls * 0.6)
        body = self.body
        tk.Label(body, text="Name", bg=S2, fg=DIM, font=f, anchor="w").pack(anchor="w", padx=pad, pady=(pad, 2))
        self.name = Field(body, f, on_change=lambda s: self._check(), on_submit=lambda s: self._save(), bg=S2,
                          width=ui.cw * 40, surface=S1)
        self.name.pack(fill="x", padx=pad)
        self.name.set(name)
        tk.Label(body, text="Text", bg=S2, fg=DIM, font=f, anchor="w").pack(anchor="w", padx=pad, pady=(gap, 2))
        self.text = dark_text(body, ui, height=16, bg=S1)
        self.text.configure(width=int(ui.cw * 0.9 * 12))
        self.text.pack(fill="both", expand=True, padx=pad)
        self.text.insert("1.0", text)
        row = tk.Frame(body, bg=S2)
        row.pack(fill="x", padx=pad, pady=(gap, 0))
        self.save_btn = Pill(row, "Save", self._save, f, kind="accent", bg=S2)
        self.save_btn.pack(side="right")
        Pill(row, "Cancel", self._cancel, f, kind="dim", bg=S2).pack(side="right", padx=(0, gap // 2))
        attach_tip(self.save_btn, ui.tip, lambda e: None if self.save_btn.enabled else (self._err or "Give the prompt a name."))
        attach_tip(self.text, ui.tip, lambda e: (
            "The instructions sent with every request. {language} is replaced by the series language.",
            [("Placeholder", "{language}"), ("Saved in", "the app data folder")]))
        self._err = ""
        self._check()
        self.show()
        self.name.entry.focus_set()

    def _check(self):
        if not hasattr(self, "save_btn"):
            return
        name = self.name.get().strip()
        self._err = self.taken(name) if name else "Give the prompt a name."
        self.save_btn.set_enabled(not self._err)

    def _save(self):
        if not self.save_btn.enabled:
            return
        name, text = self.name.get().strip(), self.text.get("1.0", "end-1c")
        self._finished = True
        if self.series:
            self.ui.winstate.clear_prompt_draft(self.series)
        self.close()
        self.on_save(name, text)

    def _cancel(self):
        """The Cancel button throws the edit away; Esc and a press outside keep it as a draft."""
        self._finished = True
        if self.series:
            self.ui.winstate.clear_prompt_draft(self.series)
        self.close()

    def close(self):
        if self.is_open and not self._finished and self.series:
            cur = (self.name.get(), self.text.get("1.0", "end-1c"))
            if cur != self.orig:
                self.ui.winstate.set_prompt_draft(self.series, *cur)
            else:
                self.ui.winstate.clear_prompt_draft(self.series)
        super().close()


# ---------------------------------------------------------------- sample panes
class SamplePanel(tk.Frame):
    """Original on the left, the translation on the right; one block per row, the two panes scroll together."""

    def __init__(self, master, ui, on_close):
        super().__init__(master, bg=BG)
        self.ui = ui
        self.rows: list = []
        self._syncing = False
        self._job = None
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", pady=(0, 2))
        self.left_label = tk.Label(head, text="Original", bg=BG, fg=DIM, font=ui.font, anchor="w")
        self.left_label.pack(side="left", expand=True, fill="x")
        self.right_label = tk.Label(head, text="", bg=BG, fg=DIM, font=ui.font, anchor="w")
        self.right_label.pack(side="left", expand=True, fill="x")
        self.close_btn = tk.Label(head, text="×", bg=BG, fg=DIM, font=ui.font, cursor="hand2", padx=6)
        self.close_btn.pack(side="right")
        self.close_btn.bind("<Button-1>", lambda e: on_close())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.configure(fg=BRIGHT))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.configure(fg=DIM))
        attach_tip(self.close_btn, ui.tip, lambda e: "Close the sample. Nothing of it is part of the book.")
        body = tk.Frame(self, bg=S1, highlightthickness=1, highlightbackground=LINE)
        body.pack(fill="both", expand=True)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1, uniform="p")
        body.grid_columnconfigure(1, weight=1, uniform="p")
        pad = int(ui.ls * 0.9)
        self.sb = ttk.Scrollbar(body, orient="vertical", style="Dark.Vertical.TScrollbar", command=self._sb_cmd)
        self.left = self._pane(body, pad, lambda a, b: self._yset(0, a, b))
        self.right = self._pane(body, pad, lambda a, b: self._yset(1, a, b))
        self.left.grid(row=0, column=0, sticky="nsew")
        self.right.grid(row=0, column=1, sticky="nsew")
        self.sb.grid(row=0, column=2, sticky="ns")
        body.bind("<Configure>", lambda e: self._later())

    def _pane(self, master, pad, ycmd):
        ui = self.ui
        t = tk.Text(master, bg=S1, fg=TEXT, font=ui.font, bd=0, relief="flat", highlightthickness=0, wrap="word",
                    padx=pad, pady=int(ui.ls * 0.35), height=1, cursor="xterm", spacing1=0, spacing3=0,
                    selectbackground=S4, selectforeground="#ffffff", insertwidth=0, state="disabled",
                    yscrollcommand=ycmd)
        t.tag_configure("dim", foreground=DIM)
        t.tag_configure("fail", foreground=DIM)
        t.tag_raise("sel")
        t.bind("<MouseWheel>", self._wheel)
        t.bind("<Button-1>", lambda e: t.focus_set(), add="+")
        return t

    # -- scrolling together
    def _sb_cmd(self, *a):
        self.left.yview(*a)
        self.right.yview(*a)

    def _yset(self, which, first, last):
        self.sb.set(first, last)
        if self._syncing:
            return
        self._syncing = True
        try:
            other = self.right if which == 0 else self.left
            other.yview_moveto(first)
        finally:
            self._syncing = False

    def _wheel(self, e):
        n = -int(round(e.delta / 120.0)) * 3
        self.left.yview_scroll(n, "units")
        return "break"

    # -- content
    def set_rows(self, rows, right_title: str, left_title: str = "Original") -> None:
        self.rows = list(rows)
        self.left_label.configure(text=left_title)
        self.right_label.configure(text=right_title)
        self._render()

    def _later(self):
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(120, self._render)

    def _render(self):
        self._job = None
        L, R = self.left, self.right
        for t in (L, R):
            t.configure(state="normal")
            t.delete("1.0", "end")
        for src, tr, reason in self.rows:
            L.insert("end", src + "\n\n")
            if tr is not None:
                R.insert("end", tr + "\n\n")
            else:
                R.insert("end", ("failed: " + reason if reason else "not translated") + "\n\n", "fail")
        self.update_idletasks()
        if L.winfo_width() > 50 and R.winfo_width() > 50:
            for k in range(len(self.rows) - 1, -1, -1):
                ln = 2 * k + 1
                a = self._lines(L, ln)
                b = self._lines(R, ln)
                if a < b:
                    L.insert("%d.end" % ln, "\n" * (b - a))
                elif b < a:
                    R.insert("%d.end" % ln, "\n" * (a - b))
        for t in (L, R):
            t.configure(state="disabled")

    @staticmethod
    def _lines(t, ln) -> int:
        try:
            return int(t.tk.call(str(t), "count", "-displaylines", "%d.0" % ln, "%d.end" % ln))
        except (tk.TclError, ValueError):
            return 0

    def texts(self) -> tuple:
        return self.left.get("1.0", "end-1c"), self.right.get("1.0", "end-1c")


# ---------------------------------------------------------------- failed blocks
class ProblemTable(VTable):
    def __init__(self, master, ui):
        super().__init__(master, ui, [Col("title", "Chapter", 22, sortable=False),
                                      Col("block", "Block", 7, "e", sortable=False),
                                      Col("source", "Source", None, sortable=False),
                                      Col("reason", "Reason", 14, sortable=False)], resizable=False)

    def draw_cells(self, c, p, cols, y, mid):
        f = self.font
        x, w = cols["title"]
        label = "%d  %s" % (cl.display_no(p.chapter), p.title) if p.title else str(cl.display_no(p.chapter))
        c.create_text(x + self.pad, y + mid, text=self.fit(label, w - 2 * self.pad), anchor="w", font=f, fill=TEXT)
        x, w = cols["block"]
        c.create_text(x + w - self.pad, y + mid, text=str(cl.display_no(p.block)), anchor="e", font=f, fill=DIM)
        x, w = cols["source"]
        c.create_text(x + self.pad, y + mid, text=self.fit(jobstate.shorten(p.source, 300), w - 2 * self.pad),
                      anchor="w", font=f, fill=TEXT)
        x, w = cols["reason"]
        c.create_text(x + self.pad, y + mid, text=self.fit(p.reason, w - 2 * self.pad), anchor="w", font=f, fill=DIM)

    def tip_body(self, e):
        i = self.row_at(e.y)
        if i is None:
            return None
        p = self.rows[i]
        col = self.col_at(e.x)
        if col == "source":
            if p.is_finding:
                return (p.detail or findingrules.KIND_TIPS.get(p.kind, ""),
                        [("Chapter", str(cl.display_no(p.chapter))), ("Block", str(cl.display_no(p.block))),
                         ("Found by", "the check"), ("Translation", jobstate.shorten(p.text, 160))])
            return (p.source, [("Chapter", str(cl.display_no(p.chapter))), ("Block", str(cl.display_no(p.block))),
                               ("Reason", p.reason)])
        if col == "reason":
            if p.is_finding:
                return (findingrules.KIND_TIPS.get(p.kind, p.reason), [("Found by", "the check"),
                                                                       ("Counts as", "translated")])
            return REASONS.get(p.reason, "The translation of this block was refused or unusable, even when sent alone.")
        return None

    def tip_head(self, e):
        c = self.col_at(e.x)
        if c == "reason":
            return ("Why the block is listed: it could not be translated after it was sent alone, or the check found "
                    "something suspicious in its translation.")
        if c == "block":
            return "The position of the block in its chapter, counting from 1."
        return None


REASONS = {
    "empty": "The answer was empty.",
    "length": "The translation was far shorter or longer than the original.",
    "script": "The answer was not written in the target language's script.",
    "language": "The answer was left in English.",
    "missing": "The answer lacked this paragraph.",
}


class ProblemsPanel(tk.Frame):
    """The failed blocks of the job's chapters, and what to do with them."""

    def __init__(self, master, ui, retry, keep, save, ignore=None):
        super().__init__(master, bg=BG)
        self.ui = ui
        self.problems: list = []
        self._enabled = True
        self._shown_text = None
        self._retry, self._keep, self._save_cb, self._ignore = retry, keep, save, ignore
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", pady=(0, 2))
        tk.Label(head, text="Problems", bg=BG, fg=DIM, font=ui.font).pack(side="left")
        self.count = tk.Label(head, text="0", bg=BG, fg=DIM, font=ui.font)
        self.count.pack(side="left", padx=(ui.cw, 0))
        self.table = ProblemTable(self, ui)
        self.table.pack(fill="both", expand=True)
        self.table.on_changed = self._selected
        self.table.wire_tips()
        gap = int(ui.ls * 0.5)
        det = tk.Frame(self, bg=BG)
        det.pack(fill="x", pady=(gap, 0))
        det.grid_columnconfigure(0, weight=1, uniform="d")
        det.grid_columnconfigure(1, weight=1, uniform="d")
        self.source = dark_text(det, ui, height=3, editable=False)
        self.source.configure(state="disabled")
        self.source.grid(row=0, column=0, sticky="ew", padx=(0, gap // 2))
        self.typed = dark_text(det, ui, height=3, editable=True)
        self.typed.grid(row=0, column=1, sticky="ew", padx=(gap // 2, 0))
        self.typed.bind("<KeyRelease>", lambda e: self._update())
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", pady=(gap, 0))
        f = ui.font
        self.retry_btn = Pill(row, "Retry", self._do_retry, f)
        self.keep_btn = Pill(row, "Keep original", self._do_keep, f)
        self.ignore_btn = Pill(row, "Ignore", self._do_ignore, f, kind="dim")
        self.save_btn = Pill(row, "Save", self._do_save, f)
        self.retry_btn.pack(side="left")
        self.keep_btn.pack(side="left", padx=(gap, 0))
        self.ignore_btn.pack(side="left", padx=(gap, 0))
        self.save_btn.pack(side="right")
        attach_tip(self.retry_btn, ui.tip, lambda e: self._retry_tip())
        attach_tip(self.ignore_btn, ui.tip, lambda e: (
            "Hide the selected check findings. A finding comes back only when the translation of its block "
            "changes. The blocks stay as they are.",
            [("Applies to", "selected check findings"), ("Remembered in", "the series folder")]))
        attach_tip(self.keep_btn, ui.tip, lambda e: (
            "Put the original text into the book for the selected blocks. They count as translated.",
            [("Applies to", "selected rows"), ("Marked", "kept")]))
        attach_tip(self.save_btn, ui.tip, lambda e: (
            "Use the text typed on the right as the translation of the selected block.",
            [("Applies to", "one selected row"), ("Marked", "manual")]))
        attach_tip(self.typed, ui.tip, lambda e: "Type the translation of the selected block here.")
        self._update()

    def _retry_tip(self):
        if self._mixed():
            return "Select failed blocks or check findings, not both: they are translated again in separate runs."
        if any(p.is_finding for p in self.selected()):
            return ("Translate the selected findings again. Only these blocks are sent. It starts like a "
                    "translation: after the running one, or after you confirm replacing an unfinished job; until "
                    "then the chapters stay as they are.",
                    [("Applies to", "selected check findings"), ("Uses", "requests of today")])
        return ("Translate these blocks again. The chapters that hold them are sent once more; blocks that are "
                "already translated are skipped, so only failed blocks cost requests.",
                [("Applies to", "chapters of the selected rows"), ("Uses", "requests of today")])

    def _mixed(self) -> bool:
        kinds = {p.is_finding for p in self.selected()}
        return len(kinds) > 1

    def set_problems(self, problems) -> None:
        keep = {(p.chapter, p.block) for p in self.table.selected_rows()}
        self.problems = list(problems)
        self.table.set_rows(self.problems, {id(p) for p in self.problems if (p.chapter, p.block) in keep})
        self.count.configure(text=str(len(self.problems)))
        self._shown_text = None
        self._selected()

    def set_accent(self, on: bool) -> None:
        self.count.configure(fg=ACCENT if on else DIM)

    def set_enabled(self, v: bool) -> None:
        self._enabled = v
        self._update()

    def selected(self) -> list:
        return self.table.selected_rows()

    def _selected(self):
        sel = self.table.selected_rows()
        set_text(self.source, sel[0].source if len(sel) == 1 else "")
        key = (sel[0].chapter, sel[0].block, sel[0].kind) if len(sel) == 1 else None
        if key != self._shown_text:
            self._shown_text = key
            if key is not None and sel[0].is_finding:       # a finding: the text it was made on, ready to edit
                self.typed.configure(state="normal")
                self.typed.delete("1.0", "end")
                self.typed.insert("1.0", sel[0].text)
        self._update()

    def _update(self):
        n = len(self.table.selected_rows())
        on = self._enabled and n > 0
        sel = self.table.selected_rows()
        self.retry_btn.set_enabled(on and not self._mixed())
        self.keep_btn.set_enabled(on)
        self.ignore_btn.set_enabled(self._enabled and n > 0 and all(p.is_finding for p in sel))
        self.save_btn.set_enabled(self._enabled and n == 1 and bool(self.typed.get("1.0", "end-1c").strip()))
        self.typed.configure(state="normal" if self._enabled and n == 1 else "disabled")

    def _do_retry(self):
        self._retry(self.selected())

    def _do_ignore(self):
        sel = [p for p in self.selected() if p.is_finding]
        if sel and self._ignore is not None:
            self._ignore(sel)

    def _do_keep(self):
        self._keep(self.selected())

    def _do_save(self):
        sel = self.selected()
        if len(sel) == 1:
            self._save_cb(sel, self.typed.get("1.0", "end-1c"))
            self.typed.delete("1.0", "end")
