# Bolt Logic Board — Schematic Design (v0.1)

Block-by-block design of the replacement logic board, derived from a full read of the
Tesla LDU V6 schematic (`Tesla-Drive-Unit/V6/Tesla_V6 - Schematic.pdf`), the
`stm32-sine` hardware definitions, and the Bolt interface work in
`02-mechanical.md` / Phase 1. This document is the input to KiCad schematic capture.

Legend: **REUSE** = V6 circuit unchanged · **ADAPT** = V6 circuit, new values/hookup ·
**NEW** = no V6 equivalent · **DROP** = V6 circuit not needed.

## 1. Corrections to the Phase 2 architecture (from reading the V6 in detail)

1. **The V6 has no resolver interface.** Its position input is a quadrature encoder
   (ENC_A/B on PA6/PA7 = TIM3 encoder mode, ENC_Z on PD2) because the Tesla LDU motor
   uses an encoder. The 74HCT4052 is the **temperature** mux. The Bolt resolver front
   end is new design work (section 4.8).
2. **Current-sense front end:** Tesla's sensors output PWM; the V6 converts it with a
   Schmitt buffer + 2nd-order filter, then divides by 2k7/4k7 (k = 0.635). The Bolt's
   HC5FW700 sensors are analog, so the filter becomes a buffer. Keeping the same
   divider gives **k = 0.635 → `il1gain`/`il2gain` ≈ 2.25 digits/A** (supersedes 2.37).
3. **The 74HCT573 is not a fault gate** — its OE is grounded. Hardware shutdown is the
   CD74HC30 NAND → **PB12 = TIM1 break input** (section 4.4).

## 2. Block summary

| Block | Status | Notes |
|----|----|----|
| Power: input, 5 V buck, 3.3 V LDO | ADAPT | add ignition-switched input; buck set to 5.0 V |
| Analog 5 V (sensor rail, CN2 28/29) | NEW | dedicated LDO |
| Gate-board 12 V supply switch | NEW | MCU-controlled high-side switch |
| −5 V (LM2664) | DROP | only fed Tesla's HV-sense board |
| MCU core, crystals, SWD | REUSE | STM32F103RBT6 |
| PWM level shift (74HCT573 + 10 k pull-downs) | REUSE | → CN2 11–16 |
| Fault / break logic (NAND → BKIN) | ADAPT | Bolt status lines; HC → HCT |
| Overcurrent window comparators | ADAPT | add 3rd phase |
| Current-sense front end | ADAPT | buffer instead of PWM filter |
| Current-sensor clock (74LVC2G17 etc.) | DROP | Tesla-only |
| Temperature mux (74HCT4052) | ADAPT | Bolt NTCs, new pull-ups |
| DC-bus voltage input | ADAPT | from CN2 pin 18 instead of HV-sense board |
| Resolver / encoder front end | NEW | software resolver; encoder by assembly option |
| Vehicle digital inputs, throttle inputs | REUSE | |
| Low-side outputs (BTS133) | REUSE + 1 | contactor, precharge, + pump/fan |
| CAN (SN65HVD234) | REUSE | |
| ESP32 WiFi | REUSE | |
| DC-bus discharge control | DROP (pending) | Tesla HV-sense board feature |

## 3. STM32F103RBT6 pin map — HW_BOLT

FT = 5 V-tolerant. Non-FT pins never see 5 V signals directly.

| Pin | Port | V6 net | Bolt net | Notes |
|----|----|----|----|----|
| 14 | PA0 | UVLO_IN | **GATE_OK** | AND of CN2 7–10 via 10 k/20 k divider (non-FT) |
| 15 | PA1 | OCUR_IN | OCUR_OK | comparator node, pulled up to **3.3 V** (non-FT) |
| 16 | PA2 | BRAKE_IN | BRAKE_IN | |
| 17 | PA3 | MPROT_IN | MPROT_IN | |
| 20 | PA4 | FWD_IN | FWD_IN | |
| 21 | PA5 | IL1 | **IL1 = phase U** (CN2 24) | |
| 22 | PA6 | ENC_A | **RES_SIN** / ENC_A | assembly option |
| 23 | PA7 | ENC_B | **RES_COS** / ENC_B | assembly option |
| 41–43 | PA8–10 | PWM1–3_P | PWM U/V/W high | → 573 → CN2 11/13/15 |
| 44/45 | PA11/12 | CAN RX/TX | CAN RX/TX | |
| 46/49 | PA13/14 | SWDIO/SWCLK | SWDIO/SWCLK | |
| 50 | PA15 | — | **GATE_PWR_EN** | NEW; 10 k pull-down (gate supply off by default) |
| 26 | PB0 | IL2 | **IL2 = phase V** (CN2 27) | |
| 27 | PB1 | PRECHARGE_OUT | PRECHARGE_OUT | |
| 28 | PB2 | BOOT1 | BOOT1 (4k7 to GND) | |
| 55 | PB3 | — | NC | must stay NC (firmware mini-mainboard detect uses PB3↔PC10) |
| 56 | PB4 | — | **BOARD_ID** | NEW; 10 k to GND, HW_BOLT detection |
| 57 | PB5 | CRUISE_IN | CRUISE_IN | |
| 58 | PB6 | START_IN | START_IN | |
| 59 | PB7 | OCURLIM_NEG | OCURLIM_NEG | TIM4 PWM → 10 k/1 µF |
| 61 | PB8 | OCURLIM_POS | OCURLIM_POS | TIM4 PWM → 10 k/1 µF |
| 62 | PB9 | USER_PWM | **PUMP_OUT** | 3rd BTS133 (firmware remap of fan_out) |
| 29/30 | PB10/11 | USART TX/RX | USART TX/RX | ESP32 |
| 33 | PB12 | PWM_INHIBIT | PWM_INHIBIT | **TIM1_BKIN** |
| 34–36 | PB13–15 | PWM1–3_N | PWM U/V/W low | → 573 → CN2 12/14/16 |
| 8 | PC0 | REGEN | THROTTLE2 | |
| 9 | PC1 | THROTTLE | THROTTLE1 | |
| 10 | PC2 | TMPM | TMPM | mux side 1 (motor temps) |
| 11 | PC3 | UDC | UDC | from CN2 pin 18 (section 4.7) |
| 24 | PC4 | TMPHS | TMPHS | mux side 2 (module NTC U/V/W) |
| 25 | PC5 | SPEED_OUT | SPEED_OUT | |
| 37 | PC6 | REV_IN | REV_IN | |
| 38 | PC7 | EMCYSTOP_IN | EMCYSTOP_IN | |
| 39 | PC8 | BMS_IN | MUX_S1 (temp1_out) | as HW_TESLA |
| 40 | PC9 | DESAT | **GATE_FLT** (CN2 22) | FT; 1 k series |
| 51 | PC10 | ERR_OUT | MUX_S0 (temp0_out) | as HW_TESLA |
| 52 | PC11 | VTG_OUT | VTG_OUT | spare |
| 53 | PC12 | LED_OUT | LED_OUT | |
| 2 | PC13 | DCSW_OUT | DCSW_OUT | main contactor |
| 3/4 | PC14/15 | 32.768 kHz | 32.768 kHz | |
| 5/6 | PD0/1 | 8 MHz | 8 MHz | |
| 54 | PD2 | ENC_Z | **RES_EXC** / ENC_Z | assembly option |

## 4. Blocks

### 4.1 Power (ADAPT + NEW)

```
CN1 M1/M4 (Batt+) ─┬─ [Q1 high-side switch, EN = IGN (CN1 L3)] ─ VBAT_SW
                   │      → SS54B ─ VCC_12V ─┬─ RT8259 buck ─ +5V (digital)
                   │                         │     └─ LD1117-3.3 ─ +3V3
                   │                         ├─ TPS7B6950-Q1 LDO ─ +5V_A (CN2 28/29)
                   │                         └─ [Q2 high-side switch, EN = PA15] ─ +12V_GATE (CN2 31/33/35/37)
CN1 L3 (IGN) ─ 124 k ─ CN2 36/38   (replicates the OEM ~125 kΩ ignition sense)
```

- **Q1, logic power switch (NEW):** smart high-side switch (Infineon PROFET+ class,
  e.g. BTS5045-1EJA; part TBD) enabled by ignition, so the board draws no quiescent
  current with ignition off. The OEM board has two DPAK parts in the same corner —
  likely the same arrangement.
- **Buck:** RT8259 (V6 JLC part). Change the feedback top resistor to **52.3 kΩ**
  (Vout = 0.8 × (1 + 52.3/10) = **4.98 V**). The V6's 56 kΩ gives 5.28 V. The
  gate board's 1ED020I12 VCC1 is specified to 5.5 V max, so 5.0 V leaves margin.
  Load: our board ~250 mA (ESP32 peaks), gate board digital ~60 mA (6× 1ED020 VCC1,
  74HC365, 2× 74AHC08).
- **+5V_A (NEW):** dedicated 5 V LDO from VCC_12V (TPS7B6950-Q1, 150 mA, SOT-223)
  for the three HC5FW sensors (~60–75 mA) via CN2 28/29. The sensors are ratiometric
  to this rail and the STM32 ADC reference doesn't track it, so it needs to be
  accurate and quiet. Dissipation ≈ (13.8 − 5) × 0.075 ≈ 0.7 W.
- **Q2, gate-board supply switch (NEW):** high-side switch from VCC_12V to CN2
  31/33/35/37, enabled by **PA15 (GATE_PWR_EN, 10 k pull-down)**. This gives a hard
  safe state: firmware enables gate power only after init. With the switch off, the
  isolated gate supplies collapse and the 1ED020I12 UVLO holds every IGBT off.
- **−5 V (LM2664): DROP.**

### 4.2 MCU core (REUSE)
STM32F103RBT6; 8 MHz crystal (22 pF), 32.768 kHz crystal (10 pF); VDDA through 10 µH;
decoupling as V6; BOOT0 10 k to GND; BOOT1 4k7 to GND; NRST 100 nF; SWD 3-pin header;
power LED (470 Ω) and status LED on PC12 (1 kΩ). **New:** PB4 10 k to GND (board ID),
PA15 10 k to GND (gate power enable default off), PB3 left unconnected.

### 4.3 PWM level shift (REUSE)
74HCT573 at 5 V, OE = GND, LE = 5 V (transparent buffer). 10 kΩ pull-downs (RN1/RN2)
on all six inputs hold the gates off while the MCU is in reset. Output mapping:

| MCU | TIM1 | 573 in → out | CN2 | IGBT |
|----|----|----|----|----|
| PA8 | CH1 | D → Q | 11 | U high |
| PB13 | CH1N | D → Q | 12 | U low |
| PA9 | CH2 | D → Q | 13 | V high |
| PB14 | CH2N | D → Q | 14 | V low |
| PA10 | CH3 | D → Q | 15 | W high |
| PB15 | CH3N | D → Q | 16 | W low |

The gate board's own HC365 has its OEs grounded and there's no interlock, so dead time
is firmware's job (TIM1 dead-time generator).

### 4.4 Fault / break logic (ADAPT)
8-input NAND **CD74HCT30** (HCT so 3.3 V-level inputs are valid) at 5 V; output →
**PWM_INHIBIT → PB12 (TIM1_BKIN)**. Each status input gets the V6's 560 Ω + 10 nF
filter, plus a **100 kΩ pull-down** so a missing or unplugged gate board reads as a fault.

| NAND input | Signal | Source | Idle (OK) |
|----|----|----|----|
| A | GATE_FLT | CN2 22 (all FLT + RDY wire-OR, OD, 20 k from gate board) | high |
| B–E | HEALTH1–4 | CN2 7, 8, 9, 10 (AHC08 push-pull) | high |
| F | OCUR_OK | overcurrent comparators (4.5) | high |
| G, H | — | tied to +5 V | high |

Any input low → PWM_INHIBIT high → TIM1 break disables all six outputs in hardware.
No pull-ups on CN2 22 or 7–10 on our side; the gate board defines those levels.
**Diagnostics:** GATE_FLT → PC9 (FT) through 1 kΩ; HEALTH1–4 → 74HC21 4-input AND →
GATE_OK → 10 k/20 k divider → PA0.

### 4.5 Overcurrent window (ADAPT)
2× LM2901 quad comparators, open-collector outputs wired together, pull-up **10 k to
+3V3** (the V6 pulls to 5 V into non-FT PA1). Thresholds OCURLIM_POS/NEG from PB8/PB7
via 10 k + 1 µF (REUSE). Six comparators: IL1, IL2, and **IW** (new third phase), each
against the + and − thresholds. Node → PA1 (OCUR_OK) and NAND input F.

### 4.6 Current-sense front end (ADAPT)
Per phase (U, V, W):
`CN2 pin → 1 kΩ + 4.7 nF (fc ≈ 34 kHz) → MCP6292 follower (5 V) → 2k7 / 4k7 → ADC`
(+ 1 nF at the ADC pin, ~94 kHz with the divider's 1.7 kΩ source).
- k = 4.7/7.4 = 0.635: sensor 0.5–4.5 V → 0.32–2.86 V at ADC; 0 A → 1.59 V.
- **il1gain/il2gain = 0.00286 × 0.635 × 4096/3.3 ≈ 2.25 digits/A.**
- U (CN2 24) → IL1/PA5; V (CN2 27) → IL2/PB0; W (CN2 26) → overcurrent only (no free
  ADC pin; firmware uses two phases).
- 2× MCP6292 (4 channels, 1 spare).

### 4.7 DC-bus voltage (ADAPT, pending confirmation)
Assumed: **CN2 pin 18 = DC-bus voltage** (TLE2022A output on the gate board, powered
from the 12 V gate rail, so it can't exceed ~13 V even on a 14 V battery).
`CN2 18 → 33 kΩ / 10 kΩ divider → BAT54S clamp to 3.3 V/GND → 3k3 + 1 nF (REUSE) →
UDC/PC3`. 13 V → 3.0 V at the ADC, so the full possible swing is safe. If the real
range is 0–5 V, that still leaves ~1,400 counts of range — adequate for bus
monitoring; the divider can be retuned once the range is known.
**Needed before HV operation:** the transfer function (pin-18 volts per bus volt) to set
firmware `udcgain`. Bench method: OEM logic + gate boards on 12 V, a current-limited
supply on the DC link at 0/12/24/48 V, record pin 18.
**CN2 pin 20** (TLE2022A ch-A input): the OEM held it at ~0 V → 10 kΩ to GND + test
point (DNP-able).

### 4.8 Position sensor front end (NEW) — software resolver, encoder by assembly option

**Decision (confirmed by owner):** firmware-native **RESOLVER** mode (exciter square wave on PD2, sin/cos
sampled on PA6/PA7). It needs no extra silicon in the signal path, and the same input
amplifiers also serve **SINCOS** Hall encoders. Incremental **AB(Z) encoders** use the
same MCU pins via 0 Ω assembly options. (Alternative kept on file: an AD2S1205 RDC,
which the firmware's SPI mode can read — same chip family as the OEM board.)

Exciter (f = PWM frequency / 2, e.g. 4.4 kHz at 8.8 kHz PWM):
`PD2 → 3-pole RC/Sallen-Key low-pass (≈ f_exc) → bridge power amplifier from VCC_12V
(candidate TCA0372 dual 1 A power op-amp) → series DC-block → CN1 B2 (EXC+) / B1 (EXC−)`
- Bridge drive gives up to ~20 Vpp across the primary from 12 V; gain is
  resistor-set so the amplitude can be matched to the resolver.
- Firmware assumes a ~305° total phase delay (filter + amp + resolver), tunable via
  `resolverSampleDelay`.

Sin/cos receivers (×2):
`CN1 C2/C1 (S1/S3, sin), D2/D1 (S2/S4, cos) → RC + TVS → MCP6292 differential amp,
gain set by resistors, output biased at 1.65 V (buffered divider from +3V3) →
100 Ω + 1 nF → PA6 (sin) / PA7 (cos)`
- Target ≈ 2.4 Vpp at the ADC, centered at 1.65 V.
- Encoder option: depopulate the amplifier output 0 Ω links, populate the
  encoder-input 10 k + 1 nF links (REUSE V6 values) from dedicated encoder pins;
  PD2 becomes the Z input.

### 4.9 Temperature mux (ADAPT)
74HCT4052 at 5 V; S0 = PC10, S1 = PC8 (as HW_TESLA).

| Mux | Ch | Signal | Source | Pull-up |
|----|----|----|----|----|
| 2 → TMPHS (PC4) | Y0 | NTC U | CN2 17 | **4.7 kΩ to +3V3**, 1 µF |
| | Y1 | NTC V | CN2 19 | 4.7 kΩ to +3V3, 1 µF |
| | Y2 | NTC W | CN2 21 | 4.7 kΩ to +3V3, 1 µF |
| | Y3 | GND | — | |
| 1 → TMPM (PC2) | Y0 | motor temp | CN1 J1 (J2 = GND) | **2.2 kΩ to +3V3 default** (own footprint; sensor type unknown) |
| | Y1 | aux temp | aux header (4.13) | 2.2 kΩ to +3V3 |
| | Y2, Y3 | spare | | |

Pulling up to 3.3 V (not the V6's 5 V) keeps an open or cold NTC within the ADC
range and makes the reading ratiometric to the ADC reference. Module NTC: R25 =
5.0 kΩ, B25/100 = 3433 K; at 25 °C → 1.70 V, at 100 °C → 0.31 V.

### 4.10 Vehicle inputs (REUSE)
Digital (12 V): 4k7 / 1k5 divider + 1 µF → FWD, REV, START, BRAKE, CRUISE (+ EMCYSTOP,
MPROT, BMS as V6). Throttle (5 V pot): 10 k / 10 k + 1 µF → PC1, PC0. Pedal 5 V supply
from +5V through a 50 mA polyfuse.

### 4.11 Outputs (REUSE + 1)
BTS133TC low-side switches: DCSW_OUT (PC13) → main contactor, PRECHARGE_OUT (PB1) →
precharge, **PUMP_OUT (PB9) → pump/fan (new 3rd channel)**.

### 4.12 CAN, ESP32, programming (REUSE)
SN65HVD234 at 3.3 V on PA11/PA12, 120 Ω termination (0 Ω link to make it optional).
ESP32-WROOM-32 on PB10/PB11 with its 6-pin programming header. SWD 3-pin header.

### 4.13 Auxiliary I/O header (NEW)
On-board 2×6, 2.54 mm header for I/O that doesn't fit CN1 without using reserved OEM
positions: AUX_TEMP (mux 1Y1, 2.2 k pull-up), EMCYSTOP_IN, MPROT_IN, BMS_IN
(12 V-tolerant, same 4k7/1k5 dividers as the other inputs), VTG_OUT (3.3 V logic,
spare), +5V (polyfused), +12V (switched VBAT, polyfused), GND ×3, plus 2 spare.

## 5. CN2 (internal, to gate board) net assignment

Part: Samtec SSW-120-01-T-D-LL (2×20, 2.54 mm socket strip, back side).

| CN2 | Net | | CN2 | Net |
|----|----|----|----|----|
| 1, 2, 5, 6, 23, 25, 30, 32, 34, 39, 40 | GND | | 17 / 19 / 21 | NTC_U / NTC_V / NTC_W |
| 3, 4 | +5V (digital) | | 18 | GB_UDC (→ 4.7) |
| 7, 8, 9, 10 | HEALTH1–4 | | 20 | GB_AUX (test point) |
| 11–16 | PWM_UH, UL, VH, VL, WH, WL | | 22 | GATE_FLT |
| 24 / 27 / 26 | ISNS_U / ISNS_V / ISNS_W | | 28, 29 | +5V_A |
| 31, 33, 35, 37 | +12V_GATE | | 36, 38 | IGN_SENSE (124 k from IGN) |

## 6. CN1 (vehicle) pin assignment — approved principle

Keep every OEM function a conversion uses in its **OEM position** (power, ignition,
resolver, motor temp, CAN, HVIL) so a Bolt drive-unit harness mates directly.
**Reserve (leave unconnected) every remaining OEM-only position** for a future
OEM-compatible revision — aux pump, transmission fluid temp, the second/third CAN
buses, IMS supplies, wake. Conversion I/O uses the 12 unused positions plus the
transmission-range-switch positions.

| Pos | OEM function | Bolt-board function |
|----|----|----|
| M1, M4 | Battery + | **Battery +** (OEM) |
| K2 | Ground | **Ground** (OEM) |
| L3 | Run/crank ignition | **Ignition** (OEM) |
| B2 / B1 | Resolver excitation + / − | **EXC+ / EXC−** (OEM) |
| C2 / C1 | Position sensor 1 / 3 | **SIN+ / SIN−** (OEM) |
| D2 / D1 | Position sensor 2 / 4 | **COS+ / COS−** (OEM) |
| J1 / J2 | Motor temp signal / ref | **Motor temp** (OEM) |
| E4 / E3, F4 / F3 | HS-GMLAN 1 +/− (daisy chain) | **CAN H / L** (OEM, both pairs) |
| G2 / G1 | HVIL signal / ref | **HVIL** (OEM) |
| B4, C3, C4, D3, D4 | Trans range switch A/B/P/C/S | **FWD, REV, BRAKE, START, CRUISE** |
| A1, A2 | — | **THROTTLE1, THROTTLE2** |
| A3, A4 | — | **Pedal 5 V, pedal GND** |
| E1, E2, B3 | — | **MAIN CONTACTOR, PRECHARGE, PUMP/FAN** (low-side outputs) |
| K1, K3, K4 | — | **ENC_A, ENC_B, ENC_Z** (encoder option) |
| L2, M3 | — | **Encoder 5 V, encoder GND** |
| F1, F2 | Aux pump control / feedback | **reserved — NC** |
| H1, H2 | Trans fluid temp | **reserved — NC** |
| G3/G4, H3/H4, J3/J4 | HS-GMLAN 3 and 2 | **reserved — NC** |
| L1, L4, M2 | IMS supplies, accessory wake | **reserved — NC** |

If a future revision also needs the stock range switch, the five drive inputs move to
the aux header (4.13).

## 7. Firmware changes (stm32-sine fork) implied by this design

1. `HW_BOLT` enum value; `detect_hw()` checks the PB4 board-ID strap **first**.
2. `io_setup()` HW_BOLT case: temp mux on PC10/PC8 (as HW_TESLA); `fan_out` → PB9;
   `err_out` → unused; new `gatepwr_out` PA15 (enable after init); new `gateok_in` PA0
   and `gateflt_in` PC9 with error messages.
3. Defaults: `il1gain`/`il2gain` ≈ 2.25 (sign at commissioning); `udcgain` from 4.7.
4. Temperature curves: Infineon module NTC (5 kΩ, B 3433) on 4.7 kΩ to 3.3 V; Bolt
   motor sensor (TBD).
5. Resolver: verify exciter frequency/amplitude and `resolverSampleDelay` on the
   bench.

## 8. Open questions

| # | Item | Status |
|----|----|----|
| 1 | CN1 pinout | **resolved** — section 6 (OEM-only positions reserved) |
| 2 | Bolt motor temp sensor type | open — 2.2 k default pull-up, own footprint |
| 3 | CN2 pin 18 | **assumed DC-bus**; transfer function needed before HV (bench test) |
| 4 | Resolver approach | **resolved** — software resolver |
| 5 | Parts to select: Q1/Q2 high-side switches, exciter power amp, polyfuses | open |
| 6 | CN2 insulator height vs. OEM | open |
