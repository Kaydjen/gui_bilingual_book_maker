"""Resume-checkpoint tool. It runs under the engine's own Python (the checkpoint is a pickle written by
that engine) and never imports the engine.

  checkpoint.py inspect <bin> <marker>
  checkpoint.py repair  <bin> <marker> [--drop-fingerprint]

repair cuts the translations at the first failed paragraph (so a resume translates it again) and,
with --drop-fingerprint, removes the record of the model and prompt that wrote the checkpoint.
The file is replaced atomically. stdout is one JSON document.
"""
import json
import os
import pickle
import sys


def _failed(item, marker):
    return isinstance(item, str) and marker in item


def _load(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:1] in (b"[",):
        return "json", json.loads(raw.decode("utf-8"))
    return "pickle", pickle.loads(raw)


def _items(state):
    if isinstance(state, dict):
        return state.get("translations") or []
    return state if isinstance(state, list) else []


def inspect(path, marker):
    kind, state = _load(path)
    items = _items(state)
    first = next((i for i, t in enumerate(items) if _failed(t, marker)), None)
    return {
        "format": kind,
        "shape": "dict" if isinstance(state, dict) else "list",
        "total": len(items),
        "first_failed": first,
        "failed": sum(1 for t in items if _failed(t, marker)),
        "has_fingerprint": bool(isinstance(state, dict) and state.get("run_fingerprint")),
    }


def repair(path, marker, drop_fingerprint):
    kind, state = _load(path)
    items = _items(state)
    first = next((i for i, t in enumerate(items) if _failed(t, marker)), None)
    keep = len(items) if first is None else first
    if isinstance(state, dict):
        state["translations"] = items[:keep]
        if isinstance(state.get("job_ids"), list):
            state["job_ids"] = state["job_ids"][:keep]
        if drop_fingerprint:
            state.pop("run_fingerprint", None)
    else:
        state = items[:keep]
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        if kind == "json":
            f.write(json.dumps(state, ensure_ascii=False).encode("utf-8"))
        else:
            pickle.dump(state, f)
    os.replace(tmp, path)
    return {"before": len(items), "after": keep, "removed": len(items) - keep}


def main():
    cmd, path, marker = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        if cmd == "inspect":
            out = inspect(path, marker)
        elif cmd == "repair":
            out = repair(path, marker, "--drop-fingerprint" in sys.argv[4:])
        else:
            sys.exit("usage")
    except Exception as e:
        out = {"error": "%s: %s" % (type(e).__name__, e)}
    sys.stdout.write(json.dumps(out, ensure_ascii=True))
    sys.exit(2 if "error" in out else 0)


if __name__ == "__main__":
    main()
