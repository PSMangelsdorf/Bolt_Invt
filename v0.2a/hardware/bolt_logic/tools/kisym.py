"""Minimal KiCad S-expression reader/writer and symbol-library helpers (KiCad 7 format).

Used by gen_sch.py to embed library symbols in generated schematics and to find
pin connection points.
"""
import os
import re

SYMBOL_DIRS = [os.environ.get("KICAD7_SYMBOL_DIR", "/usr/share/kicad/symbols"),
               os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]

_tok = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+)')


class Q(str):
    """A token that must be written quoted."""


def parse(text):
    stack, cur = [], []
    for m in _tok.finditer(text):
        t = m.group(1)
        if t == "(":
            stack.append(cur); cur = []
        elif t == ")":
            done = cur; cur = stack.pop(); cur.append(done)
        elif t.startswith('"'):
            cur.append(Q(t[1:-1].replace('\\"', '"').replace("\\\\", "\\")))
        else:
            cur.append(t)
    return cur[0] if len(cur) == 1 else cur


def dump(node, indent=0):
    if not isinstance(node, list):
        if isinstance(node, Q):
            return '"%s"' % node.replace("\\", "\\\\").replace('"', '\\"')
        return str(node)
    simple = all(not isinstance(x, list) for x in node)
    if simple or len(node) <= 2 and not any(isinstance(x, list) and len(x) > 4 for x in node):
        return "(" + " ".join(dump(x, 0) for x in node) + ")"
    pad = "  " * (indent + 1)
    parts = [dump(node[0], 0)]
    for x in node[1:]:
        parts.append("\n" + pad + dump(x, indent + 1) if isinstance(x, list) else dump(x, 0))
    return "(" + " ".join(parts[:1]) + "".join((" " + p) if not p.startswith("\n") else p for p in parts[1:]) + ")"


def find(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def first(node, key):
    r = find(node, key)
    return r[0] if r else None


_lib_cache = {}


def load_lib(lib):
    if lib not in _lib_cache:
        for d in SYMBOL_DIRS:
            p = os.path.join(d, lib + ".kicad_sym")
            if os.path.exists(p):
                _lib_cache[lib] = parse(open(p, encoding="utf-8").read())
                break
        else:
            raise FileNotFoundError("symbol library %s not found" % lib)
    return _lib_cache[lib]


def lib_symbol(lib_id):
    """Return a flattened copy of a library symbol, named 'Lib:Name' for embedding."""
    lib, name = lib_id.split(":", 1)
    tree = load_lib(lib)
    syms = {s[1]: s for s in find(tree, "symbol")}
    if name not in syms:
        raise KeyError("symbol %s not in %s" % (name, lib))
    s = syms[name]
    ext = first(s, "extends")
    if ext:
        base = parse(dump(syms[ext[1]]))          # deep copy
        props = {p[1]: p for p in find(s, "property")}
        out = [base[0], Q(name)]
        for x in base[2:]:
            if isinstance(x, list) and x[0] == "property" and x[1] in props:
                out.append(props.pop(x[1]))
            elif isinstance(x, list) and x[0] == "symbol":
                x[1] = Q(re.sub("^" + re.escape(ext[1]), name, x[1]))
                out.append(x)
            else:
                out.append(x)
        for p in props.values():
            out.append(p)
        s = out
    else:
        s = parse(dump(s))
    s[1] = Q(lib_id)
    return s


def pins(sym, unit, style=1):
    """Pins drawn for `unit`: list of dict(number, name, x, y, angle, length, hidden, type)."""
    base = sym[1].split(":", 1)[-1]
    out = []
    for sub in find(sym, "symbol"):
        m = re.match(re.escape(base) + r"_(\d+)_(\d+)$", sub[1])
        if not m:
            continue
        u, st = int(m.group(1)), int(m.group(2))
        if u not in (0, unit) or st not in (0, style):
            continue
        for p in find(sub, "pin"):
            at = first(p, "at")
            out.append(dict(
                type=p[1],
                number=first(p, "number")[1], name=first(p, "name")[1],
                x=float(at[1]), y=float(at[2]), angle=float(at[3]) if len(at) > 3 else 0.0,
                length=float(first(p, "length")[1]),
                hidden="hide" in p,
            ))
    return out


def units(sym):
    base = sym[1].split(":", 1)[-1]
    us = set()
    for sub in find(sym, "symbol"):
        m = re.match(re.escape(base) + r"_(\d+)_(\d+)$", sub[1])
        if m and int(m.group(1)) > 0:
            us.add(int(m.group(1)))
    return sorted(us) or [1]


def bbox(sym, unit):
    """Rough body bbox in symbol coords (y up): from graphics + pin ends."""
    xs, ys = [], []
    for p in pins(sym, unit):
        xs.append(p["x"]); ys.append(p["y"])
    base = sym[1].split(":", 1)[-1]
    for sub in find(sym, "symbol"):
        m = re.match(re.escape(base) + r"_(\d+)_(\d+)$", sub[1])
        if not m or int(m.group(1)) not in (0, unit):
            continue
        for g in sub[2:]:
            if not isinstance(g, list):
                continue
            for k in ("start", "end", "center"):
                e = first(g, k)
                if e:
                    xs.append(float(e[1])); ys.append(float(e[2]))
            pts = first(g, "pts")
            if pts:
                for xy in find(pts, "xy"):
                    xs.append(float(xy[1])); ys.append(float(xy[2]))
    if not xs:
        return (-2.54, -2.54, 2.54, 2.54)
    return (min(xs), min(ys), max(xs), max(ys))
