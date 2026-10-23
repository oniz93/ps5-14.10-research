# PUP fetching: verified URL grammar and container geometry to 14.20

> All values below were obtained 2026-10-23 with single HTTP Range requests against
> live Sony hosts. Reproduce with `python3 tools/fw1400/pup_url.py --all`.

## The URL grammar

Two hosts, two prefixes, one constant:

```
list:  http://fus01.ps5.update.playstation.net/update/ps5/official/<OBF>/list/<region>/updatelist.xml
image: http://dus01.ps5.update.playstation.net/update/ps5/official/<OBF>/image/<YYYY_MMDD>/<kind>_<sha256>/PS5UPDATE.PUP?dest=<region>

OBF    = tJMRE80IbXnE9YuG0jzTXgKEjIMoabr6      (constant for every build and region)
kind   = sys  (system update)  |  rec  (recovery)
region = au br cn jp ru sa uk us
```

Three details that cost real time if missed:

- **`dus01`, not `fus01`** for the image. `fus01` answers the list only.
- **`rec_` for recovery, `sys_` for system.** The hash in the community table's recovery
  row belongs in a `rec_` path; putting it under `sys_` returns 404.
- **`?dest=<region>` is required for `sys_`** and appears to be optional for `rec_`. A
  captured path without it 404s — the likely reason a previously captured path "did not
  work off-console".

## Verified builds

| build | label | date | system PUP | bytes | blocks |
|---|---|---|---|---|---|
| 13.60 | `26.05-13.60.00.07-00.00.00.0.1` | `2026_0717` | `sys_767a94ea…112561` | 1,247,471,104 | 2,436,467 |
| **14.00** | **`26.06-14.00.00.39-00.00.00.0.1`** | **`2026_0909`** | `sys_1eb4b184…108ebc` | **1,260,600,832** | 2,462,111 |
| 14.10 | `26.06-14.10.00.03-00.00.00.0.1` | `2026_0928` | `sys_c1738494…cdaaf6` | 1,261,408,256 | 2,463,688 |
| 14.20 | `26.07-14.20.00.07-00.00.00.0.1` | `2026_1014` | `sys_0f81be6f…7f68e4` | 1,266,086,912 | 2,472,826 |

All four answer `HTTP 206`, `Accept-Ranges: bytes`, and `total_blocks × 512` equals the
served content length exactly — the arithmetic check that validated the outer layout
still holds on every build.

14.00 is **the build on the shelf**: `26.06-14.00.00.39`. Record that string; it is the
anchor for any later dump.

## Container geometry: unchanged from 13.60 to 14.20

| field | 13.60 | 14.00 | 14.10 | 14.20 |
|---|---|---|---|---|
| magic | `SLB2` | `SLB2` | `SLB2` | `SLB2` |
| version | 3 | 3 | 3 | 3 |
| flags (system) | `0x10000` | `0x10000` | `0x10000` | `0x10000` |
| entries (system) | 1 | 1 | 1 | 1 |
| entry size | 48 B | 48 B | 48 B | 48 B |
| block unit | `0x200` | `0x200` | `0x200` | `0x200` |
| entry name | `PS5UPDATE1.PUP` | same | same | same |

So "did the boot-chain container change between these builds" is answered: **no**, at the
outer level. That is a negative result, and worth recording as one — it means a parser
written against 13.60 applies unchanged to the newest build.

### Recovery is structurally different, as expected

14.00 recovery (`rec_7ec8dd8a…c556`, 1,418,082,816 B):

```
flags 0x1010000   (bit 24 set)   entries 2
entry0: block 2         off 0x400        size 1,260,599,765  PS5UPDATE1.PUP
entry1: block 2,462,111 off 0x4b233e00   size   157,481,653  PS5UPDATE2.PUP
```

This confirms the earlier bit-24 claim with a live sample: **`0x01000000` distinguishes
recovery**, and `0x10000` is a base flag present on every package. Entry0 of the recovery
image is byte-sized identically to the system image's only entry (1,260,599,765), so the
recovery package is the system update plus one extra 157 MB component.

## The inner header is still plaintext, on 14.20

At entry0's offset (`0x400`), every build begins with the same 16 bytes:

```
54 14 f5 ee  10 01 01 32  04 00 00 00  b0 05 e0 0d
magic 0xEEF51454   format 0x32010110   field=4   hdr=0x05B0  hashtab=0x0DE0
```

`0x05B0` = 1456 = 16 + 45×32, so the inner PUP still declares 45 entries — the testable
prediction from the 13.60 work holds on 14.00, 14.10 and 14.20. Ciphertext still begins
at `+0x10`.

What this does **not** change: the outer key is still what blocks everything. Identical
geometry means a parser transfers; it does not mean anything decrypts.

## Tool

```bash
python3 tools/fw1400/pup_url.py --current              # what Sony serves right now
python3 tools/fw1400/pup_url.py --build 14.00          # URL + header probe for the shelf unit
python3 tools/fw1400/pup_url.py --build 14.00 --kind rec
python3 tools/fw1400/pup_url.py --all                  # geometry table, all four builds
```

Each call transfers at most 1104 bytes. Nothing here writes to a console.

## Open questions

- What is the 157 MB `PS5UPDATE2.PUP` component of the recovery image? It has no system
  counterpart, so it is recovery-specific payload — the most interesting unexamined
  artifact reachable without a console.
- Does the flag word carry other meaning bits? `0x10000` appears on every package, so it
  is not "system" vs "recovery"; the pair is (`0x10000`, `0x1010000`).
- Entry sizes differ by ~1 KB from the served file size (`1,260,600,832 − 1,260,599,765 =
  1,067`). That gap is the header + digest region; if a future build's gap moves, the
  outer header grew.
