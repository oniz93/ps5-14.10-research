# docs/95 — the heap-address disclosure hunt: five JS-visible surfaces, all clean, and a second source-level deviation the IDL layer blocks

The action (`GOAL.md`, "give the page-chosen pointer something to point at — hunt one page-reachable
heap-address disclosure") proposed five value-producing boundaries and one scoring rule: a JS-visible
value that **changes between two runs of the same page** and **lands inside a mapping of the WebProcess
measured in the same run**. This run built that instrument, swept the five surfaces plus every readback
surface this build has, and adds two extra arms the action did not name (image/audio decoders, and the
`ArrayBufferView` bounds test found while reading the source).

Result in one sentence: **no JS-visible value in this build is an address — every one of the 180 probed
entries (193 beacon records including the per-part `BOOT`/`DONE` markers) is a constant, a URL, a generic message or a clock, all 17 memory-readback surfaces return
zeros, and the decoders return only their own pixels; the one source-level deviation found (an inverted
bounds test in `ArrayBufferView::byteOffset()/byteLength()`, absent upstream) is unreachable because
`JSGenericTypedArrayView::toWrapped` refuses every view whose buffer is resizable, which is measured
here in four consumer families.**

## 1. The scorer, and the three false positives it had to be taught

`research/leak-sweep/diff.py` parses two beacon dumps plus the `/proc/<WebKitWebProcess>/maps` snapshots
taken during each run, normalises the port out of the values, and answers three questions: which keys are
identical, which changed, and for every full-width hex token in either set, which mapping contains it.
The protocol is the action's: **a value that changes across ASLR is not yet a leak; a value that changes
*and* lies in a readable mapping is a candidate; a value that is stable is a constant.**

Three corrections were needed before the scorer was trustworthy, and they are the reason a naive sweep
would have produced a false positive on the first run:

- **An 8-digit hex token cannot be an address here.** The first scoring pass flagged `w_loc`/`w_stack`/
  `r_blob` as `ADDRESS-RANGE` because UUID bytes (`89ecfe54`) fell inside `0x7fff7000-0x8fff7000 rw-p` or
  the 2 TB `0x8fff7000-0x2008fff7000 ---p` reservation the WebProcess mmaps. Real pointers in this build
  print with 12–16 hex digits (`0x610000010540`, `0x000042004100`), so the token regex now requires
  ≥10 digits and the mapping filter requires a readable mapping (`r` in the perms), not `---p`.
- **A pointer-shaped word must be tested at byte 5, not byte 3.** The first version of the pixel scanner
  in `decode.html`/`raster.html` accepted any 8-byte window whose 4th byte was in `0x60..0x7f` with a zero
  high half — which matches ordinary RGBA pixel data followed by transparent padding. It reported two
  "hits" in a 3×3 high-quality resize (`0x000071800080aa5a`, `0x000071c80036aaa3`); both are pixel
  colours, and neither is inside any mapping. The corrected test requires `b[5] ∈ 0x60..0x7f, b[6]=b[7]=0`
  (a little-endian `0x0000_6xxx_xxxx_xxxx` / `0x0000_7fxx_xxxx_xxxx`) and is calibrated by a control that
  must fire: `det_ctl=pos=nz=4/16 ptr=1[@0=0x0000610000010540] neg=nz=4/16 ptr=0`, and the positive token
  lands in the ASAN heap mapping `0x610000000000-0x610000020000 rw-p` — i.e. a real heap pointer would be
  classified as a candidate, and the two pixel coincidences are outside every mapping.
- **A stub success is not a success.** `new Blob([view]).size` returning 223 for a 64-byte view is not a
  stale length; it is the *string* `"3,10,17,…"`. Every corpus entry therefore reports the JS-visible
  `byteLength` next to the consumer's result, so a conversion fallback is visible as such (§6).

## 2. Corpus, runner, commands

`research/leak-sweep/leakcorpus.html` (md5 `d0c6a6e2054539aabde7556901c5e3e7`) is a part-selectable page:
`?part=1` presence + native stringifications, `?part=2` clone/postMessage failure texts, `?part=3` stacks +
URL/performance/Intl, `?part=4` readback scans, `?part=5` ImageBitmap/message/worker, `?part=6` the probe
kept out of the sweep, and `?only=k1,k2` to bisect a single entry. `decode.html` (md5
`137d56090106362a09c63b37421e7568`), `raster.html` (`32033fe93710f87e8fee58beb860468b`), `oobview.html`
(`9ad4c6d7f41802b7d5bb34ca83f3aa67`), `oob2.html` (`f1fe8b36b959606f22045d120586e1d4`) and `inv.html`
(`d4ea2895a971f523b654b881160ae653`) are the extra arms. Runner `lkrun.sh` (md5
`64949928ca28fe7f094579e8671163ea`) adds a 25-sample `/proc/<pid>/maps` snapshot to the beacon log.

Every run below is `run_nq.sh` (quarantine **off**), a fresh port after `pkill -f "[h]ttp.server"`, scored
from the beacon log:

```
bash /tmp/wkp/lkrun.sh <tag> <port> 20-30 "part=<N>" [page]
# then, locally:
python3 research/leak-sweep/diff.py data/leak-sweep/OUT_p<A>.txt data/leak-sweep/OUT_p<B>.txt \
        data/leak-sweep/maps_p1A.txt data/leak-sweep/maps_p1B.txt
```

Each part ran **twice**, identical page, different port → different WebProcess → different ASLR.
`data/leak-sweep/` holds all 14 beacon dumps and the maps snapshots.

## 3. The five surfaces the action named — all negative

| part | entries | identical across ASLR (port normalised) | changed | changed value that is an address |
|---|---|---|---|---|
| 1 presence + native strings | 58 | 58 | 0 | — |
| 2 clone / postMessage failures | 21 | 21 | 0 | — |
| 3 stacks + URL/performance/Intl | 25 | 23 | 2 (`u_timeOrigin`, `u_now`) | no |
| 4 readback scans | 17 | 17 | 0 | — |
| 5 ImageBitmap / message / worker | 28 | 20 | 8 (blob UUID, 3 stacks embedding it, `Math.random`, `Date.now`, blob URL, `crypto.randomUUID`) | no |

What the values actually are (quoted from the runs):

```
# part 1 — presence and stringification
p_OffscreenCanvas=undefined      p_WebGLRenderingContext=undefined   p_SharedArrayBuffer=undefined
p_Atomics=object                 p_AudioContext=function             p_WebCodecsVideoFrame=undefined
p_WebAssembly=undefined          p_perfmem=undefined                 p_webglctx=no
n_win=[object Window] [object Window]
n_fonts=[object FontFaceSet] [object FontFaceSet]
n_port=[object MessagePort] false

# part 2 — every failure text is generic; no property path, no number
c_fn=THROW DataCloneError The object can not be cloned.
c_dup=DataCloneError: Duplicate transferable for structured clone
c_port=DataCloneError: The object can not be cloned.
c_getterthrow=THROW Error GT
c_node=null

# part 3 — stacks are URLs + line:col; the only clock is performance
s1=@http://127.0.0.1:12843/leakcorpus.html:106:39 T@http://127.0.0.1:12843/leakcorpus.html:28:57 part3@…
u_timeOrigin=1793384505953   u_now=33   u_hc=8   u_ua=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 …

# part 5 — bitmap, message and worker fields
b_created=2x2 [object ImageBitmap]        b_after_close=0x0
b_closed_transfer=DataCloneError: The object can not be cloned.
b_emptyblob=InvalidStateError: Cannot create an ImageBitmap from an empty buffer
m_self=origin=http://127.0.0.1:12847 srcwin=true srcnull=false ports=0 type=[object Window]
m_port=origin= srcnull=true ports=0 type=[object Null]
m_iframe_last=origin=null srcwin=false srcnull=false ports=0 type=[object Object]
w_bm={"k":"bm","w":7,"h":9,"t":"[object ImageBitmap]"} mainw=0
w_stack={"k":"stack","s":"onmessage@blob:http://127.0.0.1:12950/89ecfe54-…:5:35"}
```

The two changing entries in part 3 are `performance.timeOrigin` (a wall clock) and `performance.now()`
(millisecond resolution, `33` and `36.00000000000001` in the two runs) — neither carries an address and
neither is inside a mapping. In part 5 every changed value contains the blob UUID or a clock; the diff
script classifies all eight as `not-in-any-mapping`. **No entry in any part contains a ≥10-digit hex token at all**
(the only such token in the whole corpus is `det_ctl`'s deliberate control), so nothing could have been a
pointer.

## 4. Every readback surface this build has returns zeros

Part 4, 15/15 identical across runs:

```
z_ab=nz=0/64  z_u8=nz=0/64  z_f64=nz=0/64  z_u8c=nz=0/64  z_big=nz=0/64
z_rabmax=nz=0/64  z_rabgrow=nz=0/64  z_cloneab=nz=0/64  z_dataview=nz=0/64
z_canvas=nz=0/64  z_canvas_fill_resize=nz=0/64  z_creatid=nz=0/64  z_newid=nz=0/64
z_ab_big=nz=0/64  z_float32=nz=0/64
```

`z_rabmax`/`z_rabgrow` are the two resizable-buffer grows, and the zeros match the source: `ArrayBuffer::
grow/resize` memsets the new range (`ArrayBuffer.cpp:541`, `:627`), and allocation memsets the whole
buffer (`:140`). Part 5 adds `z_blob=nz=0/64` and `z_response=nz=0/64` for a `Blob`→`arrayBuffer` and a
`Response`→`arrayBuffer` round trip.

## 5. Decoders, rasters, audio — no heap bytes reach pixels

`decode.html`, two runs, 18/18 identical:

```
src_png=len=254 sig=137,80,78,71         src_jpg=len=893
d_png50=ok 32x32 nz=0/16384 ptr=0        d_png75=ok 32x32 nz=0/16384 ptr=0
d_png90=ok 32x32 nz=0/16384 ptr=0        d_png99=ok 32x32 nz=0/16384 ptr=0
d_pngflip=ok 32x32 nz=0/16384 ptr=0
d_jpg50=FAIL InvalidStateError: Cannot decode the data in the argument to createImageBitmap
d_jpg90=ok 32x32 nz=0/16384 ptr=0        d_jpgflip=FAIL InvalidStateError: …
d_garbage=FAIL InvalidStateError: …
svg_blur=ok 64x64 nz=800/16384 ptr=0     svg_turb=ok 64x64 nz=16346/16384 ptr=0
svg_offset=ok 64x64 nz=2/16384 ptr=0     draw_border=nz=0/16384 ptr=0
```

`raster.html`, two runs, 26/26 identical: five canvas-2D filter strings (`blur(16px)`, `blur(24px)`,
`drop-shadow(40px 40px 8px red)`, `brightness(0.5)`, `blur(8px) brightness(1.5) contrast(2)`), each over a
drawn gradient **and** over a single small rect on a transparent canvas; four `createImageBitmap` resize
qualities; `putImageData` clipped at the edge; an SVG `feTile`; all `ptr=0`. The two `o_rs3` hits the first
detector reported are the pixel-colour false positive of §1 and are recorded here as such.

Audio, measured rather than assumed: `ac_type=function  ac_state=suspended rate=44100`, and
`decodeAudioData` fails on **five** inputs (8 kHz and 44.1 kHz WAV, full and truncated):
`au_full=FAIL EncodingError: Decoding failed`, `au_t60`, `au_t95`, `au_f441`, `au_f441s` all the same;
`au_create=nz=0/4096`. So the audio-decode surface is unreachable in this build, which corroborates
`docs/93`'s "the AudioContext never leaves suspended" from a different direction.

## 6. The second lead: an inverted bounds test in `ArrayBufferView`, and why it does not fire

While reading the BufferSource path for an unrelated reason, the drop's `ArrayBufferView::byteOffset()` and
`byteLength()` turned out to test the bounds **inverted**. The drop
(`Source/JavaScriptCore/runtime/ArrayBufferView.h:74-124`):

```cpp
size_t byteOffset() const
{
    if (UNLIKELY(isDetached())) return 0;
    if (LIKELY(!isResizableOrGrowableShared())) return byteOffsetRaw();
    size_t bufferByteLength = m_buffer->byteLength(std::memory_order_seq_cst);
    size_t byteOffsetStart = byteOffsetRaw();
    size_t byteOffsetEnd = isAutoLength() ? bufferByteLength : byteOffsetStart + byteLengthRaw();
    if (UNLIKELY(!(byteOffsetStart > bufferByteLength || byteOffsetEnd > bufferByteLength)))
        return 0;                       // <-- returns 0 when the view is IN bounds
    return byteOffsetRaw();             // <-- returns the raw offset when it is OUT of bounds
}
```

Upstream WebKit main, fetched the same day from `raw.githubusercontent.com/WebKit/WebKit/main`, has the
same function **without the negation**:

```cpp
if (byteOffsetStart > bufferByteLength || byteOffsetEnd > bufferByteLength) [[unlikely]]
    return 0;
```

For an out-of-bounds view over a resizable buffer the drop therefore hands WebCore the *stale raw* length
and the *raw* offset — exactly the pair a `memcpy`/`setRange` uses — where upstream hands it 0. (For an
in-bounds resizable view the drop returns 0 instead, a functional bug.) `baseAddress()` is also unclamped
in both: `m_baseAddress.getMayBeNull(m_byteLength)`.

That would be an OOB read/write into every `BufferSource` consumer, so it was tested directly, with a
**fixed-length** view (not the length-tracking `new Uint8Array(ab)` form, which stays in bounds after a
shrink):

```
# inv.html — in-bounds resizable view, 64 bytes
c_in64=in64 BL=64 buf=64 max=64 | ImageData TypeError: Argument 1 ('data') to the ImageData
        constructor must be an instance of Uint8ClampedArray | Blob=223 | TD TypeError: Type error
c_plain=plain BL=64 buf=64 max=64 | ImageData ok len=64 b0=0 | Blob=64 | TD=64      <- non-resizable control
# oob2.html — fixed-length 4096-byte view, then resize(16)
pre=jsBL=4096 buf=4096
post=jsBL=0 buf=16 v0=undefined v100=undef
blob=TypeError: Underlying ArrayBuffer has been detached from the view or out-of-bounds
td=TypeError: Type error
resp=TypeError: Underlying ArrayBuffer has been detached from the view or out-of-bounds
imgdata=RangeError: Length out of range of buffer
digest_full=TypeError: Type error
digest_oob=TypeError: Type error
```

The wall is one function, and it is explicit in the drop
(`Source/JavaScriptCore/runtime/JSGenericTypedArrayViewInlines.h:928-934`):

```cpp
template<typename Adaptor> RefPtr<typename Adaptor::ViewType> JSGenericTypedArrayView<Adaptor>::toWrapped(VM& vm, JSValue value)
{
    auto result = JSC::toUnsharedNativeTypedView<Adaptor>(vm, value);
    if (!result || result->isResizableOrGrowableShared())
        return nullptr;
    return result;
}
```

**Every IDL `BufferSource`/typed-array parameter refuses any view whose buffer is resizable**, so
`ArrayBufferView::byteOffset()`/`byteLength()` is never reached with the one state that would make the
inversion dangerous. What the page *does* observe is the fallback: a resizable view in a union position is
converted as a **USVString**, so `new Blob([view]).size` is the length of `String(view)` (`"3,10,17,…"` →
223 for 64 elements, 142 for a grown 64, 46 for a 16-byte one) and `new Response(view).arrayBuffer()`
returns the same text (`resp_in64=len=223`, `resp_plain=len=64` for the non-resizable control). That is a
spec violation and a silent data corruption in any page that posts bytes from a resizable buffer, but it is
not memory-unsafe.

Two points are worth keeping for the next run:

- `wrappedAs()` — the *other* constructor, used for views that already exist as JS objects — deliberately
  **skips** the sub-range check for resizable buffers (`GenericTypedArrayViewInlines.h:107-115`: "It is
  possible that verifySubRangeLength fails when underlying ArrayBuffer is resized, but it is OK since it
  will be just recognized as OOB TypedArray"). That is the constructor whose output the inverted test
  mis-handles; it is reached from `possiblySharedImpl()`, i.e. from WebCore code that is handed a
  `JSArrayBufferView` directly rather than through IDL.
- The serializer is not that consumer: it works on `JSArrayBufferView` and clamps with the JSC-side
  `byteLength()` (`docs/91` measured `bl=0` over the ServiceWorker path).

## 7. Incidental, measured, and useful later

- **An `ImageBitmap` posted with no transfer list is copied, not rejected.** `b_notransfer=nosync`
  (no synchronous `DataCloneError`) and `b_notransfer_arrival=msg:[object ImageBitmap]` — the receiver gets
  a real bitmap. So `dumpImageBitmap`'s copy path (`SerializedScriptValue.cpp:1484-1534`) is reachable
  without a transfer list, which is a second way to drive the `docs/92`/`docs/94` machinery.
- **A truncated PNG decodes to a fully transparent bitmap instead of failing.** 50 %, 75 %, 90 % and 99 %
  of a valid 32×32 PNG all give `ok 32x32 nz=0/16384`; a truncated JPEG fails cleanly at 50 % and gives a
  transparent bitmap at 90 %. Silent blank, not uninitialised memory — but a page can detect the
  difference between "decoded" and "failed" only by reading pixels.
- **Unbounded recursion kills the WebProcess with no `RangeError` and no ASAN report.**
  `function r(n){return r(n+1)}` inside `try/catch` produced no beacon and no
  `ERROR: AddressSanitizer` line, 1/1 (`part=6` exists only to keep this out of the sweep). Probably an
  ASAN-build stack artefact, recorded because it is reproducible and it silently truncated one run
  (`P3` before `s4` was moved out).
- **`SharedArrayBuffer` is `undefined`, `Atomics` is `object`, `WebGL`/`WebGL2`/`OffscreenCanvas`/
  `WebCodecsVideoFrame`/`WebAssembly`/`double`-checked: all absent**, `AudioContext` present but
  `suspended`, `indexedDB`/`caches`/`serviceWorker` present. Consistent with `docs/92`/`docs/93`.

## 8. Honest scope

- **What is proved:** the five surfaces the action named produce no address-like value, in two
  independent processes, scored against `/proc/<pid>/maps`; every readback surface is zero-filled;
  truncated/corrupt PNG and JPEG decoding, SVG filters, `feTile`, canvas filters, `putImageData` clipping
  and `createImageBitmap` resizing produce no pointer-shaped word under a detector with a firing positive
  control; and the `ArrayBufferView` bounds inversion is real in source (absent upstream) but unreachable
  through `toWrapped`.
- **What is not:** this is not a proof that the build has no disclosure — it is a proof that these
  boundaries do not have one. Surfaces not probed: font/glyph rasterisation, media (`<video>`/`<audio>`
  elements have no decoder here), `indexedDB` value round-trips, and any *memory-safety* bug (an OOB read
  from a length confusion) rather than an API that exposes internals. The audio failure may be codec
  availability rather than the API being compiled out — `AudioContext` exists and `createBuffer` works.
- **What it changes for the programme:** the leak cannot be expected from an API that stringifies or
  copies engine state; it must come from a memory-safety bug. The most concrete such lead this run
  produced is §6: the drop contains a bounds test that, unlike upstream, returns the stale length for an
  out-of-bounds resizable view, and the only thing standing between it and an OOB read is `toWrapped`'s
  refusal. Any consumer that reaches `wrappedAs()`/`possiblySharedImpl()` with a `JSArrayBufferView`
  bypasses that refusal.

## 9. Oracle state

Left clean: no instrumented source on the oracle's tree (the run never rebuilt; all pages are HTML served
from `/tmp/wkp`), `pgrep -x ninja` idle, no server left running (`lkrun.sh` kills its own port at the end).
The 14 beacon dumps and the maps snapshots are committed under `data/leak-sweep/`.
