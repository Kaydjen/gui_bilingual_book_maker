"""Form state -> argv list (the truth) -> display strings per shell (a view, never executed)."""
import os
import re
import shlex

from . import widgetkinds

MASK = "********"


def long_opt(f):
    longs = [o for o in f["options"] if o.startswith("--")]
    return longs[0] if longs else f["options"][0]


def kind_of(f, overlay):
    ov = (overlay or {}).get("flag", {}).get(f["id"], {})
    return ov.get("widget") or widgetkinds.infer(f)[0]


def is_secret(f, overlay):
    ov = (overlay or {}).get("flag", {}).get(f["id"], {})
    return bool(ov.get("secret")) or kind_of(f, overlay) == "secret"


COMPANIONS = {"--test": "--test_num"}  # "--test" may carry a number: it is emitted as "--test --test_num=N"


def build_argv(inv, state, overlay=None, mask=False):
    """state: {flag_id: value}. An absent key, None or '' means untouched and is not emitted: a typed default
    differs from silence for this engine. Flags missing from the inventory, and a companion value that would
    be ignored by the engine (--test_num without --test), are returned in `dropped`."""
    byid = {f["id"]: f for f in inv["flags"]}
    items = []
    dropped = []
    state = dict(state)
    for main, comp in COMPANIONS.items():
        val = state.get(main)
        if val not in (None, "", False, True) and comp in byid:
            state[main] = True
            state[comp] = val
        elif comp in state and not state.get(main):
            if state[comp] not in (None, ""):
                dropped.append(comp)
            del state[comp]
    for fid, val in state.items():
        f = byid.get(fid)
        if f is None:
            dropped.append(fid)
            continue
        if val is None or val == "" or val == []:
            continue
        items.append((f.get("order", 0), f, val))
    items.sort(key=lambda t: t[0])
    argv = []
    for _, f, val in items:
        kind = kind_of(f, overlay)
        opt = long_opt(f)
        if kind == "toggle":
            if val:
                argv.append(opt)
        elif kind == "toggle_inverted":
            if val is False:  # the checkbox shows the feature; the --no-* flag is emitted when it is off
                argv.append(opt)
        elif kind == "multi":
            argv.append(opt)
            argv += [str(x) for x in (split_extra(val) if isinstance(val, str) else val)]
        elif kind == "optional_value":
            argv.append(opt if val is True else "%s=%s" % (opt, val))
        else:
            shown = MASK if (mask and is_secret(f, overlay)) else str(val)
            argv.append("%s=%s" % (opt, shown))  # '=' keeps a value that starts with '-' safe
    return argv, dropped


def split_extra(text, windows=None):
    """Words typed by the user. On Windows a backslash is a path separator, not an escape, so quotes are
    handled but backslashes are kept."""
    windows = (os.name == "nt") if windows is None else windows
    try:
        if not windows:
            return shlex.split(text, posix=True)
        words = shlex.split(text, posix=False)
    except ValueError:
        return text.split()
    return [w[1:-1] if len(w) >= 2 and w[0] == w[-1] and w[0] in "\"'" else w for w in words]


def parse_extra(text, inv=None, overlay=None, windows=None):
    """Typed flags -> ({flag_id: value}, [(token, reason)]). Owned flags and stray words are refused;
    flags the engine does not have are kept as typed (an engine update may bring them back)."""
    from . import flagrules

    byid = {f["id"]: f for f in (inv or {}).get("flags", [])}
    byopt = {o: f for f in byid.values() for o in f["options"]}
    words = split_extra(text, windows)
    out, refused = {}, []
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        if not w.startswith("--"):
            refused.append((w, "Not a flag"))
            continue
        opt, eq, val = w.partition("=")
        f = byopt.get(opt)
        fid = f["id"] if f else opt
        if flagrules.is_owned(fid):
            refused.append((opt, flagrules.REASON_OWNED))
            if not eq and i < len(words) and not words[i].startswith("--"):
                i += 1  # its value
            continue
        kind = kind_of(f, overlay) if f else None
        if kind in ("toggle", "toggle_inverted") or (f is None and not eq and (i >= len(words) or words[i].startswith("--"))):
            out[fid] = False if kind == "toggle_inverted" else True
        elif kind == "multi":
            vals = [val] if eq else []
            while i < len(words) and not words[i].startswith("--"):
                vals.append(words[i])
                i += 1
            out[fid] = vals
        elif eq:
            out[fid] = val
        elif i < len(words) and not words[i].startswith("--"):
            out[fid] = words[i]
            i += 1
        else:
            out[fid] = True  # optional value given without one
    return out, refused


def q_posix(a):
    return shlex.quote(a)


def q_powershell(a):
    if a and re.fullmatch(r"[A-Za-z0-9_./:\\=+,@%-]+", a) and not a.startswith("-"):
        return a
    if re.fullmatch(r"-{1,2}[A-Za-z][\w-]*(=[A-Za-z0-9_./:\\+,@%-]*)?", a):
        return a
    return "'" + a.replace("'", "''") + "'"


def q_cmd(a):
    if a and re.fullmatch(r"[A-Za-z0-9_./:\\=+,@-]+", a):
        return a
    s = re.sub(r'(\\*)"', lambda m: m.group(1) * 2 + '\\"', a)
    s = re.sub(r"(\\+)$", lambda m: m.group(1) * 2, s)
    return '"' + s + '"'


def render(argv, shell):
    q = {"posix": q_posix, "powershell": q_powershell, "cmd": q_cmd}[shell]
    return " ".join(q(x) for x in argv)


def render_env(name, value, shell):
    if shell == "cmd":
        return 'set "%s=%s"' % (name, value)
    if shell == "powershell":
        return "$env:%s='%s'" % (name, value)
    return "%s=%s" % (name, value)
