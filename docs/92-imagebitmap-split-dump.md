# docs/92 — the split-dump shape: ImageBitmap's derived length is closed, its out-of-band backing store is not

The action (`GOAL.md`, item "the split-dump shape") asked for the one other page-reachable native whose
length is *derived* on read rather than carried — `ImageBitmap` — with a table of every `write(...)` pair in
`dumpImageBitmap`/`readImageBitmap`, then four arms: (a) `close()` before the dump, (b) `close()` after the
dump over both transports, (c) `resolutionScale` 0/`Infinity`/`NaN` and `IntSize` limits, (d) `WebCodecsVideoFrame`
and `OffscreenCanvas` only if their flags are on, measured.

Result in one sentence: **the derived length cannot disagree with the carried length on this native (the two
sides call the same truncating `IntSize::scale`, and the reader demands exact equality), but the transfer path
carries a second, out-of-band payload that the walk *can* invalidate — and the reader dereferences it without
checking that it is there. A page getter that closes a bitmap in the transfer list crashes the WebProcess
9/9 across three transports, at `ImageBitmapBacking::connect`.**

## 1. The write/read table (every pair)

`dumpImageBitmap` (`Source/WebCore/bindings/js/SerializedScriptValue.cpp:1484-1534`) and
`readImageBitmap` (`:4166-4201`), read line by line. `W` = what the writer writes, `R` = what the reader
derives from it.

| W (line) | bytes | R (line) | what the reader does with it | check on the reader side |
|---|---|---|---|---|
| `ImageBitmapTransferTag`, index (`:1488-1489`) | tag + `uint32` | `readTransferredImageBitmap` `:4023-4040` | indexes `m_backingStores`, the out-of-band vector | `index >= m_backingStores.size()` → `fail()` (`:4028`) — **an engagement check is missing** |
| `serializationState` (`:1521`) | `uint8` | `:4175` | `OptionSet<SerializationState>::fromRaw` at `:4199` | none needed (an option set) |
| `logicalWidth`/`logicalHeight` (`:1522-1523`) | 2 × `int32` | `:4180` `IntSize(w,h)` | destination `ImageBuffer` size **and** the source rect of `putPixelBuffer` | `ImageBitmap::createImageBuffer` returns null → `fail()` (`:4185`) |
| `resolutionScale` (`:1524`) | `double` → `float` | `:4182` `imageDataSize.scale(resolutionScale)` | `imageDataSize`, the length handed to `tryCreate` | none here — the equality below is the check |
| `colorSpace` (`:1525`, version > 8) | `DestinationColorSpace` | `:4175` | buffer colour space | — |
| `byteLength` (`:1527-1532`) | `CheckedUint32` | `readArrayBufferImpl<uint32_t>` | the in-line pixel buffer's length | `tryCreate` requires `computeBufferSize(format, imageDataSize) == arrayBuffer->byteLength()` **exactly** (`ByteArrayPixelBuffer.cpp:61-62`) |
| the pixels (`:1533`) | `byteLength` bytes | `:4191` `ByteArrayPixelBuffer::tryCreate(format, imageDataSize, arrayBuffer)` | the source pixel buffer | as above; then `putPixelBuffer(*pixelBuffer, {zero, logicalSize})` (`:4197`) |

**The rule this table gives.** The writer's `byteLength` is *not* `logicalSize.area()*4` — it is the byte
length of the pixel buffer `getPixelBuffer` produced for the rect, and that buffer's size is
`toBackendCoordinates(rect).size()` (`ImageBuffer.cpp:509-520`), i.e. `IntSize::scale(resolutionScale)`
(`ImageBufferBackend.h:163-170`). The reader computes `imageDataSize` with **the same** `IntSize::scale`
(`IntSize.h:95-104`: `static_cast<int>(static_cast<float>(m_width) * scale)`, a truncation). Same function,
same inputs, so the two numbers cannot disagree — which is what the exact-equality check at
`ByteArrayPixelBuffer.cpp:62` then enforces at runtime. There is no arithmetic gap to exploit here.

And `resolutionScale != 1` is not reachable from page script at all: the only 5-argument call to
`ImageBitmap::createImageBuffer` in the whole tree is the *reader* itself (`:4184`); every creator site
(`ImageBitmap.cpp:77, 272, 397, 467, 511, 644, 833`) uses the 4-argument overload whose default is
`resolutionScale = 1` (`ImageBitmap.h:95-96`). So arm (c) has no page-side input: a crafted stream is the
only way to put a non-1 scale in front of `IntSize::scale`, and no page-reachable API accepts crafted
serialized bytes. Measured corroboration: a 4×4 data-URI image with a `srcset … 2x` candidate at
`devicePixelRatio` 1 produces a 4×4 bitmap that clones (`img&nw=4&nh=4&dpr=1&bw=4&bh=4`,
`res2x&clone=ok:w4x4`) — at dpr 1 the 2x candidate is never chosen, so this arm shows only that the copy
path works, **not** that the scale is coerced; the source reading above is what settles it.

Arm (d) is measured absent in the same run: `presence&cib=function&stc=function&ib=function&close=function&oc=undefined&vf=undefined&mc=function&idb=object`
— `OffscreenCanvas` and `WebCodecsVideoFrame` do not exist on this build, so `dumpOffscreenCanvas`
(`:1536-1548`) and the video-frame paths are compiled out, exactly as `docs/77`'s lesson requires we check
rather than assume.

## 2. The one payload that is not in the stream

The transfer path splits the bitmap in two: the *stream* gets `ImageBitmapTransferTag` + index, and the
*bytes* travel beside it, in `Vector<std::optional<ImageBitmapBacking>>`. The two halves are produced at
different times, with the whole page-visible walk in between:

1. **Before the walk**, the transfer list is validated: `if (imageBitmap->isDetached()) return Exception { DataCloneError }`
   (`SerializedScriptValue.cpp:5397-5399`).
2. **During the walk**, `dumpImageBitmap` consults the transfer map *first* (`:1486-1491`), so a transferred
   bitmap's tag and index are written without the bitmap's buffer ever being read.
3. **After the walk** (`SerializedScriptValue.cpp:5481`), `ImageBitmap::detachBitmaps` (`ImageBitmap.cpp:137-145`) takes each backing store:
   `std::optional<ImageBitmapBacking> backing = bitmap->takeImageBitmapBacking();` — and for a bitmap that was
   closed in the meantime, `m_backingStore` is already `std::nullopt`, so the element stays **disengaged**.
   The vector keeps its size, so the index in the stream still validates.
4. **On arrival**, `readTransferredImageBitmap` does

```cpp
4034:            m_backingStores.at(index)->connect(*executionContext(m_lexicalGlobalObject));
4035:            m_imageBitmaps[index] = ImageBitmap::create(WTFMove(m_backingStores.at(index)));
```

`operator->` on a disengaged `std::optional` is undefined behaviour; it yields the storage anyway, and
`connect()`'s first real statement reads a field of an object that was never constructed:

```cpp
82:    ASSERT(!m_bitmapData);
83:    if (!m_serializedBitmap)
84:        return;
...
90:    } else if (is<Document>(context)) {
91:        m_bitmapData = downcast<Document>(context).page()->chrome().sinkIntoImageBuffer(WTFMove(m_serializedBitmap));
```

In an ASAN build that field is the allocator's fill, so it is non-null and the guard at `:83` passes.

## 3. The arms, measured

Page `research/fuzz-cssom/caps13.html` (final md5 `e2f28fcf10136e73ce5d1923ccf4bc4d`), runner
`research/fuzz-cssom/c13run.sh` (md5 `f72c516986aa678ded9832273137d6fa`), repetition wrapper
`c13rep.sh`. Quarantine **off** (`run_nq.sh`) throughout, a fresh port per arm, beacons scored from the
server log. One variable per arm; every arm has a twin that differs in one thing.

| arm | transport | what changes | result |
|-----|-----------|--------------|--------|
| `presence` | — | nothing | `cib=function … oc=undefined&vf=undefined` (§1, arm d) |
| `copy` | `structuredClone` | bitmap as a value | `copy&w=8&h=8&px=255,0,0,255&srcw=8` |
| `port` | MessagePort | copy, not transfer | `port&w=8&h=8&px=255,0,0,255&srcw=8` |
| `big` | `structuredClone` | 512×512 | `big&w=512&h=512&px=0,255,0,255` — the length check with a real 1 MiB payload |
| `xfer` | MessagePort | transfer, no close | `xfer&srcw=0&srch=0&ok=1&tag=msg` + `rx&w=8&h=8&px=255,0,0,255&d=ImageBitmap:w8h8` |
| `xferclose-pre` | MessagePort | closed **before** the call | `xferpre&ok=0&tag=threw&name=DataCloneError&m=The%20object%20can%20not%20be%20cloned.&srcw=0` |
| `copyclose-mid` | MessagePort | value (not transfer), getter **before** it closes it | `getter&when=beforedump` → `closed&srcw=0` → `copyclosemid&ok=0&tag=threw&name=DataCloneError` — the null-`buffer()` path is a clean `ValidationError` (action arm a) |
| **`xferclose-mid`** | MessagePort | transfer, getter **after** it closes it | **SEGV** — 5/5 (see below) |
| **`xferclose-win`** | `window.postMessage` | same, same process | **SEGV** — 2/2 |
| **`xferclose-wrk`** | dedicated worker | same, cross-thread | **SEGV** — 2/2, thread T9 |
| `xferclose-other` | MessagePort | getter closes a **different** bitmap | `closed2&b2w=0&bw=8` → `xother&ok=1` → `rx&w=8&h=8&px=255,0,0,255` — **no crash** |
| `res2x` | `structuredClone` | `srcset 2x` source at dpr 1 | inconclusive by construction (§1) |

The crash, verbatim (`/tmp/S_c13_xmid1.log`; identical in the four other MessagePort runs):

```
==901729==ERROR: AddressSanitizer: SEGV on unknown address (pc 0x7fd2f7abbcf4 bp 0x7ffdfa24dda0 sp 0x7ffdfa24dd90 T0)
==901729==The signal is caused by a READ memory access.
==901729==Hint: this fault was caused by a dereference of a high value address (see register values below).
    #0 … in WebCore::SerializedImageBuffer::sinkIntoImageBuffer(…) ImageBuffer.cpp:119
    #1 … in WebCore::ChromeClient::sinkIntoImageBuffer(…) ChromeClient.cpp:50
    #2 … in WebCore::Chrome::sinkIntoImageBuffer(…) Chrome.cpp:554
    #3 … in WebCore::ImageBitmapBacking::connect(WebCore::ScriptExecutionContext&) ImageBitmapBacking.cpp:91
    #4 … in WebCore::CloneDeserializer::readTransferredImageBitmap() SerializedScriptValue.cpp:4034
    #5 … in WebCore::CloneDeserializer::readTerminal() SerializedScriptValue.cpp:4731
    #6 … in WebCore::CloneDeserializer::deserialize() SerializedScriptValue.cpp:4911
    #10 … in WebCore::MessageEvent::create(…) MessageEvent.cpp:73
    #11 … in operator() MessagePort.cpp:292
EXIT=124
```

The worker transport takes the *other* branch of the same function — `:88`
(`WebKit::WebWorkerClient::sinkIntoImageBuffer`) instead of `:91` (`Chrome::sinkIntoImageBuffer`) — and dies at
the same `ImageBuffer.cpp:119`, on thread T9. So the defect is in `readTransferredImageBitmap`, not in the
document-only path.

The beacons of every crashing run are the same four lines and then silence — the message is posted, the getter
runs *after* the tag was written, and the process dies in the receiver:

```
cap&arm=xferclose-mid&ua=Mozilla/5.0 (X11; Linux x86_64) AppleWeb
pre&srcw=8
getter&when=afterdump
closed&srcw=0
```

## 4. What the field actually contains — and what that costs

The engine path was measured on the unmodified drop. While this run was being written, **another session
patched `SerializedScriptValue.cpp` on the oracle** (mtime 09:54, md5 `0518beb6d0ffc6d2a62da4c8ed5697b7`
against the drop's `4e3d9ea56468dfa59230d48cea4b5321`) with a 11-line `fprintf` that dumps the raw bytes of the
element, and relinked `libwebkit2gtk`. Those runs are contaminated and are recorded as such — but the print is
the measurement this section needed:

```
[IBT] sizeof=32 size=1 cap=1 idx=0 elem=0x6030000b6980 bytes=bebebebebebebebebebebebebebebebebebebebebebebebe00bebebebebebebe====…
```

Read it out: `sizeof(std::optional<ImageBitmapBacking>)` is **32**; the vector's `size` and `capacity` are
**1**; the element's 32 bytes are the ASAN fill `0xbe`, except **byte 24, which is `0x00`** — the engagement
flag. So the optional is disengaged, `m_bitmapData` (offset 0) and `m_serializedBitmap` (offset 8) are both
`0xbebebebebebebebe`, and the guard at `ImageBitmapBacking.cpp:83` passes on a pointer that was never
constructed.

Two consequences, both of which the record must keep straight:

- **Under ASAN the crash is deterministic (9/9) because the allocator fills the storage.** `malloc_fill_byte`
  is `0xbe`, so the field is reliably non-null. A *release* build has no fill: if the 32-byte allocation is
  zeroed or holds a null there, `connect()` returns at `:83`, `ImageBitmap::create(nullopt)` produces a
  detached bitmap, and the page sees `w=0 h=0` with no crash. That branch was **not** measured — it is the
  prediction this record makes explicit, and it is why this finding is not yet a console claim.
- **The dereferenced pointer is uninitialized memory, not attacker bytes.** Nothing here is a chosen address,
  which is why this is a DoS and not stage criterion 2 — yet. The hook for the next action is the exact
  shape the print gives: a **32-byte FastMalloc allocation**, `cap=1`, whose bytes 8..15 are dereferenced as
  a `SerializedImageBuffer*` and used for a **virtual call** (`buffer->sinkIntoImageBuffer()`).

The instrumentation's own ASAN report is a heap-buffer-overflow at `:4038` (`for (unsigned b = 0; b < 40; ++b)`
over a 32-byte element) — its bug, not the engine's, and it preempts the SEGV on that build. Both patched-build
runs are kept for the `[IBT]` line only.

The oracle is a moving target while that session works: the file was `0518be…` at 09:54, `b32d7b65…` at 10:05,
and a third relink was in progress when this run closed. **No run scored after 09:54 is on the drop's file** —
so the next run must check the md5 (`4e3d9ea56468dfa59230d48cea4b5321`) *and* wait for `pgrep -x ninja` to be
empty before it believes any beacon, and must record which md5 it ran against.

## 5. Honest scope

- **What is proved:** a page can put a bitmap into a transfer list, close it from a getter that runs during the
  serialization walk, and the receiving deserializer will call `connect()` on a disengaged
  `std::optional<ImageBitmapBacking>`, reading an uninitialized `std::unique_ptr` and dereferencing it. Nine
  crash runs on the unmodified drop (5 MessagePort, 2 `window.postMessage`; four of the five MessagePort logs
  retained) take the `Chrome` branch at `:91`; two more (worker) take the `WebWorkerClient` branch at `:88`,
  thread T9.
- **What is not:** no controlled address, no write, no leak, no type confusion; the pointer is the allocator's
  fill. The release-build outcome is unmeasured (§4). The console is still blocked on the Guide restart, so no
  hardware case exists for this bug either.
- **What the family rule now is, and it is worth more than the crash:** for `ImageBitmap` the derived length is
  *closed by construction* (same `IntSize::scale` on both sides + an exact-equality check + a creator population
  that can only produce `resolutionScale == 1`), and the one split that exists is not a length at all — it is
  the out-of-band payload of a transfer. Any future "split dump" candidate should be triaged on **which
  payload is out-of-band**, not on which length is derived.
- **Limit of the instrument:** `res2x` cannot answer the `resolutionScale` question at dpr 1; a device with
  dpr 2 would be needed, and the question is already settled by the call-site census in §1.

## 6. Instrument and reproduction

```
$ bash /tmp/wkp/c13run.sh xmid 12210 25 "arm=xferclose-mid"        # first crash, unmodified drop
$ bash /tmp/wkp/c13run.sh xoth 12211 25 "arm=xferclose-other"      # the isolation control
$ bash /tmp/wkp/c13rep.sh xferclose-mid 3 12400 25                 # 3 good runs of 4 tries (1 flaked: no page request)
$ bash /tmp/wkp/c13rep.sh xferclose-win 2 12500 25                 # 2/2
$ bash /tmp/wkp/c13rep.sh xferclose-wrk 2 12600 25                 # 2/2, T9
```

A flaked attempt is a harness artifact with a signature: an **empty** `/tmp/srv<port>.log` (the browser never
fetched). Three of fourteen attempts flaked this way; `c13rep.sh` retries and says so, and every crash quoted
above is from an attempt whose server log carries the four beacons.

Logs `data/imagebitmap-split/` (`frames.txt` = one summary block per crash log, `beacons.txt` = every arm's
beacon sequence, plus the 17 raw run logs). Page md5 `e2f28fcf10136e73ce5d1923ccf4bc4d`, runner md5
`f72c516986aa678ded9832273137d6fa`.
