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
