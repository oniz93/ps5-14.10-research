# docs/77 — the `CachedString` *shape*, swept whole-tree: 147 raw member rows, one unprotected site, and the window that looked real

The action (`GOAL.md`, first item): docs/76 closed the one `CachedString` instance and showed that a raw `JSValue`
member of a heap C++ object is the only way this drop frees a JSCell from plain JavaScript. Sweep
`Source/WebCore` + `Source/JavaScriptCore` for members and locals of type `JSValue`, `JSCell*`,
`Vector<JSValue>`/`Vector<JSCell*>` that are **not** `MarkedVector`, `MarkedArgumentBuffer`, `Strong<>`,
`WriteBarrier` or `Protect`, inside functions that can reach an allocation, a getter, a `resolve(` or a JSC call
between the store and the load, and decide per site whether a GC can land in that gap.

This is that sweep. Two results worth the run:

1. **There is exactly one unprotected heap-stored raw cell field in WebCore that a page can reach, and it is the
   one docs/76 already closed** (`CachedString::m_jsString`). The other heap-stored ones are behind build flags —
   measured absent below (`ShadowRealm`, `CSS.paintWorklet`, `navigator.xr`, `window.internals`).
2. **The strongest new candidate — `CloneSerializer`'s `Vector<JSObject*, 32> inputObjectStack` — has a real
   window** (script runs with 33+ entries in a heap-allocated array, and a GC demonstrably runs there), **and it
   is still safe**, for a reason the type of the field does not show: every object it walks has already been
   appended to `CloneBase::m_objectPool`, a `MarkedArgumentBuffer`. Measured with a GC probe that proves the
   collection happened inside the serialization (`gcprobe … collected` at eight depths) and a clone that still
   reads every level correctly (`bad=0`).

## 1. The tool and what it counts

`tools/jsvalue-sweep.py` (new). It strips comments/strings, finds every declaration of a raw cell type
(`JSValue`, `JSCell`, `JSObject`, `JSString`, `JSFunction`, `JSArray`, `JSGlobalObject`, `JSModuleLoader`,
`JSInternalPromise`, `JSPromise`), drops function signatures, base-class lists, `typedef`s and `static constexpr`,
and classifies each survivor as `member` (class/struct body depth), `local` (inside a function body) or `param`
(inside a parenthesis, i.e. a parameter list). For members it also records whether an owner-side marking line
mentions the field (`visitor.append*(…)` / `visitor.visit*(…)` in the class's own `.h`/`.cpp`).

```
$ python3 tools/jsvalue-sweep.py > data/jsvalue-sweep/inventory.json && python3 -c \
  'import json; d=json.load(open("data/jsvalue-sweep/inventory.json")); print(d["total"], d["members"]); print(d["counts"])'
15453 147
{"JavaScriptCore/local": 3420, "JavaScriptCore/member": 116, "JavaScriptCore/param": 7265,
 "JavaScriptCore/unknown": 5, "WebCore/local": 508, "WebCore/member": 31, "WebCore/param": 4108}
```

10,035 `WebCore` files + 2,942 `JavaScriptCore` files, 15,453 declarations matched, 147 of them members. Owner-side
marking: `JavaScriptCore` 33 marked / 83 not, `WebCore` 1 marked / 30 not.

**What the split means.** A raw cell in a *local* is a root in this drop: docs/75 measured that conservative stack
scanning is a marking constraint here (`Heap.cpp:2841` "Cs", `MachineStackMarker.cpp:39-48`, `:202`), so the whole
C++ stack range is scanned. That makes the 508 `WebCore` and 3,420 `JavaScriptCore` locals uninteresting **as
storage** — and it is why this sweep does not re-audit the script windows of docs/69-75. The dangerous storage is
the member: a field of a heap object is scanned only if its owner is a GC cell whose `visitChildren` visits it, and
a `MarkedArgumentBuffer`/`MarkedVector` is scanned because it registers itself with the VM. A raw field of a plain
C++ object is scanned by nobody.

## 2. WebCore — every member row, one at a time

31 rows from the tool, plus one template row the tool's declarator regex cannot see
(`testing/WebXRTest.h:50-51`, `std::optional<Vector<JSC::JSValue>>`). The table is the whole tree: WebCore has no
other raw-cell member.

| # | file:line | owner → field | storage | reads after a window? | verdict |
|---|---|---|---|---|---|
| 1 | `bindings/js/SerializedScriptValue.cpp:2836` | `CachedString::m_jsString` | heap: element of `Vector<CachedString> m_constantPool` | yes — `jsString()` re-resolves a pooled string | **the known bug; closed in docs/76** (the cache is not in `m_objectPool`) |
| 2 | `bindings/js/JSValueInWrappedObject.h:55` | `JSValueInWrappedObject::m_nonCell` | heap, but cells go to `Weak<JSCell> m_cell` | no cell can be stored | safe by construction (`setWeakly`: `if (!value.isCell()) … else m_nonCell = { }`) |
| 3 | `bindings/js/JSEventTargetCustom.h:52` | `JSEventTargetWrapper::m_wrapper` | stack (`IDLOperation::call` builds it) | no | conservative root |
| 4 | `bindings/js/ScriptModuleLoader.h:80` | `ScriptModuleLoader::m_shadowRealmGlobal` | **heap** (`WTF_MAKE_FAST_ALLOCATED`), raw `JSGlobalObject*` | yes — `:281` `moduleRecord->evaluate(m_shadowRealmGlobal, …)` | **unreachable: `ShadowRealm` is not in this build** (§5) |
| 5 | `platform/ThreadGlobalData.h:121` | `ThreadGlobalData::m_currentState` | thread-local, set/restored by `JSExecState` RAII (`JSExecState.h:157-210`) | only while a `JSExecState` is live | stack-scoped by construction |
| 6 | `inspector/InspectorFrontendHost.cpp:148` | `FrontendMenuProvider::m_globalObject` | heap | inspector frontend only | not reachable from page script; global alive |
| 7 | `bridge/objc/objc_instance.mm:70` | `s_exceptionEnvironment` (static) | static | ObjC bridge | not in the PlayStation source list (no `bridge/objc` entry in `WebCore/CMakeLists.txt`; the ObjC bridge comes in with the Apple includes) |
| 8 | `worklets/PaintWorkletGlobalScope.h:58` | `PaintDefinition::paintConstructor` | **heap** (`PaintDefinition` in the scope's map) | yes — `paint()` calls the constructor | **unreachable: `ENABLE_CSS_PAINTING_API` is `ENABLE_EXPERIMENTAL_FEATURES` (OFF), measured `CSS.paintWorklet === undefined`** (§5) |
| 9 | `testing/WebXRTest.h:50-51` | `Vector<JSC::JSValue>` ×2 | heap, in `FakeXRDeviceInit` | parsed by `WebXRTest.cpp:43` | **unreachable: `ENABLE_WEBXR` OFF *and* behind `Internals`** (§5) |
| 10 | `bindings/js/SerializedScriptValue.cpp:898` | `CloneBase::m_lexicalGlobalObject` | heap (the serializer/deserializer object) | yes | the page's global object; alive while its context lives |
| 11 | `bindings/js/SerializedScriptValue.cpp:4772` | `CloneDeserializer::m_globalObject` | heap | yes | same |
| 12 | `dom/CustomElementReactionQueue.h:238` | `CustomElementReactionStack::m_state` | stack — every use is a local (`Range.cpp:332`, `HTMLDocumentParser.cpp:231`, the generated bindings) | yes, inside the stack object's lifetime | conservative root |
| 13 | `bindings/js/JSLazyEventListener.cpp:50` | `CreationArguments::wrapper` | stack struct, passed by rvalue into `create()` | no | conservative root |
| 14-15 | `bindings/js/JSExecState.h:187`, `:214` | `m_previousState` ×2 | stack RAII | no | conservative root |
| 16 | `bindings/js/JSDOMGlobalObject.cpp:780` | `GetCallerGlobalObjectFunctor::m_globalObject` | stack functor | no | conservative root |
| 17 | `dom/MessageEvent.h:65`, `dom/CustomEvent.h:43`, `dom/PopStateEvent.h:44`, `dom/PromiseRejectionEvent.h:40`, `dom/ErrorEvent.h:60`, `workers/service/ExtendableMessageEvent.h:54`, `Modules/notifications/Notification.h:70`, `Modules/fetch/FetchRequestInit.h:50`, `:52`, `page/PerformanceMarkOptions.h:34`, `page/PerformanceMeasureOptions.h:35` | 11 `Init`/`Options` structs with a `JSC::JSValue` field | stack: the generated bindings build `auto init = X::Init { }` on the frame and convert each field | no | conservative roots |
| 18 | `Modules/streams/TransformStream.cpp:40` | `CreateInternalTransformStreamResult::transform` | stack (returned by value) | no | conservative root |
| 19-21 | `bindings/js/JSDOMPromiseDeferred.h:76`, `:118`, `:152`, `bindings/js/JSDOMGlobalObjectInlines.h:53` | `lexicalGlobalObject` / `constructor` | locals the tool misclassified as members (function-body braces) | no | conservative roots |

Count over the 32 rows: **1 known bug, 3 heap-stored-but-gated, 1 safe by construction (`m_nonCell`), 2 globals that
outlive the window, 1 inspector-only, 1 not in the PlayStation build, 23 stack temporaries.** Nothing new is
reachable.

## 3. The window that looked real: `CloneSerializer::inputObjectStack`

### 3.1 The shape, from the drop

`SerializedScriptValue.cpp:2493-2505`:

```cpp
SerializationReturnCode CloneSerializer::serialize(JSValue in)
{
    VM& vm = m_lexicalGlobalObject->vm();
    Vector<uint32_t, 16> indexStack;
    Vector<uint32_t, 16> lengthStack;
    Vector<PropertyNameArray, 16> propertyStack;
    Vector<JSObject*, 32> inputObjectStack;      // <-- raw pointers, no keep-alive
    Vector<JSMapIterator*, 4> mapIteratorStack;
    Vector<JSSetIterator*, 4> setIteratorStack;
    Vector<JSValue, 4> mapIteratorValueStack;
```

`inputObjectStack` is a plain `Vector`, and the *inline* capacity 32 is the whole story: up to 32 nested objects the
array lives inside the `Vector` object on the C stack, where the conservative scan sees it; the 33rd `append`
moves it to the heap, where nothing does.

What makes it a window rather than a static array is `getProperty` (`:1197-1203`):

```cpp
JSValue getProperty(JSObject* object, const Identifier& propertyName)
{
    PropertySlot slot(object, PropertySlot::InternalMethodType::Get);
    if (object->methodTable()->getOwnPropertySlot(object, m_lexicalGlobalObject, propertyName, slot))
        return slot.getValue(m_lexicalGlobalObject, propertyName);   // <-- own getter runs here
    return JSValue();
}
```

`PropertySlot::getValue` calls the getter, so `structuredClone(<object with an accessor property>)` executes page
script *inside* the serialization loop, with the ancestors sitting in the vector. That is exactly the
CVE-2026-43715 ordering, moved from the font subsystem to the binder, and it needs no `resolve(` and no event.

The contrast that makes it suspicious: the same function appends the map/set iterators and map values to a
keep-alive buffer (`m_keepAliveBuffer.appendWithCrashOnOverflow(…)` at `:2646`, `:2668`, `:2692`), and the
*deserializer* uses `MarkedVector<JSObject*, 32> outputObjectStack` (`:4830`). The serializer's
`inputObjectStack` does neither.

### 3.2 The oracle

Two beacons, because "no crash" alone cannot be told apart from "no GC":

* **`gcprobe`** — a decoy object held only by a `WeakRef`, deref'd inside the churning getter. `collected` proves a
  GC ran at that point in the serialization. The decoy must be created in a **previous job**: a `WeakRef` target
  is kept alive to the end of the job that created it, so the first version of the probe (same job, arms `A3`/`A4`)
  could only ever print `alive` and was void. That is recorded here as a pitfall, not as a result.
* **`level`** — every level declares `level` *after* `p` in insertion order, so the serializer reads it on the way
  back up, i.e. after the churn, from the very object whose cell the churn would have recycled. A missing `level`
  is the serializer's own `if (!inValue) { // Property was removed during serialisation }` branch (`:2614-2617`).

Page `research/jsvalue-stack/clone-stack.html`, md5 `e52a6f94cb10a83f2c253c163a1998cf`; runner
`research/jsvalue-stack/runs.sh` (md5 `b87fb0e6df4f15dc6bd2dd38c6476b0c`), copied to `/tmp/wkp/`, run **inside the
`wk` distrobox** (the ASAN binary needs its `libasan`), quarantine **off** via `run_nq.sh`, a fresh port per arm.

### 3.3 The arms, one knob each

The four invocations, verbatim (each arm's beacons are below; every arm is the same page, one query string):

```
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=90 /tmp/wkp/runs.sh \
  "A5 8905 n=40&ref=0&churnfrom=32&objs=400000&mb=8"'
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=35 /tmp/wkp/runs.sh \
  "C 8911 n=40&ref=0&churn=0" "E 8912 n=40&ref=0&churnfrom=32&objs=400000&mb=8&del=1"'
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=30 /tmp/wkp/runs.sh \
  "B 8921 n=20&ref=0&churnfrom=10&objs=400000&mb=8" "D 8922 n=40&ref=1&churnfrom=32&objs=400000&mb=8"'
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=25 PAGE=surfaces.html /tmp/wkp/runs.sh "S 8931 v=1"'
```


| arm | `n` | `ref` | `churn` | beacons (verbatim) | verdict |
|---|---|---|---|---|---|
| `A5` | 40 | 0 | from 32, 400k objs + 4×8 MB | `gcprobe 32 collected` … `gcprobe 39 collected`, `churn 32 400004` … `churn 39 3200032`, `done`, `verify depth=40 bad=0 first=-1 got=` | GC ran in the window, clone intact |
| `B` | 20 | 0 | from 10, 400k | `gcprobe 10 collected` … `gcprobe 19 collected`, `done`, `verify depth=20 bad=0 first=-1 got=` | vector stayed **inline**, GC still ran, clone intact |
| `C` | 40 | 0 | 0 | `gcprobe 39 alive`, `done`, `verify depth=40 bad=0 first=-1 got=` | **negative control for the probe**: no allocation, no collection |
| `D` | 40 | 1 | from 32, 400k | `gcprobe 32 … 39 collected`, `done`, `verify depth=40 bad=0 first=-1 got=` | reachability control: the chain is also referenced from `root` |
| `E` | 40 | 0 | from 32, 400k, `del=1` | `gcprobe 32 … 39 collected`, `del 39`, `done`, `verify depth=40 bad=1 first=39 got=undefined` | **oracle sensitivity**: the serializer read `level` after the getter and found it gone |

`A5` in full (arm `A3`/`A4` used 100k objects per churn, where the first probe still read `alive`):

```
   B boot n=40 ref=false churn=1 from=32 mb=8 objs=400000 del=false
   B sc ok
   B built
   B gcprobe 32 collected
   B churn 32 400004
   ...
   B gcprobe 39 collected
   B churn 39 3200032
   B done
   B verify depth=40 bad=0 first=-1 got=
```

So: 40 levels, 41 objects on `inputObjectStack`, entries 32-40 in a heap buffer, eight getters each allocating 400k
objects and 32 MB, a collection proven at every one of them, and the clone comes back with all 40 `level`s.

### 3.4 Why nothing is freed: `m_objectPool` is a `MarkedArgumentBuffer`

`CloneBase` (`:900`) holds

```cpp
MarkedArgumentBuffer m_objectPool;
```

and `addToObjectPool` (`:1163-1172`) appends **every** object it walks:

```cpp
m_objectPoolMap.add(object, m_objectPoolMap.size());
m_objectPool.appendWithCrashOnOverflow(object);
```

`addToObjectPoolIfNotDupe` is called on the object *before* it is pushed on `inputObjectStack`
(`:2578` `addToObjectPoolIfNotDupe<ObjectTag>(inObject)`, then `:2587` `inputObjectStack.append(inObject)`), and
`MarkedArgumentBuffer` is `MarkedVector<JSValue, 8>`: with at most 8 entries the values sit in the object's own
inline buffer (on the C stack, where the conservative scan sees them), and past that the vector registers itself in
`Heap::m_markListSet` (`MarkedVector.h:452-454`) which the marking phase walks (`Heap.cpp:2908-2910`,
`MarkedVectorBase::markLists`). So the heap buffer of `inputObjectStack` holds *duplicates* of pointers
that are already roots. The GC cannot see the vector, but it does not need to: the object pool sees every entry.

That is the structural answer to the whole action: in this file, the keep-alive is not the vector, it is the pool,
and `CachedString` is outside it because strings are not JS objects — they go into `m_constantPool`
(`Vector<CachedString>`) and a `StringPoolTag` index instead, which is exactly the hole docs/76 measured.

**What the arms do not show.** They do not prove that `inputObjectStack` can never hold an object that is not in
`m_objectPool` — the two are appended unconditionally side by side, so they cannot diverge without a code change.
They also do not test the `!inValue` "property removed" branch as an attack, only as an oracle (`E`). No ASAN
report is possible on this path either way: a JSCell lives in a `MarkedBlock`, which ASAN does not instrument, so
a freed-cell read would surface as `reportZappedCellAndCrash` (via `jsCast`, `JSCast.h:33`) or a wild deref, not as
`heap-use-after-free`.

## 4. JavaScriptCore — 116 rows, none page-reachable

The tool marks 33 rows by finding a `visitor.*` line that names the field; the other **83** were read one at a time
and every one of them lands in one of the categories below. A few sit on a boundary (`CallVariant::m_callee` is both
transient and IC-guarded; the DFG value types are both stack-only and JIT-only), so the per-category counts are
approximate and not additive — the exact numbers the tool produced are 33 marked and 83 not, out of 116.

| bucket | rows | what they are |
|---|---|---|
| explicitly marked by the owner's visit (exact, tool) | 33 | `SmallStrings` (18), `ShadowChicken::Packet`/`Frame` (4), `QueuedTask::m_job`/`m_arguments` (2, `MicrotaskQueue::visitAggregateImpl` → `visitor.appendUnbarriered(task.m_job)`, `VM.cpp:1663`), `NumericStrings` caches (2, `clearOnGarbageCollection` + `visitAggregate`), `FunctionPrototype` functor results (2), `SlotVisitor::m_currentCell`, `TypeProfilerLog::LogEntry`, `GetStackTraceFunctor::m_owner` |
| fields of a JSCell whose own `visitChildren` marks them (the tool's check is file-local, so nested structs land here) | 4 | `JSString::CompactFibers` (`JSString::visitChildrenImpl` walks `fiber1`/`fiber2`), `JSFinalizationRegistry::Registration::target` (`visitChildrenImpl` iterates the registration maps), `HandleSet::HandleNode::m_value` (`HandleSet::visitStrongHandles` → `visitor.appendUnbarriered(*node.slot())`) |
| stack temporaries by construction | 45 | `PropertySlot`, `PutPropertySlot`, `PropertyDescriptor`, `IteratorOperations::IterationRecord`, `JSONObject::Stringifier`/`Walker`/`Holder`, `StringRecursionChecker`, `LazyClassStructure::Initializer`, `JSGlobalObject::GlobalPropertyInfo`, `ObjectInitializationScope`, `VMEntryScope`, `EnsureStillAliveScope`, `JSPromise::DeferredData` (`WTF_FORBID_HEAP_ALLOCATION`, returned by value), `JSBigInt::ImplResult`, the DFG/FTL value types (`FrozenValue`, `AbstractValue` — JIT is off on this port) |
| compare-only or key-only, never dereferenced | 5 | `VM::stringRecursionCheckFirstObject` (`==` in `StringRecursionChecker::performCheck`/dtor), `MegamorphicCache::Entry::m_holder` (exported by `offsetOfHolder()`, compared by the IC, no read through it), `PrototypeKey::m_prototype`, `VisitRaceKey::m_cell`, `JITCompilationKey::m_codeBlock` |
| transient, lifetime is the operation itself | 4 | `VM::currentlyDestructingCallbackObject`, `ObjectPropertyChangeAdaptiveWatchpoint::m_owner`, `VariableWriteFireDetail::m_object`, `CallVariant::m_callee` (guarded by the structure check) |
| debugger / inspector only, or JIT-only (this port has no JIT) | 16 | `Debugger::m_currentException`, `JSGlobalObject::m_globalObjectAtDebuggerEntry`, `InjectedScriptBase`, `ScriptFunctionCall`, `InspectorDebuggerAgent::m_pausedGlobalObject`, the three `ScriptCallStackFactory`/`Debugger`/`ScriptProfilingScope` functors |
| weak | 2 | `WeakImpl::m_jsValue`, `JSWeakValue::primitive` |
| IC values guarded by invalidation, not by marking | 6 | `GetByVariant::m_intrinsicFunction`, `InstanceOfVariant::m_prototype`, `GetByIdMetadataProtoLoad::cachedSlot` — each is only used after the structure/property watchpoint that installed it has not fired |

Nothing in this list is both heap-stored, unmarked and reachable from page script: JSC's raw-cell storage is either
inside a GC cell whose `visitChildren` covers it, inside a VM-owned structure with an explicit aggregate visit, or on
the stack.

## 5. The gated surfaces, measured absent

`research/jsvalue-stack/surfaces.html` (md5 `24b82a2989016e833a8a18ebdcace68f`), one quarantine-off run:

```
=== S  surfaces.html?v=1
access: none
EXIT=124
   B sc function
   B shadowrealm undefined in=false
   B paintworklet undefined
   B css object
   B xr undefined
   B internals undefined
   B xrtest undefined
   B done
```

`structuredClone` is the positive control: the same probe machinery sees a real global. `ShadowRealm` is absent
from `globalThis` (`OptionsList.h:580` `v(Bool, useShadowRealm, false, …)`, read only at
`JSGlobalObject.cpp:1355`, and nothing in the tree sets it), `CSS.paintWorklet` is absent
(`ENABLE_CSS_PAINTING_API` = `${ENABLE_EXPERIMENTAL_FEATURES}` in `OptionsPlayStation.cmake:237`, default OFF), and
`navigator.xr` + `window.internals` are both absent (`ENABLE_WEBXR` default OFF and depends on `ENABLE_WEBGL`,
which `OptionsPlayStation.cmake:272` turns off; `WebXRTest` additionally needs `Internals`).

## 6. Verdict counts

* 147 member rows read/classified: **1 unprotected and reachable** (`CachedString::m_jsString`, docs/76),
  **3 heap-stored but compiled out** (ShadowRealm, CSS Painting, WebXR), **1 safe by construction**
  (`JSValueInWrappedObject::m_nonCell`), **2 globals alive by contract**, **5 compare-only/key-only**,
  **~135 stack temporaries or owner-marked fields**.
* 15,301 local/parameter declarations classified as conservative roots (docs/75's rule), not windows.
* 1 real script window with a heap buffer across it (`CloneSerializer::inputObjectStack`), measured with a GC
  inside it, and closed by `m_objectPool` — a structural keep-alive, not the vector's type.

## 7. What this changes

The action's premise — "this shape is the only way this drop frees a JSCell from plain JavaScript" — survives, and
the sweep narrows it to a single site that is already closed. The useful by-products are (a) the `m_objectPool`
rule, which is why the same `Vector<T*>` pattern that is a CVE in one function is inert in the one next to it, and
(b) the `gcprobe` method: a `WeakRef` decoy created in a previous job is a working, sanitizer-free witness that a GC
ran inside a C++ window, which docs/65/76 never had (they inferred the collection from behaviour).

There is nothing left in *this* class to test locally. The nearest neighbour is the same failure in a different
container: a `Vector<X*, N>` **local** that overflows to its heap buffer inside a function that runs script, where
the pointee is *not* separately rooted — the shape `inputObjectStack` would have had if `m_objectPool` were absent.
That is the next action; the console half (the docs/65 "Attempt 9" flip) stays blocked on the operator.
