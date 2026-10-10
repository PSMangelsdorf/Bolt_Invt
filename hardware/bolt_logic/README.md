# bolt_logic — KiCad project

Replacement logic board for the Chevrolet Bolt EV traction inverter.

Current state:
- **Schematic v0.1** — 7 hierarchical sheets, 258 parts, 169 nets (PDF:
  `../../docs/bolt_logic_schematic.pdf`; design rationale: `../../docs/03-schematic-design.md`).
- **PCB: mechanical skeleton** — board outline, 14 mounting/alignment holes, CN1 and CN2
  footprints at their measured positions. Not yet updated from the schematic.

- `bolt_logic.kicad_pcb` — generated; do not hand-edit the mechanical items.
- `tools/gen_mech.py` — generator and single source of truth for all mechanical
  dimensions. Edit the data block at the top, then re-run:
  `python3 tools/gen_mech.py` (needs KiCad's `pcbnew` Python module, KiCad 7+).
  The script asserts every pad position against the data table before saving.
- `tools/sch_design.py` — the schematic design table: every part and every pin→net.
  `python3 tools/gen_sch.py` regenerates all `.kicad_sch` files and verifies the
  KiCad-exported netlist against the table. Edit the table, not the sheets.
- `Bolt.pretty/`, `Bolt.kicad_sym` — project footprint and symbol libraries
  (registered in `fp-lib-table` / `sym-lib-table`).

Coordinate frame and measurement provenance: `../../docs/02-mechanical.md`.
Saved in KiCad 7 format; opens in KiCad 8/9 (which will offer to upgrade the file).
