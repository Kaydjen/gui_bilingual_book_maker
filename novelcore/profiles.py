"""Per-language profiles of the target language: prompt file, gender marks, answer-language check,
typography rules, default naming policy.

Nothing language-specific lives outside this module. `get(tag)` accepts `ru`, `RU`, `ru-RU`, `pt_BR`,
`ru:Russian` or an empty string and always returns a profile (a generic one for unknown tags).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"
DEFAULT_PROMPT = "default.txt"

# script name -> predicate on one letter
SCRIPTS = {
    "cyrillic": lambda c: "Ѐ" <= c <= "ԯ",
    "greek": lambda c: "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿",
    "hebrew": lambda c: "֐" <= c <= "׿",
    "arabic": lambda c: "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ",
    "thai": lambda c: "฀" <= c <= "๿",
    "hangul": lambda c: "가" <= c <= "힯" or "ᄀ" <= c <= "ᇿ",
    "han_kana": lambda c: "一" <= c <= "鿿" or "぀" <= c <= "ヿ" or "㐀" <= c <= "䶿",
    "devanagari": lambda c: "ऀ" <= c <= "ॿ",
}
TAG_SCRIPT = {
    **dict.fromkeys(("ru", "uk", "be", "bg", "sr", "mk", "kk"), "cyrillic"),
    "el": "greek", "he": "hebrew", "ar": "arabic", "fa": "arabic", "th": "thai", "ko": "hangul",
    "ja": "han_kana", "zh": "han_kana", "hi": "devanagari",
}
SCRIPT_SHARE = 0.5  # minimum share of target-script letters in an answer

# Detector of an answer left in English, for targets written in the Latin script.
DETECT_MIN_TOKENS = 12  # shorter answers are never judged
ENGLISH_SHARE = 0.2  # share of English function words that marks a text as English
OTHER_SHARE = 0.05  # at most this share of target-language signals
# Function words that are rare in other Latin-script languages (used for every Latin target).
ENGLISH_CORE = frozenset("""the and of with that this his her she from had have has not but they them their you
your said been are which would could there what when who were then than him our its did just about into out
""".split())
# Extra English words that are safe where the target is Polish.
ENGLISH_FOR_PL = ENGLISH_CORE | frozenset("was he it is for as be if at all one".split())
POLISH_WORDS = frozenset("""nie się że na jest z w po jak ale co czy był była było są już tak tylko jego jej
przez od za dla lub oraz który która które mnie ciebie ją mu tu tam bardzo kiedy gdy bo aby jestem są będzie
""".split())
POLISH_LETTERS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")

_TOKEN = re.compile(r"[^\W\d_]+")
_SPLIT = re.compile(r"[-_:]")


def primary_tag(tag) -> str:
    """'ru:Russian' / 'RU' / 'pt_BR' / 'ru-RU' -> 'ru' / 'ru' / 'pt' / 'ru'; '' stays ''."""
    return _SPLIT.split(str(tag or "").strip().lower(), maxsplit=1)[0]


def script_share(text: str, tag: str):
    """Share of letters in the script of language `tag`, or None when the tag has no script entry."""
    name = TAG_SCRIPT.get(primary_tag(tag))
    if name is None:
        return None
    test = SCRIPTS[name]
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum(1 for c in letters if test(c)) / len(letters)


def english_leftover(text: str, english: frozenset, native: frozenset = frozenset(), letters=frozenset()) -> bool:
    """True when `text` is clearly English: enough tokens, a high share of English function words and
    (almost) no signal of the target language (its function words, its special letters)."""
    tokens = [t.lower() for t in _TOKEN.findall(text)]
    n = len(tokens)
    if n < DETECT_MIN_TOKENS:
        return False
    eng = sum(1 for t in tokens if t in english)
    if eng / n < ENGLISH_SHARE:
        return False
    other = sum(1 for t in tokens if t in native or any(c in letters for c in t))
    return other / n <= OTHER_SHARE


@dataclass(frozen=True)
class Profile:
    tag: str
    name: str
    prompt: str = DEFAULT_PROMPT
    send_gender: bool = True
    gender_marks: dict = field(default_factory=dict)
    script: str | None = None  # key of SCRIPTS: an answer must be mostly in it
    english: frozenset = frozenset()  # Latin targets: English words of the leftover detector
    native: frozenset = frozenset()  # Latin targets: words of the target language
    letters: frozenset = frozenset()  # Latin targets: letters that English lacks
    typography: str = ""  # prompt line(s) inserted into the language's own prompt file
    naming: str = ""  # default naming policy for personal names of CJK origin

    def wrong_language(self, text: str):
        """'script' / 'language' when the answer text is not in the target language, else None."""
        if self.script is not None:
            letters = [c for c in text if c.isalpha()]
            if letters:
                test = SCRIPTS[self.script]
                if sum(1 for c in letters if test(c)) / len(letters) < SCRIPT_SHARE:
                    return "script"
            return None
        if self.english and english_leftover(text, self.english, self.native, self.letters):
            return "language"
        return None

    def prompt_text(self) -> str:
        return (PROMPTS / self.prompt).read_text(encoding="utf-8")

    def system_prompt(self, name: str | None = None) -> str:
        return self.prompt_text().replace("{language}", name or self.name)


_GENERIC_MARKS = {"male": "male", "female": "female", "neuter": "neuter", "plural": "plural"}

_UK_TYPO = ("- Typography: quotation marks «…» with „…“ inside them; dialogue is set with an em dash (—) "
            "followed by a space at the start of the line, not with quotation marks.")
_PL_TYPO = ("- Typography: quotation marks „…” with «…» inside them; dialogue is set with an em dash (—) "
            "followed by a space at the start of the line, not with quotation marks.")

PROFILES = {
    "ru": Profile(
        "ru", "Russian", script="cyrillic",
        gender_marks={"male": "м", "female": "ж", "neuter": "ср", "plural": "мн"},
        typography=("quotation marks «…» with „…“ inside them; dialogue with an em dash (—); "
                    "(informational: the Russian prompt is tuned and does not carry this line)"),
        naming=("Chinese personal names: Palladius system; Japanese: Polivanov system; Korean: Kontsevich "
                "system. Nicknames and in-game names: by meaning."),
    ),
    "uk": Profile(
        "uk", "Ukrainian", prompt="uk.txt", script="cyrillic",
        gender_marks={"male": "ч", "female": "ж", "neuter": "с", "plural": "мн"},
        typography=_UK_TYPO,
        naming=("Chinese, Japanese and Korean personal names: transcribe into Ukrainian letters by Ukrainian "
                "practical transcription (the same principles as the Palladius, Polivanov and Kontsevich systems "
                "for Chinese, Japanese and Korean). Nicknames and in-game names: by meaning."),
    ),
    "pl": Profile(
        "pl", "Polish", prompt="pl.txt",
        gender_marks={"male": "m", "female": "ż", "neuter": "n", "plural": "lm"},
        english=ENGLISH_FOR_PL, native=POLISH_WORDS, letters=POLISH_LETTERS,
        typography=_PL_TYPO,
        naming=("Chinese personal names: pinyin without tone marks; Japanese: Hepburn romanization without "
                "macrons; Korean: revised romanization. Nicknames and in-game names: by meaning."),
    ),
}


def get(tag, name: str | None = None) -> Profile:
    """Profile of target `tag`; a generic one (English gender words, script or English-leftover check)
    for a tag without an entry. `name` only fills the language name of a generic profile."""
    key = primary_tag(tag)
    found = PROFILES.get(key)
    if found is not None:
        return found
    return Profile(key, name or key, gender_marks=_GENERIC_MARKS, script=TAG_SCRIPT.get(key),
                   english=ENGLISH_CORE if key not in TAG_SCRIPT else frozenset())


def prompt_text(tag) -> str:
    """The shipped system prompt template for target `tag` (with `{language}`)."""
    return get(tag).prompt_text()


def looks_like(tag, text: str):
    """Optional offline check that Cyrillic `text` is Ukrainian (tag uk) or Russian (tag ru): True / False,
    or None when the text is too short (< 100 letters) or the tag is another one. Never used to reject a block."""
    key = primary_tag(tag)
    if key not in ("uk", "ru"):
        return None
    if sum(1 for c in text if c.isalpha()) < 100:
        return None
    low = text.lower()
    uk_only = any(c in low for c in "іїєґ")
    ru_only = any(c in low for c in "ыэъё")
    if key == "uk":
        return uk_only and not ru_only
    return ru_only and not uk_only
