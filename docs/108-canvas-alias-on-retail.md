# The canvas alias is real on retail — and our ASAN build was the wrong oracle for it

`c043b` ran on the console (User's Guide WebView, 14.10) at 2026-10-30 17:15:36. Beacons, verbatim in
`tools/fw1400/guide_lab/results/c043b-canvas-alias-20261030.txt`:

```
c043b-trigger inner=true outer=true same=false
c043b-sprayed=80
c043b-stale a=11.110011 b=22.220022 e=55.550055
c043b-CHANNEL sentinel-match
c043b-alias=2
c043b-reverse a=1.23 e=12.13 REVERSE-OK
c043b-prop-lineWidth-alias=2
c043b-ALIVE
```

Read in order: the re-entrant `getContext('bitmaprenderer')` replaces the 2D context (stale != outer); 80
same-type contexts are created afterwards; the **stale wrapper then reads the spray's own sentinel transform**
(`sentinel-match`); writing through the stale wrapper lands on `spray[2]` (`alias=2`); writing through `spray[2]`
and reading through the stale wrapper returns the new value (`REVERSE-OK`); a numeric property aliases the same
way (`prop-lineWidth-alias=2`); and the process survives.

So ZigZagBoi's field-control step **reproduces on hardware**, and their limitations section is the correct reading of
it: it is an in-type self-alias with bidirectional read/write of that object's fields, not arbitrary memory access.

## The part that corrects us

`docs/103` reported that the same occupation failed locally at every size (1, 2, 8, 32, 500, 3000 contexts,
pre-sprayed and GC-churned), with the first use dying in `CanvasBase::scriptExecutionContext()`. That result is
real, and it now means something different from what it looked like, because the **local ASAN build runs with
IsoHeap off** (`USE_SYSTEM_MALLOC=ON`) while the console runs with it on.

- **IsoHeap on (console):** a freed `CanvasRenderingContext2D` slot can only be taken by another
  `CanvasRenderingContext2D` — and it is, reliably, at 80 allocations. The segregation is what makes the reuse
  deterministic.
- **IsoHeap off (our ASAN build):** the freed chunk goes into the general `fastMalloc` pool, where a handful of
  same-size allocations do not reliably land on it at all, so the local test fails.

**The wall we had been reasoning about is the opposite of a wall.** `WTF_MAKE_ISO_ALLOCATED` blocks *cross-type*
reclaim, which is why every `ArrayBuffer`/`ImageData`/string spray failed, but it *helps* same-type reclaim, which
is the case we never tested because we had assumed segregation made occupation hopeless. Both our canvas verdict
("alias-only, so a DoS") and the reasoning behind it need restating: the alias is reachable on retail and carries
bidirectional field control; what it does not carry is attacker bytes in the slot, because the occupant is a real
context the engine initialised.

Consequence for method: **an IsoHeap class can never be judged by the local ASAN build's reclaim behaviour.** The
console is the only oracle for occupation, and for these classes it is the *easier* oracle, since same-type reuse is
deterministic there.

## What this does not claim

Not arbitrary read/write: every value goes through Canvas2D getters and setters, which interpret doubles, and their
own p553 notes the DAZ (denormals-are-zero) behaviour that turns pointer-shaped float64 values into `0.0`. No
pointer has been read or written here, and nothing has been written outside the aliased object.

## Next

The alias is now a working platform, so the question becomes the only one that can upgrade it: **does any aliased
field hold a pointer we can move?** `m_stateStack` is (buffer, size, capacity), and `save()`/`restore()` is the
cheapest way to drive it through the alias. If a state-stack pointer can be steered, the alias becomes arbitrary
read/write; if every reachable field is a double, it stays a field-control primitive.

## Correction (2026-10-30, `docs/111`)

The `USE_SYSTEM_MALLOC` reading above is right; the console half is not. `wtf/IsoMalloc.h:31` is
`#if USE(SYSTEM_MALLOC) || !USE(ISO_MALLOC)`, and `OptionsPlayStation.cmake:211` sets `USE_ISO_MALLOC` **OFF** for
the port, so the 834 `WTF_MAKE_ISO_ALLOCATED` classes compile to `WTF_MAKE_FAST_ALLOCATED` and live in the general
bmalloc heap on 14.10 too (the oracle does the same through the other arm of that condition). Measured there: 0
`bmalloc::api::IsoHeap` instantiations in the oracle's own 3.7 GB library, and none in the object built from
`CanvasRenderingContext2D.cpp` with the build's own flags, while `docs/65`'s `CSSFontFace` turns out not to be an ISO
class at all. Consequences for this document: `c043b`'s `alias=2` does **not** discriminate IsoHeap from a plain
bmalloc size-class free list (both reuse a freed slot for the same class; only a **cross-type** allocation of the
same size class would), and `docs/103`'s local negative was not caused by type segregation — the reason it failed is
unmeasured. The practical rule survives in a stronger form: the console is the only oracle for occupation, for
**every** class, because what differs is the allocator (bmalloc vs ASAN's malloc), not the type segregation.

## Correction (2026-10-30, `docs/112`) — the local negative is gone, so the console is not the *only* oracle

The last sentence above ("the console is the only oracle for occupation, for every class") is too strong, and
`docs/103`'s negative was not evidence for it. With gdb on the oracle's own WebProcess, the freed
`CanvasRenderingContext2D` slot is reclaimed by the 80-context spray deterministically (`sent hit=0`, 6/6) as
soon as the page's own `new Image()` beacon is moved after the spray instead of sitting between the free and it.
That beacon allocates a 720-byte `CachedImage` in the same ASAN size class and is memory-cached, so it — not the
allocator — is what every `docs/103` arm was fighting. What the local build still cannot emulate is bmalloc's
class geometry: on the console the same `sendBeacon` shape did produce `alias=2`, and locally the same shape
makes a 704-byte `CachedRawResource` take the slot. So the console stays the only oracle for *which class* a
given size lands in, not for whether ordering/liveness allows an occupation at all. `docs/112`.
