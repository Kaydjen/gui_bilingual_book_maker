"""A virtual list on a canvas: only the visible rows are drawn, so thousands of rows scroll smoothly.

Subclasses draw the cells (`draw_cells`) and the tooltips (`tip_body`, `tip_head`). Selection is a set of
row positions: click, shift-click (range), ctrl-click (toggle), drag, Ctrl+A, arrow keys.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from . import theme as T
from .theme import BRIGHT, DIM, FAINT, LINE, ROWLINE, S1, S2, S3, TEXT, blend
from .tooltip import attach_tip


class Col:
    def __init__(self, key, label, width=None, align="w", sortable=True):
        self.key = key
        self.label = label
        self.width = width        # em-ish units (multiples of the digit width); None = takes the rest
        self.align = align
        self.sortable = sortable


class VTable(tk.Frame):
    def __init__(self, master, ui, cols, header=True, resizable=True):
        super().__init__(master, bg=S1, highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE)
        self.ui = ui
        self.font = ui.font
        self.cols = cols
        self.show_header = header
        self.resizable = resizable
        self.fm = self.font.metrics("linespace")
        self.cw = self.font.measure("0")
        self.rh = self.fm + int(self.fm * 0.78)
        self.pad = int(self.cw * 1.1)
        self.widths = {c.key: int(c.width * self.cw) for c in cols if c.width}
        self.flex = next((c.key for c in cols if not c.width), None)
        self.rows: list = []
        self.pos: dict[int, int] = {}
        self.sel: set[int] = set()
        self.cursor = None
        self.anchor = None
        self.y0 = 0
        self.hover = None
        self.sort_key = None
        self.sort_desc = False
        self.last_col = None
        self.on_sort = None
        self.on_cursor = None
        self.on_changed = None
        self.on_toggle = None
        self.on_delete = None
        self.on_context = None
        self.on_activate = None
        self.on_view = None           # (first, last) visible rows, after every redraw
        self.on_widths = None         # a column width was dragged (called when the mouse is released)
        self.draw_ms = 0.0
        self._flash = None
        self._flash_job = None
        self._rrow = None
        self._fit_cache: dict = {}
        self._drag_col = None
        self.empty_note = None

        self.head = tk.Canvas(self, height=self.rh if header else 0, bg=S1, highlightthickness=0, bd=0)
        self.body = tk.Canvas(self, bg=S1, highlightthickness=0, bd=0, takefocus=1)
        self.body.taborder = True       # Tab reaches the table (keyboard.py)
        self.sb = ttk.Scrollbar(self, orient="vertical", style="Dark.Vertical.TScrollbar", command=self._sb_cmd)
        if header:
            self.head.grid(row=0, column=0, sticky="ew")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.sb.grid(row=0, column=1, rowspan=2, sticky="ns")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        b = self.body
        b.bind("<Configure>", lambda e: self._on_configure())
        b.bind("<Button-1>", self._click)
        b.bind("<Control-Button-1>", lambda e: self._click(e, ctrl=True))
        b.bind("<Shift-Button-1>", lambda e: self._click(e, shift=True))
        b.bind("<Double-Button-1>", self._dbl)
        b.bind("<B1-Motion>", self._drag)
        b.bind("<MouseWheel>", self._wheel)
        b.bind("<Motion>", self._motion)
        b.bind("<Leave>", lambda e: self._set_hover(None))
        b.bind("<Up>", lambda e: self._nav(-1, False))
        b.bind("<Down>", lambda e: self._nav(1, False))
        b.bind("<Shift-Up>", lambda e: self._nav(-1, True))
        b.bind("<Shift-Down>", lambda e: self._nav(1, True))
        b.bind("<Prior>", lambda e: self._nav(-self._page(), False))
        b.bind("<Next>", lambda e: self._nav(self._page(), False))
        b.bind("<Shift-Prior>", lambda e: self._nav(-self._page(), True))
        b.bind("<Shift-Next>", lambda e: self._nav(self._page(), True))
        b.bind("<Home>", lambda e: self._goto(0, False))
        b.bind("<End>", lambda e: self._goto(len(self.rows) - 1, False))
        b.bind("<space>", lambda e: self._call(self.on_toggle))
        b.bind("<Delete>", lambda e: self._call(self.on_delete))
        b.bind("<Control-a>", lambda e: self.select_all())
        b.bind("<Control-c>", lambda e: self.copy_rows())
        b.bind("<Control-KeyPress>", self._ctrl_key)
        b.bind("<Button-3>", self._rpress)
        b.bind("<ButtonRelease-3>", self._rrelease)
        b.bind("<Return>", lambda e: self._activate())
        b.bind("<F2>", lambda e: self._activate())
        h = self.head
        h.bind("<Configure>", lambda e: self.draw_head())
        h.bind("<Button-1>", self._head_click)
        h.bind("<B1-Motion>", self._head_drag)
        h.bind("<ButtonRelease-1>", self._head_release)
        h.bind("<Motion>", self._head_motion)

    # ---- subclass points
    def selectable(self, row) -> bool:
        return True

    def row_selectable(self, i: int) -> bool:
        return self.selectable(self.rows[i])

    def draw_cells(self, c, row, cols, y, mid):
        pass

    def tip_body(self, e):
        return None

    def tip_head(self, e):
        return None

    def copy_text(self, rows) -> str:
        return "\n".join(str(r) for r in rows)

    # ---- geometry
    def flex_w(self):
        W = self.body.winfo_width()
        return max(self.cw * 12, W - sum(self.widths.values()))

    def col_x(self):
        x = 0
        out = {}
        for c in self.cols:
            w = self.widths.get(c.key) or self.flex_w()
            out[c.key] = (x, w)
            x += w
        return out

    def col_at(self, x):
        for k, (cx, w) in self.col_x().items():
            if cx <= x < cx + w:
                return k
        return None

    def col_of(self, key):
        return next(c for c in self.cols if c.key == key)

    def _call(self, fn):
        if fn:
            fn()
        return "break"

    def _page(self):
        return max(1, self.body.winfo_height() // self.rh - 1)

    def _on_configure(self):
        self._clamp()
        self.draw()
        self.draw_head()

    # ---- data
    def index_of(self, row):
        return self.pos.get(id(row))

    def set_rows(self, rows, keep=None, keep_view=False):
        self.rows = rows
        self.pos = {id(r): i for i, r in enumerate(rows)}
        keep = keep or set()
        self.sel = {i for i, r in enumerate(rows) if id(r) in keep} if keep else set()
        self.cursor = self.anchor = None
        if not keep_view:
            self.y0 = 0
        if self.sel:
            self.cursor = self.anchor = min(self.sel)
            self.ensure_visible(self.cursor)
        self._clamp()
        self.draw()
        self.draw_head()
        self._fire()

    def refresh(self):
        """Redraw after row contents changed (rows and selection stay)."""
        self.draw()

    def selected_rows(self):
        return [self.rows[i] for i in sorted(self.sel) if i < len(self.rows)]

    def selected_indices(self):
        return sorted(i for i in self.sel if i < len(self.rows))

    def cursor_row(self):
        return self.rows[self.cursor] if self.cursor is not None and self.cursor < len(self.rows) else None

    def set_selection(self, indices, scroll=True):
        idx = sorted(i for i in indices if 0 <= i < len(self.rows) and self.row_selectable(i))
        self.sel = set(idx)
        self.cursor = self.anchor = idx[0] if idx else None
        if idx and scroll:
            self.ensure_visible(idx[0])
        self.draw()
        self._fire()

    def select_rows(self, rows, flash=False):
        idx = sorted(i for i in (self.index_of(r) for r in rows) if i is not None)
        if not idx:
            return False
        self.sel = set(idx)
        self.cursor = self.anchor = idx[0]
        self.ensure_visible(idx[0])
        self.draw()
        self._fire()
        if flash:
            self.flash([self.rows[i] for i in idx])
        return True

    def select_index(self, i):
        if not self.rows:
            self.sel, self.cursor, self.anchor = set(), None, None
        else:
            i = max(0, min(len(self.rows) - 1, i))
            self.sel, self.cursor, self.anchor = {i}, i, i
            self.ensure_visible(i)
        self.draw()
        self._fire()

    def _fire(self):
        if self.on_cursor:
            self.on_cursor(self.cursor_row())
        if self.on_changed:
            self.on_changed()

    def copy_rows(self):
        sel = self.selected_rows()
        if sel:
            self.clipboard_clear()
            self.clipboard_append(self.copy_text(sel))
        return "break"

    def _ctrl_key(self, e):
        if e.keycode == 65:
            return self.select_all()
        if e.keycode == 67:
            return self.copy_rows()
        return None

    # ---- flash (a one-off lighter row after a move)
    def flash(self, rows):
        self._flash = ({id(r) for r in rows}, time.perf_counter())
        if self._flash_job is None:
            self._flash_step()

    def flash_level(self):
        if not self._flash:
            return 0.0
        return max(0.0, 1.0 - (time.perf_counter() - self._flash[1]) / 0.7)

    def _flash_step(self):
        self._flash_job = None
        if self.flash_level() <= 0:
            self._flash = None
            self.draw()
            return
        self.draw()
        self._flash_job = self.after(35, self._flash_step)

    # ---- scrolling
    def _total(self):
        return len(self.rows) * self.rh

    def _clamp(self):
        H = self.body.winfo_height()
        self.y0 = max(0, min(self.y0, max(0, self._total() - H)))
        self._sb_set()

    def _thumb(self):
        H = max(1, self.body.winfo_height())
        tot = max(1, self._total())
        return min(1.0, max(H / tot, 3 * self.rh / H))

    def _sb_set(self):
        H = max(1, self.body.winfo_height())
        tot = max(1, self._total())
        if tot <= H:
            self.sb.set(0, 1)
        else:
            size = self._thumb()
            first = self.y0 / (tot - H) * (1 - size)
            self.sb.set(first, first + size)

    def _sb_cmd(self, *a):
        H = self.body.winfo_height()
        if a[0] == "moveto":
            tot = self._total()
            self.y0 = float(a[1]) / max(1e-6, 1 - self._thumb()) * max(0, tot - H)
        elif a[0] == "scroll":
            n = int(a[1])
            self.y0 += n * (self.rh * 3 if a[2] == "units" else H - self.rh)
        self._clamp()
        self.draw()

    def scroll_by_rows(self, n):
        self.y0 += n * self.rh
        self._clamp()
        self.draw()

    def _wheel(self, e):
        self.y0 -= (e.delta / 120.0) * self.rh * 3
        self._clamp()
        self.draw()
        self._motion(e)

    def ensure_visible(self, i):
        H = self.body.winfo_height()
        top = i * self.rh
        if top < self.y0:
            self.y0 = top
        elif top + self.rh > self.y0 + H:
            self.y0 = top + self.rh - H
        self._clamp()

    def visible_range(self):
        H = self.body.winfo_height()
        first = int(self.y0 // self.rh)
        last = min(len(self.rows) - 1, int((self.y0 + H) // self.rh))
        return first, last

    # ---- mouse / keyboard
    def row_at(self, y):
        i = int((y + self.y0) // self.rh)
        return i if 0 <= i < len(self.rows) else None

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.draw()

    def _motion(self, e):
        self._set_hover(self.row_at(e.y))

    def wire_tips(self):
        attach_tip(self.body, self.ui.tip, self.tip_body)
        attach_tip(self.head, self.ui.tip, self.tip_head)

    def _range(self, a, b):
        lo, hi = sorted((a, b))
        return {i for i in range(lo, hi + 1) if self.row_selectable(i)}

    def _click(self, e, ctrl=False, shift=False):
        self.body.focus_set()
        i = self.row_at(e.y)
        self.before_click(i)
        row = self.rows[i] if i is not None else None
        if row is not None:
            i = self.index_of(row)
        if i is None:
            return
        if not self.row_selectable(i) and not (ctrl or shift):
            return
        if shift and self.anchor is not None:
            self.sel = self._range(self.anchor, i)
        elif ctrl:
            if self.row_selectable(i):
                self.sel ^= {i}
            self.anchor = i
        else:
            self.sel = {i}
            self.anchor = i
        self.cursor = i
        self.draw()
        self._fire()
        self.after_click(e, i, ctrl, shift)

    def before_click(self, i):
        pass

    def after_click(self, e, i, ctrl, shift):
        pass

    def _drag(self, e):
        i = self.row_at(max(0, min(e.y, self.body.winfo_height() - 1)))
        if i is None or self.anchor is None:
            return
        self.sel = self._range(self.anchor, i)
        self.cursor = i
        self.draw()
        self._fire()

    def _dbl(self, e):
        i = self.row_at(e.y)
        if i is not None and self.on_activate:
            self.on_activate(self.rows[i], self.col_at(e.x))
        return "break"

    def _activate(self):
        if self.cursor is not None and self.on_activate:
            self.on_activate(self.rows[self.cursor], self.last_col)
        return "break"

    def _rpress(self, e):
        self.body.focus_set()
        i = self.row_at(e.y)
        self._rrow = i
        if i is None:
            return
        if i not in self.sel:
            self.sel, self.cursor, self.anchor = {i}, i, i
            self.draw()
            self._fire()
        else:
            self.cursor = i

    def _rrelease(self, e):
        if self._rrow is not None and self.on_context:
            self.on_context(e.x_root, e.y_root, e.x, e.y)

    def _nav(self, d, extend):
        if not self.rows:
            return "break"
        cur = 0 if self.cursor is None else self.cursor
        self._goto(cur + d, extend)
        return "break"

    def _goto(self, i, extend):
        if not self.rows:
            return "break"
        i = max(0, min(len(self.rows) - 1, i))
        if extend and self.anchor is not None:
            self.sel = self._range(self.anchor, i)
        else:
            self.sel = {i} if self.row_selectable(i) else set()
            self.anchor = i
        self.cursor = i
        self.ensure_visible(i)
        self.draw()
        self._fire()
        return "break"

    def select_all(self):
        self.sel = {i for i in range(len(self.rows)) if self.row_selectable(i)}
        self.anchor = 0
        if self.cursor is None and self.rows:
            self.cursor = 0
        self.draw()
        self._fire()
        return "break"

    # ---- header
    def _head_hit_border(self, x):
        if not self.resizable:
            return None
        for k, (cx, w) in self.col_x().items():
            if k in self.widths and abs(x - (cx + w)) <= 4:
                return k
        return None

    def _head_motion(self, e):
        self.head.configure(cursor="sb_h_double_arrow" if self._head_hit_border(e.x) else "arrow")

    def _head_click(self, e):
        k = self._head_hit_border(e.x)
        if k:
            self._drag_col = (k, e.x, self.widths[k])
            return
        c = self.col_at(e.x)
        if c and self.on_sort and self.col_of(c).sortable:
            self.on_sort(c)

    def _head_drag(self, e):
        if self._drag_col:
            k, x0, w0 = self._drag_col
            self.widths[k] = max(self.cw * 5, w0 + e.x - x0)
            self.draw()
            self.draw_head()

    def _head_release(self, e):
        moved = self._drag_col is not None
        self._drag_col = None
        if moved and self.on_widths:
            self.on_widths()

    def widths_state(self) -> dict:
        """Column widths in digit widths (stay right when the scale changes)."""
        return {k: round(px / max(1, self.cw), 2) for k, px in self.widths.items()}

    def set_widths_state(self, units: dict) -> None:
        for k, u in units.items():
            if k in self.widths and isinstance(u, (int, float)):
                self.widths[k] = max(self.cw * 5, int(u * self.cw))

    def head_colour(self, col, active):
        """Colour of a column heading (a table may mark one heading, e.g. with the accent)."""
        return BRIGHT if active else DIM

    def draw_head(self):
        if not self.show_header:
            return
        h = self.head
        h.delete("all")
        W = h.winfo_width()
        xs = self.col_x()
        for col in self.cols:
            cx, w = xs[col.key]
            active = col.key == self.sort_key
            fg = self.head_colour(col, active)
            arrow = "↓" if self.sort_desc else "↑"
            if col.align == "e":
                h.create_text(cx + w - self.pad, self.rh / 2, text=col.label, anchor="e", font=self.font, fill=fg)
                if active:
                    h.create_text(cx + w - self.pad - self.font.measure(col.label) - 6, self.rh / 2, text=arrow,
                                  anchor="e", font=self.font, fill=fg)
            else:
                h.create_text(cx + self.pad, self.rh / 2, text=col.label, anchor="w", font=self.font, fill=fg)
                if active:
                    h.create_text(cx + self.pad + self.font.measure(col.label) + 6, self.rh / 2, text=arrow,
                                  anchor="w", font=self.font, fill=fg)
        h.create_line(0, self.rh - 1, W, self.rh - 1, fill=LINE)

    # ---- body
    def fit(self, s, w):
        key = (s, w)
        r = self._fit_cache.get(key)
        if r is not None:
            return r
        f = self.font
        if f.measure(s) <= w:
            r = s
        else:
            lo, hi = 0, len(s)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if f.measure(s[:mid] + "…") <= w:
                    lo = mid
                else:
                    hi = mid - 1
            r = s[:lo].rstrip() + "…" if lo else "…"
        if len(self._fit_cache) > 20000:
            self._fit_cache.clear()
        self._fit_cache[key] = r
        return r

    def row_fill(self, i, row):
        if i in self.sel:
            return S3
        return S2 if i == self.hover else None

    def draw(self):
        t0 = time.perf_counter()
        c = self.body
        c.delete("all")
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 10:
            return
        rh = self.rh
        n = len(self.rows)
        first = int(self.y0 // rh)
        last = min(n, int((self.y0 + H) // rh) + 1)
        cols = self.col_x()
        mid = rh / 2
        fl = self._flash
        flv = self.flash_level()
        for i in range(first, last):
            row = self.rows[i]
            y = i * rh - self.y0
            base = self.row_fill(i, row)
            if fl and id(row) in fl[0]:
                base = blend(base or S1, T.FLASH, flv)
            if base:
                c.create_rectangle(0, y, W, y + rh, fill=base, outline="")
            c.create_line(0, y + rh - 1, W, y + rh - 1, fill=ROWLINE)
            self.draw_cells(c, row, cols, y, mid)
        self._sb_set()
        self.draw_ms = (time.perf_counter() - t0) * 1000
        if self.on_view:
            self.on_view(first, max(first, last - 1))
