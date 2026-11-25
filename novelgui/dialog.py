"""A small modal panel drawn inside the window, and the "add book" form built on it."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import addbook, model, tips
from .theme import BG, BRIGHT, DIM, FAINT, S1, S2, S4, TEXT
from .tooltip import attach_tip
from .widgets import Field, Pill, Segmented


class PanelStack:
    """The panels open over the window, the top one last (at most two). While one is open it holds the pointer
    grab, so a press outside it never reaches the window behind: it commits the focused field and closes the
    panel. Esc closes the top panel unless a field or a list takes it first."""

    MAX = 2

    def __init__(self, root):
        self.root = root
        self.items: list = []
        root.bind("<ButtonPress>", self._press, add="+")
        root.bind("<Escape>", self._escape, add="+")
        root.bind("<Configure>", self._configure, add="+")
        root.bind("<MouseWheel>", self._wheel, add="+")

    def top(self):
        return self.items[-1] if self.items else None

    def push(self, panel) -> None:
        while len(self.items) >= self.MAX:
            self.items[-1].close()
        self.items.append(panel)

    def remove(self, panel) -> None:
        if panel in self.items:
            self.items.remove(panel)
        t = self.top()
        if t is not None:
            t.regrab()

    def close_all(self) -> None:
        for p in list(reversed(self.items)):
            p.close()

    @staticmethod
    def _inside(panel, e) -> bool:
        x0, y0 = panel.winfo_rootx(), panel.winfo_rooty()
        return x0 <= e.x_root < x0 + panel.winfo_width() and y0 <= e.y_root < y0 + panel.winfo_height()

    def _press(self, e):
        top = self.top()
        if top is None or not top.is_open:
            return
        try:
            if top.grab_current() is not top:
                return                  # a list drawn over the panel holds the grab and handles the press
        except (KeyError, tk.TclError):
            return
        if self._inside(top, e):
            return
        f = Field.focused_field
        if f is not None:
            f.commit()
            f.leave()
        top.outside_press()

    def _escape(self, e):
        top = self.top()
        if top is None or not top.is_open:
            return None
        top.close()
        return "break"

    def _configure(self, e):
        if e.widget is self.root:
            for p in list(self.items):
                if p.is_open:
                    p.fit()

    def _wheel(self, e):
        top = self.top()
        if top is None or not top.scrolls or isinstance(e.widget, (tk.Text, tk.Entry)):
            return None
        if not self._inside(top, e):
            return None
        top.canvas.yview_scroll(-int(round(e.delta / 120.0)) * 3, "units")
        return "break"


class Modal(tk.Frame):
    """A panel over the window, drawn inside it. It is never larger than the window minus a margin; what does
    not fit scrolls inside. While open it holds the pointer grab; Esc and a press outside close it."""

    is_panel = True

    def __init__(self, ui, on_close=None):
        super().__init__(ui.root, bg=S4)
        self.ui = ui
        self.on_close = on_close
        self.pad = pad = int(ui.ls * 1.0)
        self.margin = int(ui.ls * 1.5)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=S2, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, padx=1, pady=1)
        self.sb = ttk.Scrollbar(self, orient="vertical", style="Dark.Vertical.TScrollbar",
                                command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.shell = tk.Frame(self.canvas, bg=S2)
        self.win = self.canvas.create_window(0, 0, window=self.shell, anchor="nw")
        self.body = tk.Frame(self.shell, bg=S2)
        self.body.pack(fill="both", expand=True, ipadx=pad, ipady=pad)
        self.scrolls = False
        self.is_open = False
        self._watch_job = None
        self.main = None            # the button Enter presses (a Pill); set by the panel that has one

    def reveal(self, w) -> None:
        """Scroll the panel so that control `w` is in view (Tab moved the focus to it)."""
        if not self.scrolls:
            return
        self.update_idletasks()
        total = max(1, self.shell.winfo_reqheight())
        view = int(self.canvas.cget("height"))
        y = w.winfo_rooty() - self.shell.winfo_rooty()
        top = self.canvas.canvasy(0)
        if y < top:
            self.canvas.yview_moveto(max(0.0, (y - 4) / total))
        elif y + w.winfo_height() > top + view:
            self.canvas.yview_moveto(min(1.0, (y + w.winfo_height() - view + 4) / total))

    # ---- size and place
    def fit(self) -> None:
        """Size the panel to its content, at most the window minus the margin, and centre it."""
        self.update_idletasks()
        root = self.ui.root
        W, H = root.winfo_width(), root.winfo_height()
        m = self.margin
        rw, rh = self.shell.winfo_reqwidth(), self.shell.winfo_reqheight()
        maxw, maxh = max(100, W - 2 * m - 2), max(80, H - 2 * m - 2)
        scroll = rh > maxh
        sbw = self.sb.winfo_reqwidth() if scroll else 0
        w = min(rw + sbw, maxw)
        h = min(rh, maxh)
        self.canvas.configure(width=w - sbw, height=h)
        self.canvas.itemconfigure(self.win, width=w - sbw)
        self.canvas.configure(scrollregion=(0, 0, w - sbw, max(rh, h)))
        if scroll and not self.scrolls:
            self.sb.grid(row=0, column=1, sticky="ns", pady=1, padx=(0, 1))
        elif not scroll and self.scrolls:
            self.sb.grid_remove()
            self.canvas.yview_moveto(0)
        self.scrolls = scroll
        x = max(m // 2, (W - (w + 2)) // 2)
        y = int(max(m // 2, min((H - (h + 2)) * 0.42, H - m // 2 - (h + 2))))
        self.place(x=x, y=y)

    def show(self):
        self.ui.panels.push(self)
        self.is_open = True
        self.fit()
        self.tk.call("raise", self._w)
        self.update_idletasks()
        self.regrab()
        self.focus_set()

    # ---- grab
    def regrab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            self.after(20, self._retry_grab)
            return
        if self.is_open and self.ui.panels.top() is self:
            try:
                self.focus_set()
            except tk.TclError:
                pass

    def _retry_grab(self) -> None:
        try:
            if self.is_open and self.ui.panels.top() is self:
                self.grab_set()
        except tk.TclError:
            pass

    # ---- closing
    def outside_press(self) -> None:
        """A press outside the panel (the focused field has been committed): by default the panel closes."""
        self.close()

    def watch(self, still_valid, ms: int = 250) -> None:
        """Close the panel as a cancel when `still_valid()` turns false (its subject changed underneath)."""
        def tick():
            self._watch_job = None
            if not self.is_open:
                return
            try:
                ok = still_valid()
            except Exception:
                ok = False
            if not ok:
                self.close()
                return
            self._watch_job = self.after(ms, tick)
        self._watch_job = self.after(ms, tick)

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        if self._watch_job is not None:
            try:
                self.after_cancel(self._watch_job)
            except tk.TclError:
                pass
            self._watch_job = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.place_forget()
        self.destroy()
        self.ui.panels.remove(self)
        if self.on_close:
            self.on_close()


def message(ui, text: str, on_close=None) -> Modal:
    m = Modal(ui, on_close)
    tk.Label(m.body, text=text, bg=S2, fg=TEXT, font=ui.font, justify="left", wraplength=ui.cw * 60).pack(
        padx=m.pad, pady=(m.pad, int(m.pad * 0.8)))
    ok = Pill(m.body, "OK", m.close, ui.font, bg=S2)
    ok.pack(pady=(0, 0))
    m.main = ok
    m.show()
    ok.focus_set()
    return m


class AddBookDialog(Modal):
    """Add book (window_spec 5): the file name, `Volume of <series> | New series` (only with a series selected)
    and the series name. The size is the same in both modes: the name field is always there, dim while the
    file goes into the selected series. No language here: it is chosen when translating."""

    def __init__(self, ui, library, epub: str, series, on_done, used=((), ()), on_closed=None):
        super().__init__(ui, (lambda: on_closed(self)) if on_closed else None)
        self.confirmed = False
        self.library = library
        self.series = series
        self.epub = epub
        self.on_done = on_done
        self.used = used                    # (folder names, shown names) of the library, for the name check
        f = ui.font
        gap = int(ui.ls * 0.7)
        body = self.body
        self.mode = "volume" if series is not None else "new"
        pad = self.pad

        row = tk.Frame(body, bg=S2)
        row.pack(fill="x", padx=pad, pady=(pad, gap))
        tk.Label(row, text=_short(Path(epub).name, 52), bg=S2, fg=TEXT, font=f, anchor="w").pack(side="left")

        self.mode_seg = None
        if series is not None:
            self.mode_seg = Segmented(body, f, self._mode_changed, bg=S2)
            self.mode_seg.set_items([("volume", "Volume of " + _short(series.name, 28), None),
                                     ("new", "New series", None)], self.mode)
            self.mode_seg.pack(anchor="w", padx=pad, pady=(0, gap))
            attach_tip(self.mode_seg, ui.tip, self._mode_tip)

        self.name_label = tk.Label(body, text="Series name", bg=S2, fg=DIM, font=f, anchor="w")
        self.name_label.pack(anchor="w", padx=pad)
        self.name = Field(body, f, on_change=lambda s: self._validate(), on_submit=lambda s: self._ok(),
                          bg=S2, width=ui.cw * 46, surface=S1)
        self.name.pack(fill="x", padx=pad, pady=(2, gap))
        attach_tip(self.name.entry, ui.tip, lambda e: self._name_tip())
        attach_tip(self.name_label, ui.tip, lambda e: self._name_tip())

        btns = tk.Frame(body, bg=S2)
        btns.pack(fill="x", padx=pad, pady=(int(gap * 1.4), 0))
        self.add_btn = Pill(btns, "Add", self._ok, f, bg=S2)
        self.add_btn.pack(side="right")
        self.main = self.add_btn
        Pill(btns, "Cancel", self.close, f, kind="dim", bg=S2).pack(side="right", padx=(0, gap // 2))
        attach_tip(self.add_btn, ui.tip, lambda e: self._add_tip())
        self._apply_mode()
        self.show()
        if self.mode == "new":
            self.name.entry.focus_set()
            self.name.entry.select_range(0, "end")
        else:
            self.add_btn.focus_set()

    # -- state
    def _mode_tip(self, e):
        i = self.mode_seg.seg_at(e.x)
        if i is None:
            return None
        return tips.ADD_VOLUME_OF if self.mode_seg.items[i][0] == "volume" else tips.ADD_NEW_SERIES

    def _name_tip(self):
        return tips.ADD_SERIES_NAME_FIXED if self.mode == "volume" else tips.ADD_SERIES_NAME

    def _problem(self) -> str:
        if self.mode != "new":
            return ""
        return addbook.series_name_problem(self.name.get(), model.clean_name, self.used[0], self.used[1])

    def _add_tip(self):
        if self.add_btn.enabled:
            return None
        return self._problem() or None

    def _mode_changed(self, v):
        self.mode = v
        self._apply_mode()

    def _apply_mode(self):
        if self.mode == "volume":
            self.name.set(self.series.name)
            self.name.set_enabled(False)
            self.name_label.configure(fg=FAINT)
        else:
            self.name.set_enabled(True)
            self.name.set(_prefill(self.epub))
            self.name_label.configure(fg=DIM)
            self.name.entry.focus_set()
            self.name.entry.select_range(0, "end")
        self._validate()

    def _validate(self):
        if not hasattr(self, "add_btn"):
            return
        self.add_btn.set_enabled(not self._problem())

    def result(self) -> dict:
        if self.mode == "volume":
            return {"mode": "volume", "series": self.series.path, "epub": self.epub}
        return {"mode": "new", "name": self.name.get().strip(), "epub": self.epub}

    def _ok(self):
        if not self.add_btn.enabled:
            return
        res = self.result()
        self.confirmed = True
        self.close()
        self.on_done(res)


class RenameDialog(Modal):
    """One name to edit: the series name or a volume label. `check(text)` returns the reason a name is not
    allowed ("" when it is); `on_done(text)` runs after the panel closed."""

    def __init__(self, ui, caption: str, value: str, check, on_done, button: str = "Rename"):
        super().__init__(ui)
        self.check = check
        self.on_done = on_done
        f = ui.font
        gap = int(ui.ls * 0.7)
        pad = self.pad
        tk.Label(self.body, text=caption, bg=S2, fg=DIM, font=f, anchor="w").pack(anchor="w", padx=pad,
                                                                                    pady=(pad, 2))
        self.field = Field(self.body, f, on_change=lambda s: self._validate(), on_submit=lambda s: self._ok(),
                           bg=S2, width=ui.cw * 46, surface=S1)
        self.field.pack(fill="x", padx=pad, pady=(0, gap))
        self.field.set(value)
        btns = tk.Frame(self.body, bg=S2)
        btns.pack(fill="x", padx=pad, pady=(int(gap * 0.6), 0))
        self.ok_btn = Pill(btns, button, self._ok, f, bg=S2)
        self.ok_btn.pack(side="right")
        self.main = self.ok_btn
        Pill(btns, "Cancel", self.close, f, kind="dim", bg=S2).pack(side="right", padx=(0, gap // 2))
        attach_tip(self.ok_btn, ui.tip, lambda e: None if self.ok_btn.enabled else (self.check(self.field.get())
                                                                                     or None))
        self._validate()
        self.show()
        self.field.entry.focus_set()
        self.field.entry.select_range(0, "end")

    def _validate(self):
        if hasattr(self, "ok_btn"):
            self.ok_btn.set_enabled(not self.check(self.field.get()))

    def _ok(self):
        if not self.ok_btn.enabled:
            return
        text = self.field.get().strip()
        self.close()
        self.on_done(text)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def _prefill(epub: str) -> str:
    return Path(epub).stem.replace("_", " ").strip()


def confirm(ui, text: str, yes: str, on_yes, no: str = "Cancel", valid=None) -> Modal:
    """A question with two answers; `on_yes` runs after the panel closed. A press outside, Esc and a change of
    the subject underneath (`valid()` turning false) all count as the second answer."""
    m = Modal(ui)
    tk.Label(m.body, text=text, bg=S2, fg=TEXT, font=ui.font, justify="left", wraplength=ui.cw * 60).pack(
        padx=m.pad, pady=(m.pad, int(m.pad * 0.8)))
    row = tk.Frame(m.body, bg=S2)
    row.pack(fill="x", padx=m.pad)

    def ok():
        m.close()
        on_yes()

    ok_btn = Pill(row, yes, ok, ui.font, bg=S2)
    ok_btn.pack(side="right")
    m.main = ok_btn
    Pill(row, no, m.close, ui.font, kind="dim", bg=S2).pack(side="right", padx=(0, ui.ls // 2))
    m.show()
    ok_btn.focus_set()
    if valid is not None:
        m.watch(valid)
    return m
