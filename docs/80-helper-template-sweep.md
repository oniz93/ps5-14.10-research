# docs/80 — the *helper-template* shape: 219 `helper(member, lambda)` call sites, 42 that actually iterate a container parameter, 0 with a script-capable callback — and the method spelling of the same shape is the guarded one

The action (`GOAL.md`, first item): docs/79 closed both enumerable member shapes and named the hole in its own net.
WebKit writes client iteration as a **helper template** —

```cpp
template<typename T> void iterateClients(WeakHashSet<CSSFontFace::Client>& clients, T callback)
{
    for (auto& client : copyToVectorOf<Ref<CSSFontFace::Client>>(clients))
        callback(client);
}
```
`css/CSSFontFace.cpp:55-59`

— so at the call site (`iterateClients(m_clients, [&](Client& client) { … })`) the member never appears in a
range-for head, and a per-call-site sweep for `for (… : m_member)` cannot see it at all. `iterateClients` is exactly
CVE-2026-43715's loop (`docs/65`), so this is the one hole docs/79 could name but not measure.

This doc is that sweep. It resolves, for every call that passes a member container and a lambda to the same
function, the helper's body → the callback's body → snapshot-or-not, and it adds the spelling docs/79 also could
not see: the **method** helper (`m_members.forEach([&](auto& c) { … })`), where the container is the receiver
rather than an argument.

Five results:

1. **The population is 219 syntactic `helper(member, [lambda])` sites across 24 helper names; only 42 sites — a
   slightly different set — are sites of a helper that genuinely iterates one parameter and calls another inside
   that loop.** The two sets differ because the second one does not require a lambda *literal*: the callback
   argument may be a named function or function pointer (`DOMCacheStorage.cpp:98` passes `copyCache`,
   `StyleSheetContents.cpp:508` passes `handler`, `MediaPlayerPrivateMediaStreamAVFObjC.mm` passes
   `&AudioTrackPrivateMediaStream::create`). The other 177 of the 219 are `WTF::switchOn` variant visits
   (134 — one visitor per alternative, no container), task-queue calls (19 `postTaskForModeToWorkerOrWorklet`,
   `queueTaskKeepingObjectAlive`), `ensure`/`wait`/`exchange`, and names with no definition in the two indexed
   trees. Per-name accounting in §3 — no name is dropped.
2. **Of the 42, 11 are `iterateClients` (snapshot: `copyToVectorOf<Ref<Client>>`) and 31 are raw.** The 31 raw
   rows decompose completely: **7 are `.mm` files that are not in the PlayStation build** (`SourcesCocoa.txt`),
   **1 is `ENABLE(WIRELESS_PLAYBACK_TARGET)` code that is `PRIVATE OFF`**, **2 are not member iteration at all**
   (the helper iterates `parent.normalFlowLayers()`, a derived child list), and the remaining 21 are compiled
   WebCore paths whose callbacks are pure value/predicate transforms (`is2D`, `isCompleted`, `matches`, `ended`,
   `asValidatedFormListedElement`, `Ref`/`RefPtr` copies). **0 have a script-capable callback**, checked two ways:
   a token scan over the callback body (`dispatchEvent`, `JSC::`, `resolve(`, `scheduleEvent`, …) and reading the
   callee for every non-trivial call.
3. **The method spelling is the guarded one, and this is structural, not luck.** 77 `m_member.<forEach|map>(lambda)`
   sites: 52 `.forEach`, of which **51 are `WeakHashSet::forEach`** — which *snapshots* (`map(m_set, …)` into a
   local) and re-checks `m_set.contains(*item.m_impl)` before each callback — and 25 `.map`, all `Vector::map`
   (`WTF/wtf/Vector.h:1683`) except one member whose declaration the index could not resolve. 43 of them are
   client/observer-typed; every client family's callback was resolved to
   its implementation: `HTMLTrackElement` (`scheduleLoad()`), `HTMLMediaElement` (`scheduleChangeEvent()` — queued,
   not dispatched), and `FontFaceSet`. Only the last one reaches script, and it reaches it through
   `CSSFontFace::iterateClients` — i.e. `docs/65`.
4. **No helper in this drop iterates a member of a *parameter*** (`helper(*this, lambda)` whose body does
   `for (… : object.m_member)`): 0 of the 42 helper variants read `parameter.m_member` in a loop head. The
   owner-shaped spelling that does exist (`traverseVisibleNonCompositedDescendantLayers`) iterates a *computed*
   child list, not a member.
5. **Measured, not argued: a `<track>`-created `TextTrack` really has two clients**, so one `setMode()` drives two
   iterations of `WeakHashSet::forEach` and the loop's second `contains()` runs *after* the first client callback.
   Both witnesses fire from one call — `change` on `video.textTracks` (the media element client) and
   `error`/`readyState=3` on the `<track>` element (the element client, whose `scheduleLoad()` the server log shows
   as a real `GET /nope.vtt` → 404) — with `access: none` under ASAN, quarantine off (§7).

**No ASAN run is recorded for a candidate site, and the action's conditional clause is what makes that correct**: it
asks for a quarantine-off run "for the first site that is a raw iteration of a page-reachable container".
Page-reachable raw iterations do exist — a form's `m_listedElements`, a stylesheet's `m_childRules`,
`Page::m_corsDisablingPatterns`, `TreeScopeOrderedMap::m_map`, `DOMCacheStorage::m_caches`,
`BackgroundFetch::m_records` — but **not one of their callbacks can run script** (§4 has the per-row reason, and
the token scan is empty for all 31), and a run that cannot put script inside the loop has nothing to attribute to
this shape. The one run this doc does record (§7) is a *reachability* measurement of the guarded idiom, not a
candidate hunt.

## 1. Tool and funnels

One new tool, `tools/helper-callback-sweep.py` (28s), over the 10,500 `.cpp`/`.mm`/`.h` files of `Source/WebCore`
for call sites, and over `Source/WTF` + `Source/WebCore` (11,396 files) for helper definitions:

```
$ python3 tools/helper-callback-sweep.py > data/helper-callback/sites.json
files: 10500 (helper index: 11396)
helpers: 37 names, 42 variants (iterate-param + call-param inside the loop)
sites (member in the iterated position): 42
member declarations indexed: 1316 names
method-helper sites (m_x.<forEach|map>(lambda)): 77
syntactic helper(member, lambda) sites: 219 across 24 names
shapes: {'raw': 31, 'snapshot': 11}
raw sites: 31, distinct containers 28, client-shaped 0
```

Passes:

* **H (helpers).** Every function definition whose body contains `for (… : <param>)` over a *parameter* and calls
  another parameter from inside that loop head's body. Records the container parameter's declared type (so the
  element class comes from the declaration, not from a guess), the callback parameter, and whether the loop head
  snapshots (`copyToVectorOf<…>`, `copyToVector(`, `WTF::map(`). 37 names / 42 variants.
* **S (sites).** Every call to one of those helpers where the argument in the *iterated* position is a member
  (`m_foo`, `this->m_foo`, `x->m_foo`). 42 sites, each joined to its helper variant, to the member's declared type
  (from a 1,316-name cross-file member index), and to the callback body's first method call on the element.
* **M (method helpers).** `m_member.<forEach|reverseForEach|map|forEachInContainer>(lambda)`; 77 sites, with the
  member's type resolved the same way.

## 2. Every resolved site

### A. `helper(member, lambda)` — the 42 sites that reach a real loop

| # | helper | call site | container | container type | shape | callback's first call |
|---|---|---|---|---|---|---|
| A1 | `iterateClients` | `css/CSSFontFace.cpp:155` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A2 | `iterateClients` | `css/CSSFontFace.cpp:197` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A3 | `iterateClients` | `css/CSSFontFace.cpp:234` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A4 | `iterateClients` | `css/CSSFontFace.cpp:273` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A5 | `iterateClients` | `css/CSSFontFace.cpp:295` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A6 | `iterateClients` | `css/CSSFontFace.cpp:322` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A7 | `iterateClients` | `css/CSSFontFace.cpp:341` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A8 | `iterateClients` | `css/CSSFontFace.cpp:357` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontPropertyChanged` |
| A9 | `iterateClients` | `css/CSSFontFace.cpp:436` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontLoaded` |
| A10 | `iterateClients` | `css/CSSFontFace.cpp:591` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.fontStateChanged` |
| A11 | `iterateClients` | `css/CSSFontFace.cpp:769` | `m_clients` | `WeakHashSet<Client>` | snapshot | `client.updateStyleIfNeeded` |
| A12 | `allOf` | `Modules/airplay/WebMediaSessionManager.cpp:151` | `m_clientState` | `Vector<std::unique_ptr<ClientState>>` | raw | `client.alwaysOnLoggingAllowed` |
| A13 | `allOf` | `css/typedom/transform/CSSTransformValue.cpp:141` | `m_components` | `Vector<RefPtr<CSSTransformComponent>>` | raw | `component.is2D` |
| A14 | `anyOf` | `Modules/mediastream/RTCRtpSFrameTransformer.cpp:167` | `m_keys` | `Vector<String>` | raw | — |
| A15 | `anyOf` | `css/calc/CSSCalcOperationNode.cpp:1063` | `m_children` | `Vector<Ref<CSSCalcExpressionNode>>` | raw | `child.convertingToLengthRequiresNonNullStyle` |
| A16 | `anyOf` | `page/Page.cpp:4107` | `m_corsDisablingPatterns` | `Vector<UserContentURLPattern>` | raw | `pattern.matches` |
| A17 | `anyOf` | `platform/audio/PlatformMediaSessionManager.cpp:136` | `m_audioCaptureSources` | `WeakHashSet<AudioCaptureSource>` | raw | `source.isCapturingAudio` |
| A18 | `anyOf` | `platform/audio/PlatformMediaSessionManager.cpp:593` | `m_sessions` | `Vector<WeakPtr<PlatformMediaSession>>` | raw | — |
| A19 | `anyOf` | `platform/graphics/avfoundation/objc/MediaSourcePrivateAVFObjC.mm:330` | `m_sourceBuffers` | `Vector<RefPtr<SourceBufferPrivateAVFObjC>>` | raw | `sourceBuffer.waitingForKey` |
| A20 | `anyOf` | `platform/mediastream/MediaStreamPrivate.cpp:130` | `m_trackSet` | `?` | raw | `value.ended` |
| A21 | `anyOf` | `workers/service/background-fetch/BackgroundFetch.cpp:211` | `m_records` | `Vector<Ref<Record>>` | raw | `record.isCompleted` |
| A22 | `compactMap` | `html/HTMLFormElement.cpp:148` | `m_imageElements` | `Vector<WeakPtr<HTMLImageElement>>` | raw | — |
| A23 | `compactMap` | `html/HTMLFormElement.cpp:960` | `m_listedElements` | `Vector<WeakPtr<HTMLElement>>` | raw | `weakElement.asValidatedFormListedElement` |
| A24 | `createNSArray` | `platform/cocoa/SharedBufferCocoa.mm:166` | `m_segments` | `Vector<CSSUnparsedSegment>` | raw | `segment.createNSData` |
| A25 | `createNSArray` | `platform/graphics/avfoundation/objc/CDMInstanceFairPlayStreamingAVFObjC.mm:827` | `m_expiredSessions` | `Vector<RetainPtr<NSData>>` | raw | — |
| A26 | `createNSArray` | `platform/graphics/avfoundation/objc/CDMSessionAVContentKeySession.mm:309` | `m_protocolVersions` | `Vector<int>` | raw | — |
| A27 | `createNSArray` | `platform/network/cocoa/ResourceRequestCocoa.mm:310` | `m_responseContentDispositionEncodingFallbackArray` | `Vector<String>` | raw | `name.createCFString` |
| A28 | `map` | `Modules/cache/DOMCacheStorage.cpp:98` | `m_caches` | `Vector<Ref<DOMCache>>` | raw | — |
| A29 | `map` | `Modules/cache/DOMCacheStorage.cpp:259` | `m_caches` | `Vector<Ref<DOMCache>>` | raw | — |
| A30 | `map` | `Modules/indexeddb/server/MemoryObjectStore.cpp:158` | `m_indexesByName` | `HashMap<String, RefPtr<MemoryIndex>>` | raw | `value.info` |
| A31 | `map` | `Modules/indexeddb/shared/IDBDatabaseInfo.cpp:137` | `m_objectStoreMap` | `HashMap<uint64_t, IDBObjectStoreInfo>` | raw | — |
| A32 | `map` | `Modules/indexeddb/shared/IDBObjectStoreInfo.cpp:112` | `m_indexMap` | `HashMap<uint64_t, IDBIndexInfo>` | raw | — |
| A33 | `map` | `dom/TreeScopeOrderedMap.cpp:232` | `m_map` | `HashMap<QualifiedName, std::variant<…>>` | raw | — |
| A34 | `map` | `html/HTMLFormElement.cpp:949` | `m_listedElements` | `Vector<WeakPtr<HTMLElement>>` | raw | `element.asFormListedElement` |
| A35 | `map` | `loader/DocumentLoader.cpp:2421` | `m_linkIcons` | `Vector<LinkIcon>` | raw | — |
| A36 | `map` | `loader/ResourceTiming.cpp:83` | `m_serverTiming` | `Vector<ServerTiming>` | raw | — |
| A37 | `map` | `svg/graphics/filters/SVGFilterGraph.h:121` | `m_nodeInputs` | `HashMap<Ref<NodeType>, NodeVector>` | raw | — |
| A38 | `traverseRulesInVector` | `css/StyleSheetContents.cpp:508` | `m_childRules` | `Vector<Ref<StyleRuleBase>>` | raw | — |
| A39 | `traverseVisibleNonCompositedDescendantLayers` | `rendering/RenderLayerBacking.cpp:3001` | `m_owningLayer` | `?` | raw | `layer.isVisuallyNonEmpty` |
| A40 | `traverseVisibleNonCompositedDescendantLayers` | `rendering/RenderLayerBacking.cpp:3019` | `m_owningLayer` | `?` | raw | `layer.hasVisibleContent` |
| A41 | `updateTracksOfKind` | `platform/graphics/avfoundation/objc/MediaPlayerPrivateMediaStreamAVFObjC.mm:961` | `m_audioTrackMap` | `HashMap<String, Ref<…>>` | raw | — |
| A42 | `updateTracksOfKind` | `platform/graphics/avfoundation/objc/MediaPlayerPrivateMediaStreamAVFObjC.mm:986` | `m_videoTrackMap` | `HashMap<String, Ref<…>>` | raw | — |

`A10` is `docs/65`'s loop, at the line the ASAN trace names (`setStatus` → `iterateClients` → `client.fontStateChanged`):

```cpp
    iterateClients(m_clients, [&](Client& client) {
        client.fontStateChanged(*this, m_status, newStatus);
    });

    m_status = newStatus;
```
`css/CSSFontFace.cpp:591-595`

Two `?` rows are named-member resolutions the index could not make (`m_trackSet`, `m_owningLayer` are declared in
headers with a different shape than `Container<…> m_x;`); both were read by hand (§4).

## 3. Per-name accounting — the 177 sites that are not this shape

Every helper name that appears at a `helper(member, [` call site, with how many definitions of that name exist in
the two indexed trees, how many of those iterate a parameter, how many call a *callable* parameter from inside
that loop, and how many variants survived into §2:

| helper name | sites | defs | defs iterating a param | defs calling a param in that loop | resolved variants |
|---|---|---|---|---|---|
| `switchOn` | 134 | 0 | 0 | 0 | 0 |
| `postTaskForModeToWorkerOrWorklet` | 19 | 0 | 0 | 0 | 0 |
| `iterateClients` | 11 | 2 | 1 | 1 | 1 |
| `map` | 9 | 7 | 5 | 5 | 5 |
| `anyOf` | 8 | 1 | 1 | 1 | 1 |
| `wait` | 4 | 4 | 0 | 0 | 0 |
| `callClientOnMainThread` | 4 | 0 | 0 | 0 | 0 |
| `traverseRuleFeatures` | 4 | 1 | 0 | 0 | 0 |
| `ensure` | 3 | 3 | 0 | 0 | 0 |
| `createNSArray` | 3 | 2 | 2 | 1 | 1 |
| `allOf` | 2 | 1 | 1 | 1 | 1 |
| `closeSession` | 2 | 0 | 0 | 0 | 0 |
| `compactMap` | 2 | 3 | 2 | 2 | 2 |
| `invokeDidReceiveResponse` | 2 | 0 | 0 | 0 | 0 |
| `enchant_broker_list_dicts` | 2 | 0 | 0 | 0 | 0 |
| `traverseVisibleNonCompositedDescendantLayers` | 2 | 1 | 1 | 1 | 1 |
| `ensureOnContextThread` | 1 | 0 | 0 | 0 | 0 |
| `exchange` | 1 | 11 | 0 | 0 | 0 |
| `iterateSet` | 1 | 1 | 0 | 0 | 0 |
| `consumeCommaSeparatedListWithSingleValueOptimization` | 1 | 1 | 0 | 0 | 0 |
| `beginRoutingArbitrationWithCategory` | 1 | 0 | 0 | 0 | 0 |
| `backgroundFetchIdentifiers` | 1 | 0 | 0 | 0 | 0 |
| `retrieveRecordResponseBody` | 1 | 0 | 0 | 0 | 0 |
| `CancellableTask` | 1 | 0 | 0 | 0 | 0 |

The 177 non-shape sites are one of four things, and each is worth naming because the next sweep should not
re-find them:

* **`switchOn` (134).** `WTF::switchOn(variant, [&](TypeA& a) { … }, [&](TypeB& b) { … })` — a Variant *visit*.
  Exactly one visitor runs, and its argument is a reference **into the variant object**, not into a container.
  There is no buffer to free and no iteration; it cannot be this shape. (The tool reports 0 definitions because
  `switchOn`'s return type is `decltype(auto)` and the signature parser stops at the `decltype(…)` parenthesis —
  a parser limitation, not a missing definition: `WTF/wtf/Variant.h`.)
* **Task queues (19 `postTaskForModeToWorkerOrWorklet`, plus `ensure`, `ensureOnContextThread`, `wait`,
  `invokeDidReceiveResponse`, `callClientOnMainThread`).** The lambda is *stored* and run later; nothing is
  iterated at the call.
* **`exchange`/`closeSession`/`beginRoutingArbitration…`** — a call whose second argument happens to be a lambda
  for an unrelated callback; `exchange`'s 11 definitions never iterate a parameter.
* **Names with no definition in `Source/WTF` + `Source/WebCore`** (`callClientOnMainThread`,
  `enchant_broker_list_dicts`, `backgroundFetchIdentifiers`, `CancellableTask`, …) — macros, member functions, or
  definitions in `Source/WebKit`. A member-function helper is covered by population B instead.

## 4. Verdicts, row by row

**Not compiled (7 rows: A19, A24–A27, A41, A42).** Every one is a `.mm` file listed in `SourcesCocoa.txt` and
absent from `Sources.txt`, so the PlayStation build never sees it:

```
platform/cocoa/SharedBufferCocoa.mm                                    cocoa=1 cross=0
platform/graphics/avfoundation/objc/MediaSourcePrivateAVFObjC.mm       cocoa=1 cross=0
platform/graphics/avfoundation/objc/CDMSessionAVContentKeySession.mm   cocoa=1 cross=0
platform/network/cocoa/ResourceRequestCocoa.mm                         cocoa=1 cross=0
platform/graphics/avfoundation/objc/MediaPlayerPrivateMediaStreamAVFObjC.mm cocoa=1 cross=0
platform/audio/mac/AudioSessionMac.mm                                  cocoa=1 cross=0
```

**Compiled out (A12).** `Modules/airplay/WebMediaSessionManager.cpp` is entirely inside
`#if ENABLE(WIRELESS_PLAYBACK_TARGET) && !PLATFORM(IOS_FAMILY)` (line 29), and the feature is off by default with
no PlayStation override:

```
cmake/WebKitFeatures.cmake:264:    WEBKIT_OPTION_DEFINE(ENABLE_WIRELESS_PLAYBACK_TARGET "Toggle wireless playback target support" PRIVATE OFF)
```

**Not member iteration (A39, A40).** `traverseVisibleNonCompositedDescendantLayers(const RenderLayer& parent, …)`
iterates `parent.normalFlowLayers()` — a `Vector` *returned by value* from a getter — so the container the loop
walks is a temporary, not `m_owningLayer`. The callbacks (`isVisuallyNonEmpty`, `hasVisibleContent`) are rendering
predicates and the frame runs no script; nothing in it can mutate the temporary.

**Compiled, and the callback cannot run script (21 rows).** The whole set is value/predicate work: `is2D()`
(A13), `convertingToLengthRequiresNonNullStyle` (A15), `matches` (A16), `isCapturingAudio` (A17), `ended` (A20),
`isCompleted` (A21), `asValidatedFormListedElement`/`asFormListedElement` (A23, A34), and the `WTF::map`/`compactMap`
family whose lambdas return `RefPtr`/`String`/`AtomString`/pairs (A14, A28–A37). Element ownership is explicit
too — 13 value, 6 `Ref`, 3 `RefPtr`, 4 `WeakPtr` (5 unresolved, and all of those are the `.mm`/`?` rows) — so even
a reallocation of the *buffer* (which none of these callbacks can trigger) cannot dangle an element the loop later
hands to the callback.

`traverseRulesInVector(m_childRules, handler)` (A38) is the only one that hands the loop's element to a caller's
handler; the handlers are `StyleSheetContents::traverseSubresources` (and its recursion into `@import`ed sheets,
`:499-507`) and `StyleScope.cpp:181`'s `releaseCompiledSelectors()` (a `const StyleRuleBase&` inspection under
`ENABLE(CSS_SELECTOR_JIT)`), both pure. `m_childRules` is `Vector<Ref<StyleRuleBase>>` (`StyleSheetContents.h:172`)
— a CSSOM `insertRule` inside such a handler would free the *buffer*, and no handler can run script to reach CSSOM.

## 5. Population B — `m_member.forEach(lambda)` / `.map(lambda)`, 77 sites

```
method-helper sites (m_x.<forEach|map>(lambda)): 77
  .forEach 52   (51 of them WeakHashSet::forEach)
  .map     25   (all Vector::map)
```

The two library implementations are the whole verdict, and they are opposites in the one way that matters:

```cpp
    void forEach(const Function<void(T&)>& callback)
    {
        auto items = map(m_set, [](const Ref<WeakPtrImpl>& item) { … return WeakPtr<T, WeakPtrImpl> { pointer }; });
        for (auto& item : items) {
            // FIXME: This contains check is only necessary if the set is being mutated during iteration.
            // Change it to an assertion, or make this function use begin() and end().
            if (item && m_set.contains(*item.m_impl))
                callback(*item);
        }
    }
```
`WTF/wtf/WeakHashSet.h:159-171`

```cpp
inline auto Vector<T, …>::map(MapFunction&& mapFunction) const -> …
{
    ResultVector result;
    result.reserveInitialCapacity(size());
    for (size_t i = 0; i < size(); ++i)      // size() is re-read every iteration
        result.uncheckedAppend(mapFunction(at(i)));
    return result;
}
```
`WTF/wtf/Vector.h:1683-1691`

`WeakHashSet::forEach` snapshots into `items` and re-checks membership before each call — the guard the FIXME
describes as "only necessary if the set is being mutated during iteration", i.e. exactly the guard upstream's
`iterateClients` has and Sony's does not. `Vector::map` snapshots nothing: it is an index loop with `size()`
re-read every iteration, so a lambda that shrank the vector would walk past the end (`at()`'s bound is an
`ASSERT`, not a check, in release). Both are safe here for the same reason the 31 raw rows are: the callbacks are
value transforms.

The 43 client/observer-typed sites, and every implementor each one reaches:

| # | call site | member | element | callback's first call |
|---|---|---|---|---|
| B1 | `bindings/js/WebCoreJSClientData.cpp:142` | `m_clients` | `WeakHashSet<Client>` | `client.willDestroyVM` |
| B2 | `css/CSSFontFaceSet.cpp:78` | `m_fontEventClients` | `WeakHashSet<FontEventClient>` | `client.startedLoading` |
| B3 | `css/CSSFontFaceSet.cpp:89` | `m_fontEventClients` | `WeakHashSet<FontEventClient>` | `client.completedLoading` |
| B4 | `css/CSSFontFaceSet.cpp:199` | `m_fontModifiedObservers` | `WeakHashSet<FontModifiedObserver>` | — |
| B5 | `css/CSSFontFaceSet.cpp:256` | `m_fontModifiedObservers` | `WeakHashSet<FontModifiedObserver>` | — |
| B6 | `css/CSSFontFaceSet.cpp:533` | `m_fontEventClients` | `WeakHashSet<FontEventClient>` | `client.faceFinished` |
| B7 | `css/CSSFontFaceSet.cpp:549` | `m_fontModifiedObservers` | `WeakHashSet<FontModifiedObserver>` | — |
| B8 | `html/track/AudioTrack.cpp:102` | `m_clients` | `WeakHashSet<AudioTrackClient>` | `client.audioTrackLanguageChanged` |
| B9 | `html/track/AudioTrack.cpp:123` | `m_clients` | `WeakHashSet<AudioTrackClient>` | `client.audioTrackEnabledChanged` |
| B10 | `html/track/AudioTrack.cpp:152` | `m_clients` | `WeakHashSet<AudioTrackClient>` | `client.audioTrackEnabledChanged` |
| B11 | `html/track/AudioTrack.cpp:165` | `m_clients` | `WeakHashSet<AudioTrackClient>` | `client.audioTrackIdChanged` |
| B12 | `html/track/AudioTrack.cpp:173` | `m_clients` | `WeakHashSet<AudioTrackClient>` | `client.audioTrackLabelChanged` |
| B13 | `html/track/AudioTrack.cpp:185` | `m_clients` | `WeakHashSet<AudioTrackClient>` | `client.willRemoveAudioTrack` |
| B14 | `html/track/InbandTextTrack.cpp:168` | `m_clients` | `WeakHashSet<AudioTrackClient>` | `client.willRemoveTextTrack` |
| B15 | `html/track/TextTrack.cpp:117` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackRemoveCues` |
| B16 | `html/track/TextTrack.cpp:215` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackKindChanged` |
| B17 | `html/track/TextTrack.cpp:258` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackRemoveCues` |
| B18 | `html/track/TextTrack.cpp:270` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackModeChanged` |
| B19 | `html/track/TextTrack.cpp:294` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackRemoveCues` |
| B20 | `html/track/TextTrack.cpp:351` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackAddCue` |
| B21 | `html/track/TextTrack.cpp:377` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackRemoveCue` |
| B22 | `html/track/TextTrack.cpp:472` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackRemoveCue` |
| B23 | `html/track/TextTrack.cpp:485` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackAddCue` |
| B24 | `html/track/TextTrack.cpp:629` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackLanguageChanged` |
| B25 | `html/track/TextTrack.cpp:637` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackIdChanged` |
| B26 | `html/track/TextTrack.cpp:645` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackLabelChanged` |
| B27 | `html/track/TextTrack.cpp:652` | `m_clients` | `WeakHashSet<TextTrackClient>` | `client.textTrackAddCues` |
| B28 | `html/track/VideoTrack.cpp:108` | `m_clients` | `WeakHashSet<VideoTrackClient>` | `client.videoTrackSelectedChanged` |
| B29 | `html/track/VideoTrack.cpp:133` | `m_clients` | `WeakHashSet<VideoTrackClient>` | `client.videoTrackSelectedChanged` |
| B30 | `html/track/VideoTrack.cpp:146` | `m_clients` | `WeakHashSet<VideoTrackClient>` | `client.videoTrackIdChanged` |
| B31 | `html/track/VideoTrack.cpp:154` | `m_clients` | `WeakHashSet<VideoTrackClient>` | `client.videoTrackLabelChanged` |
| B32 | `html/track/VideoTrack.cpp:166` | `m_clients` | `WeakHashSet<VideoTrackClient>` | `client.willRemoveVideoTrack` |
| B33 | `html/track/VideoTrack.cpp:186` | `m_clients` | `WeakHashSet<VideoTrackClient>` | `client.videoTrackKindChanged` |
| B34 | `html/track/VideoTrack.cpp:206` | `m_clients` | `WeakHashSet<VideoTrackClient>` | `client.videoTrackLanguageChanged` |
| B35 | `platform/audio/mac/AudioSessionMac.mm:211` | `m_configurationChangeObservers` | `WeakHashSet<ConfigurationChangeObserver>` | `observer.sampleRateDidChange` |
| B36 | `platform/audio/mac/AudioSessionMac.mm:263` | `m_configurationChangeObservers` | `WeakHashSet<ConfigurationChangeObserver>` | `observer.bufferSizeDidChange` |
| B37 | `platform/audio/mac/AudioSessionMac.mm:484` | `m_configurationChangeObservers` | `WeakHashSet<ConfigurationChangeObserver>` | `observer.bufferSizeDidChange` |
| B38 | `platform/audio/mac/AudioSessionMac.mm:541` | `m_configurationChangeObservers` | `WeakHashSet<ConfigurationChangeObserver>` | `observer.hardwareMutedStateDidChange` |
| B39 | `platform/graphics/avfoundation/objc/CDMInstanceFairPlayStreamingAVFObjC.mm:673` | `m_keyStatusChangedObservers` | `WeakHashSet<KeyStatusesChangedObserver>` | — |
| B40 | `platform/mediastream/RealtimeMediaSourceCenter.cpp:222` | `m_observers` | `WeakHashSet<Observer>` | `observer.deviceWillBeRemoved` |
| B41 | `platform/mediastream/RealtimeMediaSourceCenter.cpp:230` | `m_observers` | `WeakHashSet<Observer>` | `observer.devicesChanged` |
| B42 | `platform/mediastream/cocoa/AudioMediaStreamTrackRendererUnit.cpp:126` | `m_resetObservers` | `WeakHashSet<ResetObserver>` | — |
| B43 | `dom/EventListenerMap.cpp:89` | `m_entries` | `Vector<std::pair<AtomString, EventListenerVector>>` | — |

B35–B39 and B42 are `.mm` (not built). B40/B41's only implementors are `BaseAudioSharedUnit` (mac) and
`GStreamerCaptureDeviceManager` (gstreamer: `USE_GSTREAMER` is not set in `OptionsPlayStation.cmake`), so on this
port the observer set is empty. B1 is `WebCoreJSClientData`'s VM-client set, not page-reachable.

The three families that are page-reachable (`html/track` ×27, `css/CSSFontFaceSet` ×6) resolve like this:

* **`TextTrackClient` has exactly two implementors**, and both were read. `HTMLTrackElement`
  (`html/HTMLTrackElement.h:40`) overrides exactly one method:

  ```cpp
  void HTMLTrackElement::textTrackModeChanged(TextTrack&)
  {
      // Since we've moved to a new parent, we may now be able to load.
      if (readyState() == HTMLTrackElement::NONE)
          scheduleLoad();
  }
  ```
  `html/HTMLTrackElement.cpp:300-305`

  `scheduleLoad()` is a queued load, not a dispatch; the other ten `textTrack*` callbacks are the interface's
  empty defaults. `HTMLMediaElement` (`html/HTMLMediaElement.h:147`, private inheritance) overrides all nine, and
  every one is a queued list-change event, a layout query, or a *re-entrant* iteration that is safe by its own
  early-out:

  ```cpp
  void HTMLMediaElement::textTrackKindChanged(TextTrack& track)
  {
      if (track.kind() != TextTrack::Kind::Captions && …
          track.setMode(TextTrack::Mode::Hidden);   // re-enters TextTrack::setMode → m_clients.forEach again
      if (m_textTracks && m_textTracks->contains(track))
          m_textTracks->scheduleChangeEvent();
  }
  ```
  `html/HTMLMediaElement.cpp:2212-2219`

  The re-entry is a *nested* `forEach` over the same set, which takes its own snapshot, and `setMode` returns at
  `if (m_mode == mode)` on the second entry (`TextTrack.cpp:250`). So B15–B27 run no script and free nothing.
* **`AudioTrackClient`/`VideoTrackClient` are implemented by `HTMLMediaElement`** (`html/HTMLMediaElement.h:146,148`),
  and every override in this family is one of two shapes — a queued list-change event or a pure check:

  ```cpp
  void HTMLMediaElement::audioTrackEnabledChanged(AudioTrack& track)
  {
      if (m_audioTracks && m_audioTracks->contains(track))
          m_audioTracks->scheduleChangeEvent();
      …
  }
  ```
  `html/HTMLMediaElement.cpp:2146-2152`

  `scheduleChangeEvent()` enqueues a task; `checkForAudioAndVideo()` is a layout query. B8–B14 and B28–B34 run no
  script inside the loop.
* **`FontEventClient` has one implementor, `FontFaceSet`** (`css/FontFaceSet.h:41`), and `faceFinished` is the
  `m_wrapper`/`m_pendingPromises.take()` path measured in `docs/65` "Attempt 5"/"Attempt 6". That is the only
  place where a method-helper callback reaches the CVE's own loop, and it is already measured there.

## 6. Why the guard's absence is not the memory-safety issue (and why that matters for the next sweep)

`iterateClients` (Sony) and `WeakHashSet::forEach` (WTF) do the same thing with one difference: `forEach`
re-checks `m_set.contains(*item.m_impl)` after the snapshot; `iterateClients` does not. Upstream's fix for
CVE-2026-43715 adds exactly that check. But the check is *semantic*: `copyToVectorOf<Ref<Client>>` already holds a
`Ref` per client, so a client that removes itself during the callback stays alive to the end of the loop — the
guard only stops the loop from *calling* it. The memory-unsafety in `docs/65` comes from the other direction: the
callback frees the **owner** (`CSSFontFace`) and the loop keeps using `this`. So a future sweep of this shape must
ask "can the callback free the *owner*", not "does the helper snapshot its container" — and the owner question has
one structural answer in this drop, already recorded in `docs/70`: a wrapper-held `Ref<ImplementationClass>`
(`bindings/js/JSDOMWrapper.h:87-88`) blocks it for every object the page has named, and the `css/` CVE worked only
because the freed `CSSFontFace` had no wrapper.

That is also why B6 (the `FontFaceSet`'s own `forEach`) is safe while A10 (`CSSFontFace`'s) is not: the *set* is
`Ref`-held by `Document`, the *face* is not.

One detail of the guarded idiom is worth recording because it constrains what a "guarded" verdict means:
`WeakHashSet::forEach` reads `m_set` **after** each callback (`m_set.contains(...)` on the next iteration), so the
guard is itself a post-callback read of the *owner*. It is safe only because the owner cannot be freed there — and
for the `html/track` family that is checkable: a `<track>`-created `TextTrack` has **two** clients
(`HTMLTrackElement`, added at `HTMLTrackElement.cpp:69`, and `HTMLMediaElement`, added at
`HTMLMediaElement.cpp:4665` inside `addTextTrack` — the `<track>` path reaches it through `:4800`), so the second
`contains()` really does run after a client callback, and the track is
held by `Ref<LoadableTextTrack> m_track` (`HTMLTrackElement.h:91`) plus `Vector<RefPtr<TrackBase>> m_inbandTracks`
(`TrackListBase.h:77`). No client callback in that family drops either ref (`scheduleChangeEvent`/`scheduleLoad`
are queued, `checkForAudioAndVideo` is a layout query), so the post-callback read is on a live object. A future
sweep of this idiom should ask that question first — "what refs the owner across the callback" — because the
`contains` check does not make it safe by itself.

## 7. The measured arm — one `setMode`, two clients, no report

§6's claim that the guarded loop's second `contains()` runs *after* a client callback is only true if the set
really holds two elements, so it was measured instead of argued. Page
`research/helper-callback/track-clients.html` (md5 `3d131b15b9cc7d0ee34c51736a77b155`), one quarantine-off run:

```
$ ssh teo@<lab-ip> 'distrobox enter wk -- bash -lc "TAG=track1 PORT=9711 SECS=45 bash /tmp/wkp/hrun.sh"'
RC=0
access: none
EXIT=124
  B A kids=1 track=captions mode=disabled
  B A setmode mode=showing label=
  B A change=1
  B A terr=1 rs=3
  B B setmode=showing has=yes n=1
  B B change=1
  B B change=2
  B DONE
```

Arm A appends a `<video>` with `<track src="/nope.vtt">` and sets `track.track.mode = 'showing'`. The `change`
beacon is `HTMLMediaElement::textTrackModeChanged` → `m_textTracks->scheduleChangeEvent()`; the `terr` beacon is
`HTMLTrackElement::textTrackModeChanged` → `scheduleLoad()`, and the server log confirms that is a real fetch:

```
127.0.0.1 - - [29/Oct/2026 23:49:00] "GET /nope.vtt HTTP/1.1" 404 -
```

`rs=3` is `HTMLTrackElement::ReadyState::ERROR`. So both clients were in `m_clients` and both callbacks ran from a
single `setMode()`; arm B (`video.addTextTrack('captions','zz2','en')`, no `<track>` element) yields only `change`
beacons — the one-client set. `access: none`, 0 sanitizer lines, so the second iteration's `contains()` read a live
owner, which is what §6 predicts.

Stated plainly: the beacons do **not** order the two callbacks — a `change` is a queued event and `error` needs a
404 — so this measures *both clients invoked in one loop*, not which one ran first.

## 8. Corrections to the method, and blind spots this sweep leaves

1. **`vector-local-sweep.py`'s `CALL_RE` cannot see a qualified call.** It is
   `(?<![\w:>])([A-Za-z_]\w*)\s*\(`, so `WTF::map(m_caches, …)` never matches — the `:` before `map` is in the
   lookbehind. This tool's first pass reused it and reported **18** member-in-iterated-position sites across **5**
   helper names (`iterateClients`, `combineSegmentsData`, `updateTracksOfKind`,
   `traverseVisibleNonCompositedDescendantLayers`, `traverseRulesInVector`) with no `map`/`allOf`/`anyOf`/`compactMap`
   row at all; the same tool with a local `(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*\(` reports **42** across **9**.
   Any conclusion drawn from a `CALL_RE`-based net about `WTF::map`/`WTF::anyOf`/`Type::method(` call sites is
   under-counted; the fix is one line and should be carried into the next tool.
2. **The helper may be defined outside the tree being swept.** `WTF::anyOf` is `Source/WTF/wtf/Algorithms.h:36-43`
   and `WTF::map`/`compactMap` are `Algorithms.h` + `Vector.h`. Indexing helpers in `Source/WebCore` alone gives
   **29** names / 29 variants and misses every `WTF::` helper; indexing `Source/WTF` + `Source/WebCore` gives
   **37** names / 42 variants. Helper definitions and call sites are two different populations.
3. **A member's type is not in the file that uses it.** With a per-file declaration scan every row in population B
   read `?`; the cross-file index (1,316 member names) is what makes the element class — and therefore "is this a
   client set?" — answerable at all. It joins by name, so it inherits docs/79's collision caveat: prefer the
   same-stem header, then the same directory, and read the ambiguous ones.
4. **The owner-shaped spelling does not exist here.** 0 of 42 helper variants read `parameter.m_member` in a loop
   head, i.e. nothing in this drop writes `helper(*this, lambda)` where the helper iterates `object.m_clients`.
   The tool supports it; the population is empty, so that branch is untested in practice.
5. **Blind spot left for the next sweep: index loops.** This net, docs/78 and docs/79 all key on `for (x : …)`,
   a push inside a loop, or a helper. The third spelling of the same defect is
   `for (size_t i = 0; i < m_foo.size(); ++i) { … script … m_foo[i] … }` — `size()` read once, recomputed nowhere,
   and `Vector::map`'s own body (`Vector.h:1683`) shows the engine does write loops in that shape. It is not
   covered by any of the eight shape audits so far.
