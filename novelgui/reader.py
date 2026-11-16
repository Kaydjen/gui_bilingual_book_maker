"""Reading pane of the Terms screen: one paragraph that mentions the term, its chapter dimmed around it.

The mentions are searched in the whole book by a worker (they arrive in batches); the chapter text is
fetched by another lane, so stepping stays quick while the search runs.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import model, termlogic, termtips
from .theme import BG, DIM, FAINT, LINE, S1, S3, S4, TEXT
from .tooltip import attach_tip
from .widgets import rrect


def fit_text(f, s, w):
    if w <= 0:
        return ""
    if f.measure(s) <= w:
        return s
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if f.measure(s[:mid] + "…") <= w:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + "…" if lo else "…"


def centered_text_y(font, cy: float) -> float:
    """Y for a text anchored "w" so that digits (no descenders) sit visually centred on `cy`."""
    asc = font.metrics("ascent")
    ls = font.metrics("linespace")
    cap = asc * 0.72
    return cy + ls / 2.0 - asc + cap / 2.0


class Stepper(tk.Canvas):
    """`<  3 / 58  >` on one canvas, so the counter and the arrows share one centre line."""

    def __init__(self, master, ui, on_step):
        self.ui = ui
        self.font = ui.font
        ls = ui.ls
        self.h = ls + 2 * int(ls * 0.38)
        self.arm = int(ui.cw * 3.4)
        self.count_w = ui.cw * 12
        self.w = 2 * self.arm + self.count_w
        super().__init__(master, width=self.w, height=self.h, bg=S1, highlightthickness=0, bd=0)
        self.on_step = on_step
        self.text = "0 / 0"
        self.can_prev = self.can_next = False
        self.hover = None
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def zone(self, x):
        if x < self.arm:
            return "prev"
        if x >= self.w - self.arm:
            return "next"
        return "count"

    def _motion(self, e):
        self._set_hover(self.zone(e.x))

    def _set_hover(self, z):
        if z != self.hover:
            self.hover = z
            self.draw()

    def _click(self, e):
        z = self.zone(e.x)
        if z == "prev" and self.can_prev:
            self.on_step(-1)
        elif z == "next" and self.can_next:
            self.on_step(1)

    def set_state(self, text, can_prev, can_next):
        self.text, self.can_prev, self.can_next = text, can_prev, can_next
        self.draw()

    def draw(self):
        self.delete("all")
        cy = self.h / 2
        s = self.h * 0.2
        for zone, x0, direction in (("prev", 0, -1), ("next", self.w - self.arm, 1)):
            on = self.can_prev if zone == "prev" else self.can_next
            hot = on and self.hover == zone
            if hot:
                rrect(self, x0 + 2, 2, x0 + self.arm - 2, self.h - 2, self.h * 0.26, fill=S3, outline="")
            fg = TEXT if hot else (DIM if on else FAINT)
            cx = x0 + self.arm / 2
            self.create_line(cx - direction * s * 0.6, cy - s, cx + direction * s * 0.6, cy,
                             cx - direction * s * 0.6, cy + s, fill=fg, width=2, joinstyle="miter")
        self.create_text(self.w / 2, centered_text_y(self.font, cy), text=self.text, anchor="c", font=self.font,
                         fill=DIM)


class Hits:
    """Found paragraphs of one term."""

    def __init__(self):
        self.items: list = []           # (chapter, block, mentions, has_pronoun)
        self.done = False
        self.running = False
        self.i = 0

    def view(self, pron: bool) -> list:
        if pron:
            sel = [h for h in self.items if h[3]]
            return sel or self.items
        return self.items

    def mentions(self, pron: bool) -> int:
        return sum(h[2] for h in self.view(pron))


class Reader(tk.Frame):
    def __init__(self, master, ui):
        super().__init__(master, bg=S1, highlightthickness=1, highlightbackground=LINE)
        self.ui = ui
        font = ui.font
        ls = ui.ls
        cw = ui.cw
        self.font = font
        self.ls = ls
        self.cw = cw
        self.series_path = ""
        self.book = ""
        self.entry = None
        self.mark = False
        self.rx = None
        self.cache: dict = {}
        self.payloads: dict = {}
        self.meta = ""
        self.title = ""
        self.cut = False
        self.token = None
        self.req = 0
        self.shown_block = None
        self.last_ms = 0.0
        self.tpady = int(ls * 0.35)
        self.space3 = int(ls * 0.5)
        hpad = int(ls * 0.9)
        self.hdr = tk.Frame(self, bg=S1)
        self.hdr.pack(fill="x", padx=hpad, pady=(int(ls * 0.3), 0))
        self.stepper = Stepper(self.hdr, ui, self.step)
        self.stepper.pack(side="right")
        self.lab = tk.Canvas(self.hdr, height=self.stepper.h, bg=S1, highlightthickness=0, bd=0)
        self.lab.pack(side="left", fill="x", expand=True)
        body = tk.Frame(self, bg=S1)
        body.pack(fill="both", expand=True)
        self.sb = ttk.Scrollbar(body, orient="vertical", style="Dark.Vertical.TScrollbar")
        self.sb.pack(side="right", fill="y")
        self.text = tx = tk.Text(body, bg=S1, fg=DIM, font=font, bd=0, relief="flat", highlightthickness=0,
                                 wrap="word", padx=hpad, pady=self.tpady, height=1, cursor="xterm",
                                 spacing1=0, spacing3=self.space3, selectbackground=S4, selectforeground="#ffffff",
                                 insertwidth=0, state="disabled", yscrollcommand=self.sb.set)
        self.sb.configure(command=tx.yview)
        tx.pack(side="left", fill="both", expand=True)
        tx.tag_configure("dim", foreground=DIM)
        tx.tag_configure("cur", foreground=TEXT)
        tx.tag_configure("hit", font=ui.bold, foreground="#ffffff")
        tx.tag_configure("pron", foreground="#ffffff", underline=True)
        tx.tag_raise("sel")
        tx.bind("<MouseWheel>", self._wheel)
        tx.bind("<Button-1>", lambda e: tx.focus_set(), add="+")
        self.lab.bind("<Configure>", lambda e: self._draw_lab())
        attach_tip(self.stepper, ui.tip, self._stepper_tip)
        attach_tip(self.lab, ui.tip, lambda e: ("%s\n%s" % (self.meta, self.title)).strip() if self.cut else None)

    # ---- tooltips
    def _stepper_tip(self, e):
        z = self.stepper.zone(e.x)
        h = self._hits()
        n = len(h.view(self.mark)) if h else 0
        k = (h.i + 1) if h and n else 0
        if z == "count":
            if not h:
                return None
            return termtips.reader_counter_tip(k, n, h.mentions(self.mark), h.running)
        if z == "prev":
            return termtips.step_tip("Go to the previous paragraph that mentions the term.", "Alt+Left", k, n)
        return termtips.step_tip("Go to the next paragraph that mentions the term.", "Alt+Right", k, n)

    def _wheel(self, e):
        self.text.yview_scroll(-int(round(e.delta / 120.0)) * 3, "units")
        return "break"

    def min_height(self):
        return self.hdr.winfo_reqheight() + int(self.ls * 0.3) + 2 * self.ls + self.space3 + 2 * self.tpady + 2

    # ---- state
    def reset_book(self, series_path: str, book: str):
        if (series_path, book) != (self.series_path, self.book):
            self.series_path, self.book = series_path, book
            self.cache.clear()
            self.payloads.clear()
            if self.token:
                self.token.cancel()
            self.entry = None

    def _key(self, entry):
        return (id(entry), tuple(entry.spellings()))

    def _hits(self):
        if self.entry is None:
            return None
        return self.cache.get(self._key(self.entry))

    # ---- content
    def show(self, entry, meta: str, mark: bool):
        """Show the term's first/last viewed paragraph; starts the search on first view."""
        self.meta, self.mark = meta, mark
        if entry is not self.entry and self.token and not (self._hits() and self._hits().done):
            self.token.cancel()
            h = self._hits()
            if h:
                h.running = False
        self.entry = entry
        if entry is None or not self.series_path or not self.book:
            self.rx = None
            self._clear("0 / 0")
            return
        self.rx = termlogic.term_regex(entry)
        key = self._key(entry)
        h = self.cache.get(key)
        if h is None:
            h = self.cache[key] = Hits()
        if not h.done and not h.running:
            self._search(entry, key, h)
        self._render()

    def _search(self, entry, key, h: Hits):
        h.running = True
        h.items = []
        sp, book = self.series_path, self.book
        pattern = self.rx
        seen = sorted(entry.seen)

        def on_item(batch, h=h):
            h.items.extend(batch)
            if self._hits() is h:
                self._render(keep_place=True)

        def on_result(n, h=h):
            h.running = False
            h.done = True
            if self._hits() is h:
                self._render(keep_place=True)

        def on_error(exc, h=h):
            h.running = False
            h.done = True

        self.token = self.ui.worker.submit(
            lambda ctx: model.find_occurrences_task(ctx, sp, book, pattern, seen, self.mark),
            on_item=on_item, on_result=on_result, on_error=on_error, lane="search")

    def step(self, d):
        h = self._hits()
        if h is not None:
            n = len(h.view(self.mark))
            if n:
                self.go(h.i + d)
        return "break"

    def go(self, i):
        h = self._hits()
        if h is None:
            return
        n = len(h.view(self.mark))
        i = max(0, min(n - 1, i))
        if not n or i == h.i:
            return
        h.i = i
        self._render()

    def _clear(self, counter):
        tx = self.text
        tx.configure(state="normal")
        tx.delete("1.0", "end")
        tx.configure(state="disabled")
        self.title = ""
        self.stepper.set_state(counter, False, False)
        self._draw_lab()
        self.shown_block = None

    def _render(self, keep_place=False):
        h = self._hits()
        if h is None:
            self._clear("0 / 0")
            return
        view = h.view(self.mark)
        n = len(view)
        if not n:
            self._clear("0 / 0")
            return
        h.i = max(0, min(h.i, n - 1))
        more = "+" if h.running else ""
        counter = "%d / %d%s" % (h.i + 1, n, more)
        self.stepper.set_state(counter, h.i > 0, h.i < n - 1)
        ci, bi, _m, _p = view[h.i]
        if keep_place and self.shown_block == (self._key(self.entry), ci, bi):
            return
        self.req += 1
        req = self.req
        payload = self.payloads.get((self.book, ci))
        if payload is not None:
            self._paint(payload, ci, bi)
            return
        sp, book = self.series_path, self.book

        def done(p, req=req, ci=ci, bi=bi):
            self.payloads[(book, ci)] = p
            if len(self.payloads) > 12:
                self.payloads.pop(next(iter(self.payloads)))
            if req == self.req:
                self._paint(p, ci, bi)

        self.ui.worker.submit(lambda ctx: model.chapter_payload_task(ctx, sp, book, ci), on_result=done,
                              on_error=lambda exc: None, lane="fast")

    def _paint(self, payload, ci, bi):
        title, texts, indices = payload
        try:
            pos = indices.index(bi)
        except ValueError:
            return
        import time
        t0 = time.perf_counter()
        tx = self.text
        self.title = title
        self.shown_block = (self._key(self.entry), ci, bi)
        tx.configure(state="normal")
        tx.delete("1.0", "end")
        if pos > 0:
            tx.insert("end", "\n".join(texts[:pos]) + "\n", "dim")
        first = int(tx.index("end-1c").split(".")[0])
        self._insert_cur(texts[pos])
        last = int(tx.index("end-1c").split(".")[0])
        if pos + 1 < len(texts):
            tx.insert("end", "\n" + "\n".join(texts[pos + 1:]), "dim")
        tx.configure(state="disabled")
        self._draw_lab()
        self._place(first, last)
        self.last_ms = (time.perf_counter() - t0) * 1000

    def _insert_cur(self, block):
        tx = self.text
        spans = [(m.start(), m.end(), "hit") for m in self.rx.finditer(block)] if self.rx else []
        if self.mark:
            spans += [(m.start(), m.end(), "pron") for m in termlogic.PRONOUNS.finditer(block)
                      if not any(a < m.end() and m.start() < b for a, b, _ in spans)]
        spans.sort()
        pos = 0
        for a, b, tag in spans:
            if a > pos:
                tx.insert("end", block[pos:a], "cur")
            tx.insert("end", block[a:b], ("cur", tag))
            pos = b
        if pos < len(block):
            tx.insert("end", block[pos:], "cur")

    def current_text(self) -> str:
        """The highlighted paragraph (for checks)."""
        tx = self.text
        ranges = tx.tag_ranges("cur")
        if not ranges:
            return ""
        return tx.get(ranges[0], ranges[-1])

    def _place(self, first, last):
        tx = self.text
        tx.update_idletasks()
        vh = tx.winfo_height() - 2 * self.tpady
        tx.yview("%d.0" % first)
        if vh < self.ls:
            return
        end = "%d.0" % (last + 1) if tx.compare("%d.end" % last, "<", "end-1c") else "end"
        try:
            hh = int(tx.tk.call(str(tx), "count", "-ypixels", "%d.0" % first, end))
        except (tk.TclError, ValueError):
            return
        pad = max(0, (vh - hh) // 2)
        if pad:
            tx.yview_scroll(-pad, "pixels")

    def _draw_lab(self):
        c = self.lab
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 20:
            return
        f = self.font
        meta, title = self.meta, self.title
        gap = self.cw * 3
        mw, tw = f.measure(meta), f.measure(title)
        avail = W - gap
        if mw + tw <= avail:
            mws, tws = mw, tw
        elif mw < avail * 0.5:
            mws, tws = mw, avail - mw
        elif tw < avail * 0.5:
            mws, tws = avail - tw, tw
        else:
            mws = tws = avail // 2
        self.cut = mws < mw or tws < tw
        if meta:
            c.create_text(0, H / 2, text=fit_text(f, meta, mws), anchor="w", font=f, fill=DIM)
        if title:
            c.create_text(W, H / 2, text=fit_text(f, title, tws), anchor="e", font=f, fill=DIM)
