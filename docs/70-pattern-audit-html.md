# The CVE-2026-43715 pattern in `html/` — 323 files, 28 dispatch sites, 0 with a reachable free

GOAL action (2026-10-29), the item after `docs/69`. The pattern is: **a C++ method runs script and then
reads or writes something the script can free.** `docs/65` proved it once in `css/FontFaceSet.cpp`; `docs/69`
found no second instance in `css/` + `dom/` and left `html/` as the next place with the same shape and a
weaker guard history (media-element events, form-control setters, the parser). This doc is that audit.

Short answer: **65 raw rows across 27 files, 28 real synchronous dispatch sites read in source, 0 with a
reachable free.** Every one of them is guarded in one of four ways, and three of the verdicts are measured
here rather than read. The two sites that *look* like the font bug are not merely guarded, they are
**unreachable in this build**: `HTMLElement::showPopover` because the popover API is not exposed at all
(`P0`: `CALL err=TypeError`; `defaultPopoverAttributeEnabled()` is `false` on every non-Cocoa port), and
`WebGLRenderingContextBase::maybeRestoreContext` because `ENABLE_WEBGL` is `OFF` on Sony's own port
(`OptionsPlayStation.cmake:272`; `W1`: `NOCTX`). The popover default applies to the console too; the WebGL
flag is the console's own build flag.

## Method

```sh
cd /Users/<user>/Documents/ps5-bootchain
python3 tools/pattern-sweep.py html                                              # 54 rows, 23 files
python3 tools/pattern-sweep.py html/canvas html/forms html/parser html/shadow html/track   # 11 rows, 4 files
grep -rn "dispatchEvent(" Source/WebCore/html/*.cpp | wc -l                      # 30 hits
```

The sweep is not recursive, and `html/` has five subdirectories — 177 top-level `.cpp` plus 83 in
`canvas/`, 26 in `track/`, 20 in `parser/`, 16 in `shadow/`, 1 in `forms/` = **323 files**. Without the
second command above the audit would have missed `WebGLRenderingContextBase.cpp:5758` — the only site in the
whole audit where a member call on `this` follows a *synchronous* dispatch of a cancelable event
(`maybeRestoreContext` → `notifyCanvasContentChanged()`, no local `Ref` on either the context or the canvas)
— and `TrackListBase.cpp:153`. 65 rows total; 31 of them are `dispatchEvent`, 6 `handleEvent`, 9 `resolve`,
16 `reject`, 3 `postTask`.

The grep is the completeness check the sweep cannot give: **30 `dispatchEvent(` occurrences at top level**,
of which 7 are definitions/forwarders (`HTMLCanvasElement.cpp:1059/1061`, `HTMLMediaElement.cpp:6594/6605`,
`OffscreenCanvas.cpp:590/592`) or a comment (`HTMLMediaElement.cpp:6867`), leaving **23 real call sites**;
+5 in the subdirectories (`WebGLRenderingContextBase.cpp:565,609,5716,5758`, `TrackListBase.cpp:153`) =
**28**. Every one is in the table below. Nothing in `html/` was left to the sweep's judgement.

## The 28 sites

"Used afterwards" is the first member/`this` access after the sink returns; "ownership" is what keeps that
object alive; "free reachable?" asks whether a listener on that sink can destroy it in the same frame.

| # | site | sink | used afterwards | ownership of what's used | free reachable? |
|---|------|------|-----------------|--------------------------|-----------------|
| 1 | `HTMLDetailsElement.cpp:151` | `toggle` | `m_isToggleEventTaskQueued = false` | the task: `queueTaskKeepingThisNodeAlive` | no — **deferred** |
| 2 | `HTMLDialogElement.cpp:135` | `cancel` | `close(nullString())` | `queueTaskKeepingThisNodeAlive` | no — deferred |
| 3 | `HTMLElement.cpp:1346` | `toggle` (popover) | none (last stmt) | `queueTaskKeepingThisNodeAlive` | no — deferred |
| 4 | `HTMLElement.cpp:1368` `showPopover` | `beforetoggle` | `checkPopoverValidity(*this, …)` | caller: `RefPtr target` (`HTMLFormControlElement.cpp:391`) or the JS wrapper | no — and the API is **absent** (`P0`) |
| 5 | `HTMLElement.cpp:1447` `hidePopoverInternal` | `beforetoggle` | `checkPopoverValidity(*this, …)` | caller: `RefPtr popover` (`Document.cpp:9047`), `RefPtr target` | no — same |
| 6 | `HTMLFormElement.cpp:292` `submitIfPossible` | `submit` | `m_shouldSubmit`, `m_isSubmittingOrPreparingForSubmission` | `Ref protectedThis { *this }` at `:289` | no |
| 7 | `HTMLFormElement.cpp:461` `reset` | `reset` | `resetListedFormControlElements()` | `Ref<HTMLFormElement> protectedThis(*this)` at `:456` | no |
| 8 | `HTMLFormElement.cpp:1006` `constructEntryList` | `formdata` | `submitter->setActivatedSubmit(false)` | parameter is `RefPtr<HTMLFormControlElement>&&`; `Ref<DOMFormData>&&` | no |
| 9 | `HTMLImageLoader.cpp:72` | `load`/`error` | none (last stmt) | — | no |
| 10 | `HTMLInputElement.cpp:1599` `onSearch` | `search` | none (last stmt) | — | no |
| 11 | `HTMLLinkElement.cpp:556` | `load`/`error` | none (last stmt) | `EventSender` holds `WeakPtr<T>`, `dom/EventSender.h:60` | no |
| 12 | `HTMLMediaElement.cpp:1064` `notifyAboutPlaying` | `playing` | `resolvePendingPlayPromises`, `schedulePlaybackControlsManagerUpdate` | `Ref<HTMLMediaElement> protectedThis(*this)` at `:1061`, comment "The 'playing' event can make arbitrary DOM mutations." | no |
| 13 | `HTMLMediaElement.cpp:5043` `layoutSizeChanged` | `resize` on the UA shadow root | `m_mediaControlsHost->updateCaptionDisplaySizes()` | inside `queueTaskKeepingObjectAlive(*this, …)`; `m_mediaControlsHost` is `RefPtr` | no — deferred, and UA-shadow listeners are not script |
| 14 | `HTMLMediaElement.cpp:6515` | wireless-target event | none after | inside `queueTaskKeepingObjectAlive` | no — deferred |
| 15 | `HTMLMediaElement.cpp:6605` | forwards to `HTMLElement::dispatchEvent` | `m_videoFullscreenStandby`, `m_videoFullscreenMode`, `document().page()` | **no callers** (see below) | unreachable: dead code |
| 16 | `HTMLScriptElement.cpp:173` | `load` | none (last stmt) | — | no |
| 17 | `HTMLSlotElement.cpp:228` | `slotchange` | none (last stmt) | `event->setTarget(Ref { *this })` at `:227` | no |
| 18 | `HTMLStyleElement.cpp:143` | `load`/`error` | none (last stmt) | `EventSender` `WeakPtr` | no |
| 19 | `HTMLTextFormControlElement.cpp:545` | `select` | none (last stmt) | — | no |
| 20 | `HTMLTrackElement.cpp:261` | `error` | `return` | `makePendingActivity(*this)` at `:247`, comment "Make sure the JS wrapper stays alive until the end of this method" | no |
| 21 | `HTMLTrackElement.cpp:272` | `load` | none (last stmt) | same | no |
| 22 | `MediaController.cpp:551` `asyncEventTimerFired` | queued events | none after the loop | `Vector<Ref<Event>> pendingEvents` local | no — deferred |
| 23 | `OffscreenCanvas.cpp:592` | forwards to `EventDispatcher` | none | `EventDispatcher::dispatchEvent({ this }, event)` | no |
| 24 | `ValidatedFormListedElement.cpp:126` `checkValidity` | `invalid` | `element.isConnected()`, `originalDocument.ptr() == &element.document()` | `Ref protectedThis { element }` at `:123`, comment "An event handler can deref this object." | no — **measured**, see `V1` |
| 25 | `canvas/WebGLRenderingContextBase.cpp:565`, `:609` `create` | `webglcontextcreationerror` | `return nullptr` | — | no |
| 26 | `canvas/WebGLRenderingContextBase.cpp:5716` | `webglcontextlost` | `m_contextLostState->restoreRequested = event->defaultPrevented()` | inside `queueTaskKeepingObjectAlive` | no — deferred |
| 27 | `canvas/WebGLRenderingContextBase.cpp:5758` `maybeRestoreContext` | `webglcontextrestored` | `notifyCanvasContentChanged()` | none — the entry is `m_restoreTimer` (`:627`), a `SuspendableTimer` that holds no `Ref`; the canvas is held only by the DOM tree | no — **feature compiled out**: `ENABLE_WEBGL=OFF` (`Source/cmake/OptionsPlayStation.cmake:272`), measured `NOCTX` (`W1`) |
| 28 | `track/TrackListBase.cpp:153` | `change` | none | `queueTaskKeepingObjectAlive` | no |

Rows **not** in the table, and why: 16 `reject(...)` rows are `reject(Exception)`/`rejectType<TypeError>`
(`HTMLMediaElement` `setMediaKeys`/`setAudioOutputDevice`/`play`, `OffscreenCanvas::convertToBlob`,
`ImageBitmap::createPromise`, `HTMLVideoElement::requestFullscreen`) — an `Exception` has no `then`, so
nothing runs (`docs/69`), and the tails are `return`/`}`; 9 `resolve` rows are `resolve()` with no value or a
primitive except two — `OffscreenCanvas::convertToBlob` resolves a `Blob` and `ImageBitmap::createPromise`
resolves an `ImageBitmap`, and both are genuine `then` windows with **no statement after them**; 3 `postTask`
rows are deferred by construction; 6 `handleEvent` rows are internal (`TypeAhead`, `AttachmentSaveEventListener`
whose `m_attachment` is a `WeakPtr`, the paint worklet, the video-frame callback whose request is a
`UniqueRef` in `m_servicedVideoFrameRequests` and whose `cancelVideoFrameCallback` marks but never erases the
serviced entry).

## Measured: two of those verdicts were run, not read

Page `research/html-pattern/sink-window.html`, md5 `47d77a704283ff0fc5cb949182172b1e`; runner
`research/html-pattern/run-page.sh` (copies the page to `/tmp/wkp/index.html` on the oracle, kills stale
servers first, fresh port, `~/wk/run_nq.sh`, quarantine off, scored only from the `/ev` beacon log):

```sh
cd research/html-pattern
./run-page.sh 9731 "k=val&wipe=0" V0
./run-page.sh 9732 "k=val&wipe=1" V1
./run-page.sh 9733 "k=pop&wipe=0" P0
PAGE=webgl-restore.html ./run-page.sh 9741 "drop=0&wipe=1" W1
```

`k=val` submits a form containing `<input id=i required>` with `btn.click()`, so the `invalid` event is
dispatched by the engine's interactive-validation pass and **the input never gets a JS wrapper** (the page
names only `#wrap` and `#b`, and the capture listener never touches `event.target`). `wipe` is the only
variable: the listener either does nothing or empties `#wrap`, which removes the input mid-dispatch.

| run | query | sanitizer | beacons |
|-----|-------|-----------|---------|
| `V0` | `k=val&wipe=0` | none | `START k=val wipe=0` · `REG invalid` · **`HIT type=invalid cancelable=true conn=1`** · `HIT2 kids=2` · `CALL ok` · `POST kids=2 inp=1 pop=1` · `END` |
| `V1` | `k=val&wipe=1` | none | `START k=val wipe=1` · `REG invalid` · **`HIT type=invalid cancelable=true conn=1`** · **`HIT2 kids=0`** · `CALL ok` · **`POST kids=0 inp=0 pop=0`** · `END` |
| `P0` | `k=pop&wipe=0` | none | `START k=pop wipe=0` · `REG beforetoggle` · **`CALL err=TypeError`** · `POST kids=2 inp=1 pop=1` · `END` |
| `W1` | `drop=0&wipe=1`, page `webgl-restore.html` | none | `START drop=0 wipe=1` · **`NOCTX`** · `LATE` |

Four facts:

1. **The `invalid` window is synchronous and the teardown really runs inside it.** In `V1`, `HIT2 kids=0`
   is emitted from *inside* the listener, before `btn.click()` returns, so the subtree was gone before the
   engine's next statement — `element.isConnected()` at `ValidatedFormListedElement.cpp:127`. No ASAN,
   because `Ref protectedThis { element }` is one line above the dispatch (`:123`). That is row 24 measured,
   and it also shows why the guard is load-bearing rather than decorative.
2. **`showPopover()` does not exist in this build.** `P0` throws `TypeError` and `beforetoggle` never
   fires. `HTMLElement.idl:54-57` gates `showPopover`/`hidePopover`/`togglePopover`/`popover` on
   `[EnabledBySetting=PopoverAttributeEnabled]`, and `WebKit::defaultPopoverAttributeEnabled()` is
   `return false` for every non-Cocoa platform (`WebKit/Shared/WebPreferencesDefaultValues.cpp:289-297`).
   The attribute path dies too: `HTMLElement.cpp:419` only creates `popoverData()` when the setting is on,
   and `HTMLFormControlElement::popoverTargetElement()` returns `nullptr` when it is off (`:349`). So rows
   4 and 5 are not "guarded, could be a bug elsewhere" — on a non-Cocoa port they are unreachable.
3. The harness is not the console, and the console is still untested for this: the PlayStation port is
   non-Cocoa, so the same default applies, but that is a *read* of the default, not a run on hardware.
4. **WebGL does not exist in this build, so row 27 was never a live candidate.** `W1`
   (`webgl-restore.html`) reports `NOCTX`: `canvas.getContext('webgl')` returns null. The ASAN build's
   `configure-asan.sh` passes `-DENABLE_WEBGL=OFF`, and the comment there says why — Sony's own
   `Source/cmake/OptionsPlayStation.cmake:272` sets `WEBKIT_OPTION_DEFAULT_PORT_VALUE(ENABLE_WEBGL PRIVATE OFF)`.
   That matters for the audit: row 27 was the one row whose read verdict was *wrong*. `maybeRestoreContext`
   is also `m_restoreTimer`'s callback (`:627` — the constructor takes `*this` and the member function
   pointer), and `forceRestoreContext()` only starts that timer (`:5073-5075`), so the frame has **no** JS
   wrapper and **no** `Ref` holding the canvas: a `webglcontextrestored` listener that removes the canvas
   would free the context under its own timer. It is unreachable only because the feature is compiled out —
   on the oracle and on the target port alike.

## Row 15 is dead code, and it is the only unguarded media tail

`HTMLMediaElement::dispatchEvent(Event&)` (`HTMLMediaElement.cpp:6594`) dispatches and then reads three
members of `this` with no `Ref`:

```cpp
HTMLElement::dispatchEvent(event);
if (!m_videoFullscreenStandby && m_videoFullscreenMode == VideoFullscreenModeNone && event.type() == eventNames().webkitendfullscreenEvent)
    document().page()->chrome().client().exitVideoFullscreenForVideoElement(downcast<HTMLVideoElement>(*this));
```

It has **no call sites in the drop**: the only `dispatchEvent(` calls in `HTMLMediaElement.cpp` are
`notifyAboutPlaying` (`:1064`), the `layoutSizeChanged` task (`:5043`) and the wireless-target task (`:6515`),
all of which call the inherited `EventTarget::dispatchEvent` unqualified or are inside a `Ref`; `HTMLVideoElement.cpp`
and `HTMLAudioElement.cpp` contain no `dispatchEvent(` at all, and a tree-wide grep for `dispatchEvent(event)`
finds no media element. So the one place in `html/` that *looks* like the font bug — a synchronous dispatch
followed by unguarded member reads — never executes. (It is a latent bug in the source, not a reachable one.)

## Why nothing in `html/` is reachable

Three guards, and they are structural rather than incidental:

1. **A JS-reachable node cannot be freed while script holds it.** `JSDOMWrapper` stores
   `Ref<ImplementationClass> m_wrapped` (`bindings/js/JSDOMWrapper.h:73-87`), so every DOM object that has a
   wrapper is ref-held by that wrapper until it is collected. In `css/` the CVE worked because
   `FontFace::m_backing` is a `Ref` and the *freed* face had **no wrapper at all** (`docs/65`, Attempt 11);
   in `html/` the dispatch target is almost always the object the page just named, so it has one.
2. **Where the target is wrapper-free, WebKit has already added the `Ref`.** `makePendingActivity`
   (`HTMLTrackElement`), `Ref protectedThis` with an explanatory comment (`notifyAboutPlaying`,
   `checkValidity`, `HTMLFormElement::submit`×2/`reset`), `event->setTarget(Ref { *this })` (`HTMLSlotElement`),
   `RefPtr target`/`RefPtr popover` in the callers (`showPopover`, `hidePopoverInternal`), `UniqueRef`
   containers (`VideoFrameRequest`), `WeakPtr` (`EventSender`, `AttachmentSaveEventListener`). Six of these
   carry a comment saying the event handler can deref or destroy the object — this is a class of bug WebKit
   has already been through.
3. **The media element's own events are queued, not synchronous.** `setReadyState` only `scheduleEvent`s
   (`HTMLMediaElement.cpp:2764-2810`), `notifyFinished` uses `loadEventSender().dispatchEventSoon()`, and
   `TrackListBase::scheduleChangeEvent` uses `queueTaskKeepingObjectAlive` — so the media-player callbacks
   (`mediaPlayerReadyStateChanged`, `mediaPlayerTimeChanged`) cannot run script inside a `MediaPlayer` frame.
   That removes the "free the media player from inside its own callback" class that the GOAL action expected
   to find here.

## What this does and does not say

- It does **not** say `html/` is clean of memory bugs. It says the pattern *as defined* has no unguarded
  instance in the 28 synchronous dispatch sites of this drop, and it names the three reasons.
- The weakest read verdict is row 24 (`checkValidity`) if `V1` is read as "the guard held" — it is stronger
  than that: `HIT2 kids=0` proves the teardown ran inside the frame, so a missing `Ref` would have been a
  UAF at `:127`. The weakest verdict now is row 13 (`layoutSizeChanged`): it is a queued task whose
  `m_mediaControlsHost` is a `RefPtr`, and the `resize` is dispatched at the UA shadow root, so no script
  listener can be attached at all — but that last part is an argument from the shadow root being closed,
  not a run.
- The audit's blind spot is the sweep's name list: it cannot see `executeScript`/`evaluate`/`JSC::call`, so
  the parser's own script window (`HTMLDocumentParser::runScriptsForPausedTreeBuilder` →
  `m_scriptRunner->execute(...)`) is *not* covered by the "28 sites" count. That is the next action, and it
  is pre-read: `Document::open()` bails out when the parser is executing a script
  (`dom/Document.cpp:3067-3074`, `if (parser->isExecutingScript()) return { };`) and custom-element reactions
  are wrapped in `ThrowOnDynamicMarkupInsertionCountIncrementer` (`HTMLDocumentParser.cpp:227`), so the
  obvious self-destruct route is closed at the entry point.

## Next

1. **`html/parser/` with an extended sink list.** Add `executeScript`, `evaluate`, `JSC::call`,
   `performMicrotaskCheckpoint` and `runScriptsForPausedTreeBuilder` to `tools/pattern-sweep.py`'s `NAMES`,
   re-sweep `html/parser html/track html/canvas`, and read every frame that touches parser state
   (`m_treeBuilder`, `m_preloadScanner`, `m_input`, `m_scriptRunner`) after the sink. The free there is the
   parser or the `PendingScript`, both owned by `Document`/the element; the first candidate to read is
   `HTMLScriptRunner::execute` and its `PendingScript` (freed by `document.write()`/`remove()` from the
   script itself). Verification is the same shape as here: a page under `run_nq.sh`, quarantine off, scored
   from the beacon log.
2. Then `style/` (the GOAL's own suggestion): rule-mutation frames holding a raw `StyleRule*` across
   `RuleMutationScope`, where `didMutateRules()` can reach `CSSFontSelector::buildCompleted()` — i.e. the
   same free site as `docs/65` but reached from CSSOM rather than from a getter. `StyleSheetContents` holds
   its rules as `Ref<StyleRuleBase>`, so read for a frame that keeps the raw pointer *outside* that vector.

## Reproducing

```sh
python3 tools/pattern-sweep.py html > /tmp/audit_html.json
python3 tools/pattern-sweep.py html/canvas html/forms html/parser html/shadow html/track > /tmp/audit_html_sub.json
cd research/html-pattern && ./run-page.sh 9731 "k=val&wipe=0" V0   # and V1 / P0
```

Logs and beacon captures: `data/html-pattern/V0.txt`, `V1.txt`, `P0.txt` (+ `run_*.raw.log`), page md5
`data/html-pattern/page.md5`.
