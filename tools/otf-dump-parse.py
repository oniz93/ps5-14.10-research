#!/usr/bin/env python3
"""Score the OTFs WebKit's SVG-font writer produced (docs/104).

Reads raw sfnt bytes, so the answer does not depend on fontTools being able to load a malformed
table; fontTools is run too, and both answers are printed.  One report per file.

    tools/otf-dump-parse.py data/otf-dump/g6/g6_01.bin [...]
"""
import json
import struct
import sys


SET_WALK = 12   # sets walked past the header (docs/105: 300 declared is not printable)
COMP_WALK = 8   # components printed per bogus Ligature


def u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def sfnt(b):
    if len(b) < 12:
        raise ValueError("short file")
    version = b[:4].decode("latin-1")
    num_tables, search_range, entry_selector, range_shift = struct.unpack_from(">HHHH", b, 4)
    tables = {}
    order = []
    for i in range(num_tables):
        o = 12 + 16 * i
        tag = b[o:o + 4].decode("latin-1")
        checksum, offset, length = struct.unpack_from(">III", b, o + 4)
        tables[tag] = {"tag": tag, "checksum": checksum, "offset": offset, "length": length}
        order.append(tag)
    return {
        "version": version,
        "numTables": num_tables,
        "searchRange": search_range,
        "entrySelector": entry_selector,
        "rangeShift": range_shift,
        "order": order,
        "tables": tables,
    }


def gsub_report(b, t):
    """Decode GSUB far enough to state the ligature subtable's declared counts against its bytes."""
    base = t["offset"]
    end = base + t["length"]
    major, minor, script_off, feat_off, look_off = struct.unpack_from(">HHHHH", b, base)
    out = {"version": f"{major}.{minor}", "lookupListOffset": look_off, "lookups": []}
    ll = base + look_off
    n = u16(b, ll)
    for i in range(n):
        lo = ll + u16(b, ll + 2 + 2 * i)
        ltype, flag, subcount = struct.unpack_from(">HHH", b, lo)
        subs = []
        for j in range(subcount):
            so = lo + u16(b, lo + 6 + 2 * j)
            entry = {"offset": so}
            if ltype == 4:
                fmt = u16(b, so)
                cov = u16(b, so + 2)
                count = u16(b, so + 4)
                entry.update({
                    "format": fmt,
                    "coverageOffset": cov,
                    "ligatureSetCount": count,
                    "offsetSlots": [u16(b, so + 6 + 2 * k) for k in range(count)],
                    "coverage": {"at": so + cov, "format": u16(b, so + cov),
                                 "glyphCount": u16(b, so + cov + 2),
                                 "glyphs": [u16(b, so + cov + 4 + 2 * k)
                                            for k in range(u16(b, so + cov + 2))]},
                    "ligatureSets": [],
                })
                # follow each declared set; a shaper stops at the first one it cannot sanitise.
                # Bounded: a divergent font can declare 300 sets of 65 535 ligatures (docs/105), and an
                # unbounded walk writes megabytes of JSON for a report whose point is the header.
                for k, off in enumerate(entry["offsetSlots"][:SET_WALK]):
                    s = so + off
                    if s + 2 > end:
                        entry["ligatureSets"].append({"index": k, "offset": off, "note": "past table end"})
                        continue
                    lc = u16(b, s)
                    setrec = {"index": k, "offset": off, "ligatureCount": lc, "ligatures": []}
                    if lc > 4:
                        setrec["note"] = "walked as a reader that trusts the declared count would"
                    for m in range(min(lc, 4)):
                        p = s + 2 + 2 * m
                        if p + 2 > end:
                            setrec["ligatures"].append({"note": "offset array past table end"})
                            break
                        lg = s + u16(b, p)
                        if lg + 4 > end:
                            setrec["ligatures"].append({"offset": u16(b, p), "note": "past table end"})
                            continue
                        lig_glyph, comp_count = struct.unpack_from(">HH", b, lg)
                        comps = [u16(b, lg + 4 + 2 * c) for c in range(min(max(0, comp_count - 1), COMP_WALK))
                                 if lg + 6 + 2 * c <= end]
                        ligrec = {"offset": u16(b, p), "ligGlyph": lig_glyph,
                                  "compCount": comp_count, "components": comps}
                        if comp_count - 1 > COMP_WALK:
                            ligrec["componentsTruncated"] = comp_count - 1
                        setrec["ligatures"].append(ligrec)
                    entry["ligatureSets"].append(setrec)
                if count > SET_WALK:
                    entry["setsWalked"] = SET_WALK
                    entry["setsNotWalked"] = count - SET_WALK
                # bytes at the slot the writer never filled
                if count >= 2:
                    entry["slot2Bytes"] = struct.unpack_from(">H", b, so + 8)[0]
                entry["raw"] = b[so:min(so + 64, end)].hex()
            entry["type"] = ltype
            subs.append(entry)
        out["lookups"].append({"index": i, "type": ltype, "flag": flag, "subtables": subs})
    return out


def cmap_report(b, t):
    base = t["offset"]
    end = base + t["length"]
    version, n = struct.unpack_from(">HH", b, base)
    out = {"version": version, "numSubtables": n, "records": [], "subtables": []}
    offs = []
    for i in range(n):
        p, e, off = struct.unpack_from(">HHI", b, base + 4 + 8 * i)
        out["records"].append({"platform": p, "encoding": e, "offset": off})
        if off not in offs:
            offs.append(off)
    for off in offs:
        s = base + off
        fmt = u16(b, s)
        rec = {"offset": off, "format": fmt}
        if fmt == 4:
            length, lang = struct.unpack_from(">HH", b, s + 2)
            seg2, srch, es, rs = struct.unpack_from(">HHHH", b, s + 6)
            rec.update({"declaredLength": length, "language": lang, "segCountX2": seg2,
                        "searchRange": srch, "entrySelector": es, "rangeShift": rs,
                        "bytesLeftInCmapTable": end - s})
            if seg2:
                seg = seg2 // 2
                end_codes_at = s + 14
                rec["endCodesHead"] = [u16(b, end_codes_at + 2 * k) for k in range(min(4, seg))]
        elif fmt == 12:
            length, lang, ngroups = struct.unpack_from(">III", b, s + 4)
            rec.update({"declaredLength": length, "language": lang, "numGroups": ngroups,
                        "firstGroups": [list(struct.unpack_from(">III", b, s + 16 + 12 * k))
                                        for k in range(min(3, ngroups))]})
        else:
            rec["declaredLength"] = u16(b, s + 2) if fmt in (0, 2, 4, 6) else None
        out["subtables"].append(rec)
    return out


def maxp_report(b, t):
    base = t["offset"]
    return {"version": u32(b, base), "numGlyphs": u16(b, base + 4)}


def fonttools_view(path):
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(path, fontNumber=0)
        res = {"loaded": True, "tables": sorted(f.reader.keys())}
        try:
            cm = f["cmap"]
            res["cmap"] = [{"platformID": s.platformID, "platEncID": s.platEncID,
                            "format": s.format, "n": len(getattr(s, "cmap", {}))} for s in cm.tables]
        except Exception as e:
            res["cmap"] = f"FAILED: {type(e).__name__}: {e}"
        try:
            g = f["GSUB"].table
            res["GSUB"] = "decompiled"
            res["GSUB_features"] = [(fr.FeatureTag, list(fr.Feature.LookupListIndex))
                                    for fr in g.FeatureList.FeatureRecord]
            lst = []
            for lk in g.LookupList.Lookup:
                lt = []
                for st in lk.SubTable:
                    if lk.LookupType == 4:
                        # fontTools' LigatureSubst iterates Coverage, so it reads only the offsets the
                        # coverage reaches.  Record what it actually does, including a refusal.
                        try:
                            if not hasattr(st, "ligatures"):  # a lazy, not-yet-decompiled subtable
                                st.ensureDecompiled()
                            lt.append({"firstGlyphs": {k: [(l.LigGlyph, list(l.Component)) for l in v]
                                                       for k, v in st.ligatures.items()}})
                        except Exception as e:
                            lt.append(f"DECOMPILE FAILED: {type(e).__name__}: {e!r}")
                    else:
                        lt.append(type(st).__name__)
                lst.append({"type": lk.LookupType, "subtables": lt})
            res["GSUB_lookups"] = lst
        except Exception as e:
            res["GSUB"] = f"FAILED: {type(e).__name__}: {e}"
        return res
    except Exception as e:
        return {"loaded": False, "error": f"{type(e).__name__}: {e}"}


def main(paths):
    report = {}
    for path in paths:
        with open(path, "rb") as fh:
            b = fh.read()
        r = {"path": path, "size": len(b)}
        r["sfnt"] = sfnt(b)
        tabs = r["sfnt"]["tables"]
        r["GSUB"] = gsub_report(b, tabs["GSUB"])
        r["cmap"] = cmap_report(b, tabs["cmap"])
        if "maxp" in tabs:
            r["maxp"] = maxp_report(b, tabs["maxp"])
        r["fontTools"] = fonttools_view(path)
        report[path] = r

        print(f"### {path}  size={len(b)}  version={r['sfnt']['version']}  "
              f"numTables={r['sfnt']['numTables']}")
        print("  tables: " + " ".join(f"{tg}({tabs[tg]['offset']}+{tabs[tg]['length']})"
                                      for tg in r["sfnt"]["order"]))
        print(f"  maxp: {r.get('maxp')}")
        for lk in r["GSUB"]["lookups"]:
            for st in lk["subtables"]:
                if lk["type"] != 4:
                    print(f"  GSUB lookup{lk['index']} type={lk['type']} {st}")
                    continue
                print(f"  GSUB lookup{lk['index']} type=4 fmt={st['format']} "
                      f"ligatureSetCount={st['ligatureSetCount']} "
                      f"offsetSlots={st['offsetSlots']} slot2Bytes={st.get('slot2Bytes')}")
                print(f"    coverage at +{st['coverageOffset']}: fmt={st['coverage']['format']} "
                      f"glyphCount={st['coverage']['glyphCount']} glyphs={st['coverage']['glyphs']}")
                for s in st["ligatureSets"]:
                    print(f"    set{s['index']} at +{s['offset']}: {s}")
                print(f"    raw: {st['raw']}")
        for rec in r["cmap"]["records"]:
            print(f"  cmap record ({rec['platform']},{rec['encoding']}) -> +{rec['offset']}")
        for s in r["cmap"]["subtables"]:
            print(f"  cmap subtable +{s['offset']}: {s}")
        print(f"  fontTools: {r['fontTools']}")
        print()
    with open("data/otf-dump/report.json", "w") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    print("wrote data/otf-dump/report.json")


if __name__ == "__main__":
    main(sys.argv[1:])
