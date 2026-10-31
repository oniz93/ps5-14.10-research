# The "canvas write primitive confirmed" claim, checked against its own evidence

ZigZagBoi's README now states: *"Canvas UAF (CVE-2026-43720) write primitive confirmed on 14.10 (p553, executed
2026-10-26) — full bidirectional R/W via same-type reclaim, spray[9] alias, 6×float64 transform + 7 numeric
properties."* Pulled the repo (`4c4ed01`) and read the evidence file plus the method doc.

## The evidence file is a reconstruction, and it says so

`results/phase13_webkit/p553_canvas_uaf_write_confirm_20261026.txt`, header verbatim:

```
Source:   Reconstructed from Engram observations #2934/#2935 (beacon data)
NOTE: This file is reconstructed from session memory. The original beacon data was received via host.py
stdout (transient) and not persisted to disk at the time of execution. The beacon sequence and values below
are faithful to what Engram recorded from the live run.
```

So the artefact is an AI memory of a stdout stream, not a persisted capture. By this programme's rule — a number with
no log is a claim, not a primitive — it cannot be credited as evidence, however plausible the behaviour.

## Their own limitations section contradicts the headline

From the same file:

```
Limitations:
  - NOT arbitrary write: values pass through Canvas2D getters/setters (float interpretation)
  - Cross-type reclaim DEAD: ArrayBuffer spray does not land in 768B Canvas2D bmalloc size class
Blocker: Info leak — reading a heap pointer as a JS number is blocked by DAZ.
```

"Full bidirectional R/W" therefore means: two JS wrappers alias one `CanvasRenderingContext2D`, and that object's
**own fields** can be read and written through either wrapper. That is an in-type self-alias with field-level access,
not a read/write primitive over arbitrary memory — the same conclusion we reached, stated more generously.

## The one place we were imprecise

Their doc claims `IsoHeap | OFF`, then reports that cross-type reclaim never works — which is the observed signature
of IsoHeap being **on**. Our own conclusion ("canvas UAF is alias-only") still stands, but our *reasoning* was loose:
`c016`–`c021` only ever sprayed cross-type containers (ArrayBuffer, ImageData, strings), and under IsoHeap no
cross-type allocation can take the slot, so those failures were expected and never tested same-type reclaim at all.
The honest phrasing is: only a `CanvasRenderingContext2D` can take a freed `CanvasRenderingContext2D` slot, so the
bug yields an alias between two wrappers and one engine-initialised object — with no attacker bytes in the slot.

That also explains their 768-byte figure: our ASAN measurement of the freed object is **712 bytes**
(`CanvasRenderingContext2D.cpp:73`), so their size class reasoning is off by 56 bytes, and "the same 768B FastMalloc
slot" cannot be the object they think it is.

## What is genuinely new and worth taking from them

Two things, neither of them the headline:

1. **The alias is stable and repeatable on retail** — one object, two live wrappers, no crash, `save()`/`restore()`
   operating on the shared state stack. Worth reproducing because it is the cheapest source of a *field-control*
   primitive on this build, and our programme never tested same-type occupation for canvas.
2. **The info-leak angle.** Their blocker is turning a heap pointer into a JS number (DAZ turns pointer-shaped float64
   denormals into `0.0`), and they list APNG overread and *"RAB sort OOB (P560 confirmed sort operates on stale
   length)"* as live. The RAB-sort claim is the interesting one — our RAB work found the length cache but every
   post-shrink read returned `undefined`; `sort()` is a different path and was not among the builtins we inspected.

## Do not use their delivery

`ftrevino739-ctrl/PS5-14.10-JB` now ships a setup page that points the console's DNS at **45.56.67.85** (a
third-party resolver) or a GitHub Pages URL. That would route *every* query the console makes — including
`update.playstation.net` — through a host we do not control, which is precisely the containment we have been
holding. Never point this console at a public resolver; the lab resolver exists so that the update estate is refused
locally. Their page also states plainly that the full chain is still under research.

## Next

Two cheap experiments, in order, both of which our own corpus is missing:

1. **Same-type canvas occupation as field control** (local ASAN first, then retail): trigger the UAF, create N
   `CanvasRenderingContext2D`s in the window, then read the stale wrapper's transform and numeric fields back. If a
   sentinel appears, we have the alias they claim; then ask the only question that matters — *is any aliased field a
   pointer?* `m_stateStack` is (buffer, size, capacity), so driving `save()`/`restore()` through the alias is the
   cheapest probe of whether that field can be moved.
2. **`Array.prototype.sort` on a resized view** — their P560 claim, unchecked by us: sort caches the length?
