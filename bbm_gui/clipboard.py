"""Copy and paste that work in every text field: on any keyboard layout (Ctrl+V does not reach Tk on a Russian
layout under Windows) and through a right-click menu."""
import os
import tkinter as tk

from .theme import P

CLASSES = ("TEntry", "Entry", "TCombobox", "Text")
WIN_KEYCODES = {86: "paste", 67: "copy", 88: "cut", 65: "all"}  # V C X A (virtual-key codes, any layout)


def _do(widget, action):
    readonly = str(widget.cget("state")) in ("disabled", "readonly") if "state" in widget.keys() else False
    if action == "all":
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
        else:
            widget.select_range(0, "end")
            widget.icursor("end")
    elif action == "copy":
        widget.event_generate("<<Copy>>")
    elif action in ("cut", "paste") and not readonly:
        widget.event_generate("<<Cut>>" if action == "cut" else "<<Paste>>")


def install(root):
    def on_key(event):
        if os.name != "nt" or not (event.state & 0x4):  # Control held
            return None
        action = WIN_KEYCODES.get(event.keycode)
        if action is None or event.keysym.lower() in ("v", "c", "x", "a"):
            return None  # Latin layout: Tk already handles it
        _do(event.widget, action)
        return "break"

    menu = tk.Menu(root, tearoff=0, background=P["bg2"], foreground=P["text"], activebackground=P["bg3"],
                   activeforeground=P["text"], borderwidth=0, relief="flat")

    def on_menu(event):
        w = event.widget
        menu.delete(0, "end")
        menu.add_command(label="Paste", command=lambda: _do(w, "paste"))
        menu.add_command(label="Copy", command=lambda: _do(w, "copy"))
        menu.add_command(label="Cut", command=lambda: _do(w, "cut"))
        menu.add_separator()
        menu.add_command(label="Select all", command=lambda: _do(w, "all"))
        w.focus_set()
        menu.tk_popup(event.x_root, event.y_root)

    for cls in CLASSES:
        root.bind_class(cls, "<Control-KeyPress>", on_key, add="+")
        root.bind_class(cls, "<Button-3>", on_menu, add="+")
        if root.tk.call("tk", "windowingsystem") == "aqua":
            root.bind_class(cls, "<Button-2>", on_menu, add="+")
