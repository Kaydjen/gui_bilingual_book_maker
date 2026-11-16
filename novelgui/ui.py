"""Shared UI context handed to every view: root, fonts, tooltip, popups, worker, settings, file dialogs."""

from __future__ import annotations

from tkinter import filedialog

from .theme import Fonts
from .tooltip import Tip
from .widgets import ListPopup
from .worker import Worker


class Dialogs:
    """Native file dialogs behind one object so checks can replace them."""

    def __init__(self, root):
        self.root = root

    def choose_folder(self, initial: str = "") -> str:
        return filedialog.askdirectory(parent=self.root, initialdir=initial or None, mustexist=True) or ""

    def open_epub(self) -> str:
        return filedialog.askopenfilename(parent=self.root, filetypes=[("EPUB", "*.epub")]) or ""

    def open_json_files(self) -> list:
        return list(filedialog.askopenfilenames(parent=self.root, filetypes=[("JSON", "*.json")]) or ())

    def save_json(self, name: str) -> str:
        return filedialog.asksaveasfilename(parent=self.root, initialfile=name, defaultextension=".json",
                                            filetypes=[("JSON", "*.json")]) or ""


class UI:
    def __init__(self, root, settings, fonts: Fonts):
        self.root = root
        self.settings = settings
        self.fonts = fonts
        self.font = fonts.normal
        self.bold = fonts.bold
        self.big = fonts.big
        self.small = fonts.small
        self.ls = fonts.ls
        self.cw = fonts.cw
        self.tip = Tip(root, self.font, self.cw)
        row = int(self.ls * 1.7)
        self.popup = ListPopup(root, self.font, row)       # cell choice lists, type filter
        self.menu = ListPopup(root, self.font, row)        # right-click menu
        self.pick = ListPopup(root, self.font, row)        # "Merge with..." candidates
        self.worker = Worker(root, lanes=("bulk", "search", "fast", "run", "frontier"))
        self.dialogs = Dialogs(root)
