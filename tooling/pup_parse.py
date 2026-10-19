#!/usr/bin/env python3
"""
pup_parse.py — Parse the PS5 PUP outer SLB2 container. READ-ONLY.

Layout confirmed 2026-10-19 against two independent third-party implementations
(`Whoisraeen/Raeen` crates/raeen-firmware/src/slb2.rs and
`TINYTINY11/Kura-a-PS5-Emulator` docs/RE-pup.md), then validated numerically
against live Sony firmware. See docs/03-outer-container-verified.md.

CONFIRMED OUTER FORMAT
  0x00  4    magic             "SLB2"
  0x04  4    version           3
  0x08  4    flags/blocksize   0x00010000 base; bit 24 (0x01000000) = recovery
  0x0C  4    entry count       1 = system/update, 2 = recovery
  0x10  8    (unknown)         0x2597C8 on current builds
  0x18  8    (zero)
  0x20  N*0x30  entry records

  Entry record (0x30 bytes):
    +0x00  4   block offset      in units of 0x200 (512) bytes
    +0x04  4   size              bytes
    +0x08  8   zero
    +0x10  0x20  name, NUL-padded ASCII

  Payload begins ~0x400 (a 32-byte digest sits at 0x200). Body is encrypted.

Every entry span is checked against the file size, so a wrong interpretation
shows up as arithmetic that does not close rather than as a plausible-looking
table. That check is what caught an earlier misreading of this very format.

Usage:
    python3 pup_parse.py <file.PUP>
    python3 pup_parse.py --url <https-url>      # probe header via Range
    python3 pup_parse.py --url <url> --json
"""

import argparse
import json
import struct
import sys
import urllib.request
from pathlib import Path

SLB2_MAGIC = b"SLB2"
FLAG_RECOVERY = 0x01000000
HEADER_SIZE = 0x20
ENTRY_SIZE = 0x30
BLOCK = 0x200
NAME_OFF = 0x10
NAME_LEN = 0x20


def http_range(url, start, length):
    req = urllib.request.Request(
        url,
        headers={"Range": f"bytes={start}-{start + length - 1}", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(), r.status


def http_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        v = r.headers.get("Content-Length")
        return int(v) if v else None


def parse(buf):
    if len(buf) < HEADER_SIZE or buf[:4] != SLB2_MAGIC:
        raise ValueError(f"not SLB2: {buf[:8]!r}")

    version = struct.unpack_from("<I", buf, 0x04)[0]
    flags = struct.unpack_from("<I", buf, 0x08)[0]
    count = struct.unpack_from("<I", buf, 0x0C)[0]
    unknown10 = struct.unpack_from("<Q", buf, 0x10)[0]

    if count > 64:
        raise ValueError(f"entry count {count} implausible for the outer wrapper")

    need = HEADER_SIZE + count * ENTRY_SIZE
    if len(buf) < need:
        raise ValueError(f"need {need} bytes, have {len(buf)} — raise --header-bytes")

    entries = []
    for i in range(count):
        base = HEADER_SIZE + i * ENTRY_SIZE
        block_off, size = struct.unpack_from("<II", buf, base)
        raw = buf[base + NAME_OFF : base + NAME_OFF + NAME_LEN]
        name = raw.split(b"\x00")[0].decode("ascii", "replace")
        entries.append(
            {
                "index": i,
                "name": name,
                "block_offset": block_off,
                "byte_offset": block_off * BLOCK,
                "size": size,
                "end": block_off * BLOCK + size,
            }
        )

    return {
        "version": version,
        "flags": flags,
        "recovery": bool(flags & FLAG_RECOVERY),
        "entry_count": count,
        "total_blocks": unknown10,
        "total_bytes_from_header": unknown10 * BLOCK,
        "entries": entries,
    }


def report(info, total):
    print()
    print("== outer SLB2 header ==")
    print(f"  version          : {info['version']}")
    print(f"  flags            : {info['flags']:#010x}   recovery={info['recovery']}")
    print(f"  entry count      : {info['entry_count']}")
    print(
        f"  total size @0x10 : {info['total_blocks']:,} blocks  "
        f"= {info['total_bytes_from_header']:,} bytes"
    )
    if total:
        print(f"  file size        : {total:,} bytes  ({total/2**20:.2f} MiB)")

    print()
    print("== entries ==")
    for e in info["entries"]:
        print(f"  [{e['index']}] {e['name']}")
        print(f"      block {e['block_offset']:>12,}  ->  byte {e['byte_offset']:>15,}")
        print(f"      size  {e['size']:>12,}  ({e['size']/2**20:.2f} MiB)   end {e['end']:,}")

    print()
    print("== arithmetic check ==")
    if total:
        hb = info["total_bytes_from_header"]
        verdict = "MATCHES file size" if hb == total else f"MISMATCH (file is {total:,})"
        print(f"  header @0x10*512  : {hb:,}   {verdict}")
    if not total:
        print("  (no total size — skipped)")
        return
    last_end = max(e["end"] for e in info["entries"])
    trailer = total - last_end
    print(f"  last entry ends at : {last_end:,}")
    print(f"  file size          : {total:,}")
    print(f"  trailer            : {trailer:,} bytes")
    if trailer < 0:
        print("  >> NEGATIVE trailer — layout interpretation is WRONG")
    elif trailer < 1 << 20:
        print("  >> closes within 1 MiB — layout confirmed")
    else:
        print("  >> large remainder — more entries than declared, or trailing padding")

    if len(info["entries"]) > 1:
        a, b = info["entries"][0], info["entries"][1]
        print(f"\n  gap between entry[0] and entry[1] : {b['byte_offset'] - a['end']:,} bytes")

    if info["recovery"] and info["entries"]:
        print(
            f"\n  entry[0].size = {info['entries'][0]['size']:,}"
            "  (expect the standalone system PUP to be this + a small trailer)"
        )


def main():
    ap = argparse.ArgumentParser(description="Parse the PS5 PUP outer SLB2 container. Read-only.")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--url")
    ap.add_argument("--header-bytes", type=int, default=0x2000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    total = None
    if args.url:
        print(f"probing {args.url}")
        total = http_size(args.url)
        buf, status = http_range(args.url, 0, args.header_bytes)
        print(f"  fetched {len(buf):,} bytes  [HTTP {status}]")
    elif args.file:
        p = Path(args.file).expanduser()
        if not p.exists():
            sys.exit(f"not found: {p}")
        total = p.stat().st_size
        with open(p, "rb") as fh:
            buf = fh.read(args.header_bytes)
    else:
        ap.print_help()
        sys.exit(2)

    try:
        info = parse(buf)
    except ValueError as e:
        print(f"first 64 bytes: {buf[:64].hex(' ')}")
        sys.exit(f"parse failed: {e}")

    if args.json:
        print(json.dumps({**info, "file_size": total}, indent=2))
        return

    report(info, total)


if __name__ == "__main__":
    main()
