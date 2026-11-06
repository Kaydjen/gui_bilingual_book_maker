"""One main colour (slate) in shades plus one accent."""
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

P = {
    "bg0": "#171a1f",    # window
    "bg1": "#1f2329",    # fields, log, command
    "bg2": "#2a2f37",    # buttons
    "bg3": "#363d47",    # hover, selected
    "line": "#3a424d",
    "text": "#dfe4ea",
    "dim": "#8b95a1",
    "faint": "#5b6572",
    "accent": "#f2b13a",
    "on_accent": "#1a1405",
}


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


def mono_family(root):
    families = set(tkfont.families(root))
    for name in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo", "Courier New"):
        if name in families:
            return name
    return "TkFixedFont"


def apply(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    base = tkfont.nametofont("TkDefaultFont")
    base.configure(size=10)
    root.option_add("*Font", base)
    root.configure(background=P["bg0"])
    root.option_add("*TCombobox*Listbox.background", P["bg1"])
    root.option_add("*TCombobox*Listbox.foreground", P["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", P["bg3"])
    root.option_add("*TCombobox*Listbox.selectForeground", P["text"])
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    style.configure(".", background=P["bg0"], foreground=P["text"], fieldbackground=P["bg1"],
                    bordercolor=P["line"], lightcolor=P["line"], darkcolor=P["line"], troughcolor=P["bg1"],
                    focuscolor=P["bg0"], insertcolor=P["text"], selectbackground=P["bg3"], selectforeground=P["text"])
    style.configure("TFrame", background=P["bg0"])
    style.configure("TLabel", background=P["bg0"], foreground=P["text"])
    style.configure("Dim.TLabel", foreground=P["dim"])
    style.configure("Accent.TLabel", foreground=P["accent"])
    style.configure("Link.TLabel", foreground=P["dim"])
    style.configure("Group.TLabel", foreground=P["dim"], font=(base.actual("family"), 9, "bold"))

    style.configure("TButton", background=P["bg2"], foreground=P["text"], padding=(12, 6), borderwidth=1, relief="flat")
    style.map("TButton", background=[("disabled", P["bg1"]), ("pressed", P["bg3"]), ("active", P["bg3"])],
              foreground=[("disabled", P["faint"])])
    style.configure("Accent.TButton", background=P["accent"], foreground=P["on_accent"], bordercolor=P["accent"],
                    lightcolor=P["accent"], darkcolor=P["accent"], font=(base.actual("family"), 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", P["bg1"]), ("pressed", P["accent"]), ("active", "#f7c565")],
              foreground=[("disabled", P["faint"])])
    style.configure("Slot.TButton", background=P["bg1"], foreground=P["text"], padding=(14, 8), anchor="w")
    style.map("Slot.TButton", background=[("active", P["bg2"])])
    style.configure("SlotNeed.TButton", background=P["bg1"], foreground=P["accent"], padding=(14, 8), anchor="w")
    style.map("SlotNeed.TButton", background=[("active", P["bg2"])])
    style.configure("Icon.TButton", padding=(6, 4), background=P["bg1"])
    style.configure("Flat.TButton", background=P["bg0"], foreground=P["dim"], padding=(8, 4), borderwidth=0)
    style.map("Flat.TButton", foreground=[("active", P["text"])], background=[("active", P["bg0"])])

    style.configure("TEntry", fieldbackground=P["bg1"], padding=(6, 5), borderwidth=1)
    style.map("TEntry", bordercolor=[("focus", P["faint"])], lightcolor=[("focus", P["faint"])],
              darkcolor=[("focus", P["faint"])])
    style.configure("Dim.TEntry", fieldbackground=P["bg1"], padding=(6, 5), borderwidth=1, foreground=P["dim"])
    style.configure("Bad.TEntry", fieldbackground=P["bg1"], padding=(6, 5), borderwidth=1, bordercolor=P["accent"],
                    foreground=P["accent"],
                    lightcolor=P["accent"], darkcolor=P["accent"])
    style.map("Bad.TEntry", bordercolor=[("focus", P["accent"])], lightcolor=[("focus", P["accent"])],
              darkcolor=[("focus", P["accent"])])
    style.configure("TCombobox", fieldbackground=P["bg1"], background=P["bg2"], arrowcolor=P["dim"], padding=(6, 5),
                    arrowsize=14, borderwidth=1)
    style.map("TCombobox", fieldbackground=[("readonly", P["bg1"]), ("disabled", P["bg0"])],
              foreground=[("disabled", P["faint"])], bordercolor=[("focus", P["faint"])],
              selectbackground=[("readonly", P["bg1"])], selectforeground=[("readonly", P["text"])])
    style.configure("TCheckbutton", background=P["bg0"], foreground=P["text"], indicatorbackground=P["bg1"],
                    indicatorforeground=P["text"], indicatormargin=(0, 0, 6, 0))
    style.map("TCheckbutton", background=[("active", P["bg0"])], indicatorbackground=[("selected", P["bg3"])])
    style.configure("Seg.Toolbutton", background=P["bg1"], foreground=P["dim"], padding=(16, 7), borderwidth=1,
                    relief="flat", anchor="center")
    style.map("Seg.Toolbutton", background=[("selected", P["bg3"]), ("active", P["bg2"])],
              foreground=[("selected", P["text"]), ("active", P["text"])])
    style.configure("Vertical.TScrollbar", background=P["bg2"], troughcolor=P["bg1"], bordercolor=P["bg1"],
                    arrowcolor=P["dim"], lightcolor=P["bg2"], darkcolor=P["bg2"], arrowsize=12)
    style.map("Vertical.TScrollbar", background=[("active", P["bg3"])])
    style.configure("TSeparator", background=P["line"])
    style.configure("Treeview", background=P["bg1"], fieldbackground=P["bg1"], foreground=P["text"],
                    rowheight=base.metrics("linespace") + 12,
                    borderwidth=0, bordercolor=P["line"], lightcolor=P["bg1"], darkcolor=P["bg1"])
    style.map("Treeview", background=[("selected", P["bg3"])], foreground=[("selected", P["text"])])
    style.configure("Treeview.Heading", background=P["bg2"], foreground=P["dim"], relief="flat", padding=(8, 5),
                    borderwidth=0)
    style.map("Treeview.Heading", background=[("active", P["bg3"])])
    style.configure("Chip.TButton", background=P["bg2"], foreground=P["text"], padding=(10, 3), borderwidth=0)
    return style
