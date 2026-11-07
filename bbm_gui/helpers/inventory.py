#!/usr/bin/env python
"""Flag inventory helper. It runs under the engine's own Python and is never copied into the engine.

  runtime: <engine-python> -I -B inventory.py runtime <engine_root>
  ast    : <any python 3.9+> -I -B inventory.py ast <path/to/cli.py>

stdout is exactly one JSON document (ASCII); diagnostics go to stderr. Standard library only.
"""

import argparse, ast, contextlib, importlib, io, json, os, re, sys, time, tokenize, types, warnings

sys.dont_write_bytecode = True  # `python -I` ignores PYTHONDONTWRITEBYTECODE
SCHEMA = 1
FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")


# ------------------------------------------------------------------ runtime
_STD = [
    (argparse._StoreTrueAction, "store_true"), (argparse._StoreFalseAction, "store_false"),
    (argparse._StoreConstAction, "store_const"), (argparse._AppendConstAction, "append_const"),
    (argparse._AppendAction, "append"), (argparse._CountAction, "count"),
    (argparse._HelpAction, "help"), (argparse._VersionAction, "version"),
    (argparse._StoreAction, "store"),
]
if hasattr(argparse, "BooleanOptionalAction"):
    _STD.insert(0, (argparse.BooleanOptionalAction, "boolean_optional"))


def _fid(opts, dest):
    """Stable id: first long option string, else first option, else dest."""
    longs = [o for o in opts if o.startswith("--")]
    return longs[0] if longs else (opts[0] if opts else dest)


def _kind(a):
    for cls, name in _STD:
        if isinstance(a, cls):
            return name
    return "custom"


def _jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_jsonable(x) for x in v]
    return {"$repr": repr(v)}


def _choices(a):
    if a.choices is None:
        return None, False
    c = a.choices
    open_ = type(c).__contains__ not in (list.__contains__, tuple.__contains__,
                                         set.__contains__, dict.__contains__, range.__contains__)
    try:
        lst = [_jsonable(x) for x in c]
    except Exception:
        lst = None
    return lst, open_


def _type_name(a):
    t = a.type
    return None if t is None else (getattr(t, "__name__", None) or repr(t))


_PROBE_INT = ["-1000000", "-1", "0", "1", "2", "3", "5", "10", "16", "50", "64", "100", "200",
              "500", "1000", "4000", "5000", "10000", "100000", "1000000"]
_PROBE_FLOAT = ["-1", "0", "0.001", "0.01", "0.1", "0.5", "0.9", "1", "1.0001", "1.5", "2", "10"]


def probe_type(t):
    """Call a custom `type=` validator on a fixed grid. Pure for the validators of
    this engine (one touches the filesystem: is_file). Returns what it accepts."""
    def call(v):
        try:
            r = t(v)
            return type(r).__name__
        except BaseException:
            return None
    ints = {v: call(v) for v in _PROBE_INT}
    floats = {v: call(v) for v in _PROBE_FLOAT}
    acc_i = [int(v) for v, r in ints.items() if r]
    acc_f = [float(v) for v, r in floats.items() if r]
    res = {"text_ok": call("abc") is not None, "int_ok": bool(acc_i),
           "float_frac_ok": call("0.5") is not None}
    if acc_i:
        res["int_min_seen"] = min(acc_i); res["int_max_seen"] = max(acc_i)
        res["int_grid_open_top"] = max(acc_i) == int(_PROBE_INT[-1])
        res["int_grid_open_bottom"] = min(acc_i) == int(_PROBE_INT[0])
    if res["float_frac_ok"]:
        res["float_min_seen"] = min(acc_f); res["float_max_seen"] = max(acc_f)
    res["result_types"] = sorted({r for r in list(ints.values()) + list(floats.values()) if r})
    return res


def runtime_inventory(parser, source):
    users = {}
    for i, a in enumerate(parser._actions):
        users.setdefault(a.dest, []).append(i)
    fmt = parser._get_formatter()
    flags = []
    for i, a in enumerate(parser._actions):
        hidden = a.help is argparse.SUPPRESS
        rendered = None
        if not hidden and a.help:
            try:
                rendered = fmt._expand_help(a)   # private API; fall back to raw
            except Exception:
                rendered = a.help
        ch, open_ = _choices(a)
        d = a.default
        flags.append({
            "id": _fid(a.option_strings, a.dest),
            "options": list(a.option_strings),
            "dest": a.dest,
            "dest_shared_with": [_fid(parser._actions[j].option_strings, a.dest) for j in users[a.dest]
                                 if j != i and parser._actions[j].option_strings],
            "action": _kind(a), "action_class": type(a).__name__,
            "nargs": a.nargs, "const": _jsonable(a.const),
            "type": _type_name(a),
            "default": None if d is argparse.SUPPRESS else _jsonable(d),
            "choices": ch, "choices_open": open_,
            "metavar": _jsonable(a.metavar),
            "required": bool(a.required),
            "hidden": hidden,
            "deprecated": bool(getattr(a, "deprecated", False)),
            "help_raw": None if hidden else a.help,
            "help": rendered,
            "order": i,
        })
        if a.type not in (None, str, int, float):
            flags[-1]["type_probe"] = probe_type(a.type)
    return {"schema": SCHEMA, "source": source, "flags": flags}


def _code_strings(code, g, depth=0, seen=None):
    """Constant strings + names of a code object and of module-level functions
    it calls (depth<=2): how COMPAT_RULES rows reveal their flags."""
    seen = seen if seen is not None else set()
    strs, names = [], set()
    if code in seen:
        return strs, names
    seen.add(code)
    for c in code.co_consts:
        if isinstance(c, str):
            strs.append(c)
        elif isinstance(c, types.CodeType):
            s, n = _code_strings(c, g, depth, seen); strs += s; names |= n
    for n in code.co_names:
        names.add(n)
        f = g.get(n)
        if depth < 2 and isinstance(f, types.FunctionType):
            s, nn = _code_strings(f.__code__, g, depth + 1, seen); strs += s; names |= nn
    return strs, names


def compat_rows(mod, dests, optmap):
    rows = []
    for r in getattr(mod, "COMPAT_RULES", ()):
        try:
            ws, wn = _code_strings(r.when.__code__, mod.__dict__)
            ss, sn = _code_strings(r.say.__code__, mod.__dict__)
        except Exception as e:
            rows.append({"id": r.id, "level": r.level, "error": repr(e)}); continue
        said = []
        for s in ss + [x for x in ws if x.startswith("-")]:
            for m in FLAG_RE.findall(s):
                if m in optmap and optmap[m] not in said:
                    said.append(optmap[m])
        read = sorted(n for n in (wn | sn) if n in dests)
        rows.append({"id": r.id, "level": r.level,
                     "flags_named": said,           # flag ids in message text / when constants
                     "attrs_read": read})           # option dests read by when/say
    return rows


class _Captured(BaseException):
    def __init__(self, parser):
        self.parser = parser


def _capture_parser(mod):
    """Name-independent fallback: run the module's main() with parse_args patched to hand back the
    parser it builds. Works when build_parser is renamed or the parser is inline in main()."""
    def grab(self, *a, **k):
        raise _Captured(self)
    saved = (argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args)
    argparse.ArgumentParser.parse_args = grab
    argparse.ArgumentParser.parse_known_args = grab
    old_argv = sys.argv
    sys.argv = ["book_maker"]
    try:
        mod.main()
    except _Captured as c:
        return c.parser
    finally:
        argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args = saved
        sys.argv = old_argv
    raise RuntimeError("main() returned without parsing")


def cmd_runtime(root):
    sys.path.insert(0, root)    # -I drops PYTHONPATH and script dir
    t0 = time.perf_counter()
    errs = []
    sink = dict(stdout=io.StringIO(), stderr=io.StringIO())
    for strategy in ("build_parser", "capture"):
        try:
            with contextlib.redirect_stdout(sink["stdout"]), contextlib.redirect_stderr(sink["stderr"]),                     warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mod = importlib.import_module("book_maker.cli")
                parser = mod.build_parser() if strategy == "build_parser" else _capture_parser(mod)
                # validators may print (plan-min-coverage notes do): keep stdout JSON-only
                out = runtime_inventory(parser, {"kind": "runtime", "strategy": strategy})
            dests = {f["dest"] for f in out["flags"]}
            optmap = {o: f["id"] for f in out["flags"] for o in f["options"]}
            try:
                out["compat"] = compat_rows(mod, dests, optmap)
            except Exception as e:
                out["compat"] = []; out["compat_error"] = repr(e)
            try:  # the engine's language table: {tag: name} and {name: tag} aliases
                utils = importlib.import_module("book_maker.utils")
                out["languages"] = {str(k): str(v) for k, v in utils.LANGUAGES.items()}
                out["language_aliases"] = {str(k): str(v) for k, v in getattr(utils, "TO_LANGUAGE_CODE", {}).items()}
            except Exception:
                pass
            out["import_seconds"] = round(time.perf_counter() - t0, 2)
            out["python"] = sys.version.split()[0]
            out["errors_before_success"] = errs
            return out
        except BaseException as e:      # SystemExit included
            errs.append("%s: %s: %s" % (strategy, type(e).__name__, e))
    return {"schema": SCHEMA, "error": errs}


# ---------------------------------------------------------------------- AST
UNRES = "$unresolved"


class _Ev:
    def __init__(self, tree):
        self.consts = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                v = self.ev(n.value)
                if not _is_unres(v):
                    self.consts[n.targets[0].id] = v

    def ev(self, n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            return self.consts.get(n.id, {UNRES: n.id})
        if isinstance(n, (ast.Tuple, ast.List)):
            return [self.ev(e) for e in n.elts]
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            a, b = self.ev(n.left), self.ev(n.right)
            if isinstance(a, str) and isinstance(b, str):
                return a + b
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            v = self.ev(n.operand)
            if isinstance(v, (int, float)):
                return -v
        try:
            return {UNRES: ast.unparse(n)}
        except Exception:
            return {UNRES: "?"}


def _is_unres(v):
    return (isinstance(v, dict) and UNRES in v) or (isinstance(v, list) and any(_is_unres(x) for x in v))


def _dest_from(opts):
    longs = [o for o in opts if o.startswith("--")] or opts
    return longs[0].lstrip("-").replace("-", "_")


def _fn_name(n):
    if isinstance(n, ast.Name): return n.id
    if isinstance(n, ast.Attribute): return n.attr
    return None


def _sniff_validators(tree):
    """AST stand-in for probe_type: what does a module-level `def v(value)` convert to?"""
    out = {}
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef) or len(fn.args.args) != 1:
            continue
        p = fn.args.args[0].arg
        kinds = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("int", "float")                     and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == p:
                kinds.add(n.func.id)
            if isinstance(n, ast.Attribute) and n.attr in ("is_file", "is_dir", "exists"):
                kinds.add("path")
        if kinds:
            out[fn.name] = "float" if "float" in kinds else ("int" if "int" in kinds else "path")
    return out


def ast_inventory(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    ev = _Ev(tree)
    sniff = _sniff_validators(tree)
    sections = []   # "########## ENDPOINT ##########"
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            m = re.match(r"#{3,}\s*(.+?)\s*#{3,}$", tok.string)
            if m:
                sections.append((tok.start[0], m.group(1)))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "add_argument"]
    calls.sort(key=lambda n: (n.lineno, n.col_offset))
    flags, unres_count = [], 0
    for idx, c in enumerate(calls):
        pos = [ev.ev(a) for a in c.args]
        opts = [p for p in pos if isinstance(p, str) and p.startswith("-")]
        kw = {k.arg: k.value for k in c.keywords if k.arg}
        g = lambda k, d=None: ev.ev(kw[k]) if k in kw else d
        action = g("action", "store")
        if isinstance(action, str):
            action_name, action_class = action, None
        else:
            action_name, action_class = "custom", _fn_name(kw["action"])
        helpv = g("help")
        hidden = isinstance(kw.get("help"), ast.Attribute) and kw["help"].attr == "SUPPRESS"
        rec = {
            "id": _fid(opts, None) if opts else (pos[0] if pos and isinstance(pos[0], str) else "?"),
            "options": opts,
            "dest": g("dest") or (_dest_from(opts) if opts else None),
            "action": action_name, "action_class": action_class,
            "nargs": g("nargs"), "const": g("const"),
            "type": _fn_name(kw["type"]) if "type" in kw else None,
            "default": g("default"),
            "choices": g("choices"), "choices_open": None,
            "metavar": g("metavar"), "required": bool(g("required", False)),
            "hidden": hidden,
            "help_raw": None if hidden else helpv, "help": None if hidden else helpv,
            "order": idx, "line": c.lineno,
            "section": next((s for ln, s in reversed(sections) if ln < c.lineno), None),
        }
        # argparse-implied values, so AST and runtime inventories agree
        if action_name in ("store_true", "store_false", "store_const", "append_const", "count", "help", "version"):
            rec["nargs"] = 0
        if "default" not in kw:
            rec["default"] = {"store_true": False, "store_false": True}.get(action_name)
        if rec["type"] in sniff:
            rec["type_hint"] = sniff[rec["type"]]
        rec["unresolved"] = [k for k in ("default", "choices", "help", "nargs", "const", "dest")
                             if _is_unres(rec.get(k))]
        unres_count += len(rec["unresolved"])
        flags.append(rec)
    users = {}
    for f in flags:
        users.setdefault(f["dest"], []).append(f["id"])
    for f in flags:
        f["dest_shared_with"] = [x for x in users[f["dest"]] if x != f["id"]]
    return {"schema": SCHEMA, "source": {"kind": "ast", "path": os.path.basename(path)},
            "flags": flags, "unresolved_fields": unres_count}



def post(inv):
    """Derived fields shared by both paths: deprecated, alias_of (hidden aliases)."""
    flags = inv.get("flags", [])
    ids = {f["id"] for f in flags}
    for f in flags:
        h = f.get("help_raw") if isinstance(f.get("help_raw"), str) else ""
        f["deprecated"] = bool(f.get("deprecated")) or bool(re.match(r"\s*deprecated\b", h, re.I))
        f["alias_of"] = None
    for f in flags:                                   # 1. hidden flag sharing a dest with a visible one
        if f["hidden"]:
            for o in f.get("dest_shared_with") or []:
                if o in ids and not next(x for x in flags if x["id"] == o)["hidden"]:
                    f["alias_of"] = o
    for f in flags:                                   # 2. visible help says "--x is the old name of this flag"
        h = f.get("help_raw") if isinstance(f.get("help_raw"), str) else ""
        for m in re.findall(r"(--[\w-]+) is the old name of this flag", h):
            for g in flags:
                if g["id"] == m and g["hidden"] and not g["alias_of"]:
                    g["alias_of"] = f["id"]
    return inv




def main():
    mode = sys.argv[1]
    if mode == "runtime":
        r = post(cmd_runtime(sys.argv[2]))
    elif mode == "ast":
        try:
            r = post(ast_inventory(sys.argv[2]))
        except Exception as e:
            r = {"schema": SCHEMA, "error": ["ast: %s: %s" % (type(e).__name__, e)]}
    else:
        sys.exit("usage: inventory.py runtime <engine_root> | ast <cli.py>")
    sys.stdout.write(json.dumps(r, ensure_ascii=True))  # ASCII: Windows pipes are not UTF-8
    sys.exit(2 if "error" in r else 0)


if __name__ == "__main__":
    main()
