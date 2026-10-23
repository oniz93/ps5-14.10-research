#!/usr/bin/env python3
"""Resolve and probe PS5 PUP URLs without downloading a gigabyte.

Sony's update list is a plain-HTTP XML document on a per-region host and it carries the
current image URL in full. Historic builds are constructible from the community firmware
list: the path is

    /update/ps5/official/<OBFUSCATED>/image/<YYYY_MMDD>/sys_<SHA256>/PS5UPDATE.PUP?dest=<region>

where `<OBFUSCATED>` is a single constant for every build and region. `?dest=` is
required — the same path without it 404s, which is the most likely reason a captured
path "doesn't work off-console".

Usage
-----
    python3 pup_url.py --current                 # what Sony serves right now
    python3 pup_url.py --build 14.00             # URL + header probe for a known build
    python3 pup_url.py --build 14.00 --raw       # also dump the first 1 KiB
    python3 pup_url.py --all                     # table across the known builds

Nothing here writes to a console and nothing downloads the image: every probe is a
single HTTP Range request of at most 1 MiB.
"""

import argparse
import json
import struct
import sys
import urllib.request

OBF = "tJMRE80IbXnE9YuG0jzTXgKEjIMoabr6"
HOST_CURRENT = "fus01.ps5.update.playstation.net"
HOST_IMAGE = "dus01.ps5.update.playstation.net"

# label, date, system sha256, system size, recovery sha256, recovery size
# Source: MewX/ps5-official-firmware-list. Verified against live Sony hosts 2026-10-23.
BUILDS = {
    "13.60": ("26.05-13.60.00.07-00.00.00.0.1", "2026_0717",
              "767a94eac034d33907a6ff57af05bc30ce057258ad1cf4b5ffb75d5e21112561", 1247471104,
              "e210451f789ebe46f55b13ae049894663b796163f7b094ab993218f1cb20aa97", 1404953088),
    "14.00": ("26.06-14.00.00.39-00.00.00.0.1", "2026_0909",
              "1eb4b18451e0f064fc23b5bd4c95cae7f6489f9ad1148b5dfb0d66452a108ebc", 1260600832,
              "7ec8dd8a6f518370422844d2c9d670316774d3dc9d52d78a676a3452ff63c556", 1418082816),
    "14.10": ("26.06-14.10.00.03-00.00.00.0.1", "2026_0928",
              "c17384946df6e5c85b2d72cbeee2057b165bf90279d9e2a86d527d0778cdaaf6", 1261408256,
              "9f3a0b8811c00ab52b092d2e9f0f13dd4515f018361ff38e4be43fd8c18b21de", 1418890240),
    "14.20": ("26.07-14.20.00.07-00.00.00.0.1", "2026_1014",
              "0f81be6fd890bc04925b3953e0862dfc2ead68edfdc33f31c3c60d0c267f68e4", 1266086912,
              "549cf0d5febeca28eb0716abf086639cb216b1400ead8059de13956d0d302762", 1423693312),
}

SYSTEM = "sys"      # 1 entry, flags 0x10000
RECOVERY = "rec"    # 2 entries, flags 0x1010000 (bit 24 set)


def url_for(build: str, region: str = "us", kind: str = SYSTEM) -> str:
    label, date, ssha, _ssz, rsha, _rsz = BUILDS[build.strip()]
    sha = rsha if kind == RECOVERY else ssha
    return (f"http://{HOST_IMAGE}/update/ps5/official/{OBF}/image/{date}/"
            f"{kind}_{sha}/PS5UPDATE.PUP?dest={region}")


def fetch(url: str, start: int = 0, length: int = 1024):
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{start + length - 1}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, dict(r.headers), r.read()


def parse_outer(buf: bytes):
    if buf[:4] != b"SLB2":
        return {"error": f"not SLB2: {buf[:8].hex()}"}
    ver, flags, count = struct.unpack_from("<III", buf, 4)
    blocks = struct.unpack_from("<Q", buf, 0x10)[0]
    out = {"magic": "SLB2", "version": ver, "flags": f"0x{flags:x}", "entries": count,
           "total_blocks": blocks, "total_bytes_claimed": blocks * 512, "entry": []}
    for i in range(min(count, 4)):
        o = 0x20 + i * 0x30
        blk, size = struct.unpack_from("<II", buf, o)
        name = buf[o + 0x10:o + 0x30].split(b"\x00")[0].decode("ascii", "replace")
        out["entry"].append({"index": i, "block": blk, "offset": hex(blk * 0x200),
                             "size": size, "name": name})
    return out


def parse_inner(buf: bytes):
    """The inner PUP's first 16 bytes are plaintext even though the rest is ciphertext."""
    h = buf[0x400:0x410]
    if len(h) < 16:
        return None
    magic, fmt, four, hsz, htab = struct.unpack("<IIIIH", h[:18] if len(h) >= 18 else h + b"\0\0")
    if magic != 0xEEF51454:
        return {"error": f"no EEF51454 at 0x400: {h.hex()}"}
    return {"magic": "0xEEF51454", "format": f"0x{fmt:08x}", "field8": four,
            "header_size": hsz, "hash_table_size": htab,
            "entries_implied": (hsz - 16) // 32}


def probe(build: str, region: str = "us", raw: bool = False, kind: str = SYSTEM):
    url = url_for(build, region, kind)
    status, headers, body = fetch(url, 0, 1104)
    res = {"build": build, "label": BUILDS[build][0], "kind": kind, "region": region, "url": url,
           "http": status, "content_length": headers.get("Content-Range", "").split("/")[-1],
           "accept_ranges": headers.get("Accept-Ranges"),
           "outer": parse_outer(body), "inner": parse_inner(body)}
    want = BUILDS[build][5] if kind == RECOVERY else BUILDS[build][3]
    res["size_matches_table"] = (str(want) == res["content_length"])
    if raw:
        res["raw_head_hex"] = body[:64].hex()
    return res


def current(region: str = "us"):
    url = (f"http://{HOST_CURRENT}/update/ps5/official/{OBF}/list/{region}/updatelist.xml")
    with urllib.request.urlopen(url, timeout=30) as r:
        xml = r.read().decode("utf-8", "replace")
    import re
    m = re.search(r'<system_pup[^>]*label="([^"]+)"[^>]*>.*?<image size="(\d+)">([^<]+)</image>',
                  xml, re.S)
    if not m:
        return {"error": "could not parse updatelist.xml", "bytes": len(xml)}
    return {"label": m.group(1), "size": int(m.group(2)), "url": m.group(3), "region": region}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--current", action="store_true")
    g.add_argument("--build", choices=sorted(BUILDS))
    g.add_argument("--all", action="store_true")
    ap.add_argument("--region", default="us")
    ap.add_argument("--kind", choices=[SYSTEM, RECOVERY], default=SYSTEM)
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()

    if a.current:
        print(json.dumps(current(a.region), indent=2))
    elif a.all:
        rows = []
        for b in BUILDS:
            try:
                r = probe(b, a.region, False, a.kind)
                rows.append({"build": b, "http": r["http"], "size": r["content_length"],
                             "size_matches": r["size_matches_table"],
                             "version": r["outer"].get("version"),
                             "flags": r["outer"].get("flags"),
                             "entries": r["outer"].get("entries"),
                             "inner": (r["inner"] or {}).get("magic")})
            except Exception as e:                       # noqa: BLE001
                rows.append({"build": b, "error": str(e)})
        print(json.dumps(rows, indent=2))
    else:
        print(json.dumps(probe(a.build, a.region, a.raw, a.kind), indent=2))


if __name__ == "__main__":
    main()
