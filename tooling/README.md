# Tooling

Stage 0 parsers. Read-only by design — nothing here writes to a console, a PUP, or flash.

## `pup_parse.py`

Parse the SLB2 container: header, entry table, components.

```
python pup_parse.py <file.PUP>
```

Emits:

```
out/<pupname>/
├── entries.csv          id, name, comp_size, uncomp_size, offset, flags
├── components/          one file per entry, named <id>_<name>.bin
└── header_hex.txt       first 8 KB as hex
```

Validate against the published 5.50 breakdown (95 entries, 14 component types) before
trusting output from any other version.

## `self_header.py`

For each extracted component, parse the SELF header (`ET_SCE_EXEC`, type `0xFE00`).

Extracts: ELF structure, segment table, `p_vaddr` / `p_paddr` load addresses, entry
point, segment flags. Writes `self_map.csv`.

**This is the memory-map payload.** SELF headers are plaintext even when the segments
are encrypted, so load addresses and entry points come free.

## `loadmap.py`

Aggregate per firmware: component → load address range → entry point → size.
Diff across versions.

```
python loadmap.py out/5.50 out/13.60 out/14.00 out/14.10 --diff
```

Primary question it answers: **did the boot chain change structurally between 13.60
and 14.10?** Focus on `bootloader0` (`0x1100`) and `kernel` (`0x1000`).

## Rules

- Never commit anything from `dumps/` or `out/`. Firmware images do not leave this machine.
- Keep parsers independent of `zecoxao/ps5-pup-unpacker` so cross-checking means something.
- When output disagrees with the published 5.50 writeup, the writeup wins until proven
  otherwise — and the disagreement gets written down.
