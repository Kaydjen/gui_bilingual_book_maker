"""Tooltip texts added in stage 3, in one place. A text is a plain explanation; the caller adds the list of
`name  value` facts (see tooltip.py)."""

from __future__ import annotations

# Terms: the dim dash of an empty type / gender / About
UNKNOWN_FIELD = ("Not known yet. A later pass of the model fills it in, or you can write it yourself.",
                 [("Filled by", "the model, or you"), ("You can edit", "yes")])

# Terms: the toggle that narrows the list to the chapters chosen on Books
SELECTED_CHAPTERS = "Show only the terms that occur in the chapters selected on the Books step."

# Settings: the label of the keep-awake row
KEEP_AWAKE_LABEL = "Keep the computer awake while translating"
