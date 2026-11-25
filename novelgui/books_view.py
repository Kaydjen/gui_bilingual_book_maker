"""Step 1: series and books, the chapter list with its translation state, and the chapter selection."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path

from . import accent, addbook, libraryops, libraryrules as rules, model, platform, selection, tips
from . import chapterlogic as cl
from .dialog import AddBookDialog, RenameDialog, confirm, message
from .step import Step
from .theme import ACCENT, BG, BRIGHT, DIM, FAINT, S2, S3, S4, TEXT
from .tooltip import attach_tip, facts
from .vtable import Col, VTable
from .widgets import DotsButton, Field, Pill, Segmented

TRACK = "#1c1c1c"
BAR_PART = "#7d7d7d"
BAR_FULL = "#d0d0d0"

STATE_WORDS = {"none": "not translated", "partly": "partly translated", "translated": "translated",
               "failed": "has failed blocks", "toc": "contents page", "unknown": "not counted yet"}


class SeriesTable(VTable):
    """The series of the library. The `...` of the hovered or selected row opens the series actions (4.2); a
    series that cannot be read is dim with a `!`."""

    def __init__(self, master, ui):
        super().__init__(master, ui, [Col("name", "Series", None, sortable=False),
                                      Col("tag", "Language", 6, sortable=False),
                                      Col("act", "", 3, "e", sortable=False)], header=False, resizable=False)
        self.current = None
        self.on_actions = None          # (row, x_root, y_root) when the `...` of a row is clicked

    def draw_cells(self, c, row, cols, y, mid):
        x, w = cols["name"]
        on = self.current is not None and row.path == self.current
        broken = bool(row.broken)
        c.create_text(x + self.pad, y + mid, text=self.fit(row.name, w - 2 * self.pad), anchor="w", font=self.font,
                      fill=FAINT if broken else (BRIGHT if on else TEXT))
        x, w = cols["tag"]
        c.create_text(x + w - self.pad, y + mid, text="!" if broken else (row.tag if model.series_language(row) else ""), anchor="e", font=self.font,
                      fill=DIM)
        if on or (self.hover is not None and self.rows[self.hover] is row):
            x, w = cols["act"]
            r = max(1.5, self.rh * 0.06)
            cx0 = x + w / 2
            for k in (-1, 0, 1):
                cx = cx0 + k * self.rh * 0.22
                c.create_oval(cx - r, y + mid - r, cx + r, y + mid + r, fill=BRIGHT if on else DIM, outline="")

    def after_click(self, e, i, ctrl, shift):
        if self.col_at(e.x) == "act" and self.on_actions and not (ctrl or shift):
            self.on_actions(self.rows[i], e.x_root, e.y_root)

    def tip_body(self, e):
        i = self.row_at(e.y)
        if i is None:
            return None
        s = self.rows[i]
        if self.col_at(e.x) == "act":
            return tips.SERIES_ACTIONS
        if s.broken:
            return tips.BROKEN_SERIES % s.broken
        books = len(s.books)
        lang = model.series_language(s)
        if lang is None:
            return (tips.SERIES_NO_LANGUAGE, [("Books", str(books)), ("Folder", Path(s.path).name)])
        return ("%s, translated into %s." % (s.name, lang.partition(":")[2] or s.tag),
                [("Language tag", s.tag), ("Books", str(books)), ("Folder", Path(s.path).name)])


class ChapterTable(VTable):
    def __init__(self, master, ui):
        super().__init__(master, ui, [Col("no", "No.", 7, "e", sortable=False),
                                      Col("title", "Title", None, sortable=False),
                                      Col("state", "State", 20, sortable=False)], resizable=False)

    def selectable(self, row) -> bool:
        return row.is_toc is not True

    def copy_text(self, rows) -> str:
        return "\n".join("%d\t%s" % (r.index, r.title or "") for r in rows)

    def draw_cells(self, c, row, cols, y, mid):
        toc = row.is_toc is True
        x, w = cols["no"]
        c.create_text(x + w - self.pad, y + mid, text=str(cl.display_no(row.index)), anchor="e", font=self.font,
                      fill=FAINT if toc else DIM)
        x, w = cols["title"]
        if row.title:
            c.create_text(x + self.pad, y + mid, text=self.fit(row.title, w - 2 * self.pad), anchor="w",
                          font=self.font, fill=FAINT if toc else TEXT)
        x, w = cols["state"]
        st = row.state
        if st.kind in ("unknown", "toc", "none"):
            return
        bx0, bx1 = x + self.pad, x + w - self.pad
        bh = max(4, int(self.rh * 0.2))
        y0 = y + mid - bh / 2
        sel = self.hover is not None and 0 <= self.hover < len(self.rows) and self.rows[self.hover] is row
        c.create_rectangle(bx0, y0, bx1, y0 + bh, fill=S4 if (sel or self.index_of(row) in self.sel) else TRACK,
                           outline="")
        span = bx1 - bx0
        dw = int(span * st.fraction)
        if st.kind == "translated":
            dw = span
        if dw > 0:
            c.create_rectangle(bx0, y0, bx0 + dw, y0 + bh, fill=BAR_FULL if st.kind == "translated" else BAR_PART,
                               outline="")
        if st.failed:
            fw = max(3, int(span * st.failed_fraction))
            c.create_rectangle(bx0 + dw, y0, min(bx1, bx0 + dw + fw), y0 + bh, fill=ACCENT, outline="")

    def tip_body(self, e):
        i = self.row_at(e.y)
        if i is None:
            return None
        row = self.rows[i]
        col = self.col_at(e.x)
        if col == "state":
            st = row.state
            if st.kind == "unknown":
                return None
            if st.kind == "toc":
                return "A contents page: it only lists links, so it is never translated or selected."
            text = {
                "none": "No block of this chapter is translated yet.",
                "partly": "Some blocks of this chapter are translated.",
                "translated": "Every block of this chapter is translated.",
                "failed": "Some blocks of this chapter failed and need another try.",
            }.get(st.kind, "")
            return (text, [("Translated", "%d of %d blocks" % (st.done, st.total)), ("Failed", str(st.failed)),
                           ("Comes from", "translation log"), ("You can edit", "no")])
        if col == "title" and row.title and self.fit(row.title, self.col_x()["title"][1] - 2 * self.pad) != row.title:
            return row.title
        return None

    def tip_head(self, e):
        c = self.col_at(e.x)
        names = ("Comes from", "You can edit")
        if c == "no":
            return ("The position of the chapter in the book file, counting from 1. A chapter is identified by "
                    "its position; the number printed in its title may differ.", facts(names, ("program", "no")))
        if c == "title":
            return ("The chapter's title as the book names it. It is shown for orientation only.",
                    facts(names, ("book file", "no")))
        if c == "state":
            return ("How much of the chapter is translated: the bar fills as blocks are translated, a red mark "
                    "at its end shows blocks that failed.", facts(names, ("translation logs", "no")))
        return None


class BooksStep(Step):
    key = "books"
    label = "Books"

    def __init__(self, master, app):
        super().__init__(master, app)
        ui = self.ui
        self.ls = ui.ls
        self.gap = int(ui.ls * 0.8)
        self.series_list: list = []
        self.infos: list = []
        self.scan_token = None
        self.want = model.Want()
        self.scan_info: dict = {}
        self.t_open = 0.0
        self.t_skeleton = None
        self.t_filled = None
        self.pending_range = ""
        self.range_note = ""
        self.loading_series = False
        self._suppress = False
        self._sel_book = None           # the volume whose selection the table holds now (None while it loads)
        self._want_volume = ""          # a volume to open when the series list is next filled
        self._want_select = None
        self._add_files: list = []      # files still to offer as books, one panel each
        self._menu_reasons: dict = {}   # popup item -> why it is dim

        # ---- first start: no library yet (2.1)
        self.chooser = tk.Frame(self, bg=BG)
        box = tk.Frame(self.chooser, bg=BG)
        box.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(box, text="Where to keep your books and translations?", bg=BG, fg=TEXT, font=ui.font).pack(
            anchor="w", pady=(0, self.gap // 2))
        prow = tk.Frame(box, bg=BG)
        prow.pack(fill="x")
        self.path_field = Field(prow, ui.font, on_submit=lambda s: self.create_library(), width=ui.cw * 52)
        self.path_field.pack(side="left", fill="x", expand=True)
        self.choose_btn = Pill(prow, "Choose…", self._choose_into_field, ui.font, kind="dim")
        self.choose_btn.pack(side="left", padx=(self.gap // 2, 0))
        self.create_btn = Pill(box, "Create", self.create_library, ui.font, kind="accent")
        self.create_btn.pack(anchor="e", pady=(self.gap, 0))
        attach_tip(self.path_field.entry, ui.tip, lambda e: tips.FIRST_START_PATH)
        attach_tip(self.create_btn, ui.tip, lambda e: tips.FIRST_START_CREATE)

        self.main = tk.Frame(self, bg=BG)
        left = tk.Frame(self.main, bg=BG)
        left.pack(side="left", fill="y", padx=(0, self.gap))
        self.series_table = SeriesTable(left, ui)
        self.series_table.configure(width=ui.cw * 38)
        self.series_table.pack(fill="both", expand=True)
        self.series_table.on_cursor = self._series_picked
        self.series_table.on_actions = self._series_actions
        self.series_table.on_context = self._series_context
        self.series_table.wire_tips()
        lb = tk.Frame(left, bg=BG)
        lb.pack(fill="x", pady=(self.gap, 0))
        self.add_btn = Pill(lb, "Add book", self.add_book, ui.font)
        self.add_btn.pack(side="left")
        attach_tip(self.add_btn, ui.tip, lambda e: tips.ADDING if not self.add_btn.enabled else
                   "Add an EPUB file as a new series or as another volume of the selected series. The file is "
                   "copied into the series folder.")

        right = tk.Frame(self.main, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        top = tk.Frame(right, bg=BG)
        top.pack(fill="x", pady=(0, self.gap))
        self.top = top
        self.book_seg = Segmented(top, ui.font, self._book_picked)
        self.book_seg.bind("<Button-3>", self._volume_context, add="+")
        self.vol_dots = DotsButton(top, int(ui.ls * 1.25), self._volume_dots)
        attach_tip(self.vol_dots, ui.tip, lambda e: tips.VOLUME_ACTIONS)
        self.range_caption = tk.Label(top, text="Chapters", bg=BG, fg=DIM, font=ui.font)
        self.range_caption.pack(side="left", padx=(0, self.gap // 2))
        self.range_field = Field(top, ui.font, on_commit=self._range_typed, width=ui.cw * 22)
        self.range_field.pack(side="left")
        self.range_label = tk.Label(top, text="", bg=BG, fg=DIM, font=ui.font, anchor="w")
        self.range_label.pack(side="left", padx=(self.gap, 0))
        attach_tip(self.range_field, ui.tip, lambda e: tips.CHAPTERS_FIELD)
        self.table = ChapterTable(right, ui)
        self.table.pack(fill="both", expand=True)
        self.table.on_changed = self._table_changed
        self.table.on_view = self._viewed
        self.table.wire_tips()
        self.table.on_context = None
        attach_tip(ui.menu, ui.tip, self._menu_tip)
        self.status_ok = False
        self._last_view = (-1, -1)

    # ------------------------------------------------------------- life
    def on_show(self):
        if not self.app.library:
            self.main.pack_forget()
            self.chooser.pack(fill="both", expand=True)
            if not self.path_field.get():
                self.path_field.set(str(rules.default_library_path(Path.home())))
            self.create_btn.focus_set()
            return
        self.chooser.pack_forget()
        self.main.pack(fill="both", expand=True)
        if not self.series_list and not self.loading_series:
            self.reload_series()
        elif self.app.book:
            self.start_scan()   # logs may have changed since the step was last shown
        self.table.body.focus_set()

    def ensure_loaded(self) -> None:
        """Read the series of the library without showing this step (the app starts on another screen)."""
        if self.app.library and not self.series_list and not self.loading_series:
            self.reload_series()

    def library_changed(self, select_path: str | None = None) -> None:
        """The app took another folder as the library: show it."""
        self.series_list = []
        self.infos = []
        self._sel_book = None
        if self.scan_token:
            self.scan_token.cancel()
        self.series_table.set_rows([])
        self.table.set_rows([])
        self._want_select = select_path
        self.on_show()
        self._refresh_accent()

    # ---- first start
    def _choose_into_field(self):
        start = rules.chooser_start(self.app.library, Path.home())
        path = self.ui.dialogs.choose_folder(start)
        if path:
            self.path_field.set(path)
            self.create_btn.focus_set()

    def create_library(self):
        text = self.path_field.get().strip()
        if text:
            self.app.use_library_folder(text)

    def choose_library(self):
        """Another folder for the library (the settings `Change` does the same)."""
        self.app.change_library()

    # ------------------------------------------------------------- series
    def reload_series(self, select_path: str | None = None, after=None):
        self.loading_series = True
        lib = self.app.library
        self.app.loadline.start("series")
        select_path = select_path or self._want_select
        self._want_select = None

        def finish():
            self.loading_series = False
            self.app.loadline.stop("series")

        def done(items):
            finish()
            self.series_list = items
            want = select_path or (self.app.series.path if self.app.series else self.ui.settings.get("series"))
            self.series_table.set_rows(items)
            pick = next((s for s in items if s.path == want), None)
            if pick is not None:
                self.series_table.select_rows([pick])
            else:
                self._series_picked(self.series_table.cursor_row())
            self._refresh_accent()
            if after is not None:
                after()

        def failed(exc):
            finish()
            why = rules.explain_oserror(exc) if isinstance(exc, OSError) else str(exc)
            message(self.ui, "The library could not be read: %s." % why)
        self.ui.worker.submit(lambda ctx: model.list_series_task(ctx, lib), on_result=done, on_error=failed,
                              lane="bulk")

    def open_series_path(self, path: str) -> bool:
        """Show the series with this folder in the list (a click on the job state in the header)."""
        info = next((s for s in self.series_list if s.path == path and not s.broken), None)
        if info is None:
            return False
        if self.app.series is None or self.app.series.path != path:
            self.series_table.select_rows([info])
        return True

    def replace_series(self, info) -> None:
        """The same series with new facts (its language was chosen): swap the row in place, so nothing is
        reloaded and the selection stays."""
        for lst in {id(self.series_list): self.series_list, id(self.series_table.rows): self.series_table.rows}.values():
            for i, r in enumerate(lst):
                if r.path == info.path:
                    self.series_table.pos.pop(id(r), None)
                    lst[i] = info
                    self.series_table.pos[id(info)] = i
        self.series_table.draw()

    def _refresh_accent(self):
        """`Add book` is red only while the library or the selected series has no book (10.2); the one-red
        priority decides (accent.py)."""
        empty = not self.series_list or (self.app.series is not None and not self.app.series.books)
        red = accent.gets_accent("add_book", accent.Facts(), "add_book" if empty else "")
        kind = "accent" if red else "plain"
        if self.add_btn.kind != kind:
            self.add_btn.kind = kind
            self.add_btn.draw()

    def _hide_volume_controls(self):
        self.book_seg.pack_forget()
        self.vol_dots.pack_forget()

    def _series_picked(self, info):
        if info is None:
            if self.app.series is not None and self.series_list:
                return
            self.app.set_series(None)
            self._hide_volume_controls()
            self._clear_chapters()
            self._refresh_accent()
            return
        if info.broken:
            self.app.set_series(None)
            self.series_table.current = info.path
            self.series_table.draw()
            self._hide_volume_controls()
            self._clear_chapters()
            self._refresh_accent()
            return
        if self.app.series is not None and self.app.series.path == info.path:
            # same series: books may have changed (a volume was added)
            self.app.series = info
            self._books_for(info)
            self._refresh_accent()
            return
        self.app.set_series(info)
        self.series_table.current = info.path
        self.series_table.draw()
        self._books_for(info)
        self._refresh_accent()

    def _books_for(self, info):
        books = list(info.books)
        if len(books) > 1:
            self.book_seg.set_items([(b, _short(info.label_of(b), 24), None) for b in books],
                                    self.app.book if self.app.book in books else books[0])
            self.book_seg.pack(side="left", padx=(0, self.gap // 2), before=self.range_caption)
        else:
            self.book_seg.pack_forget()
        if books:
            self.vol_dots.pack(side="left", padx=(0, self.gap), before=self.range_caption)
        else:
            self.vol_dots.pack_forget()
        ws = self.ui.winstate
        want = self._want_volume if self._want_volume in books else ""
        self._want_volume = ""
        if not want:
            for cand in (self.app.book, ws.last_volume(info.path), self.ui.settings.get("book")):
                if cand and cand in books:
                    want = cand
                    break
        pick = want or (books[0] if books else "")
        if pick:
            self.book_seg.set_value(pick)
            self.open_book(pick)
        else:
            self._clear_chapters()

    def _book_picked(self, name):
        self.open_book(name)

    # ---- the `...` menus
    def _menu_tip(self, e):
        m = self.ui.menu
        if not m.open:
            return None
        i = m._row(e.y)
        if i is None:
            return None
        return self._menu_reasons.get(m.items[i])

    def _series_actions(self, info, xr, yr):
        self._series_menu(info, xr, yr)

    def _series_context(self, xr, yr, x, y):
        info = self.series_table.cursor_row()
        if info is not None:
            self._series_menu(info, xr, yr)

    def _popup_xy(self, xr, yr):
        root = self.ui.root
        return xr - root.winfo_rootx(), yr - root.winfo_rooty()

    def _series_menu(self, info, xr, yr):
        reason = self.app.series_block_reason(info.path)
        items = ["series.open", "series.delete"] if info.broken else ["series.rename", "series.open",
                                                                       "series.delete"]
        labels = {"series.rename": "Rename", "series.open": "Open folder", "series.delete": "Delete"}
        disabled = []
        self._menu_reasons = {}
        hints = {}
        if reason:
            disabled.append("series.delete")
            self._menu_reasons["series.delete"] = tips.CANNOT_NOW % reason
            hints["series.delete"] = "in use"

        def pick(k, nxt):
            self.series_table.body.focus_set()
            if k == "series.rename":
                self.rename_series(info)
            elif k == "series.open":
                platform.open_folder(info.path)
            elif k == "series.delete":
                self.delete_series(info)
        bx, by = self._popup_xy(xr, yr)
        self.ui.menu.show(self.ui.root, bx, by, self.ui.cw * 22, items, items[0], pick, labels=labels, hints=hints,
                          disabled=disabled, on_cancel=lambda: self.series_table.body.focus_set())

    def _volume_dots(self, e):
        self._volume_menu(self.app.book, e.x_root, e.y_root)

    def _volume_context(self, e):
        i = self.book_seg.seg_at(e.x)
        if i is None:
            return
        stem = self.book_seg.items[i][0]
        if stem != self.app.book:
            self.book_seg.set_value(stem)
            self._book_picked(stem)
        self._volume_menu(stem, e.x_root, e.y_root)

    def _volume_menu(self, stem, xr, yr):
        info = self.app.series
        if info is None or not stem:
            return
        reason = self.app.series_block_reason(info.path, stem)
        items = ["volume.rename", "volume.remove"]
        labels = {"volume.rename": "Rename", "volume.remove": "Remove volume"}
        disabled, hints = [], {}
        self._menu_reasons = {}
        if reason:
            disabled.append("volume.remove")
            self._menu_reasons["volume.remove"] = tips.CANNOT_NOW % reason
            hints["volume.remove"] = "in use"

        def pick(k, nxt):
            if k == "volume.rename":
                self.rename_volume(info, stem)
            elif k == "volume.remove":
                self.remove_volume(info, stem)
        bx, by = self._popup_xy(xr, yr)
        self.ui.menu.show(self.ui.root, bx, by, self.ui.cw * 22, items, items[0], pick, labels=labels, hints=hints,
                          disabled=disabled)

    # ---- rename
    def rename_series(self, info):
        others = [(s.path, s.name) for s in self.series_list]

        def check(text):
            return addbook.rename_problem(text, info.path, others)

        def done(text):
            if text == info.name:
                return
            self._run_op(lambda ctx: libraryops.rename_series(info.path, text),
                         lambda _: self.reload_series(select_path=info.path))
        RenameDialog(self.ui, "Series name", info.name, check, done)

    def rename_volume(self, info, stem):
        def check(text):
            return "" if len(text.strip()) <= 80 else "A label is at most 80 characters."

        def done(text):
            self._run_op(lambda ctx: libraryops.rename_volume(info.path, stem, text),
                         lambda _: self.reload_series(select_path=info.path))
        RenameDialog(self.ui, "Volume label", info.label_of(stem), check, done)

    def _run_op(self, fn, on_ok, series_path=None, volume=None, on_end=None):
        """Run a disk operation on the worker; an OpError (or any failure) opens a message panel. `on_end` runs
        when the work is over, however it ended."""
        key = (series_path, volume) if series_path else None
        if key:
            self.app.op_begin(*key)

        def end():
            if key:
                self.app.op_end(*key)
            if on_end:
                on_end()

        def ok(res):
            end()
            on_ok(res)

        def bad(exc):
            end()
            message(self.ui, str(exc) if isinstance(exc, libraryops.OpError) else
                    "The change could not be made: %s" % libraryops.reason(exc))
            self.reload_series(select_path=self.app.series.path if self.app.series else None)
        self.ui.worker.submit(fn, on_result=ok, on_error=bad, lane="bulk")

    # ---- delete and remove
    def delete_series(self, info):
        reason = self.app.series_block_reason(info.path)
        if reason:
            message(self.ui, tips.CANNOT_NOW % reason)
            return
        jv = model.job_view(info.path)
        lines = ['Delete the series "%s"?' % info.name,
                 "Its folder moves to .deleted in the library; nothing is erased."]
        if jv.unfinished:
            lines.append("Its unfinished translation job is discarded with it.")
        confirm(self.ui, "\n".join(lines), "Delete", lambda: self._do_delete_series(info),
                valid=lambda: any(s.path == info.path for s in self.series_list)
                and not self.app.series_block_reason(info.path))

    def _do_delete_series(self, info):
        lib = self.app.library
        if self.app.series is not None and self.app.series.path == info.path:
            self.app.set_series(None)
        self._clear_chapters()
        self.series_table.current = None

        def moved(dest):
            self.app.series_gone(info.path)
            self.ui.winstate.forget_series(info.path)
            if self.ui.settings.get("series") == info.path:
                self.ui.settings.set("series", None)
            self.reload_series()

        def go():
            self._run_op(lambda ctx: libraryops.delete_series(lib, info.path), moved, info.path, None)
        self.app.release_series(info.path, go)

    def remove_volume(self, info, stem):
        reason = self.app.series_block_reason(info.path, stem)
        if reason:
            message(self.ui, tips.CANNOT_NOW % reason)
            return
        jv = model.job_view(info.path)
        lines = ['Remove the volume "%s" from "%s"?' % (info.label_of(stem), info.name),
                 "Its book file, chapter logs and working files move to .deleted in the library; nothing is "
                 "erased. The finished books in out/ stay."]
        if jv.unfinished and jv.book == stem:
            lines.append("Its unfinished translation job is discarded with it.")
        confirm(self.ui, "\n".join(lines), "Remove", lambda: self._do_remove_volume(info, stem, jv.book),
                valid=lambda: any(s.path == info.path and stem in s.books for s in self.series_list)
                and not self.app.series_block_reason(info.path, stem))

    def _do_remove_volume(self, info, stem, job_book):
        lib = self.app.library
        if self.app.book == stem:
            self._clear_chapters()

        def moved(dest):
            self.app.series_gone(info.path, stem)
            self.ui.winstate.clear_volume_selection(info.path, stem)
            if self.ui.settings.get("book") == stem:
                self.ui.settings.set("book", None)
            self.reload_series(select_path=info.path)

        def go():
            self._run_op(lambda ctx: libraryops.remove_volume(lib, info.path, stem, job_book), moved,
                         info.path, stem)
        self.app.release_series(info.path, go)

    # ------------------------------------------------------------- chapters
    def _clear_chapters(self):
        if self.scan_token:
            self.scan_token.cancel()
        self.infos = []
        self._sel_book = None
        self.app.set_book("", [])
        self.table.set_rows([])
        self.range_label.configure(text="")

    def open_book(self, name: str):
        if self.app.book == name and self.infos:
            self.start_scan()
            return
        self._sel_book = None
        self.app.set_book(name, [])
        if self.app.series is not None:
            self.ui.winstate.set_last_volume(self.app.series.path, name)
        self.infos = []
        self.table.set_rows([])
        self.range_label.configure(text="")
        self.range_field.set("")
        self.pending_range = ""
        self.start_scan()

    def start_scan(self):
        if self.scan_token:
            self.scan_token.cancel()
        series = self.app.series
        if series is None or not self.app.book:
            return
        book = self.app.book
        self.t_open = time.perf_counter()
        self.t_skeleton = self.t_filled = None
        self.want.set(*self.table.visible_range() if self.table.rows else (0, 60))
        token = self.ui.worker.submit(
            lambda ctx: model.scan_chapters_task(ctx, series.path, book, self.want),
            on_item=lambda item, b=book: self._scan_item(b, item),
            on_result=lambda res, b=book: self._scan_done(b, res),
            on_error=self._scan_failed, lane="bulk")
        self.scan_token = token

    def _scan_failed(self, exc):
        message(self.ui, "This book cannot be read: %s" % exc)

    def _scan_item(self, book, item):
        if book != self.app.book:
            return
        kind, payload = item
        if kind == "skeleton":
            if self.infos and len(self.infos) == len(payload):
                # a rescan of the same book: keep the rows and the selection, refresh values as they come
                for new in payload:
                    old = self.infos[new.index]
                    if old.blocks is None:
                        self._merge(old, new)
                return
            self.infos = payload
            self.table.set_rows(self.infos)
            self.t_skeleton = time.perf_counter() - self.t_open
            if payload and payload[0].title is not None:
                self.t_filled = self.t_skeleton
            self.app.set_book(book, self.infos)
            self._restore_selection(book)
        elif kind == "rows":
            for new in payload:
                if new.index < len(self.infos):
                    self._merge(self.infos[new.index], new)
            if self.t_filled is None:
                self.t_filled = time.perf_counter() - self.t_open
            self.table.refresh()
            self.app.refresh_summary()
            self.app.infos_updated()

    def _restore_selection(self, book):
        """The chapters chosen on this volume last time (4.5)."""
        series = self.app.series
        spans = self.ui.winstate.volume_selection(series.path, book) if series is not None else None
        self._sel_book = None
        if spans:
            n = len(self.infos)
            idx = [i for a, b in spans for i in range(max(0, a), min(n - 1, b) + 1)]
            self.table.set_selection(idx)
        self._sel_book = book
        self._show_count()

    @staticmethod
    def _merge(old, new):
        old.title, old.is_toc, old.blocks = new.title, new.is_toc, new.blocks
        old.done, old.failed, old.log_sig = new.done, new.failed, new.log_sig

    def _scan_done(self, book, res):
        if book != self.app.book:
            return
        self.scan_info = dict(res, elapsed=time.perf_counter() - self.t_open)
        self.table.refresh()
        self.app.refresh_summary()
        self.app.infos_updated()
        if self.pending_range:
            text, self.pending_range = self.pending_range, ""
            self._range_typed(text)

    def _viewed(self, first, last):
        if (first, last) != self._last_view:
            self._last_view = (first, last)
            self.want.set(first, last)

    # ------------------------------------------------------------- selection
    def _show_count(self):
        n = len(self.table.selected_indices())
        self.range_label.configure(text="" if not n else "%d %s" % (n, "chapter" if n == 1 else "chapters"))

    def _table_changed(self):
        if self._suppress:
            return
        idx = self.table.selected_indices()
        self.app.set_selection(selection.make(self.app.book, idx))
        if self._sel_book and self._sel_book == self.app.book and self.app.series is not None:
            self.ui.winstate.set_volume_selection(self.app.series.path, self.app.book,
                                                  selection.make(self.app.book, idx).spans())
            self._show_count()

    def _range_typed(self, text: str) -> bool:
        """Apply a typed range. False when it cannot be read: the field goes back to its previous text."""
        text = text.strip()
        if not text:
            return True
        if not self.infos or any(i.title is None for i in self.infos):
            self.pending_range = text      # titles are still being read; applied when they are
            return True
        numbers = [i.number for i in self.infos]
        toc = [i.is_toc is True for i in self.infos]
        res = cl.select_by_numbers(text, numbers, toc)
        if res.error:
            self.range_label.configure(text=res.error)
            return False
        self.table.set_selection(res.indices)
        self.range_label.configure(text=res.note)
        self.range_note = res.note
        return True

    def select_all_chapters(self):
        self.table.select_all()

    # ------------------------------------------------------------- add
    def add_book(self):
        if not self.app.library or not self.add_btn.enabled:
            return
        path = self.ui.dialogs.open_epub()
        if not path:
            return
        self._open_add_panel(path)

    def add_files(self, files):
        """Offer several loose files as books, one Add book panel after the other."""
        self._add_files = [str(f) for f in files]
        self._next_file()

    def _next_file(self):
        if not self._add_files:
            return
        self._open_add_panel(self._add_files.pop(0), then=self._next_file)

    def _open_add_panel(self, path, then=None):
        series = self.app.series
        folders = []
        try:
            folders = [p.name for p in Path(self.app.library).iterdir() if p.is_dir()]
        except OSError:
            pass
        used = (folders, [s.name for s in self.series_list])

        def closed(dlg):
            if then is not None and not dlg.confirmed:
                self.after_idle(then)
        AddBookDialog(self.ui, self.app.library, path, series, lambda res: self._add_confirmed(res, then),
                      used=used, on_closed=closed)

    def _add_confirmed(self, res: dict, then=None):
        lib = self.app.library
        series_path = res.get("series")
        self._adding(True)

        def done(r):
            self._want_volume = r.volume
            if r.kind == "duplicate":
                self.reload_series(select_path=r.series)
                message(self.ui, "This book is already in this series (%s)." % r.volume, on_close=then)
            else:
                self.reload_series(select_path=r.series, after=then)

        self._run_op(lambda ctx: libraryops.add_book(lib, res["epub"], res["mode"], series_path, res.get("name", "")),
                     done, series_path, None, on_end=lambda: self._adding(False))

    def _adding(self, on: bool) -> None:
        """While a book is copied in, its button shows `Adding…` and the thin line moves (10.1)."""
        self.add_btn.set_text("Adding…" if on else "Add book")
        self.add_btn.set_enabled(not on)
        (self.app.loadline.start if on else self.app.loadline.stop)("add")


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"
