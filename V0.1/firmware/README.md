# Firmware for the Bolt logic board v0.1

These are compiled builds of OpenInverter stm32-sine **5.41** with the **HW_BOLT** hardware
variant (`hwver` = 11). Source: [PSMangelsdorf/stm32-sine](https://github.com/PSMangelsdorf/stm32-sine),
`master` at commit `3fb6c52` (the merged hw-bolt branch). There is one build each for
**SINE** and **FOC**.

**Not yet tested on hardware. Bench only, no high voltage.**

## Which file to use

| You want | File | Address |
|----|----|----|
| First-time SWD flash, SINE | `bolt_v0.1_sine_with_bootloader.hex` | in the file |
| First-time SWD flash, FOC | `bolt_v0.1_foc_with_bootloader.hex` | in the file |
| Same, as raw binary | `bolt_v0.1_*_with_bootloader.bin` | 0x08000000 |
| Later updates over WiFi (web interface → UPDATE) | `stm32_sine.bin` or `stm32_foc.bin` | handled by the bootloader |
| Pieces separately | `stm32_loader.*` (bootloader) | 0x08000000 |
| | `stm32_sine.*` / `stm32_foc.*` | 0x08001000 |

The `_with_bootloader` images are the OpenInverter bootloader, padded to 4 KB, followed by the
firmware. Flash only one variant; a later flash replaces it.

## How they were built

- **Firmware**
  - `make get-deps`, then `make CONTROL=SINE clean all` and `make CONTROL=FOC clean all`
  - arm-none-eabi-gcc 13.2.1, libopencm3 `5ba1bb5`, libopeninv `78e3f72`
  - Sizes: SINE 57,144 bytes, FOC 56,756 bytes (STM32F103RB: 128 KB)
- **Host unit tests:** `make Test`; `test/test_sine` and `libopeninv/test/test_libopeninv` all pass,
  including the HW_BOLT tests.
- **Bootloader**
  - [jsphuebner/tumanako-inverter-fw-bootloader](https://github.com/jsphuebner/tumanako-inverter-fw-bootloader)
    `d131ea2`, default `HWCONFIG_OLIMEX`
  - USART3 on PB10/PB11, 115200 8N2, 8 MHz crystal, which matches this board
  - Size 2,760 bytes

`SHA256SUMS.txt` lists a checksum for every file.

GitHub Actions are switched off on the stm32-sine fork, so these builds were made outside it.
Turning them on (fork → Actions tab → enable) makes the fork's existing CI workflow build both
variants on every push.
