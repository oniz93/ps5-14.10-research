# Candidate dossier: what to test next, and why

Three threads, ordered by how much they are worth. Everything here is grounded in code
that is on disk, not in a bug title.

---

## 1. Resizable ArrayBuffer serialization — the only lead with a published exploit primitive

Upstream fixed this on **2024-10-31**:

```
Race condition in CloneSerializer::dumpIfTerminal allows for injecting arbitrary
deserialization data
https://bugs.webkit.org/show_bug.cgi?id=278657   rdar://132388209
```

The commit message calls it plainly: *"Fix the exploit by using consistent byteLength
fetched from the array buffer"* and notes it is **part 1 of a security fix**.

What the bug is. `SerializedScriptValue` is the format behind `structuredClone()`,
`postMessage` and `IndexedDB`. When the serializer meets a resizable ArrayBuffer it
writes a length, then copies the data. If the buffer changes size in between, the length
in the header no longer matches the payload, and the deserializer starts reading
attacker-chosen bytes *as serialization tags*. From there the attacker forges the object
graph: the upstream test injects a `StringTag` and a fake buffer to prove it.

Sony's 14.x tree is from **September 2023**, thirteen months before the fix. Their code:

```cpp
// Source/WebCore/bindings/js/SerializedScriptValue.cpp:1822-1830
if (arrayBuffer->isResizableOrGrowableShared()) {
    appendObjectPoolTag(ResizableArrayBufferTag);
    write(ResizableArrayBufferTag);
    uint64_t byteLength = arrayBuffer->byteLength();     // read once
    write(byteLength);
    uint64_t maxByteLength = arrayBuffer->maxByteLength().value_or(0);
    write(maxByteLength);
    write(static_cast<const uint8_t*>(arrayBuffer->data()), byteLength);
    return true;
}
```

That is the pre-fix shape. `byteLength` is read before `data()` is taken, so a size
change in between gives a stale length against a fresh pointer — an over-read when the
buffer shrank, a truncated copy when it grew.

### Is it reachable? One bit decides it

`Source/JavaScriptCore/runtime/OptionsList.h`:

```
v(Bool, useResizableArrayBuffer, true,  Normal, "Expose ResizableArrayBuffer feature.")
v(Bool, useSharedArrayBuffer,    false, Normal, nullptr)
```

Resizable ArrayBuffer is **on by default** in Sony's drop. SharedArrayBuffer is off, and
that matters: mutating a buffer *between* the length read and the data copy needs a second
thread. JavaScript is single-threaded, and no amount of getters gets you inside that
window — a getter for element *n+1* runs after element *n* has been fully written.

So the chain is: cross-origin isolation → SharedArrayBuffer → Worker → grow/shrink the
buffer while the main thread serializes → corrupted clone stream.

`poc-sab-gates.js` measures exactly those gates and nothing else: `crossOriginIsolated`,
`typeof SharedArrayBuffer`, resizable `ArrayBuffer` + `grow`, growable `SharedArrayBuffer`,
and one worker round-trip. It does not attempt the race, so it cannot crash anything.

`guide_lab.py` now sends `Cross-Origin-Opener-Policy: same-origin` and
`Cross-Origin-Embedder-Policy: require-corp` on every response, without which the page is
not isolated and `SharedArrayBuffer` stays undefined regardless of engine support. The
earlier baseline measured `SharedArrayBuffer: false` — that was a non-isolated page, so it
says nothing about what isolation unlocks.

If the gates come back yes, the upstream regression test is close to a working reproducer
and this becomes the chain's first rung. If any gate is no, this lead is dead in the same
way the date-input bug was, and we move on without spending console time on it.

---

## 2. Attribute invalidation with nested selectors — a crash we can probably reproduce

**WebKit bug 276942** (Safari 17, reported 2024-07-23, still `NEW`). SIGSEGV at
`0x20`, in:

```
SelectorChecker::attributeSelectorMatches(...)
  ← Style::AttributeChangeInvalidation::invalidateStyle(...)
  ← Element::setAttributeInternal(...)
  ← DOMTokenList::updateAssociatedAttributeFromTokens()
  ← classList.add() called from a JS event listener
```

Trigger in the report: a **nested** rule `& > [class*='Box']` plus a `class` change.

The guards in Sony's tree are thin in a way that matches the crash address:

```cpp
// WebCore/style/AttributeChangeInvalidation.cpp:78-84
for (auto* selector : invalidationRuleSet.invalidationSelectors) {
    if (!selector->isAttributeSelector()) { ASSERT_NOT_REACHED(); continue; }
    bool oldMatches = ... SelectorChecker::attributeSelectorMatches(..., *selector);
```

```cpp
// WebCore/css/CSSSelector.h:385-390
inline const QualifiedName& CSSSelector::attribute() const
{
    ASSERT(isAttributeSelector());
    ASSERT(m_hasRareData);
    return m_data.rareData->attribute;
}
```

Both `ASSERT`s are compiled out of a release console build. A selector that reaches that
loop with `rareData == nullptr` dereferences `nullptr + 0x20` — the address in the report,
to the byte.

Open question, and it is again one bit: **`cssNestingEnabled`**. Safari 17.0 may ship CSS
nesting disabled by default, in which case `&` never parses. `poc-css-nesting-inval.js`
measures that first (`NEST-PARSE-yes/no` from a computed colour) and only then runs the
invalidation pattern, beaconing before each step so a crash names the step that killed it.

---

## 3. Sony's selector-parser context compares with `||` — a cache key that never misses

`CSSSelectorParserContext` is part of `SelectorQueryCache`'s key:

```cpp
// WebCore/dom/SelectorQuery.h:119
using Key = std::tuple<String, CSSSelectorParserContext, SecurityOriginData>;
```

Sony's comparison (`WebCore/css/parser/CSSSelectorParser.cpp`):

```cpp
bool CSSSelectorParserContext::operator==(const CSSSelectorParserContext& other) const
{
    return mode == other.mode
        || cssNestingEnabled == other.cssNestingEnabled
        || focusVisibleEnabled == other.focusVisibleEnabled
        || hasPseudoClassEnabled == other.hasPseudoClassEnabled;
}
```

Upstream at the same declared version (`ba9730178b6a`, Safari 17.0 cut):

```cpp
friend bool operator==(const CSSSelectorParserContext&, const CSSSelectorParserContext&) = default;
```

So: Sony carries a hand-written `||` where upstream has memberwise equality. Since `mode`
is `HTMLStandardMode` for essentially every document, every context compares *equal* — the
selector-query cache returns a query parsed under different feature flags than the caller's.
Two consequences worth testing: `querySelectorAll` can return results produced under a
different `:has()`/nesting/focus-visible configuration, and the cached `SelectorQuery` may
hold selector shapes the current context would never have produced.

`isHashTableDeletedValue` is also left out of the comparison, which the `HashTraits`
specialisation does not expect.

This is not a memory-safety primitive on its own. It is a *state-consistency* bug in a
cache key, and bugs of that shape are what turn a hard-to-reach crash (like #2) into a
reproducible one. Worth understanding before testing #2 in anger.

---

## Sweep results (15 queries, WebCore surface)

157 commit records, 87 scored `VULN-SHAPE` by the raw heuristic — which is far too
permissive, because a pre-fix code shape is also what a refactor leaves behind. After
de-noising (memory-safety title required, refactor/build/versioning titles rejected, dead
surfaces subtract), **56 candidates at score ≥ 3**, top of the list:

| score | date | verdict | what |
|---|---|---|---|
| 7 | 2024-10-31 | VULN-SHAPE | Race in `CloneSerializer::dumpIfTerminal` → arbitrary deserialization data (#1 above) |
| 5 | 2026-06-06 | PARTIAL | Data race in `Range::visitNodesConcurrently` during GC |
| 5 | 2026-06-30 | DIVERGED | UAF in `SVGGeometryElement::getPointAtLength` |
| 5 | 2026-07-01 | DIVERGED | UAF of `Document` in `trustedTypeCompliantString` |
| 5 | 2026-10-08 | DIVERGED | Null deref in `CSSParser::parsePageSelector()` |
| 4 | 2024-03-15 | VULN-SHAPE | `CachedString::m_jsString` unprotected from GC in `CloneDeserializer` |
| 4 | 2023-11-09 | VULN-SHAPE | Refcounted objects in `std::unique_ptr` (`CSSGroupingRule`) |

The 2026 rows need care: they are recent fixes, so `DIVERGED` usually means Sony's older
code differs structurally rather than being vulnerable. The 2024 rows are the ones where
"pre-fix lines present" means something.

Full ranked list: `data/candidates-ranked.json`.

---

## Traps found while doing this

| trap | consequence |
|---|---|
| `guide_lab.py` reads `guide_lab/current`, not `guide_lab/www/current` | a probe armed in the wrong file serves the *previous* probe and looks like the probe did nothing |
| Playwright CDN range reads fail while the edge serves a chain without intermediates | the sweep reported zero candidates, indistinguishable from "nothing found" |
| `urllib` cannot verify GitHub's chain on this Python | every search failed the same way |
| sweep verdicts score refactors as `VULN-SHAPE` | `triage_candidates.py` exists because the raw list would burn console time |

The pattern is worth naming: **four silent zeros in one night.** Every one of them looked
like a negative result.
