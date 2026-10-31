# 102 — the leak has no API producer left, and canvas is a lossless carrier once the packing is fixed

**Status:** measured 2026-10-30, quarantine off. Two results: a **negative that closes a search** (§1 — every
native consumer of a view reads the view's own zero page, so no API can leak), and a **correction that makes a
carrier usable** (§2 — `docs/98`'s premultiplication loss is its own byte packing, not the canvas: with alpha
255 and one byte per pixel, all 256 values survive).

## 1. The producer surface is closed by reading, not by sampling

`docs/96` found the one ungated producer and `docs/100` showed why it can only read mmap zeroes. The natural
next question was whether another consumer exists, so the tree was searched for the two shapes a leak needs:
a native `ArrayBufferView&` parameter (which skips the IDL converter that refuses resizable views,
`docs/96` §2's gate) and a copy into a JS-visible object.

`grep -rn "ArrayBufferView&" Source/WebCore` outside `bindings/js` gives exactly three families:

| site | direction | why it cannot leak |
|---|---|---|
| `page/Crypto.h:48` `getRandomValues(ArrayBufferView&)` | write | writes random bytes, never reads them out (`docs/97` measured it inert) |
| `html/canvas/WebGL*` (7 declarations) | both | `WebGL` is compiled out on this build (`docs/70`) |
| `Modules/indexeddb/IDBKey.cpp:55` | read | the only ungated read — `docs/96`, and `docs/100` proved the bytes are zeroes |

The copy sites that take `data()`+`byteLength()` are all reached through that same gated converter or handle an
`ArrayBuffer` rather than a view: `fileapi/BlobBuilder.cpp:60` (Blob parts, `BufferSource`), 
`bindings/js/StructuredClone.cpp:61` (`cloneArrayBuffer`, argument 0 via `toUnsharedArrayBuffer` and the
offsets from the builtin), `html/ImageBitmap.cpp:817` and `page/ShareDataReader.cpp:79` (an `ArrayBuffer`, not
a view), `fileapi/NetworkSendQueue.cpp:60` (an `ArrayBuffer`, and only `RTCDataChannel` reaches it, which is
compiled out). So every one of them copies from the **same committed zero page** `docs/100` measured.

**Conclusion: no API producer can leak.** The leak has to come from a memory-safety bug — a copy whose length
is not derived from the source's size, or an index/size underflow.

## 2. Correction: canvas is a lossless byte carrier when the packing is not the payload

`docs/98` closed glyph rasterisation with the observation that a 48-bit word read as RGBA has `0x00` in the
alpha slot of its middle pixel, so premultiplication zeroes the pixel. Re-measured as a **byte channel** —
8 (and then 256) bytes, one per pixel, in **R**, with **alpha forced to 255** — nothing is lost:

```
arm=real   0x00007f3a2b1c4d08 in=084d1c2b3a7f0000 got=084d1c2b3a7f0000   same=8/8
arm=toy    0x0000004200410000 in=0000410042000000 got=0000410042000000   same=8/8
arm=sweep  every value 0..255                                          same=256/256   lossy n=0
```

Page `research/leak-sweep/pxshape.html`, one arm per run, `access: none` throughout. So the premultiplication
that `docs/98` measured is a property of **which channel a byte lands in**, not of the canvas: keep the payload
in a colour channel and pin alpha, and arbitrary bytes — including `0x00` — round-trip exactly. `getImageData`
→ `toBlob` → `arrayBuffer` is therefore a faithful way to hand bytes from the engine's memory to page script or
to the lab host, which is what a leak needs on the output side.

## 3. Where that leaves the chain

The carrier half of the leak exists and is proven; the **source** half is the whole remaining problem, and it
must be a bug. Candidate classes, with the reason each is worth a run:

1. **A length that is not the source's size in a copy into JS.** The two live candidates are the `docs/99`
   GSUB over-read (glyph ids, other lane) and any future one; `docs/100` names why the visit is worth doing
   even though the usual consumer reads zeroes.
2. **A byte the engine writes into memory the page can already read.** `docs/98` §2 proved the canvas store is
   `tryFastCalloc` and the readback dense, so a pointer that reaches a pixel is readable — §2 above makes that
   exact.
3. **An index/size underflow** into a copy (`setLineDash`'s `Vector<double>` class, `docs/65`'s neighbourhood,
   never swept for a reader).

## 4. Limits and commands

- `arm=sweep` shows byte preservation, not pixel *order*: the page writes one byte per pixel, so it does not
  exercise the 2-pixels-per-word packing a real leak would still have to do by hand (4 bytes/pixel × 2 pixels
  for 8 bytes, alpha pinned per pixel — two words per row, one payload byte must land in each alpha and is
  therefore sacrificed; plan for 3 bytes per pixel usable).
- The measurement is on the ASAN oracle's ImageBuffer backend; the console's is Sony's. `docs/98` already
  records that the *store* is WebKit-side, so the packing rule is likely portable, but it is unmeasured there.

```
bash research/leak-sweep/oarun.sh px_real  1046x 20 'arm=real'  pxshape.html
bash research/leak-sweep/oarun.sh px_toy   1046x 20 'arm=toy'   pxshape.html
bash research/leak-sweep/oarun.sh px_sweep 1046x 20 'arm=sweep' pxshape.html
```
