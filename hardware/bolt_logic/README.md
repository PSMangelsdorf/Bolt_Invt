# bolt_logic — KiCad project

Replacement logic board for the Chevrolet Bolt EV traction inverter.

Current state: **mechanical skeleton** — board outline (Edge.Cuts), 14 mounting/alignment
holes, and the CN1 (external 48-way) and CN2 (internal 2×20) footprints, all at their
measured positions. No schematic yet.

- `bolt_logic.kicad_pcb` — generated; do not hand-edit the mechanical items.
- `tools/gen_mech.py` — generator and single source of truth for all mechanical
  dimensions. Edit the data block at the top, then re-run:
  `python3 tools/gen_mech.py` (needs KiCad's `pcbnew` Python module, KiCad 7+).
  The script asserts every pad position against the data table before saving.
- `Bolt.pretty/` — project footprint library (registered in `fp-lib-table`).

Coordinate frame and measurement provenance: `../../docs/02-mechanical.md`.
Saved in KiCad 7 format; opens in KiCad 8/9 (which will offer to upgrade the file).
