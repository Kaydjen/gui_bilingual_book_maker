"""Palette (black base, one red accent), fonts and the dark scrollbar style."""

from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

BG = "#000000"        # window
S1 = "#0b0b0b"        # table / pane surface
S2 = "#161616"        # controls
S3 = "#222222"        # hover / selected
S4 = "#2e2e2e"        # strong hover, focus borders
FLASH = "#515151"     # peak of the one-off row flash (a lighter shade of the base, never the accent)
LINE = "#1a1a1a"      # hairlines
ROWLINE = "#101010"
TEXT = "#dedede"
BRIGHT = "#f4f4f4"
DIM = "#8a8a8a"
FAINT = "#5a5a5a"
ACCENT = "#e5383b"
ACCENT_HOVER = "#ef4b4e"
TIP_BG = "#1b1b1b"
TIP_LINE = "#3a3a3a"


def blend(a: str, b: str, f: float) -> str:
    """Colour `a` moved the fraction `f` towards `b`."""
    pa = [int(a[k:k + 2], 16) for k in (1, 3, 5)]
    pb = [int(b[k:k + 2], 16) for k in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * f) for x, y in zip(pa, pb))


class Fonts:
    def __init__(self, root, scale=None):
        scale = scale or (float(os.environ["NOVELGUI_SCALE"]) if os.environ.get("NOVELGUI_SCALE") else None)
        if scale:
            root.tk.call("tk", "scaling", 96 / 72 * scale)
        fams = set(tkfont.families())
        fam = "Segoe UI" if "Segoe UI" in fams else tkfont.nametofont("TkDefaultFont").actual("family")
        self.normal = tkfont.Font(root=root, family=fam, size=10)
        self.bold = tkfont.Font(root=root, family=fam, size=10, weight="bold")
        self.small = tkfont.Font(root=root, family=fam, size=9)
        self.big = tkfont.Font(root=root, family=fam, size=15)
        self.ls = self.normal.metrics("linespace")
        self.cw = self.normal.measure("0")
        root.option_add("*Font", self.normal)


def style_ttk(root, fonts: Fonts) -> None:
    st = ttk.Style(root)
    st.theme_use("clam")
    st.layout("Dark.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    st.configure("Dark.Vertical.TScrollbar", troughcolor=S1, background=S3, bordercolor=S1,
                 lightcolor=S3, darkcolor=S3, relief="flat", borderwidth=0, arrowsize=int(fonts.ls * 0.55),
                 gripcount=0)
    st.map("Dark.Vertical.TScrollbar", background=[("active", S4), ("pressed", "#3a3a3a")],
           lightcolor=[("active", S4), ("pressed", "#3a3a3a")], darkcolor=[("active", S4), ("pressed", "#3a3a3a")])
