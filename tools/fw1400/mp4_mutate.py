#!/usr/bin/env python3
"""Mutate a fragmented MP4 at the box level, to fuzz Sony's proprietary MSE backend.

Why this target: the append *data* path was cleared (PSSourceBufferBackend::append copies), but
the backend still parses everything a page hands it. A valid fragmented MP4 produced a clean
`updateend` on retail 14.10, so the parser is reachable and functional; the parser itself lives
in Sony's SDK and is invisible in the OSS drop.

The mutations are deliberately structural rather than random, because a blind byte fuzz of an
unknown parser gives no feedback and every crash costs a console restart. Each case targets a
specific class of box-parser mistake:

  size 0            box runs to end of file (legal, and a classic off-by-one source)
  size 1            iger 64-bit largesize box, with largesize lying
  size < 8          impossible box, underflows the remaining-length arithmetic
  size > file       claims more bytes than exist
  type swap         declared type disagrees with the payload
  depth             deeply nested boxes, to exhaust a recursive parser
  counts            trun sample_count / tfhd / moov entry counts set absurdly high
  truncation        a cut inside moov or mdat, so a parser reads past the end of its box

One file per case, so a crash names exactly one input.

Usage:
    python3 tools/fw1400/mp4_mutate.py --base /path/to/fmp4.mp4 \
        --out tools/fw1400/guide_lab/www/mp4
"""

import argparse
import hashlib
import json
import os
import struct


def boxes(data: bytes, start: int = 0, end=None):
    """Yield (type, header_size, size, offset) for top-level or nested boxes."""
    end = len(data) if end is None else end
    p = start
    while p + 8 <= end:
        size, typ = struct.unpack(">I4s", data[p:p + 8])
        hdr = 8
        if size == 1 and p + 16 <= end:
            size = struct.unpack(">Q", data[p + 8:p + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - p
        if size < hdr or p + size > end:
            return
        yield typ.decode("latin-1"), hdr, size, p
        p += size


def patch(data: bytes, offset: int, blob: bytes) -> bytes:
    b = bytearray(data)
    b[offset:offset + len(blob)] = blob
    return bytes(b)


def find(data: bytes, wanted: bytes):
    for typ, hdr, size, off in boxes(data):
        if typ.encode("latin-1") == wanted:
            return hdr, size, off
    return None


def mutate(data: bytes):
    out = []

    ftyp = find(data, b"ftyp")
    moov = find(data, b"moov")
    moof = find(data, b"moof")
    mdat = find(data, b"mdat")

    # --- size field abuse on whichever container is handy ------------------------
    for target, label in ((ftyp, "ftyp"), (moov, "moov"), (moof, "moof"), (mdat, "mdat")):
        if not target:
            continue
        hdr, size, off = target

        out.append((f"{label}_size_zero",
                    f"{label} box size set to 0, so it extends to end of file",
                    patch(data, off, struct.pack(">I", 0))))

        out.append((f"{label}_size_one_lying_largesize",
                    f"{label} box claims size 1 (64-bit) and a largesize past EOF",
                    patch(data, off, struct.pack(">I4sQ", 1, label.encode(), 0xFFFFFFF0))))

        out.append((f"{label}_size_lt_header",
                    f"{label} box size 4, below the 8-byte header minimum",
                    patch(data, off, struct.pack(">I", 4))))

        out.append((f"{label}_size_beyond_file",
                    f"{label} box claims 0x7FFFF000 bytes",
                    patch(data, off, struct.pack(">I", 0x7FFFF000))))

        out.append((f"{label}_type_swap",
                    f"{label} box relabelled as 'free', so a strict parser skips its payload",
                    patch(data, off + 4, b"free")))

    # --- counts inside moov: mvhd timescale/duration, and entry tables -----------
    if moov:
        hdr, size, off = moov
        for typ, sub_hdr, sub_size, sub_off in boxes(data, off + hdr, off + size):
            if typ == "mvhd" and sub_size >= 24:
                # version 0: creation(4) modification(4) timescale(4) duration(4)
                body = sub_off + sub_hdr
                out.append(("mvhd_timescale_zero",
                            "mvhd timescale 0, so every time computation divides by zero",
                            patch(data, body + 8, struct.pack(">I", 0))))
                out.append(("mvhd_duration_huge",
                            "mvhd duration 0xFFFFFFFF with a small timescale",
                            patch(data, body + 12, struct.pack(">I", 0xFFFFFFFF))))
            if typ == "trak":
                out.append(("trak_type_swap",
                            "trak relabelled 'free' inside moov",
                            patch(data, sub_off + 4, b"free")))

    # --- moof payload: trun sample_count, tfhd flags ----------------------------
    if moof:
        hdr, size, off = moof
        for typ, sub_hdr, sub_size, sub_off in boxes(data, off + hdr, off + size):
            if typ != "traf":
                continue
            for t2, h2, s2, o2 in boxes(data, sub_off + sub_hdr, sub_off + sub_size):
                body = o2 + h2
                if t2 == "trun" and s2 >= 8:
                    out.append(("trun_sample_count_huge",
                                "trun sample_count 0x00FFFFFF against a tiny mdat",
                                patch(data, body + 4, struct.pack(">I", 0x00FFFFFF))))
                if t2 == "tfhd" and s2 >= 8:
                    out.append(("tfhd_flags_all",
                                "tfhd flags 0x00FFFFFF so every optional field is read",
                                patch(data, body + 1, b"\xff\xff\xff")))

    # --- structural: nesting depth and overlap ----------------------------------
    if moov:
        hdr, size, off = moov
        # wrap moov's payload in 64 nested 'free' boxes of 8 bytes each
        depth = 64
        nested = b"".join(struct.pack(">I4s", 8, b"free") for _ in range(depth))
        out.append(("moov_nesting_64",
                    "64 nested 8-byte boxes prepended inside moov",
                    patch(data, off + hdr, nested)))

    if moof and moov:
        out.append(("moof_alias_moov_offset",
                    "moof size field points at moov, so two containers share bytes",
                    patch(data, moof[2], struct.pack(">I", moov[1]))))

    # --- truncation inside the parse-relevant boxes ----------------------------
    n = len(data)
    for frac, name, note in (
        (0.15, "trunc_in_ftyp", "cut 15% in, inside the leading boxes"),
        (0.35, "trunc_in_moov", "cut 35% in, mid-moov"),
        (0.75, "trunc_in_moof", "cut 75% in, mid-moof"),
        (0.98, "trunc_in_mdat", "cut 98% in, near the end of mdat"),
    ):
        cut = max(16, int(n * frac))
        out.append((name, note, data[:cut]))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", default="tools/fw1400/guide_lab/www/mp4")
    args = ap.parse_args()

    data = open(args.base, "rb").read()
    os.makedirs(args.out, exist_ok=True)

    cases = [("valid", "unmodified fragmented MP4 (control)", data)] + list(mutate(data))

    manifest = {"base": os.path.basename(args.base), "base_bytes": len(data),
                "base_sha256": hashlib.sha256(data).hexdigest()[:16],
                "base_boxes": [t for t, _h, _s, _o in boxes(data)], "cases": []}

    for name, note, blob in cases:
        with open(os.path.join(args.out, name + ".mp4"), "wb") as f:
            f.write(blob)
        manifest["cases"].append({"name": name, "bytes": len(blob),
                                  "sha256": hashlib.sha256(blob).hexdigest()[:16], "note": note})
        print(f"{len(manifest['cases']):2d}. {name:32s} {len(blob):6d} B  {note}")

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n{len(cases)} cases -> {args.out}")
    print("base boxes: " + " ".join(manifest["base_boxes"]))


if __name__ == "__main__":
    main()
