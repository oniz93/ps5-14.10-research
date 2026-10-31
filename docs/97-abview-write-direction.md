# docs/97 — the write direction of the inverted bounds test: zero page-reachable writers, measured

**Status:** measured 2026-10-30 on the drop, quarantine off, page `research/fuzz-cssom/caps16.html`
md5 `eb6f2c9a06571e687b1db3c6b8e5a783`. **Negative result, and a structural one:** the inverted
`ArrayBufferView::byteLength()` has no page-reachable write consumer in this build. 23/23 audit checks,
five engine arms, `access: none` throughout. This closes `docs/96`'s open question and the inverted-bounds
thread in both directions.

---

## 0. What was open

`docs/96` measured the **read**: `IDBKey::createBinary` is handed an out-of-bounds resizable view and copies
`byteLength()` bytes — raw length — out to JS as an `ArrayBuffer`. `docs/96` §6 left the other direction open:
`ArrayBufferView::setImpl` / `setRangeImpl` / `zeroRangeImpl` bound their `memmove`/`memset` with the same
`byteLength()` (`ArrayBufferView.h:221-262`), and `crypto.getRandomValues` was the obvious write consumer to
read first. The question for this run: **is there any site where the inverted length makes the engine write
past the buffer, and if not, why not — as a count.**

## 1. Answer

**Zero.** Every engine write path is gated before the native view is handed over, and the one ungated
producer (`IDBKey::createBinary`) is a read. Two independent reasons, each measured:

1. **The gate is uniform across every producer spelling.** There are six functions that turn a JS value into
   a native `JSC::ArrayBufferView` (or `JSC::ArrayBuffer`), and every one of them refuses
   `isResizableOrGrowableShared()` at the call site that the bindings use — including `[AllowShared]`.
   `possiblySharedImpl()` has four call sites; three are inside a gated function, and the fourth is
   `IDBKey.cpp:55`, which only reads. `tools/abview-write-sweep.py` asserts all of it: **23/23 checks**.
2. **The failure mode would need both halves anyway.** The inverted test also returns **0** for an
   *in-bounds* resizable view (`docs/96` arm `R0`), so a `byteLength()`-bounded write to an in-bounds
   resizable view fails **closed** (a zero-length no-op), not open. Only the OOB state yields raw length,
   and only an ungated producer can carry it.

Measured on one object, in one process: an 8192-byte view over a resizable 8192-byte buffer shrunk to 4112
reads `byteLength` 0, is provably still readable through the ungated key path (8192 bytes, pre-shrink
pattern intact), and **the bytes are byte-identical after nine write spellings (eleven arms) have been aimed at it**.

## 2. There are two `byteLength()`s, and only the native one is inverted

This is the fact that decides the whole direction, and `docs/96` did not name it:

| class | where | implementation | who uses it |
|---|---|---|---|
| `JSC::ArrayBufferView` (**native**) | `ArrayBufferView.h:98` / `:120` | `if (UNLIKELY(!(byteOffsetStart > bufferByteLength \|\| byteOffsetEnd > bufferByteLength))) return 0;` — **inverted** | WebCore consumers that hold a native view, and `IDBKey` |
| `JSArrayBufferView` (**JS wrapper**) | `JSArrayBufferView.h:300-320` | `length()` → `integerIndexedObjectLength(...).value_or(0)`; `byteLength()` → `integerIndexedObjectByteLength(...)` — **correct** | every JS-level spelling: `view[i]`, `set`, `fill`, `copyWithin`, `sort`, `DataView.set*` |
| `isOutOfBounds()` | `JSArrayBufferView.h:333-342` | `isArrayBufferViewOutOfBounds(...)` with an `IdempotentArrayBufferByteLengthGetter` | `validateTypedArray`, the serializer's gate, `DataView` |
| `inBounds(i)` | `JSGenericTypedArrayViewInlines.h:736-750` | `lengthRaw()` fast path, else **the live `existingBufferInButterfly()->byteLength()`** | the index-write path |

So the inverted arithmetic is reachable **only** through a native view, and a native view with a resizable
buffer is exactly what the bindings refuse to produce.

## 3. The producer table (audited, asserted)

Tool `tools/abview-write-sweep.py` (md5 `bcee113b46be8fd2760cea78646dc5ae`),
JSON `data/abview-write/sweep.json`, stdout `data/abview-write/sweep.txt`. `23/23 checks pass`.

| producer | site | gate |
|---|---|---|
| `JSArrayBufferView::toWrapped` | `JSArrayBufferViewInlines.h:94-99` | `if (!view->isShared() && !view->isResizableOrGrowableShared())` |
| `JSArrayBufferView::toWrappedAllowShared` | `:103-110` | `if (!view->isResizableOrGrowableShared())` |
| `JSGenericTypedArrayView<Adaptor>::toWrapped` | `JSGenericTypedArrayViewInlines.h:928-934` | `if (!result \|\| result->isResizableOrGrowableShared()) return nullptr;` |
| `JSGenericTypedArrayView<Adaptor>::toWrappedAllowShared` | `:936-942` | same |
| `JSArrayBuffer::toWrapped` / `toWrappedAllowShared` | `JSArrayBuffer.h:86-98` | same — so `(ArrayBuffer or ArrayBufferView)` unions are gated on **both** arms |
| `toPossiblySharedArrayBufferView` | `JSDOMConvertBufferSource.h:101-108`, one caller | `SerializedScriptValue.cpp:1377` tests `isOutOfBounds()` first (`:1382`) |
| `possiblySharedImpl()` — 4 call sites | `JSArrayBufferViewInlines.h:89` (inside `unsharedImpl`), `:107` (inside `toWrappedAllowShared`, after its gate), `JSDOMConvertBufferSource.h:106`, `IDBKey.cpp:55` | **3 gated, 1 ungated — and it reads** |

The binding layer is uniform, which is why `[AllowShared]` is not a bypass:
`Converter<IDLArrayBufferView>` uses `BufferSourceConverter<IDLArrayBufferView, Disallow>`
(`JSDOMConvertBufferSource.h:435-443`) and `Converter<IDLAllowSharedAdaptor<T>>` uses `Allow`
(`:457-470`) — `Disallow` → `toWrapped`, `Allow` → `toWrappedAllowShared`, both gated above.

`IDBKey::createBinary`'s body has **no write sink at all** (asserted): it goes
`possiblySharedImpl()` → `ThreadSafeDataBuffer::copyData(bufferView->data(), bufferView->byteLength())` →
`memcpy`, i.e. `docs/96`'s read.

## 4. The consumer census

### 4.1 IDL (parse of every `.idl`, statements, not lines)

36 statements in the drop mention `ArrayBufferView`. **7 are write consumers**, 29 are reads, types or
dictionary members:

| write consumer | idl | build state on this port |
|---|---|---|
| `getRandomValues` | `page/Crypto.idl:35` | **present** (`grv=function`), `WEB_CRYPTO ON` (`OptionsPlayStation.cmake:223`) |
| `readPixels` ×2, `getBufferSubData` | `WebGLRenderingContextBase.idl:614`, `WebGL2RenderingContext.idl:350/506` | **absent**, `ENABLE_WEBGL OFF` (`OptionsPlayStation.cmake:272`) |
| `copyTo` ×2 | `WebCodecsVideoFrame.idl:63`, `WebCodecsEncodedVideoChunk.idl:38` | **absent**, `ENABLE_WEB_CODECS ... PRIVATE OFF` (`WebKitFeatures.cmake:260`) |
| `read` | `FileSystemSyncAccessHandle.idl:36` | **absent**, `FileSystemFileHandle` and `navigator.storage.getDirectory` are `undefined` |
| (`writeBuffer`/`writeTexture`, WebGPU) | `GPUQueue.idl:48/54` | interface objects exist (`GPUQueue=function`) but `navigator.gpu` is `undefined` → no queue |

The reachable write consumers in source are exactly two, and both bound a write with the inverted length:

```
Crypto.cpp:57      ExceptionOr<void> Crypto::getRandomValues(ArrayBufferView& array)
Crypto.cpp:61          if (array.byteLength() > 65536) return Exception { QuotaExceededError };
Crypto.cpp:64/67       CCRandomGenerateBytes / cryptographicallyRandomValues(array.baseAddress(), array.byteLength())

TextEncoder.cpp:49 auto TextEncoder::encodeInto(String&& input, Ref<Uint8Array>&& array) -> EncodeIntoResult
TextEncoder.cpp:52     auto capacity = array->byteLength();
TextEncoder.cpp:51/63  U8_APPEND(static_cast<uint8_t*>(array->baseAddress()), written, capacity, token, sawError);
```

Neither has an in-body gate (asserted) — the refusal happens **before the call**, in the converter. The
65536 cap in `getRandomValues` is not a defence of this shape: it is a length cap, and it would let a
raw-length write of up to 64 KiB through if the gate ever missed.

### 4.2 Native-parameter census (C++ side)

20 `.cpp` functions take a native `ArrayBufferView&`/`*`; exactly **one** writes through it
(`Crypto.cpp:57`). The rest are WebGL (driver sinks, compiled out), `XMLHttpRequest::send`,
`WebSocket::send`, `RTCDataChannel::send` and `FetchBody` — all reads.

## 5. Measurements

Oracle `teo@<lab-ip>`, `run_nq.sh` (quarantine off), pages from `/tmp/wkp` on a fresh port, beacons
scored from the server log. Runner `research/fuzz-cssom/c16run.sh` md5
`b012a9b6c98b45bfc6f9ccc1bc640d24`. Every run: `EXIT=124` (the harness's normal end), `access: none`.

### 5.1 The battery, one object, one process

```
$ bash /tmp/wkp/c16run.sh w 9150 22 "arm=w"
caps16 arm=w only=- resize=function grv=function te=function idbkr=function sab=undefined gpu=undefined vf=undefined glctx=null glc=undefined
W pre jsBL=0 jsLen=0 off=0 bufBL=4112 dv=ok expect4128=122 expect5000=210
K ok type=ArrayBuffer bl=8192
K head=5a5b58595e5f5c5d at4128=7a7b78797e7f7c7d tail=a2a3a0a1a6a7a4a5
GR THREW=TypeError:Argument 1 ('array') to Crypto.getRandomValues must be an instan
GRn ok nz=8155 of 8192
GRi pre jsBL=8192 bufBL=8192
GRi THREW=TypeError:Argument 1 ('array') to Crypto.getRandomValues must be an instan
SE THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
FI THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
CW THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
SO THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
IX silent read4128=undefined read5000=undefined len=0
DV THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
DVg THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
DVb THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
TEn THREW=TypeError:Argument 2 ('destination') to TextEncoder.encodeInto must be an
XH THREW=TypeError:Underlying ArrayBuffer has been detached from the view or out-of
RB ok type=ArrayBuffer bl=8192
RB head=5a5b58595e5f5c5d at4128=7a7b78797e7f7c7d tail=a2a3a0a1a6a7a4a5
RBw ok type=ArrayBuffer bl=8192
RBw head=5a5b58595e5f5c5d at4128=9900000000000000 tail=0000000000000000
done arm=w
```

Reading it:

| arm | spelling | what the engine did |
|---|---|---|
| `K` | `IDBKeyRange.only(v)` | 8192-byte key, `at4128=7a7b…` — **the OOB view is live in this process** (`docs/96`'s path) |
| `GR` | `crypto.getRandomValues(v)` | `TypeError` — the converter refused: "must be an instance of" |
| `GRn` | the same call on a **non-resizable** view | wrote: `nz=8155 of 8192` — the call itself works |
| `GRi` | the same call on an **in-bounds resizable** view (`jsBL=8192`) | `TypeError` too — **the gate is resizability, not bounds** |
| `SE` | `v.set(vn, 0)` | `TypeError` (`validateTypedArray` → `isIntegerIndexedObjectOutOfBounds`) |
| `FI` | `v.fill(0x42, 0, 8192)` | same |
| `CW` | `v.copyWithin(0, 4096, 8192)` | same |
| `SO` | `v.sort()` | same |
| `IX` | `v[4128] = 0x43; v[5000] = 0x44` | **silent drop**: `len=0`, both reads `undefined` (spec: integer-indexed set on an OOB view) |
| `DV`/`DVg`/`DVb` | `DataView` created in bounds, used after the shrink | `TypeError` on `setUint8`, `getUint8` and `byteLength` (`viewByteLength` → nullopt) |
| `TEn` | `new TextEncoder().encodeInto("A".repeat(64), v)` | `TypeError` — the `[AllowShared] Uint8Array` converter refused |
| `XH` | `XMLHttpRequest.send(v)` | `TypeError` — same `validateTypedArray` message |
| `RB` | **the witness**: the key read again, after every arm above | `at4128=7a7b78797e7f7c7d` — **identical to `K`, byte for byte** |
| `RBw` | witness sensitivity: grow, write `0x99` at 4128, shrink, key again | `at4128=9900000000000000` — the witness sees a page write |

`RB` = `K` is the result: nine write spellings and two read spellings ran on this object and the
physical bytes did not move.

**Why the witness is a key read and not a grow-back.** The first version of the page grew the buffer back
and read `u[4128]`; it returned 0. The drop explains it
(`ArrayBuffer.cpp:540`):

```cpp
if (m_contents.m_sizeInBytes < newByteLength)
    memset(bitwise_cast<uint8_t*>(data()) + m_contents.m_sizeInBytes, 0, newByteLength - m_contents.m_sizeInBytes);
```

`ArrayBuffer::resize()` zeroes the newly-visible range on grow. Arm `grow` measures all three states:

```
$ bash /tmp/wkp/c16run.sh grow 9152 22 "arm=grow"
G pre bufBL=4112 key4128=122 key5000=210
G grown at4112=0 at4128=0 at8191=0
G shrink2 key4128=153 key5000=0
```

i.e. the pre-shrink pattern is readable **while shrunk** (122 = `4128^0x5a`, 210 = `5000^0x5a`), grow zeroes
it, and a page write through the grown window survives the next shrink (153 = `0x99`). That is why the
witness has to be the ungated key read, and why the key read is a valid witness at all.

### 5.2 Positive control: the same eight spellings, non-resizable view

```
$ bash /tmp/wkp/c16run.sh ctl 9151 22 "arm=ctl"
C pre jsBL=8192 len=8192 bufBL=8192
C set at4128=65
C fill at0=66
C copyWithin at0=65 at16=65
C index at5000=68
C dv at4128=69 dvGet=69
C encodeInto read=8 written=8 at0=65
C grv nz=8162 of 8192
```

Every one writes (`0x41`/`0x42`/`0x44`/`0x45`, `written=8`, `nz=8162`). So §5.1's refusals are attributable
to the one variable that differs — the buffer's resizability — not to a broken call.

### 5.3 Which layer refuses what

```
$ bash /tmp/wkp/c16run.sh ok 9154 22 "arm=ok"
O index in-bounds at4128=71
O dv in-bounds at5000=72 dvBL=8192
O encodeInto in-bounds TypeError:Argument 2 ('destination') to TextEncoder.encodeInto must be an
O grv in-bounds TypeError:Argument 1 ('array') to Crypto.getRandomValues must be an
O shrunk jsBL=0 len=0 dvBL=TypeError
O post-shrink index read=undefined
O post-shrink dv TypeError:Underlying ArrayBuffer has been detached from the view or out-of
O post-shrink encodeInto TypeError:Argument 2 ('destination') to TextEncoder.encodeInto must be an
```

On the **same** resizable buffer, before the shrink: `u[4128]=0x47` and `dv.setUint8(5000,0x48)` write
(71, 72), while `encodeInto` and `getRandomValues` are already refused. So the two layers are distinct and
each is doing its own job:

- **JSC layer** (`view[i]`, `DataView.set*`): follows the **live** bounds — writes in bounds, refuses when
  the view is out of bounds;
- **IDL converter layer** (`getRandomValues`, `encodeInto`, `send`, …): refuses **resizability** whether the
  view is in bounds or not.

### 5.4 The other write consumers, measured absent

```
$ bash /tmp/wkp/c16run.sh fl 9153 22 "arm=fl"
FL webgl=null webgl2=null videoframe=undefined encodedchunk=undefined videoencoder=undefined fshandle=undefined opfs=undefined gpuqueue=function
```

with `sab=undefined`, `gpu=undefined`, `glc=undefined` (`typeof WebGLRenderingContext`) and `glctx=null`
(`canvas.getContext('webgl')`). So of §4.1's write consumers, exactly one — `getRandomValues` — exists as a
callable entry point on this build.

## 6. What this is, and what it is not

**Is:** the write direction of `docs/96`'s inversion enumerated and measured to **zero** page-reachable
writers; the structural reason stated as a table (six producer spellings, all gated, plus the one ungated
read-only consumer); a measured two-layer gate (JSC follows live bounds, the IDL converter refuses
resizability); a correction to how the readback must be done (`ArrayBuffer::resize` zeroes on grow); and a
complete build-state census of the other write consumers (WebGL, WebCodecs, OPFS, WebGPU) as measured, not
assumed.

**Is not:** criterion 3, and not a write primitive. There is nothing here to weaponise: the inverted length
never reaches a write, and even if a producer were ungated the in-bounds side fails closed (length 0) while
the OOB side stays inside the buffer's own `maxByteLength` reservation.

**Newly closed for the next run:** the constructor spelling is gated too. `FontFace`'s `BinaryData` branch
retains a native view for the lifetime of the font face (`CSSFontFaceSource::m_immediateSource`,
`CSSFontFaceSource.cpp:103-106`, read at `:176`), which would be the ideal async window for a
shrink-after-the-fact — but `JSArrayBuffer::toWrapped` refuses resizable buffers (`JSArrayBuffer.h:86-92`),
so `new FontFace('x', resizableArrayBuffer)` never reaches `Uint8Array::create(buffer, 0, byteLength)`
(`FontFace.cpp:93`). Any future producer hunt must go through `Uint8Array::create`/`tryCreate` with a
page-supplied length, not through an IDL conversion.

## 7. Files

- page `research/fuzz-cssom/caps16.html` md5 `eb6f2c9a06571e687b1db3c6b8e5a783` (arms `w`, `ctl`, `grow`,
  `fl`, `ok`; `only=` filters the battery)
- runner `research/fuzz-cssom/c16run.sh` md5 `b012a9b6c98b45bfc6f9ccc1bc640d24`
- audit `tools/abview-write-sweep.py` md5 `bcee113b46be8fd2760cea78646dc5ae`, JSON
  `data/abview-write/sweep.json` md5 `75d62f8e5c43785f59a8591e9fedfdbc`, stdout
  `data/abview-write/sweep.txt`, **23/23 checks**
- logs `data/abview-write/S_c16_{w,ctl,grow,fl,ok}.log`, beacons `data/abview-write/srv915[0-4].log`

## 8. Next

The inverted-bounds thread is exhausted in both directions: one ungated producer, one read-only consumer,
zero writes. The action's own fallback applies — **font/glyph rasterisation**, the last un-swept JS-visible
byte source in this build (`docs/95`). The next run should take it with the same detector discipline:
render through many font/glyph configurations (webfont `@font-face` with `local()`/`url()`, `unicodeRange`
splits, `font-feature-settings`, subpixel AA on/off, `canvas` `fillText` at fractional sizes), read every
JS-visible output back (`getImageData`, `toDataURL` length, `TextMetrics` fields), and score it in **two**
ASLR runs with the `docs/95` detector plus its positive control. A pointer-shaped word that moves with ASLR
and lands in a mapping is a disclosure; anything stable is a constant and must be written as a negative.
