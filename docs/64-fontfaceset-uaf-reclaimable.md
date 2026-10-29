# FontFaceSet::load() UAF: the first reclaimable, JIT-free memory bug on this target

Credited to ZigZagBoi's repo (`docs/WEBKIT_FINDINGS.md`, Finding 12, traced to their issue #143). This document is
our reproduction from Sony's own drop, because it changes the picture for us: unlike the canvas UAF and the
`CachedString` UAF, this one frees a **plain FastMalloc object**, so the slot can be taken by JS-controlled data.

## The bug

`FontFaceSet::load()` (`Source/WebCore/css/FontFaceSet.cpp`) does:

```cpp
m_backing->updateStyleIfNeeded();
auto matchingFacesResult = m_backing->matchingFacesExcludingPreinstalledFonts(font, text);
auto matchingFaces = matchingFacesResult.releaseReturnValue();     // Vector<std::reference_wrapper<CSSFontFace>>

for (auto& face : matchingFaces)
    face.get().load();                                             // :169  runs script

for (auto& face : matchingFaces) {
    if (face.get().status() == CSSFontFace::Status::Failure)       // :196  reads the same raw pointers
        promise.reject(NetworkError);
    ...
}
```

The vector holds `std::reference_wrapper<CSSFontFace>` — raw pointers — while the first loop can run script. The
script runs because resolving a promise with the `FontFace` triggers thenable assimilation, which reads
`FontFace.prototype.then`; a getter there removes the `<style>` that owns the face, and the face is destroyed. The
second loop then dereferences freed memory.

## Our reproduction, from Sony's drop

Trigger: `FontFace('a', local(...), {unicodeRange:'U+0041'})` added to `document.fonts`, a `then` getter that
removes a `<style>` containing `@font-face { font-family: x; ... }`, then
`document.fonts.load('1em a, x', 'AB')`.

ASAN, local build from the drop, `ENABLE_JIT=OFF`:

```
ERROR: AddressSanitizer: heap-use-after-free
READ of size 1
  #0 WebCore::CSSFontFace::status() const            CSSFontFace.h:104
  #1 WebCore::FontFaceSet::load(...)                 FontFaceSet.cpp:196
  #2 jsFontFaceSetPrototypeFunction_load             JSFontFaceSet.cpp:490
freed by:
  #1 WTF::fastFree                                   FastMalloc.cpp:267
  #2 WebCore::CSSFontFace::operator delete           CSSFontFace.h:61
  #4 WTF::RefCounted<CSSFontFace>::deref()           RefCounted.h:190
0x6100000466c2 is 130 bytes inside of 192-byte region
```

Three facts make this the best lead in the programme:

1. **The object is 192 bytes and allocated by plain `fastFree`.** Not `WTF_MAKE_ISO_ALLOCATED`, so the IsoHeap
   wall that killed the canvas UAF does not apply: any 192-byte JS allocation can take the slot.
2. **The free and the use are both inside one synchronous call.** The getter runs at `:169`, the stale read is at
   `:196`. A spray performed *in the getter* therefore lands in the window without any timing guesswork — this is
   the canvas bug's re-entrancy, but with a reclaimable class.
3. **The stale read is a status byte at offset 0x82**, and the code branches on it. If the slot is reclaimed with
   controlled bytes, the branch is ours to choose: `Failure` rejects the promise, `Success`/`Loading` continue into
   `existingWrapper()` and `wrapper()`, which are further raw-pointer dereferences of the same fake object.

## What this is not yet

A status-byte branch is not kernel access. The path from here is the same as any type confusion: reclaim, make the
fake object's fields point where we want, and use `existingWrapper()`/`wrapper()` to obtain a JS object whose
backing C++ structure we influence. Whether that yields a read/write primitive depends on what those calls do with
the fake fields, which the source can answer before another console cycle is spent.

## Status

* ASAN: confirmed (above).
* Console: the Guide app is stuck on its own menu with a dead WebProcess, so `c039` is staged but not yet run.
  ZigZagBoi measured the crash on 14.10 hardware, so the applicability is not in doubt; running it ourselves is
  confirmation, not discovery.
* Reclaim experiment in flight: spray 2000 x `ArrayBuffer(192)` inside the getter, filled with 0x00, 0x03 and 0xff,
  and observe whether the process survives and whether the promise settles instead of dying. A settle means the
  slot was taken and the byte is ours.
