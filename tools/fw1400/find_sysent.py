#!/usr/bin/env python3
"""Locate a PS5 sysent table inside an arbitrary kernel image — no symbols, no base.

Why this matters: a dumped or leaked image arrives without a symbol table, and the
sysent RVA is firmware-specific. The table is nonetheless self-identifying at the
structural level:

  * 48-byte stride
  * `sy_narg` (u32 at +0x00) is small — never more than 8 on this kernel
  * the upper u32 of that word is zero
  * `sy_call` (u64 at +0x08) is always a canonical kernel pointer
  * the pointers cluster: they index an 8-byte `jmp rel32` thunk table, so hundreds of
    entries share one `nosys` target and the rest live in one narrow window

A random 32 KiB window fails the first two conditions almost immediately, so a linear
scan with early exit is cheap.

Usage
-----
    # find every candidate table in a flat image
    python3 find_sysent.py --image dump.bin --base 0xffffffff8a9c0000

    # restrict to a region of interest (offset from base, length)
    python3 find_sysent.py --image dump.bin --base 0xffffffff8a9c0000 \
        --at 0xe6d5c0 --len 0x10000

    # prove it works on the 13.60 capture shipped with the research repo
    python3 find_sysent.py --selftest
"""

import argparse
import os
import struct
import sys
from collections import Counter

STRIDE = 48
MAX_NARG = 8


def plausible_table(buf: bytes, off: int, count: int, max_bad: int = 5):
    """Score a candidate table at `off`. Returns a dict or None.

    Malformed tail entries are tolerated: the known 13.60 table has two (677, 678)
    whose `narg` field is junk while their pointers still look canonical, which is
    why a strict all-entries check finds nothing at all.
    """
    end = off + count * STRIDE
    if end > len(buf):
        return None

    def entry_ok(e):
        narg, pad = struct.unpack_from("<II", buf, e)
        p = struct.unpack_from("<Q", buf, e + 8)[0]
        return narg <= MAX_NARG and pad == 0 and (p >> 48) == 0xFFFF

    # cheap prefilter on the head of the table before scanning all 679 entries
    if sum(entry_ok(off + i * STRIDE) for i in range(16)) < 15:
        return None

    ptrs, bad = [], 0
    for i in range(count):
        e = off + i * STRIDE
        if not entry_ok(e):
            bad += 1
            if bad > max_bad:
                return None
            continue
        ptrs.append(struct.unpack_from("<Q", buf, e + 8)[0])

    c = Counter(ptrs)
    top, top_n = c.most_common(1)[0]
    if top_n < count * 0.10:
        return None
    live = [p for p in ptrs if p != top]
    if not live:
        return None
    cluster = max(live) - min(live)
    return {
        "offset": off,
        "count": count,
        "malformed_entries": bad,
        "distinct": len(c),
        "nosys_share": round(top_n / count, 3),
        "nosys_target": top,
        "live_target_span": cluster,
        "score": round(top_n / count + min(len(c) / count, 1.0), 3),
    }


def scan(buf: bytes, count: int, limit: int = 8):
    hits = []
    for off in range(0, max(0, len(buf) - count * STRIDE) + 1, 8):
        r = plausible_table(buf, off, count)
        if r:
            hits.append(r)
    hits.sort(key=lambda r: (-r["score"], r["offset"]))

    # A table shifted by whole entries still parses (the structure is periodic at the
    # 48-byte stride), so report clusters rather than pretending to a unique answer.
    clusters = []
    for h in hits:
        if clusters and h["offset"] - clusters[-1][-1]["offset"] <= 0x100:
            clusters[-1].append(h)
        else:
            clusters.append([h])
    out = []
    for c in clusters:
        best = c[0]
        best = dict(best)
        best["offsets"] = [x["offset"] for x in c]
        out.append(best)
    out.sort(key=lambda r: (-r["score"], len(r["offsets"])))
    return out[:limit]


def selftest():
    here = os.path.dirname(os.path.abspath(__file__))
    dumps = os.path.join(here, "..", "..", "research", "PS5-14.10-Research", "docs", "dumps_13.60")
    area = os.path.join(dumps, "sysent_area.bin")
    raw = os.path.join(dumps, "sysent_raw.bin")
    if not (os.path.exists(area) and os.path.exists(raw)):
        raise SystemExit("13.60 capture not found")

    buf = open(area, "rb").read()
    table = open(raw, "rb").read()
    count = len(table) // STRIDE

    # 1. the scanner must find the table at the offset it actually occupies (0x1000)
    hits = scan(buf, count)
    found_at = False
    print(f"scanned {len(buf):#x} bytes, {len(hits)} cluster(s)")
    for h in hits[:4]:
        print(f"  cluster at {[hex(o) for o in h['offsets']]} distinct={h['distinct']} "
              f"nosys={h['nosys_share']} span={h['live_target_span']:#x}")
    if hits:
        for o in hits[0]["offsets"]:
            if buf[o:o + len(table)] == table:
                found_at = True
                break
    print(f"the known table is byte-identical to a reported candidate: "
          f"{'OK' if found_at else 'FAIL'}")

    # 2. random data must not produce candidates
    import random
    rnd = bytes(random.getrandbits(8) for _ in range(len(buf)))
    fp = scan(rnd, count)
    print(f"false positives on random data: {len(fp)}  {'OK' if not fp else 'FAIL'}")

    return 0 if found_at and not fp else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image")
    ap.add_argument("--base", type=lambda s: int(s, 0))
    ap.add_argument("--at", type=lambda s: int(s, 0), help="region start offset from base")
    ap.add_argument("--len", type=lambda s: int(s, 0), help="region length")
    ap.add_argument("--count", type=int, default=679, help="assumed entry count")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        sys.exit(selftest())
    if not a.image or a.base is None:
        raise SystemExit("--image and --base are required (or use --selftest)")

    buf = open(a.image, "rb").read()
    start = a.at or 0
    length = a.len or (len(buf) - start)
    win = buf[start:start + length]

    hits = scan(win, a.count)
    for h in hits:
        h["va"] = a.base + start + h["offset"]
        h["off_from_base"] = start + h["offset"]
        h["offset"] = h["off_from_base"]
        h["va"] = hex(h["va"])
        h["off_from_base"] = hex(h["off_from_base"])
        h["nosys_target"] = hex(h["nosys_target"])
        h["live_target_span"] = hex(h["live_target_span"])

    import json
    print(json.dumps({"assumed_entries": a.count, "candidates": hits}, indent=2))
    sys.exit(0 if hits else 1)


if __name__ == "__main__":
    main()
