# The `resolve(<DOM object>)` window across the whole tree

GOAL action (2026-10-29), the one script window in this drop that is not an event dispatch. `docs/69` measured
that a promise resolved with a DOM object hands control to script *synchronously* (`Array.prototype.then` /
`Object.prototype.then`), and `docs/70`-`73` closed every event-dispatch and observer-callback site. This doc
sweeps the remaining surface: **every promise settlement in `Source/WebCore/`, all directories, `.cpp` and `.h`**.

Short answer: **10,035 files, 364 settlement-shaped calls, 92 `resolve` arguments that are neither empty nor a brace
list in `.cpp` (17 of them literal primitives, so 75 carry a value), 41 of those with a statement after the call in
the same frame, 11 of them genuine post-resolve uses, 0 with a reachable free.** One family was measured rather
than argued: `WebAnimation`'s `resolve(*this)` fires the window twice inside one `Animation.finish()` call, script
can cancel the animation and remove its element inside it, and the frame then continues into
`hasEventListeners`/`effectEndTime`/`animationDidFinishForElement` with no sanitizer report — because the
resolved value *is* the object as a JS wrapper, and a wrapper holds `Ref<ImplementationClass>`.

## Method

```sh
cd /Users/<user>/Documents/ps5-bootchain
python3 tools/resolve-sweep.py > data/resolve-sweep/rows.json   # new tool, docs/74
```

`tools/resolve-sweep.py` walks every `.cpp` and `.h` under `Source/WebCore` recursively, strips comments and
string literals, enumerates function bodies by brace matching, and for every call matching
`resolve(` / `resolveWith*` / `settle(` emits: file, enclosing function, call line, the raw argument text, a
coarse argument class, the enclosing `for`/`while` headers whose body contains the call, and the statements that
follow inside the same function body (continuing past the block that contained the call).

```text
files 10035  (4014 .cpp, 6021 .h)   settlement-shaped calls 364  (301 .cpp, 63 .h)
```

Of the 301 `.cpp` calls, **247 are on a promise-named receiver** (`promise`, `m_xPromise`, `deferredPromise`,
`pendingPromise`, … — `grep -c '(promise|Promise)[A-Za-z]*\s*(->|\.)\s*(resolve|resolveWith[A-Za-z]*|settle)\s*\('`).
The other 54 are **methods that happen to be called `resolve`** — the net's false positives, listed in the last
table; 41 of the 63 header rows are their declarations, not calls.

## What the engine says the window is

The split is decided by the argument's type, in the engine's own promise machinery:

```text
Source/JavaScriptCore/builtins/PromiseOperations.js:187:    if (!@isObject(resolution))
PromiseOperations.js:188:        return @fulfillPromise(promise, resolution);
PromiseOperations.js:190:    var then;
PromiseOperations.js:191:    try {
PromiseOperations.js:192:        then = resolution.then;
```

So `resolve(<primitive>)`, `resolve()`, `resolve({ })` (the C++ brace form, an empty value) and every
`reject(...)` are **not** windows: a rejection never reads `then`, and a non-object fulfilment fulfils on the spot. Only an object argument
reaches line 192. `bindings/js/JSDOMPromiseDeferred.cpp:86` (`deferred()->resolve(&lexicalGlobalObject, resolution)`)
is the one bridge both `DOMPromiseDeferred` and `DOMPromiseProxy` settle through.

Coarse class of the 92 `.cpp` `resolve` arguments that are neither empty nor a brace list:

| class | rows | what it is |
|---|---|---|
| `this` (`resolve(*this)`) | 14 | `WebAnimation` ×9, `HTMLModelElement`, `FontFace`, `FontFaceSet` ×3 |
| `*ident` (deref) | 9 | `resolve(*certificate)`, `resolve(*camera)`, style `resolve(*animatedStyle, …)` |
| bare id / `WTFMove(id)` | 44 | `resolve(cache)`, `resolve(error)`, `resolve(WTFMove(devices))` |
| factory call | 24 | `resolve(PermissionStatus::create(...))`, `resolve(PublicKeyCredential::create(...))` … |
| `Ref::releaseNonNull()` | 1 | `resolve(referenceSpace.releaseNonNull())` |

17 of the 92 are literal primitives (`false`, `nullptr`, `true`, `JSC::jsNull()`, `PermissionState::Denied`) and
cannot open a window at all (`PromiseOperations.js:187`). The 14 `this` rows are the ones that matter: the resolved
value and the object whose members are used afterwards are the *same object*. `css/`'s four are `FontFace:344` and
`FontFaceSet:83/272/278` — the first two audited in `docs/69`, the last two have no statement after the resolve —
and the new ones are `WebAnimation` ×9 and `HTMLModelElement`.

## The 11 new rows with a post-resolve statement, read

41 `.cpp` rows have a statement after the call in their own frame (43 including two header template bodies). Of
those 41: **13 resolve a literal primitive**, **11 are artifacts** (the sibling arm of an `if`/`switch`, a deferred
lambda's body, or the next function definition), **2 are methods named `resolve`** (`WebAnimation::commitStyles`
calls `WebAnimation::resolve(RenderStyle&, …)`, the style-resolution routine), **1 is compiled out**
(`PeerConnectionBackend::generateCertificate`, `ENABLE_WEB_RTC 0` in the ASAN build's `cmakeconfig.h:146`),
**1 is testing-only** (`Internals`), and **2 are the already-audited `css/` rows** — which leaves the 11 below.

"Runs script" is true for every row here (object argument, `PromiseOperations.js:192`). "Free reachable" asks
whether a `then` getter can destroy what the next statement uses, in that frame.

| # | site | resolved value | next statement uses | free reachable? |
|----|------|----------------|---------------------|-----------------|
| 1 | `animation/WebAnimation.cpp:382` `setStartTime` | `*this` (Animation) | `timingDidChange(...)`, `invalidateEffect()` on `this` | no — `this` is `RefCounted` and held by the wrapper that made the `startTime=` call (`bindings/js/JSDOMWrapper.h:88` `Ref<ImplementationClass> m_wrapped`) |
| 2 | `animation/WebAnimation.cpp:498` `setCurrentTime` | `*this` | `timingDidChange(...)`, `m_effect->animationDidChangeTimingProperties()` | no — same; `m_effect` is a `RefPtr` |
| 3 | `animation/WebAnimation.cpp:867` `finish` (pending pause) | `*this` | `timingDidChange(DidSeek::Yes, SynchronouslyNotify::Yes)` | no |
| 4 | `animation/WebAnimation.cpp:873` `finish` (pending play) | `*this` | `timingDidChange(...)`, `invalidateEffect()` | no |
| 5 | `animation/WebAnimation.cpp:1003` `finishNotificationSteps` | `*this` | `hasEventListeners(finishEvent)`, `m_timeline`, `effectEndTime()`, `animationDidFinishForElement(*target)` | no — measured, see below |
| 6 | `animation/WebAnimation.cpp:1201` `runPendingPlayTask` | `*this` | `timingDidChange`, `invalidateEffect` | no |
| 7 | `animation/WebAnimation.cpp:1340` `runPendingPauseTask` | `*this` | `timingDidChange`, `invalidateEffect` | no |
| 8 | `Modules/cache/DOMCacheStorage.cpp:206` `doOpen` | `DOMCache::create(...)` | `m_connection->open(*origin(), …)` on `this` | no — `this` is `RefCounted` and the lambda holding it also holds `makePendingActivity(*this)` (`:210`) |
| 9 | `Modules/cache/DOMCacheStorage.cpp:218` `doOpen` | `cache` (`Ref<DOMCache>` local) | `m_caches.append(WTFMove(cache))` | no — `m_caches` is `Vector<Ref<DOMCache>>`, and the appended object is a `Ref` local |
| 10 | `Modules/permissions/Permissions.cpp:160` `query` | `PermissionStatus::create(...)` | `PermissionController::shared().query(..., *page, *source, …)` | no — `page` is a `WeakPtr<Page>` and `source` a local pointer; `this` is not used |
| 11 | `workers/service/FetchEvent.cpp:192` `navigationPreloadIsReady` | `Strong<Unknown>` holding the `FetchResponse` wrapper | `context->postTask(...)` | no — `context` is the worker's `ScriptExecutionContext`, not script-freeable |

Two rows outside this table are worth naming because they look like the pattern and are not:
`testing/Internals.cpp:7068` (`resolve(uuids)` then a loader callback) is only reachable through `Internals`,
which no ordinary page has; and `Modules/mediastream/UserMediaRequest.cpp:198`'s "next statement" is line 201 of
`allow()`, which runs *before* the `callback` lambda that resolves — the tool folds a lambda body into its
enclosing function when the lambda has no parseable signature (blind spot 2 below).

The remaining 28 of the 41 are the buckets named above, not post-resolve uses: the **other arm of the same `if`**
or the next branch of a `switch` (`Modules/WebGPU/GPU.cpp:60` `resolve(nullptr)` then the else-branch body,
`Modules/webauthn/AuthenticatorCoordinator.cpp:188/271` `resolve(...)` then the `ASSERT`/`reject` of the failure
path, `Modules/webxr/WebXRSystem.cpp:162/179/185` adjacent `resolve(true/false)` statements, `GPUDevice.cpp:266/269`
the other `WTF::switchOn` arms), a **deferred lambda's body** (`Permissions.cpp:170/196`,
`UserMediaRequest.cpp:198`, `PaymentRequest.cpp:527` — whose argument is a `bool` anyway),
`ServiceWorkerContainer.cpp:126` (the next function definition, not a tail), the two `commitStyles` style-resolve
false positives, the compiled-out WebRTC row, `Internals`, and the two `css/` rows already audited in `docs/69`.
Thirteen of the 41 resolve a **literal primitive** (`false`, `nullptr`, `true`, `jsNull`, `PermissionState::Denied`)
and cannot open a window at all by `PromiseOperations.js:187`.

## The `WebAnimation` family, measured

This is the only new family where seven resolve sites sit immediately before a member use of the *same* object,
so it got the probe. Page `research/resolve-sweep/anim-window.html`, md5
`ab0559dbd066664f513e37d47f5625b2`. Knobs: `k=none|then` (getter on `Object.prototype.then`), `atk=none|rm|
cancel|cancelrm`, `pre=0|1` (touch `a.ready`/`a.finished` first), `probe=1` (in-page positive control:
`Promise.resolve({probe:1})` after arming).

```sh
scp research/resolve-sweep/anim-window.html teo@<lab-ip>:/tmp/wkp/
ssh teo@<lab-ip> 'distrobox enter wk -- bash /tmp/anim_runs.sh'     # quarantine off, fresh port per run
```

| run | query | sanitizer | beacons |
|-----|-------|-----------|---------|
| `C1` | `k=none` | `access: none` / `SUMMARY: none` | `START` · `ANIM ok st=running` · `PRE st=running ct=0` · `PROMISES ready=Promise fin=Promise` · `POST st=finished hits=0 kids=1 fin=0` · `FINEV st=finished` · `LATE … fin=1` · `END hits=0 fin=1 st=finished` |
| `P0` | `k=then&atk=none&pre=0&probe=0` | `access: none` / `SUMMARY: none` | `ARMED` · `POST st=finished hits=0 kids=1 fin=0` · `DEL ok=undefined` · `FINEV` · `END hits=0 fin=1 st=finished` |
| `C2` | `k=then&atk=none&pre=1&probe=1` | `access: none` / `SUMMARY: none` | `ARMED` · **`THEN hit=1 on=Object st=running`** · `PROBE` · **`THEN hit=2 on=Animation st=finished`** · **`THEN hit=3 on=Animation st=finished`** · `POST st=finished hits=3 kids=1 fin=0` · `DEL ok=undefined` · `FINEV st=finished hits=3` · `END hits=3 fin=1 st=finished` |
| `T1` | `k=then&atk=cancelrm&pre=1` | `access: none` / `SUMMARY: none` | `ARMED` · `THEN hit=1 on=Animation st=finished` · `POST st=idle hits=1 kids=0 fin=0` · `DEL ok=undefined` · `LATE st=idle hits=1 kids=0 fin=0` · `END hits=1 fin=0 st=idle` |
| `T2` | `k=then&atk=rm&pre=1` | `access: none` / `SUMMARY: none` | `ARMED` · `THEN hit=1 on=Animation st=finished` · `THEN hit=2 on=Animation st=finished kids=0` · `POST st=finished hits=2 kids=0 fin=0` · `DEL ok=undefined` · `FINEV st=finished hits=2` · `LATE … fin=1` · `END hits=2 fin=1 st=finished` |

Four facts, each with its control:

1. **The window fires, on a wrapper-backed object, inside the C++ frame.** `C2` prints
   `THEN hit=2 on=Animation` and `hit=3 on=Animation` *before* `POST`, the beacon on the next source line after
   `a.finish()`; `C1` (no getter) prints `hits=0`. The `on=` field is `Object.prototype.toString.call(this)` of
   the resolved value, so the object handed to script is the `Animation` itself. `hit=1 on=Object` is the in-page
   positive control (`Promise.resolve({probe:1})`), which is what proves the instrumentation works rather than
   the absence of beacons.
2. **`finish()` opens the window twice**, not once: the ready promise at `:867`/`:873` and the finished promise
   in `finishNotificationSteps` at `:1003`, both synchronous (`hit=2`, `hit=3` before `POST`). Two hits cannot be
   one promise settled twice: `JSPromise::resolve` returns early once the first-resolving flag is set
   (`Source/JavaScriptCore/runtime/JSPromise.cpp:200`), so each hit is a different promise.
3. **A `DOMPromiseProxy` resolve is a no-op unless the page already holds the promise.** `P0` (same page, same
   getter, `pre=0` — `a.ready`/`a.finished` never touched) prints `hits=0`, because
   `DOMPromiseProxyWithResolveCallback::resolve` only settles the `DeferredPromise`s already in
   `m_deferredPromises` (`bindings/js/DOMPromiseProxy.h:340`), and an empty list means no `toJS`, no `then`
   read. This matters for the console: a window of this class exists only where the page has asked for the
   promise — which the page always has when it awaits it, and never otherwise.
4. **Script can change the animation's state inside the window and the frame survives it.** `T1`
   (`el.remove()` + `a.cancel()`) finishes with `POST st=idle kids=0 fin=0`: the cancel took, `finish()` returned
   without throwing, and `finishNotificationSteps`' own `playState() != Finished` guard stopped the second
   resolve, so no `finish` event was dispatched — which is at least self-consistent. `T2` (remove only) prints
   `POST st=finished kids=0` and still dispatches `FINEV`, i.e. the `:1014-1029` tail ran after script with the
   effect's target detached from the document: `keyframeEffect->target()` is a `RefPtr` local, and
   `target->document().page()` is evaluated on the live element, so nothing is dangling. `access: none` in 5/5
   runs.

The ownership argument for rows 1-7 is in the same source: `WebAnimation` is
`RefCounted<WebAnimation>, public EventTarget, public ActiveDOMObject` (`animation/WebAnimation.h:58`) and its
wrapper holds `Ref<ImplementationClass> m_wrapped` (`bindings/js/JSDOMWrapper.h:88`), so the object that resolves
`*this` is kept alive by the very JS call that is running the setter — `cancel()` or `remove()` inside the getter
changes its state but cannot drop that reference. The microtask path that reaches `finishNotificationSteps`
outside a JS call already captures `protectedThis = Ref { *this }` (`WebAnimation.cpp:975`).

## The loop shape — the CVE's actual shape — applied to settlements

`CSSFontFace::setStatus`'s bug is `iterateClients` walking a client set while a callback frees the iterating
object. The promise analogue is a settlement inside a `for` over a member container. The sweep finds **13**
settlements inside *some* loop and **3** inside a loop over a member:

| site | loop header | verdict |
|------|-------------|---------|
| `Modules/mediastream/RTCRtpScriptTransformer.cpp:159` | `for (auto& promise : std::exchange(m_pendingKeyFramePromises, { }))` | safe — drained first; `resolve()` is argument-less (`PromiseOperations.js:187` short-circuits on `undefined`) |
| `Modules/remoteplayback/RemotePlayback.cpp:289` | `for (auto& promise : std::exchange(m_promptPromises, { }))` | safe — same shape, same argument-less resolve |
| `Modules/paymentrequest/PaymentRequest.cpp:527` | `for (auto& paymentMethod : m_serializedMethodData)` | not a window — the resolve is inside a `handler->canMakePayment` completion lambda and its argument is a `bool` |

So the one place the drop is at risk of the CVE's shape, it already copies/drains the container before settling —
`DOMPromiseProxy::resolve` does the same deliberately (`bindings/js/DOMPromiseProxy.h:340`
`auto deferredPromisesCopy = m_deferredPromises;`), and its own comment says why
(`:311` "Calls to reject() / resolve() may destroy |this|").

## What the net's false positives were, so the next run does not recount them

Methods named `resolve` that are not promise settlements: `WebAnimation::resolve` / `CSSTransition::resolve` /
`DeclarativeAnimation::resolve` (style resolution, `RenderStyle&`), `SharingResolver::resolve`,
`TreeResolver::resolve`, `ViewportArguments::resolve`, `TextDecorationThickness::resolve` (via
`rendering/TextBoxPainter.cpp`, `style/InlineTextBoxStyle.cpp`), `ColorModels`' component `resolve`,
`ScriptModuleLoader::resolve` (the JSC module-loader hook), `DNSResolveQueue*::resolve` / `DNSPrefetch::resolve`,
`FileSystemStorageConnection::resolve` / `WorkerFileSystemStorageConnection::resolve` /
`FileSystemDirectoryHandle::resolve`'s inner connection call, and `FetchBodyConsumer::resolve*` (a static helper
that takes a `Ref<DeferredPromise>` and settles it in another frame). That is the 54 `.cpp` calls; 41 of the 63
header rows are declarations of the same shape, not calls.

## What this does and does not say

- **Does say:** the `resolve(<DOM object>)` surface is closed in this drop, with the reason stated per row and
  the strongest family measured. A resolve window exists (measured twice per `finish()`), but the object it names
  is the object the following statements use, and a JS wrapper keeps that object alive
  (`JSDOMWrapper.h:88`), so script inside the window can change state but not free the object.
- **Does not say** the other 51 rows — those whose own frame has no statement after the call — are safe: a
  *caller* can use an object after the callee resolved a promise. The sweep is frame-local by construction, and
  caller-side tails were not walked.
- Blind spots of the tool: (1) the tail now continues past the closing brace of the block containing the call, so
  it can pick up the sibling branch of an `if`; (2) a lambda without a parseable signature is folded into its
  enclosing function, so a deferred callback's body can appear as the enclosing frame's tail
  (`UserMediaRequest.cpp:198`) — every row above was read in source to settle which it is; (3) 6 of the 7 object-valued header rows are the `DeferredPromise` bridges themselves
  (`JSDOMPromiseDeferred.h:82/95/107/124/141/181`, whose tail is `DEFERRED_PROMISE_HANDLE_AND_RETURN_IF_EXCEPTION`
  on a local `JSGlobalObject*`), the seventh is the `ColorModels` false positive, and the real template settlements
  (`DOMPromiseProxy.h`'s three `resolve` variants, `JSDOMAsyncIterator.h:264`) are read in the loop section; (4) `testing/Internals.cpp` rows are not reachable from an ordinary page.

## Logs

`data/resolve-sweep/rows.json` (the sweep), `data/resolve-sweep/counts.json`,
`data/resolve-sweep/anim/{run,srv}_C1|P0|C2|T1|T2.log`, page
`research/resolve-sweep/anim-window.html` (md5 `ab0559dbd066664f513e37d47f5625b2`), runner
`/tmp/anim_runs.sh` on the oracle.
