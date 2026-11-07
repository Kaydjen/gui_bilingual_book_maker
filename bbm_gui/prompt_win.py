"""Prompt window: the template text on the left, the glossary on the right. Saving builds the prompt file the
engine reads."""
import tkinter as tk
from tkinter import filedialog, ttk

from . import glossary as gl
from . import langs, promptset, prompts
from .ordlist import InputField, SaveMark
from .theme import P, mono_family

COLS = ("term", "translation", "note")
HEAD = {"term": "Term", "translation": "Translation", "note": "Note"}


class PromptWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Prompt")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(1180), app.px(700)))
        self.minsize(app.px(820), app.px(480))
        self.transient(app.root)
        self.mono = mono_family(app.root)
        self.set = self._blank()
        self.target = langs.resolve(app.to_var.get())
        self.dirty = False
        self.filter_mode = None
        self.pairs = []
        self._edit = None
        self._quiet = True  # loading is not an edit
        self._build()
        path = app.prompt_path.get()
        if path:
            self._open(path)
        else:
            self._load_set()
        self.bind("<Escape>", lambda e: self._escape())
        self.bind("<Control-s>", lambda e: self.save())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------ layout
    def _build(self):
        a = self.app
        pad = a.px(16)
        top = ttk.Frame(self, padding=(pad, pad, pad, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Name", style="Dim.TLabel").pack(side="left", padx=(0, 8))
        self.name_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.name_var, width=22).pack(side="left")
        ttk.Label(top, text="Language", style="Dim.TLabel").pack(side="left", padx=(18, 8))
        self.lang_label = ttk.Label(top, text=self.target.name or "-")
        self.lang_label.pack(side="left")
        ttk.Label(top, text="Template", style="Dim.TLabel").pack(side="left", padx=(18, 8))
        self.tpl_var = tk.StringVar()
        self.tpl_box = ttk.Combobox(top, textvariable=self.tpl_var, state="readonly", width=22)
        self.tpl_box.pack(side="left")
        self.tpl_box.bind("<<ComboboxSelected>>", lambda e: self._apply_template())
        self._fill_templates()
        self.mark = SaveMark(top)
        self.mark.pack(side="right")
        ttk.Button(top, text="Save", command=self.save).pack(side="right", padx=(0, 10))
        ttk.Button(top, text="Open", command=self.open_file).pack(side="right", padx=(0, 8))

        panes = ttk.Frame(self, padding=(pad, 0, pad, pad))
        panes.pack(fill="both", expand=True)
        panes.columnconfigure(0, weight=3, uniform="p")
        panes.columnconfigure(1, weight=4, uniform="p")
        panes.rowconfigure(0, weight=1)

        left = ttk.Frame(panes)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(1, weight=4)
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="System").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.system = self._text(left, 1)
        head = ttk.Frame(left)
        head.grid(row=2, column=0, sticky="ew", pady=(10, 4))
        ttk.Label(head, text="User").pack(side="left")
        self.problem = ttk.Label(head, text="", style="Dim.TLabel")
        self.problem.pack(side="left", padx=(12, 0))
        self.user = self._text(left, 3)
        self.user.bind("<<Modified>>", self._modified)
        self.system.bind("<<Modified>>", self._modified)

        right = ttk.Frame(panes)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)
        bar = ttk.Frame(right)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="Glossary").pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.filter_var, width=18).pack(side="right")
        self.filter_var.trace_add("write", lambda *_: self._refresh())
        self.chips = ttk.Frame(right)
        self.chips.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        wrap = ttk.Frame(right)
        wrap.grid(row=2, column=0, sticky="nsew")
        self.tree = ttk.Treeview(wrap, columns=COLS, show="headings", selectmode="extended")
        for c, w in zip(COLS, (220, 260, 160)):
            self.tree.heading(c, text=HEAD[c])
            self.tree.column(c, width=self.app.px(w), anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._begin_edit)
        self.tree.tag_configure("new", background=P["bg3"])
        self.tree.bind("<Delete>", lambda e: self._delete())
        self.tree.bind("<Control-v>", lambda e: self._paste())
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

        add = ttk.Frame(right)
        add.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.add_vars = [tk.StringVar() for _ in COLS]
        self.add_entries = []
        for i, v in enumerate(self.add_vars):
            e = (InputField if i == 0 else ttk.Entry)(add, textvariable=v)
            e.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            add.columnconfigure(i, weight=(3, 3, 2)[i])
            e.bind("<Return>", lambda ev: self._add())
            self.add_entries.append(e)
        ttk.Button(add, text="Add", command=self._add).grid(row=0, column=len(COLS), padx=(8, 0))

        foot = ttk.Frame(right)
        foot.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(foot, text="Remove", command=self._delete).pack(side="left")
        ttk.Button(foot, text="Import", style="Flat.TButton", command=self.import_file).pack(side="left", padx=(6, 0))
        ttk.Button(foot, text="Export", style="Flat.TButton", command=self.export).pack(side="left", padx=(6, 0))

    def _text(self, parent, row):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="nsew")
        t = tk.Text(frame, wrap="word", background=P["bg1"], foreground=P["text"], insertbackground=P["text"],
                    relief="flat", borderwidth=0, padx=10, pady=8, undo=True, font=(self.mono, 10),
                    selectbackground=P["bg3"], highlightthickness=1, highlightbackground=P["line"],
                    highlightcolor=P["faint"], height=4)
        sb = ttk.Scrollbar(frame, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return t

    def _fill_templates(self):
        """Only templates written for the target language, plus the neutral one."""
        self.tpl_box.configure(values=[t["name"] for t in promptset.templates_for(self.target.tag)])

    def on_target_changed(self):
        """The To box of the main window changed: follow it (label, template list, and the prompt the slot switched to)."""
        self.target = langs.resolve(self.app.to_var.get())
        self.lang_label.configure(text=self.target.name or "-")
        self._fill_templates()
        path = self.app.prompt_path.get()
        if path and not self.dirty and path != getattr(self, "_path", None):
            self._open(path)
        else:
            self._check()

    # ------------------------------------------------------------------ load / save
    @staticmethod
    def _blank():
        head, hint = promptset.default_block()
        return promptset.PromptSet(name="prompt", head=head, hint=hint)

    def _open(self, path):
        self._path = path
        try:
            self.set = promptset.PromptSet.open(path)
        except (OSError, ValueError):
            self.set = self._blank()
        self._load_set()

    def _load_set(self):
        self._quiet = True
        s = self.set
        self.name_var.set(s.name)
        self.system.delete("1.0", "end")
        self.system.insert("1.0", s.system)
        self.user.delete("1.0", "end")
        self.user.insert("1.0", s.user)
        self.system.edit_modified(False)
        self.user.edit_modified(False)
        self._refresh()
        self._check()
        self._quiet = False
        self.mark.set("saved")
        self.dirty = False

    def _dirty(self):
        if not self._quiet:
            self.dirty = True
            self.mark.set("dirty")

    def _pull(self):
        s = self.set
        s.name = self.name_var.get().strip() or "prompt"
        s.system = self.system.get("1.0", "end-1c")
        s.user = self.user.get("1.0", "end-1c")
        if "{language}" in s.system or "{language}" in s.user:
            s.lang = promptset.NEUTRAL
        elif not s.lang:  # a new prompt is written for the target language it is saved under
            s.lang = self.target.tag or promptset.detect_lang(s.system, s.user)
        if s.lang not in (promptset.NEUTRAL, promptset.UNKNOWN):  # the glossary follows the prompt, not the To box
            s.language = langs.resolve(s.lang).name or s.language
        elif not s.language:
            s.language = self.target.name
        return s

    def open_file(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Prompt", "*.json"), ("All", "*.*")])
        if path:
            self._open(path)

    def save(self):
        self._end_edit(commit=True)
        try:
            built = self._pull().save()
        except OSError:
            self.mark.set("failed")
            return
        self._path = str(built)
        self.app.prompt_path.set(str(built))
        self.app.on_change()
        self.mark.set("saved")
        self.dirty = False

    def _apply_template(self):
        for t in promptset.templates():
            if t["name"] == self.tpl_var.get():
                self.system.delete("1.0", "end")
                self.system.insert("1.0", t["system"])
                self.user.delete("1.0", "end")
                self.user.insert("1.0", t["user"])
                self.set.head, self.set.hint = t["head"], t["hint"]  # the glossary block follows the template's language
                self.set.lang = t["tag"]
                if t["language"]:
                    self.set.language = t["language"]
                self._check()
                self._refresh()
                self._dirty()
                return

    def _check(self):
        system, user = self.system.get("1.0", "end-1c"), self.user.get("1.0", "end-1c")
        probs = prompts.check({"user": user})
        lang = promptset.NEUTRAL if "{language}" in system + user else self.set.lang
        probs += prompts.check_language(lang, self.target, {"system": system, "user": user})
        if gl.check_system(system):
            probs.append("sysbraces")
        shown = lang if lang not in ("", promptset.UNKNOWN) else promptset.script_lang(system + " " + user)
        names = {"user": "empty", "text": "{text}", "braces": "{ }", "lang": langs.resolve(shown).name or "?",
                 "sysbraces": "{ } system"}
        self.problem.configure(text="  ".join(names[p] for p in probs))

    def _modified(self, event):
        w = event.widget
        if w.edit_modified():
            self._check()
            self._dirty()
            w.edit_modified(False)

    # ------------------------------------------------------------------ glossary table
    def _rows_to_show(self):
        entries = self.set.entries
        idx = list(range(len(entries)))
        v = gl.validate(entries)
        if self.filter_mode == "dup":
            idx = sorted(set(v.get("dup", [])))
        elif self.filter_mode == "empty":
            idx = sorted(set(v.get("empty", [])))
        elif self.filter_mode == "similar":
            keep = set()
            for _, a, b in self.pairs:
                keep.add(entries.index(a))
                keep.add(entries.index(b))
            idx = sorted(keep)
        needle = self.filter_var.get().strip().lower()
        if needle:
            idx = [i for i in idx if needle in (entries[i].term + " " + entries[i].translation + " " + entries[i].note).lower()]
        return idx

    def _refresh(self):
        entries = self.set.entries
        self.pairs = gl.find_similar(entries) if len(entries) <= 800 else []
        self.tree.delete(*self.tree.get_children())
        for i in self._rows_to_show():
            e = entries[i]
            self.tree.insert("", "end", iid=str(i), values=(e.term, e.translation, e.note))
        self._chips()

    def _chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        v = gl.validate(self.set.entries)
        items = [("Empty", len(set(v.get("empty", []))), "empty"), ("Dup", len(set(v.get("dup", []))), "dup"),
                 ("Similar", len(self.pairs), "similar")]
        lang = self.set.language.strip().lower()
        if lang and lang != self.app.to_var.get().strip().lower() and self.set.entries:
            items.append(("Language", 0, "language"))
        for label, n, mode in items:
            if mode != "language" and not n:
                continue
            text = label if mode == "language" else "%s %d" % (label, n)
            ttk.Button(self.chips, text=text, style="Chip.TButton",
                       command=lambda m=mode: self._set_filter(m)).pack(side="left", padx=(0, 6))
        if self.filter_mode:
            ttk.Button(self.chips, text="✕", style="Chip.TButton", width=3, command=lambda: self._set_filter(None)).pack(side="left")

    def _set_filter(self, mode):
        self.filter_mode = None if mode in (None, "language") else mode
        self._refresh()

    def _flash(self, idx, ms=1400):
        """Show where rows are (new rows, or the row a duplicate matches): scroll to the first and tint all briefly."""
        ids = [str(i) for i in idx]
        if not ids:
            return
        if not all(self.tree.exists(i) for i in ids):  # hidden by a filter
            self.filter_mode = None
            self.filter_var.set("")
            self._refresh()
        self.tree.see(ids[0])
        for i in ids:
            self.tree.item(i, tags=("new",))

        def clear():
            if self.winfo_exists():
                for i in ids:
                    if self.tree.exists(i):
                        self.tree.item(i, tags=())

        self.after(ms, clear)

    def _say(self, text, bad=False):
        self.add_entries[0].say(text, bad)

    def _add(self):
        vals = [gl.norm(v.get().strip()) for v in self.add_vars]
        if not vals[0] and not vals[1]:
            if vals[2]:
                self._say("Not a term", bad=True)
            return
        k = gl.key(vals[0])
        same = [n for n, e in enumerate(self.set.entries) if k and gl.key(e.term) == k]
        for v in self.add_vars:
            v.set("")
        if same:  # never add a second row for a term: show the one that is there
            self._refresh()
            self._flash(same[:1])
            self._say("Already added")
            return
        self.set.entries.append(gl.Entry(*vals))
        self._refresh()
        self._flash([len(self.set.entries) - 1])
        self._dirty()
        self.add_entries[0].focus_set()

    def _delete(self):
        sel = sorted((int(i) for i in self.tree.selection()), reverse=True)
        for i in sel:
            del self.set.entries[i]
        if sel:
            self._refresh()
            self._dirty()

    def _paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        new = gl.from_text(text)
        if new:
            first = len(self.set.entries)
            self.set.entries.extend(new)
            self._refresh()
            self._flash(range(first, len(self.set.entries)))
            self._dirty()
            self._say("Added %d" % len(new))
        return "break"

    def _begin_edit(self, event):
        self._end_edit(commit=False)
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not iid:
            return
        ci = int(col.replace("#", "")) - 1
        x, y, w, h = self.tree.bbox(iid, col)
        entry = tk.Entry(self.tree, background=P["bg2"], foreground=P["text"], insertbackground=P["text"],
                         relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=P["faint"],
                         highlightcolor=P["faint"])
        entry.insert(0, self.tree.set(iid, COLS[ci]))
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, "end")
        entry.bind("<Return>", lambda e: self._end_edit(True))
        entry.bind("<Escape>", lambda e: self._end_edit(False))
        entry.bind("<FocusOut>", lambda e: self._end_edit(True))
        self._edit = (entry, iid, ci)

    def _end_edit(self, commit):
        if not self._edit:
            return
        entry, iid, ci = self._edit
        self._edit = None
        value = gl.norm(entry.get())
        entry.destroy()
        if commit:
            e = self.set.entries[int(iid)]
            fields = {"term": e.term, "translation": e.translation, "note": e.note}
            fields[COLS[ci]] = value
            self.set.entries[int(iid)] = gl.Entry(**fields)
            self._refresh()
            self._dirty()

    def _escape(self):
        if self._edit:
            self._end_edit(False)
        else:
            self.destroy()

    # ------------------------------------------------------------------ import / export
    def import_file(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Glossary", "*.json *.txt *.csv *.tsv"), ("All", "*.*")])
        if not path:
            return
        try:
            incoming = gl.load(path)
        except (OSError, ValueError):
            self._say("Format", bad=True)
            return
        if not self.set.entries:
            self.set.entries = list(incoming)
            self._refresh()
            self._dirty()
            self._say("Added %d" % len(incoming))
            return
        ImportPreview(self, incoming)

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            initialfile=(self.name_var.get() or "glossary") + ".json")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(gl.to_plain_json(self.set.entries))

    def apply_entries(self, entries):
        self.set.entries = list(entries)
        self._refresh()
        self._dirty()


class ImportPreview(tk.Toplevel):
    """Rows of the incoming glossary that differ from the current one. A changed term takes the file's
    translation by default; a new term is left out until its box is ticked (the New box ticks all)."""

    def __init__(self, parent, incoming):
        super().__init__(parent)
        self.parent = parent
        app = parent.app
        self.title("Import")
        self.configure(background=P["bg0"])
        self.geometry("%dx%d" % (app.px(900), app.px(560)))
        self.transient(parent)
        self.current = list(parent.set.entries)
        self.incoming = incoming
        self.rows = [r for r in gl.diff_rows(self.current, incoming) if r[0] in ("diff", "new")]
        self.take = {i: r[0] == "diff" for i, r in enumerate(self.rows)}
        pad = app.px(16)
        top = ttk.Frame(self, padding=(pad, pad, pad, 8))
        top.pack(fill="x")
        ttk.Button(top, text="Apply", command=self._apply).pack(side="right")
        ttk.Button(top, text="Current", command=lambda: self._set_all("diff", False)).pack(side="right", padx=(0, 8))
        ttk.Button(top, text="File", command=lambda: self._set_all("diff", True)).pack(side="right", padx=(0, 8))
        self.new_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="New", variable=self.new_var,
                        command=lambda: self._set_all("new", self.new_var.get())).pack(side="left")
        wrap = ttk.Frame(self, padding=(pad, 0, pad, pad))
        wrap.pack(fill="both", expand=True)
        cols = ("use", "status", "term", "current", "file")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="none")
        for c, t, w in (("use", "", 40), ("status", "", 60), ("term", "Term", 240), ("current", "Current", 280),
                        ("file", "File", 280)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=app.px(w), anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Button-1>", self._click)
        self.bind("<Escape>", lambda e: self.destroy())
        self._fill()

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        for i, (st, cur, inc) in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(i), values=(
                "✓" if self.take[i] else "", st, (cur or inc).term,
                cur.translation if cur else "", inc.translation if inc else ""))

    def _click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.identify_column(event.x) == "#1":
            self.take[int(iid)] = not self.take[int(iid)]
            self.tree.set(iid, "use", "✓" if self.take[int(iid)] else "")

    def _set_all(self, status, value):
        for i, r in enumerate(self.rows):
            if r[0] == status:
                self.take[i] = value
        self._fill()

    def _apply(self):
        skip = {gl.key((c or i).term) for n, (st, c, i) in enumerate(self.rows) if not self.take[n]}
        added = [i for n, (st, c, i) in enumerate(self.rows) if st == "new" and self.take[n]]
        incoming = [e for e in self.incoming if gl.key(e.term) not in skip]
        merged, _ = gl.merge(self.current, incoming, union=False)
        self.parent.apply_entries(merged + added)
        self.destroy()
