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
import buck_block  # noqa: E402

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


def net_clusters(board, net):
    """Own-net copper grouped into electrically connected clusters: [{layer: geometry}]."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    mm = pcbnew.ToMM
    L = (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)
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
         soft=None, soft_cost=0.5):
    """Grid A* over F.Cu / In2.Cu / B.Cu (8-way moves, through vias) between two items of one net.
    ga/gb: shapely geometries of the items, la/lb their copper layer (None = any layer).
    fo: {layer: foreign copper}. Returns (segments [(layer, p0, p1)], vias [pt]) or None."""
    import heapq
    import numpy as np
    import shapely
    L = (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)
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
        if viaok[i, j]:
            for lj in range(3):
                if lj != li and free[lj][i, j]:
                    nbrs.append(((lj, i, j), VIA_COST + (soft_cost * 6 if any(pen[k][i, j] for k in range(3)) else 0.0)))
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
        if net not in foreign_by_net:
            # obstacles excluding this net's own copper
            fo, hard, soft_l = {}, {}, {}
            for t in board.GetTracks():
                if t.GetNetname() == net:
                    continue
                if t.GetClass() == "PCB_VIA":
                    g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
                    for l in (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
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
                    for l in (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
                        if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) or p.IsOnLayer(l):
                            fo.setdefault(l, []).append(g)
                            hard.setdefault(l, []).append(g)
            from shapely.ops import unary_union
            ko = keepouts(board)
            foreign_by_net[net] = ({l: unary_union(v + [ko]) for l, v in fo.items()},
                                   {l: unary_union(v + [ko]) for l, v in hard.items()},
                                   {l: unary_union(v) for l, v in soft_l.items()})
        fo, fo_hard, fo_soft = foreign_by_net[net]
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
                    for lay in (pcbnew.In2_Cu, pcbnew.B_Cu, pcbnew.F_Cu):
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
            ca, cb = pick(a[:2]), pick(b[:2])
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
                                (t.GetLayer() in (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu) and any(v.intersects(tg) for v in nvia)):
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


def block_copper(board):
    """Draw the hand-designed 5 V buck copper (tools/buck_block.py) relative to U1 and lock it,
    so FreeRouting and the clean-up passes treat it as fixed."""
    u1 = board.FindFootprintByReference("U1")
    assert round(u1.GetOrientationDegrees()) % 360 == buck_block.U1_ROT, "U1 not at its block orientation"
    ux, uy = pcbnew.ToMM(u1.GetPosition().x), pcbnew.ToMM(u1.GetPosition().y)
    at = lambda q: VECTOR2I(FromMM(ux + q[0]), FromMM(uy + q[1]))
    layer = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    n = 0
    for net, lay, w, pts in buck_block.TRACKS:
        ni = board.FindNet(net); assert ni, net
        for a, b in zip(pts[:-1], pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(at(a)); t.SetEnd(at(b)); t.SetWidth(FromMM(w)); t.SetLayer(layer[lay])
            t.SetNet(ni); t.SetLocked(True); board.Add(t); n += 1
    for net, x, y in buck_block.VIAS:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(at((x, y))); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL)); v.SetNet(board.FindNet(net))
        v.SetLocked(True); board.Add(v)
    return n, len(buck_block.VIAS)


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


def prestub(board):
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
        if not na or na == "GND":
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
    print("5 V buck block: %d locked track segments, %d vias" % block_copper(board))
    print("pre-routed %d short pad-to-pad connections" % prestub(board))
    print("GND fan-out: %d pad vias" % stitch(board, grid=None, lock=True)[0])
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
    for t in board.GetTracks():                    # router locks off; the buck block stays locked
        t.SetLocked(is_block_copper(board, t))
    print("closed %d open connections directly" % complete_all(board))
    print("removed %d dangling stubs after completion" % remove_dangling(board))
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
