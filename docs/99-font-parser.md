# docs/99 — the font parser: FreeType 2.13.1 takes the structured corpus cleanly, and the drop's
# vertical GSUB parser reads past its table buffer

`docs/98` ended on the one page-reachable parser this programme had never measured: the webfont,
whose bytes reach `FT_New_Memory_Face` (`FontCustomPlatformDataFreeType.cpp:144`) with **no OpenType
Sanitizer in the drop** (`grep -rn OpenTypeSanitizer Source/WebCore Source/WebKit` is empty). This
run built that corpus, ran it under the ASAN oracle with quarantine off, and answered the action in
both directions:

- **FreeType is clean on every arm**: 190 arms, all executed — **109 accepted / 77 rejected / 4
  crashed (the GSUB arms of §3)**, and **0 sanitizer reports on any FreeType input**. The accepted/rejected split is a per-table line (§2), which is what "write
  which families FreeType rejects cleanly" asked for.
- **WebKit's own vertical GSUB parser is not**: a `Coverage` format-2 range whose `end+1` wraps to
  0, or whose range descends, makes `LookupTable::getSubstitutions` read past the table buffer —
  `heap-buffer-overflow READ of size 2` at `OpenTypeVerticalData.cpp:182`, **7/7 over six runs and
  two font bases**, with the region being the 56-byte `openTypeTable` copy. Upstream main carries a
  guard this drop lacks, so this is the **third source-level deviation** of the family `docs/95` §6
  opened (§4).

Page `research/font-parser/corpus.html` (md5 `427eb11f5b12496dfb81569cb0cdaa3c`), generator
`tools/font-corpus.py` (`4c73950198f65ed5c9dee59b8cd910a0`), runner
`research/font-parser/fprun2.sh` (`892646c2b4a7189002b01633cbac9be7`), model
`research/font-parser/gsub-model.py` (`8a6597261aa2e79e509b333bca964b2e`); logs
`data/font-parser/`.

## 1. The corpus, and why it is structured rather than random

One real font per base, one mutation per arm, so an accepted arm and a rejected arm differ in exactly
one field. Base: `LiberationSans-Regular.ttf`, md5 `d7b4e92b03deb1865aa61328fd5ff400`, 410712 B, 19
tables; second base `DroidSansFallbackFull.ttf` (Han glyphs plus a real `vhea`/`vmtx`) for the
vertical arms; four unmodified real faces (Twemoji COLRv0, Noto-COLRv1, NotoEmoji, OpenSans).

```
ssh teo@<lab-ip> 'cd /tmp/wkp && python3 font-corpus.py \
  --base /usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf \
  --cjk-base /usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf \
  --out f --extra twemoji=…/Twemoji.ttf --extra colrv1=…/Noto-COLRv1.ttf \
  --extra notoemoji=…/NotoEmoji-Regular.ttf --extra opensans=…/OpenSans-Regular.ttf'
base …/LiberationSans-Regular.ttf md5=d7b4e92b03deb1865aa61328fd5ff400 tables=19
arms=190 cmap=8 control=1 dir=26 glyf=6 gsub=3 head=10 hhea=6 hmtx=3 loca=6 maxp=6
     name=3 post=2 real=4 trunc-file=15 trunc-table=76 vertical=7 woff=8
```

`f/manifest.json` md5 `8e20c9685e6f67968b4df7f7d8e66bda`. The families: **trunc-file** (15 cuts from
1 B to 45 B, the whole directory), **trunc-table** (76 cuts: for each of the 19 tables, the file is
cut at the table's start, +1 B, half-way and its last byte), **dir** (numTables 0/1/0x0FFF/0x1000,
`length` 0/0xFFFFFFFF, `offset` 0xFFFFFF00 / past EOF, duplicate `head`, four `sfntVersion`s,
checksums), **head** (`indexToLocFormat` 2/3/swapped, `unitsPerEm` 0/1/0xFFFF, `magicNumber` 0,
directory lengths 53/40/0), **maxp** (`numGlyphs` 0/1/0xFFFF/n+1, version 0.5, length 6), **loca**
(all-max, descending, all-zero, lengths 4/2/0), **glyf** (0x7FFF contours, 0x7FFF endPt, a
self-referencing composite, lengths 1/4/12), **hhea/hmtx** (`numberOfHMetrics` 0/0xFFFF/n+1, hhea
lengths 20/34/0, hmtx lengths 2/4/0), **cmap** (format 4 `segCountX2` 0xFFFE/0/2, `idRangeOffset`
0xFFF0, subtable length 4, format 4 → 12 and → 0, cmap length 4), **name/post**, **woff** (a valid
WOFF 1.0 encoding of the base plus seven malformed headers/directories), **gsub/vertical** (§3),
**real**.

The page loads each arm as `new FontFace('fp_<id>', 'url(f/<id>.ttf)')`, waits for `load()` with a
1.2 s race, then forces a glyph page fill with `measureText('AVTo')` and two layouts (a
`writing-mode: vertical-rl` run of `AVAWA` and of `中中中`), and beacons `BEG <id>` before and
`RES <id> st=… res=… w=… vh=… vj=…` after. **A crash therefore names its own input**: the last `BEG`
with no `RES`.

## 2. Result on the FreeType surface: 109 accepted, 77 rejected, zero reports

```
ssh teo@<lab-ip> 'bash /tmp/wkp/fprun2.sh f1 8894 150 "kinds=trunc-file,trunc-table&tmo=1200"'
   → 91 RES, DONE n=91 loaded=36 other=55, access: none
ssh … 'bash /tmp/wkp/fprun2.sh f2 8895 150 "kinds=dir,head,maxp,loca,glyf&tmo=1200"'
   → 54 RES, DONE n=54 loaded=41 other=13, access: none
ssh … 'bash /tmp/wkp/fprun2.sh f3 8896 150 "kinds=hhea,hmtx,cmap,name,post,woff&tmo=1200"'
   → 23 RES, DONE n=23 loaded=14 other=9, access: none
ssh … 'bash /tmp/wkp/fprun2.sh f5 8906 60 "kinds=cmap&tmo=1200"'
   → 8 RES, DONE n=8 loaded=8 other=0, access: none
```

185 unique `RES` records in `data/font-parser/` (`108 loaded / 77 error`) plus the `ctl` control from
the smoke run and the four crashing GSUB arms of §3 give the 190. The rejection line is per-table and
it is exactly where the tables sit in the file:

```
  FFTM   a:lo b:lo c:lo d:lo      GDEF   a:lo b:lo c:lo d:lo      GPOS   a:lo b:lo c:lo d:lo
  GSUB   a:lo b:lo c:lo d:lo      gasp   a:lo b:lo c:lo d:lo      glyf   a:lo b:lo c:lo d:lo
  kern   a:lo b:lo c:lo d:lo      name   a:lo b:lo c:lo d:lo      post   a:lo b:lo c:lo d:lo
  head   a:er b:er c:er d:er      hhea   a:er b:er c:er d:er      hmtx   a:er b:er c:er d:er
  loca   a:er b:er c:er d:er      maxp   a:er b:er c:er d:er      cmap   a:er b:er c:er d:er
  OS_2   b:er c:er d:er           cvt    a:er b:er c:er d:er      fpgm   a:er b:er c:er d:er
  prep   a:er b:er c:er d:er
```

A cut at any table at or after `glyf` **opens the face** (`TR-glyf-a st=loaded`); a cut at any table
before it does not (`TR-head-a st=error … rejected:NetworkError`). That is one line, and it says what
FreeType requires at open: `head`, `hhea`, `maxp`, `cmap`, `hmtx`, `loca`, `OS/2`, `cvt`, `fpgm`,
`prep`. Outlines are not required — but "loaded" is not "used": `TR-glyf-a` measures
`w=60.00` against the control's `55.56`, i.e. the face opened, had no glyph data, and the page fell
back per character. The width is the witness that separates "the engine accepts these bytes" from
"the engine renders with them".

Every mutation family is in the accepted set, which is the answer to the action's question — FreeType
2.13.1 **rejects none of them** at the parser level and none of them reached a sanitizer:

- `numTables` 0x0FFF and 0x1000 (`DR-numt4095/4096 st=loaded`), table `length` 0 and 0xFFFFFFFF and
  `offset` 0xFFFFFF00 and past EOF, duplicate `head`, all checksums 0xFFFFFFFF.
- `head.indexToLocFormat` 2, 3 and swapped against the real loca; `unitsPerEm` 0/1/0xFFFF;
  `magicNumber` 0 — this last one **is** rejected (`HD-magic st=error`), as are `sfntVersion` `OTTO`
  over a glyf font, `head` shorter than 54 B, and `maxp` shorter than 6 B.
- `maxp.numGlyphs` 0, 1, 0xFFFF and n+1, `maxp` version 0.5, `loca` all-max / descending / all-zero,
  `glyf` with 0x7FFF contours, a 0x7FFF endPt, or a composite that references itself: **all accepted,
  no report** — `GL-comp-self st=loaded` does not recurse, FreeType caps composite depth.
- `hhea.numberOfHMetrics` 0/0xFFFF, `hmtx` of 2 and 4 bytes, `cmap` `segCountX2` 0xFFFE/0/2,
  `idRangeOffset` 0xFFF0, subtable length 4, format 4→12, `name` count 0xFFFF, `post` v2 over a v3
  body: accepted.
- WOFF 1.0: the valid encoding loads (`WO-ok st=loaded`), and the seven malformed ones are exactly
  the `convertWOFFToSfnt` checks — bad `length`, `totalSfntSize` 12 and 65536, `origLength`
  0x7FFFFFFF, `offset` 0xFFFFFFF0, `compLength > origLength`, and a 20-byte truncation — all
  `st=error`, no report. All 15 tables of `WO-ok` decode byte-identical to the base (checked with a
  Python re-implementation of the converter before the run).

## 3. The one sanitizer report: vertical GSUB, coverage format 2

The vertical arms were added because `FontCustomPlatformDataFreeType.cpp` is not the only parser on
this path: with `ENABLE(OPENTYPE_VERTICAL)`, `OpenTypeVerticalData` reads `hhea`/`hmtx`/`vhea`/`vmtx`
and the whole `GSUB` itself **through `FontPlatformData::openTypeTable()`**, i.e. out of a
`Vector<uint8_t>` copy of the table (`FontPlatformDataFreeType.cpp:322-341`), with its own
`validateTable`/`validatePtr`/`isValidEnd` bounds checks (`OpenTypeTypes.h:74-102`).

Four arms carry a minimal synthetic `GSUB` — one `vert` feature, `lookupType 1`, `SingleSubst`
format 2, `Coverage` format 2 — assembled so the offset chain is legal at every validator:

```
GS-ctl        glyphCount 3, range 10..12          (well formed)
GS-wrap       glyphCount 1, range 0x8000..0xFFFF  (end+1 wraps to 0)
GS-desc       glyphCount 1, range 10..5           (descending)
```

`research/font-parser/gsub-model.py` walks the same chain and predicts, before the run:

```
GS-ctl : reads=3, no read leaves the table buffer
GS-wrap: range 0: start=32768 end=65535 fromEnd=0 diff=-32768 check indexTo+diff>1 -> False
         reads=32768 first read past the table buffer: indexTo=6
GS-desc: range 0: start=10 end=5 fromEnd=6 diff=-4 check indexTo+diff>1 -> False
         reads=65532 first read past the table buffer: indexTo=6
```

The run matches, and the report names the line:

```
==1359275==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x606000064df8 …
READ of size 2 at 0x606000064df8 thread T0
    #0 … WebCore::OpenType::BigEndianUShort::operator unsigned short() const  OpenTypeTypes.h:44
    #7 … WebCore::OpenType::LookupTable::getSubstitutions(…) const  OpenTypeVerticalData.cpp:182
    #8 … WebCore::OpenType::FeatureTable::getGlyphSubstitutions(…) const  OpenTypeVerticalData.cpp:219
    #9 … WebCore::OpenType::GSUBTable::getVerticalGlyphSubstitutions(…) const  …:375
    #10 … WebCore::OpenTypeVerticalData::loadVerticalGlyphSubstitutions(…)  …:493
    #11 … WebCore::OpenTypeVerticalData::OpenTypeVerticalData(…)  …:422
    #12 … WebCore::OpenTypeVerticalData::create(…)  …:415
    #18 … WebCore::FontCache::verticalData(…)  FontCache.cpp:343
    #19 … WebCore::Font::Font(…)  Font.cpp:94
    #23 … WebCore::CSSFontFaceSource::font(…)  CSSFontFaceSource.cpp:218
0x606000064df8 is located 0 bytes after 56-byte region [0x606000064dc0,0x606000064df8)
allocated by thread T0 here:
    #3 … WTF::VectorBufferBase<unsigned char, WTF::FastMalloc>::allocateBuffer  Vector.h:320
```

56 bytes is exactly the length of the arm's `GSUB` table, and the read that dies is
`substitute[indexTo]` with `indexTo` 6 — the first index whose two bytes start at the end of the
copy. Repetition, one arm per run:

| arm | base | runs | result |
|---|---|---|---|
| `GS-wrap` | Liberation Sans | 3 (f4, gsw2, gsw3) | heap-buffer-overflow, `OpenTypeVerticalData.cpp:182` |
| `GS-desc` | Liberation Sans | 1 (f4a) | same report, same line |
| `CJ-gsub-wrap` | DroidSansFallbackFull | 2 (cjw1, cjw2) | same report, same line |
| `CJ-gsub-desc` | DroidSansFallbackFull | 1 (cjd1) | same report, same line |

7/7. Note the reachability detail this establishes: the crashing `Font::create` runs from
`CSSFontFaceSource::font` with a **vertical `FontDescription`**, i.e. a page that lays out any
`writing-mode: vertical-rl` run with a webfont reaches the whole chain — no CJK glyph is needed,
which is why the Latin-base arms fire first.

## 4. Why: the drop is missing a guard upstream has

`OpenTypeVerticalData.cpp:167-184` in the drop:

```cpp
uint16_t from = coverage2->ranges[i].start;
uint16_t fromEnd = coverage2->ranges[i].end + 1;     // OpenType "end" is inclusive
if (indexTo + (fromEnd - from) > countTo)
    return false;
for (; from != fromEnd; ++from, ++indexTo)
    map->set(from, singleSubstitution2->substitute[indexTo]);
```

Upstream main, same function, read this run:

```cpp
unsigned from = coverage2->ranges[i].start;
unsigned fromEnd = coverage2->ranges[i].end + 1;
if (fromEnd <= from || indexTo + (fromEnd - from) > countTo)
    return false;
```

Two changes, and either alone is enough: the `fromEnd <= from` guard rejects a wrapping or
descending range, and the `unsigned` locals stop `end + 1` from wrapping at 0xFFFF in the first
place. The drop has neither, so `fromEnd - from` is negative for those ranges, the `>` test passes,
and the loop runs `from` through the uint16 wrap — 32768 reads for the 0x8000..0xFFFF range, 65532
for the descending one — indexing `substitute[]` far past its `glyphCount` entries. It is the same
shape as `docs/95` §6's inverted `ArrayBufferView::byteLength()`: a bounds test that is correct in
upstream and wrong here. This is the third such deviation the programme has measured.

## 5. Controls

- `ctl` (unmodified base) loads, `w=55.56` against the fallback's `56.00` — the width is the witness
  that the webfont, not the cascade fallback, is measured.
- `GS-ctl`: same assembler, same table position, in-range coverage — `st=loaded w=55.56`, no report.
  So the crash is the range, not the synthetic `GSUB` and not `rebuild()`.
- `CJ-rebuild`: the second base through `rebuild()` with no extra table — identical to `CJ-ctl`
  (`st=loaded w=56.00 vj=72`), so the rebuild itself is inert.
- `CJ-gsub-ctl`: the well-formed `GSUB` on the second base — identical again, no report.
- `WO-ok` round-trips to the base byte for byte through an independent implementation of
  `convertWOFFToSfnt` (§2), so the WOFF arms test the converter and not the encoder.
- The four `CO-*` real faces (COLRv0, COLRv1, monochrome emoji, OpenSans) all load and only
  OpenSans changes the measured width (`54.36`) — the three emoji faces have no Latin glyphs, which
  is the same "loaded ≠ used" distinction as §2.

## 6. Honest scope

- **What is proved:** (a) across the 186 non-crashing arms, FreeType 2.13.1 (`freetype-2.13.1-2.fc39`, the
  oracle's distro library — **not** Sony's) neither crashes nor trips ASAN on this corpus, and the
  per-table split in §2 is where it stops; (b) a page webfont whose `GSUB` has a wrapping or
  descending `Coverage` format-2 range makes this build read past a heap buffer, deterministically,
  from a plain `@font-face` plus a vertical run.
- **What is not:** the FreeType result is a *parser-surface* result on a different FreeType than the
  console ships, so it is not a console claim. The GSUB bug is **compiled out on PlayStation**:
  `ENABLE_OPENTYPE_VERTICAL` defaults to 1 only for `PLATFORM(GTK) || PLATFORM(WPE)`
  (`PlatformEnable.h:887`) and `OptionsPlayStation.cmake` never sets it, so the console has neither
  `OpenTypeVerticalData` nor this loop — the same reason `openTypeTable()`'s only other callers
  (`OpenTypeMathData`, MATHML) are dead there (`OptionsPlayStation.cmake:268`). On the console the
  only page-reachable font parser is FreeType itself.
- **One instrument that did not work, recorded as such:** `CJ-witness` (vhea/vmtx replaced with one
  8000-unit metric) and `CJ-vmtx0` (0 units) do **not** change the vertical layout — both report
  `vj=72`, identical to `CJ-ctl`. The constructor demonstrably runs (the ASAN stack above), so the
  advance used by layout is not coming from the `OpenTypeVerticalData` this run attacked; the
  witness is withdrawn rather than explained. The reachability claim rests on the ASAN stack, not on
  that witness. **Update 2026-10-30 — explained, not merely withdrawn (`docs/102`):** four `vhea`/`vmtx`
  arms built with fontTools (one long metric vs 49 382, 256 vs 512 vs 1 024 units on the glyph) leave the
  measured advance at 24 px/char, while the same glyph's `hmtx` advance doubled gives 48 px/char — this
  layout reads `hmtx` and never `m_advanceHeights`, so no `vmtx` edit could have moved `vj`. The
  `vhea`/`vmtx` replacement in this file's arms was therefore inert by construction, independent of
  whether `rebuild()` wrote it correctly.
- **Corpus limits:** one mutation per arm but all on one base; `cmap` format 12 and `post` v2 bodies
  are only reachable as *patched formats* on a font that has neither, so the corpus does not fuzz
  real format-12 tables; no CFF/OTTO base (the `sfntVersion` override is the only CFF-shaped arm);
  one WOFF2 arm would need a Brotli encoder and was not built.

## 7. Oracle state

Nothing was patched and nothing was rebuilt: every page is HTML and every font is a file served from
`/tmp/wkp`, `ninja` idle, no server left running (`fprun2.sh` kills its own port and any leftover
MiniBrowser/WebKitWebProcess, which a crashed run otherwise leaves holding the log pipe). `EXIT=124`
is the harness's normal end (`timeout` kills MiniBrowser — `docs/65`, "Attempt 11"); `access: none`
on every non-crashing run. Beacon dumps and the two ASAN reports are committed under
`data/font-parser/`, and the generator, model, page and runner are in `tools/` and
`research/font-parser/`, so the corpus can be regenerated byte for byte from the md5 above.
