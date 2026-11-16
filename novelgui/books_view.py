"""Step 1: series and books, the chapter list with its translation state, and the chapter selection."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path

from . import chapterlogic as cl
from . import model, platform, selection
from .dialog import AddBookDialog, message
from .step import Step
from .theme import ACCENT, BG, BRIGHT, DIM, FAINT, S2, S3, S4, TEXT
from .tooltip import attach_tip, facts
from .vtable import Col, VTable
from .widgets import Field, Pill, Segmented

TRACK = "#1c1c1c"
BAR_PART = "#7d7d7d"
BAR_FULL = "#d0d0d0"

STATE_WORDS = {"none": "not translated", "partly": "partly translated", "translated": "translated",
               "failed": "has failed blocks", "toc": "contents page", "unknown": "not counted yet"}


class SeriesTable(VTable):
    def __init__(self, master, ui):
        super().__init__(master, ui, [Col("name", "Series", None, sortable=False),
                                      Col("tag", "Language", 6, sortable=False)], header=False, resizable=False)
        self.current = None

    def draw_cells(self, c, row, cols, y, mid):
        x, w = cols["name"]
        on = self.current is not None and row.path == self.current
        c.create_text(x + self.pad, y + mid, text=self.fit(row.name, w - 2 * self.pad), anchor="w", font=self.font,
                      fill=BRIGHT if on else TEXT)
        x, w = cols["tag"]
        c.create_text(x + w - self.pad, y + mid, text=row.tag, anchor="e", font=self.font, fill=DIM)

    def tip_body(self, e):
        i = self.row_at(e.y)
        if i is None:
            return None
        s = self.rows[i]
        books = len(s.books)
        return ("%s, translated into %s." % (s.name, s.target.partition(":")[2] or s.tag),
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
        sel = self.hover is not None and self.rows[self.hover] is row
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

        self.chooser = tk.Frame(self, bg=BG)
        self.choose_btn = Pill(self.chooser, "Library folder", self.choose_library, ui.font, kind="accent")
        self.choose_btn.place(relx=0.5, rely=0.45, anchor="center")

        self.main = tk.Frame(self, bg=BG)
        left = tk.Frame(self.main, bg=BG)
        left.pack(side="left", fill="y", padx=(0, self.gap))
        self.series_table = SeriesTable(left, ui)
        self.series_table.configure(width=ui.cw * 34)
        self.series_table.pack(fill="both", expand=True)
        self.series_table.on_cursor = self._series_picked
        self.series_table.wire_tips()
        lb = tk.Frame(left, bg=BG)
        lb.pack(fill="x", pady=(self.gap, 0))
        self.add_btn = Pill(lb, "Add book", self.add_book, ui.font)
        self.add_btn.pack(side="left")
        self.lib_btn = Pill(lb, "Library folder", self.choose_library, ui.font, kind="dim")
        self.lib_btn.pack(side="right")
        attach_tip(self.add_btn, ui.tip, lambda e: "Add an EPUB file as a new series or as another volume of the "
                   "selected series. The file is copied into the series folder.")
        attach_tip(self.lib_btn, ui.tip, lambda e: ("Change the folder that holds the series. Every series is a "
                                                    "sub-folder of it.", [("Now", self._lib_name())]))

        right = tk.Frame(self.main, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        top = tk.Frame(right, bg=BG)
        top.pack(fill="x", pady=(0, self.gap))
        self.book_seg = Segmented(top, ui.font, self._book_picked)
        self.range_caption = tk.Label(top, text="Chapters", bg=BG, fg=DIM, font=ui.font)
        self.range_caption.pack(side="left", padx=(0, self.gap // 2))
        self.range_field = Field(top, ui.font, on_commit=self._range_typed, width=ui.cw * 22)
        self.range_field.pack(side="left")
        self.range_label = tk.Label(top, text="", bg=BG, fg=DIM, font=ui.font, anchor="w")
        self.range_label.pack(side="left", padx=(self.gap, 0))
        attach_tip(self.range_field, ui.tip, lambda e: (
            "Type the chapter numbers as they are printed in the titles, for example 2729-2783, and press Enter. "
            "When a number is missing or repeats in the book, it is taken as the No. of the list instead.",
            [("Format", "a-b, or a, b, c-d"), ("Counts", "title numbers"), ("Fallback", "position")]))
        self.table = ChapterTable(right, ui)
        self.table.pack(fill="both", expand=True)
        self.table.on_changed = self._table_changed
        self.table.on_view = self._viewed
        self.table.wire_tips()
        self.table.on_context = None
        foot = tk.Frame(right, bg=BG)
        foot.pack(fill="x", pady=(self.gap, 0))
        self.export_btn = Pill(foot, "Export", self.export, ui.font)
        self.export_btn.pack(side="right")
        self.export_btn.set_enabled(False)
        self.mode_seg = Segmented(foot, ui.font, self._mode_picked)
        modes = [(k, label, None) for k, label in model.EXPORT_MODES]
        saved = ui.settings.get("export_mode")
        self.export_mode = saved if saved in dict(model.EXPORT_MODES) else "single"
        self.mode_seg.set_items(modes, self.export_mode)
        self.mode_seg.pack(side="right", padx=(0, self.gap // 2))
        self.result = tk.Label(foot, text="", bg=BG, fg=DIM, font=ui.font, anchor="w", cursor="arrow")
        self.result.pack(side="left")
        self.skipped_note = tk.Label(foot, text="", bg=BG, fg=DIM, font=ui.font, anchor="w")
        self.skipped_note.pack(side="left", padx=(self.gap, 0))
        self.outcome = None
        self.exporting = False
        self.result.bind("<Button-1>", lambda e: self._open_out())
        attach_tip(self.result, ui.tip, lambda e: self._result_tip())
        attach_tip(self.mode_seg, ui.tip, lambda e: (
            "Translation replaces the original text. Bilingual puts the translation next to each original paragraph.",
            [("Remembered", "yes")]))
        attach_tip(self.export_btn, ui.tip, lambda e: (
            "Write the selected, fully translated chapters to an EPUB file. Chapters that are not fully "
            "translated are left out. It also works while a translation runs.",
            [("Needs", "selected chapters"), ("Skips", "untranslated chapters"), ("Folder", "out, in the series")]))
        self.status_ok = False
        self._last_view = (-1, -1)

    # ------------------------------------------------------------- life
    def _lib_name(self) -> str:
        return str(self.app.library or "")

    def on_show(self):
        if not self.app.library:
            self.main.pack_forget()
            self.chooser.pack(fill="both", expand=True)
            self.choose_btn.focus_set()
            return
        self.chooser.pack_forget()
        self.main.pack(fill="both", expand=True)
        if not self.series_list and not self.loading_series:
            self.reload_series()
        elif self.app.book:
            self.start_scan()   # logs may have changed since the step was last shown
        self.table.body.focus_set()

    def choose_library(self):
        path = self.ui.dialogs.choose_folder(str(self.app.library or ""))
        if not path:
            return
        self.app.set_library(path)
        self.series_list = []
        self.on_show()

    # ------------------------------------------------------------- series
    def reload_series(self, select_path: str | None = None):
        self.loading_series = True
        lib = self.app.library

        def done(items):
            self.loading_series = False
            self.series_list = items
            want = select_path or (self.app.series.path if self.app.series else self.ui.settings.get("series"))
            self.series_table.set_rows(items)
            pick = next((s for s in items if s.path == want), None)
            if pick is None and items and not self.app.series:
                pick = None
            if pick is not None:
                self.series_table.select_rows([pick])
            else:
                self._series_picked(self.series_table.cursor_row())
        self.ui.worker.submit(lambda ctx: model.list_series_task(ctx, lib), on_result=done, lane="bulk")

    def _series_picked(self, info):
        if info is None:
            if self.app.series is not None and self.series_list:
                return
            self.app.set_series(None)
            self._clear_chapters()
            return
        if self.app.series is not None and self.app.series.path == info.path:
            # same series: books may have changed (a volume was added)
            self.app.series = info
            self._books_for(info)
            return
        self.app.set_series(info)
        self.series_table.current = info.path
        self.series_table.draw()
        self._books_for(info)

    def _books_for(self, info):
        books = list(info.books)
        if len(books) > 1:
            self.book_seg.set_items([(b, _short(b, 24), None) for b in books],
                                    self.app.book if self.app.book in books else books[0])
            self.book_seg.pack(side="left", padx=(0, self.gap), before=self.range_caption)
        else:
            self.book_seg.pack_forget()
        want = self.app.book if self.app.book in books else (self.ui.settings.get("book") if
                                                            self.ui.settings.get("book") in books else None)
        pick = want or (books[0] if books else "")
        if pick:
            self.book_seg.set_value(pick)
            self.open_book(pick)
        else:
            self._clear_chapters()

    def _book_picked(self, name):
        self.open_book(name)

    # ------------------------------------------------------------- chapters
    def _clear_chapters(self):
        if self.scan_token:
            self.scan_token.cancel()
        self.infos = []
        self.app.set_book("", [])
        self.table.set_rows([])
        self.range_label.configure(text="")

    def open_book(self, name: str):
        if self.app.book == name and self.infos:
            self.start_scan()
            return
        self.app.set_book(name, [])
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
        elif kind == "rows":
            for new in payload:
                if new.index < len(self.infos):
                    self._merge(self.infos[new.index], new)
            if self.t_filled is None:
                self.t_filled = time.perf_counter() - self.t_open
            self.table.refresh()
            self.app.refresh_summary()

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
        if self.pending_range:
            text, self.pending_range = self.pending_range, ""
            self._range_typed(text)

    def _viewed(self, first, last):
        if (first, last) != self._last_view:
            self._last_view = (first, last)
            self.want.set(first, last)

    # ------------------------------------------------------------- selection
    def _table_changed(self):
        if self._suppress:
            return
        idx = self.table.selected_indices()
        self.app.set_selection(selection.make(self.app.book, idx))
        self.export_btn.set_enabled(model.EXPORT_READY and bool(idx) and not self.exporting)

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

    # ------------------------------------------------------------- add / export
    def add_book(self):
        if not self.app.library:
            return
        path = self.ui.dialogs.open_epub()
        if not path:
            return
        AddBookDialog(self.ui, self.app.library, path, self.app.series, self._add_confirmed)

    def _add_confirmed(self, res: dict):
        ui = self.ui

        def done(path):
            self.series_list = []
            self.reload_series(select_path=res.get("series") or path)

        if res["mode"] == "new":
            lib = self.app.library
            ui.worker.submit(lambda ctx: model.create_series_task(ctx, lib, res["name"], res["target"], res["epub"]),
                             on_result=done, on_error=self._add_failed, lane="bulk")
        else:
            sp = res["series"]
            ui.worker.submit(lambda ctx: model.add_book_task(ctx, sp, res["epub"]), on_result=lambda name: done(sp),
                             on_error=self._add_failed, lane="bulk")

    def _add_failed(self, exc):
        message(self.ui, "The book could not be added: %s" % exc)

    def _mode_picked(self, key):
        self.export_mode = key
        self.ui.settings.set("export_mode", key)

    def export(self):
        sel = self.app.selection
        if not sel or not self.app.series or self.exporting:
            return
        self.exporting = True
        self.export_btn.set_enabled(False)
        sp, book, idx, mode = self.app.series.path, sel.book, list(sel.indices), self.export_mode

        def done(out):
            self.exporting = False
            self._table_changed()
            self._show_outcome(out)

        def failed(exc):
            self.exporting = False
            self._table_changed()
            message(self.ui, "The export failed: %s" % exc)

        self.ui.worker.submit(lambda ctx: model.export_task(ctx, sp, book, idx, mode), on_result=done,
                              on_error=failed, lane="bulk")

    def _show_outcome(self, out):
        self.outcome = out
        if out.nothing:
            self.result.configure(text="Nothing translated in the selection", fg=DIM, cursor="arrow")
            self.skipped_note.configure(text="")
            return
        self.result.configure(text=out.name, fg=TEXT, cursor="hand2", font=self.ui.font)
        n = len(out.skipped)
        self.skipped_note.configure(text="%d skipped" % n if n else "")

    def _result_tip(self):
        out = self.outcome
        if out is None:
            return None
        if out.nothing:
            return ("No selected chapter is fully translated, so no file was written.",
                    [("Detail", out.detail[:60] or "-")])
        return ("Click to open the folder with the file.",
                [("Kept", "%d chapters" % out.kept), ("Skipped", "%d chapters" % len(out.skipped)),
                 ("Size", _size(out.size)), ("Problems", str(len(out.problems)))])

    def _open_out(self):
        out = self.outcome
        if out is not None and not out.nothing and out.folder:
            platform.open_folder(out.folder)


def _size(n: int) -> str:
    return "%.1f MB" % (n / 1e6) if n >= 1e6 else "%d KB" % max(1, round(n / 1e3))


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"
