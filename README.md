# PS5 Boot Chain Research

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

## Ground rules

- **No writes to console flash until a full NOR dump and a verified restore path exist.**
  That is the difference between bricked and recoverable.
- Analysis and read-only tooling only. No bootable circumvention images, in or out of this repo.
- DMCA §1201 (US) / Copyright Act s.41.1 (Canada) apply to distribution. Keep it personal, keep it private.
- Sony's HackerOne bounty excludes jailbreak work. There is no legitimate cover story for a working chain.
- Keep the console stock until the software-only work is exhausted — a 14.x jailbreak may land,
  and hardware work can foreclose that option.

## Layout

| Path | What |
|---|---|
| `PLAN.md` | Staged plan, per-stage task lists, acceptance criteria |
| `docs/01-pup-format.md` | SLB2 container + SELF component format reference |
| `docs/02-resources.md` | Discords, tools, firmware sources, prior art |
| `tooling/` | Parsers to build (Stage 0) |
| `dumps/` | PUPs and extracted images — gitignored, never committed |
