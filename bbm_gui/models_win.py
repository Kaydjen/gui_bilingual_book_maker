"""Models window: the models to use, in order (one per line). The next model is used when the previous one is used up."""
import tkinter as tk
from tkinter import ttk

from . import keypool
from .theme import P


class ModelsWindow(tk.Toplevel):
    def __init__(self, app, suggestions):
        super().__init__(app.root)
        self.app = app
        self.title("Models")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(420), app.px(320)))
        self.minsize(app.px(340), app.px(240))
        self.transient(app.root)
        pad = app.px(16)
        body = ttk.Frame(self, padding=(pad, pad, pad, a_px(app, 8)))
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="none", background=P["bg1"], foreground=P["text"], relief="flat", borderwidth=0,
                            padx=10, pady=8, font=(app.mono, 10), insertbackground=P["text"],
                            selectbackground=P["bg3"], highlightthickness=1, highlightbackground=P["line"],
                            highlightcolor=P["line"])
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", "\n".join(app.model_list()))
        foot = ttk.Frame(self, padding=(pad, 0, pad, pad))
        foot.pack(fill="x")
        for name in suggestions:
            ttk.Button(foot, text=name, style="Flat.TButton", command=lambda n=name: self.add(n)).pack(side="left")
        ttk.Button(foot, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        self.text.focus_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-Return>", lambda e: self.save())

    def add(self, name):
        if name not in keypool.parse(self.text.get("1.0", "end")):
            body = self.text.get("1.0", "end").strip()
            self.text.delete("1.0", "end")
            self.text.insert("1.0", (body + "\n" if body else "") + name)

    def save(self):
        self.app.model.set(", ".join(keypool.parse(self.text.get("1.0", "end"))))
        self.destroy()


def a_px(app, n):
    return app.px(n)
