"""Prototype fabrication package for JLCPCB, written to fab/ at the repository root.

    python3 tools/gen_fab.py

Run it after gen_route.py. It writes:
  bolt_logic_<rev>_gerbers.zip   Gerbers (4 copper layers, masks, paste, silk, outline) + Excellon drill
  bolt_logic_<rev>_bom_jlc.csv   JLC assembly BOM: Comment, Designator, Footprint, LCSC Part #
  bolt_logic_<rev>_cpl_jlc.csv   JLC placement file: Designator, Mid X, Mid Y, Layer, Rotation
  bolt_logic_<rev>_bom_full.csv  every part, with MPN, spec, source and who fits it
  README.md                      fab notes: board spec to enter in the order, hand-solder list, open items

Part choices come from tools/jlc_parts.py; the run fails if a BOM line has no entry there.
"""
import csv
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(PROJ))
sys.path.insert(0, HERE)
import gen_mech  # noqa: E402
from jlc_parts import PARTS  # noqa: E402

REV = "v0.1"
PCB = os.path.join(PROJ, "bolt_logic.kicad_pcb")
OUT = os.path.join(ROOT, "fab")
LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen",
          "F.Mask", "B.Mask", "Edge.Cuts"]


def natural(ref):
    m = re.match(r"([A-Z#]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def board_parts(board):
    """[(ref, value, footprint name, footprint)] for every footprint except mounting holes."""
    rows = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if re.match(r"H\d+$", ref):
            continue
        rows.append((ref, fp.GetValue(), str(fp.GetFPID().GetUniStringLibItemName()), fp))
    return sorted(rows, key=lambda r: natural(r[0]))


def plot(board_file, tmp):
    os.makedirs(tmp)
    run = lambda *a: subprocess.run(["kicad-cli", "pcb", "export", *a], check=True, capture_output=True, text=True)
    run("gerbers", "--output", tmp + "/", "--layers", ",".join(LAYERS), "--no-x2", "--subtract-soldermask",
        board_file)
    run("drill", "--output", tmp + "/", "--format", "excellon", "--excellon-units", "mm",
        "--excellon-separate-th", board_file)
    files = sorted(os.listdir(tmp))
    want = ["-F_Cu.gtl", "-In1_Cu.g2", "-In2_Cu.g3", "-B_Cu.gbl", "-Edge_Cuts.gm1", "-PTH.drl", "-NPTH.drl"]
    missing = [w for w in want if not any(f.endswith(w) for f in files)]
    if missing:
        raise SystemExit("plot is missing %s (got %s)" % (missing, files))
    return files


def main():
    board = pcbnew.LoadBoard(PCB)
    ds = board.GetDesignSettings()
    mm = pcbnew.ToMM
    parts = board_parts(board)
    missing = sorted({(v, f) for _, v, f, _ in parts if (v, f) not in PARTS})
    if missing:
        raise SystemExit("no jlc_parts.py entry for: %s" % missing)

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    tmp = os.path.join(OUT, "_plot")
    files = plot(PCB, tmp)
    zpath = os.path.join(OUT, "bolt_logic_%s_gerbers.zip" % REV)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(tmp, f), f)
    shutil.rmtree(tmp)

    # ------------------------------------------------------------ BOMs
    lines = {}
    for ref, v, f, fp in parts:
        lines.setdefault((v, f), []).append(ref)
    jlc_rows, full_rows, hand = [], [], []
    for (v, f), refs in sorted(lines.items(), key=lambda kv: natural(kv[1][0])):
        lcsc, mpn, spec, src, fit, note = PARTS[(v, f)]
        full_rows.append([len(refs), ",".join(refs), v, f, spec, mpn, lcsc, src, fit, note])
        if fit == "smt":
            assert lcsc, (v, f)
            jlc_rows.append([spec or v, ",".join(refs), f, lcsc])
        elif fit == "hand":
            hand.append((refs, mpn or v, note))
    with open(os.path.join(OUT, "bolt_logic_%s_bom_jlc.csv" % REV), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        w.writerows(jlc_rows)
    with open(os.path.join(OUT, "bolt_logic_%s_bom_full.csv" % REV), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Qty", "Designators", "Value", "Footprint", "Chosen spec", "MPN", "LCSC", "Source", "Fit by",
                    "Note"])
        w.writerows(full_rows)

    # ------------------------------------------------------------ CPL (same absolute frame as the Gerbers)
    smt_refs = {r for (v, f), refs in lines.items() if PARTS[(v, f)][4] == "smt" for r in refs}
    cpl = []
    for ref, v, f, fp in parts:
        if ref not in smt_refs:
            continue
        p = fp.GetPosition()
        side = "Top" if fp.GetLayer() == pcbnew.F_Cu else "Bottom"
        rot = fp.GetOrientationDegrees() % 360
        cpl.append([ref, "%.4fmm" % mm(p.x), "%.4fmm" % (-mm(p.y)), side, "%g" % round(rot, 3)])
    with open(os.path.join(OUT, "bolt_logic_%s_cpl_jlc.csv" % REV), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(cpl)

    # ------------------------------------------------------------ fab notes
    bb = board.GetBoardEdgesBoundingBox()
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    min_track = min(mm(t.GetWidth()) for t in tracks)
    drills = [mm(v.GetDrill()) for v in vias]
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                drills.append(mm(min(p.GetDrillSize().x, p.GetDrillSize().y)))
    cu = {n: t for n, k, t in gen_mech.STACKUP if k == "copper"}
    oz = lambda t: "%g oz" % round(t / 0.035, 1)
    sides = sorted({r[3] for r in cpl})
    n_smt = len(cpl)
    note = README.format(
        rev=REV, w=mm(bb.GetWidth()), h=mm(bb.GetHeight()), thick=mm(ds.GetBoardThickness()),
        outer=oz(cu["F.Cu"]), inner=oz(cu["In1.Cu"]), min_track=min_track, min_drill=min(drills),
        via="%.1f / %.1f" % (mm(vias[0].GetWidth()), mm(vias[0].GetDrill())), sides=", ".join(sides), n_smt=n_smt,
        n_lines=len(jlc_rows),
        hand="\n".join("| %s | %s | %s |" % (", ".join(r), m, n) for r, m, n in hand))
    open(os.path.join(OUT, "README.md"), "w").write(note)
    print("wrote %s: %d gerber/drill files, JLC BOM %d lines / %d placements (%s), %d hand-fit lines" % (
        os.path.relpath(OUT, ROOT), len(files), len(jlc_rows), n_smt, ", ".join(sides), len(hand)))


README = """# Bolt logic board {rev}: prototype fabrication files

**Prototype for bench testing. Do not install in a vehicle.** See *Open items* below.

Generated by `hardware/bolt_logic/tools/gen_fab.py` from `bolt_logic.kicad_pcb`; don't edit by hand.

| File | What it is |
|----|----|
| `bolt_logic_{rev}_gerbers.zip` | Gerbers (F.Cu, In1.Cu, In2.Cu, B.Cu, masks, paste, silk, outline) and Excellon drill files (plated and non-plated separate). Upload this as the PCB. |
| `bolt_logic_{rev}_bom_jlc.csv` | JLCPCB assembly BOM ({n_lines} lines), LCSC part numbers. |
| `bolt_logic_{rev}_cpl_jlc.csv` | JLCPCB placement file ({n_smt} parts, side: {sides}). |
| `bolt_logic_{rev}_bom_full.csv` | Every part: chosen spec, MPN, where the LCSC number was checked, and who fits it. |

## PCB order settings

| Setting | Value |
|----|----|
| Layers | 4 |
| Size | {w:.1f} x {h:.1f} mm (outline in the Gerbers) |
| Thickness | {thick:.1f} mm |
| Material | FR-4 |
| Outer copper | **{outer}** (not the default; owner decision, for the 5 V buck's heat) |
| Inner copper | {inner} |
| Stackup | the fab's standard 4-layer {thick:.1f} mm stackup for this copper weight; no impedance control needed |
| Min track / gap | {min_track:.2f} mm / 0.20 mm (every copper gap passes DRC at 0.20 mm) |
| Min hole | {min_drill:.2f} mm; vias {via} mm pad / drill |
| Surface finish | your choice. ENIG is flatter for the 0.5 mm pitch MCU; HASL is cheaper. |
| Remove order number | optional: there is no reserved spot for it on the silkscreen |

JLCPCB's 4-layer 2 oz limits (0.15 / 0.15 mm track and gap, 0.254 mm annular ring on
component holes) are met. A fab that needs 10 / 10 mil at 2 oz would not accept this
board; see `docs/04-layout.md` §1.

## Assembly

- Assemble the **top side** only, from the BOM and CPL above.
- Positions and rotations are KiCad's footprint origins and orientations, in the same
  frame as the Gerbers. JLCPCB's preview sometimes shows a part rotated by 90° or 180°
  against its library model (SOT-23, SOIC and LQFP most often), or offset where the
  footprint origin isn't the body centre (TO-252, TO-263, the ESP32 module). Check every
  IC's pin-1 marker and those bodies in the placement preview before confirming, or ask
  their DFM review to.
- Check stock for each line when you upload; JLCPCB shows it, and these numbers were
  checked in October 2026.

Fit by hand after delivery (or order through JLCPCB Global Sourcing, where noted):

| Ref | Part | Note |
|----|----|----|
{hand}

## Open items before trusting this board

1. **L272D pinout (U13, resolver exciter).** The KiCad symbol used is V+ = 4, V- = 6,
   amplifier A = 3 / 13 / 14, amplifier B = 5 / 11 / 12 (output / inputs). ST's SO-16 pin
   drawing is a figure, not text, and nobody has checked the symbol against it yet. Check it
   before fitting U13.
2. **L30, the ESP32 supply inductor.** It is a 10 uH 0805, as on V6 (which used a 0603).
   No 0805 10 uH part is really rated for the ESP32's ~0.5 A transmit peaks. Watch for WiFi
   brown-outs on the bench.
3. **CN1 holes** are 1.0 mm placeholders; the GM header part isn't identified yet.
4. **CN2 pin 18** is assumed to be the DC-bus voltage (bench test before high voltage).
"""

if __name__ == "__main__":
    main()
