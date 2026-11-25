"""The thin moving line under the header: something takes longer than 0.3 s and the content stays (spec 10.1)."""

from __future__ import annotations

import tkinter as tk

from .theme import BG, FAINT, S4

DELAY_MS = 300
STEP_MS = 30


class LoadLine(tk.Canvas):
    def __init__(self, master, height: int = 2):
        super().__init__(master, height=height, bg=BG, highlightthickness=0, bd=0)
        self.h = height
        self.keys: set = set()
        self.visible = False
        self._show_job = None
        self._anim_job = None
        self._x = 0.0

    def start(self, key) -> None:
        """Something named `key` is loading; the line shows itself when it still takes long after 0.3 s."""
        was = bool(self.keys)
        self.keys.add(key)
        if not was and self._show_job is None and not self.visible:
            self._show_job = self.after(DELAY_MS, self._show)

    def stop(self, key) -> None:
        self.keys.discard(key)
        if not self.keys:
            if self._show_job is not None:
                self.after_cancel(self._show_job)
                self._show_job = None
            self._hide()

    def _show(self) -> None:
        self._show_job = None
        if not self.keys:
            return
        self.visible = True
        self._x = 0.0
        self._tick()

    def _hide(self) -> None:
        self.visible = False
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        self.delete("all")

    def _tick(self) -> None:
        self._anim_job = None
        if not self.visible:
            return
        W = max(self.winfo_width(), 100)
        seg = W * 0.18
        self._x = (self._x + W * 0.025) % (W + seg)
        self.delete("all")
        self.create_line(0, self.h // 2, W, self.h // 2, fill=S4, width=self.h)
        self.create_line(max(0, self._x - seg), self.h // 2, min(W, self._x), self.h // 2, fill=FAINT, width=self.h)
        self._anim_job = self.after(STEP_MS, self._tick)
