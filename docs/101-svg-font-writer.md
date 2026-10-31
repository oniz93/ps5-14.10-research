# docs/101 — the SVG font writer: reachable on both halves, 52 arms with no sanitizer report, and one page-visible GSUB defect that is upstream's

`docs/99` closed the font *parser* (FreeType on page-supplied bytes) and left one font path never run:
`convertSVGToOTFFont`, where **WebKit itself assembles an sfnt out of page data**. It is the last
console-live font surface — SVG fonts are not behind a feature macro, so the code is in the
PLAYSTATION build — and unlike a fetched face it needs no network and no bytes the page did not
write.

This run answered the action in both directions:

- **Both halves are reachable.** An in-document `<svg><defs><font>` with a `font-family` on its
  `<font-face>` is used by a plain CSS `font-family` with **no `@font-face` at all** (advance
  measured at exactly the glyph's `horiz-adv-x`), and `url(x.svg#f1)` reaches `CachedSVGFont` with
  the same result through a different loader (§2).
- **52 arms, 82 arm executions, 11 MiniBrowser runs, 0 sanitizer reports, 0 aborts.** Every
  mutation the action listed — 20 000 segments, a `d` cut mid-command, no `d`, duplicate `unicode`,
  `horiz-adv-x` 0/0xFFFF, `units-per-em` 0, `ascent` > `units-per-em`, 65 536 glyphs, a mismatched
  bbox — plus the count-overflow and length-arithmetic arms this run added (§3).
- **One defect, and it is behavioural, not memory-unsafe:** any SVG font in which **two `<glyph>`
  ligatures share a first character loses ligature substitution entirely** — `w` falls back to the
  sum of the two single advances — while one ligature, or two with different first characters,
  substitute correctly. Six arms, one variable (§4). The malformed table is
  `SVGToOTFFontConversion.cpp:771-772`: the declared `LigatureSetCount` is the **pair** count while
  only one offset per *distinct first glyph* is emitted. **Upstream main carries the identical two
  lines**, so this is a WebKit bug, not a Sony deviation — the first of the programme's findings
  that is.

Page `research/svgfont/corpus.html` (md5 `2bb480a629a1ac5cab519ecaf17ddef9`, 52 arms), runner
`research/svgfont/sfrun.sh` (`8265f7217aad2e0a230fdfa7b132b7c1`), external-file generator
`tools/svgfont-ext.py` (`97a6d657952a92375896a3e47bbecc8f`); logs `data/svgfont/`.

## 1. The path, and a correction to the action's description

`CSSFontFaceSource::load` (`css/CSSFontFaceSource.cpp:156-176`) branches on `m_hasSVGFontFaceElement`:

```cpp
if (m_hasSVGFontFaceElement) {
    if (m_svgFontFaceElement && is<SVGFontElement>(m_svgFontFaceElement->parentNode())) {
        SVGFontElement& fontElement = downcast<SVGFontElement>(*m_svgFontFaceElement->parentNode());
        if (auto otfFont = convertSVGToOTFFont(fontElement))
            m_generatedOTFBuffer = SharedBuffer::create(WTFMove(otfFont.value()));
        if (m_generatedOTFBuffer) {
            m_inDocumentCustomPlatformData = createFontCustomPlatformData(*m_generatedOTFBuffer, String());
```

Two ways in, and both are page-only:

- **In-document.** `SVGFontFaceElement::rebuildFontFace()` (`svg/SVGFontFaceElement.cpp:262-298`)
  builds `CSSFontFaceSrcLocalValue::create(fontFamily())` for a `<font-face>` whose parent is a
  `<font>`, and calls `setSVGFontFaceElement(*this)` on it (:294). `Resolver::addCurrentSVGFontFaceRules()`
  (`style/StyleResolver.cpp:205-212`) then adds that rule to the document's font selector for every
  registered `SVGFontFaceElement`. So the page writes **no CSS rule at all**: `<svg><defs><font>` +
  `font-family: <that name>` is enough, and the load is synchronous inside style resolution.
- **External.** `@font-face { src: url(f.svg#f1) format(svg) }` → `CachedSVGFont::ensureCustomFontData()`
  (`loader/cache/CachedSVGFont.cpp:72-100`) builds an `SVGDocument` from the fetched bytes, picks the
  `<font>` by fragment identifier (`getSVGFontById`, :107) and converts it. Asynchronous, needs the
  URL to finish loading.

**Correction to the action and to `GOAL.md`:** the converter emits a **CFF/OTTO** font, not a
`glyf` one — there is no `loca` and no `glyf` table anywhere in the file. The 14 tables
(`convertSVGToOTFFont` :1535-1549) are `CFF `, `GSUB`, `OS/2`, `VORG`, `cmap`, `head`, `hhea`,
`hmtx`, `kern`, `maxp`, `name`, `post`, `vhea`, `vmtx`, and each glyph is a Type-2 charstring of
`0xFF`-prefixed 16.16 numbers (`writeCFFEncodedNumber` :1117-1121) separated by
`rMoveTo`/`rLineTo`/`rrCurveTo` and closed by `endChar`.

## 2. Reachability, measured

```
ssh teo@<lab-ip> 'bash /tmp/wkp/sf/sfrun.sh reach1 8931 35 "kinds=reach"'
BOOT arms=33 kinds=reach
BEG R1-indoc kind=indoc
RES R1-indoc w=100.00 w40=40.00 ctl=64.00 cw=100.00 n=1 st=loaded ms=13
BEG R2-ext kind=ext
RES R2-ext w=71.00 w40=28.00 ctl=64.00 cw=71.00 n=1 st=loading ms=15
BEG R3-none kind=none
RES R3-none w=64.00 w40=26.00 ctl=64.00 cw=64.00 n=0 st= ms=13
BEG R4-indoc-noface kind=indoc
RES R4-indoc-noface w=64.00 w40=26.00 ctl=64.00 cw=64.00 n=0 st= ms=13
BEG R5-indoc-js kind=indocjs
RES R5-indoc-js w=100.00 w40=40.00 ctl=64.00 cw=100.00 n=1 st=loaded ms=6
DONE n=33
```

- `w=100.00` at `font-size: 100px` for a glyph with `horiz-adv-x="1000"` at `units-per-em="1000"`
  is the font's own advance, against `ctl=64.00` for the same character in an unresolvable family.
  The face is in `document.fonts` (`n=1`) and `st=loaded`, i.e. `createFontCustomPlatformData` —
  `FT_New_Memory_Face` — accepted the OTF WebKit wrote.
- **`R5-indoc-js` is the control for the HTML parser**: the same font built with
  `createElementNS('font')` gives the identical width, so the earlier result is not "the HTML
  parser quietly made an `HTMLFontElement`". (Both spellings work.)
- **`R4` (a `<font>` with no `<font-face>` child) never loads**: `n=0`, the control width. There is
  no family name, so the generated rule matches nothing — the converter is never called.
- `R2-ext` was `st=loading` at 40 ms because the first *use* is what starts the fetch. With a warmed
  span and a 1.2 s wait the external half is real (§3, `X1`/`X5`: `w=100.00`, `ink=8000`).

## 3. The mutation matrix

Every arm is one variable away from `R1`. A `BEG` is sent before the arm and a `RES` after it, so an
abort names its own input; `ink` counts non-transparent pixels of the character painted at 100 px
(proves the page's path data reached the charstring, not merely that a face loaded), `wp` is the
width of a second, deliberately-mapped codepoint (proves the face is used even when the arm's main
character is not in its cmap).

```
ssh … 'bash /tmp/wkp/sf/sfrun.sh d2  8933 110 "kinds=d,attr,uni,len"'
RES D1-huge-segments w=100.00 … ink=6097 … n=1 st=loaded ms=109
RES D2-mid-command  w=64.00  … ink=1616 … n=1 st=unloaded
RES D3-hv            w=100.00 … ink=6400 … n=1 st=loaded
RES D4-quad-arc      w=100.00 … ink=1103 … n=1 st=loaded
RES D5-huge-coords   w=100.00 … ink=110  … n=1 st=loaded
RES D6-nan           w=64.00  … ink=1616 … n=1 st=unloaded
RES D7-many-movetos  w=100.00 … ink=0    … n=1 st=loaded
RES D8-no-d          w=100.00 … ink=0    … n=1 st=loaded
RES D9-empty-d       w=100.00 … ink=0    … n=1 st=loaded
RES A1-hgx0          w=0.00   … ink=8000 … n=1 st=loaded
RES A2-hgx65535      w=6554.00 … ink=8000 … n=1 st=loaded
RES A3-hgx1e9        w=6554.00 … ink=8000 … n=1 st=loaded
RES A4-upm0          w=100.00 … ink=8000 … n=1 st=loaded
RES A5-upm-neg       w=0.00   … ink=0    … n=1 st=loaded
RES A6-upm1          w=100.00 … ink=10000 … n=1 st=loaded
RES A7-upm1e10       w=709.00 … ink=15647 … n=1 st=loaded
RES A8-asc-huge      w=100.00 … ink=8000 … n=1 st=loaded
RES U1-dup           w=100.00 … ink=8000 … n=1 st=loaded
RES U2-ligature      w=100.00 … ink=2485 … n=1 st=loaded
RES U3-astral        w=125.00 … ink=8917 … n=1 st=loaded      (ctl=125.00: the astral glyph is not found)
RES U4-long-lig      w=100.00 … ink=0    … n=1 st=loaded
RES U5-space         w=60.00  … ink=0    … n=1 st=loaded
RES F1-longfamily    w=100.00 … ink=8000 … n=1 st=loaded
RES P1-panose        w=100.00 … ink=8000 … n=1 st=loaded
```

```
ssh … 'bash /tmp/wkp/sf/sfrun.sh n1 8936 280 "kinds=num"'
RES N1-1000   w=64.00 … wp=41.00 … st=loaded
RES N2-33000  w=64.00 … wp=41.00 … st=loaded
RES N3-65535  w=43.00 w40=17.00 ctl=64.00 cw=43.00 … ink=3500 … n=1 st=loaded ms=1005
ssh … 'bash /tmp/wkp/sf/sfrun.sh e1 8938 140 "kinds=ext2,num&only=N3-65535,N4-65536,…"'
BEG N4-65536 → RES N4-65536 w=64.00 … n=1 st=unloaded ms=619
```

```
ssh … 'bash /tmp/wkp/sf/sfrun.sh e2 8939 90 "kinds=ext2&gap=300"'
WARM X1-huge n=1 st=loading → PRE X1-huge n=1 st=loaded
RES X1-huge  w=100.00 … ink=6097 … n=1 st=loaded
RES X2-many  w=64.00 … wp=41.00 … ink=1616 … st=loaded
RES X3-noface w=64.00 … n=1 st=error
RES X4-badxml w=64.00 … n=1 st=loaded
RES X5-dup   w=100.00 … wp=56.00 … ink=8000 … st=loaded
```

What the matrix says, family by family:

- **`d`**: a 20 000-segment path (`ink=6097`) and 30 000 `M` commands (`ink=0`, a path of nothing
  but movetos) both convert. A `d` that ends mid-command (`M0 0 L100`) and a `d` containing `NaN`
  are **rejected as a font, not as a glyph** — `m_error` is set by `processGlyphElement` (:1288) and
  `convertSVGToOTFFont` returns `nullopt`, so the face ends `unloaded` and the page falls back
  wholly. `H`/`V` and `Q`/`A` produce correct geometry (`ink=6400` is exactly the 80×80 square,
  `ink=1103` the quadratic+arc blob) — the `CFFBuilder` handlers for those commands are
  `ASSERT_NOT_REACHED` (:1222-1227) but **never run**: `SVGPathParser::parse`'s default is
  `NormalizedParsing` (`svg/SVGPathParser.h:37`), which converts them to `lineTo` before the consumer
  sees them (`SVGPathParser.cpp:109-146`).
- **numbers**: `horiz-adv-x` 1e9 and 0xFFFF both clamp to one 16-bit advance (`w=6554.00`); `units-per-em`
  0 is replaced by the default 1000 (`A4` == `R1`); **`units-per-em="-1000"` is not**: `unitsPerEm()`
  (:88-98) only tests `!value` after `static_cast<unsigned>(ceilf(...))`, so a negative lands as a
  huge unsigned, the scale collapses to ~2.3e-7 and every advance becomes 0 (`A5`, `ink=0`);
  `ascent`/`descent`/`x-height`/`cap-height` of ±1e9 clamp into `int16` and the font still loads
  (`A8`).
- **`unicode`**: three glyphs claiming `"A"` load and the first sorted one wins (`U1`);
  a ligature substitutes where it is the only one (`U2`, `w=100.00` = the ligature's advance);
  an astral codepoint never matches (`U3`, width equals the control); a 200-character `unicode`
  value loads and `appendLigatureGlyphs` (:1300-1326) synthesises a single-codepoint glyph for every
  codepoint it mentions, which is why `U4`'s `'a'` measures the notdef advance with no ink.
- **counts**: 1000 and 33 000 glyphs convert and *are used* (`wp=41.00` = the generated glyph 0x105's
  405-unit advance, while `'A'` is simply not in their cmap and falls back — 64.00); **65 535
  glyphs is the largest font the writer accepts** and it converts, loads and is used (`w=43.00` from
  a generated 430-unit advance); **65 536 refuses the whole font** (`m_glyphs.size() >
  numeric_limits<Glyph>::max()` → `clear()` → `convertSVGToOTFFont` false → `st=unloaded`).
  At 65 535 glyphs `appendFormat4CMAPTable`'s `uint16_t segCount = bmpMappings.size() + 1` (:315) is
  65 536 → **0**, so the format-4 subtable declares no segments at all — and nothing breaks,
  because `appendCMAPTable` (:351-370) points *both* platform-0/encoding-3 and platform-3/encoding-10
  at the format-12 subtable, which carries every mapping. **Corrected 2026-10-30 by the measured bytes
  (`docs/104` §4): on the `N3` arm `bmpMappings` is 65 505, not 65 535 — its generated range crosses
  U+10000, so 30 mappings are non-BMP — so `segCount` is 65 506 and nothing wraps; `clampTo<uint16_t>`
  saturates `length` and `segCountX2` at 65 535 instead (real subtable: 524 064 bytes). The conclusion
  is unchanged: both surviving platform records point at the intact format-12 subtable.**
- **length arithmetic**: a 40 002-character family name (`F1`) truncates the `name` record's length
  field (`append16(m_fontFamily.length() * 2)`, :484) and the font still loads; a `panose-1` with 14
  numbers (`P1`) zero-fills rather than overflowing the 10-byte local (:519-533).
- **external**: a 175 KB SVG with the same 20 000-segment glyph renders identically to the
  in-document arm (`ink=6097`, the same number — the two halves go through the same converter);
  a 2.6 MB SVG with 33 000 glyphs loads and is used (`wp=41.00`); **a `<font>` with no `<font-face>`
  is `st=error`** — `firstFontFace()` returns null and `ensureCustomFontData` returns false (:93),
  unlike the in-document half where the missing element only means "never matched"; and a truncated
  XML file still loads, because `decoder->sawError()` (:85) is the *text decoder's* error flag, not
  XML well-formedness — the parser delivered a `<font>` with a `<font-face>` and no `<glyph>`, so the
  face loads with only glyph 0.

**No sanitizer report in any arm, and no `WTFCrash`/`RELEASE_ASSERT`.** 52 distinct arms, 82 arm
executions, 11 runs, `access: none` on every one.

## 4. The defect: two ligatures sharing a first glyph lose all substitution

Six arms, one variable each. `a`,`b`,`c`,`d` are 200-unit square glyphs; the ligature glyphs are
900/800/700-unit squares, so a substitution is a 30-pixel-wide difference in `w` and a large one in
`ink`:

```
G6-one-lig-ab        ligatures {ab}          text "ab"  → w=90.00 ink=8000   substituted
G4-two-lig-ab        ligatures {ab,ac}       text "ab"  → w=40.00 ink=1260   NOT substituted
G5-two-lig-ac        ligatures {ab,ac}       text "ac"  → w=40.00 ink=1260   NOT substituted
G7-three-lig-ab      ligatures {ab,ac,ad}    text "ab"  → w=40.00 ink=1260   NOT substituted
G8-two-difffirst-ab  ligatures {ab,cd}       text "ab"  → w=90.00 ink=8000   substituted
G9-two-difffirst-cd  ligatures {ab,cd}       text "cd"  → w=70.00 ink=8000   substituted
```

`w=40.00` is `a` + `b` (200 + 200 units), `w=90.00` is the ligature's own advance. `G4` and `G8`
differ in exactly one glyph (`ac` versus `cd`); the pair `G4`/`G8` therefore separates "more than
one ligature" from "ligatures sharing a first glyph", and `G7` shows it is not an artefact of two.
This is the common case in a real SVG font — `ff`, `fi`, `fl` all start with `f` — so the writer
silently drops ligature substitution for exactly the fonts that have a ligature set.

The cause is two lines of `appendLigatureSubtable`:

```cpp
    append16(ligaturePairs.size()); // Number of LigatureSet tables
    grow(overlappingFirstGlyphSegmentLengths.size() * 2); // Placeholder for offset to LigatureSet table
```

`:771-772`. The count is the number of **pairs**; the reader is given one offset per entry of
`overlappingFirstGlyphSegmentLengths`, which has one entry per **distinct first glyph** (:753-768).
For `{ab, ac}` both pairs sort together and the vector is `[2]` — one segment — so the subtable
declares **2 LigatureSet tables and carries 1 offset**; the second offset slot is the first
LigatureSet's own `LigatureCount`/offset bytes. The shaper rejects the lookup and *every* ligature
in the font stops working, not just the second one. `{ab}` gives `[1]` and a well-formed table
(`G6`), `{ab, cd}` gives `[1,1]` and two offsets (`G8`, `G9`).

The adjacent line `previousFirstGlyph = ligaturePairs[0].first[0]` (:761) is a **second, latent**
expression of the same confusion — after a transition it re-seeds the comparator with the *smallest*
first glyph rather than the current one. It has no observable effect here (the pairs are sorted
ascending, so the smallest cannot reappear in a later segment) and is **not** the cause of the
measured failure; it is recorded so the next reader does not have to re-derive that.

**Upstream main has both lines verbatim** (`raw.githubusercontent.com/WebKit/WebKit/main/Source/WebCore/svg/SVGToOTFFontConversion.cpp`,
fetched during this run): `append16(ligaturePairs.size());` and
`previousFirstGlyph = ligaturePairs[0].first[0];`. So this is not one of the drop's deviations
(unlike `docs/99`'s missing `fromEnd <= from` guard and `docs/95` §6's inverted bounds test) — it
is a WebKit bug that ships on every port, and the only reason it has gone unnoticed is that it is
silent.

**Not memory-unsafe**, and structurally can't be: see §5.

**Measured at byte level 2026-10-30 (`docs/104` §3).** The OTF was captured out of the engine at
`FT_New_Memory_Face` and the `G4` subtable reads
`0001 001a 0002 0008 | 0002 0006 000c | …`: `LigatureSetCount` = 2 with one offset written, and the
second slot holds `0x0002`, the first LigatureSet's own `LigatureCount`. fontTools 4.67 refuses to
decompile that subtable (`ValueError: bytes length not a multiple of item size`) and `hb-shape 2.8.1`
shapes `ab` as two glyphs; the lookup is feature 0 = `liga`, the only feature the `DFLT` script
enables. Two more facts from the same dump: glyph ids are assigned after
`std::sort(…, compareCodepointsLexicographically)` (:1430), so they follow the codepoint string and
not document order; and the Ligature offsets are relative to the set's start *including* its
`2 + 2n` header.

## 5. Why this surface cannot produce an out-of-bounds read of the OTF

Every count the writer can make inconsistent with its data is inconsistent in the *understating*
direction, and the tables all live in one contiguous `Vector<uint8_t>` that becomes a single
`SharedBuffer`:

- `appendFormat4CMAPTable` clamps the subtable length (`clampTo<uint16_t>`, :348) and truncates
  `segCount` (:315) **downward**; the real data is longer than declared, so a reader stops early.
- `appendNAMETable` writes `m_fontFamily.length() * 2` into a `uint16` (:484) — modulo, so also
  downward.
- `appendMAXPTable`/`appendHHEATable`/`appendHMTXTable`/`appendCFFTable` write `m_glyphs.size()`,
  which is capped at 65 535 by the constructor's own check (:1425-1428).
- the one *upward* inconsistency — the ligature subtable's count — makes the reader walk **into the
  same buffer**, because `GSUB` is table 2 of 14, not the last one; and the shaper rejects it before
  reading (`§4`, measured: the lookup is dropped, not followed).
- the only page-shaped allocation the writer makes is `m_result` itself, whose size the page
  chooses (glyph count × charstring length) and which is kept alive by
  `FontPlatformData::CreationData::fontFaceData` (`platform/graphics/FontPlatformData.h:250-252`,
  a `Ref<SharedBuffer>`) — a heap-shaping lever, not a read.

So the answer to the action's "(c) score from whether FreeType accepts the OTF WebKit wrote" is:
**45 of the 52 arms produced an OTF that FreeType accepted and the page then used**; four were
refused by the converter itself (two bad `d`s, the 65 536-glyph font, and the external `<font>`
with no `<font-face>`); `R3` is the empty control, `R4` never reaches the converter (a `<font>`
with no `<font-face>` has no family to match), and `R2`'s fetch was still in flight in the first
run and was superseded by `X1`/`X5`. None of them produces a sanitizer frame.

## 6. Limits

1. **The oracle's FreeType is 2.13.1** (`freetype-2.13.1-2.fc39`), the console ships Sony's; nothing
   here is a console claim about FreeType, only about the bytes WebKit writes.
2. **The shaper's response is measured on the oracle.** The malformed ligature bytes are
   port-independent (plain table assembly), but "the lookup is dropped" is this build's response to
   them.
3. **No byte-level dump yet.** §4's cause is read from the source and is consistent with all six
   arms; the OTF was not captured from the engine. That is the next action.
   **Done 2026-10-30 — `docs/104`:** the OTF was captured out of the engine for `G6`, `G4` and `N3`
   (1 348 / 1 536 / 6 947 424 bytes, `OTTO`, the same 14 tables, no `loca`/`glyf`) and §4's cause is
   byte for byte what the source says, with §3's clamp statement corrected.
4. `ASSERT` is compiled out in this build (`CMAKE_BUILD_TYPE=RelWithDebInfo`, and
   `strings libWTF.so | grep -c "ASSERTION FAILED"` is 0), so the `ASSERT(m_glyphs.size() < 0xFFFF)`
   at :294 and `Placeholder::populate`'s `ASSERT(delta < uint16 max)` at :118 cannot fire — a debug
   build would abort on arms `N3` and `G3` where this build loads. That difference is worth knowing
   before anyone reads a debug-build crash as a finding.
5. The mutation matrix is in-document; the external half got five arms (base, huge `d`, 33 000
   glyphs, no `<font-face>`, truncated XML) plus the duplicate-`unicode` file.
