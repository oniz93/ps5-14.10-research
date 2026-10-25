# 37 - Console input: design and milestones

## Why the shape is dictated by PS5

PS5 does not merely pair a controller, it **verifies** it. The DualSense speaks Bluetooth Classic
L2CAP on PSMs `0x11`/`0x13` and needs a feature-set handshake plus a CRC32 on its reports; over USB it
still runs a verification handshake. Synthesising a controller therefore means reimplementing Sony's
protocol from scratch with no guarantee of success.

The design that avoids all of that: **put a genuine DualSense behind the Pico and let it answer the
handshake.** The bridge forwards its reports and ORs button bits into them on request. Consequences:

- the controller needs no modification and stays usable as a normal controller
- PS5 sees a real controller, so verification, pairing and firmware questions disappear
- we only need to rewrite report bytes in flight, not to understand the handshake

## Topology

    Mac                          Pico (RP2040)                 PS5
    console_watch.py  --UART-->  bridge firmware  --USB dev-->  console
      (camera + OCR)             ^      |
                                 |      +--USB host (PIO)--> genuine DualSense
                                 |
                            USB-serial adapter

Two USB links on one RP2040: the native controller is the USB *device* facing the PS5, and PIO-USB
provides the *host* port facing the controller. A spare ESP32 can serve as a wireless UART bridge if
no USB-serial adapter is available.

## Milestones

**M0 - prerequisites (owner: Teo)**
- grant camera access to the app running this (System Settings -> Privacy & Security -> Camera); live
  capture currently fails with `Input/output error`, which is TCC, not ffmpeg
- confirm the Pico exposes ~4 free GPIO pads (2 for PIO-USB D+/D-, 2 for UART) and whether it is a
  Pico W; a watch-form board may have none broken out, which would change the plan

**M1 - transparent passthrough.** Pico forwards controller to console untouched. Success: console
accepts it, controller behaves normally, no dropouts over 10 minutes. This is the make-or-break step;
if passthrough cannot be made transparent, nothing above it matters.

**M2 - injection.** UART commands OR button bits into forwarded reports. Success:
`ps5_input.py press cross` dismisses an on-screen dialog.

**M3 - closed loop.** `console_watch.py --on-recover "ps5_input.py --port ... press cross"` with
`--input serial`. Success: a WebProcess crash is detected and cleared without a human, and the loop
keeps running unattended.

**M4 - reliability measurement.** Run a candidate N times, record crash count and timing, correlate
with the lab's guide beacons (which already prove whether the page executed). This is the actual
deliverable: a crash *rate* on real hardware.

## What this does not do

It does not find the bug. Discovery happens on the BC-250 against the ASAN build. This harness makes
validation cheap once a candidate exists, and until one exists M3/M4 have nothing to measure.

## Fallbacks

- Passthrough too lossy (timing/descriptor mismatch) -> mechanical actuation on the real controller;
  crude but bulletproof.
- Pico unavailable -> ESP32 Bluetooth emulation, which means implementing the PSMs and the CRC the
  hard way, so only if the Pico path dies.
