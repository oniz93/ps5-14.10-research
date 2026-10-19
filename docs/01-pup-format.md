# PUP / SLB2 / SELF format reference

> **⚠ VERIFIED CORRECTION (2026-10-19).** This document describes the layout as
> published by the community for a 5.50 Update PUP. We probed live 2026 firmware
> ourselves and the **outer container does not match** — it is a two-level wrapper
> carrying *filenames* (`PS5UPDATE1.PUP`, `PS5UPDATE2.PUP`), not a 95-entry component
> table. See **`03-outer-container-verified.md`** for the raw bytes and the corrected
> outer-format fields. Treat everything below as describing the *inner* PUP level,
> still unverified.

Everything below is documented for the **5.50 Update PUP** unless marked otherwise.
Treat sizes as observations for that version, not constants.

Source: se7ensins "PS5 PUP Format Reverse Engineered" thread (2026-06-15) +
psdevwiki PS5 PUP page, which was updated from it.

## Two PUP types

- **Update PUP** — only components that changed since the previous firmware.
- **Recovery PUP** — complete firmware. Used for full reinstall.

The console accepts any PUP at or above the installed version. Older requires exploits.

## SLB2 container

Magic `53 4C 42 32` (`"SLB2"`) at offset `0x00`.

### Header

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 4 | Magic | `53 4C 42 32` |
| 0x04 | 4 | Version | format version |
| 0x08 | 4 | Mode | |
| 0x0C | 4 | Entry Count | number of components |
| 0x10 | 8 | Header Size | |
| 0x18 | 8 | Data Size | total PUP file size |
| 0x20 | 16 | Padding | |
| 0x30 | 0x30 × N | Entry Table | one 48-byte record per component |

### Entry record (48 bytes)

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 8 | Entry ID | 64-bit type identifier |
| 0x08 | 8 | Compressed Size | as stored |
| 0x10 | 8 | Uncompressed Size | equals compressed if not compressed |
| 0x18 | 8 | Data Offset | from PUP start |
| 0x20 | 4 | Flags | bit 0 = compressed, bit 1 = signed, bit 2 = encrypted |
| 0x24 | 12 | Padding | |

## Known entry IDs (5.50 observations)

| ID | Name | Description | Observed size | Copies |
|---|---|---|---|---|
| 0x0100 | `eap_kernel` | Aeolia Application Processor kernel — OS on the security co-processor's ARM cores | ~330–466 MB | 5 |
| 0x0200 | `emc_ipl` | Aeolia Embedded Controller IPL — contains an embedded x86-64 SELF | ~14 MB | 1 |
| 0x0300 | `tee` | Trusted Execution Environment | ~9 KB | |
| 0x0400 | `bios` | System BIOS, multiple hardware-variant copies | ~365–482 MB | 5 |
| 0x0600 | `smf_ipl` | System Management Firmware IPL | ~238 KB | |
| 0x1000 | `kernel` | Main PS5 kernel | ~2.2 MB | |
| 0x1100 | `bootloader0` | First-stage bootloader — **candidate for LDLR, verify** | ~4 KB arm64 / ~45 KB bin | |
| 0x1300 | `psp_bl` | Security processor bootloader | ~4.8 KB | |
| 0x1400 | `psp_kernel` | Security processor kernel | ~449 KB arm64 / ~5 KB bin | |
| 0x2000 | `update_package` | Small update blobs | 2–8 KB | 22 |
| 0x4000 | `version_info` | Per-component version tags | 1–4 B each | 32 |
| 0x5000 | `swu_manifest` | Software update manifest | ~20 KB and ~808 MB | 2 |
| 0x20000 | `gpu_ucode` | GPU microcode, byte-identical copies | ~594 KB | 11 |
| 0x30000 | `sio_firmware` | System I/O controller firmware | ~2.3 MB | 1 |

> The published extractor assigns `.arm64` / `.bin` by file-type **heuristic**
> (ARM64 opcode density). Encrypted blobs can pass the same check, so the extension
> is not proof of plaintext code. Sizes above are the stored-blob view.

## The encryption situation

**A "decrypted PUP" (`.PUP.dec`) has only the outer SLB2 encryption removed.** That gives:

- readable headers, entry table, component names, sizes, offsets, flags
- each component extractable to its own file

Each component is then a **PS5 SELF** (`ET_SCE_EXEC`, type `0xFE00`) with per-segment
AES encryption:

- **SELF headers are plaintext** — ELF structure, segment layouts, **load addresses,
  entry points** are all readable
- **Segment contents are encrypted** with per-binary keys stored in Aeolia's secure
  storage on the hardware itself

### Why this matters for us

Load addresses and entry points come free from a decrypted PUP on a PC — no console
keys needed. That is a substantial piece of the physical memory map, and it is the
Stage 0 deliverable. The *code* is not available this way.

## Tooling

| Tool | What | Where |
|---|---|---|
| `ps5-pup-unpacker` | unpacks already-decrypted PUPs | github.com/zecoxao/ps5-pup-unpacker |
| `ps5-pup-decrypt` | console-side decryption (asks a jailbroken PS5 to do it) | github.com/zecoxao/ps5-pup-decrypt |
| `pup_extract.py` / `analyse_extracted.py` | PC-side structure parser + analyser from the se7ensins writeup | se7ensins thread |
| Darthsternie archive | stock update + recovery PUPs, 60+ versions | darthsternie.net/ps5-firmwares |

## Firmware versions to collect

| Version | Why |
|---|---|
| 5.50 | ground truth — format already publicly documented |
| 13.60 | last jailbreakable; best community coverage |
| 14.00 | first patched release after Relapse |
| 14.10 | what the target console runs |
