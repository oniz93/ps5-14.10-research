# When the Pico arrives — ordered checklist

Do these in order. The first two cost nothing and one of them can save the console.

## 0. Before anything arrives

- [ ] **Identify the mainboard revision.** Look for an `EDM-0xx` marking on the board.
      The documented pinout is **EDM-010**. The repo notes the salina PMIC differs
      between EDM-010 (`rt5126`) and EDM-020 (`da9081`) — so a later revision is a
      different board with a possibly different header. **Do not probe until this is
      known.** A 14.x-era console may well be later than EDM-010.
- [ ] **Decide: is this console sacrificial?** If yes, everything below is lower
      stakes. If you want to keep a 14.x jailbreak option open, stop before any
      operation that can put the EMC into an unknown state.
- [ ] Read `uart/README.md` wiring section once, on paper, with the console in front
      of you — not on a screen while holding a probe.

## 1. Bench setup (no console connected)

- [ ] Flash `uart.uf2` to the Pico. Confirm all three CDC interfaces enumerate on
      the Mac. (`ENABLE_DEBUG_STDIO=ON` adds a stdio console — useful for firmware
      debugging, off by default.)
- [ ] Verify pin continuity on your own harness with a multimeter **before** it goes
      anywhere near the console. Especially GND.
- [ ] Confirm you are **not** carrying the console's 5 V to the Pico. VBUS comes from
      USB only. Check this with the meter, don't trust the colour of the wire.

## 2. First contact

- [ ] Console unplugged. Attach GND first, then the UART pair, then GP2 (A1), then
      GP3 (RESET#).
- [ ] Power the console. Watch the Pico's EMC interface at 115200.
- [ ] **First win = any coherent byte.** Garbage means baud/wiring. Silence means no
      contact at all. Do not proceed to `emc.screset()` on garbage.

## 3. Unlock sequence

Per the repo's `tool.py`:

```
emc.screset()        reset syscon, bring board to a consistent state
emc.unlock()         unlock the full EMC command set (UCMD)
emc.unlock_efc()     load bin_blobs/uart_shell.cpp onto the EFC
emc.load_eap()       same shell onto the EAP
```

- [ ] `screset` returns cleanly.
- [ ] `unlock` succeeds — this is the exploit step; expect it to be the fragile one.
- [ ] Only then load the shell.

## 4. What to capture first (before anything writes)

- [ ] NAND page reads — `titania/` can decode these offline afterwards.
- [ ] EMC boot log during a cold start.
- [ ] Anything the shell can read about flash/NOR layout.

**Read before you write.** The first thing this hardware should do is produce a dump,
not change state.

## Abort conditions

Stop and re-read before continuing if:

- the EMC stops responding after `screset`
- the console's fan or power LED behaves differently from normal cold boot
- anything gets warm that didn't get warm before
- you are guessing at a pin

## Note on the TTL adapters

The Pico bridges both UARTs to USB itself — you don't need a separate USB-TTL adapter
for the normal path. The adapters are still useful for an independent sniff, and as a
fallback if the Pico's CDC enumeration misbehaves. Nothing missing.
