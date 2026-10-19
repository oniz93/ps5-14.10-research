#!/usr/bin/env python3
"""
self_header.py — Inspect a PS5 SELF component blob. READ-ONLY.

Deliberately empirical. We do NOT hard-code an assumed SELF struct layout,
because getting that wrong produces plausible-looking garbage addresses,
which is worse than no answer.

What it does instead:
  1. checks the SELF magic (0x4F153D1D) in both byte orders and says which hit
  2. dumps the header's 64-bit fields as raw values *with offsets*, so the real
     layout can be confirmed against live data rather than guessed
  3. locates the embedded PLAINTEXT ELF header (\\x7fELF, 64-bit, little-endian)
  4. parses the ELF program headers -> load addresses (p_vaddr / p_paddr),
     entry point, and segment sizes

Step 3 is the valuable one: the documented claim is that SELF headers carry a
readable ELF structure even when the segments themselves are AES-encrypted.
If that is true, load addresses and entry points come free.

Usage:
    python3 self_header.py <component.bin>
    python3 self_header.py <component.bin> --json
"""

import argparse
import json
import struct
import sys
from pathlib import Path

SELF_MAGIC = 0x4F153D1D
ELF_MAGIC = b"\x7fELF"
SEARCH_WINDOW = 0x200000  # 2 MiB is plenty; the ELF header sits near the front


def find_self_magic(buf):
    """Return (offset, endian, how) for the SELF magic, or None."""
    le = struct.pack("<I", SELF_MAGIC)
    be = struct.pack(">I", SELF_MAGIC)
    i = buf.find(le)
    if i >= 0:
        return i, "little", "0x4F153D1D stored little-endian"
    i = buf.find(be)
    if i >= 0:
        return i, "big", "0x4F153D1D stored big-endian"
    return None


def dump_qwords(buf, start, count, endian="<"):
    out = []
    for i in range(count):
        off = start + i * 8
        if off + 8 > len(buf):
            break
        val = struct.unpack_from(endian + "Q", buf, off)[0]
        out.append({"offset": off, "value": val, "hex": f"{val:#x}"})
    return out


def find_elf_headers(buf, limit=SEARCH_WINDOW):
    """Find candidate ELF64 little-endian headers in the first `limit` bytes."""
    hits = []
    pos = 0
    window = buf[:limit]
    while True:
        pos = window.find(ELF_MAGIC, pos)
        if pos < 0:
            break
        if pos + 20 <= len(buf):
            ei_class = buf[pos + 4]
            ei_data = buf[pos + 5]
            if ei_class == 2 and ei_data == 1:
                hits.append(pos)
        pos += 4
    return hits


def parse_elf64(buf, base):
    """Parse an ELF64 LE header at `base`. Returns dict or raises."""
    if buf[base : base + 4] != ELF_MAGIC:
        raise ValueError("not ELF")
    (e_type, e_machine, e_version) = struct.unpack_from("<HHI", buf, base + 0x10)
    (e_entry, e_phoff, e_shoff) = struct.unpack_from("<QQQ", buf, base + 0x18)
    (e_flags,) = struct.unpack_from("<I", buf, base + 0x30)
    (e_ehsize, e_phentsize, e_phnum) = struct.unpack_from("<HHH", buf, base + 0x34)
    (e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHH", buf, base + 0x3A)

    segs = []
    if e_phoff and e_phnum and e_phentsize >= 56:
        # Program headers are relative to the ELF header.
        for i in range(e_phnum):
            ph = base + e_phoff + i * e_phentsize
            if ph + 56 > len(buf):
                segs.append({"index": i, "error": "beyond buffer"})
                continue
            (p_type, p_flags) = struct.unpack_from("<II", buf, ph)
            (p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align) = struct.unpack_from(
                "<QQQQQQ", buf, ph + 0x08
            )
            segs.append(
                {
                    "index": i,
                    "p_type": p_type,
                    "p_flags": p_flags,
                    "p_offset": p_offset,
                    "p_vaddr": p_vaddr,
                    "p_paddr": p_paddr,
                    "p_filesz": p_filesz,
                    "p_memsz": p_memsz,
                    "p_align": p_align,
                }
            )

    return {
        "elf_header_offset": base,
        "e_type": e_type,
        "e_machine": e_machine,  # 0x3E = x86-64, 0xB7 = AArch64
        "e_version": e_version,
        "e_entry": e_entry,
        "e_phoff": e_phoff,
        "e_shoff": e_shoff,
        "e_flags": e_flags,
        "e_ehsize": e_ehsize,
        "e_phentsize": e_phentsize,
        "e_phnum": e_phnum,
        "segments": segs,
    }


MACHINES = {0x3E: "x86-64", 0xB7: "AArch64", 0x03: "i386", 0x28: "ARM"}


def main():
    ap = argparse.ArgumentParser(description="Inspect a PS5 SELF component. Read-only.")
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--qwords", type=int, default=16, help="64-bit fields to dump from header")
    args = ap.parse_args()

    p = Path(args.file).expanduser()
    if not p.exists():
        sys.exit(f"not found: {p}")
    buf = p.read_bytes()
    report = {"file": str(p), "size": len(buf)}

    # 1. SELF magic
    hit = find_self_magic(buf)
    report["self_magic"] = (
        {"found": True, "offset": hit[0], "endian": hit[1], "note": hit[2]}
        if hit
        else {"found": False}
    )

    # 2. raw qword dump (for reverse-engineering the real struct layout)
    hdr_start = hit[0] if hit else 0
    report["header_qwords"] = dump_qwords(buf, hdr_start, args.qwords)

    # 3. embedded ELF headers
    elf_hits = find_elf_headers(buf)
    report["elf_headers_found"] = elf_hits

    elf_reports = []
    for base in elf_hits[:4]:
        try:
            elf_reports.append(parse_elf64(buf, base))
        except Exception as e:  # noqa: BLE001 - report, don't crash
            elf_reports.append({"elf_header_offset": base, "error": str(e)})
    report["elf"] = elf_reports

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"file : {p}")
    print(f"size : {len(buf):,} bytes")
    print()

    print("== SELF magic ==")
    if hit:
        print(f"  found at {hit[0]:#x}  ({hit[2]})")
    else:
        print(f"  NOT found in first {len(buf):,} bytes")
        print(f"  first 32 bytes: {buf[:32].hex(' ')}")
        print("  -> if this blob came from a stock PUP, the component is probably")
        print("     still SLB2-encrypted. A decrypted PUP is needed to see the SELF.")

    print(f"\n== header qwords (from {hdr_start:#x}) ==")
    for q in report["header_qwords"]:
        print(f"  +{q['offset']:04x}  {q['hex']:>20}  {q['value']:,}")

    print("\n== embedded ELF headers ==")
    if not elf_hits:
        print("  none found")
    for elf in elf_reports:
        if "error" in elf:
            print(f"  @ {elf['elf_header_offset']:#x}  error: {elf['error']}")
            continue
        mach = MACHINES.get(elf["e_machine"], f"unknown({elf['e_machine']:#x})")
        print(f"  @ {elf['elf_header_offset']:#x}   machine={mach}  type={elf['e_type']}")
        print(f"      entry point (e_entry) : {elf['e_entry']:#018x}")
        print(f"      phoff={elf['e_phoff']:#x}  phnum={elf['e_phnum']}  phentsize={elf['e_phentsize']}")
        print(f"      {'idx':>3} {'type':>6} {'flags':>6} {'p_vaddr':>18} {'p_paddr':>18} {'filesz':>10} {'memsz':>10}")
        for s in elf["segments"]:
            if "error" in s:
                print(f"      {s['index']:>3}  {s['error']}")
                continue
            print(
                f"      {s['index']:>3} {s['p_type']:>#6x} {s['p_flags']:>#6x} "
                f"{s['p_vaddr']:>#18x} {s['p_paddr']:>#18x} "
                f"{s['p_filesz']:>10,} {s['p_memsz']:>10,}"
            )


if __name__ == "__main__":
    main()
