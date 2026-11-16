"""Step 2: the term base of the series. New / Known / Questions, inline edit, merge, import, export."""

from __future__ import annotations

import tkinter as tk

from . import model, termlogic
from .dialog import message
from .reader import Reader
from .step import Step
from .terms_const import TYPES
from .terms_table import TermsTable
from .theme import BG, DIM, FAINT, LINE, S2, S3
from .tooltip import attach_tip
from .widgets import Field, Pill, Segmented


class TermsStep(Step):
    key = "terms"
    label = "Terms"

    def __init__(self, master, app):
        super().__init__(master, app)
        ui = self.ui
        ls, cw = ui.ls, ui.cw
        self.cw = cw
        self.gap = gap = int(ls * 0.8)
        self.doc = None
        self.entries: list = []
        self.tab = "new"
        self.query = ""
        self.type_filter = None
        self.in_selection = False
        self.sel_ids = None
        self._sel_key = None
        self._sel_token = None
        self.busy = False
        self.trash: list = []
        self._undo_job = None
        self._reader_job = None
        self._loaded_path = None
        self.marks = model.gender_marks("ru")
        self.fr = None
        self._fr_key = None
        self._scan_token = None
        self.scanning = False
        self.scan_frac = 0.0
        self.next_rows: list = []
        self.next_n = None
        self.next_extra = 0
        self._virt: dict = {}
        self.dismissed: list = []

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(0, gap))
        self.seg = Segmented(top, ui.font, self._tab_changed)
        self.seg.pack(side="left")
        self.type_btn = Pill(top, "All types  ▾", self._open_types, ui.font)
        self.type_btn.pack(side="right")
        self.sel_btn = Pill(top, "In selection", self._toggle_selection, ui.font, kind="dim")
        self.sel_btn.pack(side="right", padx=(0, gap // 2))
        self.search = Field(top, ui.font, on_change=self._search_changed, icon=True)
        self.search.pack(side="left", fill="x", expand=True, padx=gap)

        self.scanbar = tk.Canvas(self, height=max(2, int(ls * 0.12)), bg=BG, highlightthickness=0, bd=0)
        attach_tip(self.seg, ui.tip, lambda e: (
            "Next: the first number counts terms of the base that are not confirmed yet in the selected chapters; "
            "translation stops before the first chapter that has one. The second number counts names found in the "
            "text that are only suggestions: they never stop a job, because they are not checked by a model yet.",
            [("First number", "blocks translating"), ("Second number", "only suggested"),
             ("Questions", "need an answer")]))

        self.split = tk.Frame(self, bg=BG)
        self.split.pack(fill="both", expand=True)
        self.split.grid_propagate(False)
        self.split.grid_columnconfigure(0, weight=1)
        self.split.grid_rowconfigure(0, weight=1)
        self.table = TermsTable(self.split, ui, model.target_label("ru:Russian"), self.marks)
        self.table.grid(row=0, column=0, sticky="nsew")
        self.grip_h = max(6, int(ls * 0.45))
        self.grip = tk.Canvas(self.split, height=self.grip_h, bg=BG, highlightthickness=0, bd=0,
                              cursor="sb_v_double_arrow")
        self.grip.grid(row=1, column=0, sticky="ew")
        self.reader = Reader(self.split, ui)
        self.reader.grid(row=2, column=0, sticky="ew")
        self.reader.pack_propagate(False)
        self.pane_frac = ui.settings.get_float("pane_frac", 0.34, 0.1, 0.7)
        self.pane_default = 0.34
        self.pane_h = 0
        self._grip_drag0 = None
        self._grip_hover = False
        self.grip.bind("<Enter>", lambda e: self._grip_set_hover(True))
        self.grip.bind("<Leave>", lambda e: self._grip_set_hover(False))
        self.grip.bind("<Button-1>", self._grip_press)
        self.grip.bind("<B1-Motion>", self._grip_move)
        self.grip.bind("<Double-Button-1>", self._grip_toggle)
        self.grip.bind("<Configure>", lambda e: self._grip_draw())
        self.split.bind("<Configure>", lambda e: self._apply_frac())
        attach_tip(self.grip, ui.tip, lambda e: (
            "Drag to make the reading pane taller or shorter. Double-click switches between two sizes.",
            [("Drag", "any height"), ("Double-click", "default / tall"), ("Remembered", "yes")]))

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", pady=(gap, 0))
        self.foot = foot
        self.merge_btn = Pill(foot, "Merge", self.merge, ui.font)
        self.del_btn = Pill(foot, "Delete", self.delete, ui.font)
        self.undo_btn = Pill(foot, "Undo", self.undo, ui.font, kind="dim")
        self.not_btn = Pill(foot, "Not a term", self.dismiss_candidates, ui.font)
        self.import_btn = Pill(foot, "Import", self.import_glossary, ui.font, kind="dim")
        self.export_btn = Pill(foot, "Export", self.export_base, ui.font, kind="dim")
        self.confirm_btn = Pill(foot, "Confirm all", self.confirm_all, ui.font, kind="accent")
        self.confirm_btn.pack(side="right")
        self.merge_btn.pack(side="left")
        self.del_btn.pack(side="left", padx=(gap // 2, 0))
        self.not_btn.pack(side="left", padx=(gap // 2, 0))
        self.export_btn.pack(side="right", padx=(0, gap))
        self.import_btn.pack(side="right", padx=(0, gap // 2))
        self.gap = gap

        tip = ui.tip
        attach_tip(self.merge_btn, tip, lambda e: (
            "Join the selected rows into one term. The first row stays; the others become other spellings of it.",
            [("Applies to", "selected rows"), ("Needs", "two or more rows"), ("Undo", "no")]))
        attach_tip(self.not_btn, tip, lambda e: (
            "This is not a term, so it never holds back translation again. Works on the selected rows that are "
            "not in the term base yet.", [("Applies to", "selected rows"), ("Key", "N"), ("Undo", "yes, for 6 s")]))
        attach_tip(self.del_btn, tip, lambda e: (
            "Remove the selected terms from the base.", [("Applies to", "selected rows"), ("Undo", "yes, for 6 s")]))
        attach_tip(self.confirm_btn, tip, lambda e: (
            "Mark every row shown here as checked. Rows with an open question are skipped; they stay for you "
            "to answer.", [("Applies to", "rows shown in New"), ("Skips", "rows with questions")]))
        attach_tip(self.import_btn, tip, lambda e: (
            "Read your own glossary files, plain JSON with the English term and its translation. The terms "
            "become confirmed; a term that two files translate differently becomes a question.",
            [("Format", "{\"term\": \"translation\"}"), ("Terms become", "confirmed"),
             ("Conflicts", "become questions")]))
        attach_tip(self.export_btn, tip, lambda e: (
            "Save the whole term base to a JSON file.", [("Format", "terms.json"), ("Contains", "every term")]))
        attach_tip(self.sel_btn, tip, lambda e: (
            "Show only the terms that occur in the chapters selected on the Books step.",
            [("Chapters", str(len(self.app.selection))), ("Applies to", "the list below")]))
        attach_tip(self.type_btn, tip, lambda e: (
            "Show only terms of one type.", [("Types", "character, place, item ...")]))

        t = self.table
        t.apply = self._apply
        t.on_sort = self._sort_clicked
        t.on_cursor = self._cursor_changed
        t.on_changed = self._update_chrome
        t.on_toggle = self.toggle_confirm
        t.on_delete = self.delete
        t.on_edited = self._edited
        t.on_context = self._context_menu
        t.wire_tips()
        t.body.bind("<KeyPress>", self._key_press, add="+")
        ui.root.bind("<Control-f>", lambda e: self._focus_search() if self.winfo_ismapped() else None, add="+")
        ui.root.bind("<Control-z>", self._undo_key, add="+")
        ui.root.bind("<Alt-Left>", lambda e: self.reader.step(-1) if self.winfo_ismapped() else None, add="+")
        ui.root.bind("<Alt-Right>", lambda e: self.reader.step(1) if self.winfo_ismapped() else None, add="+")
        self._set_default_order()
        self._update_chrome()

    # ------------------------------------------------------------- life
    def on_show(self):
        self._load_if_needed()
        self.reader.reset_book(self.app.series.path if self.app.series else "", self.app.book)
        self._update_selection_state()
        self.after(10, lambda: (self._apply_frac(), self.table.body.focus_set()))

    def on_series(self):
        self._cancel_scan()
        self.fr, self._fr_key, self.next_rows, self.next_n, self._virt = None, None, [], None, {}
        self.dismissed = []
        self._loaded_path = None
        self.doc = None
        self.entries = []
        self.trash = []
        self._hide_undo()
        self.refilter()
        if self.winfo_ismapped() or self.app.current == self.key:
            self._load_if_needed()

    def on_book(self):
        self._ensure_frontier()
        self.reader.reset_book(self.app.series.path if self.app.series else "", self.app.book)
        self._sel_key = None
        self._update_selection_state()

    def on_selection(self):
        self._update_selection_state()
        if self.fr is not None:
            self.refilter()

    def shutdown(self):
        self.table.close_edit(commit=True)

    def _load_if_needed(self):
        s = self.app.series
        if s is None or self._loaded_path == s.path:
            return
        self._loaded_path = s.path
        path, tag = s.path, s.tag
        self.busy = True

        def done(doc, path=path):
            self.busy = False
            if self._loaded_path != path:
                return
            self.doc = doc
            self.marks = model.gender_marks(doc.tag)
            self.table.marks = self.marks
            self.table.cols[1].label = model.target_label(self.app.series.target or doc.tag)
            self.entries = doc.entries()
            self.tab = "new"
            self.seg.set_value("new")
            self._set_default_order()
            self.refilter(keep=set())
            self.table.draw_head()
            if self.table.rows:
                self.table.select_index(0)
            self.reader.reset_book(path, self.app.book)
            self.flush_reader()
            self._ensure_frontier()

        def failed(exc, path=path):
            self.busy = False
            self._loaded_path = None
            message(self.ui, "The term base of this series cannot be read: %s" % exc)

        self.ui.worker.submit(lambda ctx: model.load_terms_task(ctx, path, tag), on_result=done, on_error=failed,
                              lane="bulk")

    # ------------------------------------------------------------- pane height
    def pane_limits(self):
        H = self.split.winfo_height()
        return self.reader.min_height(), max(self.reader.min_height(), int(H * 0.7))

    def _apply_frac(self):
        H = self.split.winfo_height()
        if H < 50:
            return
        self.set_pane_h(int(H * self.pane_frac), remember=False)

    def set_pane_h(self, h, remember=True):
        H = max(1, self.split.winfo_height())
        mn, mx = self.pane_limits()
        self.pane_h = h = max(mn, min(mx, int(h)))
        self.reader.configure(height=h)
        if remember:
            self.pane_frac = round(h / H, 3)
            self.ui.settings.set("pane_frac", self.pane_frac)
        return h

    def _grip_set_hover(self, v):
        self._grip_hover = v
        self._grip_draw()

    def _grip_draw(self):
        g = self.grip
        g.delete("all")
        W, H = g.winfo_width(), g.winfo_height()
        g.configure(bg=S2 if self._grip_hover else BG)
        x = W // 2
        w = self.cw * 4
        g.create_line(x - w, H // 2, x + w, H // 2, fill=FAINT if self._grip_hover else S3, width=2, capstyle="round")

    def _grip_press(self, e):
        self._grip_drag0 = (e.y_root, self.pane_h)

    def _grip_move(self, e):
        if self._grip_drag0 is None:
            return
        y0, h0 = self._grip_drag0
        self.set_pane_h(h0 - (e.y_root - y0))

    def _grip_toggle(self, e):
        self._grip_drag0 = None
        H = self.split.winfo_height()
        tall = int(H * 0.55)
        self.set_pane_h(int(H * self.pane_default) if self.pane_h >= tall - 4 else tall)
        return "break"

    # ------------------------------------------------------------- keys
    def _undo_key(self, e):
        if not self.winfo_ismapped() or isinstance(e.widget, tk.Entry):
            return None
        self.undo()
        return "break"

    def _focus_search(self):
        self.search.entry.focus_set()
        self.search.entry.select_range(0, "end")
        return "break"

    # ------------------------------------------------------------- filtering
    def _set_default_order(self):
        self.table.sort_key, self.table.sort_desc = termlogic.default_order(self.tab)

    def _sort_clicked(self, col):
        tb = self.table
        if col == tb.sort_key:
            tb.sort_desc = not tb.sort_desc
        else:
            tb.sort_key, tb.sort_desc = col, col == "count"
        self.refilter()

    def refilter(self, keep=None):
        tb = self.table
        sel_ids = self.sel_ids if self.in_selection else None
        self._recompute_next()
        if self.tab == "next":
            out = termlogic.arrange_next(self.next_rows, self.query, self.type_filter, tb.sort_key, tb.sort_desc)
        else:
            out = termlogic.arrange(self.entries, self.tab, self.query, self.type_filter, tb.sort_key,
                                    tb.sort_desc, sel_ids)
        keep = set(id(t) for t in tb.selected_rows()) if keep is None else keep
        tb.set_rows(out, keep, keep_view=True)
        self._update_chrome()

    def _tab_changed(self, v):
        self.tab = v
        self._set_default_order()
        self.refilter()
        self.table.draw_head()

    def _search_changed(self, s):
        self.query = s
        self.refilter()

    def _open_types(self):
        items = ["All types"] + TYPES
        b = self.type_btn
        root = self.ui.root
        x = b.winfo_rootx() - root.winfo_rootx()
        y = b.winfo_rooty() - root.winfo_rooty() + b.h + 4
        cur = self.type_filter or "All types"

        def pick(item, nxt):
            self.type_filter = None if item == "All types" else item
            self.type_btn.set_text(item + "  ▾")
            self.type_btn.pack_forget()
            self.type_btn.pack(side="right")
            self.refilter()
            self.table.body.focus_set()
        self.ui.popup.show(root, x - self.cw * 6, y, self.cw * 22, items, cur, pick,
                           on_cancel=lambda: self.table.body.focus_set(), openers=(self.type_btn,))

    # ------------------------------------------------------------- selection filter
    def _update_selection_state(self):
        sel = self.app.selection
        self.sel_btn.set_enabled(bool(sel))
        if not sel and self.in_selection:
            self.in_selection = False
            self.sel_btn.set_on(False)
            self.refilter()
        elif self.in_selection:
            self._compute_selection_ids()

    def _toggle_selection(self):
        if not self.app.selection:
            return
        self.in_selection = not self.in_selection
        self.sel_btn.set_on(self.in_selection)
        if self.in_selection:
            self._compute_selection_ids()
        else:
            self.refilter()

    def _compute_selection_ids(self):
        sel, doc, s = self.app.selection, self.doc, self.app.series
        if doc is None or s is None or not sel:
            return
        key = (sel.signature, len(doc.base))
        if key == self._sel_key and self.sel_ids is not None:
            self.refilter()
            return
        if self._sel_token:
            self._sel_token.cancel()

        def done(ids, key=key):
            self._sel_key = key
            self.sel_ids = ids
            if self.in_selection:
                self.refilter()

        self._sel_token = self.ui.worker.submit(
            lambda ctx: model.terms_in_selection_task(ctx, doc, s.path, sel.book, list(sel.indices)),
            on_result=done, lane="search")

    def _invalidate_selection(self):
        self._sel_key = None
        if self.in_selection:
            self._compute_selection_ids()

    # ------------------------------------------------------------- actions
    def _snapshot(self):
        tb = self.table
        sel = tb.selected_rows()
        pre = min(tb.sel) if tb.sel else (tb.cursor or 0)
        return sel, pre, {id(t): tb.index_of(t) for t in sel}

    def _settle(self, acted, pre, old, force_flash=False):
        tb = self.table
        here = [t for t in acted if tb.index_of(t) is not None]
        if here:
            moved = force_flash or any(old.get(id(t)) != tb.index_of(t) for t in here)
            tb.select_rows(here, flash=moved)
        elif tb.rows:
            tb.select_index(min(pre, len(tb.rows) - 1))
        else:
            tb.select_index(0)

    def _apply(self, entry, field, value) -> bool:
        if self.doc is None or self.busy:
            return False
        if getattr(entry, "cand", False):
            value = str(value).strip()
            if field != "tr" or not value:
                return False
            self.doc.add_confirmed(entry.source, value, entry.count, termlogic.first_seen(entry))
            self._virt.pop(entry.source.lower(), None)
            self.entries = self.doc.entries()
            return True
        if field == "same_as":
            if field not in entry.questions:
                return False
            self.doc.answer_same_as(entry, value)
            return True
        return self.doc.set_field(entry, field, value)

    def _edited(self, entry):
        tb = self.table
        old = {id(entry): tb.index_of(entry)}
        pre = tb.index_of(entry) or 0
        self.refilter(keep=set())
        self._settle([entry], pre, old)

    def toggle_confirm(self):
        if self.doc is None or self.busy:
            return
        sel, pre, old = self._snapshot()
        if not sel:
            return
        sel = [t for t in sel if not getattr(t, "cand", False)]
        if not sel:
            return
        if all(t.status == "confirmed" and not t.questions for t in sel):
            self.doc.unconfirm(sel)
        else:
            self.doc.confirm([t for t in sel if t.status != "confirmed" or t.questions])
        self.refilter(keep=set())
        self._settle(sel, pre, old)

    def confirm_all(self):
        if self.doc is None or self.busy or self.tab not in ("new", "next"):
            return
        rows = [t for t in self.table.rows if t.status == "new" and not t.questions and not getattr(t, "cand", False)]
        if not rows:
            return
        self.doc.confirm(rows)
        self.refilter(keep=set())
        if self.table.rows:
            self.table.select_index(0)
        self.table.body.focus_set()

    def delete(self):
        if self.doc is None or self.busy:
            return
        sel, pre, old = self._snapshot()
        if not sel:
            return
        if any(getattr(t, "cand", False) for t in sel):
            self.dismiss_candidates()
            return
        self.trash = self.doc.delete(sel)
        self.entries = self.doc.entries()
        self._invalidate_selection()
        self.refilter(keep=set())
        self._settle([], pre, old)
        self.table.body.focus_set()
        self._show_undo()

    def _show_undo(self):
        self.undo_btn.pack_forget()
        self.undo_btn.pack(side="left", padx=(self.gap // 2, 0))
        if self._undo_job is not None:
            self.after_cancel(self._undo_job)
        self._undo_job = self.after(6000, self._hide_undo)

    def _hide_undo(self):
        self._undo_job = None
        self.undo_btn.pack_forget()
        self.trash = []
        self.dismissed = []

    def undo(self):
        if self.dismissed and self.fr is not None:
            for text in self.dismissed:
                self.fr.restore(text)
            self.dismissed = []
            if self._undo_job is not None:
                self.after_cancel(self._undo_job)
            self._hide_undo()
            self.refilter(keep=set())
            return
        if not self.trash or self.doc is None:
            return
        back = self.doc.restore(self.trash)
        self.trash = []
        if self._undo_job is not None:
            self.after_cancel(self._undo_job)
        self._hide_undo()
        self.entries = self.doc.entries()
        self._invalidate_selection()
        self.refilter(keep=set())
        self._settle(back, 0, {}, force_flash=True)

    def merge(self, sel=None):
        sel = sel or self.table.selected_rows()
        if len(sel) < 2 or self.doc is None or self.busy:
            return
        tb = self.table
        pre = min(tb.sel) if tb.sel else 0
        keep = self.doc.merge(sel[0], sel[1:])
        self.entries = self.doc.entries()
        self._invalidate_selection()
        self.refilter(keep=set())
        self._settle([keep], pre, {}, force_flash=True)
        self.table.body.focus_set()

    def merge_with(self, entry, x, y):
        if self.doc is None:
            return
        cands = self.doc.similar(entry)
        if not cands:
            return
        keys = [str(i) for i in range(len(cands))]
        labels = {k: c.source for k, c in zip(keys, cands)}

        def pick(k, nxt):
            self.merge([entry, cands[int(k)]])
        self.ui.pick.show(self.ui.root, x, y, self.cw * 30, keys, keys[0], pick, labels=labels,
                          on_cancel=lambda: self.table.body.focus_set())

    # ------------------------------------------------------------- import / export
    def import_glossary(self):
        if self.doc is None or self.busy:
            return
        files = self.ui.dialogs.open_json_files()
        if not files:
            return
        doc = self.doc
        self.busy = True

        def done(rep):
            self.busy = False
            self.entries = doc.entries()
            self.last_import = rep
            self._invalidate_selection()
            self.tab = "questions" if rep.conflicts else "new"
            self.seg.set_value(self.tab)
            self._set_default_order()
            self.refilter(keep=set())
            self.table.draw_head()
            if self.table.rows:
                self.table.select_index(0)

        def failed(exc):
            self.busy = False
            message(self.ui, "The glossary could not be imported: %s" % exc)

        self.ui.worker.submit(lambda ctx: doc.import_files(files), on_result=done, on_error=failed, lane="bulk")

    def export_base(self):
        if self.doc is None:
            return
        name = "terms-%s.json" % (self.app.series.name if self.app.series else "base")
        path = self.ui.dialogs.save_json(name)
        if not path:
            return
        doc = self.doc

        def failed(exc):
            message(self.ui, "The term base could not be saved: %s" % exc)

        self.ui.worker.submit(lambda ctx: doc.export_file(path), on_error=failed, lane="bulk")

    # ------------------------------------------------------------- right-click menu
    def _context_menu(self, xr, yr, x, y):
        tb = self.table
        sel = tb.selected_rows()
        t = tb.cursor_row()
        if not sel or t is None or self.doc is None:
            return
        items, labels = [], {}
        if any(getattr(s, "cand", False) for s in sel):
            items, labels = ["dismiss", "edit", "copy"], {"dismiss": "Not a term", "edit": "Edit", "copy": "Copy"}
            self._ctx_pick(tb, items, labels, sel, t, xr, yr, x, y)
            return
        for field, cands in t.questions.items():
            k = "keep:" + field
            value = {"gender": self.marks.get(t.gender, "?"), "tr": t.tr, "same_as": t.same_as or "no alias"}[field]
            items.append(k)
            labels[k] = 'Keep "%s"' % (value if len(value) < 22 else value[:20] + "…")
        confirmed = all(s.status == "confirmed" and not s.questions for s in sel)
        items.append("unconfirm" if confirmed else "confirm")
        labels["unconfirm"] = "Move to New"
        labels["confirm"] = "Confirm"
        items.append("edit")
        labels["edit"] = "Edit"
        items.append("merge" if len(sel) >= 2 else "mergewith")
        labels["merge"] = "Merge"
        labels["mergewith"] = "Merge with…"
        items += ["copy", "delete"]
        labels["copy"] = "Copy"
        labels["delete"] = "Delete"
        self._ctx_pick(tb, items, labels, sel, t, xr, yr, x, y)

    def _ctx_pick(self, tb, items, labels, sel, t, xr, yr, x, y):
        root = self.ui.root
        bx = tb.body.winfo_rootx() - root.winfo_rootx() + x
        by = tb.body.winfo_rooty() - root.winfo_rooty() + y
        self.ctx_items = list(items)

        def pick(k, nxt):
            tb.body.focus_set()
            if k == "dismiss":
                self.dismiss_candidates()
            elif k.startswith("keep:"):
                sel0, pre, old = self._snapshot()
                self.doc.keep(sel0, k[5:])
                self.refilter(keep=set())
                self._settle(sel0, pre, old)
            elif k == "confirm" or k == "unconfirm":
                self.toggle_confirm()
            elif k == "edit":
                tb._activate()
            elif k == "merge":
                self.merge()
            elif k == "mergewith":
                self.merge_with(t, bx, by)
            elif k == "copy":
                tb.copy_rows()
            elif k == "delete":
                self.delete()
        self.ui.menu.show(root, bx, by, self.cw * 22, items, items[0], pick, labels=labels,
                          on_cancel=lambda: tb.body.focus_set())

    # ------------------------------------------------------------- chrome
    def _cursor_changed(self, entry):
        if self._reader_job is not None:
            self.after_cancel(self._reader_job)
        self._reader_job = self.after(30, self.flush_reader)

    def flush_reader(self):
        if self._reader_job is not None:
            self.after_cancel(self._reader_job)
            self._reader_job = None
        t = self.table.cursor_row()
        if t is None:
            self.reader.show(None, "", False)
        else:
            self.reader.show(t, termlogic.meta_line(t, self.marks), "gender" in t.questions)

    def _update_chrome(self):
        c = termlogic.counts(self.entries)
        nq = c["questions"]
        n = self.next_n
        hot = bool(n)
        items = [("new", "New", c["new"]), ("known", "Known", c["known"]),
                 ("questions", "Questions", nq, nq > 0 and not hot)]
        if self.fr is not None:
            items.insert(0, ("next", "Next", n, hot, self.next_extra if self.next_extra else None))
        self.seg.set_items(items, self.tab)
        self.not_btn.set_enabled(any(getattr(t, "cand", False) for t in self.table.selected_rows()))
        n = len(self.table.sel)
        self.merge_btn.set_enabled(n >= 2 and not self.busy)
        self.del_btn.set_enabled(n >= 1 and not self.busy)
        self.confirm_btn.set_enabled(self.tab in ("new", "next") and not self.busy and any(
            t.status == "new" and not t.questions and not getattr(t, "cand", False) for t in self.table.rows))
        self.import_btn.set_enabled(self.doc is not None and not self.busy)
        self.export_btn.set_enabled(self.doc is not None)

    def _key_press(self, e):
        """N = Not a term, on any keyboard layout (the virtual key code, as for the clipboard keys)."""
        if (e.keycode == 78 or e.keysym in ("n", "N")) and not (e.state & 0x5):
            self.dismiss_candidates()
            return "break"
        return None

    # ------------------------------------------------------------- the frontier (Next)
    def scope(self) -> list:
        """Chapters whose unreviewed terms are listed: the selection, else the chapters of the unfinished job."""
        sel = self.app.selection
        if sel and sel.book == self.app.book:
            return list(sel.indices)
        tr = self.app.steps.get("translate")
        if tr is not None and tr.view.unfinished and tr.view.book == self.app.book:
            return list(tr.view.chapters)
        return []

    def show_next(self) -> None:
        """Open on the Next filter (from the Terms chip of the Translate step)."""
        self.tab = "next"
        self._set_default_order()
        self.seg.set_value("next")
        if self.doc is not None:
            self.refilter(keep=set())
            self.table.draw_head()

    def _ensure_frontier(self, force: bool = False) -> None:
        s, book = self.app.series, self.app.book
        if self.doc is None or s is None or not book:
            return
        key = (s.path, book)
        if self.fr is not None and self._fr_key == key and not force:
            return
        self._cancel_scan()
        self.fr = model.make_frontier(self.doc, s.path, book)
        self._fr_key = key
        self._start_scan(force)

    def _cancel_scan(self) -> None:
        if self._scan_token is not None:
            self._scan_token.cancel()
        self._scan_token = None
        self.scanning = False
        self.scanbar_update()

    def _start_scan(self, force: bool = False) -> None:
        fr = self.fr
        self.scanning, self.scan_frac = True, 0.0
        self.scanbar_update()

        def item(it):
            if fr is self.fr:
                self.scan_frac = it[0] / max(1, it[1])
                self.scanbar_update()

        def done(_r):
            if fr is self.fr:
                self.scanning = False
                self.scanbar_update()
                self.refilter(keep=set())

        def failed(exc):
            if fr is self.fr:
                self.scanning = False
                self.scanbar_update()

        self._scan_token = self.ui.worker.submit(lambda ctx: model.frontier_scan_task(ctx, fr, force),
                                                 on_item=item, on_result=done, on_error=failed, lane="frontier")

    def scanbar_update(self) -> None:
        bar = self.scanbar
        if not self.scanning:
            if bar.winfo_ismapped():
                bar.pack_forget()
            return
        if not bar.winfo_ismapped():
            bar.pack(fill="x", pady=(0, self.gap // 2), before=self.split)
        bar.delete("all")
        w, h = max(1, bar.winfo_width()), int(bar.cget("height"))
        bar.create_rectangle(0, 0, w, h, fill="#1c1c1c", outline="")
        bar.create_rectangle(0, 0, int(w * self.scan_frac), h, fill="#7d7d7d", outline="")

    def _recompute_next(self) -> None:
        """Cheap: the answer is derived from the cached scan; no book is read."""
        if self.doc is None or not model.frontier_ready(self.fr):
            self.next_rows, self.next_n, self.next_extra = [], None, 0
            return
        rows = []
        blocking = 0
        for it in model.next_items(self.fr, self.scope()):
            if it.candidate:
                key = it.text.lower()
                e = self._virt.get(key)
                if e is None:
                    e = self._virt[key] = model.new_candidate(it.text, it.count, it.first)
                e.count = it.count
                e.seen = {it.first}
                e.suggest = not it.blocking
            else:
                e = self.doc.base.exact(it.text)
                if e is None:
                    continue
            blocking += 1 if it.blocking else 0
            rows.append(e)
        self.next_rows, self.next_n, self.next_extra = rows, blocking, len(rows) - blocking

    def dismiss_candidates(self):
        """Not a term: the selected mined names never hold back translation again."""
        if self.doc is None or self.fr is None or self.busy:
            return
        sel, pre, old = self._snapshot()
        cands = [t for t in sel if getattr(t, "cand", False)]
        if not cands:
            return
        done = [t.source for t in cands if self.fr.dismiss(t.source)]
        for t in cands:
            self._virt.pop(t.source.lower(), None)
        self.dismissed = done
        self.refilter(keep=set())
        self._settle([], pre, old)
        self.table.body.focus_set()
        if done:
            self._show_undo()
