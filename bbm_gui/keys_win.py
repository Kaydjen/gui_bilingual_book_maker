"""Keys window: the list of API keys (one per Google project) and what state each one is in."""
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import keypool, runner
from .theme import P

KEY_URL = "https://aistudio.google.com/apikey"


class KeysWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Keys")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(520), app.px(440)))
        self.minsize(app.px(420), app.px(320))
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
        self.entry = tk.Text(top, height=3, wrap="char", background=P["bg1"], foreground=P["text"], relief="flat",
                             borderwidth=0, padx=10, pady=8, font=(a.mono, 9), insertbackground=P["text"],
                             selectbackground=P["bg3"], highlightthickness=1, highlightbackground=P["line"],
                             highlightcolor=P["line"])
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Control-Return>", lambda e: (self.add(), "break")[1])
        self.entry.bind("<<Paste>>", lambda e: self.after_idle(self.add))  # pasted keys go straight into the list
        self.entry.focus_set()
        ttk.Button(top, text="Add", style="Accent.TButton", command=self.add).grid(row=0, column=1, padx=(8, 0), sticky="ns")

        mid = ttk.Frame(self, padding=(pad, 0, pad, 0))
        mid.pack(fill="both", expand=True)
        cols = ("n", "key", "state")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        for c, w, anchor in (("n", 40, "e"), ("key", 200, "w"), ("state", 200, "w")):
            self.tree.heading(c, text={"n": "#", "key": "Key", "state": "State"}[c])
            self.tree.column(c, width=a.px(w), anchor=anchor, stretch=(c == "state"))
        self.tree.tag_configure("used", foreground=P["dim"])
        self.tree.tag_configure("bad", foreground=P["accent"])
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Delete>", lambda e: self.remove())

        foot = ttk.Frame(self, padding=(pad, a.px(8), pad, pad))
        foot.pack(fill="x")
        ttk.Button(foot, text="Remove", command=self.remove).pack(side="left")
        ttk.Button(foot, text="Reset marks", style="Flat.TButton", command=self.reset_marks).pack(side="left", padx=(6, 0))
        link = ttk.Label(foot, text="Get key", style="Link.TLabel", cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: webbrowser.open(KEY_URL))

    # ------------------------------------------------------------------ actions
    def _set_keys(self, keys):
        self.app.key.set(",".join(keys))

    def add(self):
        new = keypool.parse(self.entry.get("1.0", "end"))
        if new:
            have = self.app.key_list()
            self._set_keys(have + [k for k in new if k not in have])
        self.entry.delete("1.0", "end")
        self.refresh()

    def remove(self):
        keys = self.app.key_list()
        drop = {int(self.tree.set(i, "n")) - 1 for i in self.tree.selection()}
        self._set_keys([k for n, k in enumerate(keys) if n not in drop])
        self.refresh()

    def reset_marks(self):
        self.app.reset_marks()
        self.refresh()

    # ------------------------------------------------------------------ view
    def refresh(self):
        if not self.winfo_exists():
            return
        pool = self.app.pool()
        now = time.time()
        self.tree.delete(*self.tree.get_children())
        for n, key in enumerate(pool.keys, 1):
            st, until = pool.state(key, now)
            if st == "bad":
                text, tag = "Invalid", "bad"
            elif st == "used":
                text, tag = "Used up until " + runner.local_hhmm(until), "used"
            elif st == "part":
                text, tag = "Some models used up until " + runner.local_hhmm(until), ""
            elif key == self.app.active_key:
                text, tag = "Running", ""
            else:
                text, tag = "Ready", ""
            self.tree.insert("", "end", values=(n, keypool.mask(key), text), tags=(tag,) if tag else ())
