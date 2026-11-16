"""Base class of a window step. A step is a frame registered with `App.register_step`; the App calls its hooks.

Seams for a new step (e.g. Translate): subclass `Step`, set `key` and `label`, build the content in
`__init__`, and register it: `app.register_step(MyStep)`. Shared state lives on the App:
`app.series`, `app.book`, `app.selection`, `app.infos`, `app.ui.worker`.
"""

from __future__ import annotations

import tkinter as tk

from .theme import BG


class Step(tk.Frame):
    key = ""
    label = ""

    def __init__(self, master, app):
        super().__init__(master, bg=BG)
        self.app = app
        self.ui = app.ui

    def on_show(self) -> None:
        """The step became the visible one."""

    def on_hide(self) -> None:
        """Another step is about to be shown."""

    def on_series(self) -> None:
        """The current series changed (or was cleared)."""

    def on_book(self) -> None:
        """The current book of the series changed."""

    def on_selection(self) -> None:
        """The chapter selection changed."""

    def shutdown(self) -> None:
        """The window is closing: flush what must be kept."""
