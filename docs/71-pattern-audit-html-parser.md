# `html/parser/` with the extended sink list — 18 rows, 5 real script windows, 0 with a reachable free; `LoadableScript` snapshots raw clients where upstream holds `WeakPtr`s

GOAL action (2026-10-29), the item after `docs/70`. `docs/70`'s blind spot was its sink list: the sweep's
`NAMES` could not see `executeScript`/`evaluate`/`JSC::call`/`performMicrotaskCheckpoint`, so the parser's own
script window (`HTMLDocumentParser::runScriptsForPausedTreeBuilder` → `m_scriptRunner->execute`) was outside
the "28 sites". This doc closes that hole: the extended sweep, every new frame read in source, one candidate
read to the end (`HTMLScriptRunner::execute` and its `PendingScript`), and a measured page for the parts of the
verdict that are page-side observable.

Short answer: **18 rows, 5 real script windows, 0 with a reachable free** — and the reason is not a `Ref` in
front of each object, it is that the parser *owns* every object it touches afterwards (`std::unique_ptr`
members of a `RefCounted` parser that every entry point protects). What a script can do from inside those
windows is **detach** the parser, and every post-window dereference of `document()` is then a null deref, not a
read of a freed object. The one place where this drop differs from upstream in exactly the CVE-2026-43715 shape
is `dom/LoadableScript.cpp:52-57`: it iterates a **snapshot of raw `LoadableScriptClient*`**, where upstream
iterates a snapshot of `WeakPtr<LoadableScriptClient>` — but the set provably holds **at most one client**, so
the loop cannot walk into a freed one. That is a hardening gap, not a primitive.

## Method

```sh
cd /Users/<user>/Documents/ps5-bootchain
python3 tools/pattern-sweep.py html/parser html/track html/canvas > /tmp/audit71_sub.json   # 18 rows
```

`tools/pattern-sweep.py` `NAMES` gained `executeScript`, `executeScriptIgnoringException`,
`executePendingScript`, `evaluate`, `evaluateScript`, `JSC::call`, `JSC::evaluate`, `callFunction`,
`performMicrotaskCheckpoint`, `runScriptsForPausedTreeBuilder`, `notifyScriptExecuted`, `execute`,
`microtaskCheckpoint`, `callOnMainThread`.

Counts: 18 rows in 7 files. **3 of them are artifacts** and are named here so no later run re-reads them:
`evaluate` matches the CSS media-query evaluator (`HTMLPreloadScanner.cpp:251`, `HTMLResourcePreloader.cpp:89`,
`m_mediaQueryEvaluator.evaluate(queries)` — not JS), and adding `execute` produces argument-list tails
(`HTMLDocumentParser.cpp:245`'s row is `m_scriptRunner->execute(scriptElement.releaseNonNull(), …)` split at
the name). The remaining **5 real new sinks** are the three `performMicrotaskCheckpoint` calls
(`HTMLDocumentParser.cpp:229`, `HTMLScriptRunner.cpp:111`, `:246`), the `executePendingScript` at
`HTMLScriptRunner.cpp:115`, and the `runScriptsForPausedTreeBuilder()` call at `HTMLDocumentParser.cpp:265`.
The 10 `dispatchEvent`/`reject`/`resolve` rows in `html/track/` and `html/canvas/` are rows `docs/70` already
adjudicated.

Completeness check for `html/parser/` — every JS entry point in the directory, by grep, not by the sweep:

```sh
grep -rnE "executeScript|executeClassicScript|executePendingScript|performMicrotaskCheckpoint|JSC::(call|evaluate)|runScriptsForPaused|ScriptController" Source/WebCore/html/parser/*.cpp
```
17 hits, all of them the functions in this table plus their `executeScriptsWaitingFor{Load,Stylesheets,Parsing}`
wrappers, which reach the same sink. **`html/parser/` has no `JSC::call`/`evaluate` site at all** — its only
JavaScript doors are `HTMLScriptRunner.cpp:115` (`executePendingScript`) and `:263`
(`executeClassicScript`, the nested-inline path).

## The 5 new sinks, and what is used after them

| # | site | sink | used afterwards | owned by | free reachable? |
|---|------|------|-----------------|----------|-----------------|
| 1 | `HTMLDocumentParser.cpp:229` (`runScriptsForPausedTreeBuilder`) | `performMicrotaskCheckpoint()` | `document()->globalObject()`, `constructionData->elementInterface`, `constructElementWithFallback(*document(), …)`, `m_treeBuilder->didCreateCustomOrFallbackElement(…)` | `constructionData` is a **local `std::unique_ptr`** holding a `Ref<JSCustomElementInterface>` (`HTMLTreeBuilder.h`, `CustomElementConstructionData`); `m_treeBuilder` is a `unique_ptr` member of the parser | no — and `document.open`/`write` are **blocked** here by `ThrowOnDynamicMarkupInsertionCountIncrementer` (`HTMLDocumentParser.cpp:227`; `Document.cpp:3045`, `:3238`, `:3467`, `:3479` all test `m_throwOnDynamicMarkupInsertionCount`) |
| 2 | `HTMLScriptRunner.cpp:246` (`runScript`) | `performMicrotaskCheckpoint()` | `InsertionPointRecord`, `m_scriptNestingLevel`, `scriptElement.prepareScript()`, `m_parserBlockingScript = PendingScript::create(…)`, `executeClassicScript(…)` | `scriptElement` is `ScriptElement&` reached from a `Ref<ScriptElement>` parameter (`HTMLScriptRunner.cpp:134`, from `HTMLDocumentParser.cpp:245`'s `releaseNonNull()`); the runner and `m_input` are members of the parser | no — `document.open` bails on `hasInsertionPoint()`, not on `isExecutingScript()` (see below) |
| 3 | `HTMLScriptRunner.cpp:111` (`executePendingScriptAndDispatchEvent`) | `performMicrotaskCheckpoint()` | `NestingLevelIncrementer`, `pendingScript.element().executePendingScript(pendingScript)` | `pendingScript` is held by the caller's temporary `Ref` (`:165` `m_parserBlockingScript.releaseNonNull()`, `:199` `m_scriptsToExecuteAfterParsing.takeFirst()`), and by `Ref<PendingScript> protectedThis` inside its own `notifyClientFinished` (`dom/PendingScript.cpp:67`) | no |
| 4 | `HTMLScriptRunner.cpp:115` | `executePendingScript` | nothing — **last statement of the frame** (`ASSERT(!isExecutingScript())` after) | as row 3 | no |
| 5 | `HTMLDocumentParser.cpp:265` (`pumpTokenizerLoop`) | `runScriptsForPausedTreeBuilder()` | `isWaitingForScripts()`, `isStopped()`, `document()->frame()`, `m_parserScheduler->shouldYieldBeforeToken()` | parser members; `document()` is a `WeakPtr` (`DocumentParser.h:117`) | no — this is the frame that **detaches**, see "What a script can actually do" |

Two reads that decide the whole table:

- **The parser is `RefCounted` and every entry point protects it.** `DocumentParser : public
  RefCounted<DocumentParser>`; `Ref<HTMLDocumentParser> protectedThis(*this)` appears at
  `HTMLDocumentParser.cpp:130` (`prepareToStopParsing`), `:209` (`resumeParsingAfterYield`), `:375` (`insert`),
  `:410` (`append`), `:542` (`resumeParsingAfterScriptExecution`), `:574` (`notifyFinished`), `:610`
  (`executeScriptsWaitingForStylesheets`). Every route that can reach a `performMicrotaskCheckpoint` starts at
  one of those, so the parser cannot be deleted inside the window. `~HTMLScriptRunner` (which frees the
  `PendingScript`s in `m_parserBlockingScript` and `m_scriptsToExecuteAfterParsing`) is a `unique_ptr` member of
  that parser, so it cannot be freed inside the window either.
- **Everything the window can leave behind is a null, not a free.** A script inside the window can call
  `document.open()` → `Document::open` → `Document::detachParser()` (`Document.cpp:3129-3135`) →
  `m_parser->detach()`, which sets `m_state = Detached` and `m_document = nullptr` (`DocumentParser.cpp:66-70`),
  and `HTMLDocumentParser::detach` then nulls `m_preloadScanner`, `m_insertionPreloadScanner`,
  `m_parserScheduler` and detaches the script runner (`:103-114`). The parser object survives (the Ref above),
  its members survive, and the *next* use of `document()` — `HTMLDocumentParser.cpp:275` `document()->frame()`,
  `:231` `document()->globalObject()`, `:329`/`:567` `*document()`, `HTMLParserScheduler.cpp:97`
  `m_parser.document()->isLayoutPending()`, `:118-122` `RefPtr<Document> document = …; document->body()`
  — dereferences a null `WeakPtr` with only an `ASSERT` in front of it (`DocumentParser.h:65`). That is a crash
  class `docs/67` already has one of; it is not a freed-object read.

### The guard that actually holds the three checkpoints

`Document::open` has two tests, and the checkpoints sit exactly in the gap between them:

```cpp
if (parser->isParsing()) {
    if (parser->isExecutingScript())          // Document.cpp:3070-3071
        return { };
    if (!parser->wasCreatedByScript() && parser->hasInsertionPoint())   // :3073-3074
        return { };
}
```

`HTMLScriptRunner.cpp:110` and `:245` only checkpoint when `!isExecutingScript()`, so the *first* test can never
be what stops an `open()` from inside them. What stops it is `hasInsertionPoint()`: the loader-created parser is
not `wasCreatedByScript()` and, mid-parse, always has an insertion point. Probes `P3` (from inside a running
script) and the read disagree in the way the source predicts — see below.

## The one place this drop differs from upstream in the CVE shape

```cpp
// out/sony/full/.../Source/WebCore/dom/LoadableScript.cpp:52-57   (Sony's drop)
void LoadableScript::notifyClientFinished()
{
    Ref protectedThis { *this };
    for (auto& client : copyToVector(m_clients.values()))
        client->notifyFinished(*this);
}
```
```cpp
// WebKit main, from apple/WebKit — same function
    auto clients = WTF::map(m_clients, [](auto& entry) -> WeakPtr<LoadableScriptClient> {
        return entry.key;
    });
    for (auto& weakClient : clients) {
        if (RefPtr client = weakClient.get())
            client->notifyFinished(*this);
    }
```

The drop snapshots **raw pointers** and dereferences them after a callback that runs script; upstream snapshots
**`WeakPtr`s** and null-checks each one — the same repair `docs/65` documents for `CSSFontFaceSet::iterateClients`
(`if (clients.contains(client))`), and the header had to grow for it (`LoadableScriptClient` is a bare abstract
class here; upstream's is `AbstractRefCountedAndCanMakeWeakPtr<LoadableScriptClient>`). The change in upstream is
`a55f0e9fc70c` "Adopt more smart pointers in DOM code" (2023-10-27) — **hardening, not a CVE fix** — which is
consistent with what the client set can actually hold:

- **`LoadableScriptClient` has exactly one implementation** in this tree: `PendingScript`
  (`dom/PendingScript.h:42`). Grep for `public LoadableScript` returns only the three `LoadableScript` subclasses.
- **One `LoadableScript` per element, one `PendingScript` per element.** `ScriptElement` owns
  `RefPtr<LoadableScript> m_loadableScript` (`dom/ScriptElement.h:143`) and *creates* it per element
  (`requestClassicScript` `ScriptElement.cpp:332`, `requestModuleScript` `:373`/`:394`, `requestImportMap` `:417`)
  — two `<script src="same.js">` tags share a `CachedScript`, **not** a `LoadableScript`. And `prepareScript` runs
  once per element: `if (m_alreadyStarted) return false;` (`:186`), set at `:218`, and `m_alreadyStarted` is
  never cleared anywhere in the file (grep: lines 73, 186, 218, 434, 466, 610 — one write, no reset). The
  parser's own request path asserts the same invariant: `ASSERT(!m_parserBlockingScript)`
  (`HTMLScriptRunner.cpp:216`).
- **Only one client ever runs script from the callback.** `ScriptRunner`'s `notifyFinished` (`dom/ScriptRunner.cpp:96-106`)
  only *queues* to `m_scriptsToExecuteSoon` and starts a 0 s timer; the deferred `PendingScript`s in
  `m_scriptsToExecuteAfterParsing` have no client set until `executeScriptsWaitingForParsing` watches them
  (`HTMLScriptRunner.cpp:196`), so their `notifyFinished` is a no-op (`PendingScript.cpp:68` `if (m_client)`).
  The single client whose callback executes script is the parser's `m_parserBlockingScript`, and there is at most
  one of those.

With `|clients| ≤ 1` the loop cannot dereference a freed *second* entry, and a single freed entry is only touched
before the call, not after. So the missing `WeakPtr` is unreachable **by construction of this drop**, and the
`CachedResource` side shows what a hardened set looks like in the same tree: `WeakHashCountedSet<CachedResourceClient>
m_clients` with an explicit `m_clients.contains(client)` test (`loader/cache/CachedResource.h:350`,
`CachedResource.cpp:573-576`).

**Correction to `docs/66`:** its 17-family table has no row for this family, so `docs/66`'s "only three families
can run script from a client callback" (`CSSFontFace::Client`, `CSSFontFaceSet::FontEventClient`,
`GamepadProviderClient`) is short by one: `LoadableScriptClient`/`PendingScript` runs the page's script
synchronously from `HTMLDocumentParser::notifyFinished`. It was missed because the family is iterated with
`copyToVector(m_clients.values())` over a `HashCountedSet`, not with `forEach`/`iterateClients`, which is what the
`docs/66` greps keyed on. The verdict does not change (the set holds one client), but the family list was wrong.

## Measured — `research/html-pattern/parser-window/`, quarantine off, 3/3 identical

```sh
cd research/html-pattern && ./run-parser-window.sh 9742 "p=ALL" W2
```
Page md5 `97de53e87a78b8ca3a916561c0f612cb` (`index.html`), `p2.js` `92bafedb270a70f84bb76ac999d5c4b0`,
`p8.js` `d02356fb4b6fa998653007a2689c1bea`, `s1.js` `2163baeecd5a2b80f913a1e376c95c5d`. `W3` (same page, fresh
port) and `W5` reproduce the log below line for line; `W4` is the `p=P2` isolation run.

```
===== W2  q=p=ALL
access: none
SUMMARY: none
   1 START sel=ALL
   2 P1 inline
   3 P2 enter
   4 P2 nested exec
   5 P2 wrote
   6 P2 exit
   7 P3 enter
   8 P3 open ok
   9 P3 exit
  10 S1 n=1 id=s1elm conn=1
  11 P5 found=1
  12 P5 reinserted
  13 P5 fresh appended
  14 P6 enter
  15 P6 removed
  16 P6 wrote
  17 P6 exit
  18 P7 enter
  19 P7 found=1
  20 P7 removed
  21 P7 exit
  22 P8 depth=1
  ... (depth=2 … depth=21, one beacon each, no `ret` in between)
  43 P8 depth=22
  44 P8 ret=22   (×22 as the 22 frames unwind)
  66 TAIL
  67 S1 n=2 id=d1 conn=0
  68 S1 n=3 id=fresh conn=1
```

What each line is, and what it rules out:

- **`P2` — the parser's own load-callback frame re-enters.** `p2.js` is a literal `<script src>`, so it runs from
  `HTMLDocumentParser::notifyFinished` → `executeScriptsWaitingForLoad` → `executeParsingBlockingScripts` →
  `executePendingScriptAndDispatchEvent` (`:111` checkpoint → `:115`). Its `document.write('<script>…')` executes
  the nested inline script **between `P2 enter` and `P2 wrote`** (beacons 3,4,5), i.e. the write's `insert()` →
  `pumpTokenizer` → `runScriptsForPausedTreeBuilder` → `execute` chain ran to completion inside the outer
  script's own frame. That nested script is the `HTMLScriptRunner.cpp:261-266` path (nesting level 2 →
  `executeClassicScript` directly), which is why no `PendingScript` is involved in the nested half. `W4`
  (`p=P2` alone) gives the same 3,4,5 sequence, so it is not an artifact of the other probes.
- **`P3` — `document.open()` from inside an executing script does not throw and does not open.** `open ok`
  (beacon 8) and the parse continues (`P3 exit`, then `S1 n=1`): the bail is the `return { }` at
  `Document.cpp:3070-3071`, not an exception.
- **`P5` — the once-per-element invariant, from the page side.** `S1 n=1 id=s1elm conn=1` (beacon 10) is the
  literal parser-inserted tag. The probe then removes that element and re-appends it (`P5 reinserted`, 12) and
  **no second `id=s1elm` beacon ever appears** — `m_alreadyStarted` (`ScriptElement.cpp:186`) makes
  `prepareScript` a no-op, so no second `PendingScript` (and no second client) can be created for that element.
  The control is in the same run: a *fresh* element with the same `src` **does** run (`S1 n=3 id=fresh conn=1`,
  beacon 68), so the suppression is the element, not the URL, the cache, or CSP.
- **`P6` — the element being processed is ref-held.** `P6 removed` then `P6 wrote` (15, 16): the script removes
  its own element (`document.currentScript.remove()`) and `document.write` still works, because the element is
  the `Ref<ScriptElement>` parameter of `HTMLScriptRunner::execute` (`:134`, from
  `runScriptsForPausedTreeBuilder`'s `releaseNonNull()` at `HTMLDocumentParser.cpp:245`).
- **`P7` — the queue owns the `PendingScript`, not the DOM.** The deferred element is removed
  (`P7 removed`, 20) and the script still executes at end of parsing with `conn=0` (beacon 67). Its
  `PendingScript` lives in `HTMLScriptRunner::m_scriptsToExecuteAfterParsing`, which is why removing the element
  cannot free a client. `W4` (where `P7` is off and the element stays connected) reads `conn=1` — the control.
- **`P8` — the width of the re-entry, and the guard at its edge.** `W()` writes an **inline** script that calls
  `W()` again, so every link runs synchronously inside `Document::write` → `insert` → `pumpTokenizer` and one
  level of `m_writeRecursionDepth` accumulates per link. The chain reaches **depth 22** and then **stops**: there
  is no `depth=23`, and 22 `ret=22` beacons unwind. That is `cMaxWriteRecursionDepth = 21` (`Document.cpp:385`)
  tested as `m_writeRecursionDepth > cMaxWriteRecursionDepth` (`:3445`, drop at `:3448`) — the 23rd nested write
  is silently dropped, not an error. The first version of this probe wrote an **external** script and measured
  the opposite (`W1b`, taken before the beacons carried sequence numbers, so only the values are quotable): every
  depth `1…26` and every ret `1…26` is present and nothing stops at 22, which is only possible if the recursion
  depth never accumulated — the parser pauses for the load and the inserted script runs in a later task, outside
  the write's frame. Both runs are in `data/html-pattern/parser-window/W2.txt` (inline) and `W1b.txt` (external).

No sanitizer line in any of `W2`, `W3`, `W4`, `W5` (`grep -l AddressSanitizer /tmp/run_W*.log` → none), which is
the expected result for every row in the table above: the windows are real and deep, and nothing in them is
freeable.

## What this does and does not say

- It does **not** say `html/parser/` is free of memory bugs. It says the pattern *as defined* — a synchronous
  script window followed by a use of something the script can free — has no instance among the 5 real sinks, and
  it names the two structural reasons (the parser owns its state and is ref-held at every entry; the
  `LoadableScript` client set cannot exceed one).
- The `LoadableScript` gap is **live in the drop and fixed upstream**, so it belongs in the record even though it
  is unreachable here: if any future change lets one `LoadableScript` have two live clients (a shared script
  object, a second `prepareScript`, a re-parented element that resets `m_alreadyStarted`), the drop's raw
  snapshot becomes the same one-line UAF as `docs/65`. That is worth a note, not a primitive.
- The post-detach null derefs are **not** measured here; they are a read. The page cannot force a detach from
  inside a checkpoint without a microtask that the engine queues before the next script, which this page does not
  construct. If a future run wants that crash, the route is a promise resolved by a C++ task (font/`decode()`/
  stream) landing on `HTMLScriptRunner.cpp:246`, and the expected verdict is `SEGV` on a null `document()`, not an
  ASAN use-after-free.

## Next

1. **`style/`**, per the GOAL: rule-mutation frames holding a raw `StyleRule*` across `RuleMutationScope`, where
   `didMutateRules()` reaches `CSSFontSelector::buildCompleted()` — the same free site as `docs/65`, reached from
   CSSOM instead of from a getter. `StyleSheetContents` stores `Ref<StyleRuleBase>`, so look for a frame that
   keeps the raw pointer outside that vector.
2. If `style/` comes up empty, the console half of the flip (`docs/65`, Attempt 9) is still the only item blocked
   on physical access.

## Reproducing

```sh
cd /Users/<user>/Documents/ps5-bootchain
python3 tools/pattern-sweep.py html/parser html/track html/canvas        # 18 rows
cd research/html-pattern && ./run-parser-window.sh 9742 "p=ALL" W2       # and p=P2 for the isolation run
```

Logs: `data/html-pattern/parser-window/W1.txt` … `W5.txt` (raw MiniBrowser output in `/tmp/run_W*.log`).
