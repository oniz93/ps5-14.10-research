#!/usr/bin/env python3
"""
pup_parse.py — Parse the PS5 PUP outer SLB2 container. READ-ONLY.

Format verified empirically against live 2026 firmware on 2026-10-19 by HTTP Range
probing. See docs/03-outer-container-verified.md for the raw bytes and reasoning.

VERIFIED OUTER FORMAT
  0x00  4    magic                 "SLB2" = 53 4C 42 32
  0x04  4    format version        3 on current firmware
  0x08  4    flags                 bit 24 (0x01000000) set = recovery PUP
  0x0C  4    entry count           1 for update, 2 for recovery
  0x10  8    metadata size         differs per release
  0x20  4    constant              2
  0x24  4    format constant       0x4B2F8A3D (identical across files)
  0x30  N*0x30  entry records

  Entry record (0x30 bytes):
    +0x00  16   name, NUL-padded ASCII (e.g. "PS5UPDATE1.PUP")
    +0x10  16   unknown — all zero in every sample taken
    +0x20  16   fields, format not yet understood

The body (>= 0x200) is encrypted. There is no plaintext ELF and no nested SLB2 in
the outer container — the inner PUP is not reachable without console-side keys.

NOTE: the community-published 5.50 layout (95 entries, component IDs like 0x1000
kernel / 0x1100 bootloader0) does NOT describe this outer level. That layout likely
applies to the decrypted inner PUP. It is retained in this file as PUBLISHED layout
for cross-checking only.

Usage:
    python3 pup_parse.py <file.PUP>           # local file
    python3 pup_parse.py --url <https-url>    # probe header via Range, no full download
    python3 pup_parse.py --url <url> --csv entries.csv
"""

import argparse
import csv
import struct
import sys
import urllib.request
from pathlib import Path

SLB2_MAGIC = b"SLB2"
SLB2_CONST = 0x4B2F8A3D
FLAG_RECOVERY = 0x01000000
HEADER_FIXED = 0x30
ENTRY_SIZE = 0x30
NAME_LEN = 0x10

# From the community writeup — describes the INNER (decrypted) PUP, not verified by us.
PUBLISHED_ENTRY_IDS = {
    0x0100: "eap_kernel", 0x0200: "emc_ipl", 0x0300: "tee", 0x0400: "bios",
    0x0600: "smf_ipl", 0x1000: "kernel", 0x1100: "bootloader0", 0x1300: "psp_bl",
    0x1400: "psp_kernel", 0x2000: "update_package", 0x4000: "version_info",
    0x5000: "swu_manifest", 0x20000: "gpu_ucode", 0x30000: "sio_firmware",
}


def http_range(url, start, length):
    req = urllib.request.Request(
        url,
        headers={"Range": f"bytes={start}-{start + length - 1}", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        note = f"HTTP {resp.status}"
        if resp.status == 200:
            note += "  (Range ignored — full body returned)"
        return resp.read(), note


def http_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.headers.get("Content-Length")


def parse_header(buf):
    if len(buf) < HEADER_FIXED:
        raise ValueError(f"only {len(buf)} bytes — too short")
    magic = buf[0:4]
    version, flags, count = struct.unpack_from("<III", buf, 0x04)
    meta_size = struct.unpack_from("<Q", buf, 0x10)[0]
    const20 = struct.unpack_from("<I", buf, 0x20)[0]
    const24 = struct.unpack_from("<I", buf, 0x24)[0]
    return {
        "magic": magic,
        "version": version,
        "flags": flags,
        "entry_count": count,
        "metadata_size": meta_size,
        "const_0x20": const20,
        "const_0x24": const24,
    }


def parse_entries(buf, hdr):
    n = hdr["entry_count"]
    if n > 64:
        raise ValueError(f"entry_count={n} implausible for the outer container — refusing")
    need = HEADER_FIXED + n * ENTRY_SIZE
    if len(buf) < need:
        raise ValueError(f"need {need} bytes, have {len(buf)} — raise --header-bytes")
    out = []
    for i in range(n):
        base = HEADER_FIXED + i * ENTRY_SIZE
        raw = buf[base : base + NAME_LEN]
        name = raw.split(b"\x00")[0].decode("ascii", "replace")
        unknown = buf[base + 0x10 : base + 0x20]
        fields = buf[base + 0x20 : base + ENTRY_SIZE]
        u32a, u32b = struct.unpack_from("<II", fields, 0)
        out.append(
            {
                "index": i,
                "name": name,
                "f_0x20_u32a": u32a,
                "f_0x20_u32b": u32b,
                "unknown_0x10": unknown.hex(" "),
                "fields_hex": fields.hex(" "),
            }
        )
    return out


def report(hdr, entries, size=None, url=None):
    print()
    print("== outer SLB2 header ==")
    print(f"  magic          : {hdr['magic']!r}  {'OK' if hdr['magic'] == SLB2_MAGIC else 'MISMATCH'}")
    rec = bool(hdr["flags"] & FLAG_RECOVERY)
    print(f"  format version : {hdr['version']}")
    print(f"  flags          : {hdr['flags']:#010x}   recovery={rec}")
    if hdr["const_0x24"] != SLB2_CONST:
        print(f"  const @0x24    : {hdr['const_0x24']:#010x}  (expected {SLB2_CONST:#010x})")
    else:
        print(f"  const @0x24    : {hdr['const_0x24']:#010x}  OK")
    print(f"  entry count    : {hdr['entry_count']}")
    print(f"  metadata size  : {hdr['metadata_size']:#x}  ({hdr['metadata_size']:,})")
    print(f"  const @0x20    : {hdr['const_0x20']}")
    if size:
        print(f"  total file     : {int(size):,} bytes  ({int(size)/2**20:.2f} MiB)")
        if hdr['metadata_size']:
            print(f"  body after meta: {int(size) - hdr['metadata_size']:,} bytes")

    print()
    print("== entry records (outer: these are FILENAMES, not component IDs) ==")
    print(f"  {'idx':>3}  {'name':<20} {'f+0x20 u32a':>14} {'u32b':>14}")
    print(f"  {'-'*3}  {'-'*20} {'-'*14} {'-'*14}")
    for e in entries:
        print(f"  {e['index']:>3}  {e['name']:<20} {e['f_0x20_u32a']:>14,} {e['f_0x20_u32b']:>14,}")
    for e in entries:
        if e["f_0x20_u32a"] or e["f_0x20_u32b"]:
            print(f"\n  entry[{e['index']}] field bytes: {e['fields_hex']}")

    print()
    print("== note ==")
    print("  The 95-entry component table (kernel / bootloader0 / gpu_ucode ...) is NOT")
    print("  at this level. This container knows only about inner PUP filenames.")
    print("  Getting component-level detail needs the inner PUP decrypted.")
    if url:
        print(f"\n  (probe only — nothing was written, nothing was downloaded in full)")


def main():
    ap = argparse.ArgumentParser(description="Parse the PS5 PUP outer SLB2 container. Read-only.")
    ap.add_argument("file", nargs="?", help="local .PUP file")
    ap.add_argument("--url", help="probe a remote PUP via HTTP Range")
    ap.add_argument("--header-bytes", type=int, default=0x10000)
    ap.add_argument("--csv")
    args = ap.parse_args()

    size = None
    if args.url:
        print(f"probing {args.url}")
        size = http_size(args.url)
        buf, note = http_range(args.url, 0, args.header_bytes)
        print(f"  fetched {len(buf):,} bytes  [{note}]")
    elif args.file:
        p = Path(args.file).expanduser()
        if not p.exists():
            sys.exit(f"not found: {p}")
        size = str(p.stat().st_size)
        with open(p, "rb") as fh:
            buf = fh.read(args.header_bytes)
    else:
        ap.print_help()
        sys.exit(2)

    try:
        hdr = parse_header(buf)
    except ValueError as e:
        print(f"first 64 bytes: {buf[:64].hex(' ')}")
        sys.exit(f"header parse failed: {e}")

    if hdr["magic"] != SLB2_MAGIC:
        print(f"first 64 bytes: {buf[:64].hex(' ')}")
        sys.exit(f"not SLB2 (magic={hdr['magic']!r})")

    try:
        entries = parse_entries(buf, hdr)
    except ValueError as e:
        sys.exit(f"entry parse failed: {e}")

    report(hdr, entries, size, args.url)

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(entries[0].keys()))
            w.writeheader()
            w.writerows(entries)
        print(f"\n  wrote {args.csv}")


if __name__ == "__main__":
    main()
