#!/usr/bin/env python3
"""Generate the mechanical skeleton of the Bolt logic board (KiCad 7+).

Single source of truth for the board outline, mounting/locating holes, and the
CN1 (external 48-way) and CN2 (internal 2x20 board-to-board) footprints.
See docs/02-mechanical.md for where every number came from.

DESIGN FRAME (all values below): viewed from the COMPONENT side, external
connector tab on the left, origin = centre of the bottom-left 4 mm mounting
hole, +X right, +Y UP, millimetres.  KiCad's +Y is down; P() converts.

Usage (needs KiCad's python, e.g. `python3` with pcbnew importable):
    python3 tools/gen_mech.py            # writes ../bolt_logic.kicad_pcb + Bolt.pretty
"""
import math
import os
import sys

import pcbnew
from pcbnew import FromMM, VECTOR2I

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
LIB_NAME = "Bolt"
LIB_DIR = os.path.join(PROJ, LIB_NAME + ".pretty")
PCB_FILE = os.path.join(PROJ, "bolt_logic.kicad_pcb")

# Where the design-frame origin sits on the KiCad sheet (A3 page).
SHEET_ORIGIN = (60.0, 200.0)

# --------------------------------------------------------------------------
# MECHANICAL DATA  (design frame, mm)
# --------------------------------------------------------------------------
BOARD_THICKNESS = 2.0

BODY = dict(x0=-5.0, y0=-5.0, x1=273.0, y1=107.0)          # 278 x 112
TAB = dict(x_outer=-16.0, y_lo=33.0, y_hi=85.0)             # 11 deep x 52 wide
NOTCH = dict(cx=121.6, cy=-5.0, r=7.0)                       # bottom edge, semicircle
CHAMFER = dict(top=(253.4, 107.0), right=(273.0, 67.7))      # top-right corner cut

PLATED_HOLE = dict(drill=4.0, pad=6.5)
MOUNT_HOLES = [  # ref, x, y
    ("H1", 0.0, 0.0), ("H2", 0.0, 102.0), ("H3", 61.0, 71.7), ("H4", 134.0, 102.0),
    ("H5", 141.0, 0.0), ("H6", 188.0, 14.0), ("H7", 188.0, 67.0), ("H8", 241.0, 14.0),
    ("H9", 241.0, 67.0), ("H10", 248.0, 102.0), ("H11", 268.0, 0.0), ("H12", 268.0, 50.0),
]
NPTH_HOLES = [  # ref, x, y, drill
    ("H13", 39.0, 0.0, 4.5),     # beside CN2 - likely board-to-board alignment
    ("H14", 231.0, 101.0, 4.5),
]

# CN2: internal 2x20 receptacle, 2.54 mm, body on the BACK side.
CN2 = dict(pin1=(47.73, 15.82), pitch=2.54, row=2.54, n_per_row=20,
           drill=1.02, pad=1.7)             # Samtec SSW-120-01-T-D-LL (0.64 mm sq. tails)
# odd pins on the upper row (pin1 y), even pins one row below; numbers grow toward -X

# CN1: external GM 48-way (rows A..M without I, columns 1..4). M1 = top right.
CN1 = dict(
    cols_x={1: 0.3, 2: -3.7, 3: -7.7, 4: -11.7},               # 4.0 mm pitch
    rows_y={"M": 73.25, "L": 69.55, "K": 66.10,
            **{r: 63.55 - 2.5 * i for i, r in enumerate("JHGFEDCBA")}},
    drill=1.0, pad=1.7,                                          # VERIFY hole size
    locate=[(-8.5, 39.5), (-8.5, 77.5)], locate_drill=3.0,
)

# --------------------------------------------------------------------------
def P(x, y):
    return VECTOR2I(FromMM(SHEET_ORIGIN[0] + x), FromMM(SHEET_ORIGIN[1] - y))


def to_design(v):
    return (pcbnew.ToMM(v.x) - SHEET_ORIGIN[0], SHEET_ORIGIN[1] - pcbnew.ToMM(v.y))


def shape(parent, layer, kind, width=0.1):
    s = pcbnew.PCB_SHAPE(parent)
    s.SetShape(kind)
    s.SetLayer(layer)
    s.SetWidth(FromMM(width))
    return s


def edge_outline(board):
    b, t, n, c = BODY, TAB, NOTCH, CHAMFER
    pts = [
        (b["x0"], b["y1"]), c["top"], c["right"], (b["x1"], b["y0"]),
        (n["cx"] + n["r"], b["y0"]),
    ]
    segs = list(zip(pts[:-1], pts[1:]))
    arc = ((n["cx"] + n["r"], n["cy"]), (n["cx"], n["cy"] + n["r"]), (n["cx"] - n["r"], n["cy"]))
    pts2 = [(n["cx"] - n["r"], b["y0"]), (b["x0"], b["y0"]), (b["x0"], t["y_lo"]),
            (t["x_outer"], t["y_lo"]), (t["x_outer"], t["y_hi"]), (b["x0"], t["y_hi"]),
            (b["x0"], b["y1"])]
    segs += list(zip(pts2[:-1], pts2[1:]))
    for a, z in segs:
        s = shape(board, pcbnew.Edge_Cuts, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(*a)); s.SetEnd(P(*z)); board.Add(s)
    s = shape(board, pcbnew.Edge_Cuts, pcbnew.SHAPE_T_ARC)
    s.SetArcGeometry(P(*arc[0]), P(*arc[1]), P(*arc[2])); board.Add(s)


def new_fp(board, lib_item, ref, value):
    fp = pcbnew.FOOTPRINT(board)
    fp.SetFPID(pcbnew.LIB_ID(LIB_NAME, lib_item))
    fp.SetReference(ref)
    fp.SetValue(value)
    fp.Reference().SetLayer(pcbnew.F_Fab)
    fp.Value().SetLayer(pcbnew.F_Fab)
    fp.Value().SetVisible(False)
    return fp


def add_pad(fp, number, local, drill, size, plated=True, shape_kind=pcbnew.PAD_SHAPE_CIRCLE):
    pad = pcbnew.PAD(fp)
    pad.SetNumber(number)
    if plated:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetLayerSet(pad.PTHMask())
        pad.SetShape(shape_kind)
        pad.SetSize(VECTOR2I(FromMM(size), FromMM(size)))
    else:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
        pad.SetLayerSet(pad.UnplatedHoleMask())
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(VECTOR2I(FromMM(drill), FromMM(drill)))
    pad.SetDrillSize(VECTOR2I(FromMM(drill), FromMM(drill)))
    v = VECTOR2I(FromMM(local[0]), FromMM(local[1]))     # footprint-local, KiCad axes
    pad.SetPos0(v); pad.SetPosition(v)
    fp.Add(pad)
    return pad


def fp_rect(fp, layer, x0, y0, x1, y1, w=0.1):
    for a, z in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
        s = pcbnew.FP_SHAPE(fp, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(layer); s.SetWidth(FromMM(w))
        s.SetStart0(VECTOR2I(FromMM(a[0]), FromMM(a[1]))); s.SetEnd0(VECTOR2I(FromMM(z[0]), FromMM(z[1])))
        s.SetStart(s.GetStart0()); s.SetEnd(s.GetEnd0())
        fp.Add(s)


def fp_circle(fp, layer, r, w=0.05):
    s = pcbnew.FP_SHAPE(fp, pcbnew.SHAPE_T_CIRCLE)
    s.SetLayer(layer); s.SetWidth(FromMM(w))
    s.SetStart0(VECTOR2I(0, 0)); s.SetEnd0(VECTOR2I(FromMM(r), 0))
    s.SetStart(s.GetStart0()); s.SetEnd(s.GetEnd0())
    fp.Add(s)


def place(board, fp, x, y):
    fp.SetPosition(P(x, y))
    board.Add(fp)


# --------------------------- footprint builders ---------------------------
def fp_mount_plated(board, ref):
    fp = new_fp(board, "MountingHole_4.0mm_Pad6.5", ref, "MountingHole_4mm")
    add_pad(fp, "1", (0, 0), PLATED_HOLE["drill"], PLATED_HOLE["pad"])
    fp_circle(fp, pcbnew.F_CrtYd, PLATED_HOLE["pad"] / 2 + 0.25)
    fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    return fp


def fp_npth(board, ref, drill):
    fp = new_fp(board, "NPTH_%.1fmm" % drill, ref, "NPTH_%.1fmm" % drill)
    add_pad(fp, "", (0, 0), drill, drill, plated=False)
    fp_circle(fp, pcbnew.F_CrtYd, drill / 2 + 0.25)
    fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    return fp


def fp_cn2(board):
    """2x20 2.54 mm receptacle. Built top-view, anchored at pin 1, then flipped to
    the back side. Local x is pre-mirrored so absolute pad positions survive the
    left/right flip."""
    c = CN2
    fp = new_fp(board, "CN2_2x20_P2.54_Receptacle_Back", "CN2", "SSW-120-01-T-D-LL")
    for k in range(c["n_per_row"]):
        dx = -c["pitch"] * k                      # design frame: toward -X
        for j, dy in enumerate((0.0, -c["row"])): # odd row at pin1, even row below
            num = str(2 * k + 1 + j)
            local = (-dx, -dy)                    # pre-mirror X; KiCad Y = -design Y
            add_pad(fp, num, local, c["drill"], c["pad"],
                    shape_kind=pcbnew.PAD_SHAPE_RECT if num == "1" else pcbnew.PAD_SHAPE_CIRCLE)
    span = c["pitch"] * (c["n_per_row"] - 1)
    fp_rect(fp, pcbnew.F_Fab, -1.27, -1.27, span + 1.27, c["row"] + 1.27)
    fp_rect(fp, pcbnew.F_CrtYd, -1.8, -1.8, span + 1.8, c["row"] + 1.8, 0.05)
    place(board, fp, *c["pin1"])
    fp.Flip(fp.GetPosition(), True)               # to the back side, mirror left/right
    return fp


def fp_cn1(board):
    c = CN1
    fp = new_fp(board, "CN1_GM_48pos_4x12", "CN1", "GM X1 48-way")
    ox, oy = c["cols_x"][1], c["rows_y"]["M"]     # anchor at M1
    for row, y in c["rows_y"].items():
        for col, x in c["cols_x"].items():
            num = "%s%d" % (row, col)
            add_pad(fp, num, (x - ox, -(y - oy)), c["drill"], c["pad"],
                    shape_kind=pcbnew.PAD_SHAPE_RECT if num == "A1" else pcbnew.PAD_SHAPE_CIRCLE)
    for (x, y) in c["locate"]:
        add_pad(fp, "", (x - ox, -(y - oy)), c["locate_drill"], c["locate_drill"], plated=False)
    xs = [x - ox for x in c["cols_x"].values()] + [x - ox for x, _ in c["locate"]]
    ys = [-(y - oy) for y in c["rows_y"].values()] + [-(y - oy) for _, y in c["locate"]]
    fp_rect(fp, pcbnew.F_CrtYd, min(xs) - 2.5, min(ys) - 2.5, max(xs) + 2.5, max(ys) + 2.5, 0.05)
    place(board, fp, ox, oy)
    return fp


# ------------------------------- checks -----------------------------------
def verify(board):
    """Assert every pad lands where the design table says (design frame, 0.01 mm)."""
    want = {}
    for ref, x, y in MOUNT_HOLES:
        want[(ref, "1")] = (x, y)
    for ref, x, y, _ in NPTH_HOLES:
        want[(ref, "")] = (x, y)
    p1x, p1y = CN2["pin1"]
    for k in range(CN2["n_per_row"]):
        want[("CN2", str(2 * k + 1))] = (p1x - CN2["pitch"] * k, p1y)
        want[("CN2", str(2 * k + 2))] = (p1x - CN2["pitch"] * k, p1y - CN2["row"])
    for row, y in CN1["rows_y"].items():
        for col, x in CN1["cols_x"].items():
            want[("CN1", "%s%d" % (row, col))] = (x, y)
    got = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if fp.GetReference() == "CN1" and pad.GetNumber() == "":
                continue
            got[(fp.GetReference(), pad.GetNumber())] = to_design(pad.GetPosition())
    bad = [(k, want[k], got.get(k)) for k in want
           if k not in got or math.dist(want[k], got[k]) > 0.01]
    cn2 = next(f for f in board.GetFootprints() if f.GetReference() == "CN2")
    assert cn2.IsFlipped(), "CN2 must be on the back side"
    assert not bad, "pad position mismatch: %s" % bad[:5]
    return len(want)


def main():
    board = pcbnew.BOARD()
    board.GetDesignSettings().SetBoardThickness(FromMM(BOARD_THICKNESS))
    board.GetDesignSettings().SetAuxOrigin(P(0, 0))   # drill/place origin = H1
    board.GetDesignSettings().SetGridOrigin(P(0, 0))

    edge_outline(board)
    for ref, x, y in MOUNT_HOLES:
        place(board, fp_mount_plated(board, ref), x, y)
    for ref, x, y, d in NPTH_HOLES:
        place(board, fp_npth(board, ref, d), x, y)
    fp_cn1(board)
    fp_cn2(board)

    n = verify(board)

    # Footprint library (unflipped copies) for reuse in the schematic.
    if not os.path.isdir(LIB_DIR):
        pcbnew.FootprintLibCreate(LIB_DIR)
    seen = set()
    for fp in board.GetFootprints():
        name = fp.GetFPID().GetLibItemName().wx_str()
        if name in seen:
            continue
        seen.add(name)
        lib_fp = pcbnew.FOOTPRINT(fp)
        if lib_fp.IsFlipped():
            lib_fp.Flip(lib_fp.GetPosition(), True)
        lib_fp.SetPosition(VECTOR2I(0, 0)); lib_fp.SetOrientationDegrees(0)
        pcbnew.FootprintSave(LIB_DIR, lib_fp)

    pcbnew.SaveBoard(PCB_FILE, board)
    txt = open(PCB_FILE).read()                       # page size isn't exposed in the
    open(PCB_FILE, "w").write(txt.replace('(paper "A4")', '(paper "A3")', 1))  # v7 bindings
    print("wrote %s  (%d pad positions verified)" % (os.path.relpath(PCB_FILE, PROJ), n))


if __name__ == "__main__":
    sys.exit(main())
