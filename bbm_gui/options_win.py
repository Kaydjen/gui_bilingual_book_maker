"""Options window: engine location, output name pattern, and every engine flag, generated from the inventory."""
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, ttk

from . import cmdbuild, theme
from .theme import P

# flags that have their own control in the main window
MAIN_FLAGS = {"--book_name", "--language", "--source_lang", "--single_translate", "--prompt", "--model", "--key",
              "--api_key", "--help"}


def group_of(flag, overlay):
    ov = overlay.get("flag", {}).get(flag["id"], {})
    if ov.get("group"):
        return ov["group"]
    for rule in overlay.get("group_rule", []):
        if re.search(rule["match"], flag["id"]):
            return rule["group"]
    h = flag.get("help") if isinstance(flag.get("help"), str) else ""
    m = re.match(r"\s*([A-Z][A-Za-z-]+) only\b", h)
    if m:
        return m.group(1)
    return "Other"


def group_order(overlay):
    return {g["id"]: g.get("order", 1000) for g in overlay.get("group", [])}


def label_of(flag, overlay):
    ov = overlay.get("flag", {}).get(flag["id"], {})
    if ov.get("label"):
        return ov["label"]
    return flag["id"].lstrip("-")


class OptionsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Options")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(720), app.px(640)))
        self.minsize(app.px(560), app.px(420))
        self.transient(app.root)
        self.rows = {}
        self.vars = {}
        self._build()
        self.bind("<Escape>", lambda e: self.destroy())

    # ------------------------------------------------------------------ layout
    def _build(self):
        a = self.app
        top = ttk.Frame(self, padding=(a.px(16), a.px(14), a.px(16), a.px(6)))
        top.pack(fill="x")
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
        ttk.Separator(self).pack(fill="x", padx=a.px(16), pady=(6, 0))

        bar = ttk.Frame(self, padding=(a.px(16), a.px(10), a.px(16), a.px(4)))
        bar.pack(fill="x")
        self.search = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.search)
        entry.pack(fill="x")
        self.search.trace_add("write", lambda *_: self._filter())
        entry.focus_set()

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=(a.px(16), 0), pady=(0, a.px(10)))
        self.canvas = tk.Canvas(wrap, background=P["bg0"], highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self.body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.body_id, width=e.width))
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        extra = ttk.Frame(self, padding=(a.px(16), 0, a.px(16), a.px(12)))
        extra.pack(fill="x")
        ttk.Label(extra, text="Extra", style="Dim.TLabel").pack(side="left", padx=(0, 12))
        self.extra_var = tk.StringVar(value=a.settings.get("extra_args", ""))
        ttk.Entry(extra, textvariable=self.extra_var).pack(side="left", fill="x", expand=True)
        self.extra_var.trace_add("write", lambda *_: self._save_extra())
        self._fill()

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120) * 3, "units")

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

    def _save_extra(self):
        self.app.settings["extra_args"] = self.extra_var.get()
        self.app.settings.save()
        self.app.on_change()

    # ------------------------------------------------------------------ flag rows
    def _fill(self):
        a = self.app
        for w in self.body.winfo_children():
            w.destroy()
        self.rows.clear()
        self.vars.clear()
        if not a.inventory:
            return
        overlay = a.overlay
        gorder = group_order(overlay)
        groups = {}
        for f in a.inventory["flags"]:
            if f["hidden"] or f.get("deprecated") or f["id"] in MAIN_FLAGS or f.get("alias_of"):
                continue
            if f["id"] == "--model_list" and not a.caps.modern:
                continue
            groups.setdefault(group_of(f, overlay), []).append(f)
        for gname in sorted(groups, key=lambda g: (gorder.get(g, 1000), g)):
            head = ttk.Label(self.body, text=gname, style="Group.TLabel")
            head.pack(anchor="w", pady=(14, 4))
            self.rows[head] = ("", gname)
            for f in sorted(groups[gname], key=lambda x: x.get("order", 0)):
                self._row(f)
        self.body.update_idletasks()

    def _row(self, f):
        a = self.app
        kind = cmdbuild.kind_of(f, a.overlay)
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=2)
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text=label_of(f, a.overlay), width=24, anchor="w").grid(row=0, column=0, sticky="w")
        fid = f["id"]
        cur = a.flagstate.get(fid)
        placeholder = a.overlay.get("flag", {}).get(fid, {}).get("placeholder", "")
        var = tk.StringVar()
        self.vars[fid] = var
        ctl = None
        if kind in ("toggle", "toggle_inverted"):
            ivar = tk.BooleanVar(value=(cur if cur is not None else (kind == "toggle_inverted")))
            self.vars[fid] = ivar
            ctl = ttk.Checkbutton(row, variable=ivar, command=lambda: self._set_bool(fid, ivar, kind))
        elif kind == "optional_value":
            var.set("on" if cur is True else ("" if cur is None else str(cur)))
            ctl = ttk.Combobox(row, textvariable=var, state="readonly", values=[""] + ["on"] + list(f.get("choices") or []))
            ctl.bind("<<ComboboxSelected>>", lambda e: self._set_text(fid, var, kind))
        elif kind == "enum":
            var.set("" if cur is None else str(cur))
            ctl = ttk.Combobox(row, textvariable=var, state="readonly", values=[""] + list(f.get("choices") or []))
            ctl.bind("<<ComboboxSelected>>", lambda e: self._set_text(fid, var, kind))
        elif kind == "combo":
            var.set("" if cur is None else str(cur))
            vals = list(f.get("choices") or [])[:40] if isinstance(f.get("choices"), list) else []
            ctl = ttk.Combobox(row, textvariable=var, values=vals)
            var.trace_add("write", lambda *_: self._set_text(fid, var, kind))
        else:
            if isinstance(cur, list):
                cur = " ".join(cur)
            var.set("" if cur is None else str(cur))
            ctl = ttk.Entry(row, textvariable=var, show="•" if kind == "secret" else "")
            var.trace_add("write", lambda *_: self._set_text(fid, var, kind))
        ctl.grid(row=0, column=1, sticky="ew" if kind not in ("toggle", "toggle_inverted") else "w", padx=(8, 0))
        if placeholder and kind not in ("toggle", "toggle_inverted"):
            ttk.Label(row, text=placeholder, style="Dim.TLabel").grid(row=0, column=2, padx=(8, 0))
        ttk.Button(row, text="✕", style="Icon.TButton", width=3, command=lambda: self._clear(fid, kind)).grid(
            row=0, column=3, padx=(6, 0))
        self.rows[row] = (fid, label_of(f, a.overlay))

    def _set_bool(self, fid, var, kind):
        val = bool(var.get())
        default = kind == "toggle_inverted"
        if val == default:
            self.app.flagstate.pop(fid, None)
        else:
            self.app.flagstate[fid] = val
        self.app.on_change()

    def _set_text(self, fid, var, kind):
        text = var.get().strip()
        if not text:
            self.app.flagstate.pop(fid, None)
        elif kind == "optional_value":
            self.app.flagstate[fid] = True if text == "on" else text
        elif kind == "multi":
            self.app.flagstate[fid] = cmdbuild.split_extra(text)
        else:
            self.app.flagstate[fid] = text
        self.app.on_change()

    def _clear(self, fid, kind):
        self.app.flagstate.pop(fid, None)
        v = self.vars.get(fid)
        if isinstance(v, tk.BooleanVar):
            v.set(kind == "toggle_inverted")
        elif v is not None:
            v.set("")
        self.app.on_change()

    def _filter(self):
        needle = self.search.get().strip().lower()
        shown_group = None
        for w in list(self.body.winfo_children()):
            w.pack_forget()
        current = None
        for w, (fid, label) in self.rows.items():
            if not fid:
                current = w
                w._visible = False
                continue
            ok = not needle or needle in label.lower() or needle in fid.lower()
            w._visible = ok
            if ok and current is not None and not current._visible:
                current._visible = True
                current.pack(anchor="w", pady=(14, 4))
            if ok:
                w.pack(fill="x", pady=2)
        # keep group headers before their rows: repack in order
        order = [w for w in self.rows]
        for w in order:
            if getattr(w, "_visible", True):
                w.pack_forget()
                if not self.rows[w][0]:
                    w.pack(anchor="w", pady=(14, 4))
                else:
                    w.pack(fill="x", pady=2)
        self.canvas.yview_moveto(0)
