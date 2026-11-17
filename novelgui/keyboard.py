"""Keyboard of the window (window_spec 10.7): Tab and Shift+Tab walk the controls in reading order; while a panel is
open they stay inside it; Enter presses the panel's main button unless the focus is in a multi-line text.

A control joins the walk by saying so: `taborder = True` on a canvas control (buttons, switches, tables), an enabled
`tk.Entry` (every field) or an editable `tk.Text`. A control that has `enabled` set to False is skipped.
"""

from __future__ import annotations

import tkinter as tk

from . import keynav


class Keyboard:
    def __init__(self, ui):
        self.ui = ui
        root = ui.root
        root.bind("<Tab>", lambda e: self.tab(1), add="+")
        root.bind("<Shift-Tab>", lambda e: self.tab(-1), add="+")
        try:
            root.bind("<ISO_Left_Tab>", lambda e: self.tab(-1), add="+")     # X11 names Shift+Tab so
        except tk.TclError:
            pass
        root.bind("<Return>", self.enter, add="+")

    # ------------------------------------------------------------- what can take the focus
    @staticmethod
    def joins(w) -> bool:
        try:
            if not w.winfo_viewable():
                return False
            if getattr(w, "taborder", False):
                return bool(getattr(w, "enabled", True))
            if isinstance(w, tk.Entry):
                return str(w.cget("state")) == "normal"
            if isinstance(w, tk.Text):
                return str(w.cget("state")) == "normal"
        except tk.TclError:
            return False
        return False

    def scope(self):
        top = self.ui.panels.top()
        return top if top is not None and top.is_open else self.ui.root

    def controls(self, scope=None) -> list:
        """The controls on screen (inside the open panel, else the whole window) in reading order."""
        scope = scope or self.scope()
        found: list = []

        def walk(w):
            try:
                if not w.winfo_viewable():
                    return
            except tk.TclError:
                return
            if self.joins(w):
                found.append(w)
            for c in w.winfo_children():
                walk(c)
        walk(scope)
        boxes = [(w, w.winfo_rootx(), w.winfo_rooty(), w.winfo_height()) for w in found]
        return keynav.reading_order(boxes)

    # ------------------------------------------------------------- keys
    def tab(self, delta: int):
        scope = self.scope()
        order = self.controls(scope)
        try:
            cur = self.ui.root.focus_get()
        except (KeyError, tk.TclError):
            cur = None
        target = keynav.step(order, cur, delta)
        if target is None:
            return "break"
        self.focus(target)
        return "break"

    def focus(self, w) -> None:
        try:
            w.focus_set()
            if isinstance(w, tk.Entry):
                w.select_range(0, "end")
                w.icursor("end")
            top = self.ui.panels.top()
            if top is not None and top.is_open and hasattr(top, "reveal"):
                top.reveal(w)
        except tk.TclError:
            pass

    def enter(self, e):
        """Enter presses the main button of the open panel (a field, a button or a table takes its own Enter first;
        in a multi-line text it is a new line)."""
        top = self.ui.panels.top()
        if top is None or not top.is_open or isinstance(e.widget, tk.Text):
            return None
        main = getattr(top, "main", None)
        if main is None or not getattr(main, "enabled", True):
            return None
        main.command()
        return "break"
