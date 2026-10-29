#!/usr/bin/env python3
"""Populate the mechanical board with the schematic's footprints and nets, place them,
and set up stackup / rules.  Stage 1 of layout (routing is done separately).

    python3 tools/gen_mech.py && python3 tools/gen_layout.py

Placement is table-driven: anchors for ICs/connectors below, plus a greedy
connectivity-driven placer for the passives inside each functional region.
Coordinates use the design frame of gen_mech.py (component side, origin = H1,
+X right, +Y up, mm).
"""
import math
import os
import subprocess
import sys
import tempfile

import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kisym  # noqa: E402
from gen_mech import P, to_design, SHEET_ORIGIN  # noqa: E402
import buck_block  # noqa: E402

PCB = os.path.join(PROJ, "bolt_logic.kicad_pcb")
SCH = os.path.join(PROJ, "bolt_logic.kicad_sch")
SYS_FP = "/usr/share/kicad/footprints"
FIXED = {"CN1", "CN2"} | {"H%d" % i for i in range(1, 15)}   # placed by gen_mech.py
# package pins that are NC on the silicon and have no symbol pin (74HC21: 3, 11; 74HCT30: 9, 10, 13)
PACKAGE_NC = {("U5", "3"), ("U5", "11"), ("U6", "9"), ("U6", "10"), ("U6", "13")}


# ------------------------------------------------------------------ netlist
def read_netlist():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "n.net")
        subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, SCH],
                       check=True, capture_output=True)
        t = kisym.parse(open(out).read())
    comps = {}
    for c in kisym.find(kisym.first(t, "components"), "comp"):
        ref = kisym.first(c, "ref")[1]
        fp = kisym.first(c, "footprint")
        comps[ref] = dict(value=kisym.first(c, "value")[1], footprint=fp[1] if fp else "",
                          dnp=any(p[1] == "dnp" for p in kisym.find(c, "property")))
    nets = {}
    for n in kisym.find(kisym.first(t, "nets"), "net"):
        name = kisym.first(n, "name")[1]
        for node in kisym.find(n, "node"):
            nets[(kisym.first(node, "ref")[1], kisym.first(node, "pin")[1])] = name
    return comps, nets


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    path = os.path.join(PROJ, lib + ".pretty") if lib == "Bolt" else os.path.join(SYS_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise FileNotFoundError("footprint %s not found" % fpid)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def populate(board, comps, nets):
    netinfo = {}
    for name in sorted(set(nets.values())):
        if name.startswith("unconnected-"):
            continue
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    existing = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for ref, c in sorted(comps.items()):
        fp = existing.get(ref)
        if fp is None:
            fp = load_fp(c["footprint"])
            fp.SetReference(ref)
            fp.SetValue(c["value"])
            fp.SetPosition(P(-60, 120))           # parking spot off-board until placed
            board.Add(fp)
        if c["dnp"]:
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
            fp.SetValue(c["value"])
    # assign nets & cross-check pads <-> netlist
    errors, seen = [], set()
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for (ref, pin), name in nets.items():
        fp = fps.get(ref)
        if fp is None:
            errors.append("%s missing on board" % ref); continue
        pads = [p for p in fp.Pads() if p.GetNumber() == pin]
        if not pads:
            errors.append("%s pad %s missing in footprint %s" % (ref, pin, fp.GetFPID().GetLibItemName()))
            continue
        for p in pads:
            if not name.startswith("unconnected-"):
                p.SetNet(netinfo[name])
        seen.add((ref, pin))
    # library rule areas (ESP32 antenna keep-out) list F/In1/B only: extend them to every copper layer
    for fp in board.GetFootprints():
        for z in fp.Zones():
            if z.GetIsRuleArea():
                z.SetLayerSet(pcbnew.LSET.AllCuMask())
    # stock ESP32-WROOM footprint has 0.2 mm thermal-via drills; open them to the 0.3 mm board minimum
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and p.GetDrillSize().x < FromMM(0.3):
                p.SetDrillSize(VECTOR2I(FromMM(0.3), FromMM(0.3)))
                if p.GetSize().x < FromMM(0.5):
                    p.SetSize(VECTOR2I(FromMM(0.5), FromMM(0.5)))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            key = (fp.GetReference(), p.GetNumber())
            if p.GetNumber() and key not in seen and key not in PACKAGE_NC \
                    and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                errors.append("%s pad %s not in netlist" % key)
    return errors



# ------------------------------------------------------------------ placement data
# Regions are lists of rectangles (x0, y0, x1, y1) in the design frame.
GROUPS = [
    # name, refs, regions (x0, y0, x1, y1) in the design frame (origin H1, +y up).
    # Kept clear: 10 mm around CN1 (left tab, y ~38-79) and CN2 (bottom left, x ~-1-48, y ~13-16).
    ("power", ["TVS1", "Q1", "R1", "R2", "R3", "D1", "C1", "C2", "C3", "C4", "C5", "U1", "C6", "L1", "C7", "C8",
               "C9", "U2", "C10", "C11", "C12", "FB1", "C13", "C14", "Q2", "R4", "R5", "R6", "C15", "C16", "R7"],
     [(12, 80, 105, 106)]),
    ("mcu", ["U3", "C20", "C21", "C22", "C23", "C24", "L2", "C25", "C26", "C27", "R10", "R11", "Y1", "C28", "C29",
             "Y2", "C30", "C31", "LED1", "R12", "LED2", "R13", "J1", "R14"],
     [(113, 0, 175, 55)]),
    ("gate", ["U4", "C40", "RN1", "RN2", "R20", "R21", "R22", "R23", "R24", "R25", "R26", "R27", "R28", "R29", "R30",
              "C41", "C42", "C43", "C44", "C45", "U5", "C46", "R31", "R32", "U6", "C47", "R33", "R34", "R35", "D2",
              "R36", "C48", "R37", "TP1", "TP2"],
     [(59, -3, 113, 27), (44, -4, 59, 1)]),
    ("analog", ["U7", "U8", "U9", "U10", "U11", "R40", "R41", "R42", "R43", "R44", "R45", "R46", "R47", "R48", "C50",
                "C51", "C52", "C53", "C54", "C55", "C56", "C57", "R49", "C58", "R50", "C59", "C60", "C61", "R51",
                "C62", "R52", "R53", "R54", "R55", "R56", "C63", "C64", "C65", "C66", "C67"],
     [(12, 27, 112, 48), (-4, -4, 44, 1)]),
    ("can", ["U23", "C109", "R123", "R124"], [(12, 48, 45, 78)]),
    ("resolver", ["U12", "U13", "U14"] + ["R%d" % i for i in range(60, 94) if i != 66] +
     ["C%d" % i for i in range(70, 90) if i != 74],
     [(12, 48, 105, 80)]),
    ("vin", ["R%d" % i for i in range(100, 118)] + ["C%d" % i for i in range(100, 109)] + ["F1", "F2", "F3"],
     [(105, 55, 200, 80)]),
    ("out", ["U20", "U21", "U22", "R120", "R121", "R122"], [(105, 80, 200, 106)]),
    ("wifi", ["U30", "L30", "C120", "C121", "R130", "C122", "J4"], [(175, 2, 262, 55)]),
]
# ESP32-WROOM-32E (PCB antenna, as V6): antenna end of the module (local y = -15.75) flush with
# the bottom board edge (y = -5), per Espressif's placement guidance. The footprint's 48 mm wide
# antenna keep-out then covers the last ~6 mm of board under the antenna. The bottom edge between
# H5 (x 141) and H11 (x 268) is the only edge stretch long enough with no mounting hole in it.
ANCHORS = {"U3": (140.0, 28.0, 0), "U30": (220.0, -5.0 + 15.75, 180)}
# decoupling / bulk caps: place next to a specific pad
NEAR = {"C40": ("U4", "20"), "C46": ("U5", "14"), "C47": ("U6", "14"), "C54": ("U7", "8"), "C57": ("U8", "8"),
        "C60": ("U9", "3"), "C61": ("U10", "3"), "C62": ("U11", "16"), "C75": ("U12", "8"), "C79": ("U13", "4"),
        "C80": ("U13", "4"), "C84": ("U14", "8"), "C109": ("U23", "3"), "C20": ("U3", "19"), "C21": ("U3", "32"),
        "C22": ("U3", "48"), "C23": ("U3", "64"), "C24": ("U3", "1"), "C25": ("U3", "13"), "C26": ("U3", "13"),
        "C27": ("U3", "7"), "L30": ("U30", "2"), "C120": ("U30", "2"), "C121": ("L30", "1"), "C10": ("U2", "3"),
        "C11": ("U2", "2"), "C12": ("U2", "2"), "C13": ("FB1", "2"), "C14": ("FB1", "2"), "C15": ("Q2", "1"),
        "C16": ("Q2", "1"), "C3": ("D1", "1"), "C4": ("D1", "1"), "C28": ("Y1", "1"), "C29": ("Y1", "2"),
        "C30": ("Y2", "1"), "C31": ("Y2", "2")}
STEP = 0.75
GAP = 1.5                           # between placement boxes (which include the silk reference)
CONNECTOR_CLEARANCE = 10.0          # owner: no components within 10 mm of CN1 / CN2 (hand soldering)
GROUP_GAP = {}                      # per-group spacing override (mm), e.g. {"resolver": 1.0}


def pbox(fp):
    """Placement extent: dbox plus the silkscreen reference text, so references stay legible
    (never on top of a neighbour)."""
    x0, y0, x1, y1 = dbox(fp)
    ref = fp.Reference()
    if ref.IsVisible() and ref.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
        bb = ref.GetBoundingBox()
        xa, ya = to_design(VECTOR2I(bb.GetLeft(), bb.GetTop()))
        xb, yb = to_design(VECTOR2I(bb.GetRight(), bb.GetBottom()))
        x0, y0, x1, y1 = min(x0, xa, xb), min(y0, ya, yb), max(x1, xa, xb), max(y1, ya, yb)
    return x0, y0, x1, y1


def dbox(fp):
    """Footprint extent (pads + graphics, no text) in the design frame: x0, y0, x1, y1."""
    bb = fp.GetBoundingBox(False, False)
    xa, ya = to_design(VECTOR2I(bb.GetLeft(), bb.GetTop()))
    xb, yb = to_design(VECTOR2I(bb.GetRight(), bb.GetBottom()))
    return min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)


def body_box(fp):
    """Pads + fab outline only (the courtyard of a module with an antenna keep-out spans the
    whole keep-out, which would block parts that belong right next to the module)."""
    pts = []
    for p in fp.Pads():
        b = p.GetBoundingBox()
        pts += [to_design(VECTOR2I(b.GetLeft(), b.GetTop())), to_design(VECTOR2I(b.GetRight(), b.GetBottom()))]
    for g in fp.GraphicalItems():
        if g.GetLayer() in (pcbnew.F_Fab, pcbnew.B_Fab) and g.GetClass() != "PCB_TEXT" and "TEXT" not in g.GetClass():
            b = g.GetBoundingBox()
            pts += [to_design(VECTOR2I(b.GetLeft(), b.GetTop())), to_design(VECTOR2I(b.GetRight(), b.GetBottom()))]
    xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
    return min(xs), min(ys), max(xs), max(ys)


def keepouts(board):
    ko = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref.startswith("H"):
            x, y = to_design(fp.GetPosition())
            r = 4.0 if ref not in ("H13", "H14") else 3.0
            ko.append((x - r, y - r, x + r, y + r))
        elif ref in ("CN1", "CN2"):
            x0, y0, x1, y1 = dbox(fp)                    # pads, locating holes and body outline
            m = CONNECTOR_CLEARANCE
            ko.append((x0 - m, y0 - m, x1 + m, y1 + m))
    ko.append((113.5, -6, 130, 3.5))                     # notch
    return ko


def inside_board(b):
    x0, y0, x1, y1 = b
    if x0 < -4 or x1 > 272 or y0 < -4 or y1 > 106:
        return False
    # chamfer: line (253.4,107)-(273,67.7); stay below it with 1 mm margin
    for (x, y) in ((x1, y1), (x0, y1), (x1, y0)):
        if x > 250 and y > 107 - (x - 253.4) * (39.3 / 19.6) - 1.5:
            return False
    return True


def overlap(a, b, gap=None):
    gap = GAP if gap is None else gap
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def place_block(fps):
    """Fixed 5 V buck block (tools/buck_block.py): U1 at its anchor, every other part at its
    offset, rotated so pad 1 faces the requested side. Returns the block's placement box."""
    u1 = fps["U1"]
    u1.SetOrientationDegrees(buck_block.U1_ROT); u1.SetPosition(P(*buck_block.U1_AT))
    ux, uy = pcbnew.ToMM(u1.GetPosition().x), pcbnew.ToMM(u1.GetPosition().y)
    want = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
    for ref, (dx, dy, side) in buck_block.PARTS.items():
        fp = fps[ref]
        pos = VECTOR2I(FromMM(ux + dx), FromMM(uy + dy))
        for rot in (0, 90, 180, 270):
            fp.SetOrientationDegrees(rot); fp.SetPosition(pos)
            p1 = [p for p in fp.Pads() if p.GetNumber() == "1"][0].GetPosition()
            vx, vy = pcbnew.ToMM(p1.x - pos.x), pcbnew.ToMM(p1.y - pos.y)
            wx, wy = want[side]
            if vx * wx + vy * wy > 0.5 * math.hypot(vx, vy):
                break
        else:
            raise SystemExit("buck block: no rotation puts %s pad 1 %s" % (ref, side))
    for ref, (lx, ly) in buck_block.LABELS.items():
        t = fps[ref].Reference()
        t.SetPosition(VECTOR2I(FromMM(ux + lx), FromMM(uy + ly))); t.SetTextAngleDegrees(0)
    boxes = [pbox(fps[r]) for r in buck_block.REFS]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def place_all(board):
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    placed_boxes = keepouts(board)
    placed_pads = {}                                    # net -> list of (x, y)

    def record(fp):
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n != "GND":
                placed_pads.setdefault(n, []).append(to_design(p.GetPosition()))

    for r in FIXED:
        if r in fps:
            record(fps[r])

    def shape_at(fp, rot):
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(P(0, 0))
        x0, y0, x1, y1 = pbox(fp)
        pads = [(to_design(p.GetPosition()), p.GetNetname(), p.GetNumber()) for p in fp.Pads()]
        return (x0, y0, x1, y1), pads

    failures = []
    placed_boxes.append(place_block(fps))
    for r in buck_block.REFS:
        record(fps[r])
    for ref, (x, y, rot) in ANCHORS.items():
        fp = fps[ref]; fp.SetOrientationDegrees(rot); fp.SetPosition(P(x, y))
        placed_boxes.append(body_box(fp) if len(fp.Zones()) else pbox(fp)); record(fp)
        for z in fp.Zones():                            # footprint rule areas (antenna keep-out)
            bb = z.GetBoundingBox()
            xa, ya = to_design(VECTOR2I(bb.GetLeft(), bb.GetTop()))
            xb, yb = to_design(VECTOR2I(bb.GetRight(), bb.GetBottom()))
            placed_boxes.append((min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)))

    for gname, refs, regions in GROUPS:
        todo = [r for r in refs if r in fps and r not in ANCHORS and r not in buck_block.REFS]
        todo.sort(key=lambda r: (-(fps[r].GetPadCount()), r in NEAR))
        for ref in todo:
            fp = fps[ref]
            best = None
            for rot in ((0, 90, 180, 270) if fp.GetPadCount() <= 3 else (0, 90)):
                (bx0, by0, bx1, by1), pads = shape_at(fp, rot)
                for (rx0, ry0, rx1, ry1) in regions:
                    x = rx0 - bx0
                    while x + bx1 <= rx1:
                        y = ry0 - by0
                        while y + by1 <= ry1:
                            box = (x + bx0, y + by0, x + bx1, y + by1)
                            if inside_board(box) and not any(overlap(box, o, GROUP_GAP.get(gname)) for o in placed_boxes):
                                cost = 0.0
                                if ref in NEAR:
                                    tr, tp = NEAR[ref]
                                    tpad = [p for p in fps[tr].Pads() if p.GetNumber() == tp][0]
                                    tx, ty = to_design(tpad.GetPosition())
                                    own = [(px, py) for (px, py), n, _ in pads if n == tpad.GetNetname()] or \
                                          [(px, py) for (px, py), n, _ in pads if n != "GND"] or [(0, 0)]
                                    cost = min(math.hypot(px + x - tx, py + y - ty) for px, py in own)
                                    # orient the other pad(s) toward their own nets too (e.g. a bootstrap cap)
                                    for (px, py), n, _ in pads:
                                        if n and n not in ("GND", tpad.GetNetname()) and n in placed_pads:
                                            cost += 0.3 * min(math.hypot(px + x - qx, py + y - qy)
                                                              for qx, qy in placed_pads[n])
                                else:
                                    for (px, py), n, _ in pads:
                                        if n and n != "GND" and n in placed_pads:
                                            cost += min(math.hypot(px + x - qx, py + y - qy)
                                                        for qx, qy in placed_pads[n])
                                    rcx = sum((a + c) / 2 for a, _, c, _ in regions) / len(regions)
                                    rcy = sum((b + d) / 2 for _, b, _, d in regions) / len(regions)
                                    cost += 0.05 * math.hypot(x - rcx, y - rcy)
                                if best is None or cost < best[0]:
                                    best = (cost, rot, x, y, box)
                            y += STEP
                        x += STEP
            if best is None:
                failures.append((gname, ref)); continue
            _, rot, x, y, box = best
            fp.SetOrientationDegrees(rot); fp.SetPosition(P(x, y))
            placed_boxes.append(box); record(fp)
    return failures


# ------------------------------------------------------------------ height check
# Owner: ~7/8" (22.2 mm) maximum height measured from the BOTTOM of the board, i.e. about
# 20.2 mm above the component side with the 2.0 mm board. Values are datasheet / package
# maximum body heights above the board surface (mm).
HEIGHT_LIMIT = 22.2 - 2.0
HEIGHTS = {
    "R_0805_2012Metric": 0.6, "R_1206_3216Metric": 0.7, "R_Array_Convex_4x0603": 0.6,
    "C_0805_2012Metric": 1.45, "C_1206_3216Metric": 1.8, "L_0805_2012Metric": 1.3,
    "LED_0805_2012Metric": 1.1, "Fuse_1206_3216Metric": 1.3, "Fuse_1812_4532Metric": 3.0,
    "Crystal_SMD_3215-2Pin_3.2x1.5mm": 0.9, "Crystal_SMD_5032-2Pin_5.0x3.2mm": 1.3,
    "D_SMA": 2.44, "D_SMB": 2.62, "SOT-23": 1.2, "TSOT-23-6": 1.1, "SOT-223-3_TabPin2": 1.8,
    "SOIC-8_3.9x4.9mm_P1.27mm": 1.75, "SOIC-14_3.9x8.7mm_P1.27mm": 1.75,
    "SOIC-16_3.9x9.9mm_P1.27mm": 1.75, "SOIC-20W_7.5x12.8mm_P1.27mm": 2.65,
    "LQFP-64_10x10mm_P0.5mm": 1.6, "TO-252-4": 2.4, "TO-263-2": 4.83,
    "L_Bourns_SRN6045TA": 4.5, "ESP32-WROOM-32": 3.35,           # V6 BOM gives 3.35 mm for the -32E
    "PinHeader_1x05_P2.54mm_Vertical": 8.5, "PinHeader_1x06_P2.54mm_Vertical": 8.5,
    "PinHeader_2x06_P2.54mm_Vertical": 8.5,                      # unmated; see docs/04-layout.md
    "TestPoint_Pad_D1.5mm": 0.0, "MountingHole_4.0mm_Pad6.5": 0.0, "NPTH_4.5mm": 0.0,
}
HEIGHT_EXEMPT = {"CN1": "vehicle connector: height set by the housing opening (part not yet chosen)",
                 "CN2": "bottom side, mates with the gate board"}


def check_connector_clearance(board):
    """Every component (pads + body, not mounting holes) must stay CONNECTOR_CLEARANCE from CN1/CN2."""
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    bad = []
    for cn in ("CN1", "CN2"):
        a = dbox(fps[cn])
        for ref, fp in fps.items():
            if ref in ("CN1", "CN2") or ref.startswith("H"):
                continue
            b = dbox(fp)
            dx = max(a[0] - b[2], b[0] - a[2], 0.0); dy = max(a[1] - b[3], b[1] - a[3], 0.0)
            d = math.hypot(dx, dy)
            if d < CONNECTOR_CLEARANCE - 1e-6:
                bad.append("%s is %.1f mm from %s" % (ref, d, cn))
    return bad


def check_heights(board):
    rows, problems = [], []
    for fp in board.GetFootprints():
        ref, name = fp.GetReference(), str(fp.GetFPID().GetUniStringLibItemName())
        if ref in HEIGHT_EXEMPT:
            continue
        h = HEIGHTS.get(name)
        if h is None:
            problems.append("%s (%s): no height on file" % (ref, name))
        elif h > HEIGHT_LIMIT:
            problems.append("%s (%s): %.1f mm > %.1f mm limit" % (ref, name, h, HEIGHT_LIMIT))
        else:
            rows.append((h, ref, name))
    rows.sort(reverse=True)
    return rows, problems


# ------------------------------------------------------------------ board setup
def setup_board(board):
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(FromMM(2.0))
    ds.m_MinClearance = FromMM(0.15)
    ds.m_TrackMinWidth = FromMM(0.15)
    ds.m_ViasMinSize = FromMM(0.5)
    ds.m_MinThroughDrill = FromMM(0.3)
    ds.m_CopperEdgeClearance = FromMM(0.4)


# ------------------------------------------------------------------ review render
def render(board, path, title):
    from PIL import Image, ImageDraw, ImageFont
    S, M = 6.0, 30
    W, H = int((273 + 16) * S + 2 * M), int(112 * S + 2 * M + 40)
    img = Image.new("RGB", (W, H), (20, 24, 28)); d = ImageDraw.Draw(img)
    F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    FB = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    tx = lambda x, y: (M + (x + 16) * S, M + 40 + (107 - y) * S)
    for dr in board.GetDrawings():
        if dr.GetLayer() == pcbnew.Edge_Cuts:
            if dr.GetShape() == pcbnew.SHAPE_T_SEGMENT:
                d.line([tx(*to_design(dr.GetStart())), tx(*to_design(dr.GetEnd()))], fill=(230, 230, 230), width=2)
            else:
                c = to_design(dr.GetCenter()); r = ToMM(dr.GetRadius())
                d.arc([tx(c[0] - r, c[1] + r), tx(c[0] + r, c[1] - r)], 180, 360, fill=(230, 230, 230), width=2)
    colors = {"power": (230, 90, 70), "mcu": (90, 160, 250), "gate": (250, 200, 60), "analog": (120, 220, 120),
              "resolver": (200, 120, 240), "can": (60, 210, 210), "vin": (240, 150, 200), "out": (250, 130, 40),
              "wifi": (120, 200, 255), "fixed": (200, 200, 200)}
    gof = {r: g for g, refs, _ in GROUPS for r in refs}
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    # ratsnest (nearest-neighbour chain per net, GND omitted)
    nets = {}
    for fp in fps.values():
        for p in fp.Pads():
            if p.GetNetname() and p.GetNetname() != "GND":
                nets.setdefault(p.GetNetname(), []).append(to_design(p.GetPosition()))
    for n, pts in nets.items():
        rest = pts[1:]; cur = [pts[0]]
        while rest:
            a, b = min(((a, b) for a in cur for b in rest), key=lambda ab: math.dist(*ab))
            d.line([tx(*a), tx(*b)], fill=(70, 80, 95), width=1); cur.append(b); rest.remove(b)
    for ref, fp in fps.items():
        g = gof.get(ref, "fixed"); col = colors[g]
        x0, y0, x1, y1 = dbox(fp)
        d.rectangle([tx(x0, y1), tx(x1, y0)], outline=col, width=1)
        for p in fp.Pads():
            x, y = to_design(p.GetPosition())
            r = max(1.5, ToMM(p.GetSize().x) * S / 2)
            d.ellipse([tx(x, y)[0] - r * 0.6, tx(x, y)[1] - r * 0.6, tx(x, y)[0] + r * 0.6, tx(x, y)[1] + r * 0.6],
                      fill=col)
        if fp.GetPadCount() >= 6 or ref.startswith(("Q", "J", "CN", "Y")):
            cx, cy = tx((x0 + x1) / 2, (y0 + y1) / 2)
            d.text((cx - 3 * len(ref), cy - 6), ref, fill=(255, 255, 255), font=F)
    d.text((M, 8), title, fill=(255, 255, 255), font=FB)
    lx = M + 520
    for i, (g, c) in enumerate(colors.items()):
        d.rectangle([lx + i * 92, 12, lx + i * 92 + 12, 24], fill=c); d.text((lx + i * 92 + 16, 11), g, fill=(220, 220, 220), font=F)
    img.save(path)


if __name__ == "__main__":
    board = pcbnew.LoadBoard(PCB)
    comps, nets = read_netlist()
    errs = populate(board, comps, nets)
    print("components %d, pin-nodes %d, errors %d" % (len(comps), len(nets), len(errs)))
    for e in errs[:30]:
        print("  " + e)
    if errs:
        sys.exit(1)
    setup_board(board)
    fails = place_all(board)
    print("placement failures: %s" % (fails or "none"))
    if fails:
        sys.exit(1)
    rows, problems = check_heights(board)
    problems += ["CLEARANCE: " + b for b in check_connector_clearance(board)]
    print("tallest parts (limit %.1f mm above the top surface): %s" % (
        HEIGHT_LIMIT, ", ".join("%s %.1f" % (r, h) for h, r, _ in rows[:6])))
    for pr in problems:
        print("  HEIGHT: " + pr)
    if problems:
        sys.exit(1)
    pcbnew.SaveBoard(PCB, board)
    render(board, os.path.join(PROJ, "..", "..", "docs", "layout_placement.png"),
           "Bolt logic board - placement v0.1 (component side, ratsnest grey, GND omitted)")
