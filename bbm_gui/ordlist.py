"""An ordered list for keys and models: Shift/Ctrl+click selects, pressing and dragging moves, Delete removes."""
import tkinter as tk
from tkinter import ttk

from .theme import P

DRAG_PX = 4


class InputField(ttk.Entry):
    """The entry above a list. It also says why an input did not take effect: the reason appears in the field itself
    (accent colour for a refusal, dim for "nothing changed") and goes away on the next key press, click or after 2.5 s."""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._saying = False
        self._job = None
        for seq in ("<Key>", "<ButtonPress-1>", "<<Paste>>"):
            self.bind(seq, self._clear_saying, add="+")

    def say(self, text, bad=False):
        self.delete(0, "end")
        self.insert(0, text)
        self.configure(style="Bad.TEntry" if bad else "Dim.TEntry")
        self._saying = True
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(2500, lambda: self._clear_saying())

    def _clear_saying(self, event=None):
        if not self._saying or not self.winfo_exists():
            return
        self._saying = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.delete(0, "end")
        self.configure(style="TEntry")


class SaveMark(ttk.Label):
    """Always visible answer to "is it saved?": Saving between a change and the write, Saved after it, Not saved on a
    write error; Unsaved for windows that write on an explicit Save (edits made, nothing written yet)."""

    def __init__(self, parent, state="saved"):
        super().__init__(parent, text="")
        self.set(state)

    def set(self, state):
        if not self.winfo_exists():
            return
        text, style = {"saving": ("Saving", "TLabel"), "dirty": ("Unsaved", "TLabel"),
                       "failed": ("Not saved", "Accent.TLabel")}.get(
            state, ("Saved", "Dim.TLabel"))
        self.configure(text=text, style=style)


class OrderedList(ttk.Frame):
    """Rows are strings (the items). render(item) -> tuple of cell texts, tag(item) -> tag name or ''.

    The first `movable` rows can be dragged and are drop targets; rows after them keep their place.
    Callbacks: on_move(items) after a reorder, on_delete(selected items), on_cell(item, column) -> True when a click
    on a cell was handled (e.g. a check mark).
    """

    def __init__(self, parent, columns, render, tag=None, on_move=None, on_delete=None, on_cell=None):
        super().__init__(parent)
        self.render, self.tag = render, tag or (lambda item: "")
        self.on_move, self.on_delete, self.on_cell = on_move, on_delete, on_cell
        self.items = []
        self.movable = 0
        cols = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=cols, show="", selectmode="extended")
        for name, width, stretch in columns:
            self.tree.column(name, width=width, stretch=stretch, anchor="w")
        self.tree.tag_configure("dim", foreground=P["dim"])
        self.tree.tag_configure("bad", foreground=P["accent"])
        self.tree.tag_configure("new", background=P["bg3"])
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self._press = None
        self._dragging = False
        self.tree.bind("<ButtonPress-1>", self._on_press)
        # a quick second click is a "double" event for Tk: treat it as a plain press, never as open/close of a row
        self.tree.bind("<Double-ButtonPress-1>", self._on_double)
        self.tree.bind("<B1-Motion>", self._on_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_release)
        self.tree.bind("<Delete>", lambda e: self._delete())
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])
        self.tree.bind("<Alt-Up>", lambda e: (self._nudge(-1), "break")[1])
        self.tree.bind("<Alt-Down>", lambda e: (self._nudge(1), "break")[1])

    # ------------------------------------------------------------------ content
    def set_items(self, items, movable=None):
        keep = set(self.selected())
        self.items = list(items)
        self.movable = len(self.items) if movable is None else movable
        self.tree.delete(*self.tree.get_children())
        for n, item in enumerate(self.items):
            tag = self.tag(item)
            self.tree.insert("", "end", iid=str(n), values=self.render(item), tags=(tag,) if tag else ())
        self.tree.selection_set([str(n) for n, i in enumerate(self.items) if i in keep])

    def rerender(self):
        """Refresh the texts in place (a countdown) without touching the selection or a drag in progress."""
        for n, item in enumerate(self.items):
            iid = str(n)
            if self.tree.exists(iid):
                self.tree.item(iid, values=self.render(item))
                tags = self.tree.item(iid, "tags")
                if "new" not in tags:
                    tag = self.tag(item)
                    self.tree.item(iid, tags=(tag,) if tag else ())

    def flash(self, items, ms=1400):
        """Show where the items are: scroll to the first one and tint all briefly."""
        ids = [str(n) for n, i in enumerate(self.items) if i in items]
        if not ids:
            return
        self.tree.see(ids[0])
        for iid in ids:
            self.tree.item(iid, tags=(self.tag(self.items[int(iid)]), "new"))

        def clear():
            if self.winfo_exists():
                for iid in ids:
                    if int(iid) < len(self.items) and self.tree.exists(iid):
                        t = self.tag(self.items[int(iid)])
                        self.tree.item(iid, tags=(t,) if t else ())

        self.after(ms, clear)

    def selected(self):
        return [self.items[int(i)] for i in sorted(self.tree.selection(), key=int) if int(i) < len(self.items)]

    def _delete(self):
        if self.on_delete and self.selected():
            self.on_delete(self.selected())

    # ------------------------------------------------------------------ mouse
    def _on_press(self, e):
        self._dragging = False
        iid = self.tree.identify_row(e.y)
        self._press = None
        if not iid:
            return None
        if self.on_cell and self.on_cell(self.items[int(iid)], self.tree.identify_column(e.x)):
            return "break"
        plain = not (e.state & 0x5)  # no Shift, no Control
        if plain and iid in self.tree.selection():
            # keep a multi-selection for the drag; a click without a drag selects this row alone on release
            self._press = (iid, e.y, True)
            self.tree.focus(iid)
            return "break"
        self._press = (iid, e.y, plain)
        return None

    def _on_double(self, e):
        iid = self.tree.identify_row(e.y)
        if iid and self.on_cell and self.on_cell(self.items[int(iid)], self.tree.identify_column(e.x)):
            return "break"
        if iid and not (e.state & 0x5):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        self._press = None
        return "break"

    def _on_motion(self, e):
        if not self._press or not self._press[2]:
            return "break" if self._press else None
        iid, y0, _ = self._press
        if not self._dragging and abs(e.y - y0) < DRAG_PX:
            return "break"
        if int(iid) >= self.movable:
            return "break"
        self._dragging = True
        self.tree.configure(cursor="fleur")
        target = self.tree.identify_row(e.y)
        if target:
            t = min(int(target), self.movable - 1)
        else:
            t = 0 if e.y < 0 else self.movable - 1
        self._move_block(t)
        return "break"

    def _on_release(self, e):
        if self._press and not self._dragging and self._press[2] and self._press[0] in self.tree.selection():
            self.tree.selection_set(self._press[0])
        self.tree.configure(cursor="")
        self._press = None
        self._dragging = False

    # ------------------------------------------------------------------ moving
    def _move_block(self, t):
        sel = [i for i in self.selected() if self.items.index(i) < self.movable]
        if not sel or self.items[t] in sel:
            return
        first = self.items.index(sel[0])
        rest = [i for i in self.items if i not in sel]
        pos = rest.index(self.items[t]) + (1 if t > first else 0)
        head = rest[:pos] + sel + rest[pos:]
        tail = [i for i in self.items[self.movable:]]
        head = [i for i in head if i not in tail]
        self.set_items(head + tail, self.movable)
        if self.on_move:
            self.on_move(self.items)

    def _nudge(self, d):
        sel = [i for i in self.selected() if self.items.index(i) < self.movable]
        if not sel:
            return
        idx = [self.items.index(i) for i in sel]
        t = (min(idx) - 1) if d < 0 else (max(idx) + 1)
        if 0 <= t < self.movable:
            self._move_block(t)
