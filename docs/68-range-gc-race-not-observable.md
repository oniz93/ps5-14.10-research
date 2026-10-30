# The `Range`/GC race is a real data race, but ASAN cannot see it

GOAL action 1 after `docs/67` (row 1): *"Try to win the `Range`/GC race under ASAN — bounded at 10 runs."*
The action is closed as a **negative**, and not because the runs were unlucky: the sanitizer has nothing to
observe on this path. Evidence below is three runs plus the mechanism, both in the drop.

## The claim being tested

`docs/67` row 1 (`621e3bf30e` / `ab488735a4`): `Range` holds two boundary points as `Ref<Node>`
(`dom/RangeBoundaryPoint.h:53`) and its JS wrapper tells the collector about them from
`Range::visitNodesConcurrently` (`dom/Range.cpp:1133`):

```cpp
void Range::visitNodesConcurrently(JSC::AbstractSlotVisitor& visitor) const
{
    addWebCoreOpaqueRoot(visitor, m_start.container());
    addWebCoreOpaqueRoot(visitor, m_end.container());
}
```

`dom/Range.h:42` has no lock; the fix adds `m_boundaryPointLock` and takes it in every mutator. So a page that
reassigns a boundary from script while the concurrent marker is in that two-line visitor races the marker.
`JSC::Options::useConcurrentGC` is `true` by default (`JavaScriptCore/runtime/OptionsList.h:196`).

## Page and runs

`research/cand-triage/page-range-race.html`, md5 `4019f112f400fe821c845a980d274700`. It keeps *K* live
`Range`s, and in a loop gives each one a fresh `Text` node as both boundary points, removes the node from the
tree (the *next* `setStart` on that Range releases the last `Ref` and frees it), and allocates 1 MiB
`ArrayBuffer`s every *g* iterations to drive full GCs while the loop is running.
`mode=nor` is the same DOM churn with no Ranges (allocation control). Quarantine off, fresh port per run.

```
$ PAGE=../cand-triage/page-range-race.html ./research/cve-2026-43715/run-page.sh 9690 \
      "mode=range&k=8&n=40000&g=64" R1
access: none / SUMMARY: none
   start mode=range k=8 n=40000 g=64
   ranges=8
   iter 0 … iter 35000
   loop-done spins=40000

$ ... 9691 "mode=range&k=8&n=40000&g=64" R2
access: none / SUMMARY: none
   loop-done spins=40000                     (server log /tmp/srv9691.log, 1 hit)

$ ... 9692 "mode=nor&k=0&n=40000&g=64" RC
access: none / SUMMARY: none
   loop-done spins=40000
```

Three runs (two racing, one control), 40 000 boundary reassignments each, no ASAN report of any kind. Logs in
`data/cand-triage/run_R1.log`, `run_R2.log`, `run_RC.log`.

## Why no report is possible here

The visitor does not dereference the node it is handed. `addWebCoreOpaqueRoot` is a two-step wrapper that ends
in a **pointer insert**:

```
bindings/js/WebCoreOpaqueRootInlines.h:36-50   addWebCoreOpaqueRoot(visitor, root) -> visitor.addOpaqueRoot(root.pointer())
JavaScriptCore/heap/AbstractSlotVisitorInlines.h:123-135
                                               addOpaqueRoot(void* ptr) { … if (!m_opaqueRoots.add(ptr)) return false; … }
```

and nothing in JSC ever iterates that set to touch what it points at: `Heap::m_opaqueRoots` is only cleared
(`Heap.cpp:1416`), sized in a dump (`:1501`) and `deleteOldTables()`'d (`:1505`). The set is read exclusively
through `containsOpaqueRoot()` (`AbstractSlotVisitorInlines.h:139`), i.e. a hash lookup used by
`containsWebCoreOpaqueRoot()` in `ResizeObserver`, `IntersectionObserver`, `MutationObserverRegistration` and a
few `JSDOMWrapper` subclasses. The only implementation that dereferences an opaque root is
`VerifierSlotVisitor::didAddOpaqueRoot` (`heap/VerifierSlotVisitor.cpp:185`), and the verifier visitor is not
part of a normal run.

The remaining reads in the raced window are also not memory accesses of the freed object:

- `RangeBoundaryPoint::container()` is `return *m_container;` — loading the pointer out of a `Ref`, then binding
  a reference. A dangling reference is not a load.
- `addWebCoreOpaqueRoot(visitor, ImplType&)` takes `&impl` (`WebCoreOpaqueRootInlines.h:48-50`), i.e. address
  arithmetic on the reference.
- `Ref<Node>` is one aligned pointer; on x86-64 an assign/load cannot produce a torn value, and the old and the
  new pointer are both valid at the instant of the store (`Ref` releases the old node *after* the swap, in the
  temporary's destructor).

So the race exists — it is a genuine data race on a `Ref` member, exactly what the upstream `Lock` removes, and a
thread sanitizer would report it — but its consequence in this build is a **stale pointer inserted into a hash
set and only ever hashed**, never loaded from. ASAN reports heap use-after-free, and there is no heap access to
report. Running the remaining seven of the ten allowed runs would not change that.

## Consequence for the programme

This road cannot produce a reclaim primitive, and it cannot even produce an ASAN-verifiable bug: the marker's
only use of the boundary node is as a value. `docs/67` row 1 should be read as "live data race, not a candidate
primitive", and the `Range` family is closed for this stage of the work — a TSan-only finding has no path to
stage criterion 3, which needs a read/write that JS can see.

The one remaining live bug from the triage that is deterministic and JS-only is `docs/67` row 38
(BroadcastChannel hands one `SerializedScriptValue` to every recipient, and `deserialize` consumes it). That is
the next action in `GOAL.md`, with a bounded shape: two channels with the same name, `postMessage` an
`ArrayBuffer`/typed array, and read what the second recipient actually gets — under ASAN, and scored from the
beacon log.
