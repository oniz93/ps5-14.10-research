# GOAL — autonomous continuation

Read this file at the start of every iteration. Work the first unchecked item. Do not ask the operator anything
unless a step is blocked on physical access to the console.

## The goal

Get code execution in the PS5 14.10 WebProcess (Debug Settings via kernel is the end state, not this stage).

## Success criteria for the current stage (all verifiable by a tool run)

1. A browser-side memory bug that is **live on 14.10** and **reclaimable with attacker-controlled bytes** —
   verified by an ASAN run in which the reclaimed slot's contents visibly change the program's behaviour.
   **MET 2026-10-29** (`docs/65`, "Attempt 4"): the freed 192-byte `CSSFontFace` is reclaimed by a 172-character
   `atob` string, and a single character of it at object+0x87 changes where the engine dies
   (`fontLoadTiming:568` vs `Timer.cpp:469`), with a one-character control and two allocation controls.
2. Control over a **pointer-sized field** of that reclaimed object — verified by making a controlled address be
   read or written (an ASAN report naming that address counts). **MET 2026-10-29** (`docs/65`, "Attempt 5"):
   object+0x68 (`m_wrapper.m_impl`) is read as a `WeakPtrImpl*` by `CSSFontFace::existingWrapper()` from
   `FontFaceSet::faceFinished` — a *different client* of the same freed face — and the deref faults at exactly
   the 8 bytes we placed there plus 8 (`0x0008a827a829` is the ASAN shadow of `0x4141414149`; `0x1008` for the
   the poison `0x1000`), with an offset-shifted control at 0/6 and two poison values. The primitive is a **read**:
   the loaded value is only hashed by `m_pendingPromises.take()`, so it is not yet JS-observable. Attempt 6 closed
   the follow-up: a fake `WeakPtrImpl` built from 16 characters of the reclaimed container satisfies
   `existingWrapper()` without faulting (10 runs, 0 faults), and the recovered pointer is provably **not
   dereferenced** (0x4141414141 returned, 4/4 runs, no shadow report) — `docs/65`, "Attempt 6".
3. A read/write primitive expressed in JS — verified by reading a known value out of a known object.

Nothing above is claimed until the verification run exists and its output is quoted in a doc.

## The best primitive found so far

`docs/65`: **CVE-2026-43715 is live in Sony's drop** — `iterateClients` lacks upstream's `clients.contains(client)`
guard. Upstream's own regression test, run against our build, gives `heap-use-after-free, WRITE of size 1` at
`CSSFontFace::setStatus` (`CSSFontFace.cpp:595`) after the face is freed inside the client callback. A one-byte
write at `+0x82` of a freed 192-byte object, with the free happening inside a getter we control — so the ordering a
reclaim needs already exists.

**As of `docs/65` "Attempt 5" the slot gives a controlled pointer dereference too.** Attempt 4 established that a
172-character 8-bit `atob` string (20+172 = 192 bytes) allocated in the getter after `warm=1` occupies the freed
chunk, and that a byte at object+0x87 (`m_fontLoadTimingOverride`) is read by the engine and decides where the
process dies. Attempt 5 found that the loop then calls the face's *other* clients with the stale reference, and
`FontFaceSet::faceFinished` reads `face.m_wrapper` at **object+0x68** and dereferences it as a `WeakPtrImpl*`:
poison `0x1000` → `SEGV ... 0x000000001008`, control at object+0x60 → 0/6. That is stage criterion 2, with the
caveat that the loaded value is only hashed afterwards, so it is an arbitrary *read* of a chosen address, not yet
a JS-observable one. `setStatus` itself still cannot continue past `TimerBase::setNextFireTime`/`stop`, which
compares `m_thread` (+0xb0) by **address** against `&Thread::current()`; the platform override is a constant
`false` on Linux — no attacker bytes can pass that check.

**Attempt 11 closes the account on this bug** (`docs/65`): after the free the engine reads exactly two fields of
the container (`+0x87/+0x88` at `:599`, `+0xb0` at `:625`) and both roads end at the thread check, while
`m_status` is *written* before it is ever read, so no plant can steer `pump()`. `pump()` also cannot be run on
the container from JS at all (`FontFace::m_backing` is a `Ref`, so the freed face has no wrapper), and the
`face.load()` "hang" that looked like the next lead was the page silencing its own beacons. What remains is a
1-byte `Status` write into a JS string plus a discarded controlled read — **not stage criterion 3**. The bug
stays useful as a sanitizer-free JS-visible status flip (`docs/65`, "Attempt 9") and as a heap-shaping trick,
not as a memory-corruption primitive.

## Where we actually are

- **Confirmed live UAF:** `FontFaceSet::load()` dereferences a freed 192-byte `CSSFontFace` (plain `fastFree`,
  not IsoHeap). ASAN: `CSSFontFace::status()` at `CSSFontFace.h:104` from `FontFaceSet.cpp:196`.
- **Reclaim: OURS, with our bytes — measured.** `docs/65`, "Attempt 4": a 172-character 8-bit `atob` string in the
  getter after `warm=1` owns the freed 192-byte chunk. Proof, one character apart in the same container:
  byte 0x87 = `0x41` → `RELEASE_ASSERT_NOT_REACHED` in `CSSFontFace::fontLoadTiming()` (`:568`); byte 0x86 = `0x41`
  → the ordinary timer abort (`Timer.cpp:469`). Controls: without `warm=1` a 180-byte `FixedVector<UnlinkedArrayProfile>`
  takes the chunk (`0 bytes after 180-byte region`); a 180-character container (200 bytes, wrong class) never does
  (`:592`). `m_clients` (+0x58) cannot be used as a probe — `copyToVectorOf` copies the client set **before** the
  callbacks, so nothing reads it after the free. Free site unchanged: `CSSFontSelector::buildCompleted()` line 167
  from `Element::offsetHeight` inside the getter. Offsets: `m_status` +0x82, `m_clients` +0x58,
  `m_fontLoadTimingOverride` +0x87, timer `m_thread` +0xb0. `StringImpl` header **0x14**; the `atob` encoder must
  emit the base64 remainder or a 172-character request silently becomes 171.
- **The wall after the write is closed, and now fully enumerated — measured.** `docs/65`, "Attempt 11": after the
  free the engine reads **exactly two fields** of the container — `m_fontLoadTimingOverride` (+0x87, with
  `m_loadingBehavior` at +0x88, at `CSSFontFace.cpp:599`) and the timer's `Ref<Thread>` (+0xb0, at `:625`).
  `m_status` (+0x82) is *written* at `:595` before any post-free read, so planting it is inert by construction;
  `+0x38`, `+0x48`, `+0x54` (even a non-zero `m_sources.size()`) and `+0x58` are never read after the free
  (`S0`-`S4` identical); `+0x87 = 0x41` is the ownership witness (`S5`: `fontLoadTiming:568` ← `setStatus:599`
  ← `pump:686` ← `load:703`). `TimerBase::stop()` → `setNextFireTime` →
  `RELEASE_ASSERT(canCurrentThreadAccessThreadLocalData(m_thread) || shouldSuppressThreadSafetyCheck())`; the
  check is `&thread == &Thread::current()` (an address comparison) and `shouldSuppressThreadSafetyCheck()` is
  `return false` on Linux. No attacker bytes at +0xb0 can satisfy it, and every branch of
  `setStatus(Success/Failure)` ends in that `stop()`. The same-type reclaim survives only because a real
  `CSSFontFace` has a real `m_thread`.
- **The `face.load()` "hang" was an artifact — measured, withdrawn.** `quiet=2` makes the `then` getter set
  `SILENT = true` on every hit, including the hit that happens inside `face.load()`, and the scan's reset has
  already run; `EXIT=124` is how *every* run of `run_nq.sh` ends (`timeout` kills MiniBrowser). `H1`
  (`unquiet=1`) completes with `SELFLOAD ok st=loaded`, `SUM`, `done2`; `H2` (only `unquiet` removed)
  reproduces `G2` exactly. `docs/65`, "Attempt 11".
- **`pump()` can never run on the container — measured.** `fontLoadTiming`/`m_status` plants notwithstanding,
  `FontFace::m_backing` is a `Ref<CSSFontFace>`, so the face that `buildCompleted()` frees is one whose wrapper
  `adopt()` re-pointed in the same rebuild; a freed face has no wrapper, and `faceself=load` runs on the live
  adopted face (`H4`: planted `m_status = Failure` would have made `pump():646` return at once and read
  `error`; measured `status=unloaded` → `st=loaded`). `H3` (`mode=none`) is identical, so that beacon is not an
  oracle for the slot.
- **Pointer field, OURS — measured.** `docs/65`, "Attempt 5": after the freeing callback returns, the loop keeps
  running the face's *other* clients, and `CSSFontFaceSet::fontStateChanged` (`:533`) hands the stale
  `CSSFontFace&` to `FontFaceSet::faceFinished`, which reads `face.existingWrapper()` → `m_wrapper` at
  **object+0x68** (`objdump`: `mov 0x68(%rdi),%rax; mov 0x8(%rax),%rax`). Poison at 0x68 = `0x1000` → ASAN
  `SEGV ... 0x000000001008` (READ) at `WeakPtr.h:55` ← `existingWrapper` ← `faceFinished` ← `fontStateChanged`
  ← `iterateClients` ← `setStatus`; poison `0x0000004141414141` → `SEGV ... 0x0008a827a829`, which is the ASAN
  shadow byte of `0x4141414149` (our value + 8). Control with the same 8 bytes at object+0x60: 0/6, all
  `Timer.cpp:469`. Hit rate 4/6 and 5/8 — the read only happens when the set's client callback is iterated after
  the freeing one (WeakHashSet order is a per-run coin flip). **Read only:** `existingWrapper()` returns
  `*(m_impl+8) - 0x20`, and `faceFinished` only hashes it, so no JS-observable value yet.
- **Fake `WeakPtrImpl`, and why the read stops there — measured.** `docs/65`, "Attempt 6". The reclaimed container
  is a 192-byte `StringImpl` at **0x610000010540** (`[0x540,0x600)`, `StringImpl::create`, chars at `A+0x14`), and
  a fake impl written at `A+0x90` with `m_ptr = 0x1020` makes `existingWrapper()` return `0x1000` **without
  faulting** (10 runs, 0 faults; control `m_impl = 0x1000` faults at `0x1008` in 8/10). But the recovered pointer
  is **never dereferenced**: returning `0x4141414141` produces no shadow report (4/4), and the drop has only
  three uses of `existingWrapper()` — a bool test and a hash key (`FontFaceSet.cpp:240,243`, `take()` does not ref
  it) and `existingWrapper->adopt(...)` (`CSSFontSelector.cpp:234`, protected by `RefPtr<CSSFontFace> existingFace`).
  So the read is one level deep and its value is discarded; it cannot become observable at this site. Two
  corrections recorded there: `ov=` is inert in `atob` mode (Attempt 5 had **no** ownership witness; the atob-mode
  witness is `bidx=&b=`), and chunk ownership is ~30/30, not a lottery — the coin flip is client order (~8/10).
- **Status flip, weaponised — measured (JS-visible, permanent, not memory-unsafe).** `docs/65`, "Attempt 7": a
  post-free `new FontFace('zzpost0','local("NoSuchFontName")')` reads `status=loaded` while its `loaded` promise
  never settles (the stale loop iterates the *old* face's client snapshot), and the un-flipped twin goes to
  `error`/rejected under the same `load()`. `document.fonts.check()` returns true and `document.fonts.load()`
  resolves although the family measures like a nonexistent one (292 = 292; DejaVu 296). With a `url()` source the
  face instead renders a *visible* last-resort interstitial (304) forever, because `visibility(Success)` is
  `Visible` and `CSSFontAccessor` never recomputes for a `Success` face. No ASAN in six runs: the null is filtered
  at `CSSSegmentedFontFace.cpp:136`. **The flip needs no sanitizer to be observed**, which makes it the first
  grooming oracle usable on the console.
- **Prolapse/kernel:** closed on 14.10 by measurement, not by our inability to run it (ZigZagBoi's disassembly of
  the in-flight gate). Do not spend time here again unless new evidence appears.
- **Flip on an engine-owned face — measured.** `docs/65`, "Attempt 8": a document `CSSFontFace` created by the
  rebuild itself, with `src:local("NoSuchFontName")` and no JS object of ours in the window, reads `status=loaded`
  (twin `zzd1` in the same sheet reads `unloaded`, 5/5); `check()` true, `document.fonts.load()` resolves, width =
  nonexistent family, 9/9 runs with no ASAN. Arming it needs **two** rebuilds, because `buildCompleted()` frees at
  its last statement, after its staging re-adds; the rule's position in the sheet decides which face gets the chunk
  (2/2 flip when staged first, 2/2 silent when staged after `t`), and with four identical faces only the first is
  written. The lie survives an ordinary style recalc but dies at the next `createDocumentResolver()`. All offsets and
  the free site are unchanged from Attempts 3-7.
- **A field of the same-type occupant is ours — measured.** `docs/65`, "Attempt 10": the first post-free
  `new FontFace` takes the freed chunk (it reads `status=loaded` from the stale write with a never-loading
  `url()` source) and its `unicodeRange`/`family` can be driven from CSSOM and are dereferenced by the
  engine — `document.fonts.load('1em "zzpost0"','A')` resolves with `n=1` and `'M'` with `n=0` when the
  field is `U+41`, versus `n=1`/`n=1` with no drive. No ASAN, and none is possible on this route: CSSOM
  values are `UChar32` pairs / tags / an engine `RefPtr`, never addresses. A *fake* occupant cannot be
  driven from JS at all — `FontFace::m_backing` is a `Ref`, so the freed face has no wrapper by
  construction (measured: the setter writes nothing into the container). Offsets reconfirmed from the
  binary: variant `Ref` +0x08, variant index byte +0x10, `m_sources` +0x48 (size +0x54), `m_status` +0x82,
  `m_fontLoadTimingOverride` +0x87, `TimerBase::m_thread` +0xb0.
- **New anomaly, and the next lead: `face.load()` hangs when the wrapper's backing is a container.**
  **WITHDRAWN 2026-10-29** (`docs/65`, "Attempt 11") — there is no hang. `quiet=2` silences the page on every
  `then` hit, including the one inside `face.load()`, and `EXIT=124` is the harness's normal end. With
  `unquiet=1` the run completes; `face.load()` from the scan runs on the live `adopt()`-ed face, never on the
  container. Planting `m_status` is likewise inert by construction: the write at `:595` overwrites it before any
  post-free read, and `pump():646` reads the status before the free.
- **`CachedString` is closed, and the blocker is structural — measured (`docs/76`).** The freed object is a
  16-byte `JSString` cell in `stringSpace`, an `IsoSubspace` (`JSString.h:118-124`; `Heap.h:138` in
  `FOR_EACH_JSC_COMMON_ISO_SUBSPACE`, declared as `IsoSubspace` at `:1012-1015`), so the only cell class that can
  ever take the slot is another `JSString`. Measured, one knob per arm: 64 and 2000 `{}`s from the stream (64-byte
  `JSFinalObject`s in `vm.cellSpace`) never take it, a page `{}` literal **at the same 16-byte size class** never
  takes it (`OpNewObject` emits inline capacity 0, `BytecodeGenerator.cpp:3199`), an array flood never takes it,
  while the first flood string takes it every time (`v=FL1000`, `L=6`, `C=70`, 13/13). The read after the free is
  the collector's zap word (`HeapCell.h:54-59`): `m_structureID`=0, `m_type` left as String, `m_value` =
  `(old impl high 32) | 1` — no attacker-writable byte anywhere, so the `docs/65` one-byte plant has no offset to
  live at. Bonus: the no-flood arm is a **deterministic WebProcess abort**
  (`reportZappedCellAndCrash` ← `jsCast` ← `asString` ← `strictEqual`), 6/6 on the final page (2 plain + 4 with
  the 16-byte literal) and 9 of 11 plain runs across revisions, with no sanitizer
  and no reclaim. Page md5 `8bba4a1190665f9a67830b1882dfaa99`, logs `data/cachedstring-class/`.
- **The `CachedString` *shape* is swept whole-tree, and it has exactly one unprotected site — the one above —
  measured (`docs/77`).** 15,453 raw-cell declarations in `Source/WebCore` + `Source/JavaScriptCore` (10,035 + 2,942
  files), 147 of them members (`tools/jsvalue-sweep.py`, `data/jsvalue-sweep/inventory.json`): 31 WebCore, 116 JSC.
  WebCore's heap-stored ones are `CachedString::m_jsString` (closed, docs/76), `ScriptModuleLoader::m_shadowRealmGlobal`,
  `PaintDefinition::paintConstructor` and `WebXRTest`'s two `Vector<JSC::JSValue>` — and the last three are behind
  build flags, measured absent in one run (`ShadowRealm` not in `globalThis`, `CSS.paintWorklet` undefined,
  `navigator.xr`/`window.internals` undefined). `JSValueInWrappedObject::m_nonCell` is non-cell by construction; the
  other 24 are stack temporaries. JSC's 116 are marked by an owner visit (33 `visitor.*` lines), nested fields of a
  JSCell whose `visitChildren` walks them, VM-owned with an explicit aggregate visit (`QueuedTask`, `NumericStrings`,
  `SmallStrings`), or compare-only keys (`VM::stringRecursionCheckFirstObject`, `MegamorphicCache::Entry::m_holder`).
  **The one real window this sweep found is `CloneSerializer::inputObjectStack`**: a plain `Vector<JSObject*, 32>`
  (:2499) whose 33rd entry moves to the heap, while `getProperty` (:1197) runs an own getter *inside* the walk. It is
  safe for a reason its type does not show: every walked object is appended to `CloneBase::m_objectPool`, a
  `MarkedArgumentBuffer` (:900, :2578 before the :2587 push). Measured with a new sanitizer-free GC witness — a
  `WeakRef` decoy created in a *previous* job, deref'd inside the churning getter: `gcprobe 32..39 collected` at
  400k objects per getter, with the clone still reading all 40 levels (`bad=0`); `churn=0` gives `gcprobe 39 alive`
  (the probe's negative control) and `del=1` gives `verify bad=1 first=39` (its sensitivity control). Page md5
  `e52a6f94cb10a83f2c253c163a1998cf`, runner `research/jsvalue-stack/runs.sh`, logs `/tmp/run_{A5,B,C,D,E,S}.log`.
- **The `Vector<X*, N>` *local* shape is swept and closed, and its one page-reachable site is measured — `docs/78`.**
  164 local pointer/cell vector declarations in 10,500 `Source/WebCore` files; 93 appended inside a loop or by
  recursion; 67 read after the push; **1** with a JS entry point in the push→read interval, and it is docs/77's
  `inputObjectStack`. Exactly **4** carry a GC element: `inputObjectStack` (closed), `mapIteratorStack`/`setIteratorStack`/
  `mapIteratorValueStack` (keep-alive is the line *before* each push, `:2646`/`:2668`/`:2692`; measured — 8 nested
  `Map`/`Set` entries put the 5th in the heap buffer, `gcprobe 6/7 collected`, clone `bad=0`, and an `n=4` control with
  every vector inline gives the same result), and `IDBBindingUtilities.cpp:257` `Vector<JSArray*>` (**capacity 0**, so
  heap from the first element; `:228` push → `:232` `getIndex()`, which on a hole falls through to `get` and calls a
  page getter — measured, `gcprobe h22/h23/h24 collected` inside `createIDBKeyFromValue` and the key still reads back
  `depth=8 bad=0`, safe because the function recurses, so every appended array is also a live frame's `value`). The 40
  capacity-carrying declarations were read one at a time: 20 of them grow, 18 of those have no JS entry point at all,
  and the 2 that do are the closed serializer site and a `RefPtr::get()`. `MutationObserver::deliver`
  (`Vector<MutationObserverRegistration*, 1>`, the CVE ordering with a cap of 1) is inert by ownership — the objects
  belong to per-node `Vector<unique_ptr<…>>` registries (`Node.cpp:2389`) and the loop's callee removes each from its
  own node's weak registry (`Node.cpp:2413-2422`), with the script callback after the snapshot's last use.
  **Correction to a recorded belief: `typeof indexedDB` is `object`, not `undefined`** — the yaml default
  (`UnifiedWebPreferences.yaml:3139`, false on `PLATFORM(PLAYSTATION)`) is not in effect on this build, measured
  (`research/vector-local/surfaces.html`), so the IDB row is page-reachable. Pages md5 `efe3bc63…` (`vecmap.html`),
  `841dd52f…` (`idbkey.html`), `57d4dc4c…` (`surfaces.html`), runner `3de82dc6…`; logs `data/vector-local/`,
  `access: none` 9/9.
- **The *member* shape is swept and closed, and its unrooted pointee is measured — `docs/79`.** 49 member
  declarations carrying a raw pointer (43 at capacity 0), 69 push sites, 16 in a loop/recursion, 5 same-class rows
  read after the push, **0** with a JS entry point in the interval; 31 pointer-carrying hash locals, 26 inserted in a
  loop, 14 read after, 0 sinks. The reverse direction (the CVE's shape): 1,599 member containers, 1,070 range-fors,
  512 attributed rows, 38 with a callback-shaped call, 8 client-typed — all guarded by a copy
  (`Document.cpp:8589`), a two-buffer swap (`HTMLVideoElement.cpp:661`), a `RefPtr`/`WeakPtr` snapshot, or no script.
  `CollectionIndexCache::m_cachedList` (raw `Vector<NodeType*>`, push `Inlines.h:55` → deref `:134` across
  functions) is measured with 6 quarantine-off arms: after a removal `c[0]` answers the live node, `access: none`
  6/6, 0 sanitizer reports in 12 logs. Three of the 16 push rows are cross-class name collisions (the first pass
  joins by member name). **The blind spot the run leaves: helper templates** (`iterateClients(m_clients, lambda)`,
  `css/CSSFontFace.cpp:55-59`) — 147 `helper(member, lambda)` sites, and the only script-running one over a
  page-reachable client container is `iterateClients` (11 sites), i.e. `docs/65`'s bug. That is **done in
  `docs/80`**, below.
- **The helper-template shape is swept and closed (`docs/80`), and the guarded idiom's condition is now explicit.**
  219 syntactic `helper(m_member, [lambda])` sites across 24 helper names; **42** of them reach a helper that really
  iterates a parameter and calls another inside that loop (9 names). 11 are `iterateClients`
  (`copyToVectorOf<Ref<Client>>`, a snapshot; `A10` = `CSSFontFace.cpp:591`, `docs/65`'s loop) and 31 are raw, of
  which 7 are `.mm` files absent from `Sources.txt`, 1 is `ENABLE(WIRELESS_PLAYBACK_TARGET)` code (`PRIVATE OFF`,
  `WebKitFeatures.cmake:264`), 2 are a rendering helper iterating `parent.normalFlowLayers()`, and the remaining 21
  have pure value/predicate callbacks (`is2D`, `isCompleted`, `matches`, `ended`,
  `asValidatedFormListedElement`) — **0 with a script-capable callback**, including every raw row over a
  page-reachable container (a form's listed elements, a stylesheet's `m_childRules`,
  `Page::m_corsDisablingPatterns`, `TreeScopeOrderedMap::m_map`, `DOMCacheStorage::m_caches`), so the action's
  conditional ASAN run has no candidate. One reachability run *is* recorded: a `<track>`-created `TextTrack` really
  has two clients and one `setMode()` drives both (`A change=1` + `A terr=1 rs=3`, with `GET /nope.vtt 404` in the
  server log), `access: none` — the guarded loop's second `contains()` therefore runs after a client callback on a
  live owner. The *method* spelling — `m_member.forEach/map(lambda)`, 77 sites — is the guarded one: 51 of 52
  `.forEach` are `WeakHashSet::forEach` (`WeakHashSet.h:159-171`: snapshot + `contains` re-check), 25 `.map` are
  `Vector::map` (`Vector.h:1683`), 43 are client-typed, and every client family resolved to a *queued* callback
  (`HTMLTrackElement::textTrackModeChanged` → `scheduleLoad()`; `HTMLMediaElement::*` → `scheduleChangeEvent()`) or
  to `FontFaceSet::faceFinished` → `docs/65`. The new structural fact: that `contains` guard is itself a
  **post-callback read of the owner** (a `<track>` TextTrack has two clients — `HTMLTrackElement` at
  `HTMLTrackElement.cpp:69` and `HTMLMediaElement` at `HTMLMediaElement.cpp:4665`), so a snapshot-plus-contains
  helper is safe only where the owner is Ref-held: `TrackListBase::m_inbandTracks` + `HTMLTrackElement::m_track`
  there, and nothing at all for `CSSFontFace` — which is exactly why `docs/65` is the one live instance. Tool
  `tools/helper-callback-sweep.py`; logs `data/helper-callback/`.
- **The index-loop shape is closed twice over (`docs/81`, `docs/82`), and the second pass is type-aware — measured.**
  `docs/81`: 1,261 index loops, 310 on an owner container, 20 with a possible window, all 20 read, **0** that can
  read a shrunk container; the one member loop that really dispatches is `ApplicationCacheHost::stopDeferringEvents`
  and the drop's own comment says not to cache the size there. `docs/82` closes the blind spot `docs/81` names:
  37 of the 45 unresolved owner container types resolved through base/member chains (the 8 left are C structs, a
  forward-declared `DFA`, an anonymous struct and an owning `Vector<Ref<…>>`), 1,084 calls in the 310 bodies walked
  to depth 3 **by receiver type** in both sink classes (literal sinks and interface-client callbacks), **308 resolved
  (28.4%)**, and exactly one route — the same AppCache loop — so **0 new windows**. The complement, an
  over-approximation that follows *every* definition of a call name (a collision can only add candidates), flags
  **16 rows, all read: 15 are name collisions** (`create`, `size`, `x`/`y`/`width`/`height`, `swap`, `matches`,
  `remove`, `status`/`setStatus`) and the 16th is the AppCache loop, which is the pass's sensitivity control.
  Recall is measured: `tools/index-loop-resolve-validate.py` scores **59/60** on an automatic multi-hop ground
  truth. `read_after_window` is 0 in all 310 rows and `mutator_in_route` is empty, so no page or ASAN run follows.
  Tools `tools/index-loop-sweep.py`, `tools/index-loop-resolve.py`, `tools/index-loop-resolve-validate.py`; logs
  `data/index-loop/`.
- **The argument-passing spelling is swept and closed, and it is the last spelling of this mutation shape
  (`docs/83`).** The 310 owner-container loop bodies hold 1,368 calls and 992 arguments; **none** passes the
  loop's container, in any handle spelling (bare, `this->`, `&`, `*p`, `WTFMove`/`std::move`/`WTF::move`/
  `std::exchange`, or a local bound to it — and **no such local exists**, `alias-rows 0`). The 109 arguments
  that mention a container are element reads (108) or a size (1). On the callee side: 1,321 calls, 333
  resolved (25.2%), 371 bodies read (median 67 B) of which **28 mention the member and 0 mutate it** in any
  receiver spelling (`m_<n>.<mut>`, `self.m_<n>.<mut>`, `owner->m_<n>.<mut>` — the widened form of
  `docs/82`'s `mutator_in_route`), and 0 hand it on to a further callee. Controls: the same matcher finds 16
  sites across all 1,261 loops (all locals, all read, one `std::size` false positive) and an **independent
  pure-text regex returns the identical 0/310 and 16/1,261**; `iterateClients(m_clients, …)` matches at both
  call sites; the parameter-mutation test is positive **75 times tree-wide** (functions that take a non-const
  container `&` and mutate it — `SVGFilterGraph::visit`, `SizesCalcParser::handleOperator`,
  `SharedBufferChunkReader::nextChunk`, …), and the 5 calls in the 310 bodies that hit one of those 59 names
  are all `create(...)` collisions, which is why the pass matches arguments and not names. `this`/`*this` is
  passed **twice** in the whole population, both read. The 8 window rows were read one by one and no window
  call receives the container. No page or ASAN run: the conditional has no candidate. Correction recorded:
  `TYPE \s* NAME` splits an identifier (`m_currentCharacter` → `m_currentCharacte` + `r`) and invented two
  `SegmentedString.h` aliases; requiring `\s+` gives 0 and changes nothing else. JSON md5
  `c8d46cd36313cbb657a0e1ebf33633ed`, logs `data/index-loop/argpass.json`, `argpass.err`.
- **The sanitizer has now been pointed at the drop under a seeded in-page fuzzer, and it found nothing — `docs/84`.**
  29 ops over the four surfaces the audits kept finding (font lifecycle, CSSOM rule mutation on `<style>` and
  `<link>` sheets, custom-element reactions, `Range`/`Selection`), exactly four PRNG words per iteration so the op
  stream is a pure function of `(seed, i)`. Calibration first: the alphabet reproduces `docs/67`'s `@page` crash
  (`SEGV 0x70`, `parsePageSelector:229` ← `CSSGroupingRule.cpp:70`) and `docs/72`'s nesting crash (`SEGV 0x4`,
  `Ref<StyleRule>::operator=` ← `CSSStyleRule.cpp:229`); a Python re-implementation of the PRNG predicts the failing
  iteration exactly (`seed=1` → 62, confirmed at `n=61`/`n=62`) and reproduces the page's own per-op census **29/29**.
  Then **350,477 operations in 14 runs**: 4×20k required arms (`done&op=Fdel/Cup/Rmedia/Rfont`, `ms≈14.6-14.9 s`,
  `fc=10..18`), two reentrancy arms with **1,059 synchronous `then` windows** each — one of which
  `document.fonts.delete()`s a live face inside the window, 264 times — a 66-face pressure arm and 2×100k deep arms
  (one with 5,557 windows): **0 sanitizer reports, 0 exceptions in 19,500 executed ops**. Its limits are written down
  in `docs/84` §5: it is **not** a flip oracle, so it does not assert that `docs/65`'s free ran; one document, no
  workers/iframes/`structuredClone`; and the two known crashes are skipped by construction (they are the
  calibration, not the target).
- **The sequence-shaped instrument re-finds the bug, and it explains why `docs/84`'s null was thin — measured
  (`docs/85`).** `docs/84`'s alphabet could not open a FontFace-resolution window at all: `Fnew-local`'s source
  fails synchronously (`Pending → Loading → Failure`, and `FontFace::fontStateChanged` *rejects* on Failure), so
  `then=1` with those ops and 2,000 rounds gives **0** windows, while the same run with the new `Fnew-good`
  (`local("DejaVu Sans")`, which reaches `Status::Success`) gives **582**. `seq.html` drives rounds of 3–6 ops
  (25 PRNG words per round, `model_seq.py` reproduces the page's census **31/31**). Calibration: `cal=1` gives
  `heap-use-after-free` in **6/6** runs — `WRITE of size 1` at `CSSFontFace.cpp:595` in 2, `READ` at `:592` in 4,
  all at base+`0x82` (client order decides whether the freeing client is last), and the sampled `Fdoc` op gives
  the same UAF at `:592` (quarantine on) / the `docs/65` overflow flavour (off). **New mechanism: the window is
  only inside `setStatus` if `face.loaded` was materialised first** — otherwise `DOMPromiseProxy::resolve()`
  defers the fulfilment to `m_loadedPromise.get()` in `loadForBindings`, after the status write (measured:
  window `in=loaded` without the read, `in=loading` with it). Sweep, quarantine off, `skip=Rpage,Rnest-link,Fdoc`:
  4 seeds × 20k rounds = 328,790 ops, 23,415 windows, 0 exceptions, `access: none`; `gc=1` churned 400k objects
  inside 60 windows with the witness `pre=8/8 → post=0/8`, 0 reports; `then=0` is the control. **492,920
  operations, 29,306 in-engine windows (23,415 in the four arms), 0 sanitizer reports.** The alphabet's boundary is now the search's
  boundary: no iframe/second document, no `Animation`, no worker, no serializer.
- **The three surfaces `docs/85` could not reach are now fuzzed and closed — measured (`docs/86`).** A second
  document (an iframe with its own `CSSFontSelector`/`FontFaceSet`, driven from the parent and able to remove its
  own frame inside `setStatus`), `WebAnimation`'s resolve windows (a `then` accessor on `Animation.prototype` fires
  **inside** `finish()`, twice per call, and the window's `cancel()` suppresses the second) and a blob worker
  (terminated from inside those same frames, 64 times per arm) — 34 ops, `seq2.html`. Calibration on the new page:
  the `docs/65` UAF **6/6**, 3 `WRITE` at `:595` / 3 `READ` at `:592`, one byte. Sweep: **498,057 operations,
  43,795 in-engine windows** (21,027 in `setStatus`, 14,075 in the animation frames, 134 in the second document),
  14,308 frame destructions and 320 script-context terminations inside windows, **0 sanitizer reports, 0
  exceptions**. The limit that bounds it: `ext=1` couples the surfaces, so the inner document's own window fires 134
  times in the four arms versus 3,507 in the `then=0` control where frames persist.
- **The ranked candidate list has no second primitive — triaged, 56/56 (`docs/67`).** 5 entries are absent from
  the drop (file or feature), 3 are *older* than the code they describe and describe a defect that a later
  refactor introduced, 42 are hardening/refactor/build/perf/feature/correctness, 1 is the known `CachedString`
  bug (`docs/62`/`63`), 2 rows are one live GC race, 1 is live but not memory-unsafe (`:nth-child` int UB), 1 was
  measured negative (BroadcastChannel double-deserialize: `postMessage(any message)` has no transfer list in this
  IDL, so nothing is consumed — `docs/67`), and 1 is a live crash. The **top-ranked** entry (`cfe38930db`, "arbitrary deserialization data") cannot fire here: the drop predates the
  `std::span` writer and writes the same `byteLength` it declared (`SerializedScriptValue.cpp:1826` and `:1829`),
  so the length and the payload cannot disagree — and `JSC::Options::useSharedArrayBuffer` is **false** by
  default (`OptionsList.h:579`, only the Cocoa XPC entry point sets it), so a shared growable buffer does not
  exist in this build at all. The one live memory-safety entry (the `Range`/GC race) was probed and closed: the
  marker only hashes the boundary node pointer, so there is no heap access for ASAN to report (`docs/68`).
- **A deterministic WebProcess crash, verified — DoS, not a primitive (`docs/67`).** `<style>@media all {}</style>`,
  `sheet.deleteRule(0)` (which clears `parentStyleSheet` — the page reports `ps=null`), then
  `media.insertRule("@page foo {}", 0)` reaches `CSSParserImpl::parsePageSelector` with `styleSheet == nullptr`
  (`CSSParserImpl.cpp:229`, and `:238` for `@page foo:first`; the caller passes nullptr at `CSSGroupingRule.cpp:70`)
  and dereferences it. ASAN: `SEGV ... 0x70`, READ, top frame `RefPtr<StringImpl>::operator!()`; 2/2 with a type
  selector, 0/2 without one (`at=0` attached, `at=3` detached `@page {}`). Page md5
  `0f07e47e8fbbc642e47bf0a7235d741c`, logs in `data/cand-triage/`.
- **The pattern has no second instance in `css/` + `dom/` — audited, 26 rows (`docs/69`).** Every
  post-callback member use in those two directories is `Ref`/`RefPtr`-protected, held by a
  `GCReachableRef` container, or on an object script cannot free (`Document`, `ScriptExecutionContext`, the
  `RejectedPromiseTracker` its context owns). 4 of the 26 rows are not script sinks at all
  (`reject(Exception)`, `resolve()`, a primitive, a deferred `postTask`). The audit's lasting result is a
  sink taxonomy: **`resolve(<DOM object>)` is a synchronous script window**, measured — a
  `Array.prototype.then` accessor fires with `len=1` *before* a beacon on the next source line
  (`FontFaceSet.cpp:215`; windows `A2`/`B1`), and `Object.prototype.then` fires a second time with
  `len=undefined` for `document.fonts.ready`, whose next statement is `m_backing->addFontEventClient(*this)`
  (`:83-84`) and which survived a DOM wipe from inside the getter (`size` 2→0, no ASAN, `A4`/`A5`).
  So future pattern work must sweep events *and* `resolve(<object>)`; a page can open a script window
  inside a WebCore frame without a DOM wrapper of its own.
- **`html/` is exhausted for the same pattern — audited, 28 sites (`docs/70`).** 323 `.cpp` files (177 top
  level + 146 in `canvas/`, `track/`, `parser/`, `shadow/`, `forms/`), 65 raw sweep rows, 31 `dispatchEvent`
  rows of which 28 are real call sites (the sweep is **not recursive** — the subdirectory pass is what found
  `WebGLRenderingContextBase.cpp:5758`, the only `html/` site where a member call follows a synchronous
  cancelable dispatch — and that site turned out to be **compiled out**: `ENABLE_WEBGL OFF` in
  `Source/cmake/OptionsPlayStation.cmake:272`, matching the ASAN build, measured `NOCTX`). No reachable free,
  for three structural reasons: `JSDOMWrapper::m_wrapped` is a
  `Ref<ImplementationClass>` (`bindings/js/JSDOMWrapper.h:73-87`), so a node the page has named cannot be
  freed by a listener — the `css/` CVE worked only because the freed `CSSFontFace` had **no wrapper**;
  where the target is wrapper-free the drop already holds a `Ref`/`RefPtr`/`makePendingActivity`/
  `event->setTarget(Ref { *this })`/`UniqueRef`/`WeakPtr`, six of them with a comment saying the handler can
  deref the object; and media events are all queued (`setReadyState` → `scheduleEvent`), so a `MediaPlayer`
  callback cannot run script inside its own frame. Two of those verdicts are measured, not read (`V0`/`V1`/
  `P0` in `docs/70`): the `invalid` teardown runs inside the window (`HIT2 kids=0`) and survives
  `Ref protectedThis { element }` (`ValidatedFormListedElement.cpp:123`), and **`showPopover()` does not
  exist in this build** (`CALL err=TypeError`; `[EnabledBySetting=PopoverAttributeEnabled]`,
  `defaultPopoverAttributeEnabled()` = `false` on every non-Cocoa port) — so the only unguarded
  post-dispatch `this` use in `html/` is unreachable, not merely guarded. `HTMLMediaElement::dispatchEvent`
  (`:6594`, the one unguarded media tail) has **no callers**: dead code. Blind spot: the sweep's `NAMES`
  cannot see `executeScript`/`evaluate`/`JSC::call`, so the parser's own script window is the next action.
- **`html/parser/` is exhausted too — audited with the extended sink list, 5 script windows, 0 freeable
  (`docs/71`).** 18 rows after adding `executeScript`/`executePendingScript`/`evaluate`/`JSC::call`/
  `performMicrotaskCheckpoint`/`execute` to the sweep's `NAMES` (3 rows are artifacts: `evaluate` is the CSS
  media-query evaluator, `execute` splits an argument list). The parser's windows are three
  `performMicrotaskCheckpoint` calls and one `executePendingScript`; every object used after them is a
  `unique_ptr` member of a `Ref`-protected parser or a local `Ref`. The one upstream difference in the CVE shape —
  `LoadableScript::notifyClientFinished` iterating **raw** client pointers where upstream iterates
  `WeakPtr<LoadableScriptClient>` — is unreachable because a `LoadableScript` is per-element and `prepareScript`
  runs once per element, so the set holds one client. Measured 3/3, `access: none`.
- **`style/` has no script door, and the rule-mutation frames hold `Ref`s — but their copy path is a
  measured WebProcess crash (`docs/72`).** 14 sweep rows in 8 files are all media-query/decoration/animation
  `evaluate`/`resolve` artifacts, and `grep -rn "JSC::"` over the directory's 40 `.cpp` files is 0. The 31
  `RuleMutationScope` sites live in `css/`; their tail is `scheduleUpdate()` → `clearResolver()` + a 0 s
  timer, and `CSSFontSelector::buildCompleted()` has one caller (`StyleScope.cpp:121`), so the action's
  premise ("`didMutateRules` reaches the `docs/65` free site") is false. Measured instead:
  `document.styleSheets[0].cssRules[0].insertRule('& b{color:red}', 0)` on a `<link>` sheet → `SEGV
  0x000000000004` (READ) in `RefCountedBase::ref()` ← `Ref<StyleRule>::operator=` ←
  `CSSStyleRule::insertRule` (`css/CSSStyleRule.cpp:229`), 4/4 runs (1 or 2 links, top-level or nested in
  `@media`), vs 0/2 inline-`<style>` controls that return `ret=0`. Cause: `RuleMutationScope` inside
  `prepareChildStyleRuleForNesting` copies the contents (`willMutateRules()`, because a `<link>` sheet is
  in the memory cache even with one client) and reattaches the wrappers, so the `rules[i].ptr() ==
  &styleRule` lookup can never match and the null `RefPtr` is assigned. DoS, not a primitive: the loop
  compares the stale reference by address only, and `m_styleRule = *nullptr` has no attacker value. The raw
  `StyleRule*` local in `DeclaredStylePropertyMap::setProperty` was measured too: no fault, the write lands
  on the **pre-copy** rule (with two links, the sibling sheet gains `margin-top: 13px` while the caller's
  sheet does not) because `CachedCSSStyleSheet` pins the original contents.
- **`page/` + `loader/` are exhausted, and the reason is structural (`docs/73`).** 117 sweep rows, 62 in the
  JS-sink set over 40 functions, 0 with a reachable free: every window is either an event dispatch — where the
  `Event` refs its target (`dom/Event.h:194` `RefPtr<EventTarget> m_target`, cleared only in `initEvent`, which
  returns early while dispatching) and node dispatches add `Ref protectedNode` (`dom/EventDispatcher.cpp:155`)
  — or an observer callback whose only post-callback use is a `FAST_RETURN_IF_NO_FRONTENDS` no-op. A frame is
  not destroyed by DOM removal either: `HTMLFrameOwnerElement.cpp:82` holds `RefPtr frame` across
  `frameDetached()`, which holds `Ref protectedFrame` (`FrameLoader.cpp:2972`). 12 rows are non-sinks, 12 cannot
  run (touch/drag/device-orientation/content-filter, all default OFF in `WebKitFeatures.cmake` and not
  overridden by `OptionsPlayStation.cmake`). `page/` has no `JSC::call`/`JSC::evaluate` at all; `loader/` has 0
  `JSC::`. The one risky tail was measured: `loadInSameDocument`'s synthetic owner `load` + remove-the-iframe →
  `access: none` 3/3 with the `rm`/`div`/`none` beacons proving the window fired and the removal detached the
  frame. **This closes the directory list: every JS window in this drop is an event dispatch, an observer
  callback, or a `resolve(<DOM object>)`.**
- **The `resolve(<DOM object>)` surface is closed across the whole tree, and the one family with a real tail was
  measured (`docs/74`).** 10,035 files (`.cpp` + `.h`), 364 settlement-shaped calls, 92 `.cpp` `resolve` arguments
  that are neither empty nor a brace list (17 literal primitives → 75 that carry a value), 41 with a statement after
  the call in the same frame, 11 genuine post-resolve uses, **0 with a reachable free**. The rule that splits the
  surface is the engine's own: `PromiseOperations.js:187-192` fulfils without reading `then` unless the argument is
  an Object, so `reject(...)` and primitive resolves are not windows. The 11 rows: `WebAnimation` ×7
  (`setStartTime:382`, `setCurrentTime:498`, `finish:867/873`, `finishNotificationSteps:1003`,
  `runPendingPlayTask:1201`, `runPendingPauseTask:1340` — `this` is `RefCounted` and the wrapper that made the call
  holds `Ref<ImplementationClass> m_wrapped`, `JSDOMWrapper.h:88`), `DOMCacheStorage::doOpen:206/218` (`Ref` local
  plus `makePendingActivity`), `Permissions::query:160` (`WeakPtr<Page>` and locals), `FetchEvent:192`
  (the worker's `ScriptExecutionContext*`). Measured, not argued: `Animation.finish()` opens the window **twice**
  (`THEN hit=2/3 on=Animation` before the beacon on the next source line, with an in-page `Promise.resolve({})`
  control), script can `cancel()`+`remove()` inside it, and the frame then runs `hasEventListeners`/`effectEndTime`/
  `animationDidFinishForElement` on live objects — `access: none` 5/5. Negative control that matters for the console:
  a `DOMPromiseProxy` resolve is a **no-op unless the page has already materialised the promise**
  (`pre=0` → `hits=0`), because it only settles `DeferredPromise`s already in `m_deferredPromises`. The loop shape
  that made CVE-2026-43715 appears 3 times and is safe every time (two `std::exchange` drains, one `bool` resolve).
- **The direct-JSC class is closed, and it added two structural guards (`docs/75`).** 10,035 files, 342 calls in the
  sweep's sink list, 83 synchronous (20 header declarations, 63 `.cpp` sites in 54 functions), 42 with a statement
  after the call, **0 with a reachable free**. The split that matters is `JSExecState`'s destructor, which drains the
  microtask queue before control returns to C++ (`JSExecState.h:157-162`, `JSExecState.cpp:41`) — every synchronous
  JSC call has script-run-again semantics for its tail. (a) **Conservative stack scanning is a GC marking constraint
  in this drop** (`Heap.cpp:2841` "Cs"; `MachineStackMarker.cpp:39-48`, `:202`; `currentThreadState.stackTop` →
  `stackOrigin`), so a raw `JSValue` local across a script window is a root: `JSDOMBuiltinConstructor.h:103`
  (`jsObject` → `encode`) and `JSCustomElementInterface.cpp:156` (`newElement` → `toWrapped`) are safe for that
  reason, not because of a `Protect`. (b) **The XML parser has a real custom-element window and it is refcounted by
  hand**: `customElementReactionStack.reset()` (`XMLDocumentParserLibxml2.cpp:843`) runs the constructor and the tail
  at `:858` reads the raw `m_currentNode` (`XMLDocumentParser.h:162`), but `pushCurrentNode` calls `n->ref()`
  (`XMLDocumentParser.cpp:66-71`) and only `popCurrentNode` releases it, so no removal frees it — measured: the
  window fires (`CTOR` before `TAIL`), `document.documentElement.replaceChildren()` empties `<svg>` and the parser
  still appends into the detached node, with an XHTML `<div>` twin and a three-size spray under quarantine-off all
  identical, no ASAN in six arms. (c) `EventLoop::run()`'s tail runs on the per-agent-cluster `WindowEventLoop`
  (`WindowEventLoop.cpp:66-79`, `Document.h:2180`) that every document in the cluster keeps alive — a child task
  removing its own frame leaves the parent's 500 ms/1500 ms beacons running. Three rows are compiled out
  (`CSS_PAINTING_API 0`, legacy `MODERN_MEDIA_CONTROLS` path, content filtering); the rest are `Ref` locals,
  `makePendingActivity`, the dispatcher's `Ref<EventListener>`+`Event::m_target`, or worker contexts that `close()`
  only marks (`WorkerGlobalScope.cpp:297-310`).
- **The three surfaces left over from the audits are fuzzed now, and the fourth does not exist — measured
  (`docs/87`).** `structuredClone`, IndexedDB's key builder and `MutationObserver` are wired into
  `seq3.html` and each verified by a window that really fires; `window.open` is not wireable: five
  spellings and a programmatic link click return null, `showModalDialog` is `undefined`, `_self` returns
  the current window and replaces the document (measured: that page never sends its `done` beacon).
  Negative results worth keeping: `Object.defineProperty`'s non-enumerable default silently makes a
  clone getter invisible (the serializer walks own enumerable names, `SerializedScriptValue.cpp:2590`);
  a Proxy is rejected with `DataCloneError` **before** any trap runs (`hits=0`), so an accessor is the
  only way into that walk; and an IDB hole getter can live on a per-array prototype (receiver is the
  array), so the instrument does not have to poison `Array.prototype`.
- **The single destructive knob is split, and the delivery loop now hosts a three-level frame — measured
  (`docs/88`).** `seq4.html` (md5 `aea291c7beb30d601aedb6780b5b52e5`, 38 ops) carries `extf` (the font
  windows' destruction: face delete + frame removal + the srcdoc's kill), `extw` (worker termination,
  capped at 64 per arm) and `extm` (the delivery's own destruction), with `ext` kept as the all-three
  shorthand and `mof` gating one new op (`Mofr`) plus `moFrame()`. The delivery now resolves a face
  **inside the second document** (`d.head` rule, `d.body.offsetHeight`, `d.fonts` lookup,
  `f.loaded`/`f.load()`) and removes that frame in the same delivery: the `mofr` beacon's
  `ith0 -> ith1` +1 around the load is the witness, `rem=1` the removal, and an isolated
  `only=Mobs,Mofr` arm gives `mofd=11`/`ith=11`/`mofrem=11`/`mod=13`. `mof=0` is the axis control (same
  stream, `ith=0`). The split is worth what it cost: `extf=0&extw=1` keeps frames alive and the second
  document's own font window fires **2,828** times in an arm (against `docs/87`'s 0), while the same
  seed with `extf=1` gives `ith=0`, `frm=6,049`, `mofd=0` and every font-side counter identical. Four
  20k arms: 87,450 windows (11,109 in a second document), 7,996 deliveries, 4,756 delivery-driven
  inner resolutions each followed by that frame's removal; seven arms, 586,509 operations, 0 sanitizer
  reports. Limits: the inner `setStatus` is **not** armed for the docs/65 free (nothing changes the
  inner sheet set inside it), so the nesting is an ordering instrument; `moir=0` is unchanged; and the
  GC witness collected in 1 of 6 sampled windows, so "a collection inside every window" is not claimed.
  One instrument defect found and fixed on the way: an unguarded `moFrame` drove the initial empty
  document of a frame whose srcdoc had not run (`ith=1` against `mofd=20`), now gated on `W.__ran` and
  counted as `mofearly`.
- **The transfer list is reached and swept, and it produced the programme's first sanitizer-free
  WebProcess abort from a message (`docs/89`).** `workers/Worker.idl:35` and `dom/MessagePort.idl:35`
  really carry `postMessage(any message, sequence<object> transfer)`; `CloneSerializer::serialize`
  (`SerializedScriptValue.cpp:5463`) runs the whole walk — page getters included — **before**
  `transferArrayBuffers` (`:5477`) detaches, measured (`gx=192` inside the getter, `tx=0` after the
  call, `rx=192` at the receiver; the `wxk=0` control gives `tx=200`). A getter that shrinks a
  **resizable** buffer after the view was dumped makes the payload's length and the arrived contents
  disagree. **Typed arrays** then arrive as out-of-bounds views (`vl=0`, writes silently dropped —
  `GenericTypedArrayView::wrapImpl` uses the non-verifying `create`), while a **`DataView` with an
  explicit `byteLength`** makes `JSDataView::create` throw `RangeError("Length out of range of buffer")`
  (`JSDataView.cpp:35`), the exception survives `MessageEvent::create`, and both dispatch callers
  `RELEASE_ASSERT(vm.hasPendingTerminationException())` (`MessagePort.cpp:295`,
  `WorkerMessagingProxy.cpp:245`) — **four aborts, two call sites, two spellings**
  (`caps9.html?view=dv&res=1&shrink=1`). Controls: no shrink, non-resizable, auto-length view,
  getter-before-view (`DataCloneError` at `postMessage`), and `structuredClone` without a transfer
  list. This is a **DoS, not a primitive**, and `RELEASE_ASSERT` is enabled in release builds.
  Instrument `seq5.html` (40 ops, `wxt`/`wxk`): calibration **6/6** (3 `WRITE` at `:595`, 3 `READ` at
  `:592`, base+`0x82`), sweep **336,446 operations and 18,016 transfers in the four required arms**
  (504,624 over six, `wxtx=0` on every buffer), 25,596 `setStatus` and 23,542 `Animation` windows,
  **0 sanitizer reports, 0 exceptions**. The GC arm collected in **0 of 6** sampled windows
  (`pre=8/8 post=8/8`) and is recorded as the negative it is.

- **Console** is wedged on the Guide menu with a dead WebProcess; needs a manual app restart by the operator before
  any on-console case can run. Local ASAN work is unaffected.
- **The flip needs no attacker bytes — measured, and this is the console page.** `docs/65`, "Attempt 9":
  `mode=none&npre=0&npost=0&quiet=2&doc=zzd&docn=2` (page md5 `f0d1b337aaad040b5f1824a162295759`) reads
  `DFACE zzd0:loaded zzd1:unloaded` with `scan strs=0 faces=0` — no container, no `new FontFace`, no warm-up — 9/9 in
  every flipping configuration, `access: none` 12/12. `warm=1` is inert under `mode=none` (it warms `alloc()`, never
  called), so the lazy-compile question was tested with a new `docwarm=1` (pre-call `DOCRULE(0)`): the flip fires both
  with the compile in the window (3/3) and outside it (2/2), i.e. the compile does not steal the chunk. `docat=end`
  fails 2/2, and its `FACE picked status=loaded` is family `t`'s **live** new face (`adopt()` re-points `m_backing`,
  `FontFace.cpp:324`) receiving the write — a second witness of "first staged face wins" via `FontFace.status`, not
  the `DFACE` scan. The page's whole workload is: pick `t`, remove `<style id=v>`, layout, `insertRule` two
  unresolvable `@font-face` rules at index 0, layout, report.

## Next actions, in order, each with its verification

1. **Next: enumerate the family behind that abort — every page-reachable way to make message
   deserialization fail, and which of them need a resizable ArrayBuffer.**
   `docs/89` §3 measured one member and showed the defect is in the *handling*, not the input: a
   deserialization that fails, or leaves a pending exception, for any reason other than termination hits
   `RELEASE_ASSERT(vm.hasPendingTerminationException())` at `MessagePort.cpp:295` and
   `WorkerMessagingProxy.cpp:245`. The size of that input set is unknown. `CloneDeserializer` has many
   `fail()` returns, and `SerializedScriptValue::create` has several `SerializationReturnCode` producers
   (the transfer-list rejections at `:5377-5399`, detached/locked buffers, `read*` failures in the
   deserializer, `ValidationError` from `readArrayBufferViewImpl`'s `return false` paths). The ones that
   matter are those a page can steer **without** a resizable buffer, because whether the console build
   keeps `Options::useResizableArrayBuffer` (default **true** in this drop, `OptionsList.h:578`) is
   unmeasured. Audit every failure return in `SerializedScriptValue.cpp`'s neighbourhood for a
   page-controlled input, then for each candidate run one arm of `caps9.html`'s shape with the one
   variable changed, plus a control that differs only in that variable.
   **Verify:** each candidate is its own arm, scored from whether the harness aborts (`EXIT` plus a
   `WTFCrashWithInfo` frame in the ASAN log naming `MessagePort.cpp:295` or
   `WorkerMessagingProxy.cpp:245`), never from a beacon; record the ones that abort with the exact site
   and the ones that return cleanly with the reason they are filtered. Do **not** re-enter the console
   for this.
1. ~~**Probe the one IDL on this build that really carries a transfer list —
   `Worker.postMessage(message, [buf])` — where `m_arrayBufferContentsArray` is actually read.**~~ **DONE
   2026-10-30 — the transfer is real, the walk provably runs before the detach, and the shrink that makes
   the payload and the contents disagree is a deterministic WebProcess abort (`docs/89`).**
   `CloneSerializer::serialize` (`:5463`) runs the whole walk before `transferArrayBuffers` (`:5477`), so
   the getter reads the **full** length (`wxgx=200`) and the buffer is still attached while page script
   runs; after the call it is detached (`wxtx=0`), and the `wxk=0` control reads `wxtx=200` — same stream,
   one field different. The 192-byte class was used throughout (192/200/208 on `b % 3`). The extra
   finding: an explicit-length `DataView` over a resizable buffer that a getter shrinks **after** the view
   was dumped deserializes into a `RangeError` that `MessagePort.cpp:295` and `WorkerMessagingProxy.cpp:245`
   both `RELEASE_ASSERT` against — four aborts, two sites, two spellings, and five controls (no shrink,
   non-resizable, auto-length, getter-first → `DataCloneError`, `structuredClone` without a list). Page
   `research/fuzz-cssom/seq5.html` (md5 `e82af40a01f49f423ad2a456e39ffa32`, 40 ops, builder
   `build_seq5.py`) adds `Mwx` (MessagePort) and `Awx` (a dedicated blob worker) with `wxt`/`wxk`; the
   automatic receiver keeps the crash out of the alphabet on purpose (it would end every arm that drew
   it). Calibration **6/6**; sweep 4×20k = **336,446 operations, 18,016 transfers, 0 sanitizer reports,
   0 exceptions**, six arms 504,624 operations, the GC arm collecting in 0 of 6 sampled windows. Logs
   `/tmp/S_seq5.html.99*.log`, `/tmp/srv1002*.log`, scorer `score_seq.py`.
1. ~~**Give `ext` a per-surface split, and use the one nesting `docs/87` measured to build a
   three-level frame.**~~ **DONE 2026-10-30 — `extf`/`extw`/`extm` are separate variables, the second
   document is a window surface again (11,109 windows against `docs/87`'s 0), and the three-level frame
   is measured 1:1 (`docs/88`).** `research/fuzz-cssom/seq4.html` (md5
   `aea291c7beb30d601aedb6780b5b52e5`, builder `build_seq4.py`, 38 ops) keeps `ext` as the all-three
   shorthand; one call site proves the split (`extw=1&extf=0` -> `wterm=64`, `frm=0`, `ith=2,828`) and
   one proves the cause (`extf=1` on the same seed -> `ith=0`, `frm=6,049`, `mofd=0`, every font-side
   counter identical). The new op `Mofr` + `moFrame()` make the delivery resolve a face **inside** the
   second document and remove that frame in the same delivery: isolated `only=Mobs,Mofr` arm gives
   `mofd=11`/`ith=11`/`mofrem=11`/`mod=13` with `mofr&ith0=0&ith1=1&rem=1&ran=1`, and `mof=0` is the
   axis control (same stream, same `moh`/`mors`/`mod`, `ith=0`). Calibration `cal=1` 6/6 (2 `WRITE` at
   `:595`, 4 `READ` at `:592`, base+`0x82`; the observer moves the base `0x46bc2`->`0x46cc2`). Sweep:
   four 20k arms = **335,094 operations, 87,450 windows** (11,109 in the second document), 7,996
   deliveries, 559,807 records, 4,756 delivery-driven inner resolutions each followed by that frame's
   removal, 256 worker terminations; seven arms = **586,509 operations, 134,127 windows, 0 sanitizer
   reports, 0 exceptions, `access: none` 7/7**. One instrument defect found and fixed (an unguarded
   `moFrame` drove the initial empty document of an unparsed frame: `ith=1` against `mofd=20`; the
   `W.__ran` guard plus `mofearly` is the fix, both builds' md5s recorded). Limits kept: the inner
   `setStatus` is **not** armed for the docs/65 free (no inner sheet-set change), `moir=0` unchanged,
   and the GC arm collected in 1 of 6 sampled windows rather than every window.
1. ~~**The four surfaces the audits closed only on paper — `structuredClone`, IndexedDB's key builder,
   `MutationObserver`, and `window.open`.**~~ **DONE 2026-10-30 for three of them, and the fourth is
   measured absent (`docs/87`).** `research/fuzz-cssom/seq3.html` (md5 `6ccdf12569d4da03da27a236e411462e`,
   37 ops, built by `build_seq3.py` from `seq2.html` at six anchors that must occur once, with the page's
   own script syntax-checked and a negative control for that check) wires the serializer (`Cclone`: an
   enumerable getter at depth 24-43, i.e. past `inputObjectStack`'s 32-entry inline capacity, where
   `docs/77` had only read the keep-alive), the key builder (`Ikey`: an array hole answered by a getter on
   the array's **own** prototype — measured receiver-correct, so `Array.prototype` is not poisoned — inside
   `createIDBKeyFromValue`) and the observer (`Mobs`: one callback per 10-round task, 565,818 records and
   2,808 removals of the observed node *inside* the delivery, and the delivery hosting a `setStatus` of its
   own). **`window.open` does not exist on this build**: five spellings and a link click all return null
   (`allowPopUp()` is false for script and/or the UI client refuses `createWindow`), `showModalDialog` is
   `undefined`, and `_self` returns the current window and navigates it — so a Page-teardown Document
   destruction path stays unmeasured by construction. Calibration on the shipped page: **6/6**, 2 `WRITE`
   at `:595` and 4 `READ` at `:592`, all at base+`0x82`, with the observer moving the object's base by
   `0x100` and the fault with it. Sweep: four 20k arms = **334,690 operations, 64,777 in-engine windows**
   (26,873 `setStatus`, 12,775 `Animation`, 15,597 serializer, 9,532 key builder) plus **7,996 delivery
   windows**, 11,717 frame kills, 256 worker terminations, and a GC arm inside 60 windows with the
   identical stream; six arms = **501,958 operations, 87,253 windows, 0 sanitizer reports, 0 exceptions,
   `access: none` 6/6**. Two limits recorded: `moir=0` (a delivery never lands inside the round that queued
   it) and `ith=0` (two windows now kill frames, so the second document is a destruction target only in
   these arms) — both are the next action's subject. Original text: `docs/86` removes the previous three
   (second document, `Animation`, worker) with **498,057 operations over 43,795 in-engine windows and 0 reports**,
   so the alphabet's boundary has moved again and what is left is exactly the set the sweeps closed by reading:
   (a) the serializer — `docs/77` measured `CloneSerializer::inputObjectStack` safe because every walked object is
   already in `m_objectPool` (`MarkedArgumentBuffer`) while a page `getProperty` runs inside the walk, so a
   `structuredClone` op whose getter removes and re-adds nodes is the sequence shape applied to it; (b) IndexedDB's
   `createIDBKeyFromValue` (`docs/78`: `Vector<JSArray*>`, capacity 0, a hole falls through to a page getter) —
   `typeof indexedDB` is `object` on this build, so an op that opens a database only to drive the key builder is
   reachable; (c) `MutationObserver` — the CVE ordering with a cap of 1 (`Vector<MutationObserverRegistration*, 1>`,
   inert by ownership on paper); (d) `window.open` — a third Document class whose destruction path (Page teardown,
   not `frameDetached`) `docs/86`'s iframe work does not cover. Verify in this order: `cal=1` must still show both
   flavours at the same byte (6/6); an `only=<new op>` arm must beacon the thing it claims (a clone that runs a
   getter, a key that reads a hole, a record that fires, a window with its own `FontFaceSet`); only then four 20k
   arms, recorded in `docs/87`. Do **not** re-enter the console for this.
1. ~~**Give the instrument the three surfaces it cannot reach — a second document, `Animation`'s resolve windows,
   and a worker.**~~ **DONE 2026-10-30 — all three wired, each verified by a window that really fires, and swept:
   498,057 operations, 43,795 in-engine windows, 0 sanitizer reports (`docs/86`).** `research/fuzz-cssom/seq2.html`
   (md5 `2c3f6a900c0b5cb71879f399cbad2faf`, 34 ops = `docs/84`'s 29 + `Fnew-good` + `Fdoc` + `Aanim` + `Aframe` +
   `Aworker`) is built by `build_seq2.py` from `seq.html` at six anchors that must each occur once, and the builder
   re-asserts that the 29 extracted ops are byte-identical. **Wiring, one axis at a time:** `Animation.prototype.then`
   fires **inside** `finish()` (`athen&on=Animation&in=1&ps=finished`), **twice per call** with `ext=0` (`ath=106`
   for 53 ops) and **once** with `ext=1` (`ath=53`) because the window's `cancel()` makes `finishNotificationSteps`
   return at its first line; a second document's `FontFace` resolution runs page script in the **inner** realm
   (`protoInner=true`, `protoParent=false` — measured, so the accessor must be installed by a `<script>` in the
   srcdoc) and its window removes its own frame element **inside `setStatus`**, after which the parent's `f.load()`
   still returns `st=loaded` (`frm=23` parent-side, `caps3`/`caps4`); a blob worker is terminated from inside the
   same frames (`wterm=18` in `WK2`, capped at 64 per arm). **Calibration:** `cal=1` gives the `docs/65` UAF in
   **6/6**, 3 `WRITE` at `:595` and 3 `READ` at `:592`, every fault at `0x6100000469c2` (base+`0x82`) — the 3/3
   against `docs/85`'s 2/4 is the client-order coin flip, and the cal path is structurally untouched (`cal` returns
   before the rounds run; `ATH=0`). **Sweep** (`skip=Rpage,Rnest-link,Fdoc`): `S1..S4` seeds 1-4 × 20k = 83,074 /
   82,870 / 82,905 / 83,060 ops, `then` 5,123-5,340, `ath` 3,416-3,573, `ms≈101 s`, `e=0` everywhere; `GC2`
   (`gc=1`, 60 windows, 400k objects each) reproduces `S1`'s stream exactly (`then=5123&ath=3570`, 83,074 ops) with
   `gcprobe&pre=8/8&post=0/8&h=1`; `C0b` (`then=0`) is the window-axis control. **One limit recorded: `ext=1`
   couples the surfaces** — the outer window kills a frame on nearly every entry, so the inner document's own window
   fires only 134 times in the four arms against **3,507** in `C0b` where frames persist; splitting `ext` into
   `extf`/`extw` is what a run that wants both at once needs. Two instrument defects were found and guarded: a brace
   error in the srcdoc **string** silently disabled the whole second-document surface (the builder now
   `node --check`s the srcdoc script, with its own negative control), and a killed frame stalled the pool (fixed by
   the `!isConnected` sweep, which is also the kill's witness).

   Original text: `docs/85` closes the sequence-shaped sweep on one document: 492,920 operations,
   29,306 synchronous windows inside `CSSFontFace::setStatus` (23,415 of them in the four required arms), four
   seeds, a collection inside 60 of them, and no report. The alphabet's boundary is now the search's boundary, and three of the sites the audits closed *on
   paper* have never been fuzzed: (a) a second document — an iframe whose removal happens **inside** the window
   (`docs/73` measured one tail by hand; a frame gives a second `CSSFontSelector`, a second `FontFaceSet` and a
   separate `Document` destruction path); (b) `WebAnimation` — `docs/74` read 7 `resolve`-with-a-tail sites
   (`finish:867/873`, `setStartTime`, `setCurrentTime`, `finishNotificationSteps`, the pending play/pause tasks)
   and measured two by hand; an `Aanim` family that drives `finish()`/`cancel()`/`play()` from inside the window
   is the sequence shape applied to them; (c) a worker, which is the one script context with its own
   `ScriptExecutionContext`. Verify in this order: the `cal=1` arm must still reproduce `docs/65` (2 of 6 runs at
   `:595`, 4 of 6 at `:592` is what `docs/85` measured — a different ratio means the added ops perturb the
   schedule and must be checked before any null is believed); an `only=Aanim` arm must show the window firing
   inside `Animation::finish` (a `then` hit with the animation's own promise) or the extension is not wired; only
   then four 20k arms again, recorded in `docs/86`. Do **not** re-enter the console for this.

1. ~~**Next: make the fuzzer sequence-shaped, and calibrate it by re-finding the bug this programme already owns.**~~
   **DONE 2026-10-30 — and it found the reason `docs/84`'s null was thin: the old alphabet could not open the
   window at all (`docs/85`).** `research/fuzz-cssom/seq.html` (md5 `6004e0e4e7fe99b22538095e5cbcd7ff`, built by
   `build_seq.py` from `fuzz.html`'s 29 ops **extracted byte for byte**) drives *rounds* of 3–6 ops — one word
   picks how many of six slots run, then exactly four words per slot, so a round is 25 words and the stream is a
   pure function of `(seed, round)`; `model_seq.py` reproduces the page's census **31/31, 830 ops** and two runs of
   `seed=1,n=200` give an identical sorted census. Two ops were added and nothing else: `Fnew-good` (a
   `local("DejaVu Sans")` source that reaches `Status::Success`, the only transition that resolves `loaded` from
   inside `iterateClients`) and `Fdoc` (the `docs/65` arming sequence). **Measured: `then=1` with the old ops and
   2,000 rounds gives `then=0` windows; with `Fnew-good` it gives 582.** Calibration: `cal=1` reproduces `docs/65`
   in **6 of 6** runs — `WRITE of size 1` at `CSSFontFace.cpp:595` in 2, `READ` at `:592` in 4, all at
   `0x6100000466c2` (base + `0x82`), because the client order decides whether the freeing client is last; the
   sampled `Fdoc` op reproduces it too (quarantine on: `heap-use-after-free` `:592`; off: the `docs/65`
   overflow flavour). New mechanism recorded: **the window only exists inside `setStatus` if `face.loaded` was
   materialised first** — without that read, `DOMPromiseProxy::resolve()` defers the fulfilment to
   `m_loadedPromise.get()` in `loadForBindings`, *after* the status write, and the same page does not crash
   (window `in=loaded` versus `in=loading`). Sweep `skip=Rpage,Rnest-link,Fdoc`, quarantine off: `S1..S4`
   (seeds 1–4, 20k rounds) executed 82,065 / 82,097 / 82,190 / 82,438 ops with **0 exceptions**, 5,891 / 5,737 /
   5,821 / 5,966 windows, `done&op=Gsel|Rplain|Rfont|Gsel`, `ms≈80.5-81.2 s`, `access: none`; `GC1` (same stream,
   `gc=1&gcmax=60`) churned 400k objects inside 60 windows with the witness `pre=8/8 → post=0/8` at `h=6`,
   0 reports; `C0` (`then=0`) is the window-axis control. **492,920 ops, 29,306 in-engine windows (23,415 in the
   four arms), 0 sanitizer reports.** Limits in `docs/85` §6: the known bug is skipped by construction, one document, no workers/iframes/
   `Animation`/`structuredClone`/IndexedDB, and it is not a reclaim oracle.


1. ~~**Next: stop auditing, start fuzzing the surfaces the audits kept touching.**~~ **DONE 2026-10-30 — the
   oracle ran 350,477 operations under a seeded in-page fuzzer and returned 0 sanitizer reports, after the
   instrument proved itself on the two crashes this programme already owns (`docs/84`).** New page
   `research/fuzz-cssom/fuzz.html` (md5 `25f86f53a74c48c9809895b15b1067f0`) + `fuzz.css` + `frun.sh`: 29 ops over
   the four surfaces the audits kept finding (8 font-lifecycle, 10 CSSOM rule mutation on `<style>` **and**
   `<link>` sheets, 4 custom-element reaction, 4 `Range`/`Selection`, 3 recalc/GC), exactly **four PRNG words per
   iteration** so the op id and its arguments at index *i* are a pure function of `(seed, i)` and `only=`/`skip=`
   never renumber the stream, beacons `m=<seq>&op=<id>` on every multiple of 200, a final `m=done`, and 29
   `m=census` lines. **Calibration:** `only=Rpage` reproduces `docs/67`'s crash verbatim (`SEGV 0x70` READ,
   `RefPtr.h:87` ← `parsePageSelector:229` ← `CSSGroupingRule.cpp:70`) and `only=Rnest-link` reproduces `docs/72`'s
   (`SEGV 0x4`, `RefCounted.h:46` ← `Ref<StyleRule>::operator=` ← `CSSStyleRule.cpp:229`). A Python
   re-implementation of the PRNG, written from the weight table alone, predicts the failing iteration exactly
   (`seed=1` → 62; measured `n=61` clean with `done&op=none&tot=61`, `n=62` crashes, last beacon `50&op=Gchurn`) and
   reproduces the page's own census **29/29**. **Sweep** (`skip=Rpage,Rnest-link`, quarantine off, fresh port per
   arm): `S1..S4` seeds 1–4 × 20k all reach `done&op=Fdel/Cup/Rmedia/Rfont&ms=14732/14851/14601/14751`, `fc=10..18`,
   `access: none` — twice, in two independent sets of four (ports 9811–9814 and 9821–9824). Census `S1`: **19,500
   executed, 500 skipped (the model's exact 260+240), 0 exceptions**. Extra arms: `then=1` gives **1,059
   synchronous `then` windows** in 20k ops (`k=FontFaceSet`/`Array`/`Function`), `then=1&del=1` adds
   `document.fonts.delete()` on a live face inside the window (264 of them) with identical numbers, `P1`
   (`maxfaces=64`) ends with 66 live faces, `D5`/`D6` run 100k ops (`D6` with 5,557 windows), `batch=1` reaches only
   10,477 ops in 60 s (a `setTimeout(0)` round trip costs ≈4.5 ms, so batching is what makes 20k cheap) — all
   `access: none`. Limits recorded in `docs/84` §5: it is **not** a flip oracle, so it does not assert the `docs/65`
   free ran; one document, no workers/iframes/`structuredClone`; the two known crashes are skipped by construction.
   Tools `research/fuzz-cssom/{fuzz.html,fuzz.css,frun.sh}`, logs `/tmp/F_*.log`, `/tmp/srv9804..9851.log`.
1. ~~**Next: the one spelling of “the container shrinks under the loop” that no sweep has measured — mutation
   through a callee argument.**~~ **DONE 2026-10-30 — 0 of 1,368 calls and 0 of 992 arguments in the 310
   owner-container loop bodies pass the container, and 371 resolved callee bodies were read (`docs/83`).**
   `tools/index-loop-argpass.py` (113 s) matches every handle spelling (bare, `this->`, `&`, `*p`,
   `WTFMove`/`std::move`/`WTF::move`/`std::exchange`, and locals bound to the container): **0 sites, and 0
   aliases exist either**. The 109 arguments that mention a container are element reads (108) or a size (1).
   Callee side: 1,321 calls, 333 resolved (25.2%), 371 bodies (median 67 B), **28 mention the member and 0
   mutate it** in any receiver spelling (`m_<n>.<mut>`, `self.m_<n>.<mut>`, `owner->m_<n>.<mut>`) — the
   widened form of `docs/82`'s `mutator_in_route`; 0 pass it onward (depth 2). Controls, all real: the same
   matcher finds **16** sites across all 1,261 loops (all locals, all read, one `std::size` false positive)
   and an **independent pure-text regex gives the identical 0/310 and 16/1,261**; `iterateClients(m_clients, …)`
   is matched at both call sites; the mutation test is positive **75 times** tree-wide (functions taking a
   non-const container `&` and mutating it) while the 5 calls in the 310 bodies that hit one of those 59
   names are all `create(...)` collisions; `this`/`*this` is passed 2 times in the whole population, both read
   (`CSSFontFace::removeClient` only touches its own `m_clients`; `ReverbConvolver` has no window). The 8
   window rows were read one by one: no window call receives the container. No page or ASAN run — the
   action's conditional has no candidate. Correction recorded: `TYPE \s* NAME` splits an identifier
   (`m_currentCharacter` → type `m_currentCharacte`, name `r`) and invented two `SegmentedString.h` aliases;
   `\s+` fixes it. JSON md5 `c8d46cd36313cbb657a0e1ebf33633ed`, logs `data/index-loop/argpass.*`.
1. ~~**Close the blind spot `docs/81` names — a script window two or more hops away through a callee whose name is
   not unique.**~~ **DONE 2026-10-30 — 37 of 45 owner types resolved through base/member chains (8 explained),
   1,084 calls walked to depth 3 by receiver type (308 resolved, 28.4%), 0 new windows, and the 16 rows a
   name-union over-approximation flags are all collisions (`docs/82`).** `tools/index-loop-resolve.py` (2m07s) over
   the same 10,500 files: unresolved `container_type` **828 → 791 overall, 45 → 8 owner**; the 8 are four C structs
   (`AudioBufferList` ×3, `GstVideoFrame`), two forward-declared `DFA`s, an inline anonymous struct and an owning
   `Vector<Ref<…>>`. Both sink classes walked (literal sinks and interface-client callbacks); the only route in
   310 rows is `ApplicationCacheHost::stopDeferringEvents` → `dispatchDOMEvent()` → `dispatchEvent`, i.e. the loop
   `docs/81` §3 already measured — and `read_after_window` stays 0. The complementary over-approximation (follow
   *every* definition of a call name, so a collision can only add candidates) flags 16 rows, every one read: 15 are
   collisions (`create`, `size`, `x`/`y`/`width`/`height`, `swap`, `matches`, `remove`, `status`/`setStatus`) and
   the 16th is that same AppCache loop, which is the pass's sensitivity control. Recall measured, not assumed:
   `tools/index-loop-resolve-validate.py` scores **59/60** on an automatic multi-hop ground truth (the miss is a
   bare call to an overloaded *static free function*), and its first version scored 0/6 because every sampled
   “caller” contained its own `dispatchEvent(` — recorded as a correction. Three method fixes outlive the run:
   the owner class of an out-of-line constructor whose initializer list ends in `Base(args)` was lost (8 rows), a
   member type may carry `const`/`*`/`&` or a `WTF_GUARDED_BY_LOCK` annotation (20 rows), and a bare-name route
   must consult the owning class *before* `docs/81`'s unique-name gate — that gate had discarded the one true
   route. No page or ASAN run follows: `mutator_in_route` is empty for all 310 rows, so the action's conditional
   has no candidate. Logs `data/index-loop/resolve.json`, `resolve.err`, `resolve-validation.txt`.
1. ~~**The index-loop shape — `for (size_t i = 0; i < m_foo.size(); ++i) { … script … m_foo[i] … }`.**~~
   **DONE 2026-10-29 — 1,261 index loops, 310 on an owner container, 20 with a possible window, 0 that can read a
   shrunk container (`docs/81`).** `tools/index-loop-sweep.py` (23 s) parses every classic `for` in
   `Source/WebCore` (10,500 files) in both directions (49 descending loops, whose init is evaluated once and is
   therefore always a cached bound), takes the container from the **index expression** and links it to the bound:
   **453 re-read**, **194 cached**, **614 scalar/unlinked** (a scalar bound is cached with respect to the
   container — the first version filed these as inert, which was wrong). Of the 310 owner rows, 20 have any
   callee the tool can call a window and **all 20 were read**: 3 `SHRINK-CACHED`, 2 `SHRINK-MUTATED`,
   3 `OWNER-WINDOW`, 12 `LOCAL-WINDOW` (a copy cannot be shrunk), and none of them reads an index after a window
   in the same iteration. The one member-container index loop that really dispatches is
   `ApplicationCacheHost::stopDeferringEvents` (`loader/appcache/ApplicationCacheHost.cpp:333`), whose own
   comment says *do not cache the size* because the dispatch can append to `m_deferredEvents`; measured on the
   oracle, `applicationCache` is live and three events are dispatched from that loop after `load`, and a handler
   re-entering the host from inside the loop (`update()`, `swapCache()` → `InvalidStateError`) changes nothing
   (`access: none`, 0 sanitizer lines, two arms one query string apart). Corrections recorded: a bare-name
   callee index is unusable (34 false candidates through `append`/`at`/`get`); a member type must be resolved by
   owning class (`m_children` was `AccessibilityChildrenVector` in `RenderTableSection`); a descending loop's
   init is a cached bound; the positional test uses the call's start, so a window call's own arguments count as
   "after". Page md5 `9a5f4f3a3e03c584f958ee4af758ce37`, logs `data/index-loop/`.
1. ~~**The helper-template shape — `helper(m_member, [&](Client& c){ … })`, where the loop over the member is
   inside the helper, not at the call site.**~~ **DONE 2026-10-29 — 219 syntactic sites, 42 that reach a real loop,
   0 with a script-capable callback (`docs/80`).** `tools/helper-callback-sweep.py` (28s) indexes the
   iterate-a-parameter-and-call-a-parameter helper population over `Source/WTF` + `Source/WebCore` (11,396 files;
   37 names / 42 variants) and joins it to every call site that passes a member in the iterated position:
   **219** `helper(m_member, [lambda])` sites across **24** names, **42** of which resolve to a helper that really
   iterates one parameter and calls another inside that loop (9 helper names), **11** of them `iterateClients` with
   a `copyToVectorOf<Ref<Client>>` snapshot (`A10` = `CSSFontFace.cpp:591`, `docs/65`'s loop) and **31** raw. The 31
   raw rows decompose: **7** are `.mm` files absent from `Sources.txt`/present in `SourcesCocoa.txt`, **1** is
   `ENABLE(WIRELESS_PLAYBACK_TARGET)` code (`WebKitFeatures.cmake:264`, `PRIVATE OFF`), **2** are the rendering
   helper iterating `parent.normalFlowLayers()` (a computed child list, not the member), and the other **21** have
   pure value/predicate callbacks (`is2D`, `isCompleted`, `matches`, `ended`, `asValidatedFormListedElement`,
   `Ref`/`RefPtr` copies) — **0 with a script-capable callback**, including every raw row over a page-reachable
   container, so the action's conditional candidate run has nothing to measure. One reachability run is recorded
   instead (§7 of `docs/80`): a `<track>`-created `TextTrack` really has two clients, one `setMode()` drives both
   (`A change=1` + `A terr=1 rs=3` with `GET /nope.vtt 404` in the server log) and `access: none`. The method
   spelling is the guarded one:
   **77** `m_member.<forEach|map>(lambda)` sites, 51 of 52 `.forEach` being `WeakHashSet::forEach`
   (`WeakHashSet.h:159-171`: snapshot + `contains` re-check) and 25 `.map` being `Vector::map`; 43 client-typed, all
   client families resolved (`HTMLTrackElement::textTrackModeChanged` → `scheduleLoad()`,
   `HTMLMediaElement::*` → `scheduleChangeEvent()`, `FontFaceSet::faceFinished` → `docs/65`). New structural fact:
   the `contains` guard is itself a **post-callback read of the owner** (a `<track>` TextTrack has two clients), so
   the guard is safe only where the owner is Ref-held — `TrackListBase::m_inbandTracks` + `HTMLTrackElement::m_track`
   there, nothing for `CSSFontFace`. Corrections: `vector-local-sweep.py`'s `CALL_RE` cannot match a qualified call
   (`WTF::map(…)` — the `:` is in its lookbehind), so it under-counts 42 sites as 18; helper definitions must be
   indexed in `Source/WTF` too; and member types must be resolved across files. Logs `data/helper-callback/`,
   pages `research/helper-callback/`.
1. ~~**The same shape in *members* — `Vector<X*> m_foo` of a heap C++ object, appended in a loop and read after a
   script window; plus `HashMap`/`HashSet<X*>` locals.**~~ **DONE 2026-10-29 — 49 member declarations, 16 push-in-loop
   rows, 0 with a script window, 5 hash-local rows read, and the one unrooted pointee measured (`docs/79`).** New
   tools `tools/vector-member-sweep.py` (2m15s) and `tools/member-iterate-sweep.py` (20s). Members: 49 declarations
   carrying a raw pointer (43 of capacity 0), 69 push sites, 16 in a loop/recursion, 5 same-class rows with a read
   after the push (a 6th is a cross-class name collision, and 3 of the 16 rows are collisions because the first pass
   joins by member *name*), **0** with a JS entry point in the interval. Hash locals: 31 pointer-carrying, 26
   inserted in a loop, 14 read after, **0** sinks. The reverse direction, which is the real member shape: 1,599
   member containers, 1,070 range-fors, 512 attributed rows, 38 with a callback-shaped call, 8 client-typed — every
   one guarded by a copy (`Document.cpp:8589`), a two-buffer swap (`HTMLVideoElement.cpp:661`), a `RefPtr`/`WeakPtr`
   snapshot with a null check, or no script at all. The one member whose pointee is **not** separately rooted —
   `CollectionIndexCache::m_cachedList` (`Vector<NodeType*>`, cap 0, push `:55` → deref `:134` across functions) — is
   measured with 6 quarantine-off arms (remove / GC churn / document-level / `childNodes` / detached root): after a
   removal `c[0]` answers the live node (`d1`) where a stale list would answer the detached one, `access: none` 6/6,
   0 sanitizer reports in 12 logs. Correction recorded: `ChildNodeList::willValidateIndexCache()` is empty
   (`ChildNodeList.h:78`) yet its cache is still invalidated, by the per-node ancestor walk. Logs
   `data/vector-member/`, pages `research/vector-member/`.
2. ~~**Sweep the drop for the `Vector<T*, N>` *shape* — a raw object pointer in a local vector that overflows
   to its heap buffer inside a function that runs script between the push and the use.**~~ **DONE 2026-10-29 — 164
   declarations, 93 that grow, 40 that can cross an inline boundary, 0 new sites (`docs/78`).** New tool
   `tools/vector-local-sweep.py` over 10,500 `Source/WebCore` files, two passes (function → has-a-sink, so a call in
   an interval can be resolved one level deep; then local pointer/cell vectors that are appended inside a loop **or by
   recursion** and read after the push). Funnel: 164 → 125 with a push → 93 that can grow → 67 with a read after the
   push → **1** with a JS entry point in the interval, and that one is docs/77's `inputObjectStack`. The GC-element
   population is exactly **4** in the whole tree: `inputObjectStack` (closed), `mapIteratorStack` +
   `setIteratorStack` + `mapIteratorValueStack` (three `Vector<…, 4>` whose keep-alive is the line *before* each push,
   `:2646`/`:2668`/`:2692` — **measured**, a nested `Map`/`Set` clone with 8 entries in the heap buffer, GC at depths
   6-7, clone intact, plus an `n=4` capacity control with the same result), and
   `IDBBindingUtilities.cpp:257` `Vector<JSArray*>` (capacity **0**, i.e. always heap, `:228` push → `:232`
   `getIndex()` which falls through to `get` on a hole — **measured**, GC inside `createIDBKeyFromValue`
   (`gcprobe h22/h23/h24 collected`) and the key still reads back `depth=8 bad=0`; safe because the function
   recurses, so every appended array is also a live frame's `value`). **One belief corrected: `typeof indexedDB` is
   `object` on this build** — `UnifiedWebPreferences.yaml:3139` defaults
   `IndexedDBAPIExposeIndexedDBToWindowOrWorkerEnabled` to `false` on `PLATFORM(PLAYSTATION)`, and it is not in
   effect, so the IDB row is page-reachable after all. Three blind spots recorded: `getIndex` is a getter path a
   token scan misses, recursion is not a `for`/`while`, and a vector declared in one function and filled in another
   is invisible to any per-function net (the IDB row) — start the next sweep from
   `data/vector-local/all_locals.json`, not the funnel. Pages `research/vector-local/{vecmap,idbkey,surfaces}.html`,
   logs `data/vector-local/`, `access: none` in all 9 runs.
1. **Console, blocked on the operator (and still the only hardware step):** the `docs/65` "Attempt 9" status flip
   (`mode=none&npre=0&npost=0&quiet=2&doc=zzd&docn=2`, page md5 `f0d1b337aaad040b5f1824a162295759`) needs no JS
   allocation in the window and no sanitizer, so it is the one grooming oracle that can run on hardware — and the
   `docs/76` abort (`flood=none&n=0`, page md5 `8bba4a1190665f9a67830b1882dfaa99`) is a sanitizer-free case whose
   release behaviour is *predicted* (§5 of `docs/76`) but not measured. Both need the Guide app restarted by hand
   first. Never touch update-related anything on the console.
1. ~~**Sweep the drop for the `CachedString` shape — a raw `JSValue`/`JSCell*` held in a plain C++ container across
   a GC.**~~ **DONE 2026-10-29 — several thousand declarations, 147 member rows, one unprotected site, and it is
   the one docs/76 closed (`docs/77`).** New tool `tools/jsvalue-sweep.py` over both trees (15,453 declarations;
   147 members = 31 WebCore + 116 JSC). WebCore: `CachedString::m_jsString` (closed), `m_nonCell` (non-cell by
   construction), 24 stack temporaries, and three heap-stored fields whose owners are compiled out — measured in one
   run: `ShadowRealm` not in `globalThis`, `CSS.paintWorklet` undefined, `navigator.xr` and `window.internals`
   undefined. JSC: 33 rows marked by an explicit `visitor.*` line, the rest nested/VM-owned/stack/compare-only. The
   one real window found is `CloneSerializer::inputObjectStack` (`Vector<JSObject*, 32>`, heap buffer past 32, an
   own getter running inside the walk via `getProperty`) — and it is safe because every walked object is already in
   `m_objectPool`, a `MarkedArgumentBuffer` (`:900`, appended at `:2578` before the `:2587` push). Proven with a new
   sanitizer-free GC witness (a `WeakRef` decoy from a previous job): `gcprobe 32..39 collected` inside the
   serialization, clone still correct (`bad=0`); `churn=0` → `gcprobe alive`, `del=1` → `verify bad=1 first=39`.
   Page md5 `e52a6f94cb10a83f2c253c163a1998cf`, `research/jsvalue-stack/`, logs `/tmp/run_{A5,B,C,D,E,S}.log`.
1. ~~**Replay the `docs/65` reclaim technique on `CachedString` (`docs/62`/`63`) — the only other live
   memory-safety defect in this drop.**~~ **DONE 2026-10-29 — negative, and the wall is the allocator's, not a
   `Ref`.** `docs/76`: the freed object is a 16-byte `JSString` in `stringSpace`, an `IsoSubspace` whose only cell
   type is `JSString`, so the reclaim is same-type by construction — measured with four floods at three size
   classes (stream `{}`s at 64 B, a page `{}` literal at 16 B, arrays) and a `freek=0`/`nbuf=0` pair of controls.
   The first post-sweep string always takes the cell (`L=6`, `C=70`, 13/13; `v=FL1000` in 11 of them) and the value
   read is that
   string's content; nothing else ever takes it. The post-free fields are the zap word (`HeapCell.h:54-59`), so
   there is no byte to plant. The no-flood arm is a deterministic WebProcess abort (`reportZappedCellAndCrash` ←
   `jsCast` ← `asString` ← `strictEqual`), 6/6 on the final revision — a DoS, not a primitive. This also corrects
   `docs/63`'s explanation (key-before-value ordering) to the real cause (subspace).
1. ~~**Sweep the `setLineDash` `Vector<double>` spray on the write path (`docs/65`).**~~ **DONE 2026-10-29.**
   Six runs, p = 16/20/22/24/28/32, quarantine off. Only p=24 (192 bytes) moves execution from the `:592` client
   read to the `:595` status write; every other size is identical to the no-spray control. No `RECLAIMED` beacon:
   `setLineDash`'s converter temporary wins the chunk and is destroyed before the write. Table and outputs in
   `docs/65`, "Sweep 1". The same run found the reclaim that holds (a post-free `new FontFace` survives with
   `status="loaded"`, pre/post control inside one process).
1. ~~**Make the occupant's bytes ours, in a 192-byte plain-`fastMalloc` container that is still alive at the write.**~~
   **DONE 2026-10-29 — negative.** Six 8-bit `StringImpl` sizes (108/144/192/200/224/256 B, chars at +24), with a
   poison pointer planted at `m_clients` (object+0x58, measured from the binary) so that ownership would be proven
   by a deref of `0x4141414141414141`: no run dereferences it, in a quiet window or after six candidate triggers.
   Only a `CSSFontFace` allocated by `new FontFace` owns the slot. The allocator is not the obstacle (plain
   `fastMalloc` + `USE_SYSTEM_MALLOC`). Its explanation ("the free happens inside the `new FontFace` call, so every
   JS allocation is pre-free") was **wrong** — see "Attempt 3" — and its sizes/poison positions were 4 bytes off
   (`StringImpl` header is 0x14). Also: a fake occupant cannot survive `setStatus` (it always reaches the timer,
   `Timer.cpp:469`), so the "no report + read back a Status" criterion is unreachable — use a poison deref instead.
   `docs/65`, "Attempt 2".
1. ~~**Move the free, not the container.**~~ **DONE 2026-10-29 — negative, and the premise was wrong.** The free
   is not movable: it is the last statement of `CSSFontSelector::buildCompleted()`, already inside the window, and
   `insertRule`/layout would only reproduce the same site. The real obstacle is the allocation that follows it
   (`docs/65`, "Attempt 3"). See the next action.
1. ~~**Warm every lazily-compiled function used in the window, then place the container.**~~ **DONE 2026-10-29 —
   the container wins, and the asked-for verification was wrong.** With `warm=1` the 172-character `atob` string owns
   the chunk; the requested `0x4141…` deref is unreachable because `copyToVectorOf(m_clients)` runs **before** the
   callbacks. Replaced by a byte-level differential: object+0x87 = `0x41` → `fontLoadTiming()` `RELEASE_ASSERT`
   (`:568`); object+0x86 = `0x41` → `Timer.cpp:469`. Controls: no `warm` → 180-byte JSC vector takes the chunk;
   180-character container → `:592`. `docs/65`, "Attempt 4".
1. ~~**Audit the drop for the same missing-guard pattern where the tail after the callback is not a timer.**~~
   **DONE 2026-10-29 — and it found the pointer read, in a place the action did not predict.** `docs/66` has the
   table: 17 client-set iteration families, the drop's `WeakHashSet::forEach` re-reads `this->m_set` where
   upstream snapshots `RefPtr`s, and only three families can run script from a callback (`CSSFontFace::Client`,
   `CSSFontFaceSet::FontEventClient`, `GamepadProviderClient`). No iterating object is freed inside its own
   script callback except `CSSFontFace`. But the *argument* handed to the next client
   (`CSSFontFaceSet::fontStateChanged` → `FontFaceSet::faceFinished(face, …)`) is the freed face, and it
   dereferences `face.m_wrapper` at object+0x68 — criterion 2, measured, `docs/65` "Attempt 5".
1. ~~**Turn the `m_wrapper` read into something observable, or into a write.**~~ **DONE 2026-10-29 — negative on
   observability, positive on capability.** A fake `WeakPtrImpl` written inside the reclaimed container at
   `A+0x90` (`A` = `0x610000010540`, measured) is read by `existingWrapper()` without faulting (10 runs, 0 faults,
   while the same page with `m_impl = 0x1000` faults at `0x1008` in 8/10), so the engine receives a pointer we
   choose — `0x1000` and `0x4141414141` both returned. Nothing dereferences it: `0x4141414141` produced no shadow
   report (4/4), and the drop's three `existingWrapper()` uses are a bool test, a hash key (`take()` does not ref
   the pointer), and `adopt()` behind a `RefPtr`. No JS-observable, no write. `docs/65`, "Attempt 6". Corrections
   recorded there: `ov=` is inert in `atob` mode (Attempt 5 had no witness; use `bidx=&b=`), the reclaimed
   container is 192 bytes at `0x610000010540`, and a "region" printed next to a fault is not necessarily the
   container — check its size and allocation stack.
1. ~~**Weaponise the live-face status flip (the primitive that does survive).**~~ **DONE 2026-10-29 — the flip is
   real, permanent, and an API-level lie; it is not memory-unsafe.** `mode=fnt&src=bad&npre=4&npost=4&warm=1&quiet=2`
   reads `FACE i=4 tag=post status=loaded` with `SUM ... 4:post:loaded:pending` while all four pre-free faces read
   `unloaded` (6/6 runs); the twin face built one statement later with the same `local("NoSuchFontName")` goes to
   `error` and rejects its promise when both are `load()`ed (`POSTLOAD zzpost0 status=loaded` /
   `POSTLOAD zzpost1 status=error`, 4/4). `check('1em zzpost0')` returns **true** and `document.fonts.load()`
   resolves with the face, while the family measures exactly like a nonexistent one (292 vs 292; DejaVu 296) — the
   face owns no `Font`. No ASAN in six `use=1` runs: the null is filtered at `CSSSegmentedFontFace.cpp:136` and
   cached in `CSSFontAccessor`, so `FontRanges::fontForFirstRange()`'s `ASSERT(font)` is unreachable from here.
   The write is final because `pump()` only reaches `Failure` from `Loading`/`TimedOut`. `docs/65`, "Attempt 7".
   Two corrections recorded there: the loop's client snapshot is taken before the callbacks, so the *new* face's
   promise is never resolved (pending even when the face really does load — `src=good`), and `FACE picked` reads a
   live face because `addFontFaceRule` adopts the wrapper onto the rebuilt face (`CSSFontSelector.cpp:234`).
1. ~~**Put the flip on a *document* face — the engine-owned case — and see whether it survives the rebuild.**~~
   **DONE 2026-10-29 — positive, and it corrected the action's premise.** A `CSSFontFace` created by
   `addFontFaceRule` while rebuilding an existing `<style>` sheet, with `src:local("NoSuchFontName")` and no JS
   object of ours in the window, reads `status=loaded` while its twin (`zzd1`, one rule later, same sheet) reads
   `unloaded` — 5/5 runs; `check('1em zzd0')` true, `document.fonts.load()` resolves with it, 40 px width 292 =
   nonexistent (DejaVu 296), 9/9 runs `access: none`. Controls: same rules staged *after* `t` never flip (2/2),
   `noload=1` (no free) never flips, a new `<style>` flips the same as `insertRule`, and with `docn=4` only the
   **first** staged face is written. Corrections: `buildCompleted()` frees at its **last** statement
   (`m_cssConnectionsPossiblyToRemove.clear()`, `:167`), after its staging re-adds, so a document face created in
   the *same* rebuild is allocated **before** the free — arming the flip needs two rebuilds. The flip survives an
   ordinary style recalc (`DFACE2`) but not the next `createDocumentResolver()` (`DFACE3` unloaded). `docs/65`,
   "Attempt 8".
1. ~~**Shrink the flip to a page with no JS allocation in the window, as the console grooming oracle.**~~ **DONE
   2026-10-29 — positive, 9/9 with `strs=0 faces=0`.** `mode=none&npre=0&npost=0&quiet=2&doc=zzd&docn=2` still reads
   `DFACE zzd0:loaded zzd1:unloaded` (3/3), `check()` true, `DFACE2` loaded, width 292 = nonexistent, `access: none`
   in 12/12 runs. The action's `warm=1` twin had to be replaced as a knob: `warm=1` warms `alloc()`, which
   `mode=none&npost=0` never calls, and is provably inert (1/1). The real in-window JS allocation is JSC's lazy
   compile of the rule-builder arrow; new `docwarm=1` (pre-call `DOCRULE(0)`) moves it out, and the flip fires
   **both** ways (3/3 compile-in-window, 2/2 compile-out) — it is not a thief, so the console page needs no warm-up.
   Ordering control `docat=end` fails 2/2, and its `FACE picked status=loaded` is now explained: `FontFace::status()`
   reads `m_backing->status()` and `adopt()` re-points `m_backing`, so that line is family `t`'s *live* new face taking
   the write — an independent witness of "only the first staged face is written", on a different API than `DFACE`.
   `docmode=sheet` flips 2/2, `noload=1` never flips. Page md5 `f0d1b337aaad040b5f1824a162295759`; `docs/65`,
   "Attempt 9", logs in `data/cve-2026-43715/attempt9/`.
1. ~~**Use the flip as a sanitizer-free grooming oracle, then take it to the console.**~~ **LOCAL HALF SUPERSEDED**
   by the item above (the document-face flip needs no JS containers at all); the console half stays blocked on the
   operator restarting the Guide app. Original text: the flip is the first JS-side
   witness that the stale write landed in our allocation — no ASAN, no fault address, no leak. Verify locally with a
   page that only reports `FACE i=.. tag=post status=..` (no `use=`, no `postload=`), then re-run the same page
   against the console once the Guide app has been restarted (blocked on the operator), scoring from the page's
   beacon posts. If the flip fires on hardware, heap grooming for the same-type reclaim can be tuned there.
1. ~~**Control a field of the same-type reclaim instead of its identity.**~~ **DONE 2026-10-29 — the
   capability is real, the stated verification is unreachable.** `ffld=ur` on the first post-free
   `new FontFace` sets `unicodeRange` from CSSOM on the object that also reads `status=loaded` (the stale
   write): `FREAD ... status=loaded ur=U+41`, and the engine's own filter obeys it —
   `document.fonts.load('1em "zzpost0"','A')` → `n=1`, `...'M'` → `n=0` — against a no-drive control that
   gives `ur=U+0-10ffff`, `A n=1`, `M n=1` (`F1` vs `F2`). `ffld=fam` does the same for `m_families`
   (`FREAD fam=zzfld`, old name resolves to `n=0`/`n=0`) (`F4`). **The ASAN half cannot happen:** CSSOM
   parses into `Vector<UnicodeRange>` (`UChar32` pairs), tags and an engine-owned `RefPtr<CSSValueList>`,
   so no CSSOM value is an address; and a *fake* occupant has no JS handle to drive, because
   `FontFace::m_backing` is a `Ref` (`FontFace.h:109`) — measured with `entry=then`, the setter returns
   `ok` and writes nothing into the container (`E2`: `STR2 pre nz=0` / `STR2 post nz=0`). `docs/65`,
   "Attempt 10". Offsets reconfirmed: variant `Ref` +0x08, variant index +0x10, `m_sources` +0x48/size
   +0x54.
1. ~~**Settle the `face.load()` hang, then use it as an oracle.**~~ **DONE 2026-10-29 — there was no hang, and the
   oracle is void.** `quiet=2` makes the `then` getter silence the page on every hit (including the one inside
   `face.load()`), and `EXIT=124` is how every `run_nq.sh` run ends (`H1` completes and still reports 124); with
   `unquiet=1` the full sequence appears (`SELFLOAD ok st=loaded`, `SUM`, `done2`) and `H2` (only `unquiet`
   removed) reproduces `G2` exactly. `face.load()` from the scan cannot reach the slot: `H4` plants
   `m_status = Failure`, which would have made `pump():646` return at once and read `error`, and still gets
   `status=unloaded` → `st=loaded`, because `FontFace::m_backing` is a `Ref` and the freed face has no wrapper
   (`H3`, `mode=none`, is identical). The `bidx=110&b=4` contradiction is resolved too: `pump():686` is
   `setStatus(Success)` in the `Success` branch (addr2line over all seven `setStatus` call sites in the shipped
   lib), which requires the live `m_status`, so `:646`/`:685` are pre-free reads and `:595` writes over any plant
   before it is read. Sweep `S0`-`S5`: `+0x38`, `+0x48`, `+0x54` (even `m_sources.size() = 1`) and `+0x58` are
   inert; only `+0x87` is read (`S5`, the ownership witness at `:568`). After the free the object is read at
   exactly two fields (`+0x87/+0x88`, `+0xb0`) and `+0x10` is unreachable from this container (it is inside the
   `StringImpl` header). `docs/65`, "Attempt 11", logs in `data/cve-2026-43715/attempt11/`.
1. ~~**New audit, new subsystem: find the CVE-2026-43715 *pattern* somewhere else.**~~ **DONE 2026-10-29 —
   26 rows, 0 with a reachable free, and one correction to the method that outlives the audit.** `docs/69`
   sweeps all 309 `.cpp` files in `Source/WebCore/css/` + `dom/` (123 raw rows, 18 with a direct
   `m_`/`this->` use in the tail; 26 read in source): every post-callback member use is protected by a
   `Ref`/`RefPtr` local, a `GCReachableRef`/`Ref`-held container, or the object is not script-freeable
   (`Document`, `ScriptExecutionContext`, an owner-held tracker), and 4 of the 26 rows are not even script
   sinks (`reject(Exception)`, `resolve()`, a primitive, or a deferred `postTask`). The correction: a
   `then` accessor on **`Array.prototype`/`Object.prototype`** is a synchronous script window inside this
   drop's promise resolutions — measured on the oracle, `THENARR hit=1 len=1` firing *before* a beacon on
   the next source line (`FontFaceSet.cpp:215`), and a second hit with `len=undefined` for
   `document.fonts.ready`'s `resolve(*this)`, whose very next statement is `m_backing->addFontEventClient(*this)`
   (`:83-84`) — which survived a DOM wipe from inside the window (`size` 2→0, no ASAN, `A4`/`A5`). So the
   sink set for this pattern is events **and** `resolve(<object>)`, not just events. Original text: audit
   `Source/WebCore/css/` and `Source/WebCore/dom/` for it: take every function
   that calls `resolve(`/`reject(`, `dispatchEvent(`, `invokeCallback`, or a `getProperty`-style getter, and check
   the statements *after* that call for a member access. Verify: a new `docs/69` with one row per candidate
   (file:line, which call runs script, what is used afterwards, can the callback free it), at least 20 rows, and
   for the first candidate whose free is reachable a page + an ASAN run under `run_nq.sh` scored from the beacon
   log. If no candidate survives the read, say so in `docs/69` and propose the next subsystem.
1. ~~**Take the pattern to `Source/WebCore/html/`, where the free is a node or a media player.**~~ **DONE
   2026-10-29 — 323 files, 28 synchronous dispatch sites, 0 with a reachable free (`docs/70`).** 65 raw rows
   (both sweeps: `html` 54/23 files, `html/canvas html/forms html/parser html/shadow html/track` 11/4 files),
   every dispatch site read in source; the 30-grep cross-check gives 23 real call sites at top level + 5 in
   the subdirectories (the sweep is not recursive, so `html/canvas` was nearly missed). Three structural
   guards, all named in `docs/70`: `JSDOMWrapper::m_wrapped` is a `Ref` (a JS-named node cannot be freed by a
   listener); where the target is wrapper-free WebKit already added `makePendingActivity`/`Ref protectedThis`/
   `event->setTarget(Ref { *this })`/`RefPtr` callers/`UniqueRef`/`WeakPtr`; and media events are queued, not
   synchronous (`setReadyState` only `scheduleEvent`s), which removes the "free the media player inside its own
   callback" class. Measured: `V1` (`k=val&wipe=1`, page md5 `47d77a704283ff0fc5cb949182172b1e`) shows the
   `invalid` teardown executing *inside* the window (`HIT2 kids=0`) and surviving because
   `ValidatedFormListedElement::checkValidity` holds `Ref protectedThis { element }` (`:123`); `P0`
   (`k=pop`) shows `showPopover()` **does not exist in this build** (`CALL err=TypeError`) — the IDL gates it
   on `PopoverAttributeEnabled` and `defaultPopoverAttributeEnabled()` is `false` on every non-Cocoa port
   (`WebPreferencesDefaultValues.cpp:289-297`), so the only unguarded post-dispatch `this` use in `html/`
   (`showPopover`/`hidePopoverInternal`) is unreachable, not merely guarded. Also found: the one unguarded
   media tail, `HTMLMediaElement::dispatchEvent(Event&)` (`:6594`), has **no callers** — dead code. Logs
   `data/html-pattern/`.
1. ~~**Next: extend the sweep's sink list and audit `html/parser/`.**~~ **DONE 2026-10-29 — 18 rows, 5 real
   script windows, 0 with a reachable free (`docs/71`).** `tools/pattern-sweep.py`'s `NAMES` now carries
   `executeScript`/`executePendingScript`/`evaluate`/`JSC::call`/`performMicrotaskCheckpoint`/
   `runScriptsForPausedTreeBuilder`/`execute`; the re-sweep of `html/parser html/track html/canvas` gives 18 rows,
   3 of them artifacts (`evaluate` matches the CSS media-query evaluator; `execute` splits an argument list) and
   5 genuinely new: the three `performMicrotaskCheckpoint` calls (`HTMLDocumentParser.cpp:229`,
   `HTMLScriptRunner.cpp:111`, `:246`), `executePendingScript` (`HTMLScriptRunner.cpp:115`) and the
   `runScriptsForPausedTreeBuilder()` call (`HTMLDocumentParser.cpp:265`). A grep for every JS entry point in
   `html/parser/` returns nothing outside those functions, so the surface is closed. Why nothing is freeable: the
   parser is `RefCounted` and every entry point holds `Ref<HTMLDocumentParser> protectedThis` (`:130/:209/:375/
   :410/:542/:574/:610`), so the parser and its `unique_ptr` members (`m_scriptRunner`, `m_treeBuilder`,
   `m_input`, `m_preloadScanner`, `m_parserScheduler`) cannot be freed in the window; the `PendingScript` is held
   by the caller's `Ref` at both execution sites (`HTMLScriptRunner.cpp:165`, `:199`) and by
   `Ref<PendingScript> protectedThis` in `notifyClientFinished` (`dom/PendingScript.cpp:67`). What a script *can*
   do is detach the parser, and every post-window `document()` then dereferences a null `WeakPtr` — a crash, not
   a freed-object read. **And the one upstream difference in the CVE shape is unreachable:** Sony's
   `LoadableScript::notifyClientFinished` (`dom/LoadableScript.cpp:52-57`) iterates `copyToVector(m_clients.values())`
   of **raw** `LoadableScriptClient*` where upstream iterates `WeakPtr<LoadableScriptClient>` (upstream's
   `LoadableScriptClient` is `AbstractRefCountedAndCanMakeWeakPtr`; the change is `a55f0e9fc70c`, smart-pointer
   adoption, not a CVE fix) — but a `LoadableScript` is per-element (`ScriptElement.h:143`, created at
   `ScriptElement.cpp:332/:373/:394/:417`) and `prepareScript` runs once per element (`m_alreadyStarted`,
   `:186`/`:218`, never cleared), so the set holds at most one client and the loop cannot walk into a freed one.
   Measured 3/3 (`docs/71`, `research/html-pattern/parser-window/`, logs `data/html-pattern/parser-window/`):
   the nested script executes inside `document.write` inside the load callback, `document.open()` from an
   executing script returns without throwing, a re-inserted `<script src>` never re-runs while a fresh element
   with the same URL does, an executing element can be removed and the write still works, a deferred script whose
   element was removed still runs (`conn=0`), and the parser accepts **22 nested** write→parse→script levels
   before `cMaxWriteRecursionDepth = 21` (`Document.cpp:385`) silently drops the 23rd; `access: none` in every
   run. Correction to `docs/66`: its 17-family table is missing `LoadableScriptClient`/`PendingScript`, which
   *does* run script from a client callback.
1. ~~**Then `style/`, per the original proposal:** rule-mutation frames holding a raw `StyleRule*` across
   `RuleMutationScope`, where `didMutateRules()` can reach `CSSFontSelector::buildCompleted()`.~~
   **DONE 2026-10-29 — the premise was false, and the family has a measured crash instead (`docs/72`).**
   `style/` has **no script sink at all**: 14 sweep rows in 8 files (8 media/container-query `evaluate`, 6
   numeric/style `resolve`) and **0 `JSC::` hits in 40 `.cpp` files**. The frames live in `css/`, 31
   `RuleMutationScope` sites in 8 files, 24 of them `Ref`-backed (the exceptions are `MediaList`'s raw
   `m_parentRule` and the Typed OM raw local); their tail is `didMutateRules` →
   `Scope::didChangeStyleSheetContents` → `scheduleUpdate` → `clearResolver()` + a 0 s timer
   (`StyleScope.cpp:703-715`), and `buildCompleted()` has exactly **one** caller,
   `Scope::createDocumentResolver()` (`:121`) — a CSSOM mutation never rebuilds the font selector. What the
   frames *do* have: `CSSStyleRule::insertRule` binds `StyleRule&&` to the wrapper's rule before the call
   (`CSSStyleRule.cpp:225`), the `RuleMutationScope` ctor inside `prepareChildStyleRuleForNesting` copies the
   contents and reattaches every wrapper to the copies, so `rules[i].ptr() == &styleRule` never matches,
   the helper returns `{}` and `m_styleRule = *styleRuleWithNesting` (`:229`) dereferences null — **SEGV
   0x4 in `RefCountedBase::ref`, 4/4** (one or two `<link>`s, top-level or `@media`-nested), against
   **0/2** inline-`<style>` controls with the same call and rule, plus two `CSSMediaRule.insertRule`
   controls that pass. A `<link>` sheet is copied even with one client (`isInMemoryCache()`, boxed by the
   `case=4` witness: sheet 1 grows, sheet 2 does not). DoS only: the `Ref` is null by construction and the
   stale reference is only compared, never dereferenced. The Typed OM frame that *does* keep a raw
   `StyleRule*` (`DeclaredStylePropertyMap::setProperty`) was measured too: the write goes to the pre-copy
   rule — `A` unchanged, `B` (sibling sheet) gains `margin-top: 13px` — because the memory cache pins the
   original, so no UAF. Latent, not live: `CSSStyleRule::reattach` does not recurse into nested wrappers
   while `CSSGroupingRule::reattach` does, but a nesting sheet is never cacheable
   (`StyleSheetContents.cpp:116-131`, `HTMLLinkElement.cpp:491-492`), so it is never copied.
   `research/style-cssom/`, logs `data/style-cssom/`.
1. ~~**`page/` and `loader/` with the extended sink list — the last two directories with JS entry points.**~~
   **DONE 2026-10-29 — 117 rows, 62 JavaScript windows in 40 functions, 0 with a reachable free; one tail
   measured safe (`docs/73`).** The reason is structural, not per-site: `dom/Event.h:194` holds
   `RefPtr<EventTarget> m_target` (and `:192` `m_currentTarget`), cleared only in `initEvent`, which returns
   early while dispatching — so a listener cannot free the object it is dispatching to; node dispatches add
   `Ref protectedNode` (`dom/EventDispatcher.cpp:155`, from `Node::dispatchEvent`, `dom/Node.cpp:2446`). And a
   frame cannot be destroyed by DOM removal: `HTMLFrameOwnerElement::disconnectContentFrame` holds
   `RefPtr frame` across `frameDetached()` (`html/HTMLFrameOwnerElement.cpp:82`), which itself holds
   `Ref protectedFrame { m_frame }` (`loader/FrameLoader.cpp:2972`). The 3 observer-callback rows
   (`IntersectionObserver::notify`, `PerformanceObserver::deliver`, `ResizeObserver::deliverObservations`) pass
   `*this` to JS and then use a raw `ScriptExecutionContext*` — inert because
   `InspectorInstrumentation::didFireObserverCallback` is `FAST_RETURN_IF_NO_FRONTENDS`
   (`inspector/InspectorInstrumentation.h:1726`); with a frontend attached it would read. 12 rows are not
   sinks (`EditorCommand::execute`, `ScheduledAction::execute`, `MediaQueryEvaluator::evaluate`), 12 cannot
   run (touch 7, drag 2, device-orientation 2, content-filter 1 — `WebKitFeatures.cmake:147/158/161/240`
   default OFF and `OptionsPlayStation.cmake`'s only override in this neighbourhood is `RESOURCE_USAGE` at
   `:221`). Neither directory can call JSC directly: `page/` has **no** `JSC::call`/`JSC::evaluate`
   (81 `JSC::` lines / 92 tokens, all types/helpers) and `loader/` has 0 `JSC::`; the only direct entry is
   `DocumentLoader.cpp:2573` (content filter, compiled out). **Measured**: the one risky tail,
   `FrameLoader::loadInSameDocument` → synthetic owner-element `load` → `m_client->didFinishLoad()`, with a
   cross-origin iframe doing `location.hash` and the parent removing the iframe inside that dispatch:
   `access: none` / `SUMMARY: none` 3/3, and the `rm`/`div`/`none` beacons show the window really fired
   (`LOAD n=2` after `Q nav`, one document load) and the removal really detached the frame (`Q alive2` present
   in the two controls, absent in `rm`). `research/page-loader/`, logs `/tmp/pl_*.log`.
1. ~~**Next: the whole-tree `resolve(<DOM object>)` sweep — the one script window that is not an event.**~~
   **DONE 2026-10-29 — see the entry below (`docs/74`).** Original text: `docs/69`
   measured it inside `css/`+`dom/` (`FontFaceSet.cpp:215`; `document.fonts.ready`'s `resolve(*this)` at `:83`,
   whose next statement is `m_backing->addFontEventClient(*this)`), and `docs/70`/`71`/`72`/`73` show that every
   *other* window in this drop is an event dispatch or an observer callback, both of which hold their object
   alive. So the remaining surface is exactly `resolve(`/`reject(` whose argument is a `Ref`/`RefPtr` to a DOM
   object. Sweep all of `Source/WebCore/` (both the `resolve(` argument form and the `Promise::resolve` /
   `DeferredPromise` spellings), keep the rows where the promise is settled *synchronously* inside the C++
   frame that owns the object, and apply the `docs/69` test: can a `then` accessor on the *returned* promise
   run script before the next statement, and can it free the object that statement uses?
   Verify: a new `docs/74` with one row per candidate (file:line, the resolved type, whether the settlement is
   synchronous in that frame, what the next statement uses) and a verdict count; for the first row where the
   free is reachable, a page plus an ASAN run under `run_nq.sh` scored from the beacon log.
1. ~~**The whole-tree `resolve(<DOM object>)` sweep — the one script window that is not an event.**~~ **DONE
   2026-10-29 — 10,035 files, 364 settlement-shaped calls, 92 value-carrying `.cpp` resolves, 41 with a tail, 11
   genuine post-resolve uses, 0 with a reachable free (`docs/74`).** New tool `tools/resolve-sweep.py` (recursive
   over `.cpp` + `.h`, argument class, enclosing loops, statements after the call past the block that contains it).
   The split is the engine's: `PromiseOperations.js:187-192` reads `then` only for Object arguments, so `reject` and
   primitive resolves are out. The 11 rows are `WebAnimation` ×7 (`*this` then `timingDidChange`/`invalidateEffect`/
   `hasEventListeners`), `DOMCacheStorage::doOpen` ×2, `Permissions::query:160`, `FetchEvent::192`; every one is
   protected by a `Ref`/`RefPtr` local or a wrapper-held `Ref` (`JSDOMWrapper.h:88`), and the `*this` family was
   measured: `Animation.finish()` opens the window twice (`THEN hit=2/3 on=Animation` before the next line's
   beacon; `Promise.resolve({})` control fires once), `cancel()`+`remove()` inside it changes state without a
   fault (`access: none` 5/5), and `pre=0` shows a `DOMPromiseProxy` resolve does nothing unless the page already
   holds the promise. Loop shape (CVE-2026-43715's): 3 sites, all drained/`bool`. Page
   `research/resolve-sweep/anim-window.html` md5 `ab0559dbd066664f513e37d47f5625b2`, logs `data/resolve-sweep/`.
1. ~~**The last un-swept script-entry class — direct JSC calls, whole tree.**~~ **DONE 2026-10-29 — 342 calls in
   the sink list, 83 synchronous (20 header declarations, 63 `.cpp` sites in 54 functions), 42 with a tail, 0 with a
   reachable free (`docs/75`).** New tool `tools/script-sweep.py`; the split that matters is `JSExecState`'s
   destructor, which drains the microtask queue before returning to C++ (`JSExecState.h:157-162`,
   `JSExecState.cpp:41`), so every synchronous JSC call has script-run-again semantics for its tail. Two rows were
   measured: the **XML parser's custom-element window** (`xml/parser/`, never audited) —
   `customElementReactionStack.reset()` at `XMLDocumentParserLibxml2.cpp:843` runs the constructor, and the tail at
   `:858` reads the raw `m_currentNode` (`XMLDocumentParser.h:162`) with a null check that cannot see a freed node;
   reachable (`CTOR` before `TAIL`) but **not freeable**, because `pushCurrentNode` calls `n->ref()`
   (`XMLDocumentParser.cpp:66-71`) and only `popCurrentNode` releases it — 6 arms, no ASAN, the parse continues
   after the node is removed; and `EventLoop::run()`'s tail, which is a per-agent-cluster `WindowEventLoop`
   (`WindowEventLoop.cpp:66-79`, `Document.h:2180`) kept alive by every document in the cluster (a child task
   removing its own frame leaves the parent's 500 ms and 1500 ms beacons running). Also recorded there:
   **conservative stack scanning is a GC marking constraint in this drop** (`Heap.cpp:2841` "Cs",
   `MachineStackMarker.cpp:39-48`, `:202`), so a raw `JSValue` local across a script window is a root, not a UAF.
   With `docs/69`-`74` this closes the script-window search: every window is an event dispatch, an observer
   callback, a `resolve(<DOM object>)` or a direct JSC call.
1. ~~**Probe the BroadcastChannel double-deserialize (`docs/67` row 38) under ASAN.**~~ **DONE 2026-10-29 —
   negative, and unreachable in this build.** `docs/67`. Four runs, one variable apart: `n=3` (two recipients) and
   `n=2` (one), each with and without a transfer list. Both recipients get `ab.len=64 ta.len=8 ta0=1 s=hello` and
   no sanitizer fires; the transfer list is not honoured at all (`buf.byteLength` is still 64 right after
   `postMessage(msg, [buf])`), because `dom/BroadcastChannel.idl:34` declares `postMessage(any message)` with no
   transfer argument. ArrayBuffers are therefore written in-line and **copied** by `readArrayBufferImpl`
   (`SerializedScriptValue.cpp:3238-3250`), so the consumed `m_arrayBufferContentsArray` (`:4667`) and
   `m_backingStores` (`:5566`) are never reached from this IDL. Page md5 `2f7ec0fb3eed3917ad5c3cd07fdd2195`,
   logs `data/cand-triage/run_B3.log`, `run_B2.log`, `run_BX3.log`, `run_BX2.log`. Closed.
1. ~~**Try to win the `Range`/GC race under ASAN — bounded at 10 runs.**~~ **DONE 2026-10-29 — negative, and
   ASAN cannot see this race at all.** `docs/68`. The race is real (`Range.h:42` has no lock,
   `Range.cpp:1133` reads both boundary points) and `useConcurrentGC` is on by default
   (`OptionsList.h:196`), but the marker only **hashes** the node pointer: `addWebCoreOpaqueRoot` ends in
   `addOpaqueRoot` → `m_opaqueRoots.add(ptr)` (`AbstractSlotVisitorInlines.h:123-135`), JSC never iterates that
   set (`Heap.cpp:1416/1501/1505` — clear, dump, deleteOldTables), and the only implementation that dereferences
   an opaque root is the verifier visitor (`VerifierSlotVisitor.cpp:185`), which no normal run uses. The other
   reads in the window are `*m_container` and `&impl` — no load from the freed object — and a `Ref` is a single
   aligned pointer, so no torn value. Two racing runs and one `mode=nor` control, 40 000 boundary reassignments
   each: `access: none`, `SUMMARY: none` (`data/cand-triage/run_R1.log`, `run_R2.log`, `run_RC.log`). The road
   cannot yield a reclaim primitive and is closed; the remaining seven runs of the bound would add nothing.
1. ~~**Re-aim: triage the ranked candidate list for a second, non-font bug.**~~ **DONE 2026-10-29 — the list has
   no second primitive.** All 56 patches fetched and compared with the drop (`data/cand-patches/`), every
   survivor read in the source; one decision row per candidate in `docs/67`. Counts: 5 ABSENT (file or feature
   not in the tree), 3 OLD-GEN (the drop is older than the defect and has a different, unaffected arrangement —
   including the top-ranked `cfe38930db`, which predates the `std::span` writer and writes the same `byteLength`
   it declares at `SerializedScriptValue.cpp:1826/:1829`), 1 KNOWN (`CachedString`, `docs/62`/`63`), 2 LIVE but
   not memory-unsafe (`:nth-child` int UB; BroadcastChannel double-deserialize), 1 LIVE-RACE
   (`Range::visitNodesConcurrently`), 1 LIVE-CRASH (the `@page` null deref, now the first item), 42 NODEFECT
   (hardening/refactor/build/perf/feature/test). The first reachable one was run: `@page foo {}` inserted into a
   grouping rule removed with `deleteRule(0)` faults at `CSSParserImpl.cpp:229` (`:238` for `foo:first`) with
   ASAN `SEGV ... 0x70` READ, 2/2 when the rule is detached *and* the page selector has a type (`at=1`, `at=2`),
   0/1 attached with the same selector (`at=0`), 0/1 detached with `@page {}` (`at=3`). It is a WebProcess crash,
   not a reclaimable object. Page md5
   `0f07e47e8fbbc642e47bf0a7235d741c`, logs `data/cand-triage/`. Original text: take
   `data/candidates-ranked.json` in score order, decide JS-reachability per entry, one decision row per
   candidate in `docs/67` with file:line evidence, and a page + ASAN run for the first reachable one.
2. **Sweep the string length against the write path (`docs/65`), looking for `RECLAIMED` beacons.** (Superseded:
   done as part of the item above with a poison-pointer control instead of the beacon. 108/144/192/200/224/256-byte
   strings give `:592` / tail-abort / tail-abort / `:592` / `:595` / `:592`, and none of them owns the slot — the
   sizes only change the layout. Do not re-run this as a reclaim search.)
   Fixed: spray count 4000, quarantine off (`run_nq.sh`), upstream trigger (`face.load()` + remove `#v`).
   Vary: string length across 120, 136, 152, 160, 168, 176, 184, 200, 232, 264.
   Verify: the run whose beacons print `RECLAIMED idx=.. at=.. val=..` instead of dying is the reclaim; `val` should
   be a `Status` enum value (0..4), confirming `setStatus` did the write. Record the length.
2. **Make the crash deterministic again and isolate the variable.**
   Verify: with `delete(this)` + layout + no spray, `run_nq.sh` reports `heap-buffer-overflow` at
   `CSSFontFace.cpp:703`; with the same page and only the spray added, the report changes or disappears.
2. **Find the exact allocation size that lands in the freed slot.**
   Verify: sweep string lengths and spray counts; the run where the outcome follows the *fill byte* (e.g. fill 4
   gives `REJECTED`, fill 3 gives `RESOLVED`) is the one that reclaimed. Record the length.
3. **Turn the status byte into a pointer field.**
   Read `CSSFontFace::existingWrapper()` / `wrapper()` in the drop; identify a field the expired object supplies
   that is used as a pointer. Verify: a run where the reported fault address equals a value we wrote.
4. **Only then** return to the console (`c039`) for hardware confirmation.

## Rules

- One variable per run. A result is only attributed to the variable that changed.
- Never record a claim without the command and its output.
- Commit after each verified step, with the verification in the message.
- Console work only when the operator has restarted the Guide app; the local ASAN build is the oracle otherwise.
- **Every oracle run goes through the Fedora 39 distrobox**: `ssh teo@<lab-ip> 'distrobox enter wk -- bash -lc
  "cd /tmp/wkp && ./runs.sh …"'`. A bare `ssh` run exits 127 with `libasan.so.8: cannot open shared object file` —
  the ASAN build links against the container's `/usr/lib64`, which the Bazzite host does not have.
