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

# Books: actions of a series row and of a volume
SERIES_ACTIONS = ("Actions for this series: rename it, open its folder, delete it.",
                  [("Rename", "changes the shown name only"), ("Delete", "moves it to .deleted")])
VOLUME_ACTIONS = ("Actions for this volume: rename it or remove it from the series.",
                  [("Rename", "changes the shown label only"), ("Remove", "moves its files to .deleted")])
BROKEN_SERIES = "This series cannot be opened: %s."

# Add book panel
ADD_VOLUME_OF = ("The file becomes another book of this series. The glossary, the language and the settings "
                 "of the series are shared by all its books.",
                 [("Copies the file", "into the series folder"), ("Original", "stays where it is")])
ADD_NEW_SERIES = ("A separate series with its own glossary, language and settings. The file is copied into it.",
                  [("Copies the file", "into the new folder"), ("Original", "stays where it is")])
ADD_SERIES_NAME = ("The name of the series as the list shows it. Its folder in the library is named after it.",
                   [("Must be", "unused in the library")])
ADD_SERIES_NAME_FIXED = "The name of the series this volume goes to. Change it with Rename in the series menu."

# Settings: the library row
LIBRARY_PATH = ("The folder that holds every series. Click to open it.",
                [("Kept in", "this app's settings"), ("Series", "one sub-folder each")])
LIBRARY_CHANGE = ("Choose another folder for the library. Series in the old folder are not moved.",
                  [("Needs", "no running translation")])

# Deleting and removing: why it is not possible now
CANNOT_NOW = "%s Try again when it has ended."

# Books: the typed range
CHAPTERS_FIELD = ("Type chapter numbers as they are printed in the titles, for example 2729-2783 or 5, 9-12, and "
                  "press Enter. A number the book does not have is left out; when no title carries a number "
                  "in the range, the numbers are taken as the No. of the list.",
                  [("Format", "a-b, or a, b, c-d"), ("Counts", "title numbers"), ("Fallback", "position")])

# First start
FIRST_START_PATH = ("The folder that will hold every series, with its books and translations. A new folder is "
                    "created; a folder that already holds series is used as it is.",
                    [("Default", "Novel library, in Documents"), ("Kept in", "this app's settings")])
FIRST_START_CREATE = "Use this folder as the library."

# Languages (window 3.x)
TO_EMPTY = ("Choose the language this series is translated into. Run, Sample and the terms need it.",
            [("Applies to", "this series"), ("Changes", "until a block is translated or a term is confirmed")])
TO_CHOSEN = ("The language this series is translated into. The prompt and the terms use it.",
             [("Applies to", "this series"), ("Changes", "until a block is translated or a term is confirmed")])
TO_BUSY = "The language is read when a translation starts. %s Change it after it has ended."
TO_OTHER_FIELD = ("The language as tag:Name. The tag is its short code, the name is how the translator is told to "
                  "call it.", [("Format", "tag:Name"), ("Example", "de:German"), ("Tag", "two or three letters")])
NEED_LANGUAGE = "Choose the language first: To, next to Prompt on the Translate step, or the column heading here."
TERMS_TO_HEAD = ("The language the terms are translated into. Choose it here or on the Translate step; the "
                 "renderings in this column depend on it.",
                 [("Applies to", "this series"), ("Same setting as", "To on Translate")])
SERIES_NO_LANGUAGE = "No language chosen yet. Choose it with To on the Translate step."
