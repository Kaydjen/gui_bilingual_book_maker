"""The window: header with the step switch, the steps, and the state they share."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from . import chapterlogic as cl
from . import model, platform, selection
from .books_view import BooksStep
from .settings import Settings, api_base
from .step import Step
from .keystore import KeyStore, PromptStore
from .settings_view import SettingsPanel, model_list
from .terms_view import TermsStep
from .translate_view import TranslateStep
from .theme import BG, BRIGHT, DIM, Fonts, style_ttk
from .tooltip import attach_tip
from .ui import UI
from .widgets import Segmented, install_clipboard

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
        self.panel = None

        ls = self.fonts.ls
        pad_x, pad_y = int(ls * 1.1), int(ls * 0.9)
        outer = tk.Frame(root, bg=BG)
        outer.pack(fill="both", expand=True, padx=pad_x, pady=pad_y)
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, int(ls * 0.8)))
        self.switch = Segmented(head, ui.font, self.show_step)
        self.switch.pack(side="left")
        self.gear = Gear(head, int(ls * 1.25), self.open_settings)
        self.gear.pack(side="right", padx=(pad_x, 0))
        attach_tip(self.gear, ui.tip, lambda e: "Settings: keys, models, pace, keep awake.")
        self.summary = tk.Label(head, text="", bg=BG, fg=DIM, font=ui.font, anchor="e")
        self.summary.pack(side="right")
        attach_tip(self.summary, ui.tip, lambda e: self._summary_tip())
        self.host = tk.Frame(outer, bg=BG)
        self.host.pack(fill="both", expand=True)

        self.register_step(BooksStep)
        self.register_step(TermsStep)
        self.register_step(TranslateStep)

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

    def refresh_dot(self) -> None:
        """The step switch; the Translate tab carries a small dot while a job of the series is unfinished."""
        tr = self.steps.get("translate")
        unfinished = bool(tr is not None and (tr.view.unfinished or tr.running))
        items = []
        for k in self.order:
            if k == "translate" and unfinished and self.current != "translate":
                items.append((k, self.steps[k].label, None, self.current == "books"))
            else:
                items.append((k, self.steps[k].label, None))
        self.switch.set_items(items, self.current or None)

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
            for s in self.steps.values():
                s.shutdown()
            geo = self.root.geometry()
            self.settings.set("geometry", geo)
        finally:
            self.ui.worker.close()
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(argv=None) -> None:
    App().run()
