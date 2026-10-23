# Sysent dispatch on PS5: `sy_call` is a thunk, not a handler

> Verified 2026-10-23 against the 13.60 capture in
> `research/PS5-14.10-Research/docs/dumps_13.60/`. Reproduce with
> `python3 tools/fw1400/sysent_resolve.py selftest`.

## The finding

`sysent[i].sy_call` does **not** point at the implementing function. It points at an
8-byte thunk:

```
e9 <rel32>   cc cc cc        ; jmp rel32, then int3 padding
```

Real handler RVA = `thunk + 5 + rel32`.

Evidence, in order of strength:

1. All 679 `sy_call` values in the 13.60 capture land inside a single 33 KiB window,
   `0x25dc28`–`0x265fa8`. Real handlers cannot be that dense.
2. Every one of those addresses begins `e9` followed by `cc cc cc` padding.
3. Resolving the thunks reproduces, byte-exact, the four handler RVAs that the 14.10
   research repo derived independently by disassembly:

| syscall | thunk | resolved handler | documented | |
|---|---|---|---|---|
| 563 | `0x265dc8` | `0x602fe0` | `0x602fe0` | MATCH |
| 596 | `0x2655b0` | `0x34c750` | `0x34c750` | MATCH |
| 624 | `0x265ea8` | `0xabd4f0` | `0xabd4f0` | MATCH |
| 663 | `0x265720` | `0x3b01f0` | `0x3b01f0` | MATCH |

Zero unresolved entries, zero non-`e9` targets, zero out-of-image pointers.

## Verified 13.60 table shape

| Property | Value |
|---|---|
| entries | 679 × 48 bytes (`sysent_raw.bin` = 32,592 B) |
| live handlers | 311 |
| `nosys` entries | 368, all sharing thunk `0x265760` → handler `0x5620e0` |
| distinct live handlers | 300 |
| Sony range 532–676 | 115 live, 30 `nosys` |
| table RVA | `+0xe6e5c0` (13.60 session) |
| entries 677–678 | resolve to thunks but are structurally malformed (`narg` junk); outside the declared range — treat the table as 679 entries with a 2-entry tail that is not syscall metadata |

Resolved table: `data/sysent_1360_resolved.json` (every entry: `narg`, `thunk_off`,
`handler_off`, `nosys` flag).

## Three consequences

**1. Any cross-firmware diff must resolve thunks first.** Comparing `sy_call` values
across builds compares thunk placement, not code. A firmware that renumbers or
repacks its thunk table will look like "every syscall changed" while the handlers are
byte-identical. Conversely, an unchanged thunk layout with changed targets is a clean
signal that specific handlers were edited.

**2. The thunk table is itself a diff artefact.** Thunks are laid out in syscall order
at 8-byte stride, so a 14.00 capture tells you immediately which syscalls were added,
removed, or repointed, before you disassemble anything.

**3. The AIO surface is Sony's own code, not FreeBSD's.** This one corrects a working
assumption:

- FreeBSD 11.0 tops out at syscall 550 and has **no** `aio_multi_wait` entry. Its AIO
  calls are 255, 256, 314–319, 359, 465, 543.
- On 13.60, most of those are `nosys`: 255, 256, 314, 316, 317, 465 are all stubs.
  Only 315 (`aio_suspend`) and 543 (`aio_mlock`) are live.
- PS5 instead carries a Sony-authored AIO block at **661–670, all ten live**:

| syscall | narg | handler |
|---|---|---|
| 661 | 4 | `0x3af8f0` |
| 662 | 3 | `0x3af900` |
| **663** | 5 | `0x3b01f0` ← `aio_multi_wait`, the Relapse UaF |
| 664 | 3 | `0x3b0fb0` |
| 665 | 2 | `0x3b1670` |
| 666 | 3 | `0x3b1680` |
| 667 | 2 | `0x4a31a0` |
| 668 | 2 | `0x3af8e0` |
| 669 | 5 | `0x3b2060` |
| 670 | 4 | `0x3b28d0` |

So the Relapse kernel bug is not an un-backported FreeBSD advisory — it is a bug in
Sony's re-implementation, and 14.00's fix is Sony's own patch. That matters for
strategy: the "port FreeBSD advisories" method does not explain this bug class, and
the natural place to look for a 14.00 sibling is the nine neighbouring entries in the
same Sony block — hand-written, recently touched, and (as far as public evidence goes)
patched only at 663.

## Tools shipped with this note

| tool | what it does | proof it works |
|---|---|---|
| `tools/fw1400/sysent_resolve.py` | sysent → resolved handler RVAs; `diff A B` for two firmwares | `selftest`: 4/4 documented handlers match, 0 problems |
| `tools/fw1400/find_sysent.py` | locate a sysent table inside an arbitrary image with no symbols | `selftest`: finds the 13.60 table byte-identically in the 64 KiB capture, 0 false positives on random data |
| `tools/fw1400/identify_fw.py` | identify firmware from a dump by walking `allproc` and testing each landmark set | `--synthetic-test`: 13.60 and 14.00 both identified at 1.0; a base shifted by 0x10000 scores 0.0 |

Run order the day a 14.00 image exists:

```bash
# 1. find the table (no base needed if you pass the region)
python3 tools/fw1400/find_sysent.py --image dump.bin --base 0x<base>

# 2. resolve it and compare against 13.60
python3 tools/fw1400/sysent_resolve.py resolve --sysent <sysent.bin> \
    --text <text.bin> --base 0x<base> -o data/sysent_1400_resolved.json
python3 tools/fw1400/sysent_resolve.py diff data/sysent_1360_resolved.json \
    data/sysent_1400_resolved.json

# 3. confirm the layout hypothesis independently
python3 tools/fw1400/identify_fw.py --manifest dump.json
```

## Open questions this raises

- Does 14.00 keep the same table RVA (`+0xe6e5c0`) and the same 679 entries? The
  14.10 project has no 14.10 table, so this is unmeasured.
- Are the 368 `nosys` entries the same set? A syscall enabled between builds is a
  new attack surface; a syscall removed is a dead end.
- Did 14.00 repoint any of 661–670 besides 663? That is the cheapest question to ask
  of the first 14.00 image that lands, and the answer directs the whole kernel hunt.
