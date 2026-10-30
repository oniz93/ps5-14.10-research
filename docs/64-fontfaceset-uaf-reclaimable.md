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

## Reclaim experiments

Spraying 2000 x `ArrayBuffer(192)` inside the getter, three fills (0x00, 0x03, 0xff), and a no-spray control.

**With ASAN quarantine on** (default `run_asan_page.sh`): every mode reports the same
`heap-use-after-free` at `CSSFontFace.h:104`. Nothing can reclaim, because the quarantine parks freed memory.
That is a property of the instrument, not of the bug.

**With quarantine off** (`run_nq.sh`): the report changes to `heap-buffer-overflow`, and the stack moves one frame
earlier — the stale dereference now happens inside `face.get().load()` itself:

```
READ of size 1 at 0x...4c2
  #0 WebCore::CSSFontFace::status()   CSSFontFace.h:104
  #1 WebCore::CSSFontFace::pump()     CSSFontFace.cpp:646
  #2 WebCore::CSSFontFace::load()     CSSFontFace.cpp:703
  #3 WebCore::FontFaceSet::load()     FontFaceSet.cpp:169
0x...4c2 is located 194 bytes after 192-byte region
allocated by: fastMalloc -> CSSFontFace::operator new -> CSSFontFace::create <- FontFace::FontFace
```

Two readings, both useful:

1. **The slot is reusable.** With the quarantine gone the region is taken immediately — the wall the canvas UAF
   hit does not exist here.
2. **The next occupant is another `CSSFontFace`, not our ArrayBuffer.** The allocation stack for the live region
   the fault lands next to is `FontFace::FontFace`, i.e. a JS `new FontFace(...)`. Our 192-byte ArrayBuffers do not
   win the class; font-face allocations do, because removing the style and pumping the load path creates more of
   them.

So the groom has to be ordered around that: either allocate controlled 192-byte objects *after* the font machinery
has finished allocating its own, or make the object that lands in the slot a `CSSFontFace` whose fields we can
influence through the descriptors we pass to `new FontFace(...)`. The fault landing 194 bytes past a live 192-byte
region (rather than at a fixed offset inside a known object) says the current spray is nowhere near the slot yet.

## CORRECTION: the spray never reclaimed anything; the crash was switched off by a different edit

The experiments below are recorded as they happened, then corrected here, because the correction changes what we
know: **no reclaim has been demonstrated.**

The page that produced "no crash, RESOLVED n=2" differed from the crashing page in three ways at once: it sprayed
strings, it dropped `document.fonts.delete(this)` from the getter, and it dropped the forced layout
(`document.body.offsetHeight`). A control run that keeps the dropped-call change and replaces 3000 strings with
3000 plain numbers — no fastMalloc allocation at all — also returns `RESOLVED n=2` with no sanitizer report.

So the absent crash is a property of **not calling `delete(this)` / not forcing layout** in the getter, not of the
spray. The string spray, at every length tried (160, 168, 176, 184) and every fill (0, 3, 4, 255), never won the
slot. The single-variable rule applies: only a run that changes one thing can attribute a result.

What survives from this section: the UAF itself (confirmed under ASAN from the drop), the 192-byte plain-fastMalloc
class, and the fact that the crash is reachable or not depending on what the getter does — which is itself a
usable oracle for building the real groom.

## The string-class spray (confounded — see the correction above)

A JS string of 176 characters is a `StringImpl` whose header plus inline 8-bit characters lands in the 192-byte
class, with attacker-chosen bytes — including offset 0x82, where `status()` reads. Spraying 4000 of them inside the
getter, after `style.remove()`:

| fill byte | result |
|---|---|
| 3 (`Success`) | `RESOLVED n=2`, no sanitizer report, process alive |
| 0 (`Pending`) | `RESOLVED n=2`, no sanitizer report, process alive |
| 255 | `RESOLVED n=2`, no sanitizer report, process alive |
| 4 (`Failure`) — earlier run | `RESOLVED n=2`, no sanitizer report, process alive |

The crash is gone, which is progress: the stale pointer now lands on valid memory and the call completes. But the
outcome is **identical for every fill byte**, and `Failure` would have taken the reject branch. So the occupant is
not our string. Something the font machinery itself allocated took the slot, and we are aliasing a real
`CSSFontFace` rather than one we control.

That is a benign alias — a correctness problem, not a primitive — and it is the same shape as the canvas result:
a genuine UAF that survives, with the reclaim going to the subsystem's own allocations rather than to ours.

## Isolated test: the spray does not change the crash

One page, three toggles (`l` = forced layout, `d` = `document.fonts.delete(this)`, `s` = string spray count), run with
quarantine off so a freed slot can be reused:

| config | sanitizer | beacons |
|---|---|---|
| `l=1&d=1&s=0` | `heap-buffer-overflow` at `CSSFontFace.h:104` | `layout deleted getter-returning` |
| `l=1&d=1&s=3000` | `heap-buffer-overflow` at `CSSFontFace.h:104` | `layout deleted getter-returning` |
| `l=1&d=0&s=3000` (earlier) | none | `... RESOLVED n=2` |
| `l=0&d=0&s=0`, numbers only (earlier) | none | `... RESOLVED n=2` |

Two conclusions, both negative and both worth having:

1. The crash is controlled by `delete(this)` / forced layout, not by any allocation we perform. With those calls
   present the bug fires every time; without them it never fires, whatever the heap is doing.
2. **No string length or fill has yet won the slot.** 168 characters with fill 4 in the crashing configuration still
   faults identically to no spray at all.

So the next variable to sweep is the allocation *class*, not the count: the report must be made to change its
`SUMMARY` line (or its fault address) for a spray to count as a reclaim.

## Status

* ASAN: confirmed (above).
* Console: the Guide app is stuck on its own menu with a dead WebProcess, so `c039` is staged but not yet run.
  ZigZagBoi measured the crash on 14.10 hardware, so the applicability is not in doubt; running it ourselves is
  confirmation, not discovery.
* Reclaim experiment in flight: spray 2000 x `ArrayBuffer(192)` inside the getter, filled with 0x00, 0x03 and 0xff,
  and observe whether the process survives and whether the promise settles instead of dying. A settle means the
  slot was taken and the byte is ours.
