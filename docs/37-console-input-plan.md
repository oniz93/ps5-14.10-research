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

**Raspberry Pi Zero W / Zero 2 W - recommended.** Its OTG port is a full USB device port and it runs
Linux, so the kernel's configfs gadget stack presents a boot-protocol keyboard with no firmware, no
toolchain and no second wire: WiFi carries commands. `pi_gadget_setup.sh` creates the gadget and
`pi_kbd_daemon.py` translates the line protocol into 8-byte reports on `/dev/hidg0`.

Requirements: a **W** variant (the single OTG port faces the console, so a non-W Zero has no command
channel), and two boot-config lines:

    # /boot/firmware/config.txt
    dtoverlay=dwc2
    # /boot/firmware/cmdline.txt (same line as rootwait)
    modules-load=dwc2,libcomposite

Power: the OTG port can power the board from the console, but if it browns out use PWR IN and keep USB
for data only.

Alternatives:

- **Pico W** (about 6 GBP) - MicroPython, `ps5key.py`, WiFi. Equivalent capability, more setup.
- **RoundyPi** (already owned) - RP2040, but its only USB port faces the console and just 4 GPIO are
  broken out with no published numbering, so UART to a Pi 3 means probing pads blind.
- **Pi 1/2/3** cannot do this at all: none of them has a USB device controller.

## Milestones

- **M1** flash firmware, confirm the console sees a keyboard and `PING` answers.
- **M2** `ps5_input.py press enter` dismisses a real dialog.
- **M3** `console_watch.py --on-recover` closes the loop unattended.
- **M4** run a candidate N times and record a crash rate.

M3/M4 still have nothing to measure until a candidate exists; discovery continues on the BC-250.

## What this does not do

It does not find the bug. Discovery happens on the BC-250 against the ASAN build. This harness makes
validation cheap once a candidate exists.
