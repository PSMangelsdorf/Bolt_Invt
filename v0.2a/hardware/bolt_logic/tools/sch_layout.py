"""Schematic drawing layout for tools/gen_sch.py (v0.2a, after the forum review).

Per sheet: where every symbol goes, drawn in signal-flow order (left to right where it can be),
with each decoupling capacitor next to the IC (or the power unit of a multi-unit part) it serves.
The netlist itself lives in sch_design.py; nothing here changes a connection.

Keys per sheet:
    "REF" or "REF.unit": (x, y, rotation)   sheet mm (y down), snapped to the 2.54 mm grid.
        Two-terminal parts (R, C, L, fuse, ferrite): rotation 0 = vertical, pin 1 on top;
        90 = horizontal, pin 1 left; 180 / 270 the reverse. Diodes, LEDs, crystals: 0 =
        horizontal, pin 1 (cathode) left; 270 = vertical, pin 1 on top.
    "_wire":    supply nets drawn with wires on this sheet (elsewhere they are power symbols)
    "_anchors": {net: (x, y, direction)} where a net's label (or rail symbol) goes, at a free
                point; the router wires it to the net's pins
    "_label":   {net: "REF.pin"} the pin a net's label attaches to (default: an IC pin)
    "_labelrefs": parts whose pins each get their own label (connectors)
    "_notes":   section titles
    "_flags":   where the PWR_FLAGs go
"""

SOURCE = {  # inter-sheet net -> the sheet that drives it (label shape: output there, input elsewhere)
    "BRAKE_IN": "vehicle", "CRUISE_IN": "vehicle", "EMCYSTOP_IN": "vehicle", "FWD_IN": "vehicle",
    "MPROT_IN": "vehicle", "REV_IN": "vehicle", "START_IN": "vehicle", "THROTTLE1": "vehicle",
    "THROTTLE2": "vehicle", "CAN_RX": "vehicle", "CAN_TX": "mcu",
    "DCSW_OUT": "mcu", "PRECHARGE_OUT": "mcu", "PUMP_OUT": "mcu",
    "SIN_N": "vehicle", "SIN_P": "vehicle", "COS_N": "vehicle", "COS_P": "vehicle",
    "ENC_A_IN": "vehicle", "ENC_B_IN": "vehicle", "ENC_Z_IN": "vehicle", "MOT_TEMP": "vehicle",
    "IGN": "vehicle", "EXC_N": "resolver", "EXC_P": "resolver",
    "GATE_FLT_MCU": "gate_if", "GATE_OK": "gate_if", "UDC": "gate_if", "PWM_INHIBIT": "gate_if",
    "PWM_UH_3V": "mcu", "PWM_UL_3V": "mcu", "PWM_VH_3V": "mcu", "PWM_VL_3V": "mcu",
    "PWM_WH_3V": "mcu", "PWM_WL_3V": "mcu", "GATE_PWR_EN": "mcu",
    "IL1": "analog", "IL2": "analog", "TMPHS": "analog", "TMPM": "analog", "OCUR_OK": "analog",
    "MUX_S0": "mcu", "MUX_S1": "mcu", "OCURLIM_NEG_PWM": "mcu", "OCURLIM_POS_PWM": "mcu",
    "ISNS_U": "gate_if", "ISNS_V": "gate_if", "ISNS_W": "gate_if",
    "NTC_U": "gate_if", "NTC_V": "gate_if", "NTC_W": "gate_if",
    "POS_A": "resolver", "POS_B": "resolver", "POS_Z": "mcu",
    "USART_TX": "mcu", "USART_RX": "wifi",
}

PLACE = {}

# ======================================================================== POWER
y0 = 66.04                                   # main power path
PLACE["power"] = {
    "_wire": ["VBAT", "VCC_12V", "+5V", "+3V3", "+5V_A", "+12V_GATE"],
    "_label": {"VBAT": "Q1.3", "VCC_12V": "C5.1", "+5V": "C9.1", "+3V3": "C12.1", "+5V_A": "C14.1",
               "+12V_GATE": "C16.1"},
    "_anchors": {"IGN": (27.94, 81.28, "left"), "GATE_PWR_EN": (66.04, 129.54, "left")},
    "_notes": [(20.32, 35.56, "Battery in: TVS first, ignition high-side switch Q1, reverse-polarity diode D1"),
               (101.6, 50.8, "12 V rail"), (165.1, 45.72, "5 V buck (AP63205, 3.8-32 V in)"),
               (254.0, 45.72, "3.3 V LDO (MCU, analog)"),
               (63.5, 104.14, "Gate-board 12 V, switched by the MCU (PA15)"),
               (210.82, 93.98, "Filtered 5 V for the current sensors"),
               (25.4, 154.94, "Mounting holes: chassis, tied to GND through R7")],
    "_flags": (38.1, 215.9),
    "TVS1": (20.32, y0 - 2.54, 270),
    "Q1": (76.2, y0, 0),
    "Q3": (55.88, 81.28, 0), "R1": (38.1, 81.28, 90), "R2": (45.72, 88.9, 0), "R3": (63.5, 81.28, 0),
    "D1": (93.98, y0, 180),
    "C1": (106.68, y0 + 7.62, 0), "C2": (119.38, y0 + 7.62, 0), "C3": (132.08, y0 + 7.62, 0),
    "C4": (144.78, y0 + 7.62, 0), "C5": (157.48, y0 + 7.62, 0),
    "U1": (177.8, y0 + 2.54, 0), "C6": (195.58, 55.88, 0), "L1": (205.74, y0, 90),
    "C7": (218.44, y0 + 7.62, 0), "C8": (231.14, y0 + 7.62, 0), "C9": (243.84, y0 + 7.62, 0),
    "C10": (256.54, y0 + 7.62, 0), "U2": (271.78, y0, 0),
    "C11": (289.56, y0 + 7.62, 0), "C12": (302.26, y0 + 7.62, 0),
    "FB1": (231.14, 104.14, 90), "C13": (246.38, 111.76, 0), "C14": (259.08, 111.76, 0),
    "Q2": (129.54, 116.84, 0), "Q4": (104.14, 129.54, 0), "R4": (88.9, 129.54, 90), "R5": (76.2, 137.16, 0),
    "R6": (116.84, 127.0, 0), "C15": (147.32, 124.46, 0), "C16": (160.02, 124.46, 0),
    "R7": (220.98, 175.26, 0),
}
for i in range(12):
    PLACE["power"]["H%d" % (i + 1)] = (38.1 + 15.24 * i, 165.1, 0)
PLACE["power"]["H13"] = (233.68, 165.1, 0)
PLACE["power"]["H14"] = (246.38, 165.1, 0)

# ======================================================================== MCU
ux, uy = 215.9, 142.24                         # U3: left pins x 198.12, right 233.68, top y 93.98
PLACE["mcu"] = {
    "_wire": ["VDDA"],
    "_label": {"VDDA": "L2.2"},
    "_notes": [(119.38, 50.8, "STM32F103RBT6 (OpenInverter stm32-sine, HW_BOLT)"),
               (180.34, 55.88, "Decoupling: 100 nF at each VDD pin, 4.7 uF bulk"),
               (127.0, 180.34, "Oscillators: load caps at the crystal"),
               (251.46, 116.84, "SWD")],
    "_flags": (254.0, 215.9),
    "U3": (ux, uy, 0),
    "C20": (185.42, 76.2, 0), "C21": (195.58, 76.2, 0), "C22": (205.74, 76.2, 0), "C23": (215.9, 76.2, 0),
    "C24": (175.26, 76.2, 0),
    "L2": (238.76, 81.28, 270), "C25": (231.14, 88.9, 0), "C26": (246.38, 88.9, 0),
    "C27": (165.1, 88.9, 0),
    "R10": (180.34, 104.14, 270),
    "Y1": (165.1, 111.76, 270), "C28": (154.94, 114.3, 0), "C29": (147.32, 121.92, 0),
    "Y2": (165.1, 160.02, 270), "C30": (154.94, 162.56, 0), "C31": (147.32, 170.18, 0),
    "LED2": (175.26, 149.86, 180), "R13": (162.56, 149.86, 90),
    "R12": (127.0, 76.2, 0), "LED1": (127.0, 93.98, 90),
    "_text": {"R11": (-3.81, -2.6, 1.27, -2.6, "left"), "R14": (-3.81, 2.6, 1.27, 2.6, "left")},
    "R11": (266.7, 147.32, 90), "R14": (266.7, 152.4, 90),
    "J1": (269.24, 132.08, 0),
}

# ======================================================================== GATE INTERFACE
yk = [116.84, 132.08, 147.32, 162.56, 177.8]
chains = [("GATE_FLT", "R21", "R22", "C41"), ("HEALTH1", "R23", "R24", "C42"), ("HEALTH2", "R25", "R26", "C43"),
          ("HEALTH3", "R27", "R28", "C44"), ("HEALTH4", "R29", "R30", "C45")]
PLACE["gate_if"] = {
    "_labelrefs": ["CN2"],
    "_anchors": {"GATE_OK": (127.0, 163.83, "right"), "GATE_FLT_MCU": (111.76, 116.84, "right"),
                 "UDC": (264.16, 63.5, "right"), "GB_UDC": (187.96, 63.5, "left"), "GB_AUX": (187.96, 86.36, "left")},
    "_notes": [(25.4, 40.64, "PWM to the gate board: 3.3 V -> 5 V latch (74HCT573), pulled low while the MCU is in reset"),
               (25.4, 109.22, "Gate-board status: 100k fail-safe pull-down, 560R / 10 nF filter"),
               (132.08, 119.38, "Hardware trip: PWM_INHIBIT = NAND(healthy, no fault, no overcurrent)"),
               (180.34, 50.8, "DC-bus voltage from the gate board (CN2 18), clamped to the ADC range"),
               (180.34, 101.6, "Ignition sense to the gate board (as OEM)"),
               (304.8, 91.44, "CN2: gate-board connector (2x20)")],
    "U4": (101.6, 76.2, 0), "C40": (119.38, 50.8, 0),
    "RN1": (66.04, 93.98, 0), "RN2": (78.74, 93.98, 0),
    "U5.1": (101.6, 149.86, 0), "U5.2": (101.6, 203.2, 0), "U5.3": (154.94, 231.14, 0), "C46": (167.64, 231.14, 0),
    "U6.1": (144.78, 132.08, 0), "U6.2": (144.78, 203.2, 0), "U6.3": (175.26, 203.2, 0),
    "U6.4": (185.42, 231.14, 0), "C47": (198.12, 231.14, 0),
    "R31": (116.84, 157.48, 0), "R32": (116.84, 170.18, 0), "R33": (99.06, 116.84, 90),
    "TP2": (198.12, 60.96, 0), "R34": (208.28, 63.5, 90), "R35": (218.44, 71.12, 0),
    "D2": (231.14, 58.42, 0), "R36": (246.38, 63.5, 90), "C48": (256.54, 68.58, 0),
    "TP1": (200.66, 83.82, 0), "R37": (210.82, 91.44, 0),
    "R20": (203.2, 116.84, 90),
    "CN2": (330.2, 127.0, 0),
}
for i, net in enumerate(["PWM_UH_3V", "PWM_UL_3V", "PWM_VH_3V", "PWM_VL_3V", "PWM_WH_3V", "PWM_WL_3V"]):
    PLACE["gate_if"]["_anchors"][net] = (53.34, 63.5 + 2.54 * i, "left")
for (net, rpd, rser, cf), y in zip(chains, yk):
    PLACE["gate_if"]["_anchors"][net] = (35.56, y, "left")
    PLACE["gate_if"][rpd] = (45.72, y + 5.08, 0)
    PLACE["gate_if"][rser] = (55.88, y, 90)
    PLACE["gate_if"][cf] = (66.04, y + 5.08, 0)

# ======================================================================== ANALOG
PLACE["analog"] = {
    "_anchors": {"ISNS_U": (30.48, 50.8, "left"), "ISNS_V": (30.48, 88.9, "left"), "ISNS_W": (30.48, 127.0, "left"),
                 "IL1": (124.46, 53.34, "right"), "IL2": (124.46, 91.44, "right"),
                 "OCURLIM_NEG_PWM": (35.56, 170.18, "left"), "OCURLIM_POS_PWM": (35.56, 195.58, "left"),
                 "OCUR_OK": (299.72, 50.8, "right")},
    "_notes": [(25.4, 38.1, "Phase current: RC filter, buffer (5 V_A), 2.7k / 4.7k to the ADC"),
               (25.4, 157.48, "Overcurrent thresholds: MCU PWM, RC filtered"),
               (185.42, 38.1, "Overcurrent window (LM2901), wired-OR"),
               (279.4, 76.2, "Temperature mux and NTC pull-ups")],
    "R40": (40.64, 50.8, 90), "C50": (50.8, 55.88, 0), "U7.1": (71.12, 53.34, 0),
    "R41": (91.44, 53.34, 90), "R42": (101.6, 58.42, 0), "C51": (109.22, 58.42, 0),
    "R43": (40.64, 88.9, 90), "C52": (50.8, 93.98, 0), "U7.2": (71.12, 91.44, 0),
    "R44": (91.44, 91.44, 90), "R45": (101.6, 96.52, 0), "C53": (109.22, 96.52, 0),
    "R46": (40.64, 127.0, 90), "C55": (50.8, 132.08, 0), "U8.1": (71.12, 129.54, 0),
    "R47": (91.44, 129.54, 90), "R48": (101.6, 134.62, 0), "C56": (109.22, 134.62, 0),
    "U8.2": (71.12, 236.22, 0),
    "U7.3": (35.56, 236.22, 0), "C54": (45.72, 236.22, 0), "U8.3": (99.06, 236.22, 0), "C57": (109.22, 236.22, 0),
    "R49": (45.72, 170.18, 90), "C58": (55.88, 175.26, 0), "R50": (45.72, 195.58, 90), "C59": (55.88, 200.66, 0),
    "U9.1": (198.12, 53.34, 0), "U9.2": (198.12, 73.66, 0), "U9.3": (198.12, 93.98, 0), "U9.4": (198.12, 114.3, 0),
    "U10.1": (198.12, 134.62, 0), "U10.2": (198.12, 154.94, 0), "U10.3": (198.12, 182.88, 0),
    "U10.4": (198.12, 203.2, 0),
    "U9.5": (160.02, 236.22, 0), "C60": (170.18, 236.22, 0), "U10.5": (187.96, 236.22, 0), "C61": (198.12, 236.22, 0),
    "R51": (284.48, 43.18, 0),
    "U11": (304.8, 116.84, 0), "C62": (325.12, 91.44, 0),
}
for i, (r, c) in enumerate([("R52", "C63"), ("R53", "C64"), ("R54", "C65"), ("R55", "C66")]):
    PLACE["analog"][r] = (332.74 + 10.16 * i, 96.52, 0)
    PLACE["analog"][c] = (337.82 + 10.16 * i, 144.78, 0)
for net, y in (("NTC_U", 121.92), ("NTC_V", 124.46), ("NTC_W", 127.0), ("MOT_TEMP", 109.22)):
    PLACE["analog"]["_anchors"][net] = (381.0, y, "right")

# ======================================================================== RESOLVER
PLACE["resolver"] = {
    "_anchors": {"POS_Z": (25.4, 50.8, "left"), "EXC_P": (228.6, 55.88, "right"), "EXC_N": (228.6, 66.04, "right"),
                 "SIN_P": (25.4, 139.7, "left"), "SIN_N": (25.4, 144.78, "left"),
                 "COS_P": (25.4, 190.5, "left"), "COS_N": (25.4, 195.58, "left"),
                 "POS_A": (269.24, 142.24, "right"), "POS_B": (269.24, 193.04, "right"),
                 "ENC_A_IN": (139.7, 218.44, "left"), "ENC_B_IN": (139.7, 233.68, "left"),
                 "ENC_Z_IN": (139.7, 248.92, "left")},
    "_notes": [(25.4, 27.94, "Resolver exciter: MCU square wave -> filter -> sine -> TCA0372 bridge (12 V)"),
               (25.4, 88.9, "1.65 V reference"),
               (25.4, 127.0, "Sin / cos receivers (differential, 3.3 V)"),
               (139.7, 208.28, "Encoder option (fit R89/R91/R93, remove R60/R85/R87)")],
    "R60": (35.56, 50.8, 90), "R61": (48.26, 50.8, 90), "C70": (55.88, 58.42, 0),
    "R62": (63.5, 50.8, 90), "R63": (76.2, 50.8, 90), "C71": (88.9, 38.1, 90), "C72": (83.82, 58.42, 0),
    "U12.1": (99.06, 53.34, 0), "U12.3": (38.1, 233.68, 0), "C75": (48.26, 233.68, 0),
    "C76": (124.46, 53.34, 90),
    "R69": (139.7, 60.96, 180), "R67": (132.08, 76.2, 0), "R68": (132.08, 88.9, 0), "C77": (142.24, 88.9, 0),
    "U13": (170.18, 63.5, 0), "C79": (185.42, 40.64, 0), "C80": (198.12, 40.64, 0),
    "R70": (170.18, 35.56, 90), "R71": (157.48, 38.1, 180), "C78": (142.24, 38.1, 0),
    "R72": (170.18, 88.9, 90), "R73": (170.18, 99.06, 90),
    "C81": (198.12, 55.88, 90), "R74": (210.82, 55.88, 90), "R75": (210.82, 66.04, 90),
    "U12.2": (99.06, 104.14, 0), "R64": (76.2, 96.52, 0), "R65": (76.2, 109.22, 0), "C73": (83.82, 109.22, 0),
    "_text": {"R76": (-3.81, -2.6, 1.27, -2.6, "left"), "R77": (-3.81, 2.6, 1.27, 2.6, "left"),
              "R80": (-3.81, -2.6, 1.27, -2.6, "left"), "R81": (-3.81, 2.6, 1.27, 2.6, "left")},
    "R76": (45.72, 139.7, 90), "R77": (45.72, 144.78, 90), "R79": (55.88, 132.08, 180),
    "U14.1": (78.74, 142.24, 0), "R78": (78.74, 154.94, 90), "C82": (78.74, 162.56, 90),
    "R84": (101.6, 142.24, 90), "C85": (109.22, 147.32, 0), "R85": (119.38, 142.24, 90),
    "R80": (45.72, 190.5, 90), "R81": (45.72, 195.58, 90), "R83": (55.88, 182.88, 180),
    "U14.2": (78.74, 193.04, 0), "R82": (78.74, 205.74, 90), "C83": (78.74, 213.36, 90),
    "R86": (101.6, 193.04, 90), "C86": (109.22, 198.12, 0), "R87": (119.38, 193.04, 90),
    "U14.3": (66.04, 233.68, 0), "C84": (76.2, 233.68, 0),
}
for i, (ra, c, rb) in enumerate([("R88", "C87", "R89"), ("R90", "C88", "R91"), ("R92", "C89", "R93")]):
    y = 218.44 + 15.24 * i
    PLACE["resolver"][ra] = (149.86, y, 90)
    PLACE["resolver"][c] = (160.02, y + 5.08, 0)
    PLACE["resolver"][rb] = (170.18, y, 90)

# ======================================================================== VEHICLE
PLACE["vehicle"] = {
    "_labelrefs": ["CN1"],
    "_label": {"CAN_H": "R123.1", "CAN_L": "R124.2"},
    "_anchors": {},
    "_notes": [(25.4, 38.1, "CN1: vehicle connector (GM X1, 48-way)"),
               (139.7, 38.1, "12 V switch inputs: 4.7k / 1.5k divider, 1 uF filter"),
               (139.7, 132.08, "Throttle inputs (0-5 V -> 2.5 V max)"),
               (139.7, 172.72, "Inputs with no connector pin: held 'OK'"),
               (226.06, 50.8, "Sensor supplies (polyfuses)"),
               (213.36, 104.14, "Contactor / pump drivers (HITFET low side), off in reset"),
               (220.98, 167.64, "CAN (SN65HVD234, 3.3 V), 120R termination")],
    "F1": (233.68, 63.5, 0), "F2": (248.92, 63.5, 0),
    "U20": (238.76, 127.0, 0), "R120": (226.06, 134.62, 0),
    "U21": (279.4, 127.0, 0), "R121": (266.7, 134.62, 0),
    "U22": (320.04, 127.0, 0), "R122": (307.34, 134.62, 0),
    "U23": (254.0, 190.5, 0), "C109": (269.24, 177.8, 0),
    "R123": (284.48, 187.96, 0), "R124": (284.48, 198.12, 0),
    "R111": (149.86, 182.88, 180), "R113": (162.56, 182.88, 180),
    "CN1": (66.04, 139.7, 0),
}
for i, (s, r1, r2, c) in enumerate([("FWD", "R100", "R101", "C100"), ("REV", "R102", "R103", "C101"),
                                    ("BRAKE", "R104", "R105", "C102"), ("START", "R106", "R107", "C103"),
                                    ("CRUISE", "R108", "R109", "C104")]):
    y = 50.8 + 15.24 * i
    PLACE["vehicle"]["_anchors"][s + "_12V"] = (139.7, y, "left")
    PLACE["vehicle"]["_anchors"][s + "_IN"] = (180.34, y, "right")
    PLACE["vehicle"][r1] = (149.86, y, 90)
    PLACE["vehicle"][r2] = (160.02, y + 5.08, 0)
    PLACE["vehicle"][c] = (170.18, y + 5.08, 0)
for i, (s, adc, rs, rp, c) in enumerate([("THR1", "THROTTLE1", "R114", "R115", "C107"),
                                         ("THR2", "THROTTLE2", "R116", "R117", "C108")]):
    y = 142.24 + 15.24 * i
    PLACE["vehicle"]["_anchors"][s + "_IN"] = (139.7, y, "left")
    PLACE["vehicle"]["_anchors"][adc] = (182.88, y, "right")
    PLACE["vehicle"][rp] = (149.86, y + 5.08, 0)
    PLACE["vehicle"][rs] = (160.02, y, 90)
    PLACE["vehicle"][c] = (170.18, y + 5.08, 0)
PLACE["vehicle"]["_anchors"].update({"EMCYSTOP_IN": (149.86, 195.58, "down"), "MPROT_IN": (162.56, 195.58, "down"),
                                     "PEDAL_5V": (233.68, 76.2, "down"), "ENC_5V": (248.92, 76.2, "down")})

# ======================================================================== WIFI
PLACE["wifi"] = {
    "_wire": ["ESP_3V3"],
    "_label": {"ESP_3V3": "C121.1"},
    "_anchors": {"USART_TX": (233.68, 124.46, "right"), "USART_RX": (233.68, 119.38, "right")},
    "_notes": [(119.38, 50.8, "ESP32-WROOM-32E (PCB antenna, as Tesla V6)"),
               (119.38, 55.88, "Own 3.3 V LDO (forum review: ~0.5 A transmit bursts), 100 uF bulk + 10 uF / 100 nF at the module pin")],
    "U31": (139.7, 68.58, 0), "C123": (116.84, 76.2, 0),
    "C124": (160.02, 76.2, 0), "C120": (172.72, 76.2, 0), "C121": (185.42, 76.2, 0),
    "R130": (177.8, 88.9, 0), "C122": (170.18, 104.14, 0),
    "U30": (203.2, 129.54, 0),
    "J4": (254.0, 99.06, 0),
}
