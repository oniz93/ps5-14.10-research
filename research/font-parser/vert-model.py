#!/usr/bin/env python3
"""Predict, from the arm files alone, what docs/102's page must measure.

Walks the same chain the drop walks (`GSUBTable::getVerticalGlyphSubstitutions`
-> FeatureTable -> LookupTable -> Coverage2 -> SingleSubst2) with the drop's own
arithmetic, including the uint16 wraparound in `fromEnd = end + 1` and in the
`from` loop counter, and reports:

  * map[g_from] -- the glyph id the shaper must use for the page's character
  * the highest `substitute[]` index read, and whether it is inside the table
  * the predicted inline advance in px for that glyph (upem 256,
    `advanceHeight = vmtx[g] * fontsize / 256`)

Usage: python3 research/font-parser/vert-model.py <arm-dir>
"""
import json
import os
import struct
import sys


def u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def tables(path):
    with open(path, "rb") as fh:
        d = fh.read()
    n = u16(d, 4)
    out = {}
    for i in range(n):
        o = 12 + 16 * i
        tag = d[o:o + 4].decode("latin-1")
        off, ln = struct.unpack_from(">II", d, o + 8)
        out[tag] = d[off:off + ln]
    return out


def gsub_map(t, g_from):
    """Return (map_dict, max_index_read, table_len, note)."""
    note = []
    if not t:
        return {}, -1, 0, "no GSUB"
    script, featlist, lookuplist = struct.unpack_from(">HHH", t, 4)
    nfeat = u16(t, featlist)
    lookup_index = None
    for i in range(nfeat):
        o = featlist + 2 + 6 * i
        tag = t[o:o + 4]
        feat_off = u16(t, o + 4)
        if tag == b"vert":
            fo = featlist + feat_off
            if u16(t, fo + 2) >= 1:
                lookup_index = u16(t, fo + 4)
    if lookup_index is None:
        return {}, -1, len(t), "no vert feature"
    lo = lookuplist + u16(t, lookuplist + 2 + 2 * lookup_index)
    ltype, lflag, nsub, suboff = struct.unpack_from(">HHHH", t, lo)
    if ltype != 1:
        return {}, -1, len(t), f"vert lookupType {ltype} not walked by this model"
    so = lo + suboff
    fmt, covoff, count_to = struct.unpack_from(">HHH", t, so)
    if fmt != 2:
        return {}, -1, len(t), f"SingleSubst format {fmt} not walked by this model"
    co = so + covoff
    cfmt, ncov = struct.unpack_from(">HH", t, co)
    m = {}
    maxidx = -1
    for r in range(ncov):
        ro = co + 4 + 6 * r
        start = u16(t, ro)
        end = u16(t, ro + 2)
        covidx = u16(t, ro + 4)
        frm = start
        fromEnd = (end + 1) & 0xFFFF          # drop: uint16_t, wraps
        indexTo = covidx
        diff = fromEnd - frm                   # int promotion, can be negative
        if indexTo + diff > count_to:          # drop's test, no fromEnd<=from
            note.append(f"range {r} rejected")
            continue
        n = 0
        while True:
            if frm == fromEnd:
                break
            if indexTo >= count_to:            # this read is past substitute[]
                maxidx = max(maxidx, indexTo)
                val = u16(t, so + 6 + 2 * indexTo) if so + 6 + 2 * indexTo + 2 <= len(t) else None
            else:
                val = u16(t, so + 6 + 2 * indexTo)
            if val is not None and frm not in m:
                m[frm] = val
            frm = (frm + 1) & 0xFFFF
            indexTo += 1
            n += 1
            if n > 200000:
                note.append("loop cap")
                break
        note.append(f"range {r}: {start}..{end} -> {n} keys, last indexTo {indexTo}")
    note.append(f"table len {len(t)}, max substitute[] index read {maxidx}, "
                f"byte end {so + 6 + 2 * maxidx + 2} "
                f"({'IN' if so + 6 + 2 * maxidx + 2 <= len(t) else 'PAST'} bounds)")
    return m, maxidx, len(t), "; ".join(note)


def main():
    d = sys.argv[1]
    man = json.load(open(os.path.join(d, "manifest.json")))
    upem, g_from = man["upem"], man["g_from"]
    print(f"# base={man['base']} upem={upem} glyphs={man['glyphs']} "
          f"g_from={g_from} g_to={man['g_to']}")
    for a in man["arms"]:
        tb = tables(os.path.join(d, a["file"]))
        m, maxidx, tlen, note = gsub_map(tb.get("GSUB"), g_from)
        vmtx, vhea = tb.get("vmtx"), tb.get("vhea")
        num_long = u16(vhea, 34) if vhea and len(vhea) >= 36 else 0
        def height(g):
            if not vmtx or not num_long:
                return None
            i = g if g < num_long else num_long - 1
            o = 4 * i
            return u16(vmtx, o) if o + 2 <= len(vmtx) else None
        used = m.get(g_from) or g_from          # `if (to)` -- a zero value is a no-op
        h_got = height(used)
        h_plain = height(g_from)
        hm = tb.get("hmtx")
        def width(g):
            if not hm:
                return None
            o = 4 * g
            return u16(hm, o) if o + 2 <= len(hm) else None
        w_used = width(used)
        pred = None if h_got is None else h_got * a["fs"] / upem
        predw = None if w_used is None else w_used * a["fs"] / upem
        print(f"\n{a['id']} fs={a['fs']} {a['note']}")
        print(f"  numOfLongVerMetrics={num_long} vmtx={len(vmtx) if vmtx else 0}B "
              f"vhea={len(vhea) if vhea else 0}B")
        print(f"  map[{g_from}]={'absent' if g_from not in m else m[g_from]}  "
              f"shape uses glyph {used}  (no-sub advance {h_plain} units)")
        print(f"  hmtx[{used}]={w_used} units -> {predw} px if the advance is hmtx "
              f"(h3={None if predw is None else round(3 * predw, 4)})")
        print(f"  vmtx[{used}]={h_got} units -> {pred} px if the advance is m_advanceHeights "
              f"(h3={None if pred is None else round(3 * pred, 4)})")
        print(f"  {note}")


if __name__ == "__main__":
    main()
