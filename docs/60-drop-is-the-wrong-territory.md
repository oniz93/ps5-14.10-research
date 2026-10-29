# The drop is a map of the wrong territory

Five surfaces audited this round produced four clean negatives, one benign bug, and a pattern that explains the
whole programme's ceiling. This document states it, because it changes what the remaining options are worth.

## The pattern

Every target-specific parser on this console lives outside Sony's OSS drop. The drop contains WebKit's generic
code plus thin glue that calls into closed system libraries:

| surface | what the drop contains | where the parsing actually happens |
|---|---|---|
| fonts / GSUB | `ComplexTextControllerHarfBuzz.cpp` and three peers | system **harfbuzz** (board has 11.5.1; console has a 2023-era fork) |
| MSE / EME | `SourceBufferPrivatePlayStation.cpp:64` — `m_playstation->append(data->data(), data->size())` | Sony's closed media library |
| images | `ImageDecoder` glue | system libpng/libjpeg/libwebp |
| XML | `XMLDocumentParserLibxml2.cpp` | system **libxml2** |
| text/i18n | `TextBreakIteratorICU.cpp` | system **ICU** |

The glue is a handful of lines each; the state machines, the length arithmetic, the table lookups — the parts that
break — are in shared objects we cannot read and cannot build.

## What that implies

The readable code is the well-fuzzed code. WebKit's generic DOM/CSS/JS surfaces have had two decades of fuzzing
by Apple, Google and the security community; we sampled Streams, resizable ArrayBuffers, Canvas image paths, the
DOM/History re-entrancy cases and `SerializedScriptValue`, and found: two DoS-class bugs (TransformStream null
deref, the CSSOM `@page` null deref), one alias-only UAF blocked by IsoHeap, and nothing memory-unsafe.

The unreadable code is the target-specific code. That is where a 2026 console most plausibly still has bugs — and
it is exactly the part the drop does not describe.

This is not a claim that WebKit is clean. It is a claim that a source-level audit of the drop has a low ceiling on
*this* target, and that the ceiling is structural rather than a matter of more reading.

## The in-tree Sony-specific code, actually read

`page/playstation/` is the only substantial target-specific code in the tree. Seven files, ~30 KB total:

* `CursorNavigation.cpp` (12.6 KB) — spatial navigation for the D-pad/arrow cursor.
* `FocusControllerPlayStation.cpp`, `EventHandlerPlayStation.cpp`, `ChromePlayStation.cpp` — small.
* `ResourceUsage{Overlay,Thread}PlayStation.cpp` — debug only.

Findings: `downcast<Element>(node)` at :162 is guarded by `isElementNode()` at :159; the two `downcast<Element>`
sites at :250/:272 are guarded by `is<Element>`; `parentContainer()` and `startingRectForHitTestResult()` are
correct.

One latent defect: `cursorPositionAtCandidate` does

```cpp
if (candidate.focusableNode->hasTagName(areaTag)) {
    HTMLAreaElement* area = static_cast<HTMLAreaElement*>(candidate.focusableNode);
    LayoutPoint pos = area->computeRect(area->imageElement()->renderer()).center();
```

and `HTMLAreaElement::imageElement()` returns nullptr when the `<area>` has no `<map>` parent or the map has no
`<img usemap>`. The dereference is unchecked — but `HTMLAreaElement::isFocusable()` (line 218) returns false when
`imageElement()` is null, so an area without an image can never become a focus candidate. The only way in is to
remove the image between candidate collection and position computation, and both happen inside one synchronous
`moveCursor()` pass with no script execution in between. Latent, not reachable. Recorded so it is not
re-discovered as a find.

## What is left, honestly priced

1. **Game-save entry** — a modified save starts a TCP listener and hands over `make_syscall`. Requires a game with
   the Artemis/Lua engine *on 14.10*. Acquiring one requires PSN, and the PSN floor is 14.20, so this is closed by
   policy, not by technique. This remains the only known route to a syscall primitive.
2. **Another generic WebKit bug** — possible, but every sampled surface closed cleanly, and the one live class we
   confirmed (TransformStream) is a null deref. Continuing is cheap per surface but the hit rate for a
   *memory-unsafe, no-reclaim, no-JIT* bug is low.
3. **Blind CVE testing against the console** — the console is the only oracle for its own libraries. We can
   fingerprint behaviour (does `DOMParser` accept X, does an image decode truncate) and shoot known 2023-era
   libxml2/libpng CVEs at it. Crash-only signal, no ASAN, so a negative proves little and a positive needs
   follow-up; but it is the only route that touches the unreadable code.
4. **Wait for a public 14.10 release** — the kernel rung and any browser primitive would arrive ready-made.

## Recommendation

Option 3 is the only remaining route that is both in our control and aimed at the code most likely to be broken.
It is also the one with the worst signal-to-noise. Option 2 is comfortable and low-yield. Options 1 and 4 are not
actions at all.

The honest position for the record: with a readable tree that is the well-fuzzed half, and an unreadable half that
holds the target-specific parsers, this programme cannot promise a memory primitive. What it can do is keep
closing candidate surfaces with evidence — which is what the last five documents did — so that a future primitive
lands on a mapped chain rather than on guesswork.
