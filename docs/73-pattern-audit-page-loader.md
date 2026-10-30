# `page/` + `loader/` — 117 sweep rows, 62 JavaScript windows in 40 functions, 0 with a reachable free; the one risky tail (`loadInSameDocument`) measured safe

GOAL action (2026-10-29), the item after `docs/72`: the last two directories with JavaScript entry points.
`page/` carries the frame, window, event-handler, observer and timer plumbing; `loader/` carries the resource
callbacks and the frame loader. This doc sweeps both with the extended sink list (`docs/71`'s `NAMES`), reads
every row that runs script, and measures the one tail where a member call follows a *synthetic* dispatch the
page can fire at will.

**Short answer: 117 rows, 62 in the JavaScript-sink set, 40 functions, 0 with a reachable free.** The reason is
not per-site `Ref`s — it is structural, and it is the strongest form of the `docs/70` result:

1. **A dispatch target cannot be freed by its own listeners.** `dom/Event.h:194` holds
   `RefPtr<EventTarget> m_target` and `dom/Event.h:192` holds `RefPtr<EventTarget> m_currentTarget`; the only
   place `m_target` is cleared is `Event::initEvent` (`dom/Event.cpp:117`), which returns early while an event
   is being dispatched. `Event::resetAfterDispatch()` (`dom/Event.cpp:182`) clears the event path and the
   *current target* only. So the `Event` the caller is holding keeps the target alive for the whole window and
   after it. Node dispatches have a second ref on top: `EventDispatcher::dispatchEvent` opens with
   `Ref protectedNode { node }` (`dom/EventDispatcher.cpp:155`), reached from `Node::dispatchEvent`
   (`dom/Node.cpp:2446`).
2. **A frame cannot be destroyed synchronously by DOM removal.** `HTMLFrameOwnerElement::disconnectContentFrame()`
   holds `RefPtr frame = m_contentFrame.get()` across `frameDetached()` *and* `disconnectOwnerElement()`
   (`html/HTMLFrameOwnerElement.cpp:82`), and `FrameLoader::frameDetached()` opens with
   `Ref protectedFrame { m_frame }` because, in the drop's own words, "Calling stopAllLoadersAndCheckCompleteness()
   can cause the frame to be deallocated, including the frame loader" (`loader/FrameLoader.cpp:2969-2972`). Every
   `FrameLoader`/`EventHandler`/`PolicyChecker` tail below is therefore operating on an object that is still
   ref'd while the dispatch above it runs.

The 3 observer-callback rows are the only non-dispatch windows, and their post-callback use
(`InspectorInstrumentation::didFireObserverCallback(*context)`) is a `FAST_RETURN_IF_NO_FRONTENDS` no-op
(`inspector/InspectorInstrumentation.h:1726`). The remaining 24 rows are either not script sinks (12) or cannot
run on the target/here at all (12, feature flags — table below).

## Method

```sh
cd /Users/<user>/Documents/ps5-bootchain
python3 tools/pattern-sweep.py page > /tmp/audit73_page.json                                  # 100 rows
python3 tools/pattern-sweep.py loader loader/cache loader/archive loader/appcache loader/icon \
    > /tmp/audit73_loader.json                                                                # 15 rows
python3 tools/pattern-sweep.py page/csp page/scrolling page/linux page/playstation \
    > /tmp/audit73_pagesub.json                                                               # 1 row
python3 tools/pattern-sweep.py page/win page/ios page/mac page/cocoa page/gtk \
    loader/ios loader/mac loader/cocoa loader/soup > /tmp/audit73_rest.json                    # 1 row
```

117 rows total. 62 of them are in the JavaScript-sink set used here (`dispatchEvent`, `fireEventListeners`,
`handleEvent`, `dispatchErrorEvent`, `dispatchDOMEvent`, `execute`, `evaluate`,
`executeScriptIgnoringException`), spread over **40 functions**. The rest of the 117 are `reject`/`resolve`
on promises with no argument (35 rows: 27 `reject`, 8 `resolve`, in `page/Navigator.cpp`,
`ScreenOrientation.cpp`, `WorkerNavigator.cpp`, `NavigatorIsLoggedIn.cpp`, `UserMessageHandler.cpp`,
`ImageLoader.cpp`), `enqueueEvent` (10 rows, all `Document::queueTaskToDispatchEvent` — a queued task, not a window), and
`postTask`/`callOnMainThread` (10 rows, task bodies; two of them in subdirectories, `page/scrolling` and
`page/ios`). 35 + 10 + 10 = the 55 rows
outside the sink set.

Coverage of `page/` and `loader/` is complete: 190 `.cpp` in `page/` (118 top level + 72 in 9 subdirectories)
and 100 `.cpp` in `loader/` (62 top level + 38 in 8 subdirectories), and the sweep ran over all of them.

### There is no other way to run script from these two directories

```sh
grep -rho "JSC::[A-Za-z_]*" page/ --include=*.cpp | sort | uniq -c | sort -rn
```
81 lines / 92 tokens, **none of them a call**: 35 `JSC::JSGlobalObject`, 12 `JSC::JSValue`, 9 `JSC::VM`,
8 `JSC::Yarr` (regex), 4 `JSC::jsDynamicCast`, 3 each `jsNull`/`Unknown`/`Strong`/`JSLockHolder`, 2 each
`ExecState`/`Exception`/`AbstractSlotVisitor`, and one each of `jsNontrivialString`, `createError`,
`PreventCollectionAndDeleteAllCode`, `JSObject`, `DeleteAllCodeIfNotCollecting`, `Debugger`. A grep for a
call-ish token over the same set returns exactly one hit, `JSC::ExecState` (a type name): there is **no
`JSC::call`/`JSC::evaluate`/`JSC::profiledCall`/`JSC::construct` anywhere in `page/`**, and `loader/` has **0**
`JSC::` occurrences at all. The single direct script entry in either directory is:

```sh
grep -rnE "executeScript|executeClassicScript|executePendingScript|JSC::(call|evaluate)|evaluateScript|performMicrotaskCheckpoint" \
    page/ loader/ --include=*.cpp | grep -v "#include"
loader/DocumentLoader.cpp:2573:                scriptController->executeScriptIgnoringException(script);
```
which is the content-filter unblock script, behind a `WeakPtr<ScriptController>` and inside
`#if ENABLE(CONTENT_FILTERING)` — **off in both the oracle and the console** (flags below).

So for these two directories the question "can a script window free an object used afterwards" reduces to
"can a dispatch target, or an observer, be freed by its callback" — and the two guards above answer it.

## The 40 functions, one verdict each

`n` = rows in the sink set at that function. "used afterwards" is the first statement after the call that
touches memory.

| # | site | n | runs script | used afterwards | verdict |
|---|------|---|-------------|-----------------|---------|
| 1 | `ContextMenuController.cpp:421` `contextMenuItemSelected` | 9 | no — `EditorCommand::execute()` | — | artifact of the sweep's `execute` |
| 2 | `DOMTimer.cpp:183` `install` | 1 | no — `ScheduledAction::execute` inside the timer's own lambda | — | artifact; there is no tail |
| 3 | `DeviceController.cpp:82` `dispatchDeviceEvent` | 1 | `listener->dispatchEvent` | next listener | targets are `HashCountedSet<RefPtr<LocalDOMWindow>>` (`DeviceController.h:61`); `ENABLE_DEVICE_ORIENTATION 0` |
| 4 | `DeviceController.cpp:97` `fireDeviceEvent` | 1 | same, from a copy of `m_lastEventListeners` | next listener | same |
| 5 | `DragController.cpp:551` `dispatchTextInputEventFor` | 1 | `target->dispatchEvent` | `!event->defaultPrevented()` (local `Ref<TextEvent>`) | inside `#if ENABLE(DRAG_SUPPORT)`; target not used after |
| 6 | `EventHandler.cpp:483` `dispatchSelectStart` | 1 | `node->dispatchEvent` | `!event->defaultPrevented()` | node not used after |
| 7 | `EventHandler.cpp:2371` `handlePasteGlobalSelection` | 1 | no — `EditorCommand::execute()` | — | artifact |
| 8 | `EventHandler.cpp:2392` `dispatchDragEvent` | 1 | `dragTarget.dispatchEvent` | `m_frame.document()->existingAXObjectCache()`, `dragTarget` in the AX notification | `Ref protectedFrame` at `:2380`; `m_frame` is the frame, not freeable by a listener; DRAG_SUPPORT |
| 9 | `EventHandler.cpp:3786,3815,3847` `internalKeyEvent` | 3 | `element->dispatchEvent(keydown/keypress)` | `m_frame.page()`, `m_frame.editor()`, `keydown->defaultHandled()` | `element` is `RefPtr<Element>`, `keydown` a `Ref<KeyboardEvent>`; `m_frame` cannot be freed by the listener |
| 10 | `EventHandler.cpp:4369` `handleTextInputEvent` | 1 | `event` dispatch | `event->defaultHandled()` | local `Ref<TextEvent>` |
| 11 | `EventHandler.cpp:5023` `handleTouchEvent` | 1 | `target->dispatchEvent(touchEvent)` | `touchEvent->defaultPrevented()` | target not used after; TOUCH_EVENTS |
| 12 | `EventSource.cpp:146` `scheduleReconnect` | 1 | `dispatchErrorEvent()` | nothing — last statement | — |
| 13 | `EventSource.cpp:201,207` `didReceiveResponse` | 2 | `dispatchErrorEvent()` / `open` event | nothing — last statements | `m_state`/`m_eventStreamOrigin` written **before** |
| 14 | `EventSource.cpp:212` `dispatchErrorEvent` | 1 | `EventTarget::dispatchEvent` | nothing — last statement | event refs the target (`Event.h:194`) |
| 15 | `EventSource.cpp:284` `abortConnectionAttempt` | 1 | `error` event | nothing — last statement | `makePendingActivity(*this)` at `:277` |
| 16 | `EventSource.cpp:439` `dispatchMessageEvent` | 1 | `message` event | nothing — last statement | — |
| 17 | `IntersectionObserver.cpp:313` `notify` | 1 | `m_callback->handleEvent(*this, …)` | `InspectorInstrumentation::didFireObserverCallback(*context)` | no-op without a frontend (see below) |
| 18 | `LocalDOMWindow.cpp:311` `dispatchAllPendingUnloadEvents` | 1 | `window->dispatchEvent` | `window->enableSuddenTermination()` | `windows` is a `Vector<Ref<LocalDOMWindow>>` and the set is re-checked per iteration (`:306`) |
| 19 | `LocalDOMWindow.cpp:951` `processPostMessage` | 1 | `dispatchEvent(event.event)` | `InspectorInstrumentation::didDispatchPostMessage(frame, …)` | lambda captures `protectedThis = Ref { *this }` and `Ref frame = *this->frame()` |
| 20 | `LocalDOMWindow.cpp:2248` `failedToRegisterDeviceMotionEventListener` | 1 | `DeviceMotionEvent` dispatch, **inside** a `postTask` lambda | next statement in the task | asynchronous; DEVICE_ORIENTATION 0 |
| 21 | `LocalDOMWindow.cpp:2359,2371` `dispatchLoadEvent` | 2 | `load` event on the window, then on the owner element | `InspectorInstrumentation::loadEventFired(frame())` | `Ref protectedThis` + `RefPtr protectedLoader` (`:2348`); the owner is `RefPtr<Element>` |
| 22 | `LocalDOMWindow.cpp:2410,2411` `dispatchEvent(Event&, EventTarget*)` | 2 | `fireEventListeners` capturing, then bubbling | `event.resetAfterDispatch()` | `Ref protectedThis` at `:2384`; the event is caller-owned |
| 23 | `Page.cpp:3918,3921` `dispatchPrintEvent` | 2 | `window->dispatchEvent` | next frame in `Vector<Ref<LocalFrame>>` | `RefPtr window` captured by the task at `:3921` |
| 24 | `Performance.cpp:317` `resourceTimingBufferFullTimerFired` | 1 | `resourcetimingbufferfull` | loops over `m_backupResourceTimingBuffer` | `Performance` is `RefPtr`-held by the window (`LocalDOMWindow.h:485`) |
| 25 | `PerformanceObserver.cpp:143` `deliver` | 1 | `m_callback->handleEvent(*this, list, *this)` | `InspectorInstrumentation::didFireObserverCallback(*context)` | entries are `Vector<RefPtr<PerformanceEntry>>` (`PerformanceObserver.h:77`) |
| 26 | `PointerCaptureController.cpp:213,233,236,281,289,301` `dispatchEventForTouchAtIndex` | 6 | `dispatchEvent(...)` on a `Vector<Ref<Element>>` chain | next element | `Ref capturingData` at `:242`; TOUCH_EVENTS |
| 27 | `PointerCaptureController.cpp:373` `dispatchEvent` | 1 | `target->dispatchEvent(event)` | `pointerEventWasDispatched(event)` | that function re-looks-up `RefPtr capturingData` (`:421`) |
| 28 | `PointerCaptureController.cpp:499,500,501` `cancelPointer` | 3 | three `dispatchEvent`s | `processPendingPointerCapture(pointerId)` | `capturingData` is a `RefPtr`; `target` is `RefPtr<Element>` |
| 29 | `PointerCaptureController.cpp:524,538` `processPendingPointerCapture` | 2 | `lost`/`gotpointercapture` | `capturingData->targetOverride = pendingTargetOverride` | `RefPtr capturingData`, `pendingTargetOverride` cached as `RefPtr` **before** the dispatches |
| 30 | `ResizeObserver.cpp:182` `deliverObservations` | 1 | `jsCallback->handleEvent(*this, entries, *this)` | `InspectorInstrumentation::didFireObserverCallback(*context)` | same as 17/25 |
| 31 | `DocumentLoader.cpp:2573` `handleContentFilterDidBlock` | 1 | `executeScriptIgnoringException` | `frameLoader()->client()…` | `WeakPtr<ScriptController>`; `ENABLE_CONTENT_FILTERING 0` |
| 32 | `FrameLoader.cpp:1229` `loadInSameDocument` | 1 | synthetic `load` on the owner element | `m_client->didFinishLoad()` | **measured** below |
| 33 | `FrameLoader.cpp:3528` `dispatchUnloadEvents` | 1 | `unload` on the window | `m_frame.document()->removeAllEventListeners()` | `m_frame.document()` is a null-checked `WeakPtr` (`:3538`, and the comment at `:3500` says the frame may be detached) |
| 34 | `FrameLoader.cpp:3583` `dispatchBeforeUnloadEvent` | 1 | `beforeunload` on the window | `shouldAskForNavigationConfirmation(*document, …)` | `RefPtr<Document> document` (`:3575`), `Ref<BeforeUnloadEvent>` |
| 35 | `ImageLoader.cpp:576` `dispatchPendingErrorEvent` | 1 | `element().dispatchEvent(error)` | `updatedHasPendingEvent()` | `m_element` is `Element&` but `RefPtr<Element> m_protectedElement` (`ImageLoader.h:123`) holds it while an event is pending |
| 36 | `LinkLoader.cpp:330` `preloadIfNeeded` | 1 | no — `MediaQueryEvaluator::evaluate` | — | artifact |
| 37 | `PolicyChecker.cpp:156` `checkNavigationPolicy` | 1 | `load` on the owner element (CSP-blocked frame) | `function(...)` (a local completion handler), `POLICYCHECKER_RELEASE_LOG` | no `m_frame` use after the dispatch |
| 38 | `ApplicationCacheHost.cpp:313` `notifyDOMApplicationCache` | 1 | `dispatchDOMEvent` | nothing | `m_domApplicationCache` is a `WeakPtr` (`ApplicationCacheHost.h:154`) |
| 39 | `ApplicationCacheHost.cpp:335` `stopDeferringEvents` | 1 | `dispatchDOMEvent` per deferred event | next event, index re-reads `size()` | `Ref<DocumentLoader> protect` at `:329` protects the owner of `this` |
| 40 | `ApplicationCacheHost.cpp:385` `dispatchDOMEvent` | 1 | `m_domApplicationCache->dispatchEvent` | nothing | `WeakPtr` + `frame()` null check at `:387` |

## The observer rows, and the one raw pointer after them

Rows 17, 25, 30 pass `*this` to a JavaScript callback and then use a **raw `ScriptExecutionContext*`
captured before the callback**. That is the only unguarded-looking pointer in the set, and it is inert for
this reason:

```cpp
// inspector/InspectorInstrumentation.h:1726
inline void InspectorInstrumentation::didFireObserverCallback(ScriptExecutionContext& context)
{
    FAST_RETURN_IF_NO_FRONTENDS(void());
    if (auto* agents = instrumentingAgents(context))
        didFireObserverCallbackImpl(*agents);
}
```

`FAST_RETURN_IF_NO_FRONTENDS` returns before `context` is passed to anything, and the call itself only forms
a reference. Nothing reads the context without an attached frontend, so a page cannot turn it into a read.

**Caveat, stated so it is not mistaken for a result:** the console has `ENABLE_REMOTE_INSPECTOR ON`
(`OptionsPlayStation.cmake:220`). With a frontend attached, `instrumentingAgents(context)` *does* read the
context (`InspectorInstrumentation.cpp` `agentsForContext`), so an attacker who is already driving a remote
inspector session has one more read. That is outside the threat model here (page-only attacker) and is not a
primitive on its own.

## The 12 rows that cannot run

Two different reasons, and they must not be conflated: the oracle is a **GTK** build (`~/wk/configure-asan.sh`,
`-DPORT=GTK`), so a feature can be on locally and off in the console's `OptionsPlayStation.cmake` feature set.

| feature | oracle (`~/wk/WebKit/WebKitBuild/ASAN/cmakeconfig.h`) | console | affected rows |
|---------|------|---------|---------------|
| `ENABLE_TOUCH_EVENTS` | 1 | **0** — `WebKitFeatures.cmake:240` default OFF, no PlayStation override | 7 (11, 26) |
| `ENABLE_DRAG_SUPPORT` | 1 | **0** — `WebKitFeatures.cmake:161` default OFF, no override | 2 (5, 8) |
| `ENABLE_DEVICE_ORIENTATION` | 0 | 0 — `WebKitFeatures.cmake:158` | 2 (3, 4) |
| `ENABLE_CONTENT_FILTERING` | 0 | 0 — `WebKitFeatures.cmake:147` | 1 (31) |

`OptionsPlayStation.cmake` overrides exactly one feature in this neighbourhood —
`WEBKIT_OPTION_DEFAULT_PORT_VALUE(ENABLE_RESOURCE_USAGE PRIVATE ON)` at `:221` — and nothing else in the
list above. So **touch and drag rows are testable in the oracle and impossible on the target**; the
device-orientation and content-filter rows are impossible in both. (The 117th row,
`page/ios/ContentChangeObserver.cpp:278`, is a `callOnMainThread` in iOS-only code and is not in the sink set at
all; it is counted only so the totals are honest.)

## The one candidate that was measured: `FrameLoader::loadInSameDocument`'s tail

This is the only row in the two directories where a *synthetic* event dispatch is followed by a member call
(`m_client->didFinishLoad()`, `loader/FrameLoader.cpp:1232`) and where the page chooses the dispatch target's
fate: the target is the `<iframe>` element, and the page can remove it from inside the listener.

```cpp
// loader/FrameLoader.cpp:1226-1232
if (auto* parentFrame = dynamicDowncast<LocalFrame>(m_frame.tree().parent()); parentFrame
    && (m_frame.document()->processingLoadEvent() || m_frame.document()->loadEventFinished())
    && !m_frame.document()->securityOrigin().isSameOriginAs(parentFrame->document()->securityOrigin()))
    m_frame.ownerElement()->dispatchEvent(Event::create(eventNames().loadEvent, …));

m_client->didFinishLoad();
```

Page (`research/page-loader/`, `index.html` md5 `f141a447fe2b350204628bb329c4214d`, `q.html` md5
`f041a9f8ecc1590aea89aa4a5686bc08`): the parent is served at `127.0.0.1` and the iframe at `localhost`, so the
two documents are cross-origin; the child does `location.hash='h1'` 150 ms after load, which is a
same-document navigation **inside the child** and therefore runs `loadInSameDocument` in the child's loader;
the parent's second `load` event on the iframe element is the synthetic dispatch above, and the handler either
removes the iframe (`k=rm`) or a sibling `<div>` (`k=div`), or does nothing (`k=none`).

```sh
./research/page-loader/run.sh 8941 rm 20     # quarantine ON (run_asan_page.sh): "does a bug exist"
./research/page-loader/run.sh 8942 div 20
./research/page-loader/run.sh 8943 none 20
```

```
===== case=rm port=8941 extra=
access: none
SUMMARY: none
EXIT=124
-- beacons:
   P start k=rm host=127.0.0.1:8941&r=0.15746315906345565
   Q load hash=&r=0.07103136743922267
   LOAD n=1&r=0.5094370307484073
   Q nav&r=0.7902429783939969
   LOAD n=2&r=0.06871892205707253
   ACT removed-iframe&r=0.012242800087054029
   P alive n=2&r=0.8483976547471753
   P done n=2&r=0.7963007124712073
   P done2 n=2&r=0.29333892692144037
```

```
===== case=div port=8942 extra=
access: none
SUMMARY: none
EXIT=124
-- beacons:
   P start k=div host=127.0.0.1:8942&r=0.2747414604843159
   Q load hash=&r=0.3271844576708852
   LOAD n=1&r=0.48531584390838245
   Q nav&r=0.7408476752273226
   LOAD n=2&r=0.8081150385926077
   ACT removed-div&r=0.4357050936593174
   P alive n=2&r=0.4621856675707222
   Q alive2 hash=#h1&r=0.2567515732175426
   P done n=2&r=0.732279146148629
   P done2 n=2&r=0.4032816537432449
```

```
===== case=none port=8943 extra=
access: none
SUMMARY: none
EXIT=124
-- beacons:
   P start k=none host=127.0.0.1:8943&r=0.8791443198724046
   Q load hash=&r=0.30617284863708427
   LOAD n=1&r=0.9651447575647686
   Q nav&r=0.5782566976011744
   LOAD n=2&r=0.005125518689921393
   ACT none&r=0.9990071834624891
   P alive n=2&r=0.04003930549711776
   Q alive2 hash=#h1&r=0.28000756336287824
   P done n=2&r=0.43923314033096883
   P done2 n=2&r=0.37116901952207326
```

(`&r=` is a cache-buster. `EXIT=124` is how every `run_nq.sh`/`run_asan_page.sh` run ends — `timeout` kills
MiniBrowser; `docs/65`, "Attempt 11".)

What the three runs establish, one variable apart:

- `Q load` appears **once** and `Q nav` precedes `LOAD n=2`, so the second load is not a document load: it is
  the synthetic owner-element dispatch from `loadInSameDocument` (`:1229`). The candidate's window ran.
- `ACT removed-iframe` sits between `LOAD n=2` and the next beacon, so the removal happened **inside** that
  dispatch, before `m_client->didFinishLoad()`.
- `Q alive2 hash=#h1` is present in `div`/`none` and **absent** in `rm`: the removal really detached the frame
  (the child's `ActiveDOMObjects` were stopped, `FrameLoader::frameDetached` → `stopActiveDOMObjects`), so the
  two cases differ in the variable under test and not only in the beacon line.
- `P done2` in all three and `access: none` / `SUMMARY: none` in all three: the tail does not touch freed
  memory, and the page keeps running.

Why it holds: the removal path is
`HTMLFrameOwnerElement::disconnectContentFrame()` → `RefPtr frame = m_contentFrame.get()`
(`html/HTMLFrameOwnerElement.cpp:82`) → `frameDetached()` → `Ref protectedFrame { m_frame }`
(`loader/FrameLoader.cpp:2972`) → `detachFromParent()`, all of it *above* `loadInSameDocument` on the stack
and all of it holding a ref on the frame. The frame (and therefore the `FrameLoader`) outlives the dispatch by
at least one reference.

**What this does not prove:** that no frame-destruction path exists elsewhere (page close, bfcache eviction,
`Page::destroyDecodedData`), only that a page cannot free the frame from inside this dispatch. The row is
recorded as measured-safe in this configuration.

## What this audit does not cover

- **Indirect invocation.** The sweep's `NAMES` are textual, and `page/` contains no `JSC::call`/`JSC::evaluate`
  at all, so a JS call site there would have to be spelled as one of the enumerated wrappers. For `loader/`
  the same grep returns 0. The residual gap is a call through a function pointer whose name does not appear
  in `NAMES`; `page/`'s only such indirections are the two observer-callback rows, which are read above.
- **`ScriptController` itself lives in `bindings/js/`**, not `page/`; `page/` only constructs it
  (`LocalFrame.cpp:154`, `:1148`) and `Quirks.cpp:1257` creates a world. Its `executeScript*` methods are the
  thing that *runs* the results of these windows, not a window of their own.
- **`page/`'s remaining `JSC::` is types and helpers** (35 `JSGlobalObject`, 12 `JSValue`, `Yarr`, …), listed
  above so a later run does not have to re-do the grep to believe it.

## Next subsystem

`page/` and `loader/` close the list of directories with JavaScript entry points. The one sink class this
programme has found that is *not* an event dispatch is `resolve(<DOM object>)` — `docs/69` measured it as a
synchronous script window on `Array.prototype.then`/`Object.prototype.then` (`FontFaceSet.cpp:215`, and
`document.fonts.ready`'s `resolve(*this)` at `:83`). The next action is the whole-tree sweep for that shape
outside `css/` + `dom/`: every `resolve(`/`reject(` whose argument is a `Ref`/`RefPtr` to a DOM object, with
the same "can the callback free it" test. That is the one pattern in this drop where the window exists without
a wrapper of the page's own and without an `Event` to hold the target alive.

## Artefacts

- `research/page-loader/index.html`, `q.html`, `run.sh` (3-case runner, quarantine ON).
- Logs: `/tmp/pl_rm.log`, `/tmp/pl_div.log`, `/tmp/pl_none.log` on the workstation; server logs
  `/tmp/srv8941.log`…`/tmp/srv8943.log` on `teo@<lab-ip>`.
- Sweep JSON: `/tmp/audit73_{page,loader,pagesub,rest}.json`.
