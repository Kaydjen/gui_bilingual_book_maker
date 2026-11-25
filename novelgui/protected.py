"""The protected-book check of Add book (window_spec 14.7), until the core has its own (C14).

A file with `META-INF/encryption.xml` is not always protected: fonts are often only obfuscated (the IDPF and Adobe
algorithms). The file is refused when something that is not a font is encrypted. No Qt, standard library only; the check
reads one small member of the zip, so it is cheap even for a big book.
"""

from __future__ import annotations

import posixpath
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

ENCRYPTION = "META-INF/encryption.xml"
FONT_ALGORITHMS = ("http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC")
FONT_SUFFIXES = (".otf", ".ttf", ".ttc", ".woff", ".woff2", ".eot")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def encrypted_non_fonts(path) -> list:
    """The members of the EPUB that are encrypted and are not fonts (empty = readable). An encryption.xml that cannot be
    read counts as protection: nothing can be said about what it hides. Raises zipfile.BadZipFile / OSError for a file
    that is not a zip (the caller has its own reading check)."""
    with zipfile.ZipFile(path) as z:
        if ENCRYPTION not in z.namelist():
            return []
        raw = z.read(ENCRYPTION)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return [ENCRYPTION]
    out = []
    for data in root.iter():
        if _local(data.tag) != "EncryptedData":
            continue
        algorithm = uri = ""
        for el in data.iter():
            name = _local(el.tag)
            if name == "EncryptionMethod":
                algorithm = el.get("Algorithm", "")
            elif name == "CipherReference":
                uri = urllib.parse.unquote(el.get("URI", ""))
        font = algorithm in FONT_ALGORITHMS or posixpath.splitext(uri)[1].lower() in FONT_SUFFIXES
        if not font:
            out.append(uri or "?")
    return out


def is_protected(path) -> bool:
    return bool(encrypted_non_fonts(path))
