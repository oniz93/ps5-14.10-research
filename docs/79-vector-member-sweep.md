# docs/79 — the *member* shape: 49 raw-pointer member containers, 16 that grow inside a loop, 0 with a script window in the same function — and the shape this net cannot see is the one the drop's live bug lives in

The action (`GOAL.md`, first item): docs/78 closed the **local** `Vector<X*, N>` case (164 declarations, 1 with a
script sink, and it was docs/77's site) and excluded members by design; docs/77 swept only `JSValue`/`JSCell`
members. The member case differs in the one way that matters: the buffer is heap for the owner's whole lifetime, so
the conservative stack scan never sees it, and the owner's lifetime is something page script can influence. Sweep
`Source/WebCore` for `Vector<X*> m_*` / `FixedVector<X*>` / `Deque<X*>` / `ListHashSet<X*>` members, appended inside a
loop (or by recursion), with a JS entry point after the append and a read of the same member afterwards; plus
`HashMap`/`HashSet<X*>` locals.

This is that sweep. It produced four things:

1. **The member population is small and the push shape is empty**: 49 member declarations in the whole tree that
   carry a raw pointer (43 of them capacity 0, i.e. always heap), 69 push sites, **16** rows where the push is in a
   loop or a recursion, **5** of those read the member after the push in the same function (a 6th is a
   cross-class name collision), and **0** with a script entry point in the interval.
2. **The reverse direction is the real member shape, and it is guarded every time.** A member vector is dangerous
   when it is *iterated* and the callee runs script and mutates it — CVE-2026-43715's shape. 1,599 member container
   declarations, 1,070 range-fors over a member, 512 rows after owner attribution, 38 with a callback-shaped call in
   the body, 8 with a client-typed element: every one is guarded by a copy (`auto observersToNotify = m_resizeObservers`),
   a two-buffer swap (`m_videoFrameRequests.swap(m_servicedVideoFrameRequests)`), a `RefPtr` snapshot, or has no script
   at all.
3. **The net cannot see the loop that matters.** WebKit writes client iteration as a *helper template* —
   `iterateClients(m_clients, [&](Client& client) { … })` — so the range-for is not at the call site and the member
   never appears in a loop head. 147 call sites pass a member and a lambda to a helper; 11 of them are
   `iterateClients`, all in `CSSFontFace.cpp:155…769`, and that is exactly `docs/65`'s live bug. The helper is a
   `copyToVectorOf<Ref<Client>>` snapshot (`CSSFontFace.cpp:55-59`), which is why the lifetime is safe and the
   defect is semantic (the missing `contains` guard).
4. **The first same-class row whose pointee is not separately rooted is measured, not assumed**:
   `CollectionIndexCache::m_cachedList` is a raw `Vector<NodeType*>` (heap from the first element) pushed in
   `computeNodeCountUpdatingListCache` and dereferenced in `nodeAt` (:134) on a *later* API call, with arbitrary
   script in between. Six quarantine-off arms — removal, GC churn, document-level collection, `childNodes`
   (the one collection whose `willValidateIndexCache()` is empty, `ChildNodeList.h:78`), and a detached root — all
   answer the *live* node after the mutation (`d1`, not the detached `d0`), which is what a stale raw-pointer list
   could not do. `access: none` in 6/6, no sanitizer in any log.

## 1. Tools and funnels

Two new tools, both over the same 10,500 `.cpp`/`.mm`/`.h` files of `Source/WebCore`:

```
python3 tools/vector-member-sweep.py   > data/vector-member/inventory.json   # 2m15s
python3 tools/member-iterate-sweep.py  > data/vector-member/iterate.json     # 0m20s
```

`tools/vector-member-sweep.py` (members + hash locals; one cleaned pass shared by both, prefiltered so only files
that name a candidate are stripped):

| stage | count |
|---|---|
| member declarations with a raw pointer or GC cell (`Vector`/`FixedVector`/`Deque`/`ListHashSet`, `m_`-named) | **49** (47 distinct names) |
| … of those, capacity 0 / 8 / 16 / 1024 | 43 / 1 / 4 / 1 |
| … element kind: `node` / `ref` / `other` / `unknown` / `primitive` | 16 / 8 / 17 / 5 / 3 |
| push sites to a member that had a declaration | 69 |
| pushes inside a `for`/`while`/`do` or a recursive function | **16** |
| … that read the member after the push **in the same function** | 6 (5 same-class; 1 collision) |
| … with a direct script sink in [push, last read] | **0** |
| `HashSet`/`HashCountedSet`/`HashMap<K, X*>` locals with a pointer element | 31 |
| … inserted inside a loop / by recursion | 26 |
| … read after the insert | 14 |
| … with a script sink in the interval | **0** |

`tools/member-iterate-sweep.py` (the reverse direction, reusing the docs/78 helpers):

| stage | count |
|---|---|
| member container declarations (all element classes, 10 container templates) | **1,599** (1,246 names) |
| range-fors whose head is `: m_…` over one of those members | 1,070 |
| rows after requiring the loop's function to belong to the declaring class | **512** |
| … with a callback-shaped call in the body (`->handleEvent/->didX/client->…/function(`) | 38 |
| … with a client/observer-typed element and a method called on it | 8 |
| … with a direct sink in the body | 1 (`PaymentRequest::canMakePayment`, `resolve(bool)` — a *primitive* resolve, which docs/74 excluded: `PromiseOperations.js:187-192` reads `then` only for object arguments) |
| … whose body mutates the iterated container | 2 (both remove the *current* element: `ListHashSet::remove` in `openDBRequestCancelled`; `HashSet::remove` on a *nested value* in `BlobURLRegistry::unregisterURL`) |
| … with a callee that dispatches (one level) | **0** |

## 2. The 16 member rows, and the verdict on each

| # | declaration | owner | member | cap | push site (line) | loop | read after push | sink |
|---|---|---|---|---|---|---|---|---|
| 1 | `rendering/GridMasonryLayout.h:82` | GridMasonryLayout | `Vector<RenderBox*>` | 0 | `rendering/GridMasonryLayout.cpp:91` | for | 0 | — |
| 2 | `rendering/GridMasonryLayout.h:82` | GridMasonryLayout | `Vector<RenderBox*>` | 0 | `rendering/GridMasonryLayout.cpp:94` | for | 0 | — |
| 3 | `rendering/GridMasonryLayout.h:83` | GridMasonryLayout | `Vector<RenderBox*>` | 0 | `rendering/GridMasonryLayout.cpp:96` | for | 0 | — |
| 4 | `dom/CollectionIndexCache.h:62` | CollectionIndexCache | `Vector<NodeType*>` | 0 | `dom/CollectionIndexCacheInlines.h:55` | while | 1 (cross-function, see §6) | — |
| 5 | `platform/generic/KeyedDecoderGeneric.h:65` | KeyedDecoderGeneric | `Vector<Dictionary*>` | 16 | `platform/generic/KeyedDecoderGeneric.cpp:171` | while | 7 | — |
| 6 | `platform/generic/KeyedDecoderGeneric.h:66` | KeyedDecoderGeneric | `Vector<Array*>` | 16 | `platform/generic/KeyedDecoderGeneric.cpp:187` | while | 6 | — |
| 7 | `platform/generic/KeyedDecoderGeneric.h:65` | KeyedDecoderGeneric | `Vector<Dictionary*>` | 16 | `platform/generic/KeyedDecoderGeneric.cpp:196` | while | 4 | — |
| 8 | `rendering/svg/SVGTextQuery.h:67` | SVGTextQuery | `Vector<SVGInlineTextBox*>` | 0 | `rendering/svg/SVGTextQuery.cpp:105` | for | 0 | — |
| 9 | `platform/graphics/displaylists/DisplayListItemBuffer.h:212` | ItemBuffer | `Vector<uint8_t*>` | 0 | `platform/graphics/displaylists/DisplayListItemBuffer.cpp:721` | recursion | 0 | — |
| 10 | `Modules/indexeddb/IDBTransaction.h:252` | IDBTransaction | `Deque<IDBClient::TransactionOperation*>` | 0 | `Modules/indexeddb/IDBTransaction.cpp:273` | for | 0 | — |
| 11 | `Modules/indexeddb/IDBTransaction.h:252` | IDBTransaction | `Deque<IDBClient::TransactionOperation*>` | 0 | `Modules/indexeddb/IDBTransaction.cpp:304` | for | 0 | — |
| 12 | `Modules/indexeddb/IDBTransaction.h:252` | IDBTransaction | `Deque<IDBClient::TransactionOperation*>` | 0 | `Modules/indexeddb/IDBTransaction.cpp:1455` | for | 1 | — |
| 13 | `Modules/indexeddb/IDBTransaction.h:252` | IDBTransaction | `Deque<IDBClient::TransactionOperation*>` | 0 | `Modules/indexeddb/IDBTransaction.cpp:1500` | while | 0 | — |
| 14 | `platform/graphics/avfoundation/CDMPrivateMediaSourceAVFObjC.h:64` | CDMPrivateMediaSourceAVFObjC | `Vector<CDMSessionMediaSourceAVFObjC*>` | 0 | `Modules/encryptedmedia/MediaKeys.cpp:104` | recursion | 0 | — |
| 15 | `animation/CSSPropertyAnimation.cpp:2462` | ShorthandPropertyWrapper | `Vector<AnimationPropertyWrapperBase*>` | 0 | `animation/CSSPropertyAnimation.cpp:3823` | for | 2 | — |
| 16 | `animation/CSSPropertyAnimation.cpp:2462` | ShorthandPropertyWrapper | `Vector<AnimationPropertyWrapperBase*>` | 0 | `animation/CSSPropertyAnimation.cpp:3844` | for | 0 | — |

**Three of the sixteen are cross-class name collisions, not sites.** The first pass joins a push to a declaration by
*member name*; the same name in another class then matches:

* #14 — `CDMPrivateMediaSourceAVFObjC::m_sessions` is `Vector<CDMSessionMediaSourceAVFObjC*>` (`:64`), but the push
  is `MediaKeys::m_sessions.append(session.copyRef())` where `MediaKeys::m_sessions` is
  `Vector<Ref<MediaKeySession>>` (`Modules/encryptedmedia/MediaKeys.h:102`) — a `Ref` container, excluded by the
  tool's own filter if it had been attributed correctly.
* #15/#16 — `ShorthandPropertyWrapper::m_propertyWrappers` is a raw-pointer debug field (**only** read in
  `logBlend`, `:2457`), while the pushes at `:3823`/`:3844` go into `CSSPropertyAnimationWrapperMap`'s member of the
  same name, which holds `unique_ptr`.

The iterate tool carries the same-owner rule the first one lacks (`func == Owner::*`, or basename, or same file);
it is recorded here as the fix to make in `vector-member-sweep.py` before it is used again.

**Verdicts, one per group (source read, not tool output):**

* **#1-#3 `GridMasonryLayout`** — `RenderBox*` collected while walking a grid's children; the vector is consumed by
  the same layout pass that fills it. The render tree is owned by `RenderObject` parent/child links, layout does not
  run script (`RenderTreeUpdater` is a separate phase), and the appends are the last statement of their loop bodies.
  Inert.
* **#4 `CollectionIndexCache::m_cachedList`** — the only row whose pointee is **not** separately rooted: a raw
  `Node*` in a heap `Vector`, pushed during a traversal and dereferenced by `nodeAt` (:134) on a later JS call,
  with arbitrary script between the two. Measured in §6: `invalidate()` (`:176`, `m_cachedList.shrink(0)` at `:181`)
  drops the list on every element-affecting structural change, and the arms show the answer flips to the live node.
  Inert **by invalidation**, measured.
* **#5-#7 `KeyedDecoderGeneric`** — the stack members point into `m_rootDictionary`, a `unique_ptr<Dictionary>`
  whose children are `Vector<std::unique_ptr<Dictionary>>` (`platform/generic/KeyedDecoderGeneric.h:37,64`), i.e. the
  pointees are owned all the way down; the frames are keyed-archive decoding with no JS entry point. Inert by
  ownership.
* **#8 `SVGTextQuery::m_textBoxes`** — `SVGInlineTextBox*` collected and consumed by one synchronous query
  (`collectTextBoxesInFlowBox` then the metrics loops); render-tree ownership, no script. Inert.
* **#9 `ItemBuffer::m_allocatedBuffers`** — `uint8_t*` blocks this object allocated itself (`new uint8_t[…]`), freed
  by the destructor and by `std::exchange` at `:736`; the recursion at `:721` is `createItemBuffer` growing its own
  buffer. Inert by ownership.
* **#10-#13 `IDBTransaction::m_transactionOperationsInProgressQueue`** — a `Deque<TransactionOperation*>` whose
  pointees are owned by `m_transactionOperationMap`, a `HashMap<IDBResourceIdentifier, RefPtr<TransactionOperation>>`
  (`:255`), and every loop that appends also holds a `RefPtr` snapshot of the same operations:
  `copyToVectorOf<RefPtr<…>>` at `:269`, `copyToVector(m_transactionOperationMap.values())` at `:1452`,
  `takeFirst()` into a `RefPtr` at `:1499`. `doComplete()` does run script (the request's error handler) — that is
  the `reset`-shaped window — but the snapshot keeps the pointee alive and `abortInProgressOperations` rebuilds the
  deque from a fresh snapshot. Inert by ownership + snapshot.
* **#12's read** is `m_transactionOperationsInProgressQueue.first()` in an `ASSERT` (`:1456`), not a deref.
* **#14-#16** collisions, see above.

## 3. Hash locals

31 `HashSet`/`HashCountedSet`/`HashMap<K, X*>` locals carry a pointer; 26 are inserted inside a loop or by
recursion; 14 read the container afterwards; **0** have a script sink between the insert and the read. The 14 rows,
and why each is inert:

| # | file:line | local | element | function | verdict |
|---|---|---|---|---|---|
| 1 | `rendering/RenderBlockFlow.cpp:202` | `oldIntrudingFloatSet` | `RenderBox*` | `rebuildFloatingObjectSetFromIntrudingFloats` | render tree, no script, consumed in the same layout pass |
| 2 | `rendering/RenderObject.cpp:2265` | `selectedElementsSet` | `Element*` | `borderAndTextRects` | elements are ref-held by the tree; `Range` walk, no script |
| 3 | `rendering/svg/SVGContainerLayout.cpp:58` | `elementsThatDidNotReceiveLayout` | `RenderElement*` | `SVGContainerLayout::layoutChildren` | render tree, no script |
| 4 | `rendering/svg/SVGRenderSupport.cpp:246` | `elementsThatDidNotReceiveLayout` | `RenderElement*` | `SVGRenderSupport::layoutChildren` | same |
| 5 | `svg/SVGRadialGradientElement.cpp:155` | `processedGradients` | `SVGGradientElement*` | `collectGradientAttributes` | cycle guard over a ref-held chain; no script |
| 6 | `animation/DocumentTimeline.cpp:422` | `keyframeEffectStacksToUpdate` | `KeyframeEffectStack*` | `applyPendingAcceleratedAnimations` | collected then used; no script in the body |
| 7 | `layout/.../InlineLineBuilder.cpp:707` | `inlineBoxListWithClonedDecorationEnd` | `const Box*` | `candidateContentForLine` | layout; no script |
| 8 | `Modules/indexeddb/server/IDBServer.cpp:602` | `openDatabases` | `UniqueIDBDatabase*` | `closeDatabasesForOrigins` | database threads, no page script |
| 9 | `accessibility/AccessibilityTable.cpp:485` | `appendedRows` | `AccessibilityObject*` | `addChildren` | AX tree; `addChild` does not dispatch |
| 10 | `rendering/LegacyLineLayout.cpp:461` | `fallbackFonts` | `const Font*` | `setLogicalWidthForTextRun` | `Font` is ref-counted and held by the font cache; no script |
| 11 | `rendering/RenderLayerCompositor.cpp:1553` | `overflowScrollToLastContainedLayerMap` | `RenderLayer*` | `adjustOverflowScrollbarContainerLayers` | compositor pass; no script |
| 12 | `html/HTMLObjectElement.cpp:163` | `uniqueParamNames` | `StringImpl*` | `parametersForPlugin` | `StringImpl` ref-held by the attribute names; no script |
| 13 | `html/HTMLVideoElement.cpp:854` | `elementsAncestorRenderLayers` | `Vector<const RenderLayer*>` | `sortByRenderingOrder` | comparator only |
| 14 | `inspector/DOMPatchSupport.cpp:299` | `merges` | `Digest*` | `innerPatchChildren` | inspector-only; `innerPatchNode` does not run page script |

## 4. The reverse direction, which is where the member shape actually lives

A member vector's buffer is heap for the owner's whole lifetime, so the push→read frame is not the interesting
interval: the dangerous case is the one `CVE-2026-43715` has — the container is **iterated**, the callee runs script,
and the script mutates the container the loop is standing on. `tools/member-iterate-sweep.py` measured that shape
across all 10 container templates: 1,070 range-fors over a member, 512 rows after owner attribution, 38 with a
callback-shaped call, 8 with a client/observer-typed element. Every row in those 38 was read; the guards are:

* **a copy of the container** — `Document::deliverResizeObservations` (`dom/Document.cpp:8589`):
  `auto observersToNotify = m_resizeObservers;` then `observer->deliverObservations()` in the loop. A callback that
  unobserves everything mutates `m_resizeObservers`, not the copy.
* **a two-buffer swap** — `HTMLVideoElement::serviceRequestVideoFrameCallbacks` (`html/HTMLVideoElement.cpp:661`):
  `m_videoFrameRequests.swap(m_servicedVideoFrameRequests);` then the loop, so a callback that calls
  `requestVideoFrameCallback` appends to the *other* vector. (Moot for reachability: `HTMLVideoElement.idl` declares
  no `requestVideoFrameCallback` in this drop, so the loop is not page-reachable at all.)
* **a `RefPtr`/`WeakPtr` element with a null check** — `UniqueIDBDatabase::maybeNotifyConnectionsOfVersionChange`
  (`ListHashSet<RefPtr<UniqueIDBDatabaseConnection>>`), `Document::updateIntersectionObservations`
  (`Vector<WeakPtr<IntersectionObserver>>`, second loop over a local with `if (observer)`).
* **no script at all** — the SVG/CSS/layout rows (`CSSFilter`, `RenderSVGResourceContainer`, `SVGResourcesCache`),
  the AT-SPI/Cocoa/AVF rows (`AccessibilityAtspi`, `PlaybackSessionModelMediaElement`,
  `SourceBufferPrivateAVFObjC`), and the C++ `Function<…>` helpers (`traverseRules`, `hasMatchingEffect`,
  `PasteboardCustomData::forEach*`), whose callbacks never re-enter the engine.

`self_mutating` is 2 and both are current-element removals that the container supports: `ListHashSet::remove` while
iterating (`UniqueIDBDatabase::openDBRequestCancelled`, `:564`) and `HashSet::remove` on a **nested value**
(`BlobURLRegistry::unregisterURL`, `:86`, iterating `m_urlsPerContext` and mutating the mapped `HashSet`).

## 5. The blind spot: the loop is in a helper template, and that is where the live bug is

`CSSFontFace` does not iterate `m_clients` at the call site. It calls a helper:

```cpp
// css/CSSFontFace.cpp:55
template<typename T> void iterateClients(WeakHashSet<CSSFontFace::Client>& clients, T callback)
{
    for (auto& client : copyToVectorOf<Ref<CSSFontFace::Client>>(clients))
        callback(client);
}
```

so `m_clients` never appears in a range-for head and any range-for net — including this one — cannot see the site.
Counted across `Source/WebCore`, calls of the form `helper(m_…, [lambda])`:

* **147** call sites in total. The helper names: `switchOn` 48, `postTaskForModeToWorkerOrWorklet` 19,
  **`iterateClients` 11**, `map` 9, `anyOf` 9, `allOf` 5, `traverseRuleFeatures` 4, `startEngine` 4,
  `connectSimpleBusMessageCallback` 4, `callClientOnMainThread` 4, `wait` 3, `ensure` 3, `createNSArray` 3, and 25
  names with 1-2 sites each (`iterateSet`, `compactMap`, `exchange`, …).
* Of those, the only helper that iterates a **member container of page-reachable clients** and invokes a callback
  that runs script is `iterateClients`, and all 11 sites are in `CSSFontFace.cpp` (`:155, 197, 234, 273, 295, 322,
  341, 357, 436, 591, 769`). `iterateSet` is `DFAMinimizer`'s internal (unsigned indices, no script);
  `callClientOnMainThread` is the curl networking scheduler; `postTaskForModeToWorkerOrWorklet` defers to a task;
  the rest are `WTF::` variant/algorithm helpers.
* So the helper-template surface, read whole, contains exactly one live script window over a member client set —
  and it is `docs/65`'s CVE. Its lifetime is safe (`copyToVectorOf<Ref<…>>`), its defect is semantic (the missing
  `clients.contains(client)` guard), which is the distinction docs/65 already draws.

This is the sweep that should come next (see §8): every `helper(member, lambda)` site where the helper's body
iterates its first parameter and calls its second, resolved two levels (call site → helper → callback body), is a
superset of the range-for net and is the only shape this run could not close by enumeration.

## 6. The measured site: `CollectionIndexCache::m_cachedList`

Row #4 is the first same-class row whose pointee is **not** separately rooted — `Vector<NodeType*>`, capacity 0,
`append(&*current)` at `:55`, dereferenced at `:134` (`return m_cachedList[index];`) from `nodeAt`, which every
indexed collection read reaches (`ChildNodeList.cpp:58`, `CachedLiveNodeList` via `LiveNodeListInlines.h:79`). The
push and the deref are in **different functions**, so no in-function interval can cover this row: the honest test is
whether the list survives a structural change, and that is JS-observable — a stale list answers the *detached* node.

Page `research/vector-member/cache-invalidate.html` (md5 `1584b82b6b2d2208395d292386fdb83d`), runner
`research/vector-member/runs.sh` (md5 `e739595a6678a061fa94a761df6a8cbf`). Quarantine OFF. Run inside the Fedora 39
distrobox — a bare `ssh` run exits 127 with `libasan.so.8: cannot open shared object file`, because the ASAN build
links against the container's `/usr/lib64`:

```
ssh teo@<lab-ip> 'distrobox enter wk -- bash -lc "cd /tmp/wkp && ./runs.sh \
  \"C0 8962 mut=0&mode=children\" \"C1 8963 mut=1&mode=children\" \"C2 8964 mut=1&mode=children&gc=1\" \
  \"T1 8965 mut=1&mode=tag\" \"L1 8966 mut=1&mode=list\" \"D1 8967 mut=1&mode=detached\""'
```

Each arm builds the index cache (`c[last]` then `c.length`, which is what sets `m_listValid` and fills
`m_cachedList`), optionally removes the **first** child, optionally churns 200 000 objects, then re-reads `c[0]` and
`c.length`. A stale `m_cachedList` would answer the removed node (`d0`), not the live one.

```
=== C0  cache-invalidate.html?mut=0&mode=children
access: none
EXIT=124
   B A build mode=children first=d0 last=d7 len=8 n=8
   B C after first=d0 len=8 mut=0 mode=children gc=0
   B D again=d0 removedParented=na
   B F done
=== C1  cache-invalidate.html?mut=1&mode=children
access: none
   B A build mode=children first=d0 last=d7 len=8 n=8
   B B removed=d0
   B C after first=d1 len=7 mut=1 mode=children gc=0
   B D again=d1 removedParented=no
   B E reattached first=d0 len=8
   B F done
=== C2  cache-invalidate.html?mut=1&mode=children&gc=1
access: none
   B A build mode=children first=d0 last=d7 len=8 n=8
   B B removed=d0
   B C after first=d1 len=7 mut=1 mode=children gc=1
   B D again=d1 removedParented=no
   B E reattached first=d0 len=8
   B F done
=== T1  cache-invalidate.html?mut=1&mode=tag
access: none
   B A build mode=tag first=root last=d7 len=9 n=8
   B B removed=d0
   B C after first=root len=8 mut=1 mode=tag gc=0
   B D again=root removedParented=no
   B E reattached first=root len=9
   B F done
=== L1  cache-invalidate.html?mut=1&mode=list
access: none
   B A build mode=list first=d0 last=#t:t7 len=16 n=8
   B B removed=d0
   B C after first=d1 len=15 mut=1 mode=list gc=0
   B D again=d1 removedParented=no
   B E reattached first=d0 len=16
   B F done
=== D1  cache-invalidate.html?mut=1&mode=detached
access: none
   B A build mode=detached first=x0 last=x7 len=8 n=8
   B B removed=x0
   B C after first=x1 len=7 mut=1 mode=detached gc=0
   B D again=x1 removedParented=no
   B E reattached first=x0 len=8
   B F done
```

`access: none` in 6/6; `grep -c AddressSanitizer data/vector-member/logs/*.log` is 0 in all twelve logs
(`run_C0/C1/C2/T1/L1/D1.log`, `srv8962…srv8967.log`). `EXIT=124` is the harness's normal end (`timeout` kills
MiniBrowser), as docs/65 "Attempt 11" established.

What each arm rules out:

* **C0** the control: with no mutation the cached answer is still `d0` and the length is 8 — the reads in the other
  arms are not simply "always the live node" by accident.
* **C1** removal invalidates: `d1`/7. A surviving `m_cachedList` would have returned the detached `d0` at `:134`.
* **C2** the same answer with 200 000 allocations after the removal, so the removed node was collectible and the
  list still did not come back.
* **T1** a document-level `getElementsByTagName` collection (invalidation type `AtDocument`) behaves the same.
* **L1** `childNodes`, i.e. `ChildNodeList`, whose `willValidateIndexCache()` is an **empty override**
  (`dom/ChildNodeList.h:78`) so it never registers at the document and rides only the per-node ancestor path
  (`Node::invalidateNodeListAndCollectionCachesInAncestors`, `dom/Node.cpp:996-1014`) — the arm most likely to
  fail, and it does not.
* **D1** a collection rooted in a **detached** subtree: `invalidateNodeListAndCollectionCachesInAncestors` walks
  `this → parentNode()` (all null here) but the document-wide pass still reaches the collection, because
  `willValidateIndexCache` registered it (`CachedHTMLCollection.h:56`).

## 7. Verdict counts

* **49** raw-pointer member declarations in the tree; **16** rows that grow in a loop or by recursion; **13** of those
  are same-class (3 are name collisions); **5** read the member after the push in the same function; **0** have a JS
  entry point in that interval.
* **31** pointer-carrying hash locals; **26** inserted in a loop; **14** read after; **0** with a sink.
* **1,599** member containers; **1,070** range-fors; **512** attributed rows; **38** with a callback-shaped call;
  **8** client-typed; **0** with a live, unguarded script window after reading all 38.
* **147** member+lambda helper call sites; **1** helper (`iterateClients`) runs script over a page-reachable member
  client container; **11** sites, all in `CSSFontFace.cpp`, all `docs/65`'s bug.
* **1** measured site (`CollectionIndexCache::m_cachedList`), 6 arms, 0 sanitizer reports, 1 corrected expectation
  (`childNodes` is guarded despite its empty `willValidateIndexCache()`).
* **0** new live bugs; **1** tool defect found and fixed in the second tool only (name-only attribution).

## 8. What this changes, and the next action

The member *push* class is closed: 49 declarations, 13 same-class rows, and the only one whose pointee is not
separately rooted (`CollectionIndexCache::m_cachedList`) is invalidated on the structural change, measured. The
member *iterate* class is guarded at every one of the 38 callback rows, by four different mechanisms.

The one thing this run could not close by enumeration is the **helper-template** shape (§5): 147 `helper(member,
lambda)` sites, of which only `iterateClients` is a script window over a member client container. That is the next
sweep, and it is a superset of the range-for net: for each site, resolve the helper's body (does it iterate its
first parameter and call its second?), then the callback body (does it call a method on the element that runs
script?), then whether the helper snapshots or refs (a `copyToVectorOf<Ref<…>>` makes the lifetime safe and the
defect semantic; a raw `for (auto& x : container)` makes it a UAF).

Nothing here needs the console; the hardware half of docs/65 "Attempt 9" and docs/76 remains blocked on the
operator restarting the Guide app.
