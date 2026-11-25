"""The queue list on Translate (window_spec 7.5): the running job first, then the queued items.

Rows are rebuilt only when what they show changes, so the list does not flicker while the clock ticks.
"""

from __future__ import annotations

import tkinter as tk

from . import langrules, model, platform, tips
from .theme import BG, BRIGHT, DIM, FAINT, LINE, S1, TEXT
from .tooltip import attach_tip
from .widgets import DotsButton, Pill


class QueueList(tk.Frame):
    def __init__(self, master, ui, app, place_opts=None):
        super().__init__(master, bg=BG, highlightthickness=1, highlightbackground=LINE)
        self.place_opts = place_opts or {}
        self.ui = ui
        self.app = app
        self.gap = int(ui.ls * 0.5)
        self.sig = None
        self.rows: list = []

    # ------------------------------------------------------------- what is shown
    def wanted(self) -> bool:
        runs = self.app.runs
        cur = self.app.series.path if self.app.series is not None else ""
        other = runs.job_running and runs.run.series != cur
        return bool(len(runs.queue) or other)

    def _label(self, path: str, book: str, reach: str) -> str:
        info = self.app.series_info(path)
        if info is None:
            return "%s · gone" % path.replace("\\", "/").rsplit("/", 1)[-1]
        parts = [info.name]
        if len(info.books) > 1 and book:
            parts.append(info.label_of(book))
        if reach:
            parts.append(reach)
        lang = model.series_language(info)
        if lang:
            parts.append(langrules.label(lang, model.TARGETS))
        return " · ".join(parts)

    def _item_tip(self, path: str):
        try:
            st = model.series_settings(path)
        except Exception:
            return tips.QUEUE_ITEM[0]
        name = str(st.get("prompt") or "default")
        info = self.app.series_info(path)
        lang = model.series_language(info) if info is not None else None
        pr = st.get("per_request")
        return tips.fill(tips.QUEUE_ITEM, "Default" if name.lower() == "default" else name,
                         pr if pr in (1, 5, 10) else 5, langrules.label(lang, model.TARGETS) if lang else "not chosen")

    def signature(self):
        runs = self.app.runs
        r = runs.run if runs.job_running else None
        return (None if r is None else (r.series, r.book, r.stopping, r.name),
                tuple((i.series, i.book, i.spans, i.reach, self._label(i.series, i.book, i.reach))
                      for i in runs.queue.items),
                runs.sched.status(), runs.sched.why, runs.sched.halted, runs.running,
                self.app.series.path if self.app.series is not None else "")

    # ------------------------------------------------------------- build
    def refresh(self) -> None:
        if not self.wanted():
            if self.winfo_manager():
                self.pack_forget()
            self.sig = None
            return
        sig = self.signature()
        if sig == self.sig and self.winfo_manager():
            return
        self.sig = sig
        self._build()

    def _row(self):
        row = tk.Frame(self, bg=S1)
        row.pack(fill="x", padx=self.gap, pady=(self.gap // 2, self.gap // 2))
        return row

    def _build(self) -> None:
        for w in self.winfo_children():
            w.destroy()
        ui, runs, f = self.ui, self.app.runs, self.ui.font
        gap = self.gap
        r = runs.run if runs.job_running else None
        if r is not None:
            row = self._row()
            lab = tk.Label(row, text="▶ " + self._label(r.series, r.book, ""), bg=S1, fg=BRIGHT, font=f,
                           anchor="w")
            lab.pack(side="left", fill="x", expand=True)
            stop = Pill(row, "Stop", runs.stop, f, kind="plain", bg=S1)
            stop.set_enabled(not r.stopping)
            stop.pack(side="right")
            self.stop_btn = stop
            attach_tip(lab, ui.tip, lambda e: tips.fill(tips.QUEUE_RUNNING, r.name))
            attach_tip(stop, ui.tip, lambda e: tips.Z1_STOP)
        status = runs.sched.status()
        if status and (runs.queue or runs.sched.wait is not None):
            row = self._row()
            st = tk.Label(row, text=status, bg=S1, fg=DIM, font=f, anchor="w")
            st.pack(side="left")
            why = runs.sched.why
            attach_tip(st, ui.tip, lambda e: why or tips.IND_QUEUE[0])
            if runs.queue and runs.sched.halted and not runs.running:
                self.continue_btn = Pill(row, "Continue queue", runs.continue_queue, f, kind="plain", bg=S1)
                self.continue_btn.pack(side="right")
                attach_tip(self.continue_btn, ui.tip, lambda e: tips.QUEUE_CONTINUE)
            if runs.sched.wait is not None:
                stopw = Pill(row, "Stop", runs.stop_wait, f, kind="plain", bg=S1)
                stopw.pack(side="right")
                attach_tip(stopw, ui.tip, lambda e: tips.Z1_STOP_WAIT)
        n = len(runs.queue.items)
        for k, it in enumerate(runs.queue.items):
            row = self._row()
            lab = tk.Label(row, text=self._label(it.series, it.book, it.reach), bg=S1, fg=TEXT, font=f, anchor="w")
            lab.pack(side="left", fill="x", expand=True)
            x = tk.Label(row, text="✕", bg=S1, fg=DIM, font=f, cursor="hand2", padx=int(ui.cw * 0.8))
            x.pack(side="right")
            x.bind("<Button-1>", lambda e, s=it.series: runs.dequeue(s))
            x.bind("<Enter>", lambda e, w=x: w.configure(fg=BRIGHT))
            x.bind("<Leave>", lambda e, w=x: w.configure(fg=DIM))
            dots = DotsButton(row, int(ui.ls * 1.25), lambda e, it=it, k=k: self._menu(it, k, n, e), bg=S1)
            dots.pack(side="right")
            attach_tip(lab, ui.tip, lambda e, p=it.series: self._item_tip(p))
            attach_tip(x, ui.tip, lambda e: tips.QUEUE_REMOVE)
            attach_tip(dots, ui.tip, lambda e: tips.QUEUE_MORE)
        self.pack(fill="x", pady=(0, int(ui.ls * 0.6)), **self.place_opts)

    def _menu(self, item, k, n, e) -> None:
        items, labels, disabled = ["up", "down"], {"up": "Move up", "down": "Move down"}, []
        if k == 0:
            disabled.append("up")
        if k == n - 1:
            disabled.append("down")
        runs = self.app.runs

        def pick(key, nxt):
            runs.move(item.series, -1 if key == "up" else 1)
        root = self.ui.root
        self.ui.menu.show(root, e.x_root - root.winfo_rootx(), e.y_root - root.winfo_rooty(), self.ui.cw * 16,
                          items, items[0], pick, labels=labels, disabled=disabled)
