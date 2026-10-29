# FontFace is not auditable from the drop: the GSUB parser is not WebKit's

Opening the font surface produced a provenance correction that matters more than any bug would have.

## What WebKit actually contains

`Source/WebCore/platform/graphics/harfbuzz/` holds only glue:
`ComplexTextControllerHarfBuzz.cpp`, `DrawGlyphsRecorderHarfBuzz.cpp`, `FontDescriptionHarfBuzz.cpp`,
`HbUniquePtr.h`. There is no GSUB/GPOS table parser in the tree. `grep -rl GSUB` over `Source/WebCore` and
`Source/WTF` returns four files, none of them a layout-table parser: `SVGToOTFFontConversion.cpp` (writes GSUB
when synthesising an OTF from SVG), `OpenTypeVerticalData.cpp` (reads vertical metrics), the harfbuzz glue, and
`FontInterrogation.h` (Apple port).

The OpenType layout tables — GSUB, GPOS, the coverage/class-def lookups, all of it — are parsed inside the
**system harfbuzz shared library**, which WebKit links against dynamically.

## Why that invalidates the earlier finding

The previously recorded result — "OpenType GSUB OOB confirmed under ASAN, silent on retail" — was produced by
the board, which links `harfbuzz-11.5.1` (Fedora 43). The console runs Sony's Prospero build, whose harfbuzz is
a 2023-era fork of a much older release, and we have no copy of it.

So that result was never a statement about the console:

* the crashing code is a third-party library we do not have, at a version the console does not share;
* "silent on retail" is fully explained by the version difference, not by a mitigation;
* no amount of reading the Sony drop can find or rule out bugs in that library, because the drop does not
  contain its parser.

This is the same class of error as the earlier `cmakeconfig.h` provenance mistake: a result attributed to the
target when it belonged to our harness. Recording it as a correction rather than quietly dropping the line.

## What remains auditable on this surface

Only the scheduling code that lives in WebKit — `CSSFontFace::setStatus` and its `Status` transitions,
`CSSFontFace::fontLoaded`, the `FontFace`/`FontFaceSet` promise machinery. `setStatus` is the one we already know
had a `Ref` fix land upstream, and the drop contains it, so the interesting cases there are the re-entrancy ones:
`client.fontStateChanged(*this, m_status, newStatus)` at `CSSFontFace.cpp:592` runs client code *before*
`m_status = newStatus` at line 595, i.e. a client callback observes the old status and can re-enter. That is worth
a read, but it is a scheduling/lifetime surface, not a parser.

## Consequence for the programme

The reading programme must stay inside code Sony ships as source. That excludes harfbuzz and any other system
library reached through a shared-object boundary, which also means font-table fuzzing on the board is only ever
evidence about the board.

Surfaces that remain both in-tree and JIT-independent: Canvas 2D image paths (closed benign), Streams (closed),
CSSOM (one confirmed DoS), DOM/HTML parser interplay, SVG, serialisation (`SerializedScriptValue`), and
`structuredClone`. The last two are attractive because the code is dense, in-tree, and the known races there
only die because SharedArrayBuffer is absent rather than because the code is clean.
