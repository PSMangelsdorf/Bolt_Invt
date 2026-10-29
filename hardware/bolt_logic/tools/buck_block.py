"""Hand-designed layout block for the 5 V buck (U1 AP63205WU and its parts).

The autoplacer/autorouter only know connectivity; a switching regulator's layout is part of
the circuit. This block fixes the placement and draws the critical copper itself, before the
autorouter runs, which then routes only the block's external connections (VCC_12V in,
+5V out).

Coordinates are in U1's local frame in mm (U1 at orientation 0, KiCad axes: x right, y DOWN).
TSOT-23-6 pins: 1 FB (-1.14,-0.95)  2 EN (-1.14,0)  3 VIN (-1.14,0.95)
                6 BST (1.14,-0.95)  5 SW (1.14,0)   4 GND (1.14,0.95)

Layout (AP63205 datasheet: VIN caps as close to the device as possible, GND vias at the
input/output cap grounds, ground copper under the device):
- Input loop: C5 (100 nF) then C1, C2 (10 uF) stacked straight under the VIN/GND pin pair,
  VIN pad left, GND pad right, joined by short wide VIN and GND buses.
- Bootstrap: C6 upright next to the BST/SW pins.
- SW node: one short 1.5 mm strip from SW to L1 (about 4 mm long).
- Output: C7, C8 (22 uF), C9 (100 nF) under L1; their GND ties straight to the input-cap GND.
- FB (fixed 5 V part, pin 1 = output sense): via next to pin 1, B.Cu to the output caps; the
  In1 GND plane sits between it and the SW node.
"""

# Design-frame position of U1 (see gen_mech.py: origin H1, +y up) and its orientation.
U1_AT = (40.0, 100.0)
U1_ROT = 0

# ref: (dx, dy, direction of pad 1 from the part centre: "left", "right", "up", "down")
PARTS = {
    "C5": (0.0, 2.75, "left"),    # 100 nF, VIN | GND
    "C1": (0.0, 4.90, "left"),    # 10 uF,  VIN | GND
    "C2": (0.0, 7.25, "left"),    # 10 uF,  VIN | GND
    "C6": (3.10, -0.475, "up"),   # bootstrap: pad 1 = BST (up), pad 2 = SW
    "L1": (7.60, 0.50, "left"),   # pad 1 = SW (left), pad 2 = +5V
    "C7": (7.60, 4.95, "right"),  # 22 uF,  +5V (right) | GND
    "C8": (7.60, 7.30, "right"),  # 22 uF
    "C9": (7.60, 9.50, "right"),  # 100 nF
}

# (net, layer, width, [points...]) in U1-local mm
TRACKS = [
    # VIN: EN tied to VIN, then the VIN bus down through the input caps
    ("VCC_12V", "F.Cu", 0.6, [(-1.1375, 0.0), (-1.1375, 0.95)]),
    ("VCC_12V", "F.Cu", 0.6, [(-1.1375, 0.95), (-1.2, 1.8)]),
    ("VCC_12V", "F.Cu", 1.0, [(-1.2, 1.8), (-1.2, 7.25)]),
    # GND bus from the GND pin down through the input caps
    ("GND", "F.Cu", 0.6, [(1.1375, 0.95), (1.2, 1.8)]),
    ("GND", "F.Cu", 1.0, [(1.2, 1.8), (1.2, 7.25)]),
    # input-cap GND to output-cap GND (common return), and the output GND bus
    ("GND", "F.Cu", 1.0, [(1.475, 4.9), (6.125, 4.9)]),
    ("GND", "F.Cu", 1.0, [(1.475, 7.2), (6.125, 7.2)]),
    ("GND", "F.Cu", 1.0, [(6.4, 4.9), (6.4, 9.5)]),
    ("GND", "F.Cu", 1.0, [(3.8, 4.9), (3.8, 7.2)]),
    ("GND", "F.Cu", 0.8, [(1.2, 2.75), (2.4, 2.75)]),
    # bootstrap
    ("BST_5V", "F.Cu", 0.4, [(1.1375, -0.95), (2.0, -1.425), (3.1, -1.425)]),
    # SW node: narrow out of the pin, then one wide strip into L1 pad 1 (passes C6 pad 2)
    ("SW_5V", "F.Cu", 0.6, [(1.1375, 0.0), (2.8, 0.15)]),
    ("SW_5V", "F.Cu", 1.5, [(2.8, 0.15), (5.525, 0.15)]),
    # +5V: L1 pad 2 down through the output caps to the FB return via
    ("+5V", "F.Cu", 1.0, [(9.675, 0.5), (9.0, 3.4), (9.0, 10.9)]),
    # FB sense: pin 1 -> via -> B.Cu -> via at the output caps
    ("+5V", "F.Cu", 0.3, [(-1.1375, -0.95), (-2.2, -2.0)]),
    ("+5V", "B.Cu", 0.4, [(-2.2, -2.0), (-2.2, 10.9), (9.0, 10.9)]),
]

# (net, x, y) through vias, U1-local mm
VIAS = [
    ("+5V", -2.2, -2.0),          # FB via
    ("+5V", 9.0, 10.9),           # FB return at the output caps
    ("GND", 2.4, 2.75),           # input-loop ground to the In1 plane
    ("GND", 3.8, 4.9),            # GND vias between input and output caps
    ("GND", 3.8, 7.2),
    ("GND", 3.8, 6.05),
]

# Silkscreen reference positions (U1-local mm): the block is too dense for a label beside every
# part, so the labels sit around its outside, level with their part.
LABELS = {
    "U1": (-0.6, -3.1), "C6": (3.1, -3.1), "L1": (7.6, -4.4),
    "C5": (-4.0, 2.75), "C1": (-4.0, 4.90), "C2": (-4.0, 7.25),
    "C7": (11.6, 4.95), "C8": (11.6, 7.30), "C9": (11.6, 9.50),
}

REFS = ["U1"] + list(PARTS)
