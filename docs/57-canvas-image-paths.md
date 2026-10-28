# Canvas image paths: a divide-by-zero that survives every guard

Third surface. Recorded because the arithmetic is unchecked at every call site, with the honest caveat that the
likely outcome is a rejected promise rather than memory corruption — the probe decides.

## Cleared first: ImageData allocation

Every `ImageData` constructor funnels through `computeDataSize` with `hasOverflowed()` and a
`dataSize != byteArray->length()` cross-check (`html/ImageData.cpp:67-95`), so the classic `width * height * 4`
overflow is closed. No finding there.

## The defect: `outputSizeForSourceRectangle`

```cpp
static IntSize outputSizeForSourceRectangle(IntRect sourceRectangle, ImageBitmapOptions& options)
{
    auto outputWidth = [&] () -> int {
        if (options.resizeWidth)  return options.resizeWidth.value();
        if (options.resizeHeight) return ceil(sourceRectangle.width() * (double)options.resizeHeight.value()
                                              / sourceRectangle.height());   // <- divides by height
        return sourceRectangle.width();
    }();
    auto outputHeight = [&] () -> int {
        if (options.resizeHeight) return options.resizeHeight.value();
        if (options.resizeWidth)  return ceil(sourceRectangle.height() * (double)options.resizeWidth.value()
                                              / sourceRectangle.width());    // <- divides by width
        return sourceRectangle.height();
    }();
    return { outputWidth, outputHeight };
}
```

The only up-front validation is on the *resize* values:

```cpp
if ((options.resizeWidth && options.resizeWidth.value() <= 0) ||
    (options.resizeHeight && options.resizeHeight.value() <= 0))
    return Exception { InvalidStateError, "Invalid resize dimensions"_s };
```

The crop rectangle is never checked. `croppedSourceRectangleWithFormatting` takes the attacker's
`(sx, sy, sw, sh)`, intersects it with the image, and returns whatever falls out — including an empty rect.
`grep isEmpty() html/ImageBitmap.cpp` returns nothing, so no call site guards it.

Result: supply an empty crop rectangle plus exactly one resize dimension and the divisor is zero:

* crop `sh = 0`, options `{resizeHeight: N}` → `ceil(width * N / 0)` → `inf` (or `NaN` when width is 0)
* crop `sw = 0`, options `{resizeWidth: N}` → `ceil(height * N / 0)` → `inf`

`ceil(inf)` is then cast straight to `int`. `static_cast<int>(inf)` is undefined behaviour and yields INT_MIN on
x86, so the downstream `IntSize` carries a large negative dimension.

Note the guard that *looks* like it covers this does not: the zero-dimension check at line 349 requires that
`resizeWidth` **and** `resizeHeight` be absent, and the `!imageSize.width() || !imageSize.height()` check at
line 373 only fires when no crop rect was supplied at all. A crop rect that shrinks to nothing while the source
image has an intrinsic size passes both.

## Honest expectation

Negative dimensions most likely die in `ImageBuffer::create`, producing a rejected promise — i.e. a spec-level
oddity, not a primitive. It is worth one probe because the conversion is UB and the downstream size arithmetic is
not something to assume; but I would not fund a session on it.

## Staged

`c028-createimagebitmap-zero-div.js` — a valid control plus four shapes (zero height, zero width, crop entirely
outside the image, and both resize dimensions given so the division is skipped). Reports resolved dimensions vs
rejection, so it distinguishes "benign rejection" from "survived with a nonsense size".

The manifest now runs `c028`, then `c026b`, then `c027` — the three open candidates, ordered cheapest first.

## Hardware still offline

Console does not answer ping, BC-250 SSH times out, `guide_lab.py` is not running and the capture dongle is
absent (index 0 is `OBS Virtual Camera`), so nothing can be validated yet. When the hosts return, the local ASAN
build is the better first stop for `c026b`/`c027` — same tree, JIT off, sanitizer attached — and the console is
needed only for `c028`, which the ASAN build can answer too.
