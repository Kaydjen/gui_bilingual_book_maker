"""Constants shared by the Terms screen modules."""

from __future__ import annotations

TYPES = ["character", "organization", "place", "item", "skill", "title", "class", "creature", "term"]
OTHER = "\x00other"                       # choice-list key: type your own value
# question field of the core -> table column that shows it, and the other way round for storing a value
QUESTION_COL = {"gender": "gender", "tr": "tr", "same_as": "source"}
FIELD_OF = {"source": "same_as", "tr": "tr", "type": "type", "gender": "gender", "note": "note"}
