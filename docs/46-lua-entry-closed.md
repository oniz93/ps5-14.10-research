# Why the Lua entry is closed on this console (Digital, 14.10)

Teo reported that PSN sign-in fails on 14.10 and asked whether the package can be obtained another way, and
whether a demo used a year ago is still the right target.

## PSN: the minimum firmware is now 14.20

Sony raised the PSN sign-in floor twice in quick succession: below 14.00 -> forced to 14.10 (reported
2026-10-15), then 14.10 -> 14.20 with the 26.07-14.20.00 release, which is also stated to be required for PSN
connectivity. A console on 14.10 therefore cannot authenticate, and this is a server-side version check -
there is no client-side setting that changes it. Updating is the only cure, and that destroys the 14.10 target.

## No alternative install path

* A retail PS5 installs packages only through the store, and the store requires that authenticated session.
* Sideloading a `.pkg` requires a jailbreak - which is the thing we are trying to obtain. Circular.
* The Internet Archive item `hamidashi-creative` is `MADO-0006.ISO`, the 5.6 GB **Japanese PC release**. It is
  not a PS4/PS5 package and cannot be installed on the console.
* Moving game data between consoles still requires a licence on the target console, i.e. PSN again.

## Is a year-old demo still the right target? Yes.

* The `PS5-14.10-Research` repo uses exactly this game on 14.10, and identifies it by matching its observed
  stack pivot (eboot+0x9A2) to the `hamidashi_creative` gadget table - so it demonstrably still works there.
* The loader is firmware-independent by design: it abuses an Artemis-engine save-parsing flaw (the engine loads
  Lua from save data), not a kernel bug that patches would close.
* What changed since a year ago is licensing, not the bug: since 12.60/13.00 Sony applies 30-day expirations to
  downloaded software used by these engines, which is why the community recommends disc copies. A Digital
  Edition has no drive, so the digital route is both unavailable now and time-limited if it ever opens.

## Consequence for the goal

On this specific console the Lua rung - the only public entry on 14.10 with libkernel/syscall access - is not
reachable. What remains live is the browser entry already reproduced on this hardware (CVE-2026-43720 canvas
re-entrant UAF, alias proven) plus static kernel work on the 13.60 dump, which needs no console.

## Current console state

Stuck on "There is not enough free system memory." - the modal survived Enter, Tab, arrows and repeated
confirmations, so it needs a power cycle before further browser campaigns can run.
