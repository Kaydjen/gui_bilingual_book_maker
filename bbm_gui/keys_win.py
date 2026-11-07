"""Keys window: the API keys (one per Google project) in the order they are used, and the state of each."""
import threading
import time
import tkinter as tk
import urllib.error
import webbrowser
from tkinter import ttk

from . import keypool, models_api, runner
from .ordlist import InputField, OrderedList, SaveMark
from .theme import P

KEY_URL = "https://aistudio.google.com/apikey"


class KeysWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Keys")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(520), app.px(480)))
        self.minsize(app.px(420), app.px(360))
        self.transient(app.root)
        self._build()
        self.refresh()
        self.bind("<Escape>", lambda e: self.destroy())

    def _build(self):
        a = self.app
        pad = a.px(16)
        top = ttk.Frame(self, padding=(pad, pad, pad, a.px(8)))
        top.pack(fill="x")
        top.columnconfigure(0, weight=1)
        self.entry = InputField(top)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda e: self.add(), add="+")
        self.entry.bind("<<Paste>>", lambda e: self.after_idle(self.add), add="+")  # pasted keys go straight into the list
        self.entry.focus_set()
        ttk.Button(top, text="Add", command=self.add).grid(row=0, column=1, padx=(8, 0))
        link = ttk.Label(top, text="Get key", style="Link.TLabel", cursor="hand2")
        link.grid(row=0, column=2, padx=(14, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(KEY_URL))

        mid = ttk.Frame(self, padding=(pad, 0, pad, 0))
        mid.pack(fill="both", expand=True)
        self.list = OrderedList(mid, [("key", a.px(200), False), ("state", a.px(240), True)], self._render, self._tag,
                                on_move=self._moved, on_delete=self.remove)
        self.list.pack(fill="both", expand=True)

        foot = ttk.Frame(self, padding=(pad, a.px(8), pad, pad))
        foot.pack(fill="x")
        ttk.Button(foot, text="Remove", command=lambda: self.remove(self.list.selected())).pack(side="left")
        ttk.Button(foot, text="Clear used-up", style="Flat.TButton", command=self.reset_marks).pack(side="left", padx=(6, 0))
        self.mark = SaveMark(foot, a.save_state)
        self.mark.pack(side="right")


    # ------------------------------------------------------------------ rows
    def _state(self, key):
        return self.app.pool().state(key, time.time())

    def _render(self, key):
        st, until = self._state(key)
        if st == "bad":
            text = "Invalid"
        elif st == "dead":
            text = "No model available"
        elif st == "day":
            text = "Until " + runner.local_hhmm(until)
        elif st == "wait":
            text = "Wait " + runner.clock(until - time.time())
        elif st == "part":
            text = "Some models until " + runner.local_hhmm(until)
        elif key == self.app.active_key:
            text = "Running"
        else:
            text = "Ready"
        return keypool.mask(key), text

    def _tag(self, key):
        st = self._state(key)[0]
        return {"bad": "bad", "dead": "dim", "day": "dim", "wait": "dim"}.get(st, "")

    def tick(self):
        """Once a second: the countdowns in the state column."""
        if self.winfo_exists():
            self.list.rerender()

    # ------------------------------------------------------------------ actions
    def _set_keys(self, keys):
        self.app.key.set(",".join(keys))

    def add(self):
        tokens = keypool.parse(self.entry.get())
        if not tokens:
            return
        good = [k for k in tokens if keypool.looks_like_key(k)]
        self.entry.delete(0, "end")
        have = self.app.key_list()
        new = [k for k in good if k not in have]
        if new:
            self._set_keys(have + new)
            for k in new:
                threading.Thread(target=self._check, args=(k,), daemon=True).start()
        self.refresh()
        if new:
            self.list.flash(new)
        elif good:
            self.list.flash(good)  # already in the list: show where
        if len(good) < len(tokens):
            self.entry.say("Not a key", bad=True)
        elif not new:
            self.entry.say("Already added")

    def _check(self, key):
        """A cheap request (the model list) tells an invalid key at once; any answer also refreshes the model cache."""
        bad, names = False, None
        try:
            names = models_api.fetch(key)
        except urllib.error.HTTPError as e:
            bad = e.code in (400, 401, 403)
        except Exception:
            return  # no network: say nothing
        try:
            self.app.root.after(0, lambda: self._checked(key, bad, names))
        except (tk.TclError, RuntimeError):
            pass

    def _checked(self, key, bad, names):
        if names:
            self.app.settings["model_cache"] = names
        if bad and key in self.app.key_list():
            self.app.bad_keys.add(key)
            self.app.on_change()  # the row now says Invalid

    def _moved(self, keys):
        self._set_keys(keys)

    def remove(self, keys):
        running = self.app.runner.running
        drop = {k for k in keys if not (running and k == self.app.active_key)}  # the running key stays until the run ends
        if drop:
            self._set_keys([k for k in self.app.key_list() if k not in drop])
        self.refresh()
        if len(drop) < len(keys):
            self.list.flash([k for k in keys if k not in drop])
            self.entry.say("Running key stays", bad=True)

    def reset_marks(self):
        self.app.reset_marks()
        self.refresh()

    def refresh(self):
        if not self.winfo_exists():
            return
        self.list.set_items(self.app.key_list())
