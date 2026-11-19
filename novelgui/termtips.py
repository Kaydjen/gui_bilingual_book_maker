"""Tooltip texts of the Terms screen (core_spec 12c): plain explanation, then a fixed list of facts."""

from __future__ import annotations

FACT_NAMES = ("Comes from", "You can edit", "Translator sees it", "A model can change")

GENDER_WORDS = {"male": "male", "female": "female", "neuter": "neuter", "plural": "plural", "unknown": "unknown"}

HEAD_TIPS = {
    "source": ("The term as it is spelled in the book. The program finds names written with a capital letter, "
               "and the model then reads the chapters and adds the ones the program missed. "
               "This spelling is what is searched for in the text.",
               ("program and model", "yes", "yes", "no")),
    "tr": ("The translation written for this term in every chapter. The model proposes it, looking at the "
           "terms you already have so that related names match. Once you confirm or edit it, it stays as it is.",
           ("model", "yes", "yes", "until confirmed")),
    "type": ("What kind of thing the term is: a character, a place, an item and so on. The model decides it "
             "from the lines of the book where the term occurs. It is used here for filtering.",
             ("model", "yes", "no", "until confirmed")),
    "gender": ("For a character: man or woman. The model takes it from the text, and the program checks it by "
               "counting he and she next to the name. For other terms: the grammatical gender of the "
               "translation. The translator needs it so that verbs and adjectives agree.",
               ("model + he/she count", "yes", "yes", "until confirmed")),
    "first": ("The first chapter of the book where the term is found. The program takes it from the places it "
              "has found the term in. New terms start with the ones that appear earliest, so you meet them in "
              "reading order.",
              ("program", "no", "no", "-")),
    "count": ("How many times the term is mentioned in the chapters the program has read. The program counts "
              "it. Frequent terms matter most.",
              ("program", "no", "no", "-")),
    "note": ("A short line saying who or what the term is. The model writes it from the lines of the book "
             "where the term occurs. It helps you check the translation, and the translator gets it when "
             "the term could be understood in more than one way.",
             ("model", "yes", "when ambiguous", "until confirmed")),
}


def head_tip(key: str):
    t = HEAD_TIPS.get(key)
    if not t:
        return None
    return t[0], list(zip(FACT_NAMES, t[1]))


def question_tip(entry, field: str, marks: dict):
    cands = entry.questions[field]
    if field == "gender":
        text = ("The model and the he / she count next to the name disagree, so the program cannot tell "
                "the gender of this character. Pick any value in the list to settle it.")
        facts = [("Doubtful", "gender")]
        facts += [(GENDER_WORDS.get(c["value"], c["value"]), c.get("evidence", "")) for c in cands]
        facts.append(("Translator sees it", "without the gender"))
    elif field == "tr":
        text = ("Your glossary files give this term different translations and the program does not "
                "choose between them. Pick any value in the list to settle it.")
        facts = [("Doubtful", "translation")]
        facts += [(c["value"], c.get("evidence", "")) for c in cands]
        facts.append(("Answer", "pick any value"))
    else:
        text = ("This term may be another spelling of a term that is already in the list. Pick the term it "
                "stands for, or any other value to settle it.")
        facts = [("Doubtful", "same as")]
        facts += [(c["value"], c.get("evidence", "")) for c in cands]
        facts.append(("Answer", "pick any value"))
    return text, facts


def reader_counter_tip(k: int, n: int, mentions: int, running: bool):
    more = " The search is still running, so the total may grow." if running else ""
    return ("The counter counts paragraphs of the book that mention the term, not single mentions: this is "
            "paragraph %d of %d, and the %d paragraphs hold %d mentions in all.%s" % (k, n, n, mentions, more),
            [("Counts", "paragraphs"), ("Mentions", str(mentions)), ("Searched in", "the whole book")])


def step_tip(text: str, keys: str, k: int, n: int):
    return text, [("Shortcut", keys), ("Place", "%d of %d" % (k, n))]


# ---------------------------------------------------------------- the Terms screen of the QML window (6.7, 9.12, 14.13)
TAB_BLOCKING = ("Terms that stop translating the chapters selected in Books until you confirm them. The same number "
                "as Review N terms on Translate.")
TAB_BLOCKING_NONE = "No chapters selected in Books."
TAB_NOTCONF = ("Every term of the series that is not confirmed yet: the blocking ones, the rest of the book, names found "
               "in the book without a rendering, and confirmed terms an import brought a second rendering for (a choice).")
TAB_CONFIRMED = "Confirmed terms with no open question: the translation uses exactly these. Edit in place."
SEARCH = "Search (Ctrl+F, or just start typing)"
SEARCH_CLEAR = "Clear and close (Esc)"
MORE = "Import, Export"
MORE_BUSY = "Importing…"
HEAD_TO_EMPTY = "Choose the language to translate into. Renderings depend on it."
HEAD_TO = "Rendering in %s. Double-click or Enter to edit."
HEAD_TYPE = "Show one type only."
HEAD_TYPE_SET = "Only %s. Click: another type or all."
NO_LANGUAGE = "Choose the language first."
NO_RENDERING = "No rendering yet. Type it and press Enter: the term becomes confirmed."
CELL_EDIT = "Enter takes it, Tab: next cell, Esc: back to %s."
MERGE = "Make the ticked terms one entry: the others become its other spellings (also)."
NOT_A_TERM = "Never suggest these again."
NEUTER = "neuter: a creature or a thing"
PREV_PLACE = "Previous place (Alt+Left)"
NEXT_PLACE = "Next place (Alt+Right)"
SCANNING = ("Looking for the series' terms in every chapter: fills Count and First, adds names without a rendering, finds "
            "what blocks the selected chapters.")
IMPORT_GOES = ("Confirmed: the translation uses these terms as they are (your own, checked glossary).<br>Not confirmed: they "
               "wait in Terms for your check.<br>Leave terms out or confirm part of them after the import: Show imported.")
IMPORT_WHERE = "Where the terms of each file land in Terms. Click a value to change it."
SHOW_IMPORTED = "Show only the terms of this import: leave some out (Delete), confirm part of them, pick the choices."
IMPORTED_CHIP = "Only the %d terms of the last import. ✕ or Esc: all terms."
ENGLISH_LATER = "Comes with a later program change"
SHOW_FOLDER = "Opens the folder with the saved file."
GO_TRANSLATE = "Opens Translate with chapters %s. Does not start."


def confirm_tip(n: int) -> str:
    return ("Accept the %d terms with one value in this list as they are:<br>· translation uses exactly them and they stop "
            "holding it up;<br>· the model will not change them later;<br>· they move to Confirmed, where you can still "
            "edit them.<br>Left: rows with two values (click the right one) and names without a rendering (type it)." % n)


def chip_tip(value: str, source: str) -> str:
    where = "In use now." if source in ("", "in use") else "From %s." % source
    return "%s Click: use %s and tick the row (Confirm takes it).<br>Double-click the cell to type another." % (where, value)
