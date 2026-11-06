"""Models window: every model the key offers in one list; checked ones are used, top to bottom."""
import threading
import time
import tkinter as tk
import urllib.error
from tkinter import ttk

from . import keypool, models_api, runner
from .ordlist import InputField, OrderedList, SaveMark
from .theme import P

ON, OFF = "☑", "☐"


class ModelsWindow(tk.Toplevel):
    def __init__(self, app, fallback):
        super().__init__(app.root)
        self.app = app
        self.title("Models")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(520), app.px(500)))
        self.minsize(app.px(420), app.px(360))
        self.transient(app.root)
        self.known = list(app.settings.get("model_cache") or fallback)
        self._build()
        self.refresh()
        self.bind("<Escape>", lambda e: self.destroy())
        self.fetch()

    def _build(self):
        a = self.app
        pad = a.px(16)
        top = ttk.Frame(self, padding=(pad, pad, pad, a.px(8)))
        top.pack(fill="x")
        top.columnconfigure(0, weight=1)
        self.entry = InputField(top)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda e: self.add(), add="+")
        self.entry.bind("<<Paste>>", lambda e: self.after_idle(self.add), add="+")
        self.entry.focus_set()
        ttk.Button(top, text="Add", command=self.add).grid(row=0, column=1, padx=(8, 0))

        mid = ttk.Frame(self, padding=(pad, 0, pad, 0))
        mid.pack(fill="both", expand=True)
        self.list = OrderedList(mid, [("use", a.px(34), False), ("name", a.px(240), False), ("state", a.px(160), True)],
                                self._render, self._tag, on_move=self._moved, on_delete=self._uncheck, on_cell=self._cell)
        self.list.pack(fill="both", expand=True)

        foot = ttk.Frame(self, padding=(pad, a.px(8), pad, pad))
        foot.pack(fill="x")
        ttk.Button(foot, text="Remove", command=lambda: self._uncheck(self.list.selected())).pack(side="left")
        ttk.Button(foot, text="Refresh", style="Flat.TButton", command=self.fetch).pack(side="left", padx=(6, 0))
        self.mark = SaveMark(foot, a.save_state)
        self.mark.pack(side="right")
        self.status = ttk.Label(foot, text="", style="Dim.TLabel")
        self.status.pack(side="right", padx=(0, 16))

    # ------------------------------------------------------------------ rows
    def _state(self, model):
        pool = self.app.pool()
        now = time.time()
        keys = pool.keys
        spent = [k for k in keys if pool.is_spent(k, model, now)]
        if keys and len(spent) == len(keys):
            return "used", "Used up until " + runner.local_hhmm(min(pool.spent[pool._id(k, model)] for k in spent))
        if spent:
            return "part", "Used up on %d of %d keys" % (len(spent), len(keys))
        if self.app.runner.running and self.app.cur_pair and self.app.cur_pair[1] == model:
            return "run", "Running"
        return "", ""

    def _render(self, model):
        return (ON if model in self.app.model_list() else OFF), model, self._state(model)[1]

    def _tag(self, model):
        if model not in self.app.model_list():
            return "dim"
        return "dim" if self._state(model)[0] == "used" else ""

    # ------------------------------------------------------------------ actions
    def _apply(self, models):
        self.app.model.set(", ".join(models))

    def _cell(self, model, column):
        if column != "#1":
            return False
        chosen = self.app.model_list()
        self._apply([m for m in chosen if m != model] if model in chosen else chosen + [model])
        return True

    def _uncheck(self, models):
        self._apply([m for m in self.app.model_list() if m not in models])

    def _moved(self, items):
        self._apply(items[:len(self.app.model_list())])

    def add(self):
        names = keypool.parse(self.entry.get())
        if not names:
            return
        self.entry.delete(0, "end")
        chosen = self.app.model_list()
        for n in names:
            if n not in self.known:
                self.known.append(n)
        new = [n for n in names if n not in chosen]
        self._apply(chosen + new)
        self.refresh()
        self.list.flash(names)
        if not new:
            self.entry.say("Already in use")

    def refresh(self):
        if not self.winfo_exists():
            return
        chosen = self.app.model_list()
        rest = [m for m in self.known if m not in chosen]
        self.list.set_items(chosen + rest, len(chosen))

    # ------------------------------------------------------------------ list from the API
    def fetch(self):
        keys = [k for k in self.app.key_list() if k not in self.app.bad_keys]
        if not keys:
            return
        self.status.configure(text="Loading")

        def work():
            names, err = None, "Offline"
            for key in keys:
                try:
                    names = models_api.fetch(key)
                    break
                except urllib.error.HTTPError as e:
                    err = "Key"
                    if e.code not in (400, 401, 403):
                        break
                except Exception:
                    break
            try:
                self.after(0, lambda: self._loaded(names, err))
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, names, err):
        if not self.winfo_exists():
            return
        if names:
            extra = [m for m in self.app.model_list() if m not in names]
            self.known = names + extra
            self.app.settings["model_cache"] = names
        self.status.configure(text="" if names else err)
        self.refresh()
