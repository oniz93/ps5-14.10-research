# PS5 Boot Chain Research

> **Disclaimer:** Independent security research on hardware I own, published for educational
> and defensive purposes only. This repository is a research record — it does not ship a
> jailbreak, an exploit chain, a loader payload, Sony firmware, or decryption keys, and it is
> not affiliated with or endorsed by Sony Interactive Entertainment or any console vendor.
> Provided "as is", without warranty of any kind. Read [DISCLAIMER.md](DISCLAIMER.md) before
> using anything here; third-party material is listed in [NOTICE.md](NOTICE.md).

Personal reverse-engineering project: understand the PS5 boot chain well enough to
document it — and, long shot, eventually replace stage 2 and boot Linux directly
with no hypervisor in the path.

**Target console:** retail PS5, FW 14.10 (no public jailbreak available)
**Current stage:** 0 — software only, zero hardware risk
**Started:** 2026-10-19

## The chain

```
Power-on → BootROM (mask ROM, immutable)
         → LDLR bootloader (SPI NOR flash)      ← stage 1
         → LV2 hypervisor                        ← stage 2
         → FreeBSD-derived kernel
         → GameOS userland
```

If stage 1 is replaced, stage 2 is optional — our loader decides what runs next.
That is the entire premise of this project.

## Scope

- **Included:** format analysis, read-only parsers, probe pages, local harnesses, measurement
  data, and dated write-ups of what did and did not reproduce.
- **Not included:** firmware or update packages, decryption or signing keys, extracted
  binaries, bootable images, a kernel exploit, or a loader payload. Consoles are studied, not
  modified, and nothing here is distributed as a circumvention tool.
- **Third-party material:** quoted from openly published sources under their own licences —
  see [NOTICE.md](NOTICE.md). Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md).

## Ground rules

- **No writes to console flash until a full NOR dump and a verified restore path exist.**
  That is the difference between bricked and recoverable.
- Analysis and read-only tooling only. No bootable circumvention images, in or out of this repo.
- DMCA §1201 (US) / Copyright Act s.41.1 (Canada) restrict *distribution* of circumvention
  technology, and the US security-testing exemption does not cover trafficking. That is why
  this repository publishes analysis and measurements only — see [DISCLAIMER.md](DISCLAIMER.md) §4 and §7.
- Sony's HackerOne bounty excludes jailbreak work. There is no legitimate cover story for a working chain.
- Keep the console stock until the software-only work is exhausted — a 14.x jailbreak may land,
  and hardware work can foreclose that option.

## Layout

| Path | What |
|---|---|
| `PLAN.md` | Staged plan, per-stage task lists, acceptance criteria |
| `docs/` | Numbered research notes, 01–63: PUP/SLB2 format, loaders, WebKit and console results |
| `data/` | Measurement output in JSON — candidate sweeps, patch-presence checks, probe results |
| `tooling/`, `tools/fw1400/` | Read-only parsers, sysent resolvers, probe harnesses, fuzzers, console automation |
| `deliverables/` | Probe scripts and write-ups. Loader payloads and save files are **not** distributed here |
| `research/` | Provenance pointers and the original survey notes; third-party code is cloned, never vendored |
| `dumps/` | PUPs and extracted images — gitignored, never committed |

## Status of this repository

This is a working notebook, not a release. Documents are dated and superseded rather than
rewritten, so older notes may state things later work contradicts — `docs/` is the record of
that correction, and the newest numbered note is the current position.

---

Published under the terms in [LICENSE](LICENSE). No warranty of any kind; the views are my own
and not those of any employer. See [DISCLAIMER.md](DISCLAIMER.md) for scope, jurisdiction notes
and the takedown contact.
