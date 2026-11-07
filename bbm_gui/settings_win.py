"""Settings window: where the engine is, which Python runs it, the output name pattern, update and shortcut.
(Engine flags are chosen next to the command in the main window.)"""
import subprocess
import tkinter as tk
from tkinter import filedialog, ttk

from .theme import P


class SettingsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Settings")
        self.configure(background=P["bg0"])
        self.transient(app.root)
        self._build()
        self.update_idletasks()
        self.geometry("%dx%d" % (max(self.winfo_reqwidth(), app.px(620)), self.winfo_reqheight()))
        self.minsize(app.px(480), self.winfo_reqheight())
        self.bind("<Escape>", lambda e: self.destroy())

    def _build(self):
        a = self.app
        top = ttk.Frame(self, padding=(a.px(16), a.px(14), a.px(16), a.px(14)))
        top.pack(fill="both", expand=True)
        top.columnconfigure(1, weight=1)
        self.engine_var = tk.StringVar(value=a.engine_root or a.settings.get("engine_root", ""))
        self.python_var = tk.StringVar(value=a.python or a.settings.get("python", ""))
        self.name_var = tk.StringVar(value=a.settings.get("name_pattern", "{stem}_{lang}_{mode}"))
        for r, (label, var, pick) in enumerate((("Engine", self.engine_var, "dir"), ("Python", self.python_var, "file"),
                                                ("Name", self.name_var, None))):
            ttk.Label(top, text=label, style="Dim.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 12), pady=3)
            ttk.Entry(top, textvariable=var).grid(row=r, column=1, sticky="ew", pady=3)
            if pick:
                ttk.Button(top, text="…", style="Icon.TButton", width=3,
                           command=lambda v=var, k=pick: self._pick(v, k)).grid(row=r, column=2, padx=(6, 0))
        ttk.Button(top, text="Apply", command=self._apply_engine).grid(row=0, column=3, padx=(10, 0), sticky="ew")
        ttk.Button(top, text="Update", command=self._update_engine).grid(row=1, column=3, padx=(10, 0), sticky="ew")
        self.shortcut_btn = ttk.Button(top, text="Shortcut", command=self._shortcut)
        self.shortcut_btn.grid(row=2, column=3, padx=(10, 0), sticky="ew")
        self.name_var.trace_add("write", lambda *_: self._save_name())

    def _pick(self, var, kind):
        path = filedialog.askdirectory(parent=self) if kind == "dir" else filedialog.askopenfilename(parent=self)
        if path:
            var.set(path.replace("/", "\\") if "\\" in (var.get() or "") else path)

    def _apply_engine(self):
        self.app.settings["engine_root"] = self.engine_var.get().strip()
        self.app.settings["python"] = self.python_var.get().strip()
        self.app.settings.save()
        self.app.load_engine()
        self.destroy()

    def _shortcut(self):
        from . import shortcut

        try:
            made = shortcut.create()
        except (OSError, subprocess.SubprocessError):
            made = None
        self.shortcut_btn.configure(text="Done" if made else "Failed")
        self.after(2500, lambda: self.shortcut_btn.winfo_exists() and self.shortcut_btn.configure(text="Shortcut"))

    def _update_engine(self):
        self.app.update_engine()
        self.destroy()

    def _save_name(self):
        self.app.settings["name_pattern"] = self.name_var.get()
        self.app.settings.save()
