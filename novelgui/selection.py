"""The chapter selection shared by the steps: one book and a set of chapter positions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Selection:
    book: str = ""
    indices: tuple = ()          # ascending chapter positions

    def __len__(self) -> int:
        return len(self.indices)

    def __bool__(self) -> bool:
        return bool(self.indices)

    @property
    def signature(self) -> tuple:
        return (self.book, self.indices)

    def spans(self) -> list[tuple[int, int]]:
        """Runs of consecutive positions: (3, 3), (10, 14) ..."""
        out: list[tuple[int, int]] = []
        for i in self.indices:
            if out and out[-1][1] == i - 1:
                out[-1] = (out[-1][0], i)
            else:
                out.append((i, i))
        return out


def make(book: str, indices) -> Selection:
    return Selection(book, tuple(sorted(set(int(i) for i in indices))))


def summary(sel: Selection, chapters: int, blocks: int, complete: bool = True) -> str:
    """The dim line of the header: '55 chapters · 1 204 blocks'."""
    if not sel:
        return ""
    word = "chapter" if chapters == 1 else "chapters"
    unit = "block" if blocks == 1 else "blocks"
    more = "" if complete else "+"
    return "%d %s · %s%s %s" % (chapters, word, format(blocks, ",").replace(",", " "), more, unit)
