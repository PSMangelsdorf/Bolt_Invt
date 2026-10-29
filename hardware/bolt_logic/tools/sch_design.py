"""Bolt logic board - schematic design table (source of truth for the netlist).

Every part and every pin->net assignment lives here; gen_sch.py turns it into
KiCad sheets and verifies the exported netlist matches. Rationale and values:
docs/03-schematic-design.md (section numbers referenced below).

Conventions: nets in CAPS; '+5V' etc. are rails; 'NC' marks an intentional no-connect.
"""
import kisym
from gen_sch import Sheet

R0805 = "Resistor_SMD:R_0805_2012Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
SOIC14 = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
SOIC16 = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
SOIC20W = "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm"
FUSE = "Fuse:Fuse_1206_3216Metric"


def by_name(lib_id, names):
    """Map {pin_name: net} to {pin_number: net}; names must be unique in the symbol."""
    sym = kisym.lib_symbol(lib_id)
    table = {}
    for u in kisym.units(sym):
        for p in kisym.pins(sym, u):
            table.setdefault(p["name"], []).append(p["number"])
    out = {}
    for name, net in names.items():
        nums = table.get(name)
        if not nums or len(nums) != 1:
            raise KeyError("%s: pin name %r is %s" % (lib_id, name, "ambiguous" if nums else "missing"))
        out[nums[0]] = net
    return out


def nc_rest(lib_id, pins):
    sym = kisym.lib_symbol(lib_id)
    out = {str(k): v for k, v in pins.items()}
    for u in kisym.units(sym):
        for p in kisym.pins(sym, u):
            if p["number"] not in out and not p["hidden"]:
                out[p["number"]] = "NC"
    return out


def flag(sheet, n, net):
    sheet.add("#FLG%02d" % n, "power:PWR_FLAG", "PWR_FLAG", "", {1: net})


# =========================================================================
# 4.1 POWER
# =========================================================================
pw = Sheet("power", "power.kicad_sch", "Power")
pw.add("TVS1", "Device:D_TVS", "SMBJ26CA", "Diode_SMD:D_SMB", {1: "VBAT", 2: "GND"})
# Q1: logic power, enabled by ignition. BTS6143D (same PG-TO252-5-11 pinout as the BTS443P,
# whose symbol is used; owner chose it because JLCPCB stocks it). No GND pin: it switches on
# when IN is pulled to GND (input switch must sink up to 2.2 mA; < 30 uA keeps it off), so Q3
# pulls IN low when IGN is high (10k/6.8k divider: ~4.9 V gate at 12 V IGN).
pw.add("Q1", "Power_Management:BTS443P", "BTS6143D", "Package_TO_SOT_SMD:TO-252-4",
       {1: "VBAT_SW", 2: "Q1_IN", 3: "VBAT", 4: "Q1_IS"})
pw.r("R1", "10k", "IGN", "Q1_G")
pw.r("R2", "6.8k", "Q1_G", "GND")
pw.add("Q3", "Transistor_FET:2N7002", "2N7002", "Package_TO_SOT_SMD:SOT-23", {1: "Q1_G", 2: "GND", 3: "Q1_IN"})
pw.r("R3", "1k", "Q1_IS", "GND")
pw.add("D1", "Device:D_Schottky", "SS54", "Diode_SMD:D_SMA", {1: "VCC_12V", 2: "VBAT_SW"})
for i in range(4):
    pw.c("C%d" % (1 + i), "10uF 50V", "VCC_12V", "GND", fp=C1206)
pw.c("C5", "100nF", "VCC_12V", "GND")
# 5 V buck (AP63205WU, fixed 5.0 V, 3.8-32 V in)
pw.add("U1", "Regulator_Switching:AP63205WU", "AP63205WU", "Package_TO_SOT_SMD:TSOT-23-6",
       {1: "+5V", 2: "VCC_12V", 3: "VCC_12V", 4: "GND", 5: "SW_5V", 6: "BST_5V"})
pw.c("C6", "100nF", "BST_5V", "SW_5V")
pw.add("L1", "Device:L", "6.8uH", "Inductor_SMD:L_Bourns_SRN6045TA", {1: "SW_5V", 2: "+5V"})
pw.c("C7", "22uF", "+5V", "GND", fp=C1206)
pw.c("C8", "22uF", "+5V", "GND", fp=C1206)
pw.c("C9", "100nF", "+5V", "GND")
# 3.3 V LDO
pw.add("U2", "Regulator_Linear:LD1117S33TR_SOT223", "LD1117S33TR", "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
       {1: "GND", 2: "+3V3", 3: "+5V"})
pw.c("C10", "10uF", "+5V", "GND", fp=C1206)
pw.c("C11", "22uF", "+3V3", "GND", fp=C1206)
pw.c("C12", "100nF", "+3V3", "GND")
# Analog 5 V for the gate-board current sensors (CN2 28/29): filtered branch of the buck
pw.add("FB1", "Device:FerriteBead", "600R@100MHz 1A", "Inductor_SMD:L_0805_2012Metric", {1: "+5V", 2: "+5V_A"})
pw.c("C13", "10uF", "+5V_A", "GND", fp=C1206)
pw.c("C14", "100nF", "+5V_A", "GND")
# Q2: gate-board 12 V, MCU-controlled (PA15), default off
pw.add("Q2", "Power_Management:BTS443P", "BTS6143D", "Package_TO_SOT_SMD:TO-252-4",
       {1: "+12V_GATE", 2: "Q2_IN", 3: "VCC_12V", 4: "Q2_IS"})
# Q4 pulls Q2's IN low when PA15 is high (same active-low input as Q1). R5 holds the gate
# below the 2N7002 threshold while PA15 is still JTDI with its internal pull-up at reset.
pw.r("R4", "1k", "GATE_PWR_EN", "Q2_G")
pw.r("R5", "10k", "GATE_PWR_EN", "GND")
pw.add("Q4", "Transistor_FET:2N7002", "2N7002", "Package_TO_SOT_SMD:SOT-23", {1: "Q2_G", 2: "GND", 3: "Q2_IN"})
pw.r("R6", "1k", "Q2_IS", "GND")
pw.c("C15", "10uF 25V", "+12V_GATE", "GND", fp=C1206)
pw.c("C16", "100nF", "+12V_GATE", "GND")
# Mounting holes (PCB positions from gen_mech.py)
for i in range(1, 13):
    pw.add("H%d" % i, "Mechanical:MountingHole_Pad", "MountingHole_4mm", "Bolt:MountingHole_4.0mm_Pad6.5",
           {1: "CHASSIS"})
for i in (13, 14):
    pw.add("H%d" % i, "Mechanical:MountingHole", "NPTH_4.5mm", "Bolt:NPTH_4.5mm", {})
pw.r("R7", "0R", "CHASSIS", "GND", fp=R1206)
for n, net in enumerate(["VBAT", "GND", "VCC_12V", "+5V", "+3V3", "+5V_A", "+12V_GATE"], 1):
    flag(pw, n, net)

# =========================================================================
# 4.2 MCU
# =========================================================================
mcu = Sheet("mcu", "mcu.kicad_sch", "MCU")
STM = "MCU_ST_STM32F1:STM32F103RBTx"
stm_pins = by_name(STM, {
    "VBAT": "+3V3", "PC13": "DCSW_OUT", "PC14": "OSC32_IN", "PC15": "OSC32_OUT", "PD0": "OSC_IN",
    "PD1": "OSC_OUT", "NRST": "NRST", "PC0": "THROTTLE2", "PC1": "THROTTLE1", "PC2": "TMPM",
    "PC3": "UDC", "VSSA": "GND", "VDDA": "VDDA", "PA0": "GATE_OK", "PA1": "OCUR_OK",
    "PA2": "BRAKE_IN", "PA3": "MPROT_IN", "PA4": "FWD_IN", "PA5": "IL1", "PA6": "POS_A",
    "PA7": "POS_B", "PC4": "TMPHS", "PC5": "NC", "PB0": "IL2", "PB1": "PRECHARGE_OUT",
    "PB2": "BOOT1", "PB10": "USART_TX", "PB11": "USART_RX", "PB12": "PWM_INHIBIT",
    "PB13": "PWM_UL_3V", "PB14": "PWM_VL_3V", "PB15": "PWM_WL_3V", "PC6": "REV_IN",
    "PC7": "EMCYSTOP_IN", "PC8": "MUX_S1", "PC9": "GATE_FLT_MCU", "PA8": "PWM_UH_3V",
    "PA9": "PWM_VH_3V", "PA10": "PWM_WH_3V", "PA11": "CAN_RX", "PA12": "CAN_TX", "PA13": "SWDIO",
    "PA14": "SWCLK", "PA15": "GATE_PWR_EN", "PC10": "MUX_S0", "PC11": "NC", "PC12": "LED_OUT",
    "PD2": "POS_Z", "PB3": "NC", "PB4": "BOARD_ID", "PB5": "CRUISE_IN", "PB6": "START_IN",
    "PB7": "OCURLIM_NEG_PWM", "BOOT0": "BOOT0", "PB8": "OCURLIM_POS_PWM", "PB9": "PUMP_OUT",
})
stm_pins.update({n: "GND" for n in ("18", "31", "47", "63")})
stm_pins.update({n: "+3V3" for n in ("19", "32", "48", "64")})
mcu.add("U3", STM, "STM32F103RBT6", "Package_QFP:LQFP-64_10x10mm_P0.5mm", stm_pins)
for i, n in enumerate(range(20, 24)):
    mcu.c("C%d" % n, "100nF", "+3V3", "GND")
mcu.c("C24", "4.7uF", "+3V3", "GND")
mcu.add("L2", "Device:L", "10uH", "Inductor_SMD:L_0805_2012Metric", {1: "+3V3", 2: "VDDA"})
mcu.c("C25", "1uF", "VDDA", "GND")
mcu.c("C26", "100nF", "VDDA", "GND")
mcu.c("C27", "100nF", "NRST", "GND")
mcu.r("R10", "10k", "BOOT0", "GND")
mcu.r("R11", "4.7k", "BOOT1", "GND")
mcu.add("Y1", "Device:Crystal", "8MHz", "Crystal:Crystal_SMD_5032-2Pin_5.0x3.2mm", {1: "OSC_IN", 2: "OSC_OUT"})
mcu.c("C28", "22pF", "OSC_IN", "GND")
mcu.c("C29", "22pF", "OSC_OUT", "GND")
mcu.add("Y2", "Device:Crystal", "32.768kHz", "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm", {1: "OSC32_IN", 2: "OSC32_OUT"})
mcu.c("C30", "10pF", "OSC32_IN", "GND")
mcu.c("C31", "10pF", "OSC32_OUT", "GND")
mcu.add("LED1", "Device:LED", "PWR green", "LED_SMD:LED_0805_2012Metric", {1: "GND", 2: "LED1_A"})
mcu.r("R12", "470", "+3V3", "LED1_A")
mcu.add("LED2", "Device:LED", "STATUS", "LED_SMD:LED_0805_2012Metric", {1: "LED_OUT", 2: "LED2_A"})
mcu.r("R13", "1k", "+3V3", "LED2_A")
mcu.add("J1", "Connector_Generic:Conn_01x05", "SWD", "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
        {1: "+3V3", 2: "SWDIO", 3: "SWCLK", 4: "NRST", 5: "GND"})
mcu.r("R14", "10k", "BOARD_ID", "GND")          # HW_BOLT detection strap (PB4)
flag(mcu, 8, "VDDA")

# =========================================================================
# 4.3-4.4, 4.7, 5  GATE INTERFACE (CN2)
# =========================================================================
gi = Sheet("gate_if", "gate_if.kicad_sch", "Gate interface")
cn2 = {1: "GND", 2: "GND", 3: "+5V", 4: "+5V", 5: "GND", 6: "GND", 7: "HEALTH1", 8: "HEALTH2", 9: "HEALTH3",
       10: "HEALTH4", 11: "GB_PWM_UH", 12: "GB_PWM_UL", 13: "GB_PWM_VH", 14: "GB_PWM_VL", 15: "GB_PWM_WH",
       16: "GB_PWM_WL", 17: "NTC_U", 18: "GB_UDC", 19: "NTC_V", 20: "GB_AUX", 21: "NTC_W", 22: "GATE_FLT",
       23: "GND", 24: "ISNS_U", 25: "GND", 26: "ISNS_W", 27: "ISNS_V", 28: "+5V_A", 29: "+5V_A", 30: "GND",
       31: "+12V_GATE", 32: "GND", 33: "+12V_GATE", 34: "GND", 35: "+12V_GATE", 36: "IGN_SENSE",
       37: "+12V_GATE", 38: "IGN_SENSE", 39: "GND", 40: "GND"}
gi.add("CN2", "Connector_Generic:Conn_02x20_Odd_Even", "SSW-120-01-T-D-LL", "Bolt:CN2_2x20_P2.54_Receptacle_Back", cn2)
gi.r("R20", "124k", "IGN", "IGN_SENSE")          # replicates OEM ~125k ignition sense
gi.add("U4", "74xx:74LS573", "74HCT573", SOIC20W, {
    1: "GND", 2: "PWM_UH_3V", 3: "PWM_UL_3V", 4: "PWM_VH_3V", 5: "PWM_VL_3V", 6: "PWM_WH_3V", 7: "PWM_WL_3V",
    8: "GND", 9: "GND", 10: "GND", 11: "+5V", 12: "NC", 13: "NC", 14: "GB_PWM_WL", 15: "GB_PWM_WH",
    16: "GB_PWM_VL", 17: "GB_PWM_VH", 18: "GB_PWM_UL", 19: "GB_PWM_UH", 20: "+5V"})
gi.c("C40", "100nF", "+5V", "GND")
RA = "Resistor_SMD:R_Array_Convex_4x0603"
gi.add("RN1", "Device:R_Pack04", "4x10k", RA, {1: "GND", 2: "GND", 3: "GND", 4: "GND",
                                               8: "PWM_UH_3V", 7: "PWM_UL_3V", 6: "PWM_VH_3V", 5: "PWM_VL_3V"})
gi.add("RN2", "Device:R_Pack04", "4x10k", RA, {1: "GND", 2: "GND", 3: "GND", 4: "GND",
                                               8: "PWM_WH_3V", 7: "PWM_WL_3V", 6: "NC", 5: "NC"})
# status lines: 100k fail-safe pull-down, 560R + 10nF filter (V6 values)
for i, sig in enumerate(["GATE_FLT", "HEALTH1", "HEALTH2", "HEALTH3", "HEALTH4"]):
    gi.r("R%d" % (21 + 2 * i), "100k", sig, "GND")
    gi.r("R%d" % (22 + 2 * i), "560", sig, sig + "_F")
    gi.c("C%d" % (41 + i), "10nF", sig + "_F", "GND")
gi.add("U5", "74xx:74LS21", "74HC21", SOIC14, {
    1: "HEALTH1_F", 2: "HEALTH2_F", 4: "HEALTH3_F", 5: "HEALTH4_F", 6: "GATE_OK_5V",
    9: "GND", 10: "GND", 12: "GND", 13: "GND", 8: "NC", 7: "GND", 14: "+5V"})
gi.c("C46", "100nF", "+5V", "GND")
gi.r("R31", "10k", "GATE_OK_5V", "GATE_OK")
gi.r("R32", "20k", "GATE_OK", "GND")
# Hardware trip: PWM_INHIBIT = NAND(GATE_OK_5V, GATE_FLT_F, OCUR_OK). GATE_OK_5V is U5's AND of
# HEALTH1-4, so this is the same logic as the earlier 8-input NAND. HCT so the 3.3 V OCUR_OK level
# is valid at 5 V (owner: 74HCT10 instead of CD74HCT30, which JLCPCB doesn't stock).
gi.add("U6", "74xx:74LS10", "74HCT10", SOIC14, {
    1: "GATE_OK_5V", 2: "GATE_FLT_F", 13: "OCUR_OK", 12: "PWM_INHIBIT",
    3: "GND", 4: "GND", 5: "GND", 6: "NC", 9: "GND", 10: "GND", 11: "GND", 8: "NC", 7: "GND", 14: "+5V"})
gi.c("C47", "100nF", "+5V", "GND")
gi.r("R33", "1k", "GATE_FLT_F", "GATE_FLT_MCU")
# 4.7 DC bus voltage from CN2 18 (assumed), pin 20 held low
gi.r("R34", "33k", "GB_UDC", "UDC_DIV")
gi.r("R35", "10k", "UDC_DIV", "GND")
gi.add("D2", "Diode:BAT54S", "BAT54S", "Package_TO_SOT_SMD:SOT-23", {1: "GND", 2: "+3V3", 3: "UDC_DIV"})
gi.r("R36", "3.3k", "UDC_DIV", "UDC")
gi.c("C48", "1nF", "UDC", "GND")
gi.r("R37", "10k", "GB_AUX", "GND")
gi.add("TP1", "Connector:TestPoint", "GB_AUX", "TestPoint:TestPoint_Pad_D1.5mm", {1: "GB_AUX"})
gi.add("TP2", "Connector:TestPoint", "GB_UDC", "TestPoint:TestPoint_Pad_D1.5mm", {1: "GB_UDC"})

# =========================================================================
# 4.5, 4.6, 4.9  ANALOG: current sense, overcurrent window, temperature mux
# =========================================================================
an = Sheet("analog", "analog.kicad_sch", "Current sense, overcurrent, temperature")
OPA = "Amplifier_Operational:MCP6002-xSN"
for ph, rr, cc, adc in [("U", 40, 50, "IL1"), ("V", 43, 52, "IL2"), ("W", 46, 55, "IW_S")]:
    an.r("R%d" % rr, "1k", "ISNS_%s" % ph, "ISNS_%s_F" % ph)
    an.c("C%d" % cc, "4.7nF", "ISNS_%s_F" % ph, "GND")
    an.r("R%d" % (rr + 1), "2.7k", "ISNS_%s_BUF" % ph, adc)
    an.r("R%d" % (rr + 2), "4.7k", adc, "GND")
    an.c("C%d" % (cc + 1), "1nF", adc, "GND")
an.add("U7", OPA, "MCP6292", SOIC8, {3: "ISNS_U_F", 2: "ISNS_U_BUF", 1: "ISNS_U_BUF",
                                     5: "ISNS_V_F", 6: "ISNS_V_BUF", 7: "ISNS_V_BUF", 8: "+5V_A", 4: "GND"})
an.add("U8", OPA, "MCP6292", SOIC8, {3: "ISNS_W_F", 2: "ISNS_W_BUF", 1: "ISNS_W_BUF",
                                     5: "GND", 6: "U8B_OUT", 7: "U8B_OUT", 8: "+5V_A", 4: "GND"})
an.c("C54", "100nF", "+5V_A", "GND")
an.c("C57", "100nF", "+5V_A", "GND")
an.r("R49", "10k", "OCURLIM_NEG_PWM", "OCUR_NEG")
an.c("C58", "1uF", "OCUR_NEG", "GND")
an.r("R50", "10k", "OCURLIM_POS_PWM", "OCUR_POS")
an.c("C59", "1uF", "OCUR_POS", "GND")
CMP = "Comparator:LM2901"
an.add("U9", CMP, "LM2901", SOIC14, {5: "IL1", 4: "OCUR_NEG", 2: "OCUR_OK",
                                     7: "IL2", 6: "OCUR_NEG", 1: "OCUR_OK",
                                     11: "OCUR_POS", 10: "IL1", 13: "OCUR_OK",
                                     9: "OCUR_POS", 8: "IL2", 14: "OCUR_OK", 3: "+5V", 12: "GND"})
an.add("U10", CMP, "LM2901", SOIC14, {5: "IW_S", 4: "OCUR_NEG", 2: "OCUR_OK",
                                      7: "OCUR_POS", 6: "IW_S", 1: "OCUR_OK",
                                      11: "+3V3", 10: "GND", 13: "NC",
                                      9: "+3V3", 8: "GND", 14: "NC", 3: "+5V", 12: "GND"})
an.c("C60", "100nF", "+5V", "GND")
an.c("C61", "100nF", "+5V", "GND")
an.r("R51", "10k", "OCUR_OK", "+3V3")
an.add("U11", "Analog_Switch:CD4052B", "74HCT4052", SOIC16, {
    12: "MOT_TEMP", 14: "GND", 15: "GND", 11: "GND", 13: "TMPM",
    1: "NTC_U", 5: "NTC_V", 2: "NTC_W", 4: "GND", 3: "TMPHS",
    10: "MUX_S0", 9: "MUX_S1", 6: "GND", 7: "GND", 8: "GND", 16: "+5V"})
an.c("C62", "100nF", "+5V", "GND")
for i, (sig, rv) in enumerate([("NTC_U", "4.7k"), ("NTC_V", "4.7k"), ("NTC_W", "4.7k"),
                               ("MOT_TEMP", "2.2k")]):
    an.r("R%d" % (52 + i), rv, "+3V3", sig)
    an.c("C%d" % (63 + i), "1uF", sig, "GND")

# =========================================================================
# 4.8  POSITION SENSOR: software-resolver exciter + sin/cos receivers, encoder option
# =========================================================================
rs = Sheet("resolver", "resolver.kicad_sch", "Resolver / encoder")
rs.r("R60", "0R", "POS_Z", "EXC_SQ")                                   # RES option
rs.r("R61", "10k", "EXC_SQ", "EXC_F1")
rs.c("C70", "3.3nF", "EXC_F1", "GND")
rs.r("R62", "10k", "EXC_F1", "EXC_SK1")
rs.r("R63", "10k", "EXC_SK1", "EXC_SK2")
rs.c("C71", "4.7nF", "EXC_SK1", "EXC_SIN")
rs.c("C72", "2.2nF", "EXC_SK2", "GND")
rs.add("U12", OPA, "MCP6292", SOIC8, {3: "EXC_SK2", 2: "EXC_SIN", 1: "EXC_SIN",
                                      5: "VREF_DIV", 6: "VREF_1V65", 7: "VREF_1V65", 8: "+5V", 4: "GND"})
rs.c("C75", "100nF", "+5V", "GND")
rs.r("R64", "10k", "+3V3", "VREF_DIV")
rs.r("R65", "10k", "VREF_DIV", "GND")
rs.c("C73", "100nF", "VREF_DIV", "GND")
rs.c("C76", "1uF", "EXC_SIN", "EXC_AC")
rs.r("R67", "10k", "VCC_12V", "EXC_VB")
rs.r("R68", "10k", "EXC_VB", "GND")
rs.c("C77", "10uF 25V", "EXC_VB", "GND", fp=C1206)
rs.r("R69", "100k", "EXC_VB", "EXC_AC")
# Exciter bridge: onsemi TCA0372DW dual 1 A power op-amp (owner: replaces the L272D, which
# JLCPCB doesn't stock). Pinout from the datasheet's DW pin drawing, cross-checked with a second
# source; GND pins 4/5/12/13 are also the heat path.
rs.add("U13", "Bolt:TCA0372", "TCA0372DW", "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm", {
    9: "EXC_AC", 10: "EXC_FBA", 16: "EXC_OA",
    8: "EXC_VB", 7: "EXC_FBB", 2: "EXC_OB",
    1: "VCC_12V", 4: "GND", 5: "GND", 12: "GND", 13: "GND",
    3: "NC", 6: "NC", 11: "NC", 14: "NC", 15: "NC"})
rs.r("R70", "20k", "EXC_OA", "EXC_FBA")
rs.r("R71", "10k", "EXC_FBA", "EXC_RGA")
rs.c("C78", "10uF 25V", "EXC_RGA", "GND", fp=C1206)
rs.r("R72", "10k", "EXC_OA", "EXC_FBB")
rs.r("R73", "10k", "EXC_OB", "EXC_FBB")
rs.c("C79", "100nF", "VCC_12V", "GND")
rs.c("C80", "10uF 25V", "VCC_12V", "GND", fp=C1206)
rs.c("C81", "10uF 25V", "EXC_OA", "EXC_OA_C", fp=C1206)
rs.r("R74", "10", "EXC_OA_C", "EXC_P", fp=R1206)
rs.r("R75", "10", "EXC_OB", "EXC_N", fp=R1206)
# sin/cos differential receivers on 3.3 V (output can't exceed the ADC range)
rs.r("R76", "10k", "SIN_P", "SIN_INP")
rs.r("R77", "10k", "SIN_N", "SIN_INN")
rs.r("R78", "4.7k", "SIN_INN", "RES_SIN")
rs.r("R79", "4.7k", "SIN_INP", "VREF_1V65")
rs.c("C82", "1nF", "SIN_INN", "RES_SIN")
rs.r("R80", "10k", "COS_P", "COS_INP")
rs.r("R81", "10k", "COS_N", "COS_INN")
rs.r("R82", "4.7k", "COS_INN", "RES_COS")
rs.r("R83", "4.7k", "COS_INP", "VREF_1V65")
rs.c("C83", "1nF", "COS_INN", "RES_COS")
rs.add("U14", OPA, "MCP6292", SOIC8, {3: "SIN_INP", 2: "SIN_INN", 1: "RES_SIN",
                                      5: "COS_INP", 6: "COS_INN", 7: "RES_COS", 8: "+3V3", 4: "GND"})
rs.c("C84", "100nF", "+3V3", "GND")
rs.r("R84", "100", "RES_SIN", "RES_SIN_F")
rs.c("C85", "1nF", "RES_SIN_F", "GND")
rs.r("R85", "0R", "RES_SIN_F", "POS_A")                                # RES option
rs.r("R86", "100", "RES_COS", "RES_COS_F")
rs.c("C86", "1nF", "RES_COS_F", "GND")
rs.r("R87", "0R", "RES_COS_F", "POS_B")                                # RES option
# encoder option (populate R89/R91/R93, depopulate R60/R85/R87)
for i, (sig, pos) in enumerate([("A", "POS_A"), ("B", "POS_B"), ("Z", "POS_Z")]):
    rs.r("R%d" % (88 + 2 * i), "10k", "ENC_%s_IN" % sig, "ENC_%s_F" % sig)
    rs.c("C%d" % (87 + i), "1nF", "ENC_%s_F" % sig, "GND")
    rs.r("R%d" % (89 + 2 * i), "0R", "ENC_%s_F" % sig, pos, dnp=True)

# =========================================================================
# 4.10-4.12, 6  VEHICLE: CN1, inputs, outputs, CAN
# =========================================================================
vh = Sheet("vehicle", "vehicle.kicad_sch", "Vehicle connector and I/O")
CN1_NETS = {
    "A1": "THR1_IN", "A2": "THR2_IN", "A3": "PEDAL_5V", "A4": "GND",
    "B1": "EXC_N", "B2": "EXC_P", "B3": "PUMP_OUT_SW", "B4": "FWD_12V",
    "C1": "SIN_N", "C2": "SIN_P", "C3": "REV_12V", "C4": "BRAKE_12V",
    "D1": "COS_N", "D2": "COS_P", "D3": "START_12V", "D4": "CRUISE_12V",
    "E1": "MAIN_CONT_OUT", "E2": "PRECHG_OUT_SW", "E3": "CAN_L", "E4": "CAN_H",
    "F1": "NC", "F2": "NC", "F3": "CAN_L", "F4": "CAN_H",
    "G1": "NC", "G2": "NC", "G3": "NC", "G4": "NC",
    "H1": "NC", "H2": "NC", "H3": "NC", "H4": "NC",
    "J1": "MOT_TEMP", "J2": "GND", "J3": "NC", "J4": "NC",
    "K1": "ENC_A_IN", "K2": "GND", "K3": "ENC_B_IN", "K4": "ENC_Z_IN",
    "L1": "NC", "L2": "ENC_5V", "L3": "IGN", "L4": "NC",
    "M1": "VBAT", "M2": "NC", "M3": "GND", "M4": "VBAT",
}
CN1_LABELS = {  # pin names shown on the symbol (OEM function in brackets where reserved)
    "F1": "RSVD(aux pump ctl)", "F2": "RSVD(aux pump fb)", "G1": "RSVD(HVIL ref)", "G2": "RSVD(HVIL sig)",
    "G3": "RSVD(CAN3-)", "G4": "RSVD(CAN3+)",
    "H1": "RSVD(TFT sig)", "H2": "RSVD(TFT ref)", "H3": "RSVD(CAN3-)", "H4": "RSVD(CAN3+)",
    "J3": "RSVD(CAN2-)", "J4": "RSVD(CAN2+)", "L1": "RSVD(IMS A)", "L4": "RSVD(IMS B)", "M2": "RSVD(wake)",
}
vh.add("CN1", "Bolt:CN1_GM48", "GM X1 48-way", "Bolt:CN1_GM_48pos_4x12", CN1_NETS)
for i, s in enumerate(["FWD", "REV", "BRAKE", "START", "CRUISE"]):
    vh.r("R%d" % (100 + 2 * i), "4.7k", "%s_12V" % s, "%s_IN" % s)
    vh.r("R%d" % (101 + 2 * i), "1.5k", "%s_IN" % s, "GND")
    vh.c("C%d" % (100 + i), "1uF", "%s_IN" % s, "GND")
# No emergency-stop / motor-protection inputs on this board (no connector for them): the
# firmware's inputs are held at "OK" (high) by pull-ups.
for i, s in enumerate(["EMCYSTOP", "MPROT"]):
    vh.r("R%d" % (111 + 2 * i), "10k", "%s_IN" % s, "+3V3")
for i, (s, adc) in enumerate([("THR1", "THROTTLE1"), ("THR2", "THROTTLE2")]):
    vh.r("R%d" % (114 + 2 * i), "10k", "%s_IN" % s, adc)
    vh.r("R%d" % (115 + 2 * i), "10k", "%s_IN" % s, "GND")
    vh.c("C%d" % (107 + i), "1uF", adc, "GND")
vh.add("F1", "Device:Polyfuse", "50mA", FUSE, {1: "+5V", 2: "PEDAL_5V"})
vh.add("F2", "Device:Polyfuse", "200mA", FUSE, {1: "+5V", 2: "ENC_5V"})
for i, (inp, out) in enumerate([("DCSW_OUT", "MAIN_CONT_OUT"), ("PRECHARGE_OUT", "PRECHG_OUT_SW"),
                                ("PUMP_OUT", "PUMP_OUT_SW")]):
    vh.add("U%d" % (20 + i), "Bolt:BTS133TC", "BTS133TC", "Package_TO_SOT_SMD:TO-263-2", {1: inp, 2: out, 3: "GND"})
    vh.r("R%d" % (120 + i), "10k", inp, "GND")          # keep outputs off while the MCU is in reset
vh.add("U23", "Interface_CAN_LIN:SN65HVD234", "SN65HVD234", SOIC8,
       {1: "CAN_TX", 2: "GND", 3: "+3V3", 4: "CAN_RX", 5: "+3V3", 6: "CAN_L", 7: "CAN_H", 8: "GND"})
vh.c("C109", "100nF", "+3V3", "GND")
vh.r("R123", "120", "CAN_H", "CAN_TERM")
vh.r("R124", "0R", "CAN_TERM", "CAN_L")                # remove to disable termination

# =========================================================================
# 4.12  WIFI (ESP32)
# =========================================================================
wf = Sheet("wifi", "wifi.kicad_sch", "WiFi (ESP32)")
ESP = "RF_Module:ESP32-WROOM-32"
# As Tesla V6 IC14: ESP32-WROOM-32E (M113EH2800PH3Q0, PCB antenna); same land pattern as WROOM-32
wf.add("U30", ESP, "ESP32-WROOM-32E", "RF_Module:ESP32-WROOM-32",
       nc_rest(ESP, {1: "GND", 2: "ESP_3V3", 3: "ESP_EN", 25: "ESP_IO0", 34: "USART_TX", 35: "USART_RX",
                     15: "GND", 38: "GND", 39: "GND"}))
wf.add("L30", "Device:L", "10uH", "Inductor_SMD:L_0805_2012Metric", {1: "+3V3", 2: "ESP_3V3"})
wf.c("C120", "10uF", "ESP_3V3", "GND", fp=C1206)
wf.c("C121", "100nF", "+3V3", "GND")              # V6 C11 sits on the 3.3 V side of the inductor
wf.r("R130", "4.7k", "ESP_3V3", "ESP_EN")
wf.c("C122", "100nF", "ESP_EN", "GND")
wf.add("J4", "Connector_Generic:Conn_01x06", "ESP PROG", "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
       {1: "ESP_IO0", 2: "GND", 3: "GND", 4: "+5V", 5: "USART_RX", 6: "USART_TX"})

SHEETS = [pw, mcu, gi, an, rs, vh, wf]


# =========================================================================
# custom symbols (Bolt.kicad_sym)
# =========================================================================
def _pin(kind, x, y, ang, name, num, length=2.54):
    from kisym import Q
    f = ["effects", ["font", ["size", "1.27", "1.27"]]]
    return ["pin", kind, "line", ["at", str(x), str(y), str(ang)], ["length", str(length)],
            ["name", Q(name), f], ["number", Q(num), f]]


def _symbol(name, ref, value, fp, body, pins, desc):
    from kisym import Q
    f = ["effects", ["font", ["size", "1.27", "1.27"]]]
    fh = ["effects", ["font", ["size", "1.27", "1.27"]], "hide"]
    x0, y0, x1, y1 = body
    return ["symbol", Q(name), ["in_bom", "yes"], ["on_board", "yes"],
            ["property", Q("Reference"), Q(ref), ["at", str(x0), str(y1 + 1.27), "0"], f],
            ["property", Q("Value"), Q(value), ["at", str(x0), str(y0 - 1.27), "0"], f],
            ["property", Q("Footprint"), Q(fp), ["at", "0", "0", "0"], fh],
            ["property", Q("Datasheet"), Q("~"), ["at", "0", "0", "0"], fh],
            ["property", Q("Description"), Q(desc), ["at", "0", "0", "0"], fh],
            ["symbol", Q(name + "_0_1"),
             ["rectangle", ["start", str(x0), str(y1)], ["end", str(x1), str(y0)],
              ["stroke", ["width", "0.254"], ["type", "default"]], ["fill", ["type", "background"]]]],
            ["symbol", Q(name + "_1_1")] + pins]


def write_custom_symbols(path):
    from kisym import dump
    syms = []
    # BTS133TC: Infineon HITFET low-side switch, pinout from the Tesla V6 schematic
    syms.append(_symbol("BTS133TC", "U", "BTS133TC", "Package_TO_SOT_SMD:TO-263-2", (-5.08, -3.81, 5.08, 3.81),
                        [_pin("input", -7.62, 0, 0, "IN", "1"), _pin("passive", 0, 6.35, 270, "D", "2"),
                         _pin("passive", 0, -6.35, 90, "S", "3")],
                        "Smart low-side power switch (HITFET), TO-263"))
    # TCA0372 (onsemi, DW = SOIC-16W): dual power op-amp, one box
    syms.append(_symbol("TCA0372", "U", "TCA0372DW", "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
                        (-7.62, -10.16, 7.62, 10.16),
                        [_pin("input", -10.16, 7.62, 0, "+INA", "9"), _pin("input", -10.16, 5.08, 0, "-INA", "10"),
                         _pin("input", -10.16, -2.54, 0, "+INB", "8"), _pin("input", -10.16, -5.08, 0, "-INB", "7"),
                         _pin("output", 10.16, 6.35, 180, "OUTA", "16"), _pin("output", 10.16, -3.81, 180, "OUTB", "2"),
                         _pin("power_in", 0, 12.7, 270, "VCC", "1"),
                         _pin("power_in", -3.81, -12.7, 90, "GND", "4"), _pin("power_in", -1.27, -12.7, 90, "GND", "5"),
                         _pin("power_in", 1.27, -12.7, 90, "GND", "12"), _pin("power_in", 3.81, -12.7, 90, "GND", "13"),
                         _pin("no_connect", 10.16, 8.89, 180, "NC", "15"), _pin("no_connect", 10.16, 3.81, 180, "NC", "3"),
                         _pin("no_connect", 10.16, 1.27, 180, "NC", "6"), _pin("no_connect", 10.16, -1.27, 180, "NC", "11"),
                         _pin("no_connect", 10.16, -6.35, 180, "NC", "14")],
                        "Dual power operational amplifier, 1 A, single or split supply up to 40 V"))
    # CN1: GM X1 48-way header; pin numbers = footprint pad names (A1..M4)
    order = ["%s%d" % (r, c) for r in "ABCDEFGHJKLM" for c in (1, 2, 3, 4)]
    pins = []
    for i, num in enumerate(order):
        left = i < 24
        k = i if left else i - 24
        y = 29.21 - 2.54 * k
        name = CN1_LABELS.get(num, CN1_NETS[num])
        pins.append(_pin("passive", -15.24 if left else 15.24, round(y, 2), 0 if left else 180,
                         "%s %s" % (num, name), num, 5.08))
    syms.append(_symbol("CN1_GM48", "CN", "GM X1 48-way", "Bolt:CN1_GM_48pos_4x12",
                        (-10.16, -31.75, 10.16, 31.75), pins,
                        "Bolt inverter external connector (GM 98993-5021 mating), rows A-M (no I), columns 1-4"))
    tree = ["kicad_symbol_lib", ["version", "20220914"], ["generator", "kicad_symbol_editor"]] + syms
    open(path, "w").write(dump(tree) + "\n")
