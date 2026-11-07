"""Which flags the user may set by hand. One place, used by the flag form, the extra-flags field and the migration."""

# Flags the application sets itself or that would break it: a user entry for them is refused.
OWNED = frozenset({
    "--book_name", "--language", "--source_lang", "--single_translate", "--prompt",
    "--model", "--model_list", "--key", "--api_key", "--provider",
    "--glossary", "--glossary-auto", "--resume", "--help",
})

# Pace flags: set by the Pace slot (the interval is computed, grouping is chosen in the Pace window).
# --accumulated_num is not offered at all: on this route the engine keeps no progress or checkpoint for it.
PACE = frozenset({"--interval", "--block_size", "--accumulated_num"})
PACE_OWNED = True

# Flags that are never kept between sessions: a forgotten one would silently change the next book.
TRANSIENT = frozenset({"--test", "--test_num", "--retranslate", "--plan-dry-run"})

# Flags that only make sense next to another one (--test carries its number) and are not offered on their own.
COMPANIONS = frozenset({"--test_num"})

REASON_OWNED ="Set in the main window"

# Which tags the engine translates. Its own default is `p` only, which leaves headings, list items, table cells and
# captions in the source language; the presets list every text-carrying tag instead.
TAGS_FLAG = "--translate-tags"
EXCLUDE_TAGS_FLAG = "--exclude-translate-tags"
DEFAULT_TAGS = "p,h1,h2,h3,h4,h5,h6,li,blockquote,dt,dd,figcaption,td,th"


def is_owned(flag_id):
    return flag_id in OWNED or (PACE_OWNED and flag_id in PACE)


def is_transient(flag_id):
    return flag_id in TRANSIENT
