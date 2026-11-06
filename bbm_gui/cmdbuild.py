"""Form state -> argv list (the truth) -> display strings per shell (a view, never executed)."""
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


def build_argv(inv, state, overlay=None, mask=False):
    """state: {flag_id: value}. An absent key, None or '' means untouched and is not emitted: a typed default
    differs from silence for this engine. Flags missing from the inventory are returned in `dropped`."""
    byid = {f["id"]: f for f in inv["flags"]}
    items = []
    dropped = []
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
            argv += [str(x) for x in val]
        elif kind == "optional_value":
            argv.append(opt if val is True else "%s=%s" % (opt, val))
        else:
            shown = MASK if (mask and is_secret(f, overlay)) else str(val)
            argv.append("%s=%s" % (opt, shown))  # '=' keeps a value that starts with '-' safe
    return argv, dropped


def split_extra(text):
    """Extra args typed by the user (shell-like words)."""
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


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
