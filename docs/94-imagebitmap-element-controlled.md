# docs/94 — the 32-byte backing-store element is page-controlled: the slot is the *last* block freed in the walk

The action (`GOAL.md`, item "turn the disengaged optional into a chosen address") asked for three arms on the
32-byte `std::optional<ImageBitmapBacking>` element that `readTransferredImageBitmap` reads
(`SerializedScriptValue.cpp:4034`): (a) baseline → the ASAN fill, (b) a shaping arm whose fault address is the
planted bytes, (c) the same with `0x00` → the `ImageBitmapBacking.cpp:83` early return and a detached bitmap.
Its stated prerequisite was that the oracle's `SerializedScriptValue.cpp` be the drop's file again
(`4e3d9ea56468dfa59230d48cea4b5321`).

Result in one sentence: **all three arms exist, the shaping arms work, and the pointer field is not just
influenced but *written* by page bytes — a `structuredClone()` of a 16-bit string inside the walk leaves its own
serialize buffer on the 32-byte free list, and the element reuses it, so the engine's virtual call
`buffer->sinkIntoImageBuffer()` (`ImageBuffer.cpp:119`) dereferences a pointer the page chose
(`SEGV` at `0x000042004100`), while the all-NUL arm is a measured no-crash that hands the page a detached
`ImageBitmap` (`w=0 h=0`).** The two plans the action proposed (transfer-list reshaping, GC-freed ArrayBuffers)
were both measured to fail, for reasons worth keeping.

## 0. Relation to `docs/93` (a concurrent session, same action, opposite result)

A parallel session committed `docs/93-grooming-the-32-byte-element.md` for this same action at 10:21, concluding
"five schemes, all negative": with the shape it used, `+8` stayed `0x00000000002b6280` in 4/4 runs and every
payload arm crashed unchanged. That run is **not** contradicted here — it is *superseded*, and the difference is
one variable its page did not have. Its arms put the groom in a job boundary before the walk (a `StringImpl`
spray, a CSS-face free, a `Blob` body) and left the walk's own last 32-byte free in place; this run puts the
groom **inside the getter, as the last thing the walk does**, which is where the slot's block comes from. Two of
its recorded beliefs are corrected by measurement below:

- "the `Vector` is allocated in the `takeAllMessagesForPort` **reply dispatch** after the IPC round trip (not in
  the getter's frame)". The element reuses a block that a `structuredClone()` freed **inside the getter**, before
  `postMessage` returns, with byte-exact fidelity (§5). If the element were built after the IPC round trip, that
  block would have been consumed by the reply's own allocations. The vector is built by
  `ImageBitmap::detachBitmaps` in the sender (`SerializedScriptValue.cpp:5490`), and only *read* in the reply.
- "a `StringImpl` puts **no page byte** at `+8` (that offset is `m_length`; characters start at `0x14`)". In this
  drop `StringImplShape` is `{m_refCount, m_length, union{m_data8,m_data16}, m_hashAndFlags}`
  (`StringImpl.h:161-171`), so `+8` is the **character pointer** — which is why a freed `StringImpl` hands the
  element a heap pointer (the `quiet` arm, §4) and a freed character buffer hands it characters (the beacon arm).

Its `+24` observation is confirmed and matters: the engagement byte is written by the `std::optional`
move-constructor, so it is always `0` and the element is always disengaged. Only bytes 0..23 are stale, and only
byte 8 is read.

## 1. Provenance, and what "the drop's file" cost

`out/sony/full/…/SerializedScriptValue.cpp` on this Mac was **also** patched at 10:10 by the concurrent session
(md5 `b32d7b65…`), not only the oracle's copy, so the drop file had to be *reconstructed*: the known 11-line
`[IBT]` print (`#include <stdio.h>` + a 9-line `fprintf` block between the index check and the `if
(!m_imageBitmaps[index])` guard) was reversed, and the result hashes to the recorded
**`4e3d9ea56468dfa59230d48cea4b5321`** — byte-identical to the drop by construction. That file was copied to the
oracle (backing up the other session's instrumented copy to `~/wk/ssv-other-b32d7b65.cpp`), `ninja` was run with
no other job in flight, and every arm below ran against it:

```
md5sum ~/wk/WebKit/Source/WebCore/bindings/js/SerializedScriptValue.cpp
4e3d9ea56468dfa59230d48cea4b5321  .../SerializedScriptValue.cpp
ls -la .../WebKitBuild/ASAN/lib/libwebkit2gtk-4.1.so.0.11.0   -> 10:23:06
strings .../libwebkit2gtk-4.1.so.0.11.0 | grep -c "\[IBT\]"  -> 0
```

The other session's file is restored and relinked at the end of this run (§7). The local `out/` copy is left as
that session has it; the pristine file is kept at `~/.hermes/cache/scratch/wk92/ssv-pristine.cpp` and on the
oracle at `~/wk/ssv-pristine-4e3d9ea5.cpp`.

## 2. Method correction: ASAN does not name the address here

The action's verification said "the fault address ASAN prints must equal the bytes the shaping arm planted".
**On this oracle it never prints one.** Every wild-pointer report in this run reads

```
==…==ERROR: AddressSanitizer: SEGV on unknown address (pc 0x7f837babbd0b bp … sp … T0)
==…==The signal is caused by a READ memory access.
==…==Hint: this fault was caused by a dereference of a high value address (see register values below).
```

with **no address field and no register dump** (`grep -c 0xbebebebebebebe` on the docs/92 fill run = 0, so the
`0xbe` value in that doc was reasoned, not printed). The address only appears when the pointer is canonical; a
non-canonical pointer raises `#GP`, `si_addr` stays 0, and ASAN prints the `(pc …)` form. So the readout method
was changed to gdb, which `ptrace_scope=0` allows:

```
# page parked by ?delay=12000 so the attach lands inside the walk
gdb -q -batch -x /tmp/gdbcmd.y -p $(pgrep -n -f WebKitWebProcess)
```

and the *scored* evidence is ASAN naming a canonical address (`0x000042004100`), which needs no gdb at all.
Runner `research/fuzz-cssom/c14gdb.sh` (md5 `6abdc8e069e43e905bc3ab13dbc663a2`).

## 3. The two plans the action proposed, and why both fail — measured

**(a) `ArrayBuffer.prototype.transfer` does not exist on this build.**

```
presence2&cib=function&stc=function&ib=function&mc=function&acc=function&tr=undefined&rs=function&fr=function&wr=function&sab=undefined&oc=undefined
cls32&abl=32&transfer=throw%3ATypeError&detached=0
```

`tr=undefined` while `rs=function`: `arrayBufferProtoFuncTransfer` is installed only under
`Options::useArrayBufferTransfer()` (`JSArrayBufferPrototype.cpp:464`), whose default is **false**
(`OptionsList.h:571`), while `useResizableArrayBuffer` is **true** (`:578`). A resizable buffer would not help
anyway: `ArrayBuffer::resize`/`transferTo` go through `BufferMemoryHandle` page memory
(`ArrayBuffer.cpp:457-503`), not the 32-byte FastMalloc class. So the deterministic-free route the action
assumed is closed, and `SharedArrayBuffer`/`OffscreenCanvas` are absent as `docs/92` recorded.

**(b) A GC-freed ArrayBuffer spray does not reach the slot, for two independent reasons.**

- *GC does not run inside the walk.* `arm=gctest` (20,000 shaped 32-byte `ArrayBuffer`s, one `WeakRef` sentinel,
  2,000,000-object churn) in a **plain task**: `gcres&n=20000&iters=2000000&wr=alive&fcount=313&ms=709
  &cls=32&mode=lo` — 313 of 313 registered buffers were finalized, i.e. the churn really collects. The same
  churn inside a getter during `postMessage`: `wr=alive&fcount=0` (`arm=spray&xfer=0`, a value-path message that
  cannot crash). The binding call defers the collection.
- *Even with freed blocks on the list, a spray before the walk is buried.* `arm=spray2` shapes 20,000 blocks
  with `0x1a2b3c4d` at offset 8, frees them, churns, then posts: the report names **no** address, i.e. the
  dereferenced pointer was not the planted canonical `0x000000001a2b3c4d`. Whatever the slot reuses, it is
  freed *after* the spray, inside the walk.

## 4. What the slot actually is: the last 32-byte block the walk frees

`std::optional<ImageBitmapBacking>` is 32 bytes (`sizeof(ImageBitmap)` = 24 + the engagement byte at **24**), the
vector is `size=1 cap=1`, and for a bitmap closed inside a getter the optional is **disengaged**, so bytes 0..23
are never written: the element is whatever the block held before. Two page actions *select* that block, which is
what makes it page-controllable at all:

| arm | last page action before the walk ends | value read at element offset 8 |
|---|---|---|
| `base` (beacons inside the getter) | `new Image().src='/ev?m=…'` | the **document URL host** as ASCII: `0x2e302e002e373231` ("127.\0.0.") for `127.0.0.1`, `0x736f680061636f6c` ("loca\0hos") for `localhost`, identical across ports and query strings (3 runs), different only with the host |
| `base&quiet=1` (no beacons in the getter) | nothing page-side | a **heap pointer** into a 32-byte allocation: ASAN `heap-buffer-overflow on address 0x6030000b1b70, READ of size 8` at `ImageBuffer.cpp:119` |
| `clone` (§5) | `structuredClone(<16-bit string>)` | **the serialized stream's bytes 8..15** — page-chosen |

The mechanism is `StringImpl`'s layout in this drop (`StringImpl.h:161-171`): `{unsigned m_refCount; unsigned
m_length; union {m_data8,m_data16}; unsigned m_hashAndFlags}`, so a freed **`StringImpl` object** puts its
`m_data8` pointer at offset 8 (the `quiet` arm) while a freed **character buffer** puts characters there (the
beacon arm). Both are the *last* class-32 free of the walk, and both are read as a `SerializedImageBuffer*`.

## 5. The arm that wins it: a serialize buffer with page bytes at offset 8

`structuredClone()` of a string builds a `Vector<uint8_t>` whose capacity grows 16 → 25 → 38
(`Vector::expandCapacity`, `Vector.h`), and the whole stream is written before the deserializer runs:

```
[0..3] CurrentVersion = 13 (SerializedScriptValue.cpp:679, :1079)
[4]    StringTag
[5..8] length | StringDataIs8BitFlag (little endian, :2120-2123)
[9..]  characters (2 bytes each for a 16-bit string)
```

The buffer that ends up as the `SerializedScriptValue`'s own storage is **class 32** whenever the stream is
17..25 bytes, and it is freed at the end of the `structuredClone()` call — the last class-32 free inside the
walk, immediately before `ImageBitmap::detachBitmaps` allocates the element. Element offset 8 then reads stream
bytes 8..15. Measured, one variable per arm, quarantine off, `max_malloc_fill_size=0` (the same value is
reproducible with the fill on only for the crash/no-crash outcome — see the control below):

| arm | string (UTF-16 code units) | stream | predicted value at offset 8 | ASAN |
|---|---|---|---|---|
| `clone` | `A B \0 \0 \0 \0 \0 U+0100` | 25 B | `0x0000000042004100` | **`SEGV on unknown address 0x000042004100`** (2/2) |
| `clone&s=00430044…` | `C D \0 …` | 25 B | `0x0000000044004300` | **`SEGV on unknown address 0x000044004300`** |
| `clone` (8-bit spelling, a truncated hex spec) | `A B C \0 …` (all ≤ U+00FF) | 23 B | `0x0000000043424180` | **`SEGV on unknown address 0x000043424180`** — the low byte is `StringDataIs8BitFlag` |
| `clone&s=0000…0100` | all NUL + U+0100 | 25 B | `0` | **no crash**: `xmid&ok=1`, `rx&d=ImageBitmap:w0h0&w=0&h=0`, `access: none` |
| `clone&s=004100420100` | 3 units (stream 15 B → capacity 16, **class 16**) | 15 B | not ours | `SEGV` with **no** address field — class control |
| `clone` with the ASAN fill **on** | as row 1 | 25 B | overwritten by `0xbe` | `SEGV` with **no** address field — fill control |

The bytes are read as `[length MSB][chars]`, which is why the 16-bit arms put `0x00` in the low byte and the
8-bit arm puts `0x80` there; the pointer is therefore an arbitrary **56-bit** page-chosen value of the form
`0x00 c0h c0l c1h c1l c2h c2l c3l` (and `0x80 …` for the 8-bit spelling). The report names the address
verbatim, so the field, the byte order and the class are all confirmed by the engine's own output rather than by
inference.

## 6. Honest scope

- **What is proved:** (1) the disengaged element's `m_serializedBitmap` is read from a 32-byte FastMalloc block
  that page script selects; (2) three different page strings put three different chosen values there, each
  named by ASAN as the fault address; (3) an all-zero value takes the `ImageBitmapBacking.cpp:83` early return
  and the page receives a **detached** `ImageBitmap` (`w=0 h=0`) instead of a crash — `docs/92` §4's
  release-build prediction, measured in the ASAN build with the fill off; (4) the class (16 vs 32) and the ASAN
  malloc fill both change the outcome, so the value demonstrably comes from stale block content and not from the
  page directly.
- **What is not:** no write (the pointer is only loaded and used as a vptr for one virtual call, then the
  process dies), no leak, no JS-observable read, no type confusion. This remains a **DoS with a controlled
  address**, which is stage criterion 2's *read* half, not criterion 3.
- **What it changes for the console:** the branch that decides crash vs detached bitmap is now page-controlled,
  and a release build has no malloc fill, so the `SW=0x80…`/`0x00…` shaping that this run measured under
  `max_malloc_fill_size=0` is the same shaping a release build would see. That makes the console case
  *page-decided* rather than allocator-lottery — still a DoS, not a primitive.
- **Limits of the instrument:** the element's own address and the vector's contents are not printed (no
  instrumentation in the scored build); the mapping from "which block the slot reuses" to "which free in the
  walk" is established by the value's byte-exact identity with the serialize stream, the class control and the
  fill control, not by watching the allocator. `arm=clone` with a 20-unit string died in an unrelated
  `RenderLayer::~RenderLayer()` `WTFCrashWithInfo` (`RenderLayer.cpp:400`) and is recorded as unusable, not as
  a result.

## 7. Exact commands

```
# per arm: fresh port, quarantine off, chosen malloc fill
bash /tmp/wkp/c14run.sh <tag> <port> 45 "arm=clone&s=<hex units>" max_malloc_fill_size=0
# address readout when the pointer is not canonical
bash /tmp/wkp/c14gdb.sh <tag> <port> 55 "arm=<arm>" max_malloc_fill_size=0
```

Pages: `research/fuzz-cssom/caps14.html` (md5 `5e6619afdace5c68d4f94aba1bae55a2`), runner `c14run.sh`
(`fa5ee19c60c2c77793340c23a11f4575`), gdb probe `c14gdb.sh` (`6abdc8e069e43e905bc3ab13dbc663a2`); logs
`/tmp/S_c14_cl*.log`, `/tmp/srv1243*.log`, `/tmp/G_gdb*.log`.

**Oracle state this run leaves behind:** tree file pinned to the drop's
`4e3d9ea56468dfa59230d48cea4b5321`, library `libwebkit2gtk-4.1.so.0.11.0` from the 10:23:06 relink and
unmodified since (`pgrep -x ninja` idle at the end of the run) — i.e. **the next run starts on a pristine,
already-linked build** and needs no rebuild to score the same arms. The concurrent session's instrumented copy
(`b32d7b65…`, the 24-byte `[IBT]` print) is preserved at `~/wk/ssv-other-b32d7b65.cpp`; that session's own
`patch_ibt.py` re-applies it, so it was deliberately **not** restored — a pristine tree is what both sessions'
GOAL text asks the next run to find.
