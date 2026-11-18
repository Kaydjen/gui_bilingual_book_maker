#!/bin/sh
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python) || { echo "Python 3.11 or newer is required." >&2; exit 1; }
exec "$PY" novel.pyw "$@"
