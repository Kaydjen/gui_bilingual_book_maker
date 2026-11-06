"""Main window."""
import base64
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import clipboard, cmdbuild, engine, icon, installer, jobs, keypool, promptset, prompts, runner, theme
from .keys_win import KeysWindow
from .models_win import ModelsWindow
from .options_win import OptionsWindow
from .prompt_win import PromptWindow
from .settings import Settings, data_dir
from .theme import P

LANGUAGES = ["Russian", "Polish", "English", "Ukrainian", "German", "French", "Spanish", "Italian", "Portuguese",
             "Czech", "Japanese", "Korean", "Chinese"]
MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
PRESETS = {
    "Gemini free": {"--api_format": "gemini", "--interval": "4", "--temperature": "0.4", "--use_context": True},
    "Custom": {},
}
LOG_LINES = 6000
LINE_CUT = 500
BOOK_TYPES = [("Books", "*.epub *.txt *.srt *.md *.pdf"), ("All files", "*.*")]


def open_path(path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App:
    def __init__(self, root, first_file=None):
        self.root = root
        self.settings = Settings()
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        root.title("Bilingual Book Maker")
        theme.apply(root)
        clipboard.install(root)
        try:
            self._icon = tk.PhotoImage(data=base64.b64encode(icon.png_bytes(64)))
            root.iconphoto(True, self._icon)
        except tk.TclError:
            pass
        root.geometry("%dx%d" % (self.px(940), self.px(700)))
        root.minsize(self.px(780), self.px(560))
        self.mono = theme.mono_family(root)

        self.inventory = None
        self.caps = engine.Capabilities(None)
        self.overlay = engine.load_overlay()
        self.engine_root = None
        self.python = None
        self.flagstate = {}
        self.preset_keys = set()
        self.runner = runner.Runner()
        self.monitor = runner.Monitor()
        self.job = None
        self.state = "idle"  # idle ready running stopping stopped finished error
        self.chip = ""
        self.chip_tone = "dim"
        self._job_key = None
        self.result_path = None
        self.started = 0.0
        self.closing = False
        self.busy_engine = False
        self.options = None
        self.prompt_win = None
        self.keys_win = None
        self.models_win = None
        self.bad_keys = set()  # keys the API refused in this session
        self.active_key = None
        self.cur_pair = None  # (key, model) of the run in progress
        self.run_note = ""  # chip text while a run uses one of several keys
        self._switching = False

        s = self.settings
        self.source = tk.StringVar(value="")
        self.from_var = tk.StringVar(value=s.get("from", "Auto"))
        self.to_var = tk.StringVar(value=s.get("to", "Russian"))
        self.mode = tk.StringVar(value=s.get("mode", "bilingual"))
        self.preset = tk.StringVar(value=s.get("preset", "Gemini free"))
        self.model = tk.StringVar(value=s.get("model", ", ".join(MODELS)))
        self.key = tk.StringVar(value=s.get("key", ""))
        self.prompt_path = tk.StringVar(value=s.get("prompt", ""))
        self.folder = tk.StringVar(value=s.get("folder", ""))
        self._build()
        self._apply_preset(self.preset.get(), initial=True)
        for v in (self.from_var, self.to_var, self.mode, self.model, self.key, self.prompt_path, self.folder):
            v.trace_add("write", lambda *_: self.on_change())
        self.preset.trace_add("write", lambda *_: self._apply_preset(self.preset.get()))
        self.source.trace_add("write", lambda *_: self.on_change())
        self.pool().purge(time.time())

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-o>", lambda e: self.choose_file())
        root.bind("<Control-Return>", lambda e: self.on_main_button())
        root.after(40, self._poll)
        root.after(1000, self._tick)
        self.load_engine()
        if first_file:
            self.set_file(first_file)
        elif s.get("last_file") and Path(s["last_file"]).is_file():
            self.set_file(s["last_file"])

    # ------------------------------------------------------------------ helpers
    def px(self, n):
        return int(n * self.scale)

    # ------------------------------------------------------------------ layout
    def _build(self):
        r = self.root
        pad = self.px(18)
        main = ttk.Frame(r, padding=(pad, pad, pad, self.px(10)))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(8, weight=1)

        # file, languages
        row = ttk.Frame(main)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.file_btn = ttk.Button(row, text="Choose file", style="SlotNeed.TButton", command=self.choose_file)
        self.file_btn.grid(row=0, column=0, sticky="ew")
        self.clear_btn = ttk.Button(row, text="✕", style="Icon.TButton", width=3, command=self.clear_file)
        self.from_box = ttk.Combobox(row, textvariable=self.from_var, values=["Auto"] + LANGUAGES, width=11)
        self.from_label = ttk.Label(row, text="From", style="Dim.TLabel")
        self.arrow = ttk.Label(row, text="→", style="Dim.TLabel")
        self.to_label = ttk.Label(row, text="To", style="Dim.TLabel")
        self.to_box = ttk.Combobox(row, textvariable=self.to_var, values=LANGUAGES, width=14)
        self.clear_btn.grid(row=0, column=1, padx=(6, 0))
        self.clear_btn.grid_remove()
        self.from_label.grid(row=0, column=2, padx=(18, 6))
        self.from_box.grid(row=0, column=3)
        self.arrow.grid(row=0, column=4, padx=10)
        self.to_label.grid(row=0, column=5, padx=(0, 6))
        self.to_box.grid(row=0, column=6)

        # mode, preset
        row = ttk.Frame(main)
        row.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        seg = ttk.Frame(row)
        seg.pack(side="left")
        ttk.Radiobutton(seg, text="Bilingual", value="bilingual", variable=self.mode, style="Seg.Toolbutton").pack(side="left")
        ttk.Radiobutton(seg, text="Translation only", value="single", variable=self.mode, style="Seg.Toolbutton").pack(side="left", padx=(2, 0))
        ttk.Combobox(row, textvariable=self.preset, values=list(PRESETS), state="readonly", width=14).pack(side="right")
        ttk.Label(row, text="Preset", style="Dim.TLabel").pack(side="right", padx=(0, 8))

        # model, key
        row = ttk.Frame(main)
        row.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        row.columnconfigure(1, weight=1)
        row.columnconfigure(3, weight=1)
        ttk.Label(row, text="Model", style="Dim.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.model_btn = ttk.Button(row, text="", style="Slot.TButton", command=self.open_models)
        self.model_btn.grid(row=0, column=1, sticky="ew")
        ttk.Label(row, text="Keys", style="Dim.TLabel").grid(row=0, column=2, padx=(18, 8))
        self.keys_btn = ttk.Button(row, text="Add key", style="SlotNeed.TButton", command=self.open_keys)
        self.keys_btn.grid(row=0, column=3, sticky="ew")

        # prompt
        row = ttk.Frame(main)
        row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="Prompt", style="Dim.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.prompt_btn = ttk.Button(row, text="none", style="Slot.TButton", command=self.open_prompt)
        self.prompt_btn.grid(row=0, column=1, sticky="ew")
        ttk.Button(row, text="✕", style="Icon.TButton", width=3, command=lambda: self.prompt_path.set("")).grid(row=0, column=2, padx=(6, 0))
        self.prompt_problem = ttk.Label(row, text="", style="Dim.TLabel")
        self.prompt_problem.grid(row=0, column=3, padx=(10, 0))

        # output
        row = ttk.Frame(main)
        row.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="Folder", style="Dim.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.folder_btn = ttk.Button(row, text="beside the book", style="Slot.TButton", command=self.choose_folder)
        self.folder_btn.grid(row=0, column=1, sticky="ew")
        ttk.Button(row, text="✕", style="Icon.TButton", width=3, command=lambda: self.folder.set("")).grid(row=0, column=2, padx=(6, 0))

        # command
        ttk.Separator(main).grid(row=5, column=0, sticky="ew", pady=(16, 12))
        box = ttk.Frame(main)
        box.grid(row=6, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.cmd = tk.Text(box, height=4, wrap="char", background=P["bg1"], foreground=P["text"], relief="flat",
                           borderwidth=0, padx=12, pady=10, font=(self.mono, 9), state="disabled", cursor="arrow",
                           selectbackground=P["bg3"], highlightthickness=1, highlightbackground=P["line"],
                           highlightcolor=P["line"])
        self.cmd.tag_configure("dim", foreground=P["dim"])
        self.cmd.grid(row=0, column=0, sticky="ew")
        self.copy_btn = tk.Canvas(box, width=self.px(30), height=self.px(30), background=P["bg1"], highlightthickness=0,
                                  cursor="hand2")
        self.copy_btn.grid(row=0, column=1, sticky="ne", padx=(6, 0))
        s = self.px(9)
        self.copy_btn.create_rectangle(s, s, s + self.px(10), s + self.px(11), outline=P["dim"], width=1.3)
        self.copy_btn.create_rectangle(s - self.px(4), s - self.px(4), s + self.px(6), s + self.px(7), outline=P["text"], width=1.3, fill=P["bg1"])
        self.copy_btn.bind("<Button-1>", lambda e: self.copy_command())

        # run row
        row = ttk.Frame(main)
        row.grid(row=7, column=0, sticky="ew", pady=(14, 10))
        row.columnconfigure(2, weight=1)
        self.main_btn = ttk.Button(row, text="Run", width=12, command=self.on_main_button)
        self.main_btn.grid(row=0, column=0)
        self.restart_btn = ttk.Button(row, text="Restart", style="Flat.TButton", command=self.restart)
        self.restart_btn.grid(row=0, column=1, padx=(6, 0))
        self.restart_btn.grid_remove()
        self.bar = tk.Canvas(row, height=self.px(10), background=P["bg0"], highlightthickness=0)
        self.bar.grid(row=0, column=2, sticky="ew", padx=14)
        self.bar.bind("<Configure>", lambda e: self._draw_bar())
        self.count_var = tk.StringVar()
        ttk.Label(row, textvariable=self.count_var, style="Dim.TLabel").grid(row=0, column=3)
        self.chip_label = ttk.Label(row, text="", style="Dim.TLabel")
        self.chip_label.grid(row=0, column=4, padx=(14, 0))
        self.open_btn = ttk.Button(row, text="Open", style="Accent.TButton", command=lambda: self.result_path and open_path(self.result_path))
        self.folder_open_btn = ttk.Button(row, text="Folder", command=lambda: self.result_path and open_path(Path(self.result_path).parent))
        self.open_btn.grid(row=0, column=5, padx=(14, 0))
        self.folder_open_btn.grid(row=0, column=6, padx=(6, 0))
        self.open_btn.grid_remove()
        self.folder_open_btn.grid_remove()

        # log
        logf = ttk.Frame(main)
        logf.grid(row=8, column=0, sticky="nsew")
        self.log = tk.Text(logf, wrap="char", background=P["bg1"], foreground=P["text"], relief="flat", borderwidth=0,
                           padx=12, pady=8, font=(self.mono, 9), state="disabled", selectbackground=P["bg3"],
                           highlightthickness=1, highlightbackground=P["line"], highlightcolor=P["line"])
        self.log.tag_configure("dim", foreground=P["dim"])
        self.log.tag_configure("strong", foreground=P["text"], font=(self.mono, 9, "bold"))
        sb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        foot = ttk.Frame(main)
        foot.grid(row=9, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(foot, text="Options", style="Flat.TButton", command=self.open_options).pack(side="left")
        ttk.Button(foot, text="Log file", style="Flat.TButton", command=self.open_log_file).pack(side="left")

    # ------------------------------------------------------------------ engine
    def load_engine(self):
        info = installer.current()
        root = self.settings.get("engine_root") or (info or {}).get("root")
        py = self.settings.get("python") or (info or {}).get("python")
        if root and engine.is_engine(root):
            py = py or engine.guess_python(root)
            self.engine_root, self.python = root, py
            self._set_chip("Loading", "dim")
            threading.Thread(target=self._load_inventory, args=(root, py), daemon=True).start()
        else:
            self.engine_root = self.python = None
            self.inventory = None
            self.caps = engine.Capabilities(None)
            self.on_change()

    def _load_inventory(self, root, py):
        inv, note = engine.load_inventory(root, py, data_dir())
        self.root.after(0, lambda: self._inventory_ready(inv, note))

    def _inventory_ready(self, inv, note):
        self.inventory = inv
        self.caps = engine.Capabilities(inv)
        self._set_chip("" if inv else "Engine", "dim" if inv else "accent")
        if self.options is not None and self.options.winfo_exists():
            self.options._fill()
        self.on_change()

    def update_engine(self):
        """Install the newest engine release (also the first install)."""
        if self.busy_engine or self.runner.running:
            return
        self.busy_engine = True
        self._set_chip("Installing", "dim")
        self.on_change()

        def work():
            try:
                version = installer.latest_version()
                cur = installer.current()
                if cur and cur["version"] == version and engine.is_engine(cur["root"]):
                    self.root.after(0, lambda: self._install_done(cur, None))
                    return
                info = installer.install(version, self._install_log)
                self.root.after(0, lambda: self._install_done(info, None))
            except Exception as e:  # network, disk, pip
                self.root.after(0, lambda: self._install_done(None, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _install_log(self, line):
        if line.startswith(("Collecting", "  Using cached", "  Downloading", "Ignoring", "  Actual", "  Requested",
                            "Actual", "Requested")):
            return
        self.root.after(0, lambda: self.log_append(line[:LINE_CUT], "dim"))

    def _install_done(self, info, error):
        self.busy_engine = False
        if error:
            self.log_append(error, "strong")
            self._set_chip("Engine", "accent")
            self.on_change()
            return
        self.settings["engine_root"] = info["root"]
        self.settings["python"] = info["python"]
        self.settings.save()
        self.load_engine()

    # ------------------------------------------------------------------ files
    def choose_file(self):
        if self.runner.running:
            return
        path = filedialog.askopenfilename(parent=self.root, initialdir=self.settings.get("last_dir") or None,
                                          filetypes=BOOK_TYPES)
        if path:
            self.set_file(path)

    def set_file(self, path):
        p = Path(path)
        if not p.is_file():
            return
        self.source.set(str(p))
        self.settings["last_dir"] = str(p.parent)
        self.settings["last_file"] = str(p)

    def clear_file(self):
        if self.runner.running:
            return
        self.source.set("")

    def choose_folder(self):
        path = filedialog.askdirectory(parent=self.root, initialdir=self.folder.get() or self.settings.get("last_dir") or None)
        if path:
            self.folder.set(path.replace("/", os.sep))

    def open_prompt(self):
        if self.prompt_win is not None and self.prompt_win.winfo_exists():
            self.prompt_win.lift()
            return
        self.prompt_win = PromptWindow(self)

    def open_options(self):
        if self.options is not None and self.options.winfo_exists():
            self.options.lift()
            return
        self.options = OptionsWindow(self)

    def open_log_file(self):
        if self.job and self.job.log_path.is_file():
            open_path(self.job.log_path)

    # ------------------------------------------------------------------ presets and command
    def _apply_preset(self, name, initial=False):
        for k in self.preset_keys:
            self.flagstate.pop(k, None)
        self.preset_keys = set()
        for k, v in PRESETS.get(name, {}).items():
            if k not in self.flagstate:
                self.flagstate[k] = v
                self.preset_keys.add(k)
        if not initial:
            self.on_change()

    def _mode_job(self):
        return "single" if self.mode.get() == "single" else "bilingual"

    def _job(self):
        src = self.source.get()
        if not src:
            return None
        return jobs.Job(src, self._mode_job(), self.to_var.get().strip() or "x")

    def _state_flags(self, book_path, model=None):
        st = dict(self.flagstate)
        st["--book_name"] = book_path
        to = self.to_var.get().strip()
        if to:
            st["--language"] = to
        frm = self.from_var.get().strip()
        if frm and frm.lower() != "auto" and self.caps.has("--source_lang"):
            st["--source_lang"] = frm
        if self.mode.get() == "single":
            st["--single_translate"] = True
        if self.prompt_path.get():
            st["--prompt"] = self.prompt_path.get()
        if model is None:
            models = self.model_list()
            model = models[0] if models else ""
        if model:
            st["--model"] = model
        return st

    def build_args(self, mask, book_path, resume, model=None):
        st = self._state_flags(book_path, model)
        argv, _ = cmdbuild.build_argv(self.inventory, st, self.overlay, mask=mask)
        argv += cmdbuild.split_extra(self.settings.get("extra_args", ""))
        if resume and "--resume" not in argv:
            argv.append("--resume")
        return argv

    def key_list(self):
        return keypool.parse(self.key.get())

    def model_list(self):
        return keypool.parse(self.model.get())

    def pool(self):
        p = keypool.Pool(self.key_list(), self.model_list(), self.settings.get("spent"))
        p.bad = self.bad_keys & set(p.keys)
        p.purge(time.time())
        return p

    def _store_pool(self, pool):
        self.settings["spent"] = pool.spent
        try:
            self.settings.save()
        except OSError:
            pass

    def reset_marks(self):
        self.bad_keys = set()
        self.settings["spent"] = {}
        self.on_change()

    def open_models(self):
        if self.models_win is not None and self.models_win.winfo_exists():
            self.models_win.lift()
            return
        self.models_win = ModelsWindow(self, MODELS)

    def open_keys(self):
        if self.keys_win is not None and self.keys_win.winfo_exists():
            self.keys_win.lift()
            return
        self.keys_win = KeysWindow(self)

    def _shell(self):
        return "cmd" if os.name == "nt" else "posix"

    def command_text(self):
        if not self.inventory or not self.engine_root:
            return "", ""
        job = self.job
        book = str(job.copy) if job else "…"
        resume = bool(job and job.has_cache())
        pair = self.pool().next_pair(time.time())
        argv = self.build_args(True, book, resume, pair[1] if pair else None)
        prefix = [self.python, str(Path(self.engine_root) / "make_book.py")]
        line = cmdbuild.render(prefix + argv, self._shell())
        env = ""
        if self.key_list():
            env = cmdbuild.render_env("BBM_API_KEY", cmdbuild.MASK, self._shell())
        return env, line

    # ------------------------------------------------------------------ state
    def on_change(self):
        job = self._job()
        key = str(job.dir) if job else None
        if not self.runner.running and not self.busy_engine and key != self._job_key:
            self._job_key = key
            self.state = "ready" if (job and self.engine_root) else "idle"
            if self.chip not in ("Loading", "Installing", "Engine"):
                self._set_chip("", "dim")
            self.result_path = None
            self.monitor = runner.Monitor()
            self.count_var.set("")
        elif self.state == "idle" and job and self.engine_root:
            self.state = "ready"
        self.job = job
        self._refresh()

    def _problems(self):
        out = []
        path = self.prompt_path.get()
        if path:
            try:
                out = prompts.check(prompts.load(path), self.to_var.get())
            except (OSError, ValueError):
                out = ["user"]
        return out

    def _key_needed(self):
        return self.preset.get() != "Custom"

    def _set_chip(self, text, tone="dim"):
        self.chip = text
        self.chip_tone = tone
        self.chip_label.configure(text=text, style="Accent.TLabel" if tone == "accent" else "Dim.TLabel")

    def _refresh(self):
        src = self.source.get()
        no_file = not src
        need_file = no_file and bool(self.engine_root) and not self.busy_engine
        self.file_btn.configure(text=Path(src).name if src else "Choose file",
                                style="SlotNeed.TButton" if need_file else "Slot.TButton")
        if src:
            self.clear_btn.grid()
        else:
            self.clear_btn.grid_remove()
        show_from = self.caps.has("--source_lang")
        for w in (self.from_label, self.from_box):
            (w.grid if show_from else w.grid_remove)()
        pp = self.prompt_path.get()
        self.prompt_btn.configure(text=Path(pp).name if pp else "none")
        models = self.model_list()
        self.model_btn.configure(text=("%d models" % len(models)) if len(models) > 1 else (models[0] if models else "none"))
        keys = self.key_list()
        pool = self.pool()
        usable = pool.usable_keys(time.time())
        if not keys:
            ktext, kneed = "Add key", self._key_needed()
        elif self.runner.running and self.active_key in keys and len(keys) > 1:
            ktext, kneed = "Key %d of %d" % (keys.index(self.active_key) + 1, len(keys)), False
        elif len(keys) == 1:
            ktext, kneed = "1 key", not usable
        else:
            ktext = "%d keys" % len(keys) if len(usable) == len(keys) else "%d of %d keys" % (len(usable), len(keys))
            kneed = not usable
        self.keys_btn.configure(text=ktext, style="SlotNeed.TButton" if kneed else "Slot.TButton")
        if self.keys_win is not None and self.keys_win.winfo_exists():
            self.keys_win.refresh()
        problems = self._problems()
        names = {"user": "?", "text": "{text}", "braces": "{ }", "language": "{language}"}
        self.prompt_problem.configure(text="  ".join(names[p] for p in problems))
        self.folder_btn.configure(text=self.folder.get() or "beside the book")

        env, line = self.command_text()
        self.cmd.configure(state="normal")
        self.cmd.delete("1.0", "end")
        if env:
            self.cmd.insert("end", env + "\n", "dim")
        self.cmd.insert("end", line)
        self.cmd.configure(state="disabled")

        running = self.runner.running
        stopping = running and self.runner.stop_requested
        resumable = bool(self.job and self.job.has_cache()) and not running
        if self.busy_engine:
            self.main_btn.configure(text="Installing", state="disabled", style="TButton")
        elif not self.engine_root or not self.inventory:
            self.main_btn.configure(text="Install engine" if not self.engine_root else "Run",
                                    state="normal" if not self.engine_root else "disabled",
                                    style="Accent.TButton" if not self.engine_root else "TButton")
        elif stopping:
            self.main_btn.configure(text="Kill", state="normal", style="TButton")
        elif running:
            self.main_btn.configure(text="Stop", state="normal", style="TButton")
        else:
            ready = (not no_file) and not problems and (bool(self.key_list()) or not self._key_needed())
            accent = ready and self.state != "finished" and self.chip_tone != "accent"
            self.main_btn.configure(text="Resume" if resumable else "Run", state="normal" if ready else "disabled",
                                    style="Accent.TButton" if accent else "TButton")
        if resumable and not running:
            self.restart_btn.grid()
        else:
            self.restart_btn.grid_remove()
        if self.state == "finished" and self.result_path:
            self.open_btn.grid()
            self.folder_open_btn.grid()
        else:
            self.open_btn.grid_remove()
            self.folder_open_btn.grid_remove()
        if no_file and not running:
            self.count_var.set("")
        self._draw_bar()

    def _draw_bar(self):
        c = self.bar
        c.delete("all")
        w = max(c.winfo_width(), 10)
        h = max(c.winfo_height(), 6)
        c.create_rectangle(0, 0, w, h, fill=P["bg1"], outline="")
        m = self.monitor
        if m.total:
            x = int(w * min(m.n / m.total, 1.0))
            c.create_rectangle(0, 0, x, h, fill=P["bg3"], outline="")
            if self.runner.running and not self.runner.stop_requested:
                c.create_rectangle(max(x - self.px(6), 0), 0, x, h, fill=P["accent"], outline="")
        elif self.runner.running and not self.runner.stop_requested:
            c.create_rectangle(0, 0, self.px(6), h, fill=P["accent"], outline="")

    # ------------------------------------------------------------------ run
    def on_main_button(self):
        if self.busy_engine:
            return
        if not self.engine_root:
            self.update_engine()
            return
        if self.runner.running:
            if self.runner.stop_requested:
                self.runner.kill()
            else:
                self.runner.stop()
                self._set_chip("Stopping", "dim")
                self._refresh()
            return
        if str(self.main_btn.cget("state")) == "disabled":
            return
        self.start_run()

    def restart(self):
        if self.job and not self.runner.running:
            self.job.restart()
            self.on_change()

    def start_run(self):
        job = self._job()
        if not job or not self.inventory:
            return
        pool = self.pool()
        keys = pool.keys
        if keys:
            pair = pool.next_pair(time.time())
            if pair is None:
                back = pool.earliest_return(time.time())
                if back is None:
                    self._set_chip("Key", "accent")
                else:
                    self._set_chip("Quota " + runner.local_hhmm(back), "accent")
                self._refresh()
                return
        else:
            models = self.model_list()
            pair = ("", models[0] if models else "")
        key, model = pair
        self.cur_pair = pair
        self.active_key = key or None
        self.run_note = "Key %d/%d" % (keys.index(key) + 1, len(keys)) if len(keys) > 1 else ""
        try:
            job.prepare()
        except OSError as e:
            self.log_append("Cannot prepare the job folder: %s" % e, "strong")
            return
        self.job = job
        if self.prompt_path.get():
            try:
                promptset.rebuild(self.prompt_path.get())
            except (OSError, ValueError) as e:
                self.log_append("Prompt: %s" % e, "strong")
        resume = job.has_cache()
        if resume:
            shutil.copy2(job.bin_path, job.dir / "checkpoint.bak")
            res = runner.run_tool(self.python, engine.HELPERS / "checkpoint.py",
                                  ["repair", str(job.bin_path), engine.FAILURE_MARKER, "--drop-fingerprint"])
            if "error" in res:
                self.log_append("Checkpoint: %s" % res["error"], "strong")
                self._set_chip("Checkpoint", "accent")
                return
            if res.get("removed"):
                self.log_append("Checkpoint: %d failed paragraph(s) will be translated again" % res["removed"], "dim")
        args = self.build_args(False, str(job.copy), resume, model)
        env = {"BBM_API_KEY": key}  # one key per run: the GUI, not the engine, decides when to change it
        # stray key variables must not leak into the job
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
                     "XAI_API_KEY", "DASHSCOPE_API_KEY", "LITELLM_MASTER_KEY"):
            env.setdefault(name, "")
        self.monitor = runner.Monitor()
        self.result_path = None
        if not self._switching:
            self.log_clear()
            self.log_append("")  # keep the view non-empty
        if self._switching and len(keys) > 1:
            self.log_append("%s  %s" % (self.run_note, model), "strong")
        self._switching = False
        self.state = "running"
        self.started = time.time()
        self._set_chip(self.run_note, "dim")
        self.count_var.set("")
        try:
            self.runner.start(self.python, self.engine_root, args, env, job.dir, job.log_path, keys)
        except OSError as e:
            self.state = "error"
            self._set_chip("Engine", "accent")
            self.log_append(str(e), "strong")
        self._refresh()

    # ------------------------------------------------------------------ events
    def _poll(self):
        t0 = time.perf_counter()
        n = 0
        try:
            while time.perf_counter() - t0 < 0.012 and n < 400:
                stream, kind, payload = self.runner.events.get_nowait()
                n += 1
                if stream == "exit":
                    self._on_exit(payload)
                    continue
                self._on_output(stream, kind, payload)
        except queue.Empty:
            pass
        if n:
            self._update_count()
        self.root.after(40 if n < 400 else 5, self._poll)

    def _on_output(self, stream, kind, text):
        guard = self.monitor.feed(stream, kind, text)
        if guard and self.runner.running and not self.runner.stop_requested:
            self.runner.stop(guard)
            self._set_chip("Stopping", "dim")
            self._refresh()
        if self.monitor.retrying and self.chip == self.run_note:
            self._set_chip("Retrying", "dim")
        elif not self.monitor.retrying and self.chip == "Retrying":
            self._set_chip(self.run_note, "dim")
        if kind == "frame":
            return
        if stream == "err" and runner.TQDM.search(text):
            return
        tag = "dim" if stream == "err" else ""
        if runner.FAILED.search(text) or runner.FATAL.search(text):
            tag = "strong"
        self.log_append(text[:LINE_CUT] + (" …" if len(text) > LINE_CUT else ""), tag)

    def _update_count(self):
        m = self.monitor
        if m.total:
            self.count_var.set("%d/%d  %d%%" % (m.n, m.total, int(100 * m.n / m.total)))
        self._draw_bar()

    def _tick(self):
        if self.runner.running:
            sec = int(time.time() - self.started)
            self.root.title("Bilingual Book Maker  %d:%02d" % divmod(sec, 60))
        self.root.after(1000, self._tick)

    def _on_exit(self, rc):
        job = self.job
        out_ok = bool(job and job.has_result())
        state, chip = runner.classify(rc, self.runner.stop_requested, self.runner.killed, self.runner.guard,
                                      self.monitor, out_ok)
        self.state = state
        guard = self.runner.guard
        self.active_key = None
        if guard in ("quota", "key", "model") and self.cur_pair and not self.runner.killed and not self.closing:
            nxt, back = self._next_after_guard(guard)
            if nxt:
                self.state = "stopped"
                self._set_chip("Next key" if nxt[0] != self.cur_pair[0] else "Next model", "dim")
                self.root.title("Bilingual Book Maker")
                self._switching = True
                self._refresh()
                self.root.after(600, self._continue_switch)
                return
            if guard == "quota" and back:
                chip = "Quota " + runner.local_hhmm(back)
        if state == "finished" and job:
            try:
                name = jobs.target_name(self.settings.get("name_pattern"), job.source, job.language, job.mode)
                folder = self.folder.get() or str(job.source.parent)
                self.result_path = str(jobs.deliver(job, folder, name))
                for p in (job.bin_path,):
                    try:
                        p.unlink()
                    except OSError:
                        pass
                self.log_append(self.result_path, "strong")
            except OSError as e:
                self.state, chip = "error", "No output"
                self.log_append("Cannot copy the result: %s" % e, "strong")
        tone = "accent" if chip else "dim"
        self._set_chip(chip, tone)
        self.root.title("Bilingual Book Maker")
        self._refresh()
        if self.closing:
            self._finish_close()

    def _next_after_guard(self, guard):
        """Mark the pair the run used as spent (or its key as invalid) and return (next pair or None, earliest return)."""
        key, model = self.cur_pair
        pool = self.pool()
        now = time.time()
        if guard == "key":
            self.bad_keys.add(key)
            pool.mark_bad(key)
        else:
            daily = self.monitor.daily or guard == "model"  # a missing model is not worth retrying today
            until = runner.quota_reset_utc().timestamp() if daily else now + keypool.SHORT_WAIT
            pool.mark(key, model, until)
        self._store_pool(pool)
        return pool.next_pair(now), pool.earliest_return(now)

    def _continue_switch(self):
        try:
            if not self.closing and not self.runner.running:
                self.start_run()
        finally:
            self._switching = False

    # ------------------------------------------------------------------ log
    def log_clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def log_append(self, text, tag=""):
        at_end = self.log.yview()[1] >= 0.999
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_LINES:
            self.log.delete("1.0", "%d.0" % (lines - LOG_LINES))
        self.log.configure(state="disabled")
        if at_end:
            self.log.see("end")

    def copy_command(self):
        env, line = self.command_text()
        self.root.clipboard_clear()
        self.root.clipboard_append((env + "\n" if env else "") + line)

    # ------------------------------------------------------------------ close
    def save_settings(self):
        s = self.settings
        s.update({"from": self.from_var.get(), "to": self.to_var.get(), "mode": self.mode.get(),
                  "preset": self.preset.get(), "model": self.model.get(), "key": self.key.get(),
                  "prompt": self.prompt_path.get(), "folder": self.folder.get()})
        try:
            s.save()
        except OSError:
            pass

    def on_close(self):
        self.save_settings()
        if self.runner.running:
            self.closing = True
            self.runner.stop()
            self.root.after(30000, lambda: (self.runner.kill(), self._finish_close()))
            return
        self._finish_close()

    def _finish_close(self):
        self.root.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    theme.enable_dpi_awareness()
    root = tk.Tk()
    App(root, first_file=argv[0] if argv else None)
    root.mainloop()
