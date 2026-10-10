# Bolt Logic Board — Mechanical Definition (draft v0.1)

Sources: owner's caliper/ruler measurements, cross-checked against two ruler-referenced
photos (component side and connector side). Each photo was perspective-corrected by
fitting the four straight body edges (fit residual ≤ 0.16 mm RMS) and solving a
homography onto the measured 278 × 112 mm body. The two photos agree with each other on
every hole to within ~0.5 mm. Overlay check: `mechanical_overlay.png`.

**Status:** photo-derived values are ±0.5 mm. Items marked **VERIFY** must be confirmed
with calipers before the outline and footprints are frozen.

## Coordinate system

- Viewed from the **component side** (the side opposite CN2's housing).
- External connector tab on the **left**.
- **Origin = center of the bottom-left 4 mm mounting hole.** +X right, +Y up.
- KiCad uses +Y down; the generator will flip Y.
- All mounting holes sit 5.0 mm in from the adjacent body edges.

## Board

| Item | Value | Notes |
|----|----|----|
| Material / thickness | FR-4, **2.0 mm** | confirmed |
| Body | 278.0 × 112.0 mm, corners at (−5, −5) and (273, 107) | confirmed (caliper + both photos) |
| Connector tab (left) | x −16.1 … −5, y 33 … 85 (11.1 deep × 52 wide) | **VERIFY depth** — measured 1 mm by caliper, 11.1 mm in both photos |
| Notch (bottom edge) | R7 semicircle, center (121.6, −5) | photo, both agree |
| Chamfer (top-right) | (253.4, 107) → (273, 67.7) — 19.6 × 39.3 mm | photo, both agree |
| Silkscreen legend | "290.5 × 133" | width doesn't match this board (112) — treat as unreliable |

## Holes

| # | x | y | Ø | Type | Status |
|----|----|----|----|----|----|
| 1 | 0 | 0 | 4.0 | plated, origin | confirmed |
| 2 | 0 | 102 | 4.0 | plated | confirmed |
| 3 | **61** | **71.7** | 4.0 | plated | **VERIFY** — listed as (70, 61); photos show (61, 71.7), likely swapped |
| 4 | 134 | 102 | 4.0 | plated | confirmed |
| 5 | 141 | 0 | 4.0 | plated | confirmed |
| 6 | 188 | 14 | 4.0 | plated | confirmed |
| 7 | 188 | 67 | 4.0 | plated | confirmed (photos 66.3) |
| 8 | 241 | 14 | 4.0 | plated | confirmed |
| 9 | 241 | 67 | 4.0 | plated | confirmed (photos 66.5) |
| 10 | 248 | 102 | 4.0 | plated | confirmed |
| 11 | 268 | 0 | 4.0 | plated | confirmed |
| 12 | 268 | 50 | 4.0 | plated | minor: photos read 51.0 |
| 13 | 39 | 0 | 4.5 | non-plated (back) | confirmed; photos 39.6. Sits by CN2 → likely board-to-board alignment |
| 14 | **≈231** | **≈101** | 4.5 | non-plated | **VERIFY** — listed as (251, 49); no hole there (QR label). Photo shows a plain hole at ≈(231, 101) |
| 15 | −8.6 | 39.5 | 3.0 | locating, ext. connector | confirmed (7.5 from tab edge, 38 apart) |
| 16 | −8.6 | 77.5 | 3.0 | locating, ext. connector | confirmed |

## CN2 — internal 40-pin board-to-board connector

| Item | Value |
|----|----|
| Arrangement | 2 × 20, rows parallel to X |
| Pitch / row spacing | **2.54 mm** (0.1") — photo 2.551 over 19 pitches; 2.50 would be 0.76 mm off by pin 20 — **VERIFY** |
| Pin 1 | (47.7, 15.8) — silkscreen "1"; odd pins on upper row (y 15.8), even on lower (y 13.3) |
| Pin 39 / 40 | (−0.5, 15.8) / (−0.5, 13.3) |
| Housing | female receptacle on the **back** side (bottom layer); marking "S" with bars |
| Open | mating part number, **stack height** to gate board |

## J1 — external 48-way connector (GM X1, mates 98993-5021 / 19354859)

| Item | Value |
|----|----|
| Arrangement | 4 columns (along X) × 12 rows A–M (no I), rows along Y |
| Column x | −11.7, −7.7, −3.7, +0.3 (pitch **4.0**; first column 4.5 from tab edge) |
| Row y | M 73.3, L 69.6, K 66.1, J 63.6, then 2.50 pitch down to A 43.6 |
| Locating holes | #15, #16 (3 mm), symmetric about the pin field |
| Open | which end is column 1 (read M1/M4 silkscreen); connector part ("JXI 2", "366380002") |

Caliper readings of 3.5 / 3.0 / 2.0 mm match the photo center-to-center pitches
(4.0 / 3.7 / 2.5) minus about one hole diameter — consistent with edge-to-edge gaps.

## Verification checklist (calipers)

1. Tab depth (outer tab edge to body edge): expect ~11.1 mm.
2. Hole #3 center: expect (61, 71.7).
3. Second 4.5 mm hole: expect ≈(231, 101).
4. CN2: pin 1 to pin 39 center-to-center — 48.26 mm (2.54) vs 47.50 (2.50); pin 1 position.
5. J1: column 1 to column 4 = 12.0 mm; row J to row A = 20.0 mm; which corner is M1.
6. Board-to-board stack height (logic board to gate board).
7. Optional: hole #12 y (50 vs 51), hole #13 x (39 vs 39.6).
