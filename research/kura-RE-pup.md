# RE notes — PS5UPDATE.PUP / SLB2 container

_Observations from local analysis of a retail PS5 update file (user-supplied, never committed). Sources: empirical byte analysis on 2026-10-09; community research published June 2026 (Se7enSins "PS5 PUP Format Reverse Engineered" full breakdown + psdevwiki update, tools `pup_extract.py` / `analyse_extracted.py`); reporting on the December 2025 BootROM key disclosure (KitGuru, Tech Insider, Insider Gaming via Reddit r/PS5). Layout reconciled 2026-10-10 against zecoxao's published ps5-pup-unpacker sources; source landscape re-surveyed the same day — both below._

## Findings (verified against the file itself)

| Offset | Type | Value observed | Meaning / confidence |
|---|---|---|---|
| 0x00 | char[4] | `SLB2` | magic — **confirmed** |
| 0x04 | u32 LE | 3 | version — high confidence |
| 0x08 | u32 LE | 0x10000 | block size (64 KiB) — high confidence (used for block scan) |
| 0x0C | u32 LE | 1 | **disputed 2026-10-10** — read as entry count by the June-2026 community layout; on this *encrypted wrapper* it is an unidentified field (see Layout reconciliation) |
| 0x10 | u64 LE | 0x2597C8 (2,463,688) | **disputed 2026-10-10** — was "header size"; a 2.4 MB header is implausible, and on a decrypted `.dec` this offset is the embedded file-size field. Wrapper-only meaning unknown |
| 0x18 | u64 LE | 0 | data size (community layout) — 0 here, consistent with encrypted container |
| 0x20 | u32 LE | 2 | padding region per community layout |
| 0x24 | u32 LE | 1,261,406,781 | near-file-size (actual file: 1,261,408,256 — **1,475 bytes larger**). Open question: payload-only size? trailer excluded? |
| 0x30 | char[16] | `PS5UPDATE1.PUP` | image name (legacy field) — **confirmed** |
| 0x200 | 32 B | `4c294437…cd03` | digest (SHA-256-shaped) over what exactly — unknown |
| 0x3E0 | payload | entropy ≈ 7.997/8.0 | **encrypted** — near-max Shannon entropy everywhere sampled |

## Community layout (published June 2026 — cross-check against our empirical table)

> **Status (2026-10-10): disputed — superseded by the Layout reconciliation
> section below.** This 48-byte-record layout conflicts at every field offset
> past the magic with the scene tooling that actually extracts `.dec` files
> (zecoxao's ps5-pup-unpacker, transcribed 2026-10-10). It is kept here for
> research continuity; **no code uses it**, and the entry-ID table below is
> likewise superseded by the tool's flag-derived IDs.

A full RE of the 5.50 update PUP established the decrypted-container layout. Our
field offsets agree where they overlap (entry count @0x0C, header size @0x10),
which retroactively explains our "unknown" fields.

| Offset | Size | Field |
|---|---|---|
| 0x00 | 4 | magic `SLB2` |
| 0x04 | 4 | version |
| 0x08 | 4 | mode |
| 0x0C | 4 | entry count |
| 0x10 | 8 | header size |
| 0x18 | 8 | data size |
| 0x20 | 16 | padding |
| 0x30 | count × 0x30 | **entry table** |

Each 48-byte entry: `id:u64, compressed_size:u64, uncompressed_size:u64,
offset:u64, flags:u32 (bit0=compressed, bit1=signed, bit2=encrypted), pad[12]`.

Known entry IDs (5.50, community-documented; **superseded** — kept for research, not used in code; see Layout reconciliation):

| ID | Name | Notes |
|---|---|---|
| 0x100 | eap_kernel | Aeolia A53 co-processor OS (~330–466 MB × 5 copies) |
| 0x200 | emc_ipl | Aeolia embedded controller; contains x86-64 SELF |
| 0x300 | tee | trusted execution environment |
| 0x400 | bios | main system BIOS (multiple variants) |
| 0x600 | smf_ipl | system management firmware IPL |
| 0x1000 | kernel | main PS5 kernel |
| 0x1100 | bootloader0 | first-stage bootloader |
| 0x1300/0x1400 | psp_bl / psp_kernel | security processor stages |
| 0x2000 | update_package | small update blobs |
| 0x4000 | version_info | per-component version tags |
| 0x5000 | swu_manifest | software update manifest |
| 0x20000 | gpu_ucode | GPU microcode (11 identical copies in 5.50) |
| 0x30000 | sio_firmware | system I/O controller firmware |

## Layout reconciliation (2026-10-10) — two headers, the tool wins

Fetching zecoxao's published `ps5-pup-unpacker` sources resolved the
contradictions above: **there are two different headers**, not one.

**Provenance** (all fetched 2026-10-10, read-only):
`raw.githubusercontent.com/zecoxao/ps5-pup-unpacker/master/` → `PUP.h`,
`PUP.cpp`, `Entry.h` — the README states it only accepts previously-decrypted
blobs and "will not unpack the contents of nested filesystems"; the code is
Zer0xFF's ps4-pup_unpack rewrite via idc, the same lineage PSXHAX/Wololo
documented in Oct 2022.

1. **The encrypted wrapper** (the retail file analyzed above): name @0x30,
   payload @0x3E0, total_size @0x24 — field 0x10 is *not* a header size
   (0x2597C8 vs a 1.26 GB file) and field 0x0C is *not* an entry count. Its
   structure stays empirical; this is what stage 1 sees on any
   un-decrypted `PS5UPDATE.PUP`.
2. **The decrypted `.dec` container** (scene-unpacker layout — authoritative
   for code):

   | Offset | Type | Field |
   |---|---|---|
   | 0x00 | char[4] | `SLB2` |
   | 0x04 | u32 | version |
   | 0x10 | u64 | **file size — must equal the actual file size** (the outer-vs-.dec separator) |
   | 0x18 | u16 | **entry count** |
   | 0x20 | count × 0x20 | entry records |

   Each 32-byte record: `{u32 flags, u32 reserved, u64 offset, u64 csize,
   u64 usize}`. Flag decode (per `PUP.cpp`): `id = flags >> 20`; compressed =
   `flags & 8`; blocked = `flags & 0x800`; records whose class
   `(flags & 0xF0000000)` is `0xE0000000`/`0xF0000000` are skipped **without**
   size checks — and so do we.

**Conflict resolution:** June-2026 community layout vs tool layout — they
disagree at every offset past the magic; the **tool wins provisionally** (it
is what working scene extraction runs on; the community post is unverified
against real files). Verification pending a supplied real `.dec` — until then
`kura_pup` logs the two decisive probes on failure (`u64@0x10=… vs actual …;
u16@0x18=…`) so a mismatch is diagnosable in one line.

**Entry names** come from the tool's PopulateMaps — `eula.xml`, `kernel.bin`,
`eap_kbl.bin`, `ariel_sec_ldr_a.bin`, `wlanbt.bin`, `ssd0.system_b`,
`ssd0.preinst`, … — corroborated by the psdevwiki install log (513 = 0x201,
519 = 0x207). Unknown-but-plausible IDs return an empty name, never an
invented one.

**Verdict logic in `kura_pup`:** readable table (embedded size == actual
size) ⇒ outer layer is decrypted ⇒ exit 0 with the component list and
"next: image extraction". Table unreadable **and** payload entropy ≥ 7.0 ⇒
encryption wall ⇒ exit 3, unchanged.

## The encryption situation (two layers)

This is the crucial structural finding, and it matches our entropy results:

1. **Outer SLB2 container** — removed by "decrypting the PUP" → a `.PUP.dec`
   file with a readable entry table. Our retail file fails exactly here
   (entropy ≈ 7.997 from 0x3E0 onward, entry table unreadable).
2. **Inner SELF segments** — every extracted component is a PS5 SELF
   (`ET_SCE_EXEC`, 0xFE00) whose **headers are plaintext** (ELF structure,
   segment VAs, entry points all readable) but whose **segment data is
   per-binary AES-encrypted** with keys held in Aeolia secure storage.
   Segment entropy 7.95–7.997.

Practical consequence for Kura: even with a `.dec` file, code segments stay
encrypted — but structural metadata (load addresses, segment sizes, entry
points) is already useful for M2/M3 planning, and `kura_pup` can now read it.

Inner SELF details recovered by the community (emc_ipl/smf_ipl share an
identical embedded x86-64 SELF: entry VA 0x400080, 6 PT_LOAD-style segments,
execute-only segment 0 (no-read hardening), BSS tail on segment 2, zero
section headers). An "encrypted segment info table" precedes the ELF header
with entries whose offsets end in `0x0006` and heavy padding (anti-analysis).

## Keys situation (2025-12 → 2026-01, from news reporting)

- **2021**: fail0verflow publicly stated they obtained all symmetric root keys
  via software; they never published them.
- **Late Dec 2025 / early Jan 2026**: PS5 **BootROM keys leaked** online
  (hardware root-of-trust material, identical across all revisions to date).
  Per reporting: allows decrypting early-stage bootloader images; does **not**
  include the asymmetric keys; no complete public firmware-decryption chain
  has been published as of 2026-06. Inner SELF per-binary keys live in Aeolia
  secure storage — their presence in the leak is not established by any
  source found.
- Console-side tools (zecoxao's `ps5-pup-decrypt`, Oct 2022) produce `.dec`
  files **using a PS5 itself** (backup/restore flow). The user has no console,
  so this path is closed for us unless a `.dec` file is obtained elsewhere.

**Kura policy (design doc §12 + repo hygiene):** Kura never contains key
material, never downloads it, and does not fetch `.dec` files. If a user can
legitimately produce or obtain a decrypted PUP, `kura_pup` will parse and
extract it via the modern layout; the pipeline continues from there. The
encrypted-retail path remains blocked on keys we are not going to hardcode.

### Source landscape (surveyed 2026-10-10, updated 2026-10-11, read-only)

The keys conclusion above is unchanged; the *file* landscape moved:

- **On-console-only decrypt tools** — zecoxao's `ps5-pup-decrypt` and
  idlesauce's `PS5-SELF-Decrypter` v0.5 (2025-11-04, 3.00–10.01) both run
  **on a jailbroken PS5**; the user has no console, so this path stays closed.
- **zecoxao's original MEGA folder** (the 3.00–6.02 `.dec` set announced via
  Wololo/PSXHAX/proboards in Oct 2022): **deleted by the owner** — verified
  live 2026-10-10 and again 2026-10-11 ("Folder cannot be accessed"). The URL
  was recovered 2026-10-11 from the descriptions of both zecoxao announcement
  videos: **`mega.nz/folder/290hgR6I#yi-UhHuL72YD-xg2dhyn4A`** — both videos
  ("PUP Decryptor and Unpacker OUT Now!" `M9xVCjyc1eQ` and "P.T Running on
  6.02" `4Cf4KaNqzB4`) link the same single folder; no second copy ever
  existed at that URL.
- **No archive can resurrect that folder.** Wayback CDX holds 8 captures of
  the URL (2022-10-17 → 2026-02-17) but each is the ~1 KB MEGA app shell —
  the encrypted file blobs live server-side and are **never** captured, so a
  deleted folder cannot be recovered from archives. This is structural, not a
  failed search.
- **PSXHAX firmware threads** (7.20/8.20) reference a *second* MEGA folder
  with `*_update1.pup.dec` files (incl. `720_update1.pup.dec`, 1.07 GB), but
  every external link on psxhax.com resolves to `/login/` for guests — in
  current HTML **and** in the 2023 Wayback snapshot. XenForo link-shortening
  keeps the real URL server-side, so it was never in any guest-facing HTML or
  archive (which is why the video descriptions were the only recovery path).
  The flow0 thread's `.dec` file lists (3.00–7.61, 116 names) are XenForo
  attachments: zero file-host URLs in the archived HTML.
- **2026-10-11 mainstream mirror sweep**: searches across psx-place, wololo,
  GitHub, reddit and YouTube found the *tools* everywhere and re-uploaded
  `.dec` sets nowhere; no indexed `mega.nz/folder` link containing `.pup.dec`
  besides the deleted one. Finding re-uploads would require non-mainstream
  search engines/forums, which is outside the user's boundary (no sketchy
  sites) — deliberately not crossed.
- **2026-10-11 re-sweep (user request — user has no console)**: PSXHAX 7.20
  and 8.20 news threads fetched live — their "Decrypted PS5 PUPs" MEGA folder
  links resolve to `/login/` for guests (XenForo link-shortening, as above);
  archive.org advanced-search API for `"pup.dec" AND ps5` → **0 items**;
  direct searches for the named files (`820_update1.pup.dec`,
  `720_update1.pup.dec`) → nothing indexed; GitHub → only the console-side
  decrypt tool sources (zecoxao `ps5-pup-decrypt`, `ps5-pup-decrypt-elf` —
  both "run on the system"), no `.dec` payloads; reddit → dump *requests*, no
  public links. Conclusion re-confirmed: no public, registration-free `.dec`
  exists on mainstream sources.
- **archive.org `ps5-official-firmwares`** hosts official **encrypted** PUPs
  only (through 08.60) — the same wall; GameTechWiki's emulator-firmware table
  lists no public decrypted-PS5 backup either.
- **`darksoftware.xyz/PS5/decryptedFWlist`** — the only live *comprehensive*
  decrypted source found: retail 1.12→10.60, recovery 2.20→6.02, testkit,
  devkit — all downloads behind account login.

No published off-console decryption chain appeared in any of this: obtaining a
`.dec` remains a **user-supplied file** (registering on darksoftware to fetch
one is the user's own action). Kura's policy is unchanged — it never fetches,
contains, or requests firmware or keys.

## Open questions (next RE session)

- **Real-`.dec` verification pass**: confirm the tool-derived header/record/flag layout against a supplied decrypted file (stage 2's extraction code is written and synthetic-verified; this pass remains the reason real-file behavior is not yet claimed)
- The 1,475-byte size delta (trailer? alignment? footer with QR?)
- Digest coverage (header only vs whole file)
- Exact cipher/key-schedule for the outer container (no public source names
  the algorithm concretely — "AES" is the community assumption from entropy
  alone)
- Encrypted-segment-info-table format (entries at …0x0006 offsets)

## Tooling

- `kura_pup <file>` in `tools/firmware/` reproduces the empirical analysis
  **and** now parses the modern entry table when readable (decrypted files);
  on encrypted files it reports "entry table: not readable" — by design.
- `kura_pup <file.dec> --extract <dir>` (stage 2, 2026-10-11): streams every
  payload-bearing component to `<dir>` (created if missing, refused if
  non-empty — nothing is clobbered; names generated from the entry index +
  our fixed id table, so container bytes never reach a path; every range
  re-checked per component, short reads fail cleanly with all partials
  removed). Components land **bytes-as-stored**: compressed entries stay
  compressed and inner SELF segments may still be encrypted — unpacking is
  not decryption, and every report says so.
- Unit tests use **synthetic headers and tables only** — no real firmware
  bytes in the repo.
