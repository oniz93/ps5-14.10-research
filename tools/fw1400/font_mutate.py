#!/usr/bin/env python3
"""Generate malformed TrueType fonts to fingerprint and probe the console's FreeType.

The PlayStation port compiles platform/FreeType.cmake, so a web font travels:

    FontFace(ArrayBuffer) -> FontCustomPlatformDataFreeType::create
        -> FT_New_Memory_Face(library, buffer.data(), buffer.size(), 0, &face)

with no OpenTypeSanitizer anywhere in the tree. Every byte below therefore reaches Sony's
system FreeType parser. Two things are worth learning from that:

 1. Which FreeType vintage the console ships. Fedora 39 has 2.13.1; if a case that 2.13.1
    rejects is accepted on the console (or vice versa), the console is older or newer, and
    that tells us which published CVEs are still in play.
 2. Whether any malformed case crashes it. A crash is a WebProcess bug in a system library,
    reachable from a page with zero prerequisites.

Two families are emitted, and the distinction matters when reading results:

  content   - table bytes are corrupt, but the sfnt is rebuilt with correct offsets and
              checksums, so the font is structurally sane and the *parser* is what gets tested.
  dirent    - the table directory itself is corrupt (numTables, offsets, lengths, overlaps).
  trunc     - the file is cut short at a chosen point.

Usage:
    python3 tools/fw1400/font_mutate.py --base <font.ttf> --out tools/fw1400/guide_lab/www/fonts
"""

import argparse
import hashlib
import json
import os
import struct

# hdmx: version(2) numRecords(2) sizeDeviceRecord(4) then numRecords records
# loca/glyf are indexed through maxp.numGlyphs; a short loca is the classic 2.12-era bug class.


# ---------------------------------------------------------------- sfnt read/write

def parse_sfnt(data: bytes):
    """Return (version, [(tag, checksum, offset, length)])."""
    if len(data) < 12:
        raise ValueError("too short for an sfnt header")
    version = data[:4]
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables = []
    for i in range(num_tables):
        p = 12 + i * 16
        if p + 16 > len(data):
            raise ValueError("table directory truncated")
        tag = data[p:p + 4]
        checksum, offset, length = struct.unpack(">III", data[p + 4:p + 16])
        tables.append((tag, checksum, offset, length))
    return version, tables


def table_bytes(data: bytes, tables, tag: bytes):
    for t, _ck, off, ln in tables:
        if t == tag:
            return data[off:off + ln]
    return None


def _checksum(b: bytes) -> int:
    b = b + b"\0" * ((4 - len(b) % 4) % 4)
    return sum(struct.unpack(">%dI" % (len(b) // 4), b)) & 0xFFFFFFFF


def build_sfnt(version: bytes, tables) -> bytes:
    """Rebuild with recomputed offsets/checksums, in the order given.

    tables: [(tag, payload)] -- offsets are recomputed so the result is structurally valid.
    """
    n = len(tables)
    # searchRange/entrySelector/rangeShift as the spec defines them
    entry_selector = max(0, n.bit_length() - 1)
    search_range = (1 << entry_selector) * 16 if n else 0
    range_shift = n * 16 - search_range

    header = version + struct.pack(">HHHH", n, search_range, entry_selector, range_shift)
    offset = 12 + n * 16
    directory, blobs = b"", b""
    for tag, payload in tables:
        directory += tag + struct.pack(">III", _checksum(payload), offset, len(payload))
        padded = payload + b"\0" * ((4 - len(payload) % 4) % 4)
        blobs += padded
        offset += len(padded)
    return header + directory + blobs


# ---------------------------------------------------------------- mutations

def mutate_content(base_data: bytes, tables):
    """Yield (name, description, bytes). Offsets stay valid; table contents are hostile."""
    def rebuild(replacements, drop=(), extra=()):
        keep = [(t, table_bytes(base_data, tables, t)) for t, _c, _o, _l in tables]
        keep = [(t, p) for t, p in keep if t not in drop and p is not None]
        keep = [(t, replacements.get(t, p)) for t, p in keep]
        for tag, payload in extra:
            if not any(t == tag for t, _ in keep):
                keep.append((tag, payload))
        return build_sfnt(base_data[:4], keep)

    def put(container: bytearray, offset: int, blob: bytes):
        container[offset:offset + len(blob)] = blob
        return bytes(container)

    # --- hdmx: three flavours of the 2.12.0 fix (CVE-2022-27406) -----------------
    hdmx = table_bytes(base_data, tables, b"hdmx")
    hdmx_records_huge = struct.pack(">HHI", 0, 0xFFFF, 2) + b"\0" * 8
    yield ("hdmx_numrecords_huge",
           "hdmx numRecords=0xFFFF with a two-byte record, so the table is far shorter than it claims",
           rebuild({b"hdmx": hdmx_records_huge}))

    hdmx_sizedevice_zero = struct.pack(">HHI", 0, 4, 0) + b"\0" * 8
    yield ("hdmx_sizedevice_zero",
           "hdmx sizeDeviceRecord=0: recordCount*size == 0, so the stride is zero",
           rebuild({b"hdmx": hdmx_sizedevice_zero}))

    hdmx_overflow = struct.pack(">HHI", 0, 0xFFFF, 0xFFFF) + b"\0" * 4
    yield ("hdmx_count_times_size_overflow",
           "hdmx 0xFFFF*0xFFFF: the 16-bit multiply overflows if done in 16 bits",
           rebuild({b"hdmx": hdmx_overflow}))

    if hdmx:
        # a real hdmx with the record count inflated past the actual data
        bumped = bytearray(hdmx)
        struct.pack_into(">H", bumped, 2, 0x3FFF)
        yield ("hdmx_real_count_inflated",
               "genuine hdmx table with numRecords raised to 0x3FFF",
               rebuild({b"hdmx": bytes(bumped)}))

    # --- loca / maxp / glyf: the glyph index space -------------------------------
    maxp = table_bytes(base_data, tables, b"maxp")
    loca = table_bytes(base_data, tables, b"loca")
    glyf = table_bytes(base_data, tables, b"glyf")

    if maxp:
        num_glyphs = struct.unpack(">H", maxp[4:6])[0]
        huge = bytearray(maxp)
        struct.pack_into(">H", huge, 4, 0xFFFE)
        yield ("maxp_numglyphs_huge",
               "maxp numGlyphs=0xFFFE while loca still describes the original count",
               rebuild({b"maxp": bytes(huge)}))

        zero = bytearray(maxp)
        struct.pack_into(">H", zero, 4, 0)
        yield ("maxp_numglyphs_zero",
               "maxp numGlyphs=0 against a non-empty loca",
               rebuild({b"maxp": bytes(zero)}))

    if loca:
        yield ("loca_short",
               "loca truncated to a quarter of its length, so glyph indices run off the end",
               rebuild({b"loca": loca[:max(4, len(loca) // 4)]}))

        yield ("loca_empty",
               "loca replaced by four bytes of zeroes",
               rebuild({b"loca": b"\0\0\0\0"}))

        # short-format loca (word offsets * 2) claiming offsets past the end of glyf
        if glyf:
            far = struct.pack(">H", min(0xFFFE, len(glyf) // 2 + 0x100))
            yield ("loca_offsets_past_glyf",
                   "every loca entry points beyond the end of glyf",
                   rebuild({b"loca": far * 8}))

        if glyf:
            yield ("glyf_glyph_span_huge",
                   "loca entries that describe a single glyph spanning the whole font",
                   rebuild({b"loca": struct.pack(">HH", 0, 0x7FFF) + loca[4:]}))

    # --- cmap -------------------------------------------------------------------
    cmap = table_bytes(base_data, tables, b"cmap")
    if cmap:
        bad = bytearray(cmap)
        if len(bad) >= 8:
            struct.pack_into(">I", bad, 4, 0x7FFFFFF0)      # subtable offset far past the table
        yield ("cmap_subtable_offset_oob",
               "cmap encoding record points 2 GB past the start of the table",
               rebuild({b"cmap": bytes(bad)}))

        seg = _first_format4_offset(cmap)
        if seg is not None and seg + 8 <= len(cmap):
            f4 = bytearray(cmap)
            struct.pack_into(">H", f4, seg + 6, 0xFFFF)     # segCountX2
            yield ("cmap_format4_segcount_huge",
                   "format 4 subtable segCountX2=0xFFFF with no matching arrays",
                   rebuild({b"cmap": bytes(f4)}))

    # --- head: the values every other table is scaled by -------------------------
    head = table_bytes(base_data, tables, b"head")
    if head:
        z = bytearray(head)
        struct.pack_into(">H", z, 18, 0)                   # unitsPerEm
        yield ("head_unitsperem_zero",
               "head unitsPerEm=0, so every scaled metric collapses",
               rebuild({b"head": bytes(z)}))

        m = bytearray(head)
        struct.pack_into(">I", m, 12, 0xDEADBEEF)          # magicNumber
        yield ("head_magic_bad",
               "head magicNumber replaced",
               rebuild({b"head": bytes(m)}))

        s = bytearray(head)
        struct.pack_into(">h", s, 16, 0x7FFF)              # indexToLocFormat
        yield ("head_locformat_bad",
               "head indexToLocFormat=0x7FFF, neither short nor long",
               rebuild({b"head": bytes(s)}))

    # --- misc tables with a count field -----------------------------------------
    for tag, off, name, desc in (
        (b"name", 2, "name_count_huge", "name count=0xFFFF with a two-entry string table"),
        (b"kern", 2, "kern_npairs_huge", "kern nPairs=0xFFFF against a handful of pairs"),
        (b"post", 32, "post_numglyphs_huge", "post numGlyphs=0xFFFF"),
        (b"gasp", 2, "gasp_ranges_huge", "gasp numRanges=0xFFFF"),
    ):
        payload = table_bytes(base_data, tables, tag)
        if payload and len(payload) > off + 2:
            b = bytearray(payload)
            struct.pack_into(">H", b, off, 0xFFFF)
            yield (name, desc, rebuild({tag: bytes(b)}))

    # --- synthesized tables that are not in the base font ------------------------
    yield ("fpgm_inflated",
           "fpgm (font program) present with a length that implies deep instruction nesting",
           rebuild({}, extra=[(b"fpgm", b"\x40" * 4096)]))

    yield ("prep_huge",
           "prep table of 64 KiB of malformed hinting bytecode",
           rebuild({}, extra=[(b"prep", b"\xB0\x00" * 16384)]))


def _first_format4_offset(cmap: bytes):
    """Offset of the first format-4 cmap subtable, or None."""
    if len(cmap) < 4:
        return None
    n = struct.unpack(">H", cmap[2:4])[0]
    for i in range(n):
        p = 4 + i * 8
        if p + 8 > len(cmap):
            return None
        off = struct.unpack(">I", cmap[p + 4:p + 8])[0]
        if off + 2 <= len(cmap) and struct.unpack(">H", cmap[off:off + 2])[0] == 4:
            return off
    return None


def mutate_directory(base_data: bytes):
    """Corrupt the table directory itself, in place, so the sfnt is not structurally valid."""
    if len(base_data) < 12:
        return
    num_tables = struct.unpack(">H", base_data[4:6])[0]

    def poke(offset, blob, name, desc):
        b = bytearray(base_data)
        b[offset:offset + len(blob)] = blob
        return name, desc, bytes(b)

    yield poke(4, struct.pack(">H", 0xFFFE), "dirent_numtables_huge",
               "sfnt numTables=0xFFFE with a directory that holds only the original count")
    yield poke(4, struct.pack(">H", 0), "dirent_numtables_zero",
               "sfnt numTables=0: no tables at all")

    if num_tables:
        first = 12
        # offset/length of the first table, deliberately absurd
        yield poke(first + 8, struct.pack(">II", 0xFFFFFF00, 0x200), "dirent_offset_overflow",
                   "first table offset 0xFFFFFF00 with length 0x200: the end wraps 32 bits")
        yield poke(first + 12, struct.pack(">I", 0x7FFFFFFF), "dirent_length_huge",
                   "first table claims a 2 GB length")

        # make table 0 and table 1 overlap completely
        if num_tables >= 2:
            off0 = struct.unpack(">I", base_data[first + 8:first + 12])[0]
            yield poke(first + 16 + 8, struct.pack(">I", off0), "dirent_overlap",
                       "second table shares the first table's offset, so two parsers read one blob")


def mutate_truncation(base_data: bytes):
    """Cut the file at points that a sanitiser would reject but a lenient parser may not."""
    n = len(base_data)
    for frac, name in ((0.0, "trunc_8"), (0.02, "trunc_header"), (0.5, "trunc_half"), (0.97, "trunc_tail")):
        cut = max(8, int(n * frac)) if frac else 8
        yield name, f"file truncated to {cut} of {n} bytes", base_data[:cut]


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="/System/Library/Fonts/Supplemental/NotoSansLepcha-Regular.ttf")
    ap.add_argument("--out", default="tools/fw1400/guide_lab/www/fonts")
    args = ap.parse_args()

    data = open(args.base, "rb").read()
    version, tables = parse_sfnt(data)
    os.makedirs(args.out, exist_ok=True)

    cases = [("valid", "unmodified base font (control)", data)]
    cases += list(mutate_content(data, tables))
    cases += list(mutate_directory(data))
    cases += list(mutate_truncation(data))

    manifest = {"base": os.path.basename(args.base),
                "base_bytes": len(data),
                "base_sha256": hashlib.sha256(data).hexdigest()[:16],
                "base_tables": [t.decode("latin-1") for t, _c, _o, _l in tables],
                "cases": []}

    for name, desc, blob in cases:
        path = os.path.join(args.out, name + ".ttf")
        with open(path, "wb") as f:
            f.write(blob)
        manifest["cases"].append({"name": name, "bytes": len(blob),
                                  "sha256": hashlib.sha256(blob).hexdigest()[:16],
                                  "note": desc})
        print(f"{len(manifest['cases']):2d}. {name:32s} {len(blob):7d} B  {desc[:60]}")

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n{len(cases)} cases + manifest -> {args.out}")
    print("base tables: " + " ".join(manifest["base_tables"]))


if __name__ == "__main__":
    main()
