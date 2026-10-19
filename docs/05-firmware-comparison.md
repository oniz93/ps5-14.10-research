# Cross-firmware comparison: 13.60 → 14.00 → 14.10

Measured 2026-10-19 by Range-probing Sony's official update servers. URLs come
from `MewX/ps5-official-firmware-list` (community-maintained, with checksums), which
publishes the date + hash path segment for every release. Pattern:

```
https://pc.ps5.update.playstation.net/update/ps5/official/<OBFUSCATED>/image/<DATE>/sys_<HASH>/PS5UPDATE.PUP
https://pc.ps5.update.playstation.net/update/ps5/official/<OBFUSCATED>/image/<DATE>/rec_<HASH>/PS5UPDATE.PUP
```

Total transfer for this entire comparison: a few kilobytes per version.

## Results

| Version | Blocks @0x10 | × 512 | Actual file | Match | entry[0].size |
|---|---|---|---|---|---|
| 14.10 | 2,463,688 | 1,261,408,256 | 1,261,408,256 | ✓ | 1,261,406,781 (`0x4B2F8A3D`) |
| 14.00 | 2,462,111 | 1,260,600,832 | 1,260,600,832 | ✓ | 1,260,599,765 (`0x4B2339D5`) |
| 13.60 | 2,436,467 | 1,247,471,104 | 1,247,471,104 | ✓ | 1,247,469,973 (`0x4A5AE195`) |

The header-derived size matches the real file size **exactly on all three**. The
layout in `04-slb2-format-confirmed.md` is not a one-release coincidence.

## Inner PUP header — invariant across all three

At `0x400` (entry[0].block_offset 2 × 0x200):

| Offset | Size | 13.60 | 14.00 | 14.10 |
|---|---|---|---|---|
| +0x00 | 4 | `0xEEF51454` | same | same |
| +0x04 | 4 | `0x32010110` | same | same |
| +0x08 | 4 | 4 | 4 | 4 |
| +0x0C | 2 | `0x05B0` (1456) | same | same |
| +0x0E | 2 | `0x0DE0` (3552) | same | same |

Byte-identical across three firmware generations. Encryption begins at `0x410` —
the first 256-byte block measures 7.15 bits/byte entropy because 16 structured
bytes sit in front of 240 random ones, then it sits at 7.2+.

Cross-check: `deepkicks/TitaniaPy` independently reports FW 14.00 as 1,260,600,832
bytes / BLS entry size `0x4B2339D5`, and FW 14.10 as 1,261,408,256 bytes / `0x4B2F8A3D`.
Both match exactly, from a different implementation.

## What changed between versions: only the payload

Container version, flags, entry count, header geometry, inner magic, and the
`0x32010110` format field are identical across 13.60, 14.00 and 14.10. The only
differences are `entry[0].size` and the header-derived total.

**So at the container level, the answer is no — the boot chain structure did not
change between the last jailbreakable firmware and the one we run.** The content
changed; the format did not.

## Hypothesis: the inner PUP has 45 entries

`0x05B0` = 1456 bytes. If the header is a 16-byte base followed by 32-byte records:

```
(1456 − 16) / 32 = 45 exactly
```

That is a clean fit and would mean the inner PUP consistently describes **45
segments**. The 5.50 community writeup claims 95 entries at 48 bytes — a different
number and a different record size, which is further evidence that it describes a
different (exploded/decrypted) representation rather than this one.

**Unverified.** Confirming it needs the Layer 1 key. Recorded as a hypothesis with
a testable prediction: decrypt the header and the entry count should be 45.

## What this does and does not buy

**Buys:** a closed container-format question, a cross-version guarantee, and a
known 16-byte window that any future decryption attempt must start from.

**Does not buy:** components, load addresses, or a memory map. From `0x410` onward
it is ciphertext, and the Layer 1 key is not public (see
`04-slb2-format-confirmed.md`).

## Sources for this page

- `MewX/ps5-official-firmware-list` — release table (date, hash, size, MD5) for every PUP
- `deepkicks/TitaniaPy` — independent 14.00/14.10 measurements and the crypto-layer map
- Live probes of `pc.ps5.update.playstation.net`, 2026-10-19
