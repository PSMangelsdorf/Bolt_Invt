# 06 — v0.2a: response to the forum review of v0.1

The review started on page 3 of the build thread,
[Chevy Bolt Motor Control Adventures](https://openinverter.org/forum/viewtopic.php?t=6078&start=50),
with comments from Jack Bauer and jrbe. v0.2a is a redesign that answers each point. v0.1 stays
unchanged in `V0.1/` for comparison. A separate v0.2b is planned, so the forum can compare the two.

What did **not** change:
- the netlist, apart from the ESP32 supply (§2);
- CN1/CN2 pin assignments, so the firmware pin map is the same;
- the part choices the owner has approved, such as U20–U22 BTS133TC, Q1/Q2 BTS6143D and the AP63205.

## 1. Change table

| # | Who | Feedback | v0.2a |
|----|----|----|----|
| 1 | Jack | Reference designators all in one orientation | Every reference is horizontal and sits above its part, whatever the part's rotation (`ref_upright` in `gen_layout.py`). |
| 2 | Jack | Silkscreen must not overlap vias | After routing, any reference that touches a via, pad, part or other reference is moved to the nearest free spot (`refs_off_copper` in `gen_route.py`). |
| 3 | Jack, jrbe | Stackup: signal / GND / power / signal, with uninterrupted planes | F.Cu signal, **In1 solid GND**, **In2 power planes**, B.Cu signal. Nothing is routed on In1 or In2. Both inner layers are KiCad "power" layers, so FreeRouting can't use them. |
| 4 | Jack, jrbe | 3.3 V on thin traces is bad; put 3.3 V on a plane | In2 is a **+3V3 plane over most of the board**. +3V3 pins reach it through a via at their decoupling cap. |
| 5 | jrbe | In2 islands: small 12 V near the high-side switch and buck, 5 V, large 3.3 V | In2 zones (`POWER_ZONES` / `plane_regions` in `gen_route.py`): VCC_12V island over D1, the bulk caps, the buck input and Q2; +5V island over the buck output and LDO input; ESP_3V3 island around the WiFi module; +3V3 everywhere else. The zones are plain rectangles that overlap the outline, as suggested. KiCad clips them. |
| 6 | Jack, jrbe | Decoupling: plane → cap → IC | Each IC supply pin is tied by a short top-layer trace to its decap's pad. That group gets **one via at the cap**, onto its plane (`plane_fanout`). The IC pin has no via of its own. |
| 7 | jrbe | Vias right outside pads, never under ICs | Fan-out vias are placed only outside every footprint body. **One exception:** MCU pin 63 (VSS). The 32 kHz crystal sits right outside that pin (row 22), so its via is just inside the pin row, under the LQFP body, where there is no pad. |
| 8 | jrbe | Larger thermal reliefs on the inner planes for through-hole parts | Inner planes: 0.5 mm relief gap, 0.45 mm spokes (`INNER_THERMAL`). |
| 9 | jrbe | Avoid unintentional antennas (pour slivers): stitch or remove them | Outer GND pours have a 0.4 mm minimum width. After the fill, any narrow dead-end finger at least 4 mm long gets a stitching via; if no via fits, the finger is cut off with a no-pour area (`fix_slivers`). Islands are removed, and orphans get a via. |
| 10 | jrbe | Lock the mounting holes | H1–H14, CN1 and CN2 are locked in the PCB. |
| 11 | jrbe | Chassis ring on top / bottom only | A 2.5 mm CHASSIS ring on F.Cu and B.Cu along the edge, joined to the plated mounting holes. Parts stay 2.5 mm from the edge. Inner layers have no ring. |
| 12 | jrbe | Crystals (showstopper): no traces under them, ground or keep-out beneath, short paths, no vias to the load caps, place them first | Crystals and load caps are placed before anything else in the MCU group. MCU pin → crystal → load cap are routed first, on F.Cu only, with no vias. Under each crystal: a B.Cu keep-out (no tracks or vias) and a keep-out between its pads on F.Cu. In2 has a **GND island** under each crystal and its caps, so there is ground on both inner layers (`crystal_copper`). |
| 13 | jrbe | Rotate / centre the STM32 so the crystals sit apart and the traces fan out | The MCU moved from the bottom edge to the board centre, (145, 54). All four rotations were tried and the one with the shortest ratsnest kept: 90°, with the oscillator pins toward the bottom. Y1 and Y2 sit on different sides of the corner. |
| 14 | jrbe | Place critical parts first: decaps, oscillators, high-integrity signals | Placement order is: anchors, then each IC followed straight away by its own decaps and load parts, then everything else. Decaps may sit 0.8 mm from their IC, where the general spacing is 1.5 mm. |
| 15 | jrbe | Contactor drivers: thin traces, far from the connector, ground bounce | U20–U22 sit **next to CN1**, just outside the 10 mm hand-solder zone, with their tabs (drain = output) facing the connector. Outputs use a 1.2 mm class. Each tab has copper on F and B extended toward CN1 with a row of vias. Each source pin has a GND copper area with vias straight into In1, so the coil return current stays in the strip between the drivers and CN1's ground pins, away from the logic. |
| 16 | jrbe | More vias on source / tab (~0.8 A per via) | 42 vias placed on the three drivers' tabs and sources, about 14 per driver, before routing. The router adds more on the output nets. |
| 17 | jrbe | High-current parts near the connectors | Power entry (TVS1, Q1, D1, buck, LDO) is at the top left, beside CN1's VBAT row (M). Contactor drivers are beside CN1 rows B/E. The current-sense front end is beside CN2. |
| 18 | jrbe | TVS first in line on the input | TVS1 is anchored as the first part on VBAT, right beside CN1's M row, before Q1. |
| 19 | jrbe | Buck reference layout as copper areas, not thin ("pink") traces | The AP63205 block keeps its datasheet geometry. Its VIN, GND, SW and +5V buses (≥ 1 mm) are now **copper zones**. Locked tracks underneath keep the autorouter out. Only the pin necks and the FB sense line are traces. |
| 20 | jrbe | ESP32: ≥ 100 µF bulk plus decoupling at its pin; it browns out on thin traces | U30 now has **its own LDO (U31, LD1117S33)** from +5V, a **100 µF / 16 V** bulk cap (C124, Nichicon UWT1C101MCL1GB, LCSC C340722), and 10 µF + 100 nF at the module's 3V3 pin. All of them sit on the ESP_3V3 In2 island. |
| 21 | jrbe | The 800 mA LDO vs the ESP's 650 mA surges | Same fix: U2 now supplies only the MCU and analog parts, and U31 the ESP32. |
| 22 | jrbe | Move In2 traces to the bottom | In2 has no traces at all now. |
| 23 | Jack, jrbe | Schematics unreadable; they should show the circuit flow; readable labels; decaps drawn next to their IC (multi-unit too); in/out label types; a clean buck schematic | New generator (§3): parts are placed by hand in signal-flow order, local nets are drawn as wires, supplies are power symbols, and there is one input/output-shaped global label per sheet for each inter-sheet net. |
| 24 | jrbe | "Netlist seems borked" | Not reproduced. Every pin's net in the KiCad export is checked against the design table on every run (`verify` in `gen_sch.py`). v0.1 connected every pin through a global label, which looks broken in KiCad's net highlighting, because nothing is drawn. If a specific net looked wrong, please name it. |
| 25 | jrbe | Buck rated 18 V | See §4.1. The AP63205 is rated 32 V in, so the part stays. |
| 26 | jrbe | D1 is unnecessary | See §4.2. D1 stays. |

## 2. Circuit change

Only the ESP32 supply changed (`sch_design.py`, WiFi sheet):

| v0.1 | v0.2a |
|----|----|
| ESP_3V3 from +3V3 (U2) through L30, 10 µH 0805 | U31 LD1117S33TR (LCSC C86781), its own 3.3 V LDO from +5V |
| C120 10 µF, C121 100 nF | C124 100 µF / 16 V aluminium (C340722), plus C120 10 µF and C121 100 nF at U30 pin 2; C123 10 µF at U31's input |

- L30 is gone.
- R130 / C122 (EN RC) and J4 are unchanged.
- The MCU-side 3.3 V (U2) no longer carries the radio's 0.5–0.65 A transmit bursts.
- U31 dissipates about 1.7 V × the ESP current: roughly 0.25 W average, and about 1.1 W for the length of a burst. That is within a SOT-223 on its plane island.

## 3. Schematic drawing (new `tools/gen_sch.py` + `tools/sch_layout.py`)

- `sch_layout.py` places every symbol on each sheet by hand, in signal-flow order, mostly left to right:
  - power: battery in, then 12 V, buck, LDO;
  - analog: sensor in, then filter, buffer, ADC;
  - gate: status filter, then AND, then the trip NAND.
- Decaps sit next to their IC. On multi-unit parts (LM2901, MCP6292, 74HC21, SN74ACT10), they sit next to the power unit.
- An orthogonal grid router wires every local net. It avoids symbol bodies and text, and allows crossings but never a corner or an end on another net's wire. T-connections are split and get a junction dot.
- Supply rails are power symbols. The board's own rails have project power symbols: VBAT, VCC_12V, +5V_A, +12V_GATE, VDDA, ESP_3V3. On the power sheet, the main power path is drawn with wires instead, so the regulator chain reads as a circuit.
- Each inter-sheet net has one global label per sheet, shaped *output* on the sheet that drives it and *input* elsewhere (`SOURCE` in `sch_layout.py`).
- CN1 and CN2 keep a label on every pin, the usual style for a connector. The CN1 symbol is wider, so its two columns of pin names no longer overlap.
- The netlist check is unchanged: the generator fails unless every pin is on its design net.
- Nets drawn only as wires get KiCad's automatic names in the schematic. The PCB keeps the design table's names, matched pin by pin (`read_netlist` in `gen_layout.py`).

## 4. Points where v0.2a does not follow the review

These are offered for discussion, with sources.

### 4.1 AP63205 input rating: 32 V, not 18 V

The AP63205 datasheet gives **VIN 3.8 V to 32 V**, with an absolute maximum of **35 V DC** and **40 V for 400 ms**. See the [AP63200/AP63201/AP63203/AP63205 datasheet](https://www.mouser.com/datasheet/2/115/AP63200_AP63201_AP63203_AP63205-1525010.pdf) and [Diodes' product page](https://www.diodes.com/part/AP63205). The part stays.

Two things are worth discussing:

- **Margin to the TVS clamp.** TVS1 (SMBJ26CA) clamps at about 42 V at its full 14 A rating, and lower at small surge currents. Behind it are Q1 and D1, and the buck's 400 ms absolute maximum is 40 V. jrbe's ~85 V example is the contactor coil's flyback. That spike appears on the driver's drain (the CN1 output pin), where the BTS133TC's own clamp absorbs it. It does not appear on VBAT, which feeds the logic supply. If the forum wants more margin on VBAT, the next step is a buck rated 40–60 V in. That is a part change for the owner to decide; v0.2a does not make it.
- **Automotive grade.** The AP63205Q (AEC-Q100 Grade 1) has the same voltage ratings and pinout, and uses a 4.7 µH inductor. It isn't stocked at JLCPCB, so it adds no voltage headroom.
  - If an adjustable automotive part is wanted, the **AP63200Q / AP63201Q** works: 500 kHz, VFB 0.8 V. For 5 V, the datasheet values are R1 158 kΩ and R2 30.1 kΩ, a 10 µH inductor, 2 × 22 µF output and 100 pF feed-forward.
  - It would need two resistors and a capacitor added to the block. It is listed here as an alternative, not fitted.

### 4.2 D1 (reverse-polarity diode) stays

The BTS6143D offers "reverse battery protection by self turn on": with the battery reversed, the switch turns itself on to limit its own dissipation. That means **the reversed voltage is passed to the load**, and its operating range is 5.5–38 V. See the [BTS6143D datasheet](https://datasheetspdf.com/amp-datasheet/364505/BTS6143D.html).

Without D1, a reversed battery would put about −12 V on VCC_12V and everything behind it, including the buck, the exciter op-amp and Q2. D1 (SS54) blocks it, at the cost of about 0.5 V drop and about 0.5 W at 1 A.

## 5. Results

See `04-layout.md` for:
- the stackup and plane map;
- routing statistics and DRC;
- the placement table;
- the decoupling distances.
