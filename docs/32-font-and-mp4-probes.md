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

## Round 1 on hardware: clean, and shallower than it looked

Both corpora ran end to end on retail 14.10 with no crash.

**Fonts.** All 28 cases, twice through (forward sweep `F-DONE n=28`, reverse `F-ALL-DONE`). Four
rejections, all `NetworkError`, and they are *exactly* the four FreeType 2.15.0 rejects:
`head_unitsperem_zero`, `dirent_numtables_zero`, `trunc_8`, `trunc_header`. The other 24 loaded.

That match is the useful part: on these discriminators the console's FreeType behaves like a
current, fully-patched build. Nothing in this corpus is near a pre-2.12 validation gap.

**MP4.** All 32 cases produced `updateend`, including `moov_size_lt_header` (a box size of 4,
below the header minimum). That is not credible as "fully parsed" — which is the tell.

### Why round 1 was shallow, and what round 2 changes

Two facts visible only in the beacon output:

1. **Every font reported `w150`.** The base font is NotoSans**Lepcha**, so rendering `AaBbGg019`
   fell back to the system font every time. Face creation *was* exercised — that is where the
   four rejections came from — but glyph outlines and the TrueType hinting interpreter were not.
   Round 2 renders real Lepcha codepoints (U+1C00–U+1C07) and reports `applied=yes` only when the
   measured width differs from the monospace fallback, so a substituted font can no longer look
   like a successful parse.

2. **`updateend` means accepted, not demuxed.** Nothing ever played the media, so the demuxer was
   barely driven. Round 2 plays each case, seeks to 0.15 s, and reports the deepest event reached
   (`metadata`, `data`, `canplay`, `timeupdate`, `playing`) alongside the outcome.

Round 2 is `probes/corpus-v2.js`: fonts first, then MP4, one reload, roughly four minutes.
`F2-*` and `M2-*` prefixes keep its beacons distinguishable from round 1 in the same log.

## Round 2: real coverage, two solid negatives

**Fonts.** `FALLBACK-LEPCHA-w112` against `w152` for every loaded case proves the font's own
outlines were used rather than a substitute. Two cases carry the weight: `fpgm_inflated` and
`prep_huge` both rendered at **w0**, which means the TrueType bytecode interpreter processed 4 KiB
and 64 KiB of hostile hinting programs. That is the historically richest FreeType surface, and it
was exercised for the first time here. Rejections were again exactly the four that 2.15.0 rejects.

**MP4.** The container parser is now properly cleared: nine cases reached `deep=playing`, i.e. the
demuxer *and* decoder ran — `valid`, `ftyp_type_swap`, `mdat_size_beyond_file`,
`mvhd_timescale_zero`, `mvhd_duration_huge`, `tfhd_flags_all`, `trunc_in_moof`, `trunc_in_mdat`,
`moof_alias_moov_offset`. Four were cleanly rejected with `M2-VERR deep=none`
(`moov_size_lt_header`, `moov_type_swap`, `trak_type_swap`, `moof_type_swap`). Nothing crashed.

## What is left: the codec layer

Every mutation so far changed box structure. None touched the bitstream — the `avcC`
configuration record (SPS/PPS, parsed at init) or the length-prefixed NAL units in `mdat`. Those
reach a different parser, and a hostile SPS is the classic route to making a decoder allocate by
numbers it was told but never validated.

`tools/fw1400/avc_mutate.py` emits 22 cases: `avcC` count/length abuse, `SPS` profile/level/
body replacement (zeros and 0xFF, the densest Exp-Golomb encoding), `PPS` id out of range,
`lengthSize` mismatch, NAL length zero and 0x7FFFFFFF, forbidden bit, reserved types, body
replacement, an injected Annex-B start code, a length that swallows the rest of `mdat`, and a
truncated access unit. `probes/bitstream-probe.js` plays and seeks each one and records the
deepest event, so "accepted and stalled" cannot be mistaken for "decoded".

Stamp: 28 font cases, 32 container cases, 22 bitstream cases — all reachable from a page with no prerequisites.
