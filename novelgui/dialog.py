"""A small modal panel drawn inside the window, and the "add book" form built on it."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from . import model
from .theme import BG, BRIGHT, DIM, FAINT, S1, S2, S4, TEXT
from .tooltip import attach_tip
from .widgets import Field, Pill, Segmented


class Modal(tk.Frame):
    """Centered panel over the window. Esc closes it."""

    def __init__(self, ui, on_close=None):
        super().__init__(ui.root, bg=S4)
        self.ui = ui
        self.on_close = on_close
        self.body = tk.Frame(self, bg=S2)
        pad = int(ui.ls * 1.0)
        self.body.pack(padx=1, pady=1, ipadx=pad, ipady=pad)
        self.pad = pad
        self.is_open = False
        self.bind("<Escape>", lambda e: self.close())

    def show(self):
        self.place(relx=0.5, rely=0.42, anchor="center")
        self.tk.call("raise", self._w)
        self.is_open = True

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        self.place_forget()
        self.destroy()
        if self.on_close:
            self.on_close()


def message(ui, text: str, on_close=None) -> Modal:
    m = Modal(ui, on_close)
    tk.Label(m.body, text=text, bg=S2, fg=TEXT, font=ui.font, justify="left", wraplength=ui.cw * 60).pack(
        padx=m.pad, pady=(m.pad, int(m.pad * 0.8)))
    ok = Pill(m.body, "OK", m.close, ui.font, bg=S2)
    ok.pack(pady=(0, 0))
    m.show()
    ok.focus_set()
    return m


class AddBookDialog(Modal):
    """Asks whether the file starts a new series or is a volume of the selected one."""

    def __init__(self, ui, library, epub: str, series, on_done):
        super().__init__(ui)
        self.library = library
        self.series = series
        self.epub = epub
        self.on_done = on_done
        f = ui.font
        gap = int(ui.ls * 0.7)
        body = self.body
        self.mode = "new" if series is None else "volume"
        self.target_choice = "Russian"
        pad = self.pad

        row = tk.Frame(body, bg=S2)
        row.pack(fill="x", padx=pad, pady=(pad, gap))
        tk.Label(row, text=Path(epub).name, bg=S2, fg=DIM, font=f, anchor="w").pack(side="left")

        self.mode_seg = None
        if series is not None:
            self.mode_seg = Segmented(body, f, self._mode_changed, bg=S2)
            self.mode_seg.set_items([("volume", "Volume of " + _short(series.name, 28), None),
                                     ("new", "New series", None)], self.mode)
            self.mode_seg.pack(anchor="w", padx=pad, pady=(0, gap))

        self.new_box = tk.Frame(body, bg=S2)
        self.new_box.pack(fill="x", padx=pad)
        tk.Label(self.new_box, text="Name", bg=S2, fg=DIM, font=f, anchor="w").pack(anchor="w")
        self.name = Field(self.new_box, f, on_change=lambda s: self._validate(), on_submit=lambda s: self._ok(),
                          bg=S2, width=ui.cw * 46, surface=S1)
        self.name.pack(fill="x", pady=(2, gap))
        self.name.set(_prefill(epub))
        tk.Label(self.new_box, text="Language", bg=S2, fg=DIM, font=f, anchor="w").pack(anchor="w")
        self.lang = Segmented(self.new_box, f, self._lang_changed, bg=S2)
        self.lang.set_items([(lbl, lbl, None) for _v, lbl in model.TARGETS] + [("Other", "Other", None)],
                            "Russian")
        self.lang.pack(anchor="w", pady=(2, 0))
        self.other = Field(self.new_box, f, on_change=lambda s: self._validate(), on_submit=lambda s: self._ok(),
                           bg=S2, surface=S1)
        attach_tip(self.other, ui.tip, lambda e: (
            "The language as tag:Name, for example de:German. The tag is used in file names and in the term "
            "base, the name is told to the translator.", [("Example", "de:German")]))

        btns = tk.Frame(body, bg=S2)
        btns.pack(fill="x", padx=pad, pady=(int(gap * 1.4), 0))
        self.btns = btns
        self.add_btn = Pill(btns, "Add", self._ok, f, kind="accent", bg=S2)
        self.add_btn.pack(side="right")
        Pill(btns, "Cancel", self.close, f, kind="dim", bg=S2).pack(side="right", padx=(0, gap // 2))
        attach_tip(self.add_btn, ui.tip, lambda e: self._add_tip())
        self._apply_mode()
        self.show()
        self.name.entry.focus_set() if self.mode == "new" else self.add_btn.focus_set()
        self.name.entry.select_range(0, "end")

    # -- state
    def _add_tip(self):
        if self.add_btn.enabled:
            return None
        return "A series with this name already exists. Change the name, or add the file as a volume of it."

    def _mode_changed(self, v):
        self.mode = v
        self._apply_mode()

    def _lang_changed(self, v):
        self.target_choice = v
        self._apply_mode()

    def _apply_mode(self):
        if self.mode == "new":
            self.new_box.pack(fill="x", padx=self.pad, before=self.btns)
        else:
            self.new_box.pack_forget()
        if self.mode == "new" and self.target_choice == "Other":
            self.other.pack(fill="x", pady=(int(self.ui.ls * 0.4), 0))
        else:
            self.other.pack_forget()
        self._validate()

    def _validate(self):
        if not hasattr(self, "add_btn"):
            return
        ok = True
        if self.mode == "new":
            name = self.name.get().strip()
            ok = bool(name) and not model.series_exists(self.library, name)
            if self.target_choice == "Other":
                ok = ok and ":" in self.other.get() and bool(self.other.get().split(":")[0].strip())
        self.add_btn.set_enabled(ok)

    def result(self) -> dict:
        if self.mode == "volume":
            return {"mode": "volume", "series": self.series.path, "epub": self.epub}
        return {"mode": "new", "name": self.name.get().strip(), "epub": self.epub,
                "target": model.target_of(self.target_choice, self.other.get())}

    def _ok(self):
        if not self.add_btn.enabled:
            return
        res = self.result()
        self.close()
        self.on_done(res)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def _prefill(epub: str) -> str:
    return Path(epub).stem.replace("_", " ").strip()


def confirm(ui, text: str, yes: str, on_yes, no: str = "Cancel") -> Modal:
    """A question with two answers; `on_yes` runs after the panel closed."""
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
    Pill(row, no, m.close, ui.font, kind="dim", bg=S2).pack(side="right", padx=(0, ui.ls // 2))
    m.show()
    ok_btn.focus_set()
    return m
