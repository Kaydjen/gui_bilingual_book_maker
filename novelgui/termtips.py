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
