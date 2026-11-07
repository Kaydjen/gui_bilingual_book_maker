"""Pace window: how many paragraphs go into one request, and the numbers the pace is computed from."""
import tkinter as tk
from tkinter import ttk

from . import estimate, pace
from .theme import P


class PaceWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Pace")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(480), app.px(330)))
        self.minsize(app.px(420), app.px(300))
        self.transient(app.root)
        self.choice = tk.IntVar(value=app.group_size())
        self._build()
        self.refresh()
        self.bind("<Escape>", lambda e: self.destroy())

    def _build(self):
        a = self.app
        pad = a.px(18)
        body = ttk.Frame(self, padding=(pad, pad, pad, pad))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Per request", style="Dim.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 16))
        seg = ttk.Frame(body)
        seg.grid(row=0, column=1, sticky="w")
        self.radios = []
        for n in pace.GROUPS:
            r = ttk.Radiobutton(seg, text=str(n), value=n, variable=self.choice, style="Seg.Toolbutton",
                                command=self._picked)
            r.pack(side="left", padx=(0, 2))
            self.radios.append(r)
        self.version_note = ttk.Label(seg, text="", style="Dim.TLabel")
        self.version_note.pack(side="left", padx=(12, 0))

        ttk.Separator(body).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 12))
        self.vars = {}
        for i, (key, title) in enumerate((("model", "Model"), ("limit", "Limit"), ("latency", "Request"),
                                          ("interval", "Interval"))):
            ttk.Label(body, text=title, style="Dim.TLabel").grid(row=2 + i, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            ttk.Label(body, textvariable=var).grid(row=2 + i, column=1, sticky="w", pady=2)
            self.vars[key] = var

        ttk.Separator(body).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 12))
        self.plan = tk.StringVar()
        ttk.Label(body, textvariable=self.plan, font=("TkDefaultFont", 12)).grid(row=7, column=0, columnspan=2, sticky="w")

    def _picked(self):
        self.app.set_per_request(self.choice.get())

    def refresh(self):
        if not self.winfo_exists():
            return
        a = self.app
        ok = pace.grouping_ok(a.py_version)
        for r in self.radios:
            r.configure(state="normal" if ok else "disabled")
        self.version_note.configure(text="" if ok or not a.py_version else "Python %d.%d" % tuple(a.py_version[:2]))
        self.choice.set(a.group_size())
        nums = a.pace_numbers()
        self.vars["model"].set(nums["model"] or "-")
        limit = "%d / min" % nums["rpm"] + (" · %d / day" % nums["rpd"] if nums["rpd"] else "")
        self.vars["limit"].set(limit)
        self.vars["latency"].set(("%.1f s" % nums["latency"]) if nums["measured"] else "~%.1f s" % nums["latency"])
        self.vars["interval"].set("%s s" % pace.fmt_interval(nums["interval"]))
        info = a.plan_info()
        self.plan.set(estimate.plan_line(info["requests"], info["seconds"], info["days"]) if info else "")
