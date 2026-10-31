# docs/105 predictions — written before any run

Action (GOAL.md, the open item): **make the ligature count overshoot the GSUB table and see whether any
reader reads past it.** `docs/104` measured the count/slot overlap at N=2; every reader it exercised stopped
inside the same `SharedBuffer`. This run pushes N to 300 with a single distinct first glyph, dumps the font,
scores three readers against the dump, and runs the same arm on the ASAN oracle.

Nothing below has been measured yet. Predictions are numbered so §6 of the doc can score them.

## Method (fixed before the run)

1. New arm `G10-lig300-f`: 300 ligatures `faa, fab, … , fln` (all start with `f`), plus a `<glyph>` for
   `f`; `text='faa'`. `gen.kind='ligf'`, `gen.n=300`.
2. Dump: `bash research/svgfont/otfgdb.sh g10 <port> 'only=G10-lig300-f' 25000 120` — one arm, gdb at
   `*FT_New_Memory_Face`, `$rsi..$rsi+$rdx`. Quarantine off.
3. Score the dump three ways: `tools/otf-dump-parse.py` (raw struct reader), fontTools 4.67, `hb-shape
   2.8.1`, plus a new naive-reader model `tools/gsub-trust-model.py` that parses the format-1 ligature
   subtable the way the spec reads — count from +4, then `count` offsets — follows every offset it is
   given with no per-table bound, and records the **highest byte offset it reads**, relative to the
   subtable, the GSUB table and the whole font buffer.
4. ASAN: `bash research/svgfont/sfrun.sh g10asan <port> 60 'only=G10-lig300-f'`, quarantine off, scored
   from `ERROR: AddressSanitizer` frames and a `BEG`/`RES` beacon pair.

## Predictions

### P1 — layout of the subtable at N=300
One segment (`overlappingFirstGlyphSegmentLengths == [300]`), so `:771` declares 300 and `:772` grows
**one** offset slot. Predicted byte layout, offsets decimal from the subtable start:

```
+0    0001              format 1
+2    <cov>             placeholder, filled last
+4    012c              LigatureSetCount = 300
+6    <off0>            the only slot grown — set #0 at +8
+8    012c              LigatureSet #0: LigatureCount = 300
+10   ...               300 Ligature offsets (600 B), each 602+6j, relative to the set
+610  ...               300 Ligature records (6 B each): ligGlyph, 2, component
+2410 0001 0001 <fid>   coverage format 1, GlyphCount 1, glyph id of 'f'
      total subtable length 2416 B
```

So the declared offset array is **600 B** and the data the writer actually emitted is **2 416 B**: a
reader that enumerates `LigatureSetCount` offsets reads slots 2..300 out of the set's own
`LigatureCount` and its ligature offsets — all inside the subtable, 1 810 B short of its end.

### P2 — the first bogus offset, followed
Slot 1 (the second offset) reads `0x012c` = 300. A reader that follows it lands at subtable+300, i.e.
inside the ligature-offset array (index 145), and reads `LigatureCount` = **1 472** there. 1 472 × 2 B of
offsets from +302 ends at +3 246 — **830 B past the subtable**, i.e. past the GSUB table (the subtable
is the last thing in GSUB), into `OS/2`. Still inside the font `SharedBuffer`.

### P3 — what the three readers do
- `otf-dump-parse.py`: reads the bytes as they are; must show count 300, one offset, and the overlap.
- fontTools 4.67: `FAILED`, same class as `G4` (`bytes length not a multiple of item size`) or a
  `struct.error` from following the bogus set — either way a Python exception, never a native read.
- `hb-shape`: the `liga` lookup is **not applied** — `faa` shapes as `f`,`a`,`a` (three glyphs of the
  single advances), i.e. the page's `w` equals the three single advances, not the ligature advance.
  HarfBuzz sanitises every offset against the GSUB blob, so the 830-byte overshoot is unreachable there.
- naive model: **must report a read past the GSUB table end** (P2), and must stay inside the font buffer
  (GSUB is table 2 of 14). If it leaves the font buffer, that is a stronger result than predicted.

### P4 — ASAN arm
**No sanitizer report, no abort.** The engine's only readers of a type-4 subtable on the oracle are
HarfBuzz (blob-bounded) and, for vertical text, `OpenTypeVerticalData`, which parses **type 1 only**
(`GSUBTable.cpp:139`) and is compiled out on PlayStation anyway. Expected beacons: `BEG G10-lig300-f`,
`RES G10-lig300-f … st=loaded`, `DONE n=<arms>`; `EXIT=124` is the harness's own timeout, as always.

### P5 — expected falsifications
The one way P1 fails is if `std::sort`'s `first[0]` comparison splits the 300 pairs into more than one
segment — it cannot, every string starts with `f`, but if the dump shows more than one offset the cause
must be read before any conclusion. The one way P4 fails is if a reader I have not counted does parse the
subtable; then the fault frame names it and the doc records it instead of this prediction.
