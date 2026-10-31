#!/usr/bin/env python3
"""Build the vertical-substitution arms for docs/102.

Base: DroidSansFallbackFull.ttf (upem 256, 49382 glyphs, real vhea/vmtx with a
single long metric, one `vert` lookup).  Each arm replaces `vhea`+`vmtx` and/or
`GSUB` with hand-built bytes, so the only thing that differs between an arm and
its control is the table the arm is named after.

Why raw bytes: the point of the exercise is to control `numOfLongVerMetrics`
(one entry clamps every glyph to entry 0) and to place a *padding island* right
after `SingleSubst2::substitute[]` so that the OOB-shaped coverage range can be
measured **in bounds** (ASAN aborts on the real thing, which is why docs/99
could never see what the map does).

    python3 tools/font-vertical.py --base base.ttf --out out-vert
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fontTools.ttLib import TTFont, newTable      # noqa: E402
from fontTools.ttLib.tables.DefaultTable import DefaultTable  # noqa: E402


def raw(tag, data):
    t = DefaultTable(tag)
    t.data = data
    return t


def build_vhea(num_long):
    """36-byte vhea: one long metric per glyph when num_long == numGlyphs."""
    return struct.pack(
        ">I" + "h" * 10 + "8s" + "hH", 0x00010000,
        0, 0, 0, 0, 0, 0, 0, 0, 1, 0,          # ascent..caretOffset
        b"\0" * 8, 0, num_long)


def build_vmtx(heights):
    """num_long == len(heights): every glyph gets its own (advanceHeight, tsb)."""
    out = bytearray()
    for h in heights:
        out += struct.pack(">Hh", h & 0xFFFF, 0)
    return bytes(out)


def build_gsub(count_to, subs, ranges, pad=b""):
    """GSUB with one 'vert' feature -> lookupType 1 -> SingleSubst format 2.

    `pad` is appended after the coverage table so reads of substitute[i] for
    i >= count_to walk over the coverage bytes and then into page-chosen bytes
    that are still inside the same allocation (offsets are 16-bit, so the pad
    cannot sit between substitute[] and the coverage).
    """
    hdr = 10
    off_script = hdr
    script = struct.pack(">H", 0)
    off_featlist = off_script + len(script)
    off_feature = off_featlist + 2 + 6
    off_lookuplist = off_feature + 6
    off_lookup = off_lookuplist + 4
    off_sub = off_lookup + 8
    off_cov = off_sub + 6 + 2 * count_to
    featlist = struct.pack(">H", 1) + b"vert" + struct.pack(">H", off_feature - off_featlist)
    feature = struct.pack(">HHH", 0, 1, 0)
    lookuplist = struct.pack(">HH", 1, off_lookup - off_lookuplist)
    lookup = struct.pack(">HHHH", 1, 0, 1, off_sub - off_lookup)
    sub = struct.pack(">HHH", 2, off_cov - off_sub, count_to)
    sub += b"".join(struct.pack(">H", s) for s in subs)
    cov = struct.pack(">HH", 2, len(ranges))
    cov += b"".join(struct.pack(">HHH", a, b, c) for a, b, c in ranges)
    head = struct.pack(">IHHH", 0x00010000, off_script, off_featlist, off_lookuplist)
    assert len(head) == hdr
    return head + script + featlist + feature + lookuplist + lookup + sub + cov + pad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ch", default="\u4e2d", help="character the page renders")
    ap.add_argument("--sub", default="\u4e00", help="glyph the vert table maps it to")
    ap.add_argument("--set", default="v", choices=["v", "h", "t", "all"], help="which arm group")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    probe = TTFont(args.base, lazy=True)
    order = probe.getGlyphOrder()
    cmap = probe.getBestCmap()
    upem = probe["head"].unitsPerEm
    n = probe["maxp"].numGlyphs
    g_from = order.index(cmap[ord(args.ch)])
    g_to = order.index(cmap[ord(args.sub)])
    print(f"base upem={upem} glyphs={n} {args.ch!r}={g_from} {args.sub!r}={g_to}")

    arms = []

    def add(aid, fs, note, vmtx=None, gsub=None, hmtx=None, hmtx_fix=None):
        f = TTFont(args.base)
        if vmtx is not None:
            f["vhea"] = raw("vhea", build_vhea(len(vmtx)))
            f["vmtx"] = raw("vmtx", build_vmtx(vmtx))
        if hmtx is not None:
            hm = f["hmtx"].metrics
            for g in f.getGlyphOrder():
                hm[g] = (hmtx[order.index(g)], hm[g][1])
            for gid, adv in (hmtx_fix or {}).items():
                hm[order[gid]] = (adv, hm[order[gid]][1])
            f["hhea"].numberOfHMetrics = n
        if gsub is not None:
            f["GSUB"] = raw("GSUB", gsub)
        fn = f"{aid}.ttf"
        f.save(os.path.join(args.out, fn), reorderTables=True)
        f.close()
        arms.append({"id": aid, "file": fn, "fs": fs, "note": note,
                     "md5": __import__("hashlib").md5(
                         open(os.path.join(args.out, fn), "rb").read()).hexdigest()})

    do_v = args.set in ("v", "all")
    do_h = args.set in ("h", "all")

    # --- V arms: does layout read m_advanceHeights at all? ----------------
    flat256 = [256] * n
    flat512 = [512] * n
    one_tall = list(flat256)
    one_tall[g_from] = 1024
    if do_v:
        add("V0", 24, "base vhea/vmtx untouched (one long metric, 256 units)")
        add("V1", 24, "vmtx replaced: numLongVerMetrics=glyphs, every height 256", vmtx=flat256)
        add("V2", 24, "vmtx: every height 512 (2 em) -- 2x the control if vmtx is read",
            vmtx=flat512)
        add("V3", 24, f"vmtx: all 256 except {args.ch!r}={g_from} at 1024 (4 em)", vmtx=one_tall)

    # --- R arms: a glyph id encoded as an advance height (1 unit = 1/64 px) -
    enc = [256 + g for g in range(n)]          # id readback: (h*64)-256 == glyph id
    well = build_gsub(1, [g_to], [(g_from, g_from, 0)])
    well0 = build_gsub(1, [0], [(g_from, g_from, 0)])
    desc_pad = build_gsub(1, [g_to], [(10, 5, 0)], pad=struct.pack(">H", g_to) * 65532)
    wrap_pad = build_gsub(1, [g_to], [(0x8000, 0xFFFF, 0)],
                          pad=struct.pack(">H", g_to) * 32768)
    if do_v:
        add("R0", 4, "vmtx encodes 256+glyphid; GSUB well formed, substitute 0 (no sub)",
        vmtx=enc, gsub=well0)
        add("R1", 4, f"vmtx encodes 256+glyphid; GSUB well formed {g_from}->{g_to}",
            vmtx=enc, gsub=well)
        add("R2", 4, "same vmtx; GSUB coverage descending 10..5 with a 65532-word pad of "
                     f"{g_to} after substitute[] (OOB shape, reads stay in bounds)",
            vmtx=enc, gsub=desc_pad)
        add("R3", 4, "same vmtx; GSUB coverage wrapping 0x8000..0xFFFF with a 32768-word "
                     f"pad of {g_to} (keys cannot hit {g_from})", vmtx=enc, gsub=wrap_pad)
    # --- H arms: the advance comes from hmtx on this layout (measured, V2) --
    if do_h:
        one_wide = list(flat256)
        one_wide[g_from] = 512
        add("Hx", 24, f"hmtx: all 256 except {args.ch!r}={g_from} at 512 (2 em), GSUB untouched",
            hmtx=one_wide)
        encw = [256 + g for g in range(n)]
        add("H0", 4, "hmtx encodes 256+glyphid; GSUB untouched (base table has no match)",
            hmtx=encw)
        add("H1", 4, f"hmtx encodes 256+glyphid; GSUB well formed {g_from}->{g_to}",
            hmtx=encw, gsub=well)
        add("H2", 4, "same hmtx; GSUB coverage descending 10..5 with a 65532-word pad "
                     f"of {g_to} (OOB shape, reads in bounds)", hmtx=encw, gsub=desc_pad)
        add("H3", 4, "same hmtx; GSUB coverage wrapping 0x8000..0xFFFF with a 32768-word "
                     f"pad of {g_to} (keys cannot hit {g_from})", hmtx=encw, gsub=wrap_pad)
        add("H4", 4, f"hmtx encodes 256+glyphid; GSUB well formed {g_from}->60000 "
                     "(past numGlyphs: what a huge substituted id does)", hmtx=encw,
            gsub=build_gsub(1, [60000], [(g_from, g_from, 0)]))
        add("H5", 256, f"hmtx encodes 256+glyphid at font-size 256px (1 unit = 1px); "
                       f"GSUB well formed {g_from}->{g_to}", hmtx=encw, gsub=well)
        add("H6", 256, f"same, {g_from}->7100 (a second in-range target: 7356 px)",
            hmtx=encw, gsub=build_gsub(1, [7100], [(g_from, g_from, 0)]))
        add("H7", 256, f"same, {g_from}->40000 (a high in-range target: 40256 px)",
            hmtx=encw, gsub=build_gsub(1, [40000], [(g_from, g_from, 0)]))

    # --- T arms: where does the glyph-id / advance funnel stop? ------------
    if args.set in ("t", "all"):
        encw = [256 + g for g in range(n)]
        add("T1", 256, f"hmtx 256+id; GSUB well formed {g_from}->20000 (advance 20256)",
            hmtx=encw, gsub=build_gsub(1, [20000], [(g_from, g_from, 0)]))
        add("T2", 256, "same ids; hmtx[20000] forced to 40000 (advance above 32767, id 20000)",
            hmtx=encw, hmtx_fix={20000: 40000},
            gsub=build_gsub(1, [20000], [(g_from, g_from, 0)]))
        add("T3", 256, f"hmtx 256+id; GSUB well formed {g_from}->32000 (advance 32256)",
            hmtx=encw, gsub=build_gsub(1, [32000], [(g_from, g_from, 0)]))
        add("T4", 32, "same ids; hmtx[20000]=40000 at font-size 32px (40000 units = 5000 px)",
            hmtx=encw, hmtx_fix={20000: 40000},
            gsub=build_gsub(1, [20000], [(g_from, g_from, 0)]))
        add("T5", 32, "same ids; hmtx[20000]=20256 at font-size 32px (2532 px) -- size control",
            hmtx=encw, hmtx_fix={20000: 20256},
            gsub=build_gsub(1, [20000], [(g_from, g_from, 0)]))
        for tag, adv in (("B1", 32767), ("B2", 32768)):
            add(tag, 256, f"same ids; hmtx[20000]={adv} at font-size 256px "
                          f"({adv} px, the boundary probe)", hmtx=encw,
                hmtx_fix={20000: adv}, gsub=build_gsub(1, [20000], [(g_from, g_from, 0)]))

    # --- C arm: the real thing, unpadded, expected to abort under ASAN ------
    add("C1", 4, "same vmtx/hmtx; GSUB coverage descending 10..5, NO pad -- reads past "
                 "the table copy (docs/99 crash, expected)",
        vmtx=None if do_h else enc, hmtx=enc if do_h else None,
        gsub=build_gsub(1, [g_to], [(10, 5, 0)]))

    man = {"base": os.path.basename(args.base), "upem": upem, "glyphs": n,
           "ch": args.ch, "g_from": g_from, "sub": args.sub, "g_to": g_to, "arms": arms}
    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump(man, fh, indent=1)
    for a in arms:
        print(f"{a['id']:3s} fs={a['fs']:2d} {a['md5']} {a['note']}")


if __name__ == "__main__":
    main()
