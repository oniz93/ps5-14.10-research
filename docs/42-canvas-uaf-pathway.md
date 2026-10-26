# The live pathway for 14.10: CVE-2026-43720 (canvas getContext re-entrant UAF)

This supersedes the "no public entry for 14.10" assumption. There is exactly one live public pathway for
this firmware, and it is now reproduced here, independently, on our own console.

## Why this one and nothing else

Checked against the public 14.10 status work and our own tree:

| entry | range | state on 14.10 |
|---|---|---|
| Relapse webkit + kernel | 7.00-13.60 | dead: kernel bug (`aio_multi_wait`) patched in 14.00, and its browser-stage object-pool bug is fixed in Sony's tree |
| BD-JB5 | <= 13.42 | dead |
| Y2JB (YouTube) | <= 12.70 | dead |
| hypervisor (S3-resume) | 6.xx-13.60 | patched in 14.10 |
| kernel | nothing public | no public 14.10 kernel bug |
| **CVE-2026-43720 canvas UAF** | **14.10** | **live** |

## The bug, in Sony's own source

`HTMLCanvasElement::getContext(JSC::JSGlobalObject&, ...)` checks `m_context` at entry (line 226), then
converts the options dictionary - which runs JS getters - and only afterwards calls
`createContextBitmapRenderer()`. That function is:

```cpp
ImageBitmapRenderingContext* HTMLCanvasElement::createContextBitmapRenderer(...)
{
    ASSERT(!m_context);                                                  // compiled out in release
    m_context = ImageBitmapRenderingContext::create(*this, WTFMove(settings));   // overwrites
```

A getter that calls `canvas.getContext('2d')` therefore creates a 2d context that the outer call replaces.
The JS wrapper from the inner call outlives the context it points at.

## Reproduced here

Local ASAN build of this same tree: `heap-use-after-free` in
`CanvasRenderingContext::hasActiveInspectorCanvasCallTracer()` on the first use of the stale wrapper.

On the console, ordering matters and that is the whole trick:

* naive (touch the stale wrapper first) - dies every time; beacons stop right after `triggered`.
* reclaim first (500 Canvas2D contexts), then use it - survives, and the wrapper aliases a live context.

Measured on retail 14.10:

```
c014-triggered:ctx/ctx
c014-sprayed:500
c014-alias-index:4        <- stale wrapper aliases live spray context #4
c014-readback:777.25      <- write via spray[4] visible through the stale wrapper
survived:1
```

So: UAF -> same-type reclaim -> **bidirectional alias between two JS objects and one live C++ context**.

## Remaining stages to code execution

Mapped from the public 14.10 browser research and consistent with what is confirmed here:

1. **ASLR defeat** - APNG overread leaks heap pointers (published: 1651 pointers). Needed because the alias
   is only useful once we can name addresses.
2. **Arbitrary R/W** - grow `stateStack` so the realloc frees the old buffer, reclaim that buffer with an
   ArrayBuffer (gigacage is disabled on PS5, so ArrayBuffer backing stores share the heap), then forge a
   `lineDash` `Vector<double>` inside it: `m_buffer` = target, `m_size` = count. `getLineDash` reads at the
   target; `setLineDash` copy-assigns in place when capacity >= N, giving a write.
3. **Code execution** - overwrite a vtable, or `startOfStructureHeap` (JSC Config is unfrozen on PS5), then
   ROP. No PAC and no JIT to fight.
4. **Then** the kernel rung, which has no public 14.10 bug - that gap is Teo's open problem, not this one.

## Appendix: the public exploit probe, run on our console (V665)

The 14.10 browser research has 68 probe files. The newest (`v665.html`, "save-count OOB stateStack info
leak") was served to the console through the lab and executed. Beacons, in order:

```
V665-BOOT, V665-UAF, V665-GROW, V665-GROW-LW, V665-LD, V665-ATTRS,
V665-SPRAY, V665-XF, V665-CANVAS, V665-NO-OOB, V665-RESTORE-LW, V665-DONE
```

`V665-NO-OOB` is the result that matters: growing `m_stateStack` past its capacity and reading through the
stale wrapper did **not** produce an out-of-bounds read on this console. So the arbitrary-R/W stage is still
designed rather than demonstrated - which matches the source repo's own status table, where arbitrary R/W is
"DESIGNED" and only the UAF, reclaim, alias, crash oracle and ASLR leak are "CONFIRMED".

Our independent contribution stands on its own: the trigger, the reclaim ordering (reclaim *before* touching
the stale wrapper, otherwise the process dies), and a measured bidirectional alias (`alias-index:4`,
`readback:777.25`).

### Where that leaves the chain

| stage | status |
|---|---|
| UAF trigger | confirmed here and publicly |
| same-type reclaim | confirmed here (500 contexts) |
| alias R/W (two JS objects, one context) | confirmed here |
| ASLR leak | confirmed publicly (APNG overread), not yet reproduced here |
| arbitrary R/W | open - public save-count OOB returns NO-OOB on retail |
| code exec | open |
| kernel for 14.10 | nothing public at any layer |

The next idea worth trying is a different reclaim target: instead of growing the state stack and hoping for
an OOB read, reclaim the freed 768-byte `CanvasRenderingContext2D` **itself** with an ArrayBuffer. Gigacage is
disabled on PS5, so AB backing stores share the heap; controlling the object's bytes would let us set
`m_stateStack` to a forged `State` array directly rather than relying on a size confusion.
