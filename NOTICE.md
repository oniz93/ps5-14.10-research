# Third-party notices and provenance

This repository mixes original work with material derived from, or referring to, other
people's projects. This file records what came from where and under what terms.

If you believe an attribution is missing or wrong, open an issue and it will be corrected.

## Original work

Everything not listed below — the research notes in `docs/`, the tooling in `tooling/` and
`tools/fw1400/`, the probe pages, the harnesses, and the measurement data in `data/` — is
original work by the repository owner, except where a file carries its own copyright header.

## WebKit source and Sony's open-source drop

| Path | Origin | Terms |
|---|---|---|
| `out/diffs/**` | Diffs against WebKit as published in Sony Interactive Entertainment's PS5 open-source drop (`playstation.com/en-us/oss/ps5/`) | WebKit is distributed under **LGPL-2.1** (with portions under the **BSD-2-Clause** licence). The diffs are derivative works of that source and carry the original copyright headers. |
| `data/*.json` (patch-presence, presence-*, sweep-*, wk-*) | Excerpts, file lists and classification data derived from the same drop | Same as above; only short excerpts and derived metadata are stored. |
| `data/test-corpus/*.html` | WebKit `LayoutTests` regression tests, as shipped in the same drop | LGPL-2.1 / BSD-2-Clause |

No Sony proprietary code, firmware image, key material or decrypted binary is included.
The repository stores *diffs*, *filenames*, *excerpts* and *measurements* — never a copy of
the drop.

## Data derived from firmware analysis

| Path | Origin | Note |
|---|---|---|
| `data/sysent_1360_resolved.json` | Syscall-table layout recovered from a publicly circulated 13.60 kernel memory capture, cross-checked against `ps5-payload-dev/sdk` | Factual addresses and table geometry, no code. The capture itself is **not** redistributed here. |
| `data/webkit-oss-map.json` | Sony's public OSS index page for PS5 | Facts about published archive names/versions. |

## Removed third-party code

Earlier revisions of this repository vendored source files from other research projects so
they could be read offline. Those files have been **removed from the published tree** because
their licences either do not permit redistribution or were unclear, and the copies were
replaceable by a `git clone`. They are listed here so the provenance record survives:

| Project | Licence | What was used |
|---|---|---|
| [`ps5-linux/ps5-linux-loader`](https://github.com/ps5-linux/ps5-linux-loader) | GPL-3.0 | `loader-offsets.c` (per-firmware offset tables) — read for the offset-field taxonomy only |
| [`Whoisraeen/Raeen`](https://github.com/Whoisraeen/Raeen) | GPL-2.0 | `raeen-slb2.rs` (SLB2 container parser) — read as a cross-check on the container layout |
| [`symbrkrs/ps5-uart`](https://github.com/symbrkrs/ps5-uart) | No licence stated | Pico UART tooling, wiring notes, and captured boot/EAP logs — read for the EMC/UART gate |
| [`shahrilnet/remote_lua_loader`](https://github.com/shahrilnet/remote_lua_loader) | No licence stated | Lua loader payload and save-package scaffolding — **not distributed** |
| [`rezaadi0105/PSFree`](https://github.com/rezaadi0105/PSFree) | AGPL-3.0 | Kernel-patch shellcode ancestry of one loader file — **not distributed** |
| [`MewX/ps5-official-firmware-list`](https://github.com/MewX/ps5-official-firmware-list) | Apache-2.0 | Firmware version/date/size table used to derive PUP URLs — facts only |
| [`gzimbric/ps5-linux-porting`](https://github.com/gzimbric/ps5-linux-porting) | MIT | Loader-porting boundary list — cited, not copied |
| [`TINYTINY11/Kura-a-PS5-Emulator`](https://github.com/TINYTINY11/Kura-a-PS5-Emulator) | No licence stated | PUP format notes — cited, not copied |

Provenance and re-fetch instructions for each are recorded in
[`research/UPSTREAM.md`](research/UPSTREAM.md).

## Generated test assets

The fonts in `tools/fw1400/guide_lab/www/fonts/`, the MP4 fragments in
`www/mp4/` and `www/mp4b/`, and the corpus pages under `www/cases/` are generated or
hand-written locally (see `tools/fw1400/font_mutate.py`, `mp4_mutate.py`,
`avc_mutate.py`, `img_corpus.py`). They contain no third-party font, media or code.

## Trademarks

PlayStation, PS5 and Sony are trademarks of Sony Interactive Entertainment Inc. Apple,
Safari and WebKit are trademarks of Apple Inc. They are used here descriptively, to refer to
the systems being studied. This project is not affiliated with, endorsed by, or supported by
any of these companies.
