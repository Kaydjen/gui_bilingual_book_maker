"""The header path `Books › Terms 12 › Translate › Export`: ordered steps, not peer tabs (window_spec 1.1, 1.2).

items: (key, label, count or None, hot). A count is dim, red when `hot` (the one red of the screen is decided
by accent.py, not here). Without a count a `hot` item carries a small bright dot (a job of the series is
unfinished). The current step is lit; the others are dim and brighter under the pointer.
"""

from __future__ import annotations

import tkinter as tk

from .theme import ACCENT, BG, BRIGHT, DIM, FAINT, S3, TEXT
from .widgets import rrect

ARROW = "›"


class PathBar(tk.Canvas):
    def __init__(self, master, font, on_change, bg=BG):
        self.font = font
        self.on_change = on_change
        ls = font.metrics("linespace")
        self.pad = int(ls * 0.7)
        self.h = ls + 2 * int(ls * 0.38)
        self.items: list = []
        self.value = None
        self.hover = None
        self.boxes: list = []
        self.total = 0
        self.enabled = True
        super().__init__(master, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._motion(None))

    # ------------------------------------------------------------- data
    def set_items(self, items, value=None) -> None:
        items = [tuple(i) for i in items]
        if value is not None:
            self.value = value
        if items != self.items or value is not None:
            self.items = items
            self.draw()

    def set_value(self, value) -> None:
        if value != self.value:
            self.value = value
            self.draw()

    def seg_at(self, x):
        for i, (a, b) in enumerate(self.boxes):
            if a <= x < b:
                return i
        return None

    def width_needed(self) -> int:
        return self.total

    # ------------------------------------------------------------- events
    def _motion(self, e) -> None:
        h = None if e is None or not self.enabled else self.seg_at(e.x)
        if h != self.hover:
            self.hover = h
            self.draw()

    def _click(self, e) -> None:
        i = self.seg_at(e.x) if self.enabled else None
        if i is not None:
            self.on_change(self.items[i][0])

    # ------------------------------------------------------------- drawing
    def _count_w(self, cnt) -> int:
        return self.font.measure(str(cnt)) + int(self.pad * 0.45) if cnt is not None else 0

    def draw(self) -> None:
        self.delete("all")
        f = self.font
        arrow_w = f.measure(ARROW)
        gap = int(self.pad * 0.55)
        x = 2
        boxes = []
        spans = []
        for n, (key, label, cnt, *rest) in enumerate(self.items):
            hot = bool(rest and rest[0])
            wl = f.measure(label)
            wc = self._count_w(cnt)
            dot = cnt is None and hot
            wd = int(self.h * 0.3) + int(self.pad * 0.3) if dot else 0
            w = wl + wc + wd + 2 * self.pad
            spans.append((x, x + w, wl, wc, hot))
            boxes.append((x, x + w))
            x += w
            if n < len(self.items) - 1:
                x += gap + arrow_w + gap
        self.total = x + 2
        self.boxes = boxes
        self.configure(width=self.total)
        cy = self.h / 2
        for i, (key, label, cnt, *rest) in enumerate(self.items):
            a, b, wl, wc, hot = spans[i]
            active = key == self.value
            if active:
                rrect(self, a, 2, b, self.h - 2, (self.h - 4) * 0.26, fill=S3, outline="")
            fg = BRIGHT if active else (TEXT if self.hover == i else DIM)
            if not self.enabled:
                fg = FAINT
            tx = a + self.pad
            self.create_text(tx, cy, text=label, anchor="w", font=f, fill=fg)
            if cnt is not None:
                bright = len(rest) > 1 and bool(rest[1])        # a running job: seen from every step
                self.create_text(tx + wl + int(self.pad * 0.45), cy, text=str(cnt), anchor="w", font=f,
                                 fill=ACCENT if hot else (TEXT if bright else (DIM if active else FAINT)))
            elif hot:
                r = self.h * 0.07
                cx = tx + wl + int(self.pad * 0.3) + r + 1
                self.create_oval(cx - r, cy - r * 1.4, cx + r, cy + r * 0.6, fill=BRIGHT, outline="")
            if i < len(self.items) - 1:
                self.create_text(b + gap, cy, text=ARROW, anchor="w", font=f, fill=FAINT)
