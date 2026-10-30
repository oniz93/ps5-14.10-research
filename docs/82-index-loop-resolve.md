# docs/82 — the blind spot `docs/81` named: container types resolved through base/member chains (45 → 8), every call in the 310 owner loops walked to depth 3 by receiver type, **0 new windows** — and the 16 rows a name-union over-approximation still flags are all name collisions

The action (`GOAL.md`, first item): `docs/81` followed a callee only when its name had exactly one definition in
the tree, and resolved one hop through the class-qualified `(class, method)` index. That leaves two holes:
**828 of 1,261 rows have no resolved `container_type`** (45 of them *owner* rows, where the verdict logic needs
the type), and **a call whose receiver type is known but whose method name is not unique is never followed**, so
a script window two or three hops away through `m_document->updateStyleIfNeeded()` or
`page->chrome().client().didX()` is invisible.

This doc closes both. One new tool, `tools/index-loop-resolve.py`, and one recall check,
`tools/index-loop-resolve-validate.py`. Five results:

1. **45 unresolved owner types → 8.** 37 rows now carry a type, resolved through the base-class chain
   (`Partition` for `DFAMinimizer`'s `m_partitionedElements`), through member chains
   (`m_atomData.group.terms` → `Vector<Term>`), through pointer/reference member declarations
   (`const DFA& m_dfaA`), through `WTF_GUARDED_BY_LOCK` annotations (`m_frameBufferCache`), and by recovering
   the owning class for out-of-line constructors. The 8 that remain are named and explained in §3; none of them
   can hold a raw script-freeable pointer.
2. **Every call in the 310 owner-row loop bodies was resolved by receiver type and walked to depth 3: 1,084
   calls, 308 resolved to a class (28.4%), 380 unresolved receivers** (loop locals introduced by `auto` from an
   expression the index cannot type). Both sink classes were walked — a literal sink (`dispatchEvent`,
   `resolve(`, `JSC::call`, …, `docs/75`'s list) and a virtual call on a client/observer-typed receiver
   (`docs/66`/`docs/80`) — and the walk finds **exactly one** route: `ApplicationCacheHost::stopDeferringEvents`
   → `dispatchDOMEvent()` → `dispatchEvent`, i.e. the loop `docs/81` already read and measured. **Zero rows gain
   a window.**
3. **The over-approximation agrees, and it cannot miss by name.** The complement of `docs/81`'s unique-name gate
   is to follow *every* definition of a name in the tree (a collision can only add candidates, never hide one).
   That flags **16 rows**, and every one was read in source: **15 are name collisions** (`create`, `size`,
   `x`/`y`/`width`/`height`, `swap`, `matches`, `remove`, `status`/`setStatus`) over a loop that runs no script,
   and the 16th is the one row known to dispatch — `ApplicationCacheHost::stopDeferringEvents`, which is the
   pass's sensitivity control (§5).
4. **The walker's recall is measured, not assumed: 59/60 on an automatically built ground truth** — a caller with
   no window of its own calling a method whose body is a window, i.e. a real multi-hop chain. The single miss is
   a bare call to an overloaded *static free function* (§6), and the first version of the check scored 0/6
   because its "callers" all contained their own `dispatchEvent(` (a depth-1 hit, not a multi-hop test) — that
   correction is recorded, because a bad oracle in this programme already produced one false claim.
5. **No page and no ASAN run follow from this.** The action's conditional — a chain that reaches a sink *and* a
   `remove`/`clear` on the container — is not met: `mutator_in_route` is empty for all 310 rows, and the one
   route (AppCache) has a **re-read** bound and clears its container *after* the loop. §7 records that rather
   than spending a run on an empty candidate.

## 1. Tool and funnel

```
$ python3 tools/index-loop-resolve.py > data/index-loop/resolve.json
files 10500 owner_rows 310
unresolved before {'unresolved_all': 828, 'unresolved_owner': 45}
           after {'unresolved_all': 791, 'unresolved_owner': 8, 'resolved_owner': 37}
counts {'recv-unresolved': 380, 'rows-with-ambiguous-name': 16}
new-window rows 0
real  2m6.534s
```

The tool re-reads nothing from `docs/81` except `data/index-loop/loops.json`: it re-finds each loop by its
recorded line, takes the body span, and then builds four indexes over the same 10,500 files:

* **member types**, keyed `(class, member)`, with three forms the first pass could not match — a pointer/reference
  type (`const DFA& m_dfaA`, `const RenderLayer* m_clipRectsRoot[N]`), an array declarator
  (`SQLTransactionState m_stateAuditTrail[s_sizeOfStateAuditTrail]`), and a `WTF_*` annotation between the name and
  the terminator (`Vector<ScalableImageDecoderFrame, 1> m_frameBufferCache WTF_GUARDED_BY_LOCK(m_lock)`);
* **any field of any class/struct/union**, declarations inside a function body excluded, so a nested struct field
  (`AtomData::group`, `Group::terms`) is walkable but a local `Vector<X> foo;` inside an inline method is not
  keyed to its class;
* **method bodies**, keyed `(class, method)`, from every `.cpp`/`.mm`/`.h`, with the return type of each
  qualified and inline definition (`Document::page` → `Page*`, `Chrome::client` → `ChromeClient&`);
* **bare names**, kept as a fallback only where a class-scoped lookup fails.

Resolution walks: a member chain splits on `.`/`->`, each hop resolved through the base-class BFS
(`vls.class_index()`, the same walk `vector-local-sweep.py`'s `classify()` does) and, for a smart-pointer member,
through the pointee (`std::unique_ptr<WebMData> m_webmData` continues into `WebMData`, not into `unique_ptr`).

## 2. What "depth 3 by receiver type" means here

For each of the 310 owner loops the tool enumerates every call in the body, in six spellings, and resolves the
receiver to a class before touching the method table:

| spelling | receiver resolution |
|---|---|
| `foo(...)` | the owning class first (this is the fix, §4), then a unique-name lookup |
| `this->foo(...)` / `m_x.foo(...)` / `m_x->foo(...)` | owning class, member type, member chain, base chain |
| `local->foo(...)` | the local's declared type; an `auto` local follows its rhs through a member chain or a method return type |
| `container[i]->foo(...)` / `container.at(i).foo(...)` | the element type of the resolved container |
| `m_foo[i]->foo(...)` via `auto& e = m_foo[i]` | the element type of the resolved container |
| `Class::foo(...)` | `Class` from the class index |

Then `route(class, method)` walks method bodies breadth-first to depth 3 and stops at either sink class. A
client-typed receiver stops the walk (the implementation lives in whoever implements the interface, so following
it would land in an unrelated class).

Coverage, stated plainly: **1,084 calls, 308 resolved (28.4%), 380 unresolved receivers, 99 of the 310 rows with
no `RECV_CALL` at all**. The unresolved names are loop locals the index cannot type — `inlineItem` (30),
`builder` (20), `run` (18), `resource` (11), `cell` (9), `rowRenderer` (9), `positionValue` (9), `event` (6) —
almost all `auto` bindings whose rhs is an expression this tool cannot type (a structured binding, a lambda
parameter, or a call on an unindexed type). That is the honest limit of the 28.4% number, and the reason §5 runs a
second, type-free pass instead of trusting the resolver alone.

## 3. Container types: 45 → 8, one row per newly-resolved site

```
before  unresolved_all 828   unresolved_owner 45
after   unresolved_all 791   unresolved_owner  8   resolved_owner 37
```

The 37 newly resolved rows:

| site | container | type |
|---|---|---|
| `Modules/webdatabase/SQLTransactionStateMachine.h:73` | `m_stateAuditTrail` | `SQLTransactionState` |
| `animation/CSSPropertyAnimation.cpp:3812` | `m_propertyToIdMap` | `short` |
| `contentextensions/DFAMinimizer.cpp:85` | `m_partitionedElements` | `Vector<unsigned, 0, ContentExtensionsOverflowHandler>` |
| `contentextensions/DFAMinimizer.cpp:174` | `m_partitionedElements` | same |
| `contentextensions/DFAMinimizer.cpp:187` | `m_partitionedElements` | same |
| `contentextensions/DFAMinimizer.cpp:280` | `m_flattenedTransitionsStartOffsetPerNode` | same |
| `contentextensions/Term.h:637` | `m_atomData.group.terms` | `Vector<Term>` |
| `css/CSSValuePool.cpp:50` | `m_pixelValues` | `LazyNeverDestroyed<CSSPrimitiveValue>` |
| `css/ShorthandSerializer.cpp:196` | `m_longhandValues` | `RefPtr<CSSValue>` |
| `css/ShorthandSerializer.cpp:536` | `m_skipSerializing` | `bool` |
| `cssjit/SelectorCompiler.cpp:1794` | `m_functionCalls` | `Vector<std::pair<Assembler::Call, CodePtr<JSC::OperationPtrTag>>, 32>` |
| `dom/ElementData.cpp:88` | `m_attributeArray` | `Attribute` |
| `dom/ElementData.cpp:95` | `m_attributeArray` | `Attribute` |
| `dom/ElementData.cpp:110` | `m_attributeArray` | `Attribute` |
| `dom/Node.cpp:974` | `m_nodeListAndCollectionCounts` | `unsigned` |
| `editing/TextIterator.cpp:2408` | `m_isCharacterStartBuffer` | `Vector<bool>` |
| `platform/ScrollingMomentumCalculator.cpp:100` | `m_snapAnimationCurveCoefficients` | `FloatSize` |
| `platform/image-decoders/avif/AVIFImageDecoder.cpp:79` | `m_frameBufferCache` | `Vector<ScalableImageDecoderFrame, 1>` |
| `platform/image-decoders/bmp/BMPImageReader.cpp:382` | `m_bitMasks` | `uint32_t` |
| `platform/image-decoders/bmp/BMPImageReader.cpp:421` | `m_bitMasks` | `uint32_t` |
| `platform/image-decoders/bmp/BMPImageReader.cpp:438` | `m_bitMasks` | `uint32_t` |
| `platform/image-decoders/gif/GIFImageDecoder.cpp:104` | `m_frameBufferCache` | `Vector<ScalableImageDecoderFrame, 1>` |
| `platform/image-decoders/webp/WEBPImageDecoder.cpp:103` | `m_frameBufferCache` | `Vector<ScalableImageDecoderFrame, 1>` |
| `platform/image-decoders/webp/WEBPImageDecoder.cpp:354` | `m_frameBufferCache` | `Vector<ScalableImageDecoderFrame, 1>` |
| `platform/text/PlatformLocale.cpp:288` | `m_decimalSymbols` | `String` |
| `platform/text/SegmentedString.h:304` | `m_currentSubstring.currentCharacter8` | `const LChar*` |
| `platform/text/SegmentedString.h:311` | `m_currentSubstring.currentCharacter16` | `const UChar*` |
| `plugins/DOMMimeType.cpp:50` | `m_info.extensions` | `Vector<String>` |
| `rendering/RenderFrameSet.cpp:130` | `m_rows.m_sizes` | `Vector<int>` |
| `rendering/RenderFrameSet.cpp:132` | `m_cols.m_sizes` | `Vector<int>` |
| `rendering/RenderFrameSet.cpp:504` | `m_rows.m_sizes` | `Vector<int>` |
| `rendering/RenderFrameSet.cpp:507` | `m_cols.m_sizes` | `Vector<int>` |
| `rendering/RenderLayer.cpp:242` | `m_clipRectsRoot` | `const RenderLayer*` |
| `rendering/RenderTableCell.cpp:1167` | `m_borders` | `CollapsedBorder` |
| `rendering/shapes/RasterShape.cpp:57` | `m_xIntercepts` | `Vector<int>` |
| `rendering/style/QuotesData.cpp:41` | `m_quotePairs` | `std::pair<String, String>` |
| `rendering/style/QuotesData.cpp:47` | `m_quotePairs` | `std::pair<String, String>` |

Two of the 37 matter for the verdict logic and neither changes it:

* `RenderLayer.cpp:242` (`ClipRectsCache` ctor) is now the only newly-typed row whose *element* class is a raw
  pointer (`const RenderLayer* m_clipRectsRoot[NumCachedClipRectsTypes]`). The loop is
  `for (i…) m_clipRectsRoot[i] = 0;` — no callee, no window, and `docs/81`'s `first_script_pos` is `-1`. Inert
  by inspection, not by the heuristic.
* `SegmentedString.h:304/311` resolve to `const LChar* / const UChar*`, i.e. the *index* is a character offset
  into a buffer, not a slot in a container of pointers. There is nothing to free.

The 8 that remain unresolved, with the reason read from the source:

| site | container | why the type is still unknown |
|---|---|---|
| `contentextensions/DFACombiner.cpp:159` | `m_dfaA.actions` | `DFA` is only forward-declared in the headers (`DFABytecodeCompiler.h:37 struct DFA;`); its definition is not in this drop's header set |
| `contentextensions/DFACombiner.cpp:166` | `m_dfaB.actions` | same |
| `platform/audio/cocoa/AudioFileReaderCocoa.cpp:346` | `m_webmData->m_samples` | `WebMData` is a struct declared in the `.cpp` and `m_webmData`'s declaration is not indexed; the member itself is `Vector<Ref<MediaSampleAVFObjC>>` (`:138`), i.e. owning |
| `platform/audio/cocoa/WebAudioBufferList.cpp:50` | `m_canonicalList->mBuffers` | `AudioBufferList` is a CoreAudio C struct (`mBuffers` is its flexible array) |
| `platform/audio/cocoa/WebAudioBufferList.cpp:103` | `m_canonicalList->mBuffers` | same |
| `platform/graphics/avfoundation/AudioSourceProviderAVFObjC.mm:137` | `m_list->mBuffers` | same |
| `platform/graphics/gbm/GBMBufferSwapchain.cpp:98` | `m_array.object` | `GBMBufferSwapchain.h:132 } m_array;` — an inline **anonymous** struct, so there is no type name to key |
| `platform/graphics/gstreamer/GStreamerVideoFrameHolder.cpp:156` | `m_videoFrame.data` | `GstVideoFrame` is a GStreamer C struct |

None of the 8 is a raw-pointer container of a page-reachable C++ object: four are C structs (`AudioBufferList`
×3, `GstVideoFrame`), two are a forward-declared content-extension type (`DFA`), one is an inline anonymous
struct, and one is an owning `Vector<Ref<MediaSampleAVFObjC>>`. So the 8 do not hide an `ELEMENT-RAW` row.

## 4. The call walk: one route, and it is `docs/81`'s

```
calls 1084   resolved 308 (28.4%)   rows with no RECV_CALL 99   recv-unresolved 380
routes found: 1
  loader/appcache/ApplicationCacheHost.cpp:333  ApplicationCacheHost::stopDeferringEvents
    call dispatchDOMEvent()  ->  ApplicationCacheHost::dispatchDOMEvent  sinks ['dispatchEvent']
```

`ApplicationCacheHost::dispatchDOMEvent` is `m_domApplicationCache->dispatchEvent(createApplicationCacheEvent(…))`
— so the chain from the loop body is two hops and ends in a real DOM dispatch. That is the loop `docs/81` §3
already measured on the oracle (`access: none`, 0 sanitizer lines, a handler re-entering `update()`/`swapCache()`
inside the loop changes nothing). The tool recovering exactly this row, and nothing else, is the result: **no
second member-container index loop in `Source/WebCore` reaches a script window within three hops** once receiver
types are resolved.

The other 309 rows fall into two groups, counted from the JSON:

* **221 rows with no resolved call at all** (99 with no `RECV_CALL` in the body, 122 whose calls were all loop
  locals). These are the rows §5 covers by name instead of by type.
* **88 rows whose calls resolve but whose bodies do not reach a sink within three hops** — render/layout
  arithmetic (`LayoutUnit`, `FloatSize`, `CellStruct`), audio DSP, image decoding. 7 of these already had a window
  in `docs/81` — the verdicts across all 8 windowed rows are 3 `SHRINK-CACHED`, 2 `SHRINK-MUTATED` and 3
  `OWNER-WINDOW`, and the eighth is the route row above — so the resolver adds no new sink to any of them, and
  `mutator_in_route` is empty for all 310 rows (no callee on any route mutates the same-named member).

`read_after_window` is **0** across all 310 owner rows, unchanged from `docs/81`: no owner loop reads an index
after a script window in the same iteration.

## 5. The over-approximation: follow *every* definition of a name

The resolver's 28.4% coverage is only as good as its type index. The complement is cheap and cannot miss by name:
for every method name in the tree, compute the minimum depth at which **some** definition of that name reaches a
window (literal sink, or a client-name callback by spelling), propagating names at depths 2 and 3. Then flag every
owner row whose body calls a name with depth ≤ 3, ignoring receivers entirely. A name collision can only add
candidates; it cannot hide one.

16 rows are flagged. All 16 were read in source:

| row | container | flagged name | what the loop actually does | verdict |
|---|---|---|---|---|
| `Modules/webaudio/ScriptProcessorNode.cpp:91` | `m_inputBuffers` | `create` | `m_inputBuffers[i] = AudioBuffer::create(…)` | collision (`AudioBuffer::create` allocates, runs no script) |
| `Modules/webdatabase/SQLStatement.cpp:133` | `m_arguments` | `create` | `statement->bindValue(i+1, m_arguments[i])` | collision (`SQLError::create`) |
| `css/CSSFontFace.cpp:650` | `m_sources` | `setStatus` | `source->status()`, `source->load(document())` | `docs/65`'s family; bound re-read, `m_sources` not script-mutable |
| `css/CSSFontFace.cpp:737` | `m_sources` | `status`, `create` | same loop's other half | same |
| `loader/appcache/ApplicationCacheHost.cpp:333` | `m_deferredEvents` | `dispatchDOMEvent` | **the one real dispatch** | `docs/81` §3, measured |
| `loader/cache/MemoryCache.cpp:350` | `m_allResources` | `remove` | descending loop, `copyToVector(*m_allResources[i])`, `destroyDecodedData()`, `remove(*resource)`, `m_allResources.shrink(i)` | no script: `SetForScope m_inPruneResources` guards re-entry, `remove` is `MemoryCache::remove`, and the descending index stays valid after `shrink(i)` |
| `platform/graphics/ComplexTextController.cpp:845` | `m_coreTextIndices` | `swap` | `std::swap(m_coreTextIndices[r], m_coreTextIndices[end])` | collision (`std::swap`) |
| `platform/graphics/GlyphBuffer.h:219` | `m_advances` | `x`,`y`,`width`,`height`,`size` | `makeGlyphBufferAdvance(-x(m_origins[i]) + width(m_advances[i]) …)` | collisions (`FloatSize` accessors) |
| `platform/graphics/GlyphBuffer.h:230` | `m_origins` | `x`,`y` | `if (x(m_origins[i]) \|\| y(m_origins[i]))` | collisions |
| `platform/graphics/filters/FilterOperations.cpp:197` | `m_operations` | `create` | `toOp->blend(fromOp.get(), context)` | collision; `blend` is arithmetic |
| `platform/graphics/gbm/GBMBufferSwapchain.cpp:98` | `m_array.object` | `swap` | fills empty slots with `new Buffer` | collision |
| `platform/image-decoders/gif/GIFImageDecoder.cpp:104` | `m_frameBufferCache` | `size` | `auto& frame = m_frameBufferCache[i-1]` + disposal-method switch | collision; pure decode |
| `platform/image-decoders/webp/WEBPImageDecoder.cpp:103` | `m_frameBufferCache` | `size` | `webpFrameAtIndex(…)` + rect test | collision; pure decode |
| `platform/text/PlatformLocale.cpp:288` | `m_decimalSymbols` | `matches` | `matches(input, position, m_decimalSymbols[symbolIndex])` | collision (a local `String` comparison) |
| `rendering/RenderFrameSet.cpp:130` | `m_rows.m_sizes` | `height`,`width` | `xPos += m_cols.m_sizes[c]` | collisions (`LayoutUnit::height/width`) |
| `rendering/RenderFrameSet.cpp:132` | `m_cols.m_sizes` | `height` | same paint loop's column pass | collision |

Sensitivity control: this pass flags `ApplicationCacheHost.cpp:333` — the one row that provably dispatches (via
`dispatchDOMEvent`, §4 and `docs/81` §3). A pass that flagged nothing would be uninformative; this one flags
exactly one real case and 15 collisions, and the real case is the known one.

## 6. Recall, measured — and one correction to the oracle

Ground truth without hand-picking: for every method body **with no window of its own**, find a call it makes to a
method whose body *is* a window. That caller→callee pair is a real multi-hop chain, and `route(caller)` must
reach the callee at depth ≥ 2.

```
$ python3 tools/index-loop-resolve-validate.py
bare multi-hop callers tested: 60  ok=59  miss=1
  MISS ('DOMCacheStorage', 'startSequentialMatch', 'doSequentialMatch', [])
receiver multi-hop callers tested: 0  ok=0  miss=0
real  2m12s
```

* **59/60 on the bare arm.** The miss is `Modules/cache/DOMCacheStorage.cpp:86` — `startSequentialMatch` and
  `doSequentialMatch` are **static free functions** (`:65`, `:86`), and `doSequentialMatch` is *also* a member
  (`:96`). Two definitions block the unique-name route and neither is in `(class, method)`, so a bare call to an
  overloaded free function is not followed. That is a bounded, named limitation, not a silent one.
* **0 receiver-arm instances for the nine callee names the check uses**: no method body in `Source/WebCore` both
  (a) has no window of its own and (b) calls one of those nine window-bearing methods through `obj->`/`obj.`. Every
  such chain in the tree is written as a bare call, which is why the bare arm is the meaningful one. (The arm is
  narrower than the bare arm by construction — the callee name has to be one of the nine — so this is not a claim
  that receiver-path chains do not exist.) The receiver path is exercised elsewhere: `docs/65`'s
  `m_domApplicationCache->dispatchEvent(…)` inside `dispatchDOMEvent` (§4).
* **Correction recorded: the first version of this check scored 0/6 and its oracle was wrong.** It compared the
  route's last hop against the callee, but every "caller" it sampled contained its own `dispatchEvent(`, so
  `route()` correctly stopped at depth 1. A caller with its own window is a depth-1 hit, not a multi-hop test;
  both arms now exclude it. The programme has already published one false reclaim claim from a bad comparison —
  this is the same class of mistake caught before it reached a doc.

## 7. Corrections to the method, and what this closes

Method corrections that outlive the run (all three cost rows in `docs/81`'s 45 and are fixed in the tool):

1. **`docs/81`'s `class` field is empty for out-of-line constructors whose initializer list ends in `Base(args)`.**
   `signature_before()` sees the *initializer's* `)` as the parameter list, so
   `ShareableElementData::ShareableElementData(std::span<const Attribute>) : ElementData(attributes.size()) {`
   parses as function `ElementData`, no class. Eight of the 45 rows were this. A backward search for
   `Class<…>::method(` in the 2,500 characters before the loop recovers it — and the naive version of that regex
   (`<[^;{}()]{0,80}>`) matches across `template<typename T>\nSQLTransactionStateMachine<T>::`, returning
   `template`; the angle group must exclude `<`/`>` (`<[^<>;{}()]{0,80}>`).
2. **A member declaration's type may carry `const`, `*`/`&`, and an annotation before the terminator.** The first
   pattern (`TYPE NAME ;`) missed `const DFA& m_dfaA`, `const RenderLayer* m_clipRectsRoot[N]` and
   `m_frameBufferCache WTF_GUARDED_BY_LOCK(m_lock)` — three separate causes, 20 more rows.
3. **A bare-name route must consult the owning class before the unique-name gate.** `docs/81`'s `defs == 1`
   condition discarded `dispatchDOMEvent`, a method with exactly one definition *in its own class* but zero in
   the bare index (it is never called without a receiver elsewhere). The gate is what made the walker miss the
   one true route it had already found.

Plus one smaller fix: a member chain must unwrap a smart pointer before stripping its template
(`std::unique_ptr<WebMData>` → `WebMData`, not `unique_ptr`). Nothing here touches the CVE or the 192-byte
`StringImpl` reclaim of `docs/65`.

**What this closes:** the index-loop shape's last two blind spots. After `docs/78` (locals), `docs/79` (members),
`docs/80` (helper templates) and `docs/81` (the loop itself), `docs/82` says the population is not merely
"swept by one heuristic" but "resolved by type where a type exists, walked to depth 3 by receiver, and
over-approximated by name where it does not". Across 10,500 files, 310 owner loops, 1,084 calls and 16
name-flagged rows, there is **no second instance** of the shape that made CVE-2026-43715: a member container, a
script window inside the iteration, and a subsequent read of the container.

**What it does not close:** the 28.4% receiver coverage — though that gap is narrower than it looks, because §5's
pass does not use receiver types at all. A call text `foo(...)` whose real target dispatches is flagged as soon as
*some* definition of `foo` in the tree dispatches, and the real target is itself one of those definitions. What
the pair still cannot see is a window that is not named at the call site: a lambda or function pointer invoked
through a variable (`m_completionHandler(...)`, `callback(...)`) whose dispatch lives in the lambda body, and a
dispatch reached only through a virtual override whose name matches nothing that dispatches. Neither is a new
shape — `docs/74`–`docs/77` measured the completion-handler and callback families directly. The remaining
structural gap here is different, and the next action takes it: **mutation of the container through a callee
argument**. Every mutator check in `docs/81`/`docs/82` looks at
`container.remove(...)` written in the loop body; a helper that takes the container by reference and removes from
it inside the window is invisible to both, and it is the one spelling of "the container shrinks under the loop"
that no sweep in this series has measured.
