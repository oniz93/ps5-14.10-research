# Console input path — verified on retail 14.10

The Pi Zero W keyboard bridge drives the PS5's User's Guide with no controller. This records the
verification and the two defects that made it look broken for hours, because both produced *silent*
success at every layer and would cost the same time again.

## Result

Three presses, three predicted outcomes, all correct (2026-10-26, Guide app open on the home screen):

| # | key | predicted | observed |
|---|---|---|---|
| 1 | Enter | activate the focused item ("User's Guide") | left the Guide menu, opened the User's Guide, which failed to load and showed `WV-109144-9` |
| 2 | Enter | dismiss the dialog | dialog gone, Guide browser page visible |
| 3 | Escape | go back | Guide menu restored with the same four labels |

Screen state was read with Vision OCR (`tools/fw1400/ocr`), not by diffing pixels — the OCR text is the
evidence, and each transition changed it in the predicted direction.

## What was actually broken

**1. The report was empty, not undelivered.** `send_report` assembled the 8-byte report in a loop over
`${!i}`, which is *indirect* expansion — the value of the variable whose **name** is `$i` — so for
positional parameters it expanded to nothing and every press went out as `00 00 00 00 00 00 00 00`,
i.e. "all keys released". Fixed in `a486487`; the report is now composed directly as
`"\x00\x00$1\x00\x00\x00\x00\x00"`.

Why it hid: the descriptor was valid, the host enumerated a real `Logitech Keyboard K120`, the UDC
reported `configured`, `/dev/hidg0` accepted all eight bytes, and the host genuinely received eight
bytes. Every observable said success. Three earlier "fixes" (canonical padding bytes `81 03`/`91 03`,
real IDs `046d:c31c` instead of `1d6b:0104`, holding the fd open across press and release) were each
real improvements and none could change the outcome.

**2. Reopening the device per report can discard the report.** `printf … > /dev/hidg0` opens, queues and
closes; `f_hid` frees its request on close and the host only polls an interrupt endpoint every
`bInterval` (4 ms here). The device is now opened once per command with `exec 3>` and held through the
press, the release, and one extra polling interval.

## Oracles, ranked by trust

1. **`hidraw` on a Linux host** — the only one that cannot lie. `/dev/hidraw0` was world-readable on the
   BC-250, so no root was needed; read it unbuffered in Python (`os.read`, `flush=True`), not with `od`,
   which block-buffers to a file and shows nothing until it exits. Three presses produced six all-zero
   reports before the fix and `0000280000000000` / `0000000000000000` / `0000510000000000` after.
2. **OCR of the console's own text** — exposure-independent and readable through a webcam, and the
   classification (`GUIDE`, `NET_ERROR`) is derived from the words on screen.
3. **A human glance** — cheap and decisive. "You just pressed something" after a manual `dd` of the
   literal bytes is what exposed the encoding bug: the manual path and the script path differed only in
   the bytes, which pointed straight at the code that built them.
4. **Camera frame diffing — do not use.** Auto-exposure on a bright page moved every pixel with no UI
   change (23.4 dB, inside the "changed" band), and an edge-detected variant did not separate either.

## Deployment

- `hid_key.sh` is driven per command over SSH (`ps5_input.py --ssh root@<pi>`), which needs no Python on
  the Pi and has no state to corrupt; `HOLD`/`RELEASE` are rejected explicitly because state cannot span
  invocations.
- The gadget is bound at boot by `ps5kbd-gadget.service`, so a reboot no longer takes the console's
  keyboard away.
- `HID_KEY_DRYRUN=1 hid_key.sh "PRESS enter 0"` prints the bytes a press would send. Always run this
  before concluding the console ignored a key.
