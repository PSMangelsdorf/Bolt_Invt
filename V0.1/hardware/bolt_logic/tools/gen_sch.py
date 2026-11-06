#!/usr/bin/env python3
"""Generate the Bolt logic-board schematic (KiCad 7 format) from tools/sch_design.py.

Every pin is connected by a short wire stub and a global label carrying its net
name, so the design table in sch_design.py *is* the netlist. After writing, the
script exports the netlist with kicad-cli and checks it against the table.

    python3 tools/gen_sch.py          # generate + verify
"""
import math
import os
import re
import subprocess
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kisym  # noqa: E402
from kisym import Q, dump  # noqa: E402

PROJECT = "bolt_logic"
NS = uuid.UUID("6f1c5b1e-2f6a-4c55-9a4e-b01700000000")
GRID = 2.54
STUB = 2.54
PAPERS = [("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0)]


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def snap(v, g=GRID):
    return round(v / g) * g


def fmt(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


# ------------------------------------------------------------------ design model
class Part:
    def __init__(self, ref, lib_id, value, footprint, pins, dnp=False, fields=None):
        self.ref, self.lib_id, self.value, self.footprint = ref, lib_id, value, footprint
        self.pins = {str(k): v for k, v in pins.items()}
        self.dnp = dnp
        self.fields = fields or {}


class Sheet:
    def __init__(self, name, file, title):
        self.name, self.file, self.title = name, file, title
        self.parts = []

    def add(self, *a, **k):
        p = Part(*a, **k)
        self.parts.append(p)
        return p

    # convenience two-terminal helpers -----------------------------------
    def r(self, ref, value, a, b, fp="Resistor_SMD:R_0805_2012Metric", **k):
        return self.add(ref, "Device:R", value, fp, {1: a, 2: b}, **k)

    def c(self, ref, value, a, b, fp="Capacitor_SMD:C_0805_2012Metric", **k):
        return self.add(ref, "Device:C", value, fp, {1: a, 2: b}, **k)


# ------------------------------------------------------------------ geometry
def outward(angle):
    a = math.radians(angle)
    return (-math.cos(a), math.sin(a))            # schematic coords (y down)


def label_angle(d):
    dx, dy = d
    if abs(dx) > abs(dy):
        return 0 if dx > 0 else 180
    return 270 if dy > 0 else 90


def label_len(net):
    return 1.0 * len(net) + 4.0


# ------------------------------------------------------------------ writer
def effects(hide=False, justify=None, size=1.27):
    e = ["effects", ["font", ["size", fmt(size), fmt(size)]]]
    if justify:
        e.append(["justify"] + justify.split())
    if hide:
        e.append("hide")
    return e


def prop(name, value, x, y, ang=0, hide=False, justify=None):
    return ["property", Q(name), Q(value), ["at", fmt(x), fmt(y), str(ang)], effects(hide, justify)]


def build_sheet(sheet, root_uuid, sheet_uuid, page, intended):
    libs = {}
    cells = []
    for part in sheet.parts:
        sym = libs.get(part.lib_id) or kisym.lib_symbol(part.lib_id)
        libs[part.lib_id] = sym
        all_numbers = set()
        for u in kisym.units(sym):
            pins = kisym.pins(sym, u)
            if not pins and kisym.units(sym) != [1]:
                continue
            all_numbers |= {p["number"] for p in pins}
            x0, y0, x1, y1 = kisym.bbox(sym, u)
            m = {"l": 2.0, "r": 2.0, "t": 4.0, "b": 4.0}
            for p in pins:
                net = part.pins.get(p["number"])
                if not net or p["hidden"]:
                    continue
                dx, dy = outward(p["angle"])
                side = "l" if dx < -0.5 else "r" if dx > 0.5 else ("t" if dy < 0 else "b")
                m[side] = max(m[side], STUB + label_len(net) + (2 if side in "tb" else 0))
            w = (x1 - x0) + m["l"] + m["r"]
            h = (y1 - y0) + m["t"] + m["b"]
            cells.append(dict(part=part, sym=sym, unit=u, pins=pins, bb=(x0, y0, x1, y1), m=m, w=w, h=h))
        missing = [n for n in all_numbers if n not in part.pins]
        # hidden stacked pins inherit; anything else must be specified
        for n in list(missing):
            pass
        extra = set(part.pins) - all_numbers
        if extra:
            raise ValueError("%s: pins %s not in symbol %s" % (part.ref, sorted(extra), part.lib_id))

    # choose paper and shelf-pack
    for paper, PW, PH in PAPERS:
        x, y, rowh, pos = 15.0, 25.0, 0.0, []
        for c in cells:
            if x + c["w"] > PW - 15 and x > 15:
                x, y, rowh = 15.0, y + rowh + 2, 0.0
            pos.append((x, y)); x += c["w"] + 2; rowh = max(rowh, c["h"])
        if y + rowh < PH - 35:
            break

    items, symbols = [], []
    for c, (cx, cy) in zip(cells, pos):
        part, sym, u = c["part"], c["sym"], c["unit"]
        x0, y0, x1, y1 = c["bb"]
        sx = snap(cx + c["m"]["l"] - x0)
        sy = snap(cy + c["m"]["t"] + y1)
        sid = uid(sheet.file, part.ref, u)
        # connection points
        groups = {}
        for p in c["pins"]:
            pt = (round(sx + p["x"], 3), round(sy - p["y"], 3))
            groups.setdefault(pt, []).append(p)
        for pt, plist in groups.items():
            nets = {part.pins.get(p["number"]) for p in plist} - {None}
            nets.discard("~unspecified")
            vis = [p for p in plist if not p["hidden"]]
            if not nets:
                unspecified = [p["number"] for p in plist if p["number"] not in part.pins
                               and not (p["hidden"] and p["type"] == "no_connect")]
                if unspecified:
                    raise ValueError("%s unit %d: pins %s have no net (use 'NC')" % (part.ref, u, unspecified))
                continue
            if len(nets) > 1:
                raise ValueError("%s: stacked pins at %s have different nets %s" % (part.ref, pt, nets))
            net = nets.pop()
            for p in plist:
                intended[(part.ref, p["number"])] = net
            if net == "NC":
                items.append(["no_connect", ["at", fmt(pt[0]), fmt(pt[1])], ["uuid", uid(sid, "nc", pt)]])
                continue
            d = outward((vis or plist)[0]["angle"])
            end = (pt[0] + STUB * d[0], pt[1] + STUB * d[1])
            items.append(["wire", ["pts", ["xy", fmt(pt[0]), fmt(pt[1])], ["xy", fmt(end[0]), fmt(end[1])]],
                          ["stroke", ["width", "0"], ["type", "default"]], ["uuid", uid(sid, "w", pt)]])
            ang = label_angle(d)
            items.append(["global_label", Q(net), ["shape", "passive"],
                          ["at", fmt(end[0]), fmt(end[1]), str(ang)], ["fields_autoplaced"],
                          effects(justify="left" if ang in (0, 90) else "right"),
                          ["uuid", uid(sid, "gl", pt)],
                          ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"),
                           ["at", fmt(end[0]), fmt(end[1]), "0"], effects(hide=True)]])
        s = ["symbol", ["lib_id", Q(part.lib_id)], ["at", fmt(sx), fmt(sy), "0"], ["unit", str(u)],
             ["in_bom", "no" if part.ref.startswith("#") else "yes"],
             ["on_board", "no" if part.ref.startswith("#") else "yes"], ["dnp", "yes" if part.dnp else "no"],
             ["uuid", sid],
             prop("Reference", part.ref, sx + x0, sy - y1 - 1.6, hide=part.ref.startswith("#"), justify="left"),
             prop("Value", part.value + (" (DNP)" if part.dnp else ""), sx + x0, sy - y0 + 2.4, justify="left"),
             prop("Footprint", part.footprint, sx, sy, hide=True),
             prop("Datasheet", "~", sx, sy, hide=True)]
        for k, v in part.fields.items():
            s.append(prop(k, v, sx, sy, hide=True))
        for p in c["pins"]:
            s.append(["pin", Q(p["number"]), ["uuid", uid(sid, "pin", p["number"])]])
        s.append(["instances", ["project", Q(PROJECT), ["path", Q("/%s/%s" % (root_uuid, sheet_uuid)),
                                                        ["reference", Q(part.ref)], ["unit", str(u)]]]])
        symbols.append(s)

    tree = ["kicad_sch", ["version", "20230121"], ["generator", "eeschema"],
            ["uuid", uid("file", sheet.file)], ["paper", Q(paper)],
            ["title_block", ["title", Q("Bolt logic board - " + sheet.title)], ["date", Q("2026-10-10")],
             ["rev", Q("0.1")], ["company", Q("Bolt_Invt open-source inverter controller")],
             ["comment", "1", Q("GENERATED by tools/gen_sch.py from tools/sch_design.py - edit the design file, not this sheet")]],
            ["lib_symbols"] + list(libs.values())]
    tree += items + symbols
    return tree


def build_root(sheets, root_uuid):
    tree = ["kicad_sch", ["version", "20230121"], ["generator", "eeschema"], ["uuid", root_uuid],
            ["paper", Q("A3")],
            ["title_block", ["title", Q("Bolt logic board")], ["date", Q("2026-10-10")], ["rev", Q("0.1")],
             ["company", Q("Bolt_Invt open-source inverter controller")],
             ["comment", "1", Q("Replacement logic board for the Chevrolet Bolt EV inverter (OpenInverter stm32-sine, HW_BOLT)")]],
            ["lib_symbols"]]
    for i, sh in enumerate(sheets):
        x, y = 30 + (i % 4) * 95, 40 + (i // 4) * 60
        su = uid("sheet", sh.file)
        tree.append(["sheet", ["at", fmt(x), fmt(y)], ["size", "80", "40"], ["fields_autoplaced"],
                     ["stroke", ["width", "0.1524"], ["type", "solid"]], ["fill", ["color", "0", "0", "0", "0.0000"]],
                     ["uuid", su],
                     prop("Sheetname", sh.title, x, y - 0.7, justify="left bottom"),
                     prop("Sheetfile", sh.file, x, y + 40.6, justify="left top"),
                     ["instances", ["project", Q(PROJECT), ["path", Q("/" + root_uuid), ["page", Q(str(i + 2))]]]]])
    tree.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
    return tree


# ------------------------------------------------------------------ verify
def verify(intended):
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "n.net")
        r = subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out,
                            os.path.join(PROJ, PROJECT + ".kicad_sch")], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError("kicad-cli netlist export failed:\n" + r.stdout + r.stderr)
        net = kisym.parse(open(out).read())
    got = {}
    for n in kisym.find(kisym.first(net, "nets"), "net"):
        name = kisym.first(n, "name")[1]
        for node in kisym.find(n, "node"):
            got[(kisym.first(node, "ref")[1], kisym.first(node, "pin")[1])] = name
    errors = []
    for key, want in intended.items():
        if key[0].startswith("#"):          # power flags are virtual - not in netlists
            continue
        g = got.get(key)
        if want == "NC":
            if g is not None and not g.startswith("unconnected"):
                errors.append("%s-%s should be NC, is on %s" % (key[0], key[1], g))
        elif g != want:
            errors.append("%s-%s expected %s, got %s" % (key[0], key[1], want, g))
    for key, g in got.items():
        # pins absent from the design can only be hidden no-connect pins (visible ones
        # without a net are rejected at generation time) - they must stay unconnected
        if key not in intended and not g.startswith("unconnected"):
            errors.append("%s-%s on %s not in design" % (key[0], key[1], g))
    return errors, got


def main():
    import sch_design
    if hasattr(sch_design, "write_custom_symbols"):
        sch_design.write_custom_symbols(os.path.join(PROJ, "Bolt.kicad_sym"))
        kisym._lib_cache.pop("Bolt", None)
    sheets = sch_design.SHEETS
    refs = [p.ref for sh in sheets for p in sh.parts]
    dups = sorted({r for r in refs if refs.count(r) > 1})
    if dups:
        raise ValueError("duplicate reference designators: %s" % dups)
    root_uuid = uid("root")
    intended = {}
    for i, sh in enumerate(sheets):
        tree = build_sheet(sh, root_uuid, uid("sheet", sh.file), i + 2, intended)
        open(os.path.join(PROJ, sh.file), "w").write(dump(tree) + "\n")
    open(os.path.join(PROJ, PROJECT + ".kicad_sch"), "w").write(dump(build_root(sheets, root_uuid)) + "\n")
    errors, got = verify(intended)
    nets = len(set(v for v in intended.values() if v != "NC"))
    nparts = sum(len(s.parts) for s in sheets)
    if errors:
        print("NETLIST CHECK FAILED (%d):" % len(errors))
        for e in errors[:40]:
            print("  " + e)
        return 1
    print("wrote %d sheets, %d parts, %d pins on %d nets - netlist matches design" %
          (len(sheets), nparts, len(intended), nets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
