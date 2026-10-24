# Hunting variants of Sony's own fixes

The 59-file delta (`docs/17`) is not just a patch list — it is a catalogue of the bug
classes that were live in Sony's 13.60-era engine. Each fix says: *this shape of mistake
was reachable from a page here*. The most productive next question is therefore not
"which upstream fix is missing" but "where else does that shape appear in the tree they
did not touch".

## What Sony patched, in class terms

| file | fix | bug class to hunt |
|---|---|---|
| `dom/EventTarget.cpp` | `auto& context = *scriptExecutionContext()` → `Ref context = …` | reentrancy: a listener destroys the context during dispatch, then the tail of the function dereferences it |
| `css/parser/CSSParserImpl.cpp` | `maximumRuleListNestingLevel = 128` enforced in `consumeStyleRule` | unbounded recursion in parsing (stack exhaustion), other recursive parse entries |
| `runtime/JSCell.cpp` | `static_cast<const JSObject*>` → `jsSecureCast<…>` after the `isString/isSymbol/isHeapBigInt` ladder | unchecked downcasts justified only by an exclusion argument |
| `builtins/ProxyHelpers.js` + `NodesCodegen.cpp` | `@toThis(receiver)` in proxy traps | any place a raw JSValue is treated as `this` |
| `yarr/YarrPattern.cpp` | pop the `UnresolvedForwardReference` when a `{0}` term is elided | bookkeeping structures that outlive the term they point at |
| `image-decoders/bmp/BMPImageReader.cpp` | index absolute-mode runs relative to `startX` | every other pixel index computed from an absolute coordinate |
| `interpreter`/`TransformStream.cpp` | `ASSERT(size == 3)` + unchecked `jsDynamicCast(...)->wrapped()` → TypeError | ASSERTS standing in for real error handling in release builds |

## The three greps worth running

1. **Reentrancy tails.** In Sony's tree, find functions that take a reference from a
   document/element, dispatch an event or run script, then use the reference again:

   ```
   grep -rn 'auto& .*= \*scriptExecutionContext()' Source/WebCore
   grep -rn 'auto& .*= \*element()'                Source/WebCore
   ```
   The `EventTarget` fix is one instance; `dispatchEvent` call sites inside those
   functions are the tell.

2. **Unbounded recursion.** `parseCSSSelector`, `consumeAtRule`, `parseSupportsCondition`,
   `CSSSelectorParser::consumeComplexSelector` and any other recursive descent without a
   depth counter. Sony added the guard to one entry point only.

3. **Unchecked downcasts.** Any `static_cast<X*>` or `downcast<X>` reached after a
   type ladder that *excludes* the other cases, rather than a positive check. The
   `JSCell` fix is the model; `JSCJSValue`, `Operations.cpp`, `JSObject.cpp` are the
   places to look.

## Live candidate shortlist

Verified by reading Sony's source, not by the sweep alone:

| # | candidate | trigger | state |
|---|---|---|---|
| 1 | `ShadowBlur::blurShadowBuffer` heap-buffer-overflow (upstream 1e8c797c / 264978) | pure CSS: huge div + box-shadow + filter | **probe armed**, no interaction needed |
| 2 | `BaseDateAndTimeInputType::didChangeValueFromControl` UAF (869d5c55 / 310544) | type change inside `input` on a date field | needs a USB keyboard (UA shadow root blocks synthetic keys) |

Rejected after reading the code, with reasons worth keeping:

- **XSLT import UAF (a8459d45)** — `ENABLE_XSLT OFF` on this port. Dead.
- **`TransformationMatrix::clampedBoundsOfProjectedQuad`** — VULN-SHAPE by line match,
  but the fix is hit-testing correctness ("mirrors corners behind the eye"), not memory
  safety. Drop.
- **Float16 `getPixelBuffer` heap disclosure (b6908339)** — the repro needs the IPC
  testing API, i.e. the GPU process, which is compiled out.
- **`PopoverData` uninitialised enums (0f465110)** — real but weak: deterministic state
  confusion inside the popover machinery, no obvious memory-safety consequence.
- **`CtapHidDriver` OOB read (808e7719)** — WebAuthn/FIDO USB path, not reachable from a
  page. **`InspectorAnimationAgent` (122493b2)** — inspector only. **`AudioContext`,
  `SincResampler`, `WebCodecsVideoFrame`** — those subsystems are off.

## Coverage, stated honestly

The sweep depends on commit messages naming a symptom, and Apple does not label security
work. A missing fix therefore proves nothing, and a present pre-fix shape proves only
that the code is the same — not that the bug is triggerable on a build with no JIT, no
GPU process, no workers and no XSLT. Both filters have to be applied by hand, which is
why six of the nine `VULN-SHAPE` hits died on inspection.

What the pipeline is genuinely good at: turning "is this worth any of my time?" into a
two-minute read of the shipped source.

## First pass of the greps — results

The full tree is now local (`out/sony/tree/WebKit-1400/WebKit-1400/Source`, 726 MB,
8,271 `.cpp` + 17,623 `.h`), so these are greps over Sony's actual code rather than
samples fetched one file at a time.

**Reentrancy scan (the `EventTarget` class).** 17 sites take a raw
`auto& x = *scriptExecutionContext()`; a scan for those followed by any
`dispatchEvent` / `fireEvent` / `willDispatchEvent` within 160 lines returns six:

```
OffscreenCanvas::scheduleCommitToPlaceholderCanvas
MessagePort::disentangle
ServiceWorkerContainer::{updateRegistration,getRegistration,getRegistrations,postMessage}
```

Five are in subsystems this port compiles out (OffscreenCanvas measured `false` at
runtime, service workers off). `MessagePort::disentangle` reads its context before any
script can run, so it is not the pattern. **No reachable sibling of the EventTarget fix.**

**`JSCell` downcast class.** `jsSecureCast` exists in the tree and `JSCell::toPrimitive`
/`toNumber`/`toObject` use it, so that fix was backported. Only 1
`static_cast<const JSObject*>` and 6 `static_cast<JSObject*>` remain in all of
JavaScriptCore — the class is effectively cleaned up.

**BMP RLE re-audit.** The backported fix is complete for `processNonRLEData`: reads are
indexed from `startX`, `endX > width` fails the image, and every paletted path validates
`colorIndex < biClrUsed`. `processRLEData` allows `x == width` (the delta check uses `>`
rather than `>=`) but every downstream consumer is a no-op at that coordinate, and
`pastEndOfImage` only inspects `y` — verified contained, not exploitable as written.

Net: three of the four classes Sony patched are either fully fixed or unreachable here.
The remaining surface is the one the sweep found — `ShadowBlur` — plus whatever a
sustained audit of the reachable parsers (CSS, HTML, image decoders, Yarr) turns up.
