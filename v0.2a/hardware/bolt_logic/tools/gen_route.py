#!/usr/bin/env python3
"""Stage 2 of layout: stackup + planes, autoroute with FreeRouting, pour, DRC.

    python3 tools/gen_mech.py && python3 tools/gen_layout.py && python3 tools/gen_route.py

Stackup (4 layers, 2.0 mm), v0.2a after the forum review:
    F.Cu  signals (+ GND pour)
    In1.Cu solid GND plane, nothing routed on it
    In2.Cu power planes, nothing routed on it: a large +3V3 plane, with VCC_12V / +5V islands around
           the regulators and an ESP_3V3 island around the WiFi module (POWER_ZONES)
    B.Cu  signals (+ GND pour)
Power pins connect plane -> via -> decoupling-cap pad -> short trace -> IC pin (plane_fanout).
Requires: java, xvfb-run, FreeRouting jar (FREEROUTING_JAR, default ~/tools/freerouting.jar).
"""
import math
import os
import re
import subprocess
import sys

import pcbnew
from pcbnew import FromMM, VECTOR2I

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gen_mech import P, BODY, TAB, NOTCH, CHAMFER  # noqa: E402
import buck_block  # noqa: E402

PCB = os.path.join(PROJ, "bolt_logic.kicad_pcb")
WORK = os.path.join(PROJ, "route_work")
JAR = os.environ.get("FREEROUTING_JAR", os.path.expanduser("~/tools/freerouting.jar"))

# Net classes (width, clearance in mm). Everything else: KiCad default 0.2 / 0.2.
NETCLASSES = {
    # contactor coil currents: wide, short runs from the drivers' tabs to CN1
    "CONTACTOR": (1.2, 0.3, ["MAIN_CONT_OUT", "PRECHG_OUT_SW", "PUMP_OUT_SW"]),
    "POWER": (0.8, 0.3, ["VBAT", "VBAT_SW", "VCC_12V", "+12V_GATE", "SW_5V", "AUX_12V", "EXC_OA", "EXC_OB",
                         "EXC_OA_C", "EXC_P", "EXC_N"]),
    "SUPPLY": (0.5, 0.2, ["+5V", "+3V3", "+5V_A", "VDDA", "ESP_3V3", "AUX_5V", "PEDAL_5V", "ENC_5V", "CHASSIS",
                          "Q1_IN", "Q2_IN"]),
}


def outline_points():
    """Board outline polygon in the design frame (notch arc as segments)."""
    b, t, n, c = BODY, TAB, NOTCH, CHAMFER
    pts = [(b["x0"], b["y1"]), c["top"], c["right"], (b["x1"], b["y0"])]
    for i in range(17):
        a = math.pi * i / 16
        pts.append((n["cx"] + n["r"] * math.cos(a), n["cy"] + n["r"] * math.sin(a)))
    pts += [(b["x0"], b["y0"]), (b["x0"], t["y_lo"]), (t["x_outer"], t["y_lo"]),
            (t["x_outer"], t["y_hi"]), (b["x0"], t["y_hi"])]
    return pts


def add_zone(board, layer, net, priority=0, name="", polys=None, clearance=0.3, min_width=0.25,
             thermal=(0.3, 0.4), connection=None, locked=False):
    """Copper zone. polys: list of shapely polygons or point lists in the design frame (default:
    the board outline). KiCad clips the fill to the board outline, so plane rectangles may overlap
    it. thermal = (gap, spoke) mm for through-hole pads."""
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(board.FindNet(net))
    z.SetAssignedPriority(priority)
    z.SetMinThickness(FromMM(min_width))
    z.SetLocalClearance(FromMM(clearance))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL if connection is None else connection)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetThermalReliefGap(FromMM(thermal[0]))
    z.SetThermalReliefSpokeWidth(FromMM(thermal[1]))
    z.SetLocked(locked)
    if name:
        z.SetZoneName(name)
    ol = z.Outline()
    for poly in (polys or [outline_points()]):
        rings = [list(poly.exterior.coords)[:-1]] + [list(h.coords)[:-1] for h in poly.interiors] \
            if hasattr(poly, "exterior") else [poly]
        ol.NewOutline()
        for x, y in rings[0]:
            ol.Append(P(x, y))
        for hole in rings[1:]:
            h = ol.NewHole()
            for x, y in hole:
                ol.Append(P(x, y).x, P(x, y).y, ol.OutlineCount() - 1, h)
    board.Add(z)
    return z


def add_rule_area(board, layers, poly, tracks=True, vias=True, pour=False, name=""):
    """Keep-out (rule area) on the given copper layers; poly in the design frame."""
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.SetDoNotAllowTracks(tracks); z.SetDoNotAllowVias(vias); z.SetDoNotAllowCopperPour(pour)
    z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
    if name:
        z.SetZoneName(name)
    ol = z.Outline(); ol.NewOutline()
    pts = list(poly.exterior.coords)[:-1] if hasattr(poly, "exterior") else poly
    for x, y in pts:
        ol.Append(P(x, y))
    board.Add(z)
    return z


def rect(x0, y0, x1, y1):
    from shapely.geometry import box
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


# In2.Cu power planes (design frame rectangles; KiCad clips them to the outline). A higher priority
# zone is cut out of a lower one with the zone clearance. jrbe's suggestion: a small 12 V plane at
# the high-side switch / buck, a 5 V plane, and a 3.3 V plane over most of the board.
POWER_ZONES = [  # net, priority, [rectangles]
    ("+3V3", 0, [(-20.0, -10.0, 280.0, 112.0)]),
    ("VCC_12V", 2, []),          # filled in by plane_regions() from the placement
    ("+5V", 1, []),
    ("ESP_3V3", 2, []),
]
INNER_THERMAL = (0.5, 0.45)      # jrbe: larger thermal reliefs on the inner planes for the through-hole parts


def plane_regions(board):
    """Rectangles of the In2 islands (design frame), drawn around the regulators as placed by
    gen_layout.py; checked against the pads they must serve."""
    from gen_mech import to_design
    zones = {
        # 12 V: reverse-polarity diode, bulk caps, buck input, Q2's supply tab
        "VCC_12V": [(12.0, 78.0, 44.6, 108.0), (43.0, 82.0, 56.0, 87.5)],      # pieces overlap: one island
        # 5 V: buck output and LDO input; the +5V loads elsewhere are fed by traces
        "+5V": [(44.6, 87.5, 60.0, 108.0), (56.0, 78.0, 91.5, 89.0), (86.0, 84.0, 94.6, 88.0)],
        # WiFi 3.3 V: LDO U31, bulk C124, module supply pin and its caps
        "ESP_3V3": [(188.0, -10.0, 280.0, 24.0)],
    }
    must = {"VCC_12V": [("D1", "1"), ("U1", "3"), ("Q2", "3")], "+5V": [("L1", "2"), ("U2", "3")],
            "ESP_3V3": [("U31", "2"), ("U30", "2"), ("C124", "1")]}
    for net, pads in must.items():
        for ref, num in pads:
            x, y = to_design(pad_of(board, ref, num).GetPosition())
            if not any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in zones[net]):
                raise SystemExit("plane_regions: %s.%s (%.1f, %.1f) is outside the %s island - placement moved?"
                                 % (ref, num, x, y, net))
    return zones


def setup(board):
    board.SetCopperLayerCount(4)
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)       # solid GND plane, not routed
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)       # power planes, not routed
    if len(board.Zones()) or len(board.GetTracks()):
        # removing items through the SWIG API corrupts later ZONE wrappers in KiCad 7; start clean
        raise SystemExit("board already has zones/tracks: re-run gen_mech.py and gen_layout.py first")
    add_zone(board, pcbnew.In1_Cu, "GND", 0, "GND_PLANE", thermal=INNER_THERMAL)
    regions = plane_regions(board)
    for net, prio, rects in POWER_ZONES:
        from shapely.ops import unary_union
        u = unary_union([rect(*r) for r in (rects or regions[net])])     # one outline per island
        add_zone(board, pcbnew.In2_Cu, net, prio, net + "_PLANE", polys=list(getattr(u, "geoms", [u])),
                 thermal=INNER_THERMAL)


def net_widths(board):
    """net -> (width, clearance) mm. A class width is capped at the narrowest SMD pad on the net
    (FreeRouting cannot neck down, so a 0.5 mm +3V3 trace could never enter a 0.3 mm LQFP pad)."""
    narrow = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.GetNetname():
                d = pcbnew.ToMM(min(p.GetSize().x, p.GetSize().y))
                narrow[p.GetNetname()] = min(narrow.get(p.GetNetname(), 99), d)
    out = {}
    for _, (w, clr, nets) in NETCLASSES.items():
        for n in nets:
            # a track as wide as an SMD pad violates clearance to that pad's neighbours: stay 0.05 under
            out[n] = (max(0.2, min(w, math.floor((narrow.get(n, 99) - 0.05) * 20 + 1e-6) / 20)), clr)
    return out


EDGE_INSET = 0.3     # mm; routing boundary pulled in so copper keeps >= 0.4 mm from the board edge


def patch_dsn(path, board):
    """Add per-net width classes and an inset routing boundary to the DSN (units: um)."""
    from shapely.geometry import Polygon
    t = open(path).read()
    res = re.search(r"\(resolution\s+(\w+)\s+(\d+)\)", t)
    scale = {"um": 1.0, "mil": 1 / 25.4, "mm": 0.001}[res.group(1)] * 1000 if res else 1000
    # boundary inset
    b = re.search(r"\(boundary\s*\(path pcb 0([-\d.\s]+)\)\s*\)", t)
    v = [float(x) for x in b.group(1).split()]
    poly = Polygon(list(zip(v[0::2], v[1::2]))).buffer(-EDGE_INSET * scale, join_style=2)
    pts = list(poly.exterior.coords)
    t = t[:b.start(1)] + " " + "  ".join("%d %d" % (round(x), round(y)) for x, y in pts) + t[b.end(1):]
    # net classes
    m = re.search(r"\(class kicad_default \"\"(.*?)\(circuit", t, re.S)
    if not m:
        raise RuntimeError("DSN default class not found")
    members = m.group(1)
    groups = {}
    for n, wc in net_widths(board).items():
        if re.search(r'(?<![\w+])"?%s"?(?=[\s)])' % re.escape(n), members):
            members = re.sub(r'(\s)"?%s"?(?=[\s)])' % re.escape(n), r"\1", members, count=1)
            groups.setdefault(wc, []).append(n)
    blocks = []
    for (w, clr), nets in sorted(groups.items()):
        q = " ".join('"%s"' % n if not re.match(r"^[A-Za-z_][\w]*$", n) else n for n in nets)
        blocks.append('(class W%03d_C%03d %s\n      (circuit (use_via Via[0-3]_600:300_um))\n'
                      '      (rule (width %d) (clearance %d)))' % (w * 100, clr * 100, q, w * scale, clr * scale))
    t = t[:m.start(1)] + members + t[m.end(1):]
    t = t.replace("(class kicad_default", "\n    ".join(blocks) + "\n    (class kicad_default", 1)
    open(path, "w").write(t)
    return groups


def import_ses(board, ses_path, dsn_path):
    """Recreate FreeRouting's wires and vias on the board (KiCad 7's ImportSpecctraSES
    needs the GUI). Scale/sign are calibrated from component placements in DSN vs SES."""
    import kisym
    ses = kisym.parse(open(ses_path).read())
    # DSN declares (string_quote ") - a bare quote the tokenizer would treat as a string opener
    dsn = kisym.parse(open(dsn_path).read().replace('(string_quote ")', "(string_quote dq)"))

    def places(tree, key):
        out = {}
        sect = kisym.first(tree, key)
        for comp in kisym.find(sect, "component"):
            for pl in kisym.find(comp, "place"):
                out[pl[1]] = (float(pl[2]), float(pl[3]))
        return out
    pd, ps = places(dsn, "placement"), places(ses, "placement")
    common = [r for r in pd if r in ps and abs(pd[r][0]) > 1000]
    f = sum(ps[r][0] / pd[r][0] for r in common) / len(common)          # SES units per DSN unit
    # DSN units are um, y negated relative to KiCad
    to_k = lambda x, y: VECTOR2I(int(round(x / f * 1000)), int(round(-y / f * 1000)))
    # the board must still have the placement that was routed
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    moved = [r for r, (x, y) in ps.items()
             if r in fps and (fps[r].GetPosition() - to_k(x, y)).EuclideanNorm() > 1000]
    if moved:
        raise RuntimeError("placement changed since routing: %s" % moved[:10])
    routes = kisym.first(ses, "routes")
    layers = {board.GetLayerName(l): l for l in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)}
    ntracks = nvias = 0
    for net in kisym.find(kisym.first(routes, "network_out"), "net"):
        ni = board.FindNet(net[1])
        for item in net[2:]:
            if not isinstance(item, list):
                continue
            if item[0] == "wire":
                path = kisym.first(item, "path")
                layer = layers[path[1]]
                width = int(round(float(path[2]) / f * 1000))
                coords = [float(v) for v in path[3:] if not isinstance(v, list)]
                pts = [to_k(coords[i], coords[i + 1]) for i in range(0, len(coords) - 1, 2)]
                for a, b in zip(pts[:-1], pts[1:]):
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(a); t.SetEnd(b); t.SetWidth(width); t.SetLayer(layer); t.SetNet(ni)
                    board.Add(t); ntracks += 1
            elif item[0] == "via":
                m = re.search(r"_(\d+):(\d+)_um", item[1])
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(to_k(float(item[2]), float(item[3])))
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetWidth(FromMM(int(m.group(1)) / 1000)); v.SetDrill(FromMM(int(m.group(2)) / 1000))
                v.SetNet(ni)
                board.Add(v); nvias += 1
    return ntracks, nvias


SIG = (pcbnew.F_Cu, pcbnew.B_Cu)     # routed layers; In1 (GND) and In2 (power) are planes
VIA_D, VIA_DRILL = 0.6, 0.3
CLR = 0.25           # mm, stitching via / stub clearance to foreign copper
HOLE_GAP = 0.5       # mm, drill edge to drill edge


def keepouts(board):
    """Union of copper rule areas (ESP32 antenna keep-out), board mm coords."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    mm = pcbnew.ToMM
    polys = []
    zones = list(board.Zones()) + [z for fp in board.GetFootprints() for z in fp.Zones()]
    for z in zones:
        if z.GetIsRuleArea():
            ol = z.Outline()
            for i in range(ol.OutlineCount()):
                c = ol.Outline(i)
                polys.append(Polygon([(mm(c.CPoint(k).x), mm(c.CPoint(k).y)) for k in range(c.PointCount())]))
    return unary_union(polys)


def _obstacles(board):
    """Shapely geometry (board mm coords) of non-GND copper per layer, all pads, and drills."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    mm = pcbnew.ToMM
    layers = SIG
    foreign = {l: [] for l in layers}
    pads_f, drills = [], []
    for t in board.GetTracks():
        if t.GetNetname() == "GND":
            if t.GetClass() == "PCB_VIA":
                drills.append(Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetDrill()) / 2))
            continue
        if t.GetClass() == "PCB_VIA":
            g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
            for l in layers:
                foreign[l].append(g)
            drills.append(Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetDrill()) / 2))
        elif t.GetLayer() in foreign:
            g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))])
            foreign[t.GetLayer()].append(g.buffer(mm(t.GetWidth()) / 2))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            g = box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
            th = p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            if th:
                drills.append(Point(mm(p.GetPosition().x), mm(p.GetPosition().y)).buffer(mm(p.GetDrillSize().x) / 2))
            pads_f.append(g)
            if p.GetNetname() != "GND":
                for l in layers:
                    if th or p.IsOnLayer(l):
                        foreign[l].append(g)
    ko = keepouts(board)
    return ({l: unary_union(v + [ko]) for l, v in foreign.items()}, unary_union(pads_f), unary_union(drills))


def stitch(board, grid=7.0, lock=False):
    """GND vias: one beside every SMD GND pad that has none yet (short stub to it), then, if grid
    is set, a stitching grid tying the F/In2/B pours to the In1 plane. Every candidate is checked
    against foreign copper on all layers. Run before routing (grid=None, lock=True) as a GND
    fan-out so the router works around it, and again after routing for the grid."""
    from shapely.geometry import LineString, Point, Polygon
    from gen_layout import dbox
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    foreign, pads, drills = _obstacles(board)
    outline = Polygon([(mm(Pd(x, y).x), mm(Pd(x, y).y)) for x, y in outline_points()])
    inner = outline.buffer(-(0.4 + VIA_D / 2))
    bodies = []
    for fp in board.GetFootprints():
        x0, y0, x1, y1 = dbox(fp)
        a, b = Pd(x0, y0), Pd(x1, y1)
        bodies.append(Polygon([(mm(a.x), mm(a.y)), (mm(b.x), mm(a.y)), (mm(b.x), mm(b.y)), (mm(a.x), mm(b.y))]))
    from shapely.ops import unary_union
    bodies = unary_union(bodies)
    gnd = board.FindNet("GND")
    placed = []

    def via_ok(x, y, keep=CLR, avoid_bodies=False):
        c = Point(x, y)
        if not inner.contains(c):
            return False
        ring = c.buffer(VIA_D / 2 + keep)
        if any(ring.intersects(g) for g in foreign.values()) or ring.intersects(pads):
            return False
        if c.buffer(VIA_DRILL / 2 + HOLE_GAP).intersects(drills):
            return False
        if avoid_bodies and c.buffer(VIA_D / 2).intersects(bodies):
            return False
        return True

    def add_via(x, y):
        nonlocal drills
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
        v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL)); v.SetNet(gnd)
        v.SetLocked(lock)
        board.Add(v)
        drills = drills.union(Point(x, y).buffer(VIA_DRILL / 2))
        placed.append((x, y))

    pad_vias = 0
    stubbed = {(t.GetStart().x, t.GetStart().y) for t in board.GetTracks()
               if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "GND"}
    for fp in board.GetFootprints():
        if fp.GetReference() in buck_block.REFS:      # buck block GND is drawn with its own vias
            continue
        for p in fp.Pads():
            if p.GetNetname() != "GND" or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            px, py = mm(p.GetPosition().x), mm(p.GetPosition().y)
            if (p.GetPosition().x, p.GetPosition().y) in stubbed:
                continue
            bb = p.GetBoundingBox()
            hw, hh = mm(bb.GetWidth()) / 2, mm(bb.GetHeight()) / 2
            sw = min(0.3, min(hw, hh) * 2 - 0.05)          # stub narrower than the pad (fine-pitch pins)
            ring = []
            for dist in (0.55, 0.9, 1.3, 1.8):
                for ang in range(0, 360, 30):
                    a = math.radians(ang)
                    ex = px + math.cos(a) * hw; ey = py + math.sin(a) * hh      # pad edge in direction a
                    ring.append((ex + math.cos(a) * dist, ey + math.sin(a) * dist))
            # v0.2a (jrbe): no vias under IC bodies - only right outside the pad
            cands = ring
            lay = p.GetLayer() if p.GetLayer() in foreign else pcbnew.F_Cu
            for x, y in cands:
                if not via_ok(x, y, keep=0.2) or Point(x, y).buffer(VIA_D / 2).intersects(bodies):
                    continue
                stub = LineString([(px, py), (x, y)]).buffer(sw / 2 + 0.2)
                if stub.intersects(foreign[lay]):
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(p.GetPosition()); t.SetEnd(VECTOR2I(FromMM(x), FromMM(y)))
                t.SetWidth(FromMM(sw)); t.SetLayer(lay); t.SetNet(gnd); t.SetLocked(lock)
                board.Add(t)
                add_via(x, y); pad_vias += 1
                break
    grid_vias = 0
    if not grid:
        return pad_vias, 0
    x0, y0, x1, y1 = outline.bounds
    y = y0 + grid / 2
    while y < y1:
        x = x0 + grid / 2
        while x < x1:
            if via_ok(x, y, keep=0.5, avoid_bodies=True) and all(math.dist((x, y), q) > grid * 0.6 for q in placed):
                add_via(x, y); grid_vias += 1
            x += grid
        y += grid
    return pad_vias, grid_vias


# ------------------------------------------------------------------ power-plane fan-out
PLANE_NETS = ("+3V3", "+5V", "VCC_12V", "ESP_3V3")


def plane_region(board, net):
    """Where a via of `net` lands on its own In2 zone: its zone outlines minus every higher
    priority In2 zone (with margin), inside the board (board mm). None if it has no zone."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    def poly(z):
        ol = z.Outline()
        out = []
        for i in range(ol.OutlineCount()):
            c = ol.Outline(i)
            out.append(Polygon([(mm(c.CPoint(k).x), mm(c.CPoint(k).y)) for k in range(c.PointCount())]))
        return unary_union(out)
    zs = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetLayer() == pcbnew.In2_Cu]
    own = [z for z in zs if z.GetNetname() == net]
    if not own:
        return None
    pr = min(z.GetAssignedPriority() for z in own)
    reg = unary_union([poly(z) for z in own])
    for z in zs:
        if z.GetNetname() != net and z.GetAssignedPriority() > pr:
            reg = reg.difference(poly(z).buffer(0.6 + VIA_D / 2))
    outline = Polygon([(mm(Pd(x, y).x), mm(Pd(x, y).y)) for x, y in outline_points()]).buffer(-(1.0 + VIA_D / 2))
    return reg.intersection(outline)


def pad_clusters(board, net):
    """Pads of `net` grouped by the copper already joining them: [(pads, has_via)]."""
    from shapely.geometry import LineString, Point
    mm = pcbnew.ToMM
    items = []                                           # (kind, obj, geom, layers)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == net:
                lays = set(SIG) if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else {l for l in SIG if p.IsOnLayer(l)}
                items.append(("pad", p, pad_geom(p), lays))
    for t in board.GetTracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            items.append(("via", t, Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2), set(SIG)))
        elif t.GetLayer() in SIG:
            items.append(("trk", t, LineString([(mm(t.GetStart().x), mm(t.GetStart().y)),
                                               (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2),
                          {t.GetLayer()}))
    for z in board.Zones():                              # locked pre-route zones (buck block, contactors)
        if not z.GetIsRuleArea() and z.GetNetname() == net and z.GetLayer() in SIG:
            from shapely.geometry import Polygon
            ol = z.Outline()
            for i in range(ol.OutlineCount()):
                c = ol.Outline(i)
                items.append(("zone", z, Polygon([(mm(c.CPoint(k).x), mm(c.CPoint(k).y)) for k in range(c.PointCount())]),
                              {z.GetLayer()}))
    parent = list(range(len(items)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][3] & items[j][3] and items[i][2].intersects(items[j][2]):
                parent[find(i)] = find(j)
    groups = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    return [([it[1] for it in g if it[0] == "pad"], any(it[0] == "via" or (it[0] == "pad" and it[1].GetAttribute() ==
             pcbnew.PAD_ATTRIB_PTH) for it in g)) for g in groups.values()]


def pad_via(board, p, net, region=None, fo=None, drills=None, bodies=None, w=None, lock=True, n=1):
    """Via(s) right outside pad p (never inside a footprint body), tied by a short stub."""
    from shapely.geometry import LineString, Point
    mm = pcbnew.ToMM
    if fo is None:
        fo, drills = obstacles_for(board, net)
    if bodies is None:
        bodies = body_union(board)
    px, py = mm(p.GetPosition().x), mm(p.GetPosition().y)
    bb = p.GetBoundingBox()
    hw, hh = mm(bb.GetWidth()) / 2, mm(bb.GetHeight()) / 2
    sw = w or min(0.5, max(0.2, min(hw, hh) * 2 - 0.05))
    lay = p.GetLayer() if p.GetLayer() in SIG else pcbnew.F_Cu
    placed = []
    for dist in (0.55, 0.9, 1.3, 1.8, 2.4):
        for ang in range(0, 360, 15):
            a = math.radians(ang)
            ex, ey = px + math.cos(a) * hw, py + math.sin(a) * hh
            x, y = ex + math.cos(a) * dist, ey + math.sin(a) * dist
            c = Point(x, y)
            if region is not None and not region.contains(c):
                continue
            if c.buffer(VIA_D / 2).intersects(bodies) and not pad_geom(p).buffer(VIA_D / 2 + 0.05).contains(c):
                continue
            if any(c.buffer(VIA_D / 2 + 0.2).intersects(g) for g in fo.values()):
                continue
            if c.buffer(VIA_DRILL / 2 + HOLE_GAP).intersects(drills):
                continue
            if LineString([(px, py), (x, y)]).buffer(sw / 2 + 0.2).intersects(fo[lay]):
                continue
            add_track(board, net, lay, (px, py), (x, y), sw, lock)
            add_via(board, net, x, y, lock)
            drills = drills.union(c.buffer(VIA_DRILL / 2))
            placed.append((x, y))
            if len(placed) >= n:
                return placed
    return placed


def plane_fanout(board):
    """jrbe / Jack Bauer: plane -> via -> decoupling cap -> IC. Each group of pads already joined by
    copper (an IC power pin and its decap, joined by prestub) gets one via at its capacitor, right
    outside the pad, where the via lands on the net's own In2 plane; large pads (LDO tabs) get
    several. Pads outside their plane are left to the router."""
    bodies = body_union(board)
    stats = {}
    for net in PLANE_NETS:
        region = plane_region(board, net)
        if region is None or region.is_empty:
            continue
        nv = 0
        for pads, has_via in pad_clusters(board, net):
            if has_via or not pads:
                continue
            order = sorted(pads, key=lambda p: (not p.GetParentAsString().startswith("C"),
                                                -(p.GetSize().x * p.GetSize().y)))
            fo, drills = obstacles_for(board, net)
            for p in order:
                big = pcbnew.ToMM(p.GetSize().x) * pcbnew.ToMM(p.GetSize().y) > 6.0
                got = pad_via(board, p, net, region, fo, drills, bodies, n=3 if big else 1)
                if got:
                    nv += len(got)
                    break
        stats[net] = nv
    return stats


def gnd_orphans(board, lock=True):
    """GND pads still without a way down to the plane (QFP ground pins boxed in by their
    neighbours' fan-out): a short grid route to the nearest GND via, which may drop its own via
    on the way."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    outline = Polygon([(mm(Pd(x, y).x), mm(Pd(x, y).y)) for x, y in outline_points()]).buffer(-0.4)
    fixed = 0
    for pads, has_via in pad_clusters(board, "GND"):
        smd = [p for p in pads if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
        if has_via or not smd:
            continue
        p = smd[0]
        px, py = mm(p.GetPosition().x), mm(p.GetPosition().y)
        vias = sorted(((mm(t.GetPosition().x), mm(t.GetPosition().y)) for t in board.GetTracks()
                       if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"), key=lambda v: math.dist(v, (px, py)))[:3]
        if not vias:
            continue
        fo, _ = obstacles_for(board, "GND")
        src = {l: pad_geom(p) for l in SIG if p.IsOnLayer(l)}
        fp = board.FindFootprintByReference(p.GetParentAsString())
        if fp.GetPadCount() >= 20:
            # fine-pitch pin: leave straight along the pin axis first (exact geometry clears the
            # neighbouring pins), then search from the end of that stub
            from shapely.geometry import LineString
            c = fp.GetPosition()
            dx, dy = mm(p.GetPosition().x - c.x), mm(p.GetPosition().y - c.y)
            ux, uy = (math.copysign(1, dx), 0.0) if abs(dx) > abs(dy) else (0.0, math.copysign(1, dy))
            half = mm(max(p.GetSize().x, p.GetSize().y)) / 2
            for ext in (0.6, 1.0, 1.5):
                e = (px + ux * (half + ext), py + uy * (half + ext))
                if not LineString([(px, py), e]).buffer(0.125 + 0.2).intersects(fo[p.GetLayer()].difference(pad_geom(p).buffer(0.01))):
                    add_track(board, "GND", p.GetLayer(), (px, py), e, 0.25, lock)
                    src = {p.GetLayer(): Point(e).buffer(0.125)}
                    break
        dst = {l: unary_union([Point(v).buffer(VIA_D / 2) for v in vias]) for l in SIG}
        r = maze(board, "GND", src, dst, fo, outline, 0.25, 0.2, layers=SIG, vias_ok=True)
        if not r and fp.GetPadCount() >= 20:
            # boxed in outside (the 32 kHz crystal sits right outside MCU pin 63): the only
            # exception to "no vias under ICs" - a via just inside the pin row, under the LQFP
            # body (no pad there, tented)
            c = fp.GetPosition()
            dx, dy = mm(p.GetPosition().x - c.x), mm(p.GetPosition().y - c.y)
            ux, uy = (math.copysign(1, dx), 0.0) if abs(dx) > abs(dy) else (0.0, math.copysign(1, dy))
            half = mm(max(p.GetSize().x, p.GetSize().y)) / 2
            e = (px - ux * (half + 0.75), py - uy * (half + 0.75))
            add_track(board, "GND", p.GetLayer(), (px, py), e, 0.25, lock)
            add_via(board, "GND", e[0], e[1], lock)
            print("  GND pad %s.%s: via under the body (no room outside)" % (p.GetParentAsString(), p.GetNumber()))
            fixed += 1
            continue
        if not r:
            print("  GND pad %s.%s: no way to the plane" % (p.GetParentAsString(), p.GetNumber()))
            continue
        for l, a, b in r[0]:
            if math.dist(a, b) > 1e-6:
                add_track(board, "GND", l, a, b, 0.25, lock)
        for x, y in r[1]:
            add_via(board, "GND", x, y, lock)
        fixed += 1
    return fixed


def repair_clearance(board, rounds=3):
    """Router leftovers that touch another net (FreeRouting very occasionally leaves a loop across
    a neighbouring pin's track): rip up the offending router segments of one net near the spot and
    let complete_all() close the connection again."""
    mm = pcbnew.ToMM
    total = 0
    for _ in range(rounds):
        rep = os.path.join(WORK, "clr.rpt")
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.WriteDRCReport(board, rep, pcbnew.EDA_UNITS_MILLIMETRES, True)
        hits = re.findall(r"\[clearance\].*?\n.*?\n\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): Track \[([^\]]+)\].*?\n"
                          r"\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): Track \[([^\]]+)\]", open(rep).read())
        dead = {}
        for x1, y1, n1, x2, y2, n2 in hits:
            if n1 == n2:
                continue
            # rip the net that is not a power class net, else the first one
            pick = n1 if n1 not in net_widths(board) else n2
            pt = ((float(x1) + float(x2)) / 2, (float(y1) + float(y2)) / 2)
            for t in board.GetTracks():
                if t.GetClass() == "PCB_TRACK" and t.GetNetname() == pick and not t.IsLocked():
                    a = (mm(t.GetStart().x), mm(t.GetStart().y)); b = (mm(t.GetEnd().x), mm(t.GetEnd().y))
                    if min(math.dist(a, pt), math.dist(b, pt)) < 2.5:
                        dead[t.m_Uuid.AsString()] = t
        if not dead:
            break
        for t in dead.values():
            board.Remove(t)
        total += len(dead)
        print("  clearance repair: ripped %d segment(s)" % len(dead))
        remove_dangling(board)
        complete_all(board)
    return total


def open_pairs(board):
    """Unconnected item pairs (non-GND) from KiCad's DRC: [(x, y, kind, net), (x, y, kind, net)]."""
    rep = os.path.join(WORK, "open.rpt")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())       # plane nets connect through the In2 zones
    pcbnew.WriteDRCReport(board, rep, pcbnew.EDA_UNITS_MILLIMETRES, True)
    lines = open(rep).read().split("\n")
    pairs = []
    for i, l in enumerate(lines):
        if l.startswith("[unconnected_items]"):
            items = []
            for k in (2, 3):
                m = re.match(r"\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): (\S+).*?\[([^\]]+)\]", lines[i + k])
                if m:
                    items.append((float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)))
            if len(items) == 2 and items[0][3] == items[1][3] and items[0][3] != "GND":
                pairs.append(items)
    return pairs


def net_clusters(board, net):
    """Own-net copper grouped into electrically connected clusters: [{layer: geometry}]."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    mm = pcbnew.ToMM
    L = SIG
    items = []
    for t in board.GetTracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            items.append((set(L), Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)))
        elif t.GetLayer() in L:
            items.append(({t.GetLayer()}, LineString([(mm(t.GetStart().x), mm(t.GetStart().y)),
                                                       (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2)))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == net:
                bb = p.GetBoundingBox()
                lays = set(L) if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else {l for l in L if p.IsOnLayer(l)}
                items.append((lays, box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))))
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i][0] & items[j][0] and items[i][1].intersects(items[j][1]):
                parent[find(i)] = find(j)
    groups = {}
    for i, (lays, g) in enumerate(items):
        for l in lays:
            groups.setdefault(find(i), {}).setdefault(l, []).append(g)
    return [{l: unary_union(v) for l, v in grp.items()} for grp in groups.values()]


def maze(board, net, src_map, dst_map, fo, outline, w, clr, grid=float(os.environ.get("MAZE_GRID", "0.05")), margin=6.0,
         soft=None, soft_cost=0.5, layers=None, vias_ok=True):
    """Grid A* over the signal layers (F.Cu / B.Cu; 8-way moves, through vias) between two items of one net.
    ga/gb: shapely geometries of the items, la/lb their copper layer (None = any layer).
    fo: {layer: foreign copper}. Returns (segments [(layer, p0, p1)], vias [pt]) or None."""
    import heapq
    import numpy as np
    import shapely
    L = tuple(layers) if layers else SIG
    from shapely.ops import unary_union
    ga, gb = unary_union(list(src_map.values())), unary_union(list(dst_map.values()))
    x0, y0, x1, y1 = ga.union(gb).bounds
    x0 -= margin; y0 -= margin; x1 += margin; y1 += margin
    nx, ny = int((x1 - x0) / grid) + 1, int((y1 - y0) / grid) + 1
    xs = [float(v) for v in x0 + np.arange(nx) * grid]
    ys = [float(v) for v in y0 + np.arange(ny) * grid]
    X, Y = np.meshgrid(np.array(xs), np.array(ys), indexing="ij")
    inside = shapely.contains_xy(outline.buffer(-(w / 2)), X, Y)
    free, viaok = [], np.copy(inside)
    for l in L:
        g = fo.get(l)
        f = inside.copy()
        if g is not None and not g.is_empty:
            f &= ~shapely.contains_xy(g.buffer(w / 2 + clr + grid * 0.75), X, Y)
            viaok &= ~shapely.contains_xy(g.buffer(VIA_D / 2 + clr), X, Y)
        free.append(f)
    for l in (pcbnew.F_Cu, pcbnew.B_Cu):                 # a via spans both outer layers
        if l not in L and fo.get(l) is not None and not fo[l].is_empty:
            viaok &= ~shapely.contains_xy(fo[l].buffer(VIA_D / 2 + clr), X, Y)
    pen = [np.zeros_like(inside) for _ in L]
    if soft:                                             # rip-up mode: soft copper is passable at a cost
        for li, l in enumerate(L):
            g = soft.get(l)
            if g is not None and not g.is_empty:
                pen[li] = shapely.contains_xy(g.buffer(w / 2 + clr + grid * 0.75), X, Y)
    tol = grid * 0.75
    # the two items' own copper already clears foreign copper: let the search run along it
    for li, l in enumerate(L):
        for m in (src_map, dst_map):
            if l in m:
                free[li] |= shapely.contains_xy(m[l].buffer(tol), X, Y)

    def seeds(m):
        out = []
        for li, l in enumerate(L):
            if l in m:
                ii, jj = np.nonzero(shapely.contains_xy(m[l].buffer(tol), X, Y) & free[li])
                out += [(li, int(i), int(j)) for i, j in zip(ii, jj)]
        return out
    src, dst = seeds(src_map), set(seeds(dst_map))
    if os.environ.get("MAZE_DEBUG"):
        print("  maze: grid %dx%d, free %s, via-ok %d, src %d, dst %d" % (
            nx, ny, [int(f.sum()) for f in free], int(viaok.sum()), len(src), len(dst)))
    if not src or not dst:
        return None
    tx, ty = gb.centroid.x, gb.centroid.y
    h = lambda i, j: math.hypot(xs[i] - tx, ys[j] - ty)
    VIA_COST = 2.0
    dist, prev, pq = {}, {}, []
    for n in src:
        dist[n] = 0.0
        heapq.heappush(pq, (h(n[1], n[2]), 0.0, n))
    moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
    goal = None
    while pq:
        f, d, n = heapq.heappop(pq)
        if d > dist.get(n, 1e18):
            continue
        if n in dst:
            goal = n
            break
        li, i, j = n
        nbrs = []
        for di, dj, c in moves:
            a, b = i + di, j + dj
            if 0 <= a < nx and 0 <= b < ny and free[li][a, b]:
                if di and dj and not (free[li][a, j] and free[li][i, b]):
                    continue                             # no corner cutting
                nbrs.append(((li, a, b), c * grid + (soft_cost if pen[li][a, b] else 0.0)))
        if vias_ok and viaok[i, j]:
            for lj in range(len(L)):
                if lj != li and free[lj][i, j]:
                    nbrs.append(((lj, i, j), VIA_COST + (soft_cost * 6 if any(pen[k][i, j] for k in range(len(L))) else 0.0)))
        for m, c in nbrs:
            nd = d + c
            if nd < dist.get(m, 1e18):
                dist[m] = nd; prev[m] = n
                heapq.heappush(pq, (nd + h(m[1], m[2]), nd, m))
    if goal is None:
        if os.environ.get("MAZE_DEBUG"):
            print("  maze: no path, explored %d" % len(dist))
        return None
    path = [goal]
    while path[-1] in prev:
        path.append(prev[path[-1]])
    path.reverse()
    segs, vias = [], []
    run = [path[0]]
    for n in path[1:]:
        if n[0] != run[-1][0]:                           # layer change = via
            vias.append((xs[n[1]], ys[n[2]]))
            if len(run) > 1:
                segs.append((L[run[0][0]], run))
            run = [n]
        else:
            run.append(n)
    if len(run) > 1:
        segs.append((L[run[0][0]], run))
    out = []
    for lay, pts in segs:                                # merge collinear steps into segments
        pts = [(xs[i], ys[j]) for _, i, j in pts]
        keep = [pts[0]]
        for k in range(1, len(pts) - 1):
            ax, ay = pts[k][0] - keep[-1][0], pts[k][1] - keep[-1][1]
            bx, by = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
            if abs(ax * by - ay * bx) > 1e-9:
                keep.append(pts[k])
        keep.append(pts[-1])
        out += [(lay, p0, p1) for p0, p1 in zip(keep[:-1], keep[1:])]
    # tie the grid ends onto the items themselves
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    for node, m in ((path[0], src_map), (path[-1], dst_map)):
        pt = (xs[node[1]], ys[node[2]])
        geom = m[L[node[0]]]
        if not geom.contains(Point(pt)):
            q = nearest_points(geom, Point(pt))[0]
            out.append((L[node[0]], (float(q.x), float(q.y)), pt))
    return out, vias


def complete(board, protected=None):
    """Close connections the router left open: a straight or L-shaped track on whichever layer is
    clear, else a grid search (through vias), else a grid search that may cross other nets'
    tracks; those tracks are ripped up and their nets closed again on the next call (see
    complete_all). Uses KiCad's DRC to find open connections (GND is left to pours/stitching).
    Returns (closed, ripped)."""
    protected = set() if protected is None else protected
    ripped = 0
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import nearest_points
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    pairs = open_pairs(board)
    if not pairs:
        return 0, 0
    foreign_by_net = {}
    widths = net_widths(board)
    outline = Polygon([(mm(Pd(x, y).x), mm(Pd(x, y).y)) for x, y in outline_points()]).buffer(-0.4)

    def geom(x, y, kind, net):
        """Geometry and copper layer of a DRC item (None = through-hole, reachable on any layer)."""
        if kind == "Track":
            for t in board.GetTracks():
                if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net:
                    g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))])
                    if g.distance(Point(x, y)) < 0.01:
                        return g, t.GetLayer()
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == net and math.dist((mm(p.GetPosition().x), mm(p.GetPosition().y)), (x, y)) < 0.01:
                    return Point(x, y), (p.GetLayer() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD else None)
        return Point(x, y), None
    done = 0
    for a, b in pairs:
        net = a[3]
        if "Zone" in (a[2], b[2]) and net in PLANE_NETS:
            # a pad left off its power plane: give it a via onto the plane, right outside the pad
            it = b if a[2] == "Zone" else a
            pad = next((p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == net and
                        math.dist((mm(p.GetPosition().x), mm(p.GetPosition().y)), it[:2]) < 0.01), None)
            if pad is not None and it[2] != "Zone" and pad_via(board, pad, net, plane_region(board, net), lock=False):
                done += 1
                foreign_by_net.clear()
                continue
        if net not in foreign_by_net:
            # obstacles excluding this net's own copper
            fo, hard, soft_l = {}, {}, {}
            for t in board.GetTracks():
                if t.GetNetname() == net:
                    continue
                if t.GetClass() == "PCB_VIA":
                    g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
                    for l in SIG:
                        fo.setdefault(l, []).append(g)
                        hard.setdefault(l, []).append(g)
                else:
                    g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)),
                                    (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2)
                    fo.setdefault(t.GetLayer(), []).append(g)
                    if t.GetNetname() == "GND" or t.IsLocked() or t.m_Uuid.AsString() in protected:
                        hard.setdefault(t.GetLayer(), []).append(g)
                    else:
                        soft_l.setdefault(t.GetLayer(), []).append(g)
            for fp in board.GetFootprints():
                for p in fp.Pads():
                    if p.GetNetname() == net:
                        continue
                    bb = p.GetBoundingBox()
                    from shapely.geometry import box
                    g = box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
                    for l in SIG:
                        if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) or p.IsOnLayer(l):
                            fo.setdefault(l, []).append(g)
                            hard.setdefault(l, []).append(g)
            from shapely.ops import unary_union
            ko = keepouts(board)
            foreign_by_net[net] = ({l: unary_union(v + [ko]) for l, v in fo.items()},
                                   {l: unary_union(v + [ko]) for l, v in hard.items()},
                                   {l: unary_union(v) for l, v in soft_l.items()})
        fo, fo_hard, fo_soft = foreign_by_net[net]
        if a[2] == "Zone" or b[2] == "Zone":                 # skip the direct L-route, use the grid search
            (ga, la), (gb, lb) = (Point(-1e6, -1e6), None), (Point(1e6, 1e6), None)
        else:
            (ga, la), (gb, lb) = geom(*a), geom(*b)
        w, clr = widths.get(net, (0.2, 0.2))
        ends = lambda g: [(c[0], c[1]) for c in g.coords] if g.geom_type == "LineString" else [(g.x, g.y)]
        npa, npb = nearest_points(ga, gb)
        cand = [((npa.x, npa.y), (npb.x, npb.y))] + sorted(
            ((p, q) for p in ends(ga) for q in ends(gb)), key=lambda pq: math.dist(*pq))

        own_vias = [(mm(t.GetPosition().x), mm(t.GetPosition().y)) for t in board.GetTracks()
                    if t.GetClass() == "PCB_VIA" and t.GetNetname() == net]
        own_tht = [p.GetBoundingBox() for fp in board.GetFootprints() for p in fp.Pads()
                   if p.GetNetname() == net and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        has_via = lambda pt: any(math.dist(pt, v) < 0.01 for v in own_vias) or any(
            mm(bb.GetLeft()) <= pt[0] <= mm(bb.GetRight()) and mm(bb.GetTop()) <= pt[1] <= mm(bb.GetBottom())
            for bb in own_tht)              # already on a via or a through-hole pad: any layer is reachable

        def via_fits(pt):
            c = Point(pt).buffer(VIA_D / 2 + clr)
            return outline.contains(c) and not any(c.intersects(fo[l]) for l in fo)

        from shapely.prepared import prep
        pfo = {l: prep(g) for l, g in fo.items()}
        blocked = lambda geom, l: l in pfo and pfo[l].intersects(geom)

        def access(pt, lay_item):
            """Ways to reach an item end: (point, layer or None for any, via point or None, stub)."""
            if lay_item is None or has_via(pt):
                return [(pt, None, None, None)]
            out = [(pt, lay_item, None, None)]
            for r in (0.8, 1.2, 1.6, 2.0, 2.6):
                for k in range(16):
                    an = 2 * math.pi * k / 16
                    v = (pt[0] + r * math.cos(an), pt[1] + r * math.sin(an))
                    stub = LineString([pt, v])
                    if via_fits(v) and not blocked(stub.buffer(w / 2 + clr), lay_item):
                        out.append((v, None, v, (lay_item, pt, v)))
            return out

        best = None
        for pa0, pb0 in cand[:4]:
            for (pa, la2, va, sa) in access(pa0, la):
                for (pb, lb2, vb, sb) in access(pb0, lb):
                    if va and vb and math.dist(va, vb) < VIA_D + 2 * clr and math.dist(va, vb) > 1e-6:
                        continue
                    for lay in (pcbnew.B_Cu, pcbnew.F_Cu):
                        if (la2 is not None and la2 != lay) or (lb2 is not None and lb2 != lay):
                            continue
                        for path in ([pa, pb], [pa, (pb[0], pa[1]), pb], [pa, (pa[0], pb[1]), pb]):
                            g = LineString(path)
                            if not outline.contains(g) or blocked(g.buffer(w / 2 + clr), lay):
                                continue
                            nvia = (va is not None) + (vb is not None)
                            cost = g.length + nvia * 3.0
                            if best is None or cost < best[0]:
                                best = (cost, lay, path, [x for x in (sa, sb) if x], [x for x in (va, vb) if x])
                            break
            if best:
                break
        segs = None
        if best is not None:
            _, lay, path, stubs, vias = best
            segs = [(lay, s0, s1) for s0, s1 in zip(path[:-1], path[1:])] + [(l, p0, p1) for l, p0, p1 in stubs]
        else:                                            # no straight / L route: grid search
            cl = net_clusters(board, net)
            pick = lambda pt: next((c for c in cl if any(g.distance(Point(pt)) < 0.02 for g in c.values())), None)
            def near_pad(it):
                if it[2] != "Zone":
                    return it[:2]
                pads = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == net]
                p = min(pads, key=lambda p: math.dist((mm(p.GetPosition().x), mm(p.GetPosition().y)), it[:2]))
                return (mm(p.GetPosition().x), mm(p.GetPosition().y))
            ca, cb = pick(near_pad(a)), pick(near_pad(b))
            r = maze(board, net, ca, cb, fo, outline, w, clr) if ca and cb and ca is not cb else None
            if r is None and ca and cb and ca is not cb:
                r = maze(board, net, ca, cb, fo_hard, outline, w, clr, soft=fo_soft)
                if r:                                    # rip up the foreign tracks the route crosses
                    nseg = [(l, LineString([p0, p1]).buffer(w / 2 + clr)) for l, p0, p1 in r[0]]
                    nvia = [Point(v).buffer(VIA_D / 2 + clr) for v in r[1]]
                    dead = []
                    for t in board.GetTracks():
                        if t.GetClass() != "PCB_TRACK" or t.GetNetname() in (net, "GND") \
                                or t.IsLocked() or t.m_Uuid.AsString() in protected:
                            continue
                        tg = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)),
                                         (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2)
                        if any(l == t.GetLayer() and g.intersects(tg) for l, g in nseg) or \
                                (t.GetLayer() in SIG and any(v.intersects(tg) for v in nvia)):
                            dead.append(t)
                    print("  rip-up for %s: removing %d segment(s) of %s" % (
                        net, len(dead), sorted({t.GetNetname() for t in dead})))
                    for t in dead:
                        board.Remove(t)
                    ripped += len(dead)
            if r:
                segs, vias = r
        ok = segs is not None
        if ok:
            for l, s0, s1 in segs:
                if math.dist(s0, s1) < 1e-6:
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(VECTOR2I(FromMM(s0[0]), FromMM(s0[1]))); t.SetEnd(VECTOR2I(FromMM(s1[0]), FromMM(s1[1])))
                t.SetWidth(FromMM(w)); t.SetLayer(l); t.SetNet(board.FindNet(net))
                board.Add(t)
                protected.add(t.m_Uuid.AsString())
            for vx, vy in vias:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(VECTOR2I(FromMM(vx), FromMM(vy)))
                v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL)); v.SetNet(board.FindNet(net))
                board.Add(v)
        if ok:
            done += 1
            foreign_by_net.clear()
        else:
            print("  could not close %s: %s <-> %s" % (net, a[:3], b[:3]))
        if ripped:
            break                                        # ripped nets show up as new open pairs
    return done, ripped


def complete_all(board, rounds=4):
    """complete() until nothing is open or ripped; copper it adds is never ripped again."""
    protected, total = set(), 0
    for _ in range(rounds):
        done, ripped = complete(board, protected)
        total += done
        if not ripped:
            break
    return total


def remove_dangling(board):
    """Drop router leftovers that KiCad's DRC reports as dangling (one end connected to nothing).
    Removing such a segment can never break a connection."""
    mm = pcbnew.ToMM
    rep = os.path.join(WORK, "dangling.rpt")
    removed = 0
    for _ in range(4):
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())   # vias onto the planes are not dangling
        pcbnew.WriteDRCReport(board, rep, pcbnew.EDA_UNITS_MILLIMETRES, True)
        found = re.findall(r"\[track_dangling\].*?\n.*?\n\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): Track \[([^\]]+)\] on (\S+), length ([\d.]+) mm",
                           open(rep).read())
        dead = []
        for x, y, net, layer, length in found:
            if net == "GND":                             # fan-out stubs end on vias the plane fill connects
                continue
            for t in board.GetTracks():
                if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net and board.GetLayerName(t.GetLayer()) == layer \
                        and abs(mm(t.GetLength()) - float(length)) < 0.001 and t not in dead:
                    sx, sy, ex, ey = mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y)
                    if min(math.dist((sx, sy), (float(x), float(y))), math.dist((ex, ey), (float(x), float(y)))) < 0.01:
                        dead.append(t)
                        break
        # vias connected on one layer only are dead ends too
        for x, y, net in re.findall(r"\[via_dangling\].*?\n.*?\n\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): Via \[([^\]]+)\]",
                                    open(rep).read()):
            if net == "GND":
                continue
            for t in board.GetTracks():
                if t.GetClass() == "PCB_VIA" and t.GetNetname() == net and \
                        math.dist((mm(t.GetPosition().x), mm(t.GetPosition().y)), (float(x), float(y))) < 0.01:
                    dead.append(t)
                    break
        dead = [t for t in dead if not t.IsLocked()]
        if not dead:
            break
        for t in dead:
            board.Remove(t)
        removed += len(dead)
    return removed


def island_vias(board):
    """Give every filled GND pour island that has no via / THT pad of its own a via to the plane."""
    from shapely.geometry import Point, Polygon
    mm = pcbnew.ToMM
    foreign, pads, drills = _obstacles(board)
    anchors = [Point(mm(t.GetPosition().x), mm(t.GetPosition().y)) for t in board.GetTracks()
               if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"]
    anchors += [Point(mm(p.GetPosition().x), mm(p.GetPosition().y)) for fp in board.GetFootprints()
                for p in fp.Pads() if p.GetNetname() == "GND" and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    gnd = board.FindNet("GND")
    added = 0
    for z in list(board.Zones()):
        lay = z.GetLayer()
        if z.GetNetname() != "GND" or lay not in foreign:
            continue
        ps = z.GetFilledPolysList(lay)
        for i in range(ps.OutlineCount()):
            ring = lambda c: [(mm(c.CPoint(k).x), mm(c.CPoint(k).y)) for k in range(c.PointCount())]
            poly = Polygon(ring(ps.Outline(i)), [ring(ps.Hole(i, h)) for h in range(ps.HoleCount(i))])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if any(poly.contains(a) for a in anchors):
                continue
            core = poly.buffer(-(VIA_D / 2 + 0.05))
            if core.is_empty:
                continue
            x0, y0, x1, y1 = core.bounds
            found = None
            y = y0
            while y <= y1 and not found:
                x = x0
                while x <= x1:
                    c = Point(x, y)
                    if core.contains(c):
                        r = c.buffer(VIA_D / 2 + 0.2)
                        if not any(r.intersects(g) for g in foreign.values()) and not r.intersects(pads) \
                                and not c.buffer(VIA_DRILL / 2 + HOLE_GAP).intersects(drills):
                            found = (x, y); break
                    x += 0.25
                y += 0.25
            if found:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(VECTOR2I(FromMM(found[0]), FromMM(found[1])))
                v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL)); v.SetNet(gnd)
                board.Add(v); added += 1
                anchors.append(Point(*found)); drills = drills.union(Point(*found).buffer(VIA_DRILL / 2))
    return added


RING_W = 2.5      # chassis ring width (mm from the board edge, F/B only)


def chassis_ring_poly():
    from shapely.geometry import Polygon
    o = Polygon(outline_points())
    return o.difference(o.buffer(-RING_W, join_style=2))


def finish(board):
    """Chassis ring (F/B, jrbe), GND pours on F/B, fill, tie orphan pour islands to the plane,
    remove dead-end pour slivers (unintentional antennas), refill."""
    ring = chassis_ring_poly()
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        add_zone(board, layer, "CHASSIS", 9, "CHASSIS_RING", polys=[ring], clearance=0.4, min_width=0.5)
        add_zone(board, layer, "GND", 1, "GND_POUR", clearance=0.3, min_width=0.4)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    print("chassis ring F/B stitching vias: %d" % ring_vias(board))
    filler.Fill(board.Zones())
    n = island_vias(board)
    if n:
        filler.Fill(board.Zones())
    print("pour islands given a via: %d" % n)
    for k in range(3):
        v, ko = fix_slivers(board)
        print("slivers: %d stitched, %d removed (pass %d)" % (v, ko, k + 1))
        if not (v or ko):
            break
        filler.Fill(board.Zones())


def ring_vias(board, pitch=8.0):
    """Stitch the F and B chassis rings together every `pitch` mm along the ring centre line, where
    both layers are filled and nothing else is in the way. Ties every stretch of the top ring (it
    is cut where tracks cross near the edge) to the continuous bottom ring and the holes."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    fills = {}
    for z in board.Zones():
        if not z.GetIsRuleArea() and z.GetNetname() == "CHASSIS" and z.GetLayer() in SIG:
            ps = z.GetFilledPolysList(z.GetLayer())
            g = []
            for i in range(ps.OutlineCount()):
                c = ps.Outline(i)
                g.append(Polygon([(mm(c.CPoint(k).x), mm(c.CPoint(k).y)) for k in range(c.PointCount())]))
            fills[z.GetLayer()] = unary_union(g)
    if len(fills) < 2:
        return 0
    both = fills[pcbnew.F_Cu].intersection(fills[pcbnew.B_Cu]).buffer(-(VIA_D / 2 + 0.05))
    o = Polygon([(mm(Pd(x, y).x), mm(Pd(x, y).y)) for x, y in outline_points()])
    line = o.buffer(-RING_W / 2, join_style=2).exterior
    fo, drills = obstacles_for(board, "CHASSIS")
    n, d = 0, 0.0
    while d < line.length:
        c = line.interpolate(d)
        if both.contains(c) and not any(c.buffer(VIA_D / 2 + 0.25).intersects(g) for g in fo.values()) \
                and not c.buffer(VIA_DRILL / 2 + HOLE_GAP).intersects(drills):
            add_via(board, "CHASSIS", c.x, c.y, lock=False)
            drills = drills.union(c.buffer(VIA_DRILL / 2)); n += 1
            d += pitch
        else:
            d += 0.5
    return n


SLIVER_R = 0.9     # mm: pour parts narrower than 2 x this are slivers
SLIVER_LEN = 4.0   # mm: ... and a dead end at least this long needs a via or goes


def fix_slivers(board):
    """jrbe: avoid unintentional antennas. Narrow GND-pour fingers on F/B (narrower than
    2*SLIVER_R) whose far end has no via are either stitched with a via or cut away with a
    no-pour rule area."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    mm = pcbnew.ToMM
    foreign, pads, drills = _obstacles(board)
    anchors = [Point(mm(t.GetPosition().x), mm(t.GetPosition().y)) for t in board.GetTracks()
               if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"]
    anchors += [Point(mm(p.GetPosition().x), mm(p.GetPosition().y)) for fp in board.GetFootprints()
                for p in fp.Pads() if p.GetNetname() == "GND"]
    nv = nk = 0
    for z in list(board.Zones()):
        lay = z.GetLayer()
        if z.GetIsRuleArea() or z.GetNetname() != "GND" or lay not in SIG or z.GetZoneName() != "GND_POUR":
            continue
        ps = z.GetFilledPolysList(lay)
        for i in range(ps.OutlineCount()):
            ring = lambda c: [(mm(c.CPoint(k).x), mm(c.CPoint(k).y)) for k in range(c.PointCount())]
            poly = Polygon(ring(ps.Outline(i)), [ring(ps.Hole(i, h)) for h in range(ps.HoleCount(i))]).buffer(0)
            core = poly.buffer(-SLIVER_R).buffer(SLIVER_R)
            thin = poly.difference(core.buffer(0.05))
            for g in (thin.geoms if thin.geom_type == "MultiPolygon" else [thin] if not thin.is_empty else []):
                if g.area < 0.3:
                    continue
                d = g.minimum_rotated_rectangle
                xs = list(d.exterior.coords)
                length = max(math.dist(xs[0], xs[1]), math.dist(xs[1], xs[2]))
                if length < SLIVER_LEN:
                    continue
                # a finger is a dead end if it touches the core at one place only
                touch = g.buffer(0.1).intersection(core)
                parts = 0 if touch.is_empty else (len(touch.geoms) if hasattr(touch, "geoms") else 1)
                if parts >= 2 or any(g.buffer(0.2).contains(a) for a in anchors):
                    continue
                # stitch the far end if a via fits, else cut it off
                far = g.representative_point()
                done = False
                for c in [far] + [Point(x, y) for x, y in list(g.exterior.coords)[::3]]:
                    r = c.buffer(VIA_D / 2 + 0.2)
                    if g.buffer(0.15).contains(c) and not any(r.intersects(f) for f in foreign.values()) \
                            and not r.intersects(pads) and not c.buffer(VIA_DRILL / 2 + HOLE_GAP).intersects(drills):
                        add_via(board, "GND", c.x, c.y, lock=False); nv += 1
                        anchors.append(c); drills = drills.union(c.buffer(VIA_DRILL / 2)); done = True
                        break
                if not done:
                    dp = [board_to_design(x, y) for x, y in list(g.buffer(0.3, join_style=2).exterior.coords)[:-1]]
                    add_rule_area(board, (lay,), dp, tracks=False, vias=False, pour=True, name="SLIVER_CUT")
                    nk += 1
    return nv, nk


def board_to_design(x, y):
    from gen_mech import to_design
    return to_design(VECTOR2I(FromMM(x), FromMM(y)))


def block_copper(board):
    """Draw the hand-designed 5 V buck copper (tools/buck_block.py) relative to U1 and lock it,
    so FreeRouting and the clean-up passes treat it as fixed. v0.2a (forum review, jrbe): the wide
    power paths (VIN, GND, SW, +5V buses) are copper zones following the datasheet layout, not
    traces; only the narrow pin necks and the FB sense line stay tracks."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    u1 = board.FindFootprintByReference("U1")
    assert round(u1.GetOrientationDegrees()) % 360 == buck_block.U1_ROT, "U1 not at its block orientation"
    ux, uy = pcbnew.ToMM(u1.GetPosition().x), pcbnew.ToMM(u1.GetPosition().y)
    at = lambda q: VECTOR2I(FromMM(ux + q[0]), FromMM(uy + q[1]))
    layer = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    n, areas = 0, {}
    for net, lay, w, pts in buck_block.TRACKS:
        ni = board.FindNet(net); assert ni, net
        if w >= ZONE_MIN_W:
            g = LineString([(ux + a, uy + b) for a, b in pts]).buffer(w / 2, cap_style=3, join_style=2)
            areas.setdefault((net, lay), []).append(g)
            # the zone is the copper; the locked track under it keeps the router out of it
            # (FreeRouting treats copper zones as planes it may route across)
        for a, b in zip(pts[:-1], pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(at(a)); t.SetEnd(at(b)); t.SetWidth(FromMM(w)); t.SetLayer(layer[lay])
            t.SetNet(ni); t.SetLocked(True); board.Add(t); n += 1
    for (net, lay), gs in areas.items():
        u = unary_union(gs)
        polys = [u] if u.geom_type == "Polygon" else list(u.geoms)
        dpolys = [[board_to_design(x, y) for x, y in list(pg.exterior.coords)[:-1]] for pg in polys]
        add_zone(board, layer[lay], net, BLOCK_PRIO.get(net, 5), "BUCK_" + net, polys=dpolys, clearance=0.2,
                 min_width=0.2, connection=pcbnew.ZONE_CONNECTION_FULL, locked=True)
    for net, x, y in buck_block.VIAS:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(at((x, y))); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL)); v.SetNet(board.FindNet(net))
        v.SetLocked(True); board.Add(v)
    return n, len(areas), len(buck_block.VIAS)


ZONE_MIN_W = 1.0                     # block tracks at least this wide become zones
BLOCK_PRIO = {"SW_5V": 8, "VCC_12V": 7, "+5V": 7, "GND": 6}


# ------------------------------------------------------------------ helpers for pre-routing
def obstacles_for(board, net):
    """Foreign copper per signal layer for `net` (tracks, vias, pads, keep-outs) and all drills,
    board mm. Zones are not obstacles (they refill around everything)."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    mm = pcbnew.ToMM
    fo, drills = {l: [] for l in SIG}, []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            c = Point(mm(t.GetPosition().x), mm(t.GetPosition().y))
            drills.append(c.buffer(mm(t.GetDrill()) / 2))
            if t.GetNetname() != net:
                for l in SIG:
                    fo[l].append(c.buffer(mm(t.GetWidth()) / 2))
        elif t.GetNetname() != net and t.GetLayer() in fo:
            fo[t.GetLayer()].append(LineString([(mm(t.GetStart().x), mm(t.GetStart().y)),
                                                (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            th = p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            if th:
                drills.append(Point(mm(p.GetPosition().x), mm(p.GetPosition().y)).buffer(mm(p.GetDrillSize().x) / 2))
            if p.GetNetname() == net and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                continue
            bb = p.GetBoundingBox()
            g = box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
            for l in SIG:
                if th or p.IsOnLayer(l):
                    fo[l].append(g)
    ko = keepouts(board)
    return {l: unary_union(v + [ko]) for l, v in fo.items()}, unary_union(drills)


def body_union(board, skip=()):
    """Footprint bodies (pads + fab outline, board mm): vias stay outside them (jrbe: vias right
    outside the pads, never under an IC)."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    from gen_layout import dbox
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    out = []
    for fp in board.GetFootprints():
        if fp.GetReference() in skip:
            continue
        x0, y0, x1, y1 = dbox(fp)
        a, b = Pd(x0, y0), Pd(x1, y1)
        out.append(box(min(mm(a.x), mm(b.x)), min(mm(a.y), mm(b.y)), max(mm(a.x), mm(b.x)), max(mm(a.y), mm(b.y))))
    return unary_union(out)


def add_track(board, net, layer, a, b, w, lock=True):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(VECTOR2I(FromMM(a[0]), FromMM(a[1]))); t.SetEnd(VECTOR2I(FromMM(b[0]), FromMM(b[1])))
    t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(board.FindNet(net)); t.SetLocked(lock)
    board.Add(t)
    return t


def add_via(board, net, x, y, lock=True):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL)); v.SetNet(board.FindNet(net)); v.SetLocked(lock)
    board.Add(v)
    return v


def pad_geom(p):
    from shapely.geometry import box
    mm = pcbnew.ToMM
    bb = p.GetBoundingBox()
    return box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))


def pad_of(board, ref, num, net=None):
    fp = board.FindFootprintByReference(ref)
    ps = [p for p in fp.Pads() if p.GetNumber() == num and (net is None or p.GetNetname() == net)]
    return max(ps, key=lambda p: p.GetSize().x * p.GetSize().y)


def connect_pads(board, pa, pb, layers, w, clr=0.2, lock=True, vias_ok=False):
    """Straight / L track between two pads on one layer, else a grid search on `layers`."""
    from shapely.geometry import LineString, Polygon
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    net = pa.GetNetname()
    fo, _ = obstacles_for(board, net)
    ca = (mm(pa.GetPosition().x), mm(pa.GetPosition().y)); cb = (mm(pb.GetPosition().x), mm(pb.GetPosition().y))
    for lay in layers:
        for path in ([ca, cb], [ca, (cb[0], ca[1]), cb], [ca, (ca[0], cb[1]), cb]):
            if not LineString(path).buffer(w / 2 + clr).intersects(fo[lay]):
                for a, b in zip(path[:-1], path[1:]):
                    if math.dist(a, b) > 1e-6:
                        add_track(board, net, lay, a, b, w, lock)
                return True
    outline = Polygon([(mm(Pd(x, y).x), mm(Pd(x, y).y)) for x, y in outline_points()]).buffer(-0.4)
    src = {l: pad_geom(pa) for l in layers if pa.IsOnLayer(l)}
    dst = {l: pad_geom(pb) for l in layers if pb.IsOnLayer(l)}
    r = maze(board, net, src, dst, fo, outline, w, clr, layers=layers, vias_ok=vias_ok)
    if not r:
        return False
    segs, vias = r
    for l, a, b in segs:
        if math.dist(a, b) > 1e-6:
            add_track(board, net, l, a, b, w, lock)
    for x, y in vias:
        add_via(board, net, x, y, lock)
    return True


def connect_point(board, net, pt, pb, layers, w, clr, lock=True):
    """Grid search from a point (end of an escape stub) to pad pb on `layers`."""
    from shapely.geometry import Point, Polygon
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    fo, _ = obstacles_for(board, net)
    outline = Polygon([(mm(Pd(x, y).x), mm(Pd(x, y).y)) for x, y in outline_points()]).buffer(-0.4)
    src = {l: Point(pt).buffer(w / 2) for l in layers}
    dst = {l: pad_geom(pb) for l in layers if pb.IsOnLayer(l)}
    r = maze(board, net, src, dst, fo, outline, w, clr, layers=layers, vias_ok=False)
    if not r:
        return False
    for l, a, b in r[0]:
        if math.dist(a, b) > 1e-6:
            add_track(board, net, l, a, b, w, lock)
    return True


# ------------------------------------------------------------------ oscillators
# jrbe (showstopper): crystals first, short paths, load caps on the crystal's own layer with no
# vias in the oscillator nets, nothing routed underneath, ground below.
XTALS = {"Y1": [("U3", "5", "1", "C28"), ("U3", "6", "2", "C29")],
         "Y2": [("U3", "3", "1", "C30"), ("U3", "4", "2", "C31")]}


def crystal_copper(board):
    """Route MCU pin -> crystal pad -> load cap on F.Cu (locked), keep tracks and vias of other nets
    out from under the crystal (B.Cu: whole footprint, F.Cu: between its pads), and put a GND
    island on In2 under crystal + load caps, so it has ground on both inner layers."""
    from shapely.ops import unary_union
    from gen_layout import dbox
    nets = []
    for y, chains in XTALS.items():
        boxes = []
        for mref, mpin, ypin, cref in chains:
            pm, py = pad_of(board, mref, mpin), pad_of(board, y, ypin)
            net = py.GetNetname()
            pc = [p for p in board.FindFootprintByReference(cref).Pads() if p.GetNetname() == net][0]
            # straight escape out of the 0.5 mm pitch QFP pin first (exact geometry keeps 0.2 mm
            # to the neighbouring pins), then the shortest F.Cu path to the crystal
            mm = pcbnew.ToMM
            c = board.FindFootprintByReference(mref).GetPosition()
            pp = pm.GetPosition()
            dx, dy = mm(pp.x - c.x), mm(pp.y - c.y)
            ux, uy = (math.copysign(1, dx), 0.0) if abs(dx) > abs(dy) else (0.0, math.copysign(1, dy))
            half = mm(max(pm.GetSize().x, pm.GetSize().y)) / 2
            a0 = (mm(pp.x), mm(pp.y)); a1 = (a0[0] + ux * (half + 0.9), a0[1] + uy * (half + 0.9))
            add_track(board, net, pcbnew.F_Cu, a0, a1, 0.2)
            if not connect_point(board, net, a1, py, (pcbnew.F_Cu,), 0.2, 0.2) or \
                    not connect_pads(board, py, pc, (pcbnew.F_Cu,), 0.2, clr=0.2):
                raise SystemExit("could not route %s on F.Cu (%s)" % (net, y))
            nets.append(net)
            boxes.append(rect(*dbox(board.FindFootprintByReference(cref))))
        fp = board.FindFootprintByReference(y)
        x0, y0, x1, y1 = dbox(fp)
        body = rect(x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5)
        add_rule_area(board, (pcbnew.B_Cu,), body, name=y + "_KEEPOUT")
        # F.Cu: nothing of another net between the crystal's pads (its own traces enter from outside)
        from shapely.geometry import LineString
        mm = pcbnew.ToMM
        pg = [pad_geom(pp) for pp in fp.Pads()]
        own = [LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(0.45)
               for t in board.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() in
               {pp.GetNetname() for pp in fp.Pads()}]
        gap = unary_union(pg).convex_hull.difference(unary_union(pg + own).buffer(0.3))
        for g in (gap.geoms if gap.geom_type == "MultiPolygon" else [gap]):
            if g.area > 0.2:
                dp = [board_to_design(x, y) for x, y in list(g.exterior.coords)[:-1]]
                add_rule_area(board, (pcbnew.F_Cu,), dp, name=y + "_KEEPOUT_F")
        isl = unary_union([body] + boxes).envelope.buffer(0.8, join_style=2)
        add_zone(board, pcbnew.In2_Cu, "GND", 3, y + "_GND", polys=[isl], thermal=INNER_THERMAL)
    return nets


# ------------------------------------------------------------------ contactor drivers
CONTACTORS = ("U20", "U21", "U22")


def contactor_copper(board):
    """jrbe: contactor outputs are high-current paths. Each driver's tab (drain = output) gets copper
    on F and B extended toward CN1 with a row of vias (heat + current), and its source pin a GND
    copper area with vias straight into the In1 plane; the return current then stays in the strip
    between the drivers and CN1's ground pins, away from the logic."""
    from shapely.geometry import Point
    mm = pcbnew.ToMM
    nv = 0
    for ref in CONTACTORS:
        fp = board.FindFootprintByReference(ref)
        tab = max((p for p in fp.Pads() if p.GetNumber() == "2"), key=lambda p: p.GetSize().x * p.GetSize().y)
        src = pad_of(board, ref, "3")
        out = tab.GetNetname()
        bb = tab.GetBoundingBox()
        (xa, ya), (xb, yb) = board_to_design(mm(bb.GetLeft()), mm(bb.GetTop())), board_to_design(mm(bb.GetRight()), mm(bb.GetBottom()))
        tx0, tx1, ty0, ty1 = min(xa, xb), max(xa, xb), min(ya, yb), max(ya, yb)
        ext = rect(tx0 - 2.8, ty0 - 0.4, tx1, ty1 + 0.4)              # toward CN1 (-x)
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            add_zone(board, lay, out, 4, ref + "_TAB", polys=[ext], clearance=0.3,
                     connection=pcbnew.ZONE_CONNECTION_FULL, locked=True)
        bb = src.GetBoundingBox()
        (xa, ya), (xb, yb) = board_to_design(mm(bb.GetLeft()), mm(bb.GetTop())), board_to_design(mm(bb.GetRight()), mm(bb.GetBottom()))
        sx0, sx1, sy0, sy1 = min(xa, xb), max(xa, xb), min(ya, yb), max(ya, yb)
        cy = (sy0 + sy1) / 2
        p1y = board_to_design(mm(pad_of(board, ref, "1").GetPosition().x), mm(pad_of(board, ref, "1").GetPosition().y))[1]
        up = 1 if cy > p1y else -1                                     # away from pin 1
        sarea = rect(sx0 - 0.3, cy - up * 0.8, sx1 + 3.2, cy + up * 2.6)
        add_zone(board, pcbnew.F_Cu, "GND", 4, ref + "_SRC", polys=[sarea], clearance=0.3,
                 connection=pcbnew.ZONE_CONNECTION_FULL, locked=True)
        # locked tracks along the zones: FreeRouting treats zones as planes it may cross
        def dtrack(net, lay, a, b, w):
            pa, pb = P(*a), P(*b)
            add_track(board, net, lay, (mm(pa.x), mm(pa.y)), (mm(pb.x), mm(pb.y)), w)
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            dtrack(out, lay, (tx0 - 1.4, ty0 + 0.2), (tx0 - 1.4, ty1 - 0.2), 2.0)
        dtrack("GND", pcbnew.F_Cu, ((sx0 + sx1) / 2, cy), (sx1 + 2.0, cy + up * 1.8), 1.2)
        # vias: a column in the tab extension, a block in the source area
        cands = {out: [(tx0 - 1.4, y) for y in frange(ty0 + 0.8, ty1 - 0.6, 1.3)],
                 "GND": [(x, y) for x in frange(sx0 + 0.6, sx1 + 2.6, 1.3) for y in (cy + up * 1.3, cy + up * 2.1)]}
        for net, pts in cands.items():
            fo, drills = obstacles_for(board, net)
            for x, y in pts:
                b = P(x, y); bx, by = mm(b.x), mm(b.y)
                c = Point(bx, by)
                if any(c.buffer(VIA_D / 2 + 0.25).intersects(g) for g in fo.values()):
                    continue
                if c.buffer(VIA_DRILL / 2 + HOLE_GAP).intersects(drills):
                    continue
                add_via(board, net, bx, by); nv += 1
                drills = drills.union(c.buffer(VIA_DRILL / 2))
    return nv


def frange(a, b, step):
    out, v = [], a
    while v <= b + 1e-9:
        out.append(v); v += step
    return out


def is_block_copper(board, t):
    """True for a track/via that is part of the hand-designed buck block (possibly split at a
    junction by the router): same net, same layer, and lying on one of the block's paths."""
    from shapely.geometry import LineString, Point
    mm = pcbnew.ToMM
    u1 = board.FindFootprintByReference("U1")
    ux, uy = mm(u1.GetPosition().x), mm(u1.GetPosition().y)
    net = t.GetNetname()
    if t.GetClass() == "PCB_VIA":
        x, y = mm(t.GetPosition().x) - ux, mm(t.GetPosition().y) - uy
        return any(n == net and math.dist((x, y), (vx, vy)) < 0.01 for n, vx, vy in buck_block.VIAS)
    g = LineString([(mm(t.GetStart().x) - ux, mm(t.GetStart().y) - uy), (mm(t.GetEnd().x) - ux, mm(t.GetEnd().y) - uy)])
    lay = board.GetLayerName(t.GetLayer())
    return any(n == net and l == lay and abs(mm(t.GetWidth()) - w) < 1e-3 and g.within(LineString(pts).buffer(0.02))
               for n, l, w, pts in buck_block.TRACKS)


def prestub(board, skip=()):
    """Pre-route short same-net pad pairs (adjacent connector pins, decoupling caps, IC pin ties) as
    locked straight or L-shaped tracks. FreeRouting tends to box these pins in and give up on them."""
    from shapely.geometry import LineString, Point, box
    mm = pcbnew.ToMM
    widths = net_widths(board)
    block = set(buck_block.REFS)
    pads = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_PTH):
                bb = p.GetBoundingBox()
                pads.append((p, (mm(p.GetPosition().x), mm(p.GetPosition().y)),
                             box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))))
    stubs = {l: [] for l in (pcbnew.F_Cu, pcbnew.B_Cu)}          # layer -> [(net, geom)]
    for t in board.GetTracks():                                  # copper already drawn (buck block)
        g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2) \
            if t.GetClass() == "PCB_VIA" else \
            LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2)
        for l in stubs:
            if t.GetClass() == "PCB_VIA" or t.GetLayer() == l:
                stubs[l].append((t.GetNetname(), g))
    ko = keepouts(board)
    parent = {}

    def find(k):
        while parent.setdefault(k, k) != k:
            k = parent[k]
        return k
    cands = []
    for i, (pa, ca, _) in enumerate(pads):
        na = pa.GetNetname()
        if not na or na == "GND" or na in skip:
            continue
        for pb, cb, _ in pads[i + 1:]:
            if pb.GetParentAsString() in block and pa.GetParentAsString() in block:
                continue                                         # drawn by block_copper()
            if pb.GetNetname() == na and math.dist(ca, cb) <= 4.0:
                cands.append((math.dist(ca, cb), pa, ca, pb, cb))
    cands.sort(key=lambda c: c[0])
    n = 0
    for _, pa, ca, pb, cb in cands:
        net = pa.GetNetname()
        ka, kb = (id(pa), net), (id(pb), net)
        if find(ka) == find(kb):
            continue
        smd = [p for p in (pa, pb) if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
        if len({p.GetLayer() for p in smd}) > 1:
            continue
        layers = [smd[0].GetLayer()] if smd else [pcbnew.F_Cu, pcbnew.B_Cu]
        w, clr = widths.get(net, (0.2, 0.2))
        clr = max(clr, 0.2) + 0.01
        paths = [[ca, cb], [ca, (cb[0], ca[1]), cb], [ca, (ca[0], cb[1]), cb]]
        done = False
        for lay in layers:
            for path in paths:
                g = LineString(path).buffer(w / 2 + clr)
                if any(g.intersects(gp) for p, _, gp in pads
                       if p.GetNetname() != net and (p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or p.IsOnLayer(lay))):
                    continue
                if any(g.intersects(sg) for sn, sg in stubs[lay] if sn != net):
                    continue
                if g.intersects(ko):
                    continue
                for s0, s1 in zip(path[:-1], path[1:]):
                    if math.dist(s0, s1) < 1e-6:
                        continue
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(VECTOR2I(FromMM(s0[0]), FromMM(s0[1]))); t.SetEnd(VECTOR2I(FromMM(s1[0]), FromMM(s1[1])))
                    t.SetWidth(FromMM(w)); t.SetLayer(lay); t.SetNet(pa.GetNet()); t.SetLocked(True)
                    board.Add(t)
                stubs[lay].append((net, LineString(path).buffer(w / 2)))
                parent[find(ka)] = find(kb); n += 1; done = True
                break
            if done:
                break
    return n


def run_freerouting(board, dsn, ses, passes, timeout=None):
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise RuntimeError("DSN export failed")
    groups = patch_dsn(dsn, board)
    if os.path.exists(ses):
        os.remove(ses)
    cmd = ["xvfb-run", "-a", "java", "-jar", JAR, "-de", dsn, "-do", ses, "-mp", str(passes)]
    print(" ".join(cmd), flush=True)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=WORK, timeout=timeout)
        open(ses + ".log", "w").write(r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        subprocess.run(["pkill", "-f", "--", "-de " + dsn])
        print("FreeRouting timed out after %d s" % timeout)
        return None
    if not os.path.exists(ses):
        raise RuntimeError("FreeRouting produced no SES; see %s.log" % ses)
    return groups


BASE = os.path.join(WORK, "base.kicad_pcb")       # placement + In1 plane + locked pre-route stubs


STAGE1 = os.path.join(WORK, "stage1.kicad_pcb")  # BASE + stage-1 routing, all locked


def stage2(d1, s1, d2, s2):
    """Re-run FreeRouting on the stage-1 result so it only routes what stage 1 left open.
    FreeRouting leaves fixed wires out of its SES (and KiCad's DSN export merges chained
    segments, so a fixed stub can swallow a routed segment). Locking everything from stage 1
    makes the stage-2 SES contain exactly the new wires, which are then added to STAGE1."""
    b1 = pcbnew.LoadBoard(BASE)
    import_ses(b1, s1, d1)
    left = len(open_pairs(b1))
    print("stage 1 left %d signal connections open" % left)
    if left <= int(os.environ.get("STAGE2_MIN_OPEN", "4")):
        return False                                 # complete() closes a handful directly
    for t in b1.GetTracks():
        t.SetLocked(True)
    pcbnew.SaveBoard(STAGE1, b1)
    return run_freerouting(pcbnew.LoadBoard(STAGE1), d2, s2, os.environ.get("FR_PASSES2", "15"), timeout=900) is not None


def main():
    os.makedirs(WORK, exist_ok=True)
    d1, s1 = os.path.join(WORK, "stage1.dsn"), os.path.join(WORK, "stage1.ses")
    d2, s2 = os.path.join(WORK, "stage2.dsn"), os.path.join(WORK, "stage2.ses")
    if "--import-only" in sys.argv:                  # reuse the last routing run
        if os.path.exists(s2) and os.path.getmtime(s2) > os.path.getmtime(s1):
            import_and_finish(d2, s2, STAGE1)
        else:
            import_and_finish(d1, s1, BASE)
        return
    if "--stage2-only" in sys.argv:                  # reuse stage 1, redo stage 2
        if stage2(d1, s1, d2, s2):
            import_and_finish(d2, s2, STAGE1)
        return
    if not os.path.exists(JAR):
        raise SystemExit("FreeRouting jar not found at %s (set FREEROUTING_JAR)" % JAR)
    board = pcbnew.LoadBoard(PCB)
    setup(board)
    print("5 V buck block: %d locked track segments, %d zones, %d vias" % block_copper(board))
    xn = crystal_copper(board)
    print("oscillators routed on F.Cu with keep-outs: %s" % " ".join(xn))
    print("contactor drivers: %d vias on tabs / sources" % contactor_copper(board))
    print("pre-routed %d short pad-to-pad connections" % prestub(board, skip=set(xn)))
    print("plane fan-out vias: %s" % plane_fanout(board))
    print("GND fan-out: %d pad vias" % stitch(board, grid=None, lock=True)[0])
    print("GND pads tied to a nearby via: %d" % gnd_orphans(board))
    pcbnew.SaveBoard(BASE, board)
    board = pcbnew.LoadBoard(BASE)
    if "--export-only" in sys.argv:
        pcbnew.ExportSpecctraDSN(board, d1); patch_dsn(d1, board)
        return
    for (w, clr), nets in sorted(run_freerouting(board, d1, s1, os.environ.get("FR_PASSES", "40")).items()):
        print("  class %.2f/%.2f mm: %s" % (w, clr, " ".join(nets)))
    if stage2(d1, s1, d2, s2):
        import_and_finish(d2, s2, STAGE1)
    else:                          # stage 2 skipped, or FreeRouting 1.9 hung on it (it can)
        print("finishing from stage 1")
        import_and_finish(d1, s1, BASE)


def drc(board, path):
    """Run KiCad DRC; return {violation type: count} parsed from the text report."""
    pcbnew.WriteDRCReport(board, path, pcbnew.EDA_UNITS_MILLIMETRES, True)
    counts, section = {}, None
    for line in open(path):
        m = re.match(r"\*\* Found (\d+) (.*) \*\*", line)
        if m:
            section = m.group(2)
            counts[section] = {"total": int(m.group(1))}
            continue
        m = re.match(r"\[(\w+)\]:", line)
        if m and section:
            counts[section][m.group(1)] = counts[section].get(m.group(1), 0) + 1
    return counts


def render_routed(board, path, title):
    from PIL import Image, ImageDraw, ImageFont
    from gen_mech import to_design
    S, M = 6.0, 30
    W, H = int((273 + 16) * S + 2 * M), int(112 * S + 2 * M + 40)
    img = Image.new("RGB", (W, H), (16, 18, 22)); d = ImageDraw.Draw(img)
    F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    FB = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    tx = lambda p: (M + (p[0] + 16) * S, M + 40 + (107 - p[1]) * S)
    pts = [tx(p) for p in outline_points()]
    d.polygon(pts, fill=(28, 40, 32), outline=(230, 230, 230))
    col = {pcbnew.B_Cu: (60, 110, 230), pcbnew.In2_Cu: (200, 160, 40), pcbnew.F_Cu: (220, 60, 50)}
    zc = {"+3V3": (200, 160, 40), "+5V": (240, 120, 40), "VCC_12V": (240, 70, 160), "ESP_3V3": (120, 220, 255), "GND": (120, 200, 120)}
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetLayer() != pcbnew.In2_Cu:
            continue
        ps = z.Outline()                     # the plane outline (the fill's fracture lines would read as traces)
        for i in range(ps.OutlineCount()):
            c = ps.Outline(i)
            pts = [tx(to_design(c.CPoint(k))) for k in range(c.PointCount())]
            if len(pts) > 2:
                d.line(pts + [pts[0]], fill=zc.get(z.GetNetname(), (200, 200, 200)), width=3)
    for lyr in (pcbnew.B_Cu, pcbnew.F_Cu):
        for t in board.GetTracks():
            if t.GetClass() == "PCB_TRACK" and t.GetLayer() == lyr:
                w = max(1, int(pcbnew.ToMM(t.GetWidth()) * S))
                d.line([tx(to_design(t.GetStart())), tx(to_design(t.GetEnd()))], fill=col[lyr], width=w)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            x, y = tx(to_design(p.GetPosition()))
            sx, sy = pcbnew.ToMM(p.GetBoundingBox().GetWidth()) * S / 2, pcbnew.ToMM(p.GetBoundingBox().GetHeight()) * S / 2
            d.rectangle([x - sx, y - sy, x + sx, y + sy], fill=(200, 200, 200) if fp.GetLayer() == pcbnew.F_Cu else (130, 130, 160))
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            x, y = tx(to_design(t.GetPosition())); r = pcbnew.ToMM(t.GetWidth()) * S / 2
            d.ellipse([x - r, y - r, x + r, y + r], fill=(240, 240, 240))
    for fp in board.GetFootprints():
        if fp.GetPadCount() >= 6 or fp.GetReference().startswith(("Q", "J", "CN", "Y")):
            x, y = tx(to_design(fp.GetPosition()))
            d.text((x - 3 * len(fp.GetReference()), y - 6), fp.GetReference(), fill=(255, 255, 120), font=F)
    d.text((M, 8), title, fill=(255, 255, 255), font=FB)
    keys = [("F.Cu", col[pcbnew.F_Cu]), ("B.Cu", col[pcbnew.B_Cu])] + [("In2 " + n, c) for n, c in zc.items()]
    for i, (n, c) in enumerate(keys):
        d.rectangle([W - 700 + i * 100, 12, W - 688 + i * 100, 24], fill=c)
        d.text((W - 684 + i * 100, 11), n, fill=(220, 220, 220), font=F)
    img.save(path)


def refs_off_copper(board):
    """Forum review (Jack Bauer): silkscreen must not sit on vias. Every reference that touches a
    via, a pad, another part or another reference moves to the nearest free spot around its own
    part, staying horizontal (gen_layout.py set them all to one orientation)."""
    from shapely.geometry import Point, box
    from shapely.ops import unary_union
    from gen_layout import dbox, TEXT_AREA
    from gen_mech import P as Pd, to_design
    mm = pcbnew.ToMM
    def bbox_design(bb):
        (xa, ya), (xb, yb) = to_design(VECTOR2I(bb.GetLeft(), bb.GetTop())), to_design(VECTOR2I(bb.GetRight(), bb.GetBottom()))
        return box(min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))
    copper = [Point(to_design(t.GetPosition())).buffer(mm(t.GetWidth()) / 2 + 0.15) for t in board.GetTracks()
              if t.GetClass() == "PCB_VIA"]
    copper += [bbox_design(p.GetBoundingBox()).buffer(0.15) for fp in board.GetFootprints() for p in fp.Pads()]
    copper = unary_union(copper)
    bodies = {fp.GetReference(): box(*dbox(fp)) for fp in board.GetFootprints()}
    from shapely.geometry import Polygon
    inside = Polygon(outline_points()).buffer(-RING_W - 0.3)
    text_area = box(*TEXT_AREA)
    texts = {fp.GetReference(): bbox_design(fp.Reference().GetBoundingBox()) for fp in board.GetFootprints()
             if fp.Reference().IsVisible() and fp.Reference().GetLayer() == pcbnew.F_SilkS}
    moved, stuck = 0, []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in texts or ref.startswith("H") or ref in buck_block.REFS:
            continue
        t = fp.Reference()
        def bad(g):
            return (g.intersects(copper) or not inside.contains(g) or g.intersects(text_area) or
                    any(g.intersects(b) for r, b in bodies.items() if r != ref) or
                    any(g.intersects(b) for r, b in texts.items() if r != ref))
        g = texts[ref]
        if not bad(g):
            continue
        x0, y0, x1, y1 = bodies[ref].bounds
        w, h = g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        best = None
        for k in range(1, 16):
            d = 0.25 * k
            for px, py in ((cx, y1 + d + h / 2), (cx, y0 - d - h / 2), (x1 + d + w / 2, cy), (x0 - d - w / 2, cy),
                           (x1 + d + w / 2, y1 + d + h / 2), (x0 - d - w / 2, y1 + d + h / 2),
                           (x1 + d + w / 2, y0 - d - h / 2), (x0 - d - w / 2, y0 - d - h / 2)):
                cand = box(px - w / 2, py - h / 2, px + w / 2, py + h / 2)
                if not bad(cand):
                    best = (px, py, cand)
                    break
            if best:
                break
        if best is None:
            stuck.append(ref)
            continue
        t.SetPosition(Pd(best[0], best[1]))
        texts[ref] = best[2]
        moved += 1
    return moved, stuck


def import_and_finish(dsn, ses, base):
    pre = {t.m_Uuid.AsString() for t in pcbnew.LoadBoard(BASE).GetTracks()}
    board = pcbnew.LoadBoard(base)
    nt, nv = import_ses(board, ses, dsn)
    for t in board.GetTracks():                    # router copper unlocked; the pre-route stays locked
        t.SetLocked(t.m_Uuid.AsString() in pre)
    print("imported %d track segments, %d vias; removed %d dangling stubs" % (nt, nv, remove_dangling(board)))
    print("closed %d open connections directly" % complete_all(board))
    print("removed %d dangling stubs after completion" % remove_dangling(board))
    repair_clearance(board)
    pv, gv = stitch(board)
    print("GND vias: %d beside SMD pads, %d stitching" % (pv, gv))
    print("GND pads tied to a nearby via: %d" % gnd_orphans(board, lock=False))
    finish(board)
    mv, stuck = refs_off_copper(board)
    print("references moved off vias / pads / other parts: %d%s" % (mv, (" (no free spot: %s)" % " ".join(stuck)) if stuck else ""))
    pcbnew.SaveBoard(PCB, board)
    board = pcbnew.LoadBoard(PCB)
    rep = os.path.join(WORK, "drc.rpt")
    for sect, c in drc(board, rep).items():
        print("DRC %s: %s" % (sect, c))
    render_routed(board, os.path.join(PROJ, "..", "..", "docs", "layout_routed.png"),
                  "Bolt logic board - routed v0.2a (component side view; F red, B blue, In2 power planes outlined)")


if __name__ == "__main__":
    main()
