# The CVE-2026-43715 pattern, searched across `css/` and `dom/`

GOAL action (2026-10-29). The pattern is: **a C++ method runs script and then reads or writes a member of
`this`, or of an object it holds by pointer, that the script can free.** That is exactly what made
`setStatus` write into a freed `CSSFontFace` (`docs/65`). This doc is the audit of `Source/WebCore/css/`
and `Source/WebCore/dom/` for a second instance, and it answers three questions per candidate: which call
runs script, what is used after it, and whether the callback can free that object.

Short answer: **28 rows tabled, 26 of them real script sinks, 0 with a reachable free.** Every post-callback use in these two
directories is protected by a `Ref`/`RefPtr` local, a GC-reachable container, or the object is not
script-freeable (a `Document`, a `ScriptExecutionContext`, an owner-held tracker). One row did produce a
new *measured* fact that changes how the whole class must be judged: **a `then` accessor on
`Array.prototype` or `Object.prototype` runs script synchronously inside the drop's own promise
resolutions** — so every `resolve(<object>)` site is a script window, not just `dispatchEvent`. Probe A/B
below measures that on the ASAN oracle.

## Method

```sh
cd /Users/<user>/Documents/ps5-bootchain   # the sweep resolves ROOT from the working directory
python3 tools/pattern-sweep.py            # defaults to css dom: 128 + 181 = 309 .cpp files
```

The sweep strips comments and string literals, enumerates function bodies by brace matching against the
signature before each `{` (rejecting `if`/`for`/`while`/`switch`/`catch`), then for every call to a
script-running name (`resolve`, `reject`, `dispatchEvent`, `invokeCallback`, `handleEvent`,
`fireEventListeners`, `getProperty`, `postTask`, …) dumps the statements that follow it inside the same
function body. It produced **123 raw rows** across 31 files; 18 of them have a direct `m_` / `this->`
use within the first five following statements. The 28 rows tabled below are those 18, plus eight that
reach a member through a helper (`node.hasEventListeners`, `m_context->…`, `m_backing->…`), plus two
kept on purpose to show the method's blind spots (a false positive and a deferred sink).

Four distinct sinks came out of the read. They are **not** equivalent, and the difference decides every
verdict:

| sink | runs script synchronously? | why |
|---|---|---|
| `EventTarget::dispatchEvent` / `fireEventListeners` | yes | listener invoked on the spot (`EventTarget.cpp:372`) |
| `promise->resolve(<DOM object>)` | **yes, measured** | JSC reads `then` off the resolved value; an accessor on the prototype chain runs now |
| `promise->resolve(<primitive>)`, `resolve()`, `reject(Exception)` | no | nothing to read `then` from; the reaction is a queued job |
| `postTask` / `queueMicrotask` / `queueTask` | no (deferred) | the callback runs in a later task; the frame has returned |

Rows where the sink is in the third or fourth class are listed with that fact, because "runs script" is
what the pattern needs and they do not have it.

## Probe A/B — the `then` accessor is a live script window in this drop

Page `research/cve-2026-43715/thenable.html`, md5 `3c3126bd65b6f576c28ac84ada8ed09b` (knobs `k=none`,
`k=arr`, `k=obj`, `td=1`); page 2 `thenable2.html`, md5 `df4c4314e62101e8d4f9809377f99d65`, adds a
synchronous `AFTERLOAD` beacon immediately after `document.fonts.load()`. Both served from `/tmp/wkp` on
a fresh port, quarantine off, scored only from the `/ev` beacon log.

```sh
# on the oracle, inside the distrobox that holds the build
./run_nq.sh "http://127.0.0.1:9712/thenable.html?k=arr&td=0" 18
```

| run | query | sanitizer | beacons |
|-----|-------|-----------|---------|
| `A1` | `k=none&td=0` | none | `START` · `LOADOK n=1` · `READY` · `END hits=0 status=loaded size=2` |
| `A2` | `k=arr&td=0` | none | `START` · **`THENARR hit=1 len=1`** · `LOADOK n=1` · `READY` · `END hits=1 … size=2` |
| `A3` | `k=obj&td=0` | none | `START` · **`THENOBJ hit=1 len=1`** · `LOADOK n=1` · **`THENOBJ hit=2 len=undefined`** · `READY` · `END hits=2 … size=2` |
| `A4` | `k=arr&td=1` | none | `THENARR hit=1 len=1` · … · `END hits=1 … size=0` |
| `A5` | `k=obj&td=1` | none | `THENOBJ hit=1/2` · … · `END hits=2 … size=0` |
| `B1` | `thenable2 k=arr&td=0` | none | `THENARR hit=1 len=1` → **`AFTERLOAD st=loaded size=2`** · `LOADOK n=1` · `READY` |
| `B2` | `thenable2 k=obj&td=0` | none | `THENOBJ hit=1 len=1` → `AFTERLOAD …` · `LOADOK n=1` · **`THENOBJ hit=2 len=undefined`** · `READY` |

Three facts from that table:

1. **The accessor fires.** With `k=arr`, the getter on `Array.prototype.then` runs exactly once with
   `len=1`, while the same page with `k=none` reports `hits=0`. So a promise resolved with a JS array
   hands control to script *inside* `resolve`.
2. **It is synchronous inside `load()`, and that fixes the site.** In `B1` the hit precedes the
   `AFTERLOAD` beacon that sits on the next source line, so the resolve is the one executed before
   `FontFaceSet::load` returns: `css/FontFaceSet.cpp:215`
   (`if (!waiting) pendingPromise->promise->resolve(pendingPromise->faces);`), reached because
   `local("DejaVu Sans")` resolves during the `face.get().load()` loop at `:167`, leaving `waiting`
   false. `:252` in `faceFinished` is the same call shape and therefore the same window, but this probe
   measured `:215` directly.
3. **`Object.prototype.then` gives a second hit with `len=undefined`** (`A3`/`B2`), after `AFTERLOAD`
   and before `READY`: that is `document.fonts.ready` resolving with the `FontFaceSet` *wrapper* —
   `m_readyPromise->resolve(*this)` — and the very next statement in that row is a member call,
   `m_backing->addFontEventClient(*this)` (`css/FontFaceSet.cpp:83-84`). With `td=1` the getter removes
   `<style>` and forces layout (`document.fonts.size` goes 2 → 0 in `A4`/`A5`), so the teardown really
   executed inside the window, and the engine survived it: `access: none`, `SUMMARY: none`, in 2/2 runs.
   `m_backing` is a `Ref<CSSFontFaceSet>` and `FontFaceSet` is `RefCounted` (`FontFaceSet.h:41`), so this
   is the expected result — but it is now measured rather than assumed.

Consequence for the rest of this doc: rows whose sink is `resolve(<DOM object or sequence>)` are script
windows. Rows whose sink is `reject(Exception)`, `resolve()` or a primitive are not.

## The 26 rows

`file:line` is the script-running call. "Free reachable" asks whether a callback on that sink can destroy
the object used by the statements after it, in the same frame.

| # | site | runs script | used afterwards | free reachable? | verdict |
|---|------|-------------|-----------------|-----------------|---------|
| 1 | `css/FontFace.cpp:344` `fontStateChanged` | `m_loadedPromise->resolve(*this)` | `return` — nothing in this frame | **yes, in the callers** | the known CVE (`docs/65`); this frame is the free site, not the tail |
| 2 | `css/FontFace.cpp:54` `setErrorState` | `reject(Exception)` | `m_backing->setErrorState()` | no — reject of an `Exception` cannot read `then` | inert; `m_backing` is a `Ref` anyway |
| 3 | `css/FontFaceSet.cpp:83` ctor / ready resolve | `m_readyPromise->resolve(*this)` | `m_backing->addFontEventClient(*this)` | no | window **measured** (A3/B2 hit 2); teardown survived, 1/1 (A5) |
| 4 | `css/FontFaceSet.cpp:188` `load` | `resolve(array of wrappers)` | `return` | no | quirks-mode branch only; window measured for the same value type (`:215`) |
| 5 | `css/FontFaceSet.cpp:215` `load` | `resolve(pendingPromise->faces)` | `}` — none | no | window **measured** (A2/B1); no tail to attack |
| 6 | `css/FontFaceSet.cpp:252` `faceFinished` | `resolve(pendingPromise->faces)` | `pendingPromise->hasReachedTerminalState = true` | no | `pendingPromises` is `Vector<Ref<PendingPromise>>` (`FontFaceSet.h:119`), so the write target is ref-held |
| 7 | `css/FontFaceSet.cpp:257` `faceFinished` | `reject(NetworkError)` | `hasReachedTerminalState = true` | no — reject cannot run script | inert |
| 8 | `css/CSSStyleSheet.cpp:485` `replace` | `resolve<IDLInterface<CSSStyleSheet>>(*this)` | none (function ends) | no | window exists, no post-script use |
| 9 | `css/MediaQueryList.cpp:104` `evaluate` | `dispatchEvent(change)` | `m_needsNotification = false` | no | caller `MediaQueryMatcher::evaluateAll` copies the set and holds `RefPtr protectedList` (`:125-127`) |
| 10 | `css/SelectorChecker.cpp:1307` | `filter->reject(hasSelector)` | — | — | **false positive**: `HasSelectorFilter::reject`, not a promise. Kept to show the name matcher's blind spot |
| 11 | `css/DOMCSSPaintWorklet.cpp:83` `addModule` | `promise.resolve()` | none | no | no value, no `then` read |
| 12 | `dom/AbortSignal.cpp:146` `signalAbort` | `dispatchEvent(abort)` | `for (auto& s : std::exchange(m_dependentSignals, { }))` | no | `Ref protectedThis { *this }` at `:140`; `m_dependentSignals` is a `WeakListHashSet` (`AbortSignal.h:76,101`) |
| 13 | `dom/AbortSignal.cpp:179` | `algorithm->handleEvent(reason)` | `return 0` | no | internal `WTF::Function` (remove-listener), not a JS callback; also returns immediately |
| 14 | `dom/EventTarget.cpp:257` `dispatchEvent` | `fireEventListeners(capturing)` | `fireEventListeners(bubbling)`, `event.resetAfterDispatch()` | no | `event` is the caller's `Ref` |
| 15 | `dom/EventTarget.cpp:372` `innerInvokeEventListeners` | `callback().handleEvent(context, event)` | `didHandleEvent(…, *registeredListener)`, `registeredListener->isPassive()` | no | the vector is **passed by value** (`EventListenerVector = Vector<RefPtr<RegisteredEventListener>>`, `EventListenerMap.h:46`) and `Ref<EventTarget> protectedThis` is held for the loop |
| 16 | `dom/Document.cpp:1439` `setReadyState` | `dispatchEvent(readystatechange)` | `settings().suppressesIncrementalRendering()`, `setVisualUpdatesAllowed()` | no | no local `Ref`, but upstream `main` has the identical shape and callers hold the `Document`; not provable either way from JS |
| 17 | `dom/Document.cpp:4506` `runResizeSteps` | `dispatchWindowEvent(resize)` | `m_needsVisualViewportResizeEvent` | no | `this` is the `Document`, alive |
| 18 | `dom/Document.cpp:4575` `runScrollSteps` | `target->dispatchEvent(scroll)` | next `target->isDocumentNode()` | no | `targets` is `Vector<GCReachableRef<ContainerNode>>` (`Document.cpp:394`) and is moved out before the loop |
| 19 | `dom/Document.cpp:6470` `finishedParsing` | `dispatchEvent(DOMContentLoaded)` | `m_eventTiming…`, `m_sharedObjectPoolClearTimer.startOneShot`, `m_cachedResourceLoader->clearPreloads` | no | `Ref<Document> protectedThis(*this)` at `:6454` |
| 20 | `dom/Document.cpp:9463` | `postTask(weakThis)` | — | — | deferred, not a synchronous sink |
| 21 | `dom/FullscreenManager.cpp:288` `cancelFullscreen` | `reject(Exception)` | `m_pendingPromise = nullptr` | no | reject cannot run script |
| 22 | `dom/FullscreenManager.cpp:395` `exitFullscreen` | `reject(TypeError)` | `m_pendingPromise = WTFMove(promise)`, `finishExitFullscreen`, `m_pendingFullscreenElement` | no | same |
| 23 | `dom/FullscreenManager.cpp:642` | `reject(TypeError)` | `m_pendingPromise = nullptr` | no | same |
| 24 | `dom/FullscreenManager.cpp:658` `dispatchEventForNode` | `node.dispatchEvent(fullscreenchange)` | `node.hasEventListeners(…)`, second `node.dispatchEvent(…)` | no | the node comes from a `Deque<GCReachableRef<Node>>` (`:636`, `:691`) and the manager holds `RefPtr<Element> m_fullscreenElement` |
| 25 | `dom/IdleCallbackController.cpp:125` | `callback->handleEvent(idleDeadline)` | `m_runnableIdleCallbacks.isEmpty()`, `queueTaskToInvokeIdleCallbacks` | no | controller is `std::unique_ptr` owned by `Document` (`Document.h:2099`); the task captures `Ref{*m_document}` |
| 26 | `dom/RejectedPromiseTracker.cpp:171` | `dispatchEvent(rejectionhandled)` | `m_context->reportUnhandledPromiseRejection(…)`, `m_outstandingRejectedPromises.set(…)` | no | tracker is owned by its `ScriptExecutionContext` (`ScriptExecutionContext.h:270`), which the listener cannot destroy |
| 27 | `dom/ScriptExecutionContext.cpp:534` `dispatchErrorEvent` | `target->dispatchEvent(*errorEvent)` | `m_inDispatchErrorEvent = false`, `errorEvent->defaultPrevented()` | no | `errorEvent` is a local `RefPtr`; `this` is the context, alive through the caller |
| 28 | `dom/ScriptedAnimationController.cpp:171` | `callback->handleEvent(highResNowMs)` | `InspectorInstrumentation::didFireAnimationFrame(protectedDocument, …)` | no | `protectedDocument` is a local `Ref` in that frame |

Rows counted as candidates: 28 listed, 26 with a real synchronous sink (10 and 20 are excluded as a
false positive and a deferred sink), 0 with a reachable free.

## What this does and does not say

- It does **not** say `css/` and `dom/` are clean. It says the pattern *as defined* — script inside a
  method, then a member use of the same object — has no unguarded instance in these two directories in
  this drop. WebKit's hot directories are heavily fuzzed, and the guards are one-line `Ref`s, which is
  exactly the shape that survives that treatment.
- The weak point of the audit is the fourth column: "free reachable" is a reading of ownership
  (`Ref`, `RefCounted`, owner-held `unique_ptr`, `GCReachableRef`, `WeakListHashSet`), not a run. Row 16
  is the only one where the ownership argument is indirect (upstream shape rather than a local `Ref`).
- The audit's **new** contribution is the sink taxonomy. The programme had been treating
  `dispatchEvent` as the only script-in-C++ sink. `resolve(<object>)` is one too, it is measured
  (`A2`/`A3`/`B1`/`B2`), and it is more numerous than event dispatch in `css/`. Any future audit of this
  pattern must include it, and any page that wants a synchronous script window inside a WebCore frame can
  now use `Array.prototype.then` instead of a DOM wrapper's own `then` property — which matters on the
  console, where a container-backed `FontFace` has no wrapper at all (`docs/65`, Attempt 11).

## Next subsystem

`css/` and `dom/` are exhausted for this pattern. The next place to look is **`Source/WebCore/html/`**,
for the same reason the font bug existed: its callbacks (`HTMLMediaElement` events, form-control
`selectionchange`, `HTMLInputElement` setters that re-enter layout) are far less fuzzed than `dom/`, and
the free there is a *node* or a *media player*, which script can destroy synchronously
(`element.remove()` frees an unref'd node immediately). The concrete action is in `GOAL.md`.

## Reproducing

```sh
# the sweep (read-only, prints 123 rows as JSON)
python3 tools/pattern-sweep.py > /tmp/audit3.json

# probe A/B (build lives inside the distrobox; outside it libasan.so.8 is not on the loader path)
scp research/cve-2026-43715/thenable*.html teo@<lab-ip>:/tmp/wkp/
ssh teo@<lab-ip> 'distrobox enter wk -- bash /tmp/thenable_runs.sh'
```

Logs: `data/cand-audit/thenable/A1-A5.txt`, `B1-B2.txt`; page md5s
`3c3126bd65b6f576c28ac84ada8ed09b` (A) and `df4c4314e62101e8d4f9809377f99d65` (B).
