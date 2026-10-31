#!/usr/bin/env python3
"""Score a format-1 ligature subtable the way a reader that trusts its declared counts would.

docs/105: the SVG-font writer puts `ligaturePairs.size()` in "Number of LigatureSet tables"
(SVGToOTFFontConversion.cpp:771) but grows one offset per *distinct first glyph* (:772), so the
declared array runs into the set's own data and past the table.  This model reads the bytes with no
per-table bound and records the highest byte *offset* it touches, so "does a reader leave the GSUB
table" becomes a number instead of an argument.

    python3 tools/gsub-trust-model.py data/otf-dump/g10/g10_01.bin [--max-count N] [--json out]

Two models, both starting at the same subtable:
  A  "offsets only"     read LigatureSetCount offsets at subtable+6 and stop.
  B  "follow"           for each declared offset read a LigatureSet (count + that many offsets), and
                        for each of those read a Ligature (ligGlyph, compCount, compCount-1 comps).
Reads past the end of the font buffer are clamped and *counted*, never actually performed.
"""
import json
import struct
import sys


class Buf:
    """Byte reader that records every byte it is asked for, clamped to the font."""

    def __init__(self, data):
        self.d = data
        self.n = len(data)
        self.max_abs = -1
        self.max_want = -1
        self.out_of_font = 0
        self.reads = 0

    def u16(self, abs_off):
        self.reads += 1
        end = abs_off + 2
        if end > self.max_want:
            self.max_want = end
        if end > self.n:
            self.out_of_font += 1
            abs_off = max(0, min(abs_off, self.n - 2))
        if abs_off + 2 > self.max_abs:
            self.max_abs = abs_off + 2
        return struct.unpack_from(">H", self.d, abs_off)[0]

    def u16_many(self, abs_off, count):
        """Read `count` uint16 at abs_off; returns them (clamped once, like a memcpy would fail)."""
        end = abs_off + 2 * count
        if end > self.max_want:
            self.max_want = end
        if end > self.max_abs:
            self.max_abs = min(end, self.n) if end <= self.n else self.n
        if end > self.n:
            self.out_of_font += count
            count = max(0, (self.n - abs_off) // 2)
        self.reads += count
        return list(struct.unpack_from(">%dH" % count, self.d, abs_off)) if count else []


def tables(d):
    n = struct.unpack_from(">H", d, 4)[0]
    t = {}
    for i in range(n):
        o = 12 + 16 * i
        tag = d[o:o + 4].decode("latin-1")
        off, ln = struct.unpack_from(">II", d, o + 8)
        t[tag] = (off, ln)
    return t


def main():
    path = sys.argv[1]
    max_count = 65535
    json_out = None
    args = sys.argv[2:]
    while args:
        a = args.pop(0)
        if a == "--max-count":
            max_count = int(args.pop(0))
        elif a == "--json":
            json_out = args.pop(0)
    d = open(path, "rb").read()
    tb = tables(d)
    gsub_off, gsub_len = tb["GSUB"]
    gsub_end = gsub_off + gsub_len

    # GSUB 1.0 header -> LookupList -> Lookup[0] -> subtable
    lookup_list = gsub_off + struct.unpack_from(">H", d, gsub_off + 8)[0]
    lookup_count = struct.unpack_from(">H", d, lookup_list)[0]
    lookups = [lookup_list + struct.unpack_from(">H", d, lookup_list + 2 + 2 * i)[0]
               for i in range(lookup_count)]
    look = lookups[0]
    look_type, flag, sub_count = struct.unpack_from(">HHH", d, look)
    sub_rel = struct.unpack_from(">H", d, look + 6)[0]
    sub = look + sub_rel
    fmt, cov_off, set_count = struct.unpack_from(">HHH", d, sub)

    out = {
        "file": path, "font_size": len(d), "gsub_off": gsub_off, "gsub_len": gsub_len,
        "gsub_end": gsub_end, "lookup_count": lookup_count, "lookup_type": look_type,
        "subtable_off": sub, "subtable_rel_to_gsub": sub - gsub_off, "format": fmt,
        "coverage_rel": cov_off, "ligature_set_count": set_count,
    }

    # The subtable's real extent: coverage is appended last, and its own size is 4 + 2*GlyphCount.
    cov_fmt, cov_n = struct.unpack_from(">HH", d, sub + cov_off)
    sub_len = cov_off + 4 + 2 * cov_n
    out.update({"coverage_fmt": cov_fmt, "coverage_glyph_count": cov_n,
                "subtable_len": sub_len, "subtable_end": sub + sub_len,
                "gsub_tail_after_subtable": gsub_end - (sub + sub_len)})

    # Model A — enumerate the declared offset array and nothing else.
    a = Buf(d)
    declared = a.u16_many(sub + 6, min(set_count, max_count))
    written = 1  # one slot per distinct first glyph; the set header is at +8, i.e. slot 1
    out["A_offsets_only"] = {
        "declared": len(declared), "first_8": declared[:8],
        "max_abs": a.max_abs, "max_rel_subtable": a.max_abs - sub,
        "bytes_past_subtable_end": max(0, a.max_abs - (sub + sub_len)),
        "bytes_past_gsub_end": max(0, a.max_abs - gsub_end),
        "out_of_font_reads": a.out_of_font,
    }

    # Model B — follow every declared offset one level down: LigatureSet -> its Ligatures.
    b = Buf(d)
    reached_past_sub = 0
    reached_past_gsub = 0
    reached_past_font = 0
    lig_records = 0
    for off in declared:
        if off == 0:
            continue
        s = sub + off
        if s >= sub + sub_len:
            reached_past_sub += 1
        if s >= gsub_end:
            reached_past_gsub += 1
        if s >= len(d):
            reached_past_font += 1
            continue
        n = min(b.u16(s), max_count)
        offs = b.u16_many(s + 2, n)
        for lo in offs[:64]:          # one Ligature per set is enough for the reach number
            lg = s + lo
            if lg >= sub + sub_len:
                reached_past_sub += 1
            if lg >= gsub_end:
                reached_past_gsub += 1
            if lg >= len(d):
                reached_past_font += 1
                continue
            lig_glyph = b.u16(lg)
            comp = b.u16(lg + 2)
            comp = min(comp, max_count)
            if comp:
                b.u16_many(lg + 4, comp - 1)
            lig_records += 1
    out["B_follow"] = {
        "ligature_sets_walked": len(declared), "ligature_records_read": lig_records,
        "set_starts_past_subtable": reached_past_sub,
        "set_starts_past_gsub": reached_past_gsub,
        "set_starts_past_font": reached_past_font,
        "max_abs": b.max_abs, "max_rel_subtable": b.max_abs - sub,
        "max_want_abs": b.max_want, "max_want_rel_subtable": b.max_want - sub,
        "want_bytes_past_font_end": max(0, b.max_want - len(d)),
        "bytes_past_subtable_end": max(0, b.max_abs - (sub + sub_len)),
        "bytes_past_gsub_end": max(0, b.max_abs - gsub_end),
        "bytes_past_font_end": max(0, b.max_abs - len(d)),
        "out_of_font_reads": b.out_of_font, "reads": b.reads,
    }

    for k, v in out.items():
        print("%-26s %s" % (k, v))
    if json_out:
        json.dump(out, open(json_out, "w"), indent=1)


if __name__ == "__main__":
    main()
