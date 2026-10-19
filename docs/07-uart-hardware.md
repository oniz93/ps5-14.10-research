# ps5-uart: hardware requirements and what the notes already contain

From `symbrkrs/ps5-uart`. Two halves that meet at one cable.

## Board requirements

| Requirement | Why |
|---|---|
| **RP2040** (not RP2350, not ESP32) | the UARTs are PIO-based (`uart/pio_uart.pio`) — PIO is RP2040 hardware |
| **GP0, GP1, GP2, GP3, GP8, GP9 broken out** | GP0/1 = EMC UART, GP2 = EMC ROM trigger, GP3 = EMC RESET#, GP8/9 = Titania UART |
| **USB** | three CDC interfaces: debug stdio (optional), EMC, Titania |
| **BOOTSEL button** | "the button on the pico will reset it to flash mode" — or short the pin manually |
| **3.3 V logic, common GND** | console header is 3.3 V |
| 2 MB flash | stock Pico; firmware is small |

**Do not buy a Pico 2 or Pico 2 W (RP2350).** Three specific reasons, strongest first:

1. **The board target is hard-coded.** `uart/CMakeLists.txt` contains `set(PICO_BOARD "pico")` — an RP2040 family ID. An RP2350 board will reject that UF2 outright. Fixable by editing one line and rebuilding, but you are then off the author's tested path.
2. **`pio_ = pio0;` is hard-coded** (`ps5_uart.cpp:1023`). On W boards the CYW43 wireless driver takes a PIO block (prefers PIO1, falls back to PIO0). Not linked here, so probably survivable — but it's a variable you don't need.
3. **RP2350 erratum E9** — GPIO inputs can latch at ~2 V and internal pull-downs are unreliable. The usual workaround is to enable the input only while reading, but **PIO cannot control `GPIO.IE`**, so on PIO-driven pins the only mitigation is an external ≤8.2 kΩ pull-down. This firmware runs PIO UART on six pins and reads `emc reset#` for liveness. Fixed in RP2350 A4 stepping, so recent boards may not exhibit it.

**Buy a plain Pico (RP2040).** "Pico H" if you want headers pre-soldered. Pico W is still RP2040 and would most likely work, but there is no reason to take the extra variable.

### Wiring (physical pin numbers on a Pico)

```
Pico pin 1  GP0  → EMC header  6   EMC UART RX   115200
Pico pin 2  GP1  → EMC header  7   EMC UART TX   115200
Pico pin 3  GND  → EMC header  4   GND
Pico pin 4  GP2  → EMC header  5   EMC GPIO A1   (pull low at EMC boot → ROM UART shell @ 460800)
Pico pin 5  GP3  → EMC header 24   EMC RESET#
Pico pin 11 GP8  → EMC header 12   Titania UART0 RX
Pico pin 12 GP9  → EMC header 11   Titania UART0 TX
```

**The console's 5V pins are not used.** The Pico is USB-powered; only GND is
shared. Do not bridge 5V from the header — that is how consoles die.

### Where the header is

A **24-pin header near the "salina" chip (EDM-010)**. There is also a duplicate
connector near the BT/Wi-Fi module, with markings matching the same pinout —
photographed in `uart/notes/emc_header_dupe_near_wifi.jpg`. That duplicate is
the friendlier entry point if it's reachable without lifting the shield.

### Board revision risk — read this first

The pinout above is documented for **EDM-010** ("salina"). The repo notes that
the "salina" PMIC is `rt5126` on **EDM-010** or `da9081` on **EDM-020**. A 14.x-era
console may be a later revision. **Verify your board revision before probing
anything** — the header may still match, but that is an assumption, not a fact.

## The 24-pin header, annotated

| Pin | Signal |
|---|---|
| 1, 2 | 5V |
| 3, 4 | GND |
| 5 | EMC GPIO A1 — pull low at EMC boot → EMC ROM UART shell @ 460800 |
| 6, 7 | EMC UART RX / TX @ 115200 |
| 8 | 3.3V, goes low when EMC resets |
| 10, 15, 23 | GND |
| 11, 12 | Titania UART0 TX / RX (EFC fw 460800, EAP fw 691200) |
| 13, 14 | Titania UART1 RX / TX (bootrom 460800, APU 230400) |
| 19 | EMC GPIO A49 — `devif_det#` |
| 20 | EMC GPIO A27 — main power switch |
| 21, 22 | I²C data / clock (`i2c_bus_4`, 400 kHz) |
| 24 | EMC RESET# |

### I²C bus 4 addresses (7-bit)

```
0x1f  pca9557_gpioexpander   CP/dev only
0x2c  ad5272_nand            Titania NAND
0x2e  ad5272_g6_2            GDDR6
0x2f  ad5272_g6_1            GDDR6
0x51  rt5127_pmic            Titania PMIC
0x58  ds80pci102_redriver
0x64  rt5069_pmic            salina PMIC (rt5126 on EDM-010, da9081 on EDM-020)
```

## What the repo's notes already give you — for free, no hardware

This is the part worth reading before buying anything.

### `uart/notes/uart_eap.txt` — a real MMIO map

Actual FreeBSD boot output from the EAP. This is the co-processor side, not the
x86 SoC, but it is measured silicon:

```
real memory  = 536870912 (512 MB)
avail memory = 122986496 (117 MB)

titania_spm0     <Titania SPM>      mem 0x18308000-0x1830afff
titania_efuse0   <Titania eFuse>    mem 0x1010f000-0x1010ffff
titania_apb0     <Titania APB>      mem 0x10115000-0x10115fff
titania_aon0     <Titania AON>      mem 0x10113060-0x1011405f
titania_clock0   <Titania Clock>    mem 0x10112000-0x10112fff
intc0            <ARM PL190 VIC>    mem 0xfffff000-0xffffffff
eap_hpet0        <EAP HPET>         mem 0x10111000-0x10111fff
uart0            <Titania UART>     mem 0x11010100-0x110101ff
sig0             <Titania SIG2>     mem 0x18307000-0x18307fff
titania_bcm0     <Titania BCM>      mem 0x19000000-0x19000fff
titania_ddr_phy0 <Titania DDR PHY>  mem 0x10128000-0x10128fff
titania_ddrmc0   <Titania DDRMC>    mem 0x11000000-0x11000fff
titania_pcie_tree0 <Titania PCIe>   mem 0x10121000-0x10121fff
```

### `uart/notes/update_timestamps.txt` — the boot timeline

Real timestamps from a cold boot:

```
 23   emc_pg2on_end
 33   efc boot start
127   efc boot end
250   efc init end
654   fc_load_psp_bl
658   fc_load_idstorage
813   emc_soc_on end
818   psp start
1348  abl start          ← AMD AGESA Boot Loader
```

**`abl start` matters.** ABL is AMD's standard AGESA boot loader, which means a
chunk of the PS5 boot chain is generic AMD x86 code, not Sony-specific. Anything
known about ABL from the PC side is potentially applicable.

### `uart/notes/bootlog_hcmd.txt` — the power sequence

141 `[PSQ]` stage markers listing the exact cold-boot power order. The first 26
before `Main SoC Power ON`:

```
BT WAKE Disabled · GDDR6/NAND Voltage Setting · Titania PMIC Register Init
Power Group 2 ON · PCIe Redriver EQ Setting · GPI SW Open · WLAN Module USB Enable
10GbE NIC Reset de-assert · SB PCIe init EFC · EFC Boot Mode Set
Flash Controller ON EFC · Floyd Reset De-assert · Subsystem PCIe USP/DSP Enable
Flash Controller Init EFC · Fan Servo Param Reset · FAN Control Start
MDCDC ON · HDMI Start · HDMI5VOn · HDD Power On · USB VBUS On
Main SoC Power ON (Cold Boot) · Main SoC Reset Release · MSOC Reset Moni High
BT WAKE Enabled
```

That is a cold-boot bring-up order, written down. For the bootloader project this
is closer to useful than any address table — it is the order things must happen in.

## Still missing from the repo

- The x86 SoC physical memory map (DRAM base/size, MMIO apertures, IOMMU blocks).
  `uart_eap.txt` covers the EAP/Titania side only.
- Hypervisor load address and handoff details.
- Anything about the NOR/LDLR specifically.

Those need either a console in hand or a NAND dump decoded offline.
