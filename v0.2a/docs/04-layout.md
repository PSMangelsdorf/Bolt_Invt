# Bolt Logic Board — PCB Layout (v0.2a)

v0.2a is placed and routed. It is a prototype for review: not tested, and not yet ordered. Every
change from v0.1 follows the forum review, point by point in `06-forum-review.md`.

Renders:
- `layout_placement.png`: placement, ratsnest;
- `layout_routed.png`: routed, with the In2 plane outlines;
- `buck_block.png`: buck close-up.

The flow is generated end to end from scripts, so it can be re-run and reviewed:

```
python3 tools/gen_sch.py      # schematic + netlist check
python3 tools/gen_mech.py     # outline, holes, connectors, stackup
python3 tools/gen_layout.py   # placement
python3 tools/gen_route.py    # planes, pre-route, FreeRouting, pours, DRC  (FREEROUTING_JAR=...)
python3 tools/gen_fab.py      # Gerbers, drill, JLC BOM / CPL
```

## 1. Stackup and planes

| Layer | Use |
|----|----|
| F.Cu (2 oz) | signals, GND pour, chassis ring |
| In1.Cu | **solid GND plane**, nothing routed |
| In2.Cu | **power planes**, nothing routed: +3V3 over most of the board; islands for VCC_12V, +5V, ESP_3V3; GND under each crystal |
| B.Cu (2 oz) | signals, GND pour, chassis ring |

In1 and In2 are KiCad *power* layers, so the autorouter cannot use them.

The In2 islands are rectangles that may run past the outline; KiCad clips them (`plane_regions()` in `gen_route.py`):

| Island | Covers |
|----|----|
| VCC_12V (pink in the render) | D1, the bulk caps, the buck input, Q2's supply tab |
| +5V (orange) | buck output, L1, output caps, FB1, LDO U2 input |
| ESP_3V3 (cyan) | U31, C124, the module supply pin and its caps |
| GND (green) | Y1 / Y2 and their load caps |

- Everything else is +3V3. The U2 output tab sits on the +3V3 plane, with three vias.
- The +5V loads away from the power corner (gate logic, comparators, polyfuses, ESP LDO input) are fed by 0.5 mm traces.
- Thermal reliefs on the inner planes are 0.5 mm gap and 0.45 mm spoke, for hand-soldering CN1, CN2, J1 and J4.

Limits:
- 2 oz outer copper, 0.15 / 0.20 mm minimum track and gap.
- Vias 0.6 / 0.3 mm.
- Parts are kept 2.5 mm from the edge for the chassis ring.

## 2. Placement (functional floorplan)

| Area (design frame, origin H1, +y up) | Contents |
|----|----|
| Top left, beside CN1 row M (VBAT) | Power entry: **TVS1 first** (16.5, 83), Q1, D1, bulk caps, AP63205 buck block, LD1117 U2, FB1, Q2 |
| Beside CN1 rows B–E, just outside the 10 mm zone | **Contactor drivers U20–U22**, at x = 24, y = 60 / 47 / 34, tab (output) toward CN1 |
| x 42–118, y 27–68 | CAN (U23), resolver exciter and receivers, next to CN1 rows B–F |
| x 42–128, y 68–104 | Vehicle input dividers and filters |
| Beside CN2 (bottom left) | Current-sense front end, overcurrent comparators, temperature mux |
| Centre | **STM32 at (145, 54), rotated 90°**, with its decaps, crystals, SWD |
| Below the MCU | Gate-board PWM latch and fault logic |
| Bottom right | ESP32 module (antenna at the edge), U31, C124, J4 |

Rules unchanged from v0.1:
- nothing within 10 mm of CN1 / CN2;
- everything below 7/8" (22.2 mm) total height (tallest: J1 / J4 8.5 mm, C124 5.8 mm);
- only CN1, CN2, J1, J4 and TP1 / TP2.

The placement order is:
1. anchors (connectors, holes, U3, U30, TVS1, U20–22, U13);
2. each IC followed straight away by its own decoupling and load parts, with the crystals and load caps first in the MCU group;
3. everything else.

**Decap distance**, from the cap pad to the IC pin it serves, over 48 decoupling and load parts:
- median 4.6 mm; 18 of them within 4 mm.
- Outliers:
  - C124 (ESP bulk) 19.6 mm and U31 (ESP LDO) 20.8 mm. They sit across the module from its supply pin, because mounting hole H8 and the antenna keep-out fill the near side. Both are on the ESP_3V3 plane island, so the current runs on a plane, not a trace.
  - The EN RC (R130 / C122) is 9 mm away.
  - C27 (NRST) is 9.5 mm away.
  - C62 (mux) is 9.5 mm away.
  - Q4 → Q2 is 10.8 mm (gate drive, slow).

All references are horizontal and sit above their part. After routing, every reference that touched a via, pad, part or other reference was moved; six in the WiFi corner have no free spot and are hidden (see `fab/README.md`).

## 3. Pre-routed copper (locked)

| Block | What |
|----|----|
| Buck (U1) | Datasheet layout. The VIN, GND, SW and +5V buses are **copper zones**, with locked tracks under them so the autorouter stays out. The pin necks and the FB sense line are traces. |
| Oscillators | MCU pin → crystal → load cap on F.Cu, 0.2 mm, no vias. Each QFP pin leaves on a straight escape first. B.Cu keep-out under each crystal; F.Cu keep-out between its pads; In2 GND island under crystal + caps. |
| Contactor drivers | Tab (output) zones on F and B extended 2.8 mm toward CN1 with a via column. Source GND zone with a via block. 42 vias placed on the three drivers' tabs and sources. Outputs are 1.2 mm to CN1. |
| Decoupling | 66 short pad-to-pad ties: each IC supply pin to its cap. |
| Plane fan-out | One via per cap group onto its In2 plane, right outside the cap pad: +3V3 29, VCC_12V 6, ESP_3V3 8, +5V 2. |
| GND fan-out | A via beside every SMD GND pad, outside every footprint body. MCU pin 63 is the one exception: the 32 kHz crystal sits right outside it, so its via is just inside the pin row, under the LQFP body. |

## 4. Routing and finish

- FreeRouting on F.Cu / B.Cu only.
- Grid-search completion of the leftovers:
  - one connection, EXC_P to CN1 B2 behind the first pin column, is 0.6 mm wide instead of 0.8;
  - automatic rip-up of anything touching another net.
- Then:
  - GND stitching (314 vias);
  - chassis ring on F/B, stitched every 8 mm (68 vias);
  - F/B GND pours, 0.4 mm minimum width;
  - pour islands get a via;
  - dead-end slivers are stitched (32) or cut (13).

| | v0.2a |
|----|----|
| Track segments | 3118 (F 7.1 m, B 5.3 m) |
| Vias | 953 (GND 538, CHASSIS 68, +5V 33, +3V3 30, contactor outputs 31, VCC_12V 11, ESP_3V3 8, signals the rest) |
| Unconnected | **0** |
| Clearance / short / hole errors | **0** |
| Isolated copper | **0** |
| Silkscreen | 2 notes: the ESP32 module outline meets the board edge where its antenna sits flush, as in v0.1 |
| Footprint library notes | 199 "footprint differs from library", the same as v0.1 (KiCad library version, not geometry) |

## 5. For hand review before ordering

- Contactor output copper and the CN1 entry (rows B / E), and the EXC_P run behind CN1's first column.
- Buck block zones against the AP63205 datasheet layout (`buck_block.png`).
- Crystal areas: keep-outs, GND island, trace lengths.
- The ESP32 corner: U31 / C124 sit about 20 mm from the module pin, on the ESP_3V3 island.
- Silkscreen readability after the moves.
- Run KiCad's DRC with zones refilled after any edit; the generator does that.
