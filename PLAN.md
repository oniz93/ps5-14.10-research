# Plan

Staged, cheapest-and-lowest-risk first. Each stage has a standalone payoff — if the
project stalls at stage N, stages 0..N-1 still produced real artifacts.

**Success condition is not "Linux boots."** It is "I documented a stage of the chain
nobody has documented." Linux is the trophy at the end; the documentation is the project.

---

## Stage 0 — PUP archaeology

**Cost:** $0. **Risk:** none (nothing touches a console). **Time:** ~2 weeks at 5–10 h/wk.

Goal: build a personal, version-diffable map of the PS5 boot components — entirely
from public firmware images, entirely on the Mac.

### What you actually get from a PUP

Two layers of encryption, and the distinction matters:

1. **Outer SLB2 container encryption.** Remove it ("decrypted PUP", `.PUP.dec`) and you
   get readable headers: the entry table, every component name, sizes, offsets, flags.
2. **Per-component SELF segment encryption.** Each component is a PS5 SELF
   (`ET_SCE_EXEC`, type `0xFE00`). The SELF *header* is plaintext — ELF structure,
   segment layout, **load addresses, and entry points are all readable**. The actual
   code and data in each segment is encrypted with keys held in Aeolia secure storage.

**This is the key insight for Stage 0:** you do not need console-side keys to get
load addresses and entry points. That is a real chunk of the memory map, obtainable
from a decrypted PUP on a PC. Nobody has published it as a clean per-firmware table.

Full PUP decryption requires a jailbroken console (the on-console tool asks the PS5 to
decrypt for you). Community consensus is that on-console key extraction is only
practical on very low firmware (≈3.xx). On FW 14.10 we cannot decrypt our own PUPs —
so Stage 0 uses **stock PUPs from the archive for structure** plus **community-decrypted
images for ground truth**.

### Tasks

1. **Ask before building.** Post in the psdevwiki and ps5-linux Discords (see
   `docs/02-resources.md`): what's already known about the SELF load map, whether
   anyone has a decrypted 13.xx/14.xx image, whether the LDLR container format is
   documented anywhere. One question here can save a month. Do this on day one.
2. **Pull firmware images** from Darthsternie's archive (see resources):
   - `14.10` and `14.00` — the target class
   - `13.60` — last jailbreakable, best-documented
   - `5.50` — ground truth, because the format is already publicly documented for it
   Download both update and recovery PUPs for at least one version (they differ).
3. **Write `tooling/pup_parse.py`.** Parse SLB2 header + entry table, emit `entries.csv`
   (entry id, name, compressed size, uncompressed size, data offset, flags). Format
   reference is in `docs/01-pup-format.md`.
4. **Validate against 5.50.** Reproduce the published 5.50 breakdown exactly — 95
   entries, 14 component types — before trusting the parser on anything else.
5. **Cross-check your parser against `zecoxao/ps5-pup-unpacker`** so you're not
   fighting a private interpretation of the format.
6. **Write `tooling/self_header.py`.** For each extracted component, parse the SELF
   header: ELF magic, segment table, `p_vaddr` / `p_paddr` load addresses, entry point,
   segment flags. Emit `loadmap.csv`.
7. **Write `tooling/loadmap.py`.** Aggregate per firmware: component → load address
   range → entry point → size. Diff across versions.
8. **Produce `docs/loadmap-<fw>.md`** for 5.50, 13.60, 14.00, 14.10.
9. **Diff 13.60 → 14.00 → 14.10, focused on `bootloader0` (entry id `0x1100`) and
   `kernel` (`0x1000`).** Did the boot chain change structurally between the firmware
   everyone has written about and the firmware this console runs? This is a real,
   answerable question and nobody has published the answer.
10. **Load the ARM blobs** (`eap_kernel`, `emc_ipl`, `psp_bl`, `psp_kernel`) into Ghidra.
    These are the co-processor side of the chain, separate from the x86-64 main path.
    Note: code is encrypted unless you have a fully-decrypted image — expect to be
    limited to headers and structure for now.
11. **Write up findings** in `docs/`. Anything genuinely new goes to the community.

### Acceptance criteria

- [ ] `entries.csv` for four firmware versions, parser validated against 5.50 ground truth
- [ ] `loadmap.csv` with load address + entry point per component per version
- [ ] A written answer to: did the boot chain structure change 13.60 → 14.10?
- [ ] Posted findings in at least one Discord, asked the "what's already known" question
- [ ] Zero hardware touched

### Known unknowns

- Whether `bootloader0` (`0x1100`, ~4 KB arm64 / ~45 KB bin in the 5.50 sample) is
  actually LDLR or a smaller flash-stage helper. **Verify, don't assume.**
- The `.arm64` extension is a byte-distribution heuristic in the published extractor and
  can false-positive on encrypted data. Size and layout claims are the stored-blob view.
- Whether community-decrypted 13.xx/14.xx images exist at all. Ask first (task 1).

---

## Stage 1 — LDLR container format

**Cost:** $0–50 (a NOR dump, probably from the community). **Risk:** none if the dump
comes from someone else.

1. Get a NOR dump (community first — do not desolder your own yet).
2. Decrypt LDLR using the leaked BootROM symmetric keys.
3. Document the container: header layout, load address, entry point, size constraints,
   and what exactly the BootROM validates beyond the hash.
4. Diff LDLR across firmware versions.
5. Build a read-only parser (`tooling/ldlr_parse.py`).

**Acceptance:** a written, publishable description of the LDLR format. This is the
real contribution milestone.

---

## Stage 2 — EMC UART unlock

**Cost:** ~$10–30 (Raspberry Pi Pico + USB-TTL). **Risk:** low, but this is the first
time hardware is involved.

1. Wire up `symbrkrs/ps5-uart` on a Pico.
2. Get a UART shell on the EMC (southbridge).
3. Document exactly which PS5 hardware revision / EMC version you have.
4. Confirm whether EMC can read flash — that would beat desoldering.

**Acceptance:** a serial console that prints on boot.

---

## Stage 3 — custom stage-2 "hello world"

**The wall.** Everything before this is preparation.

1. Dump NOR, verify a full restore path works. **Do not proceed without this.**
2. Build a minimal stage-2 that the BootROM accepts and that prints one character
   to UART, then halts.
3. Only then: DDR init, payload load, and anything resembling Linux.

**If this stage never completes, stages 0–2 still produced a format spec, a load map,
a parser suite and a serial console.** That is a successful project.

---

## Stage 4+ (aspirational)

DDR init → payload load from NVMe/USB → minimal Linux with serial console only →
storage, USB, display. Port from BC-250 bring-up work rather than writing from scratch.
