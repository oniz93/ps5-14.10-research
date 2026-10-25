# 37 - Console input: a USB keyboard, not a controller

## The discovery that deleted most of this problem

PS5 verifies controllers: the DualSense speaks Bluetooth Classic L2CAP on PSMs `0x11`/`0x13`, needs a
feature-set handshake and carries a CRC32, and the USB path runs a verification handshake too. That
made emulating a controller a reverse-engineering project.

It accepts an **ordinary USB keyboard** with none of that. Tested on the console:

| key | effect on the Guide |
|---|---|
| arrows | move focus |
| Enter | OK / activate |
| Escape | back out |
| F3 | the Options button - closes the Guide |

So the input device is a standard HID keyboard, the DualSense is never touched, and no protocol
reverse-engineering is needed. All the controller work in this document's first draft is obsolete.

## Design

    Mac                                  RP2040                     PS5
    console_watch.py --(TCP/UART)--> ps5key.py --(USB HID)--> console
      camera + OCR                     keyboard + command loop

- `tools/fw1400/ps5key.py` - MicroPython firmware: presents as a boot-protocol HID keyboard and
  accepts `PING / PRESS / HOLD / RELEASE / SEQUENCE / ALLUP` over TCP (Pico W) or UART.
- `tools/fw1400/ps5_input.py` - host client, serial or TCP, with a pty selftest.
- `tools/fw1400/fake_bridge.py` - stand-in implementing the firmware's replies so host-side changes
  can be tested without hardware. It already caught two real bugs: the CLI still validated controller
  buttons after the device became a keyboard, and the fake server accepted only one connection.

## Safety interlocks

1. `UPDATE_PROMPT` is a distinct state in `console_watch.py` and is **never** acted on. Enter on that
   dialog could accept an update to 14.20, which adds the generation-ID check that kills the
   kernel-side work. The watcher only alerts.
2. The firmware has a deadman timer: if no command arrives for `DEADMAN_S` (15 s), every key is
   released. A stuck key on a console that is expensive to recover is not an acceptable failure mode.
3. `ALLUP` releases everything immediately, for when a run goes wrong.

## Hardware choice

The command channel is the only reason to connect anything else:

- **Pico W** (about 6 GBP) - WiFi, so no wires at all, and a standard 40-pin board. Recommended.
- **RoundyPi** (already owned) - RP2040 with a micro-USB port that faces the console, but its SD and
  LCD pins consume most GPIOs and only 4 are broken out. UART needs 2 of them plus GND, wired to a
  Pi 3 running a TCP-to-UART bridge. Workable, but the exposed GPIO numbers are not documented, so
  they would have to be found empirically.

## Milestones

- **M1** flash firmware, confirm the console sees a keyboard and `PING` answers.
- **M2** `ps5_input.py press enter` dismisses a real dialog.
- **M3** `console_watch.py --on-recover` closes the loop unattended.
- **M4** run a candidate N times and record a crash rate.

M3/M4 still have nothing to measure until a candidate exists; discovery continues on the BC-250.

## What this does not do

It does not find the bug. Discovery happens on the BC-250 against the ASAN build. This harness makes
validation cheap once a candidate exists.
