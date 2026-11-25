"""Plain data to JSON and back, for the helper process protocol (one JSON object per line).

Kept apart: tuples (`{"__t": [...]}`), sets (`{"__s": [...]}`), dicts with non-string keys (`{"__d": [[k, v]]}`),
compiled patterns (`{"__re": [pattern, flags]}`) and dataclasses of this program or the core
(`{"__c": "module:Class", "f": {...}}`). Anything else that JSON cannot carry is refused (TypeError): a live
object never crosses a process boundary.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import re

_OK_MODULES = ("novelgui.", "novelcore.")


def encode(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, list):
        return [encode(x) for x in obj]
    if isinstance(obj, tuple):
        return {"__t": [encode(x) for x in obj]}
    if isinstance(obj, (set, frozenset)):
        return {"__s": [encode(x) for x in sorted(obj, key=repr)]}
    if isinstance(obj, dict):
        if all(isinstance(k, str) and not k.startswith("__") for k in obj):
            return {k: encode(v) for k, v in obj.items()}
        return {"__d": [[encode(k), encode(v)] for k, v in obj.items()]}
    if isinstance(obj, re.Pattern):
        return {"__re": [obj.pattern, int(obj.flags)]}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        cls = type(obj)
        name = "%s:%s" % (cls.__module__, cls.__qualname__)
        if not cls.__module__.startswith(_OK_MODULES):
            raise TypeError("not plain data: %s" % name)
        return {"__c": name, "f": {f.name: encode(getattr(obj, f.name)) for f in dataclasses.fields(obj)
                                   if f.init}}
    raise TypeError("not plain data: %s" % type(obj).__name__)


def _class(name: str):
    mod, _, qual = name.partition(":")
    if not mod.startswith(_OK_MODULES):
        raise ValueError("refused class %s" % name)
    obj = importlib.import_module(mod)
    for part in qual.split("."):
        obj = getattr(obj, part)
    if not dataclasses.is_dataclass(obj):
        raise ValueError("not a dataclass: %s" % name)
    return obj


def decode(obj):
    if isinstance(obj, list):
        return [decode(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    if len(obj) == 1:
        (k, v), = obj.items()
        if k == "__t":
            return tuple(decode(x) for x in v)
        if k == "__s":
            return set(decode(x) for x in v)
        if k == "__d":
            return {_key(decode(a)): decode(b) for a, b in v}
        if k == "__re":
            return re.compile(v[0], v[1])
    if "__c" in obj and set(obj) == {"__c", "f"}:
        cls = _class(obj["__c"])
        return cls(**{k: decode(v) for k, v in obj["f"].items()})
    return {k: decode(v) for k, v in obj.items()}


def _key(k):
    return tuple(k) if isinstance(k, list) else k


def dumps(obj) -> bytes:
    """One protocol line (ASCII, ends with a newline)."""
    return (json.dumps(encode(obj), ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")


def loads(line) -> object:
    if isinstance(line, (bytes, bytearray)):
        line = line.decode("utf-8")
    return decode(json.loads(line))
