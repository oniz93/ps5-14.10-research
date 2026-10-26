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
