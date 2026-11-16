"""The window: header with the step switch, the steps, and the state they share."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path

from . import busy
from . import chapterlogic as cl
from . import libraryrules as rules
from . import accent, header, langrules, model, platform, selection, tips
from .books_view import BooksStep
from .export_view import ExportStep
from .dialog import RenameDialog, confirm, message
from .loadline import LoadLine
from .applock import AppLock
from .pathbar import PathBar
from .runctl import RunControl
from .settings import Settings, api_base, data_dir
from .step import Step
from .keystore import KeyStore, PromptStore
from .settings_view import SettingsPanel, model_list
from .terms_view import TermsStep
from .translate_view import TranslateStep
from .theme import BG, BRIGHT, DIM, TEXT, Fonts, style_ttk
from .tooltip import attach_tip
from .ui import UI
from .widgets import install_clipboard

DEFAULT_TITLE = "Novel"


class Gear(tk.Canvas):
    """Icon-only control: a cog."""

    def __init__(self, master, size, command, bg=BG):
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.size, self.command, self.hover = size, command, False
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<ButtonRelease-1>", lambda e: self.command())
        self.draw()

    def _set(self, v):
        self.hover = v
        self.draw()

    def colour(self) -> str:
        """Brighter on hover, never darker than the background."""
        return BRIGHT if self.hover else DIM

    def draw(self):
        import math
        self.delete("all")
        c = self.size / 2
        fg = self.colour()
        r_out, r_in = c * 0.82, c * 0.56
        for k in range(8):
            a = k * math.pi / 4
            self.create_line(c + math.cos(a) * r_in, c + math.sin(a) * r_in, c + math.cos(a) * r_out,
                             c + math.sin(a) * r_out, fill=fg, width=max(2, int(c * 0.28)), capstyle="butt")
        self.create_oval(c - r_in, c - r_in, c + r_in, c + r_in, outline=fg, width=max(2, int(c * 0.2)))
        self.create_oval(c - c * 0.2, c - c * 0.2, c + c * 0.2, c + c * 0.2, fill=BG, outline="")


class App:
    def __init__(self, title: str = DEFAULT_TITLE, settings: Settings | None = None, scale=None):
        platform.enable_dpi()
        self.settings = settings or Settings()
        self.root = root = tk.Tk()
        root.withdraw()
        root.title(title)
        root.configure(bg=BG)
        self.fonts = Fonts(root, scale)
        style_ttk(root, self.fonts)
        install_clipboard(root)
        self.ui = ui = UI(root, self.settings, self.fonts)

        # state shared by the steps
        lib = self.settings.get("library")
        self.library: Path | None = Path(lib) if lib and Path(lib).is_dir() else None
        self.series = None          # model.SeriesInfo
        self.book = ""
        self.infos: list = []       # chapter infos of the current book (owned by the Books step)
        self.selection = selection.Selection()
        self.current = ""
        self.steps: dict[str, Step] = {}
        self.order: list[str] = []
        self.export_enabled = model.EXPORT_READY
        self.keystore = KeyStore(self.settings.folder)
        self.prompts = PromptStore(self.settings.folder)
        self.closing = False
        self.lock = None                # the one-window lock, held from main()
        self.runs = RunControl(self)    # the one place that starts, watches and stops translations
        self.panel = None
        self._lang_reasons: dict = {}   # item of the open language list -> why it is dim
        self.busy_ops: dict = {}    # (series path, volume or None) -> how many operations run on it now
        self._infos_job = None
        self.terms_n = None         # unreviewed terms of the selection that hold the job back (None = not known)
        self.terms_first_blocked = False    # the first chosen chapter has such a term: translation cannot start
        self.terms_blocked_at = None        # the first chosen chapter that has one (the job runs up to it)

        ls = self.fonts.ls
        pad_x, pad_y = int(ls * 1.1), int(ls * 0.9)
        outer = tk.Frame(root, bg=BG)
        outer.pack(fill="both", expand=True, padx=pad_x, pady=pad_y)
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, int(ls * 0.8)))
        self.head = head
        self.switch = PathBar(head, ui.font, self.path_clicked)
        self.switch.pack(side="left")
        self.gear = Gear(head, int(ls * 1.25), self.open_settings)
        self.gear.pack(side="right", padx=(pad_x, 0))
        attach_tip(self.gear, ui.tip, lambda e: "Settings: keys, models, pace, keep awake.")
        self.summary = tk.Label(head, text="", bg=BG, fg=DIM, font=ui.font, anchor="e")
        self.summary.pack(side="right")
        attach_tip(self.summary, ui.tip, lambda e: self._summary_tip())
        attach_tip(ui.pick, ui.tip, self._language_tip)
        attach_tip(self.switch, ui.tip, self._path_tip)
        # the context line: next to the path, or on a second row when the header is crowded (1.4)
        self.context = tk.Label(outer, text="", bg=BG, fg=DIM, font=ui.font, anchor="w", cursor="hand2")
        self.context.pack(in_=head, side="left", padx=(pad_x, 0), after=self.switch)
        self.context.bind("<Button-1>", lambda e: self.show_step("books"))
        self.context.bind("<Enter>", lambda e: self.context.configure(fg=TEXT))
        self.context.bind("<Leave>", lambda e: self.context.configure(fg=DIM))
        attach_tip(self.context, ui.tip, lambda e: tips.CONTEXT_LINE if self.context.cget("text") else None)
        self.head2 = tk.Frame(outer, bg=BG)
        self.context_row = 1
        self._context_text = ""
        head.bind("<Configure>", lambda e: self._layout_header())
        self.loadline = LoadLine(outer)
        self.loadline.pack(fill="x", pady=(0, int(ls * 0.4)))
        self.host = tk.Frame(outer, bg=BG)
        self.host.pack(fill="both", expand=True)

        self.register_step(BooksStep)
        self.register_step(TermsStep)
        self.register_step(TranslateStep)
        self.register_step(ExportStep)

        for i, key in enumerate(self.order, 1):
            root.bind("<Control-Key-%d>" % i, lambda e, k=key: self.show_step(k))
        root.bind("<Control-a>", self._ctrl_a)
        root.protocol("WM_DELETE_WINDOW", self.close)

        cw, ls = self.fonts.cw, self.fonts.ls
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(int(cw * 150), sw - 40), min(int(ls * 48), sh - 80)
        geo = self.settings.get("geometry")
        root.geometry(self._geometry(geo, w, h, sw, sh))
        root.minsize(int(cw * 100), int(ls * 28))
        platform.dark_titlebar(root)
        root.deiconify()
        root.update_idletasks()
        first = self.settings.get("step")
        self.show_step(first if first in self.steps and first != "translate" else "books")
        root.update()

    # ------------------------------------------------------------- steps
    def register_step(self, cls) -> Step:
        step = cls(self.host, self)
        self.steps[cls.key] = step
        self.order.append(cls.key)
        self.refresh_dot()
        return step

    def show_step(self, key: str) -> None:
        if key not in self.steps:
            return
        if self.current and self.current in self.steps:
            self.steps[self.current].on_hide()
            self.steps[self.current].pack_forget()
        self.current = key
        self.refresh_dot()
        self.steps[key].pack(fill="both", expand=True)
        self.steps[key].on_show()
        self.settings.set("step", key)

    # ------------------------------------------------------------- the header path (1.1, 1.2)
    def accent_facts(self, screen: str | None = None) -> accent.Facts:
        """What the one-red priority needs to know on `screen` (default: the visible one). An element that
        does not exist on a screen cannot hold the red there: `Add keys` and `To` live on Translate (and `To`
        in the Terms heading), so the keys fact counts only on Translate and the language fact on Translate
        and Terms."""
        screen = screen or self.current
        keys = bool(self.keystore.keys) or screen != "translate"
        lang = not self.language_pending() or screen not in ("translate", "terms")
        return accent.Facts(keys, lang, self.terms_first_blocked)

    def set_terms_state(self, n, first_blocked: bool, blocked_at=None) -> None:
        """The Terms step reports the unreviewed terms of the selection (None = not known), whether the
        first chosen chapter is blocked by them and which chapter is the first one that is (None = none)."""
        first_blocked = bool(first_blocked) and bool(n)
        blocked_at = blocked_at if n else None
        if n == self.terms_n and first_blocked == self.terms_first_blocked and blocked_at == self.terms_blocked_at:
            return
        self.terms_n, self.terms_first_blocked, self.terms_blocked_at = n, first_blocked, blocked_at
        self.refresh_path()
        tr = self.steps.get("translate")
        if tr is not None:
            tr.on_terms()
        exp = self.steps.get("export")
        if exp is not None:
            exp._update_buttons()
        terms = self.steps.get("terms")
        if terms is not None and hasattr(terms, "_update_chrome"):
            terms._update_chrome()

    def terms_red(self) -> bool:
        """`Terms N` of the path is the red of the screen: the first chosen chapter is blocked, nothing of a
        higher priority is open, and the screen has no element of its own for it (Translate has)."""
        if not self.terms_n or self.current == "translate":
            return False
        return accent.gets_accent(accent.TERMS, self.accent_facts())

    def translate_indicator(self):
        """What follows `Translate` in the path: (text or None, lit). The running job of any series as
        `> series . 62 %` with the queue count, else the reason a job or the queue waits (`Wait 09:01`, `Terms 12`,
        `Stopped`, `Failed`); tied to the job, never to the series shown."""
        text = self.runs.indicator()
        return (text or None), False

    def path_items(self) -> list:
        items = []
        for k in self.order:
            step = self.steps[k]
            if k == "terms":
                n = self.terms_n if self.terms_n else None
                items.append((k, step.label, n, bool(n) and self.terms_red()))
            elif k == "translate":
                text, lit = self.translate_indicator()
                items.append((k, step.label, text, lit, bool(text) and text.startswith("▶")))
            else:
                items.append((k, step.label, None, False))
        return items

    def refresh_path(self) -> None:
        self.switch.set_items(self.path_items(), self.current or None)
        self._layout_header()

    refresh_dot = refresh_path

    def _path_tip(self, e):
        i = self.switch.seg_at(e.x)
        if i is None:
            return None
        key = self.switch.items[i][0]
        if key == "books":
            return tips.PATH_BOOKS
        if key == "terms":
            n = self.terms_n
            if not n:
                return tips.PATH_TERMS
            why = tips.PATH_TERMS_RED if self.terms_first_blocked else tips.PATH_TERMS_DIM
            return tips.PATH_TERMS_N[0] % (n, why), tips.PATH_TERMS_N[1]
        if key == "translate":
            return self.indicator_tip() or tips.PATH_TRANSLATE
        return tips.PATH_EXPORT

    def path_clicked(self, key: str) -> None:
        """A click on the path. `Translate` with a job of another series running or waiting opens that series."""
        if key == "translate":
            path = self.runs.indicator_series()
            if path and (self.series is None or self.series.path != path):
                books = self.steps.get("books")
                if books is not None and books.open_series_path(path):
                    self.show_step("translate")
                    return
        self.show_step(key)

    def indicator_tip(self):
        """The tooltip of `Translate` while it carries a job state: series, volume, chapters, model, keys, pace."""
        runs = self.runs
        text = runs.indicator()
        if not text:
            return None
        series = runs.indicator_series()
        info = self.series_info(series) if series else None
        name = info.name if info is not None else "-"
        r = runs.run
        if r is not None and r.kind == "job":
            cfg = self.run_config()
            vol = info.label_of(r.book) if info is not None else r.book
            keys = len(cfg.keys)
            return tips.fill(tips.IND_RUNNING, name, vol, self.chapters_label(r.series, r.book, r.chapters),
                             (cfg.models or ["-"])[0], "%d, used in turn" % keys if keys else "none",
                             "%g a minute" % (cfg.pace or model.default_pace()))
        if text.startswith("Wait"):
            return tips.fill(tips.IND_WAIT, text[5:], name)
        if text.startswith("Terms"):
            return tips.fill(tips.IND_TERMS, name)
        if text.startswith("Failed"):
            return tips.fill(tips.IND_FAILED, name)
        if text.startswith("Queue"):
            return tips.fill(tips.IND_QUEUE, str(len(runs.queue)))
        return tips.fill(tips.IND_STOPPED, name)

    def chapters_label(self, series_path: str, book: str, chapters) -> str:
        """`2697-2750` for the chapters of a job: title numbers when that volume is open, else positions."""
        if self.series is not None and self.series.path == series_path and book == self.book and self.infos:
            return header.range_text(self.infos, chapters) or "-"
        spans = []
        for i in sorted(set(chapters)):
            if spans and spans[-1][1] == i - 1:
                spans[-1][1] = i
            else:
                spans.append([i, i])
        return ", ".join("%d" % (a + 1) if a == b else "%d-%d" % (a + 1, b + 1) for a, b in spans[:3]) or "-"

    def series_info(self, path: str):
        """The list entry of a series of the library, or None."""
        books = self.steps.get("books")
        for s in (books.series_list if books is not None else []):
            if s.path == path:
                return s
        return None

    # ------------------------------------------------------------- the run (stage 3 step 5)
    def runs_changed(self, starting: bool = False, ended=None, tick: bool = False) -> None:
        """The run, the wait or the queue changed (or the clock ticked while one is active)."""
        if self.closing:
            return
        self.refresh_path()
        tr = self.steps.get("translate")
        if tr is not None:
            tr.on_runs(starting, ended, tick)
        if not tick:
            exp = self.steps.get("export")
            if exp is not None and ended is not None:
                exp._update_buttons()

    def run_progress(self, run) -> None:
        """The chapters of a running job moved on: the chapter list of Books and the pieces of Export follow."""
        tr = self.steps.get("translate")
        if tr is not None:
            tr.on_progress(run)

    def series_gone(self, series_path: str, book: str | None = None) -> None:
        """A series was deleted or a volume removed: queue items of it go, a wait on it ends."""
        self.runs.series_gone(series_path, book)

    # ------------------------------------------------------------- the context line (1.3, 1.4)
    def context_text(self) -> str:
        info = self.series
        if info is None:
            return ""
        vol = info.label_of(self.book) if self.book else ""
        sel = self.selection
        chapters = header.chapters_text(self.infos, sel.indices) if sel and sel.book == self.book else ""
        lang = self.series_language()
        return header.context_line(info.name, vol, chapters, langrules.label(lang, model.TARGETS) if lang else "")

    def refresh_context(self) -> None:
        self._context_text = self.context_text()
        self._layout_header()

    def _layout_header(self) -> None:
        """Put the context line next to the path, or on a second row when the header cannot hold it."""
        if not hasattr(self, "context"):
            return
        f = self.ui.font
        text = self._context_text
        gap = int(self.fonts.ls * 1.1)
        avail = self.head.winfo_width()
        if avail <= 1:
            avail = self.root.winfo_width() - 2 * gap
        side = self.gear.size + self.summary.winfo_reqwidth() + 2 * gap
        ctx_w = f.measure(text) if text else 0
        second = header.crowded(self.switch.width_needed(), ctx_w, side, avail, gap)
        want = 2 if second else 1
        if want != self.context_row:
            self.context_row = want
            self.context.pack_forget()
            if want == 2:
                self.head2.pack(fill="x", after=self.head, pady=(0, int(self.fonts.ls * 0.5)))
                self.context.pack(in_=self.head2, side="left", padx=(gap // 2, 0))
            else:
                self.head2.pack_forget()
                self.context.pack(in_=self.head, side="left", padx=(gap, 0), after=self.switch)
        self.context.tkraise()          # it is packed into a frame that is not its parent: keep it on top
        room = (avail if want == 2 else max(60, avail - self.switch.width_needed() - side - 2 * gap)) - gap
        shown = self._fit(text, room)
        if self.context.cget("text") != shown:
            self.context.configure(text=shown)

    def _fit(self, text: str, width: int) -> str:
        f = self.ui.font
        if not text or f.measure(text) <= width:
            return text
        while text and f.measure(text + "…") > width:
            text = text[:-1]
        return text.rstrip(" ·") + "…"

    def infos_updated(self) -> None:
        """The chapter states of the open volume changed (a scan batch, a running job): steps that show them hear
        about it, at most about seven times a second (a scan of 4000 chapters sends many batches)."""
        if self._infos_job is None:
            self._infos_job = self.root.after(150, self._infos_now)

    def _infos_now(self) -> None:
        self._infos_job = None
        for st in self.steps.values():
            st.on_infos()
        self.refresh_context()

    def show_problems(self, position: int | None = None) -> None:
        """The `1 problem` link of Export: the problem list of Translate, landing on the first row of that chapter."""
        self.show_step("translate")
        tr = self.steps.get("translate")
        if tr is not None and hasattr(tr, "show_problem_at"):
            tr.show_problem_at(position)

    # ------------------------------------------------------------- settings, keys
    def models(self) -> list:
        return model_list(self.settings)

    def run_config(self):
        pace = self.settings.get("pace")
        try:
            pace = model.clean_pace(pace)
        except (ValueError, TypeError):
            pace = None
        return model.RunConfig(list(self.keystore.keys), self.models(), pace, api_base())

    def keys_changed(self) -> None:
        tr = self.steps.get("translate")
        if tr is not None:
            tr.refresh_all()

    def open_settings(self) -> None:
        if self.panel is not None and self.panel.is_open:
            return
        self.panel = SettingsPanel(self.ui, self, on_close=self.keys_changed)

    def show_terms_blockers(self) -> None:
        terms = self.steps.get("terms")
        if terms is not None and hasattr(terms, "show_next"):
            terms.show_next()
        self.show_step("terms")

    # ------------------------------------------------------------- shared state
    def set_library(self, path) -> None:
        self.library = Path(path)
        self.settings.set("library", str(path))
        self.set_series(None)

    # ------------------------------------------------------------- the library folder (2.2, 2.3, 13.7)
    def use_library_folder(self, path) -> bool:
        """Take a folder as the library by the rules of 2.2. A folder that cannot be written is refused with
        a message and the library stays as it was. Returns True when the library is now that folder."""
        path = Path(str(path)).expanduser()
        scan = rules.scan_folder(path)
        if scan.kind == "invalid":
            message(self.ui, "%s cannot be the library: it is a file or cannot be read. The library was not "
                    "changed." % path)
            return False
        _created, problem = rules.prepare_library(scan.library)
        if problem:
            message(self.ui, "The folder %s cannot be used as the library: %s. The library was not changed."
                    % (scan.library, problem))
            return False
        self.set_library(scan.library)
        books = self.steps.get("books")
        if scan.series is not None:
            self.settings.set("series", str(scan.series))
        if books is not None:
            books.library_changed(str(scan.series) if scan.series is not None else None)
        if self.current != "books":
            self.show_step("books")
        if scan.kind == "epubs" and books is not None:
            n = len(scan.epubs)
            confirm(self.ui, "This folder holds %d EPUB file%s. Add %s as books?" % (n, "" if n == 1 else "s",
                                                                                       "it" if n == 1 else "them"),
                    "Add", lambda: books.add_files(scan.epubs), no="Not now")
        return True

    def library_block_reason(self) -> str:
        """Why the library cannot be changed now ("" when it can): a translation runs or waits."""
        if self.runs.running or self.runs.sched.wait is not None:
            return "A translation is running or waiting for the daily quota. Stop it first."
        books = self.steps.get("books")
        views = []
        for s in (books.series_list if books is not None else []):
            if not s.broken:
                try:
                    views.append(model.job_view(s.path))
                except Exception:
                    pass
        return busy.library_change_reason(views)

    def queue_items(self) -> list:
        """The queued translations; changing the library clears them."""
        return self.runs.queue_items()

    def clear_queue(self) -> None:
        self.runs.clear_queue()

    def change_library(self, on_done=None) -> bool:
        """The settings `Change`: choose a folder and use it. Disabled while a translation runs or waits; with
        queued items it asks first, since the queue is cleared (13.7)."""
        reason = self.library_block_reason()
        if reason:
            message(self.ui, reason)
            return False
        path = self.ui.dialogs.choose_folder(rules.chooser_start(self.library, Path.home()))
        if not path:
            return False

        def go():
            self.clear_queue()
            if self.use_library_folder(path) and on_done:
                on_done()
        n = len(self.queue_items())
        if n:
            confirm(self.ui, "The queue holds %d item%s. Changing the library clears it." % (n, "" if n == 1 else "s"),
                    "Change", go)
        else:
            go()
        return True

    # ------------------------------------------------------------- what is going on with a series (4.4, 13.6)
    def op_begin(self, series_path: str, volume=None) -> None:
        k = (series_path, volume)
        self.busy_ops[k] = self.busy_ops.get(k, 0) + 1

    def op_end(self, series_path: str, volume=None) -> None:
        k = (series_path, volume)
        n = self.busy_ops.get(k, 0) - 1
        if n > 0:
            self.busy_ops[k] = n
        else:
            self.busy_ops.pop(k, None)

    def extra_block_reasons(self, series_path: str, volume=None) -> list:
        """Further reasons a series cannot be deleted or changed now: this window starts or runs a job of it (the
        record may not say so yet). A queued item does not hold a deletion back: it leaves the queue."""
        r = self.runs.run
        if r is not None and r.series == series_path and r.kind == "job" and (
                volume is None or not r.book or r.book == volume):
            return [busy.RUNNING]
        return []

    def series_block_reason(self, series_path: str, volume=None) -> str:
        """Empty when the series (or one volume) may be deleted or removed now, else why not."""
        try:
            view = model.job_view(series_path)
        except Exception:
            view = None
        return busy.block_reason(view, list(self.busy_ops), series_path, volume,
                                 self.extra_block_reasons(series_path, volume))

    # ------------------------------------------------------------- the target language (window 3.x)
    def series_language(self):
        """`tag:Name` of the current series, None while it is not chosen (or there is no series)."""
        return model.series_language(self.series)

    def language_pending(self) -> bool:
        """A series is open and its language is not chosen yet."""
        return self.series is not None and self.series_language() is None

    def language_block_reason(self, series_path: str, view=None) -> str:
        """Why the language of the series cannot change now: it runs, waits (the queue of a later step comes in
        through extra_block_reasons). `view` is the JobView the caller already holds."""
        if view is None:
            try:
                view = model.job_view(series_path)
            except Exception:
                view = None
        extra = self.extra_block_reasons(series_path)
        if self.runs.queued(series_path) is not None:
            extra.append("This series is waiting in the queue; the language is read when it starts.")
        return busy.language_reason(view, extra)

    def language_menu(self, xr: int, yr: int, openers=()) -> None:
        """The `To` list at screen position (xr, yr): Russian, Ukrainian, Polish, Other.... Once a block is
        translated or a term confirmed, every language but the current one is dim, with the reason."""
        info = self.series
        if info is None or info.broken:
            return
        why = self.language_block_reason(info.path, getattr(self.steps.get("translate"), "view", None))
        if why:
            message(self.ui, tips.TO_BUSY % why)
            return
        locked = langrules.lock_reason(*model.language_lock(info.path))
        current = self.series_language()
        items, disabled = langrules.menu(current, model.TARGETS, bool(locked))
        labels = {t: langrules.label(t, model.TARGETS) for t in items if t != langrules.OTHER}
        hints = {}      # a dim row and its tooltip say it all (no explanation words in the list)
        self._lang_reasons = {i: locked for i in disabled}
        self._lang_items = list(items)
        path = info.path
        root = self.root

        def pick(item, nxt):
            self._lang_reasons = {}
            if item == langrules.OTHER:
                self._other_language(path)
            else:
                self.choose_language(path, item)
        self.ui.pick.show(root, xr - root.winfo_rootx(), yr - root.winfo_rooty(), self.fonts.cw * 24, items,
                          current or items[0], pick, labels=labels, hints=hints, disabled=disabled,
                          openers=openers, on_cancel=lambda: setattr(self, "_lang_reasons", {}))

    def _language_tip(self, e):
        m = self.ui.pick
        if not m.open or list(m.items) != getattr(self, "_lang_items", None):
            return None
        i = m._row(e.y)
        return self._lang_reasons.get(m.items[i]) if i is not None else None

    def _other_language(self, path: str) -> None:
        def done(text):
            try:
                target = langrules.parse_other(text)
            except ValueError:
                return
            self.choose_language(path, target)
        dlg = RenameDialog(self.ui, "Language, as tag:Name (for example de:German)", "", langrules.problem_other,
                           done, button="Use")
        attach_tip(dlg.field.entry, self.ui.tip, lambda e: tips.TO_OTHER_FIELD)

    def choose_language(self, series_path: str, target: str) -> bool:
        """Set the language of the series (the only place that does). Refused, with a message, while a job of it
        runs or waits, and once a block is translated or a term confirmed (unless it is the same language)."""
        info = self.series
        if info is None or info.path != series_path or target == self.series_language():
            return False
        why = self.language_block_reason(series_path, getattr(self.steps.get("translate"), "view", None))
        if not why:
            why = langrules.lock_reason(*model.language_lock(series_path))
        if why:
            message(self.ui, why)
            return False
        try:
            model.set_series_language(series_path, target)
        except (OSError, ValueError) as exc:
            message(self.ui, "The language could not be saved: %s. It was not changed." % exc)
            return False
        new = model.with_language(info, target)
        books = self.steps.get("books")
        if books is not None:
            books.replace_series(new)
        self.series = new
        for s in self.steps.values():
            s.on_language()
        self.refresh_summary()
        return True

    def release_series(self, series_path: str, then) -> None:
        """Close the books of the series that worker threads keep open (an open zip blocks a move on Windows),
        then call `then()`. Waits at most a few seconds for a busy lane."""
        lanes = [n for n in self.ui.worker.lane_names if n != "run"]
        state = {"left": len(lanes), "done": False}

        def finish(*a):
            if state["done"]:
                return
            state["left"] -= 1
            if state["left"] <= 0:
                state["done"] = True
                then()

        def timeout():
            if not state["done"]:
                state["done"] = True
                then()
        for lane in lanes:
            self.ui.worker.submit(lambda ctx: model.release_books_task(ctx, series_path), on_result=finish,
                                  on_error=finish, lane=lane)
        self.root.after(5000, timeout)

    def set_series(self, info) -> None:
        self.series = info
        if info is not None:
            self.settings.set("series", info.path)
        self.book = ""
        self.infos = []
        self.selection = selection.Selection()
        for s in self.steps.values():
            s.on_series()
        self.refresh_summary()

    def set_book(self, name: str, infos) -> None:
        changed = name != self.book
        self.book = name
        self.infos = infos
        if changed:
            self.selection = selection.Selection()
            if name:
                self.settings.set("book", name)
        for s in self.steps.values():
            s.on_book()
        self.refresh_summary()

    def set_selection(self, sel) -> None:
        if sel == self.selection:
            return
        self.selection = sel
        for s in self.steps.values():
            s.on_selection()
        self.refresh_summary()

    def refresh_summary(self) -> None:
        sel = self.selection
        if not sel or not self.infos:
            text = ""
        else:
            n, b, complete = cl.selection_size(self.infos, sel.indices)
            text = selection.summary(sel, n, b, complete)
        if self.summary.cget("text") != text:
            self.summary.configure(text=text)
        self.refresh_context()

    def _summary_tip(self):
        sel = self.selection
        if not sel:
            return None
        spans = ", ".join("%d" % a if a == b else "%d-%d" % (a, b) for a, b in sel.spans()[:4])
        if len(sel.spans()) > 4:
            spans += " ..."
        return ("The chapters chosen on the Books step. The Terms and Translate steps work on them.",
                [("Book", sel.book), ("Positions", spans)])

    def _ctrl_a(self, e):
        step = self.steps.get(self.current)
        if isinstance(e.widget, (tk.Entry, tk.Text)):
            return None
        if isinstance(step, BooksStep):
            step.select_all_chapters()
            return "break"
        return None

    # ------------------------------------------------------------- window
    @staticmethod
    def _geometry(geo, w, h, sw, sh) -> str:
        if isinstance(geo, str):
            import re
            m = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", geo)
            if m:
                gw, gh, gx, gy = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                if 300 <= gw <= sw + 40 and 200 <= gh <= sh + 40 and -gw + 80 < gx < sw - 80 and 0 <= gy < sh - 80:
                    return geo
        return "%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3))

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        try:
            self.ui.panels.close_all()          # an open prompt editor keeps its draft
            self.runs.shutdown()                # a running job is stopped first, up to a minute
            for s in self.steps.values():
                s.shutdown()
            geo = self.root.geometry()
            self.settings.set("geometry", geo)
        finally:
            self.ui.worker.close()
            if self.lock is not None:
                self.lock.release()
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _already_open(holder) -> None:
    """A second start: say so and bring the first window to the front (window_spec 10.9). The environment
    variable NOVELGUI_MESSAGE_FILE makes the message a line in that file (scripted checks)."""
    hwnd = int((holder or {}).get("hwnd") or 0)
    raised = platform.raise_window(hwnd) if hwnd else False
    path = os.environ.get("NOVELGUI_MESSAGE_FILE")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("%s | raised=%s hwnd=%d\n" % (tips.ALREADY_OPEN, raised, hwnd))
        except OSError:
            pass
        return
    try:
        root = tk.Tk()
        root.withdraw()
        from tkinter import messagebox
        messagebox.showinfo(DEFAULT_TITLE, tips.ALREADY_OPEN, parent=root)
        root.destroy()
    except tk.TclError:
        pass


def main(argv=None) -> int:
    """Start the window unless another one of this program is open (one app window at a time)."""
    lock = AppLock(data_dir(), model.holder_alive)
    if not lock.acquire():
        _already_open(lock.holder)
        return 3
    app = None
    try:
        app = App()
        app.lock = lock
        lock.set_window(platform.window_handle(app.root))
        app.run()
    finally:
        lock.release()
    return 0
