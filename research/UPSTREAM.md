# Upstream projects — provenance and re-fetch

Earlier revisions of this repository vendored copies of other people's source files so they
could be read offline. Those copies are gone from the published tree: most of the projects
state no licence (so redistribution is not permitted by default), two are copyleft, and every
one of them is one `git clone` away. This file keeps the provenance record — what was read,
why, and what it contributed — without redistributing the code.

Clone these into `research/` under the names below; the paths are already gitignored.

| Project | Clone as | Licence | Used for |
|---|---|---|---|
| [ps5-linux/ps5-linux-loader](https://github.com/ps5-linux/ps5-linux-loader) | `research/ps5-linux-loader/` | GPL-3.0 | Per-firmware offset tables. Read for the shape of an offset set: 21 fields at 3.00, 28 at 7.61, 53 at 13.x — every field a file offset inside the kernel or hypervisor binary. |
| [symbrkrs/ps5-uart](https://github.com/symbrkrs/ps5-uart) | `research/ps5-uart/` | none stated | Pico UART tooling plus `uart/notes/` boot logs. The `emc.unlock()` overflow is gated to EMC firmware shipped on system FW ≤ 5.02; `fw_constants_map` gives `kFwConstsVersionUnknown` on anything newer, and that requirement appears only in a code comment. The `titania/` NAND stack works offline on a dump. |
| [Whoisraeen/Raeen](https://github.com/Whoisraeen/Raeen) | `research/raeen/` | GPL-2.0 | `crates/raeen-firmware/src/slb2.rs` — an independent SLB2 parser, used to cross-check the outer-container geometry. |
| [TINYTINY11/Kura-a-PS5-Emulator](https://github.com/TINYTINY11/Kura-a-PS5-Emulator) | `research/kura/` | none stated | `docs/RE-pup.md` — the community PUP note that the 32-byte entry records agree with, and that the 48-byte/entry-ID table conflicts with. |
| [MewX/ps5-official-firmware-list](https://github.com/MewX/ps5-official-firmware-list) | `research/mewx/` | Apache-2.0 | Date/hash/size table for every firmware ever shipped. Source of the PUP URL grammar's build list. |
| [gzimbric/ps5-linux-porting](https://github.com/gzimbric/ps5-linux-porting) | `research/ps5-linux-porting/` | MIT | The seven loader boundaries and the field categories behind a firmware port; the argument that an offset table cannot come from a PUP. |
| [shahrilnet/remote_lua_loader](https://github.com/shahrilnet/remote_lua_loader) | `research/remote_lua_loader/` | none stated | The Artemis/Lua save-file entry. **Not distributed here** — the loader payload was removed from the published tree; this is a pointer only. Pin `7c2840e47506f258fc815533d5f7ed7c842cbc3c` if you need the revision that was read. |
| [rezaadi0105/PSFree](https://github.com/rezaadi0105/PSFree) | `research/PSFree/` | AGPL-3.0 | `lapse.mjs` and the kernel-patch ancestry of the loader file that was previously vendored. **Not distributed here.** |
| [hammer-83/ps5-jar-loader](https://github.com/hammer-83/ps5-jar-loader) | `research/ps5-jar-loader/` | none stated | Kernel offsets for FW 1.00–10.01, cited as prior art in the AIO write-ups. |
| [bucanero/apollo-ps4](https://github.com/bucanero/apollo-ps4) | `research/apollo-ps4/` | GPL-3.0 | Save-file management, referenced for the save export/import workflow. |

## What was vendored, and where it went

| Removed file | From | Why removed |
|---|---|---|
| `loader-offsets.c` | ps5-linux-loader | GPL-3.0 — redistribution requires the full licence and source, and the file is a verbatim copy |
| `raeen-slb2.rs` | Raeen | GPL-2.0 — same |
| `ps5-uart-main.cpp`, `ps5-uart-pio_uart.pio`, `ps5-uart-CMakeLists.txt`, `ps5-uart-uart-CMakeLists.txt` | ps5-uart | no licence stated |
| `ps5-uart-README.md`, `ps5-uart-WIRING.md`, `ps5-titania-README.md`, `titania-README.md`, `titania-RESEARCH_POST.md`, `prosperismo-README.md`, `fw1400-README.md`, `gzimbric-README.md`, `mewx-README.md` | various | third-party READMEs; quoted where needed, not republished |
| `uart-note-bootlog_hcmd.txt`, `uart-note-uart_eap.txt`, `uart-note-update_timestamps.txt` | ps5-uart | captured console logs containing third-party hardware addresses and Sony copyright strings |
| `remote_lua_loader` (gitlink) | shahrilnet/remote_lua_loader | broken submodule with no `.gitmodules`; points at an unlicensed exploit loader |
| `deliverables/lua-entry/save-payload/` | remote_lua_loader / PSFree | an exploit payload and game-save artefacts; see `DISCLAIMER.md` §2 |

The analysis that depended on these files is in `docs/`, with its conclusions stated there.
Nothing in `docs/` needs the vendored copies to be read.
