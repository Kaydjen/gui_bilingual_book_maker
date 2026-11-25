"""The window's facade over `novelcore`, kept as one name for the Tk window: everything lives in
`novelgui.facade` (books, terms, run, checks, quota) and is re-exported here unchanged."""

from __future__ import annotations

from .facade.books import *  # noqa: F401,F403
from .facade.books import _broken_reason, _local, _series_info  # noqa: F401
from .facade.checks import *  # noqa: F401,F403
from .facade.quota import *  # noqa: F401,F403
from .facade.run import *  # noqa: F401,F403
from .facade.terms import *  # noqa: F401,F403
from .facade.terms import _doc_add_confirmed  # noqa: F401
from .lanes import Want  # noqa: F401
