# docs/102 — the vertical `vert` substitution *is* JS-visible (through hmtx), and the glyph-id readback stops at 32 767 px

`docs/99` found the drop's vertical GSUB parser reading past its table copy (7/7) and could not say
whether the substituted glyph ids ever reach a value a page can read. `GOAL.md` item 1 asked exactly
that: a vertical run with a webfont, per-character advances read back, the malformed range against a
correct one. This run answers it in four steps, each with one variable:

1. **The advance this layout uses is `hmtx`, not `OpenTypeVerticalData::m_advanceHeights`** — so
   `docs/99` §6's withdrawn `vmtx` witness is explained, not merely withdrawn (`vmtx` is never read
   here whatever the page writes into it).
2. **A `vert` substitution really does change the advance a page measures** — 115 px/char without it,
   114 px/char with it, horizontal width unchanged, and the same 114 reached through the *malformed*
   descending coverage as long as its reads land on page-written bytes.
3. **The substituted glyph id reads back exactly** when the font is built at 1 font unit = 1 px
   (7 320 px = 256 + 7 064; 7 356 = 256 + 7 100; 20 256 = 256 + 20 000; 32 256 = 256 + 32 000).
4. **The funnel has a hard ceiling**: an advance of 32 767 px is reported as 32 767, 32 768 px is
   reported as **0** — and it is a *pixel* bound, not a font-unit bound (the same 40 000-unit advance
   gives 5 000 px at font-size 32 and 0 at font-size 256).

The real, unpadded malformed range still aborts under ASAN before any layout (`docs/99`'s crash,
reproduced on this page as the calibration arm), so on this build the bytes past the table are never
observed. What is measured here is the funnel; what would happen to an OOB word is an inference and
is written as one (§5). `ENABLE(OPENTYPE_VERTICAL)` is still GTK/WPE-only, so none of this exists on
the console (`docs/99` §6, unchanged).

Page `research/font-parser/vert.html` (md5 `101dcc49c0d261d2ee7b1e07b780f46c`), runner
`research/font-parser/vgrun.sh` (`453b8ea60c7aa0c711d317e0566b0231`), arm builder
`tools/font-vertical.py` (`c6c9da1f6aba24537c9e560c3f70a138`), predictor
`research/font-parser/vert-model.py` (`1989c97b489b7a81cc9e0d8b269843d5`); beacons
`data/font-vertical/beacons.txt`, predictions `data/font-vertical/model-{H,T}.txt`, ASAN excerpt
`data/font-vertical/c1-asan.txt`.

## 1. The arms, and why each one is a single variable

Base: `DroidSansFallbackFull.ttf` (upem **256**, 49 382 glyphs, real `vhea`/`vmtx` with **one** long
metric of 256 units, one real `vert` lookup of type 7). `中` is glyph **7 109**, `一` is glyph
**7 064**. Every arm is that file with one table replaced by hand-built bytes:

- **V arms** replace `vhea`+`vmtx` only (`V1` 49 382 long metrics of 256, `V2` of 512, `V3` all 256
  except `中` at 1 024), `V0` is the untouched base — the question "is `m_advanceHeights` read at
  all".
- **H arms** replace `hmtx` only (every glyph's advance = `256 + glyph id`, so one font unit is the
  glyph id's low bits at 1 unit/px) and, for `H1`-`H4`, `GSUB` with one `vert`/`SingleSubst2` entry.
  `H0` is the same `hmtx` with the base `GSUB` (its `vert` lookup is type 7 and never matches `中`) —
  the no-substitution control.
- **`H2`** is the same substitution reached through a **descending `Coverage` format 2 range
  (10..5)** whose `substitute[]` reads walk a 65 532-word pad of `7 064` inside the same table
  allocation. It is the OOB-shaped range with in-bounds reads: the only way to see what the map does
  to layout, because the unpadded arm aborts (§5).
- **`H3`** is the *wrapping* range (0x8000..0xFFFF) the same way — its key set cannot contain 7 109,
  so it must be inert. It is the negative control for `H2`'s positive.
- **`C1`** is `H2` with the pad removed: reads past the allocation, expected to abort (calibration).
- **T/B arms** (`T1`-`T5`, `B1`, `B2`) chase the boundary of the readback: same substitution, one
  `hmtx` entry and/or the font size changed.

The predictor (`vert-model.py`) parses each arm's own bytes the way the drop does — including the
`uint16_t fromEnd = end + 1` wrap and the `from != fromEnd` loop — and prints the predicted advance
*before* the run. Predictions and measurements agree arm for arm.

## 2. The advance is `hmtx` — measured twice, and it retires `docs/99`'s withdrawn witness

`Font::widthForGlyph` reads `m_verticalData->advanceHeight()` only when the `Font` has a
`verticalData`, i.e. when it was created with `FontOrientation::Vertical` **and**
`OrientationFallback::No` (`Font.cpp:93`). `V2` doubles every `vmtx` advance and nothing moves:

```
ssh … bash /tmp/wkp/vg/vgrun.sh v2 8949 60 "only=V0,V1,V2,V3"
RES V0 … fs=24 h1=24.0000 w1=24.000 h3=72.0000 w3=24.000 rc=24.000@0.000,24.000@24.000,24.000@48.000 gid=1280.00 hw=72.000
RES V1 … fs=24 h1=24.0000 w1=24.000 h3=72.0000 w3=24.000 rc=24.000@0.000,… hw=72.000
RES V2 … fs=24 h1=24.0000 w1=24.000 h3=72.0000 w3=24.000 rc=24.000@0.000,… hw=72.000
RES V3 … fs=24 h1=24.0000 w1=24.000 h3=72.0000 w3=24.000 rc=24.000@0.000,… hw=72.000
```

Four arms, one variable each (`vhea`/`vmtx` present, one vs 49 382 long metrics, 256 vs 512 vs 1 024
units) and **every number identical**, including the per-character rects. So the layout path this
page exercises does not consult `m_advanceHeights` at all: `m_verticalData` is null on the font that
fills the glyph page, which is precisely why `docs/99` §6's `CJ-witness` (one 8 000-unit `vmtx`
metric) changed nothing. That entry can now read *explained*, not just *withdrawn*.

`hmtx` is the source, and doubling it doubles the advance:

```
RES Hx … fs=24 h1=48.0000 w1=24.000 h3=144.0000 w3=24.000 rc=48.000@0.000,48.000@48.000,48.000@96.000
```

(`Hx` = base font with `hmtx[中] = 512` instead of 256; nothing else changed.)

## 3. The substitution is JS-visible — and it is vertical-only

`H0`/`H1` differ in the `GSUB` table alone: `H1` carries a well-formed `SingleSubst2` mapping
7 109 → 7 064 with `hmtx` encoding `256 + glyph id` for every glyph, so a substitution must change
the advance by (7 109 − 7 064)/64 px = 0.703 px per character.

```
RES H0 … fs=4 h1=115.0000 w1=4.000 h3=345.0000 w3=4.000 rc=115.000@0.000,115.000@115.000,115.000@230.000 gid=7104.00 hw=345.000
RES H1 … fs=4 h1=114.0000 w1=4.000 h3=342.0000 w3=4.000 rc=114.000@0.000,114.000@114.000,114.000@228.000 gid=7040.00 hw=345.000
RES H2 … fs=4 h1=114.0000 w1=4.000 h3=342.0000 w3=4.000 rc=114.000@0.000,114.000@114.000,114.000@228.000 gid=7040.00 hw=345.000
RES H3 … fs=4 h1=115.0000 w1=4.000 h3=345.0000 w3=4.000 rc=115.000@0.000,115.000@115.000,115.000@230.000 gid=7104.00 hw=345.000
```

(read as the two runs `h1`/`h3b`; `H3` is from `h1`, the repeat `h3b` gives `H0`/`H1`/`H2` byte for
byte, and the earlier `h1` run — page without the `hw` column — gave the same `h1/h3/rc` values.)

- `H0` → 115 px/char (7 365 units + 1 px quantisation), no substitution: the base `GSUB`'s `vert`
  lookup is an **extension lookup (type 7)**, and `LookupTable::getSubstitutions` starts with
  `if (lookupType != 1) return false;` (`OpenTypeVerticalData.cpp:139`) — the drop supports Single
  Substitution format 2 only, so a real CJK font's `vert` table is inert here and only a hand-built
  type-1 table reaches the map.
- `H1` → 114 px/char. **The substituted glyph id reaches layout**: 45 units ≈ 0.70 px, rounded to a
  1 px difference by the engine's whole-pixel advance.
- `H2` → **identical to `H1`**. The descending, out-of-shape `Coverage` range builds the same map and
  the map is applied the same way; a page does not need a well-formed table to drive this.
- `H3` → **identical to `H0`**, i.e. the wrapping range's key set (0x8000..0xFFFF, 32 768 entries) does
  not contain 7 109 and is inert for this glyph — which is the shape `docs/99`'s `GS-wrap` arm would
  have had if it could run to completion.
- `hw` (**horizontal** width of the same three characters in the same font) is 345 in all four arms:
  the substitution is applied to the vertical font's glyph page only, which is what
  `substituteWithVerticalGlyphs` is supposed to do. This is the control that keeps the 1 px
  difference from being a font-wide effect.

## 4. Precision and the ceiling

At font-size 256 px with upem 256, one font unit is exactly one pixel, and the measured inline
advance is the substituted glyph's `hmtx` advance to the pixel:

| arm | substitute | `hmtx[substitute]` | measured `h1` (px) |
|---|---|---|---|
| `H5` | 7 064 | 7 320 | **7 320.0000** |
| `H6` | 7 100 | 7 356 | **7 356.0000** |
| `T1` | 20 000 | 20 256 | **20 256.0000** |
| `T3` | 32 000 | 32 256 | **32 256.0000** |
| `H7` | 40 000 | 40 256 | **0.0000** |
| `H4` | 60 000 (> 49 382) | — | **0.0000** |

So the substituted id is read back **exactly**, and the funnel ends between 32 256 and 40 256 px.
`B1`/`B2` pin it: the same substitution with `hmtx[20000]` set to 32 767 gives 32 767 px, set to
32 768 gives **0**:

```
RES B1 … fs=256 h1=32767.0000 … rc=32767.000@0.000,32767.000@0.000,32767.000@0.000
RES B2 … fs=256 h1=0.0000     … rc=0.000@0.000,0.000@0.000,0.000@0.000
```

And it is a **pixel** bound, not a font-unit bound: a 40 000-unit advance at font-size 32 px is
5 000 px and is reported exactly (`T4 h1=5000.0000`), while the same 40 000 units at font-size 256 px
is 0 (`T2 h1=0.0000`). An advance above the bound collapses the glyph's inline box to nothing rather
than clamping it. `H4` (substitute 60 000, past `maxp.numGlyphs`) also reports 0, but it cannot
separate "id out of range" from "advance over the bound": a past-the-end id clamps to the last
`hmtx` entry, 49 637 units, which is itself over the bound.

Read as a channel: at 1 unit = 1 px a page can measure a substituted glyph id in one number, so a
font with `hmtx[g] = g` and upem 256 reads back every id **0 … 32 767** exactly. Ids above 32 767
would need advances above the bound; two glyphs (high/low halves) or a second font would carry them.
That is the width of this funnel: 15 bits per measurement, 16 with a second pass.

## 5. What was *not* observed: the OOB read itself

`C1` is `H2` with the pad removed, so `substitute[]` reads run past the 56-byte table copy exactly as
in `docs/99`. On this page, in a vertical run, it aborts before any layout:

```
==…==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x606000060958 …
READ of size 2 at 0x606000060958 thread T0
    #0 WebCore::OpenType::BigEndianUShort::operator unsigned short() const  OpenTypeTypes.h:44
    #7 WebCore::OpenType::LookupTable::getSubstitutions(…) const  OpenTypeVerticalData.cpp:182
    #8 WebCore::OpenType::FeatureTable::getGlyphSubstitutions(…) const  OpenTypeVerticalData.cpp:219
    #9 WebCore::OpenType::GSUBTable::getVerticalGlyphSubstitutions(…) const  …:375
    #10 WebCore::OpenType::OpenTypeVerticalData::loadVerticalGlyphSubstitutions(…)  …:493
    #11 WebCore::OpenType::OpenTypeVerticalData::OpenTypeVerticalData(…)  …:422
    #18 WebCore::FontCache::verticalData(…)  FontCache.cpp:343
0x606000060958 is located 0 bytes after 56-byte region [0x606000060920,0x606000060958)
```

Same line, same region size, same chain as `docs/99` — so the page's vertical run does reach the
parser, and the malformed range is fatal *while the map is being built*, before a single glyph is
shaped.

**Therefore:** what is proved is that a substitution reaches layout and is JS-readable with a 15-bit
funnel (§3, §4); what is *inferred* is that in a build without ASAN the same code would fill the map
from the bytes past the table and each of those words would be readable the same way. The inference
is not idle — `H2` is the same map construction with the same range, and its values are the ones the
page wrote — but it is an inference, and it is the only claim here that a run on this build cannot
make.

## 6. Honest scope

- **Console: nothing changes.** `ENABLE_OPENTYPE_VERTICAL` is set only for GTK/WPE
  (`PlatformEnable.h:887`); `OptionsPlayStation.cmake` never sets it. On 14.10 neither
  `OpenTypeVerticalData` nor this loop exists, so the funnel is oracle-only and does **not** move
  criterion 3. It is filed with `docs/99`'s GSUB defect, ranked below every console-live surface.
- **The oracle's metrics are cairo/FreeType's**, and the 32 767 px bound is *that* path's (measured,
  not explained: it is a pixel bound, it collapses rather than clamps, and it is not
  `hhea.advanceWidthMax`, which stayed 256 while 32 256 px worked). Sony's font backend may differ.
- **One layout, one writing mode.** The measurements are `writing-mode: vertical-rl` with upright
  CJK, `line-height: 1`, one absolutely positioned block. The substitution's effect on the *block*
  axis, on `text-orientation: upright`, on `vertical-lr`, and on `Range.getClientRects` beyond the
  three rects read here were not measured.
- **`gid=` in the beacons is a naive decode** (`(h3/3)*64 − 256`) and is only exact at 1 unit/px; at
  font-size 4 the whole-pixel advance quantisation moves it by up to 64 units (H0 reports 7 104 for
  7 109). The numbers to use are `h1`/`h3`/`rc`, not `gid`.
- **`H2`'s pad is page-written, by construction.** The bytes the map reads there are `7 064`
  repeated; a real OOB read would see heap contents. This is the stand-in, and §5 says so.

## 7. Oracle state

Nothing was patched and nothing was rebuilt. Nine runs (`v1`, `h1`, `h3a`, `h3b`, `h3c`, `h4a`,
`t1`, `t2`, `b1`, plus the uniform `v2` re-run), each on its own port, all killed afterwards
(`pkill -f "[h]ttp.server"`, `pkill -x MiniBrowser`), `ninja` idle, no server left running.
`EXIT=124` is the harness's normal end; `access: none` on every run except `h3c`, which is the
calibration arm.
