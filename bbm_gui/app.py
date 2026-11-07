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

from . import clipboard, cmdbuild, engine, estimate, flagrules, icon, installer, jobs, keypool, langs, pace, promptset, prompts, runner, theme
from .flagstate import FlagState
from .keys_win import KeysWindow
from .flagpanel import FlagBar
from .models_win import ModelsWindow
from .pace_win import PaceWindow
from .prompt_win import PromptWindow
from .settings import Settings, data_dir
from .settings_win import SettingsWindow
from .theme import P

MODELS = ["gemini-3.1-flash-lite"]
PRESETS = {
    "Gemini free": {"--api_format": "gemini", "--temperature": "0.4", "--use_context": True,
                    flagrules.TAGS_FLAG: flagrules.DEFAULT_TAGS},
    "Custom": {"--api_format": "gemini", flagrules.TAGS_FLAG: flagrules.DEFAULT_TAGS},
}
LOG_LINES = 6000
LINE_CUT = 500
RIDE_OUT_MAX = 10  # seconds of per-minute cooldown the engine may wait out itself
HOP_GUARDS = ("quota", "busy", "key", "model")
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
        self.flagstate = FlagState(PRESETS, self.settings.get("preset", "Gemini free"), self.settings.get("flags"))
        self.dropped = []  # flags of the last built command that the engine does not know
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
        self.settings_win = None
        self.prompt_win = None
        self.keys_win = None
        self.models_win = None
        self.pace_win = None
        self.py_version = None  # (major, minor) of the engine's Python
        self.per_request = int(self.settings.get("per_request") or 1)
        self.seg = None  # pace of the segment in progress: model, paragraphs per request, wait after each request
        self._plan_counts = None  # (path, mtime, tags, excluded tags, with nav, (paragraphs per chapter, uncovered blocks))
        self.bad_keys = set()  # keys the API refused in this session
        self.active_key = None
        self.cur_pair = None  # (key, model) of the run in progress
        self.run_note = ""  # chip text while a run uses one of several keys
        self._switching = False
        self._switch_job = None  # the pending "start the next pair" callback
        self.waiting = False  # no process: every pair rests, the run restarts by itself at wait_until
        self.wait_until = 0.0
        self.wait_day = False
        self.accept_below = (None, 0)  # (job folder, paragraphs): failed ones among them were already tried again
        self.idle_segments = 0  # runs in a row that ended without any progress
        self._seg_sig = None  # checkpoint signature at the start of the segment

        self._save_job = None  # needed by _schedule_save, which the prompt memory may call during construction
        self.save_state = "saved"  # saved / saving / failed: what the Keys and Models windows show
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
        self._to_tag = langs.resolve(self.to_var.get()).tag  # the target the prompt slot was last aligned to
        self.prompt_path.trace_add("write", lambda *_: self._remember_prompt())
        self._remember_prompt()
        self.source.trace_add("write", lambda *_: self.on_change())
        for v in (self.key, self.model):  # keys and models are written to disk at once, not only on close
            v.trace_add("write", lambda *_: self._schedule_save())
        if "spent" in self.settings:  # the old key-by-key marks
            self.settings["pairs"] = keypool.migrate_spent(self.settings.pop("spent"), time.time())
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
        main.rowconfigure(9, weight=1)

        # file, languages
        row = ttk.Frame(main)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.file_btn = ttk.Button(row, text="Choose file", style="SlotNeed.TButton", command=self.choose_file)
        self.file_btn.grid(row=0, column=0, sticky="ew")
        self.clear_btn = ttk.Button(row, text="✕", style="Icon.TButton", width=3, command=self.clear_file)
        self.from_box = ttk.Combobox(row, textvariable=self.from_var, values=["Auto"] + langs.display_list(), width=11)
        self.from_label = ttk.Label(row, text="From", style="Dim.TLabel")
        self.arrow = ttk.Label(row, text="→", style="Dim.TLabel")
        self.to_label = ttk.Label(row, text="To", style="Dim.TLabel")
        self.to_box = ttk.Combobox(row, textvariable=self.to_var, values=langs.display_list(), width=14)
        self.to_box.bind("<FocusOut>", lambda e: self._normalise_to())
        self.to_box.bind("<<ComboboxSelected>>", lambda e: self._normalise_to())
        self.to_note = ttk.Label(row, text="", style="Dim.TLabel")
        self.clear_btn.grid(row=0, column=1, padx=(6, 0))
        self.clear_btn.grid_remove()
        self.from_label.grid(row=0, column=2, padx=(18, 6))
        self.from_box.grid(row=0, column=3)
        self.arrow.grid(row=0, column=4, padx=10)
        self.to_label.grid(row=0, column=5, padx=(0, 6))
        self.to_box.grid(row=0, column=6)
        self.to_note.grid(row=0, column=7, padx=(8, 0))

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
        self.pace_label = ttk.Label(row, text="Pace", style="Dim.TLabel")
        self.pace_btn = ttk.Button(row, text="Steady", style="Slot.TButton", width=22, command=self.open_pace)
        self.pace_label.grid(row=0, column=4, padx=(18, 8))
        self.pace_btn.grid(row=0, column=5)

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
        self.flagbar = FlagBar(main, self)
        self.flagbar.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        box = ttk.Frame(main)
        box.grid(row=7, column=0, sticky="ew")
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
        row.grid(row=8, column=0, sticky="ew", pady=(14, 10))
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
        self.plan_var = tk.StringVar()
        self.plan_label = ttk.Label(row, textvariable=self.plan_var, style="Dim.TLabel")
        self.plan_label.grid(row=1, column=2, columnspan=3, sticky="w", padx=14, pady=(4, 0))
        self.open_btn = ttk.Button(row, text="Open", style="Accent.TButton", command=lambda: self.result_path and open_path(self.result_path))
        self.folder_open_btn = ttk.Button(row, text="Folder", command=lambda: self.result_path and open_path(Path(self.result_path).parent))
        self.open_btn.grid(row=0, column=5, padx=(14, 0))
        self.folder_open_btn.grid(row=0, column=6, padx=(6, 0))
        self.open_btn.grid_remove()
        self.folder_open_btn.grid_remove()

        # log
        logf = ttk.Frame(main)
        logf.grid(row=9, column=0, sticky="nsew")
        self.log = tk.Text(logf, height=5, wrap="char", background=P["bg1"], foreground=P["text"], relief="flat", borderwidth=0,
                           padx=12, pady=8, font=(self.mono, 9), state="disabled", selectbackground=P["bg3"],
                           highlightthickness=1, highlightbackground=P["line"], highlightcolor=P["line"])
        self.log.tag_configure("dim", foreground=P["dim"])
        self.log.tag_configure("strong", foreground=P["text"], font=(self.mono, 9, "bold"))
        sb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        foot = ttk.Frame(main)
        foot.grid(row=10, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(foot, text="Settings", style="Flat.TButton", command=self.open_settings).pack(side="left")
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
        version = engine.python_version(py)
        self.root.after(0, lambda: self._inventory_ready(inv, note, version))

    def _inventory_ready(self, inv, note, version=None):
        self.py_version = version
        self.inventory = inv
        self.caps = engine.Capabilities(inv)
        self._set_chip("" if inv else "Engine", "dim" if inv else "accent")
        self._migrate_extra()
        if inv:
            langs.use_table(inv.get("languages"), inv.get("language_aliases"))
            self.to_box.configure(values=langs.display_list())
            self.from_box.configure(values=["Auto"] + langs.display_list())
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

    def open_pace(self):
        if self.pace_win is not None and self.pace_win.winfo_exists():
            self.pace_win.lift()
            return
        self.pace_win = PaceWindow(self)

    def open_settings(self):
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        self.settings_win = SettingsWindow(self)

    def open_log_file(self):
        if self.job and self.job.log_path.is_file():
            open_path(self.job.log_path)

    # ------------------------------------------------------------------ presets and command
    def _apply_preset(self, name, initial=False):
        self.flagstate.set_preset(name)
        if not initial:
            self.flags_changed()

    def flags_changed(self):
        self.on_change()
        self._schedule_save()

    def add_extra(self, text):
        """Flags typed by hand go to the user layer. Returns (added ids, refused [(flag, reason)])."""
        found, refused = cmdbuild.parse_extra(text, self.inventory, self.overlay)
        added = [fid for fid, val in found.items() if self.flagstate.set(fid, val)]
        if added:
            self.flags_changed()
        return added, refused

    def suggestions_for(self, flag_id):
        """Names offered while a list of file names is typed: the documents of the chosen EPUB."""
        src = self.source.get()
        if flag_id in ("--exclude_filelist", "--only_filelist") and src.lower().endswith(".epub"):
            return estimate.document_files(src)
        return []

    def _migrate_extra(self):
        """The old free-text "extra" setting is moved into the user layer once."""
        text = self.settings.get("extra_args")
        if not text or not self.inventory:
            return
        added, refused = self.add_extra(text)
        for flag, why in refused:
            self.log_append("%s: %s" % (flag, why), "dim")
        self.settings.pop("extra_args", None)
        self.save_settings()

    # ------------------------------------------------------------------ pace
    def pace_on(self):
        """The Pace slot belongs to the Gemini route only."""
        return self._key_needed()

    def group_size(self):
        """Paragraphs per request that the engine will really get (1 when grouping is off or impossible)."""
        return pace.group_size(self.per_request, self.py_version)

    def set_per_request(self, n):
        self.per_request = n
        self.settings["per_request"] = n
        self.flags_changed()

    def pace_model(self):
        """The model of the pair that runs, or that runs next."""
        if self.runner.running and self.cur_pair and self.cur_pair[1]:
            return self.cur_pair[1]
        pair = self.pool().next_pair(time.time()) if self.key_list() else None
        if pair:
            return pair[1]
        models = self.model_list()
        return models[0] if models else ""

    def pace_numbers(self, model=None):
        """The numbers behind the pace for a model: limits, latency, interval (seconds), paragraphs per request."""
        model = self.pace_model() if model is None else model
        n = self.group_size()
        rpm, rpd, src = pace.limits(model, self.settings.get("limits"))
        lat = pace.latency_of(self.settings.get("latency"), model, n)
        measured = bool((self.settings.get("latency") or {}).get(pace.latency_key(model, n)))
        return {"model": model, "n": n, "rpm": rpm, "rpd": rpd, "src": src, "latency": lat, "measured": measured,
                "interval": pace.interval(pace.latency_low_of(self.settings.get("latency"), model, n), rpm)}

    def plan_info(self):
        """Requests, seconds and days for the chosen book (an EPUB; other formats have no estimate), or None."""
        src = self.source.get()
        if not src or Path(src).suffix.lower() != ".epub":
            return None
        try:
            mtime = Path(src).stat().st_mtime
        except OSError:
            return None
        tags = estimate.tag_list(self.effective_tags(), estimate.TAGS)
        excluded = estimate.tag_list(self.flagstate.get(flagrules.EXCLUDE_TAGS_FLAG), estimate.EXCLUDED)
        nav = not self._nav_hidden()
        if not self._plan_counts or self._plan_counts[:5] != (src, mtime, tags, excluded, nav):
            self._plan_counts = (src, mtime, tags, excluded, nav, estimate.scan(src, tags, excluded, nav))
        found = self._plan_counts[5]
        counts, uncovered = found if found else (None, 0)
        if not counts:
            return None
        nums = self.pace_numbers()
        n_req = estimate.requests(counts, nums["n"])
        seconds = n_req * (nums["latency"] + float(pace.fmt_interval(nums["interval"])))
        now = time.time()
        pool = self.pool()
        if pool.keys:
            models = [m for k, m in pool.pairs() if k not in pool.bad and not pool.blocked(k, m, now)]
        else:
            models = [nums["model"]]
        caps = [pace.limits(m, self.settings.get("limits"))[1] for m in models]
        capacity = sum(caps) if caps and all(caps) else None
        return {"requests": n_req, "seconds": seconds, "days": estimate.days(n_req, capacity), "paragraphs": sum(counts),
                "uncovered": uncovered}

    def plan_text(self):
        info = self.plan_info()
        return estimate.plan_line(info["requests"], info["seconds"], info["days"], info["uncovered"]) if info else ""

    def _nav_hidden(self):
        """In a translation without the original, a list item of the navigation document would lose its link (the engine
        replaces the content of a translated tag with plain text): that document is left out of the run."""
        return self.mode.get() == "single" and "li" in estimate.tag_list(self.effective_tags(), estimate.TAGS)

    def effective_tags(self):
        """The --translate-tags value of the next run: the one the user's flags give, except that a job with a
        checkpoint keeps the tags it was started with (its saved paragraphs are numbered by them)."""
        job = self.job
        if job and job.has_cache():
            return job.recorded_tags() or ""
        return self.flagstate.get(flagrules.TAGS_FLAG) or ""

    def _mode_job(self):
        return "single" if self.mode.get() == "single" else "bilingual"

    def _job(self):
        src = self.source.get()
        if not src:
            return None
        return jobs.Job(src, self._mode_job(), langs.resolve(self.to_var.get() or "x"))

    def _state_flags(self, book_path, model=None):
        """preset <- user <- owned: the owned layer is computed here and always wins."""
        owned = {"--book_name": book_path}
        to = langs.resolve(self.to_var.get())
        if to:
            owned["--language"] = langs.engine_value(to)
        frm = self.from_var.get().strip()
        if frm and frm.lower() != "auto" and self.caps.has("--source_lang"):
            owned["--source_lang"] = frm
        if self.mode.get() == "single":
            owned["--single_translate"] = True
        if self.prompt_path.get():
            owned["--prompt"] = self.prompt_path.get()
        if model is None:
            models = self.model_list()
            model = models[0] if models else ""
        if model:
            owned["--model"] = model
        if model and self.pace_on():
            owned.update(pace.owned_flags(model, self.per_request, self.settings, self.py_version))
        return self.flagstate.effective(owned)

    def build_args(self, mask, book_path, resume, model=None):
        st = self._state_flags(book_path, model)
        if resume:
            tags = self.effective_tags()
            if tags:
                st[flagrules.TAGS_FLAG] = tags
            else:
                st.pop(flagrules.TAGS_FLAG, None)
        if self._nav_hidden() and Path(book_path).is_file():
            names = estimate.nav_files(book_path)
            if names:
                typed = [x for x in str(st.get("--exclude_filelist") or "").split(",") if x]
                st["--exclude_filelist"] = ",".join(dict.fromkeys(typed + names))
        argv, self.dropped = cmdbuild.build_argv(self.inventory, st, self.overlay, mask=mask)
        if resume and "--resume" not in argv:
            argv.append("--resume")
        return argv

    def key_list(self):
        return keypool.parse(self.key.get())

    def model_list(self):
        return keypool.parse(self.model.get())

    def pool(self):
        p = keypool.Pool(self.key_list(), self.model_list(), self.settings.get("pairs"))
        p.bad = self.bad_keys & set(p.keys)
        p.purge(time.time())
        return p

    def _store_pool(self, pool):
        self.settings["pairs"] = pool.states
        try:
            self.settings.save()
        except OSError:
            pass

    def _schedule_save(self):
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._set_save_state("saving")
        self._save_job = self.root.after(300, self.save_settings)

    def _set_save_state(self, state):
        self.save_state = state
        for w in (self.keys_win, self.models_win):
            if w is not None and w.winfo_exists():
                w.mark.set(state)

    def reset_marks(self):
        self.bad_keys = set()
        self.settings["pairs"] = {}
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
        if self.runner.running and self.cur_pair:
            pair = self.cur_pair  # the command of the pair that is working
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
            self._cancel_pending()  # another book or language: a waiting run is not this one
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

    def _normalise_to(self):
        """Commit the To box: show the display name of the typed language (ru -> Russian; unknown text stays as it is)
        and let the Prompt slot follow the language."""
        lang = langs.resolve(self.to_var.get())
        if lang.known and lang.name != self.to_var.get():
            self.to_var.set(lang.name)
        self._align_prompt(lang)
        if self.prompt_win is not None and self.prompt_win.winfo_exists():
            self.prompt_win.on_target_changed()

    def _remember_prompt(self):
        """Each language keeps its own prompt: remember the file of the slot under the language it is written for."""
        path = self.prompt_path.get()
        if not path or not Path(path).is_file():
            return
        lang = promptset.lang_of(path)
        if lang == promptset.UNKNOWN:
            return
        memory = self.settings.setdefault("prompt_by_lang", {})
        if memory.get(lang) != path:
            memory[lang] = path
            self._schedule_save()

    def _align_prompt(self, lang):
        """When the target language changes, the Prompt slot takes the prompt of that language (the remembered one, else
        the shipped template, else the neutral prompt). A prompt of unknown language is only replaced when it clearly
        does not fit."""
        if not lang or lang.tag == self._to_tag:
            return
        self._to_tag = lang.tag
        path = self.prompt_path.get()
        if not path:
            return
        have = promptset.lang_of(path)
        if have == "?":
            try:
                if not prompts.check_language(have, lang, prompts.load(path)):
                    return
            except (OSError, ValueError):
                return
        elif have == lang.tag:
            return
        try:
            new = promptset.select_for(lang.tag, self.settings.get("prompt_by_lang"))
        except (OSError, ValueError, StopIteration):
            return
        if new != path:
            self.prompt_path.set(new)
            self._flash(self.prompt_btn, "Slot.TButton")

    def _flash(self, widget, normal, ms=700):
        """A short accent flash on a slot: it changed by itself."""
        widget.configure(style="SlotNeed.TButton")
        self.root.after(ms, lambda: widget.winfo_exists() and widget.configure(style=normal))

    def _lang_problems(self):
        """Blocking problems with the From/To pair: 'to' (empty) and 'same' (From = To)."""
        if not langs.resolve(self.to_var.get()):
            return ["to"]
        if self.caps.has("--source_lang") and langs.same(self.from_var.get(), self.to_var.get()):
            return ["same"]
        return []

    def _problems(self):
        out = []
        path = self.prompt_path.get()
        if path:
            try:
                data = prompts.load(path)
                out = prompts.check(data)
                out += prompts.check_language(promptset.lang_of(path), langs.resolve(self.to_var.get()), data)
            except (OSError, ValueError):
                out = ["user"]
        return out

    def _key_needed(self):
        return self.flagstate.get("--api_format") == "gemini"

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
        if self.runner.running and self.cur_pair and self.cur_pair[1]:
            mtext = self.cur_pair[1]
        elif models:
            mtext = models[0] + (" +%d" % (len(models) - 1) if len(models) > 1 else "")
        else:
            mtext = "none"
        self.model_btn.configure(text=mtext, style="SlotNeed.TButton" if not models else "Slot.TButton")
        if self.models_win is not None and self.models_win.winfo_exists():
            self.models_win.refresh()
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
            kneed = not usable and not self.waiting
        self.keys_btn.configure(text=ktext, style="SlotNeed.TButton" if kneed else "Slot.TButton")
        if self.keys_win is not None and self.keys_win.winfo_exists():
            self.keys_win.refresh()
        self._refresh_pace()
        problems = self._problems()
        lang_problems = self._lang_problems()
        lang = langs.resolve(self.to_var.get())
        if "same" in lang_problems:
            self.to_note.configure(text="= From", style="Accent.TLabel")
        else:
            self.to_note.configure(text="No tag" if lang and not lang.known else "", style="Dim.TLabel")
        names = {"user": "?", "text": "{text}", "braces": "{ }"}
        if "lang" in problems:  # the language the prompt is written for
            names["lang"] = langs.resolve(promptset.lang_of(self.prompt_path.get())).name or "?"
        self.prompt_problem.configure(text="  ".join(names[p] for p in problems),
                                      style="Accent.TLabel" if "lang" in problems else "Dim.TLabel")
        self.folder_btn.configure(text=self.folder.get() or "beside the book")

        env, line = self.command_text()
        self.cmd.configure(state="normal")
        self.cmd.delete("1.0", "end")
        if env:
            self.cmd.insert("end", env + "\n", "dim")
        self.cmd.insert("end", line)
        self._dim_tokens(self.cmd, (r"--model=\S*", r"--interval=\S*", r"--resume"))
        self.cmd.configure(state="disabled")
        self.flagbar.refresh()

        running = self.runner.running
        stopping = running and self.runner.stop_requested
        resumable = bool(self.job and self.job.has_cache()) and not running
        if self.busy_engine:
            self.main_btn.configure(text="Installing", state="disabled", style="TButton")
        elif not self.engine_root or not self.inventory:
            self.main_btn.configure(text="Install engine" if not self.engine_root else "Run",
                                    state="normal" if not self.engine_root else "disabled",
                                    style="Accent.TButton" if not self.engine_root else "TButton")
        elif self.waiting or self._switching:
            self.main_btn.configure(text="Stop", state="normal", style="TButton")  # cancels the wait
        elif stopping:
            self.main_btn.configure(text="Kill", state="normal", style="TButton")
        elif running:
            self.main_btn.configure(text="Stop", state="normal", style="TButton")
        else:
            ready = (not no_file) and not problems and not lang_problems and (bool(self.key_list()) or not self._key_needed())
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

    @staticmethod
    def _dim_tokens(widget, patterns):
        """The parts of the command that change from one pair to the next are drawn dim."""
        for pat in patterns:
            start = "1.0"
            while True:
                n = tk.IntVar()
                at = widget.search(pat, start, stopindex="end", regexp=True, count=n)
                if not at:
                    break
                end = "%s+%dc" % (at, n.get())
                widget.tag_add("dim", at, end)
                start = end

    def _refresh_pace(self):
        on = self.pace_on()
        for w in (self.pace_label, self.pace_btn):
            (w.grid if on else w.grid_remove)()
        n = self.group_size()
        self.pace_btn.configure(text="Steady" if n == 1 else "Steady · %d per request" % n)
        running = self.runner.running or self.waiting or self._switching
        resumable = bool(self.job and self.job.has_cache())
        if not on or running or resumable or self.state == "finished":
            self.plan_var.set(self._eta_text() if running else "")
        else:
            self.plan_var.set(self.plan_text())
        if self.pace_win is not None and self.pace_win.winfo_exists():
            self.pace_win.refresh()

    def _eta_text(self):
        m = self.monitor
        sec = pace.eta_seconds(m.eta) if m.eta else None
        return "~%s left" % estimate.duration(sec) if sec is not None and m.total and m.n else ""

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
        if self.waiting or self._switching:
            self._cancel_pending()
            self._refresh()
            return
        if not self.runner.running:
            self._normalise_to()  # a typed language counts even when the box never lost focus
            self._refresh()
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
            self.accept_below = (None, 0)
            self.on_change()

    def start_run(self, auto=False):
        """Start the engine with the first ready pair. auto: the app continues by itself after a hop or a wait."""
        job = self._job()
        if not job or not self.inventory:
            return
        if not auto:
            self.idle_segments = 0
        self.waiting = False
        pool = self.pool()
        keys = pool.keys
        if keys:
            pair = pool.next_pair(time.time())
            if pair is None:
                self._enter_wait(pool, time.time())
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
            accept = self.accept_below[1] if self.accept_below[0] == str(job.dir) else 0
            res = runner.run_tool(self.python, engine.HELPERS / "checkpoint.py",
                                  ["repair", str(job.bin_path), engine.FAILURE_MARKER, "--drop-fingerprint"]
                                  + (["--accept", str(accept)] if accept else []))
            if "error" in res:
                self.log_append("Checkpoint: %s" % res["error"], "strong")
                self._set_chip("Checkpoint", "accent")
                return
            if res.get("removed"):
                self.log_append("Checkpoint: %d paragraph(s) from the first failed one are translated again"
                                % res["removed"], "dim")
        args = self.build_args(False, str(job.copy), resume, model)
        if not resume:
            job.record_tags(self.effective_tags())
        if self.dropped:
            self.log_append("Ignored flags: %s" % " ".join(self.dropped), "dim")
        env = {"BBM_API_KEY": key}  # one key per run: the GUI, not the engine, decides when to change it
        # stray key variables must not leak into the job
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
                     "XAI_API_KEY", "DASHSCOPE_API_KEY", "LITELLM_MASTER_KEY"):
            env.setdefault(name, "")
        self.monitor = runner.Monitor(policy=self._minute_policy, step=self.group_size())
        flags = pace.owned_flags(model, self.per_request, self.settings, self.py_version) if self.pace_on() else {}
        self.seg = {"model": model, "n": self.group_size(), "wait": float(flags.get("--interval") or 0)} if flags else None
        self.result_path = None
        if not auto:
            self.log_clear()
            self.log_append("")  # keep the view non-empty
        self._switching = False
        self._seg_sig = self._count()
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
        if runner.NOISE.search(text):
            return
        tag = "dim" if stream == "err" else ""
        if runner.FAILED.search(text) or runner.FATAL.search(text):
            tag = "strong"
        self.log_append(text[:LINE_CUT] + (" …" if len(text) > LINE_CUT else ""), tag)

    def _update_count(self):
        m = self.monitor
        if m.total:
            self.count_var.set("%d/%d  %d%%" % (m.n, m.total, int(100 * m.n / m.total)))
            if self.runner.running:
                self.plan_var.set(self._eta_text())
        self._draw_bar()

    def _tick(self):
        now = time.time()
        if self.runner.running:
            sec = int(now - self.started)
            self.root.title("Bilingual Book Maker  %d:%02d" % divmod(sec, 60))
        elif self.waiting:
            if now >= self.wait_until or self.pool().next_pair(now):  # the time came, or a key was added
                self.waiting = False
                self.root.after_idle(lambda: self.start_run(auto=True))
            else:
                self._wait_chip(now)
        if self.keys_win is not None and self.keys_win.winfo_exists():
            self.keys_win.tick()
        self.root.after(1000, self._tick)

    def _minute_policy(self, ev):
        """A per-minute 429 is ridden out by the engine only when the wait is short; the engine gives up after its
        last attempt and then caches the paragraph as failed, so anything longer stops the run and the GUI waits."""
        return keypool.minute_cooldown(ev.delay) > RIDE_OUT_MAX

    def _count(self):
        """Paragraphs saved in the job's checkpoint (the file's size or time says nothing: a stop re-saves it)."""
        job = self.job
        if not job or not job.has_cache():
            return 0
        res = runner.run_tool(self.python, engine.HELPERS / "checkpoint.py",
                              ["inspect", str(job.bin_path), engine.FAILURE_MARKER])
        return int(res.get("total") or 0)

    def _failed_count(self):
        """Paragraphs of the job's checkpoint that hold the failure marker or nothing."""
        job = self.job
        if not job or not job.has_cache():
            return 0
        res = runner.run_tool(self.python, engine.HELPERS / "checkpoint.py",
                              ["inspect", str(job.bin_path), engine.FAILURE_MARKER])
        return int(res.get("failed") or 0)

    def _enter_wait(self, pool, now):
        """No pair is ready: wait for the earliest one (no process runs), or say why nothing can be used."""
        back = pool.earliest_return(now)
        if back is None:
            self.state = "stopped"
            self._set_chip("Key" if pool.keys and all(k in pool.bad for k in pool.keys) else "Model", "accent")
            self._refresh()
            return
        self.waiting = True
        self.wait_until = back
        self.wait_day = pool.earliest_kind(now) == "day"
        self.state = "waiting"
        self._wait_chip(now)
        self._refresh()

    def _wait_chip(self, now):
        left = self.wait_until - now
        if self.wait_day or left >= 600:
            self._set_chip("Resume " + runner.local_hhmm(self.wait_until), "accent")  # the one thing to know: keep the app open
        else:
            self._set_chip("Wait " + runner.clock(left), "dim")

    def _cancel_pending(self):
        """Stop a wait or the gap between two pairs (nothing is running then)."""
        if self._switch_job is not None:
            self.root.after_cancel(self._switch_job)
            self._switch_job = None
        was_waiting = self.waiting
        if was_waiting or self._switching:
            self.waiting = self._switching = False
            self.state = "stopped"
            quota = was_waiting and (self.wait_day or self.wait_until - time.time() >= 600)
            self._set_chip("Quota " + runner.local_hhmm(self.wait_until) if quota else "", "accent" if quota else "dim")

    def _on_exit(self, rc):
        job = self.job
        out_ok = bool(job and job.has_result())
        state, chip = runner.classify(rc, self.runner.stop_requested, self.runner.killed, self.runner.guard,
                                      self.monitor, out_ok)
        self.state = state
        guard = self.runner.guard
        self.active_key = None
        self.monitor.flush()
        self._learn_pace()
        if (guard in HOP_GUARDS and self.cur_pair and self.key_list() and not self.runner.killed and not self.closing):
            self._hop(guard)
            return
        bad = self._failed_count()
        if guard == "blocked":
            self.accept_below = (str(job.dir) if job else None, self._count())  # the next Resume goes past them
            self.log_append("Stopped: the model gave no answer for %d paragraphs in a row" % runner.BLOCK_STREAK, "strong")
        if state == "finished" and job:
            self.accept_below = (None, 0)
            try:
                name = jobs.target_name(self.settings.get("name_pattern"), job.source, job.language, job.mode)
                folder = self.folder.get() or str(job.source.parent)
                self.result_path = str(jobs.deliver(job, folder, name))
                if not bad:  # with failures the checkpoint stays: Resume translates them again
                    try:
                        job.bin_path.unlink()
                    except OSError:
                        pass
                self.log_append(self.result_path, "strong")
            except OSError as e:
                self.state, chip = "error", "No output"
                self.log_append("Cannot copy the result: %s" % e, "strong")
        if bad:
            if state == "finished" and self.state == "finished":
                chip = "Not translated %d" % bad
            then = "Resume goes on past them." if guard == "blocked" else "Resume translates again from the first of them."
            self.log_append("%d paragraph%s not translated. %s" % (bad, " is" if bad == 1 else "s are", then), "strong")
        tone = "accent" if chip else "dim"
        self._set_chip(chip, tone)
        self.root.title("Bilingual Book Maker")
        self._refresh()
        if self.closing:
            self._finish_close()

    def _learn_pace(self):
        """Keep what the finished segment showed: the limits a 429 named and the measured time of one request."""
        seg, self.seg = self.seg, None
        if not seg:
            return
        changed = pace.learn(self.settings.setdefault("limits", {}), seg["model"], self.monitor.events)
        value = pace.measured(self.monitor.gaps, seg["wait"])
        if value:
            low = pace.measured_low(self.monitor.gaps, seg["wait"])
            pace.store_latency(self.settings.setdefault("latency", {}), seg["model"], seg["n"], value, low)
            changed = True
        if changed:
            self._schedule_save()

    def _hop(self, guard):
        """The run was stopped by the guard: set the state of its pair from the classified error and go on with the
        next ready pair, or wait for one. Returns True when the exit is fully handled."""
        key, model = self.cur_pair
        keys = self.key_list()
        pool = self.pool()
        now = time.time()
        ev = self.monitor.event
        progressed = self._count() > self._seg_sig
        if progressed:
            self.idle_segments = 0
            pool.success(key, model)
        else:
            self.idle_segments += 1
        if guard == "key":
            self.bad_keys.add(key)
            pool.mark_bad(key)
            why = "key refused"
        else:
            state, until = pool.record(key, model, ev.kind if ev else "unknown", ev.delay if ev else None, now,
                                       runner.day_return())
            why = {"cool": "cooling %d s" % round(until - now), "day": "used up today"}.get(state, "not available")
        self._store_pool(pool)
        left = "Key %d/%d  %s  %s" % (keys.index(key) + 1 if key in keys else 0, len(keys), model, why)
        self.root.title("Bilingual Book Maker")
        if self.idle_segments >= keypool.LOOP_LIMIT:
            self.log_append(left, "dim")
            self.log_append("Stopped: %d runs in a row made no progress" % self.idle_segments, "strong")
            self.state = "error"
            self._set_chip("Failed", "accent")
            self._refresh()
            return True
        nxt = pool.next_pair(now)
        if nxt:
            self.log_append("%s  >  Key %d/%d  %s" % (left, keys.index(nxt[0]) + 1, len(keys), nxt[1]), "dim")
            self.state = "stopped"
            self._set_chip("Next key" if nxt[0] != key else "Next model", "dim")
            self._switching = True
            self._switch_job = self.root.after(600, self._continue_switch)
            self._refresh()
            return True
        self.log_append(left + "  >  waiting", "dim")
        self._enter_wait(pool, now)
        return True

    def _continue_switch(self):
        self._switch_job = None
        if self._switching and not self.closing and not self.runner.running:
            self.start_run(auto=True)
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
                  "prompt": self.prompt_path.get(), "folder": self.folder.get(), "flags": self.flagstate.to_json()})
        try:
            s.save()
        except OSError:
            self._set_save_state("failed")
            return False
        self._set_save_state("saved")
        return True

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
