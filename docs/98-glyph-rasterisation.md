# docs/98 — font/glyph rasterisation: no byte the rasteriser emits is an address

The last JS-visible byte source `docs/95` §8 left unprobed was text: glyph rasterisation,
`TextMetrics`, canvas `fillText`. This run built that sweep, corrected the leak detector it needed,
and closed the surface as a **negative** — with the reason measured, not argued.

Page `research/leak-sweep/glyph.html` (md5 `bdbb38ace96fa3c11253b8c93739cbf2`), runner
`research/leak-sweep/glyrun.sh` (md5 `0a2a60506410aa37d1c6410e52bff17c`), logs
`data/glyph-raster/`. Two runs, two processes, quarantine **off** (`~/wk/run_nq.sh`), fresh port each
(`pkill` of that port only), 26 `/proc/<WebKitWebProcess>/maps` samples per run:

```
ssh teo@<lab-ip> 'bash /tmp/wkp/glyrun.sh glyphA 8859 45 "" glyph.html' > data/glyph-raster/OUT_A.txt
ssh teo@<lab-ip> 'bash /tmp/wkp/glyrun.sh glyphB 8860 45 "" glyph.html' > data/glyph-raster/OUT_B.txt
python3 research/leak-sweep/diff.py data/glyph-raster/OUT_A.txt data/glyph-raster/OUT_B.txt \
        data/glyph-raster/maps_A.txt data/glyph-raster/maps_B.txt
```

## 1. The detector had to be corrected first, and the correction is measured

`docs/95`'s pixel rule pins three bytes (`b5 ∈ 0x60..0x7f`, `b6 = b7 = 0`). On antialiased white
text that fires on **premultiplied grey pixels**: a pixel with `R=G=B=A=0x68` followed by a
transparent one is the byte run `68 68 68 68 00 00 00 00`, whose `b5` is the green channel. The first
run (kept as the calibration, `data/glyph-raster/OUT_loose_A.txt`, 118 records) reported a hit on
**76 of its 118 records**, every one of that shape:

```
r0=… ptr=14[@18290=0x000075ffffffc8ff,@18770=0x000078ffffff82ff,@19250=0x000078ffffffdcff]
r1=… ptr=10[@16394=0x00006bfffffffaff,@16858=0x000079ffffff86ff,@19266=0x00006efffffff0ff]
```

An address in this build is `0x0000_6xxx_xxxx_xxxx` or `0x0000_7fxx_xxxx_xxxx`, i.e. **five** pinned
bytes: `b3 = 0`, `b4 = 0`, `b5 ∈ 0x60..0x7f`, `b6 = b7 = 0`. `b4 = 0` is the discriminator (bits
32..39 clear) and it rejects every one of the hits above, whose `b4` is `0xff`. The sharpened
`ptrscan` also counts the windows the loose rule would have reported, so the false-positive rate is a
number in the log rather than an opinion: **`grey=1678`** over the two runs, `ptr=0`.

The control fires, at every alignment:

```
det_ctl=pos=nz=4/16 ptr=1 grey=0[@0=0x0000610000010540] neg=nz=4/16 ptr=0 grey=0 align=11111111
```

and the scorer classifies that token inside the ASAN heap mapping: `0x610000000000-0x610000020000 rw-p`.

## 2. What the page renders

124 probe beacons per run (plus a `DONE` marker; the scorer sees 125 entries):
**63 rasterisation arms** (9 font configurations × 7 strings — Latin, kerning/
ligature text, combining marks, CJK, Arabic, Devanagari, emoji), **12 knob arms** (feature settings,
small-caps, condensed, tracking, `text-rendering`, RTL, baseline, `scale()`, `rotate()`, stroke,
shadow, filter), **11 odd widths** (1, 2, 3, 5, 7, 13, 33, 37, 101, 257, 509), a 4096-glyph run, a
231.7 px run, a 0.7 px run, two SVG-text arms, the DOM layout path, `toDataURL('image/png'|'image/jpeg')`,
and five control arms. Fonts: `local()` faces, a face split by `unicode-range`, a CJK face, a real
webfont over HTTP (7.6 MB DejaVuSans.ttf served from `/tmp/wkp`), a 4 KiB truncation of it, 1 KiB of
`0x41`, and a family that does not exist.

Every arm reports an ink census next to the scan, so a "no hits" can never be a vacuous one:
**80/80 ink-censused arms painted glyphs**, `px` from 84 to 24329, and the arms that paint nothing by
construction (never-touched margin, 1×1 corner) report `nz=0`. **4,835,556 bytes** were read back and
scanned across the two runs.

## 3. Result: zero

```
entries: A=125 B=125 shared=125
identical across runs: 125
changed across runs:   0
VERDICT: no value both changes between runs and lands in a mapping
```

Exactly two `ptr=1` records exist in each run and both are the sweep's own controls — `det_ctl`
(synthetic word) and `raw_chain` (the same word through `Blob → arrayBuffer`). Every surface the
rasteriser produced is `ptr=0`:

```
odd1=w=1 solid=1 nz=12/12 ptr=0 grey=0          odd509=w=509 solid=1 nz=6108/6108 ptr=0 grey=0
clip_rect=len=6400 w=40 nz=504/6400 ptr=0 grey=3 corner1=nz=0/4 ptr=0 grey=0
big_run=chars=4096 px=2582/amax=255 nz=10328/196608 ptr=0 grey=82
huge_size=px=24329/amax=255 nz=97316/524288 ptr=0 grey=86
svg_text=nat=160x64 ink[px=1220/amax=255] nz=4602/40960 ptr=0 grey=51
svg_knobs=nat=200x64 ink[px=1238/amax=255] nz=4471/51200 ptr=0 grey=43
churn=n=48 painted=48 with_ptr=0
```

The `toDataURL` outputs are deterministic functions of the pixels, and identical across ASLR:
`png=len=2042 h=110399503498536e`, `jpeg=len=3471 h=acb89e6c70766cd2`.

## 4. Why the canvas path cannot carry an address — measured

Three source facts and one measurement. The measurement is the one that closes it:

```
premult_proof=a0=0000000000000000 p0 aF=400501ff006100ff p0
raw_chain=len=32 nz=4/32 ptr=1 grey=0[@0=0x0000610000010540]
```

`premult_proof` writes the canonical word `40 05 01 00 00 61 00 00` into a canvas with
`putImageData`, reads it back, and gets **eight zero bytes**; the same word with alpha forced to
`0xff` survives as `40 05 01 ff 00 61 00 ff` — RGB preserved, no longer pointer-shaped, and the
detector refuses it. `raw_chain` pushes the identical bytes through `new Blob([u]).arrayBuffer()`,
a pipeline that is not premultiplied, and the detector sees it. So the detector is sensitive and the
canvas is the thing that cannot carry the word: a canonical 48-bit address has byte 3 = 0, i.e. it can
only sit in a pixel with alpha 0, where premultiplication zeroes RGB and the unpremultiply on read
returns 0 for all four bytes.

The source says the same thing three ways, and the width sweep measures the middle one:

- The backing store is **allocated zeroed**: `ImageBufferCairoImageSurfaceBackend::create` takes
  `stride = cairo_format_stride_for_width(CAIRO_FORMAT_ARGB32, width)` and
  `tryFastCalloc(height, stride)` (`ImageBufferCairoImageSurfaceBackend.cpp:86-88`).
- The readback is **dense**: `ImageBufferBackend::getPixelBuffer` copies with
  `destinationBytesPerRow = static_cast<unsigned>(4u * sourceRect.width())` (`:113`) and
  `zeroFill()`s a clipped destination (`:105`) — so source stride can never reach JS. Measured:
  `odd1..odd509` all `solid=1` with `nz` exactly `4·W·3`, i.e. no padding row and no gap.
- Glyphs never pass through WebCore memory on this port: `FontCascade::drawGlyphs` builds
  `cairo_glyph_t`s and calls `Cairo::drawGlyphs` (`FontCairo.cpp:52-80`), which is
  `drawGlyphsToContext` → `cairo_show_glyphs` (`CairoOperations.cpp:279-311`). There is no WebKit-side
  glyph atlas here; cairo/FreeType rasterises into the destination surface.

## 5. New facts about the text stack (all measured)

- **The canvas 2D context in this drop exposes no modern text properties.** `letterSpacing`,
  `wordSpacing`, `fontKerning`, `fontStretch`, `fontVariantCaps`, `textRendering` and `filter` are
  all `absent` (`cap=… direction=ltr font=10px sans-se …`), so those knobs are only reachable through
  CSS/SVG — which is why the sweep drives them through `svg_knobs` as well as the canvas arms.
- **A page can make the engine parse a font it served.** `@font-face { src: url(f.ttf) }` gives
  `face_gD=st=loaded load=loaded chk=true`, its 16 px width equals the system face's
  (`w_gA=182.7188`, `w_gD=182.7188`, versus `w_gG=173.8400` for a family that does not exist), and
  all twelve `TextMetrics` fields agree with the `local()` face field by field:
  `tm_gA=n=12 width:125.38,aBBLeft:0.00,aBBRight:125.38,fBBAscent:14.00,fBBDescent:4.00,aBBAscent:12.00,aBBDescent:1.00,emHeightAscent:14.00,emHeightDescent:4.00,hangingBL:14.00,alphabeticBL:0.00,ideographicBL:-4.00`
  (identical `tm_gD`).
- **The failure paths are inert.** A 4 KiB truncation, 1 KiB of `0x41`, and a nonexistent `local()`
  all give `st=error load=rejected:NetworkError`, and their measured width falls back to the same
  value as the nonexistent family (`173.8400`), so a failed face is not silently substituted.
- **`TextMetrics` reports 12 fields** and no others (`tm_fields=n=12 width,actualBoundingBoxLeft,
  …ideographicBaseline`). Their values are integers and doubles — no field is an address, and none
  moved between the two processes.
- **The DOM layout path agrees with the canvas path**: `dom_rect=w=1008.000 h=15.000 rects=1008.000 rw=283.013`
  (the `<p>` box versus its `Range`), and the text is laid out by the same `FontCascade`.

## 6. Controls

- `det_ctl` fires at all eight byte alignments and its negative twin does not (§1).
- `ink` proves the rasteriser ran; 80/80 arms.
- **Recycling canary**: a distinctive opaque 16-pixel pattern is painted into a 41×13 canvas, the
  canvas is discarded, and 64 fresh canvases at the same size class are read back —
  `canary=painted_ok=533/533 fresh=32 nz_bytes=3424 canary_found=0`. The opaque-context spelling is
  the one where unpremultiply is the identity, and it is separately measured:
  `opaque_fresh=7x3:0/84/p0/g0 33x17:0/2244/p0/g0 …` and
  `opaque_canary=painted=533/533 nz_px=1712 canary_found=0`.
- **Ghosting, bit-exact**: a canvas that only ever saw `H` versus one that saw `W` then a full red
  fill, then `canvas.width = canvas.width`, then `H` —
  `ghost=33x17:d0 red0 37x19:d0 red0 101x23:d0 red0 257x29:d0 red0`. Four odd sizes, zero differing
  bytes, and `red0` proves the reset really cleared.
- `churn` gives `n=48 painted=48 with_ptr=0`: 48 fresh text canvases at mixed size classes, every
  one painted, none carrying a pointer-shaped word.

## 7. Honest scope

- **What is proved:** across 125 records in two processes, no byte this build's text path hands back
  to JS is pointer-shaped, and the reason is structural: the canvas store is premultiplied and
  zero-allocated, the readback conversion is dense, and no WebKit-side glyph atlas exists on Cairo.
- **What is not:** this is not a proof that the rasteriser is memory-safe — only that its *output* is
  not an address. Media decode, IndexedDB value round-trips and accelerated canvas remain unprobed
  (`docs/95` §8), and nothing here is a console claim: the console ships its own FreeType/WebKit.
- **What it opens, and the next action:** the webfont arm is a page-reachable parser that is **not
  sanitised**. `grep -rn OpenTypeSanitizer Source/WebCore Source/WebKit` is empty in this drop, and
  `FontCustomPlatformDataFreeType.cpp:144` calls `FT_New_Memory_Face` on the buffer directly. The
  oracle's FreeType is 2.13.1 (`freetype-2.13.1-2.fc39`, distro library, not Sony's).

## 8. Oracle state

Nothing instrumented, no rebuild: every page is HTML served from `/tmp/wkp`, `ninja` idle, no server
left running (`glyrun.sh` kills only its own port). `EXIT=124` is the harness's normal end
(`timeout` kills MiniBrowser — `docs/65`, "Attempt 11"); `access: none` on both runs. Beacon dumps
and maps snapshots are committed under `data/glyph-raster/`, together with the loose-detector
calibration (`OUT_loose_A.txt`) and the scorer output (`diff_A_B.txt`).
