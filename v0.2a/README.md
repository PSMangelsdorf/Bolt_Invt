# Bolt logic board — v0.2a

v0.2a redesigns v0.1 (kept unchanged in `../V0.1/`) to answer the review on the openinverter forum
([Chevy Bolt Motor Control Adventures, page 3 on](https://openinverter.org/forum/viewtopic.php?t=6078&start=50)).
A separate v0.2b will follow, so the two can be compared.

**Prototype. Untested. Do not install in a vehicle.**

| | |
|----|----|
| What changed, point by point | `docs/06-forum-review.md` |
| Schematic (PDF) | `docs/bolt_logic_schematic.pdf` |
| Layout notes, stackup, DRC | `docs/04-layout.md` |
| Fabrication files (JLCPCB) | `fab/` |
| KiCad project and generator scripts | `hardware/bolt_logic/` |

In short:
- the stackup is signal / GND / power / signal, with a 3.3 V plane;
- decoupling runs plane → cap → IC;
- the crystals are routed first, with keep-outs;
- the contactor drivers sit next to CN1 with heavy copper and vias;
- the buck's copper is drawn as zones;
- the ESP32 has its own LDO and a 100 µF bulk cap;
- the schematic is drawn as wired, readable sheets.

The firmware pin map and the CN1 / CN2 pinouts are unchanged from v0.1.
