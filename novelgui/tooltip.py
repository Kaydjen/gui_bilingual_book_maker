"""Hover tooltip drawn inside the window. Two parts (core_spec 12c): a plain explanation, then under a
thin line a fixed list of `name  value` facts. A plain string gives only the first part."""

from __future__ import annotations

import tkinter as tk

from . import theme as T
from .theme import DIM, TEXT

DELAY_MS = 600


def facts(names, values) -> list:
    return list(zip(names, values))


class Tip(tk.Frame):
    def __init__(self, root, font, cw):
        super().__init__(root, bg=T.TIP_LINE)
        self.font = font
        self.cw = cw
        self.inner = tk.Frame(self, bg=T.TIP_BG)
        self.inner.pack(padx=1, pady=1)
        px, py = int(cw * 0.9), int(cw * 0.5)
        self.px = px
        self.label = tk.Label(self.inner, bg=T.TIP_BG, fg=TEXT, font=font, justify="left", anchor="w",
                              padx=px, pady=py)
        self.label.pack(fill="x")
        self.sep = tk.Frame(self.inner, bg="#333333", height=1)
        self.facts = tk.Frame(self.inner, bg=T.TIP_BG)
        self.rows = []
        for r in range(8):
            n = tk.Label(self.facts, bg=T.TIP_BG, fg=DIM, font=font, anchor="w")
            v = tk.Label(self.facts, bg=T.TIP_BG, fg=TEXT, font=font, anchor="w")
            n.grid(row=r, column=0, sticky="w", padx=(0, int(cw * 2)))
            v.grid(row=r, column=1, sticky="w")
            self.rows.append((n, v))
        self.root = root
        self.job = None
        self.widget = None
        root.bind("<KeyPress>", lambda e: self.hide(), add="+")
        root.bind("<ButtonPress>", lambda e: self.hide(), add="+")

    def arm(self, widget, e, content):
        self.widget = widget
        x, y = e.x_root, e.y_root
        self.job = widget.after(DELAY_MS, lambda: self.show(x, y, content))

    def show(self, xr, yr, content):
        self.job = None
        cw = self.cw
        self.sep.pack_forget()
        self.facts.pack_forget()
        if isinstance(content, str):
            self.label.configure(text=content, wraplength=cw * 38)
        else:
            text, fl = content
            self.label.configure(text=text, wraplength=cw * 46)
            self.sep.pack(fill="x", padx=self.px)
            self.facts.pack(fill="x", padx=self.px, pady=(int(cw * 0.6), int(cw * 0.7)))
            pairs = list(fl)
            for r, (n, v) in enumerate(self.rows):
                if r < len(pairs):
                    name, val = pairs[r]
                    n.configure(text=name)
                    v.configure(text=val, fg=DIM if val in ("no", "-") else TEXT)
                    n.grid()
                    v.grid()
                else:
                    n.grid_remove()
                    v.grid_remove()
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        W, H = self.root.winfo_width(), self.root.winfo_height()
        x = xr - self.root.winfo_rootx() + 14
        y = yr - self.root.winfo_rooty() + 22
        if y + h > H - 4:
            y = yr - self.root.winfo_rooty() - h - 10
        x = max(4, min(x, W - w - 4))
        y = max(4, y)
        self.place(x=x, y=y)
        self.tk.call("raise", self._w)

    @property
    def visible(self) -> bool:
        return bool(self.winfo_ismapped())

    def text(self) -> str:
        """Visible text of the tooltip (for checks)."""
        parts = [self.label.cget("text")]
        for n, v in self.rows:
            if n.winfo_ismapped():
                parts.append("%s  %s" % (n.cget("text"), v.cget("text")))
        return "\n".join(parts)

    def hide(self):
        if self.job is not None and self.widget is not None:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
        self.job = None
        if self.winfo_ismapped():
            self.place_forget()


def attach_tip(widget, tip, fn):
    """fn(event) -> None | str | (text, facts)."""
    def moved(e):
        tip.hide()
        t = fn(e)
        if t:
            tip.arm(widget, e, t)
    widget.bind("<Motion>", moved, add="+")
    widget.bind("<Enter>", moved, add="+")
    for ev in ("<Leave>", "<ButtonPress>", "<MouseWheel>", "<KeyPress>"):
        widget.bind(ev, lambda e: tip.hide(), add="+")
