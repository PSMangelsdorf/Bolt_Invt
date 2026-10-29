"""Proposed JLCPCB / LCSC part for every BOM line (prototype v0.1). FOR OWNER APPROVAL.

Key: (value, footprint name) exactly as in the netlist. Each entry:
    lcsc   - LCSC / JLCPCB part number, or "" when JLC can't place it
    mpn    - manufacturer part number
    spec   - what was chosen (rating, dielectric, ...)
    src    - where the number was checked:
             "lcsc"   - an LCSC / JLCPCB listing found by search or fetched (title shows this MPN)
             "v6"     - taken from the Tesla V6 JLC BOM (tesla-drive-unit/V6/Tesla_V6_BOM_JLC.xls),
                        not independently confirmed
    fit    - "smt" JLC places it; "hand" solder it yourself after delivery (or order it through
             JLC Global Sourcing); "none" nothing to place (DNP, test pad, mounting hole)
    note   - anything the owner should look at

Stock and Basic/Extended status change daily; JLCPCB shows both when the BOM is uploaded.
"""

PARTS = {
    # ---------------------------------------------------------------- resistors 0805 (UNI-ROYAL, 1 %)
    ("0R", "R_0805_2012Metric"): ("C17477", "0805W8F0000T5E", "0 ohm jumper", "lcsc", "smt", ""),
    ("100", "R_0805_2012Metric"): ("C17408", "0805W8F1000T5E", "100 ohm 1%", "lcsc", "smt", ""),
    ("120", "R_0805_2012Metric"): ("C17437", "0805W8F1200T5E", "120 ohm 1% (CAN termination)", "lcsc", "smt", ""),
    ("470", "R_0805_2012Metric"): ("C17710", "0805W8F4700T5E", "470 ohm 1%", "lcsc", "smt", ""),
    ("560", "R_0805_2012Metric"): ("C28636", "0805W8F5600T5E", "560 ohm 1%", "lcsc", "smt", ""),
    ("1k", "R_0805_2012Metric"): ("C17513", "0805W8F1001T5E", "1 k 1%", "lcsc", "smt", ""),
    ("1.5k", "R_0805_2012Metric"): ("C4310", "0805W8F1501T5E", "1.5 k 1%", "lcsc", "smt", ""),
    ("2.2k", "R_0805_2012Metric"): ("C17520", "0805W8F2201T5E", "2.2 k 1%", "lcsc", "smt", ""),
    ("2.7k", "R_0805_2012Metric"): ("C17530", "0805W8F2701T5E", "2.7 k 1%", "lcsc", "smt", ""),
    ("3.3k", "R_0805_2012Metric"): ("C26010", "0805W8F3301T5E", "3.3 k 1%", "lcsc", "smt", ""),
    ("4.7k", "R_0805_2012Metric"): ("C17673", "0805W8F4701T5E", "4.7 k 1%", "lcsc", "smt", ""),
    ("6.8k", "R_0805_2012Metric"): ("C17772", "0805W8F6801T5E", "6.8 k 1%", "lcsc", "smt", ""),
    ("10k", "R_0805_2012Metric"): ("C17414", "0805W8F1002T5E", "10 k 1%", "lcsc", "smt", ""),
    ("20k", "R_0805_2012Metric"): ("C4328", "0805W8F2002T5E", "20 k 1%", "lcsc", "smt", ""),
    ("33k", "R_0805_2012Metric"): ("C17633", "0805W8F3302T5E", "33 k 1%", "lcsc", "smt", ""),
    ("100k", "R_0805_2012Metric"): ("C149504", "0805W8F1003T5E", "100 k 1%", "lcsc", "smt", ""),
    ("124k", "R_0805_2012Metric"): ("C4135024", "CRCW0805124KFKEA", "124 k 1% (Vishay)", "lcsc", "smt",
                                    "only 124 k 0805 found; check stock"),
    ("0R (DNP)", "R_0805_2012Metric"): ("", "", "not fitted", "", "none", "DNP"),
    # ---------------------------------------------------------------- resistors 1206 / arrays
    ("0R", "R_1206_3216Metric"): ("C17888", "1206W4F0000T5E", "0 ohm jumper 1206", "lcsc", "smt", ""),
    ("10", "R_1206_3216Metric"): ("C17903", "1206W4F100JT5E", "10 ohm 5% 1206", "lcsc", "smt", ""),
    ("4x10k", "R_Array_Convex_4x0603"): ("C29718", "4D03WGJ0103T5E", "4 x 10 k convex array", "lcsc", "smt",
                                         "same part as V6"),
    # ---------------------------------------------------------------- capacitors 0805
    ("10pF", "C_0805_2012Metric"): ("C157608", "0805CG100J500NT", "10 pF C0G 50 V", "lcsc", "smt", ""),
    ("22pF", "C_0805_2012Metric"): ("C24658", "0805CG220J500NT", "22 pF C0G 50 V", "lcsc", "smt", ""),
    ("1nF", "C_0805_2012Metric"): ("C46653", "CL21B102KBCNNNC", "1 nF X7R 50 V", "lcsc", "smt", "same part as V6"),
    ("2.2nF", "C_0805_2012Metric"): ("C51795", "0805CG222J500NT", "2.2 nF C0G 50 V", "lcsc", "smt",
                                     "C0G proposed: exciter sine filter"),
    ("3.3nF", "C_0805_2012Metric"): ("C77062", "GRM2165C1H332JA01D", "3.3 nF C0G 50 V (Murata)", "lcsc", "smt",
                                     "C0G proposed: exciter sine filter"),
    ("4.7nF", "C_0805_2012Metric"): ("C77063", "GRM2165C1H472JA01D", "4.7 nF C0G 50 V (Murata)", "lcsc", "smt",
                                     "C0G proposed: exciter filter and current-sense filters"),
    ("10nF", "C_0805_2012Metric"): ("C1710", "CL21B103KBANNNC", "10 nF X7R 50 V", "lcsc", "smt", "same part as V6"),
    ("100nF", "C_0805_2012Metric"): ("C49678", "CC0805KRX7R9BB104", "100 nF X7R 50 V", "lcsc", "smt",
                                     "same part as V6; 50 V because some sit on 12 V rails"),
    ("1uF", "C_0805_2012Metric"): ("C28323", "CL21B105KBFNNNE", "1 uF X7R 50 V", "lcsc", "smt", "same part as V6"),
    ("4.7uF", "C_0805_2012Metric"): ("C1779", "CL21A475KAQNNNE", "4.7 uF X5R 25 V", "lcsc", "smt", ""),
    # ---------------------------------------------------------------- capacitors 1206
    ("10uF", "C_1206_3216Metric"): ("C9807", "CL31A106KAHNNNE", "10 uF X5R 25 V", "lcsc", "smt", "5 V / 3.3 V rails"),
    ("10uF 25V", "C_1206_3216Metric"): ("C9807", "CL31A106KAHNNNE", "10 uF X5R 25 V", "lcsc", "smt", ""),
    ("10uF 50V", "C_1206_3216Metric"): ("C13585", "CL31A106KBHNNNE", "10 uF X5R 50 V", "lcsc", "smt", ""),
    ("22uF", "C_1206_3216Metric"): ("C12891", "CL31A226KAHNNNE", "22 uF X5R 25 V", "lcsc", "smt", ""),
    # ---------------------------------------------------------------- inductors, ferrite, fuses
    ("6.8uH", "L_Bourns_SRN6045TA"): ("C2041457", "SRN6045TA-6R8M", "6.8 uH 20% (Bourns)", "lcsc", "smt", ""),
    ("10uH", "L_0805_2012Metric"): ("C88182", "MLZ2012N100LT000", "10 uH 0805, DCR 0.3 ohm (TDK)", "lcsc", "smt",
                                    "L30 feeds the ESP32 (~0.5 A transmit peaks): no 0805 10 uH part is "
                                    "really rated for that. V6 used a 0603 10 uH (C1035) here. Review"),
    ("600R@100MHz 1A", "L_0805_2012Metric"): ("C1017", "GZ2012D601TF", "600 ohm @ 100 MHz, 500 mA, 0.3 ohm",
                                              "lcsc", "smt",
                                              "rated 500 mA, not the 1 A in the value field; the +5V_A load "
                                              "(gate-board current sensors) is well under that"),
    ("50mA", "Fuse_1206_3216Metric"): ("C315892", "1206L005/60WR", "PPTC 50 mA hold, 60 V (Littelfuse)", "lcsc",
                                       "smt", ""),
    ("200mA", "Fuse_1206_3216Metric"): ("C207035", "1206L020YR", "PPTC 200 mA hold, 24 V (Littelfuse)", "lcsc",
                                        "smt", ""),
    # ---------------------------------------------------------------- crystals, LEDs
    ("8MHz", "Crystal_SMD_5032-2Pin_5.0x3.2mm"): ("C115962", "X50328MSB2GI", "8 MHz 5032 (YXC)", "lcsc", "smt",
                                                  "same part as V6"),
    ("32.768kHz", "Crystal_SMD_3215-2Pin_3.2x1.5mm"): ("C32346", "Q13FC13500004", "32.768 kHz, 12.5 pF (Epson)",
                                                       "lcsc", "smt",
                                                       "12.5 pF crystal with the board's 10 pF caps runs a little "
                                                       "fast (RTC only); no 7 pF version found at LCSC"),
    ("PWR green", "LED_0805_2012Metric"): ("C2297", "KT-0805G", "green 0805", "lcsc", "smt", ""),
    ("STATUS", "LED_0805_2012Metric"): ("C2297", "KT-0805G", "green 0805", "lcsc", "smt",
                                        "colour not specified; green proposed"),
    # ---------------------------------------------------------------- discretes
    ("SS54", "D_SMA"): ("C22452", "SS54", "40 V 5 A Schottky (MDD)", "lcsc", "smt", "same part as V6"),
    ("SMBJ26CA", "D_SMB"): ("C3719606", "SMBJ26CA", "26 V bidirectional TVS, 600 W (Bourns)", "lcsc", "smt", ""),
    ("BAT54S", "SOT-23"): ("C47546", "BAT54S,215", "dual Schottky, series (Nexperia)", "lcsc", "smt", ""),
    ("2N7002", "SOT-23"): ("C8545", "2N7002", "60 V N-MOSFET (JSCJ)", "lcsc", "smt", "new in v0.1: BTS443P input switch"),
    ("BTS6143D", "TO-252-4"): ("C95232", "BTS6143D", "PROFET high-side 10 mohm, PG-TO252-5-11 (Infineon)", "lcsc",
                               "smt", "owner: replaces BTS443P (same pinout and IN-to-GND input)"),
    ("BTS133TC", "TO-263-2"): ("C2681318", "BTS133TC (BTS133TCBUMA1)", "HITFET low-side, TO-263", "v6", "smt",
                               "owner: keep. Number from the V6 BOM, not found at LCSC: if JLCPCB can't "
                               "place it, hand-solder (Digi-Key / Farnell / RS)"),
    # ---------------------------------------------------------------- ICs
    ("AP63205WU", "TSOT-23-6"): ("C2071056", "AP63205WU-7", "5 V 2 A sync buck (Diodes)", "lcsc", "smt", ""),
    ("LD1117S33TR", "SOT-223-3_TabPin2"): ("C86781", "LD1117S33TR", "3.3 V LDO (ST)", "lcsc", "smt", ""),
    ("STM32F103RBT6", "LQFP-64_10x10mm_P0.5mm"): ("C8735", "STM32F103RBT6", "MCU", "lcsc", "smt", "same part as V6"),
    ("ESP32-WROOM-32E", "ESP32-WROOM-32"): ("C701341", "ESP32-WROOM-32E-N4", "WiFi module, PCB antenna", "lcsc",
                                            "smt", ""),
    ("74HCT573", "SOIC-20W_7.5x12.8mm_P1.27mm"): ("C5209384", "74HCT573D,653", "octal latch (Nexperia)", "lcsc",
                                                  "smt", "V6 BOM lists C5608, which LCSC shows as the HC part"),
    ("74HC21", "SOIC-14_3.9x8.7mm_P1.27mm"): ("C5617", "74HC21D,653", "dual 4-input AND (Nexperia)", "lcsc",
                                              "smt", ""),
    ("74HCT10", "SOIC-14_3.9x8.7mm_P1.27mm"): ("C547236", "74HCT10D,653", "triple 3-input NAND, HCT (Nexperia)",
                                               "lcsc", "smt", "owner: replaces CD74HCT30 (one gate used)"),
    ("LM2901", "SOIC-14_3.9x8.7mm_P1.27mm"): ("C7932", "LM2901DR", "quad comparator (TI)", "lcsc", "smt", ""),
    ("74HCT4052", "SOIC-16_3.9x9.9mm_P1.27mm"): ("C469908", "CD74HCT4052M96", "dual 4:1 analog mux, HCT (TI)",
                                                 "lcsc", "smt", ""),
    ("TCA0372DW", "SOIC-16W_7.5x10.3mm_P1.27mm"): ("C362060", "TCA0372DWR2G", "dual 1 A power op-amp (onsemi)",
                                                    "lcsc", "smt", "owner: replaces L272D (not stocked)"),
    ("MCP6292", "SOIC-8_3.9x4.9mm_P1.27mm"): ("C556929", "MCP6292-E/SN", "dual RRIO op-amp (Microchip)", "lcsc",
                                              "smt", "low stock at LCSC (38 in October 2026; 4 per board)"),
    ("SN65HVD234", "SOIC-8_3.9x4.9mm_P1.27mm"): ("C99818", "SN65HVD234DR", "3.3 V CAN transceiver (TI)", "lcsc",
                                                 "smt", ""),
    # ---------------------------------------------------------------- connectors / mechanical
    ("GM X1 48-way", "CN1_GM_48pos_4x12"): ("", "GM 48-way header (part not yet identified)", "vehicle connector",
                                            "", "hand", "hand-solder (owner); 1.0 mm placeholder holes"),
    ("SSW-120-01-T-D-LL", "CN2_2x20_P2.54_Receptacle_Back"): ("", "SSW-120-01-T-D-LL (Samtec)",
                                                              "2x20 receptacle, bottom side", "", "hand",
                                                              "hand-solder (owner)"),
    ("SWD", "PinHeader_1x05_P2.54mm_Vertical"): ("", "1x05 2.54 mm header", "SWD", "", "hand", "hand-solder"),
    ("ESP PROG", "PinHeader_1x06_P2.54mm_Vertical"): ("", "1x06 2.54 mm header", "ESP32 programming", "", "hand",
                                                      "hand-solder"),
    ("GB_AUX", "TestPoint_Pad_D1.5mm"): ("", "", "test pad", "", "none", ""),
    ("GB_UDC", "TestPoint_Pad_D1.5mm"): ("", "", "test pad", "", "none", ""),
}
