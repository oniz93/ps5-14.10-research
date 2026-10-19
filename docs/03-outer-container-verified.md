# Outer SLB2 container — verified against live firmware (2026-10-19)

These are **our own measurements**, not quoted from community docs. Method and raw
bytes below so anyone can reproduce or refute.

## Method

Sony serves PUPs with `Accept-Ranges: bytes`, so we can read any region of a
multi-gigabyte image for a few kilobytes of transfer. Reproduce with:

```bash
python3 tooling/pup_parse.py --url '<PUP URL>'
# or directly:
curl -r 0-511 -o head.bin '<PUP URL>'
```

The direct URLs are scraped from the official PS5 system-software page
(`playstation.com/en-us/support/hardware/ps5/system-software/`) — two links per
release, one `rec_…` (recovery) and one `sys_…` (update). The hash segment in the
path changes each release, so scrape rather than hard-code.

## The two files (2026_0928 release)

| | Recovery | Update |
|---|---|---|
| URL path segment | `rec_9f3a0b88…` | `sys_c1738494…` |
| Content-Length | 1,418,890,240 B (1353.16 MiB) | 1,261,408,256 B (1202.97 MiB) |

## Raw header, first 0x60 bytes

**Recovery:**
```
0000  53 4c 42 32 03 00 00 00 00 00 01 01 02 00 00 00  |SLB2............|
0010  46 49 2a 00 00 00 00 00 00 00 00 00 00 00 00 00  |FI*.............|
0020  02 00 00 00 3d 8a 2f 4b 00 00 00 00 00 00 00 00  |....=./K........|
0030  50 53 35 55 50 44 41 54 45 31 2e 50 55 50 00 00  |PS5UPDATE1.PUP..|
0040  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00  |................|
0050  c8 97 25 00 b5 fa 62 09 00 00 00 00 00 00 00 00  |..%...b.........|
0060  50 53 35 55 50 44 41 54 45 32 2e 50 55 50 00 00  |PS5UPDATE2.PUP..|
```

**Update:**
```
0000  53 4c 42 32 03 00 00 00 00 00 01 00 01 00 00 00  |SLB2............|
0010  c8 97 25 00 00 00 00 00 00 00 00 00 00 00 00 00  |..%.............|
0020  02 00 00 00 3d 8a 2f 4b 00 00 00 00 00 00 00 00  |....=./K........|
0030  50 53 35 55 50 44 41 54 45 31 2e 50 55 50 00 00  |PS5UPDATE1.PUP..|
0040  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00  |................|
0050  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00  |................|
```

## Interpretation

| Offset | Size | Field | Recovery | Update |
|---|---|---|---|---|
| 0x00 | 4 | magic | `SLB2` | `SLB2` |
| 0x04 | 4 | format version | 3 | 3 |
| 0x08 | 4 | flags | `0x01010000` | `0x00010000` |
| 0x0C | 4 | **entry count** | **2** | **1** |
| 0x10 | 8 | metadata/header size | `0x2a4946` (2,771,270) | `0x2597c8` (2,463,688) |
| 0x20 | 4 | constant | 2 | 2 |
| 0x24 | 4 | **format constant** | `0x4B2F8A3D` | `0x4B2F8A3D` |
| 0x30 | 0x30 × N | entry records | 2 records | 1 record |

- **0x08 bit 24 (`0x01000000`) is the recovery flag.** Only difference in the flags
  word between the two files, and it tracks exactly the rec/sys distinction.
- **0x24 is byte-identical in both files.** A format constant, not a checksum —
  two different files of different sizes cannot share a checksum. Candidate magic
  `0x4B2F8A3D`.
- **Entry record = 0x30 bytes**, confirmed by the two filenames landing 0x30 apart
  (0x30 and 0x60):
  - `+0x00` name[16], NUL-padded ASCII
  - `+0x10` 16 bytes — **all zero in every sample taken**, purpose unknown
  - `+0x20` 16 bytes of fields, format unknown (see open questions).
    Only recovery entry[0] is non-zero: `002597c8` then `0962fab5`, then 8 zero bytes.

## Finding 1 — the container is two-level, and it carries *filenames*

The entry table at this level holds ASCII filenames, not component IDs:

- `PS5UPDATE1.PUP` — present in **both** files
- `PS5UPDATE2.PUP` — present in **recovery only**

This is the outer wrapper. The 95-entry / 14-component-type table described in the
public 5.50 writeup (kernel, `bootloader0`, `gpu_ucode`, …) is **not** what you see
at this level. Either that analysis was performed on an exploded/decrypted image, or
the format differs from the current one. Unresolved — see open questions.

## Finding 2 — recovery ≈ update + one more payload

```
REC − SYS = 1,418,890,240 − 1,261,408,256 = 157,481,984 bytes
Recovery entry[0] field @0x58        =      157,481,653 bytes
                                          ----------------
difference                           =              331 bytes
```

331 bytes of overhead is a plausible container/alignment cost. That makes
`PS5UPDATE2.PUP` ≈ 157.5 MB the recovery-only payload, and recovery = update +
that payload. Consistent with entry count 2 vs 1 and with the recovery flag.

**Treat as strong hypothesis, not proof** — the 0x58 field's exact semantics are
not confirmed (it could be size, offset, or a hash-derived value).

## Finding 3 — the body is encrypted; the inner PUPs are not reachable this way

- 0x00–0x1FF is plaintext (header + entry table + zero padding).
- High-entropy data starts at **0x200**.
- A coarse scan (4 KiB windows on an 8 MiB stride out to 96 MiB) found **no `SLB2`
  magic anywhere except offset 0**. Targeted probes at 0x2597c8, 0x2a4946, 0x962fab5,
  0x200000, 0x280000, 0x300000, 0x400000, 0x100000 are all high-entropy, no magic.
- No `\x7fELF` (or any plaintext ELF) in the header region.

**Conclusion:** the inner PUPs are encrypted before storage. The outer container gives
you the file inventory and the metadata block size — nothing about components,
load addresses, or memory layout.

## Open questions

1. Does the 5.50 published layout match current firmware at all, or did the format
   change? Test by probing an older PUP — Sony only serves the latest from its page,
   so this needs an archived URL or a MEGA download from Darthsternie.
2. What are the 32 field bytes at entry `+0x10`? Only recovery entry[0] is
   non-zero in our samples, so we have one data point, not a pattern. Probe more
   releases to get multiple data points.
3. Does `0x10` (2,771,270 vs 2,463,688) mean "metadata block size"? Note the update
   file's value (0x2597c8) is byte-identical to the recovery file's entry[0] `+0x20`
   field — probably not a coincidence, but the link is not understood.
4. Where does the inner PUP actually begin, and is it reachable at all without a
   console-side key?
