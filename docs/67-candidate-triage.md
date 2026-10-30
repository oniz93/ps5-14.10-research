# Triage of the 56 ranked candidates: one reachable crash, no second primitive

GOAL next action 1, 2026-10-29: *"Re-aim: triage the ranked candidate list for a second, non-font bug.
Take `data/candidates-ranked.json` in score order and, for each entry whose file exists in the drop,
decide JS-reachability from the source alone: name the entry point, say whether the fix hunk is present,
and either write the harness page or state why it is unreachable. Start with `cfe38930db`."*

This document does that for all 56 entries. The result is not the one the ranking predicted: the list is
dominated by commits whose code is either **not in this generation of the drop at all**, or **not a defect**
(hardening, refactors, build fixes, perf, features). Of 56, exactly **three** are live defects with a JS entry
point — one deterministic **null-pointer dereference that kills the WebProcess**, one GC data race with no
observable memory effect (`docs/68`), and one integer-conversion UB — and a fourth candidate that looked live
(the BroadcastChannel row) was measured to be unreachable in this build. **None of them is a reclaimable
object.** The project's second bug is not in this list.

## Method

1. `data/candidates-ranked.json` (56 entries, `worst`/`score`/`sigs` computed earlier from the Sony 1400 drop).
2. Every commit's real patch was downloaded to `data/cand-patches/<sha>.patch`
   (`curl -sL https://github.com/WebKit/WebKit/commit/<sha>.patch`, 56/56 OK) and the commit message read. The
   patches are gitignored (2.4 MB, re-fetchable with that one command); the decision rows below quote the drop,
   not the patch, so they stand without them.
3. Each patch's hunks were compared mechanically with the drop: for every file that exists, how many removed
   (`-`) and added (`+`) lines appear verbatim. That check is *necessary but not sufficient* — a single matched
   `#include` line marks a whole commit "pre-shape" — so every entry that survived it was read in the drop.
4. Verdicts below are one of:
   - **ABSENT** — the file, or the feature the code needs, does not exist in the drop.
   - **OLD-GEN** — the drop is *older* than the defect: it has a different arrangement that does not have the bug
     (the ranking matched generic lines, not the vulnerable statement).
   - **NODEFECT** — the commit is a hardening/refactor/build/perf/feature/test change; there is nothing to trigger.
   - **KNOWN** — already worked in this programme (`docs/62`, `docs/63`).
   - **LIVE-RACE / LIVE-CRASH / LIVE-BUG** — a real defect present in the drop, with its reachability stated.
5. The single deterministic live bug was then exercised on the ASAN oracle, one variable per run
   (`research/cand-triage/page-null.html`, md5 `0f07e47e8fbbc642e47bf0a7235d741c`,
   logs in `data/cand-triage/`).

## Table

`file:line` is the Sony 1400 drop (`out/sony/full/WebKit-1400/WebKit-1400/`).

| # | commit | what it claims | drop evidence | verdict |
|---|--------|----------------|---------------|---------|
| 0 | `cfe38930db` | race in `CloneSerializer::dumpIfTerminal` → arbitrary deserialization data (growing `SharedArrayBuffer`) | `bindings/js/SerializedScriptValue.cpp:1822-1829`: the resizable-SAB branch writes `byteLength` at `:1826` and the payload with **the same `byteLength`** at `:1829`. The vulnerable form writes `arrayBuffer->span()`, whose size is re-read after the grow; that form is not in this drop. Second, independent reason: `JSC::Options::useSharedArrayBuffer` defaults to **false** (`JavaScriptCore/runtime/OptionsList.h:579`) and the only setter in the tree is the Cocoa XPC entry point (`WebKit/Shared/EntryPointUtilities/Cocoa/XPCService/XPCServiceEntryPoint.h:116`), so a *shared* growable buffer cannot be created in this build at all. | **OLD-GEN + unreachable** — length and payload cannot disagree here, and the object the race needs does not exist. |
| 1 | `621e3bf30e` | data race in `Range::visitNodesConcurrently` during GC → UAF of a boundary node | `dom/Range.cpp:1133` visitor reads `m_start.container()`/`m_end.container()`; `dom/RangeBoundaryPoint.h:53` is `Ref<Node> m_container`; `dom/Range.h:42` has **no** `m_boundaryPointLock` (the fix adds one and takes it in every mutator). | **LIVE-RACE** — real UAF, needs the concurrent marker to read the `Ref` while `setStart`/`setEnd` reassigns it. Not deterministic. |
| 2 | `ab488735a4` | same bug, follow-up (locks + `Ref range` in the `m_ranges` loops) | `dom/Document.cpp:5203,5214,5246` iterate `m_ranges` with `range.get()`; no lock in `Range.h`. | **LIVE-RACE** — same defect as row 1; do not count twice. |
| 3 | `5b3364fd97` | revert of a stale `HashMap` iterator in `LegacyRenderSVGResourceFilter::applyResource` | file absent; the equivalent code `rendering/svg/RenderSVGResourceFilter.cpp:110,117,136,154` removes **by key** (`remove(&renderer)`), which is exactly what the revert restores. | **ABSENT/OLD-GEN** — the bad form (`remove(addedIterator)`) came later. |
| 4 | `a93904b977` | UAF in `SVGGeometryElement::getPointAtLength` — raw renderer held across nested `updateLayout` | `svg/SVGGeometryElement.cpp:68-75`: `renderer()` is read at `:75`, *after* the nested `getTotalLength()` (which lays out) at `:73`. The bug needs the read *before* it. | **OLD-GEN** — the dangerous ordering was introduced by a later refactor. |
| 5 | `e147963ac4` | UAF in `WebCodecsAudioData::memoryCost()` via concurrent GC marker | `Modules/webcodecs/WebCodecsAudioData.cpp` absent. | **ABSENT** |
| 6 | `cb83583e5f` | UAF of `Document` in `trustedTypeCompliantString` | `trustedTypeCompliantString` does not exist anywhere in the drop (grep: no hits). | **ABSENT** — Trusted Types is not in this tree. |
| 7 | `d7904663aa` | Safari crash in AppKit Writing Tools | `page/writing-tools/WritingToolsController.mm` absent. | **ABSENT** (macOS-only) |
| 8 | `cc88e18743` | null deref inserting `@page` into a **detached** grouping rule | `css/parser/CSSParserImpl.cpp:229` and `:238` call `styleSheet->defaultNamespace()` unguarded; `css/CSSGroupingRule.cpp:70` passes `nullptr` when `parentStyleSheet()` is null. | **LIVE-CRASH** — verified, 4 arms, below. |
| 9 | `8e3c2c07a9` | "Fix bad cases of refcounted objects being stored in `std::unique_ptr`" | the commit *adds* a `static_assert` to `makeUnique` and a `makeUniqueWithoutRefCountedCheck` escape hatch (`WTF/wtf/StdLibExtras.h`); no runtime defect is removed. | **NODEFECT** — hardening of the type system. |
| 10 | `44884327f7` | "`ImageBitmapBacking` is a redundant class" | `html/ImageBitmap.cpp`, `html/ImageBitmapBacking.cpp` restructure. | **NODEFECT** — refactor. |
| 11 | `74df988dc5` | "beginParsingChildren/finishParsingChildren should only exist on Element" | `dom/Element.cpp`, `dom/Node.h` virtual removal. | **NODEFECT** — cleanup. |
| 12 | `560b9a991f` | "Drop dead code in `processTemplateEndTag()`" | `html/parser/HTMLTreeBuilder.cpp:963`. | **NODEFECT** — dead code. |
| 13 | `442482adf1` | `CachedString::m_jsString` not protected from GC in `CloneDeserializer` | `bindings/js/SerializedScriptValue.cpp:2825-2836`: raw `JSValue m_jsString`, no keep-alive append. | **KNOWN** — live and already weaponised as far as it goes (`docs/62`, `docs/63`): string substitution, not a memory primitive. |
| 14 | `eb2cefb5ee` | fold `TreeDepthLimit.h` into `XMLDocumentParser.cpp` | build file only. | **NODEFECT** — build. |
| 15 | `af0b4e780f` | get `GraphicsLayer.h` out of hot include paths | `platform/graphics/Pattern.h` etc. | **NODEFECT** — build. |
| 16 | `643cd318d6` | `UncountedCallArgsChecker`/`UncountedLocalVarsChecker` in `CSSParserImpl.cpp` | `css/CSSFontPaletteValuesOverrideColorsValue.h`, checker expectations. | **NODEFECT** — hardening. |
| 17 | `94ec0f4523` | "Re-land missing exception checks" | 22 of 38 added lines are already in the drop. | **NODEFECT** — the re-land is already in this tree; exception checks, not memory. |
| 18 | `6e19b3bf99` | merge `CSSParser` and `CSSParserImpl` | `Sources.txt`, `css/parser/*`. | **NODEFECT** — refactor. |
| 19 | `3c7fe87417` | "Leverage the `RefPtr<T>(T&)` constructor in more places" | `Modules/highlight/AppHighlightStorage.cpp:70` and ~40 files. | **NODEFECT** — hardening. |
| 20 | `59959a003b` | "Address safer cpp warnings in `SerializedScriptValue.cpp`" | raw `JSObject*` locals in the serializer; the fix lines are absent. | **NODEFECT** — hardening; the encoder only reads live objects held by the caller's graph. |
| 21 | `4a6e51b91b` | "Inline nesting selector when possible" | `style/RuleData.cpp:62` (moves `selectorCanMatchPseudoElement` to `CSSSelector.cpp`), `parser/MutableCSSSelector.cpp` copy tag. | **NODEFECT** — perf/correctness of `&` resolution. |
| 22 | `b435bcbfaf` | "Stop storing raw pointers in containers in `SerializedScriptValue.cpp`" | the drop already takes the transfer list as `Vector<JSC::Strong<JSC::JSObject>>` (`:5355`); pool objects are additionally rooted by `MarkedArgumentBuffer m_objectPool` (`:900`, appended at `:1170`). | **NODEFECT** — hardening; nothing in the pool can be collected while the map is consulted. |
| 23 | `479cba7de8` | ASAN_ILL in `XMLDocumentParser::detach` (CheckedPtr release assert) | `xml/parser/XMLDocumentParser.cpp:91` `clearCurrentNodeStack()`; the members are raw `ContainerNode*` (`XMLDocumentParser.h:162-163`). | **OLD-GEN** — the reported assert exists only in the later `CheckedPtr` generation; the raw-pointer form just frees. |
| 24 | `13585ff380` | "Avoid heap-allocating `CSSSelector` in `MutableCSSSelector`" | `css/parser/MutableCSSSelector.h:51-56` (unique_ptr → value). | **NODEFECT** — refactor. |
| 25 | `5de150e5b4` | `MessagePort::DataType` does not need a `SerializedScriptValue` option | `bindings/js/JSMessageEventCustom.cpp:54`. | **NODEFECT** — refactor. |
| 26 | `3ce7856bc4` | "WebKit is slow at opening very big HTML files" | `dom/CharacterData.cpp:80` `makeChildChange`. | **NODEFECT** — perf. |
| 27 | `aff0077f73` | deeply nested `<div>` hang in the parser | `html/parser/HTMLTreeBuilder.cpp:619`. | **NODEFECT** — DoS/hang, not memory. |
| 28 | `b271e70e72` | allow `Object.prototype` to be serialized by `structuredClone` | `bindings/js/SerializedScriptValue.cpp:973` `serialize`. | **NODEFECT** — feature. |
| 29 | `414b33a529` | O(1) `isParsingTemplateContents()` | `html/parser/HTMLTreeBuilder.cpp:131`. | **NODEFECT** — perf. |
| 30 | `d093ebaada` | XML parser hangs on deeply nested entity references | `xml/parser/XMLDocumentParserLibxml2.cpp:614`. | **NODEFECT** — DoS/hang. |
| 31 | `87ee373497` | `innerText` blank lines for `<p>`/headings | `dom/Element.cpp:3787`. | **NODEFECT** — correctness. |
| 32 | `c58af30db1` | `innerText` newlines for `white-space:pre-line` | `editing/TextIterator.cpp:462`. | **NODEFECT** — correctness. |
| 33 | `2b861656bd` | build speed improvements | `WebKit/Shared/SessionState.h`. | **NODEFECT** — build. |
| 34 | `4d33765661` | `innerText` on tables | `editing/TextIterator.cpp:473`. | **NODEFECT** — correctness. |
| 35 | `ff2f768ad6` | case-sensitive modifier `s` in attribute selectors | `css/CSSSelector.cpp:376`. | **NODEFECT** — feature. |
| 36 | `30bf5b4225` | split `Style::DocumentScope` out of `Style::Scope` | `css/CSSStyleSheet.cpp:247`. | **NODEFECT** — refactor. |
| 37 | `fab4ac5572` | `:nth-child()` An+B converted from `double` to `int` without clamping | `css/parser/CSSSelectorParser.cpp:1035` (`static_cast<int>(token.numericValue())`) and `:1057` (`result.first = token.numericValue()`, implicit) — the drop has the unclamped conversions. | **LIVE-BUG** (source-level, not run) — reachable from CSSOM (`insertRule(':nth-child(1e100n+1)')`), UB and a wrong match; the value only feeds `(index-b)/a`, never an index, so no OOB. No primitive. |
| 38 | `84cde5ed5a` | `SerializedScriptValue::deserialize` cannot be called twice (BroadcastChannel) | the consumed members are `m_arrayBufferContentsArray` (`SerializedScriptValue.cpp:4667`, `ArrayBuffer::create(WTFMove(m_arrayBufferContents->at(index)))`) and `m_backingStores` (`:5566`); `WebBroadcastChannelRegistry.cpp:94-116` shares one SSV between recipients. **But `BroadcastChannel.idl:34` is `postMessage(any message)` — no transfer list** — so every `ArrayBuffer` is copied in-line by `readArrayBufferImpl` (`:3238-3250`) and no consumed member is ever reached. | **NEGATIVE, measured** — 3 channels (two recipients), with and without a transfer list: both get `ab.len=64 ta0=1 s=hello`; `buf.byteLength` is still 64 after `postMessage(m,[buf])` (the second argument is ignored), no ASAN. Unreachable in this build; the upstream fix is a correctness fix for types this IDL cannot send. |
| 39 | `e0d162e570` | migrate cloning of terminal JS values to JSC | `WTF/wtf/text/AtomString.h:163`. | **NODEFECT** — refactor. |
| 40 | `e20361406f` | `containsPlainText()` re-scans the head | `editing/TextIterator.cpp:2633`. | **NODEFECT** — perf. |
| 41 | `c0625bcafb` | `Error.isError()` should be true for `DOMException` | `JavaScriptCore/runtime/ErrorInstance.h:61`. | **NODEFECT** — correctness. |
| 42 | `045a0c6379` | `DOMException` should have a stack property | `bindings/js/SerializedScriptValue.cpp:517`. | **NODEFECT** — feature. |
| 43 | `7390911815` | optimize `[class~=foo]` like a class selector | `style/RuleFeature.cpp:219`. | **NODEFECT** — perf. |
| 44 | `d719d23779` | `createImageBitmap` from HDR | `html/ImageBitmap.cpp:75` (large feature/refactor). | **NODEFECT** — feature. |
| 45 | `165f9ed4d0` | `CString` raw-byte constructors restricted on Cocoa | `JavaScriptCore/assembler/Printer.cpp:48`. | **NODEFECT** — build. |
| 46 | `35090d6160` | make `HTMLEnhancedSelectMultipleAndListBoxEnabled` testable | `editing/markup.cpp:261`. | **NODEFECT** — test/feature flag. |
| 47 | `21862acf2c` | preserve `QuotaExceededError` when structured cloning | `bindings/js/SerializedScriptValue.cpp:248`. | **NODEFECT** — correctness. |
| 48 | `86d0164f83` | generate structured-deserialization exposure checks from IDL | `Modules/streams/TransformStream.idl`. | **NODEFECT** — spec/exposure. |
| 49 | `83fa59d858` | uncounted-call-arguments warnings, part 3 | `accessibility/AXTextMarker.cpp:131` and ~60 files. | **NODEFECT** — hardening. |
| 50 | `ce011e7c0b` | drawing a BGRX `VideoFrame` should disregard alpha | `platform/graphics/cv/ImageTransferSessionVT.h:49`. | **NODEFECT** — rendering. |
| 51 | `eb71e0180b` | annotate `Source/WebCore/html` functions `NODELETE` | `html/ColorInputType.h`. | **NODEFECT** — annotations. |
| 52 | `3199d04f22` | annotate `Source/WebCore/bindings` functions `NODELETE` | `bindings/js/CachedModuleScriptLoader.h`. | **NODEFECT** — annotations. |
| 53 | `f5fa7b5d46` | annotate `Source/WebCore/editing` functions `NODELETE` | `editing/EditCommand.cpp:155`. | **NODEFECT** — annotations. |
| 54 | `7d12474f8d` | parse processing instructions in HTML | `dom/ProcessingInstruction.cpp:80`, tokenizer. | **NODEFECT** — feature. |
| 55 | `202ef7bf88` | serializing a `SharedArrayBuffer` requires a cross-origin isolated process | no cross-origin-isolation plumbing exists in the drop (`grep -r isCrossOriginIsolated Source/WebCore Source/WebKit`: no hits); `useSharedArrayBuffer` is false by default and only the Cocoa XPC entry point sets it (`XPCServiceEntryPoint.h:116`). | **ABSENT** — the policy this commit tightens does not exist in this tree. |

Count: 5 ABSENT (3, 5, 6, 7, 55), 3 OLD-GEN (0, 4, 23), 1 KNOWN (13), 1 LIVE-CRASH (8), 2 LIVE-RACE (1, 2 — one
bug), 1 LIVE-BUG (37), 1 measured NEGATIVE (38), and 42 NODEFECT.

## The one deterministic live bug: `@page` on a detached grouping rule

This is the first candidate in score order that is both present and reachable, and it is a **null-pointer
dereference**, i.e. a WebProcess crash, not a reclaimable slot.

Entry point, all from plain script:

```
CSSGroupingRule::insertRule()                 css/CSSGroupingRule.cpp:70  passes nullptr when parentStyleSheet() == nullptr
  CSSParser::parseRule()                      css/parser/CSSParser.cpp:76
    CSSParserImpl::consumePageRule()          css/parser/CSSParserImpl.cpp:883
      CSSParserImpl::parsePageSelector()      css/parser/CSSParserImpl.cpp:229 / :238
        styleSheet->defaultNamespace()        css/parser/CSSParserImpl.cpp:229 / :238  <- styleSheet == nullptr
```

The page (`research/cand-triage/page-null.html`) makes a `<style>@media all {…}</style>`, takes
`document.styleSheets[0].cssRules[0]`, optionally removes it with `deleteRule(0)` (which clears
`parentStyleSheet` — the page reports it), and then calls `media.insertRule(...)`. Four arms, one variable apart:

```
$ PAGE=../cand-triage/page-null.html ./research/cve-2026-43715/run-page.sh 9680 "at=0" N0   # control: attached
access: none / SUMMARY: none
   after-delete ps=[object CSSStyleSheet] sheetRules=1
   BEFORE @page foo {}
   AFTER ok idx=0 childRules=2

$ ... 9681 "at=1" N1                                                                       # detached, @page foo
ERROR: AddressSanitizer: SEGV on unknown address 0x000000000070 (pc … T0)
    #0 RefPtr<StringImpl>::operator!() const      wtf/RefPtr.h:87
    #3 makeComponents                             dom/QualifiedName.cpp:47
    #5 WebCore::CSSParserImpl::parsePageSelector  css/parser/CSSParserImpl.cpp:229
    #6 WebCore::CSSParserImpl::consumePageRule    css/parser/CSSParserImpl.cpp:883
    #8 WebCore::CSSParserImpl::parseRule          css/parser/CSSParserImpl.cpp:182
    #10 WebCore::CSSGroupingRule::insertRule      css/CSSGroupingRule.cpp:70
   after-delete ps=null sheetRules=0
   BEFORE @page foo {}
   (no further beacon; WebProcess CRASHED)

$ ... 9682 "at=2" N2                                                                       # detached, @page foo:first
ERROR: AddressSanitizer: SEGV on unknown address 0x000000000070
    #5 WebCore::CSSParserImpl::parsePageSelector  css/parser/CSSParserImpl.cpp:238

$ ... 9683 "at=3" N3                                                                       # detached, @page {} (no type selector)
access: none / SUMMARY: none
   after-delete ps=null sheetRules=0
   BEFORE @page {}
   AFTER ok idx=0 childRules=2
```

`0x70` is `StyleSheetContents::defaultNamespace()` reading the `AtomString` member through a null `this`
(`QualifiedName`'s three-argument constructor then tests the empty string — `makeComponents`), i.e. a **fixed
low address, READ**. `at=3` is the control that proves the selector text, not the detachment, chooses the branch:
with no type selector neither `:229` nor `:238` runs and the insert succeeds on the same detached rule.

This is a clean, reproducible crash and it is *new* for this programme (it is not in `docs/65` or `docs/66`), but
it is **not** stage criterion 3 and it is not a step toward it: the fault address is zero-page and not
attacker-influenced. Its value is as a reliability datum (a 6-line page kills the WebProcess) and as the first
proof that the harness can find non-font bugs at all.

## The one live memory-unsafe bug: the Range/GC race

`Range` keeps two `Ref<Node>` boundary points and a JS wrapper visitor that reads them from the **concurrent
GC marker**:

```
dom/Range.cpp:1133   void Range::visitNodesConcurrently(JSC::AbstractSlotVisitor& visitor) const
                     {   addWebCoreOpaqueRoot(visitor, m_start.container());
                         addWebCoreOpaqueRoot(visitor, m_end.container()); }
dom/RangeBoundaryPoint.h:53   Ref<Node> m_container;
dom/Range.h:42                class Range final : … (no lock member)
```

The fix (rows 1 and 2) adds `Lock m_boundaryPointLock` and takes it in every mutator (`setStart`, `setEnd`,
`selectNodeContents`, `nodeChildrenChanged`, `nodeWillBeRemoved`, `textInserted/Removed/Merged/Split`,
`createLiveRange`) **and** in the visitor. The race is real: `setStart` assigns the `Ref<Node>` non-atomically,
and the marker can read the pointer while the old node's last reference is being dropped. Winning it needs the
GC thread to be inside the two-line visitor at the exact instant the main thread reassigns the member — a
window of a few instructions per GC cycle. That is why it is not the harness target of this run: it has no
deterministic trigger, only a probability per GC that a page can try to amplify.

## The BroadcastChannel row: measured, and unreachable in this build

Row 38 looked like the one deterministic *multi-recipient* bug: `WebBroadcastChannelRegistry::postMessageLocally`
gives the same `SerializedScriptValue` to every channel with that name (`message.copyRef()` per recipient,
`WebKit/WebProcess/WebCoreSupport/WebBroadcastChannelRegistry.cpp:94-116`), and `deserialize` consumes part of the
message — `ArrayBuffer::create(WTFMove(m_arrayBufferContents->at(index)))` at `SerializedScriptValue.cpp:4667`
for a transferred buffer, and `WTFMove(m_backingStores)` at `:5566`.

`research/cand-triage/page-broadcast.html` (md5 `2f7ec0fb3eed3917ad5c3cd07fdd2195`) creates N channels with one
name, posts `{ab: ArrayBuffer(64), ta: Uint8Array, s: 'hello'}` from channel 0, and has every other channel
report what it received. With N=3 two channels receive, so one of them is the second deserialize; N=2 is the
control (one recipient).

```
$ ... 9700 "n=3"        B3    access: none / SUMMARY: none
   BC1 ab.len=64 ta.len=8 ta0=1 s=hello
   BC2 ab.len=64 ta.len=8 ta0=1 s=hello
$ ... 9701 "n=2"        B2    BC1 ab.len=64 ta.len=8 ta0=1 s=hello
$ ... 9702 "n=3&xfer=1" BX3   posted xfer=1 detached=64
   BC1 ab.len=64 …   BC2 ab.len=64 …
$ ... 9703 "n=2&xfer=1" BX2   BC1 ab.len=64 …
```

Both recipients get a complete, valid message, and no sanitizer fires — **and the transfer list is not honoured
either**: `buf.byteLength` is still 64 immediately after `postMessage(msg, [buf])`, because
`dom/BroadcastChannel.idl:34` declares `postMessage(any message)` with no `sequence<object>` transfer argument.
Without a transfer the serializer writes the buffer in-line (`readArrayBufferImpl`, `:3238-3250` **copies** from
the data stream), so the moved-from `m_arrayBufferContentsArray` is never consulted. `m_backingStores` (the other
consumed member) is only reachable through a transferred `ImageBitmap`, which this IDL cannot send.

So row 38 is a real upstream correctness fix for a shape this build cannot express. **Negative, closed** — not a
memory-safety candidate and not a second trigger.

## What this says about the ranked list

`data/candidates-ranked.json` was built by matching patch lines against the drop, and its `score`/`worst` fields
are dominated by *line presence*, not by whether the vulnerable statement exists. Concretely:

- The top entry's bug (`write(span())` after a grow) **cannot happen in this drop**, because the drop predates
  the `std::span` writer and uses the same `byteLength` for the declared length and the payload. The ranking's
  `pre 2/3` matched the four lines that survive in both forms.
- Three entries are *older* than the drop's code path and describe a defect introduced by a later refactor.
- Six entries are Security-adjacent *hardening* (`makeUnique` static_asserts, `Strong<>`, `RefPtr<T>(T&)`,
  uncounted-args annotations, safer-cpp warnings) with no trigger at all.
- The rest are perf, build, features, tests, or hangs.

So: **CVE-2026-43715 is not the only bug, but this list does not contain its successor.** The next step has to
come from a different direction (a new source-level audit), not from a higher `score` in this file.

## Next

GOAL next action: try to win the Range/GC race under ASAN, bounded. The page keeps *K* live `Range`s over a
large, churning subtree, mutates `setStart`/`setEnd` on them in a tight loop, and allocates to force repeated
GCs; 10 runs under `run_nq.sh`; success = `heap-use-after-free` with `visitNodesConcurrently` /
`addWebCoreOpaqueRoot` in the stack (`T1` acceptable). If 10 runs produce no report, record the negative and
close that road — do not turn it into an open-ended sweep.
