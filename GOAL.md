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
- **Second live UAF, and its slot is measured from inside — `docs/112`.** `HTMLCanvasElement::getContext`
  overwrites `m_context` during the options-getter re-entry, destroying the 712-byte
  `CanvasRenderingContext2D` the inner `getContext('2d')` returned while its JS wrapper keeps the raw
  pointer. gdb on the run's own WebProcess: the free is `CanvasRenderingContext2D::~… ←
  createContextBitmapRenderer ← getContext`, and the slot `A` is then genuinely recycled — but in
  `docs/103`'s arms it was taken first by the harness's own `new Image()` beacon (`CachedImage`, **720** B,
  memory-cached, hence permanent), which is why every spray there failed. Move that beacon after the spray
  and the 80-context spray takes A (`sent hit=0`, 6/6); eighty 692-char `atob` strings take it too
  (704/712/720/744 are one ASAN class). The string occupant is the attacker-byte foothold `docs/65` had.
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

- **The deserialization-abort family is enumerated and measured, and it is one input wide — `docs/90`.**
  Six sites carry the `RELEASE_ASSERT(vm.hasPendingTerminationException())` after a `MessageEvent::create`
  (`BroadcastChannel.cpp:256`, `LocalDOMWindow.cpp:947`, `MessagePort.cpp:295`,
  `WorkerMessagingProxy.cpp:199`/`:245`, `ServiceWorkerContainer.cpp:472`) — `docs/89` counted two. The
  `docs/89` input (explicit-length `DataView` over a resizable buffer, shrink in the walk, buffer in the
  transfer list) aborts **four** of them from page script: MessagePort 3/3, `window.postMessage` 3/3 in
  both IDL spellings, worker → document 2/2 (`:199`, thread T0), document → worker (`:245`, thread T9).
  The other two do **not**, for measured reasons: across the **service worker** IPC a 0-byte transferred
  buffer arrives **non-resizable** (`mx=0`, against `mx=192` for the same buffer over a MessagePort), so
  `DataView::wrappedAs` returns nullptr and `toJS` yields `jsNull` — the message completes with `v ===
  null`, no exception, no assert; and `BroadcastChannel` has no transfer list, so the buffer is written
  in-line at the view's dump point and the DataView arrives intact (`vb=192&bb=192`). Every other
  fail path in `CloneDeserializer` is a clean `fail()` → `ValidationError` → `didFail` → `messageerror`:
  57 `fail();` call sites, and the two non-`try*` allocations are measured negatives — `constructEmptyArray`
  cannot throw from a page payload (ArrayStorage allocates a **fixed** vector, so an array of 0x10000001
  arrives with `al=268435457` after a 22 s walk, and 0x10000000 behaves identically; ≈80 ns per hole) and
  the transfer-list rejections throw at `postMessage` before a message exists (`DataCloneError` ×3
  measured). The sharpest control is that the same message through `structuredClone` is a catchable
  `TypeError("Unable to deserialize data.")` 3/3 with no abort: **the defect is the caller's error mode
  (`NonThrowing` + `RELEASE_ASSERT`), not the input.** Pages `research/fuzz-cssom/caps10.html`
  (md5 `daed8a5fc70ded2ca1a798dadcbc910e`), `sw90d.js` (md5 `bd658cf382fe62a0e64226f6d12d3be5`), runner
  `c10run.sh`; logs `data/deser-family/`.
  - **The fail-silent wrapper shape is measured and inert, and it explains the whole family's asymmetry —
  `docs/91`.** A failed view wrapper is stored as `null`, is reachable through the **object pool**
  (a message carrying the same view four times arrives with all four slots `null` and
  `a === b === cc[0] === d`), and page script consumes it as an ordinary `null`: `new Map([[null,1]])`,
  `JSON.stringify`, `Object.keys` all work and the only throw is the page's own `null.byteLength`
  `TypeError` — no sanitizer line, no abort, 23 runs over 16 arms. It cannot become an object of the
  wrong type: the deserializer's only typed consumer of a pooled value re-checks
  `inherits<JSArrayBuffer>()` (`SerializedScriptValue.cpp:3290-3293`, false for `jsNull()`), the other
  four `readTerminal()` sites are value positions, an out-of-bounds view is clamped by
  `viewByteLength` (`JSDataView.h:59-78`) and cannot be re-serialized (`:1376`). **The rule behind the
  asymmetry:** `DataView::wrapImpl` calls the *verifying* `JSDataView::create` (`runtime/DataView.cpp:67`,
  throws at `JSDataView.cpp:52/59/64`) while `GenericTypedArrayView::wrapImpl` calls the
  *non-verifying* `create` overload (`GenericTypedArrayViewInlines.h:145`), so only the DataView
  spelling can leave a pending exception — and only it aborts. **The transport decides the outcome of
  one payload:** `MessagePort` → abort at `MessagePort.cpp:295` (3/3 + a re-run); `client.postMessage`
  (SW) → `null` (2/2 + a re-run), because the SW IPC delivers the transferred buffer with
  `mx=0` (non-resizable), so `wrappedAs` declines *before* `wrapImpl` can throw; a typed array over the
  port arrives as an empty out-of-bounds object (`vb0 bb0`, write dropped) and over the SW path as
  `null`. Auto-length is a clean `messageerror` on that transport in both directions
  (`:3311-3315` tests the *arriving* buffer's resizability), so explicit-length is the only input that
  reaches the throw. The second unchecked site, `cryptoKey = getJSValue(result.get())` (`:3848`), is
  measured on three key classes (extractable HMAC, non-extractable HMAC, ECDSA P-256 pair) — every one
  arrives as a real `CryptoKey`, so it has no page-side null. Pages
  `research/fuzz-cssom/caps12.html` (md5 `1d19801f33e75f07000abbd045601e4f`), `sw12.js` (md5
  `20e217ce9debe8ba27023cbd61430dbd`), runner `c12run.sh`; logs `data/deser-null/`.
- **The split-dump shape is closed on the length and open on the out-of-band payload — and that one is a
  measured crash, 9/9 over three transports (`docs/92`).** `ImageBitmap` was the only other page-reachable
  native whose length is *derived* on read: `dumpImageBitmap` writes `logicalSize`/`resolutionScale`/`byteLength`
  (`SerializedScriptValue.cpp:1521-1533`) and `readImageBitmap` re-derives `imageDataSize = logicalSize.scale(res)`
  for `ByteArrayPixelBuffer::tryCreate` (`:4180-4191`). It cannot disagree: the writer's length comes from
  `getPixelBuffer` → `toBackendCoordinates` → the *same* truncating `IntSize::scale` (`ImageBufferBackend.h:163-170`,
  `IntSize.h:95-104`) and `tryCreate` demands exact equality (`ByteArrayPixelBuffer.cpp:61-62`); moreover every
  creator path calls the 4-argument `ImageBitmap::createImageBuffer` whose `resolutionScale` defaults to 1 — the
  only 5-argument call site in the tree is the reader itself — so a non-1 scale is not page-reachable, and
  `OffscreenCanvas`/`WebCodecsVideoFrame` are measured absent. **The split that is real is the transfer's
  out-of-band backing store:** the transfer list is validated before the walk (`:5397-5399`), the tag is written
  from the transfer map during it (`:1486-1491`), and `ImageBitmap::detachBitmaps` takes the stores after it
  (`:5481`), so a getter calling `close()` in between leaves a **disengaged**
  `std::optional<ImageBitmapBacking>` at that index — and `readTransferredImageBitmap` dereferences it
  (`:4034`) with no engagement check, so `connect()`'s `if (!m_serializedBitmap)` guard (`ImageBitmapBacking.cpp:83`)
  reads a field of an object that was never constructed. Under ASAN that field is the malloc fill, so the
  deref is `SEGV` on `0xbebebebebebebe` at `ImageBuffer.cpp:119`: MessagePort 5/5, `window.postMessage` 2/2,
  document→worker 2/2 (`:88`, `WebWorkerClient`, thread T9). Four controls: no close arrives 8×8; a getter
  closing a *different* bitmap does not crash; closed before the call and closed before a value-path dump are
  both `DataCloneError`. **DoS, not a primitive** — the pointer is uninitialized memory. Page
  `research/fuzz-cssom/caps13.html` (md5 `e2f28fcf10136e73ce5d1923ccf4bc4d`), runner `c13run.sh`, retry wrapper
  `c13rep.sh`; logs `data/imagebitmap-split/`. One operational note: a **concurrent session** patched the
  oracle's `SerializedScriptValue.cpp` at 09:54 with a `fprintf` that over-reads the 32-byte element, so runs
  after that time are not on the drop's file (`0518be…` vs `4e3d9e…`) and must be restored before scoring.
- **The 32-byte element does not yet take page bytes — five shaping schemes, all negative (`docs/93`).** The
  pointer survives removing ASAN's fill (`max_malloc_fill_size=0` gives a deterministic recycled
  `0x00000000002b6280` at +8 in 4/4 runs), so the crash is not the fill, and a release build has two outcomes,
  not one. 512-byte `StringImpl`s + churn, 64 CSS faces freed at `buildCompleted()` with a 12-character family
  (the measured class: `sizeof=32 cap=1`), the 512/1024/2048 classes, zero bytes (which *must* trip the
  `ImageBitmapBacking.cpp:83` early return) and a `41…` pattern all left `+8` unchanged and all crashed, 5/5.
  Three design constraints recorded there: a `StringImpl` puts `m_length`, not a byte, at +8; the vector is
  allocated in the `takeAllMessagesForPort` reply dispatch, not the getter's frame; and `WeakRef`-plus-churn is
  unusable as the free side (`JSWeakObjectRef::deref` write-barriers its target, so 200 targets survived
  900,000 allocations, `dead=0` 3/3). Two further dead family members are measured on their own channels: the
  Wasm **agent-cluster** comparison (`WebAssembly` is `undefined`; the `SharedWorker` port and a cross-origin
  `window.postMessage` both deliver) and the **`isTypeExposedToGlobalObject`** membrane (`AudioContext` stays
  `suspended`; console has `WEB_AUDIO OFF`). Page `research/fuzz-cssom/caps11.html`
  (`f2aa6befd12d18c8bf88a2618b60f876`), runner `c11run.sh`. **Patch state, verified after this run closed:**
  while it was written the oracle's file was `b32d7b655…` (the `[IBT]` print cut to 24 bytes + the flag byte, so
  it no longer trips its own `heap-buffer-overflow` or preempts the SEGV), but a concurrent session has since
  **restored it to the drop's `4e3d9ea56468dfa59230d48cea4b5321`** with a relink in flight — so the `[IBT]`
  payload dump is gone from the build the next run will find. `patch_ibt.py` re-applies it (three lines, additive)
  when the payload bytes are what the arm needs; without it a shaping arm can only be scored from the fault
  address or from the no-crash outcome.

- **The 32-byte backing-store element is page-controlled, and the pointer it hands the engine is chosen by the
  page — measured (`docs/94`).** The element that `readTransferredImageBitmap` reads (`:4034`) is a 32-byte
  FastMalloc block built by `ImageBitmap::detachBitmaps` (`:5490`) and reused as-is: for a bitmap closed inside
  a getter the optional is disengaged, the engagement byte at **24** is always written `0` by the
  `std::optional` move-constructor, and only byte **8** (`m_serializedBitmap`) is ever read — so the value is
  whatever the *last* 32-byte block the walk freed still holds. Two page actions select it, and a third writes
  it: in-getter beacons leave the document URL's host there (`"127.0.0.1"` → `0x2e302e002e373231`,
  `"localhost"` → `0x736f680061636f6c`), a quiet getter leaves a heap pointer (`heap-buffer-overflow READ of size
  8 at 0x6030000b1b70`), and a `structuredClone(<16-bit string>)` as the getter's last statement leaves its own
  serialize buffer, so `+8` reads stream bytes 8..15. Measured on the drop's file, quarantine off,
  `max_malloc_fill_size=0`: `'A','B',NUL…,U+0100` → `SEGV on unknown address 0x000042004100` (2/2), `'C','D'` →
  `0x000044004300`, the 8-bit spelling → `0x000043424180` (low byte = `StringDataIs8BitFlag`), all-NUL → **no
  crash**, `ImageBitmap:w0h0`. Controls: a 16-byte-class stream (class 16) and the same arm with the ASAN fill on
  both fail to take the slot. So `docs/92` §4's open question is answered in both directions and the field is 56
  page-chosen bits — still a read-only dereference (one virtual call at `ImageBuffer.cpp:119`), i.e. a DoS with a
  chosen address, not criterion 3. Two plans are measured dead on the way: `ArrayBuffer.prototype.transfer` is
  `undefined` (`useArrayBufferTransfer` defaults false, `JSArrayBufferPrototype.cpp:464`) and a GC-freed
  `ArrayBuffer` spray cannot work because the collection is deferred inside the binding call
  (`fcount=0/313` in a getter, `313/313` in a plain task) and because the slot takes the *last* free of the walk.
  Pages `research/fuzz-cssom/caps14.html` (md5 `5e6619afdace5c68d4f94aba1bae55a2`), `c14run.sh`, `c14gdb.sh`;
  logs `data/`… `/tmp/S_c14_cl*.log`.
- **The JS-visible surface carries no address — swept whole and measured (`docs/95`).** 193 beacon records
  (180 probes) over
  the five boundaries the action named (clone/`postMessage` failure texts, `DOMException`/`Error.stack`
  including worker frames, `ImageBitmap` crossing a worker, `URL`/`performance`/`Intl`/`navigator` strings,
  `MessageEvent` `origin`/`source`) plus 17 readback scans, each part run twice in two processes and scored
  against `/proc/<pid>/maps`: 183 records byte-identical across ASLR once the URL port is normalised, the 10
  that change are clocks, UUIDs and `Math.random`, none lands in a readable mapping, and **no entry contains
  a ≥10-digit hex token at all** (the only one is the detector's own control). Every readback surface is zero-filled (`nz=0/64`, 15/15, including both resizable-grow paths —
  `ArrayBuffer.cpp:541`/`:627`), and truncated/corrupt PNG/JPEG, SVG `feBlur`/`feTurbulence`/`feTile`,
  canvas filters and `createImageBitmap` resizes produce no pointer-shaped word under a detector whose
  positive control fires and lands in `0x610000000000`. WebGL/WebGL2/`OffscreenCanvas`/`VideoFrame`/
  `WebAssembly`/`SharedArrayBuffer` measured absent; `decodeAudioData` fails `EncodingError` on five WAVs.
  Pages `research/leak-sweep/*.html`, runner `lkrun.sh`, scorer `diff.py`, logs `data/leak-sweep/`.
- **A second source-level deviation, dead at the IDL boundary — measured (`docs/95` §6).**
  `ArrayBufferView::byteOffset()`/`byteLength()` test the bounds **inverted** (`if (UNLIKELY(!(byteOffsetStart
  > bufferByteLength || byteOffsetEnd > bufferByteLength))) return 0;`), where upstream main has no `!`, so
  an out-of-bounds resizable view would hand WebCore the stale raw length and raw offset instead of 0. Not
  reachable: `JSGenericTypedArrayView::toWrapped` refuses every view whose buffer is
  `isResizableOrGrowableShared()` (`JSGenericTypedArrayViewInlines.h:928-934`), measured across `Blob`,
  `Response`, `TextDecoder`, `crypto.subtle.digest` and `ImageData` — an OOB view throws `TypeError:
  Underlying ArrayBuffer has been detached from the view or out-of-bounds`, and an in-bounds resizable view
  silently takes the **USVString** branch, so `new Blob([view]).size` is the length of `String(view)` (223
  for 64 elements vs 64 for the non-resizable control). `wrappedAs()` deliberately skips the sub-range check
  for resizable buffers (`GenericTypedArrayViewInlines.h:107-115`), which is the bypass to look for — **and it
  exists: `docs/96`, next bullet.**
- **The inversion is reachable, and it is a JS-visible out-of-bounds read plus two crash spellings — measured
  (`docs/96`).** `IDBKey::createBinary(JSC::JSArrayBufferView&)` (`IDBKey.cpp:53-59`) is the one WebCore
  consumer that takes a *raw* JS view, and it goes `possiblySharedImpl()` → `wrappedAs()` (no sub-range check
  for resizable buffers) → `ThreadSafeDataBuffer::copyData(view->data(), view->byteLength())` → `memcpy`.
  `IDBKeyRange.only(view).lower` hands the copy back to JS as an `ArrayBuffer` and needs no database. Measured,
  quarantine off (`caps15.html` md5 `60a9556b…`, logs `data/oobview/`): an 8192-byte view over a resizable
  buffer shrunk to 4112 reads `byteLength` **0** in JS and produces a **8192-byte** `ArrayBuffer` whose bytes
  are the pre-shrink `i^0x5a` pattern through `at4128=7a7b7879…`; the in-bounds twin (`byteLength` 8192)
  produces a **0-byte** key — the inversion in both directions. Controls on the same object:
  `structuredClone` → `DataCloneError`, `new Blob([v])` → `TypeError`. A shrink that crosses a **64 KiB**
  boundary (`PageCount::pageSize`, `PageCount.h:111`; `ArrayBuffer::resize` mprotects `[roundUp64K(new), old)`)
  is an ASAN `SEGV` in `memcpy` ← `ThreadSafeDataBuffer.h:52` ← `IDBKey.cpp:58` ←
  `IDBBindingUtilities.cpp:250` ← `IDBKeyRange.cpp:75`, and the auto-length underflow
  (`byteOffset > bufferByteLength` → `roundDownToMultipleOf(1, 2^64-k)`) is `READ of size 4294963216`. The
  copy length is bounded by `maxByteLength` (the constructor refuses a longer view, measured `RangeError`) and
  the reservation is allocated **zeroed** (`Gigacage::tryAllocateZeroedVirtualPages`), so no bounded spelling
  can return foreign bytes — 16/16 fresh 64 KiB reservations read all-zero. Audit
  `tools/oobview-audit.py`, 12/12. So the IDL gate `docs/95` measured is real, but it is not the only producer.
- **The write direction is closed, and the inversion is confined to the native class — measured (`docs/97`).**
  There are two `byteLength()`s: `JSC::ArrayBufferView`'s (native, inverted, `ArrayBufferView.h:120`) and
  `JSArrayBufferView`'s (JS wrapper, correct, `integerIndexedObjectByteLength`, `JSArrayBufferView.h:311`), so
  every JS-level write spelling (`set`/`fill`/`copyWithin`/`sort`/`view[i]=`/`DataView.set*`) works on the
  correct length and refuses an OOB view. The native one is reachable only through a converter, and all six
  producer spellings gate `isResizableOrGrowableShared()` — including `JSArrayBuffer::toWrapped`
  (`JSArrayBuffer.h:86-92`), so `(ArrayBuffer or ArrayBufferView)` unions are gated on both arms. The IDL
  census is 36 statements / **7 write consumers**, of which exactly one exists on this build:
  `Crypto::getRandomValues` (`Crypto.cpp:57-70`). Measured on one object in one process: the OOB view returns
  an 8192-byte key (`at4128=7a7b…`) and after **nine** write spellings (eleven arms) the same key reads **byte-identical**
  (`RB` = `K`), with `RBw` proving the witness is sensitive; the same eight spellings all write on a
  non-resizable control (`nz=8162/8192`). Two new facts: the inverted test returns 0 for an *in-bounds*
  resizable view too, so a `byteLength()`-bounded write fails closed; and `ArrayBuffer::resize()` memsets the
  newly-visible range on grow (`ArrayBuffer.cpp:540`), which is why a grow-back is not a usable readback.
  Audit `tools/abview-write-sweep.py` 23/23, `data/abview-write/`. The inverted-bounds thread is exhausted in
  both directions; **the programme's live memory primitives remain `docs/65` (one-byte write, inert) and
  `docs/94` (page-chosen pointer, read-only deref)** — no route to criterion 3 from either.

- **The text path carries no address, and it is the last un-swept JS-visible byte source — measured
  (`docs/98`).** 125 records × two processes, 63 rasterisation arms, 12 knob arms, 11 odd widths, two
  SVG-text arms, `toDataURL` PNG/JPEG, all 12 `TextMetrics` fields: **0 pointer-shaped words**,
  125/125 records identical across ASLR. The detector needed correcting first: `docs/95`'s
  `b5/b6/b7` rule fires on premultiplied grey pixels (`68 68 68 68 00 00 00 00`, 76 of the
  calibration run's 118 records), so the sharp rule also pins `b3=b4=0` and the loose windows are
  counted as `grey=` (1678). The reason is structural and measured on one object: `premult_proof`
  writes the canonical word into a canvas and reads back eight zero bytes (a 48-bit address has
  byte 3 = 0 → an alpha-0 pixel → premultiplied away), while the same bytes through
  `Blob → arrayBuffer` are seen (`raw_chain ptr=1`); the store is `tryFastCalloc`
  (`ImageBufferCairoImageSurfaceBackend.cpp:86-88`), the readback copies `4u * width` densely
  (`ImageBufferBackend.cpp:113`), and cairo shows glyphs straight to the destination
  (`CairoOperations.cpp:311`) — no WebKit-side glyph atlas. Two enabling facts for the next action:
  the canvas 2D context has **no** `letterSpacing`/`wordSpacing`/`fontKerning`/`fontStretch`/
  `fontVariantCaps`/`textRendering`/`filter`, and **a webfont served over HTTP really loads**
  (`face_gD st=loaded`, widths and all 12 metrics identical to the `local()` face).
- **Console** is wedged on the Guide menu with a dead WebProcess; needs a manual app restart by the operator before
  any on-console case can run. Local ASAN work is unaffected. The DoS family above adds four page-side
  crash sites that all need `ArrayBuffer.prototype.resize` (so `Options::useResizableArrayBuffer`, still
  unmeasured on the console), none of which is a memory primitive.
- **The one ungated OOB read cannot leak, for a structural reason — measured (`docs/100`).** `docs/96`'s key path
  copies a raw `byteLength()`; a full 64 KiB committed page read out from behind a 16-byte buffer returns
  `bl=65536 nz=16` — the page's own 16 bytes and 65,520 zeroes — and 0 pointer-shaped pairs. A resizable
  `ArrayBuffer` never reaches `fastMalloc`: `ArrayBuffer::tryCreate`'s `maxByteLength` branch goes to
  `tryAllocateResizableMemory` (`ArrayBuffer.cpp:316`), which commits `roundUpToMultipleOf<64 KiB>` pages of a
  `BufferMemoryManager` reservation (`:79-96`) and builds the contents from that pointer with no memset, so the
  over-read can only ever see the buffer's own fresh-zero pages — never a `StringImpl`, an `ArrayBuffer`
  neighbour, or the cage. Neighbour arms (`ab`, `str`, 64 planted of the class) give `seen=0`; the in-bounds
  control gives `bl=0`. Two corrections: a view longer than the live buffer **cannot be built from birth**
  (`RangeError: Length out of range of buffer`, the ctor validates against `byteLength`, not `maxByteLength` — grow
  first, then view, then shrink), and `docs/96` §8's "find another consumer" is qualified: it would still read
  zeroes. The shape survives as a 64 KiB zero-page oracle; the leak must come from a bug.
- **The OTF is out of the engine and every table checks out — measured (`docs/104`).** Three runs, one arm each
  (`G6`/`G4`/`N3`), gdb attached to that run's own WebProcess at `*FT_New_Memory_Face` (its only caller in the
  drop) dumping `$rsi..$rsi+$rdx`: 1 348 / 1 536 / 6 947 424 bytes, all `OTTO`, the same 14 tables in the
  writer's order (`CFF GSUB OS/2 VORG cmap head hhea hmtx kern maxp name post vhea vmtx`), no `loca`/`glyf`,
  `maxp.numGlyphs` 4/6/65 535. `G6` is one LigatureSet with one offset and a coverage of one glyph — `hb-shape`
  gives `[2=0+900]`, the page's `w=90.00`. `G4` is `0001 001a 0002 0008 | 0002 0006 000c | …`:
  **`LigatureSetCount` = 2 with one offset written and the second slot = `0x0002`, the first set's own
  `LigatureCount`** — a reader that enumerates the declared array lands at subtable+2 and reads the coverage
  offset (26) as its "LigatureCount"; fontTools 4.67 refuses the subtable (`ValueError: bytes length not a
  multiple of item size`) and `hb-shape 2.8.1` shapes `ab` as `[1=0+200|4=1+200]`, the page's `w=40.00`. The
  lookup is feature 0 = `liga`, the only feature the `DFLT` script enables (:873). `N3`'s format-12 subtable is
  intact (65 535 groups, 786 436 B) and its format-4 one is malformed **differently than `docs/101` §3 said**:
  `bmpMappings` is 65 505 because the arm's range crosses U+10000, so `segCount` is 65 506 and does not wrap —
  `clampTo<uint16_t>` saturates `length` and `segCountX2` at 65 535 against 524 064 real bytes. New facts: glyph
  ids follow `std::sort(…, compareCodepointsLexicographically)` (:1430), not document order, and Ligature offsets
  are relative to the set's start including its `2 + 2n` header. Dumps `data/otf-dump/{g6,g4}/*.otf` (+ hashes and
  the regeneration command in `dumps.txt`, the 6.9 MB one not stored), parser `tools/otf-dump-parse.py`,
  transcript `data/otf-dump/logs/`.
- **A live module address in the slot makes the engine execute `call *(*value + 0x20)`, and slot 4 is
  `sinkIntoImageBuffer` — `docs/104`.** Harness `research/canvas-alias/vrun.sh` reads the running WebProcess's
  `/proc/<pid>/maps`, plants `base+offset` (rounded to the 256-alignment the encoding forces) through a file the
  page fetches, so the value is a real address of that process rather than a guess. Six arms: every fault is
  exactly `qword_at_target + 0x20` and the top frame is `ImageBuffer.cpp:119`, i.e. `element+8 → this`, `*(this) →
  vptr`, `call *(vptr+0x20)` — and `0x20` is slot 4, which the vtable order confirms is the virtual we want
  (`ImageBuffer.h:248-259`). **Caveat that decides the next move:** those qwords are **link-time** offsets in this
  build, not relocated runtime addresses, so `*(value)` is unmapped and a fake vtable must be `base + *value` —
  cheap once anything leaks `base`, impossible without it. A real call therefore needs a *relocated* vptr (a live
  heap object → the leak again) or the `.got` route (§4).
- **The two ZigZagBoi claims are reproduced, and neither is a primitive — `docs/103`.** (a) The canvas UAF
  itself reproduces and its free is synchronous — `createContextBitmapRenderer`'s `unique_ptr` reset →
  `WTF::fastFree`, 712-byte region, 32 bytes inside, `heap-use-after-free` under quarantine at
  `CanvasRenderingContext::canvasBase()` — but **same-type occupation never takes the slot** at 1/2/8/32/500/3000
  fresh contexts, at 2000 contexts whose canvases were made before the trigger, or after a 400 k-object churn:
  the first use dies in `CanvasBase::scriptExecutionContext()` every time. So the alias half is **unconfirmed
  locally** and only the console can settle it; do not restate their p553 numbers as reproduced. Note also that
  `Uint8Array(712)` is *not* the same class as a freed fastFree chunk — `ArrayBuffer` data comes from
  `Gigacage::tryMalloc`. (b) `sort` on a shrunk view **is** on a stale length (192 comparator calls, the length
  is read once at `TypedArrayPrototype.js:229`) but the write-back is **guarded**: it throws
  `TypeError: … detached … or out-of-bounds` from the per-store check (`JSArrayBufferViewInlines.h:194`) and
  writes **nothing** — grow the buffer back and the bytes past the shrink are still the zero page. The
  asymmetry is the keeper: JSC validates on store and not on load, so reads past a shrunk view are fine and
  writes are not.
- **No API producer can leak, and the canvas carrier is lossless once the packing is fixed — `docs/102`.**
  Searching the two shapes a leak needs (a native `ArrayBufferView&` parameter, which skips the IDL converter
  that refuses resizable views, and a copy into a JS-visible object) gives exactly three families: `Crypto::
  getRandomValues` (write), the `WebGL*` declarations (compiled out) and `IDBKey` (the `docs/96` read). The
  copy sites that take `data()`+`byteLength()` are all reached through the same gated converter or take an
  `ArrayBuffer`, not a view (`BlobBuilder`, `StructuredClone::cloneArrayBuffer`, `ImageBitmap`,
  `ShareDataReader`, `NetworkSendQueue`), so every one copies from the same committed zero page. **The leak
  must come from a bug.** Second half, a correction to `docs/98`: its premultiplication loss is its own byte
  packing, not the canvas — with one byte per pixel in **R** and alpha pinned to 255, a realistic pointer shape
  round-trips 8/8, the `byte3 = 0` toy word 8/8, and a 0..255 sweep 256/256 with **0 lossy values**, so
  `getImageData → toBlob → arrayBuffer` is a faithful byte carrier and `docs/98`'s "the canvas store cannot
  carry an address" holds only for an RGBA-packed word.
- **A pointer oracle over the `docs/94` slot is calibrated in both directions — `docs/101`.** Any 8-byte value
  can now be tested against the element instead of just crashing blindly: a valid `SerializedImageBuffer`
  vptr makes the call return and the message **arrive**, `0` takes the `ImageBitmapBacking.cpp:83` early return
  and the page gets a **detached** bitmap (`rx&d=ImageBitmap:w0h0`, `w=0 h=0`), anything else is a `SEGV` at
  `ImageBuffer.cpp:119`. Three encoding traps are recorded (the pointer's low byte must be `0x00`, so candidates
  are 256-aligned; an all-ASCII payload serialises 8-bit and shifts that byte to `0x80`, so a trailing `U+0100`
  unit forces 16-bit; the stream must be 25 bytes so the freed block is class 32) and one allocator condition:
  **with ASAN's malloc fill on, every value crashes**, so the arms run `max_malloc_fill_size=0` — the closest
  available stand-in for a release build. It is a **validator, not a scanner**: a wrong-but-mapped address does
  not arrive because the value is *called*, so a successful arm needs a real vtable, not readable memory — the
  five candidates tried (`0x4141414100`, `0x7f00000000`, `0x7f00001000`, two zero controls) all crashed. Tools
  `research/leak-sweep/poracle.sh`, `oarun.sh` (kills only its own port so concurrent runs do not collide), page
  `caps14.html`. `caps18.html` is a sweep skeleton that never reaches the slot (always crashes, 4 runs) and is
  kept only as the harness frame.
- **Rung 1.5 (egress) is answered from the public chains: the WebKit process reaches libkernel and issues
  syscalls.** The published 4.03 chain ROPs inside the WebKit process and calls `getpid`/`write`/`socketpair`
  from a **worker thread's** stack, and finds libkernel's base from a GOT import the WebKit library itself
  carries (`libSceNKWebKit`, `OFFSET_wk___stack_chk_fail_import`) — so the WebProcess needs no separate sandbox
  escape to gain a syscall surface, and the base comes from the same primitive that reads WebKit. Two shape
  constraints follow and match the kernel-side notes: CFI is forward-edge only, so a **return address** on a
  worker stack is the pivot (never a vtable — although WebKit itself is built without `ENABLE_CFI`, which is not
  a port option here and only arrives via `ENABLE_SANITIZERS`); and clang's `__stack_chk_fail` interposition check
  has to be defeated. Read as: a WebView bug is a usable entry, and rung 1 — not 1.5 — is what is missing.
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

- **The font parser is measured and only WebKit's vertical GSUB has a defect — `docs/99`.** 190 arms
  over two bases, run as page `FontFace`s under the ASAN oracle with quarantine off: **109 accepted /
  77 rejected / 4 crashed, and no sanitizer report on any FreeType input.** FreeType's requirement at
  open is exactly the tables before `glyf` (`head`, `hhea`, `maxp`, `cmap`, `hmtx`, `loca`, `OS/2`,
  `cvt`, `fpgm`, `prep`); everything from `glyf` on can be cut away and the face still opens, with the
  per-character fallback as the only sign (`w=60.00` vs `55.56`). `numTables` 0x1000, table lengths 0
  and 0xFFFFFFFF, offsets past EOF, a duplicate `head`, an all-max/descending/zero `loca`, `numGlyphs`
  0xFFFF, a 0x7FFF-contour glyph and a self-referencing composite are all accepted without a report.
  The defect is `OpenTypeVerticalData.cpp:182` (`map->set(from, substitute[indexTo])`): a `Coverage`
  format-2 range that wraps (`end+1` = 0) or descends passes the drop's `indexTo + (fromEnd - from) >
  countTo` test because the subtraction goes negative, and the loop then runs the uint16 wrap — 32768
  and 65532 reads — `heap-buffer-overflow READ of size 2`, 7/7 over six runs and two bases. Upstream
  has `if (fromEnd <= from || …)` and `unsigned` locals; the drop has neither. **Console: compiled
  out** (`ENABLE(OPENTYPE_VERTICAL)` is GTK/WPE-only), so on 14.10 the whole font surface is FreeType.
- **The next font path is the SVG writer, and unlike the GSUB bug it does exist on the console.**
  `CSSFontFaceSource::load` (`:162-171`) calls `convertSVGToOTFFont` (`svg/SVGToOTFFontConversion.cpp:1559`)
  for an in-document `SVGFontFaceElement` (`CSSFontFaceSrcLocalValue::svgFontFaceElement`,
  `CSSFontFaceSrcValue.cpp:55`) or a `CachedSVGFont` fetched over HTTP, and the bytes it writes go
  straight into `createFontCustomPlatformData` → `FT_New_Memory_Face`. SVG fonts are not behind a
  feature macro (`grep -rn SVG_FONTS Source/cmake Source/WTF/wtf/PlatformEnable.h` is empty), so this
  is WebKit code that builds `head`/`maxp`/`hmtx`/`cmap`/`loca`/`glyf` from page-supplied path data on
  every port. Nothing in this programme has ever run it.

- **The SVG font writer is reachable on both halves, memory-clean on 52 arms, and its one defect is a
  silent GSUB truncation that is upstream's — measured (`docs/101`).** An in-document `<font>` with a
  `<font-face font-family>` is used by a plain CSS `font-family` with **no `@font-face` at all**
  (`SVGFontFaceElement::rebuildFontFace` :262-298 → `Resolver::addCurrentSVGFontFaceRules`,
  `StyleResolver.cpp:205-212`), and `url(f.svg#f1)` reaches `CachedSVGFont`; both end in
  `convertSVGToOTFFont` → `createFontCustomPlatformData` → `FT_New_Memory_Face`. The drop writes a
  **CFF/OTTO** font — 14 tables, **no `loca`, no `glyf`** (the action's table list was wrong) — with
  one Type-2 charstring per glyph. 52 arms / 82 arm executions / 11 runs, quarantine off:
  **0 sanitizer reports, 0 aborts**, 45 arms accepted by FreeType and used by the page. Bounds:
  **65 535 glyphs is the largest font accepted** and it loads and is used (`w=43.00` from a generated
  430-unit advance); **65 536 refuses the whole font**; at 65 535 `appendFormat4CMAPTable`'s
  `uint16_t segCount` (:315) is 65 536 → 0, and nothing changes because both Unicode encoding records
  point at the format-12 subtable (:351-370). A `d` cut mid-command or containing `NaN` fails the
  **whole font**, not the glyph (`m_error`, :1288 → `nullopt`); `units-per-em="-1000"` collapses every
  advance to 0 because `unitsPerEm()` (:88-98) only tests `!value` after `static_cast<unsigned>` of a
  negative float; `H`/`V`/`Q`/`A` geometry is correct because `SVGPathParser::parse` defaults to
  `NormalizedParsing` and the `CFFBuilder` `ASSERT_NOT_REACHED` handlers (:1222-1227) never run.
  **The defect:** two `<glyph>` ligatures sharing a first character — the `ff`/`fi`/`fl` case — give
  `LigatureSetCount = ligaturePairs.size()` (:771) with one offset emitted per *distinct first glyph*
  (:772), the shaper rejects the lookup and **all** ligature substitution stops: measured `w=40.00`
  (the two single advances) against `90.00` for the same font with `{ab,cd}` or `{ab}` alone — 6 arms,
  one variable each. **Upstream main carries both lines verbatim**, so this is a WebKit bug, not a
  Sony deviation. Not memory-unsafe and structurally cannot be: every other count the writer emits is
  understated, and the one overstated count is internal to the single `m_result` allocation and
  rejected by the reader.

- **The vertical substitution channel is JS-visible, and the funnel is a glyph id — measured (`docs/102`).**
  `docs/99`'s OOB GSUB read was "does anything read these glyph ids back"; the answer is **`hmtx` advances**.
  Four `vhea`/`vmtx` arms (one long metric vs 49 382, 256 vs 512 vs 1 024 units on `中`) are identical to the
  base at 24 px/char, while doubling `hmtx[中]` gives 48 px → the layout never reads
  `OpenTypeVerticalData::m_advanceHeights` (**this explains `docs/99` §6's withdrawn `vmtx` witness**, which is
  now recorded as explained, not withdrawn). A `vert` `SingleSubst2` 7 109→7 064 changes the measured advance
  115 → 114 px/char (`H0` vs `H1`), the *descending* `Coverage` range with in-allocation reads matches the
  well-formed arm exactly (`H2`), the wrapping range is inert (`H3` = `H0`), and horizontal width is unchanged
  (`hw=345`) → vertical-only. At 1 unit = 1 px the substituted id reads back exactly (7 320, 7 356, 20 256,
  32 256 px for ids 7 064, 7 100, 20 000, 32 000) and the ceiling is exact too: **32 767 px is reported,
  32 768 px collapses to 0**, a pixel bound rather than a font-unit one. The unpadded arm still aborts in
  `LookupTable::getSubstitutions` before layout, so the OOB word itself is an inference for a non-ASAN build;
  `ENABLE(OPENTYPE_VERTICAL)` is GTK/WPE-only, so the channel does not exist on 14.10 and does not touch
  criterion 3. Note also that the drop supports `lookupType == 1` only (`:139`), so a real CJK font's type-7
  `vert` lookup is inert — the whole funnel needs a hand-built table.
- **The `docs/94` slot's value is an engine pointer at every level, and the leak action has no candidate left —
  measured (`docs/103`).** A gdb probe at `ImageBitmapBacking::connect` dumps the 32-byte element itself: with no
  page action (`arm=md8&sk=none`) `+8 = 0x611000040c80`, the 8 bytes there are another engine pointer, and the
  engine's vtable-slot load lands at `*(*(+8)) + 0x20` — ASAN `heap-buffer-overflow READ of size 8` at
  `ImageBuffer.cpp:119`, `docs/94` §4's quiet row reproduced with the bytes in hand. With a page string freed in
  the getter (`sk=title`) the value moved to a **live `StringImpl`** (refCount 2, length 3, `m_data16 =
  self+0x14`, chars `"pad"` inline), so the vptr the engine loaded was `(m_length<<32)|m_refCount =
  0x0000000300000002` — two 32-bit integers, structurally never a vtable; the reuse arms (`A2`/`A3`) put no page
  word anywhere, which the inline-character layout explains. Candidate (b) therefore cannot "make the call
  return", and candidate (c) counts to zero: **2** raw `JSC::JSArrayBufferView` occurrences in `Source/WebCore`
  outside `bindings/js` (both `IDBKey`, `docs/96`), with `toWrappedAllowShared` applying the same resizable
  refusal as `toWrapped` in all four spellings. Corrections: ASAN prints the **shadow** address for a bad vptr
  (`0xdfff8004` for `0x300000022`), which looks like a pointer and is not one; `docs/94` §6's "no address" is
  that. Page `research/fuzz-cssom/caps19.html`, probes `research/leak-sweep/md8gdb.sh`, predictions and
  falsification `data/md8/predictions.md`.
- **The ligature count overshoots the table and no reader in the process follows it — measured (`docs/105`).**
  300 ligatures sharing one first glyph make `LigatureSetCount` 300 against one written offset slot (slot 1 =
  `0x012c` = set0's `LigatureCount`), at 150× `G4`: subtable 3 016 B of a 3 224-byte `GSUB`, `numGlyphs` 327,
  page `w=60.00`. A byte model (`tools/gsub-trust-model.py`) splits the question three ways — the declared array
  ends at subtable+606, **2 410 B short** of the subtable's end (the writer declares 2 B per pair and emits 6-8,
  so the array can never overtake the data); following the bogus offsets reaches **810 B past the subtable** and
  **3 584 B past the `GSUB` end** across all 300; and one bogus record's `compCount` 65 535 asks for **127 584 B
  past the font**. So the bytes declare reads outside the allocation and no engine reader takes them: the console
  shapes with HarfBuzz (`OptionsPlayStation.cmake:329-334`, `USE_FREETYPE`/`USE_HARFBUZZ` unconditional), whose
  sanitizer bounds every offset, and the drop's own parser reads `lookupType != 1` only
  (`OpenTypeVerticalData.cpp:140`) and is GTK/WPE-only. The well-formed twin at the same N
  (`G11-lig300-distinct`) measures **100.00** and decompiles cleanly in the same run — the mismatch, not the
  size. ASAN: 0 reports, 0 aborts, `EXIT=124`, `access: none` in four logs. **`docs/101` §5 is now measured, with
  one qualification: the safety is the reader's sanitizer, not the writer's arithmetic.**

- **Every Sony-only branch in `Source/JavaScriptCore` + `Source/WebCore` is now classified, and the
  allocation-and-free layer is where the differences are not — `docs/106`.** 186 conditional blocks (21 JSC,
  165 WebCore; 206 raw matches + 4 `PLATFORM (PLAYSTATION)` spellings, minus 24 `#endif` trailer comments):
  **42 replace shared logic**, 5 are stubs for a `playstation/` definition, 13 are logs, 32 are PS-only
  implementations, 8 are tests, 86 add a platform path. Not one of the six memory-lifetime replacements is
  reachable on the GTK oracle: `StructureID`'s 128 MB heap makes `structureIDMask = 0x07ffffff`, so a
  corrupted StructureID can only decode inside the structure reservation; the console's `WebConfig::g_config`
  (which *is* `g_jscConfig`, unified record) is never `mprotect`ed because `WTFConfig.cpp`'s only protection
  arm is `#elif OS(LINUX)` while the port is plain `OS(UNIX)`, and `VM.cpp:395` skips the freeze call anyway;
  `RenderElement::canDestroyDecodedData` destroys decoded image data where shared code refuses, whenever
  `shouldPaintEntireContents()` is true; the rest is `#if ENABLE(MAT)`-gated or compositor allocation shape.
  Two deviations that are real and non-memory: **`ReferrerPolicy::Default = NoReferrerWhenDowngrade`** — a
  console document with no policy sends its full URL cross-origin, measured on the oracle in the opposite
  direction (`research/referrer/refrun.sh`: default `referer=http://localhost:8971/`, `unsafe-url` full,
  `no-referrer` none) — and `ContentSecurityPolicy.cpp:827`, whose AND→OR is a *downstream fix*.
  `isLLIntPC()` returning false costs a `VMTraps` trap in LLInt code and profiler frames, nothing more.
  Blind spot recorded: 46 of the 64 files in `WebCore/PlatformPlayStation.cmake` carry no `#if` at all, and
  `ENABLE_LIBPAS` defaults **OFF** there — so the next surface is WTF + bmalloc + WebKit (`docs/106` §7-§8).

- **The Sony-only surface outside `JavaScriptCore`/`WebCore` is enumerated too, and the interesting differences
  are bounds, not logic — `docs/107`.** 183 blocks (`Source/WTF` 30, `Source/bmalloc` 36, `Source/WebKit` 117;
  189 raw lines, 53 with a non-PS alternative branch): 138 add, 33 `dev` (21 behaviour, **5 memory**, 4 inert,
  2 security, 1 flag), 8 stub, 3 impl, 1 flag. The five memory rows, all in the allocator layer:
  **every non-JavaScript WTF thread gets a 64 KB stack** (`-DDEFAULT_THREAD_STACK_SIZE_IN_KB=64`,
  `PlatformPlayStation.cmake:44`; JS threads 512 KB) where the oracle passes no `setstacksize` at all (8 MB
  glibc); `PageBlock`'s ceiling is **16 KB** where every 4 KB port clamps at 4 KB; `BUSE_RELEASE_LARGE_FREE 0`
  makes the PS-only `LargeMap::purge()` **dead**; `isSanitizerEnabled()` returning false is *why the oracle
  runs bmalloc as a debug heap and the console does not*; and `IPC::Connection` closes the socket **before** it
  stops its monitor thread (`ConnectionUnix.cpp:115-116` vs `:134`). Two corrections: **docs/106 §6.4's
  `canDestroyDecodedData` candidate is dead by construction** (nothing in the WebProcess ever sets
  `paintsEntireContents()` — `grep -rn shouldPaintEntireContents Source/` yields only the `ChromeClient.h`
  default, the `LocalFrameView.cpp:343` caller and a WebKitLegacy/mac override), and docs/106 §7's blind spot
  is **45** unguarded files, not 46 (`PlatformPlayStation.cmake:36` is a commented-out `.cpp`). The file lists:
  WebCore 63 `.cpp/.mm` (18 guarded / 45 not), WebKit 125, WTF 14; **0** of the 136 PS-only files supply a body
  for a definition that `Sources.txt` compiles unguarded — every one is a docs/106 stub or a port abstraction.
  New build facts, from `OptionsPlayStation.cmake`: **`ENABLE_JIT`/`FTL_JIT`/`DFG_JIT` OFF** (LLInt only) and
  **`USE_ISO_MALLOC` OFF**, so the 834 WebCore `WTF_MAKE_ISO_ALLOCATED` classes lose their dedicated heaps on
  console. The negative that matters most: **bmalloc's small-heap geometry is compile-time**
  (`smallLineSize 256`, `smallPageSize 4 KB`, `chunkSize 1 MB`, `Sizes.h:51-54`), so docs/65's and docs/94's
  page geometry and reuse order **do** transfer to the console. And a compile-time proof that the port is not
  plain `OS(UNIX)`: `MemoryPressureHandlerUnix.cpp:131` `#error`s unless `OS(LINUX)` or `OS(FREEBSD)` holds, and
  the `_np`/`pthread_np.h`/`CLOCK_MONOTONIC_FAST` API set says `OS(FREEBSD)` — which leaves docs/106 §6.2's
  conclusion intact (the freeze is skipped at `VM.cpp:395`) but corrects its first reason.

- **The four page-driven "recursive walkers" are priced, and two of them do not recurse in C++ at all —
  measured (`docs/108`).** On the oracle, `$rsp` read at every breakpoint hit over the whole recursion:
  `WebCore::createIDBKeyFromValue` **912 B/level**, constant over 2 000 deltas (min = max = mode), total
  **1 824 000 B** at its own cap of 2 000 (`maximumDepth`, `IDBBindingUtilities.cpp:194`), identical on a
  worker thread (measured on thread 10, `widb2000`); `CSSParserImpl::consumeRegularRuleList` **1 520 B/level**
  over 127 deltas, 193 040 B at the parser's cap of 128 (`:67`, `:582-587`). `CloneSerializer::serialize` and
  `CloneDeserializer::deserialize` are `while (1) switch (state)` machines: **1 hit** for a depth-20 000 clone
  and **1 hit** for a depth-20 000 `MessagePort` message, with `maximumFilterRecursion = 40000` a *heap* cap
  whose breach is a catchable `RangeError` (`clone err d=41000`), and `SVGPathParser::parsePathData` is a
  `while` loop (`:303-319`, source-read). `JSON.parse` is recursive but thread-aware — it falls back to the
  iterative parser at `vm.softStackLimit()` (`LiteralParser.cpp:1190-1205`) and parses 100 000 levels with no
  error. Recompiling both recursive TUs from the same tree at `-O2` without ASAN (build's own includes and
  defines) gives the release-shaped frames **128 B** (exact: the IDB recursion is a direct self-call) and
  **160 B** for the CSS entry function alone, whose per-level cost also carries two intermediate frames that were
  not recompiled (so 160 B is a lower bound there); the ASAN `-O1` build charges 912 and 1 520. Console arithmetic from the port's own sizes (`Threading.cpp:101-118` + `PlatformPlayStation.cmake:44`):
  a `ThreadType::JavaScript` thread (512 KiB) fits 4 096 IDB levels (exact) or ≤ 3 276 CSS levels (the CSS
  figure is an upper bound), a 64 KiB thread 512 or ≤ 409 — and **the 64 KiB define makes none of the four walkers a page-reachable hazard**,
  because none of them runs on a non-JS WTF thread and every one is either iterative or capped. What remains is
  one inequality: the deepest legal structure (2 000 IDB levels) needs the release frame to be **≤ 262 B** to
  fit a worker's 512 KiB — 2.05× above the `-O2` measurement, 3.5× below the ASAN one. Also measured: the
  oracle's worker stack is exactly **8 388 608 B** (the mapping containing the worker's `$rsp`), i.e. 16× the
  console's, so the oracle cannot settle that inequality by itself. Harness `research/stack-depth/{stack.html,
  stkrun.sh,arms.sh}`, page md5 `9d7b7880bfc0061f6dc1a52ab17c21c6`, logs `data/stack-depth/`.
- **The console's own 512 KiB is emulated on the oracle, and it moved the boundary into a recursion `docs/108`
  never instrumented — measured (`docs/109`).** `ulimit -s 512` gives the worker an `rw-p` mapping of exactly
  **524 288 B** (a 4 096-byte `---p` guard below it) and 1 024 gives 1 048 576 B, so the console's
  `ThreadType::JavaScript` size is a knob, not an inference. Sweeping `arm=widb&d=` at that size: **`d=376` is
  `ok` (2/2) and `d=377` is a `stack-overflow`** — but the crash is in `WebCore::toJS(…, IDBKey*)`
  (`IDBBindingUtilities.cpp:153`), the **outbound** key conversion, which recurses once per level at
  **1 344 B** (constant over 278 and 377 deltas) against the inbound walker's 912 B. At `d=376` the deepest
  `toJS` hit has **288 B** above the floor and is the number level (no call); `d=377` puts an array level
  there and `constructEmptyArray` crosses into the guard page 668 B below the floor. The walk's own limit is
  556-557 entries (`u512_2000` crashes at 557 in `Vector::append`:228, with the walk complete at `d=550`), and
  at 1 MiB the boundary is **766/767** in the conversion and **1 132** entries in the walk —
  `floor((S-offset)/frame)` reproduces all four with the two measured offsets (15 776 / 18 656 B). Release
  frames from the same TU at `-O2`: **144 B** for `toJS` (the recursive call goes straight to
  `[clone .part.0]`, bypassing the public thunk) and 128 B for the walk, so the deepest legal structure
  (2 000 levels) needs **54.9 %** and **48.8 %** of a console worker's stack — the 262 B threshold is 1.82× /
  2.05× above them, so **a legal structure cannot push a console worker over** at the measured release frames.
  The remaining unknown is Sony's clang frame, which no oracle arm can bound from above except by the ASAN
  frame (1 344 B, 5.1× over). Harness `research/stack-depth/ulrun.sh` + `STK_BT=1`, logs
  `data/stack-depth/ulimits/` (22 arms).
- **The IsoHeap question is settled for both builds, and it was never about `docs/65` — measured (`docs/111`).**
  `wtf/IsoMalloc.h:31` is `#if USE(SYSTEM_MALLOC) || !USE(ISO_MALLOC)`, so the 834 `WTF_MAKE_ISO_ALLOCATED` classes
  become `WTF_MAKE_FAST_ALLOCATED` on the console by the port default (`OptionsPlayStation.cmake:211` OFF, the
  generic default at `WebKitFeatures.cmake:267` ON being the only other site) **and** on the oracle by
  `USE_SYSTEM_MALLOC 1` (`cmakeconfig.h:200,211`; `fastMalloc` → `malloc`, `FastMalloc.cpp:156,236,265`).
  Measured on the real `CanvasRenderingContext2D.cpp` compiled with the build's own flags: `U WTF::fastMalloc`, no
  allocator symbols defined in the object, 0 mangled `_ZN6bmalloc3api7IsoHeap`; and 0 in the whole 3.7 GB library
  with `IsoSubspace` 2 928 as the same-file control. `css/CSSFontFace.h:61` is
  `WTF_MAKE_FAST_ALLOCATED_WITH_HEAP_IDENTIFIER`, so `docs/65` never depended on the answer; JSC has no
  `USE(ISO_MALLOC)` reference, so `docs/76` stands; `docs/103`'s canvas negative is **not** explained by type
  segregation, and `c043b` cannot discriminate IsoHeap from a bmalloc size-class free list. Data `data/isoheap/`.

## Next actions, in order, each with its verification

1. **Next: turn the string occupant of the canvas slot into a controlled pointer read** — `docs/112` leaves the
   page with 692 attacker-chosen bytes holding the freed `CanvasRenderingContext2D` slot, which is the thing
   `docs/65`'s `CSSFontFace` never had (its occupant was 172 bytes of a `StringImpl` too, but the object was a
   font face). The stale wrapper is a `JSCanvasRenderingContext2D` with a raw
   `CanvasRenderingContext*`, so any getter/setter that reads a pointer member of the container is a deref of
   *our* bytes. `CanvasRenderingContext::m_canvas` is a `CanvasBase&` (one pointer) and
   `CanvasRenderingContext2DBase::setFillColor` reaches `CanvasStyle::createFromString(color, canvasBase())`
   before anything else, which is where the string arm dies today (`CanvasBase.h:97
   scriptExecutionContext`). **Verify:** with `arm=str&n=80&btrig=late`, put a chosen 8-byte value at the offset
   `setFillColor` reads as `m_canvas` (find it from the crash `si_addr` and a `x/` of the container), and score
   the ASAN fault address against the value placed: the value plus the member offset the engine then touches,
   with the same bytes at a neighbouring offset as the offset-shifted control and a second value as the
   value control. A result is the reported address being our value (+ a constant) and changing with the value;
   "the fault address does not follow the bytes" is also a result and closes the getter path. No console access.

1. ~~**Next: settle which build has IsoHeap, because the drop's CMake and the console disagree and several closures
   rest on the answer.**~~ **DONE 2026-10-30 (`docs/111`) — one condition with two arms, both builds land on the
   general heap, and `docs/65`'s object turns out not to be an ISO class at all.** `IsoMalloc.h:31` is
   `#if USE(SYSTEM_MALLOC) || !USE(ISO_MALLOC)`. The console takes the second arm by the port default
   (`OptionsPlayStation.cmake:211` OFF against `WebKitFeatures.cmake:267` ON — those are the only two sites in the
   tree), so all **834** `WTF_MAKE_ISO_ALLOCATED` classes compile to `WTF_MAKE_FAST_ALLOCATED`; our oracle takes
   the first, because its `cmakeconfig.h` (sha `4d1cfe68…`, 6 983 B) says `USE_ISO_MALLOC 1` **and**
   `USE_SYSTEM_MALLOC 1`, so `fastMalloc` is `malloc` (`FastMalloc.cpp:156,236,265`). Measured, one variable — the
   real `CanvasRenderingContext2D.cpp` compiled with the build's own `DEFINES/INCLUDES/FLAGS` into a
   12 218 040-byte object — has `U WTF::fastMalloc(unsigned long)` and **none** of the four allocator symbols the
   ISO-on branch would define in that same object (`IsoHeapInlines.h:159-190`), and 0 mangled
   `_ZN6bmalloc3api7IsoHeap`; the oracle's own 3 695 564 176-byte library has 0 of them too, against `IsoSubspace`
   2 928 as the same-file pipeline control (its 77 `IsoHeap*` strings are JSC's `IsoHeapCellType`). The distro
   library is stripped (0 `.symtab`) and gives no verdict. **Scope corrections:** `css/CSSFontFace.h:61` is
   `WTF_MAKE_FAST_ALLOCATED_WITH_HEAP_IDENTIFIER`, so `docs/65` never depended on this gate; `Source/JavaScriptCore`
   has no `USE(ISO_MALLOC)` reference, so `docs/76`'s `stringSpace` stands; `docs/103`'s local canvas negative was
   **not** caused by type segregation (that build has none), and `c043b` cannot discriminate IsoHeap from a plain
   bmalloc size-class free list — the discriminating input is a cross-type allocation of the same size, which is a
   console case. Data `data/isoheap/` (`gate.txt`, `census.txt`, `verdicts.json`). Two limits: no ISO-on object
   could be built here (`bmalloc/GigacageConfig.h` is never generated in a system-malloc build dir), and the shipped
   console value is not readable from source — only an explicit `-DUSE_ISO_MALLOC=ON` in Sony's cmake would flip it.
1. ~~**Next: give `docs/103`'s canvas negative a measured cause — it is the one local result `docs/111` leaves
   unexplained, and it decides whether the console's deterministic same-type reclaim has any local analogue.**~~
   **DONE 2026-10-30 (`docs/112`) — the cause is the page's own beacon, and the local oracle does reclaim the slot,
   6/6.** With gdb on the run's own WebProcess (dtor → `A`, `fastFree(A)`, a `fastMalloc` tracer for the 704–744
   class and a write watchpoint on `A`), the exact `docs/103` arm gives: free at `0x6170…1c00` from
   `CanvasRenderingContext2D::~CanvasRenderingContext2D ← createContextBitmapRenderer ← getContext`, then
   **`ALLOC req=720 ret=A n=1 <== A`** from `createResource ← CachedResourceLoader::loadResource ←
   requestImage ← ImageLoader::updateFromElement` with `WROTE-A val=CachedResource-vtable` at offset 0 — a
   `CachedImage` of **720** bytes allocated by the `B('trig')` beacon one statement after `getContext` returns,
   memory-cached, so it keeps the slot for the whole run while all 80 `req=712` contexts land at `0x…12300`,
   `0x…12680`, … (the ladder never touches A; the page dies at its first use, 4/4). Move that one beacon after the
   spray (`btrig=late`) and the slot is taken by the transient 744-byte `JSC::BytecodeGenerator`, freed, then by
   **`ALLOC req=712 ret=A n=2` = `CanvasRenderingContext2D::create`**, and the page scores
   `sent hit=0 e=777.25 f=0` / `done` / `access: none` — **6/6** (11101-3, 11131-3; gdb 11105). Cross-type arm
   (`arm=str`: eighty 692-char `atob` strings = 712 B): `ALLOC req=712 ret=A` from
   `StringImpl::createUninitializedInternalNonEmpty(length=692) ← String::String ← Base64Utilities::atob`,
   `WROTE-A val=0x2`, page dies (2/2) — same size, different class, same slot. No-spray control: the slot is owned
   by the BytecodeGenerator (library vtable at A at the fault, `si_addr=0x8`), so a live context is required, 1/1.
   `bkind=sb` (retail's `sendBeacon`) swaps the thief to `CachedRawResource` (**704** B via
   `CachedResourceLoader::requestBeaconResource ← NavigatorBeacon::sendBeacon`) but its beacons never reach the
   server (0 `GET/POST /ev`), so that arm is recorded as **unscored**. Corrections: 704/712/720/744 are one ASAN
   class (712 never identified a class); `docs/108`'s "local build cannot judge occupation" narrows to *class
   geometry*, not ordering/liveness; `docs/103`'s crash site is a property of the occupant, not of the bug. Page
   md5 `08bfde9edc37a3e20130049fb7129d3a`, harness `research/canvas-alias/slotgdb.sh` + `slotwatch.py`, logs
   `data/canvas-slot/`.
2. ~~**Next: put the console's 512 KiB on the oracle — glibc derives the default thread stack size from
   `RLIMIT_STACK`, so a worker really can be given the console's stack without touching the console, and the
   maps instrument below already proves the size it got.**~~ **DONE 2026-10-30 (`docs/109`) — the console's
   524 288-byte stack is on the oracle, the boundary is 376 levels, and the IDB key path turns out to recurse
   twice.** `ulimit -s 512` gives the worker an `rw-p` mapping of exactly **524 288 B** (with a 4 096-byte
   `---p` guard below it, `maps_u512_376.txt`) and `ulimit -s 1024` gives **1 048 576 B**. The sweep is not the
   one the action assumed: `d=376` is `ok` (2/2) and `d=377` crashes, but both crashes are in
   `WebCore::toJS(…, IDBKey*)` (`IDBBindingUtilities.cpp:153`) — the **outbound** conversion `docs/108` never
   instrumented — at **1 344 B/level** (constant over 278 and 377 deltas), against the inbound walk's 912 B.
   At `d=376` the deepest `toJS` hit has **288 B** left and that level is the number (no call); `d=377` puts an
   array level there and its `constructEmptyArray` crosses the floor, 668 B into the guard page. The walk's own
   limit is 556-557 entries (`u512_2000`: 557 hits, then `Vector::append`:228), and at 1 MiB the boundary is
   **766/767** in the conversion and 1 132 entries in the walk — `floor((S-offset)/frame)` predicts all four
   exactly with the two measured offsets (15 776 / 18 656 B). Release frames from the same TU at `-O2`:
   **144 B** for `toJS` (its recursive call goes straight to `[clone .part.0]`, so the 16-byte thunk is not
   per-level) and 128 B for the walk, so a legal 2 000-level key needs **54.9 %** and **48.8 %** of a console
   worker's stack: the 262 B threshold sits 1.82× / 2.05× above them, i.e. **the console cannot be pushed over
   by a legal structure at the measured release frames** — conditional only on Sony's clang frame, which no
   oracle run can bound from above except by the ASAN frame. 22 arms, harness `research/stack-depth/ulrun.sh`
   (+`STK_BT=1` in `stkrun.sh`), logs `data/stack-depth/ulimits/`. Original text: **Next: put the console's 512 KiB on the oracle — glibc derives the default thread stack size from
   `RLIMIT_STACK`, so a worker really can be given the console's stack without touching the console, and the
   maps instrument below already proves the size it got.** `docs/108` priced the walkers but had to stop at a
   threshold, because the oracle's threads are 8 MiB (measured: the worker's stack mapping is exactly
   8 388 608 B) while 14.10 gives a `ThreadType::JavaScript` thread 524 288 B. The premise is already verified in
   `docs/108` §5: with only `ulimit -s 1024` added in front of `run_nq.sh`, the worker's mapping is
   **1 048 576 B** (`data/stack-depth/maps_ul1024.txt`), so `STK_ULIMIT=512` gives the console's own number. The page's deepest *legal*
   recursion is the IDB key builder at 2 000 levels, and the console is safe only if the release frame is
   ≤ **262 B/level** (measured `-O2`: 128 B; measured ASAN `-O1`: 912 B, i.e. 3.5× over). **Verify:** launch the
   same `run_nq.sh` under `ulimit -s 512` (and 1 024 as a second arm), confirm from `/proc/<pid>/maps` that the
   worker's stack mapping is the reduced size, then sweep `arm=widb&d=` downward from 2 000 until the arm stops
   returning `ok`; the crash depth gives the frame the path costs *including its callers* and the ratio to
   262 B settles whether the console's worker can be pushed over by a legal structure. One depth per run, one
   control at half that depth, and the same page and runner as `docs/108` (`research/stack-depth/`) — the only
   changed variable is the thread's stack size.
2. ~~**Next: turn docs/107's 64 KB thread stack into a predicted console limit — the oracle can measure the
   per-frame cost of a page-driven recursion without changing the console.**~~ **DONE 2026-10-30 (`docs/108`) —
   all four walkers priced by `$rsp` per level, and the answer is that two of them do not recurse at all.**
   `createIDBKeyFromValue` costs **912 B/level** in this ASAN build (2 000 deltas, min = max = 912; total
   1 824 000 B at its own cap of 2 000, and identical on a worker thread, measured on thread 10), and
   `CSSParserImpl::consumeRegularRuleList` **1 520 B/level** (127 deltas; 193 040 B at the parser's cap of 128).
   `CloneSerializer::serialize` and `CloneDeserializer::deserialize` are iterative state machines — **1 hit**
   for a depth-20 000 clone and for a depth-20 000 `MessagePort` message — and over `maximumFilterRecursion =
   40000` is a JS `RangeError`, not a stack event; `SVGPathParser::parsePathData` is a `while` loop (source-read);
   `JSON.parse` is recursive but falls back to the iterative parser at `vm.softStackLimit()`, measured at
   `d=100000`, no error. Recompiling both TUs at `-O2` without ASAN (same includes/defines) gives the
   release-shaped frames: **128 B** and **160 B**, so the console's limits are 4 096 / 3 276 levels in a 512 KiB
   JS thread and 512 / 409 in a 64 KiB one. **The 64 KiB define converts none of the four into a page-reachable
   hazard**: none of them runs on a non-JS WTF thread, and the deepest legal structure costs 48.8 % of a worker's
   512 KiB at the `-O2` frame and 3.5× its size at the ASAN frame — hence the 262 B threshold the next action
   tests. Original text: **Next: turn docs/107's 64 KB thread stack into a predicted console limit — the oracle can measure the
   per-frame cost of a page-driven recursion without changing the console.** `-DDEFAULT_THREAD_STACK_SIZE_IN_KB=64`
   is a PS-only build define (`PlatformPlayStation.cmake:44`) and `Thread::establishHandle` passes it to
   `pthread_attr_setstacksize` (`posix/ThreadingPOSIX.cpp:294-295`), so every WorkQueue/RunLoop/compiler/IPC
   thread on 14.10 has 1/128 of the oracle's 8 MB — and `OSAllocatorPlayStation::reserve*` **drops guard pages**
   (`ASSERT_UNUSED(includesGuardPages, !includesGuardPages)`), so an overflow there is silent corruption rather
   than a fault. The recursive walkers a page can drive are already enumerated: `CloneSerializer`'s walk
   (`SerializedScriptValue.cpp:2590`, depth-limited), `IDBBindingUtilities::createIDBKeyFromValue`
   (`docs/78`, `depth=8` measured), the CSS parser's nested blocks, and `SVGPathParser`. **Verify:** on the
   oracle, attach gdb to the run's own WebProcess, break at the recursive function, and read `$rsp` at entry
   for successive depths (`ignore` counts) to get the **frame size in bytes**; then `65536 / frame` is the
   console's depth limit and `depth_max(page) × frame` the fraction of it a page can reach. One page that
   builds the deepest legal structure, one control at half the depth, quarantine off, scored from the `$rsp`
   deltas and from the page's own counters — no console access.
2. ~~**Next: read the Sony-only surface *outside* `Source/JavaScriptCore`/`Source/WebCore` — the allocator and
   the config record are where the last audit's two structural facts came from, and neither directory has
   been read with this question.**~~ **DONE 2026-10-30 (`docs/107`) — 183 blocks classified, 33 `dev`, and the
   five memory rows are all allocator bounds rather than logic changes.** `Source/WTF` 32 lines/30 blocks,
   `Source/bmalloc` 39 (22 `BPLATFORM`)/36, `Source/WebKit` 118/117; 189 raw lines → 183 blocks (53 with a
   non-PS alternative). Verdicts `data/ps-branches/verdicts-outer.json`: 138 `add`, 33 `dev` (21 behav, 5 mem,
   4 inert, 2 sec, 1 flag), 8 `stub`, 3 `impl`, 1 `flag`. The memory rows: 64 KB non-JS WTF thread stacks
   (`PlatformPlayStation.cmake:44` + `Threading.cpp:104-117`; JS 512 KB), `PageBlock` ceiling 16 KB
   (`PageBlock.h:52`), `LargeMap::purge()` dead under `BUSE_RELEASE_LARGE_FREE 0` (`BPlatform.h:360`,
   `bmalloc.cpp:151`), `isSanitizerEnabled()` false on PS (`Environment.cpp:130`) which is the oracle's debug
   heap, and `ConnectionUnix`'s close-before-detach ordering (`:115-116` vs `:134`). Source-list half
   (`tools/ps-file-list-sweep.py`): WebCore 63 `.cpp/.mm` = 18 guarded + **45** unguarded (docs/106 §7 said
   46 — one entry is commented out at `PlatformPlayStation.cmake:36`), WebKit 125, WTF 14; 136 PS-only files,
   **0** supplying a body for a definition `Sources.txt` compiles unguarded. Corrections: **docs/106 §6.4 is
   dead by construction**; §6.2's conclusion stands but its first reason is wrong because the port must define
   `__linux__` **or** `__FreeBSD__` (`MemoryPressureHandlerUnix.cpp:131` `#error`), and the API set says
   FreeBSD. New build facts: `ENABLE_JIT`/`FTL`/`DFG` OFF (LLInt only), `USE_ISO_MALLOC` OFF (834 classes out
   of their heaps), bmalloc small-heap geometry compile-time so docs/65/docs/94 offsets transfer.
   Original text: **Next: read the Sony-only surface *outside* `Source/JavaScriptCore`/`Source/WebCore` — the allocator and
   the config record are where the last audit's two structural facts came from, and neither directory has
   been read with this question.** `Source/WTF` (32 `PLATFORM(PLAYSTATION)` lines / 16 files), `Source/bmalloc`
   (39 `PLATFORM(PLAYSTATION)` + 22 `BPLATFORM(PLAYSTATION)` / 22 files) and `Source/WebKit` (118 lines / 57
   files); plus the **46** files in `Source/WebCore/PlatformPlayStation.cmake` that carry no `#if` at all and
   are PS-only by source list (the last audit's blind spot, `docs/106` §7). `ENABLE_LIBPAS` defaults **OFF**
   there (`OptionsPlayStation.cmake:284,286` → `-DBENABLE_LIBPAS=0`), so the classic bmalloc allocator is what
   the console runs — read every `BPLATFORM(PLAYSTATION)` block in `bmalloc/{Heap,Scavenger,LargeMap,Mutex,
   BVMTags,VMAllocate,BPlatform}.{h,cpp}` and say for each whether it changes a *bound*, a *container* or a
   *lifetime* that shared code also has. **Verify:** the same classification table as `docs/106`, one verdict
   per block with the line quoted, and for every `dev` row either a page/ASAN arm on the oracle or an explicit
   "console-only, unmeasured" — the oracle is GTK, so `BPLATFORM(PLAYSTATION)` code cannot run there.
   Do **not** re-enter the console.

1. ~~**Next: read every Sony-only branch in the tree — a `PLATFORM(PLAYSTATION)` block that changes shared logic is
   the one place upstream has no test coverage, and the three source-level deviations this programme has found
   were all in *plain* code that no audit had read with this question in mind.**~~ **DONE 2026-10-30 —
   186 conditional blocks (21 JSC, 165 WebCore) classified, 42 of them replacements, and not one of the six
   memory-lifetime ones is reachable on the oracle (`docs/106`).** The surface reconciles exactly: 206 raw
   matches + 4 `PLATFORM (PLAYSTATION)` spellings, of which 24 are `#endif` trailer comments → 186 blocks;
   GOAL's 17/185 is the `.cpp`/`.h` subset plus comments. Verdicts (`tools/ps-branch-classify.py`,
   `data/ps-branches/verdicts.json`): 42 `dev`, 5 `stub`, 13 `log`, 32 `impl`, 8 `test`, 86 `add`. The six
   memory rows are all console-only or build-dependent — `StructureID` 128 MB mask (containment: a corrupted
   StructureID can only decode into the reservation), `VM.cpp` + `WTFConfig.cpp:150` (`#elif OS(LINUX)` means
   the port's `WebConfig::g_config` is *never* mprotected, and PS additionally skips the freeze call),
   `RenderElement::canDestroyDecodedData` (destroys decoded image data where shared code refuses whenever
   `shouldPaintEntireContents()`), `Options::useConcurrentGC` (`#if ENABLE(MAT)`, default OFF),
   `TextureMapper` (no texture pool), `BlockDirectory` (statistics only). Two real deviations, both
   non-memory: **`ReferrerPolicy::Default` = `NoReferrerWhenDowngrade`**, so a console page without a policy
   sends its **full URL** cross-origin — measured on the oracle in the other direction (default = origin
   only, `unsafe-url` = full, `no-referrer` = none) with `research/referrer/refrun.sh`; and
   `ContentSecurityPolicy.cpp:827`'s AND→OR, which is a **downstream fix** (upstream's `&&` lets a
   non-Document context reach `downcast<Document>`; `WorkletGlobalScope.cpp:63` is the null-client
   constructor). `LLIntPCRanges::isLLIntPC` returning false is a *behaviour* row, not a memory one: it makes
   `VMTraps` drop a trap taken in LLInt code and leaves profiling/asserts without LLInt frames, nothing more.
   Verify (original):

0. ~~**Check the two claims taken from ZigZagBoi's repo (`docs/90`)** — same-type canvas occupation as field control,
   and `Array.prototype.sort` on a resized view.~~ **DONE 2026-10-30 by the concurrent session (`docs/103`,
   commit `74bad58`): the canvas UAF reproduces with a synchronous free but same-type occupation never takes the
   slot, and `sort`'s comparisons run past the shrink while the write-back store is guarded.** Their `p553`
   "bidirectional R/W" is an in-type self-alias by their own limitations section, and its evidence file is a
   reconstruction, so reproduce rather than cite — measured, that is what it is: unconfirmed locally and a
   console arm. Verify (original): canvas —
   a sentinel written into a freshly created context is visible through the stale wrapper, and `save()`/`restore()`
   moves `m_stateStack`; sort — a shrunken resizable view sorted after the callback shows reads past the new length.

1. ~~**Next: turn the GSUB over-read into a JS-visible byte — a `Vector<uint16_t>` of substituted glyphs is
   built from OOB `substitute[]` entries, so does anything copy it back to script?**~~ **DONE 2026-10-30 — it
   is JS-visible, through `hmtx` advances, with a 15-bit funnel and a hard 32 767 px ceiling (`docs/102`).**
   `V0`-`V3` (one `vhea`/`vmtx` variable each, up to 49 382 long metrics and 1 024 units on `中`) are
   **identical to the untouched base**, while doubling the same glyph's `hmtx` advance doubles the layout
   (`Hx`: 24 → 48 px/char) — so the advance this layout uses is `hmtx`, never
   `OpenTypeVerticalData::m_advanceHeights`, which is exactly why `docs/99` §6's `vmtx` witness could not
   move. A `vert` `SingleSubst2` entry 7 109→7 064 then moves the measured advance 115 → 114 px/char
   (`H0` vs `H1`, one table), the **descending** `Coverage` range with its `substitute[]` reads inside the
   same allocation is **byte-identical to the well-formed arm** (`H2`), the wrapping range is inert
   (`H3` = `H0`), and the horizontal width is unchanged in all four (`hw=345`) — vertical-only. At 1 font
   unit = 1 px (font-size 256, upem 256) the substituted id reads back **exactly**: 7 320 = 256+7 064,
   7 356 = 256+7 100, 20 256, 32 256; 32 767 px is reported and **32 768 px collapses to 0** (`B1`/`B2`),
   a *pixel* bound (the same 40 000-unit advance is 5 000 px at font-size 32 and 0 at 256). The unpadded
   arm still aborts in `LookupTable::getSubstitutions` (`:182`, 56-byte region) before any layout, so the
   OOB values themselves remain an inference for a build without ASAN — and `ENABLE_OPENTYPE_VERTICAL` is
   still GTK/WPE-only, so **none of this exists on 14.10**. Original text: **Next: turn the GSUB over-read into a JS-visible byte — a `Vector<uint16_t>` of substituted glyphs is
   built from OOB `substitute[]` entries, so does anything copy it back to script?** `docs/99` closed the
   FreeType corpus negative and found the one real defect next door: `LookupTable::getSubstitutions`
   (`Source/WebCore/platform/graphics/freetype/GSUBTable.cpp`) accepts a `Coverage` format-2 range whose `end+1`
   wraps (`0x8000..0xFFFF`) or descends (`10..5`), so `indexTo + (fromEnd - from)` underflows the bounds test and
   the loop reads past `substitute[]` — `heap-buffer-overflow READ`, 7/7. The substituted glyph ids are what
   `OpenTypeVerticalData::loadVerticalGlyphSubstitutions` stores into `m_verticalGlyphMap`
   (`HashMap<uint16_t,uint16_t>`). The question is whether a *vertical* substitution reaches a JS-visible value:
   the map is only consulted for vertical layout, so a page would need `writing-mode: vertical-rl` / `vertical-lr`
   text with the webfont and a measurable per-glyph difference. **Verify:** one page that loads a font whose
   `vhea`/`vmtx` are valid and whose synthetic `GSUB` carries the wrapping coverage, sets vertical text, and reads
   back per-character advances/`TextMetrics` bounded by the OOB range versus the same font with a correct range —
   a difference proves the OOB glyph ids reached layout; also record whether an id can be made large enough to be
   distinguishable from the neighbours a correct table would have produced. If nothing JS-visible moves, say so
   and mark the defect read-only and inert. Do **not** re-enter the console.
1. ~~**Next: a heap-address disclosure has to come from a memory-safety bug now, because every API surface is
   closed.**~~ **DONE 2026-10-30 — both remaining candidates close, (b) by measurement at the element itself and
   (c) by a tree-wide count (`docs/103`).** `docs/95` (five API surfaces), `docs/98` (rasterisation) and `docs/100`
   (the one ungated OOB read, which is mmap zeroes) close the API route between them, and `docs/100` also names
   why: a resizable `ArrayBuffer` never reaches `fastMalloc`, so the overflow cannot see a neighbour. So the leak
   has to be a bug that copies *engine* bytes into JS. Candidates in order of reachability: (a) ~~the GSUB
   over-read above, if its glyph ids reach layout~~ — **measured, `docs/102`**: they do, but the funnel is a glyph
   id (15 bits, 32 767 px bound) and the code path is absent from the console, so it cannot be the console leak;
   (b) ~~the `docs/94` slot's `m_data8` arm — a freed `StringImpl` hands the element a real character *pointer*,
   and `sinkIntoImageBuffer` reads a vptr from it, so a fake object whose vtable slot lands on a real function
   would make the call return and reveal where it went~~ — **measured, `docs/103`: the value at element+8 is an
   engine pointer and the engine chases two of its own indirections (`+8` → an object → its first word → the
   `+0x20` slot) before calling; where the value did point at a live `StringImpl`, the vptr loaded was
   `(m_length<<32)|m_refCount = 0x0000000300000002`, which is never a vtable, and the call's only JS-visible
   product is `width/height` of an `ImageBuffer` a real function returned**;
   (c) ~~any new ungated producer of a view/OOB length~~ — **counted, `docs/103`: 2 raw `JSC::JSArrayBufferView`
   occurrences in `Source/WebCore` outside `bindings/js/`, both `IDBKey` (`docs/96`), and every converter spelling
   including `toWrappedAllowShared` applies the resizable refusal — 0 new producers**. So the leak has to come
   from a *different* bug class than "an OOB length that reaches a copy", and this action has no candidate left.
   Original text: **Next: a heap-address disclosure has to come from a memory-safety bug now, because every API surface is
   closed.** `docs/95` (five API surfaces), `docs/98` (rasterisation) and `docs/100` (the one ungated OOB read, which
   is mmap zeroes) close the API route between them, and `docs/100` also names why: a resizable `ArrayBuffer`
   never reaches `fastMalloc`, so the overflow cannot see a neighbour. So the leak has to be a bug that copies
   *engine* bytes into JS. Candidates in order of reachability: (a) ~~the GSUB over-read above, if its glyph ids
   reach layout~~ — **measured, `docs/102`**: they do, but the funnel is a glyph id (15 bits, 32 767 px bound) and
   the code path is absent from the console, so it cannot be the console leak**; (b) the `docs/94` slot's `m_data8` arm — a freed `StringImpl` hands the element a real character
   *pointer*, and `sinkIntoImageBuffer` reads a vptr from it, so a fake object whose vtable slot lands on a real
   function would make the call return and reveal where it went; (c) any new ungated producer of a view/OOB length.
   **Verify:** `docs/95`'s rule — a JS-visible value that changes between two runs **and** lies inside a mapping
   of the same `/proc/<pid>/maps`, with `research/leak-sweep/diff.py` as the scorer and the assumed class of each
   candidate written down before the run.

1. ~~**Next: take the OTF out of the engine and score it table by table — `docs/101` §4's cause is read
   from the source, not from the bytes, and the 65 535-glyph cmap is inferred, not measured.**~~ **DONE
   2026-10-30 (`docs/104`) — the OTF is out of the engine and every claim in §4 is byte for byte
   confirmed, while §3's clamp statement is falsified.** Three runs, one arm each, gdb attached to the
   run's own WebProcess at `*FT_New_Memory_Face` (single caller in the drop) with `$rsi/$rdx` dumped:
   `G6` 1 348 B, `G4` 1 536 B, `N3` 6 947 424 B, all `OTTO` with the same 14 tables and no
   `loca`/`glyf` (`maxp` 4/6/65 535). `G6` is one LigatureSet, one offset `8`, coverage at +18 with
   `GlyphCount` 1 — `hb-shape` gives `[2=0+900]`, the page's `w=90.00`. `G4` is
   `0001 001a 0002 0008 | 0002 0006 000c | …`: `LigatureSetCount` = 2 with **one** offset written and
   the second slot = `0x0002`, the first set's own `LigatureCount` (the walk a reader does lands on
   the coverage offset, 26, as its "LigatureCount"); fontTools 4.67 refuses the subtable (`ValueError:
   bytes length not a multiple of item size`) and `hb-shape` gives `[1=0+200|4=1+200]` = the page's
   `w=40.00`; the lookup is feature 0 `liga`, the only feature the `DFLT` script enables. `N3`'s
   format-12 subtable is intact (65 535 groups, 786 436 B) and its format-4 one is malformed
   *differently than predicted*: `bmpMappings` is 65 505 (the arm's range crosses U+10000, 30 non-BMP
   mappings), so `segCount` is 65 506 and does not wrap — `clampTo<uint16_t>` saturates `length` and
   `segCountX2` at 65 535 against 524 064 real bytes. New facts: glyph ids follow
   `std::sort(…, compareCodepointsLexicographically)` (:1430), not document order; Ligature offsets are
   relative to the set's start including its `2 + 2n` header. Two predictions were corrected by the
   dumps (glyph ids, and the `segCountX2 == 0` claim), and neither correction changes any conclusion.
   Original text: **Next: take the OTF out of the engine and score it table by table — `docs/101` §4's cause is read
   from the source, not from the bytes, and the 65 535-glyph cmap is inferred, not measured.**
   `docs/101` measured the *behaviour* with one variable per arm (two ligatures sharing a first glyph
   lose all substitution: `w=40.00` vs `90.00`; six arms) and found the two lines that explain it
   (`append16(ligaturePairs.size())` at :771 against `grow(overlappingFirstGlyphSegmentLengths.size() * 2)`
   at :772), and it inferred that `N3`'s `segCountX2 == 0` format-4 subtable is masked by the
   format-12 subtable at the same offset. Neither claim has been made against bytes the engine
   produced. **Verify:** capture the buffer on the oracle with gdb — breakpoint on
   `WebCore::createFontCustomPlatformData(SharedBuffer&, WTF::String const&)`
   (`FontCustomPlatformDataFreeType.cpp:137`, the only caller of `FT_New_Memory_Face`), `finish`, dump
   `buffer.data()`/`buffer.size()` — for `G6` (one ligature), `G4` (two sharing a first glyph) and
   `N3` (65 535 glyphs), then parse each dump with fontTools in the `wk` box: `G6` must be one
   `LigatureSet` with one offset, `G4` must declare two sets with only one offset written so that the
   second offset is the first LigatureSet's own header bytes (that overlap is the byte-level statement
   of §4 and of the shaper's rejection), and `N3` must show a format-4 subtable with `segCountX2 == 0`
   beside an intact format-12 one. If a dump disagrees with §4, correct §4. Do **not** re-enter the
   console.
1. ~~**Next: make the ligature count overshoot the GSUB table and see whether any reader reads past it**~~ **DONE
   2026-10-30 — it overshoots, and every reader in the process is bounded (`docs/105`).** One arm with 300
   ligatures all starting with `f` (`G10-lig300-f`), dumped at `FT_New_Memory_Face`: `LigatureSetCount` = **300**
   with **one** offset slot grown and slot 1 = `0x012c` = the first set's own `LigatureCount`, at 150× `G4`'s
   size (subtable 3 016 B of a 3 224-byte `GSUB`, `maxp.numGlyphs` 327, `w=60.00`). A new byte model
   (`tools/gsub-trust-model.py`) separates three questions: enumerating the declared array ends at subtable+606,
   **2 410 B short** of the subtable's end (the declared array can never overtake the data — 2 B declared per
   pair against 6-8 B emitted); following the bogus offsets reaches **810 B past the subtable** and, across all
   300, **3 584 B past the `GSUB` table's end** into `OS/2`/`cmap`; and one bogus record's `compCount` 65 535
   would ask for **127 584 B past the end of the font**. So a naive reader *does* leave the buffer — and no
   reader here does: the console shapes with HarfBuzz (`OptionsPlayStation.cmake:329-334` sets `USE_FREETYPE`/
   `USE_HARFBUZZ` unconditionally), whose sanitizer bounds every offset (fontTools 4.67 fails the decompile with
   `unpack requires a buffer of 2 bytes` at `CompCount`, `hb-shape` gives `[6=0+200|1=1+200|1=2+200]`), and the
   drop's own parser reads `lookupType != 1` only (`OpenTypeVerticalData.cpp:140`) and is GTK/WPE-only anyway.
   The well-formed twin at the same N (`G11-lig300-distinct`, 300 distinct first glyphs) measures **100.00** and
   decompiles cleanly, in the same run as the defective arm's 60.00 — so it is the count/slot mismatch, not the
   size. ASAN, quarantine off, two arms: 0 reports, 0 aborts, `EXIT=124`, `access: none` in all four logs.
   Original text: the subtable declares `ligaturePairs.size()` sets while `grow(overlappingFirstGlyphSegmentLengths.size() * 2)`
   wrote one offset per *distinct first glyph* (`:771-772`), so a font with N ligatures that all start with the
   same glyph declares N offsets and writes one. In `G4` (N=2) the bogus slot landed on the first set's
   `LigatureCount` — a 2 — so the damage is invisible; with N large, a reader that enumerates the declared array
   reads `2N-2` bytes that were never written, and `GSUB` is table 2 of 14, so those reads cross into `OS/2`,
   `VORG` and `cmap` inside the same font buffer. **Verify:** one corpus arm with 300 ligatures that all start
   with `f` (`{fa, fb, …}`; a real `ff`/`fi`/`fl` font is the same shape), dumped through
   `research/svgfont/otfgdb.sh` to confirm the layout (count 300, one offset, the second slot = the first set's
   `LigatureCount`); then (a) score what a count-trusting reader does with the dump — fontTools' GSUB decompile
   and `hb-shape` on text that reaches the lookup — and (b) run the same page under the ASAN oracle, quarantine
   off, one arm, scoring from `ERROR: AddressSanitizer` frames. If the reader stays inside the `SharedBuffer`,
   the result is "malformed but not memory-unsafe" and `docs/101` §5's assertion becomes measured instead of
   argued; if it does not, this is a second console-live font defect and `docs/99`'s family grows. Do **not**
   re-enter the console. (This is now the first unchecked local action: with it, everything else in this list is
   either done or the console half.)

1. ~~**Next: the SVG font writer — the only console-live font path left, and it is WebKit building an
   sfnt out of page data.**~~ **DONE 2026-10-30 — reachable on both halves, 52 arms with no sanitizer
   report, and one silent GSUB defect that upstream shares (`docs/101`).** In-document `<font>` +
   `font-family` needs no `@font-face` (`SVGFontFaceElement::rebuildFontFace` :262-298 →
   `Resolver::addCurrentSVGFontFaceRules`); `url(f.svg#f1)` goes through `CachedSVGFont` and needs a
   `<font-face>` child or it is `st=error`. The writer emits a **CFF/OTTO** font (14 tables, no
   `loca`/`glyf`), one Type-2 charstring per glyph. 52 arms / 82 executions / 11 runs: **0 sanitizer
   reports, 0 aborts**, 45 accepted; 65 535 glyphs loads and is used, 65 536 refuses the font, a bad
   `d` fails the whole font, `units-per-em="-1000"` zeroes every advance, `H`/`V`/`Q`/`A` normalise
   correctly. The defect: two ligatures sharing a first glyph (the `ff`/`fi`/`fl` case) write
   `LigatureSetCount = ligaturePairs.size()` with one offset per distinct first glyph (:771-772), the
   lookup is dropped and `w` falls to the two single advances (40.00 vs 90.00, 6 arms, 1 variable);
   upstream main has both lines verbatim, so it is WebKit's, not Sony's. Original text: **Next: the SVG font writer — the only console-live font path left, and it is WebKit building an
   sfnt out of page data.** `CSSFontFaceSource::load` calls `convertSVGToOTFFont` for an in-document
   `<font>` referenced from `src` (`CSSFontFaceSrcLocalValue::svgFontFaceElement`) and for an external
   `url(font.svg#id)` through `CachedSVGFont`; the result is handed to `createFontCustomPlatformData`
   → `FT_New_Memory_Face`. Unlike `docs/99` §3's GSUB bug, SVG fonts are always compiled — no feature
   macro gates them — so this path exists on PLAYSTATION. Both halves are page-controlled: the path
   parser (`SVGPathParser`) and the sfnt assembly (`SVGToOTFFontConversion.cpp`, ~1560 lines that write
   `head`/`maxp`/`hmtx`/`cmap`/`loca`/`glyf` by hand). **Verify:** (a) first that the path is
   reachable at all — one page with an in-document `<svg><defs><font id="f" horiz-adv-x="…"><font-face
   units-per-em="…" ascent="…"/><glyph unicode="A" d="M0 0 L100 0 L100 100 Z"/></font></defs></svg>`
   plus `@font-face { src: url(#f) format(svg) }`, and its external twin `url(font.svg#f)` — and a
   beacon that says which one loaded (`st=loaded`, measured width against a nonexistent family); a
   path that never loads is itself the result and must be written down before any mutation is tried;
   (b) then one mutation per arm under the ASAN oracle, quarantine off, `BEG` before each arm: `d`
   with a huge segment count, a `d` that ends mid-command, `<glyph>` with no `d`, duplicate
   `unicode`, `horiz-adv-x` 0/0xFFFF, `units-per-em` 0, `ascent` > `units-per-em`, a `<font>` with
   65536 glyphs, and a `<font-face>` whose `bbox` disagrees with the glyphs; (c) a control font
   element with one square glyph. Score from `ERROR: AddressSanitizer` frames and from whether
   FreeType accepts the OTF WebKit wrote. Do **not** re-enter the console.

1. ~~**Next: the font parser is page-reachable and unsanitised — measure what a page can make FreeType do.**~~
   **DONE 2026-10-30 — FreeType takes the whole structured corpus without a sanitizer report, and the
   drop's vertical GSUB parser reads past its table buffer 7/7 (`docs/99`).** 190 arms over two bases
   (table-directory runs, per-table file truncations at every boundary, `head`/`maxp`/`loca`/`glyf`/
   `hhea`/`hmtx`/`cmap`/`name`/`post` field mutations, WOFF 1.0 header faults, four real colour faces,
   and a synthetic `GSUB`) run as page `FontFace`s, quarantine off, one `BEG`/`RES` beacon pair per arm:
   **109 accepted, 77 rejected, 0 sanitizer reports on any FreeType input**. The rejection line is
   per-table and sits exactly at `glyf` — a cut at or after `glyf` still opens the face (`TR-glyf-a`
   `st=loaded`, then `w=60.00` against the control's `55.56`: the face has no outlines and the page
   falls back per character), a cut before it does not. The one defect is WebKit's own:
   `LookupTable::getSubstitutions` accepts a `Coverage` format-2 range whose `end+1` wraps (0x8000..
   0xFFFF) or descends (10..5) and indexes `substitute[]` past the table — `heap-buffer-overflow READ
   of size 2` at `OpenTypeVerticalData.cpp:182`, 7/7 over six runs and two bases, region = the 56-byte
   `openTypeTable()` copy, reached from `CSSFontFaceSource::font` with a vertical `FontDescription`.
   Upstream main carries the guard the drop lacks (`fromEnd <= from`, plus `unsigned` locals), so it is
   the **third source-level deviation** of `docs/95` §6's family — and `ENABLE(OPENTYPE_VERTICAL)` is
   on only for GTK/WPE (`PlatformEnable.h:887`, `OptionsPlayStation.cmake` never sets it), so it is
   **compiled out on PlayStation**. Limits in `docs/99` §6: the oracle's FreeType is the distro's
   2.13.1, not Sony's; and the `vmtx` advance-height witness did not move layout — withdrawn, not
   explained. Original text: `docs/98` established the enabling facts: `@font-face { src: url(f.ttf) }` over HTTP reaches
   `FontCustomPlatformDataFreeType.cpp:144` (`FT_New_Memory_Face`) with `status=loaded` and metrics identical
   to the `local()` face, and `grep -rn OpenTypeSanitizer Source/WebCore Source/WebKit` is **empty** in this
   drop — there is no OpenType Sanitizer between page bytes and FreeType. Every audit this programme has run
   is WebKit-side; this parser never has been. **Verify:** (a) one page that loads a corpus of mutated fonts
   as `FontFace` objects and reports `status`/`loaded`/`measureText` per arm, so a *rejected* input is
   distinguishable from a *crashing* one — table-directory runs (`numTables`, `tableLength` past the file),
   `head`/`maxp`/`loca`/`cmap`/`glyf`/`hmtx` truncations at every boundary, `loca` disagreeing with
   `maxp.numGlyphs`, `hmtx` shorter than `numberOfHMetrics`, and a bitmap face (CBDT/`sbix`/COLR) to reach
   the non-outline paths; (b) the same corpus under the ASAN oracle, quarantine **off**, one arm per run
   group, scored from `ERROR: AddressSanitizer`/`WTFCrash` frames in the log, with a beacon sent **before**
   each load so an abort names its input; (c) a control arm with the unmodified font. A negative is a
   result — write which families FreeType rejects cleanly. State the version boundary explicitly: the
   oracle's FreeType is the distro's 2.13.1 (`freetype-2.13.1-2.fc39`), the console ships its own, so a
   crash found here is a parser-surface result, not a console claim. Do **not** re-enter the console.
1. ~~**Next: the last un-swept JS-visible byte source — font/glyph rasterisation.**~~ **DONE 2026-10-30 —
   NEGATIVE, and the reason is structural and measured (`docs/98`).** 125 records per run, two processes,
   63 rasterisation arms (9 font configurations × 7 strings), 12 knob arms, 11 odd widths, two SVG-text
   arms, `toDataURL` PNG/JPEG and all 12 `TextMetrics` fields: **0 pointer-shaped words**, **125/125 records
   byte-identical across ASLR**, `pn`/`jpeg` checksums identical. The detector had to be corrected first —
   `docs/95`'s `b5/b6/b7` rule fires on premultiplied grey pixels (`68 68 68 68 00 00 00 00`), 76 of the
   calibration run's 118 records; the sharp rule adds `b3=b4=0` and counts the rejected windows as `grey=`
   (1678 over two runs). The reason, measured on one object: `premult_proof` writes the canonical word into
   a canvas and reads back **eight zero bytes** — a 48-bit address has byte 3 = 0, so it can only sit in an
   alpha-0 pixel where premultiplication zeroes it — while the same bytes through `Blob → arrayBuffer` are
   seen (`raw_chain ptr=1`); the store is `tryFastCalloc` (`ImageBufferCairoImageSurfaceBackend.cpp:86-88`),
   the readback copies `4u * width` densely (`ImageBufferBackend.cpp:113`, measured `odd1..odd509 solid=1`
   with `nz = 4·W·3`), and cairo shows glyphs straight to the destination (`CairoOperations.cpp:311`) with no
   WebKit-side glyph atlas. Controls: recycling canary `painted_ok=533/533 canary_found=0` over 64 fresh
   surfaces, ghosting bit-exact at four odd sizes (`d0 red0`), 48-canvas churn `with_ptr=0`, ink census
   80/80 arms painted (84..24329 px). `EXIT=124`, `access: none`, 26 maps samples per run. Page
   `research/leak-sweep/glyph.html` (`bdbb38ac…`), runner `glyrun.sh` (`0a2a6050…`), logs
   `data/glyph-raster/`. Original text: `docs/97` closed the inverted-bounds thread in both directions
   (zero page-reachable writers, measured), so the write side of `docs/96` is no longer open. What
   `docs/95` named as remaining is the text path: glyph rasterisation, `TextMetrics`, and canvas `fillText`
   have never been scored with the leak detector. **Verify:** one page that renders through many font/glyph
   configurations (`@font-face` with `local()`/`url()`, `unicodeRange` splits, `font-feature-settings`,
   subpixel AA on/off, fractional sizes, `letterSpacing`), reads every JS-visible output back
   (`getImageData`, `toDataURL` length, all `TextMetrics` fields), and is run **twice** in two processes and
   scored against `/proc/<pid>/maps` with `research/leak-sweep/diff.py` and its positive control — a
   ≥10-digit hex token that changes across ASLR and lands in a readable mapping is a disclosure; a stable one
   is a constant and must be written as a negative. If it is negative, write that and treat the leak thread
   as closed for this build. Do **not** re-enter the console.
1. ~~**Next: audit the *write* direction of the same inversion — every consumer that writes into an
   `ArrayBufferView`, and whether an out-of-bounds resizable view can reach one.**~~ **DONE 2026-10-30 —
   ZERO page-reachable writers, and the reason is structural (`docs/97`).** Six functions produce a native
   view and every one refuses `isResizableOrGrowableShared()` at the binding call site —
   `JSArrayBufferView::toWrapped`/`toWrappedAllowShared` (`JSArrayBufferViewInlines.h:94-110`),
   `JSGenericTypedArrayView::toWrapped*` (`JSGenericTypedArrayViewInlines.h:928-942`), and
   `JSArrayBuffer::toWrapped*` (`JSArrayBuffer.h:86-98`, which gates the `ArrayBuffer` arm of every
   `(ArrayBuffer or ArrayBufferView)` union, so `new FontFace('x', resizableAB)` never reaches
   `FontFace.cpp:93` either). `possiblySharedImpl()` has 4 call sites, 3 inside a gated function, and the
   fourth is `IDBKey.cpp:55` — the read of `docs/96`. The IDL census (36 statements, parsed, not grepped)
   gives **7 write consumers**, of which exactly one exists here: `Crypto::getRandomValues`
   (`Crypto.cpp:57`, bound `array.byteLength()`, cap 65536); WebGL's `readPixels`/`getBufferSubData`,
   WebCodecs' `copyTo`, OPFS's `read` and WebGPU's `writeBuffer` are all measured absent
   (`webgl=null`, `VideoFrame`/`FileSystemFileHandle`/`navigator.storage.getDirectory` undefined,
   `navigator.gpu` undefined while `GPUQueue` is a function). `TextEncoder::encodeInto`
   (`TextEncoder.cpp:49`, `U8_APPEND` bounded by `byteLength()`) is the typed-view spelling of the same
   shape, also refused. Measured on one object, one process: `K` (key read, 8192 bytes, `at4128=7a7b…`) then
   nine write spellings (`getRandomValues`, `set`, `fill`, `copyWithin`, `sort`, `v[i]=`, two DataView writes,
   `encodeInto`, `XHR.send`) — all `TypeError` except the index write (silent drop, spec), and
   then `RB` (**identical to `K`, byte for byte**) with `RBw` proving the witness sees a page write. Positive
   control: the same eight spellings write on a non-resizable view (`65/66/65/68/69`, `written=8`,
   `nz=8162`). Two-layer picture measured in arm `ok`: the JSC gate follows the **live** bounds
   (`u[4128]=0x47`, `dv.setUint8` both work in bounds, refuse after the shrink) while the IDL converter
   refuses **resizability** even in bounds. Two new facts recorded: the inverted test also returns 0 for an
   in-bounds resizable view, so a `byteLength()`-bounded write fails *closed*; and `ArrayBuffer::resize()`
   memsets the newly-visible range on grow (`ArrayBuffer.cpp:540`), which is why a grow-back is not a usable
   readback witness. Audit `tools/abview-write-sweep.py` **23/23**; pages `caps16.html`
   (`eb6f2c9a…`), `c16run.sh` (`b012a9b6…`); logs `data/abview-write/`. Original text: **Next: audit the
   *write* direction of the same inversion — every consumer that writes into an `ArrayBufferView`, and
   whether an out-of-bounds resizable view can reach one.** `docs/96` closed the read
   direction from both sides: the bounded spellings copy out of the buffer's own zeroed reservation (16/16
   all-zero, and the reservation is `reserveAndCommit`/`tryLargeZeroedMemalignVirtual` by construction) and
   the unbounded one (`byteLength()` underflow → `READ of size 4294963216`) always dies before a byte reaches
   JS. What has not been asked is whether the same inverted test can make the engine *write* out of bounds:
   `ArrayBufferView::setImpl`/`setRangeImpl`/`zeroRangeImpl` (`ArrayBufferView.h:221-262`) bound their
   `memmove`/`memset` with `byteLength()`, and the two `wrappedAs` producers are read-only, so the candidate
   family is elsewhere: every WebCore *and* JSC site that takes a raw `JSArrayBufferView` (`jsDynamicCast`/
   `jsCast`/`jsCast<JSGenericTypedArrayView<…>*>`) and writes through `vector()`+`length()` or
   `data()`+`byteLength()` **without** `JSTypedArray::validateTypedArray`/`isOutOfBounds` — `crypto.getRandomValues`
   is the obvious one to read first, then `WebAssembly`-gated and canvas paths. **Verify:** the sweep's count of
   write consumers (0 is a result and must be written), then for the first candidate a page whose beacon is an
   ASAN `WRITE of size N` at a buffer whose `byteLength` is smaller than N, with the same page and a
   non-resizable control that writes only N. If the count is 0, say so and move to font/glyph rasterisation
   (`docs/95`'s last un-swept JS-visible byte source). Do **not** re-enter the console.

1. ~~**Next: reach `ArrayBufferView::byteOffset()/byteLength()` with an out-of-bounds resizable view — or
   prove every constructor is gated.**~~ **DONE 2026-10-30 — reachable, through exactly one ungated producer,
   and it is a JS-visible out-of-bounds read plus two crash spellings (`docs/96`).** The producer is
   `IDBKey::createBinary(JSC::JSArrayBufferView&)` (`IDBKey.cpp:53-59`): it calls
   `JSArrayBufferView::possiblySharedImpl()` → `wrappedAs()` (which deliberately skips `verifySubRangeLength`
   for resizable buffers, `GenericTypedArrayViewInlines.h:111-112`) → `ThreadSafeDataBuffer::copyData(data(),
   byteLength())` → `memcpy`. `IDBKeyRange.only(view)` needs no database and is synchronous, and the binary key
   comes back to JS as an `ArrayBuffer` (`IDBBindingUtilities.cpp:161-172`). Measured (`caps15.html`
   `60a9556b…`, quarantine off): `R1 jsBL=0 jsLen=0 off=0 bufBL=4112` → `R1 ok type=ArrayBuffer bl=8192`
   with the whole pre-shrink `i^0x5a` pattern including `at4128=7a7b7879…` — an 8192-byte copy out of a
   4112-byte buffer, returned to JS. The in-bounds arm is the same inversion from the other side:
   `R0 jsBL=8192 → bl=0`. Controls on the *same object*: `structuredClone` → `DataCloneError`,
   `new Blob([v])` → `TypeError`. Audit `tools/oobview-audit.py` 12/12: the gate exists only in
   `toWrapped`/`toWrappedAllowShared` and in the serializer's call-site `isOutOfBounds()`
   (`SerializedScriptValue.cpp:1377`); `possiblySharedImpl()` has exactly two WebCore callers. Two crash
   spellings: a shrink that crosses a **64 KiB** boundary (`PageCount::pageSize`, `PageCount.h:111`; `resize`
   mprotects `[roundUp64K(new), old)` PROT_NONE) → ASAN `SEGV` in `__memcpy_avx_unaligned_erms` ←
   `ThreadSafeDataBuffer.h:52` ← `IDBKey.cpp:58` ← `IDBBindingUtilities.cpp:250` ← `IDBKeyRange.cpp:75` (a
   shrink 8192→4096 does *not* fault, and still reads 8192 — measured); and the **auto-length underflow**
   (`byteOffset > bufferByteLength` → `roundDownToMultipleOf(1, underflow)` truncated to `unsigned`) →
   `READ of size 4294963216`. Every bounded byte is page-written or zero, so this is **not** a disclosure and
   **not** criterion 3. Logs `data/oobview/`.
   Original text: **Next: reach `ArrayBufferView::byteOffset()/byteLength()` with an out-of-bounds resizable
   view — or prove every constructor is gated.** The drop's bounds test is inverted relative to upstream
   (`docs/95` §6) and the only gate measured is `toWrapped`'s refusal of resizable buffers. Enumerate every
   path that builds a `JSC::ArrayBufferView` for WebCore *without* that gate: callers of `wrappedAs()` and
   `possiblySharedImpl()`, `DataView::wrappedAs` (`DataView.h:80`), `AudioBuffer.copyToChannel` /
   `copyFromChannel` (typed, not a union), and any binding with `[AllowShared]`. For the first one that can
   be handed an OOB view, call a consumer whose output is JS-visible (`Blob.arrayBuffer`,
   `TextDecoder.decode`, `ImageData`'s `.data`, `AudioBuffer.copyFromChannel`) with a **fixed-length** view
   (`new Uint8Array(ab, 0, N)`, not the length-tracking form) over a resizable buffer shrunk after the view
   was made. **Verify:** a beacon of the form `oob size=4096 jsBL=0` — the consumer returns the view's raw
   `lengthRaw()` while `view.byteLength` is 0 — and the same page with a non-resizable control returns 0.
   Cap the requested length at one page (`resize` keeps the first page mapped, so a bounded read does not
   fault); a `SEGV` at the page boundary is not a result and must be recorded as a crash. If every
   constructor is gated, write that as the negative and move to font/glyph rasterisation, the last
   un-swept JS-visible byte source in this build.

1. ~~**Next: enumerate the family behind that abort — every page-reachable way to make message
   deserialization fail, and which of them need a resizable ArrayBuffer.**~~ **DONE 2026-10-30 — the
   family is six `RELEASE_ASSERT` sites, four of them abort from page script, and exactly one input
   reaches any of them (`docs/90`).** `grep -rn hasPendingTerminationException` gives six sites that
   follow a `MessageEvent::create` (`BroadcastChannel.cpp:256`, `LocalDOMWindow.cpp:947`,
   `MessagePort.cpp:295`, `WorkerMessagingProxy.cpp:199` and `:245`, `ServiceWorkerContainer.cpp:472`),
   not the two `docs/89` recorded. Measured, one mechanism per arm (`caps10.html`, md5
   `daed8a5fc70ded2ca1a798dadcbc910e`): MessagePort **aborts** (3/3), `window.postMessage` **aborts** in
   both IDL spellings (3/3 at `LocalDOMWindow.cpp:947`), worker → document **aborts**
   (2/2 at `WorkerMessagingProxy.cpp:199`), document → worker **aborts** (`:245`, thread T9). The other
   two do not, for measured reasons: a service worker's 0-byte transfer arrives **non-resizable**
   (`mx=0` across the SW→client IPC versus `mx=192` for the same buffer over a MessagePort), so
   `DataView::wrappedAs` returns nullptr and `toJS` yields `null` with no exception; and
   `BroadcastChannel` has no transfer list, so the buffer is written in-line at the view's dump and the
   DataView arrives intact. **The whole family needs a resizable ArrayBuffer** — the one throw is
   `JSDataView::create` via the verifying `DataView::wrapImpl`, and every other fail path in the
   deserializer is a clean `fail()` → `ValidationError` → `messageerror`. The two candidate second
   members are measured negatives: `constructEmptyArray` cannot throw from a page payload (ArrayStorage
   allocates a fixed vector, so 0x10000001 elements arrive, 22 s walk, and 0x10000000 behaves
   identically), and the transfer-list rejections all throw at `postMessage` before a message exists.
   The sharpest control: the same message through `structuredClone` is a catchable `TypeError("Unable to
   deserialize data.")`, 3/3, no abort — the defect is the caller's error mode, not the input.
1. ~~**Next: turn the disengaged optional into a chosen address — groom the 32-byte FastMalloc element so
   `m_serializedBitmap` holds page bytes, then read the fault address out of ASAN.**~~ **DONE 2026-10-30 —
   NEGATIVE, five schemes, and the arms settle more than they shape (`docs/93`).** Arm (a) is real and is
   *not* the fill: with `max_malloc_fill_size=0` the payload is a deterministic recycled chunk, `+8` =
   `0x00000000002b6280` in 4/4 runs, so the non-null pointer survives removing the fill and a release build
   has *two* outcomes, not the one `docs/92` predicted. Arms (b)/(c) never land: 200 × 512-byte `StringImpl`s
   + 900 k objects of churn, 64 CSS `@font-face` faces freed deterministically at `buildCompleted()` with a
   12-character family (the measured class: `sizeof=32 cap=1`, `0x14+12`), the same at 512/1024/2048-byte
   classes (all negative *before* the instrumented class was known), and zero-byte (`gch=Z`, where a landed
   chunk **must** give the `ImageBitmapBacking.cpp:83` early return and a delivered message) and
   `41 41 41 41 00 00 00 00` (`gch=X`) payloads — every arm crashed with `+8` unchanged, 5/5, and the zero
   arm crashed 3/3. Three findings the next arm must design around: a `StringImpl` puts **no page byte** at
   `+8` (that offset is `m_length`; characters start at `0x14`), the `Vector` is allocated in the
   `takeAllMessagesForPort` **reply dispatch** after the IPC round trip (not in the getter's frame), and the
   `WeakRef`-plus-churn witness is unusable as the free side — 200 targets survived 900,000 allocations in a
   later job (`dead=0`, 3/3) because `JSWeakObjectRef::deref` write-barriers its target on every version
   change (`JSWeakObjectRef.h:50-57`). Provenance: every run is on oracle file `b32d7b655…` (the 24-byte
   print that no longer preempts the SEGV), `ninja` idle; page `caps11.html`
   (`f2aa6befd12d18c8bf88a2618b60f876`), runner `c11run.sh` (`ba79609b93a142fc5fa24da8ccf7f55c`).
   `docs/93` also records two dead family members `docs/90`'s table does not name, both measured on their own
   channel: the **agent-cluster** comparison (Wasm tags) is dead because `WebAssembly` is `undefined` while
   the `SharedWorker` port and a cross-origin `window.postMessage` both deliver, and the
   **`isTypeExposedToGlobalObject`** membrane is unreachable because the `AudioContext` never leaves
   `state=suspended` here and the console turns `ENABLE_WEB_AUDIO` off.
1. ~~**Next: shape with an allocation whose byte 8 *is* page data, and put the free in the reply's job.**~~
   **DONE 2026-10-30 — the sixth scheme lands, and the free belongs in the getter, not the reply: the element
   reuses the buffer a `structuredClone()` frees at the end of its own call, so the field is page bytes and ASAN
   names the address they encode (`docs/94`).** `StringImpl` was the wrong vehicle for two reasons this run
   measured: `+8` is `m_data8` (`StringImpl.h:161-171`), so a freed `StringImpl` hands the element a *pointer*,
   and a `Blob` body's free is GC-bound. The vehicle that works is the serializer's own output buffer: `arm=clone`
   runs `structuredClone(<16-bit string>)` as the last statement of the getter, the stream is
   `[version=13/4B][StringTag/1B][length|8bitFlag/4B][characters]`, and element `+8` reads stream bytes 8..15.
   Measured, quarantine off, `max_malloc_fill_size=0`, every arm on the drop's file
   (`4e3d9ea56468dfa59230d48cea4b5321`, lib relinked 10:23:06, `strings | grep -c "[IBT]"` = 0):
   `'A','B',NUL…,U+0100` → `SEGV on unknown address 0x000042004100` (2/2); `'C','D'` →
   `0x000044004300`; the 8-bit spelling → `0x000043424180` (the low byte is `StringDataIs8BitFlag`); all-NUL
   characters → **no crash at all**, the message arrives as `ImageBitmap:w0h0` (`w=0 h=0`) — `docs/92` §4's
   detached-bitmap branch, measured. Controls: a 3-unit string (stream 15 B → capacity 16, class 16) does not
   take the slot (no address named), and the same 8-unit arm with the ASAN malloc fill on does not either, so the
   value demonstrably comes from stale block content. This also settles the disputed point in `docs/93`: the
   element is built in the **sender** (`ImageBitmap::detachBitmaps`, `SerializedScriptValue.cpp:5490`), because
   it reuses a block freed inside the getter and not one freed by the reply's dispatch. Still a read-only,
   non-JS-observable dereference — a DoS with a page-chosen address, and the field is 56 controlled bits
   (`0x00 c0h c0l c1h c1l c2h c2l c3l`). Page `research/fuzz-cssom/caps14.html`
   (md5 `5e6619afdace5c68d4f94aba1bae55a2`), runner `c14run.sh` (`fa5ee19c60c2c77793340c23a11f4575`), gdb probe
   `c14gdb.sh` (`6abdc8e069e43e905bc3ab13dbc663a2`); logs `/tmp/S_c14_cl*.log`, `/tmp/G_gdb*.log`.
   Original text: **shape with an allocation whose byte 8 *is* page data, and put the free in the reply's job.**
   A 32-byte `SharedBuffer` body does what a `StringImpl` cannot: `new Blob([new Uint8Array(32)])` puts our bytes
   at `+0`…`+31`, so `+8` can be `0x41…`, `+24` decides engagement and a zeroed payload produces the
   `ImageBitmapBacking.cpp:83` early return and a delivered message. The free is the hard half: the blob body dies
   with its wrapper, so the churn has to run in the job that *decodes the reply*.
1. ~~**Next: give the page-chosen pointer something to point at — hunt one page-reachable heap-address disclosure.**~~
   **DONE 2026-10-30 — negative on every surface the item named, and the sweep also found a second
   source-level deviation (`docs/95`).** Two runs per part, 193 beacon records (180 probes), scored against
   `/proc/<pid>/maps`: 183 byte-identical across ASLR after the URL port is normalised and the 10 that change
   are clocks/UUIDs/`Math.random`, none in a mapping; no entry anywhere contains a ≥10-digit hex token
   except the detector's own control. Readback surfaces are 15/15
   `nz=0/64`; truncated/corrupt PNG/JPEG, SVG filters, `feTile`, canvas filters and bitmap resizes give no
   pointer-shaped word (detector calibrated: `det_ctl pos=1` inside `0x610000000000`, `neg=0`).
   `decodeAudioData` fails `EncodingError` on five WAVs. Side find: `ArrayBufferView::byteOffset()/
   byteLength()` invert the bounds test (upstream has no `!`), but `toWrapped` refuses all resizable views,
   so an OOB view never reaches them — measured, `TypeError: Underlying ArrayBuffer has been detached from
   the view or out-of-bounds`. The item's premise stands: **no API in this build hands JS an address**, so
   the disclosure has to come from a memory-safety bug. Superseded by the new item 1 above.
   Original text: the slot now yields a virtual call (`buffer->sinkIntoImageBuffer()`, `ImageBuffer.cpp:119`) through a value the
   page writes, so it crashes at whatever address the page names and nowhere else. Weaponising it needs one
   address: a mapped object whose first 8 bytes the page also controls (a fake vtable), or a live
   `SerializedImageBuffer` to re-sink (which would make `width()`/`height()` read from attacker-chosen memory —
   a JS-observable read). Neither is reachable without a disclosure, and this programme has never hunted one
   directly. Sweep the value-producing boundaries the audits only *assumed* clean, one arm each, scored on a
   JS-visible number/string that equals an address measured in the same run and that **moves with ASLR** between
   two runs: `structuredClone`/`postMessage` failure texts (`DataCloneError` messages quote property names),
   `DOMException`/`Error().stack`, `ImageBitmap` crossing a worker (identity, `width` of a failed transfer),
   `URL`/`performance`/`Intl` strings, and the `MessageEvent` `origin`/`source` fields. **Verify:** a beacon whose
   value changes between two runs of the same page and matches a heap or library address printed by the same
   build (the `[IBT]`-style instrument or the gdb probe); a value that is stable across ASLR is a constant, not a
   leak, and must be recorded as a negative. Do **not** re-enter the console for this.
1. ~~**Next: the split-dump shape — a native whose *length* is written at one point in the walk and whose
   *bytes* are written at another, with a page getter running in between.**~~ **DONE 2026-10-30 — ImageBitmap's
   derived length is closed by construction, and the one split that exists is the transfer's out-of-band
   backing store, which crashes the WebProcess 9/9 over three transports (`docs/92`).** Both sides call the
   *same* truncating `IntSize::scale` (`ImageBufferBackend.h:163-170` on the writer via
   `getPixelBuffer` → `toBackendCoordinates`, `IntSize.h:95-104` on the reader), the reader then demands
   `computeBufferSize(format, imageDataSize) == arrayBuffer->byteLength()` **exactly**
   (`ByteArrayPixelBuffer.cpp:61-62`), and every page-reachable creator calls the 4-argument
   `ImageBitmap::createImageBuffer` whose `resolutionScale` defaults to 1 (the only 5-argument call site in
   the tree is the reader itself) — so arm (c) has no page-side input, and `OffscreenCanvas`/`WebCodecsVideoFrame`
   are **measured absent** (`oc=undefined&vf=undefined`), so arm (d) is compiled out. The split that is real:
   the transfer list is validated **before** the walk (`:5397-5399`), `dumpImageBitmap` writes the tag from
   the transfer map **during** it (`:1486-1491`), and `ImageBitmap::detachBitmaps` takes the backing stores
   **after** it (`:5481`) — so a getter that calls `close()` in between leaves a **disengaged**
   `std::optional<ImageBitmapBacking>` at that index, and `readTransferredImageBitmap` calls
   `m_backingStores.at(index)->connect(...)` (`:4034`) with no engagement check. `connect()`'s guard reads a
   field of an object that was never constructed (`ImageBitmapBacking.cpp:83`); in the ASAN build that field
   is the malloc fill, so the deref lands at `ImageBuffer.cpp:119` — `SEGV` on `0xbebebebebebebe`. Measured
   9/9: MessagePort 5 (`ImageBitmapBacking.cpp:91` ← `Chrome::sinkIntoImageBuffer`), `window.postMessage` 2
   (same), document→worker 2 (`:88` ← `WebWorkerClient::sinkIntoImageBuffer`, thread T9), with four controls
   (no close → 8×8 bitmap arrives; getter closes a **different** bitmap → no crash; closed before the call →
   `DataCloneError`; value-path close-before-dump → `DataCloneError`). The mechanism is corroborated by a
   concurrent session's instrumentation, which printed the element: `sizeof=32 size=1 cap=1`, engagement flag
   `0x00` at byte 24, `0xbe` everywhere else. DoS, not a primitive — the pointer is uninitialized memory, not
   attacker bytes. Pages `research/fuzz-cssom/caps13.html` (md5 `e2f28fcf10136e73ce5d1923ccf4bc4d`), runner
   `c13run.sh` (md5 `f72c516986aa678ded9832273137d6fa`), `c13rep.sh`; logs `data/imagebitmap-split/`.
   Original text: `docs/89`-`docs/91` spent
   three runs on the one instance they found (`ArrayBufferView`: view header at dump, buffer contents at
   transfer) and it is now closed three ways (abort, OOB-but-clamped view, inert null). The shape
   generalises, and the serializer has exactly one other page-reachable native whose length is
   *derived* rather than carried: **`ImageBitmap`**, whose copy path dumps
   `serializationState/logicalWidth/logicalHeight/resolutionScale/colorSpace` and then a pixel
   `ArrayBuffer` (`dumpImageBitmap`, `SerializedScriptValue.cpp:1484-1534`, the writes at :1521-1533), while the reader re-derives
   `imageDataSize = logicalSize.scale(resolutionScale)` and hands it to
   `ByteArrayPixelBuffer::tryCreate` (`readImageBitmap`, `:4166-4202`). Read first, then one arm per
   candidate, in this order: (a) `dumpImageBitmap`'s null-`buffer()` path — a getter that calls
   `bitmap.close()` **before** the bitmap is dumped (expect a clean `DataCloneError`/`ValidationError`,
   which is the control); (b) the same `close()` **after** the bitmap is dumped and before the transfer
   detaches, over both transports (the SW path truncates, the port path does not — `docs/91` §3);
   (c) a `resolutionScale` of 0/`Infinity`/`NaN` and a `logicalSize` at `IntSize` limits (the reader
   scales an `IntSize` by a double — `tryCreate` is the only length check); (d) `WebCodecsVideoFrame`
   and `OffscreenCanvas` only if their build flags are on, which must be **measured** in the same run,
   not assumed (`docs/77`'s lesson).
   **Verify:** a table of every `write(...)` pair in `dumpImageBitmap`/`readImageBitmap` and what each
   side computes from it; then, for each arm, the beacon must name the *arrived* bitmap's
   `width/height`/`close()`d-ness and the pixel buffer's length, and the run must be scored from
   `EXIT` + an ASAN/`WTFCrash` frame, never from a beacon. A negative (every disagreement is caught by
   `tryCreate`) is the expected outcome and must be written as such — the value of the action is the
   *rule* ("which natives have a derived length, and which check it"), not a bug.
   Do **not** re-enter the console for this.
1. ~~**Next: stop auditing this generator and take the one structural shape `docs/90` opened — a wrapper
   creation that returns null and leaves a pending exception, whose null result the engine then stores
   and uses.**~~ **DONE 2026-10-30 — the null is stored, is reachable through the object pool, is
   page-observable as an ordinary `null`, and is inert; this shape cannot reach a type confusion
   (`docs/91`).** Audited: 20 `toJS`/`toJSNewlyCreated`/`wrap` call sites in
   `SerializedScriptValue.cpp`, exactly one family unchecked (`readArrayBufferViewImpl`'s twelve
   `wrappedAs` arms) and one more unchecked in principle (`cryptoKey = getJSValue(result.get())`,
   `:3848`). The native can be null in only two ways and only `DataView` can throw, because
   `DataView::wrapImpl` calls the **verifying** `JSDataView::create` while
   `GenericTypedArrayView::wrapImpl` calls the **non-verifying** `create` overload
   (`runtime/DataView.cpp:67` vs `GenericTypedArrayViewInlines.h:145`). Measured, 23 runs over 16 arms,
   quarantine off: over `client.postMessage` a shrunk resizable buffer arrives **non-resizable**
   (`sw12&posted=1&bl=0&mx=0`), so the same payload that **aborts** at `MessagePort.cpp:295` over a
   `MessagePort` (3/3 + a final-build re-run) arrives as **`null`** (2/2 + re-run) — and a typed array
   arrives as an empty out-of-bounds object over the port (`vb0 bb0`, write dropped) but as `null` over
   the SW path. The null is **in the object pool**: with the view repeated four times (one dump + three
   `ObjectReferenceTag`s) all four slots are `null` and `a===b`, `a===cc[0]`, `a===d`
   (`F_POOLSW`: `a=tn1 … ab1&ac01&ad1`), `new Map([[a,1]]).size` is 1 and `JSON.stringify` renders
   `null` — the only throw is the page's own `null.byteLength` `TypeError`. It is inert because the
   deserializer's only typed consumer of a pooled value re-checks `inherits<JSArrayBuffer>()`
   (`:3290-3293`, false for `jsNull()`), the other four `readTerminal()` sites are value positions, and
   an out-of-bounds view is clamped by `viewByteLength` (`JSDataView.h:59-78`) and cannot be
   re-serialized (`:1376`). Auto-length is a **clean `messageerror`** on that transport in both
   directions (`:3311-3315` tests the arriving buffer's resizability), so the explicit-length spelling
   is the only input that reaches the throw. CryptoKey measured on three key classes (extractable HMAC,
   non-extractable HMAC, ECDSA P-256 pair): all arrive as real `CryptoKey`s, so that site has no
   page-side null. Pages `research/fuzz-cssom/caps12.html` (md5
   `1d19801f33e75f07000abbd045601e4f`), `sw12.js` (md5 `20e217ce9debe8ba27023cbd61430dbd`), runner
   `c12run.sh` (md5 `1a8e167f746ca95796be9b8e9fb0c481`); logs `data/deser-null/`.
   Original text: `readArrayBufferViewImpl` is exactly that shape: `toJS(..., wrappedAs(...))` returns
   `jsNull()` while a `RangeError`/`TypeError` is pending, `readArrayBufferViewImpl` returns **true**,
   the message is built and the process dies later in a `RELEASE_ASSERT` that was written for a
   different case. The question for this action is not "how many callers assert" (done) but **how many
   places in the deserializer — and in the DOM bindings it calls — can continue after a failed wrapper
   creation**, and whether any of them can leave a slot that page script then observes as an object of
   the wrong type (a null in an object pool, a `Blob` with a null body, a `Map` key that is null where
   the payload says view). That is the only shape in this drop that could turn a fail-silent path into
   a type confusion, which is what stage criterion 3 needs. Audit, then measure: for each site a
   `mode=` arm on `caps10.html`'s pattern whose verification is that the *arrived* message's slot is
   what the payload wrote (a beacon naming the slot's type and value), never that a beacon fired.
   **Verify:** a table of `toJS`/`toJSNewlyCreated`/`wrap` call sites in `SerializedScriptValue.cpp`
   whose result is not null-checked, each one read; then for every one that a page can reach, one arm
   in which a *successful* message proves the null is stored (beacon the slot) and one where the slot is
   then used by page script without a throw. Record the negative as carefully as the positive: if every
   null is inert (as the `jsNull` view already is), say so and say why the search is finished.
   Do **not** re-enter the console for this.
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
