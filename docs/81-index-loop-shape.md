# docs/81 — the *index-loop* shape: 1,261 `for (i…; i < bound; ++i)` loops, 310 standing on an owner container, 20 with a callee that could be a script window, 0 that can read a shrunk container — and the one member loop that really dispatches is the drop's own documented hazard

The action (`GOAL.md`, first item): every net so far keys on a *range-for* over a container (`docs/79`,
`docs/80`), a push into a container (`docs/78`), or a helper template that hides the range-for (`docs/80`).
None of them can see the loop that reads a bound and then indexes:

```cpp
for (size_t i = 0; i < m_foo.size(); ++i) {
    ...
    client.didSomething();     // script here can shrink m_foo
    use(m_foo[i]);             // stale bound / freed element
}
```

This doc is that sweep over the whole of `Source/WebCore` (10,500 `.cpp`/`.mm`/`.h` files). Five results:

1. **1,261 index loops index a container with their own loop variable, and 310 of those stand on a container
   that belongs to the owner object** (a member, or a local *reference* to one; a local copy is immune). Bound
   spelling: **453 re-read** (`i < m_foo.size()`), **194 cached** (`size_t n = m_foo.size()`, or an init
   evaluated once — every descending loop, 49 of them), **614 not linked to the container at all** (a scalar:
   `i < m_count`, `i < numberOfInputs()`, `i < originalSize`), which is *also* a cached bound with respect to
   the container.
2. **20 of the 310 have any callee in the body that could run script, and all 20 were read in source: 0 can
   shrink the container whose index they read.** Three are `SHRINK-CACHED` (cached bound + a call), two
   `SHRINK-MUTATED` (the body mutates the container), three `OWNER-WINDOW` (a call that really can run script),
   twelve `LOCAL-WINDOW` (the container is a copy, so a shrink cannot matter).
3. **The dangerous ordering — a script window *before* the index read in the same iteration — occurs in zero
   owner-container loops.** Where a call and an index read coexist, the read comes first (`auto& e = m_foo[i];
   e->call();`), and the bound is re-read at the top of the next iteration.
4. **Exactly one member-container index loop dispatches a DOM event from its body:
   `ApplicationCacheHost::stopDeferringEvents` (`loader/appcache/ApplicationCacheHost.cpp:333`), and the drop's
   own comment above it says not to cache the size because the loop must see events appended during the
   dispatch** — the shape this doc hunts, written down by the engine, and handled. Measured: `applicationCache`
   is live on the oracle and three events (`checking`, `downloading`, `progress`) are dispatched **after**
   `load`, i.e. from that loop, and a handler that re-enters the host from inside the loop (`update()`,
   `swapCache()`) changes nothing (`access: none`, 0 sanitizer lines, §5).
5. **Two corrections to the method that outlive the audit**: a bare-name callee index reports false candidates
   by the dozen (34 on the first run, every one through `append`/`at`/`add`), and a member type resolved by
   name instead of by owning class is simply wrong (`m_children` → `AccessibilityChildrenVector` in
   `RenderTableSection`).

## 1. Tool and funnel

One new tool, `tools/index-loop-sweep.py`, over `Source/WebCore`:

```
$ python3 tools/index-loop-sweep.py > data/index-loop/loops.json
files 10500 loops 1261
funnel {'not-three-part': 5157, 'init-not-numeric': 1462, 'no-index-read-with-loop-var': 1018,
        'container-unlinked-to-bound': 614, 'cond-not-index': 261, 'inc-not-step': 110, 'loops': 1261}
verdicts {'inert': 1241, 'LOCAL-WINDOW': 12, 'SHRINK-CACHED': 3, 'OWNER-WINDOW': 3, 'SHRINK-MUTATED': 2}
bound_kinds {'reread': 453, 'cached': 194, 'unlinked': 614}
```

Passes:

* **H (helpers/sinks).** Every function body → its direct script sinks
  (`DIRECT_RE`, the `docs/69`–`docs/75` list: `dispatchEvent`, `resolve(`/`reject(`, `JSC::call` &c.,
  `performMicrotaskCheckpoint`, `getProperty`/`getValue`, the parser entries) and its callee set. Qualified
  calls are captured (`docs/80` records that the older `CALL_RE` could not match `WTF::map(`). A callee is
  followed only when its name has **exactly one definition** in the tree.
* **M (methods).** A `(class, method) → body` index from out-of-line definitions (`CSSFontFace::pump`) and
  from in-class inline definitions (via class scopes, so `CustomElementQueue::invokeAll` resolves). This is how
  a call on an element (`m_faces[i]->removeClient(`) or on `this` (`updateStyleIfNeeded(`) is resolved against
  *that class*, not against the first same-named function in the tree.
* **L (loops).** Every `for (` with three header parts, an integer index variable, a bound and a step:
  ascending (`i < expr`, `++i`) and descending (`i >= 0`, `--i`, where the init is evaluated once). The
  container is taken **from the index expression** (`c[i]`, `c.at(i)`, `c[i - 1]`), then linked to the bound
  (`c.size()` re-read, or a local assigned from it). Member types are resolved per owning class
  (`(class, member) → type`), with a flat name index only as a fallback.

Funnel, bucket by bucket:

| bucket | count | what it is |
|---|---|---|
| `not-three-part` | 5,157 | range-for (`for (auto& x : v)`) — the shape of `docs/78`–`docs/80`, not this one |
| `init-not-numeric` | 1,462 | `for (auto it = …; …)` — iterator loops, no index |
| `cond-not-index` | 261 | bound not a comparison on the loop variable (`i + 4 < n`, `it != end`) |
| `inc-not-step` | 110 | `i = i + 2`, `i += n` — no unit step |
| `no-index-read-with-loop-var` | 1,018 | the body never does `c[i]` / `c.at(i)` with *this* variable |
| `loops` | **1,261** | an index loop that reads a container with its own variable |

Of the 1,261: 310 stand on an owner container (126 re-read bound, 58 cached, 126 unlinked), 49 are descending,
322 read an element and call something on it, and **20 have any callee the tool classifies as a possible script
window**.

## 2. The 20 rows, one per line, each read in source

`SHRINK-CACHED` = cached bound + a call in the body; `SHRINK-MUTATED` = the body mutates the container itself;
`OWNER-WINDOW` = a call that really can run script; `LOCAL-WINDOW` = the container is a local copy.

| verdict | site | container | bound | window |
|---|---|---|---|---|
| SHRINK-CACHED | `Modules/airplay/WebMediaSessionManager.cpp:235` | `m_clientState` | cached | `recv:remove` |
| OWNER-WINDOW | `Modules/airplay/WebMediaSessionManager.cpp:394` | `m_clientState` | reread | `setPlaybackTarget`, `setShouldPlayToPlaybackTarget`, … |
| LOCAL-WINDOW | `Modules/async-clipboard/Clipboard.cpp:324` | `items` | reread | `self:didSetAllData` |
| SHRINK-MUTATED | `accessibility/atspi/AccessibilityAtspi.cpp:306` | `m_pendingRootRegistrations` | reread | `elem:completionHandler` |
| LOCAL-WINDOW | `bindings/js/JSDOMWindowBase.cpp:362` | `wrapperWorlds` | reread | `recv:fireAll` |
| SHRINK-MUTATED | `css/CSSFontFaceSet.cpp:268` | `m_faces` | reread | `trans:decrementActiveCount` |
| OWNER-WINDOW | `dom/CustomElementReactionQueue.cpp:339` | `m_elements` | reread | `recv:invokeAll` |
| LOCAL-WINDOW | `dom/EventListenerMap.cpp:96` | `listeners` | reread | `elem:callback` |
| LOCAL-WINDOW | `dom/ImageOverlay.cpp:512` | `result.lines` | reread | `recv:updateLayoutIfDimensionsOutOfDate` |
| LOCAL-WINDOW | `dom/ImageOverlay.cpp:536` | `lineElements.children` | unlinked | `recv:updateLayoutIfDimensionsOutOfDate` |
| LOCAL-WINDOW | `html/HTMLMediaElement.cpp:1815` | `currentCues` | cached | `recv:updateDisplayTree` |
| LOCAL-WINDOW | `loader/FrameLoader.cpp:3474` | `targetFrames` | reread | `self:dispatchBeforeUnloadEvent` |
| OWNER-WINDOW | `loader/appcache/ApplicationCacheHost.cpp:333` | `m_deferredEvents` | reread | `self:dispatchDOMEvent` |
| LOCAL-WINDOW | `page/DragController.cpp:1562` | `placeholders` | reread | `elem:clientWidth` |
| LOCAL-WINDOW | `page/EventHandler.cpp:4836` | `points` | reread | `self:handleTouchEvent` |
| LOCAL-WINDOW | `page/EventHandler.cpp:5006` | `changedTouches` | unlinked | `direct:dispatchEvent` |
| LOCAL-WINDOW | `platform/ios/WebCoreMotionManager.mm:332` | `orientationClients` | reread | `elem:orientationChanged` |
| LOCAL-WINDOW | `platform/text/DateTimeFormat.cpp:118` | `source` | reread | `recv:visitLiteral`, `recv:visitField` |
| SHRINK-CACHED | `rendering/RenderGeometryMap.cpp:61` | `m_mapping` | cached | `recv:applyTransform` |
| SHRINK-CACHED | `rendering/RenderTableSection.cpp:562` | `m_grid` | cached | `recv:updateLayerTransform` |

What each one actually is:

* **`WebMediaSessionManager.cpp:235` and `:394`** — `Vector<std::unique_ptr<ClientState>>`, and the calls are
  `MediaSessionManagerClient` virtuals. Not our shape twice over: the file is `ENABLE(WIRELESS_PLAYBACK_TARGET)`
  code that is `PRIVATE OFF` in `WebKitFeatures.cmake` (`docs/80` §4 measured the same family), and `:235`'s
  `remove` is `m_clientState.remove(i - 1)` in a **descending** loop — the correct removal idiom.
* **`Clipboard.cpp:324`** — `items` is a *parameter* `const Vector<RefPtr<ClipboardItem>>&`; `collectDataForWriting`
  hands its completion to the vector element's callback. No container mutation is possible from the page.
* **`AccessibilityAtspi.cpp:306`** — `pendingRootRegistration.completionHandler({ })` then
  `m_pendingRootRegistrations.remove(i); return;` — the mutation is *after* the read and the loop returns
  immediately; atspi is Linux accessibility, and the handler is a `CompletionHandler`, not a page callback.
* **`JSDOMWindowBase.cpp:362`** — `Vector<Ref<DOMWrapperWorld>>` (a copy, elements `Ref`), `fireAll` on a JSC
  watchpoint set. Nothing the page holds.
* **`CSSFontFaceSet.cpp:268`** — `m_faces[i]->removeClient(*this); m_faces.remove(i); return;` — documented in
  `docs/65`: `removeClient` is `m_clients.remove(client)` on a `WeakHashSet`, no script, and the loop returns.
* **`CustomElementReactionQueue.cpp:339`** — the one loop where JS really runs between two iterations of a
  member container: `queue->invokeAll(element)` runs custom-element reactions, and the comment at `:337` says
  elements **can be appended** during the callback. Safe by the re-read bound plus a fresh `m_elements[i]` each
  iteration, and a shrink is impossible: `m_elements.clear()` is the only removal and a re-entrant `invokeAll`
  on the same queue hits `RELEASE_ASSERT(!m_invoking)` (`:332`).
* **`EventListenerMap.cpp:96`** — `listeners[i]->callback()` is a *getter* on `RegisteredEventListener`.
* **`ImageOverlay.cpp:512/536`** — geometry over a local `TextRecognitionResult`; `updateLayoutIfDimensionsOutOfDate`
  is a layout nudge, no script.
* **`HTMLMediaElement.cpp:1815`** — local `Vector<CueInterval> currentCues`, cached `currentCuesSize`;
  `cue->updateDisplayTree()` updates cue boxes. A local copy cannot be shrunk by anyone.
* **`FrameLoader.cpp:3474`** — `targetFrames` is a local `Vector<Ref<Frame>>`; `dispatchBeforeUnloadEvent` runs
  page script, and the loop re-checks `targetFrames[i]->tree().isDescendantOf(&m_frame)` at `:3475` **after** the
  previous iteration's dispatch before using it. The element is `Ref`-held, so no UAF either.
* **`ApplicationCacheHost.cpp:333`** — the live one; §3.
* **`DragController.cpp:1562`** — local `Vector<Ref<HTMLImageElement>>`; `clientWidth()` forces layout,
  `setAttributeWithoutSynchronization` explicitly skips synchronous mutation events.
* **`EventHandler.cpp:4836`** — `handleTouchEvent`'s body; `ENABLE(TOUCH_EVENTS)` is OFF in this build
  (`docs/73`), and the call is on the function itself.
* **`EventHandler.cpp:5006`** — the one `dispatchEvent` inside an index loop in the whole tree, and it is not
  this shape: the loop is `for (unsigned state = 0; state != PlatformTouchPoint::TouchStateEnd; ++state)` over
  an **enum sentinel**, and `changedTouches` is a stack array (`changedTouches[PlatformTouchPoint::TouchStateEnd]`,
  `:4821`). The dispatch sits in a nested range-for over `m_targets`. Touch is compiled out.
* **`WebCoreMotionManager.mm:332`** — Cocoa-only `.mm`, not in `Sources.txt`.
* **`DateTimeFormat.cpp:118`** — iterating a `String` by index; `visitLiteral`/`visitField` are date-format
  builder callbacks.
* **`RenderGeometryMap.cpp:61`** — `const RenderGeometryMapStep& currentStep = m_mapping[i]`, then
  `transformState.applyTransform(...)`; `applyTransform` touches a `TransformState`, never `m_mapping`.
* **`RenderTableSection.cpp:562`** — cached `totalRows`, body is layout only (`updateLayerTransform`,
  `layoutIfNeeded`). Layout does not re-enter script.

## 3. The one member-container index loop with a real dispatch — and what the drop says about it

```cpp
void ApplicationCacheHost::stopDeferringEvents()
{
    Ref<DocumentLoader> protect(m_documentLoader);

    // Note, do not cache the size in a local variable.
    // This code needs to properly handle the case where more events are added to
    // m_deferredEvents while iterating it. This is why we don't use a modern for loop.
    for (size_t i = 0; i < m_deferredEvents.size(); ++i) {
        auto& event = m_deferredEvents[i];
        dispatchDOMEvent(event.eventType, event.progressTotal, event.progressDone);
    }

    m_deferredEvents.clear();
    m_defersEvents = false;
}
```
`loader/appcache/ApplicationCacheHost.cpp:326-340`

That comment is this doc's shape, written by the engine: an index loop over a member `Vector`, whose body runs
script (`dispatchDOMEvent` → `m_domApplicationCache->dispatchEvent(…)`, `:380-386`), and the author's answer is
*do not cache the size*. The queue it protects is real: `m_defersEvents { true }` until after `onload`
(`ApplicationCacheHost.h:157`), `notifyDOMApplicationCache` appends to `m_deferredEvents` while it is true
(`:307-309`), and `DocumentLoader::dispatchOnloadEvents()` calls `stopDeferringEvents()`
(`loader/DocumentLoader.cpp:2457-2461`) — so the whole initial event burst is dispatched from this one loop.

### Measured: the loop is live on the oracle, and a handler can re-enter the host from inside it

Page `research/index-loop/appcache-loop.html` (md5 `9a5f4f3a3e03c584f958ee4af758ce37`), manifest
`research/index-loop/ac.appcache`, server `research/index-loop/srv.py` (only for `text/cache-manifest`), runner
`research/index-loop/arun.sh` (md5 `e8b7545aff4c4c2a9e8d308b313c4383`). One variable apart: the query string.
Both arms under `run_nq.sh` (quarantine off), scored from the beacon log.

Arm A (`reentry=0`):

```
$ ssh teo@<lab-ip> 'distrobox enter wk -- bash -lc "TAG=acA PORT=9721 SECS=40 bash /tmp/wkp/arun.sh"'
RC=0
access: none
EXIT=124
  B START reentry=false ua=101
  B AC typeof=object
  B LOAD
  B EV checking i=1
  B EV downloading i=2
  B EV progress i=3
```

Arm B (`reentry=1` — the `checking` handler calls `applicationCache.update()`, the `downloading` handler calls
`swapCache()`):

```
$ ssh teo@<lab-ip> 'distrobox enter wk -- bash -lc "TAG=acB PORT=9722 SECS=45 QS=\"?reentry=1\" bash /tmp/wkp/arun.sh"'
RC=0
access: none
EXIT=124
  B START reentry=true ua=101
  B AC typeof=object
  B LOAD
  B EV checking i=1
  B UPD
  B EV downloading i=2
  B SWPERR InvalidStateError
  B EV progress i=3
```

What this measures, stated plainly:

* `applicationCache` is `object` on this build (`defaultOfflineWebApplicationCacheEnabled()` returns `true` on
  every non-Cocoa port, `WebKit/Shared/WebPreferencesDefaultValues.cpp:128-138`), so the row is **not** dead
  code, unlike the `ENABLE(WIRELESS_PLAYBACK_TARGET)` and touch rows above.
* The three events arrive **after** `LOAD`, which is the deferral: they were queued while `m_defersEvents` was
  true and dispatched by this loop. Page script therefore runs *inside* an index loop over a member container,
  three times, on a live page.
* A handler can re-enter the host from inside the loop: `update()` is accepted and `swapCache()` throws
  `InvalidStateError` (no newer cache yet, per spec). Neither aborts, and the loop continues to `progress`:
  `access: none`, no `AddressSanitizer` line, no `RELEASE_ASSERT`.
* **Not** measured: an event appended to `m_deferredEvents` *during* the loop. The re-entry arm produced no new
  event (the events all predate `onload`), so the append-during-iteration path the comment describes was not
  exercised. That path is safe by inspection — the bound is re-read and `auto& event`'s fields are all read as
  arguments before the call, so a reallocation inside `dispatchDOMEvent` cannot be observed — but the doc does
  not claim a measurement for it.
* Artifact to record: the page's `DONE` timer beacon (4 s) never arrived in either arm although the runs lasted
  40 s and 45 s. No claim rests on it; the harness always ends with `EXIT=124` (`docs/65`, Attempt 11).

## 4. Corrections to the method

1. **A bare-name callee index is unusable as a window oracle.** The first run reported 34 `CANDIDATE` rows and
   every one was `append`, `at`, `add`, `get` or `contains` matching a same-named function elsewhere in the
   tree. Gating the route on `definitions == 1` dropped it to 1, and the type-directed method index replaced it.
2. **A member type must be resolved by owning class.** A flat `m_name → type` index gave `RenderTableSection`'s
   `m_children` the type `AccessibilityChildrenVector` and `FontTaggedSettings`' `m_list` the type
   `Vector<RefPtr<SourceBuffer>>`. `(class, member) → type` fixes both; the flat index is now only a fallback
   and is marked as such in the row (`container_type` is empty when neither resolves).
3. **A scalar bound is a cached bound.** `i < m_count`, `i < numberOfInputs()` and `i < originalSize` do not
   move when the container shrinks, so they belong to the `SHRINK` class even though they contain no `.size()`.
   The first version filed all 614 of them as "unlinked" and therefore inert; that was wrong and is the reason
   `SHRINK-SCALAR` exists in the tool.
4. **A descending loop's init is evaluated once.** `for (int i = m_mapping.size() - 1; i >= 0; --i)` looks like
   a re-read bound in text and is a cached bound in fact. All 49 descending loops are now `cached`.
5. **The positional test uses the call's start**, so a window call's own arguments count as "after the window".
   `ApplicationCacheHost`'s `event.eventType` is exactly that: read by hand, not by position.

## 5. What this closes, and the blind spot it leaves

With `docs/78` (local `Vector<X*>`, push-then-read), `docs/79` (member containers, iterate-and-callback),
`docs/80` (helper-template and method spellings) and this doc (index loops, both directions, cached and
re-read bounds, raw and owning elements), **every in-tree spelling of "a container is walked by a C++ loop that
can run script" has been enumerated and read**. The conclusion is the same in all four: the engine's loops are
written to survive the window — a snapshot of `Ref`s, a re-read bound, a re-check after the dispatch — and the
one loop that documents the hazard in a comment is the one that handles it.

The blind spot this sweep leaves is explicit: **a window two or more hops away through a callee whose name is
not unique**. The tool follows callees to depth 2 only when the name has exactly one definition, and resolves
one hop through the class-qualified method index. A virtual call on a member whose type does not resolve
(`container_type == ""`, 828 rows) is invisible. That is the next action in `GOAL.md`.

No ASAN run is recorded for a candidate site, and the action's conditional clause is what makes that correct: it
asks for a quarantine-off run "for the first site where a page-reachable callee can remove from the container".
No such site exists in the 20 rows, so the only run this doc records is the reachability measurement in §3.
