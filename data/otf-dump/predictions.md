# docs/104 predictions — written before any run

Action (GOAL.md, the open item): take the OTF out of the engine and score it table by table.
`docs/101` §4's cause is read from the source; §2's 14-table CFF/OTTO claim and §3's 65 535-glyph
cmap are inferences. Nothing below has been measured yet.

## Method (fixed before the run)

One run per arm, `only=<id>`, `delay=25000` so gdb attaches while the page is parked (the corpus page
gains a `delay` parameter for this; default 0, so no earlier result changes). Quarantine off
(`~/wk/run_nq.sh`). In the WebProcess: `break *FT_New_Memory_Face`, dump `$rsi .. $rsi+$rdx`
(`file_base`, `file_size`). `FT_New_Memory_Face` has exactly one caller in the drop
(`FontCustomPlatformDataFreeType.cpp:144`), reached from `convertSVGToOTFFont` via
`CSSFontFaceSource::load` (:166) / `CachedSVGFont` (:95), so every dump is the bytes WebKit wrote.

Scoring is done on the Mac with fontTools 4.67.0 **and** an independent `struct` reader, per table.

## Predictions

### P0 — shape, all three arms
One dump per arm, starting `4F 54 54 4F` (`OTTO`); `numTables` = 14; tags in this order:
`CFF `, `GSUB`, `OS/2`, `VORG`, `cmap`, `head`, `hhea`, `hmtx`, `kern`, `maxp`, `name`, `post`,
`vhea`, `vmtx` (`convertSVGToOTFFont` :1515-1540). No `loca`, no `glyf`. G6/G4 dumps are ~1-3 KB;
N3 is multi-MB.

### P1 — `G6-one-lig-ab` (glyphs: 1=`a`, 2=`b`, 3=`ab`; one ligature pair `(1,2) -> 3`)
GSUB has one lookup, type 4, with one subtable. Segment count 1 → offset[0] = 6 + 2*1 = **8**; the
coverage is appended last, at 8 + (2 + 2*1) + 6 = **18**:
`0001 0012 0001 0008 | 0001 0004 | 0003 0002 0002 | 0001 0001 0001`
(format 1, cov 0x12, count 1, set0 at 8; set: LigatureCount 1, ligature at 4; ligature: LigGlyph 3,
CompCount 2, Component[0] = 2; coverage: format 1, GlyphCount 1, [1]). Count 1 and one offset agree:
this is the well-formed arm and the page measured `w=90.00`.

### P2 — `G4-two-lig-ab` (glyphs: 1=`a`, 2=`b`, 3=`c`, 4=`ab`, 5=`ac`; pairs `(1,2)->4`, `(1,3)->5`)
Both pairs share first glyph 1, so `overlappingFirstGlyphSegmentLengths == [2]` (one segment) while
`:771` writes `ligaturePairs.size()` = **2** into "Number of LigatureSet tables" — and only **one**
offset placeholder was grown (`:772`). Predicted bytes (the sort compares only `first[0]`, so the
two ligatures may also appear as `0005 … 0004 …`; the count and the overlap do not change):

```
0001 001C 0002 0008 | 0002 0004 000A | 0004 0002 0002 | 0005 0002 0003 | 0001 0001 0001
fmt  cov  cnt=2 off0   LigCount offs      Lig1:glyph4  b   Lig2:glyph5  c    cov fmt1 n=1 [a]
```

so the *second* LigatureSet offset slot (subtable+8, 2 bytes) contains **`0002`**, which is the first
LigatureSet's own `LigatureCount` — the overlap §4 asserts. `LigatureSetCount` (2) > `GlyphCount` (1)
in the coverage, and offset #1 = 2 points inside the subtable header. Prediction: a shaper rejects
the lookup (HarfBuzz sanitises the set array) and the page keeps measuring `w=40.00`.

### P3 — `N3-65535` (glyph 0 + 65 534 square glyphs, codepoints 0x20..0xFFFD)
`bmpMappings.size()` = 65 535, so `uint16_t segCount = 65 536` wraps to **0**:
- format-4 subtable header: `0004`, length field = 524 304 mod 65536 = **`0010` (16)**,
  `0000` language, `0000` segCountX2, `0000` searchRange, `0000` entrySelector, `0000` rangeShift;
- the subtable *really* occupies 524 304 bytes (14 + 131 072 + 2 + 131 072 + 131 072 + 131 072);
- format-12 subtable at cmap+28 is intact: length 786 436, numGroups **65 535**;
- cmap's three encoding records: (0,3) -> 28, (3,1) -> the format-4 offset, (3,10) -> 28.
The font still loads and the page uses it (measured before: `w=43.00`), because every mapping is in
the format-12 subtable.

### Falsifiers
- If G4's subtable+8 bytes are not `0002`, §4's "the second offset is the first LigatureSet's own
  header" is wrong in that detail and §4 gets corrected.
- If N3's `segCountX2` is not 0 (e.g. the writer clamped differently), §3's clamp claim is corrected.
- If a dump is not OTTO/14 tables, §2 is corrected.
