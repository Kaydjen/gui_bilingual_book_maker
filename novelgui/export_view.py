"""Step 4: Export, the end of the path (window_spec 8, 10.5). Ready pieces of the current volume, a `from - to`
pair, two buttons, and a result panel. It never reads or changes the chapter selection of Books."""

from __future__ import annotations

import tkinter as tk

from . import accent, langrules, model, pieces, platform, tips
from .dialog import Modal
from .step import Step
from .theme import ACCENT, BG, BRIGHT, DIM, FAINT, S1, S2, S3, TEXT
from .tooltip import attach_tip
from .widgets import Field, Pill


class PieceList(tk.Canvas):
    """The ready pieces, one per row: `2697-2750` and, when the run has problems, `53 of 54 · 1 problem` with the
    problem count as a link. A row click fills the pair."""

    def __init__(self, master, ui):
        super().__init__(master, bg=S1, highlightthickness=0, bd=0)
        self.ui = ui
        self.font = ui.font
        self.rh = int(ui.ls * 1.9)
        self.pad = int(ui.ls * 0.9)
        self.rows: list = []
        self.selected = None            # (first, last) positions of the piece the pair names
        self.hover = None
        self.y0 = 0
        self.links: list = []           # (x0, x1, row index)
        self.on_pick = None
        self.on_problem = None
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._click)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self._scroll(-1))
        self.bind("<Button-5>", lambda e: self._scroll(1))

    # ---- data
    def set_rows(self, rows, selected=None) -> None:
        self.rows = list(rows)
        self.selected = selected
        self._clamp()
        self.draw()

    def set_selected(self, selected) -> None:
        if selected != self.selected:
            self.selected = selected
            self.draw()

    def _max_y(self) -> int:
        return max(0, len(self.rows) * self.rh - self.winfo_height())

    def _clamp(self) -> None:
        self.y0 = max(0, min(self.y0, self._max_y()))

    def _scroll(self, n) -> None:
        self.y0 += n * self.rh
        self._clamp()
        self.draw()

    def _wheel(self, e) -> None:
        self._scroll(-1 if e.delta > 0 else 1)

    # ---- hit testing
    def row_at(self, y):
        i = (y + self.y0) // self.rh
        return int(i) if 0 <= i < len(self.rows) else None

    def link_at(self, x, y):
        i = self.row_at(y)
        if i is None:
            return None
        for a, b, k in self.links:
            if k == i and a <= x < b:
                return i
        return None

    def _set_hover(self, h) -> None:
        if h != self.hover:
            self.hover = h
            self.draw()

    def _motion(self, e) -> None:
        self._set_hover(self.row_at(e.y))

    def _click(self, e) -> None:
        i = self.row_at(e.y)
        if i is None:
            return
        if self.link_at(e.x, e.y) is not None and self.on_problem:
            self.on_problem(self.rows[i])
        elif self.on_pick:
            self.on_pick(self.rows[i])

    # ---- drawing
    def draw(self) -> None:
        self.delete("all")
        self.links = []
        f = self.font
        W, H = self.winfo_width(), self.winfo_height()
        first = max(0, self.y0 // self.rh)
        for i in range(first, len(self.rows)):
            y = i * self.rh - self.y0
            if y > H:
                break
            p = self.rows[i]
            on = self.selected == (p.first, p.last)
            if on:
                self.create_rectangle(0, y, W, y + self.rh, fill=S3, outline="")
            elif self.hover == i:
                self.create_rectangle(0, y, W, y + self.rh, fill=S2, outline="")
            mid = y + self.rh / 2
            x = self.pad
            self.create_text(x, mid, text=p.label, anchor="w", font=f, fill=BRIGHT if on else TEXT)
            x += f.measure(p.label) + self.pad
            if p.problems:
                lead = "%d of %d · " % (p.done, p.total)
                self.create_text(x, mid, text=lead, anchor="w", font=f, fill=DIM)
                x += f.measure(lead)
                link = "%d %s" % (p.problems, "problem" if p.problems == 1 else "problems")
                lw = f.measure(link)
                hot = self.hover == i
                self.create_text(x, mid, text=link, anchor="w", font=f, fill=TEXT if hot else DIM)
                self.create_line(x, mid + f.metrics("linespace") * 0.5, x + lw, mid + f.metrics("linespace") * 0.5,
                                 fill=TEXT if hot else FAINT)
                self.links.append((x, x + lw, i))
            else:
                txt = "%d %s" % (p.done, "chapter" if p.done == 1 else "chapters")
                self.create_text(x, mid, text=txt, anchor="w", font=f, fill=DIM)


class ResultPanel(Modal):
    """What an export did (8.5): the file, the numbers, `Show in folder`, `Close`; or why no file was written."""

    def __init__(self, ui, outcome=None, error: str = "", on_close=None):
        super().__init__(ui, on_close)
        self.outcome = outcome
        f = ui.font
        pad = self.pad
        self.left_label = None
        self.show_btn = None
        if error:
            head, lines = "The export failed.", [error]
        elif outcome is not None and outcome.nothing:
            head, lines = "No file was written.", ["No chapter of the range is fully translated yet."]
        else:
            head, lines = outcome.name, []
        tk.Label(self.body, text=head, bg=S2, fg=BRIGHT, font=ui.bold, anchor="w", justify="left",
                 wraplength=ui.cw * 60).pack(anchor="w", padx=pad, pady=(pad, int(pad * 0.4)))
        for t in lines:
            tk.Label(self.body, text=t, bg=S2, fg=TEXT, font=f, anchor="w", justify="left",
                     wraplength=ui.cw * 60).pack(anchor="w", padx=pad, pady=(0, int(pad * 0.4)))
        if outcome is not None and not outcome.nothing and not error:
            row = tk.Frame(self.body, bg=S2)
            row.pack(anchor="w", padx=pad, pady=(0, int(pad * 0.7)))
            kept, left, size = pieces.result_line(outcome.kept, len(outcome.skipped), outcome.size)
            tk.Label(row, text=kept, bg=S2, fg=TEXT, font=f).pack(side="left")
            if left:
                tk.Label(row, text=" · ", bg=S2, fg=DIM, font=f).pack(side="left")
                self.left_label = tk.Label(row, text=left, bg=S2, fg=ACCENT, font=f, cursor="arrow")
                self.left_label.pack(side="left")
                attach_tip(self.left_label, ui.tip, lambda e: self._left_tip())
            tk.Label(row, text=" · %s" % size, bg=S2, fg=TEXT, font=f).pack(side="left")
        btns = tk.Frame(self.body, bg=S2)
        btns.pack(fill="x", padx=pad, pady=(int(pad * 0.3), 0))
        close = Pill(btns, "Close", self.close, f, bg=S2)
        close.pack(side="right")
        if outcome is not None and not outcome.nothing and not error:
            self.show_btn = Pill(btns, "Show in folder", self._show, f, kind="dim", bg=S2)
            self.show_btn.pack(side="right", padx=(0, ui.ls // 2))
        self.close_btn = close
        self.show()
        close.focus_set()

    def _show(self) -> None:
        o = self.outcome
        if o is not None and o.path:
            platform.reveal_file(o.path)

    def _left_tip(self):
        sk = list(self.outcome.skipped)
        names = []
        for idx, title, missing in sk[:8]:
            names.append("%s (%d %s)" % ((title or "Chapter %d" % (idx + 1))[:40], missing,
                                         "block" if missing == 1 else "blocks"))
        if len(sk) > 8:
            names.append("and %d more" % (len(sk) - 8))
        return tips.EXPORT_LEFT_OUT[0] % "; ".join(names), tips.EXPORT_LEFT_OUT[1]


class ExportStep(Step):
    key = "export"
    label = "Export"

    def __init__(self, master, app):
        super().__init__(master, app)
        ui = self.ui
        self.gap = gap = int(ui.ls * 0.8)
        self.pieces: list = []
        self.exporting = ""             # "" or the mode being written
        self.last = None                # the last ExportOutcome that wrote a file
        self.src = langrules.FALLBACK   # source language of the volume (names of the second button)
        self._src_key = None
        self.panel = None

        self.list = PieceList(self, ui)
        self.list.pack(fill="both", expand=True)
        self.list.on_pick = self.pick_piece
        self.list.on_problem = self.open_problem
        attach_tip(self.list, ui.tip, self._list_tip)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", pady=(gap, 0))
        self.foot = foot
        self.single_btn = Pill(foot, "Export", lambda: self.run("single"), ui.font)
        self.both_btn = Pill(foot, "Export + Original", lambda: self.run("bilingual"), ui.font, kind="dim")
        self.both_btn.pack(side="right")
        self.single_btn.pack(side="right", padx=(0, gap // 2))
        self.to_field = Field(foot, ui.font, on_commit=self._pair_committed, on_change=lambda s: self._pair_changed(),
                              width=ui.cw * 9)
        self.dash = tk.Label(foot, text="-", bg=BG, fg=DIM, font=ui.font)
        self.from_field = Field(foot, ui.font, on_commit=self._pair_committed,
                                on_change=lambda s: self._pair_changed(), width=ui.cw * 9)
        self.from_field.pack(side="left")
        self.dash.pack(side="left", padx=(gap // 2, gap // 2))
        self.to_field.pack(side="left")
        self.last_line = tk.Label(foot, text="", bg=BG, fg=DIM, font=ui.font, anchor="w", cursor="arrow")
        self.last_line.pack(side="left", padx=(gap, 0))
        self.last_line.bind("<Button-1>", lambda e: self._reveal_last())
        attach_tip(self.from_field, ui.tip, lambda e: tips.EXPORT_FROM)
        attach_tip(self.to_field, ui.tip, lambda e: tips.EXPORT_TO)
        attach_tip(self.single_btn, ui.tip, lambda e: self._button_tip("single"))
        attach_tip(self.both_btn, ui.tip, lambda e: self._button_tip("bilingual"))
        attach_tip(self.last_line, ui.tip, lambda e: tips.EXPORT_LAST if self.last else None)
        self._update_buttons()

    # ------------------------------------------------------------- hooks
    def on_show(self) -> None:
        books = self.app.steps.get("books")
        if books is not None and self.app.book:
            books.start_scan()          # the logs may have changed since the volume was last read
        self._lookup_source()
        self.refresh()

    def on_hide(self) -> None:
        self.app.loadline.stop("export")

    def on_series(self) -> None:
        self.from_field.set("")
        self.to_field.set("")
        self.pieces = []
        self.last = None
        self.last_line.configure(text="", cursor="arrow")
        self._src_key = None
        self.refresh()

    def on_book(self) -> None:
        self.from_field.set("")
        self.to_field.set("")
        self.pieces = []
        self._src_key = None
        if self.winfo_ismapped():
            self._lookup_source()
        self.refresh()

    def on_language(self) -> None:
        self._update_buttons()

    def on_infos(self) -> None:
        """The chapter states of the volume changed (a scan batch, a running job). Nothing is computed while
        another step is shown: `on_show` reads the states then."""
        if self.winfo_ismapped():
            self.refresh()

    # ------------------------------------------------------------- the list
    def refresh(self) -> None:
        infos = self.app.infos or []
        self.pieces = pieces.compute(infos) if infos else []
        loading = bool(infos) and any(i.blocks is None for i in infos) and self.winfo_ismapped()
        (self.app.loadline.start if loading else self.app.loadline.stop)("export")
        if self.pieces and not self._pair_ok() and not self.from_field.get() and not self.to_field.get():
            p = self.pieces[0]
            self.from_field.set(str(p.first_no))
            self.to_field.set(str(p.last_no))
        self.list.set_rows(self.pieces, self._selected_piece())
        self._update_buttons()

    def _selected_piece(self):
        pair = self._pair()
        if pair is None:
            return None
        p = pieces.piece_at(self.pieces, *pair)
        return (p.first, p.last) if p is not None else None

    def pick_piece(self, p) -> None:
        self.from_field.set(str(p.first_no))
        self.to_field.set(str(p.last_no))
        self.list.set_selected((p.first, p.last))
        self._update_buttons()

    def open_problem(self, p) -> None:
        self.app.show_problems(p.problem_at[0] if p.problem_at else p.first)

    def _list_tip(self, e):
        i = self.list.row_at(e.y)
        if i is None:
            return None
        return tips.EXPORT_PROBLEM if self.list.link_at(e.x, e.y) is not None else tips.EXPORT_PIECE

    # ------------------------------------------------------------- the pair
    def _pair(self):
        a, b = pieces.parse_number(self.from_field.get()), pieces.parse_number(self.to_field.get())
        if a is None or b is None:
            return None
        return (a, b) if a <= b else (b, a)

    def _pair_ok(self) -> bool:
        return bool(self._resolve()[1])

    def _resolve(self):
        """(positions of the range, the ones that will be written)."""
        pair = self._pair()
        infos = self.app.infos or []
        if pair is None or not infos:
            return (), []
        pos, _by = pieces.positions_for(infos, *pair)
        return pos, pieces.kept_positions(infos, pos)

    def _pair_committed(self, text) -> bool:
        """A field accepts a number only (or nothing)."""
        t = (text or "").strip()
        return not t or pieces.parse_number(t) is not None

    def _pair_changed(self) -> None:
        self.list.set_selected(self._selected_piece())
        self._update_buttons()

    # ------------------------------------------------------------- buttons
    def _target_name(self) -> str:
        lang = self.app.series_language()
        return langrules.label(lang, model.TARGETS) if lang else ""

    def _blocked(self) -> str:
        """Why Export cannot run now ("" when it can)."""
        if self.app.series is None or not self.app.book:
            return tips.EXPORT_NEED_PAIR
        if self.exporting:
            return tips.EXPORT_RUNNING
        if self.app.language_pending():
            return tips.NEED_LANGUAGE
        if not self._pair_ok():
            return tips.EXPORT_NEED_PAIR
        return ""

    def _update_buttons(self) -> None:
        name = self._target_name()
        single = "Export %s" % name if name else "Export"
        both = "Export %s + %s" % (name, self.src.name) if name else "Export + %s" % self.src.name
        if self.exporting == "single":
            single = "Exporting…"
        elif self.exporting == "bilingual":
            both = "Exporting…"
        self.single_btn.set_text(single)
        self.both_btn.set_text(both)
        ok = not self._blocked()
        self.single_btn.set_enabled(ok)
        self.both_btn.set_enabled(ok)
        facts = accent.Facts(bool(self.app.keystore.keys), not self.app.language_pending(),
                             self.app.terms_first_blocked)
        panel_open = self.panel is not None and self.panel.is_open
        red = ok and not panel_open and accent.gets_accent("export", facts, "export")
        kind = "accent" if red else "plain"
        if self.single_btn.kind != kind:
            self.single_btn.kind = kind
            self.single_btn.draw()
        self.foot.update_idletasks()

    def _button_tip(self, mode):
        why = self._blocked()
        if why and why != tips.EXPORT_RUNNING:
            return why
        return tips.EXPORT_SINGLE if mode == "single" else tips.EXPORT_BILINGUAL

    # ------------------------------------------------------------- the source language of the volume
    def _lookup_source(self) -> None:
        s, book = self.app.series, self.app.book
        if s is None or not book:
            return
        key = (s.path, book)
        if key == self._src_key:
            return
        self._src_key = key

        def done(res, key=key):
            if key == self._src_key:
                self.src = res
                self._update_buttons()
        self.ui.worker.submit(lambda ctx: model.source_language(s.path, book), on_result=done, lane="bulk")

    # ------------------------------------------------------------- exporting
    def run(self, mode: str) -> None:
        if self._blocked():
            return
        s, book, infos = self.app.series, self.app.book, self.app.infos
        positions, kept = self._resolve()
        tag = langrules.split(self.app.series_language() or "")[0]
        a, b = (kept[0], kept[-1]) if kept else (positions[0], positions[-1])
        name = pieces.file_name(model.clean_name(s.name, 60, "series"), pieces.number_of(infos[a]),
                                pieces.number_of(infos[b]), tag, self.src.tag if mode == "bilingual" else "")
        sp = s.path
        self.exporting = mode
        self._update_buttons()
        self.app.op_begin(sp, book)

        def finish():
            self.app.op_end(sp, book)
            self.exporting = ""
            self._update_buttons()

        def done(out):
            finish()
            if not out.nothing:
                self.last = out
                self.last_line.configure(text=out.name, fg=TEXT, cursor="hand2")
            self.panel = ResultPanel(self.ui, out, on_close=self._update_buttons)
            self._update_buttons()

        def failed(exc):
            finish()
            self.panel = ResultPanel(self.ui, error=str(exc) or exc.__class__.__name__,
                                     on_close=self._update_buttons)
            self._update_buttons()

        self.ui.worker.submit(lambda ctx: model.export_piece_task(ctx, sp, book, list(positions), mode, name),
                              on_result=done, on_error=failed, lane="bulk")

    def _reveal_last(self) -> None:
        if self.last is not None and self.last.path:
            platform.reveal_file(self.last.path)
