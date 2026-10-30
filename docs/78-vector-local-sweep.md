# docs/78 — the `Vector<X*, N>` local shape, swept whole-tree: 164 declarations, 93 that can grow, 40 that can cross an inline boundary, and the one page-reachable window is safe for a reason its type does not show

The action (`GOAL.md`, first item): docs/77 closed the raw-JSCell *member* shape and found the one `Vector<T*, N>`
local it could see — `CloneSerializer::inputObjectStack` — inert only because every pointee is also in
`m_objectPool`, a `MarkedArgumentBuffer`. The same shape **without** a separate root is a use-after-free, so sweep
`Source/WebCore` for local `Vector<X*, N>` / `Vector<X>` where X is a GC or DOM object, the vector can grow past
`N` (an unbounded loop, or recursion), and a getter / `resolve(` / event dispatch / JSC call runs between a push
and a later `last()`/index read; decide per site whether the pointee is separately rooted.

This is that sweep, and it produced three things worth the run:

1. **The GC-element population is exactly four declarations in the whole tree**, and all four are closed: three by
   an adjacent one-line keep-alive, one because its gate is (nominally) off — and that last one is *not* off, which
   is the new fact here. `typeof indexedDB` is `object` on this build, so `IDBBindingUtilities::createIDBKeyFromValue`
   is page-reachable: a raw `JSArray*` chain in a `Vector<JSArray*>` with **default capacity 0, i.e. always on the
   heap**, with page script running inside its loop. Measured with the docs/77 GC witness: a collection lands inside
   the walk (`gcprobe h22/h23/h24 collected`) and the key still reads back correctly (`depth=8 bad=0`).
2. **The capacity boundary is inert wherever it exists.** Three of the four GC rows are `Vector<…, 4>` and cross
   their inline capacity at depth 5; a nested `Map`/`Set` clone puts 8 entries in the heap buffer of
   `mapIteratorStack` / `setIteratorStack` / `mapIteratorValueStack`, a GC runs there (`collected` at depth 6 and 7),
   and the clone is still correct — the keep-alive at `:2646`, `:2668`, `:2692` is one line *before* each push.
3. **The refcounted rows are inert for a different reason each time, and the most suspicious one
   (`MutationObserver::deliver`, `Vector<MutationObserverRegistration*, 1>`) is inert by ownership, not by luck**:
   the snapshot holds raw pointers into a `WeakHashSet`, but the objects are owned by per-node
   `Vector<std::unique_ptr<…>>` registries (`Node.cpp:2389`) and the loop's callee removes each registration only
   from its *own* node's weak registry (`Node.cpp:1509-1520`) — and the script callback runs after the snapshot's
   last use.

Nothing in this class is a live bug. The by-product is the funnel and the three blind spots that made it take a
second pass to see the one row that mattered.

## 1. The tool and the funnel

`tools/vector-local-sweep.py` (new). Two passes over `Source/WebCore` — 10,500 `.cpp`/`.mm`/`.h` files:

* **PASS 1** every function body → does it contain a direct script sink (`DISPATCH`, 27 tokens: the `docs/69`-`75`
  families plus `getProperty`/`getOwnPropertySlot` from `docs/77`)? This gives name → *n* definitions / *k* that
  dispatch, so a call in an interval can be resolved one level deep, but only when **every** definition of that name
  dispatches and it has ≤12 of them (without that rule `get`, `begin`, `data`, `write` match 53,595 names and the
  transitivity is meaningless — measured, the first version of this tool reported 14 "windows" of which 13 were
  `RefPtr::get()`).
* **PASS 2** every local `Vector<X*, N>` / `Vector<X*>` / `FixedVector<X*, N>` / `Deque<X*>` whose element is not a
  keeping wrapper (`Ref`, `RefPtr`, `WeakPtr`, `unique_ptr`, `Strong`, `MarkedVector`, `GCReachableRef`), that is
  appended to **inside a `for`/`while`/`do` body or by recursion**, and is read (`.last()`, `.at()`, `[i]`,
  range-for) after that push. For each row it records the element's class chain, the inline capacity, the loop kind,
  and two interval scans: the 27 direct sink tokens, and a separate **getter-capable** pass
  (`getIndex`, `getProperty`, `getOwnPropertySlot*`, `->get(`, `.get(`).

```
$ python3 tools/vector-local-sweep.py > data/vector-local/inventory.json
KINDS: Counter({'node': 28, 'other': 25, 'ref': 19, 'unknown': 16, 'gc': 3, 'primitive': 2})
$ python3 -c 'import json; d=json.load(open("data/vector-local/inventory.json")); print(d["counts"])'
{'files': 10500, 'funcs_with_sink': 53595, 'decls': 164, 'with_push': 125,
 'push_in_loop': 93, 'with_read': 67, 'with_window': 1}
```

The funnel, and what each step removes:

| step | rows | what it drops |
|---|---|---|
| local pointer/cell vector declarations | **164** | members, parameters, return types, `Ref`/`RefPtr`/`unique_ptr` elements |
| … with at least one `append`/`insert` | 125 | 39 filled only by `WTF::map(...)`/constructor/`appendVector` from elsewhere |
| … append inside a loop **or by recursion** | 93 | 32 with a fixed, literal number of appends |
| … read after the push | 67 | 26 filled and then handed to a callee (the vector is read *inside* the callee) |
| … a script sink in the push→read interval | **1** | 66 with no JS entry point at all between push and read |

The single survivor is `CloneSerializer::inputObjectStack` — the row docs/77 already closed. Element kinds over the
93: 28 DOM (`node`), 19 refcounted (`ref`), 3 GC (`gc`), 16 classes the index could not resolve (`unknown`), 25 that
resolve to neither `RefCounted` nor `Node` (`other` — mostly `RenderObject` subclasses and parser/layout structs),
2 primitives (`const char*`, `String`).

## 2. Three blind spots, two of them mine

The funnel above is the *second* version. The first reported 14 windows, and both versions would have missed the
only row that matters:

1. **`getIndex` was not a sink.** `JSObject::getIndex` (`JSObject.h:409-414`) is
   `if (tryGetIndexQuickly(i)) return …; return get(globalObject, i);` — on a hole it is a full `get`, so it reaches
   `PropertySlot::getValue` and calls a page getter. The getter-capable pass was added because of that; it reports
   **12 rows**, of which **10 are smart-pointer `.get()` false positives** (`RefPtr::get()`, `vertex->edges.last()
   .child.get()`), 1 is the serializer's own `getProperty`, and 1 is an accessibility `getElementById` path
   (`AccessibilityObject::elementsFromAttribute`, `:4017-4045`, whose `Vector<Element*>` is filled by
   `treeScope.getElementById()` — pure C++, no script).
2. **Recursion was not a loop.** `IDBBindingUtilities::createIDBKeyFromValue` appends `stack.append(array)` *outside*
   its `for`, and grows by calling itself. `in_loop()` alone drops it; a name match of the enclosing function inside
   its own body recovers it (2 more rows: `RenderLayerCompositor.cpp:1409`, `AccessibilityObjectAtspi.cpp:484`, both
   non-script).
3. **A vector declared in one function and filled in another is invisible to any per-function net — and that is
   exactly this bug's shape.** `createIDBKeyFromValue` declares `Vector<JSArray*> stack` in the two-argument
   wrapper (`:257`) and appends in the recursive overload (`:223`). It was found by reading
   `data/vector-local/all_locals.json` (the unfiltered population), not by the funnel. Recorded here so the next
   sweep of this class starts from the unfiltered list, not from the funnel.

## 3. The GC-element population: four declarations, all closed

Everything else is either a conservative-stack root (docs/75: `Heap.cpp:2841` "Cs", `MachineStackMarker.cpp:39-48`)
or a `Ref`/`Node` that script cannot free. The four `gc` rows are the whole class:

| # | file:line | vector | cap | push → read | verdict |
|---|---|---|---|---|---|
| 1 | `bindings/js/SerializedScriptValue.cpp:2499` | `Vector<JSObject*, 32>` | 32 | `:2578` pool, `:2587` push → `:2653` `last()` | **closed, docs/77** (`m_objectPool` is a `MarkedArgumentBuffer`) |
| 2 | `bindings/js/SerializedScriptValue.cpp:2500` | `Vector<JSMapIterator*, 4>` | 4 | `:2646` keep-alive → `:2647` push → `:2653` `last()` | inert: keep-alive is the line **before** the push; **measured**, §5 |
| 3 | `bindings/js/SerializedScriptValue.cpp:2501` | `Vector<JSSetIterator*, 4>` | 4 | `:2692` → `:2693` → `:2699` | inert, same shape; **measured**, §5 |
| 4 | `bindings/js/IDBBindingUtilities.cpp:257` | `Vector<JSArray*>` | **0** | `:228` push (recursive overload) → `:232` `getIndex()` | **inert, and page-reachable**: `getIndex` falls through to `get` on a hole, a page getter runs with the ancestor chain in the heap vector; **measured**, §5 |

Row 4 deserves its source quoted, because the shape is textbook (`:218-232`):

```cpp
if (auto* array = jsDynamicCast<JSArray*>(object)) {
    size_t length = array->length();
    if (stack.contains(array))
        return nullptr;
    if (stack.size() >= maximumDepth)          // maximumDepth = 2000, :194
        return nullptr;
    stack.append(array);                       // raw JSArray*, capacity 0 -> heap buffer
    Vector<RefPtr<IDBKey>> subkeys;
    for (size_t i = 0; i < length; i++) {
        JSValue item = array->getIndex(&lexicalGlobalObject, i);   // <- page script can run here
        RETURN_IF_EXCEPTION(scope, { });
        RefPtr<IDBKey> subkey = createIDBKeyFromValue(lexicalGlobalObject, item, stack);
```

Its entry point is synchronous and needs no database: `IDBKeyRange.only(value)` →
`IDBKeyRange::only(JSGlobalObject&, JSValue)` → `scriptValueToIDBKey` → `createIDBKeyFromValue`
(`IDBKeyRange.cpp:71-79`, `IDBBindingUtilities.cpp:426-429`).

**The gate is nominally closed and actually open.** `IDBFactory.idl:27` is
`EnabledBySetting=IndexedDBAPIEnabled`, and `UnifiedWebPreferences.yaml:3139` defaults
`IndexedDBAPIExposeIndexedDBToWindowOrWorkerEnabled` to `false` on `PLATFORM(PLAYSTATION)` for WebKitLegacy, WebKit
and WebCore, with the comment *"we need to hide window.indexedDB but expose the IndexedDB types"*. Measured on this
build (`research/vector-local/surfaces.html`, quarantine off):

```
=== S  surfaces.html?
access: none
EXIT=124
   B idb object
   B idbfactory function
   B idbobjectstore function
   B idbkeyrange function
   B idbrequest function
   B ctl-mutationobserver function
   B ctl-structuredclone function
   B ctl-map function
   B ctl-weakref function
   B ctl-attachshadow function
   B ctl-element function ctl-cssfontface function
   B done
```

`typeof indexedDB` is **`object`**, not `undefined`, and `IDBFactory`/`IDBKeyRange` are functions — so the
PlayStation default is not in effect in this build (either the port sets the preference elsewhere, or the generated
`WebPreferences` default for the key is not the one applied for a local page). The row is therefore live, and it is
the only page-reachable GC-element local vector in the tree.

## 4. The rows that can cross an inline boundary: 20, one at a time

40 of the 164 declarations have a non-zero inline capacity — the only ones where "grows past `N`" has any meaning
(without a capacity the buffer is heap from the first element). 20 of those 40 are appended inside a loop or by
recursion; the table is those 20, with the push→read interval scanned for a JS entry point. `d` = direct sink token,
`p` = getter-capable call.

| # | file:line | vector | kind | name | grow | d | p |
|---|---|---|---|---|---|---|---|
| 1 | `bindings/js/SerializedScriptValue.cpp:2499` | `Vector<JSObject*, 32>` | gc | `inputObjectStack` | while | `getProperty` | `getProperty` |
| 2 | `bindings/js/SerializedScriptValue.cpp:2500` | `Vector<JSMapIterator*, 4>` | gc | `mapIteratorStack` | while | – | – |
| 3 | `bindings/js/SerializedScriptValue.cpp:2501` | `Vector<JSSetIterator*, 4>` | gc | `setIteratorStack` | while | – | – |
| 4 | `bindings/js/SerializedScriptValue.cpp:2502` | `Vector<JSValue, 4>` | other | `mapIteratorValueStack` | while | – | – |
| 5 | `dom/Node.cpp:1918` | `Vector<const Node*, 16>` | node | `chain` | while | – | – |
| 6 | `editing/markup.cpp:780` | `Vector<Node*, 8>` | node | `exitedAncestors` | for | – | – |
| 7 | `rendering/RenderBlock.cpp:1819` | `Vector<RenderBox*, 16>` | node | `renderersToRemove` | for | – | – |
| 8 | `rendering/mathml/RenderMathMLUnderOver.cpp:95` | `Vector<RenderBox*, 3>` | node | `embellishedOperators` | for | – | – |
| 9 | `rendering/mathml/RenderMathMLUnderOver.cpp:96` | `Vector<RenderMathMLOperator*, 3>` | node | `stretchyOperators` | for | – | – |
| 10 | `rendering/updating/RenderTreePosition.cpp:71` | `Vector<Element*, 30>` | node | `elementStack` | while | – | – |
| 11 | `style/StyleInvalidator.cpp:192` | `Vector<Element*, 20>` | node | `parentStack` | for | – | – |
| 12 | `css/StyleRule.cpp:285` | `Vector<const CSSSelector*, 8>` | other | `componentsInThisSelector` | for | – | – |
| 13 | `html/parser/HTMLFormattingElementList.cpp:153` | `Vector<const HTMLStackItem*, 10>` | other | `candidates` | for | – | – |
| 14 | `dom/MutationObserver.cpp:195` | `Vector<MutationObserverRegistration*, 1>` | ref | `transientRegistrations` | for | – | – |
| 15 | `platform/text/BidiContext.cpp:110` | `Vector<BidiContext*, 64>` | ref | `contexts` | for | – | – |
| 16 | `rendering/BackgroundPainter.cpp:117` | `Vector<const FillLayer*, 8>` | ref | `layers` | for | – | – |
| 17 | `contentextensions/CombinedURLFilters.cpp:319` | `Vector<ReverseSuffixTreeVertex*, 128>` | unknown | `stack` | for | – | – |
| 18 | `contentextensions/CombinedURLFilters.cpp:410` | `Vector<PrefixTreeVertex*, 128>` | unknown | `stack` | while | – | `get` (a `RefPtr::get()`) |
| 19 | `rendering/RenderView.cpp:924` | `Vector<std::pair<RenderElement*, CachedImage*>, 10>` | unknown | `toRemove` | for | – | – |
| 20 | `style/ElementRuleCollector.cpp:211` | `Vector<const RuleSet::RuleDataVector*, 4>` | unknown | `ruleVectors` | for | – | – |

**18 of the 20 have no JS entry point in the interval at all** (the two that do are #1, closed, and #18, a
`RefPtr::get()`), and the intervals are short and mechanical — `chain.append(node); node = node->parentOrShadowHostNode();`
(#5), `candidates.append(&candidate); } if (` (#13), `ruleVectors.append(rules); } for (auto* rules` (#20). The frames
are layout, paint, style-recalc, tree-building, text iteration and parser bookkeeping; per docs/69-75 every JS entry
in this drop is an event dispatch, an observer callback, a `resolve(<DOM object>)` or a direct JSC call, and none of
the 20 intervals contains one. Two rows are additionally out of reach: `CombinedURLFilters` is content-extension
compilation (no page input into `processNFAs` from a normal load), and `mapIteratorValueStack` only exists on the
serializer's map path.

The other 20 capacity-carrying declarations never grow past `N` in a loop and are listed for completeness:
`CSSPropertyAnimation.cpp:1667,1673` (`const ShadowData*`, 4), `css/SelectorFilter.cpp:84` (`Element*`, 20),
`display/css/DisplayBoxDecorationPainter.cpp:1439` (`const FillLayer*`, 8), `dom/EventPath.cpp:320`,
`dom/Node.cpp:1217,1762,1763`, `dom/TreeScope.cpp:198,203,531,534` (`TreeScope*`/`Node*`, 5-16),
`editing/TextIterator.cpp:238` (`Node*`, 100), `rendering/InlineBoxPainter.cpp:297`,
`rendering/style/FillLayer.cpp:315` (`const FillLayer*`), `rendering/updating/RenderTreeBuilderSVG.cpp:110,125`,
`rendering/updating/RenderTreeUpdater.cpp:588` (`Element*`, 30), `style/StyleInvalidator.cpp:318,341` (`Element*`, 16).
Their appends are either absent or a fixed literal count, so the buffer never moves.

## 5. The measurements

Page md5s: `research/vector-local/vecmap.html` `efe3bc639cfd3672e79395e6fb21156f`,
`idbkey.html` `841dd52f68c704475b09987e97b55cfe`, `surfaces.html` `57d4dc4cf52155c0e6af7338dc7813d7`,
runner `runs.sh` `3de82dc673d762b466cce9c8d42f6c6b`. All copied to `/tmp/wkp/` on `teo@<lab-ip>`, run inside
the `wk` distrobox, **quarantine off** (`run_nq.sh`), a fresh port per arm.

```
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=20 PAGE=surfaces.html /tmp/wkp/runs.sh "S 8941 -"'
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=110 PAGE=idbkey.html /tmp/wkp/runs.sh "I0 8961 n=8&churn=0" "IN 8952 n=8&nocall=1" "IS 8953 n=8&churn=0&skew=1"; ... "I8 8962 n=8&churn=1"'
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=100 /tmp/wkp/runs.sh "M8 8971 n=8&kind=map&churn=1&from=6" "M4 8972 n=4&kind=map&churn=1&from=2" "MS 8973 n=8&kind=set&churn=1&from=6"'
```

| arm | page, query | beacons (verbatim) | verdict |
|---|---|---|---|
| `S` | `surfaces.html` | `idb object`, `idbfactory function`, `idbkeyrange function`, … `done` | the IDB gate is **open** on this build |
| `I0` | `idbkey.html?n=8&churn=0` | `gcprobe h22 alive`, `h23 alive`, `h24 alive`, `called hits=24`, `key kind=IDBKeyRange depth=8 bad=0 first=-1 got=` | probe negative control + shape oracle |
| `IN` | `idbkey.html?n=8&nocall=1` | `nocall hits=0` | the 24 hole reads happen **only** inside the engine |
| `IS` | `idbkey.html?n=8&churn=0&skew=1` | `key kind=IDBKeyRange depth=0 bad=2 first=0 got=4` | oracle sensitivity: a getter returning `999` instead of its index is visible in the reconstructed key |
| `I8` | `idbkey.html?n=8&churn=1` | `gcprobe h22 collected`, `h23 collected`, `h24 collected`, `churn h24 1200012`, `key depth=8 bad=0` | **GC inside `createIDBKeyFromValue`**, 8 raw `JSArray*` on an always-heap vector, key still correct |
| `M0` | `vecmap.html?n=8&kind=map&churn=0&from=6` | `gcprobe 6 alive`, `7 alive`, `verify kind=map depth=8 bad=0` | probe negative control |
| `M8` | `vecmap.html?n=8&kind=map&churn=1&from=6` | `gcprobe 6 collected`, `7 collected`, `verify kind=map depth=8 bad=0` | `mapIteratorStack` + `mapIteratorValueStack` past cap 4, GC in window, clone intact |
| `M4` | `vecmap.html?n=4&kind=map&churn=1&from=2` | `gcprobe 2 collected`, `3 collected`, `verify kind=map depth=4 bad=0` | **capacity control**: same page, same churn, `n=4` keeps every vector inline — identical outcome |
| `MS` | `vecmap.html?n=8&kind=set&churn=1&from=6` | `gcprobe 6 collected`, `7 collected`, `verify kind=set depth=8 bad=0` | `setIteratorStack` past cap 4, GC in window, clone intact |

`access: none` in all nine runs (no ASAN report, no `RELEASE_ASSERT`, no zapped cell). `EXIT=124` in every arm is
the harness's normal end (`timeout` kills MiniBrowser), as recorded in docs/65 "Attempt 11".

`I8` in full:

```
=== I8  idbkey.html?n=8&churn=1
access: none
EXIT=124
   B boot n=8 churn=1 hot=1 skew=0 nocall=0
   B idbkeyrange ok
   B built
   B gcprobe h22 collected
   B churn h22 400004
   B gcprobe h23 collected
   B churn h23 800008
   B gcprobe h24 collected
   B churn h24 1200012
   B called hits=24
   B key kind=IDBKeyRange depth=8 bad=0 first=-1 got=
   B done
```

### 5.1 What row 4's safety is, and what the run does not show

The key is that **this function recurses**: every array it appends to `stack` is also the `value` parameter of the
frame that appended it, and that frame is still on the C stack while its child is being walked. Conservative stack
scanning (docs/75) therefore sees all 8 arrays twice over, and the third root is the object graph itself — each
ancestor is its parent's `a[3]`, reachable from `value`, which is a live local of the wrapper.

So the site is safe for a reason *stronger* than the vector's type: the recursion is the keep-alive, exactly as
`m_objectPool` was in docs/77's site. And that is also why the run cannot distinguish "the vector is enough" from
"the frames are enough" — there is no way from JS to make an appended array unreachable while the frame that
appended it is live. The measurement establishes the two things it can establish: a GC really does land inside
this window, and the engine still reads the whole chain correctly afterwards.

## 6. The refcounted rows, read in source

The one worth quoting is `MutationObserver::deliver`, because it has the CVE-2026-43715 *ordering* (a snapshot of
raw pointers, then a callee that mutates the container the snapshot came from) and a cap of 1, so it crosses its
inline capacity on the second element:

```cpp
// dom/MutationObserver.cpp:189-215
Vector<MutationObserverRegistration*, 1> transientRegistrations;
Vector<HashSet<GCReachableRef<Node>>, 1> nodesToKeepAlive;
HashSet<GCReachableRef<Node>> pendingTargets;
pendingTargets.swap(m_pendingTargets);
for (auto& registration : m_registrations)              // WeakHashSet<MutationObserverRegistration>
    if (registration.hasTransientRegistrations())
        transientRegistrations.append(&registration);   // raw pointer into the weak set
for (auto& registration : transientRegistrations)
    nodesToKeepAlive.append(registration->takeTransientRegistrations());
...
m_callback->handleEvent(*this, records, *this);         // script runs here, after the last use
```

Why it is inert, in three facts from the tree:

* the registrations are **owned by the node**, not by the observer: `Node::registerMutationObserver` appends
  `makeUnique<MutationObserverRegistration>(...)` to a per-node registry (`dom/Node.cpp:2389`), and
  `m_registrations` is only a `WeakHashSet` of views (`dom/MutationObserver.h:129`);
* the loop's callee removes the registration from its **own node's** weak registry only —
  `Node::unregisterTransientMutationObserver` does `transientRegistry->remove(registration)` and nothing else
  (`dom/Node.cpp:2413-2422`), so element *i* cannot free element *j*;
* `nodesToKeepAlive` deliberately copies out the `GCReachableRef<Node>` sets before the callback, and the script
  callback comes after the snapshot's last read.

The other ref/node rows are inert for one of the two reasons this programme has already established: the frame
contains no JS entry point at all (`Node::showNodePathForThis`, `StyledMarkupAccumulator::traverseNodesForSerialization`,
`RenderTreePosition::nextSiblingRenderer`, `StyleInvalidator`, `RenderBlock::removePositionedObjects`,
`BidiContext::copyStackRemovingUnicodeEmbeddingContexts`, `RenderView::resumePausedImageAnimationsIfNeeded`,
`ElementRuleCollector::collectMatchingRules`, `BackgroundPainter::paintFillLayers`), or the vector's owner is not
page-reachable at all (`inspector/agents/*`, `workers/service/server/SWServer.cpp` — worker-thread code with no page
script, `platform/mac/HIDDevice.cpp` — not in the PlayStation build).

## 7. Verdict counts

* 10,500 files, **164** local pointer/cell vector declarations, **93** that grow in a loop or by recursion, **67**
  read after the push, **1** with a script sink in the push→read interval — and that one is docs/77's closed site.
* **4** GC-element declarations in the whole tree: 3 kept alive by an adjacent `m_keepAliveBuffer` line (measured:
  GC in window at depths 6-7 with the vectors past cap 4, clone intact, and a `n=4` capacity control with the same
  result), 1 (the IDB key builder) safe by recursion, measured with a GC inside its loop.
* **40** declarations with a non-zero inline capacity; **20** of them grow unboundedly (table §4); **0** of those 20
  has a JS entry point in the interval except the serializer's (closed).
* **2** tool blind spots found and fixed (`getIndex`, recursion), **1** that cannot be fixed by a per-function net
  (a vector declared in one function and filled in another — the IDB row, found by reading).
* 0 new live bugs; 1 corrected belief: the IDB surface is **not** gated off on this build.

## 8. What this changes

The local `Vector<X*, N>` class is done: every site that can cross its inline buffer has been read, the three GC
ones are measured, and the only page-reachable one is safe because it recurses. The capacity boundary itself is
inert everywhere it exists — for a refcounted pointee the capacity never mattered (a raw pointer does not ref
anything, inline or heap), and for a GC pointee the drop always has a keep-alive one line away.

What this sweep did **not** cover, and what should come next:

* **Members.** `Vector<X*> m_foo` of a heap C++ object was excluded by design here (docs/77 swept `JSValue`/`JSCell`
  members only). A raw `Vector<Element*>` or `Vector<Node*>` member, appended in a loop, read after a script window,
  is the same shape with a lifetime the page can influence — and 19 `.cpp` rows plus the headers were never
  enumerated.
* **`HashMap`/`HashSet<X*>` locals.** Always heap, no capacity question, and the same "is the pointee rooted?" test.
  The tool's `CONTAINERS` list names them but PASS 2 only walks `Vector`/`FixedVector`/`Deque`/`ListHashSet`.
* **`Vector<X>` where X is a value type holding a raw pointer** (e.g. `std::pair<RenderElement*, CachedImage*>`,
  row 19 here is only caught because the pointer is in the template argument) — an exhaustive version would need a
  layout pass, not a regex.

The console half (docs/65 "Attempt 9" flip, `docs/76`'s abort) stays blocked on the operator restarting the Guide
app; nothing in this doc needs the console.
