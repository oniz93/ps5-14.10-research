# 93 — grooming the 32-byte element: five schemes, all negative, and why the shape resists

`GOAL.md`, "turn the disengaged optional into a chosen address". `docs/92` §4 gives the shape and the arm
list; this run ran it. Result in one sentence: **the class is right, the free is real, and the element still
keeps the allocator's value — five shaping schemes leave `m_serializedBitmap` at `0x00000000002b6280`, and
the one thing the arms did settle is that the crash is *not* ASAN's malloc fill.**

Oracle `teo@<lab-ip>`, quarantine off (`~/wk/run_nq.sh`), one fresh port per arm, scored from the
harness log. Page `research/fuzz-cssom/caps11.html` (`f2aa6befd12d18c8bf88a2618b60f876`), runner
`research/fuzz-cssom/c11run.sh` (`ba79609b93a142fc5fa24da8ccf7f55c`), instrument script
`patch_ibt.py` (`3b884811c50a874709a77a7e852bd7f0`).

**Provenance first, because `docs/92` left the tree a moving target.** The oracle's
`Source/WebCore/bindings/js/SerializedScriptValue.cpp` is `b32d7b655…` — the *second* patch, i.e. the one
that dumps **24** bytes plus the engagement byte instead of 40, so it no longer trips its own
`heap-buffer-overflow` and no longer preempts the SEGV (`docs/92` §4 lists this md5 as its 10:05 state).
`pgrep -x ninja` was idle. Every run below is on that file; the print fires once per transfer and its own
line is quoted where it matters. **It has since been undone:** a concurrent session restored the oracle file to
the drop's `4e3d9ea56468dfa59230d48cea4b5321` and started a relink, so the build the next run finds has no
`[IBT]` line. `patch_ibt.py` re-applies the 24-byte version; without it a shaping arm is scored only from the
fault address or from the no-crash outcome.

---

## 1. Arm (a): the baseline, and the fill question

`docs/92` established the baseline under the default ASAN options: the element's 24 payload bytes are the
fill `0xbe`. The action's arm (a) expects exactly that. It is true — and it is **not the reason the pointer
is non-null**:

```
A (default options)   [IBT] … bytes=bebebe…be flag=0      → SEGV
B (max_malloc_fill_size=0)
                      [IBT] … bytes=97e601000000000080622b000000000100008067077f0000 flag=0   → SEGV
                      [IBT] … bytes=13ea01000000000080622b000000000100008067077f0000 flag=0   → SEGV
                      [IBT] … bytes=b9ea01000000000080622b000000000100008067077f0000 flag=0   → SEGV
```

With the fill disabled the bytes are **not** zero: `+0` varies per run (`0x0001e697`, `0x0001ea13`,
`0x0001eab9`) and **`+8` is `0x00000000002b6280` in all four runs**, which is the address
`SerializedImageBuffer::sinkIntoImageBuffer` loads the vtable from. So the 32-byte size class hands the
element a **deterministic recycled chunk**, and `docs/92` §4's release prediction ("zeroed ⇒ `connect()`
returns at `:83` ⇒ detached bitmap, no crash") is only one of two release outcomes — the other is this
recycled pointer, which crashes. `+24` (the engagement byte) is `0` in every arm: the decoder does
initialise it, and only the 24 payload bytes are uninitialised.

## 2. Arm (b) and (c): five shaping schemes, identical bytes

All arms are the same message in the same transport (`mode=bmptrans`, `MessageChannel`, `[bmp]`, the getter
closes the bitmap), with one groom variable. `gch=Z` is arm (c): zero bytes, so a landed chunk would give
`m_serializedBitmap == 0` and the `:83` early return, i.e. **the message arriving instead of crashing**.
`gch=X` plants the 8-byte pattern `41 41 41 41 00 00 00 00` at the start of every groomed chunk.

| arm | scheme | beacon | bytes at +8 | crash |
|---|---|---|---|---|
| B0 | none, fill off | — | `80622b00…` | yes |
| G1 | 200 × 512-byte `StringImpl`, dropped, 900 k objects of churn across a job boundary | `n=200&chars=492&rounds=...&dead=0` | `80622b00…` | yes |
| G2 | 64 CSS `@font-face` rules whose family is a 492-char string, rules deleted, `offsetHeight` re-laid out so `buildCompleted()` frees the faces and their strings | `faces=0&rulelen=551&rules=64` | `80622b00…` | yes |
| G2-12 | the same at a **12-char family** (`0x14+12 = 32`, the element's own class) | `faces=0&rulelen=71&faces0=64` | `80622b00…` | yes |
| G2-Z / G2-X | the same at 12 chars with zero bytes / the `41…` pattern | `gch=Z` / `gch=X` | `80622b00…` | yes |

The size sweep that found the class is part of the record too, because the action warned about it and the
first attempt still got it wrong: 492 / 1000 / 2000-character families (512 / 1024 / 2048-byte chunks) were
all negative before the instrumented run printed `sizeof=32 cap=1`, i.e. the `Vector` allocates **one
32-byte element**, not the 16 × 32 = 512 the deserializer's own prototype suggests.

The zero arm is the sharp one: `connect()` is `ASSERT(!m_bitmapData); if (!m_serializedBitmap) return;`
(`ImageBitmapBacking.cpp:82-84`) and `m_bitmapData`'s assert is compiled out, so a zero payload **must**
produce the early return and a delivered message. It crashed instead, 3/3. No chunk was landed.

Command shape (one arm, verbatim runner use):

```
bash research/fuzz-cssom/c11run.sh ibt3 10333 30 'mode=bmptrans&groom=2&glen=12&gch=X' \
  'detect_leaks=0:…:max_free_fill_size=0:max_malloc_fill_size=0'
```
```
wxR0&mode=bmptrans&g=2&gch=X&glen=12&rulelen=71&faces=0&faces0=64&ms=0&post=1
[IBT] sizeof=32 size=1 cap=1 idx=0 elem=0x6030000b46d0 bytes=13ea01000000000080622b000000000100008067077f0000 flag=0
==920168==ERROR: AddressSanitizer: SEGV … ImageBuffer.cpp:119
SUMMARY: AddressSanitizer: SEGV … ImageBuffer.cpp:119 in WebCore::SerializedImageBuffer::sinkIntoImageBuffer(…)
EXIT=124
```

## 3. Why it resists — three findings the next arm has to design around

1. **A `StringImpl` does not put page bytes at offset 8.** The layout is `m_refCount` (0), `m_length` (4),
   `m_hashAndFlags` (0xC), characters at **0x14** (`StringImpl.h:161-171`, `lengthMemoryOffset`,
   `flagsOffset`). At 32 bytes the chunk is `0x14 + 12` characters, so `+8` is the **length** (`0x0C`) and
   `+12..15` is header padding, not characters. Even a landed chunk would give
   `0x????0000000c`, never the planted `0x41…`. The `gch=X` pattern was therefore never able to show at
   `+8` on this class — a 32-byte allocation whose **byte 8 is data** is required (see §5).
2. **The vector is not allocated where the getter is.** `readTransferredImageBitmap` runs in the
   `WebMessagePortChannelProvider::takeAllMessagesForPort` reply dispatch (`:104`) — the
   `SerializedScriptValue` and its `m_backingStores` have already crossed to the network process and back.
   The getter's frees are the last *page* frees, not the last frees the allocation sees; the reply decode
   does its own, and one `0x2b6280` value survives all of them.
3. **The `WeakRef`-plus-churn witness cannot be used as the free side.** 200 `WeakRef` targets survived
   **900,000** `{}` allocations in the next job (`mode=wtest`, `dead=0`, 3/3 for `{}`, `new String` and a
   holder object). The reason is in the runtime, not the page: `JSWeakObjectRef::deref` treats a changed
   `currentWeakRefVersion` as a reason to **write-barrier the target** so it "stays alive if we wouldn't
   otherwise" (`JSWeakObjectRef.h:50-57`), and `finalizeSynchronousJSExecution` bumps that version per
   synchronous execution — so every poll re-roots the thing it is polling. The CSS `@font-face` scheme in
   §2 exists because of this: it frees deterministically with no GC at all (`faces=0` proves the faces left
   the set, `buildCompleted()`'s `m_cssConnectionsPossiblyToRemove.clear()` is the docs/65 free site).

One process-level note: the groom's own allocations are not free — `document.fonts.size` grows by 64 and
every `Image` beacon allocates. The 12-char arm moves all beacons out of the free→post interval and passes
its summary through the `wx` beacon instead; that change alone did not move `+8`.

## 4. Two residual audit rows `docs/90`'s table does not name

`docs/90` answers the family question and does not list these; both are validation-shaped, so they are
recorded here as **dead members** rather than left implicit:

- **WebAssembly across agent clusters.** `readTerminal` compares `agentClusterID` for `WasmModuleTag`
  (`:4562`) and `WasmMemoryTag` (`:4585`) and `fail()`s on a mismatch, and the only per-global cluster
  difference is the `-sharedworker`/`-serviceworker` suffix (`JSDOMGlobalObject.cpp:725-729`), so a
  `SharedWorker` port is exactly the channel that would fire it. It cannot: `WebAssembly` is `undefined`
  here, because `WEBKIT_OPTION_DEPEND(ENABLE_WEBASSEMBLY ENABLE_JIT)` (`WebKitFeatures.cmake:280`) with an
  interpreter-only build. Measured on the channel itself so the negative is the tag's, not the transport's:
  `swobj` echoes a plain object, `swu8` echoes `t=[object Uint8Array]`, and `swwasm`/`ifrwasm` beacon
  `nowasm`; a cross-origin `window.postMessage` (`127.0.0.1` → `localhost`) delivers an object (`ifrobj`,
  `ifrx got=1`) and likewise has no tag to carry.
- **`isTypeExposedToGlobalObject` (`:376`).** The only global in the switch is `JSAudioWorkletGlobalScope`,
  so the membrane is a `Blob` (or `File`/`ImageData`/`DOMPoint`) posted to an `AudioWorkletNode` port. The
  ASAN build has `ENABLE_WEB_AUDIO=ON` but the context never leaves `state=suspended` (no gesture, no audio
  device under Xvfb), so the processor is never instantiated and the port delivers nothing: `awblob` is
  `wx post=1`, `state=suspended`, then the 4.5 s timeout, 2/2. The console turns `ENABLE_WEB_AUDIO` off
  anyway (`OptionsPlayStation.cmake:256`), so the member is absent there by build flag.

## 5. What the next shaping arm needs

- **A 32-byte allocation whose byte 8 is page data.** `StringImpl` cannot do it. A 32-byte
  `SharedBuffer`/`Vector<uint8_t>` body can — e.g. a `Blob` built from a 32-byte `Uint8Array` — and the
  bytes are then fully chosen, so `+8` is `0x41…`, `+24` decides engagement and a zero payload produces the
  `:83` return.
- **The free has to land in the reply dispatch's job.** The blob body's free needs the wrapper's death, i.e.
  a scavenge — so either the blob is created and dropped in the job *before* the post and the churn runs in
  the reply's job (which the page cannot schedule), or the shaping allocation is one whose C++ owner the
  page can drop synchronously while the message is in flight. A second `MessageChannel` whose only task is
  the churn, posted ahead of the bitmap message on the *same* port, is one way to get page code into that
  queue position.
- **Score from the fault address, not the bytes.** The `[IBT]` print is a crutch; a landed `0x41…` gives
  `SEGV on unknown address 0x4141…` directly, and a landed zero gives `rx` + `det=0`.

## 6. Limits

- The class (`32 B`, `cap=1`, flag at `+24`, payload deref at `+8`) is measured on the ASAN build with
  `USE_SYSTEM_MALLOC`; the console's allocator is not ASAN's and its size classes differ.
- The instrumentation is not the drop's file, and the oracle is shared: the file was `4e3d9ea56468dfa59230d48cea4b5321`
  again before this run closed. Every future run must check the md5 (and `pgrep -x ninja`) before scoring;
  `patch_ibt.py` is additive if the payload print is wanted.
- Nothing here changes `docs/92`'s finding, and nothing here is a chosen address: the element is still
  uninitialised memory and the dereference still a virtual call on `0x2b6280`, i.e. a deterministic crash,
  not criterion 2.
