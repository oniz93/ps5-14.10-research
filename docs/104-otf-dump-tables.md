# docs/104 — the OTF out of the engine, scored table by table

2026-10-30. The open action was: *take the OTF out of the engine and score it table by table —
`docs/101` §4's cause is read from the source, not from the bytes, and the 65 535-glyph cmap is
inferred, not measured.* This is that run. Predictions were written first, in
`data/otf-dump/predictions.md`; two of them were wrong and are corrected in §6.

## 1. Method

The writer's output reaches exactly one function before any parser sees it:

```cpp
// Source/WebCore/platform/graphics/freetype/FontCustomPlatformDataFreeType.cpp:144
if (FT_New_Memory_Face(library, reinterpret_cast<const FT_Byte*>(buffer.data()), buffer.size(), 0, &freeTypeFace))
```

`FT_New_Memory_Face` has one caller in the drop (that line), reached from `convertSVGToOTFFont`
through `CSSFontFaceSource::load` (`:166`) or `CachedSVGFont` (`:95`). So a breakpoint at the symbol
with `$rsi`/`$rdx` dumped is the writer's bytes, not a re-encoding.

The corpus page gained a `delay` parameter (`research/svgfont/corpus.html`, default 0, so every
earlier result stands) that parks the driver before the first arm, and `research/svgfont/otfgdb.sh`
does one arm per run: fresh port, `~/wk/run_nq.sh` (quarantine **off**), attach gdb to that run's own
`WebKitWebProcess`, `break *FT_New_Memory_Face`, dump `$rsi .. $rsi+$rdx`, `continue`.

```
bash research/svgfont/otfgdb.sh g6 8941 'only=G6-one-lig-ab' 25000 90
bash research/svgfont/otfgdb.sh g4 8942 'only=G4-two-lig-ab' 25000 90
bash research/svgfont/otfgdb.sh n3 8943 'only=N3-65535'      25000 120
```

Each run's own transcript, g6 (the other two differ only in addresses and size):

```
  From                To                  Syms Read   Shared Object Library
  0x00007f02c2c92000  0x00007f02c2d62000  Yes (*)     target:/lib64/libfreetype.so.6
  Breakpoint 1 at 0x7f02c2cac3b0
  BP_READY
  DUMP /tmp/otf/g6_01.bin base=0x61a000009c80 size=1348 head=4f54544f
  #0  0x00007f02c2cac3b0 in FT_New_Memory_Face () from target:/lib64/libfreetype.so.6
  #1  0x00007f02ccd4665d in WebCore::createFontCustomPlatformData(WebCore::SharedBuffer&, WTF::String const&) ()
  #2  0x00007f02d0c1f929 in WebCore::CSSFontFaceSource::load(WebCore::Document*) ()
  launch->attach start: 8.2 s
  RES G6-one-lig-ab w=90.00 w40=36.00 ctl=118.00 cw=90.00 wp=- ink=8000 inkctl=3038 n=1 st=loaded ms=90
```

| arm | dump | size | first 4 bytes | `maxp.numGlyphs` | ASAN lines |
|---|---|---|---|---|---|
| `G6-one-lig-ab` | `data/otf-dump/g6/g6.otf` | 1 348 | `4f54544f` (`OTTO`) | 4 | 0 |
| `G4-two-lig-ab` | `data/otf-dump/g4/g4.otf` | 1 536 | `4f54544f` | 6 | 0 |
| `N3-65535` | 6.9 MB, not stored (sha256 in `data/otf-dump/dumps.txt`) | 6 947 424 | `4f54544f` | 65 535 | 0 |

`*.bin` is git-ignored here, so the two small fonts are stored as `.otf` (identical bytes) and the
large one is identified by hash; `data/otf-dump/dumps.txt` has all three hashes and the regeneration
command.

One dump per run, so nothing here is a claim about run-to-run variation. All three logs end
`EXIT=124` (the harness's own `timeout`), `grep -c "ERROR: AddressSanitizer\|SUMMARY\|WTFCrash"` = 0
on all three — this run had no memory-safety question, and it did not produce one.

All three dumps have the same 14-table directory, in the order `convertSVGToOTFFont` (:1515-1540)
appends them, and **no `loca`/`glyf`** — §2's "CFF/OTTO" claim is now measured, not inferred:

```
g6: CFF (236+359)   GSUB(596+232)   OS/2(828+100)  VORG(928+8)    cmap(936+128)
    head(1064+54)   hhea(1120+36)   hmtx(1156+16)  kern(1172+32)  maxp(1204+32)
    name(1236+26)   post(1264+32)   vhea(1296+36)  vmtx(1332+16)
n3: CFF (236+5111799) GSUB(5112036+218) cmap(5112364+1310528) … hmtx(6422984+262140)
    vmtx(6685284+262140)   maxp numGlyphs = 65535
```

## 2. `G6` — the well-formed single-ligature font

Glyph ids are **not** document order: `std::sort(m_glyphs.begin(), …, &compareCodepointsLexicographically)`
(:1430) runs before the cmap is built, so the dump has `a`=1, `ab`=2, `b`=3 (`cmap` maps 0x61→1,
0x62→3; the ligature glyph is unmapped, as it should be). One lookup, type 4, one subtable:

```
raw: 0001 0012 0001 0008 | 0001 0004 | 0002 0002 0003 | 0001 0001 0001
     fmt1 cov=+18 cnt=1 off0=8   LigCnt=1 at+4  ligGlyph=2 comp=2 [3]   cov fmt1 n=1 [1]
```

Everything the source says to expect is there: `LigatureSetCount` = number of **pairs** = 1 = number
of distinct first glyphs, one offset (8), the set's `Ligature` offset is relative to the set (+4), and
the coverage is appended last at +18. `hb-shape 2.8.1` shapes `ab` as one glyph:

```
$ hb-shape --no-glyph-names data/otf-dump/g6/g6.otf "ab"
[2=0+900]
```

900 units = the ligature's own `horiz-adv-x`, i.e. the page's `w=90.00` at `font-size:100px`/upem
1000 — the two numbers are the same fact.

## 3. `G4` — the defect, in the file

Glyph ids again sorted: `a`=1, `ab`=2, `ac`=3, `b`=4, `c`=5 (`cmap` 0x61→1, 0x62→4, 0x63→5). Both
ligature pairs share first glyph 1, so there is one segment while `:771` writes the pair count:

```
raw: 0001 001a 0002 0008 | 0002 0006 000c | 0002 0002 0004 | 0003 0002 0005 | 0001 0001 0001
     fmt1 cov=+26 cnt=2 off0=8   LigCnt=2 off=6,12  lig(2,[4])    lig(3,[5])    cov fmt1 n=1 [1]
                     ^^^^^^ this byte pair is the slot for a second offset, and it is set0's own
                            LigatureCount
```

That is the whole claim of `docs/101` §4, now at byte level:

- **`LigatureSetCount` = 2** (two pairs) while only **one** offset placeholder was grown
  (`grow(overlappingFirstGlyphSegmentLengths.size() * 2)`, :772, with
  `overlappingFirstGlyphSegmentLengths == [2]`).
- The value in the second slot is **`0x0002`** — the first LigatureSet's `LigatureCount`. So a reader
  that enumerates the declared array reads *set #1 at subtable+2*, inside the subtable's own header
  (the offset field it lands on is the coverage offset 0x1a = 26, which it then takes as
  `LigatureCount = 26`, and the "offsets" it reads are the coverage/ligature bytes).
- The coverage of the same subtable has **`GlyphCount` = 1** (`a` only), against a declared count of 2.

Two independent readers agree, and they fail in the two different ways the bytes predict:

```
$ fontTools 4.67.0  GSUB: FAILED: ValueError: ('bytes length not a multiple of item size',
        'Component', 'Ligature', 'LigatureSet', 'SubTable', 'Lookup', 'LookupList')
$ hb-shape --no-glyph-names data/otf-dump/g4/g4.otf "ab"
[1=0+200|4=1+200]
```

fontTools enumerates the declared offsets and refuses to decompile the table; HarfBuzz shapes `ab` as
two glyphs of 200 units each (`w=40.00` on the page), i.e. the `liga` lookup is not applied at all —
not "the second ligature is missing", *all* of them are, which is why `ff`/`fi`/`fl` fonts lose their
ligatures wholesale. The lookup sits under **feature 0 = `liga`**, and the `DFLT` script table
enables exactly one feature (`appendScriptSubtable(1)`, :873), so this is the feature a Latin run
applies by default — the defect is not confined to the Arabic features beside it
(`fina`/`medi`/`init`/`rlig` are features 1-4, enabled only under the `arab` script).

## 4. `N3` — the 65 535-glyph cmap, and the prediction that failed

The `N3` arm generates 65 534 glyphs starting at U+0020, so its last 30 codepoints are
**U+10000…U+1001D**: the mapping set is 65 535 entries of which only **65 505 are BMP**. The
format-12 subtable is complete and correct; the format-4 one is malformed in three fields at once,
but not in the way `docs/101` §3 predicted:

```
cmap records:  (0,3) -> +28          format 12, length 786436, numGroups 65535, first groups
                                     (0,0,0) (32,32,1) (33,33,2), last group (65565,65565,65534)
               (3,1) -> +786464      format 4
               (3,10) -> +28         format 12 (same subtable)
fmt4 header: 0004 ffff 0000 ffff ffff 000f ffc5
             fmt=4  len=65535  lang=0  segCountX2=65535  searchRange=65535  entrySelector=15
             rangeShift=65477
fmt4 real extent: 524064 bytes  (8 * 65505 + 24)   ← the declared length is 8x too small
```

`uint16_t segCount = bmpMappings.size() + 1` is 65 506, **not** 65 536, so it does not wrap to 0:
`clampTo<uint16_t>` saturates `segCountX2` and `searchRange` at 65 535 (declaring 32 767.5 segments)
and `rangeShift = 2*65506 - 65535 = 65 477` is arithmetically consistent with that segCount. The
subtable's declared length saturates at 65 535 against 524 064 real bytes, so a reader that honours
the length stops in the middle of the arrays.

The conclusion `docs/101` §3 drew survives, because it rests on the format-12 subtable, not on this
one — every BMP mapping is still reachable through platform-0/3 and platform-3/10:

```
$ fontTools 4.67.0  cmap: FAILED: ValueError: bytes length not a multiple of item size
$ hb-shape --no-glyph-names data/otf-dump/n3/n3_01.bin "A"
[34=0+433]
```

0x41 → glyph 34 with a 433-unit advance: the same advance the page measured as `w=43.00`. So on this
font a strict reader refuses the cmap while the engine's own lookup path still works, which is worth
knowing before anyone reads a `cmap` parse failure as "the font is unusable".

## 5. Reproduce

```
python3 tools/otf-dump-parse.py data/otf-dump/g6/g6.otf data/otf-dump/g4/g4.otf \
                                data/otf-dump/n3/n3_01.bin     # -> data/otf-dump/report.json
hb-shape --no-glyph-names data/otf-dump/g4/g4.otf "ab"
```

`report.json` holds the same facts as data; the parser reads raw bytes, so its answer does not depend
on fontTools being willing to load a malformed table (fontTools' answer is recorded beside it).

## 6. What this changes in `docs/101`

1. **§3's clamp statement is wrong on the bytes.** "At 65 535 glyphs `uint16_t segCount =
   bmpMappings.size() + 1` is 65 536 → 0" — measured, `bmpMappings` is 65 505 because the arm's
   generated range crosses the BMP boundary at U+10000, so `segCount` is 65 506 and nothing wraps;
   `clampTo<uint16_t>` saturates `length` and `segCountX2` at 65 535 instead. The *conclusion* (the
   font works because both surviving platform records point at the format-12 subtable) is unchanged.
2. **§4's cause is confirmed byte for byte** and needs no correction: count = pairs, one offset
   written, the second slot holds the first set's `LigatureCount`; the coverage has one glyph.
3. **New fact — glyph ids are lexicographic by codepoint, not document order** (:1430). Any future
   arm that asserts a glyph id must sort its codepoint strings first; this run's own prediction had
   `ab`=3/`b`=2 for `G6` and had to be corrected by the dump.
4. **New fact — the ligature lookup is `liga` under the `DFLT` script** (feature 0, the only feature
   `DFLT` enables), so the failure is on the default path, not an Arabic-only one.
5. Prediction detail corrected: the Ligature offsets inside a set are relative to the set's start
   *including* its `2 + 2n` header (6 and 12 for two ligatures), not 4 and 10.

## 7. Limits

- The dump is the buffer **handed to** `FT_New_Memory_Face`; nothing here is a claim about what
  FreeType or the shaper does *inside* the font beyond the two shaper readings quoted above.
- `hb-shape` here is **2.8.1** (the Mac's), and the oracle's HarfBuzz is Fedora 39's; the engine's
  own response to these same bytes is `docs/101` §4's page measurement (`w=90.00` vs `w=40.00`). The
  three agree, but they are three different readers, and only the page is the engine.
- FreeType on the oracle is 2.13.1 and on the console it is Sony's; `N3`'s broken format-4 subtable
  is therefore a statement about the bytes, plus one measured reader's tolerance of them.
- One dump per arm (the conversion is cached after the first load), so the absence of a second dump
  is not evidence about anything.
