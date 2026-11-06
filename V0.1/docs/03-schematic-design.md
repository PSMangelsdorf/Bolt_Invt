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
   CD74HC30 NAND → **PB12 = TIM1 break input** (section 4.4). This board uses a SN74ACT10 for it.

## 2. Block summary

| Block | Status | Notes |
|----|----|----|
| Power: input, 5 V buck, 3.3 V LDO | ADAPT | ignition-switched input; AP63205 fixed 5.0 V buck |
| Analog 5 V (sensor rail, CN2 28/29) | NEW | ferrite-filtered branch of the buck |
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
| 17 | PA3 | MPROT_IN | MPROT_IN | no input on this board: 10 k pull-up holds it at OK |
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
| 25 | PC5 | SPEED_OUT | NC | |
| 37 | PC6 | REV_IN | REV_IN | |
| 38 | PC7 | EMCYSTOP_IN | EMCYSTOP_IN | no input on this board: 10 k pull-up holds it at OK |
| 39 | PC8 | BMS_IN | MUX_S1 (temp1_out) | as HW_TESLA |
| 40 | PC9 | DESAT | **GATE_FLT** (CN2 22) | FT; 1 k series |
| 51 | PC10 | ERR_OUT | MUX_S0 (temp0_out) | as HW_TESLA |
| 52 | PC11 | VTG_OUT | NC | |
| 53 | PC12 | LED_OUT | LED_OUT | |
| 2 | PC13 | DCSW_OUT | DCSW_OUT | main contactor |
| 3/4 | PC14/15 | 32.768 kHz | 32.768 kHz | |
| 5/6 | PD0/1 | 8 MHz | 8 MHz | |
| 54 | PD2 | ENC_Z | **RES_EXC** / ENC_Z | assembly option |

## 4. Blocks

### 4.1 Power (ADAPT + NEW)

```
CN1 M1/M4 (Batt+) ─ TVS1 SMBJ26CA
   └─ Q1 BTS6143D (IN ← Q3 2N7002 ← IGN via 10k/6.8k) ─ VBAT_SW ─ D1 SS54 ─ VCC_12V
         VCC_12V ─┬─ U1 AP63205WU buck (fixed 5.0 V) ─ +5V ─┬─ U2 LD1117-3.3 ─ +3V3
                  │                                          └─ FB1 ferrite ─ +5V_A (CN2 28/29)
                  └─ Q2 BTS6143D (IN ← Q4 2N7002 ← PA15 GATE_PWR_EN, 10k pull-down) ─ +12V_GATE (CN2 31/33/35/37)
CN1 L3 (IGN) ─ 124 kΩ ─ CN2 36/38   (replicates the OEM ~125 kΩ ignition sense)
```

- **Q1 / Q2: Infineon BTS6143D** smart high-side switches (10 mΩ, 8 A nominal, 5.5–38 V,
  PG-TO252-5-11). The owner chose it over the BTS443P because JLCPCB stocks it. It has the
  same pinout (OUT 1/5, IN 2, Vbb 3 = tab, IS 4) and the same ground-referenced input, so the
  BTS443P symbol and footprint are kept.
  Q1 is enabled by ignition, so the board draws nothing with ignition off. Q2 is
  enabled by firmware after init; with it off the isolated gate supplies collapse and
  the 1ED020I12 UVLO holds every IGBT off. Both IS (current-sense) pins have 1 kΩ to
  GND. The OEM board has two DPAK parts in the same corner.
- **Input drive (fixed in v0.1, owner-approved).** Neither the BTS443P nor the BTS6143D has a
  GND pin. Each switches on when IN is pulled to ground. For the BTS6143D the input switch
  has to sink up to 2.2 mA, and under 30 µA keeps it off (Infineon datasheets, pin table and
  input specs). The first
  schematic drove IN like a logic input. Q1's IN went to GND through 6.8 k, which left it
  always on, and Q2's IN went to PA15 through 1 k, which the MCU could never switch off.
  Each now has a 2N7002 (Q3, Q4) from IN to GND:
  - **Q3** gate from the IGN divider (10 k / 6.8 k: about 4.9 V at 12 V IGN, 6.5 V at 16 V).
  - **Q4** gate from PA15 through R4 (1 k). The existing R5 (10 k to GND) holds it below the
    2N7002's 1 V minimum threshold while PA15 is still JTDI with its internal 30–50 k
    pull-up at reset (≤ 0.8 V).
  Polarity is unchanged for the firmware (PA15 high = gate power on), and the board
  detection still sees PA15 pulled low.
- **Buck: AP63205WU** (fixed 5.0 V, 2 A, 3.8–32 V input, synchronous), replacing the
  V6's RT8259 (~24 V input, 5.28 V with the V6 divider). The 32 V rating suits an
  automotive 12 V rail, and the exact 5.0 V keeps the gate board's 1ED020 VCC1 inside
  its 5.5 V limit. 6.8 µH, 2× 22 µF out.
- **+5V_A** (current sensors): a ferrite-filtered branch of the buck output. The
  automotive LDO candidate (TPS7B6950-Q1) is only ±3%, and the sensors are ratiometric
  to this rail while the ADC reference doesn't track it, so the buck's tighter output
  is the more accurate source; the ferrite keeps switching noise out.
- **3.3 V:** LD1117S33 from +5V (REUSE).
- **TVS1** SMBJ26CA (Littelfuse) on VBAT; **−5 V (LM2664): DROP.**
- Mounting holes H1–H12 (plated) → CHASSIS → 0 Ω → GND (assembly option); H13/H14 NPTH.

### 4.2 MCU core (REUSE)
STM32F103RBT6; 8 MHz crystal (22 pF), 32.768 kHz crystal (10 pF); VDDA through 10 µH;
decoupling as V6; BOOT0 10 k to GND; BOOT1 4k7 to GND; NRST 100 nF; SWD header J1 (5-pin: 3.3 V, SWDIO, SWCLK, NRST, GND);
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
3-input NAND, one gate of a **SN74ACT10** (U6, TI) at 5 V. Its TTL-level inputs (HCT or
ACT, VIH 2.0 V) let the 3.3 V OCUR_OK level read as high. The 74HCT10D first chosen went out
of stock at JLCPCB; the ACT10 has the same pinout. Its output → **PWM_INHIBIT → PB12 (TIM1_BKIN)**. Each status
input gets the V6's 560 Ω + 10 nF filter, plus a **100 kΩ pull-down** so a missing or
unplugged gate board reads as a fault.

| NAND input | Signal | Source | Idle (OK) |
|----|----|----|----|
| 1 | GATE_OK_5V | U5 74HC21: AND of HEALTH1–4 (CN2 7, 8, 9, 10, AHC08 push-pull) | high |
| 2 | GATE_FLT | CN2 22 (all FLT + RDY wire-OR, OD, 20 k from gate board) | high |
| 13 | OCUR_OK | overcurrent comparators (4.5) | high |

The first schematic used an 8-input CD74HCT30 that took HEALTH1–4 directly. JLCPCB
doesn't stock it, so the owner approved this equivalent. NAND(AND(HEALTH1–4), GATE_FLT,
OCUR_OK) is the same function, and a HEALTH fault now passes through U5 first, which
adds about 20 ns against the 5.6 µs input filter. U6's other two gates have their inputs
grounded.

Any input low → PWM_INHIBIT high → TIM1 break disables all six outputs in hardware.
No pull-ups on CN2 22 or 7–10 on our side; the gate board defines those levels.
**Diagnostics:** GATE_FLT → PC9 (FT) through 1 kΩ; HEALTH1–4 → 74HC21 4-input AND →
GATE_OK → 10 k/20 k divider → PA0.

### 4.5 Overcurrent window (ADAPT)
2× LM2901 quad comparators, open-collector outputs wired together, pull-up **10 k to
+3V3** (the V6 pulls to 5 V into non-FT PA1). Thresholds OCURLIM_POS/NEG from PB8/PB7
via 10 k + 1 µF (REUSE). Six comparators: IL1, IL2, and **IW** (new third phase), each
against the + and − thresholds. Node → PA1 (OCUR_OK) and NAND input 13.

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
`PD2 → 0 Ω (RES option) → RC pole (10 k/3.3 nF) → unity-gain Sallen-Key (MCP6292,
fc ≈ 5 kHz, Q ≈ 0.73) → 1 µF AC-couple → TCA0372 bridge from VCC_12V (A: non-inverting
gain 3 about VCC_12V/2; B: unity inverter about the same bias) → 10 µF DC-block +
10 Ω → CN1 B2 (EXC+) / 10 Ω → B1 (EXC−)`
- **TCA0372DW** (onsemi): dual 1 A power op-amp. Single or split supply up to 40 V,
  1.4 V/µs typical, 1.4 MHz GBW typical, and the input range includes ground (a ~20 Vpp,
  5 kHz exciter needs ~0.3 V/µs). The owner chose it over the first choice, ST's L272D,
  which JLCPCB doesn't stock. Pinout (SOIC-16W):
  - VCC 1; OUTB 2; −INB 7; +INB 8; +INA 9; −INA 10; OUTA 16;
  - GND 4/5/12/13 (also the heat path);
  - NC 3/6/11/14/15.

  This comes from the datasheet's DW pin drawing (label order) and a component-library pin
  table, which agree. The resistors are unchanged.
- Output swing is about 1.3 V from each rail at 1 A, and less at the exciter's ~100 mA.
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
| | Y1 | GND | — | |
| | Y2, Y3 | GND | — | |

Pulling up to 3.3 V (not the V6's 5 V) keeps an open or cold NTC within the ADC
range and makes the reading ratiometric to the ADC reference. Module NTC: R25 =
5.0 kΩ, B25/100 = 3433 K; at 25 °C → 1.70 V, at 100 °C → 0.31 V.

### 4.10 Vehicle inputs (REUSE)
Digital (12 V): 4k7 / 1k5 divider + 1 µF → FWD, REV, START, BRAKE, CRUISE (all on CN1).
EMCYSTOP and MPROT have no input on this board; 10 k pull-ups to 3.3 V hold both MCU pins at
"OK", so the stock firmware runs unchanged. There is no BMS input either: PC8 is the mux
select, as on the Tesla board, and a BMS signal goes over CAN. Throttle (5 V pot): 10 k / 10 k + 1 µF → PC1, PC0. Pedal 5 V supply
from +5V through a 50 mA polyfuse.

### 4.11 Outputs (REUSE + 1)
BTS133TC low-side switches: DCSW_OUT (PC13) → main contactor, PRECHARGE_OUT (PB1) →
precharge, **PUMP_OUT (PB9) → pump/fan (new 3rd channel)**. Each MCU drive line has a 10 kΩ
pull-down so contactors stay off while the MCU is in reset.

### 4.12 CAN, ESP32, programming (REUSE)
SN65HVD234 at 3.3 V on PA11/PA12, 120 Ω termination (0 Ω link to make it optional).
ESP32 WiFi exactly as the V6 (IC14): ESP32-WROOM-32E (M113EH2800PH3Q0, PCB antenna) on
PB10/PB11. Supply through a 10 µH inductor, with 100 nF on the 3.3 V side and 10 µF on the
module side. EN has 4.7 k to the module's 3.3 V and 100 nF to GND. The 6-pin programming
header (J4) is the same as the V6: IO0, GND, GND, +5 V, RX, TX. STM32 programming: SWD
header J1 (3.3 V, SWDIO, SWCLK, NRST, GND).

**Connectors (owner):** the only connections on the board are CN1, CN2 and the two
programming headers J1 and J4.

### 4.13 Auxiliary I/O header — removed

The earlier 2×6 aux header (J3) is gone; the owner wants no connectors beyond CN1, CN2 and
programming. It took with it:
- **Aux outputs:** the aux 12 V and 5 V outputs and their polyfuses (F3, F4).
- **Aux temperature:** the input and its pull-up; mux 1Y1 is now grounded.
- **Inputs:** the emergency-stop and motor-protection inputs (see 4.10).
- **HVIL:** the routing from CN1 G1/G2, which are now reserved positions (section 6).
- **Spare output:** VTG_OUT; PC11 is unconnected.

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
resolver, motor temp, CAN) so a Bolt drive-unit harness mates directly.
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
| B4, C3, C4, D3, D4 | Trans range switch A/B/P/C/S | **FWD, REV, BRAKE, START, CRUISE** |
| A1, A2 | — | **THROTTLE1, THROTTLE2** |
| A3, A4 | — | **Pedal 5 V, pedal GND** |
| E1, E2, B3 | — | **MAIN CONTACTOR, PRECHARGE, PUMP/FAN** (low-side outputs) |
| K1, K3, K4 | — | **ENC_A, ENC_B, ENC_Z** (encoder option) |
| L2, M3 | — | **Encoder 5 V, encoder GND** |
| F1, F2 | Aux pump control / feedback | **reserved — NC** |
| G2 / G1 | HVIL signal / ref | **reserved — NC** (was routed to the removed aux header) |
| H1, H2 | Trans fluid temp | **reserved — NC** |
| G3/G4, H3/H4, J3/J4 | HS-GMLAN 3 and 2 | **reserved — NC** |
| L1, L4, M2 | IMS supplies, accessory wake | **reserved — NC** |

Printable pin-by-pin comparison (OEM use vs. new use): `cn1_oem_vs_new.pdf`, generated from the
schematic design table by `hardware/bolt_logic/tools/gen_cn1_compare.py`.

If a future revision also needs the stock range switch, the five drive inputs would need
other CN1 positions; there is no other connector on this board.

## 7. Firmware changes (stm32-sine fork) implied by this design

**Status:** implemented on branch `hw-bolt` of the stm32-sine fork; see `05-firmware.md`.


1. `HW_BOLT` enum value; `detect_hw()` checks the PB4 board-ID strap **first**.
2. `io_setup()` HW_BOLT case: temp mux on PC10/PC8 (as HW_TESLA); `fan_out` → PB9;
   `err_out` → unused; new `gatepwr_out` PA15 (enable after init); new `gateok_in` PA0
   and `gateflt_in` PC9 with error messages.
3. Defaults: `il1gain`/`il2gain` ≈ 2.25 (sign at commissioning); `udcgain` from 4.7.
4. Temperature: HW_BOLT branch in `VehicleControl::GetTemps()` (the HW_TESLA branch
   hard-codes Tesla curves). Mux cycle: channel 0 → NTC U + motor temp, 1 → NTC V,
   2 → NTC W (side 1 grounded on 1–3), 3 → both sides grounded; tmphs = max(U, V, W). Curves:
   Infineon module NTC (5 kΩ, B 3433) on 4.7 kΩ to 3.3 V; motor sensor TBD (2.2 kΩ
   pull-up).
4a. Break handler (`pwmgeneration.cpp`): extend `ocur_in.Get() && hwRev == HW_TESLA`
   to HW_BOLT so a gate-board fault reports as DESAT, not overcurrent (PC9 already
   carries the combined FLT/RDY line).
5. Resolver: verify exciter frequency/amplitude and `resolverSampleDelay` on the
   bench.

## 8. Schematic capture (v0.1)

`hardware/bolt_logic/` — 7 hierarchical sheets (power, MCU, gate interface, analog,
resolver/encoder, vehicle I/O, WiFi), 249 parts, 160 nets. Generated by
`tools/gen_sch.py` from the design table `tools/sch_design.py`; every pin is
connected by a named global label, and after writing the script exports the netlist
with `kicad-cli` and checks every pin against the table (currently: exact match, no
duplicate references). PDF: `docs/bolt_logic_schematic.pdf`.

Library symbols are used wherever KiCad has an exact or pin-identical part (value
field carries the real part): 74LS573 → 74HCT573, 74LS10 → SN74ACT10, 74LS21 → 74HC21,
CD4052B → 74HCT4052, MCP6002 → MCP6292, BTS443P → BTS6143D (same pinout). Custom symbols
(`Bolt.kicad_sym`): CN1_GM48, BTS133TC, TCA0372.

### Pre-layout verification checklist (datasheet vs. symbol/footprint)

| Part | Check |
|----|----|
| **TCA0372DW** (replaces L272D) | Pinout from two agreeing sources (§4.8); glance at onsemi's DW pin drawing before ordering. |
| **BTS443P → BTS6143D** | **Checked (Infineon datasheets):** both parts share this pinout. OUT 1/5, IN 2, Vbb 3 = tab, IS 4; package PG-TO252-5-11. The KiCad TO-252-4 footprint has pads 1, 2, 4, 5 plus the tab as pin 3, which matches. IN is pulled to GND to switch on, and the drive is fixed with Q3/Q4 (§4.1). Still to confirm: the lead pitch of the footprint (1.14 mm) against Infineon's package drawing. |
| **BTS133TC** | TO-263 pad mapping (tab = D = pin 2) and that 3.3 V drive fully enhances it (V6 does this). |
| **AP63205WU** | EN tied to VIN, input/output capacitor values. Inductor: 6.8 µH (as the AP63205 EVB) kept, owner-approved. |
| **CN1** | Hole diameters (1.0 mm placeholder; rows M/L may use larger terminals). |
| **CN2** | Samtec SSW insulator height vs. the OEM part. |

## 9. Open questions

| # | Item | Status |
|----|----|----|
| 1 | CN1 pinout | **resolved** — section 6 (OEM-only positions reserved) |
| 2 | Bolt motor temp sensor type | open — 2.2 k default pull-up, own footprint |
| 3 | CN2 pin 18 | **assumed DC-bus**; transfer function needed before HV (bench test) |
| 4 | Resolver approach | **resolved** — software resolver |
| 5 | Parts: Q1/Q2 = BTS6143D, exciter = TCA0372, buck = AP63205WU, polyfuses chosen | **resolved** (verify per checklist) |
| 6 | CN2 insulator height vs. OEM | open |
