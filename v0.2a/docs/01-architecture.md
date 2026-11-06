# Bolt Inverter — Replacement Logic Board Architecture (Phase 2)

Open-source drop-in **logic board** for the LG-built Chevrolet Bolt EV traction
inverter (Infineon HybridPACK 2, FS800R07A2E3). The stock gate-driver board is
retained; this board replaces the stock logic board and runs OpenInverter firmware.

## Approach

- **EDA:** KiCad (migrated from the Tesla LDU V6 DesignSpark design, used as the
  circuit reference).
- **Hardware base:** Tesla LDU "V6" openinverter controller. In firmware terms the
  V6 is the **HW_TESLA** variant. We create a new **HW_BOLT** variant that reuses the
  V6 topology and changes only what the Bolt interface requires.
- **MCU:** STM32F103RBT6 (LQFP-64), same as V6. *Watch:* 128 KB flash is ample for
  stm32-sine; verify the FOC build fits or move to the pin-compatible RET6 (512 KB) —
  no board change either way.
- **Firmware:** fork of `stm32-sine` (sine + FOC). Position sensing kept
  motor-agnostic: RESOLVER (Bolt), SINCOS, and incremental ENCODER all supported by
  the same front end.

## Why the V6 maps so well onto the Bolt

The HW_TESLA variant already implements three things the Bolt needs (verified in
`stm32-sine`):

| Need | V6 / HW_TESLA mechanism | Source |
|----|----|----|
| 3 module NTCs, 1 ADC | PC8 repurposed as 74HCT4052 mux select (`temp1_out`/`bms_in`) | `hwinit.cpp` io_setup HW_TESLA case |
| Resolver decode | **firmware only** — TIM3_CC4-triggered ADC sampling of sin/cos on PA6/PA7, exciter on PD2. The V6 *hardware* is encoder-only; the resolver front end is new (see 03-schematic-design.md) | `inc_encoder.cpp` |
| 6-PWM + HW fault trip | TIM1 CH1-3 + CH1N-3N, break input on PB12 | `hwdefs.h` PWM_TIMER=TIM1, `digio_prj.h` bk_in=PB12 |
| Board detection | `detect_hw()` pin-state tree + variant resistor on ADC ch15/PC5 | `hwinit.cpp` |
| Current scaling | runtime `il1gain`/`il2gain` params | `param_prj.h` |

## Canonical STM32F103 pin map (from stm32-sine hwdefs)

Analog (`ANA_IN_LIST`, Tesla/main list):

| Signal | STM32 | Role |
|----|----|----|
| throttle1 | PC1 | pedal 1 (or CAN torque in non-vehicle use) |
| throttle2 | PC0 | pedal 2 |
| udc | PC3 | DC-bus voltage |
| tmpm | PC2 | motor temperature |
| tmphs | PC4 | heatsink/module temp (**muxed via 4052 on Tesla**) |
| uaux | PA3 | 12 V aux sense |
| il1 | PA5 | phase current 1 |
| il2 | PB0 | phase current 2 |
| variant R | PC5 / ADC ch15 | board-version strap |

Digital (`DIG_IO_LIST`) — relevant to the gate interface and vehicle:

| Signal | STM32 | Role |
|----|----|----|
| bk_in | PB12 | **TIM1 break** — hardware PWM shutdown |
| desat_in | PC9 | gate-driver fault input |
| ocur_in | PA1 | overcurrent input |
| bms_in / temp1_out | PC8 | **temp mux select** on Tesla hw |
| dcsw_out | PC13 | main contactor |
| prec_out | PB1 | precharge contactor |
| vtg_out | PC11 | aux / spi_cs |
| fan_out | PA0 | cooling fan/pump |
| led_out | PC12 | status LED |
| err_out | PC10 | error out (remapped away on Tesla) |
| speed_out | PB9 | speed signal |
| cruise/start/brake/fwd/rev/emcystop | PB5/PB6/PA2/PA4/PC6/PC7 | vehicle inputs |

PWM (TIM1): PA8=CH1, PA9=CH2, PA10=CH3 (high side); PB13=CH1N, PB14=CH2N,
PB15=CH3N (low side). Break = PB12.

## Internal 40-pin connector → board mapping (gate board side)

| Bolt pin | Function | Board / STM32 | Notes |
|----|----|----|----|
| 11 / 12 | PWM U hi / lo | TIM1 CH1 (PA8) / CH1N (PB13) | via 3.3→5 V level shift |
| 13 / 14 | PWM V hi / lo | TIM1 CH2 (PA9) / CH2N (PB14) | " |
| 15 / 16 | PWM W hi / lo | TIM1 CH3 (PA10) / CH3N (PB15) | " |
| 24 / 27 / 26 | Current U / V / W | il1 (PA5), il2 (PB0), [3rd spare] | rescale front end for HC5FW700; firmware uses 2, derives 3rd |
| 17 / 19 / 21 | NTC U / V / W | tmphs (PC4) via 4052 mux, select PC8 | **provide 3 pull-ups to analog 5 V on our board** |
| 22 | Combined FLT+RDY (OD, active-low) | bk_in / BKIN (PB12) via 5→3.3 V | hardware trip; optionally also desat_in |
| 7–10 | Gate-board health AND outputs (high=OK) | desat_in (PC9), ocur_in (PA1), + spare GPIO | 4 lines; read-only; see open items |
| 18 | Conditioned analog from gate board | udc (PC3) candidate | **confirm it's DC-bus sense before wiring to udc** |
| 20 | TLE2022A ch A node | TBD | pending Phase 1 open item |
| 3 / 4 | Digital 5 V to gate board | board supply out | generate clean 5.0 V |
| 28 / 29 | Analog 5 V (sensor + ADC ref) | board supply out | ADC ref tie-point |
| 31/33/35/37 | 12 V → isolated gate supply | pass vehicle 12 V | |
| 36 / 38 | Ignition/enable sense (~125 k to Run/Crank) | uaux (PA3) or GPIO | |
| GND | 1,2,5,6,23,25,30,32,34,39,40 | GND plane | |

## External 48-way connector → board mapping (vehicle/motor side)

(GM Power Invert Module X1, OEM 98993-5021 / service 19354859.)

| Function | Bolt ext pins | Board / STM32 |
|----|----|----|
| Resolver excitation − / + | B1 / B2 | resolver exciter out (TIM3-driven) |
| Resolver sin/cos signals | C1/C2/D1/D2 | resolver sin/cos ADC (injected, TIM3_CC4) |
| Motor temperature | J1 / J2 | tmpm (PC2) |
| CAN (GMLAN HS) | E3/E4 (+ F/G/H/J pairs) | SN65HVD230 |
| HV interlock (HVIL) | G1 / G2 | GPIO (loop monitor) |
| Run/Crank ignition | L3 | wake / uaux |
| Battery + | M1 / M4 | 12 V in |
| Ground | K2 | GND |
| Trans range switch, aux pump | B4/C3/C4/D3/D4, F1/F2 | optional GPIO/CAN |

## Functional blocks: reuse vs. change from V6

**Reuse largely as-is:** power tree (RT8259 buck, LD1117 3.3 V; the LM2664 −5 V is
dropped), CAN (SN65HVD234), ESP32 WiFi web UI, temp mux,
TIM1 PWM core, BKIN fault path, contactor/precharge/pump low-side drivers (BTS133).

**Change for the Bolt:**
1. **Connectors** — replace Tesla's connectors with the Bolt internal 40-pin
   (board-to-board) and external 48-way (GM) footprints. Mechanical fit is the top
   risk (see below).
2. **Current-sense front end** — re-scale for HC5FW700-S/SP3 (ratiometric, 0 A =
   Vcc/2, 0–5 V out) into the STM32's 0–3.3 V ADC window; set `il1gain`/`il2gain`.
3. **NTC pull-ups** — add three pull-ups (~4.7 kΩ to analog 5 V) for the module NTCs
   on 17/19/21; wire through the 4052 mux.
4. **Board-detect strap** — pick a unique variant-resistor value (or pin signature)
   for HW_BOLT in `detect_hw()`.
5. **Fault mapping** — pin 22 → BKIN; distribute 7–10 across desat_in/ocur_in/GPIO.
6. **No gate-enable line** — power-up sequencing parks all PWM off (TIM1 break
   asserted) until rails are up and firmware releases; rely on 1ED020I12 UVLO.

## Current-sense scaling (finalized)

HC5FW700-S/SP3 is ratiometric: `Vout = Vcc/2 + S·I`.
- **Sensitivity S = 2.86 mV/A** (from datasheet), 0 A = Vcc/2 = 2.5 V.
- Over ±700 A the output swings ±2.0 V → **~0.5–4.5 V range**. This is larger than the
  0–3.3 V ADC window, so the Bolt sensor is **attenuated, not amplified** (opposite of
  the V6's gain stage — reconfigure the op-amp as an attenuating buffer).

Front end: attenuate by **k = 0.635** (the V6's 2k7 / 4k7 divider after an op-amp buffer).
Maps 0.5–4.5 V → 0.32–2.86 V at the ADC; 2.5 V (0 A) → 1.59 V, near mid-scale.

```
il_gain = S · k · (4096 / 3.3) = 0.00286 × 0.635 × 1241 ≈ 2.25 digits/A
```

- HW_BOLT default **`il1gain`/`il2gain` ≈ 2.25** (sign set at commissioning).
- Resolution ≈ 0.44 A/count across ±700 A (sensor-limited).
- **Reference note:** true ratiometric cancellation is NOT achievable here — the STM32
  ADC reference is 3.3 V VDDA and does not track the 5 V sensor rail. Instead: regulate
  the analog 5 V tightly; OpenInverter auto-calibrates the zero-current offset at
  startup (handles the 2.5 V center); gain drift vs. 5 V is second-order.

## Firmware change list (stm32-sine fork)

1. `include/hwdefs.h` — add `HW_BOLT` to the HWREV enum.
2. `src/hwinit.cpp` — `detect_hw()`: add HW_BOLT signature; `io_setup()`: HW_BOLT
   case (temp mux on PC8, resolver init, current inputs, IO enables).
3. `include/param_prj.h` — HW_BOLT default `il1gain`/`il2gain`, resolver params.
4. `include/temp_meas.h` — add the Infineon module NTC curve (R25 = 5.0 kΩ,
   B25/100 = 3433 K) and the Bolt motor-temp curve.
5. Resolver exciter freq / `resolverSampleDelay` tuned for the Bolt resolver.
6. Optional: extend to read the 3rd current sensor for redundancy.

## Open items / risks

1. **Mechanical fit (highest risk).** Board outline, mounting-hole pattern, 40-pin
   connector position, and board-to-board stack height to the gate board. Needs
   measurement of the OEM logic board — *you have the board.*
2. **FOC flash fit** on 128 KB RB vs. RET6.
3. **Pin 18/20 function** — confirm pin 18 is DC-bus sense (then → udc); resolve pin
   20 (Phase 1 open item).
4. **7–10 mapping** — 4 health lines vs. available fault inputs; decide AND-combine
   vs. per-line GPIO.
5. **Resolver compatibility** — Bolt resolver pole count / excitation vs. V6 defaults;
   and the config path for non-Bolt resolvers/encoders.
6. **Connector sourcing** — mating 40-pin board-to-board and 48-way GM part + KiCad
   footprints.

## Next steps

1. KiCad project skeleton in this repo + library/footprint plan.
2. Mechanical: capture OEM board outline, hole pattern, connector positions, stack
   height (from your physical board).
3. Deep-read V6 schematic (gate interface, current front end, resolver) to port exact
   values into KiCad.
4. HC5FW700-S/SP3 datasheet → finalize current front-end + gains.
5. Schematic capture, block by block.
