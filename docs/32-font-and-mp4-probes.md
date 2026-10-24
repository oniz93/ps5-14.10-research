# Two probes for the last open surfaces: fonts, and the MP4 parser

Both are built, syntax-checked, and served by the lab. Neither needs the Linux board — that
board's only use was as a FreeType 2.13.1 reference oracle, and Homebrew's FreeType 2.15.0 on
this Mac does the same job better (newer reference). It is currently unreachable anyway.

## Track 1: FreeType

The PlayStation port compiles `platform/FreeType.cmake`, and `FontCustomPlatformDataFreeType`
does

```cpp
FT_New_Memory_Face(library, reinterpret_cast<const FT_Byte*>(buffer.data()), buffer.size(), 0, &freeTypeFace)
```

with no OpenTypeSanitizer anywhere in the tree. `FontFace` works on the console and woff2 is
accepted, so this is a system-library parser reachable from a page with zero prerequisites.

`tools/fw1400/font_mutate.py` emits 28 cases from a 24.5 KiB base font (NotoSansLepcha), in
three families: **content** (table bytes corrupt, sfnt rebuilt with valid offsets, so the parser
is what gets tested), **dirent** (the table directory itself is corrupt), **trunc** (file cut
short). `probes/font-probe.js` fetches each from `/fonts/`, loads it as a `FontFace`, then forces
the glyph loader and rasteriser both through layout and through canvas `fillText` + `getImageData`.

### Reference column: FreeType 2.15.0 on this Mac

| case | open | glyphs |
|---|---|---|
| `valid` | ok | 141 |
| `dirent_numtables_zero` | **Err 2** | — |
| `head_unitsperem_zero` | **Err 8** | — |
| `trunc_8` | **Err 85** | — |
| `trunc_header` | **Err 2** | — |
| `loca_empty` | ok | **1** |
| `loca_offsets_past_glyf` | ok | **7** |
| `loca_short` | ok | **34** |
| `maxp_numglyphs_zero` | ok | **0** |
| everything else | ok | 141 |

No case crashes 2.15.0. The four open-rejections plus the four wrong glyph counts are the
fingerprint: if the console rejects a different set, its FreeType is a different vintage, and
that decides which published CVEs are worth attempting.

A harness bug is worth recording because it nearly became a false result: my first `ft_probe`
shared one `FT_Library` across files and segfaulted whenever a **second** face was created —
including `valid.ttf` twice. That is a property of the harness, not of any font, and it would
have looked like 28 crashes. The shipped probe therefore runs one process per file. Any future
FreeType harness here must do the same or isolate libraries deliberately.

## Track 2: the MP4 parser

The append *data* path is closed (`PSSourceBufferBackend::append` copies — proven by
`mse-append-churn.js`, 120 churned appends and a teardown with an append in flight). But the
backend still parses every byte a page hands it, a valid fragmented MP4 produced a clean
`updateend`, and `isTypeSupported` claims avc1 High, HEVC and VP9. The parser is in Sony's SDK
and absent from the OSS drop.

`tools/fw1400/mp4_mutate.py` emits 32 structural cases from a real fMP4: size 0 (runs to EOF),
size 1 with a lying 64-bit largesize, size < 8 (underflows remaining length), size beyond EOF,
type swaps, `mvhd` timescale 0 and duration 0xFFFFFFFF, `trun` sample_count 0x00FFFFFF, `tfhd`
flags all-set, 64-deep nesting, a container aliasing another's bytes, and four truncations.
`probes/mp4-fuzz.js` gives **each case a fresh video + MediaSource + SourceBuffer**, so a
poisoned pipeline cannot taint later results and a crash names exactly one input.

Stamp: 28 font cases + 32 MP4 cases, both reachable from a page with no prerequisites.
