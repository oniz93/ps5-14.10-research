#!/usr/bin/env python3
"""Predict what OpenTypeVerticalData::loadVerticalGlyphSubstitutions does with a
generated GSUB arm, by re-implementing the drop's validators exactly.

Reads the GSUB table out of an sfnt and walks the same chain the C++ does:

    GSUBTable::feature('vert')  -> FeatureList::findFeature
    LookupList::lookup(0)       -> LookupTable::getSubstitutions
    Coverage2Table              -> the nested loop

It prints where the walk stops and, for coverage format 2, the first index at
which `singleSubstitution2->substitute[indexTo]` leaves the *table buffer* —
the read that ASAN must report if the path is reached.

    python3 research/font-parser/gsub-model.py f/GS-wrap.ttf [...]
"""
import struct
import sys


def rd16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def rd32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def sfnt_table(data, tag):
    n = rd16(data, 4)
    for i in range(n):
        o = 12 + 16 * i
        if data[o:o + 4] == tag:
            off, ln = rd32(data, o + 8), rd32(data, o + 12)
            return data[off:off + ln]
    return None


class Buf:
    """The WebKit validators: isValidEnd / validatePtr / validateOffset."""

    def __init__(self, data):
        self.d = data

    def valid_end(self, pos):
        if pos < 0:
            return False
        return pos <= len(self.d)

    def validate_ptr(self, pos, size):
        return self.valid_end(pos + size)

    def validate_offset(self, base, off, size):
        return self.validate_ptr(base + off, size)


def walk(gsub, label):
    b = Buf(gsub)
    out = [f"--- {label}: GSUB {len(gsub)} B"]
    if len(gsub) < 10:
        out.append("  GSUBTable validateTable fails (needs 10 B)")
        return out
    script_off, feat_off, lookup_off = rd16(gsub, 4), rd16(gsub, 6), rd16(gsub, 8)
    if not b.validate_offset(0, feat_off, 2):
        out.append("  FeatureList offset outside the buffer")
        return out
    fl = feat_off
    count = rd16(gsub, fl)
    out.append(f"  featureCount={count}")
    feat = None
    for i in range(count):
        rec = fl + 2 + 6 * i
        if not b.valid_end(rec + 6):
            break
        tag = gsub[rec:rec + 4]
        if tag == b"vert":
            fo = rd16(gsub, rec + 4)
            if b.validate_offset(fl, fo, 6):
                feat = fl + fo
            break
    if feat is None:
        out.append("  no 'vert' feature -> getVerticalGlyphSubstitutions returns false (no loop)")
        return out
    lc, li = rd16(gsub, feat + 2), rd16(gsub, feat + 4)
    out.append(f"  FeatureTable at {feat}: lookupCount={lc} lookupListIndex[0]={li}")
    if not b.validate_offset(0, lookup_off, 4):
        out.append("  LookupList offset outside the buffer")
        return out
    ll = lookup_off
    lcount = rd16(gsub, ll)
    out.append(f"  lookupCount={lcount}")
    lo = rd16(gsub, ll + 2)                        # lookupOffsets[li]
    if not b.validate_offset(ll, lo, 8):
        out.append("  LookupTable offset outside the buffer")
        return out
    lk = ll + lo
    ltype, _, nsub = rd16(gsub, lk), rd16(gsub, lk + 2), rd16(gsub, lk + 4)
    out.append(f"  LookupTable at {lk}: type={ltype} subTableCount={nsub}")
    if ltype != 1:
        out.append("  lookupType != 1 -> return false (no loop)")
        return out
    if not b.valid_end(lk + 6 + 2 * nsub):
        out.append("  subTableOffsets[] past the buffer")
        return out
    for i in range(nsub):
        so = rd16(gsub, lk + 6 + 2 * i)
        if not b.validate_offset(lk, so, 4):
            out.append(f"  subtable {i}: SubstitutionSubTable offset outside")
            return out
        sub = lk + so
        if not b.validate_offset(sub, rd16(gsub, sub + 2), 2):
            out.append(f"  subtable {i}: coverage offset outside")
            return out
        cov = sub + rd16(gsub, sub + 2)
        if rd16(gsub, sub) != 2:
            out.append(f"  subtable {i}: substFormat {rd16(gsub, sub)} != 2")
            return out
        if not b.validate_ptr(sub, 8):
            out.append(f"  subtable {i}: SingleSubstitution2 does not fit")
            return out
        count_to = rd16(gsub, sub + 4)
        if not b.valid_end(sub + 6 + 2 * count_to):
            out.append(f"  subtable {i}: substitute[{count_to}] past the buffer")
            return out
        fmt = rd16(gsub, cov)
        out.append(f"  subtable {i}: countTo={count_to} coverage fmt={fmt} at {cov}")
        if fmt != 2:
            out.append("  coverage format != 2 -> return false (no loop)")
            return out
        if not b.validate_ptr(cov, 10):
            out.append("  Coverage2Table does not fit")
            return out
        nrange = rd16(gsub, cov + 2)
        if not b.valid_end(cov + 4 + 6 * nrange):
            out.append(f"  ranges[{nrange}] past the buffer")
            return out
        reads = 0
        index_to = 0
        first_past = None
        first_past_val = None
        for r in range(nrange):
            ro = cov + 4 + 6 * r
            start, end, sci = rd16(gsub, ro), rd16(gsub, ro + 2), rd16(gsub, ro + 4)
            from_end = (end + 1) & 0xFFFF
            diff = ((from_end - start + 0x8000) & 0xFFFF) - 0x8000   # int arithmetic
            out.append(f"  range {r}: start={start} end={end} fromEnd={from_end} diff={diff} "
                       f"check indexTo+diff>{count_to} -> {index_to + diff > count_to}")
            if index_to + diff > count_to:
                out.append("  -> return false before the loop")
                return out
            frm = start
            while True:
                if frm == from_end:
                    break
                reads += 1
                at = sub + 6 + 2 * index_to
                if at + 2 > len(gsub) and first_past is None:
                    first_past = index_to
                    first_past_val = at + 2 - len(gsub)
                index_to = (index_to + 1) & 0xFFFF
                frm = (frm + 1) & 0xFFFF
                if index_to == 0 and reads > 200000:
                    out.append("  !! indexTo wrapped, loop bounded by uint16")
                    break
        out.append(f"  reads={reads} first read past the table buffer: indexTo="
                   f"{first_past} ({first_past_val} B past end)" if first_past is not None
                   else f"  reads={reads}, no read leaves the table buffer")
    return out


def main():
    for path in sys.argv[1:]:
        data = open(path, "rb").read()
        g = sfnt_table(data, b"GSUB")
        if g is None:
            print(f"--- {path}: no GSUB table")
            continue
        print("\n".join(walk(g, path)))


if __name__ == "__main__":
    main()
