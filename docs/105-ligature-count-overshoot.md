# docs/105 — 300 ligatures on one first glyph: the count overshoots, no reader in the process follows it

2026-10-30. The open action was: *make the ligature count overshoot the GSUB table and see whether any reader
reads past it.* `docs/104` measured the count/slot overlap at N=2 and every reader it exercised stopped inside
the same `SharedBuffer`. This run pushes N to 300 with a single distinct first glyph, dumps the font, scores
three readers against the dump, models a count-trusting walk byte by byte, and runs the arm under ASAN.
Predictions were written first (`data/gsub-300/predictions.md`); two of their numbers were wrong and §6 says why.

## 1. Method

New arms in `research/svgfont/corpus.html` (md5 `b7fcc58fcbf1778dedbdfd6aa5ad684e`, 54 arms):

- `G10-lig300-f` — 300 `<glyph>` ligatures `faa, fba, fca, …` (all start with `f`), plus `a`–`z`; `text='faa'`.
- `G11-lig300-distinct` — the well-formed twin: 300 ligatures with **300 distinct** first glyphs
  (`U+0100+i` + `a`); `text='Āa'`. Same N, same writer, same page.

```
bash research/svgfont/otfgdb.sh g10 8951 'only=G10-lig300-f'        25000 120
bash research/svgfont/otfgdb.sh g11 8954 'only=G11-lig300-distinct' 25000 100
bash research/svgfont/g10asan.sh g10asan 8952 45 'only=G10-lig300-f'
bash research/svgfont/g10asan.sh g10g11  8953 50 'only=G10-lig300-f,G11-lig300-distinct'
```

`g10asan.sh` is new and differs from `sfrun.sh` in one way that matters on a shared box: it kills only its own
port and its own `MiniBrowser http://127.0.0.1:<port>/`, never `pkill -x MiniBrowser`, because a concurrent
session had a page running there. Quarantine off throughout (`~/wk/run_nq.sh`).

Dumps: `data/otf-dump/g10/g10.otf` (29 036 B, sha256 `6c0c7e10329dffb7…`),
`data/otf-dump/g11/g11.otf` (56 356 B, sha256 `87bbfb368baa7363…`), transcripts `/tmp/G_895{1,4}.log`.

```
DUMP /tmp/otf/g10_01.bin base=0x62c000008200 size=29036 head=4f54544f
#0  0x00007fca9779d3b0 in FT_New_Memory_Face () from target:/lib64/libfreetype.so.6
#1  0x00007fcaa194665d in WebCore::createFontCustomPlatformData(WebCore::SharedBuffer&, WTF::String const&) ()
#2  0x00007fcaa581f929 in WebCore::CSSFontFaceSource::load(WebCore::Document*) ()
```

## 2. What the writer emitted at N=300 (P1 scored)

`G10` table directory: `CFF(236+21991) GSUB(22228+3224) OS/2(25452+100) VORG … vmtx(27728+1308)`,
`maxp.numGlyphs = 327`; the ligature subtable sits at `GSUB+168` and is 3 016 B of it. First 16 bytes:

```
0001 0bc2 012c 0008 | 012c 025a 0262 026a
fmt=1  cov=+3010  LigatureSetCount=300  offset[0]=8 | LigatureCount=300  off 602 610 618 626
```

- `LigatureSetCount` = **300** (the pair count, `:771`) and exactly **one** offset slot was grown (`:772`, one
  per *distinct* first glyph). Slot 1 therefore holds `0x012c` = **300**, the first set's own `LigatureCount`,
  exactly as `docs/104` found at N=2 — the same defect, 150× the declared array.
- The 300 real ligature records are at set0+602 stepping **8** bytes (`ligGlyph`, `compCount` 3, two
  components) and they are all in set0: `LigatureCount` 300, `max compCount` 3, coverage `fmt=1 n=1 glyph=6`
  (`f` = 6 because glyph ids are lexicographic: `a`..`z` = 1..26).
- Predicted layout was right in shape, wrong in one field: §P1 assumed 2-component ligatures (6-byte
  records), the arm's strings are 3 characters (`f`+2), so records are 8 B and the subtable is 3 016 B, not
  2 416 B. That is the whole difference between the predicted and the measured arithmetic below.

The twin, same writer, one variable:

```
G11 subtable at GSUB+168, declared 300, offset slots 606 610 614 618 … (300 of them, step 4)
G11 subtable length 4210, GSUB length 4418, font 56356
```

So the two fonts declare the **same** count and differ only in how many offsets were written — 1 against 300.

## 3. Three readers on `G10`

| reader | result |
|---|---|
| `tools/otf-dump-parse.py` | walks it: `ligatureSetCount=300`, `offsetSlots=[8, 300, 602, 610, …]`, `slot2Bytes=300`, `set0 at +8 ligatureCount=300`, coverage `+3010` |
| fontTools 4.67 | **FAILED during GSUB decompile**: `error ('unpack requires a buffer of 2 bytes', 'CompCount', 'Ligature', 'LigatureSet', 'SubTable', 'Lookup', 'LookupList')` — it follows the bogus offsets and runs off the end of its own table slice |
| `hb-shape 2.8.1` | `faa` → `[6=0+200\|1=1+200\|1=2+200]` — the `liga` lookup is **not applied** |

The twin, same three readers: fontTools **decompiles OK, 300 sets**, and `hb-shape 'Āa'` → `[3=0+1000]`, one
ligature glyph of 1 000 units. On the page, in one run:

```
RES G10-lig300-f          w=60.00 w40=24.00 ctl=146.00 cw=60.00 ink=1890 st=loaded ms=89
RES G11-lig300-distinct   w=100.00 w40=40.00 ctl=120.00 cw=100.00 ink=1240 st=loaded ms=81
```

60.00 = three single advances (200+200+200 units), 100.00 = the ligature's own default advance. That is the
one-variable control: at the same N the ligature works when count and slots agree, and all substitution is
lost when they do not — which is `docs/101` §4's defect at 150× the size, not a size limit.

## 4. How far a reader that trusts the counts would go (`tools/gsub-trust-model.py`)

A byte reader that records every offset it is asked for, in two models: **A** enumerates the declared offset
array only; **B** follows each declared offset as a LigatureSet (count + that many offsets) and each of those
as a Ligature (ligGlyph, compCount, compCount−1 components), clamped only to report rather than fault.

```
G10 (subtable 22396, len 3016, GSUB 22228+3224, font 29036)
A_offsets_only  declared 300  max_rel_subtable 606   bytes_past_subtable_end 0     out_of_font_reads 0
B_follow        set_starts_past_subtable 733  set_starts_past_gsub 564  ligature_records_read 17547
                max_abs 29036 (= font end)  bytes_past_subtable_end 3624  bytes_past_gsub_end 3584
                max_want_abs 156620  want_bytes_past_font_end 127584  out_of_font_reads 122675135
G11 (subtable 22396, len 4210, GSUB 22228+4418, font 56356)
A_offsets_only  declared 300  max_rel_subtable 606   bytes_past_subtable_end 0
B_follow        set_starts_past_subtable 0  max_rel_subtable 3606  want_bytes_past_font_end 0  reads 1500
```

Read as three separate statements, because they are three different questions:

1. **Enumerating the declared array never leaves the subtable.** 300 offsets are 600 B and the enumerated
   array ends at subtable+606, which is **2 410 B short** of the subtable's end (3 016). The count can never
   overtake the data: the writer emits one offset (2 B) plus one record (6-8 B) per pair, so the declared array
   is always the smaller of the two. This is why N=2 and N=300 behave the same.
2. **Following the bogus offsets does leave the table, by a measured amount.** Slot 1 is 300, i.e. subtable+300,
   inside set0's own ligature-offset array (index 145), where `LigatureCount` reads **1 762**; 1 762 offsets
   from +302 end at +3 826, **810 B past the subtable's end** into the `OS/2` table. Across all 300 followed
   offsets the model reaches **3 584 B past the GSUB table's end** — 564 set starts land past it — and the
   highest address it reads is the font buffer's last byte.
3. **The largest single request would leave the allocation.** One bogus Ligature record declares
   `compCount` 65 535, whose component array would end **127 584 B past the end of the font**. An unbounded
   reader's first outside-the-allocation access is therefore the byte after the font's last, i.e. a
   `heap-buffer-overflow READ` in an ASAN build and a mapped-or-not gamble in a release build.

So the answer to the action's question is **yes for a naive reader, no for this engine** — and §5 is why.

## 5. Why no engine reader follows it, measured rather than assumed

The process has exactly two GSUB parsers in this drop, and both bound themselves:

- **HarfBuzz** — the shaper both on the oracle and on the console: `OptionsPlayStation.cmake:329-334` sets
  `USE_FREETYPE ON` and `USE_HARFBUZZ ON` unconditionally inside `if (ENABLE_WEBCORE)`. HarfBuzz's
  `hb_sanitize_context_t` re-checks every offset against the *table's* blob, which is what turns §4's 3 584-byte
  overshoot into "lookup rejected" and produces the measured `[6=0+200|1=1+200|1=2+200]`.
- **`OpenTypeVerticalData`** — WebKit's own parser, and it reads one lookup type only:
  `if (lookupType != 1) // "Single Substitution Subtable" is all what we support` (`OpenTypeVerticalData.cpp:140`).
  A type-4 ligature subtable never reaches its loop. It is also compiled out on PlayStation
  (`ENABLE(OPENTYPE_VERTICAL)` is GTK/WPE-only, `docs/102`).

The ASAN runs say the same thing from the other side: two arms, quarantine off, **0 `ERROR: AddressSanitizer`
lines, 0 aborts, `EXIT=124`** (the harness's own timeout) in all four logs, including the gdb runs that are on
the same binary. `access: none`.

## 6. What this changes

1. **`docs/101` §5's assertion is now measured on its reader half, and its word "internal" needs a
   qualification.** "The one overstated count is internal to the single `m_result` allocation and rejected by
   the reader" — true of the *writer's* array, and true of every reader in the process. But the count is not
   harmless by construction: a reader without a per-table bound would read 3 584 B past the table and, on one
   record, request 127 KB past the font. The safety is the engine's sanitizer, not the writer's arithmetic.
2. **The defect has no size threshold at which it becomes memory-unsafe.** N=2 (`docs/104`) and N=300 behave
   identically at every reader; the declared array can never exceed the emitted data because the writer spends
   8 B per pair and declares 2.
3. **The subtable's real extent is measurable from the writer's own coverage table**, which is appended last:
   `subtable_len = coverageOffset + 4 + 2*GlyphCount` = 3 016 B for `G10`. `tools/gsub-trust-model.py` uses
   that, so its byte arithmetic does not depend on guessing record sizes (the mistake §P1 made).
4. Predictions corrected: P1/P2 assumed 6-byte ligature records (2-component ligatures) and produced a
   2 416-byte subtable, a slot-1 count of 1 472 and an 830-byte overshoot; the arm's 3-component records make
   the subtable 3 016 B, the count 1 762 and the first-set overshoot 810 B. P3 (all three readers) and P4
   (no sanitizer report) held as written.
5. New tool: `tools/gsub-trust-model.py` (§4) and new runner `research/svgfont/g10asan.sh` (§1).
   `data/gsub-300/trust-model.json` and `trust-model-g11.json` hold the numbers, `data/gsub-300/report.json` /
   `parse.txt` the parser's view, `data/otf-dump/{g10,g11}/*.otf` the fonts. `tools/otf-dump-parse.py` gained a
   bound (`SET_WALK` 12, `COMP_WALK` 8) because an unbounded walk of this arm writes 2.9 MB of JSON for a report
   whose point is the header — the bound does not touch any count or offset it reads.

## 7. Limits

- One dump per arm, one arm per run: no claim about run-to-run variation.
- The model in §4 is a model, not an engine: it states what a reader *would* request, and every number past the
  font's end is a request the model clamps. What the engine *did* is §5's two sanitizer-bounded readers and the
  two ASAN runs.
- The oracle's HarfBuzz is Fedora 39's and the console ships its own; the argument in §5 rests on the shaper
  being HarfBuzz (measured in `OptionsPlayStation.cmake`) and on HarfBuzz's sanitizer being version-independent
  in kind, not on a specific version number.
- `G11`'s page measurement proves the lookup applies at N=300; its dump confirms count 300 with 300 offsets,
  but the twin was not walked by the model beyond the byte arithmetic in §4.
