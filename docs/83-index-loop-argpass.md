# The argument-passing spelling: does a callee get the owner loop's container by reference and shrink it?

`docs/79`–`docs/82` close the index-loop shape from four directions: locals (`78`), members (`79`),
helper templates (`80`), the loop body (`81`) and receiver-typed routes to depth 3 (`82`). All of them
look for the container being mutated **where the container's name is written** — `m_foo.remove(i)` in
the loop body, or `m_foo.remove(...)` inside a callee body (docs/82's `mutator_in_route`, empty for all
310 owner rows). None of them can see a callee that takes the container **as an argument**:

```cpp
for (size_t i = 0; i < m_foo.size(); ++i) {
    evictFrom(m_foo, i);          // <- the body never says "m_foo.remove"
    ...                           //    and the window is inside evictFrom
}
```

If `evictFrom(Vector<T>& v, size_t i)` removes from `v` after running script, the container shrinks
under a cached-bound loop and every earlier pass misses it. This document measures that spelling over
the same 310 owner-container loops, with the container **type-resolved** (docs/82's `resolve.json`) and
every resolved callee read for a mutator on the parameter it receives.

Tool: `tools/index-loop-argpass.py` (`python3 tools/index-loop-argpass.py > data/index-loop/argpass.json`).
Data: `data/index-loop/argpass.json`, `data/index-loop/argpass.err`.

## 1. What is matched

A *container handle* argument is an argument that denotes the container object itself, in these
spellings (after peeling parentheses): bare (`m_foo`), `this->m_foo`, `&m_foo`, `*p` where `p` is a local
pointer to it, `WTFMove(...)`, `std::move(...)`, `WTF::move(...)`, `std::exchange(...)` (first argument),
and any local of the enclosing function bound to it (`auto& v = m_foo;` → `ref`, `auto* p = &m_foo;` →
`ptr`, `auto v = WTFMove(m_foo);` → `moved`). `this`/`*this` (the owner object) is counted separately,
because it reaches the container only through `this->m_foo` inside the callee.

Element and query expressions are **not** handles and are counted on their own: `m_foo[i]`,
`m_foo.at(i)`, `m_foo[i].ptr()`, `m_foo.size()`, `.isEmpty()`, `.begin()`, `.end()`, `.data()`,
`.first()`, `.last()`.

A callee's parameter is treated as able to shrink the caller's container only when it is a **non-const
reference or pointer** to a container type; a by-value parameter is a copy and a `const&` cannot be
mutated. The mutator set is `clear/remove/removeAt/removeAll/removeAllMatching/removeFirst/
removeFirstMatching/removeLast/removeIf/take/takeFirst/takeLast/shrink/shrinkToFit/resize/truncate/
pop_back/pop_front/erase/swap/reverse/sort/fill`, plus whole-container assignment and `WTFMove(param)`.

## 2. Result — body level: 0 of 1,368 calls, 0 of 992 arguments

```
$ /usr/bin/time -p python3 tools/index-loop-argpass.py > data/index-loop/argpass.json
owner rows 310 | calls 1368 | args 992
argpass 0 depth2 0 alias-rows 0 member-in-callee 0 growth-ctrl 0 member-arg-ctrl 0 {'container-not-a-member': 16}
callee scan: 1321 calls, 333 resolved, unresolved {'max': 37, 'builder.append': 18, '.get': 16, 'min': 15, ...}
mentions {'element-index': 108, 'size': 1}
control all loops: 5399 calls 16 hits
control iterateClients: [{'file': 'Source/WebCore/css/CSSFontFace.cpp', 'arg0': 'WeakHashSet<CSSFontFace::Client>& clients', 'matched': False, 'how': ''},
                         {'file': 'Source/WebCore/css/CSSFontFace.cpp', 'arg0': 'm_clients', 'matched': True, 'how': 'handle'},
                         {'file': 'Source/WebCore/css/CSSFontFace.cpp', 'arg0': 'm_clients', 'matched': True, 'how': 'handle'}]
real 113.04
user 109.00
sys 1.20
```

(The JSON is deterministic: two runs give the same md5, `c8d46cd36313cbb657a0e1ebf33633ed`.)

**No call in any of the 310 owner-container loop bodies passes the loop's container as an argument.**
The bodies contain 1,368 call sites with 992 arguments in total. The container does appear in arguments
109 times, and every one is a read of one element or of the size:

* 108 `element-index` — `m_clientState[i - 1].get()`, `m_events[i]`, `m_faces[i].ptr()`, `m_inputs[i]`,
  `m_cellSlots[rowIndex].size()` inside a callee, `m_grid[row].row[col]`, `memcpy(m_channels[channelIndex]->data(), …)`;
* 1 `size` — `m_events.size() - i` handed to `m_events.remove(...)`.

**Zero locals in the 310 enclosing functions are bound to the container** (`alias-rows 0`): even the
alias spelling has no instance here. The first version of the detector reported two, in
`platform/text/SegmentedString.h:304` and `:311`, and both were artefacts of its own regex — see §7.

## 3. Result — callee level: 371 bodies read, 28 mention the member, 0 mutate it

Resolving every call in the 310 bodies by receiver type (docs/82's index, plus the base chain) gives
**1,321 calls, 333 resolved (25.2%), 371 callee bodies** (median body 67 bytes, minimum 13 — so the
slicing is real and is not silently returning empty text). Inside those bodies:

* **28 bodies mention the loop's container at all.** All 28 are reads or element writes:
  `m_events[eventIndex] = ParamEvent::createSetValueEvent(...)`,
  `if (i < m_inputs.size()) return m_inputs[i].get();`,
  `if (m_cellSlots[rowIndex].size() < columnIndex + 1)`,
  `for (size_t i = idx; i > 0; --i) m_buffers[i].swap(m_buffers[i-1]);`,
  `recalcCellsIfNeeded(); return m_grid[row].row[col];`.
* **0 bodies mutate the container** in any receiver spelling — `m_<name>.<mut>`,
  `self.m_<name>.<mut>`, `owner->m_<name>.<mut>` (`member-in-callee 0`). This is the widened form of
  docs/82's `mutator_in_route`: docs/82 matched `(this->)?m_<name>`, which cannot see an aliased
  receiver, and the widening still finds nothing.
* **0 bodies pass the member onward as an argument** to a further callee (`member-arg-ctrl 0`), so the
  depth-2 form of the same spelling does not exist either.
* **Growth control 0**: the same walk with `append/add/insert/set/prepend` instead of the shrink verbs
  also finds nothing (`growth-ctrl 0`). Since 28 of the 371 bodies do contain the member, this zero is a
  fact about the code — no callee of these loops touches the container at container level — and not a
  silent failure of the walk.

## 4. The eight rows that do run script, read one by one

`docs/81` flags 8 of the 310 as carrying any window at all. The argument question for each is: does the
window call receive the container? Read in source, none does.

| row | container | window call | what the window receives |
|---|---|---|---|
| `Modules/airplay/WebMediaSessionManager.cpp:235` | `m_clientState` | `m_clientState.remove(i - 1)` (the mutator itself) | no argument |
| `Modules/airplay/WebMediaSessionManager.cpp:394` | `m_clientState` | `state->client.setPlaybackTarget(state->contextId, *m_playbackTarget.copyRef())` and two siblings | the playback target and an id |
| `accessibility/atspi/AccessibilityAtspi.cpp:306` | `m_pendingRootRegistrations` | `pendingRootRegistration.completionHandler({ })` | an empty variant |
| `css/CSSFontFaceSet.cpp:268` | `m_faces` | `m_faces[i]->removeClient(*this)` then `m_faces.remove(i)` | `*this` — read below |
| `dom/CustomElementReactionQueue.cpp:339` | `m_elements` | `queue->invokeAll(element)` | the element |
| `loader/appcache/ApplicationCacheHost.cpp:333` | `m_deferredEvents` | `dispatchDOMEvent(event.eventType, event.progressTotal, event.progressDone)` | three values |
| `rendering/RenderGeometryMap.cpp:61` | `m_mapping` | `transformState.applyTransform(*currentStep.m_transform.get())` | the transform |
| `rendering/RenderTableSection.cpp:562` | `m_grid` | `rowRenderer->updateLayerTransform()` | no argument |

Two of them deserve a line of their own, because they are the closest the tree comes to the shape:

* **`CSSFontFaceSet::remove`** hands the *owner* to a callee — `m_faces[i]->removeClient(*this)` — which
  is the only way left for a callee to reach `m_faces` without naming it. `CSSFontFace::removeClient`
  (`css/CSSFontFace.cpp:488-492`) is `ASSERT(m_clients.contains(client)); m_clients.remove(client);`: it
  touches its own client set, never the set it is passed. The loop then removes `m_faces[i]` and returns,
  and `decrementActiveCount()` (the window) runs after the read.
* **`CustomElementQueue::invokeAll`** grows its container from inside the window — `add()` appends when a
  missing `CEReaction` lets page script enqueue — and the code says so: the bound is `m_elements.size()`
  re-read every iteration and `clear()` is outside the loop. Growth is not a shrink; the read is in
  bounds by construction, and `takeElements()` (the only emptying path) moves the vector out, which ends
  the loop at the next bound check.

## 5. The only other way in: `this` / `*this` as an argument

A callee can also reach `m_foo` through the *owner object*. Across all 310 bodies there are exactly
**2 call sites that pass `this` or `*this`**, both read:

1. `CSSFontFaceSet.cpp:268` — `removeClient(*this)`, above.
2. `rendering/ReverbConvolver.cpp:168` — `processInBackground(this)` on the audio thread, in a row with
   no window at all (`window_before: []`).

So the owner-object route is not a hidden third path: it is two call sites, and neither can shrink the
loop's container during a script window.

## 6. Controls

1. **The same matcher over all 1,261 loops finds 16 sites** (`control all loops: 5399 calls 16 hits`),
   all on local containers, none on an owner row — `WebSocketHandshake.cpp:421` (`makeString(_, statusCodeString)`),
   `CSSPropertyParser.cpp:666` (`std::size(values)`), `Editing.cpp:372`
   (`rebalancedString.appendSubstring(string, …)`), `SimplifyMarkupCommand.cpp:94`
   (`pruneSubsequentAncestorsToRemove(nodesToRemove, i)`), `InlineContentBreaker.cpp:334/599`,
   `QuotedPrintable.cpp:68` ×2, `LocaleWin.cpp:187` ×4, `RenderObject.cpp:2448`,
   `RenderText.cpp:1186`, `SVGTextChunkBuilder.cpp:73`. Every one was read: they are reads
   (`pruneSubsequentAncestorsToRemove` only indexes; `adjustLineHeightOfSelectionGeometries` writes
   elements, never removes), a `String` being passed where this pass calls it a "container", or
   `std::size` — a false positive class, recorded below. **Zero of the 16 mutate the parameter.**
2. **An independent implementation agrees.** A pure text regex over the same bodies —
   `[(,]\s*(?:WTFMove\(|std::move\(|WTF::move\(|std::exchange\()?&?\s*(?:this->)?<container>\s*[,)]`,
   with no call walker and no type resolution — gives the same numbers: **0 hits in the 310 owner
   bodies, 16 in all 1,261 loops**, the identical 16 files. Two different matchers, one answer.
3. **The known helper idiom is found.** `iterateClients(m_clients, …)` (`docs/80`'s 11 sites, the
   `docs/65` bug's own loop) is matched as `handle` at arg 0 in both call sites in `CSSFontFace.cpp`;
   the only unmatch is the *definition*'s parameter, which is correctly not a container handle.
4. **The mutation detector itself is positive in this tree, 75 times.** A tree-wide scan for functions
   that take a **non-const** `Vector/HashMap/HashSet/Deque/List/WeakHashSet<…>&` and mutate the parameter
   finds **75 definitions (59 distinct names)** — e.g. `SVGAltGlyphDefElement::hasValidGlyphElements`
   (`glyphNames.clear()`), `SVGSVGElement`'s `SVGFilterGraph::visit` (`stack.removeLast()`),
   `SizesCalcParser::handleOperator` (`stack.removeLast()`), `SharedBufferChunkReader::nextChunk`
   (`chunk.clear()`), `ServicesOverlayController::replaceHighlights` (`remove()` on a `HashSet<RefPtr<…>>&`).
   So the parameter-mutation test fires on real code; the 310 loops just never hand it the container.
   Cross-check: 5 calls in the 310 bodies hit one of those 59 *names*, and all five are `create(...)` —
   a name collision with a static factory. That is exactly why this pass matches the argument expression
   and not the callee name.

## 7. Corrections and limits of this pass

* **`std::size(container)` is not a handle pass.** The matcher's `std::size` exemption is written as
  `std::size(...)` but the call walker sees the inner `(...)`, so the control set carries one false
  positive (`CSSPropertyParser.cpp:666`). It is in the control set, not in the owner set, so no count
  changes; recorded so the next reader does not take it for a site.
* **A receiver that is an element or a deref loses its name** (`m_foo[0].get()`, `(*p).get()`,
  `x->data()`): the backward walk stops at `]`/`)`, so dozens of the 988 unresolved calls appear as
  `.get` (16), `->data` (11), `->mutableData` (8), `.ptr` (7) at the head of the list. This cannot hide a
  container-argument site — the container test runs on the *argument list*, independently of whether the
  callee resolves — but it does thin the callee-side coverage, which is why §3 reports its own denominator.
* **The alias detector's first version split identifiers.** `TYPE \s* NAME = …` allows zero whitespace
  between type and name, so `m_currentCharacter = *m_currentSubstring.currentCharacter8;` parses as type
  `m_currentCharacte`, name `r` — which produced two aliases in `SegmentedString.h:304/311` that do not
  exist. Requiring `\s+` before the name gives `alias-rows 0` and changes nothing else (argpass stays 0,
  so no site was ever matched through the phantom name `r`). Recorded because the same zero-width split
  would silently invent one-letter aliases anywhere in this tree.
* **16 rows have a container that is not an `m_` member** (a local or a chain resolved to a local); the
  callee-side scan skips them (`container-not-a-member: 16`) because a same-named member in an unrelated
  class would be a different object. Their body-level result (0) still stands.
* **Resolution recall is docs/82's**: 59/60 on a multi-hop ground truth, with the one miss being a call
  to an overloaded static free function. The growth control (§3) is the local check that the walk reaches
  the member where the member is really there.
* **No page, no ASAN run.** The action's conditional — "if any row has both a mutating callee and a
  window" — has no candidate: 0 argument-passing sites, 0 callee mutations, 0 depth-2 passes. Running the
  oracle here would measure nothing, so nothing was run.

## 8. What this closes

The last spelling of "the container shrinks under the loop" in this shape. Across 10,500 files:

* the body says `m_foo.remove(...)`: **16 rows, all read** (`docs/81`);
* a callee `m_foo.remove(...)`s: **0 rows** (`docs/82`, widened here to any receiver);
* a callee receives `m_foo` and removes from the parameter: **0 of 1,368 calls / 992 arguments**, with
  371 callee bodies read, 28 of them mentioning the member, and two independent matchers agreeing;
* the owner object is handed to a callee instead: **2 call sites, both read**.

No second instance of the `docs/65` shape exists in this population. What remains un-swept is not another
spelling of the *mutation* but the shape's **other half**: a container that is not the loop's index
container at all — a different member of the same object that the window shrinks and that a later
statement reads for a purpose the loop does not index. That is a lifetime question, not an indexing one,
and it is not reachable by another join over loop bodies: the eight window rows of §4 are the whole
population in which it can arise, and §3 already shows that none of their callees touches a container
member by name. The next instrument is therefore not a twenty-first sweep but the oracle itself, driven by
a seeded in-page fuzzer over exactly these surfaces (`GOAL.md`, next action 1) — the audits have chosen
the alphabet, and only a run can tell whether the protected paths are protected under churn.
