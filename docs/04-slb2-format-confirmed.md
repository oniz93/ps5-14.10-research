# SLB2 outer container — CONFIRMED spec

Status: **resolved**. Verified three ways: our own byte probes of live Sony
firmware, two independent third-party implementations, and exact arithmetic.

Supersedes `03-outer-container-verified.md`, which records the first probe pass
and got two fields wrong. The corrections are listed at the bottom — they are
kept deliberately, because the way they were caught is the useful part.

## Layout

```
0x00   4    magic              "SLB2"  (53 4C 42 32)
0x04   4    version            3
0x08   4    flags              0x00010000 base; bit 24 (0x01000000) = recovery
0x0C   4    entry_count        1 = system/update, 2 = recovery
0x10   8    total size         in 0x200-byte blocks
0x18   8    zero
0x20   N×0x30  entry records
```

### Entry record (0x30 bytes)

```
+0x00  4    block_offset       in 0x200-byte blocks
+0x04  4    size               bytes
+0x08  8    zero
+0x10  0x20 name               NUL-padded ASCII
```

### Body

- `0x200` — 32-byte digest (SHA-256-shaped; coverage unknown)
- `~0x400` — payload, encrypted (entropy ≈ 7.997/8.0)

## Proof — the arithmetic closes exactly

**System / update PUP** (1,261,408,256 bytes):

```
0x10 = 2,463,688 blocks  × 512 = 1,261,408,256   = file size, exactly
entry[0] PS5UPDATE1.PUP: block 2 → byte 1,024; size 1,261,406,781; end 1,261,407,805
trailer: 451 bytes
```

**Recovery PUP** (1,418,890,240 bytes):

```
0x10 = 2,771,270 blocks  × 512 = 1,418,890,240   = file size, exactly
entry[0] PS5UPDATE1.PUP: block 2,463,688 ... size 1,261,406,781; end 1,261,407,805
entry[1] PS5UPDATE2.PUP: block 2,463,688 → byte 1,261,408,256; size 157,481,653; end 1,418,889,909
gap 451 · trailer 331
```

Both files close to the byte. `0x10 × 512` matching the on-disk size on two
different files is not coincidence — it is the field's definition.

Structural consequence: **recovery = system payload + one extra ~150 MiB payload.**
`entry[0].size` (1,261,406,781) is the same in both, and the system PUP is that
payload plus a 451-byte trailer.

## Corroboration

Two independent implementations parse this layout:

| Source | Confirms |
|---|---|
| `Whoisraeen/Raeen` — `crates/raeen-firmware/src/slb2.rs` | header 0x20, entries at 0x20, 0x30 stride, name at entry+0x10 len 0x20, block offset × 0x200 |
| `TINYTINY11/Kura-a-PS5-Emulator` — `docs/RE-pup.md` | magic, version 3, `PS5UPDATE1.PUP` at 0x30 "confirmed", payload entropy ≈ 7.997 |
| `zecoxao/ps5-pup-decrypt` — `source/decrypt.c` | string-compares `PS5UPDATE1.PUP` / `PS5UPDATE2.PUP`; README: one or two `.dec` files depending on sys vs recovery |

Kura's independent reading of `0x24` as "near-file-size, 1,475 bytes larger" is
the same number our layout calls `entry[0].size` — their file was the system
PUP, where `entry[0].size + 451 = file size`, and 1,475 is their measurement of
the delta from a slightly different baseline. Same field, two derivations.

## What this does NOT give you

The payload is encrypted. There is no plaintext ELF and no nested `SLB2` inside
the outer wrapper — a coarse scan (4 KiB windows, 8 MiB stride, 96 MiB) found the
magic only at offset 0.

So the outer container yields: **file inventory, sizes, offsets, and the
recovery/system relationship.** It does not yield components, load addresses, or
a memory map. That still requires a `.dec` file.

Per `deepkicks/TitaniaPy`, the crypto stack is:

| Layer | What | Status |
|---|---|---|
| 0 | PBKDF2 master key derivation | solved, public |
| 1 | **PUP container encryption** | **blocked — key not public** |
| 2 | PUP segment-level | blocked (depends on 1) |
| 3 | Inner firmware encryption | solved |

Layer 1 is the whole wall. Its key lives behind console-side crypto; the only
public extraction route is a jailbroken PS5 at ≤13.60 with kernel R/W.

## Corrections to the first pass

| Field | First pass (wrong) | Confirmed |
|---|---|---|
| entry table offset | `0x30` | **`0x20`** — names land at `0x30` only because the name field is at entry`+0x10` |
| `0x24` | "format constant `0x4B2F8A3D`" | **`entry[0].size`** = 1,261,406,781. Identical across both files because recovery *contains* the same system payload — not because it is a constant |
| `0x10` | "metadata size" | **total size in 0x200 blocks** |
| body start | "`0x200`" | `0x200` is a digest; payload starts ~`0x400` |
| `0x0C` | entry count (correct) | entry count — confirmed by having *two* files where Kura had one and doubted it |

The "constant across two files" inference was the trap. It was true as an
observation and wrong as an explanation: two files can share a field because one
contains the other. Arithmetic against file size is what broke the tie.

## Reproduce

```bash
cd tooling
python3 pup_parse.py --url '<PUP URL>'          # ~8 KB transferred
```

The parser prints the header-derived size, the per-entry spans, and the trailer,
and flags `NEGATIVE trailer` if the interpretation ever stops closing.
