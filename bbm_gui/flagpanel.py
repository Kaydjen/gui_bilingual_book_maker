"""Flags next to the command: a strip of chips (the flags in effect) and, under it, an inline panel to find, add,
edit and remove a flag. The state lives in flagstate; the panel only edits it."""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import flagdocs, flagmenu
from .flagfields import FlowFrame, ValueEditor
from .ordlist import InputField
from .theme import P

CHIP_STYLE = {"preset": "ChipPreset", "user": "ChipMine", "bad": "ChipBad"}
LIST_ROWS = 6


class FlagBar(ttk.Frame):
    """The chip strip plus the panel row. Put it in one grid row of the main window."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.strip = FlowFrame(self, gap=app.px(6))
        self.strip.grid(row=0, column=0, sticky="ew")
        self.editing = None  # the flag whose chip is selected (kept even while its value is still empty)
        self.panel = FlagPanel(self, app)
        self.is_open = False
        self._buttons = []
        self._sig = None
        self._before = None  # window height before the panel pushed it
        self._grown = None
        app.root.bind("<Escape>", self._escape, add="+")
        self.refresh()

    # ------------------------------------------------------------------ strip
    def refresh(self):
        app = self.app
        items = flagmenu.chips(app.flagstate, app.inventory, app.overlay, self.editing)
        sig = (tuple(items), self.editing, self.is_open, bool(app.inventory), app.flagstate.differs())
        if self.is_open:
            self.panel.refresh_marks()
        if sig == self._sig:
            return
        self._sig = sig
        for b in self._buttons:
            b.destroy()
        self._buttons = []
        for chip in items:
            style = CHIP_STYLE[chip.origin] + ("Edit" if chip.fid == self.editing and self.is_open else "") + ".TButton"
            b = ttk.Button(self.strip, text=chip.text, style=style, width=len(chip.text) + 2,
                           command=lambda f=chip.fid: self.edit(f))
            b.bind("<Delete>", lambda e, f=chip.fid: self.panel.remove(f))
            b.bind("<Return>", lambda e, f=chip.fid: (self.edit(f), "break")[1])
            self._buttons.append(b)
        if app.inventory:
            self.plus = ttk.Button(self.strip, text="+", style="Chip.TButton", width=3, command=self.toggle)
            self._buttons.append(self.plus)
            if app.flagstate.differs():  # a preset flag is off or changed: one click brings the defaults back
                self._buttons.append(ttk.Button(self.strip, text="Defaults", style="Chip.TButton", width=9,
                                                command=self.restore_defaults))
        self.strip.set(self._buttons)

    def restore_defaults(self):
        if self.app.flagstate.reset_preset():
            self.editing = None
            self.app.flags_changed()
        self.refresh()

    # ------------------------------------------------------------------ panel
    def toggle(self):
        self.close() if self.is_open else self.open()

    def edit(self, fid):
        if not self.is_open:
            self.open()
        self.panel.show_flag(fid, reveal=True)

    def open(self):
        if self.is_open or not self.app.inventory:
            return
        self.is_open = True
        self.panel.grid(row=1, column=0, sticky="ew", pady=(self.app.px(6), 0))
        self.panel.populate()
        self._grow()
        self.refresh()
        self.panel.search_entry.focus_set()

    def close(self):
        if not self.is_open:
            return
        self.panel.finish_edit()
        self.is_open = False
        self.panel.grid_remove()
        self.editing = None
        self._shrink()
        self.refresh()
        if self._buttons:
            self._buttons[-1].focus_set()

    def _escape(self, event):
        if self.is_open:
            self.close()
            return "break"
        return None

    def _grow(self):
        """The panel pushes the command and the log down; the window grows by what is missing."""
        root = self.app.root
        root.update_idletasks()
        need, have = root.winfo_reqheight(), root.winfo_height()
        limit = root.winfo_screenheight() - self.app.px(90)
        if need > have:
            self._before = have
            self._grown = min(need, limit)
            root.geometry("%dx%d" % (root.winfo_width(), self._grown))
        else:
            self._before = self._grown = None

    def _shrink(self):
        root = self.app.root
        if self._before and root.winfo_height() == self._grown:
            root.geometry("%dx%d" % (root.winfo_width(), self._before))
        self._before = self._grown = None


class FlagPanel(tk.Frame):
    def __init__(self, bar, app):
        super().__init__(bar, background=P["line"], padx=1, pady=1)
        self.bar, self.app = bar, app
        px = app.px
        inner = ttk.Frame(self, padding=(px(12), px(10)))
        inner.pack(fill="both", expand=True)
        inner.columnconfigure(0, weight=3, minsize=px(300))
        inner.columnconfigure(1, weight=2, minsize=px(250))
        self.fid = None
        self._rendered = None  # the flag the detail and editor were last drawn for
        self.rows = []
        self.at = {}  # flag id -> row id
        self.editor = None
        self.search = tk.StringVar()
        self.show_all = tk.BooleanVar(value=False)

        top = ttk.Frame(inner)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(8)))
        top.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(top, textvariable=self.search)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(top, text="All flags", variable=self.show_all, style="Seg.Toolbutton",
                        command=self.populate).grid(row=0, column=1, padx=(px(8), 0))
        self.search.trace_add("write", lambda *_: self.populate())
        self.search_entry.bind("<Down>", lambda e: (self.tree.focus_set(), "break")[1])

        left = ttk.Frame(inner)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, px(12)))
        left.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(left, columns=("mark", "label", "reason", "line"), show="", selectmode="browse",
                                 height=LIST_ROWS)
        self.tree.column("mark", width=px(22), stretch=False, anchor="center")
        self.tree.column("label", width=px(130), stretch=False)
        self.tree.column("reason", width=0, minwidth=0, stretch=False)
        self.tree.column("line", width=px(160), stretch=True)
        base = tkfont.nametofont("TkDefaultFont")
        self.tree.tag_configure("head", foreground=P["dim"], font=(base.actual("family"), 9, "bold"))
        self.tree.tag_configure("dim", foreground=P["dim"])
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selected())
        self.tree.bind("<Return>", lambda e: (self.activate(), "break")[1])
        self.tree.bind("<Double-ButtonPress-1>", lambda e: (self.activate(), "break")[1])
        self.tree.bind("<Delete>", lambda e: self.remove(self.fid) if self.fid else None)

        other = ttk.Frame(left)
        other.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))
        other.columnconfigure(1, weight=1)
        ttk.Label(other, text="Other", style="Dim.TLabel").grid(row=0, column=0, padx=(0, px(10)))
        self.other_var = tk.StringVar()
        self.other = InputField(other, textvariable=self.other_var)
        self.other.grid(row=0, column=1, sticky="ew")
        self.other.bind("<Return>", lambda e: self._add_other())

        right = ttk.Frame(inner)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.detail = tk.Text(right, height=7, width=30, wrap="word", background=P["bg1"], foreground=P["text"],
                              relief="flat", borderwidth=0, padx=px(10), pady=px(6), state="disabled", cursor="arrow",
                              highlightthickness=1, highlightbackground=P["line"], highlightcolor=P["line"],
                              selectbackground=P["bg3"])
        self.detail.tag_configure("title", font=(base.actual("family"), 10, "bold"))
        self.detail.tag_configure("dim", foreground=P["dim"])
        self.detail.tag_configure("h", foreground=P["dim"], font=(base.actual("family"), 9, "bold"))
        dsb = ttk.Scrollbar(right, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=dsb.set)
        self.detail.grid(row=0, column=0, sticky="nsew")
        dsb.grid(row=0, column=1, sticky="ns")
        self.host = ttk.Frame(right)
        self.host.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))
        self.host.columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ list
    def populate(self):
        app = self.app
        shown = self.show_all.get() or bool(self.search.get().strip())
        self.tree.column("reason", width=self.app.px(100) if shown else 0, stretch=False)
        self.rows = flagmenu.rows(app.inventory, app.overlay, self.show_all.get(), self.search.get())
        self.tree.delete(*self.tree.get_children())
        self.at = {}
        for n, row in enumerate(self.rows):
            iid = str(n)
            if row.head:
                self.tree.insert("", "end", iid=iid, values=("", row.head, "", ""), tags=("head",))
            else:
                self.at[row.flag["id"]] = iid
                self.tree.insert("", "end", iid=iid, values=("", row.label, row.reason, row.line))
        self.refresh_marks()
        want = self.at.get(self.fid) or next((str(n) for n, r in enumerate(self.rows) if not r.head), None)
        if want:
            self.tree.selection_set(want)
            self.tree.see(want)
            if want == next((str(n) for n, r in enumerate(self.rows) if not r.head), None):
                self.tree.yview_moveto(0)  # the first flag selected: keep its sub-head in view
        elif not self.fid:
            self._clear_detail()

    def refresh_marks(self):
        st = self.app.flagstate
        eff = st.effective()
        byid = {f["id"]: f for f in (self.app.inventory or {}).get("flags", [])}
        for fid, iid in self.at.items():
            f = byid[fid]
            on = flagmenu.active(flagmenu.spec_of(f, self.app.overlay).kind, eff.get(fid))
            mark = "✓" if on else ""
            if self.tree.exists(iid) and self.tree.set(iid, "mark") != mark:
                self.tree.set(iid, "mark", mark)

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        n = int(sel[0])
        row = self.rows[n] if n < len(self.rows) else None
        if row is None:
            return
        if row.head:  # a sub-head is no flag: move on in the direction of travel
            last = getattr(self, "_last_row", -1)
            step = -1 if n < last else 1
            m = n + step
            while 0 <= m < len(self.rows) and self.rows[m].head:
                m += step
            if not 0 <= m < len(self.rows):
                m = n - step
                while 0 <= m < len(self.rows) and self.rows[m].head:
                    m -= step
            if 0 <= m < len(self.rows):
                self.tree.selection_set(str(m))
            return
        self._last_row = n
        if row.flag["id"] != self._rendered:  # the same flag again (a late echo of selection_set) changes nothing
            self.show_flag(row.flag["id"])

    # ------------------------------------------------------------------ one flag
    def show_flag(self, fid, reveal=False):
        if self.bar.editing and self.bar.editing != fid:
            self.finish_edit()
        self.fid = fid
        known = fid in {f["id"] for f in (self.app.inventory or {}).get("flags", [])}
        if reveal and known and fid not in self.at:
            self.show_all.set(True)
            self.populate()
        if fid in self.at and self.tree.selection() != (self.at[fid],):
            self.tree.selection_set(self.at[fid])
            self.tree.see(self.at[fid])
        f = self._flag(fid)
        on = bool(f) and self._is_on(f) or (f is None)
        self.bar.editing = fid if (on or self.bar.editing == fid) else None
        self._render_detail(fid)
        self._render_editor()
        self.bar.refresh()

    def _flag(self, fid):
        for f in (self.app.inventory or {}).get("flags", []):
            if f["id"] == fid:
                return f
        return None

    def _is_on(self, f):
        spec = flagmenu.spec_of(f, self.app.overlay)
        return flagmenu.active(spec.kind, self.app.flagstate.effective().get(f["id"]))

    def _clear_detail(self):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.configure(state="disabled")
        for w in self.host.winfo_children():
            w.destroy()
        self.editor = None
        self._rendered = None

    def _render_detail(self, fid):
        app = self.app
        t = self.detail
        t.configure(state="normal")
        t.delete("1.0", "end")
        f = self._flag(fid)
        if f is None:
            t.insert("end", fid, "title")
            t.insert("end", "\nNot in this engine", "dim")
        else:
            ov = flagmenu.ov_of(app.overlay, fid)
            doc = flagdocs.describe(f, ov)
            t.insert("end", flagmenu.label_of(f, app.overlay), "title")
            t.insert("end", "   " + fid, "dim")
            if doc.about:
                t.insert("end", "\nAbout  ", "h")
                t.insert("end", doc.about)
            if doc.example:
                t.insert("end", "\nExample  ", "h")
                t.insert("end", doc.example)
            default = flagmenu.spec_of(f, app.overlay).default
            if default:
                t.insert("end", "\nDefault  ", "h")
                t.insert("end", default)
            if doc.engine:
                t.insert("end", "\nEngine text  ", "h")
                t.insert("end", doc.engine, "dim")
        t.configure(state="disabled")
        t.yview_moveto(0)

    def _render_editor(self):
        for w in self.host.winfo_children():
            w.destroy()
        self.editor = None
        fid = self.fid
        self._rendered = fid
        f = self._flag(fid)
        if f is None:
            if fid:
                ttk.Button(self.host, text="✕", style="Icon.TButton", width=3,
                           command=lambda: self.remove(fid)).grid(row=0, column=1)
            return
        spec = flagmenu.spec_of(f, self.app.overlay)
        if not self._is_on(f) and self.bar.editing != fid:
            ttk.Button(self.host, text="Add", command=lambda: self.add(fid)).grid(row=0, column=0, sticky="w")
            return
        cur = self.app.flagstate.effective().get(fid)
        if spec.editor != "toggle":
            self.editor = ValueEditor(self.host, spec, cur, lambda v: self._value(fid, v),
                                      suggestions=lambda: self.app.suggestions_for(fid), px=self.app.px)
            self.editor.grid(row=0, column=0, sticky="ew")
        ttk.Button(self.host, text="✕", style="Icon.TButton", width=3,
                   command=lambda: self.remove(fid)).grid(row=0, column=1, sticky="ne", padx=(self.app.px(6), 0))

    # ------------------------------------------------------------------ edits
    def activate(self):
        """Enter or a double click on a row: add the flag, or go to its value."""
        if not self.fid:
            return
        f = self._flag(self.fid)
        if f is not None and not self._is_on(f):
            self.add(self.fid)
        elif self.editor is not None:
            self.editor.focus_main()

    def add(self, fid):
        app, st = self.app, self.app.flagstate
        f = self._flag(fid)
        if f is None:
            return
        spec = flagmenu.spec_of(f, app.overlay)
        if st.origin(fid) == "hidden":
            st.revert(fid)  # a preset flag switched off: back to the preset value
        else:
            st.set(fid, flagmenu.start_value(spec, f))
        self.bar.editing = fid
        app.flags_changed()
        if spec.editor == "toggle":
            self.bar.close()
            return
        self._render_editor()
        if self.editor is not None:
            self.editor.focus_main()

    def _value(self, fid, value):
        self.app.flagstate.set(fid, value)
        self.app.flags_changed()

    def remove(self, fid):
        """Stop using my value: back to the preset value, or off (a preset flag gets a tombstone)."""
        st = self.app.flagstate
        if st.origin(fid) == "user" and fid in st.preset_flags():
            st.revert(fid)
        else:
            st.remove(fid)
        f = self._flag(fid)
        on = f is not None and self._is_on(f)
        self.bar.editing = fid if on else None
        self.app.flags_changed()
        if self.is_current(fid):
            self._render_detail(fid)
            self._render_editor()
        self.bar.refresh()

    def is_current(self, fid):
        return self.fid == fid and self.bar.is_open

    def finish_edit(self):
        """Leave the flag being edited: an emptied value means the flag is off."""
        fid = self.bar.editing
        if not fid:
            return
        f = self._flag(fid)
        st = self.app.flagstate
        if f is not None and not self._is_on(f) and fid in st.effective():
            st.remove(fid)
            self.app.flags_changed()
        self.bar.editing = None

    def _add_other(self):
        text = self.other_var.get().strip()
        if not text:
            return
        added, refused = self.app.add_extra(text)
        if refused:
            self.other.say("%s: %s" % refused[0], bad=True)
        else:
            self.other_var.set("")
            if added:
                self.show_flag(added[-1], reveal=True)
