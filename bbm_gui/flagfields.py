"""Widgets of the flag panel: wrapping rows of chips, and the value editors (spinbox, choice, list of chips, color,
file, text) that show a problem in the field itself and keep the last valid value."""
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk

from . import flagmenu
from .theme import P

SUGGEST_MAX = 12


class FlowFrame(ttk.Frame):
    """Children (created with this frame as parent) are laid out left to right and wrap to the next line when the
    frame is too narrow. The frame takes the height of its lines."""

    def __init__(self, parent, gap=6, **kw):
        super().__init__(parent, **kw)
        self.gap = gap
        self.items = []
        self._last = None
        self.bind("<Configure>", lambda e: self.reflow())

    def set(self, widgets):
        self.items = list(widgets)
        self._last = None
        self.after_idle(self.reflow)

    def clear(self):
        for w in self.items:
            w.destroy()
        self.set([])

    def lines(self, width):
        """[(widget, x, y)] and the total height for a given width."""
        x = y = rowh = 0
        out = []
        for w in self.items:
            ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            if x and x + ww > width:
                x, y, rowh = 0, y + rowh + self.gap, 0
            out.append((w, x, y))
            x += ww + self.gap
            rowh = max(rowh, wh)
        return out, y + rowh

    def reflow(self):
        if not self.winfo_exists():
            return
        width = self.winfo_width()
        if width <= 1:
            return
        placed, height = self.lines(width)
        key = (width, height, tuple((id(w), x, y) for w, x, y in placed))
        if key == self._last:
            return
        self._last = key
        for w, x, y in placed:
            w.place(x=x, y=y)
        self.configure(height=max(height, 1))


def decimals(step):
    text = ("%.6f" % step).rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


class ValueEditor(ttk.Frame):
    """The control for the value of one flag. on_value(value) gets every valid change ('' when emptied); a value that
    does not parse stays out of the command and the field shows why. suggestions() gives names for a list field."""

    def __init__(self, parent, spec, value, on_value, suggestions=None, px=lambda n: n):
        super().__init__(parent)
        self.spec, self.on_value, self.px = spec, on_value, px
        self.suggestions = suggestions or (lambda: [])
        self.var = tk.StringVar(value=flagmenu.initial_text(value))
        self.items = [x for x in str(value or "").split(",") if x] if spec.editor == "csv" else []
        self.columnconfigure(0, weight=1)
        self.hint = ttk.Label(self, text="", style="Dim.TLabel")
        self.main = None
        self.suggest_row = FlowFrame(self, gap=px(2))
        build = getattr(self, "_build_" + spec.editor, self._build_text)
        build()
        self._show_hint("")
        self.suggest_row.grid(row=1, column=0, columnspan=3, sticky="ew")
        self._fill_suggestions()
        if spec.editor != "csv":
            self.var.trace_add("write", lambda *_: self._changed())

    # ------------------------------------------------------------------ building
    def _entry(self, **kw):
        e = ttk.Entry(self, textvariable=self.var, **kw)
        e.grid(row=0, column=0, sticky="ew")
        self.main = e
        if self.spec.placeholder:
            self._placeholder(e)
        return e

    def _placeholder(self, entry):
        label = tk.Label(entry, text=self.spec.placeholder, background=P["bg1"], foreground=P["faint"], borderwidth=0)

        def sync(*_):
            if self.var.get():
                label.place_forget()
            else:
                label.place(x=self.px(7), rely=0.5, anchor="w")

        label.bind("<Button-1>", lambda e: entry.focus_set())
        self.var.trace_add("write", sync)
        sync()

    def _build_text(self):
        self._entry()
        self.hint.grid(row=0, column=1, padx=(8, 0))

    _build_json = _build_text
    _build_multi = _build_text

    def _build_secret(self):
        self._entry(show="•")

    def _build_combo(self):
        c = ttk.Combobox(self, textvariable=self.var, values=list(self.spec.choices))
        c.grid(row=0, column=0, sticky="ew")
        self.main = c

    def _build_enum(self):
        choices = list(self.spec.choices)
        if len(choices) <= 4:
            row = ttk.Frame(self)
            row.grid(row=0, column=0, sticky="w")
            for c in choices:
                ttk.Radiobutton(row, text=c, value=c, variable=self.var, style="Seg.Toolbutton").pack(side="left", padx=(0, 2))
            self.main = row
        else:
            c = ttk.Combobox(self, textvariable=self.var, values=choices, state="readonly")
            c.grid(row=0, column=0, sticky="ew")
            self.main = c

    def _build_toggle(self):
        self.main = None

    def _build_int(self):
        s = self.spec
        kw = {"from_": s.lo if s.lo is not None else -(10 ** 9), "to": s.hi if s.hi is not None else 10 ** 9,
              "increment": s.step}
        if self.spec.editor == "float":
            kw["format"] = "%%.%df" % decimals(s.step)
        box = ttk.Spinbox(self, textvariable=self.var, width=9, **kw)
        box.grid(row=0, column=0, sticky="w")
        self.main = box
        self.hint.grid(row=0, column=1, padx=(8, 0))
        self.columnconfigure(1, weight=0)

    _build_float = _build_int

    def _build_file(self):
        self._entry()
        ttk.Button(self, text="…", style="Icon.TButton", width=3, command=self._browse).grid(row=0, column=1, padx=(6, 0))

    _build_dir = _build_file

    def _browse(self):
        top = self.winfo_toplevel()
        path = filedialog.askdirectory(parent=top) if self.spec.editor == "dir" else filedialog.askopenfilename(parent=top)
        if path:
            self.var.set(path)

    def _build_color(self):
        self._entry()
        self.swatch = tk.Canvas(self, width=self.px(26), height=self.px(26), highlightthickness=1,
                                highlightbackground=P["line"], background=P["bg1"], cursor="hand2")
        self.swatch.grid(row=0, column=1, padx=(6, 0))
        self.swatch.bind("<Button-1>", lambda e: self._pick_color())
        self.hint.grid(row=0, column=2, padx=(8, 0))
        self.var.trace_add("write", lambda *_: self._paint())
        self._paint()

    def _color(self):
        text = self.var.get().strip()
        try:
            self.winfo_rgb(text)
            return text
        except tk.TclError:
            return None

    def _paint(self):
        col = self._color()
        self.swatch.configure(background=col or P["bg1"])

    def _pick_color(self):
        picked = colorchooser.askcolor(color=self._color() or "#808080", parent=self.winfo_toplevel())
        if picked and picked[1]:
            self.var.set(picked[1])

    # ------------------------------------------------------------------ list of items
    def _build_csv(self):
        self.flow = FlowFrame(self, gap=self.px(4))
        self.flow.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.entry = ttk.Entry(self.flow, textvariable=self.var, width=14)
        self.main = self.entry
        self.entry.bind("<Return>", lambda e: (self._commit(), "break")[1])
        self.entry.bind("<FocusOut>", lambda e: self._commit())
        self.entry.bind("<BackSpace>", self._backspace)
        self.var.trace_add("write", lambda *_: self._typing())
        self._chips = []
        self._redraw()

    def _redraw(self):
        for b in self._chips:
            b.destroy()
        self._chips = []
        for item in self.items:
            text = item + "  ✕"
            b = ttk.Button(self.flow, text=text, style="Chip.TButton", width=len(text) + 1, command=lambda i=item: self._drop(i))
            self._chips.append(b)
        self.flow.set(self._chips + [self.entry])

    def _typing(self):
        if "," in self.var.get():
            self._commit()
        else:
            self._fill_suggestions()

    def _commit(self):
        if not self.winfo_exists():
            return
        parts = [x.strip() for x in self.var.get().replace("\n", ",").split(",") if x.strip()]
        if not parts:
            return
        self.var.set("")
        self.add_items(parts)

    def add_items(self, parts):
        for p in parts:
            if p not in self.items:
                self.items.append(p)
        self._items_changed()

    def _drop(self, item):
        if item in self.items:
            self.items.remove(item)
        self._items_changed()
        self.entry.focus_set()

    def _backspace(self, event):
        if not self.var.get() and self.items:
            self.items.pop()
            self._items_changed()

    def _items_changed(self):
        self._redraw()
        self._fill_suggestions()
        self.on_value(",".join(self.items))

    # ------------------------------------------------------------------ suggestions and feedback
    def _names(self):
        return list(self.suggestions()) + list(self.spec.suggest)

    def _fill_suggestions(self):
        if not self.suggest_row.winfo_exists():
            return
        for w in self.suggest_row.items:
            w.destroy()
        names = self._names()
        typed = self.var.get().strip().lower() if self.spec.editor == "csv" else ""
        shown = [n for n in dict.fromkeys(names) if n not in self.items and (not typed or typed in n.lower())]
        buttons = []
        for n in shown[:SUGGEST_MAX]:
            buttons.append(ttk.Button(self.suggest_row, text=n, style="Sug.TButton", width=len(n) + 1,
                                      command=lambda v=n: self._use(v)))
        self.suggest_row.set(buttons)

    def _use(self, name):
        if self.spec.editor == "csv":
            self.add_items([name])
            self.entry.focus_set()
        else:
            self.var.set(name)

    def _show_hint(self, message):
        s = self.spec
        if message:
            self.hint.configure(text=message, style="Accent.TLabel")
        elif s.editor in ("int", "float") and (s.lo is not None or s.hi is not None):
            self.hint.configure(text="%s - %s" % (flagmenu._num(s.lo), flagmenu._num(s.hi)), style="Dim.TLabel")
        else:
            self.hint.configure(text="", style="Dim.TLabel")

    def _set_bad(self, bad):
        if self.spec.editor in ("int", "float"):
            self.main.configure(style="Bad.TSpinbox" if bad else "TSpinbox")
        elif isinstance(self.main, ttk.Entry):
            self.main.configure(style="Bad.TEntry" if bad else "TEntry")

    def _changed(self):
        status, value, message = flagmenu.parse_value(self.spec, self.var.get())
        if status == "ok" and self.spec.editor == "color" and self._color() is None:
            status, message = "bad", "#rrggbb or a name"
        self._set_bad(status == "bad")
        self._show_hint(message if status == "bad" else "")
        if status == "ok":
            self.on_value(value)
        elif status == "empty":
            self.on_value("")

    def focus_main(self):
        if self.main is not None and self.main.winfo_exists():
            try:
                self.main.focus_set()
            except tk.TclError:
                pass
