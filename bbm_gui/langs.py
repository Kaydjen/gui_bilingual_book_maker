"""Target and source languages: one identity (the engine's tag) for the To box, the job folder, the prompt and the
engine call (`--language tag:Name`)."""
from dataclasses import dataclass

# Used until the engine's own table is known (and for an engine that does not report one).
FALLBACK = {
    "en": "english", "ru": "russian", "pl": "polish", "uk": "ukrainian", "de": "german", "fr": "french",
    "es": "spanish", "it": "italian", "pt": "portuguese", "cs": "czech", "ja": "japanese", "ko": "korean",
    "zh": "chinese", "zh-hans": "simplified chinese", "zh-hant": "traditional chinese", "nl": "dutch",
    "tr": "turkish", "ar": "arabic", "sv": "swedish", "fi": "finnish", "el": "greek", "he": "hebrew",
    "hi": "hindi", "hu": "hungarian", "ro": "romanian", "bg": "bulgarian", "sk": "slovak", "da": "danish",
    "no": "norwegian", "vi": "vietnamese", "th": "thai", "id": "indonesian",
}
FAVOURITES = ["Russian", "Polish", "English", "Ukrainian", "German", "French", "Spanish", "Italian", "Portuguese",
              "Czech", "Japanese", "Korean", "Chinese"]

_table = dict(FALLBACK)
_aliases = {}


@dataclass(frozen=True)
class Lang:
    tag: object  # lower-case engine tag, or None when the text is not a language the engine knows
    name: str  # display name (title case) or the text as typed
    known: bool

    def __bool__(self):
        return bool(self.name)


def display(name):
    return name.title() if name == name.lower() else name


def use_table(languages, aliases=None):
    """Take the engine's {tag: name} table (and {name: tag} aliases); an empty one keeps the built-in list."""
    global _table, _aliases
    if isinstance(languages, dict) and languages:
        _table = {str(k).lower(): str(v).lower() for k, v in languages.items()}
        _aliases = {str(k).lower(): str(v).lower() for k, v in (aliases or {}).items() if isinstance(aliases, dict)}
    else:
        _table, _aliases = dict(FALLBACK), {}


def resolve(text, table=None):
    """Text typed by the user -> Lang. Accepts a tag, a name (any case), an alias or `tag:Name`."""
    tbl = table if table is not None else _table
    text = (text or "").strip()
    if not text:
        return Lang(None, "", False)
    if ":" in text:
        tag, _, name = text.partition(":")
        tag, name = tag.strip().lower(), name.strip()
        if tag and name:
            return Lang(tag, name, True)
        return Lang(None, text, False)
    key = text.lower()
    if key in tbl:
        return Lang(key, display(tbl[key]), True)
    by_name = {v: k for k, v in tbl.items()}
    tag = by_name.get(key)
    if tag is None:
        tag = _aliases.get(key) if table is None else None
    if tag is not None and tag in tbl:
        return Lang(tag, display(tbl[tag]), True)
    return Lang(None, text, False)


def engine_value(lang):
    """`tag:Name` for a known language so {language} is always the same capitalised word and the output is stamped
    with the right tag; text the engine does not know is passed as typed."""
    if lang.known and lang.tag:
        return "%s:%s" % (lang.tag, lang.name)
    return lang.name


def display_list(table=None):
    """Names for the To box: the favourites first, then the rest alphabetically."""
    tbl = table if table is not None else _table
    names = {display(v) for v in tbl.values()}
    first = [n for n in FAVOURITES if n in names]
    return first + sorted(names - set(first))


def same(a, b):
    """Two known languages with the same tag."""
    ra, rb = resolve(a), resolve(b)
    return bool(ra.tag and rb.tag and ra.tag == rb.tag)
