# The direct-JSC script-entry class, whole tree

GOAL action (2026-10-29), the last un-swept script-entry class. `docs/70` recorded that
`tools/pattern-sweep.py`'s `NAMES` cannot see `JSC::call`/`JSC::evaluate` and only `html/` was ever re-run with
those names (`docs/71`); `docs/74` swept `resolve(<DOM object>)` only. This doc covers calls that enter
JavaScript **directly** — the engine bridge, the DOM callback dispatchers, the script controllers, the microtask
checkpoints and the worklet constructors — instead of through an event dispatch or a promise settlement.

Short answer: **10,035 files, 342 calls in the sink list, 83 synchronous (20 header declarations, 63 `.cpp` call
sites in 54 functions), 42 of those 63 with a statement after the call in the same frame, 259 deferred
(`queueMicrotask`/`queueTask`, which cannot run in the calling frame), 0 rows with a reachable free.** Two families
were measured, and both produced a new structural fact rather than a primitive: the XML parser's
custom-element window (`xml/parser/`, never audited before) is a real script window, but its raw
`ContainerNode* m_currentNode` is **refcounted by hand** (`pushCurrentNode` calls `n->ref()`), so removing the node
from the tree cannot free it; and `EventLoop::run()`'s tail runs on a **per-agent-cluster singleton** that every
document in the cluster keeps alive, so it cannot be freed by destroying one document.

## Method

```sh
cd /Users/<user>/Documents/ps5-bootchain
python3 tools/script-sweep.py > data/script-sweep/rows.json   # new tool, docs/75
```

`tools/script-sweep.py` walks every `.cpp` and `.h` under `Source/WebCore` recursively, strips comments and string
literals, enumerates function bodies by brace matching, and for every call matching one of these names emits file,
enclosing function, line, the raw argument/capture list, and the statements that follow inside the same function
body (continuing past the block that contained the call):

- **sync** — `JSC::call`, `JSC::evaluate`, `JSC::profiledCall`, `JSC::profiledEvaluate`, `JSC::construct`,
  `JSExecState::call|evaluate|profiledCall|profiledEvaluate|runTask|loadModule|linkAndEvaluateModule`,
  `executeScriptInWorld*`, `executeScriptIgnoringException`, `evaluateScriptInExtensionTab`,
  `evaluateModule`, `linkAndEvaluateModule`, `performMicrotaskCheckpoint`;
- **defer** — `queueMicrotask`, `queueMicrotaskToEventLoop`, `queueTask`, `queueTaskKeepingObjectAlive`.

```text
files 10035   hits 342   sync 83 (20 in headers, 63 in .cpp)   defer 259   sync rows with a tail 42
```

The 63 `.cpp` `sync` rows by directory: `bindings/` 34, `html/` 9, `workers/` 9, `dom/` 5, `testing/` 2,
`Modules/` 1, `animation/` 1, `loader/` 1, `xml/` 1. The `defer` rows live in 102 files and are not windows by construction:
`EventLoop::queueMicrotask` appends to the microtask queue
(`dom/EventLoop.cpp:43-47`, `microtaskQueue().append` at `:46`) and `EventLoop::queueTask` appends to
`EventLoop::m_tasks` (`:34-40`); both run only
when the loop next runs, never inside the caller.

## Why a synchronous JSC call is a window, and a bigger one than it looks

The dividing line is not the call itself but the destructor of `JSExecState`:

```text
bindings/js/JSExecState.h:150    ~JSExecState()
bindings/js/JSExecState.h:157        bool didExitJavaScript = lexicalGlobalObject && !m_previousState;
bindings/js/JSExecState.h:161        if (didExitJavaScript) {
bindings/js/JSExecState.h:162            didLeaveScriptContext(lexicalGlobalObject);
bindings/js/JSExecState.cpp:36   void JSExecState::didLeaveScriptContext(JSC::JSGlobalObject* lexicalGlobalObject)
bindings/js/JSExecState.cpp:41       context->eventLoop().performMicrotaskCheckpoint();
```

`JSExecState currentState(...)` is constructed inside `JSExecState::call`/`profiledCall`/`evaluate`. If the call
came from C++ (no JS on the stack), `m_previousState` is null, so **the destructor drains the microtask queue before
the C++ caller regains control**. Every `JSC::call`/`JSExecState::call` in this drop therefore has
script-run-again semantics for its tail even if the called function queues a microtask and returns: the microtask
drains inside the bridge, not after the tail. The same is true of the explicit `performMicrotaskCheckpoint` rows,
which drain the queue synchronously (`dom/Microtasks.cpp:51-107`).

## The rows, read

`sync` rows that are not post-script uses are listed first, because they define the surface rather than a candidate:
**20 rows are in headers** (4 engine bridges with bodies, 2 template function definitions, 14 declarations), and
**7 engine-bridge rows** are the window itself (`JSExecState.h:59/72/91/104`, `JSExecState.cpp:41/46/51` — their
tails are `scope.assertNoExceptionExceptTermination()`, which touches the VM only).

| # | site | what runs script | what the tail uses | free reachable? |
|---|------|------------------|--------------------|-----------------|
| 1 | `bindings/js/JSEventListener.cpp:224` `handleEvent` | `profiledCall` on the listener function | `event.target()`, `m_isAttribute`, `scriptExecutionContext` | no — the dispatcher holds `Ref<EventListener>` and `Event` holds `RefPtr<EventTarget> m_target` (`dom/Event.h:194`), cleared only in `initEvent`; docs/73 |
| 2 | `bindings/js/JSErrorHandler.cpp:113` | `profiledCall` on `onerror` | `event`, `savedEvent`, `jsFunctionWindow` | no — `Ref<JSErrorHandler> protectedThis(*this)` at `:85` |
| 3 | `bindings/js/JSCallbackData.cpp:92` `invokeCallback` | `profiledCall` on the callback | `InspectorInstrumentation::didCallFunction(context)` | no — `FAST_RETURN_IF_NO_FRONTENDS` (`inspector/InspectorInstrumentation.h:1726`); nothing of `this` is used |
| 4 | `bindings/js/JSCustomElementInterface.cpp:305` `invokeCallback` | `JSExecState::call` on the reaction callback | `InspectorInstrumentation::didCallFunction`, `reportException(callback->globalObject(), …)` | no — `Ref<JSCustomElementInterface> protectedThis(*this)` at `:284`; `callback` is held by the interface's `WriteBarrier` |
| 5 | `bindings/js/JSCustomElementInterface.cpp:156` `constructCustomElementSynchronously` | `construct` at `:143`, then `performMicrotaskCheckpoint()` at `:156` | `newElement` (`JSValue`), `wrappedElement`, `document` | no — `document` is the caller's `Document&`; a raw `JSValue` in a stack slot is a GC root here (see "conservative scan" below) |
| 6 | `bindings/js/JSDOMMicrotask.cpp:88` `run` | `profiledCall` on the microtask job | `returnedException`, `globalObject->hasDebugger()` | no — `job` is `m_job.get()`, a `WriteBarrier`-held object on the microtask itself |
| 7 | `bindings/js/JSDOMBuiltinConstructor.h:103` `construct` | `JSC::call` on the initialize function | `return JSC::JSValue::encode(jsObject)` | no — `jsObject` is a freshly allocated wrapper held only by a stack local; conservative scan roots it |
| 8 | `bindings/js/JSNavigatorCustom.cpp:57` `getUserMedia` | `JSC::call` on the builtin shim | `return jsUndefined()` | no — nothing used after |
| 9 | `bindings/js/JSDOMIterator.h:224` `iteratorForEach` | `JSC::call` on the callback | `scope.exception()`, loop continues into `iterator.next()` | no — `arguments.append(&thisObject)` in the still-live `MarkedArgumentBuffer` roots the wrapper; `iterator` is a stack object |
| 10 | `bindings/js/JSDOMSetLike.cpp:65/79/99/118`, `JSDOMMapLike.cpp:60/76/97/116` | builtin `JSC::call` | — (`n_after=0`) | no — no statement follows |
| 11 | `bindings/js/ScheduledAction.cpp:119` `executeFunctionInContext` | `profiledCall` on the scheduled function | `catchScope`, `InspectorInstrumentation`, `reportException` | no — nothing of `this`/`m_function` is used after; the action is owned by its caller |
| 12 | `bindings/js/ScheduledAction.cpp:141` `execute` | `executeScriptInWorldIgnoringException` | — (`n_after=0`) | no |
| 13 | `bindings/js/ScriptController.cpp:156` `evaluateInWorld` | `profiledEvaluate` | `reportException`, `returnValue` | no — `Ref protector { m_frame }` at `:150` |
| 14 | `bindings/js/ScriptController.cpp:676/694` `callInWorld` | `profiledEvaluate`, then `profiledCall` | `InspectorInstrumentation`, `reportException` | no — `Ref protector { m_frame }` at `:667`; arguments are in `markedArguments` |
| 15 | `bindings/js/ScriptController.cpp:185/201` `loadModuleScriptInWorld` | `JSExecState::loadModule` | `setupModuleScriptHandlers(moduleScript, promise, world)` | no — `moduleScript` is the caller's `LoadableModuleScript&`, `world` the caller's |
| 16 | `bindings/js/ScriptController.cpp:223` `linkAndEvaluateModuleScriptInWorld` | `JSExecState::linkAndEvaluateModule` | `reportException(&lexicalGlobalObject, …)` | no — `Ref protectedFrame { m_frame }` at `:220` |
| 17 | `bindings/js/ScriptController.cpp:830` `executeJavaScriptURL` | `executeScriptIgnoringException` | `RELEASE_ASSERT(&vm == &jsWindowProxy(...).window()->vm())` | no — reads the VM, not a DOM object |
| 18 | `bindings/js/ScriptModuleLoader.cpp:285/289` `evaluate` | `evaluateModule` (tail call) | `jsUndefined()` | no — `RELEASE_AND_RETURN`, no post-use |
| 19 | `animation/DocumentTimelinesController.cpp:181` `updateAnimationsAndSendEvents` | `performMicrotaskCheckpoint` | `timelinesToUpdate`, `protectedTimelines`, `m_document` | no — every element used afterwards is in a `Vector<Ref<…>>` (`:98`, `:109-111`), and `Ref { m_document }` spans the call |
| 20 | `dom/Document.cpp:6469` `finishedParsing` | `performMicrotaskCheckpoint` | `dispatchEvent(DOMContentLoaded)`, `m_eventTiming`, `frame()` | no — `Ref<Document> protectedThis(*this)` at `:6453` |
| 21 | `dom/EventLoop.cpp:126/135` `run` | `microtaskQueue().performMicrotaskCheckpoint()` after `task->execute()` | `m_tasks`, `microtaskQueue()` on `this` | no — `this` is the per-agent-cluster `WindowEventLoop` (see below), measured |
| 22 | `dom/EventLoop.cpp:181` `EventLoopTaskGroup::performMicrotaskCheckpoint` | same | `m_eventLoop` (`WeakPtr`) | no — the deref is null-checked by `WeakPtr` and nothing is used after |
| 23 | `html/parser/HTMLDocumentParser.cpp:229`, `HTMLScriptRunner.cpp:111/246` | `performMicrotaskCheckpoint` | tree builder / pending script | no — docs/71 (parser holds `Ref<HTMLDocumentParser protectedThis>`, `PendingScript` held by the caller) |
| 24 | `html/HTMLMediaElement.cpp:5030/8108/8190/8237/9079` | `JSC::call` on the media-controls script | `m_haveSetUpCaptionContainer`, `m_mediaControlsHost`, `status`/`resultValue` | no — `setupAndCallJS` takes `makePendingActivity(*this)` and `Ref protectedFrame` before the call (`:4974-4976`); `:8190` is also compiled out (`#if !ENABLE(MODERN_MEDIA_CONTROLS)`, and `ENABLE_MODERN_MEDIA_CONTROLS 1` in `cmakeconfig.h:85`) |
| 25 | `html/CustomPaintImage.cpp:116` `doCustomPaint` | `JSC::construct` on the paint class | `callback.handleEvent(thisObject, …)`, `canvas->replayDisplayList` | no — `ENABLE_CSS_PAINTING_API 0` in the ASAN build (`cmakeconfig.h:27`); `canvas` is a `Ref` local |
| 26 | `Modules/webaudio/AudioWorkletGlobalScope.cpp:155` | `JSC::construct` on the processor | `jsDynamicCast`, `m_processors.add`, `jsProcessor->wrapped()` | no — worklet thread, `jsProcessor` is a stack local (conservative scan), `wrapped()` returns a `Ref`-owned object |
| 27 | `workers/WorkerOrWorkletScriptController.cpp:234/287/369/388/406/445/468/541`, `WorkerThread.cpp:170` | `profiledEvaluate`/`loadModule`/`linkAndEvaluateModule`/`performMicrotaskCheckpoint` | `m_globalScope`, `isTerminatingExecution()`, `finishedEvaluatingScript()` | no — worker-only; `m_globalScope` is owned by the thread and `close()` only marks + posts a cleanup task (`workers/WorkerGlobalScope.cpp:297-310`) |
| 28 | `loader/DocumentLoader.cpp:2573` `handleContentFilterDidBlock` | `executeScriptIgnoringException` | `frameLoader()->client().contentFilterDidBlockLoad(...)` | no — content filtering is compiled out (docs/73) |
| 29 | `testing/Internals.cpp:4089/5348` | `executeScriptInWorld…`, `JSC::call` | — | no — `Internals`, not page-reachable |
| 30 | `xml/parser/XMLDocumentParserLibxml2.cpp:822` `startElementNs` | `performMicrotaskCheckpoint` | 16 statements, first `customElementReactionStack.emplace(...)` | **no — measured, see below** |

Two structural guards account for most of the "no" column and are new to this doc:

**Conservative stack scanning is a GC marking constraint in this drop.** A raw `JSValue`/`JSObject*` in a C++ stack
slot or callee-saved register is a root:

```text
Source/JavaScriptCore/heap/Heap.cpp:2841   "Cs", "Conservative Scan"
Source/JavaScriptCore/heap/Heap.cpp:2860       gatherStackRoots(conservativeRoots);
Source/JavaScriptCore/heap/MachineStackMarker.cpp:39  void MachineThreads::gatherFromCurrentThread(...)
MachineStackMarker.cpp:44      conservativeRoots.add(registersBegin, registersEnd, …);
MachineStackMarker.cpp:47      conservativeRoots.add(currentThreadState.stackTop, currentThreadState.stackOrigin, …);
MachineStackMarker.cpp:202 void MachineThreads::gatherConservativeRoots(…, CurrentThreadState* currentThreadState, …)
```

So `JSDOMBuiltinConstructor<JSClass>::construct` (`jsObject` → `encode(jsObject)` after a `JSC::call`) and
`constructCustomElementSynchronously` (`newElement` → `toWrapped` after a `performMicrotaskCheckpoint`) are safe for
the same reason a `Protect<>` would make them safe — the cell is reachable from the stack, so the wrapper cannot be
collected and the `Ref<ImplementationClass>` inside it keeps the WebCore object alive. **A raw `JSValue` local across
a script window is not, by itself, a UAF in this drop.**

*(The check that matters here is allocator-level, and it holds: `cmakeconfig.h:200 #define USE_ISO_MALLOC 1` and
`:211 #define USE_SYSTEM_MALLOC 1`, and `wtf/IsoMalloc.h:31` makes `WTF_MAKE_ISO_ALLOCATED` degrade to
`WTF_MAKE_FAST_ALLOCATED` when `USE(SYSTEM_MALLOC)` — so `Node`, `Element`, `SVGElement` are plain `fastMalloc` and
ASAN sees their frees.)*

## Measured 1 — the XML parser's custom-element window (`xml/parser/`)

This directory was never audited: `docs/69` covered `css/`+`dom/`, `docs/70` `html/`, `docs/71` `html/parser`,
`docs/72` `style/`+CSSOM, `docs/73` `page/`+`loader/`, `docs/74` only promise settlements. It has one script window
that its HTML twin does not have in the same shape:

```text
xml/parser/XMLDocumentParserLibxml2.cpp:820    if (UNLIKELY(willConstructCustomElement)) {
XMLDocumentParserLibxml2.cpp:821        markupInsertionCountIncrementer.emplace(m_currentNode->document());
XMLDocumentParserLibxml2.cpp:822        m_currentNode->document().eventLoop().performMicrotaskCheckpoint();
XMLDocumentParserLibxml2.cpp:823        customElementReactionStack.emplace(m_currentNode->document().globalObject());
                                             }
XMLDocumentParserLibxml2.cpp:826    auto newElement = m_currentNode->document().createElement(qName, true);
XMLDocumentParserLibxml2.cpp:843        customElementReactionStack.reset();      // <- runs the custom element constructor
XMLDocumentParserLibxml2.cpp:858        if (!m_currentNode || newElement->parentNode() || &newElement->document() != &m_currentNode->document()) {
XMLDocumentParserLibxml2.cpp:869    m_currentNode->parserAppendChild(newElement);
XMLDocumentParserLibxml2.cpp:870    if (!m_currentNode) // Synchronous DOM events may have removed the current node.
```

`m_currentNode` is a raw `ContainerNode*` (`xml/parser/XMLDocumentParser.h:162`), and the code's own comment at
`:845-857` says the drained constructor "may have re-parented newElement, adopted it into another document, or
detached the current parser node" — the null check at `:858` cannot see a *freed* node. Reachability is real:
`XMLDocumentParser` is what `Document::createParser()` returns for a non-HTML document
(`dom/Document.cpp:2938-2942`), `CustomElementRegistry::findInterface(const QualifiedName&)` matches any
XHTML-namespace name (`dom/CustomElementRegistry.cpp:107-112`), and an SVG document executes `<script>` while it is
being parsed (`XMLDocumentParserLibxml2.cpp:939`, `:945`), so a page can define the element before the parser reaches
it.

Page `research/script-sweep/xml-ce.svg`, served as `image/svg+xml` top-level, knobs `reg=0|1`,
`atk=none|rm|rmgc|gc|wipe|wipeg|wipespray|wref`, `n`, `cnt`. The page changed between arms, so each arm carries its
md5: `a9d4f76d714aaa09ec74005515aff91a` for `R0`-`R4`, `80e0870270241f77c7c52383cb0fb023` for the first `R5`,
`1dd8463d7529c26330daa99ac2b56fce` for `R1`/`R5`/`R6`, `ec08c8e917c194e9498445321e0b8b25` for `R7`, and
`9ae0efff7ba4a5aa2cf16955cccc5a84` for `S0`-`S3`. `xml-ce-div.svg` (the XHTML `<div>` twin, md5
`724e78db9ffcc1cdd311be18de9adaea`) differs from `xml-ce.svg` only in the element that contains `<x-a>`. Logs:
`data/script-sweep/run_R*.log`, `run_S*.log`, `run_E*.log` and the beacon server logs `data/script-sweep/srv97*.log`.

```sh
scp research/script-sweep/xml-ce.svg research/script-sweep/xml-ce-div.svg research/script-sweep/xce_runs.sh \
    teo@<lab-ip>:/tmp/
ssh teo@<lab-ip> 'cp /tmp/xml-ce*.svg /tmp/wkp/ && distrobox enter wk -- bash /tmp/xce_runs.sh'
```

| run | page / query | sanitizer | beacons |
|-----|--------------|-----------|---------|
| `R0` | `xml-ce.svg?reg=0&atk=none` | `access: none` | `START reg=false atk=none root=svg` · `TAIL g=true xa=1 xaparent=g` |
| `R1` | `xml-ce.svg?reg=1&atk=none` | `access: none` | `START reg=true …` · `DEF ok` · **`CTOR atk=none`** · `CTOR done` · `TAIL g=true xa=1 xaparent=g` · `LATE root=yes g=1 xa=1 text=1` |
| `R6` | `xml-ce.svg?reg=1&atk=wipeg` | `access: none` | `WIPEG before kids=4` · `WIPEG after kids=0 doc=yes` · `CTOR done` · `TAIL g=false xa=0` · `LATE root=yes g=0 xa=0 text=1` |
| `R8` | `xml-ce-div.svg?reg=1&atk=wipeg` | `access: none` | same as `R6` with an XHTML `<div>` as the current node |
| `R5` | `xml-ce.svg?reg=1&atk=wipe` | `access: none` | `WIPE before kids=2` · `WIPE after kids=0 root=no` · `CTOR done` · `LATE root=no …` (**no `TAIL`**) |
| `R2` | `xml-ce.svg?reg=1&atk=rm` | `access: none` | `RM found=true gone=true` · `CTOR done` · `TAIL g=false xa=0` |
| `R3` | `xml-ce.svg?reg=1&atk=rmgc` | `access: none` | `RM found=true gone=true` · `ALLOC i=0/50000/…` · `ALLOC done n=200000` · `CTOR done` · `TAIL g=false xa=0` |
| `R4` | `xml-ce.svg?reg=1&atk=gc` | `access: none` | `ALLOC done n=200000` · `TAIL g=true xa=1 xaparent=g` |
| `S0`-`S3` | `xml-ce.svg?reg=1&atk=wipespray&n=208/240/272` (quarantine off, `run_nq.sh`) | `access: none` | `SPRAY n=… cnt=4000 len=…` · `TAIL g=false xa=0` in all three |
| `R7` | `xml-ce.svg?reg=1&atk=wref` | `access: none` | `WREF armed` · `WREF alloc done` · `WREF later alive=no` |

Four facts:

1. **The window is real and sits inside the XML parser's own frame.** `R1` prints `CTOR` *before* `TAIL` (the beacon
   of the `<script>` element parsed after `<x-a>`), and `R0` never prints it. The constructor is entered from
   `customElementReactionStack.reset()` at `:856`, i.e. between `createElement` and the null check at `:858`.
2. **Removing the current node from its parent does not free it.** `R6`: `<svg>`'s children are gone
   (`WIPEG after kids=0`), yet the parser continues, appends `<x-a>` into the detached node and reaches the trailing
   script (`TAIL`, `LATE … text=1`). Same with an XHTML `<div>` (`R8`), so it is not an SVG-class effect. No
   sanitizer report in either, with quarantine on.
3. **The spray cannot take the slot either.** `S1`-`S3` fill three size classes with 4,000 8-bit `StringImpl`s right
   after the removal, with quarantine **off** so a freed chunk is actually reusable — the parser's decision does not
   change in any of the three. A reclaim that never happens is not a reclaim.
4. **The reason is in the source, and it is a guard no sweep can see from the call site:** `pushCurrentNode` refs
   the node by hand and only `popCurrentNode`/`clearCurrentNodeStack` release it.

```text
xml/parser/XMLDocumentParser.cpp:66   void XMLDocumentParser::pushCurrentNode(ContainerNode* n)
XMLDocumentParser.cpp:70       if (n != document())
XMLDocumentParser.cpp:71           n->ref();
XMLDocumentParser.cpp:78   void XMLDocumentParser::popCurrentNode()
XMLDocumentParser.cpp:84       if (m_currentNode != document())
XMLDocumentParser.cpp:85           m_currentNode->deref();
XMLDocumentParser.cpp:92   void XMLDocumentParser::clearCurrentNodeStack()
```

So `m_currentNode` is a raw pointer **with a matching `ref()`**, held until the element's `endElementNs`. This is the
same shape as `JSDOMWrapper::m_wrapped` (docs/70) and `Event::m_target` (docs/73), implemented by hand instead of with
a smart pointer, and it means a `ContainerNode*` member is not evidence of an unowned object. `R5` (whole-document
wipe) prints no `TAIL`, but that arm cannot distinguish a free from the simpler explanation that the trailing
`<script>` element was removed from the document before it was parsed; facts 2 and 3 already show that removal alone
does not free the node, so nothing is claimed from `R5`.

## Measured 2 — `EventLoop::run()`'s tail (`dom/`)

`EventLoop::run` is the only place in `dom/` where the engine touches a member immediately after arbitrary task code:

```text
dom/EventLoop.cpp:124            task->execute();
dom/EventLoop.cpp:125            didPerformMicrotaskCheckpoint = true;
dom/EventLoop.cpp:126            microtaskQueue().performMicrotaskCheckpoint();
```

A task is arbitrary script (timer, message, observer delivery). The object the tail runs on is a
`WindowEventLoop` — a per-agent-cluster singleton:

```text
dom/WindowEventLoop.cpp:66   Ref<WindowEventLoop> WindowEventLoop::eventLoopForSecurityOrigin(const SecurityOrigin& origin)
WindowEventLoop.cpp:72           auto addResult = windowEventLoopMap().add(key, nullptr);
WindowEventLoop.cpp:75           addResult.iterator->value = newEventLoop.ptr();
dom/Document.h:2180          RefPtr<WindowEventLoop> m_eventLoop;
```

The static map holds a *raw* pointer; the loop is kept alive by the `RefPtr` each document in the cluster holds. So
the tail is only dangerous if a task can destroy the last document of the cluster. Page
`research/script-sweep/evloop.html` (md5 `4a6c35bdd7350c9fe60b702ba1a19dc0`) + `child.html` (md5
`71ff2c3dd8f2253d1721d6b089dd45f1`): a same-origin iframe whose own `setTimeout` task reads `frameElement` and
removes it (`rm=1`) or does not (`rm=0`), with parent-side beacons at 500 ms and 1500 ms as the liveness witness.

| run | query | sanitizer | beacons |
|-----|-------|-----------|---------|
| `E1` | `evloop.html?rm=1` | `access: none` | `PARENT start rm=1` · `CHILD start rm=true` · `PARENT alive fe=no` · `PARENT late` |
| `E2` | `evloop.html?rm=1` | `access: none` | `PARENT start rm=1` · `CHILD start rm=true` · `TASK start` · `PARENT alive fe=no` · `PARENT late` |

The parent's 500 ms and 1500 ms beacons still fire after the child removed itself, and no sanitizer report exists in
either run: the loop survives, because the parent document is in the same agent cluster and holds its own `RefPtr`.
The last-document case cannot be arranged from script either: a unique-origin (sandboxed) child would own a private
loop (`eventLoopForSecurityOrigin` returns `create({})` when the cluster key is null), but its `frameElement` getter
is `[CheckSecurityForNode]` (`page/LocalDOMWindow.idl:75`) and throws, so it cannot remove its own frame. The
`<script>`-side beacons inside the child are unreliable by construction here — a document that dies immediately after
`remove()` cancels the image request that would have carried the beacon — which is why the parent beacons are the
witness and the `TASK start` line differs between `E1` and `E2`.

## Verdict count

83 `sync` rows: 20 in headers (4 engine bridges, 2 template definitions, 14 declarations) and 63 `.cpp` rows (3
engine bridges, 60 call sites in 54 functions) in `bindings/`, `dom/`, `html/`, `workers/`, `animation/`, `xml/`,
`loader/`, `Modules/` and `testing/`. 42 of the 63 have a tail statement. **0 have a reachable
free.** Two rows were measured end to end (`docs/75` Measured 1 and 2); three rows are compiled out of the ASAN build
(`CSS_PAINTING_API 0`, `MODERN_MEDIA_CONTROLS 1` for the legacy media path, content filtering); the rest are guarded
by a `Ref`/`RefPtr` local, `makePendingActivity`, the dispatcher's `Ref<EventListener>` + `Event::m_target`, the
conservative stack scan, or (workers) a context that cannot be destroyed synchronously. With `docs/69`-`74`, this
closes the script-window search for this drop: every window is an event dispatch, an observer callback, a
`resolve(<DOM object>)`, or a direct JSC call, and every one of them has a named owner that survives the window.

## What is left

Two leads, in order:

1. **The console (blocked on the operator).** The `docs/65` "Attempt 9" flip
   (`mode=none&npre=0&npost=0&quiet=2&doc=zzd&docn=2`, page md5 `f0d1b337aaad040b5f1824a162295759`) needs no JS
   allocation in the window and no sanitizer, so it is the one heap-shaping oracle that can run on hardware. The
   Guide app has to be restarted by hand first; until then nothing on-console can run.
2. **`CachedString` (`docs/62`/`63`) with the `docs/65` reclaim method.** It is the only other *live* memory-safety
   defect in the drop (`docs/67` row KNOWN), and it was never revisited after the atob/StringImpl technique was
   calibrated. Unlike the font-face bug its stale reference is not protected by a hand-rolled `ref()`, so the
   `+0x87`-style ownership witness should be tried there next.
