"""The settings panel: keys, models, pace, keep-awake. Opened from the gear in the header."""

from __future__ import annotations

import tkinter as tk

from . import keystore, model, platform, tips
from .dialog import Modal
from .settings import DEFAULT_MODEL, old_data_dir
from .theme import BG, BRIGHT, DIM, FAINT, S1, S2, S4, TEXT
from .tooltip import attach_tip
from .translate_parts import dark_text
from .vtable import Col, VTable
from .widgets import Field, Pill, Segmented


class _List(VTable):
    def __init__(self, master, ui, shown):
        super().__init__(master, ui, [Col("v", "", None, sortable=False)], header=False, resizable=False)
        self.shown = shown

    def draw_cells(self, c, row, cols, y, mid):
        x, w = cols["v"]
        c.create_text(x + self.pad, y + mid, text=self.fit(self.shown(row), w - 2 * self.pad), anchor="w",
                      font=self.font, fill=TEXT)


def model_list(settings) -> list:
    raw = settings.get("models")
    out = [m for m in raw if isinstance(m, str) and m.strip()] if isinstance(raw, list) else []
    return out or [DEFAULT_MODEL]


class SettingsPanel(Modal):
    def __init__(self, ui, app, on_close=None):
        super().__init__(ui, on_close)
        self.app = app
        self._built = False
        self.settings = ui.settings
        f = ui.font
        pad, gap = self.pad, int(ui.ls * 0.6)
        body = self.body
        self.models = model_list(self.settings)
        width = ui.cw * 56

        def label(text):
            lab = tk.Label(body, text=text, bg=S2, fg=DIM, font=f, anchor="w")
            lab.pack(anchor="w", padx=pad, pady=(gap, 2))
            return lab

        # keys
        keys_label = label("Keys")
        self.keys = _List(body, ui, keystore.mask)
        self.keys.body.configure(width=width, height=int(ui.ls * 5.2))
        self.keys.pack(fill="x", padx=pad)
        self.keys.on_changed = self._update
        self.keys.wire_tips()
        self.keys.set_rows(list(app.keystore.keys))
        row = tk.Frame(body, bg=S2)
        row.pack(fill="x", padx=pad, pady=(gap // 2, 0))
        self.remove_btn = Pill(row, "Remove", self._remove_keys, f, kind="dim", bg=S2)
        self.remove_btn.pack(side="left")
        self.import_btn = Pill(row, "Import keys from the old app", self._import_keys, f, kind="dim", bg=S2)
        paste_label = label("Add keys")
        self.paste = dark_text(body, ui, height=3, editable=True, bg=S1)
        self.paste.pack(fill="x", padx=pad)
        self.paste.bind("<KeyRelease>", lambda e: self._update())
        arow = tk.Frame(body, bg=S2)
        arow.pack(fill="x", padx=pad, pady=(gap // 2, 0))
        self.add_btn = Pill(arow, "Add", self._add_keys, f, bg=S2)
        self.add_btn.pack(side="left")
        paste_tip = lambda e: (
            "Paste one key, or several, one per line, and press Add. Text that is not a key is left out.",
            [("Stored in", "the app data folder"), ("Shown as", "dots and the last 4 characters")])
        keys_tip = lambda e: (
            "Your API keys. Each key from a separate Google project brings its own daily quota. A key is never "
            "shown in full.", [("Stored in", "keys.json"), ("Never", "in a series or a log")])
        attach_tip(self.paste, ui.tip, paste_tip)
        attach_tip(paste_label, ui.tip, paste_tip)
        attach_tip(self.keys, ui.tip, keys_tip)
        attach_tip(keys_label, ui.tip, keys_tip)
        attach_tip(self.import_btn, ui.tip, lambda e: (
            "Copy the keys of the earlier app. They are not shown; the earlier app keeps its own copy.",
            [("Offered", "only while this app has no keys")]))

        # models
        models_label = label("Models")
        self.mlist = _List(body, ui, lambda m: m)
        self.mlist.body.configure(width=width, height=int(ui.ls * 3.2))
        self.mlist.pack(fill="x", padx=pad)
        self.mlist.on_changed = self._update
        self.mlist.set_rows(list(self.models))
        mrow = tk.Frame(body, bg=S2)
        mrow.pack(fill="x", padx=pad, pady=(gap // 2, 0))
        self.model_field = Field(mrow, f, on_submit=lambda s: self._add_model(), bg=S2, width=ui.cw * 30, surface=S1)
        self.model_field.pack(side="left")
        self.model_add = Pill(mrow, "Add", self._add_model, f, bg=S2)
        self.model_add.pack(side="left", padx=(gap // 2, 0))
        self.model_up = Pill(mrow, "Up", self._model_up, f, kind="dim", bg=S2)
        self.model_up.pack(side="left", padx=(gap // 2, 0))
        self.model_del = Pill(mrow, "Remove", self._remove_model, f, kind="dim", bg=S2)
        self.model_del.pack(side="left", padx=(gap // 2, 0))
        models_tip = lambda e: (
            "The models to translate with, in order of preference. The first one is used until its quota is gone.",
            [("Default", DEFAULT_MODEL), ("Order", "top is used first")])
        attach_tip(self.mlist, ui.tip, models_tip)
        attach_tip(models_label, ui.tip, models_tip)

        # pace
        pace_label = label("Pace")
        prow = tk.Frame(body, bg=S2)
        prow.pack(fill="x", padx=pad)
        self.pace = Field(prow, f, on_commit=self._commit_pace, bg=S2, width=ui.cw * 8, surface=S1)
        self.pace.pack(side="left")
        cur = self.settings.get("pace")
        self.pace.set(str(int(cur)) if isinstance(cur, (int, float)) and not isinstance(cur, bool)
                      else str(model.default_pace()))
        pace_tip = lambda e: (
            "Requests a minute in total. One even rate is used for all keys together, because the service answers "
            "'too many requests' for the whole computer, not per key; more keys add daily quota, not speed.",
            [("Range", "1 to 120"), ("Default", str(model.default_pace())), ("Applies to", "every key")])
        attach_tip(self.pace.entry, ui.tip, pace_tip)
        attach_tip(pace_label, ui.tip, pace_tip)

        # keep awake
        krow = tk.Frame(body, bg=S2)
        krow.pack(fill="x", padx=pad, pady=(gap, 0))
        awake_label = tk.Label(krow, text=tips.KEEP_AWAKE_LABEL, bg=S2, fg=DIM, font=f)
        awake_label.pack(side="left", padx=(0, gap))
        self.awake = Segmented(krow, f, self._awake_picked, bg=S2)
        self.awake.set_items([("off", "Off", None), ("on", "On", None)],
                             "on" if self.settings.get("keep_awake") else "off")
        self.awake.pack(side="left")
        awake_tip = lambda e: (
            "Stop the computer from going to sleep while a translation runs. It is released when the run ends.",
            [("Default", "off"), ("Only while", "a job runs")])
        attach_tip(self.awake, ui.tip, awake_tip)
        attach_tip(awake_label, ui.tip, awake_tip)

        # library (2.4)
        lrow = tk.Frame(body, bg=S2)
        lrow.pack(fill="x", padx=pad, pady=(gap, 0))
        lib_label = tk.Label(lrow, text="Library", bg=S2, fg=DIM, font=f)
        lib_label.pack(side="left", anchor="n", padx=(0, gap))
        self.change_btn = Pill(lrow, "Change", self._change_library, f, kind="dim", bg=S2)
        self.change_btn.pack(side="right", anchor="n", padx=(gap, 0))
        self.lib_path = tk.Label(lrow, text=str(app.library or "not chosen"), bg=S2, fg=TEXT, font=f, anchor="w",
                                 justify="left", wraplength=ui.cw * 40, cursor="hand2" if app.library else "arrow")
        self.lib_path.pack(side="left", fill="x", expand=True)
        self.lib_path.bind("<ButtonRelease-1>", lambda e: self._open_library())
        self.lib_path.bind("<Enter>", lambda e: self.lib_path.configure(fg=BRIGHT))
        self.lib_path.bind("<Leave>", lambda e: self.lib_path.configure(fg=TEXT))
        self._lib_reason = app.library_block_reason()
        self.change_btn.set_enabled(not self._lib_reason)
        lib_tip = lambda e: tips.LIBRARY_PATH
        attach_tip(self.lib_path, ui.tip, lib_tip)
        attach_tip(lib_label, ui.tip, lib_tip)
        attach_tip(self.change_btn, ui.tip, lambda e: (self._lib_reason or None) if not self.change_btn.enabled
                   else tips.LIBRARY_CHANGE)

        close = tk.Frame(body, bg=S2)
        close.pack(fill="x", padx=pad, pady=(gap, 0))
        Pill(close, "Close", self.close, f, bg=S2).pack(side="right")
        self._built = True
        self._update()
        self.show()

    # ------------------------------------------------------------- keys
    def _update(self):
        if not self._built:
            return
        ks = self.app.keystore
        self.add_btn.set_enabled(bool(keystore.parse_keys(self.paste.get("1.0", "end-1c"))))
        self.remove_btn.set_enabled(bool(self.keys.selected_rows()))
        old = bool(not ks.keys and keystore.old_app_keys(old_data_dir()))
        if old and not self.import_btn.winfo_ismapped():
            self.import_btn.pack(side="left", padx=(self.pad // 2, 0))
        elif not old and self.import_btn.winfo_ismapped():
            self.import_btn.pack_forget()
        sel = self.mlist.selected_rows()
        self.model_del.set_enabled(bool(sel) and len(self.models) > 1)
        self.model_up.set_enabled(bool(sel) and self.models.index(sel[0]) > 0)
        self.model_add.set_enabled(bool(self.model_field.get().strip()))

    def _refresh_keys(self):
        self.keys.set_rows(list(self.app.keystore.keys))
        self._update()
        self.app.keys_changed()

    def _add_keys(self):
        self.app.keystore.add(self.paste.get("1.0", "end-1c"))
        self.paste.delete("1.0", "end")
        self._refresh_keys()

    def _remove_keys(self):
        for k in list(self.keys.selected_rows()):
            self.app.keystore.remove(k)
        self._refresh_keys()

    def _import_keys(self):
        found = keystore.old_app_keys(old_data_dir())
        if found:
            self.app.keystore.add("\n".join(found))
        self._refresh_keys()

    # ------------------------------------------------------------- models
    def _save_models(self):
        self.settings.set("models", list(self.models))
        self.mlist.set_rows(list(self.models))
        self._update()
        self.app.keys_changed()

    def _add_model(self):
        name = self.model_field.get().strip()
        if name and name not in self.models:
            self.models.append(name)
            self.model_field.set("")
            self._save_models()

    def _remove_model(self):
        sel = self.mlist.selected_rows()
        if sel and len(self.models) > 1:
            self.models.remove(sel[0])
            self._save_models()

    def _model_up(self):
        sel = self.mlist.selected_rows()
        if sel:
            i = self.models.index(sel[0])
            if i > 0:
                self.models[i - 1], self.models[i] = self.models[i], self.models[i - 1]
                self._save_models()
                self.mlist.select_index(i - 1)

    # ------------------------------------------------------------- pace, awake
    def _commit_pace(self, text=None):
        """Take the typed pace. False (the field goes back to the stored value and flashes) when it is not a
        number from 1 to 120."""
        text = (self.pace.get() if text is None else text).strip()
        try:
            p = model.clean_pace(text)
        except ValueError:
            return False
        self.settings.set("pace", None if p is None else (int(p) if p == int(p) else p))
        self.pace.set(str(int(p)) if p is not None and p == int(p) else (str(p) if p is not None
                                                                          else str(model.default_pace())))
        self.app.keys_changed()
        return True

    def close(self):
        if self.is_open:
            self.pace.commit()
        super().close()

    def _open_library(self):
        if self.app.library:
            platform.open_folder(self.app.library)

    def _change_library(self):
        """Choose another folder; the panel closes once the library is changed."""
        self.app.change_library(on_done=self.close)

    def _awake_picked(self, key):
        self.settings.set("keep_awake", key == "on")
