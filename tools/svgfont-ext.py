#!/usr/bin/env python3
"""Generate the external-SVG half of the SVG-font corpus.

Each file is the document that `@font-face { src: url(<file>#f1) format(svg) }` makes
CachedSVGFont fetch: it builds an SVGDocument from the bytes
(loader/cache/CachedSVGFont.cpp:88), finds the <font id="f1"> by fragment
(getSVGFontById, :107), and hands it to convertSVGToOTFFont (:101).

One file per arm so a crash names its input through the page's BEG beacon.
"""
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "research" / "svgfont"
SQUARE = "M0 0 L1000 0 L1000 800 L0 800 Z"


def doc(body: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0">\n'
            '  <defs>\n' + body + '\n  </defs>\n</svg>\n')


def font(face: str | None, glyphs: str, extra: str = "") -> str:
    s = '<font id="f1" horiz-adv-x="1000">'
    if face:
        s += face
    s += extra + glyphs + "</font>"
    return s


def big_path(n: int) -> str:
    parts = ["M0 0"]
    for i in range(n):
        parts.append("L%d %d" % (i % 1000, (i * 7) % 800))
    return " ".join(parts) + " Z"


def main() -> None:
    files = {}

    files["x_R2-ext.svg"] = doc(font(
        '<font-face font-family="Zzext2" units-per-em="1000" ascent="800" descent="200"/>',
        '<missing-glyph horiz-adv-x="500" d="M0 0 L500 0 L500 500 Z"/>'
        '<glyph unicode="A" horiz-adv-x="1000" d="%s"/>' % SQUARE))

    # 20000 line segments in one glyph: one charstring of ~160 KB.
    files["x_X1-huge.svg"] = doc(font(
        '<font-face font-family="Zzx1" units-per-em="1000" ascent="800" descent="200"/>',
        '<glyph unicode="A" horiz-adv-x="1000" d="%s"/>' % big_path(20000)))

    # 33000 glyphs: the cmap format-4 subtable passes 64 KiB, where its declared length is
    # `clampTo<uint16_t>` (SVGToOTFFontConversion.cpp:345).
    g = []
    for i in range(33000):
        cp = 0x100 + i
        g.append('<glyph unicode="&#x%X;" horiz-adv-x="%d" d="M0 0 L500 0 L500 700 L0 700 Z"/>'
                 % (cp, 400 + i % 601))
    files["x_X2-many.svg"] = doc(font(
        '<font-face font-family="Zzx2" units-per-em="1000" ascent="800" descent="200"/>',
        "".join(g)))

    # No <font-face> child at all: m_fontFaceElement is null, so units-per-em is 1 and the CFF
    # Name string is empty (appendCFFTable :599-609).
    files["x_X3-noface.svg"] = doc(font(
        None, '<glyph unicode="A" horiz-adv-x="1000" d="%s"/>' % SQUARE))

    # Malformed XML: TextResourceDecoder::sawError() -> the conversion is never attempted.
    files["x_X4-badxml.svg"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg"><defs><font id="f1" '
        'horiz-adv-x="1000"><font-face font-family="Zzx4" units-per-em="1000"/>'
        '<glyph unicode="A" d="M0 0 L1000 0')

    # Duplicate unicode attributes: three glyphs claim "A", which is what U1 tests in-document.
    files["x_X5-dup.svg"] = doc(font(
        '<font-face font-family="Zzx5" units-per-em="1000" ascent="800" descent="200"/>',
        '<glyph unicode="A" d="%s"/><glyph unicode="A" horiz-adv-x="300" d="M0 0 L300 0 L300 300 Z"/>'
        '<glyph unicode="A" horiz-adv-x="700" d="M0 0 L700 0 L700 700 Z"/>' % SQUARE))

    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
        print("%-16s %8d B" % (name, len(text.encode())))


if __name__ == "__main__":
    main()
