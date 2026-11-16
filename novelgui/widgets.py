"""Small flat widgets drawn on canvases: buttons, switch, search box, text field, popup list."""

from __future__ import annotations

import time
import tkinter as tk

from . import theme as T
from .platform import KEYCODES
from .theme import ACCENT, ACCENT_HOVER, BG, BRIGHT, DIM, FAINT, FLASH, S1, S2, S3, S4, TEXT


def rrect(c, x1, y1, x2, y2, r, **kw):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


class Pill(tk.Canvas):
    """Flat rounded button. kind: plain | accent | dim. `on` draws a plain/dim pill as switched on."""

    def __init__(self, master, text, command, font, kind="plain", bg=BG, padx=None, pady=None):
        self.font = font
        self.text = text
        self.kind = kind
        self.command = command
        self.base = bg
        self.enabled = True
        self.on = False
        self.hover = False
        ls = font.metrics("linespace")
        self.px = padx if padx is not None else int(ls * 0.95)
        self.py = pady if pady is not None else int(ls * 0.38)
        self.w = font.measure(text) + 2 * self.px
        self.h = ls + 2 * self.py
        super().__init__(master, width=self.w, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def _set_hover(self, v):
        self.hover = v
        self.draw()

    def _click(self, e):
        if self.enabled and 0 <= e.x < self.w and 0 <= e.y < self.h:
            self.command()

    def set_text(self, text):
        self.text = text
        self.w = self.font.measure(text) + 2 * self.px
        self.configure(width=self.w)
        self.draw()

    def set_enabled(self, v):
        if v != self.enabled:
            self.enabled = v
            self.configure(cursor="hand2" if v else "arrow")
            self.draw()

    def set_on(self, v):
        if v != self.on:
            self.on = v
            self.draw()

    def draw(self):
        self.delete("all")
        if not self.enabled:
            fill, fg = (self.base if self.kind == "dim" else (S1 if self.base != S2 else S3)), FAINT
        elif self.kind == "dim":
            if self.on:
                fill, fg = S3, BRIGHT
            else:
                fill, fg = (S2 if self.hover else self.base), (TEXT if self.hover else DIM)
        elif self.kind == "accent":
            fill, fg = (ACCENT_HOVER if self.hover else ACCENT), "#ffffff"
        else:
            rest = S3 if self.base == S2 else S2
            fill, fg = (S4 if self.hover else (S3 if self.on else rest)), (BRIGHT if self.on else TEXT)
        rrect(self, 0, 0, self.w, self.h, self.h * 0.28, fill=fill, outline="")
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg, font=self.font)


def rest_hot(rest) -> bool:
    return bool(rest and rest[0])


class Segmented(tk.Canvas):
    """Switch of a few choices. items: (key, label, count or None[, hot]); a hot count is drawn in the accent."""

    def __init__(self, master, font, on_change, bg=BG):
        self.font = font
        self.on_change = on_change
        ls = font.metrics("linespace")
        self.pad = int(ls * 0.95)
        self.h = ls + 2 * int(ls * 0.38)
        self.items = []
        self.value = None
        self.hover = None
        self.boxes = []
        self.enabled = True
        super().__init__(master, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._motion(None))

    def set_items(self, items, value=None):
        self.items = items
        if value is not None:
            self.value = value
        self.draw()

    def set_value(self, value):
        if value != self.value:
            self.value = value
            self.draw()

    def set_enabled(self, v):
        if v != self.enabled:
            self.enabled = v
            self.configure(cursor="hand2" if v else "arrow")
            self.draw()

    def seg_at(self, x):
        for i, (a, b) in enumerate(self.boxes):
            if a <= x < b:
                return i
        return None

    def _motion(self, e):
        h = None if e is None or not self.enabled else self.seg_at(e.x)
        if h != self.hover:
            self.hover = h
            self.draw()

    def _click(self, e):
        i = self.seg_at(e.x) if self.enabled else None
        if i is not None and self.items[i][0] != self.value:
            self.value = self.items[i][0]
            self.draw()
            self.on_change(self.value)

    def draw(self):
        self.delete("all")
        f = self.font
        inset = 3
        x = inset
        boxes, spans = [], []
        for key, label, cnt, *rest in self.items:
            wl = f.measure(label)
            wc = f.measure(str(cnt)) + int(self.pad * 0.4) if cnt is not None else 0
            extra = rest[1] if len(rest) > 1 and rest[1] is not None else None
            if extra is not None:
                wc += f.measure("\u00b7 %s" % extra) + int(self.pad * 0.4)
            if cnt is None and rest_hot(rest):
                wc = int(self.h * 0.3) + int(self.pad * 0.4)
            w = wl + wc + 2 * self.pad
            spans.append((x, x + w, wl, wc))
            boxes.append((x, x + w))
            x += w
        total = x + inset
        self.boxes = boxes
        self.configure(width=total)
        rrect(self, 0, 0, total, self.h, self.h * 0.28, fill=S2, outline="")
        for i, (key, label, cnt, *rest) in enumerate(self.items):
            a, b, wl, wc = spans[i]
            hot = bool(rest and rest[0])
            active = key == self.value
            if active:
                rrect(self, a, inset, b, self.h - inset, (self.h - 2 * inset) * 0.26, fill=S4, outline="")
            elif self.hover == i:
                rrect(self, a, inset, b, self.h - inset, (self.h - 2 * inset) * 0.26, fill=S3, outline="")
            tx = a + self.pad
            fg = BRIGHT if active else DIM
            if not self.enabled:
                fg = FAINT
            self.create_text(tx, self.h / 2, text=label, anchor="w", font=f, fill=fg)
            if cnt is None and hot:
                r = self.h * 0.07
                cx = tx + wl + int(self.pad * 0.4) + r + 1
                self.create_oval(cx - r, self.h / 2 - r * 1.4, cx + r, self.h / 2 + r * 0.6, fill=ACCENT,
                                 outline="")
            if cnt is not None:
                self.create_text(tx + wl + int(self.pad * 0.4), self.h / 2, text=str(cnt), anchor="w", font=f,
                                 fill=ACCENT if hot else (DIM if active else FAINT))
                if len(rest) > 1 and rest[1] is not None:
                    self.create_text(tx + wl + int(self.pad * 0.8) + f.measure(str(cnt)), self.h / 2,
                                     text="\u00b7 %s" % rest[1], anchor="w", font=f, fill=FAINT)


class DotsButton(tk.Canvas):
    """Icon-only `...` control (actions of a row or a volume). Brighter on hover, never darker than the window."""

    def __init__(self, master, size, command, bg=BG):
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.size, self.command, self.hover, self.enabled = size, command, False, True
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def _set(self, v):
        self.hover = v
        self.draw()

    def _click(self, e):
        if self.enabled and 0 <= e.x < self.size and 0 <= e.y < self.size:
            self.command(e)

    def set_enabled(self, v):
        if v != self.enabled:
            self.enabled = v
            self.configure(cursor="hand2" if v else "arrow")
            self.draw()

    def draw(self):
        self.delete("all")
        fg = FAINT if not self.enabled else (BRIGHT if self.hover else DIM)
        r = max(1.5, self.size * 0.075)
        cy = self.size / 2
        for k in (-1, 0, 1):
            cx = self.size / 2 + k * self.size * 0.26
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fg, outline="")


class Field(tk.Canvas):
    """A one-line text field on a rounded surface; `icon` adds the magnifier and a clear cross.

    Behaviour of every field (window_spec 9.3, 9.4, 9.8):
    - Enter commits the value and leaves the field; a click anywhere outside does the same.
    - Esc puts back the value the field had when it was entered and leaves it (it never clears).
    - `on_commit(value)` takes a value; it returns False (or raises ValueError) when the value is not allowed:
      the field then shows the previous value again and flashes once.
    - `on_submit(value)` is the Enter action of a field that adds or starts something; it runs after a
      successful commit, on Enter only.
    """

    focused_field = None            # the Field whose entry has the keyboard focus
    FLASH_MS = 160

    def __init__(self, master, font, on_change=None, on_submit=None, icon=False, bg=BG, width=None, surface=S2,
                 on_commit=None):
        self.font = font
        self.surface = surface
        ls = font.metrics("linespace")
        self.h = ls + 2 * int(ls * 0.38)
        self.var = tk.StringVar()
        self.on_change = on_change
        self.on_submit = on_submit
        self.on_commit = on_commit
        self.icon = icon
        self.focused = False
        self.base = ""              # the committed value: what Esc and an invalid entry go back to
        self.flashing = False
        super().__init__(master, height=self.h, bg=bg, highlightthickness=0, bd=0)
        if width:
            self.configure(width=width)
        self.entry = tk.Entry(self, textvariable=self.var, font=font, bd=0, relief="flat", bg=surface, fg=BRIGHT,
                              insertbackground=BRIGHT, insertwidth=2, selectbackground=S4,
                              selectforeground=BRIGHT, highlightthickness=0, disabledbackground=surface,
                              disabledforeground=FAINT)
        self.win = self.create_window(0, 0, window=self.entry, anchor="w")
        self.var.trace_add("write", lambda *a: self._changed())
        self.entry.bind("<FocusIn>", lambda e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._focus(False))
        self.entry.bind("<Escape>", lambda e: self._escape())
        self.entry.bind("<Return>", lambda e: self._enter())
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self._click)

    # ---- value
    def get(self) -> str:
        return self.var.get()

    def set(self, text: str) -> None:
        """Programmatic value: it counts as the committed one."""
        self.base = text
        self.var.set(text)

    def clear(self):
        self.var.set("")

    def set_enabled(self, v: bool) -> None:
        self.entry.configure(state="normal" if v else "disabled")

    # ---- commit, restore, leave
    def commit(self, force: bool = False) -> bool:
        """Take the typed value (Enter forces it even when unchanged). False, with the previous value back and
        one flash, when it is not allowed."""
        text = self.var.get()
        if text == self.base and not force:
            return True
        ok = True
        if self.on_commit:
            try:
                ok = self.on_commit(text) is not False
            except ValueError:
                ok = False
        if ok:
            self.base = self.var.get()      # the callback may have written the value in its canonical form
            return True
        self.var.set(self.base)
        self.flash()
        return False

    def restore(self) -> None:
        self.var.set(self.base)

    def leave(self) -> None:
        """Take the keyboard focus off the field (to the panel it sits in, else to the window)."""
        try:
            if self.entry.focus_get() is not self.entry:
                return
            w = self.master
            while w is not None and not getattr(w, "is_panel", False):
                w = getattr(w, "master", None)
            (w if w is not None else self.winfo_toplevel()).focus_set()
        except (tk.TclError, KeyError):
            pass

    def flash(self) -> None:
        if self.flashing:
            return
        self.flashing = True
        self.draw()

        def end():
            self.flashing = False
            try:
                self.draw()
            except tk.TclError:
                pass
        self.after(self.FLASH_MS, end)

    def _escape(self):
        self.restore()
        self.leave()
        return "break"

    def _enter(self):
        ok = self.commit(force=True)
        self.leave()
        if ok and self.on_submit:
            self.on_submit(self.var.get())
        return "break"

    def _changed(self):
        self.draw()
        if self.on_change:
            self.on_change(self.var.get())

    def _focus(self, v):
        self.focused = v
        if v:
            Field.focused_field = self
            self.base = self.var.get()
        elif Field.focused_field is self:
            Field.focused_field = None
            # focus moved on by the keyboard: the typed value counts as entered
            try:
                if self.winfo_exists() and self.entry.winfo_exists():
                    self.commit()
            except tk.TclError:
                pass
        self.draw()

    def _click(self, e):
        if self.icon and self.var.get() and e.x > self.winfo_width() - self.h:
            self.clear()
        self.entry.focus_set()

    @classmethod
    def install(cls, root) -> None:
        """One press handler for the window: a press outside the focused field commits it and leaves it."""
        root.bind("<ButtonPress>", cls._press_outside, add="+")

    @classmethod
    def _press_outside(cls, e):
        f = cls.focused_field
        if f is None:
            return
        try:
            under = f.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            under = None
        w = under
        while w is not None:
            if w is f or w is f.entry:
                return
            w = getattr(w, "master", None)
        f.commit()
        f.leave()

    def draw(self):
        W = max(self.winfo_width(), 50)
        H = self.h
        self.delete("shape")
        edge = FLASH if self.flashing else (S4 if self.focused else self.surface)
        rrect(self, 0, 0, W, H, H * 0.28, fill=self.surface, outline=edge, width=2 if self.flashing else 1,
              tags="shape")
        left = int(H * 0.45)
        right = int(H * 0.4)
        if self.icon:
            r = H * 0.17
            cx, cy = H * 0.55, H * 0.46
            self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=DIM, width=2, tags="shape")
            self.create_line(cx + r * 0.75, cy + r * 0.75, cx + r * 1.7, cy + r * 1.7, fill=DIM, width=2,
                             tags="shape")
            left = int(H * 1.0)
            if self.var.get():
                self.create_text(W - H * 0.5, H / 2, text="×", fill=DIM, font=self.font, tags="shape")
                right = H
        self.coords(self.win, left, H / 2)
        self.itemconfigure(self.win, width=max(10, W - left - right), height=H - 6)
        self.tag_raise(self.win)


class ListPopup(tk.Canvas):
    """Popup list drawn inside the window (a Toplevel would be invisible to PrintWindow)."""

    def __init__(self, root, font, row_h):
        super().__init__(root, bg=S2, highlightthickness=1, highlightbackground=S4, bd=0)
        self.font = font
        self.rh = row_h
        self.items = []
        self.labels = {}
        self.cur = 0
        self.on_pick = None
        self.on_cancel = None
        self.open = False
        self.hints = {}
        self.disabled = set()
        self.root = root
        self.openers = []
        self.watched = set()
        self.inside = set()
        self.seen = False
        self.armed = False
        self.leave_job = None
        self.geom = None
        self.LEAVE_MS = 350
        self._watch(self)
        root.bind("<ButtonPress>", self._global_press, add="+")
        root.bind("<Configure>", self._global_configure, add="+")
        self.bind("<Motion>", self._motion)
        self.bind("<Button-1>", self._click)
        self.bind("<Key-Up>", lambda e: self._move(-1))
        self.bind("<Key-Down>", lambda e: self._move(1))
        self.bind("<Return>", lambda e: self._pick(self.cur, 0))
        self.bind("<Tab>", lambda e: self._pick(self.cur, 1) or "break")
        self.bind("<Shift-Tab>", lambda e: self._pick(self.cur, -1) or "break")
        self.bind("<Escape>", lambda e: self._escape())
        self.bind("<FocusOut>", lambda e: self.after(60, self._lost))
        self.prev_grab = None
        self.opener_closed = None       # (time, opener) when a press on the opener closed the list

    def _arm(self):
        """After the event that opened the list is over: a press outside closes it, and the window behind is
        shut off by a grab."""
        if self.open:
            self.armed = True
            self._grab()

    def _escape(self):
        self.close(cancel=True)
        return "break"

    def _grab(self):
        """While the list is open the window behind ignores clicks: a press outside is only seen here."""
        try:
            self.prev_grab = self.grab_current()
        except (KeyError, tk.TclError):
            self.prev_grab = None
        try:
            self.grab_set()
        except tk.TclError:
            self.after(15, self._grab_again)

    def _grab_again(self):
        if not self.open:
            return
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _ungrab(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        prev, self.prev_grab = self.prev_grab, None
        try:
            if prev is not None and prev is not self and prev.winfo_exists():
                prev.grab_set()
        except tk.TclError:
            pass

    def _lost(self):
        if self.open and self.focus_get() is not self:
            self.close(cancel=True)

    def _watch(self, w):
        if w in self.watched:
            return
        self.watched.add(w)
        w.bind("<Enter>", lambda e, w=w: self._enter(w), add="+")
        w.bind("<Leave>", lambda e, w=w: self._leave(w), add="+")

    def _enter(self, w):
        if not self.open:
            return
        self.inside.add(w)
        self.seen = True
        if self.leave_job is not None:
            self.after_cancel(self.leave_job)
            self.leave_job = None

    def _leave(self, w):
        if not self.open:
            return
        self.inside.discard(w)
        if self.seen and not self.inside and self.leave_job is None:
            self.leave_job = self.after(self.LEAVE_MS, self._leave_check)

    def _leave_check(self):
        self.leave_job = None
        if self.open and self.seen and not self.inside:
            self.close(cancel=True)

    def _global_press(self, e):
        if not self.open:
            self.opener_closed = None       # a new click: the one that closed the list is over
            return
        if not self.armed:
            return
        try:
            under = self.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            under = None
        if under is self:
            return
        if under in self.openers:
            self.opener_closed = (time.monotonic(), under)
        self.close(cancel=True)

    def _global_configure(self, e):
        if self.open and e.widget is self.root and self.geom != self._geom():
            self.close(cancel=True)

    def _geom(self):
        r = self.root
        return (r.winfo_x(), r.winfo_y(), r.winfo_width(), r.winfo_height())

    def show(self, root, x, y, w, items, cur, on_pick, on_cancel=None, labels=None, hints=None, openers=(),
             disabled=()):
        oc, self.opener_closed = self.opener_closed, None
        if oc is not None and time.monotonic() - oc[0] < 1.5 and oc[1] in openers:
            return                  # the press on the opener just closed this list: a second click only closes it
        if self.open:
            self.close()
        self.openers = list(openers)
        for o in self.openers:
            self._watch(o)
        self.inside = set()
        self.seen = False
        self.armed = False
        self.after_idle(self._arm)
        self.hints = hints or {}
        self.disabled = set(disabled)
        self.items = items
        self.labels = labels or {}
        self.cur = items.index(cur) if cur in items else 0
        self.on_pick, self.on_cancel = on_pick, on_cancel
        h = len(items) * self.rh + 8
        W = root.winfo_width()
        H = root.winfo_height()
        if y + h > H:
            y = max(0, y - h - self.rh)
        x = max(0, min(x, W - w))
        self.configure(width=w, height=h)
        self.place(x=x, y=y)
        self.tk.call("raise", self._w)
        self.open = True
        self.geom = self._geom()
        self.draw()
        self.focus_set()

    def close(self, cancel=False):
        if not self.open:
            return
        self.open = False
        if self.leave_job is not None:
            self.after_cancel(self.leave_job)
            self.leave_job = None
        self._ungrab()
        self.place_forget()
        if cancel and self.on_cancel:
            self.on_cancel()

    def _row(self, y):
        i = (y - 4) // self.rh
        return int(i) if 0 <= i < len(self.items) else None

    def _motion(self, e):
        i = self._row(e.y)
        if i is not None and i != self.cur:
            self.cur = i
            self.draw()

    def _click(self, e):
        i = self._row(e.y)
        if i is not None:
            self._pick(i, 0)

    def _move(self, d):
        self.cur = max(0, min(len(self.items) - 1, self.cur + d))
        self.draw()
        return "break"

    def _pick(self, i, nxt):
        item = self.items[i]
        if item in self.disabled:
            return                  # a dim row does nothing; the list stays open
        cb = self.on_pick
        self.close()
        if cb:
            cb(item, nxt)

    def draw(self):
        self.delete("all")
        w = int(self.cget("width"))
        for i, it in enumerate(self.items):
            y = 4 + i * self.rh
            if i == self.cur:
                rrect(self, 4, y, w - 4, y + self.rh, 5, fill=S4, outline="")
            self.create_text(int(self.rh * 0.5) + 4, y + self.rh / 2, text=self.labels.get(it, it), anchor="w",
                             font=self.font, fill=FAINT if it in self.disabled else (BRIGHT if i == self.cur else TEXT))
            if self.hints.get(it):
                self.create_text(w - int(self.rh * 0.5) - 4, y + self.rh / 2, text=self.hints[it], anchor="e",
                                 font=self.font, fill=DIM)


# ---------------------------------------------------------------- clipboard on any keyboard layout
def _clip_do(widget, action):
    try:
        readonly = str(widget.cget("state")) in ("disabled", "readonly")
    except tk.TclError:
        readonly = False
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


def install_clipboard(root):
    """Ctrl+C/V/X/A on any layout (Tk binds by keysym, which is Cyrillic on a Russian layout). On the Latin
    layout Tk already acts, so only Select-all is forced there."""
    def on_key(event):
        action = KEYCODES.get(event.keycode)
        if action not in ("paste", "copy", "cut", "all"):
            return None
        if event.keysym.lower() in ("v", "c", "x", "a") and action != "all":
            return None
        _clip_do(event.widget, action)
        return "break"
    for cls in ("Entry", "Text"):
        root.bind_class(cls, "<Control-KeyPress>", on_key, add="+")
