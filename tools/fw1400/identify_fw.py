#!/usr/bin/env python3
"""Identify which PS5 firmware a kernel dump came from, and validate its layout.

The problem this solves: when a dump lands — from a leak, a friend, a lucky break —
you usually know neither the firmware nor the kernel data base. Every downstream
symbol (allproc, rootvnode, security_flags) is an offset *from that base*, so a
wrong base silently produces plausible-looking garbage.

This tool tries each known firmware's offset set, walks the process list, and reports
which profile produces a structurally coherent kernel. The process-list walk is the
strongest cheap oracle available: `allproc` holds a direct pointer to the first proc,
`proc + 0x00` is the next pointer, and `proc + 0xBC` is the pid (verified against
ps5-payload-dev/sdk `crt/kernel.c`, `kernel_get_proc`).

Usage
-----
    # dump described by a manifest (kernel_base + regions of file/offset/size)
    python3 identify_fw.py --manifest dump.json

    # flat image with a known base
    python3 identify_fw.py --image dump.bin --base 0xffffffff8a9c0000

    # data base known from a leak, firmware unknown
    python3 identify_fw.py --image dump.bin --base 0xffffffff8a9c0000 --data-base 0xffffffff8b680000

    # prove the detector works without a console
    python3 identify_fw.py --synthetic-test
"""

import argparse
import json
import os
import struct
import sys
from typing import Optional

PAGE = 0x1000

# proc layout — firmware-independent in the SDK
PROC_NEXT = 0x00     # TAILQ/LIST linkage: first field of struct proc
PROC_UCRED = 0x40
PROC_FD = 0x48
PROC_PID = 0xBC
PROC_VMSPACE = 0x200

# Per-firmware landmark offsets. `text_from_data` is subtracted from D to get text.
# Source: ps5-payload-dev/sdk crt/kernel.c (case blocks) and ps5-payload-dev/ftpsrv
# self-prospero.c. 14.00 and 14.10 share one case block upstream.
PROFILES = {
    "13.60": dict(text_from_data=0x0CC0000, allproc=0x28C9E80, security_flags=0x0D9C064,
                  rootvnode=0x314B510, bus_data_devices=0x2098228, pager_table=0xE03910),
    "14.00": dict(text_from_data=0x0CE0000, allproc=0x28D9EA0, security_flags=0x0DA4064,
                  rootvnode=0x315B510, bus_data_devices=0x20A8878, pager_table=0xE13E00),
    "14.10": dict(text_from_data=0x0CE0000, allproc=0x28D9EA0, security_flags=0x0DA4064,
                  rootvnode=0x315B510, bus_data_devices=0x20A8878, pager_table=0xE13E00),
}
SHARED = {"14.00", "14.10"}   # indistinguishable by these landmarks


class Image:
    """Sparse little-endian address space over one or more captured regions."""

    def __init__(self):
        self.regions = []          # (vaddr, bytes)

    def add(self, vaddr: int, data: bytes):
        self.regions.append((vaddr, data))

    @classmethod
    def from_manifest(cls, path):
        m = json.load(open(path))
        base = int(m["kernel_base"], 0)
        img = cls()
        root = os.path.dirname(os.path.abspath(path))
        # regions may be relative to the manifest, and offset is from kernel base
        for r in m["regions"]:
            f = r["file"]
            for cand in (os.path.join(root, f), f):
                if os.path.exists(cand):
                    f = cand
                    break
            img.add(base + int(r["offset"], 0),
                    open(f, "rb").read()[:int(r["size"], 0)])
        return img, base

    @classmethod
    def from_flat(cls, path, base):
        img = cls()
        img.add(base, open(path, "rb").read())
        return img, base

    def read(self, addr: int, n: int) -> Optional[bytes]:
        for v, data in self.regions:
            if v <= addr and addr + n <= v + len(data):
                o = addr - v
                return data[o:o + n]
        return None

    def u64(self, addr) -> Optional[int]:
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b else None

    def u32(self, addr) -> Optional[int]:
        b = self.read(addr, 4)
        return struct.unpack("<I", b)[0] if b else None


def canonical(x: Optional[int]) -> bool:
    return x is not None and (x >> 48) == 0xFFFF and x != 0xFFFFFFFFFFFFFFFF


def walk_procs(img: Image, D: int, off_allproc: int, limit: int = 256):
    """Walk allproc. Returns (procs, stop_reason)."""
    head = img.u64(D + off_allproc)
    if head is None:
        return [], "allproc not in captured regions"
    if head == 0:
        return [], "empty list"
    if not canonical(head):
        return [], f"head {head:#x} not canonical"

    procs, seen = [], set()
    addr = head
    while addr:
        if addr in seen:
            return procs, "cycle"
        seen.add(addr)
        pid = img.u32(addr + PROC_PID)
        if pid is None:
            return procs, f"proc {addr:#x} pid unreadable"
        procs.append({
            "addr": addr,
            "pid": pid,
            "ucred": img.u64(addr + PROC_UCRED),
            "fd": img.u64(addr + PROC_FD),
            "vmspace": img.u64(addr + PROC_VMSPACE),
        })
        if len(procs) >= limit:
            return procs, "limit"
        nxt = img.u64(addr + PROC_NEXT)
        if nxt is None:
            return procs, f"next of {addr:#x} unreadable"
        addr = nxt
    return procs, "term"


def score(img: Image, D: int, prof: dict):
    """Structural coherence of one (data-base, profile) hypothesis. 0.0 .. 1.0"""
    procs, reason = walk_procs(img, D, prof["allproc"])
    if not procs:
        return 0.0, reason, []

    checks = passed = 0
    for p in procs:
        checks += 4
        passed += (0 <= p["pid"] <= 0x100000)
        passed += canonical(p["ucred"])
        passed += canonical(p["fd"])
        passed += canonical(p["vmspace"])
    checks += 2
    passed += (reason == "term")
    passed += (len(procs) >= 3)

    # independent landmarks must at least be readable and plausible
    sf = img.u32(D + prof["security_flags"])
    rv = img.u64(D + prof["rootvnode"])
    checks += 2
    passed += (sf is not None and sf < 0x10000)
    passed += canonical(rv)

    return (passed / checks if checks else 0.0), reason, procs


def identify(img: Image, kernel_base: Optional[int], data_base: Optional[int]):
    results = []
    seen = {}
    for name, prof in PROFILES.items():
        key = tuple(sorted((k, v) for k, v in prof.items()))
        if key in seen:
            continue
        seen[key] = name
        d = data_base if data_base is not None else (kernel_base - prof["text_from_data"]
                                                    if kernel_base is not None else None)
        if d is None:
            continue
        s, reason, procs = score(img, d, prof)
        results.append({"profile": name, "data_base": d, "score": round(s, 3),
                        "walk": reason, "procs": len(procs)})
    share = [r for r in results if r["profile"] in SHARED]
    if len(share) == 2 and share[0]["score"] == share[1]["score"]:
        for r in results:
            if r["profile"] in SHARED:
                r["note"] = "indistinguishable from the other 14.x profile by these landmarks"
    return sorted(results, key=lambda r: -r["score"])


def scan(img: Image, kernel_base: int, span: int = 0x4000000):
    """Brute-force the data base on a page grid when nothing is known."""
    hits = []
    for delta in range(0, span, PAGE):
        d = kernel_base + delta
        s, reason, procs = score(img, d, PROFILES["14.00"])
        if s >= 0.9:
            hits.append({"data_base": d, "score": round(s, 3), "walk": reason,
                         "procs": len(procs)})
    return hits


# --------------------------------------------------------------------------- tests

def _synth(fw: str, data_base=0xFFFFFFFF8B680000, nproc=6, proc_pool=0x4000000):
    """Build a minimal synthetic image containing a coherent proc list."""
    prof = PROFILES[fw]
    img = Image()
    img.add(data_base - prof["text_from_data"], bytes(0x1000))

    marks = [prof["allproc"], prof["security_flags"], prof["rootvnode"], prof["bus_data_devices"]]
    lo = min(marks) & ~0xFFF
    hi = max(max(marks) + 0x1000, proc_pool + nproc * 0x1000)
    span = (hi - lo + PAGE - 1) & ~0xFFF
    data = bytearray(span)

    def put(off, val, size=8):
        o = off - lo
        assert 0 <= o < span, (hex(off), hex(lo), span)
        data[o:o + size] = int(val).to_bytes(size, "little")

    proc_offs = [proc_pool + i * 0x1000 for i in range(nproc)]
    put(prof["allproc"], data_base + proc_offs[0])
    for i, off in enumerate(proc_offs):
        put(off, data_base + proc_offs[i + 1] if i + 1 < nproc else 0)
        put(off + PROC_PID, 100 + i, 4)
        put(off + PROC_UCRED, data_base + 0x8000000 + i * 0x100)
        put(off + PROC_FD, data_base + 0x8100000 + i * 0x100)
        put(off + PROC_VMSPACE, data_base + 0x8200000 + i * 0x100)
    put(prof["security_flags"], 0x20, 4)
    put(prof["rootvnode"], data_base + 0x8300000)
    img.add(data_base + lo, bytes(data))
    return img, data_base


def synthetic_test():
    ok = True
    for fw in ("13.60", "14.00"):
        img, D = _synth(fw)
        res = identify(img, None, D)
        top = res[0]
        good = top["profile"] == fw and top["score"] >= 0.95
        ok &= good
        print(f"[{fw}] identified {top['profile']} score={top['score']} "
              f"procs={top['procs']} walk={top['walk']}  {'OK' if good else 'FAIL'}")

    # a wrong base must not score high
    img, D = _synth("14.00")
    bad = score(img, D + 0x10000, PROFILES["14.00"])[0]
    print(f"[negative] shifted base score={bad:.3f}  {'OK' if bad < 0.9 else 'FAIL'}")
    ok &= bad < 0.9

    # 13.60 profile must not claim a 14.00 image
    cross = [r for r in identify(img, None, D) if r["profile"] == "13.60"]
    if cross:
        print(f"[cross] 13.60 on a 14.00 image scored {cross[0]['score']:.3f}  "
              f"{'OK' if cross[0]['score'] < 0.9 else 'FAIL'}")
        ok &= cross[0]["score"] < 0.9
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", help="dump manifest json with kernel_base + regions")
    src.add_argument("--image", help="flat kernel image")
    src.add_argument("--synthetic-test", action="store_true")
    ap.add_argument("--base", type=lambda s: int(s, 0), help="kernel text base (flat image)")
    ap.add_argument("--data-base", type=lambda s: int(s, 0), help="known kernel data base")
    ap.add_argument("--scan", action="store_true", help="brute-force the data base on a page grid")
    ap.add_argument("--span", type=lambda s: int(s, 0), default=0x4000000)
    a = ap.parse_args()

    if a.synthetic_test:
        sys.exit(synthetic_test())

    if a.manifest:
        img, base = Image.from_manifest(a.manifest)
    else:
        if a.base is None:
            raise SystemExit("--base is required with --image")
        img, base = Image.from_flat(a.image, a.base)

    if a.scan and a.data_base is None:
        hits = scan(img, base, a.span)
        print(json.dumps({"candidate_data_bases": hits[:20], "tested_span": hex(a.span)}, indent=2))
        sys.exit(0 if hits else 1)

    res = identify(img, base, a.data_base)
    print(json.dumps({"kernel_base": hex(base) if base else None,
                      "regions": [(hex(v), len(d)) for v, d in img.regions],
                      "candidates": res}, indent=2))
    sys.exit(0 if res and res[0]["score"] >= 0.9 else 1)


if __name__ == "__main__":
    main()
