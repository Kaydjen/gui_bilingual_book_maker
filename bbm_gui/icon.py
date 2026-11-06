"""The application icon, drawn in code (no image files): two text lines, one of them the accent colour."""
import struct
import zlib

BG = (31, 35, 41)
LINE = (223, 228, 234)
ACCENT = (242, 177, 58)


def _pixels(size):
    px = []
    pad = size // 6
    bar_h = max(size // 9, 2)
    rows = [  # (top, left, right, colour)
        (size * 30 // 100, pad, size - pad, LINE),
        (size * 52 // 100, pad, size - pad * 2, ACCENT),
        (size * 74 // 100, pad, size - pad * 3, LINE),
    ]
    for y in range(size):
        row = []
        for x in range(size):
            colour = BG
            for top, left, right, c in rows:
                if top <= y < top + bar_h and left <= x < right:
                    colour = c
            row.append(colour)
        px.append(row)
    return px


def png_bytes(size=64):
    raw = b"".join(b"\x00" + b"".join(bytes(c) for c in row) for row in _pixels(size))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico_bytes(size=64):
    """A Windows icon file that wraps one PNG image."""
    png = png_bytes(size)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), 22)
    return header + entry + png
