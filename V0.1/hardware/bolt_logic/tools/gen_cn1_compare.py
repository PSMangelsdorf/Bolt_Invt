#!/usr/bin/env python3
"""CN1 (external 48-way connector) comparison: OEM use vs. use on this board -> PDF.

    python3 tools/gen_cn1_compare.py      # writes ../../docs/cn1_oem_vs_new.pdf

OEM functions: owner's pinout spreadsheet (Bolt pinout.xlsx, "Inverter" sheet, GM Power
Invert Module X1, OEM 98993-5021 / service 19354859); pins it doesn't list are "Not used".
New use: CN1_NETS in sch_design.py, so the table always matches the schematic.
"""
import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sch_design import CN1_NETS  # noqa: E402

OUT = os.path.join(HERE, "..", "..", "..", "docs", "cn1_oem_vs_new.pdf")

OEM = {
    "B1": "Drive Motor 1 Position Sensor Excitation Signal Negative",
    "B2": "Drive Motor 1 Position Sensor Excitation Signal Positive",
    "B4": "Transmission Range Switch Signal A",
    "C1": "Drive Motor 1 Position Sensor 3 Signal",
    "C2": "Drive Motor 1 Position Sensor 1 Signal",
    "C3": "Transmission Range Switch Signal B",
    "C4": "Transmission Range Switch Signal P",
    "D1": "Drive Motor 1 Position Sensor 4 Signal",
    "D2": "Drive Motor 1 Position Sensor 2 Signal",
    "D3": "Transmission Range Switch Signal C",
    "D4": "Transmission Range Switch Signal S",
    "E3": "High Speed GMLAN Serial Data [-] 1",
    "E4": "High Speed GMLAN Serial Data [+] 1",
    "F1": "Transmission Aux Fluid Pump Relay Control",
    "F2": "Transmission Aux Fluid Pump Feedback Signal",
    "F3": "High Speed GMLAN Serial Data [-] 1",
    "F4": "High Speed GMLAN Serial Data [+] 1",
    "G1": "High Voltage System Interlock Low Reference 2",
    "G2": "High Voltage System Interlock Signal 3",
    "G3": "High Speed GMLAN Serial Data [-] 3",
    "G4": "High Speed GMLAN Serial Data [+] 3",
    "H1": "Transmission Fluid Temperature Sensor Signal",
    "H2": "Transmission Fluid Temperature Sensor Low Reference",
    "H3": "High Speed GMLAN Serial Data [-] 3",
    "H4": "High Speed GMLAN Serial Data [+] 3",
    "J1": "Traction Power Inverter Motor 1 Temperature Sensor Signal",
    "J2": "Traction Power Inverter Motor 1 Temperature Sensor Low Reference",
    "J3": "High Speed GMLAN Serial Data [-] 2",
    "J4": "High Speed GMLAN Serial Data [+] 2",
    "K2": "Ground",
    "L1": "Internal Mode Switch Voltage Supply A",
    "L3": "Run/Crank Ignition Voltage",
    "L4": "Internal Mode Switch Voltage Supply B",
    "M1": "Battery Positive Voltage",
    "M2": "Accessory Wake-Up Serial Data 2",
    "M4": "Battery Positive Voltage",
}

# Board net on CN1 -> plain-language use (a pin whose net is "NC" is reserved, not connected)
NEW = {
    "THR1_IN": "Throttle 1 (pedal potentiometer, 0-5 V)",
    "THR2_IN": "Throttle 2 (pedal potentiometer, 0-5 V)",
    "PEDAL_5V": "Pedal 5 V supply (50 mA polyfuse)",
    "EXC_N": "Resolver excitation - (same as OEM)",
    "EXC_P": "Resolver excitation + (same as OEM)",
    "PUMP_OUT_SW": "Pump / fan low-side output",
    "FWD_12V": "Forward input (12 V)",
    "SIN_N": "Resolver SIN - (same as OEM)",
    "SIN_P": "Resolver SIN + (same as OEM)",
    "REV_12V": "Reverse input (12 V)",
    "BRAKE_12V": "Brake input (12 V)",
    "COS_N": "Resolver COS - (same as OEM)",
    "COS_P": "Resolver COS + (same as OEM)",
    "START_12V": "Start input (12 V)",
    "CRUISE_12V": "Cruise input (12 V)",
    "MAIN_CONT_OUT": "Main contactor low-side output",
    "PRECHG_OUT_SW": "Precharge contactor low-side output",
    "CAN_L": "CAN low (same as OEM)",
    "CAN_H": "CAN high (same as OEM)",
    "MOT_TEMP": "Motor temperature sensor signal (same as OEM)",
    "ENC_A_IN": "Encoder A input (encoder assembly option)",
    "ENC_B_IN": "Encoder B input (encoder assembly option)",
    "ENC_Z_IN": "Encoder Z input (encoder assembly option)",
    "ENC_5V": "Encoder 5 V supply (200 mA polyfuse)",
    "IGN": "Run/crank ignition, turns the board on (same as OEM)",
    "VBAT": "Battery + 12 V (same as OEM)",
}
GND_USE = {"A4": "Pedal ground", "J2": "Motor temperature sensor low reference (same as OEM)",
           "K2": "Ground (same as OEM)", "M3": "Encoder ground"}


def rows():
    out = []
    for r in "ABCDEFGHJKLM":
        for c in "1234":
            pin = r + c
            net = CN1_NETS[pin]
            if net == "NC":
                new = "Not connected (reserved)" if pin in OEM else "Not connected"
            elif net == "GND":
                new = GND_USE[pin]
            else:
                new = NEW[net]
            out.append((pin, OEM.get(pin, "Not used"), new))
    assert len(out) == 48 and len(CN1_NETS) == 48
    return out


def build():
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=8.5, leading=10.5)
    head = cell.clone("head", fontName="Helvetica-Bold", textColor=colors.white)
    doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title="CN1 external connector: OEM vs. new use",
                            author="Bolt_Invt project")
    title = styles["Title"].clone("t", fontSize=15, leading=18, spaceAfter=4)
    story = [Paragraph("CN1 external connector (GM X1, 48-way): OEM vs. new use", title),
             Paragraph("OEM: Power Invert Module X1, OEM 98993-5021 / service 19354859. "
                       "New: open-source replacement logic board, schematic v0.1.", cell),
             Spacer(1, 5)]
    data = [[Paragraph("Pin", head), Paragraph("OEM use", head), Paragraph("New use", head)]]
    data += [[Paragraph(p, cell), Paragraph(o, cell), Paragraph(n, cell)] for p, o, n in rows()]
    t = Table(data, colWidths=[12 * mm, 94 * mm, 80 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3b4c")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef1f5")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa4b2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.0),
    ]))
    story.append(t)
    doc.build(story)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    build()
