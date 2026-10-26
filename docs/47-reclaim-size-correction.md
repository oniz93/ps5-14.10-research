# The reclaim was aimed at the wrong size

## Correction: the object is 712 bytes

The earlier ASAN report on the BC-250 carries the allocation details that the reclaim work depended on:

```
#1 WTF::fastMalloc(unsigned long)            Source/WTF/wtf/FastMalloc.cpp:240
#2 WebCore::CanvasRenderingContext2D::operator new(unsigned long)   canvas/CanvasRenderingContext2D.h:37
#3 WebCore::CanvasRenderingContext2D::create(...)                  canvas/CanvasRenderingContext2D.cpp:73
```

Region: **712 bytes**, not the 768 assumed when the ArrayBuffer spray was built. That alone explains `c015`:
1200 buffers of the wrong size class cannot reclaim the slot, so the first canvas call landed on freed memory
and the process died without a hit.

## The oracle was also wrong

`lineWidth` writes into `m_state`, which points into a separate `stateStack` allocation - so it faults whether
or not the object itself was reclaimed. It cannot distinguish "reclaim failed" from "reclaim succeeded but the
state pointer is garbage". This is exactly what the quarantine-off run showed: a SEGV inside
`CanvasRenderingContext2DBase::setLineWidth` at `CanvasRenderingContext2DBase.cpp:536`, with the object never
having been reused.

`beginPath()` is a better oracle: it allocates a `Path` and stores the pointer **into the object**. If a string
occupies that memory, the string's own characters change, which is observable from JS via `charCodeAt` and
simultaneously leaks a heap pointer. `c016` sweeps string lengths from 600 to 1010 in steps of 10 so whichever
size class holds 712 is covered, fires `beginPath()`, then scans for bytes that stopped being the fill value.

## Why this cannot be developed locally

* ASAN cannot model a reclaim: it quarantines freed allocations. Disabling the quarantine
  (`quarantine_size_mb=0`) is not enough - the freed slot still was not reused, and the write faulted.
* The console allocator is libpas (bmalloc). The GTK build here is configured `USE_SYSTEM_MALLOC=ON`, i.e. glibc
  malloc, which reuses differently.
* A bmalloc-enabled GTK build is impossible: `bmalloc/CMakeLists.txt:697` calls `WEBKIT_FRAMEWORK_DECLARE`, an
  Apple-port-only macro, so configuration fails outright.

So grooming parameters only mean something on the console, and each failed attempt costs a WebProcess restart.
`c016` is written to test as much as possible per run: 41 classes x 160 objects, one oracle call, one scan.
