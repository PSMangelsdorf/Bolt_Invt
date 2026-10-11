# Bolt Logic Board — Mechanical Definition (v0.2)

Sources: owner's caliper/ruler measurements, cross-checked against two ruler-referenced
photos (component side and connector side). Each photo was perspective-corrected by
fitting the four straight body edges (≤ 0.16 mm RMS) and solving a homography onto the
278 × 112 mm body; the two photos agree on every hole to within ~0.5 mm. Disputed values
were re-checked with calipers by the owner and are now confirmed.

The KiCad board is generated from this data by
`hardware/bolt_logic/tools/gen_mech.py` (single source of truth). The generator asserts
all 102 pad positions against the table; KiCad DRC reports 0 violations.
Visual check of the KiCad file against the real board: `mechanical_overlay.png`.

## Coordinate system

- Viewed from the **component side** (opposite CN2's housing), external connector tab on
  the **left**.
- **Origin = centre of the bottom-left 4 mm mounting hole (H1).** +X right, +Y up, mm.
- In KiCad, the auxiliary (drill/place) origin and grid origin are set on H1; KiCad's +Y
  is down.
- All mounting holes sit 5.0 mm in from the adjacent body edges.

## Board

| Item | Value | Status |
|----|----|----|
| Material / thickness | FR-4, 2.0 mm | confirmed |
| Body | 278.0 × 112.0, corners (−5, −5) … (273, 107) | confirmed |
| Connector tab (left) | x −16 … −5, y 33 … 85 (11 deep × 52 wide) | confirmed |
| Notch (bottom edge) | R7 semicircle, centre (121.6, −5) | photo (both agree) |
| Chamfer (top-right) | (253.4, 107) → (273, 67.7) | photo (both agree) |
| Corner radii | modelled sharp | minor, optional to measure |
| Silkscreen legend "290.5 × 133" | does not match this board's width | ignore |

## Holes

| Ref | x | y | Ø | Type | Status |
|----|----|----|----|----|----|
| H1 | 0 | 0 | 4.0 | plated (origin) | confirmed |
| H2 | 0 | 102 | 4.0 | plated | confirmed |
| H3 | 61 | 71.7 | 4.0 | plated | confirmed (was listed as 70, 61) |
| H4 | 134 | 102 | 4.0 | plated | confirmed |
| H5 | 141 | 0 | 4.0 | plated | confirmed |
| H6 | 188 | 14 | 4.0 | plated | confirmed |
| H7 | 188 | 67 | 4.0 | plated | confirmed |
| H8 | 241 | 14 | 4.0 | plated | confirmed |
| H9 | 241 | 67 | 4.0 | plated | confirmed |
| H10 | 248 | 102 | 4.0 | plated | confirmed |
| H11 | 268 | 0 | 4.0 | plated | confirmed |
| H12 | 268 | 50 | 4.0 | plated | confirmed (photos read 51.0) |
| H13 | 39 | 0 | 4.5 | non-plated, beside CN2 | confirmed (photos 39.6) |
| H14 | 231 | 101 | 4.5 | non-plated | confirmed (was listed as 251, 49) |
| CN1 locating | −8.5 | 39.5 / 77.5 | 3.0 | non-plated, in CN1 footprint | confirmed |

Plated pads modelled at 6.5 mm OD (photo ring OD 6.5–6.8). Net assignment (GND /
chassis / floating) to be decided in the schematic.

## CN2 — internal 2×20 board-to-board receptacle (back side)

| Item | Value | Status |
|----|----|----|
| Arrangement | 2 × 20, rows parallel to X | confirmed |
| Pitch / row spacing | 2.54 mm (pin 1 → pin 39 = 48.26) | confirmed |
| Pin 1 | (47.73, 15.82); odd pins upper row, even pins lower row (y 13.28) | confirmed; matches Phase 1 numbering |
| Pin 39 / 40 | (−0.53, 15.82) / (−0.53, 13.28) | |
| Mounting | female receptacle, body on the back side; the gate board's pins set the stack | confirmed |
| Part | **Samtec SSW-120-01-T-D-LL** (owner-identified; Samtec logo on the housing): 2×20 socket strip, 2.54 mm, -01 tail 2.64 mm, "-LL" = locking leads, mates TSW-style 0.64 mm posts, 5.7 A/pin | identified |
| Pads | Ø1.02 drill / 1.7 pad (0.64 mm square tails) | |
| Open | confirm insulator height against the OEM part (measure, or Samtec drawing) | open |

## CN1 — external GM 48-way header (mates 98993-5021 / service 19354859)

| Item | Value | Status |
|----|----|----|
| Arrangement | 4 columns × 12 rows A–M (no I); pad names A1 … M4 | confirmed |
| Orientation | **M1 top-right** (highest x, y), M4 top-left; column 1 at x = 0.3 | confirmed |
| Column x | col 1 = 0.3, col 2 = −3.7, col 3 = −7.7, col 4 = −11.7 (4.0 pitch) | photo |
| Row y | M 73.25, L 69.55, K 66.10, J 63.55, then 2.50 pitch to A 43.55 | photo (±0.3) |
| Locating holes | 3.0 mm at (−8.5, 39.5) and (−8.5, 77.5) | confirmed |
| Pads | Ø1.0 drill / 1.7 pad placeholder | **open** — confirm from part datasheet |
| Open | header part ("JXI 2", "366380002"), terminal hole sizes (rows M/L may differ) | **open** |

## Remaining open items

1. CN2 insulator height check (part identified: Samtec SSW-120-01-T-D-LL).
2. CN1 header part number and hole diameters.
3. Mounting-hole net assignment (schematic decision).
4. Optional: corner radii.
