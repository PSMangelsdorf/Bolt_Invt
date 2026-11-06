#!/usr/bin/env python3
"""Generate the Bolt logic-board schematic (KiCad 7 format) from tools/sch_design.py.

v0.2a (forum review: "schematics are unreadable, they should show the circuit flow"):
  - every symbol is placed by hand per sheet (tools/sch_layout.py), laid out in signal-flow order
    with decoupling caps drawn next to their IC (and next to the power unit of multi-unit parts);
  - nets local to a sheet are drawn as wires by an orthogonal grid router (2.54/1.27 mm grid,
    avoiding symbol bodies, text and other nets; crossings allowed, never a corner or an end on a
    foreign wire; T-connections are split and get a junction dot);
  - supply rails are power symbols (GND, +3V3, +5V, VCC_12V, ...), drawn at the pin;
  - nets shared with other sheets get one global label per sheet, with an input / output /
    bidirectional shape (SOURCE below);
  - the netlist KiCad exports is still checked against the design table, pin by pin.

    python3 tools/gen_sch.py          # generate + verify
"""
import heapq
import math
import os
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
G = 1.27                     # routing grid (mm)
STUB = 2.54
REV, DATE = "0.2a", "2026-11-06"
PAPER = ("A3", 420.0, 297.0)


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def fmt(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


def snap(v, g=2.54):
    return round(v / g) * g


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

    def r(self, ref, value, a, b, fp="Resistor_SMD:R_0805_2012Metric", **k):
        return self.add(ref, "Device:R", value, fp, {1: a, 2: b}, **k)

    def c(self, ref, value, a, b, fp="Capacitor_SMD:C_0805_2012Metric", **k):
        return self.add(ref, "Device:C", value, fp, {1: a, 2: b}, **k)


# ------------------------------------------------------------------ power symbols
STD_POWER = {"GND": "power:GND", "+3V3": "power:+3V3", "+5V": "power:+5V"}
CUSTOM_POWER = ["VBAT", "VCC_12V", "+5V_A", "+12V_GATE", "VDDA", "ESP_3V3"]
POWER_NETS = set(STD_POWER) | set(CUSTOM_POWER)


def power_lib_id(net):
    return STD_POWER.get(net) or "Bolt:PWR_" + net.replace("+", "P")


def custom_power_symbols():
    """Rail symbols for the board's own supply nets (same drawing as power:+3V3; the hidden pin's
    name and the value are the net name)."""
    out = []
    for net in CUSTOM_POWER:
        name = "PWR_" + net.replace("+", "P")
        s = kisym.parse(dump(kisym.lib_symbol("power:+3V3")))
        s[1] = Q(name)
        for x in s:
            if isinstance(x, list) and x and x[0] == "property":
                if x[1] == "Value":
                    x[2] = Q(net)
                elif x[1] == "ki_description":
                    x[2] = Q('Power symbol creates a global label with name "%s"' % net)
            if isinstance(x, list) and x and x[0] == "symbol":
                x[1] = Q(x[1].replace("+3V3", name))
                for pin in kisym.find(x, "pin"):
                    kisym.first(pin, "name")[1] = Q(net)
        out.append(s)
    return out


# ------------------------------------------------------------------ geometry
def rot_pt(x, y, r):
    a = math.radians(r)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def outward(angle):
    a = math.radians(angle)
    return (round(-math.cos(a)), round(math.sin(a)))       # sheet coords (y down)


def cell(x, y):
    return (int(round(x / G)), int(round(y / G)))


def text_w(s, size=1.27):
    return 0.85 * size * len(s) + 0.6


# ------------------------------------------------------------------ the sheet builder
class Builder:
    def __init__(self, sheet, place, sources, global_nets, root_uuid, sheet_uuid, intended, power_refs):
        self.sheet, self.place, self.sources, self.global_nets = sheet, place, sources, global_nets
        self.root_uuid, self.sheet_uuid, self.intended = root_uuid, sheet_uuid, intended
        self.power_refs = power_refs
        self.libs, self.items, self.symbols = {}, [], []
        self.blocked = set()
        self.soft = set()          # text: the router avoids it when it can
        self.rails = []            # power symbols placed: (net, x, y, direction)
        self.node = {}            # cell -> net (pin ends, wire ends/bends, label / power pins)
        self.hw, self.vw = {}, {}  # cell -> net for horizontal / vertical wire through the cell
        self.reserved = {}        # cell -> net: the first step out of a pin
        self.segs = {}            # net -> [(cellA, cellB)]
        self.pins = []            # dict(net, cell, out, ref, number, kind)
        self.warnings = []
        self.wired_power = set(place.get("_wire", ()))

    # ---------------------------------------------------------- symbols
    def lib(self, lib_id):
        if lib_id not in self.libs:
            self.libs[lib_id] = kisym.lib_symbol(lib_id)
        return self.libs[lib_id]

    def block_rect(self, x0, y0, x1, y1):
        """Cells whose centre lies inside the rectangle (edges inclusive)."""
        a = (math.ceil(min(x0, x1) / G - 0.01), math.ceil(min(y0, y1) / G - 0.01))
        b = (math.floor(max(x0, x1) / G + 0.01), math.floor(max(y0, y1) / G + 0.01))
        for i in range(a[0], b[0] + 1):
            for j in range(a[1], b[1] + 1):
                self.blocked.add((i, j))

    def add_text_block(self, x, y, s, justify="left", size=1.27, vertical=False):
        w = text_w(s, size)
        if vertical:
            r = (x - size / 2, y - w, x + size / 2, y)
        elif justify == "left":
            r = (x, y - size / 2, x + w, y + size / 2)
        elif justify == "right":
            r = (x - w, y - size / 2, x, y + size / 2)
        else:
            r = (x - w / 2, y - size / 2, x + w / 2, y + size / 2)
        a, b = cell(r[0], r[1]), cell(r[2], r[3])
        for i in range(a[0], b[0] + 1):
            for j in range(a[1], b[1] + 1):
                self.soft.add((i, j))

    def place_parts(self):
        auto_x, auto_y = 20.0, 230.0
        for part in self.sheet.parts:
            if part.ref.startswith("#FLG"):
                continue
            sym = self.lib(part.lib_id)
            units = kisym.units(sym)
            for u in units:
                pins = kisym.pins(sym, u)
                if not pins and units != [1]:
                    continue
                key = part.ref if len(units) == 1 else "%s.%d" % (part.ref, u)
                if key not in self.place and part.ref in self.place and len(units) > 1:
                    key = part.ref                    # only unit 1 placed explicitly? use offsets
                pl = self.place.get(key)
                if pl is None:
                    pl = (auto_x, auto_y, 0)
                    self.warnings.append("no placement for %s (parked at %.0f,%.0f)" % (key, auto_x, auto_y))
                    auto_x += 25
                    if auto_x > 380:
                        auto_x, auto_y = 20.0, auto_y + 20
                sx, sy, r = snap(pl[0]), snap(pl[1]), pl[2] if len(pl) > 2 else 0
                self.emit_symbol(part, sym, u, pins, sx, sy, r)

    def emit_symbol(self, part, sym, u, pins, sx, sy, r):
        sid = uid(self.sheet.file, part.ref, u)
        x0, y0, x1, y1 = kisym.bbox(sym, u)
        corners = [rot_pt(cx, cy, r) for cx in (x0, x1) for cy in (y0, y1)]
        bx0, bx1 = sx + min(c[0] for c in corners), sx + max(c[0] for c in corners)
        by0, by1 = sy - max(c[1] for c in corners), sy - min(c[1] for c in corners)
        if bx1 - bx0 < 2.6:
            m = (bx0 + bx1) / 2; bx0, bx1 = m - 1.3, m + 1.3
        if by1 - by0 < 2.6:
            m = (by0 + by1) / 2; by0, by1 = m - 1.3, m + 1.3
        self.block_rect(bx0, by0, bx1, by1)
        groups = {}
        for p in pins:
            px, py = rot_pt(p["x"], p["y"], r)
            pt = (round(sx + px, 3), round(sy - py, 3))
            groups.setdefault(pt, []).append(p)
        for pt, plist in groups.items():
            nets = {part.pins.get(p["number"]) for p in plist} - {None}
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
                self.intended[(part.ref, p["number"])] = net
            c = cell(*pt)
            if abs(c[0] * G - pt[0]) > 0.01 or abs(c[1] * G - pt[1]) > 0.01:
                raise ValueError("%s pin %s off grid at %s" % (part.ref, plist[0]["number"], pt))
            d = outward((vis or plist)[0]["angle"] + r)
            self.blocked.discard(c)
            self.pins.append(dict(net=net, cell=c, out=d, ref=part.ref, number=plist[0]["number"],
                                  multi=len(part.pins) > 2))
        # reference / value text
        two = len(pins) <= 2 and not part.ref.startswith(("J", "CN", "TP", "H", "Y"))
        vertical_part = (by1 - by0) > (bx1 - bx0)
        ref_vis = not part.ref.startswith("#")
        unit_tag = ""
        if len(kisym.units(sym)) > 1:
            unit_tag = ""                                   # KiCad appends the unit letter itself
        val = part.value + (" (DNP)" if part.dnp else "")
        if two and vertical_part:
            rx, ry, vx, vy, just = bx1 + 0.6, sy - 0.9, bx1 + 0.6, sy + 1.1, "left"
        elif two:
            rx, ry, vx, vy, just = sx, by0 - 1.6, sx, by1 + 1.6, "center"
        else:
            rx, ry, vx, vy, just = bx0, by0 - 1.6, bx0, by1 + 1.8, "left"
        ov = self.place.get("_text", {}).get(part.ref)
        if ov:                                              # per-part override: (dx_ref, dy_ref, dx_val, dy_val, justify)
            rx, ry, vx, vy, just = sx + ov[0], sy + ov[1], sx + ov[2], sy + ov[3], ov[4]
        hide_val = part.ref in self.place.get("_hidevalue", ()) or part.ref.startswith("H")
        if ref_vis:
            self.add_text_block(rx, ry, part.ref + ("A" if len(kisym.units(sym)) > 1 else ""), just)
        if not hide_val:
            self.add_text_block(vx, vy, val, just)
        jarg = None if just == "center" else just
        s = ["symbol", ["lib_id", Q(part.lib_id)], ["at", fmt(sx), fmt(sy), str(int(r))], ["unit", str(u)],
             ["in_bom", "no" if part.ref.startswith("#") else "yes"],
             ["on_board", "no" if part.ref.startswith("#") else "yes"], ["dnp", "yes" if part.dnp else "no"],
             ["uuid", sid],
             # KiCad draws a field of a 90/270-rotated symbol turned with it unless its angle says otherwise
             prop("Reference", part.ref, rx, ry, ang=90 if r in (90, 270) else 0, hide=not ref_vis, justify=jarg),
             prop("Value", val, vx, vy, ang=90 if r in (90, 270) else 0, justify=jarg, hide=hide_val),
             prop("Footprint", part.footprint, sx, sy, hide=True),
             prop("Datasheet", "~", sx, sy, hide=True)]
        for k, v in part.fields.items():
            s.append(prop(k, v, sx, sy, hide=True))
        for p in pins:
            s.append(["pin", Q(p["number"]), ["uuid", uid(sid, "pin", p["number"])]])
        s.append(["instances", ["project", Q(PROJECT), ["path", Q("/%s/%s" % (self.root_uuid, self.sheet_uuid)),
                                                        ["reference", Q(part.ref)], ["unit", str(u)]]]])
        self.symbols.append(s)

    # ---------------------------------------------------------- attachments
    def free_line(self, start, d, n, net):
        """Cells start+d .. start+n*d free for `net` (no block, no foreign node/wire)."""
        c = start
        for _ in range(n):
            c = (c[0] + d[0], c[1] + d[1])
            if c in self.blocked or self.node.get(c, net) != net or self.hw.get(c, net) != net \
                    or self.vw.get(c, net) != net or self.reserved.get(c, net) != net:
                return False
        return True

    def add_wire(self, net, a, b):
        if a == b:
            return
        self.segs.setdefault(net, []).append((a, b))
        if a[1] == b[1]:
            for i in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
                self.hw[(i, a[1])] = net
        else:
            for j in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
                self.vw[(a[0], j)] = net
        self.node[a] = net; self.node[b] = net

    def stub_end(self, p, cells=2):
        c, d = p["cell"], p["out"]
        return (c[0] + d[0] * cells, c[1] + d[1] * cells)

    def power_symbol(self, net, c, d, key):
        """Power symbol whose pin is at cell c; its body extends along d (the stub direction), so a
        GND below a pin hangs down, a rail above a pin points up, and on a connector's side pins
        they point sideways."""
        lib_id = power_lib_id(net)
        self.lib(lib_id)
        x, y = c[0] * G, c[1] * G
        gnd = net == "GND"
        # body direction at rotation 0: GND down (0, 1), rails up (0, -1) in sheet coords
        if gnd:
            r = {(0, 1): 0, (0, -1): 180, (1, 0): 90, (-1, 0): 270}[d]
        else:
            r = {(0, -1): 0, (0, 1): 180, (-1, 0): 90, (1, 0): 270}[d]
        ex, ey = x + d[0] * 3.2, y + d[1] * 3.2
        self.block_rect(min(x + d[0] * 0.6, ex) - (1.4 if d[0] == 0 else 0), min(y + d[1] * 0.6, ey) - (1.4 if d[1] == 0 else 0),
                        max(x + d[0] * 0.6, ex) + (1.4 if d[0] == 0 else 0), max(y + d[1] * 0.6, ey) + (1.4 if d[1] == 0 else 0))
        # a row of the same rail (an IC's supply pins, a connector's ground pins) shows its name once
        twin = any(n == net and dd == d and ((d[1] != 0 and abs(py - y) < 0.1 and abs(px - x) < 8.0) or
                                             (d[0] != 0 and abs(px - x) < 0.1 and abs(py - y) < 8.0))
                   for n, px, py, dd in self.rails)
        self.rails.append((net, x, y, d))
        if d[1] != 0:
            vx, vy, just = x, y + d[1] * (4.4 if gnd == (d[1] > 0) else 4.0), None
            if not twin:
                self.add_text_block(vx, vy, net, "center")
        else:
            vx, vy = x + d[0] * 3.9, y
            just = "left" if d[0] > 0 else "right"
            if not twin:
                self.add_text_block(vx, vy, net, just)
        ref = "#PWR%03d" % self.power_refs[0]
        self.power_refs[0] += 1
        sid = uid(self.sheet.file, "pwr", key)
        self.symbols.append(["symbol", ["lib_id", Q(lib_id)], ["at", fmt(x), fmt(y), str(r)], ["unit", "1"],
                             ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["uuid", sid],
                             prop("Reference", ref, x, y, hide=True), prop("Value", net, vx, vy, justify=just, hide=twin),
                             prop("Footprint", "", x, y, hide=True), prop("Datasheet", "", x, y, hide=True),
                             ["pin", Q("1"), ["uuid", uid(sid, "pin")]],
                             ["instances", ["project", Q(PROJECT),
                                            ["path", Q("/%s/%s" % (self.root_uuid, self.sheet_uuid)),
                                             ["reference", Q(ref)], ["unit", "1"]]]]])
        self.node[c] = net

    def label(self, net, c, d, glob, key):
        x, y = c[0] * G, c[1] * G
        if d[0] != 0:
            ang = 0 if d[0] > 0 else 180
        else:
            ang = 270 if d[1] > 0 else 90
        w = text_w(net) + (2.5 if glob else 0)
        if ang == 0:
            self.block_rect(x + 0.6, y - 1.0, x + w, y + 1.0)
        elif ang == 180:
            self.block_rect(x - w, y - 1.0, x - 0.6, y + 1.0)
        elif ang == 270:
            self.block_rect(x - 1.0, y + 0.6, x + 1.0, y + w)
        else:
            self.block_rect(x - 1.0, y - w, x + 1.0, y - 0.6)
        self.node[c] = net
        if glob:
            shape = self.shape(net)
            self.items.append(["global_label", Q(net), ["shape", shape], ["at", fmt(x), fmt(y), str(ang)],
                               ["fields_autoplaced"], effects(justify="left" if ang in (0, 270) else "right"),
                               ["uuid", uid(self.sheet.file, "gl", key)],
                               ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", fmt(x), fmt(y), "0"],
                                effects(hide=True)]])
        else:
            lj = {0: "left bottom", 180: "right bottom", 90: "left bottom", 270: "right bottom"}[ang]
            self.items.append(["label", Q(net), ["at", fmt(x), fmt(y), str(ang)], ["fields_autoplaced"],
                               effects(justify=lj), ["uuid", uid(self.sheet.file, "ll", key)]])

    def force_label(self, p, glob, key):
        """Last resort for a label: on the pin end itself (no stub), so it can never touch
        another net's wire."""
        self.label(p["net"], p["cell"], p["out"], glob, key)
        self.warnings.append("label for %s sits on %s.%s (no room for a stub)" % (p["net"], p["ref"], p["number"]))

    def shape(self, net):
        src = self.sources.get(net)
        if src is None:
            return "bidirectional"
        return "output" if src == self.sheet.name else "input"

    def attach(self, p, kind, key, any_dir=False, stub=False):
        """Stub out of pin p ending in a power symbol / label. Tries stub lengths 2.54 .. 7.62
        (any_dir: also an L out of the pin, for a label that just needs to sit somewhere)."""
        for n in ((0, 2, 4) if kind == "power" and not stub else (2, 4, 6)):
            if self.free_line(p["cell"], p["out"], n, p["net"]):
                e = self.stub_end(p, n)
                if n:
                    self.add_wire(p["net"], p["cell"], e)
                if kind == "power":
                    self.power_symbol(p["net"], e, p["out"], key)
                else:
                    self.label(p["net"], e, p["out"], kind == "global", key)
                return e
        return None

    # ---------------------------------------------------------- routing
    def route(self, net, start, d0, targets, limit):
        """A* from pin cell `start` (first step d0) to any cell in targets. Returns cell path."""
        def ok(c, d):
            if c in targets:
                return True
            if c in self.blocked:
                return False
            if self.node.get(c, net) != net or self.reserved.get(c, net) != net:
                return False
            par, perp = (self.hw, self.vw) if d[1] == 0 else (self.vw, self.hw)
            if par.get(c, net) != net:
                return False
            return True

        def crossing(c, d):
            perp = self.vw if d[1] == 0 else self.hw
            return perp.get(c, net) != net

        def near(c):
            pen = 0.0
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q = (c[0] + dx, c[1] + dy)
                for m in (self.hw, self.vw, self.node):
                    if m.get(q, net) != net:
                        pen += 0.25
            return pen
        tx = [t[0] for t in targets]; ty = [t[1] for t in targets]
        bx0, bx1, by0, by1 = min(tx), max(tx), min(ty), max(ty)

        def h(c):
            dx = max(bx0 - c[0], 0, c[0] - bx1); dy = max(by0 - c[1], 0, c[1] - by1)
            return dx + dy
        s1 = (start[0] + d0[0], start[1] + d0[1])
        if not ok(s1, d0):
            return None
        if s1 in targets:
            return [start, s1]
        pq = [(h(s1) + 1, 1.0, s1, d0)]
        best = {(s1, d0): 1.0}
        prev = {(s1, d0): None}
        n = 0
        while pq:
            f, g, c, d = heapq.heappop(pq)
            if g > best.get((c, d), 1e18):
                continue
            n += 1
            if n > 200000:
                return None
            if c in targets:
                path = [c]
                k = (c, d)
                while prev[k] is not None:
                    k = prev[k]
                    path.append(k[0])
                path.append(start)
                return path[::-1]
            if g > limit:
                continue
            cross = crossing(c, d)
            for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if nd == (-d[0], -d[1]):
                    continue
                if nd != d and cross:
                    continue                                 # no corner on a foreign wire
                q = (c[0] + nd[0], c[1] + nd[1])
                if not ok(q, nd):
                    continue
                if q in targets and crossing(q, nd) is False and self.node.get(q) is None:
                    pass
                cost = g + 1.0 + (2.0 if nd != d else 0.0) + (3.0 if crossing(q, nd) else 0.0) + near(q) + \
                    (6.0 if q in self.soft else 0.0)
                if cost < best.get((q, nd), 1e18):
                    best[(q, nd)] = cost
                    prev[(q, nd)] = (c, d)
                    heapq.heappush(pq, (cost + h(q), cost, q, nd))
        return None

    def commit_path(self, net, path):
        pts = [path[0]]
        for k in range(1, len(path) - 1):
            a, b, c = path[k - 1], path[k], path[k + 1]
            if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
                pts.append(b)
        pts.append(path[-1])
        end = path[-1]
        # T into the middle of an own wire: split it there
        for i, (a, b) in enumerate(list(self.segs.get(net, []))):
            if end != a and end != b and min(a[0], b[0]) <= end[0] <= max(a[0], b[0]) \
                    and min(a[1], b[1]) <= end[1] <= max(a[1], b[1]):
                self.segs[net].remove((a, b))
                self.segs[net] += [(a, end), (end, b)]
                break
        for a, b in zip(pts[:-1], pts[1:]):
            self.add_wire(net, a, b)

    def cells_of(self, path):
        out = [path[0]]
        for a, b in zip(path[:-1], path[1:]):
            out.append(b)
        return out

    def component(self, net, start):
        """Cells of the copper already joined to `start` (its stub / label wire)."""
        cells, todo = {start}, [start]
        segs = self.segs.get(net, [])
        while todo:
            c = todo.pop()
            for a, b in segs:
                on = (a[1] == b[1] == c[1] and min(a[0], b[0]) <= c[0] <= max(a[0], b[0])) or \
                     (a[0] == b[0] == c[0] and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))
                if on:
                    line = ([(i, a[1]) for i in range(min(a[0], b[0]), max(a[0], b[0]) + 1)] if a[1] == b[1]
                            else [(a[0], j) for j in range(min(a[1], b[1]), max(a[1], b[1]) + 1)])
                    for q in line:
                        if q not in cells:
                            cells.add(q); todo.append(q)
        return cells

    def tree_cells(self, net):
        cells = {c for c, n in self.node.items() if n == net}
        for a, b in self.segs.get(net, []):
            if a[1] == b[1]:
                cells |= {(i, a[1]) for i in range(min(a[0], b[0]), max(a[0], b[0]) + 1)}
            else:
                cells |= {(a[0], j) for j in range(min(a[1], b[1]), max(a[1], b[1]) + 1)}
        return cells

    def snapshot(self):
        return (dict(self.node), dict(self.hw), dict(self.vw), {k: list(v) for k, v in self.segs.items()},
                set(self.blocked), len(self.items), len(self.symbols), self.power_refs[0])

    def restore(self, s):
        self.node, self.hw, self.vw, self.segs, self.blocked = s[0], s[1], s[2], s[3], s[4]
        del self.items[s[5]:]; del self.symbols[s[6]:]
        self.power_refs[0] = s[7]

    # ---------------------------------------------------------- main
    def build(self):
        self.place_parts()
        for p in self.pins:
            self.node[p["cell"]] = p["net"]
        for p in self.pins:
            if p["net"] != "NC":
                q = (p["cell"][0] + p["out"][0], p["cell"][1] + p["out"][1])
                self.reserved.setdefault(q, p["net"])
        # no-connects
        for p in self.pins:
            if p["net"] == "NC":
                x, y = p["cell"][0] * G, p["cell"][1] * G
                self.items.append(["no_connect", ["at", fmt(x), fmt(y)], ["uuid", uid(self.sheet.file, "nc", p["ref"], p["number"])]])
        by_net = {}
        for p in self.pins:
            if p["net"] != "NC":
                by_net.setdefault(p["net"], []).append(p)
        # power symbols at every pin of an unwired rail
        for net, ps in by_net.items():
            if net in POWER_NETS and net not in self.wired_power:
                for p in ps:
                    if self.attach(p, "power", (p["ref"], p["number"])) is None:
                        self.warnings.append("no room for %s symbol at %s.%s" % (net, p["ref"], p["number"]))
                        self.power_symbol(net, p["cell"], p["out"], (p["ref"], p["number"]))
        # label-only parts (connectors): every signal pin gets its own label, wired to nothing else
        labelrefs = set(self.place.get("_labelrefs", ()))
        for net, ps in by_net.items():
            if net in POWER_NETS and net not in self.wired_power:
                continue
            for p in [p for p in ps if p["ref"] in labelrefs]:
                glob = net in self.global_nets
                if net in POWER_NETS:
                    kind = "power"
                else:
                    kind = "global" if glob else "local"
                if self.attach(p, kind, ("lr", p["ref"], p["number"])) is None:
                    if kind == "power":
                        self.power_symbol(net, p["cell"], p["out"], ("lr", p["ref"], p["number"]))
                    else:
                        self.force_label(p, glob, ("lr", p["ref"], p["number"]))
                ps.remove(p)
        # one label (or rail symbol, for wired rails) per routed net that leaves the sheet. A free
        # anchor point (x, y, direction the label extends) can be given per net in _anchors.
        anchors = {}
        dirs = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        for net, (ax, ay, ad) in self.place.get("_anchors", {}).items():
            if net not in by_net:
                self.warnings.append("anchor for %s: net not on this sheet" % net)
                continue
            c, d = cell(snap(ax, G), snap(ay, G)), dirs[ad]
            glob = net in self.global_nets
            kind = "power" if net in POWER_NETS else ("global" if glob else "local")
            if kind == "power":
                self.power_symbol(net, c, d, ("anchor", net))
            else:
                self.label(net, c, d, glob, ("anchor", net))
            pseudo = dict(net=net, cell=c, out=(-d[0], -d[1]), ref="@", number=net, multi=False)
            self.node[c] = net
            by_net[net].append(pseudo)
            anchors[net] = pseudo
        for net, ps in sorted(by_net.items()):
            if net in anchors or not ps:
                continue
            if net in POWER_NETS and net not in self.wired_power:
                continue
            had_labels = any(p["ref"] in labelrefs for p in self.pins if p["net"] == net)
            kind = "power" if net in POWER_NETS else ("global" if net in self.global_nets else
                                                     ("local" if had_labels else None))
            if kind is None or (had_labels and kind == "power"):
                continue
            want = self.place.get("_label", {}).get(net)
            order = sorted(ps, key=lambda p: (not p["multi"], -p["cell"][0]))
            if want:
                order = [p for p in ps if "%s.%s" % (p["ref"], p["number"]) == want] + order
            for p in order:
                e = self.attach(p, kind, ("anchor", net), stub=True)
                if e is not None:
                    anchors[net] = p
                    break
            else:
                self.warnings.append("no room for the %s label" % net)
        # route
        nets = [n for n in by_net if not (n in POWER_NETS and n not in self.wired_power)]

        def span(n):
            xs = [p["cell"][0] for p in by_net[n]] or [0]; ys = [p["cell"][1] for p in by_net[n]] or [0]
            return (max(xs) - min(xs)) + (max(ys) - min(ys))
        failed = []
        for net in sorted(nets, key=span):
            ps = by_net[net]
            if len(ps) < 2:
                continue
            snap_ = self.snapshot()
            first = anchors.get(net) or ps[0]
            done, ok = [first], True
            for p in ps:
                if p is not first:
                    self.reserved.pop((p["cell"][0] + p["out"][0], p["cell"][1] + p["out"][1]), None)
            rest = [p for p in ps if p is not first]
            tree = self.component(net, first["cell"])
            while rest:
                rest.sort(key=lambda p: min(abs(p["cell"][0] - t[0]) + abs(p["cell"][1] - t[1]) for t in tree))
                p = rest.pop(0)
                dist = min(abs(p["cell"][0] - t[0]) + abs(p["cell"][1] - t[1]) for t in tree)
                path = self.route(net, p["cell"], p["out"], tree, limit=dist * 2.5 + 40)
                if path is None:
                    ok = False
                    break
                self.commit_path(net, path)
                tree |= set(self.cells_of(path))
                done.append(p)
            if not ok:
                self.restore(snap_)
                failed.append(net)
        # nets that would not route: a label at every pin instead
        for net in failed:
            glob = net in self.global_nets
            for p in by_net[net]:
                if anchors.get(net) is p:
                    continue
                if self.attach(p, "global" if glob else "local", ("fb", p["ref"], p["number"])) is None:
                    self.force_label(p, glob, ("fb", p["ref"], p["number"]))
            if net not in anchors and not glob:
                pass
        self.failed = failed
        self.flags()
        self.emit_wires()

    def flags(self):
        """PWR_FLAGs for ERC: each one sits on a short wire to a rail symbol of its net."""
        flags = [p for p in self.sheet.parts if p.ref.startswith("#FLG")]
        base = self.place.get("_flags", (25.0, 250.0))
        for i, part in enumerate(flags):
            net = part.pins["1"]
            self.intended[(part.ref, "1")] = net
            x, y = snap(base[0] + 22.86 * i), snap(base[1])
            sym = self.lib("power:PWR_FLAG")
            sid = uid(self.sheet.file, part.ref, 1)
            self.symbols.append(["symbol", ["lib_id", Q("power:PWR_FLAG")], ["at", fmt(x), fmt(y), "0"], ["unit", "1"],
                                 ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"], ["uuid", sid],
                                 prop("Reference", part.ref, x, y - 3.0, hide=True),
                                 prop("Value", "PWR_FLAG", x, y - 3.8),
                                 prop("Footprint", "", x, y, hide=True), prop("Datasheet", "~", x, y, hide=True),
                                 ["pin", Q("1"), ["uuid", uid(sid, "pin", "1")]],
                                 ["instances", ["project", Q(PROJECT),
                                                ["path", Q("/%s/%s" % (self.root_uuid, self.sheet_uuid)),
                                                 ["reference", Q(part.ref)], ["unit", "1"]]]]])
            e = (int(round(x / G)), int(round(y / G)) + 2)
            self.add_wire(net, cell(x, y), e)
            if net == "GND":
                self.power_symbol(net, e, (0, 1), ("flag", part.ref))
            else:                                       # rail symbol turned over, hanging below the flag
                self.power_symbol(net, e, (0, 1), ("flag", part.ref))

    def emit_wires(self):
        ends = {}
        for net, segs in self.segs.items():
            for a, b in segs:
                for c in (a, b):
                    ends[c] = ends.get(c, 0) + 1
                self.items.append(["wire", ["pts", ["xy", fmt(a[0] * G), fmt(a[1] * G)], ["xy", fmt(b[0] * G), fmt(b[1] * G)]],
                                   ["stroke", ["width", "0"], ["type", "default"]],
                                   ["uuid", uid(self.sheet.file, "w", net, a, b)]])
        pin_cells = {p["cell"] for p in self.pins}
        for c, n in ends.items():
            if n + (1 if c in pin_cells else 0) >= 3:
                self.items.append(["junction", ["at", fmt(c[0] * G), fmt(c[1] * G)], ["diameter", "0"],
                                   ["color", "0", "0", "0", "0"], ["uuid", uid(self.sheet.file, "j", c)]])

    def tree(self, page):
        tb = ["title_block", ["title", Q("Bolt logic board - " + self.sheet.title)], ["date", Q(DATE)],
              ["rev", Q(REV)], ["company", Q("Bolt_Invt open-source inverter controller")],
              ["comment", "1", Q("GENERATED by tools/gen_sch.py from tools/sch_design.py + tools/sch_layout.py - "
                                 "edit those, not this sheet")]]
        notes = []
        for i, (x, y, text) in enumerate(self.place.get("_notes", [])):
            notes.append(["text", Q(text), ["at", fmt(x), fmt(y), "0"],
                          ["effects", ["font", ["size", "2", "2"], "bold"], ["justify", "left", "bottom"]],
                          ["uuid", uid(self.sheet.file, "note", i)]])
        return (["kicad_sch", ["version", "20230121"], ["generator", "eeschema"],
                 ["uuid", uid("file", self.sheet.file)], ["paper", Q(PAPER[0])], tb,
                 ["lib_symbols"] + list(self.libs.values())] + notes + self.items + self.symbols)


# ------------------------------------------------------------------ writer helpers
def effects(hide=False, justify=None, size=1.27):
    e = ["effects", ["font", ["size", fmt(size), fmt(size)]]]
    if justify:
        e.append(["justify"] + justify.split())
    if hide:
        e.append("hide")
    return e


def prop(name, value, x, y, ang=0, hide=False, justify=None):
    return ["property", Q(name), Q(value), ["at", fmt(x), fmt(y), str(ang)], effects(hide, justify)]


def build_root(sheets, root_uuid):
    tree = ["kicad_sch", ["version", "20230121"], ["generator", "eeschema"], ["uuid", root_uuid],
            ["paper", Q("A3")],
            ["title_block", ["title", Q("Bolt logic board")], ["date", Q(DATE)], ["rev", Q(REV)],
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
    # KiCad names a net after a label on it, else after a pin ("Net-(R1-Pad2)"): compare by grouping
    want_groups, got_name = {}, {}
    errors = []
    for key, want in intended.items():
        if key[0].startswith("#"):
            continue
        g = got.get(key)
        if want == "NC":
            if g is not None and not g.startswith("unconnected"):
                errors.append("%s-%s should be NC, is on %s" % (key[0], key[1], g))
            continue
        want_groups.setdefault(want, set()).add(key)
    seen = {}
    for want, keys in want_groups.items():
        names = {got.get(k) for k in keys}
        if len(names) != 1 or None in names:
            errors.append("net %s split across %s" % (want, sorted(str(n) for n in names)))
            continue
        name = names.pop()
        if name in seen and seen[name] != want:
            errors.append("nets %s and %s are shorted (%s)" % (want, seen[name], name))
        seen[name] = want
        if name.split("/")[-1] != want and not name.startswith("Net-("):
            errors.append("net %s exported as %s" % (want, name))
    for key, g in got.items():
        if key not in intended and not g.startswith("unconnected"):
            errors.append("%s-%s on %s not in design" % (key[0], key[1], g))
    return errors, got


def sheet_nets(sheets):
    where = {}
    for sh in sheets:
        for p in sh.parts:
            for n in p.pins.values():
                if n != "NC":
                    where.setdefault(n, set()).add(sh.name)
    return {n for n, s in where.items() if len(s) > 1 and n not in POWER_NETS}


def main():
    import sch_design
    import sch_layout
    if hasattr(sch_design, "write_custom_symbols"):
        sch_design.write_custom_symbols(os.path.join(PROJ, "Bolt.kicad_sym"), extra=custom_power_symbols())
        kisym._lib_cache.pop("Bolt", None)
    sheets = sch_design.SHEETS
    refs = [p.ref for sh in sheets for p in sh.parts]
    dups = sorted({r for r in refs if refs.count(r) > 1})
    if dups:
        raise ValueError("duplicate reference designators: %s" % dups)
    root_uuid = uid("root")
    intended = {}
    glob = sheet_nets(sheets)
    missing = sorted(n for n in glob if n not in sch_layout.SOURCE)
    if missing:
        print("note: no source sheet given for %s (bidirectional labels)" % ", ".join(missing))
    power_refs = [1]
    total_failed = 0
    for i, sh in enumerate(sheets):
        b = Builder(sh, sch_layout.PLACE.get(sh.name, {}), sch_layout.SOURCE, glob, root_uuid,
                    uid("sheet", sh.file), intended, power_refs)
        b.build()
        open(os.path.join(PROJ, sh.file), "w").write(dump(b.tree(i + 2)) + "\n")
        total_failed += len(b.failed)
        print("%-9s %3d wires, %d nets drawn as labels%s" % (
            sh.name, sum(len(v) for v in b.segs.values()), len(b.failed),
            (": " + " ".join(b.failed)) if b.failed else ""))
        for w in b.warnings:
            print("    " + w)
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
