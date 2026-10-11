# 05 — Firmware: HW_BOLT in stm32-sine

The firmware is the owner's stm32-sine fork, `github.com/PSMangelsdorf/stm32-sine`, on
branch **`hw-bolt`**. It adds the Bolt board as hardware variant `HW_BOLT` (`hwver` = 11).
Both builds compile cleanly, `CONTROL=SINE` and `CONTROL=FOC`, and the host unit tests pass.
This implements the change list in `03-schematic-design.md` §7.

## 1. What changed

| Area | File | Change |
|----|----|----|
| Detection | `src/hwinit.cpp` | The board is recognised when PB4 and PA15 are both held low by their 10 k pull-downs and PB3 floats. It is checked after the mini-mainboard and Blue Pill tests, because PB4 is the Blue Pill's precharge output and must not be pulled up there. It comes before the floating-pin tests, because PC9 floats while the gate board is unpowered and would otherwise be taken for Rev1. |
| IO setup | `src/hwinit.cpp` | Temperature mux: S0 = PC10, S1 = PC8 (same as Tesla). `fan_out` → PB9, the third BTS133 (pump/fan). `err_out` and `speed_out` → unused pins: PC10 is the mux select, and PB9 is the pump. New `gatepwr_out` on PA15 and `gateok_in` on PA0. PB9 is not set up as a TIM4 PWM output on this board. |
| Output mode | `src/stm32_sine.cpp` | `outmode` always keeps the contactor on PC13 and the pump/fan on PB9. The stock code would remap one of them onto PA0, which is an input here. |
| Gate supply | `src/stm32_sine.cpp` | The +12 V gate-driver supply is switched on once, at the end of init, after the PWM outputs are parked off. Until then the 1ED020I12 under-voltage lockout holds every IGBT off. |
| Hardware trip | `src/pwmgeneration.cpp` | On a trip: GATE_FLT low (PC9) → `DESAT`; gate-board health low (PA0) → new error **`GATEBOARD`**; otherwise `DESAT` if there's no overcurrent, else `OVERCURRENT`. Emergency stop and motor protection aren't wired into this board's trip logic (as on V6), so they're not blamed for a trip. |
| Temperatures | `src/vehiclecontrol.cpp`, `temp_meas` | Mux cycle 0 → 1 → 2. `tmphs` = hottest of the three module NTCs (CN2 17/19/21), using a new table for the FS800R07A2E3 NTC (5 k, B 3433) on 4.7 k to 3.3 V. `tmpm` = CN1 J1 on channel 0, using the sensor type set in `snsm`. The aux-header temperature (channel 1) is read but not used yet. |
| BMS input | `src/vehiclecontrol.cpp`, `src/stm32_sine.cpp` | None on this board (PC8 is the mux select), same handling as Tesla. A BMS signal still works over CAN. |
| New value | `include/param_prj.h` | `din_gateok` (1 = gate board healthy; 2 = not applicable on other boards). |
| Defaults | `src/stm32_sine.cpp` | On first start, with no saved parameters, `il1gain` and `il2gain` are set to 2.25 instead of the stock 4.7. |
| Tests | `test/test_bolt.cpp` | NTC table points and limits, mux sequence, mux readings (hottest phase, motor sensor on channel 0), and `din_gateok`. The GPIO and ADC stubs now simulate pin state for pins a test configures. |

Not changed:
- **Resolver support:** stock firmware, `encmode` = 4.
- **Current sense, PWM and the TIM1 core:** same pins as the V6.
- **Other hardware variants:** behaviour is unchanged.

## 2. Values that still need to be measured or set

| Parameter | Status |
|----|----|
| `udcgain`, `udcofs` | **Unknown until the CN2 pin 18 transfer function is measured** (bench test in `03` §4.7). Until then the reported `udc` is meaningless, and `udcmin`/`udclim`/`udcsw` protect nothing. |
| `il1gain`, `il2gain` | 2.25 dig/A in magnitude. **The sign depends on the sensor's orientation**, so check it at commissioning. `il1` is phase U, `il2` is phase V. |
| `deadtime` | Stock default (63 dig). Not yet set for the FS800 / 1ED020I12. Measure the OEM board's dead time with a scope on CN2 11/12 while it runs, then match it. |
| `pwmpol` | 0 (active high). Phase 1 open item 5: confirm the gate-board polarity before the first PWM test. |
| `snsm` | Bolt motor sensor type unknown (open question 2). |
| Resolver (`encmode` = 4, `respolepairs`, `polepairs`, `syncofs`) | Set for the motor. The exciter amplitude and the firmware's sample-delay setting are confirmed on the bench. |

## 3. Bench commissioning order (no high voltage)

1. **12 V only, no gate board.** Check `hwver` = 11 in the web UI or terminal. `din_desat` and `din_gateok` should read Error: the 100 k pull-downs on the status inputs read as a fault when no gate board is present.
2. **Add the gate board, still 12 V only.** Within a second of boot, `din_desat` and `din_gateok` should go to OK. Then check the following:
   - `tmphs` reads close to room temperature.
   - `il1` and `il2` read close to 0 A. If not, set the offsets.
   - The temperature mux cycles (watch PC10/PC8 on a scope).
3. **Gate supply in reset.** Hold the MCU in reset: +12V_GATE (CN2 31) must be off. The 10 k
   pull-down on PA15 keeps Q2 off whenever the MCU isn't driving it.
4. **Hardware trip.** Start the inverter at zero throttle with the usual start conditions
   met. With no high voltage, set `udcsw` to 0 temporarily so it will start.
   - Pull one HEALTH line low (CN2 7–10): expect error `GATEBOARD`, and the PWM must stop.
   - Repeat with CN2 22 low: expect `DESAT`.
5. **PWM.** With the DC link unpowered, check PWM polarity and dead time at the gate driver inputs before any high-voltage test.
6. **CN2 pin 18.** Do the DC-bus bench test (`03` §4.7), then set `udcgain`/`udcofs`.

## 4. Open firmware questions

- **Aux-header temperature:** add a value for the aux temperature, or fold it into `tmpm`?
- **Pump/fan output:** it currently follows the stock fan logic (`outmode` 1/2 with `fanthresh`). Should the pump instead run whenever the inverter is enabled?
- **Gate-board health:** decide whether to refuse start while `din_gateok` or `din_desat` reads Error. Right now a start with an unhealthy gate board trips straight away, and the reason is reported.
