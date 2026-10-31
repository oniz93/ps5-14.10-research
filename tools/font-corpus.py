#!/usr/bin/env python3
"""Generate the font-parser corpus used by docs/99.

Every arm is a font file a page can fetch over HTTP and hand to WebKit as
`@font-face { src: url(...) }`.  The arms are structural mutations of one real
font (Liberation Sans), one mutation each, plus real colour/bitmap faces, plus
WOFF1 encodings of the base and a synthetic GSUB table for the vertical path.

Pure stdlib on purpose: the oracle container has no fontTools.

    python3 tools/font-corpus.py --base LiberationSans-Regular.ttf --out f \
            --extra twemoji=/usr/share/fonts/twemoji/Twemoji.ttf ...

writes <out>/<id>.<ext> for every arm and <out>/manifest.json:

    {"base": ..., "base_md5": ..., "arms": [{"id","file","kind","desc"}]}
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys
import zlib


def rd16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def rd32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def wr16(b, o, v):
    struct.pack_into(">H", b, o, v & 0xFFFF)


def wr32(b, o, v):
    struct.pack_into(">I", b, o, v & 0xFFFFFFFF)


class Sfnt:
    def __init__(self, data):
        self.data = bytes(data)
        self.version = self.data[0:4]
        self.n = rd16(self.data, 4)
        self.dir = []          # list of dicts, in directory order
        for i in range(self.n):
            o = 12 + 16 * i
            if o + 16 > len(self.data):
                break
            self.dir.append(dict(
                i=i, at=o, tag=self.data[o:o + 4],
                csum=rd32(self.data, o + 4), off=rd32(self.data, o + 8),
                ln=rd32(self.data, o + 12)))

    def entry(self, tag):
        for e in self.dir:
            if e["tag"] == tag:
                return e
        return None

    def table(self, tag):
        e = self.entry(tag)
        if not e:
            return None
        return self.data[e["off"]:e["off"] + e["ln"]]


def patched(data, tag, field, value):
    """Copy of `data` with one table-directory field of one table replaced."""
    b = bytearray(data)
    s = Sfnt(b)
    e = s.entry(tag)
    if not e:
        return None
    off = e["at"] + {"csum": 4, "off": 8, "ln": 12}[field]
    wr32(b, off, value)
    return bytes(b)


def patched_table(data, tag, rel, fmt, value, rel_from_table=True):
    """Copy with a field inside a table's bytes replaced."""
    b = bytearray(data)
    s = Sfnt(b)
    e = s.entry(tag)
    if not e:
        return None
    at = e["off"] + rel
    if at + struct.calcsize(fmt) > len(b):
        return None
    if fmt == ">H":
        wr16(b, at, value)
    elif fmt == ">h":
        struct.pack_into(">h", b, at, value)
    else:
        wr32(b, at, value)
    return bytes(b)


def rebuild(font, extra):
    """Rebuild the sfnt with `extra` tables (dict tag->bytes) added/replaced.

    Directory is re-sorted, offsets recomputed, checksums of untouched tables
    preserved (FreeType does not verify them)."""
    s = Sfnt(font)
    entries = []
    for e in s.dir:
        entries.append([e["tag"], e["csum"], s.data[e["off"]:e["off"] + e["ln"]]])
    for tag, data in extra.items():
        entries = [x for x in entries if x[0] != tag]
        entries.append([tag, 0, data])
    entries.sort(key=lambda x: x[0])
    n = len(entries)
    es = 1 << (n.bit_length() - 1) if n else 1
    sr = es * 16
    out = bytearray(s.version)
    out += struct.pack(">HHHH", n, sr, int(math.log2(es)) if es else 0,
                       n * 16 - sr)
    off = 12 + 16 * n
    body = bytearray()
    for tag, csum, data in entries:
        out += tag + struct.pack(">III", csum, off, len(data))
        pad = (-len(data)) % 4
        body += data + b"\0" * pad
        off += len(data) + pad
    return bytes(out + body)


def make_woff(font):
    """WOFF 1.0 wrapper: what CachedFont::convertWOFFToSfnt consumes."""
    s = Sfnt(font)
    entries = [(e["tag"], e["csum"], s.data[e["off"]:e["off"] + e["ln"]])
               for e in s.dir]
    hdr_len, dir_len = 44, 20 * len(entries)
    total_sfnt = 12 + 16 * len(entries) + sum((len(d) + 3) // 4 * 4
                                              for _, _, d in entries)
    off = hdr_len + dir_len
    dirbytes, databytes = b"", b""
    for tag, csum, data in entries:
        comp = zlib.compress(data, 9)
        if len(comp) >= len(data):
            comp = data
        clen = len(comp)
        dirbytes += tag + struct.pack(">IIII", off, clen, len(data), csum)
        databytes += comp + b"\0" * ((-clen) % 4)
        off += clen + ((-clen) % 4)
    total = hdr_len + dir_len + len(databytes)
    hdr = b"wOFF" + s.version + struct.pack(
        ">IHHIHHIIIII", total, len(entries), 0, total_sfnt, 1, 0,
        0, 0, 0, 0, 0)
    return hdr + dirbytes + databytes


def woff_entry_offset(woff, i):
    return 44 + 20 * i


def build_gsub(count_to, subs, ranges):
    """Assemble a GSUB with one 'vert' feature -> lookupType 1 -> SingleSubst2.

    `ranges` are (start, end, startCoverageIndex) for a Coverage format 2."""
    hdr = 10                                            # version + 3 offsets
    off_script = hdr
    script = struct.pack(">H", 0)                       # scriptCount = 0
    off_featlist = off_script + len(script)
    off_feature = off_featlist + 2 + 6                  # count + one record
    off_lookuplist = off_feature + 6
    off_lookup = off_lookuplist + 4
    off_sub = off_lookup + 8
    off_cov = off_sub + 6 + 2 * count_to
    featlist = struct.pack(">H", 1) + b"vert" + struct.pack(
        ">H", off_feature - off_featlist)
    feature = struct.pack(">HHH", 0, 1, 0)              # params, count, index
    lookuplist = struct.pack(">HH", 1, off_lookup - off_lookuplist)
    lookup = struct.pack(">HHHH", 1, 0, 1, off_sub - off_lookup)
    sub = struct.pack(">HHH", 2, off_cov - off_sub, count_to)
    sub += b"".join(struct.pack(">H", s) for s in subs)
    cov = struct.pack(">HH", 2, len(ranges))
    cov += b"".join(struct.pack(">HHH", a, b, c) for a, b, c in ranges)
    head = struct.pack(">IHHH", 0x00010000, off_script, off_featlist,
                       off_lookuplist)
    assert len(head) == hdr
    return head + script + featlist + feature + lookuplist + lookup + sub + cov


def build_vhea(n_long, advance):
    """vhea + vmtx with one long metric of `advance` font units."""
    vhea = struct.pack(
        ">I" + "h" * 10 + "8s" + "hh", 0x00010000,
        1000, -200, 0, advance, 0, 0, 0, 0, 1, 0,      # metrics + caret
        b"\0" * 8,                                      # reserved[4]
        0, n_long)                                      # format, numLongVerMetrics
    vmtx = struct.pack(">Hh", advance, 0)
    return vhea, vmtx


def glyph_offsets(font):
    """(offsets, lengths, long_format) for the glyf/loca pair; None if absent."""
    s = Sfnt(font)
    head, maxp = s.table(b"head"), s.table(b"maxp")
    loca, glyf = s.table(b"loca"), s.table(b"glyf")
    if not (head and maxp and loca and glyf) or len(head) < 54:
        return None
    fmt = rd16(head, 50)
    ng = rd16(maxp, 4)
    offs = []
    if fmt == 0:
        for i in range(min(ng + 1, len(loca) // 2)):
            offs.append(rd16(loca, 2 * i) * 2)
    else:
        for i in range(min(ng + 1, len(loca) // 4)):
            offs.append(rd32(loca, 4 * i))
    lens = [max(0, offs[i + 1] - offs[i]) for i in range(len(offs) - 1)]
    return offs, lens, fmt == 1, len(glyf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--extra", action="append", default=[],
                    help="tag=/path/to/font.ttf, a real face served unchanged")
    ap.add_argument("--cjk-base", default=None,
                    help="a font with Han glyphs and vhea/vmtx, for the vertical arms")
    args = ap.parse_args()

    base = open(args.base, "rb").read()
    s = Sfnt(base)
    arms = []

    def add(aid, kind, data, desc, ext="ttf"):
        aid = "".join(c if (c.isalnum() or c in "-_") else "_" for c in aid)
        arms.append(dict(id=aid, file=f"{aid}.{ext}", kind=kind, desc=desc,
                         data=data))

    add("ctl", "control", base, "unmodified Liberation Sans")

    # ---- TR: truncation of the file at table boundaries ------------------
    for n in (1, 2, 3, 4, 8, 11, 12, 13, 16, 17, 27, 28, 29, 44, 45):
        add(f"TR{n:03d}", "trunc-file", base[:n],
            f"file cut to {n} bytes (directory)")
    for e in s.dir:
        tag = e["tag"].decode("latin1")
        for delta, lab, what in ((0, "a", "table start"), (1, "b", "+1 byte"),
                                 (e["ln"] // 2, "c", "half"),
                                 (max(e["ln"] - 1, 0), "d", "last byte")):
            n = e["off"] + delta
            if 0 < n < len(base):
                add(f"TR-{tag.strip() or 'sp'}-{lab}", "trunc-table", base[:n],
                    f"file cut inside {tag} at {what} ({n} B)")

    # ---- DR: table directory ---------------------------------------------
    for n, lab in ((0, "0"), (1, "1"), (0x0FFF, "4095"), (0x1000, "4096")):
        b = bytearray(base)
        wr16(b, 4, n)
        add(f"DR-numt{lab}", "dir", bytes(b), f"numTables = {n}")
    for tag in (b"glyf", b"cmap", b"name", b"GSUB"):
        if not s.entry(tag):
            continue
        t = tag.decode("latin1").strip()
        for val, lab, what in ((0xFFFFFFFF, "lenmax", "length 0xFFFFFFFF"),
                               (0, "len0", "length 0"),
                               (0xFFFFFF00, "offmax", "offset 0xFFFFFF00"),
                               (len(base) - 8, "offend",
                                f"offset {len(base)-8} length 0x1000")):
            if lab.startswith("off"):
                b = patched(base, tag, "off", val)
                if lab == "offend":
                    b = patched(b, tag, "ln", 0x1000)
            else:
                b = patched(base, tag, "ln", val)
            add(f"DR-{t}-{lab}", "dir", b, f"{tag.decode()} {what}")
    for ver, lab in ((b"OTTO", "otto"), (b"\0\0\0\0", "zero"),
                     (b"true", "true"), (b"\xff\xff\xff\xff", "ffff")):
        b = bytearray(base)
        b[0:4] = ver
        add(f"DR-ver-{lab}", "dir", bytes(b), f"sfntVersion = {ver!r}")
    b = bytearray(base)
    for e in s.dir:
        wr32(b, e["at"] + 4, 0xFFFFFFFF)
    add("DR-csum-all", "dir", bytes(b), "every table checksum 0xFFFFFFFF")
    other = next((e["tag"] for e in s.dir
                  if e["tag"] not in (b"head", b"hhea", b"maxp")), None)
    if other:
        b = bytearray(base)
        e = s.entry(other)
        b[e["at"]:e["at"] + 4] = b"head"
        add("DR-dup-head", "dir", bytes(b),
            f"duplicate 'head' entry (second is {other.decode()})")

    # ---- HD: head --------------------------------------------------------
    head = s.table(b"head")
    if head and len(head) >= 54:
        fmt = rd16(head, 50)
        upem = rd16(head, 18)
        for val, lab, what in ((2, "loc2", "indexToLocFormat 2"),
                               (3, "loc3", "indexToLocFormat 3"),
                               (1 - fmt, "locswap",
                                f"indexToLocFormat {1-fmt} on a {fmt} loca"),
                               (0, "upem0", "unitsPerEm 0"),
                               (1, "upem1", "unitsPerEm 1"),
                               (0xFFFF, "upemmax", "unitsPerEm 0xFFFF")):
            b = patched_table(base, b"head", 50 if lab.startswith("loc") else 18,
                              ">H", val)
            add(f"HD-{lab}", "head", b, what)
        b = patched_table(base, b"head", 12, ">I", 0)
        add("HD-magic", "head", b, "magicNumber 0")
        for n in (53, 40, 0):
            add(f"HD-len{n}", "head", patched(base, b"head", "ln", n),
                f"head directory length {n}")

    # ---- MX: maxp --------------------------------------------------------
    maxp = s.table(b"maxp")
    if maxp and len(maxp) >= 6:
        real_ng = rd16(maxp, 4)
        for val, lab in ((0, "numg0"), (1, "numg1"), (0xFFFF, "numgmax"),
                         (real_ng + 1, "numgplus1")):
            add(f"MX-{lab}", "maxp", patched_table(base, b"maxp", 4, ">H", val),
                f"maxp.numGlyphs {real_ng} -> {val}")
        add("MX-ver05", "maxp", patched_table(base, b"maxp", 0, ">I", 0x00005000),
            "maxp version 0.5 (CFF flavour) on a glyf font")
        add("MX-len6", "maxp", patched(base, b"maxp", "ln", 6),
            "maxp directory length 6")

    # ---- LC: loca --------------------------------------------------------
    gl = glyph_offsets(base)
    if gl:
        offs, lens, longf, glyflen = gl
        ng = len(offs) - 1
        unit = 4 if longf else 2
        b = bytearray(base)
        loca = s.entry(b"loca")
        for i in range(len(offs)):
            v = 0xFFFF if longf else 0x7FFF
            if longf:
                wr32(b, loca["off"] + 4 * i, v)
            else:
                wr16(b, loca["off"] + 2 * i, v)
        add("LC-allff", "loca", bytes(b), "every loca entry at the maximum")
        b = bytearray(base)
        for i in range(len(offs)):
            v = 0 if i else (glyflen if longf else min(glyflen // 2, 0xFFFF))
            if longf:
                wr32(b, loca["off"] + 4 * i, v)
            else:
                wr16(b, loca["off"] + 2 * i, v)
        add("LC-desc", "loca", bytes(b), "loca descending: first entry = end of glyf, rest 0")
        b = bytearray(base)
        for i in range(len(offs)):
            if longf:
                wr32(b, loca["off"] + 4 * i, 0)
            else:
                wr16(b, loca["off"] + 2 * i, 0)
        add("LC-zero", "loca", bytes(b), "every loca entry 0 (all glyphs empty)")
        for n in (4, 2, 0):
            if n < loca["ln"]:
                add(f"LC-len{n}", "loca", patched(base, b"loca", "ln", n),
                    f"loca directory length {n} of {loca['ln']}")

    # ---- GL: glyf --------------------------------------------------------
    if gl and lens and lens[0] > 0:
        goff, glen0 = offs[0], lens[0]
        glyf_e = s.entry(b"glyf")
        if glen0 >= 10:
            b = bytearray(base)
            wr16(b, glyf_e["off"] + goff, 0x7FFF)
            add("GL-contoursmax", "glyf", bytes(b),
                "glyph 0 numberOfContours = 0x7FFF")
            b = bytearray(base)
            wr16(b, glyf_e["off"] + goff + 10, 0x7FFF)
            add("GL-endptmax", "glyf", bytes(b),
                "glyph 0 first contour endPt = 0x7FFF")
            # composite that references itself (numberOfContours = -1)
            comp = struct.pack(">HhHHhh", 0xFFFF, 0, 0x0021, 0, 0, 0)
            b = bytearray(base)
            wr16(b, glyf_e["off"] + goff, 0xFFFF)      # -1
            wr16(b, glyf_e["off"] + goff + 2, 0)       # xMin
            wr16(b, glyf_e["off"] + goff + 4, 0)       # yMin
            wr16(b, glyf_e["off"] + goff + 6, 0)       # xMax
            wr16(b, glyf_e["off"] + goff + 8, 0)       # yMax
            b[glyf_e["off"] + goff + 10:glyf_e["off"] + goff + 20] = comp[:10]
            add("GL-comp-self", "glyf", bytes(b),
                "glyph 0 replaced by a composite that references glyph 0")
        for n in (1, 4, 12):
            if n < glyf_e["ln"]:
                add(f"GL-len{n}", "glyf", patched(base, b"glyf", "ln", n),
                    f"glyf directory length {n} of {glyf_e['ln']}")

    # ---- HM: hhea/hmtx ---------------------------------------------------
    hhea = s.table(b"hhea")
    if hhea and len(hhea) >= 36:
        nh = rd16(hhea, 34)
        for val, lab in ((0xFFFF, "hmetricsmax"), (0, "hmetrics0"),
                         (nh + 1, "hmetricsplus1")):
            add(f"HM-{lab}", "hhea",
                patched_table(base, b"hhea", 34, ">H", val),
                f"hhea.numberOfHMetrics {nh} -> {val}")
        for n in (20, 34, 0):
            add(f"HM-hhea-len{n}", "hhea", patched(base, b"hhea", "ln", n),
                f"hhea directory length {n} of {hhea and len(hhea)}")
    if s.entry(b"hmtx"):
        hl = s.entry(b"hmtx")["ln"]
        for n in (2, 4, 0):
            if n < hl:
                add(f"HM-hmtx-len{n}", "hmtx", patched(base, b"hmtx", "ln", n),
                    f"hmtx directory length {n} of {hl}")

    # ---- CM: cmap --------------------------------------------------------
    cmap = s.table(b"cmap")
    if cmap and len(cmap) >= 4:
        nsub = rd16(cmap, 2)
        subs = []
        for i in range(min(nsub, 8)):
            o = 4 + 8 * i                       # platformID, encodingID, offset
            if o + 8 <= len(cmap):
                so = rd32(cmap, o + 4)
                if so + 4 <= len(cmap):
                    subs.append((rd16(cmap, so), so))   # (subtable format, offset)
        fmt4 = next((so for f, so in subs if f == 4), None)
        if fmt4 is not None:
            so = fmt4
            segx2 = rd16(cmap, so + 6)
            for val, lab in ((0xFFFE, "segmax"), (0, "seg0"), (2, "seg1")):
                add(f"CM-{lab}", "cmap",
                    patched_table(base, b"cmap", so + 6, ">H", val),
                    f"cmap fmt4 segCountX2 {segx2} -> {val}")
            # idRangeOffset of the first segment: at so+14 + segCount*2 + 2
            seg = segx2 // 2
            iro_at = so + 14 + seg * 2 + 2
            if iro_at + 2 <= len(cmap):
                add("CM-idrange", "cmap",
                    patched_table(base, b"cmap", iro_at, ">H", 0xFFF0),
                    "cmap fmt4 endCode[0] idRangeOffset 0xFFF0")
            if so + 2 <= len(cmap):
                add("CM-sub-len4", "cmap",
                    patched_table(base, b"cmap", so + 2, ">H", 4),
                    "cmap fmt4 subtable length field = 4")
                add("CM-fmt12", "cmap",
                    patched_table(base, b"cmap", so, ">H", 12),
                    "cmap subtable format 4 -> 12")
                add("CM-fmt0", "cmap",
                    patched_table(base, b"cmap", so, ">H", 0),
                    "cmap subtable format 4 -> 0")
        add("CM-len4", "cmap", patched(base, b"cmap", "ln", 4),
            "cmap directory length 4")

    # ---- NM / PO: name, post --------------------------------------------
    name = s.table(b"name")
    if name and len(name) >= 6:
        add("NM-countmax", "name", patched_table(base, b"name", 2, ">H", 0xFFFF),
            "name count 0xFFFF")
        add("NM-len6", "name", patched(base, b"name", "ln", 6),
            "name directory length 6")
        if len(name) >= 18:
            add("NM-strlenmax", "name",
                patched_table(base, b"name", 16, ">H", 0xFFFF),
                "first name record stringLength 0xFFFF")
    post = s.table(b"post")
    if post and len(post) >= 32:
        add("PO-ver2", "post", patched_table(base, b"post", 0, ">I", 0x00020000),
            "post version 2.0 on a version-3 table")
        add("PO-len32", "post", patched(base, b"post", "ln", 32),
            "post directory length 32")

    # ---- WO: WOFF 1.0 (WebKit's zlib decoder in this build) --------------
    woff = make_woff(base)
    add("WO-ok", "woff", woff, "the base font encoded as WOFF 1.0", ext="woff")
    for lab, apply in (
            ("len-1", lambda b: wr32(b, 8, len(b) - 1)),
            ("total12", lambda b: wr32(b, 16, 12)),
            ("total64k", lambda b: wr32(b, 16, 65536)),
            ("origmax", lambda b: wr32(b, woff_entry_offset(woff, 0) + 12, 0x7FFFFFFF)),
            ("offmax", lambda b: wr32(b, woff_entry_offset(woff, 0) + 4, 0xFFFFFFF0)),
            ("compgtorig", lambda b: wr32(b, woff_entry_offset(woff, 0) + 8, 0x7FFFFFF0)),
    ):
        b = bytearray(woff)
        apply(b)
        add(f"WO-{lab}", "woff", bytes(b), f"WOFF header/directory: {lab}", ext="woff")
    b = bytearray(woff[:-20])
    wr32(b, 8, len(b))
    add("WO-trunc20", "woff", bytes(b), "WOFF truncated by 20 bytes", ext="woff")

    # ---- GS: GSUB vertical substitution (ENABLE(OPENTYPE_VERTICAL)) ------
    # On the Latin base these arms can never be reached: vertical Latin runs use
    # Font::verticalRightOrientationFont() (OrientationFallback::Yes), which by
    # construction has no OpenTypeVerticalData.  They are kept as the
    # reachability negative control next to the CJ arms below.
    gs_ctl = build_gsub(3, [5, 6, 7], [(10, 12, 0)])
    add("GS-ctl", "gsub", rebuild(base, {b"GSUB": gs_ctl}),
        "GSUB vert, coverage fmt2 range 10..12 with 3 substitutes (well formed)")
    gs_wrap = build_gsub(1, [5], [(0x8000, 0xFFFF, 0)])
    add("GS-wrap", "gsub", rebuild(base, {b"GSUB": gs_wrap}),
        "GSUB vert, coverage range start 0x8000 end 0xFFFF (end+1 wraps to 0)")
    gs_desc = build_gsub(1, [5], [(10, 5, 0)])
    add("GS-desc", "gsub", rebuild(base, {b"GSUB": gs_desc}),
        "GSUB vert, coverage range start 10 end 5 (descending, end+1 < start)")

    # ---- CJ: a font with Han glyphs and real vhea/vmtx --------------------
    # Upright ideographs are the only text that calls
    # OpenTypeVerticalData::advanceHeight(), so this is the only base on which
    # the vertical path (and therefore the GSUB parser inside it) is reachable.
    if args.cjk_base:
        cb = open(args.cjk_base, "rb").read()
        add("CJ-ctl", "vertical", cb,
            f"{os.path.basename(args.cjk_base)} unmodified (Han glyphs, real vhea/vmtx)")
        add("CJ-rebuild", "vertical", rebuild(cb, {}),
            "the same font rebuilt through rebuild() with no extra table")
        vhea, vmtx = build_vhea(1, 8000)
        add("CJ-witness", "vertical", rebuild(cb, {b"vhea": vhea, b"vmtx": vmtx}),
            "vhea/vmtx replaced: one long metric, advanceHeight 8000 units")
        add("CJ-vmtx0", "vertical",
            rebuild(cb, {b"vhea": build_vhea(1, 0)[0], b"vmtx": build_vhea(1, 0)[1]}),
            "vhea/vmtx replaced: advanceHeight 0 units")
        add("CJ-gsub-ctl", "vertical", rebuild(cb, {b"GSUB": gs_ctl}),
            "GSUB replaced by the well-formed control")
        add("CJ-gsub-wrap", "vertical", rebuild(cb, {b"GSUB": gs_wrap}),
            "GSUB replaced by the wrapping-range arm")
        add("CJ-gsub-desc", "vertical", rebuild(cb, {b"GSUB": gs_desc}),
            "GSUB replaced by the descending-range arm")

    # ---- CO: real colour / bitmap / CJK faces ---------------------------
    for spec in args.extra:
        tag, path = spec.split("=", 1)
        data = open(path, "rb").read()
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        add(f"CO-{tag}", "real", data,
            f"{os.path.basename(path)} ({len(data)} B) unmodified", ext=ext)

    os.makedirs(args.out, exist_ok=True)
    for a in arms:
        with open(os.path.join(args.out, a["file"]), "wb") as fh:
            fh.write(a["data"])
    man = dict(base=os.path.basename(args.base),
               base_md5=hashlib.md5(base).hexdigest(),
               base_size=len(base),
               tables=[e["tag"].decode("latin1") for e in s.dir],
               arms=[{k: v for k, v in a.items() if k != "data"} for a in arms])
    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump(man, fh, indent=1)
    kinds = {}
    for a in arms:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    print(f"base {args.base} md5={man['base_md5']} tables={len(s.dir)}")
    print(f"arms={len(arms)} " + " ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print(f"out {args.out}")


if __name__ == "__main__":
    main()
