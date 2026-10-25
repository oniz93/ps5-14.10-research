#!/usr/bin/env python3
"""Generate a format-aware image corpus for the ASAN MiniBrowser.

Targets the four decoders WebKit implements in-tree (BMP, ICO, WBMP, GIF). PNG/JPEG/WebP/AVIF go
through system libraries, so a bug there would not be a WebKit bug; they are included only as a
control.

The mutations are aimed at the fields each decoder performs arithmetic or indexing on, not at random
bytes:

  BMP  - width/height sign and magnitude (the classic `width * bpp / 8` overflow), bpp values the
         decoder may not expect, compression values that change the row layout, dataOffset past EOF,
         and a palette that is shorter than the bit depth implies.
  ICO  - directory count, entry offsets and sizes (a real icon is a directory pointing at embedded
         BMP/PNG data, so almost every field is an index into the file).
  WBMP - the multi-byte varint width/height: a long run of 0x80 continuation bytes is the shape that
         overflows naive shift-and-or readers.
  GIF  - LZW minimum code size (0..12 including the invalid range), sub-block lengths that exceed the
         remaining data, truncated streams, and global colour table sizes.

Usage: img_corpus.py <outdir> [per-format]
"""

import os
import random
import struct
import sys


def w(path, data):
    with open(path, "wb") as f:
        f.write(data)


# --------------------------------------------------------------------------- seeds

def bmp(width=2, height=2, bpp=24, palette=0, compression=0, px=None, data_off=None):
    """Minimal BMP. Rows are padded to 4 bytes."""
    if bpp == 24:
        row = bytes([10, 20, 30]) * width
        stride = (width * 3 + 3) & ~3
        row += b"\x00" * (stride - len(row))
        pixels = row * abs(height)
    elif bpp == 8:
        stride = (width + 3) & ~3
        pixels = (b"\x00" * (stride - width) + b"\x00" * width) * abs(height)
    else:  # 1bpp
        stride = (((width + 7) // 8) + 3) & ~3
        pixels = (b"\x00" * stride) * abs(height)

    pal = b""
    if palette:
        for i in range(palette):
            pal += bytes([i, i, i, 0])

    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, bpp, compression,
                      len(pixels), 2835, 2835, palette, 0)
    off = data_off if data_off is not None else 14 + len(dib) + len(pal)
    file_size = off + len(pixels)
    hdr = b"BM" + struct.pack("<IHHI", file_size, 0, 0, off)
    return hdr + dib + pal + pixels


def wbmp(width=4, height=4, typ=0):
    def mb(v):
        out = [v & 0x7F]
        v >>= 7
        while v:
            out.insert(0, (v & 0x7F) | 0x80)
            v >>= 7
        return bytes(out)
    bits = ((width + 7) // 8) * height
    return bytes([typ, 0]) + mb(width) + mb(height) + b"\x00" * bits


def ico_from_bmp(width=2, height=2):
    """A real ICO wraps a BMP with a doubled height and no bottom-up padding rules of its own."""
    inner = bmp(width, height * 2, 24)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 24, 0,
                      width * height * 4, 2835, 2835, 0, 0)
    data = dib + inner[54:]
    entry = struct.pack("<BBBBHHII", width & 0xFF, height & 0xFF, 0, 0, 1, 24, len(data), 22)
    return b"\x00\x00\x01\x00\x01\x00" + entry + data


GIF1 = (b"GIF89a" + struct.pack("<HHBBB", 1, 1, 0x80, 0, 0) + b"\x00\x00\x00\xff\xff\xff"
        + b"\x2c" + struct.pack("<HHHHB", 0, 0, 1, 1, 0) + b"\x02\x02\x44\x01\x00\x3b")

GIF_ANIM = (b"GIF89a" + struct.pack("<HHBBB", 4, 4, 0x80, 0, 0) + b"\x00\x00\x00\xff\xff\xff"
            + b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
            + b"\x2c" + struct.pack("<HHHHB", 0, 0, 4, 4, 0) + b"\x02\x03\x84\x8f\x00"
            + b"\x2c" + struct.pack("<HHHHB", 0, 0, 4, 4, 0) + b"\x02\x03\x84\x8f\x00"
            + b"\x3b")


# --------------------------------------------------------------------------- mutations

def mutate_bmp(rng, base):
    variants = []

    # Field-targeted: each of these changes one number the decoder divides by, multiplies, or seeks with.
    for width, height in [(0, 2), (2, 0), (-2, -2), (65536, 2), (2, 65536),
                          (0x7FFFFFFF, 1), (1, 0x7FFFFFFF), (0x7FFF, 0x7FFF), (1, -0x7FFFFFFF)]:
        v = bytearray(base)
        struct.pack_into("<ii", v, 18, width, height)
        variants.append(("wh", bytes(v)))

    for bpp in [0, 1, 4, 8, 16, 24, 32, 64, 0xFFFF]:
        v = bytearray(base)
        struct.pack_into("<H", v, 28, bpp)
        variants.append((f"bpp{bpp}", bytes(v)))

    for comp in [0, 1, 2, 3, 4, 5, 6, 0xFFFF]:
        v = bytearray(base)
        struct.pack_into("<I", v, 30, comp)
        variants.append((f"comp{comp}", bytes(v)))

    for off in [0, 14, len(base) - 1, len(base), len(base) + 4096, 0x7FFFFFFF]:
        v = bytearray(base)
        struct.pack_into("<I", v, 10, off)
        variants.append((f"off{off}", bytes(v)))

    for i in range(10):
        v = bytearray(base)
        pos = rng.randrange(len(v))
        v[pos] ^= 1 << rng.randrange(8)
        variants.append((f"flip{i}", bytes(v)))

    for cut in [14, 20, 40, len(base) // 2]:
        variants.append((f"trunc{cut}", base[:cut]))

    return variants


def mutate_wbmp(rng, base):
    variants = []
    # Continuation-byte runs: the shape that overflows shift-and-or varint readers.
    for n in [1, 2, 4, 5, 8, 16, 64]:
        body = b"\x80" * n + b"\x00"
        variants.append((f"varint{n}", bytes([0, 0]) + body + body + b"\x00" * 8))
        variants.append((f"varintw{n}", bytes([0, 0]) + body + b"\x04" + b"\x00" * 8))
    for typ in [0, 1, 2, 0xFF]:
        v = bytearray(base)
        v[0] = typ
        variants.append((f"type{typ}", bytes(v)))
    # Declared size far larger than the pixel data present.
    variants.append(("bigdim", bytes([0, 0]) + b"\x84\x00" + b"\x84\x00" + b"\x00" * 4))
    for cut in [1, 2, 3, 5]:
        variants.append((f"trunc{cut}", base[:cut]))
    for i in range(8):
        v = bytearray(base)
        v[rng.randrange(len(v))] ^= 0xFF
        variants.append((f"flip{i}", bytes(v)))
    return variants


def mutate_ico(rng, base):
    variants = []
    for count in [0, 1, 2, 0xFFFF]:
        v = bytearray(base)
        struct.pack_into("<H", v, 4, count)
        variants.append((f"count{count}", bytes(v)))
    for off in [0, 6, 22, len(base) - 1, len(base), len(base) + 1024, 0x7FFFFFFF]:
        v = bytearray(base)
        struct.pack_into("<I", v, 18, off)
        variants.append((f"offset{off}", bytes(v)))
    for size in [0, 1, 0x7FFFFFFF, len(base)]:
        v = bytearray(base)
        struct.pack_into("<I", v, 14, size)
        variants.append((f"bytes{size}", bytes(v)))
    for w, h in [(0, 0), (255, 255), (1, 255)]:
        v = bytearray(base)
        v[6] = w
        v[7] = h
        variants.append((f"dim{w}x{h}", bytes(v)))
    for i in range(8):
        v = bytearray(base)
        v[rng.randrange(len(v))] ^= 1 << rng.randrange(8)
        variants.append((f"flip{i}", bytes(v)))
    return variants


def mutate_gif(rng, base):
    variants = []
    # LZW minimum code size sits right after the image descriptor separator; values above 8 are invalid.
    idx = base.find(b"\x2c")
    if idx != -1:
        mcs = idx + 10
        for size in [0, 1, 2, 7, 8, 9, 11, 12, 255]:
            v = bytearray(base)
            if mcs < len(v):
                v[mcs] = size
                variants.append((f"mcs{size}", bytes(v)))
    # Sub-block lengths that overrun the remaining data.
    if idx != -1:
        sb = idx + 11
        for size in [0, 1, 0xFF, 0x7F]:
            v = bytearray(base)
            if sb < len(v):
                v[sb] = size
                variants.append((f"sub{size}", bytes(v)))
    for w, h in [(0, 0), (0xFFFF, 0xFFFF), (1, 0xFFFF)]:
        v = bytearray(base)
        struct.pack_into("<HH", v, 6, w, h)
        variants.append((f"dim{w}x{h}", bytes(v)))
    for packed in [0x00, 0x80, 0xF7, 0xFF]:
        v = bytearray(base)
        v[10] = packed
        variants.append((f"packed{packed:02x}", bytes(v)))
    for cut in [6, 13, len(base) // 2, len(base) - 2]:
        variants.append((f"trunc{cut}", base[:cut]))
    for i in range(12):
        v = bytearray(base)
        v[rng.randrange(len(v))] ^= 1 << rng.randrange(8)
        variants.append((f"flip{i}", bytes(v)))
    return variants


def main():
    out = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    os.makedirs(out, exist_ok=True)
    rng = random.Random(1400)

    groups = []

    bmp_seeds = [bmp(2, 2, 24), bmp(1, 1, 24), bmp(17, 5, 24), bmp(3, 3, 8, palette=16),
                 bmp(5, 5, 1, palette=2), bmp(4, 4, 24, data_off=1000)]
    for i, s in enumerate(bmp_seeds):
        w(os.path.join(out, f"bmp-seed{i}.bmp"), s)
        for tag, d in mutate_bmp(rng, s):
            groups.append((f"bmp-{i}-{tag}.bmp", d))

    wbmp_seeds = [wbmp(4, 4), wbmp(1, 1), wbmp(100, 3)]
    for i, s in enumerate(wbmp_seeds):
        w(os.path.join(out, f"wbmp-seed{i}.wbmp"), s)
        for tag, d in mutate_wbmp(rng, s):
            groups.append((f"wbmp-{i}-{tag}.wbmp", d))

    ico_seeds = [ico_from_bmp(2, 2), ico_from_bmp(16, 16)]
    for i, s in enumerate(ico_seeds):
        w(os.path.join(out, f"ico-seed{i}.ico"), s)
        for tag, d in mutate_ico(rng, s):
            groups.append((f"ico-{i}-{tag}.ico", d))

    for i, s in enumerate([GIF1, GIF_ANIM]):
        w(os.path.join(out, f"gif-seed{i}.gif"), s)
        for tag, d in mutate_gif(rng, s):
            groups.append((f"gif-{i}-{tag}.gif", d))

    if limit:
        groups = groups[:limit]

    for name, data in groups:
        w(os.path.join(out, name), data)

    print(f"wrote {len(groups)} mutated files plus {len(bmp_seeds) + len(wbmp_seeds) + len(ico_seeds) + 2} seeds to {out}")
    by_fmt = {}
    for name, _ in groups:
        by_fmt[name.split("-")[0]] = by_fmt.get(name.split("-")[0], 0) + 1
    print("by format:", by_fmt)


if __name__ == "__main__":
    main()
