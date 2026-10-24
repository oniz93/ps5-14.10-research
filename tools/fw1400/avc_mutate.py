#!/usr/bin/env python3
"""Mutate the H.264 bitstream inside a fragmented MP4, not the container.

Everything tried so far mutated box structure (sizes, types, counts, truncation). The demuxer
survived all of it, up to and including full playback. Untouched is the codec layer:

  * the avcC configuration record (SPS/PPS) inside moov/trak/mdia/minf/stbl/stsd/avc1, which is
    parsed at init time before any sample is decoded;
  * the NAL units inside mdat, length-prefixed per the avcC lengthSizeMinusOne field.

These reach a different parser from the box reader, and in many stacks a different process or
even hardware. A malformed SPS is also the classic way to make a decoder allocate by numbers it
was told but never validated.

Cases are deliberately structural rather than random noise: a bit flip in a length prefix gives a
different class of failure from a bit flip in a slice header.

Usage:
    python3 tools/fw1400/avc_mutate.py --base <fmp4.mp4> --out tools/fw1400/guide_lab/www/mp4b
"""

import argparse
import hashlib
import json
import os
import struct


def boxes(data, start=0, end=None):
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


def find_path(data, path):
    """Walk a box path like ['moov','trak','mdia','minf','stbl','stsd'] -> (hdr,size,off)."""
    start, end = 0, len(data)
    found = None
    for wanted in path:
        found = None
        for typ, hdr, size, off in boxes(data, start, end):
            if typ == wanted:
                found = (hdr, size, off)
                break
        if not found:
            return None
        start, end = found[2] + found[0], found[2] + found[1]
    return found


def patch(data, offset, blob):
    b = bytearray(data)
    b[offset:offset + len(blob)] = blob
    return bytes(b)


def locate_avcc(data):
    """Return (avcC_offset, avcC_body_offset, avcC_length, length_size, sps_list, pps_list)."""
    stsd = find_path(data, ["moov", "trak", "mdia", "minf", "stbl", "stsd"])
    if not stsd:
        return None
    s_hdr, s_size, s_off = stsd
    # stsd: version/flags(4) entry_count(4) then sample entries
    entry = s_off + s_hdr + 8
    for typ, hdr, size, off in boxes(data, entry, s_off + s_size):
        if typ not in ("avc1", "avc3"):
            continue
        # VisualSampleEntry is 78 bytes of fixed fields after the 8-byte box header
        inner = off + hdr + 78
        for t2, h2, s2, o2 in boxes(data, inner, off + size):
            if t2 == "avcC":
                body = o2 + h2
                cfg = data[body:o2 + s2]
                if len(cfg) < 7:
                    return None
                length_size = (cfg[4] & 0x03) + 1
                sps, pps = [], []
                p = 5
                nsps = cfg[p] & 0x1F
                p += 1
                for _ in range(nsps):
                    if p + 2 > len(cfg):
                        break
                    ln = struct.unpack(">H", cfg[p:p + 2])[0]
                    sps.append((body + p, ln, cfg[p + 2:p + 2 + ln]))
                    p += 2 + ln
                if p < len(cfg):
                    npps = cfg[p]
                    p += 1
                    for _ in range(npps):
                        if p + 2 > len(cfg):
                            break
                        ln = struct.unpack(">H", cfg[p:p + 2])[0]
                        pps.append((body + p, ln, cfg[p + 2:p + 2 + ln]))
                        p += 2 + ln
                return body, cfg, length_size, sps, pps, o2 + s2
    return None


def locate_mdat(data):
    for typ, hdr, size, off in boxes(data):
        if typ == "mdat":
            return off + hdr, off + size
    return None


def nal_units(data, start, end, length_size):
    """Yield (header_offset, payload_offset, nal_length) for length-prefixed NALs."""
    p = start
    while p + length_size + 1 <= end:
        ln = int.from_bytes(data[p:p + length_size], "big")
        if ln <= 0 or p + length_size + ln > end:
            return
        yield p, p + length_size, ln
        p += length_size + ln


def mutate(data):
    out = []
    info = locate_avcc(data)
    if not info:
        raise SystemExit("no avcC found - is this file AVC/H.264?")
    cfg_off, cfg, length_size, sps, pps, cfg_end = info

    # ---------------- avcC configuration record (parsed at init) ----------------
    out.append(("cfg_sps_count_31",
                "avcC numOfSequenceParameterSets=0x1F with only one SPS present",
                patch(data, cfg_off + 5, bytes([(cfg[5] & 0xE0) | 0x1F]))))

    out.append(("cfg_sps_len_zero",
                "avcC SPS length prefix 0, so the parser reads a zero-length SPS",
                patch(data, cfg_off + 6, struct.pack(">H", 0))))

    out.append(("cfg_sps_len_huge",
                "avcC SPS length prefix 0xFFFE against a 20-byte SPS",
                patch(data, cfg_off + 6, struct.pack(">H", 0xFFFE))))

    out.append(("cfg_pps_count_255",
                "avcC numOfPictureParameterSets=0xFF",
                patch(data, cfg_off + 6 + 2 + (len(sps[0][2]) if sps else 0), b"\xff")))

    if sps:
        sps_off = sps[0][0] + 2      # skip the 2-byte length prefix, land on the SPS body
        sps_len = sps[0][1]
        # SPS payload: [0]=profile, [1]=constraint flags, [2]=level, then exp-golomb
        yield_sps = [
            ("sps_profile_ff", "SPS profile_idc=0xFF, an undefined profile", sps_off, b"\xff"),
            ("sps_level_ff", "SPS level_idc=0xFF", sps_off + 2, b"\xff"),
            ("sps_zero_bytes", "SPS body replaced by zeroes, so every Exp-Golomb read decodes 0",
             sps_off, b"\x00" * min(16, max(1, sps_len - 1))),
            ("sps_ff_bytes", "SPS body replaced by 0xFF, the densest Exp-Golomb encoding",
             sps_off, b"\xff" * min(16, max(1, sps_len - 1))),
        ]
        for name, note, off, blob in yield_sps:
            out.append((name, note, patch(data, off, blob)))

    if pps:
        pps_off = pps[0][0] + 2
        out.append(("pps_zero_bytes",
                    "PPS body replaced by zeroes, so slice headers reference parameter set 0",
                    patch(data, pps_off, b"\x00" * min(8, max(1, pps[0][1] - 1)))))
        out.append(("pps_id_31",
                    "PPS pic_parameter_set_id forced to 31",
                    patch(data, pps_off, b"\xfc")))

    out.append(("cfg_lengthsize_3of4",
                "avcC lengthSizeMinusOne=2 (3-byte prefixes) while the stream uses 4",
                patch(data, cfg_off + 4, bytes([(cfg[4] & 0xFC) | 0x02]))))

    # ---------------- NAL units inside mdat ----------------
    md = locate_mdat(data)
    if md:
        m_start, m_end = md
        nals = list(nal_units(data, m_start, m_end, length_size))
        if nals:
            first = nals[0]
            hdr_off = first[1]
            length_field = first[0]

            out.append(("nal_len_zero",
                        "first NAL length prefix 0",
                        patch(data, length_field, (0).to_bytes(length_size, "big"))))
            out.append(("nal_len_huge",
                        "first NAL length prefix 0x7FFFFFFF",
                        patch(data, length_field, (0x7FFFFFFF).to_bytes(length_size, "big"))))
            out.append(("nal_forbidden_bit",
                        "first NAL header has forbidden_zero_bit set",
                        patch(data, hdr_off, bytes([data[hdr_off] | 0x80]))))
            out.append(("nal_type_zero",
                        "first NAL header type 0 (unspecified)",
                        patch(data, hdr_off, bytes([data[hdr_off] & 0xE0]))))
            out.append(("nal_type_31",
                        "first NAL header type 31 (reserved)",
                        patch(data, hdr_off, bytes([(data[hdr_off] & 0xE0) | 0x1F]))))
            out.append(("nal_zero_body",
                        "first NAL body replaced by zeroes",
                        patch(data, hdr_off + 1, b"\x00" * min(32, first[2] - 1))))
            out.append(("nal_ff_body",
                        "first NAL body replaced by 0xFF",
                        patch(data, hdr_off + 1, b"\xff" * min(32, first[2] - 1))))
            out.append(("nal_startcode_injected",
                        "an Annex-B start code injected into the first NAL body",
                        patch(data, hdr_off + 1, b"\x00\x00\x00\x01\x67")))

            # a length prefix that swallows the rest of mdat
            if len(nals) > 1:
                out.append(("nal_len_swallows_mdat",
                            "first NAL length set to the remainder of mdat",
                            patch(data, length_field,
                                  (m_end - hdr_off).to_bytes(length_size, "big"))))

            # strip every NAL but the first, leaving a truncated access unit
            last = nals[-1]
            cut = last[0]
            out.append(("au_truncated_at_last_nal",
                        "file cut immediately before the final NAL unit",
                        data[:cut]))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", default="tools/fw1400/guide_lab/www/mp4b")
    args = ap.parse_args()

    data = open(args.base, "rb").read()
    os.makedirs(args.out, exist_ok=True)

    info = locate_avcc(data)
    if info:
        _, cfg, length_size, sps, pps, _ = info
        print(f"avcC: lengthSize={length_size} sps={len(sps)} pps={len(pps)} "
              f"sps_bytes={[len(s[2]) for s in sps]}")

    cases = [("valid", "unmodified fragmented MP4 (control)", data)] + list(mutate(data))

    manifest = {"base": os.path.basename(args.base), "base_bytes": len(data),
                "base_sha256": hashlib.sha256(data).hexdigest()[:16], "cases": []}
    for name, note, blob in cases:
        with open(os.path.join(args.out, name + ".mp4"), "wb") as f:
            f.write(blob)
        manifest["cases"].append({"name": name, "bytes": len(blob),
                                  "sha256": hashlib.sha256(blob).hexdigest()[:16], "note": note})
        print(f"{len(manifest['cases']):2d}. {name:26s} {len(blob):6d} B  {note}")

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n{len(cases)} cases -> {args.out}")


if __name__ == "__main__":
    main()
