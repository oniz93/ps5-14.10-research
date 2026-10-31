# 103 — the two ZigZagBoi claims, reproduced instead of cited: neither is a primitive here

**Status:** measured 2026-10-30, local ASAN oracle. `docs/90-canvas-claim-checked.md` ended with these two as
its own next actions; both are now run. Result: **claim 1 does not reproduce locally** (the bug does, the
occupation does not) and **claim 2 is half true** (the stale length is real for comparisons, the write-back is
guarded and throws, so nothing is written out of bounds). Neither yields memory corruption.

## 1. Same-type canvas occupation as field control — bug yes, occupation no

Trigger (`arm=spray`/`probe`, page `research/canvas-alias/canvasfield.html`):
`canvas.getContext('bitmaprenderer', { get alpha() { canvas.getContext('2d'); return false; } })`. The inner
call's wrapper is stale, `stale=1&outer=1`.

The free is **synchronous**, and the stack says so — quarantine on, `arm=probe`:

```
==…==ERROR: AddressSanitizer: heap-use-after-free on address 0x61700006baa0
0x61700006baa0 is located 32 bytes inside of 712-byte region [0x61700006ba80,0x61700006bd48)
freed by thread T0 here:
    #1 WTF::fastFree(void*) …/wtf/FastMalloc.cpp:267
    #2 WebCore::CanvasRenderingContext2D::operator delete(void*)
    #8 WebCore::HTMLCanvasElement::createContextBitmapRenderer(…)   ← the unique_ptr reset
```

So: 712 bytes, plain `fastFree` (IsoHeap is **off** in this build), freed inside the overwrite. First use
afterwards dies — `arm=nospray`, SEGV in `CanvasBase::scriptExecutionContext()`, and with quarantine on the UAF
report above. Nothing about the trigger is in doubt.

**Occupations tried, all fail to take the slot** (first use still dies in the same frame):

| arm | window content | result |
|---|---|---|
| `spray&n=1 / 2 / 8 / 32 / 500 / 3000` | that many fresh `CanvasRenderingContext2D` | SEGV, same site |
| `spray&n=2000&pre=1` | canvases made **before** the trigger, so the window holds only contexts | SEGV, same site |
| `gc&n=3000` | 400 k objects churned in a task first, then 3000 contexts | SEGV, same site |

A cross-check with `Uint8Array(712)` is *not* informative: `ArrayBuffer` data comes from `Gigacage::tryMalloc`,
a different allocator from the freed `fastFree` chunk, so a same-size typed array is the wrong class by
construction. That is worth keeping — "712 bytes" alone does not identify a size class here.

**Verdict:** the defect reproduces and the free site is proven; the *alias* does not, on this build, at any
occupation size tried. So ZigZagBoi's field-control step is **unconfirmed locally**, and the only place it can
be settled is the console where they ran it (which needs the LOW_MEMORY modal cleared). Do not restate their
p553 numbers as reproduced.

## 2. `Array.prototype.sort` on a resized view — stale for reads, guarded for writes

Page `research/canvas-alias/rabsort.html`, `Uint32Array(64)` over `ArrayBuffer(256, {maxByteLength: 16384})`,
comparator shrinks the buffer to 16 on its first call. One variable per arm.

| arm | what happened |
|---|---|
| `noshrink` | sorts in 3 ms, 192 comparator calls, result ascending, correct |
| `shrink` | **192 comparator calls anyway** — the length *is* cached (`TypedArrayPrototype.js:229` reads `@typedArrayLength(this)` once, then `@typedArrayMergeSort(this, length, comparator)`) — then **`TypeError: Underlying ArrayBuffer has been detached from the view or out-of-bounds`** |
| `grow` | 192 calls, no throw, buffer at 16384, correct ascending result |

And the scoring question — did anything get written past `byteLength`? Grow the buffer back and read:
`v = 64,63,62,61,0,0,0,0,…` — the four elements inside the 16-byte buffer are the **original** descending
values and the twenty-four bytes past it are the zero page, so the write-back wrote **nothing**.

The throw comes from the per-store validation (`JSArrayBufferViewInlines.h:194`,
`isIntegerIndexedObjectOutOfBounds`), not from a length check: the merge sort's *loads* don't validate, so the
comparisons run on the stale length and the first *store* aborts the operation.

**Verdict:** "sort operates on the stale length" is true and measured; "sort is an OOB write" is not, on this
build. It is also not a read primitive, because the same `docs/100` zero page answers every OOB load.

## 3. What this changes

- Neither claim gives criterion 3. The canvas path's value is now precisely stated as *unconfirmed* rather than
  inherited, and the sort path is closed as a write source.
- The one thing in claim 2 worth carrying forward is the **asymmetry** itself: JSC validates on store and not
  on load for typed-array operations. Any primitive that needs a *read* past a shrunk view is fine
  (`docs/96`'s key builder already does exactly that); anything that needs a *write* must re-establish
  in-bounds state first.
- Claim 1's next step is a console arm, not a local one: `canvasfield.html?arm=spray&n=500` after the trigger
  with the modal cleared, scored on the page's own `sent&hit=` beacon, not on survival alone.

## 4. Commands

```
bash research/leak-sweep/oarun.sh cf_spray  10472 25 'arm=spray&n=32'    canvasfield.html
bash research/leak-sweep/oarun.sh cf_pre    10483 30 'arm=spray&n=2000&pre=1' canvasfield.html
bash research/leak-sweep/oarun.sh cf_quar   10478 25 'arm=probe'         canvasfield.html \
  detect_leaks=0:abort_on_error=1:symbolize=1:handle_abort=1      # quarantine ON, for the free stack
bash research/leak-sweep/oarun.sh rs3_shrink 10501 25 'arm=shrink&n=64&mx=4096' rabsort.html
```

Both pages live in `research/canvas-alias/`; `access: none` on every sort arm.

## Correction (2026-10-30, `docs/112`) — the occupation failure was the harness, not the build

The table in §1 is accurate and its conclusion is wrong. gdb on the run's own WebProcess (dtor → `A`,
`fastFree(A)`, a `fastMalloc` tracer for the 704–744 class, a write watchpoint on `A`) shows that the exact
trigger frees `0x6170…1c00` as described, and then the **first allocation after the free is the page's own
`B('trig')` beacon** — a 720-byte `CachedImage` (`createResource ← CachedResourceLoader::loadResource ←
requestImage ← ImageLoader::updateFromElement`), written at `A` and memory-cached, so it keeps the slot for the
rest of the run while all 80 `req=712` contexts land elsewhere. Moving that one beacon after the spray
(`btrig=late`) makes the 80-context spray take the slot: `sent hit=0 e=777.25 f=0`, `done`, `access: none`,
6/6 runs. Cross-type arm: eighty 692-character `atob` strings (712 B) also take it
(`StringImpl::createUninitializedInternalNonEmpty(length=692)` → `ALLOC req=712 ret=A`), so there is no type
segregation on this build. And 704/712/720/744 all landed in the was-one-slot in different runs, so the "712
bytes" in §1 never identified a size class. Details, log lines and the two controls: `docs/112`.
