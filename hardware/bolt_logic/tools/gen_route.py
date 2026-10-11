#!/usr/bin/env python3
"""Stage 2 of layout: stackup + planes, autoroute with FreeRouting, pour, DRC.

    python3 tools/gen_mech.py && python3 tools/gen_layout.py && python3 tools/gen_route.py

Stackup (4 layers, 2.0 mm):  F.Cu signals | In1.Cu solid GND plane | In2.Cu signals + GND pour | B.Cu signals + GND pour
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

PCB = os.path.join(PROJ, "bolt_logic.kicad_pcb")
WORK = os.path.join(PROJ, "route_work")
JAR = os.environ.get("FREEROUTING_JAR", os.path.expanduser("~/tools/freerouting.jar"))

# Net classes (width, clearance in mm). Everything else: KiCad default 0.2 / 0.2.
NETCLASSES = {
    "POWER": (0.8, 0.3, ["VBAT", "VBAT_SW", "VCC_12V", "+12V_GATE", "MAIN_CONT_OUT", "PRECHG_OUT_SW",
                         "PUMP_OUT_SW", "SW_5V", "AUX_12V", "EXC_OA", "EXC_OB", "EXC_OA_C", "EXC_P", "EXC_N"]),
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


def add_zone(board, layer, net, priority=0, name=""):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(board.FindNet(net))
    z.SetAssignedPriority(priority)
    z.SetMinThickness(FromMM(0.25))
    z.SetLocalClearance(FromMM(0.3))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)   # solid to SMD pads, reliefs on THT
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetThermalReliefGap(FromMM(0.3))
    z.SetThermalReliefSpokeWidth(FromMM(0.4))
    if name:
        z.SetZoneName(name)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in outline_points():
        ol.Append(P(x, y))
    board.Add(z)
    return z


def setup(board):
    board.SetCopperLayerCount(4)
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)       # solid GND plane, not routed
    if len(board.Zones()) or len(board.GetTracks()):
        # removing items through the SWIG API corrupts later ZONE wrappers in KiCad 7; start clean
        raise SystemExit("board already has zones/tracks: re-run gen_mech.py and gen_layout.py first")
    add_zone(board, pcbnew.In1_Cu, "GND", 0, "GND_PLANE")


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


VIA_D, VIA_DRILL = 0.6, 0.3
CLR = 0.25           # mm, stitching via / stub clearance to foreign copper
HOLE_GAP = 0.5       # mm, drill edge to drill edge


def _obstacles(board):
    """Shapely geometry (board mm coords) of non-GND copper per layer, all pads, and drills."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    mm = pcbnew.ToMM
    layers = (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)
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
    return ({l: unary_union(v) for l, v in foreign.items()}, unary_union(pads_f), unary_union(drills))


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
            inward = []
            # inward, toward the footprint centre (QFP/SOIC ground pins: via under the body)
            cx, cy = mm(fp.GetPosition().x), mm(fp.GetPosition().y)
            dc = math.dist((px, py), (cx, cy))
            if dc > 1.5:
                ux, uy = (cx - px) / dc, (cy - py) / dc
                d = max(hw, hh) + 0.6
                while d <= dc:
                    inward.append((px + ux * d, py + uy * d)); d += 0.3
            cands = inward + ring if fp.GetPadCount() >= 6 else ring + inward
            lay = p.GetLayer() if p.GetLayer() in foreign else pcbnew.F_Cu
            for x, y in cands:
                if not via_ok(x, y, keep=0.2):
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


def open_pairs(board):
    """Unconnected item pairs (non-GND) from KiCad's DRC: [(x, y, kind, net), (x, y, kind, net)]."""
    rep = os.path.join(WORK, "open.rpt")
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


def complete(board):
    """Close connections the router left open with a straight or L-shaped track, on whichever
    layer is clear. Uses KiCad's DRC to find them (GND is left to the pours and stitching)."""
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import nearest_points
    from gen_mech import P as Pd
    mm = pcbnew.ToMM
    pairs = open_pairs(board)
    if not pairs:
        return 0
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
        if net not in foreign_by_net:
            # obstacles excluding this net's own copper
            fo = {}
            for t in board.GetTracks():
                if t.GetNetname() == net:
                    continue
                if t.GetClass() == "PCB_VIA":
                    g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
                    for l in (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
                        fo.setdefault(l, []).append(g)
                else:
                    fo.setdefault(t.GetLayer(), []).append(LineString(
                        [(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2))
            for fp in board.GetFootprints():
                for p in fp.Pads():
                    if p.GetNetname() == net:
                        continue
                    bb = p.GetBoundingBox()
                    from shapely.geometry import box
                    g = box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
                    for l in (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
                        if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) or p.IsOnLayer(l):
                            fo.setdefault(l, []).append(g)
            from shapely.ops import unary_union
            foreign_by_net[net] = {l: unary_union(v) for l, v in fo.items()}
        fo = foreign_by_net[net]
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

        ok = False
        for lay in (pcbnew.In2_Cu, pcbnew.B_Cu, pcbnew.F_Cu):
            for pa, pb in cand:
                vias = [pt for pt, l in ((pa, la), (pb, lb)) if l is not None and l != lay and not has_via(pt)]
                if not all(via_fits(v) for v in vias):
                    continue
                for path in ([pa, pb], [pa, (pb[0], pa[1]), pb], [pa, (pa[0], pb[1]), pb]):
                    g = LineString(path)
                    if not outline.contains(g) or g.buffer(w / 2 + clr).intersects(fo.get(lay, Point(-1e6, -1e6))):
                        continue
                    for s0, s1 in zip(path[:-1], path[1:]):
                        if math.dist(s0, s1) < 1e-6:
                            continue
                        t = pcbnew.PCB_TRACK(board)
                        t.SetStart(VECTOR2I(FromMM(s0[0]), FromMM(s0[1]))); t.SetEnd(VECTOR2I(FromMM(s1[0]), FromMM(s1[1])))
                        t.SetWidth(FromMM(w)); t.SetLayer(lay); t.SetNet(board.FindNet(net))
                        board.Add(t)
                    for vx, vy in vias:
                        v = pcbnew.PCB_VIA(board)
                        v.SetPosition(VECTOR2I(FromMM(vx), FromMM(vy)))
                        v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                        v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL)); v.SetNet(board.FindNet(net))
                        board.Add(v)
                    ok = True
                    break
                if ok:
                    break
            if ok:
                break
        if ok:
            done += 1
            foreign_by_net.clear()
        else:
            print("  could not close %s: %s <-> %s" % (net, a[:3], b[:3]))
    return done


def remove_dangling(board):
    """Drop router leftovers that KiCad's DRC reports as dangling (one end connected to nothing).
    Removing such a segment can never break a connection."""
    mm = pcbnew.ToMM
    rep = os.path.join(WORK, "dangling.rpt")
    removed = 0
    for _ in range(4):
        pcbnew.WriteDRCReport(board, rep, pcbnew.EDA_UNITS_MILLIMETRES, True)
        found = re.findall(r"\[track_dangling\].*?\n.*?\n\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): Track \[([^\]]+)\] on (\S+), length ([\d.]+) mm",
                           open(rep).read())
        dead = []
        for x, y, net, layer, length in found:
            for t in board.GetTracks():
                if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net and board.GetLayerName(t.GetLayer()) == layer \
                        and abs(mm(t.GetLength()) - float(length)) < 0.001 and t not in dead:
                    sx, sy, ex, ey = mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y)
                    if min(math.dist((sx, sy), (float(x), float(y))), math.dist((ex, ey), (float(x), float(y)))) < 0.01:
                        dead.append(t)
                        break
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


def tidy_silk(board):
    """Small passives carry their reference on the fab layer (assembly drawing) instead of silk:
    on this density the silk references would sit on pads and on each other."""
    n = 0
    for fp in board.GetFootprints():
        if fp.GetPadCount() <= 3 and fp.GetAttributes() & pcbnew.FP_SMD:
            fp.Reference().SetLayer(pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab)
            n += 1
    return n


def finish(board):
    """GND pours on the signal layers, fill, tie orphan pour islands to the plane, refill."""
    for layer, prio in ((pcbnew.F_Cu, 1), (pcbnew.In2_Cu, 1), (pcbnew.B_Cu, 1)):
        add_zone(board, layer, "GND", prio, "GND_POUR")
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    n = island_vias(board)
    if n:
        filler.Fill(board.Zones())
    print("pour islands given a via: %d" % n)


def prestub(board):
    """Pre-route short same-net pad pairs (adjacent connector pins, decoupling caps, IC pin ties) as
    locked straight or L-shaped tracks. FreeRouting tends to box these pins in and give up on them."""
    from shapely.geometry import LineString, box
    mm = pcbnew.ToMM
    widths = net_widths(board)
    pads = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_PTH):
                bb = p.GetBoundingBox()
                pads.append((p, (mm(p.GetPosition().x), mm(p.GetPosition().y)),
                             box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))))
    stubs = {l: [] for l in (pcbnew.F_Cu, pcbnew.B_Cu)}          # layer -> [(net, geom)]
    parent = {}

    def find(k):
        while parent.setdefault(k, k) != k:
            k = parent[k]
        return k
    cands = []
    for i, (pa, ca, _) in enumerate(pads):
        na = pa.GetNetname()
        if not na or na == "GND":
            continue
        for pb, cb, _ in pads[i + 1:]:
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
    print("pre-routed %d short pad-to-pad connections" % prestub(board))
    print("GND fan-out: %d pad vias" % stitch(board, grid=None, lock=True)[0])
    pcbnew.SaveBoard(BASE, board)
    board = pcbnew.LoadBoard(BASE)
    if "--export-only" in sys.argv:
        pcbnew.ExportSpecctraDSN(board, d1); patch_dsn(d1, board)
        return
    for (w, clr), nets in sorted(run_freerouting(board, d1, s1, os.environ.get("FR_PASSES", "100")).items()):
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
    for lyr in (pcbnew.B_Cu, pcbnew.In2_Cu, pcbnew.F_Cu):
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
    for i, (n, c) in enumerate((("F.Cu", col[pcbnew.F_Cu]), ("In2.Cu", col[pcbnew.In2_Cu]), ("B.Cu", col[pcbnew.B_Cu]))):
        d.rectangle([W - 330 + i * 100, 12, W - 318 + i * 100, 24], fill=c)
        d.text((W - 314 + i * 100, 11), n, fill=(220, 220, 220), font=F)
    img.save(path)


def import_and_finish(dsn, ses, base):
    board = pcbnew.LoadBoard(base)
    nt, nv = import_ses(board, ses, dsn)
    print("imported %d track segments, %d vias; removed %d dangling stubs" % (nt, nv, remove_dangling(board)))
    for t in board.GetTracks():
        t.SetLocked(False)                         # locks were only for the router
    print("closed %d open connections directly" % complete(board))
    print("passive references moved to fab layer: %d" % tidy_silk(board))
    pv, gv = stitch(board)
    print("GND vias: %d beside SMD pads, %d stitching" % (pv, gv))
    finish(board)
    pcbnew.SaveBoard(PCB, board)
    board = pcbnew.LoadBoard(PCB)
    rep = os.path.join(WORK, "drc.rpt")
    for sect, c in drc(board, rep).items():
        print("DRC %s: %s" % (sect, c))
    render_routed(board, os.path.join(PROJ, "..", "..", "docs", "layout_routed.png"),
                  "Bolt logic board - autorouted v0.1 (component side view; F red, In2 amber, B blue; GND planes not drawn)")


if __name__ == "__main__":
    main()
