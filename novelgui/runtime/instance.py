"""The name of this program instance and its lock file (no Qt: computed first, before anything else starts)."""

from __future__ import annotations

import getpass
import hashlib
import os
import re
from pathlib import Path

from . import paths

ENV_API_BASE = "NOVELGUI_API_BASE"


def user_name() -> str:
    try:
        name = getpass.getuser()
    except Exception:
        name = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "user"


def instance_name() -> str:
    """`novelgui-<user>-<10 hex>`: another data folder or another service address is another instance, so
    scripted runs never meet the owner's window."""
    data = os.path.normcase(str(paths.settings_dir().resolve()))
    base = os.environ.get(ENV_API_BASE) or ""
    digest = hashlib.sha1((data + "|" + base).encode("utf-8")).hexdigest()[:10]
    return "novelgui-%s-%s" % (user_name(), digest)


def lock_path() -> Path:
    return paths.lock_path()
