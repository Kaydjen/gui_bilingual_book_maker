"""The header's pure logic (window_spec 1.1-1.4): the context line and whether it fits. No Tk, no core imports."""

from __future__ import annotations

from . import pieces

SEP = " · "
MAX_SPANS = 3


def chapters_text(infos, indices) -> str:
    """`chapters 2697-2750`, `chapter 5`, `chapters 1-4, 9-12`: the chosen chapters by the numbers printed in
    their titles (their position when a title has none). Empty without a selection."""
    idx = sorted({i for i in indices if 0 <= i < len(infos)})
    if not idx:
        return ""
    spans = []
    for i in idx:
        if spans and spans[-1][1] == i - 1:
            spans[-1][1] = i
        else:
            spans.append([i, i])
    parts = [pieces.number_label(pieces.number_of(infos[a]), pieces.number_of(infos[b])) for a, b in spans]
    more = " …" if len(parts) > MAX_SPANS else ""
    word = "chapter" if len(idx) == 1 else "chapters"
    return "%s %s%s" % (word, ", ".join(parts[:MAX_SPANS]), more)


def context_line(series: str, volume: str, chapters: str, language: str) -> str:
    """`series · volume · chapters a-b · language`; a part that is not there is left out. Without a series the
    line is empty; without a chosen language the language part is left out (3.6)."""
    if not series:
        return ""
    return SEP.join(p for p in (series, volume, chapters, language) if p)


def crowded(path_w: int, context_w: int, side_w: int, avail_w: int, gap: int) -> bool:
    """True when the path, the context line and the right-hand parts do not fit one header row."""
    if not context_w:
        return False
    return path_w + gap + context_w + gap + side_w > avail_w
