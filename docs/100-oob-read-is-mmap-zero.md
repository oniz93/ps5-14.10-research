# 100 — the OOB resizable view cannot leak an address: the buffer is a fresh mmap page, so the view reads its own zeros

**Status:** measured 2026-10-30, quarantine off, ASAN oracle. **Negative, and structural.** `docs/96` found the
only ungated out-of-bounds read in the build (`IDBKey::createBinary` copies a raw `byteLength()` of an
out-of-bounds resizable view into a JS `ArrayBuffer`) and could not get an address out of it; `docs/96` §8
called the reason "the Gigacage". This run shows the reason is stronger and final: **a resizable `ArrayBuffer`
is never a heap allocation at all**, so the overflow cannot reach a neighbouring object of any kind.

Page `research/leak-sweep/oobadj.html`, runner `research/leak-sweep/oarun.sh` (kills only its own port — another
session was running a font corpus on the board).

## 1. The arms

One arm per run, one variable each. `n` = live buffer bytes, `v` = view length, `k` = neighbours planted of the
class (64). Scored off the page's own beacon, which reports the number of **non-zero** bytes and of
pointer-shaped `u32` pairs (heap `0x7f…`, cage `0x00000c…-0x000010…`, `0x00004…-0x00008…`, 8-aligned).

| arm | n | v | planted neighbour | result |
|---|---|---|---|---|
| `ab` | 4096 | 4096 | 64 × class-4096 `ArrayBuffer`, each stamped `ABMARK<i>:` | `bl=4096 nz=4096 seen=0 pairs=0` |
| `str` | 4096 | 4096 | 64 × class-4096 `StringImpl` (`0x14+4076`), each stamped `M<i>:…` | `bl=4096 nz=4096 seen=0 pairs=0` |
| `leak` | 4096 | 4096 | none | `bl=4096 nz=4096 pairs=0` |
| `nosh` | 4096 | 4096 | none, no shrink | `bl=0` — the inverted test's zero-length control |
| `page64kc` | 16 | 65536 | none | `bl=65536 nz=16 pairs=0` |

`nz=4096` in the first three is the page's own `0x5A` fill, still sitting in the bytes beyond the shrunk
`byteLength` — the copy really happens, it just has nothing but page bytes to find. The decisive row is the
last: a **full 64 KiB page** read out from behind a 16-byte buffer, and exactly 16 non-zero bytes in it.

## 2. Why: resizable buffers take the mmap path, not `fastMalloc`

`ArrayBuffer::tryCreate` branches on `maxByteLength` (`ArrayBuffer.cpp:298-306`): without it, the classic
`ArrayBufferContents::tryAllocate` → `Gigacage::tryMalloc(Primitive, …)` path (`:132`); **with** it,

```
:316  auto handle = tryAllocateResizableMemory(nullptr, sizeInBytes.value(), maxByteLength.value());
:321  ArrayBufferContents contents(memory, sizeInBytes.value(), maxByteLength.value(), handle.releaseNonNull());
```

and that function never touches the heap:

```
:79   size_t initialBytes = roundUpToMultipleOf<PageCount::pageSize>(sizeInBytes);   // pageSize = 64 KiB, PageCount.h:111
:82   size_t maximumBytes = roundUpToMultipleOf<PageCount::pageSize>(maxByteLength);
:88   BufferMemoryManager::singleton().tryAllocatePhysicalBytes(initialBytes)        // commit
:96   BufferMemoryManager::singleton().tryAllocateGrowableBoundsCheckingMemory(maximumBytes)  // reserve
```

`ArrayBufferContents` is then built from that pointer and **no memset runs** — the zeroes the arms count are the
kernel's fresh-page zeroes, and `grow` only commits further pages of the same reservation. So the region a view
can over-read is (a) inside the buffer's own reservation and (b) committed-and-zero beyond the live length.
Neither a `StringImpl` nor another `ArrayBuffer` is ever adjacent, because the class runs the allocator would
put them in are different address spaces entirely.

That also explains `docs/96`'s own `rc`/`rc2` zeros without invoking a GC that never fired, and it **qualifies
`docs/96` §8's conclusion**: finding another consumer that reaches `wrappedAs()`/`possiblySharedImpl()` with an
out-of-bounds view is still worth doing, but it will hand over zeroes, so it cannot be the leak by itself.

## 3. Two corrections to the record

- **A view longer than the live buffer cannot be built "from birth".** `new Uint8Array(buf, 0, v)` validates
  against the *current* `byteLength`, not `maxByteLength`: with `n=16, v=4096` it throws
  `RangeError: Length out of range of buffer` (measured, arm `v16`). Every OOB arm, `docs/96`'s included, must
  **grow first, then view, then shrink** — which is why the committed page is always as large as the view and
  the tail is always fresh-zero.
- **An earlier note in this programme's chain discussion** that a fastMalloc neighbour could be reached from
  this shape is wrong for the same reason.

## 4. What the shape is still good for

- A **64 KiB zero-page oracle**: `new ArrayBuffer(16,{maxByteLength:65536})`, `resize(65536)`, view 65536,
  `resize(16)`, `IDBKeyRange.only(v).lower` reliably yields 65536 zeroed bytes with the 16 live ones — usable to
  prove a buffer's committed extent without a sanitizer.
- Reading past the committed extent is a **fault**, not a leak (`docs/96` C1: the next page is `PROT_NONE`), so
  any consumer of this shape must keep `v ≤ roundUpToPage(n)`.

## 5. Consequence for the chain

The heap-address disclosure has to come from a **memory-safety bug that copies engine bytes into JS**, not from
an API boundary — `docs/95` (API surfaces), `docs/98` (rasterisation) and now this (the one OOB read) close the
API route completely. The live queue is the FreeType corpus (`GOAL.md`, running on the oracle at the time of
writing) and any new ungated producer, and the criterion for either is the one `docs/95` set: a JS-visible value
that changes between two runs **and** lands in a `/proc/<pid>/maps` mapping of the same process.

## 6. Exact commands

```
bash research/leak-sweep/oarun.sh adjab 10401 25 'arm=ab'
bash research/leak-sweep/oarun.sh str   10402 20 'arm=str'
bash research/leak-sweep/oarun.sh leak  10403 20 'arm=leak'
bash research/leak-sweep/oarun.sh nosh  10404 20 'arm=nosh'
bash research/leak-sweep/oarun.sh v16   10414 20 'arm=leak&n=16&mx=65536&v=4096'   # RangeError, the ctor rule
bash research/leak-sweep/oarun.sh page64kc 10415 25 'arm=leak&n=16&mx=65536&v=65536'  # bl=65536 nz=16
```

Page `oobadj.html` (md5 `abcbaf947f09d5247f8a92e301187cf4`), runner `oarun.sh`
(md5 `39245ea6c74ae68e95d114d1dbb19be5`, kills only its own port); logs `/tmp/S_oa_*.log`, `/tmp/srv1040*.log`. `access: none` in all six.
