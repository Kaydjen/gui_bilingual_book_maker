"""Tab order of the window (window_spec 10.7): the order a person reads the screen in, row by row, left to right.

Pure: boxes in, an order out. The Tk side (keyboard.py) collects the boxes of the controls on screen.
"""

from __future__ import annotations


def reading_order(boxes) -> list:
    """`boxes`: (key, x, y, height) of controls, y and x in screen pixels. The keys sorted into rows (controls whose
    vertical middles lie within 60 % of a row's height of the row's first control share a row), each row by x."""
    items = sorted(boxes, key=lambda b: (b[2] + b[3] / 2.0, b[1]))
    rows: list = []
    for key, x, y, h in items:
        mid = y + h / 2.0
        if rows and mid - rows[-1]["mid"] <= 0.6 * max(1.0, rows[-1]["h"]):
            rows[-1]["items"].append((x, key))
            rows[-1]["h"] = max(rows[-1]["h"], h)
        else:
            rows.append({"mid": mid, "h": h, "items": [(x, key)]})
    out = []
    for r in rows:
        out.extend(k for _x, k in sorted(r["items"], key=lambda t: t[0]))
    return out


def step(order, current, delta: int):
    """The key after (delta 1) or before (delta -1) `current` in `order`, wrapping round. `current` not in the order
    (or None) gives the first key going forward and the last one going back. None for an empty order."""
    if not order:
        return None
    if current not in order:
        return order[0] if delta >= 0 else order[-1]
    return order[(order.index(current) + (1 if delta >= 0 else -1)) % len(order)]
