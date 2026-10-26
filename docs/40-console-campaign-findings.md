# Console campaign: first confirmed engine fault (2026-10-26)

State of the hunt for a WebProcess vulnerability reachable from the User's Guide on retail 14.10, using
the Pi keyboard bridge + camera as an unattended validation loop.

## Confirmed: the Guide's WebProcess dies on a detached @media rule

Reproducer (`guide_lab/www/cases/c007-page-detached-grouping.js`), three lines of CSSOM:

```js
var style = document.createElement('style');
style.textContent = '@media all {}';
document.head.appendChild(style);
var sheet = style.sheet, media = sheet.cssRules[0];
sheet.deleteRule(0);                       // detach the grouping rule
try { media.insertRule('@page foo {}', 0); } catch (e) { }
try { media.insertRule('@page foo:first {}', 0); } catch (e) { }
```

Measured on the console, twice, with a control:

| run | beacons | screen |
|---|---|---|
| control (`c000`, trivial) | `start:0` `survived:0` `FUZZ-RUNNER-DONE:1` | page fine, no dialog |
| `c007` | `start:0`, then **nothing** | system message "There is not enough free system memory." |

So the harness is sound and the case reliably stops the engine. Upstream fix `cc88e18743` describes this
exactly: a null dereference in `CSSParser::parsePageSelector` when inserting an `@page` rule into a
detached grouping rule. Sony's tree still has the pre-fix shape:

```cpp
selector = makeUnique<CSSParserSelector>(QualifiedName(nullAtom(), typeSelector, styleSheet->defaultNamespace()));
...
selector->prependTagSelector(QualifiedName(nullAtom(), typeSelector, styleSheet->defaultNamespace()));
```

`styleSheet` is `m_styleSheet.get()`, which is null once the rule is detached — dereferenced with no check
at `CSSParserImpl.cpp:229` and `:238`.

**Class: denial of service, not memory corruption.** It terminates the process; it is not by itself a
path to code execution and says nothing about the debug menu. Recorded because it is real, reproducible
and fixable, and because it proves the loop finds genuine unpatched faults.

## Killed, with evidence

- **`cfe38930db` — bug 278657, poison-injection through a ResizableSharedArrayBuffer.** Needs a
  `SharedArrayBuffer` another thread can grow mid-serialisation. Measured on the console:
  `sab=undefined, rab=resizable, grow=ReferenceError` → structurally dead on 14.10.
- **`442482adf1` — `CachedString::m_jsString` unrooted.** `m_jsString` is only touched by
  `StringTag`/`StringObjectTag`, but pool indices are emitted *only* by `write(const Identifier&)`, and
  property names are materialised with `Identifier::fromString(vm, cachedString->string())` — never the
  cached `JSValue`. String values are written raw by `dumpString`, so a cached value is used once with no
  GC window. Not reachable from JS on this build.

## The candidate list is the bottleneck, not the console

Of 56 ranked candidates, **22 ship an upstream reproducer**; the rest are refactors ("Fold
TreeDepthLimit.h", "Get GraphicsLayer.h out of hot include paths", "ImageBitmapBacking is a redundant
class"). A "VULN-SHAPE" flag mostly means the code *shape* matched, not that a bug exists.

`tools/fw1400/patch_presence.py` replaces that with a sharper test: for each patch, does a **contiguous
run of the lines the fix deletes** still exist in Sony's tree? Run over the same 56 patches it reports 22
with a surviving pre-fix block, and it independently re-finds `cfe38930db` with its exact 4-line block —
so it agrees with the manual analysis on a known case. Anything below a 3-line run is one generic line
matching across versions and means nothing.

## Harness lessons paid for here

- A fixed tail window over `beacons.jsonl` reads an old `FUZZ-RUNNER-DONE` and the supervisor exits
  before starting. `BeaconTail` tracks a byte offset and keeps a partial trailing line.
- The attempt counter must be incremented **before** a case runs, or a hanging case reloads forever at
  attempt 0 and pins the campaign.
- Cases that allocate hundreds of MB take the whole console down: 150 x 4 MB `Float64Array` produced the
  system memory dialog, which then intercepts input and poisons every later observation.
- That memory dialog **does not accept keyboard input** (three Enters did nothing), unlike the `WV-`
  network dialogs where Enter works. The supervisor classifies it `UNKNOWN` and keeps pressing; it should
  be its own alarm state.

## Strongest live candidate: array-index / tag confusion in structured clone

Upstream fix `3a900e192f` (Mark Lam, 2023-12-14), bug 262616:

> `NonIndexPropertiesTag` is `0xFFFFFFFD`, which is less than `MAX_ARRAY_INDEX` (`0xFFFFFFFE`), i.e. an
> index of `0xFFFFFFFD` can be confused for the `NonIndexPropertiesTag`, resulting type confusion.

The serializer terminates an array's indexed-property section with that very value, so the deserializer
cannot distinguish "this array has an element at 4294967293" from "the indexed section ends here". It
stops early and parses the remaining bytes as non-index properties. That is a **type confusion inside
`structuredClone`**, reachable from ordinary JavaScript with no crafted byte stream:

```js
var a = [];
a[4294967293] = 'x';        // 0xFFFFFFFD is a legal array index
structuredClone(a);         // deserializer reads the index as the terminator
```

Sony's tree is still pre-fix: `TerminatorTag = 0xFFFFFFFF` and `NonIndexPropertiesTag = 0xFFFFFFFD` at
`SerializedScriptValue.cpp:679/681`, the bare `write(NonIndexPropertiesTag)` at `:2539`, and the
`index == NonIndexPropertiesTag` test at `:4869`. The upstream fix changes the wire format to always
emit a `TerminatorTag` first, which is why the whole file had to change rather than one comparison.

Reproducer staged as `guide_lab/www/cases/c012-array-index-tag-confusion.js`. It beacons
`roundtrip-ok` / `wrong-value` / `threw`, so a clean result is distinguishable from a dead process.

Status: not yet run on the console - it is parked on the low-memory dialog, which the supervisor now
treats as an alarm instead of pressing keys into it.

## How the candidate list was rebuilt

The sweep's ranking was dominated by refactors. Replacing it with targeted commit search
(`use-after-free`, `out-of-bounds`, `type confusion`, since the 17.0 cut) gave 141 memory-safety commits;
two automated gates then cut it to 10:

1. **Presence** - does a contiguous run (>= 3 lines) of the lines the fix deletes still exist in Sony's
   tree? Isolated single-line matches are noise (a `case VideoPixelFormat::RGBX:` label exists in every
   version).
2. **Reachability** - drop patches that only touch subsystems this build does not ship: ANGLE/WebGL,
   WebGPU, WebRTC, Web Audio, WebCodecs, EME, WebXR, IndexedDB, service workers, OffscreenCanvas, and
   JSC's optimising tiers (compiled out).

An era gate also applies: a fix for `REGRESSION(322468@main)` cannot exist in a September-2023 snapshot,
however familiar the surrounding code looks. `--snapshot-rev` defaults to 268000 and drops later ones.

## Killed: array-index / tag confusion (bug 262616) is not reachable from JavaScript

The deserializer really does confuse an index of `0xFFFFFFFD` with `NonIndexPropertiesTag`, and Sony's
tree is pre-fix. But the *serializer* walks the array's index range, so producing the malicious stream
from JS is impractical. Measured in the local ASAN build with the same page reporting through beacons:

| event | result |
|---|---|
| `small-index:ok:19ms` | `a[100000] = 'x'; structuredClone(a)` round-trips in 19 ms |
| `big-alloc:0ms` | `b[4294967293] = 'y'` is instant |
| `big-index:...` | **never arrives** — `structuredClone(b)` hangs |

Upstream's own reproducer injects a hand-built byte stream for exactly this reason, so the bug needs a
sender that can supply serialized bytes — a sandbox-escape direction, not an entry point. Dead for a
WebView entry; recorded so it is not re-chased.

## The local ASAN oracle now works (recipe that matters)

Getting a page-driven answer out of the ASAN build needed four things, and each failure looks like a
WebKit bug rather than a harness bug:

1. `ASAN_OPTIONS=...:detect_stack_use_after_return=0`. JSC scans the raw stack for GC roots; ASAN's fake
   stack lives elsewhere, so the scanner walks unmapped memory and SEGVs. Every run aborted inside GC.
2. `WEBKIT_DISABLE_COMPOSITING_MODE=1` keeps rendering in-process so faults land in the instrumented
   build rather than a separate GPU process.
3. Run **inside the wk distrobox**: on the host, `libasan.so.8` is missing and every run exits 127.
4. Serve the page over HTTP and report through image GETs. A `file://` page has an opaque origin and its
   `sendBeacon` calls are dropped, which is indistinguishable from "the page never ran"; MiniBrowser does
   not forward `console.log`.

`/tmp/run_asan_page.sh` wraps 1-3; the http.server access log supplies the results.

## Killed: XPath GC-thread race (bug 309776) - the mechanism does not exist here

Upstream fix `e8db86ea12` (May 2026) locks `XPathResult::m_nodeSet` because the GC thread iterates the node
vector while the main thread can call `sort()` from `firstNode`/`snapshotItem`, a use-after-free. Sony's
tree carries the exact FIXME:

```cpp
// FIXME: This looks like it might race, but I'm not sure.
for (auto& node : value.toNodeSet())
    addWebCoreOpaqueRoot(visitor, node.get());
```

But the fix's own shape gives it away: it replaces that body with
`wrapped().visitAdditionalChildrenInGCThread(visitor)`. A recursive grep over `Source/` finds
`visitAdditionalChildrenInGCThread` in **zero files** in this snapshot - the off-thread visitation
mechanism did not exist in September 2023. Here the node set is only walked on the main thread, the same
thread that sorts it, so the race cannot happen. The FIXME was a premonition about a later architecture.

This is a recurring pattern worth stating: a fix dated 2024-2026 can describe a bug that this build simply
cannot have, either because the subsystem is absent (WebGL, WebRTC, Web Audio, WebCodecs) or because the
concurrency that creates the race was added later. The era gate catches the explicit `REGRESSION(<rev>)`
case; this class has to be caught by checking that the *mechanism* the fix refers to exists at all.

## Reachable-candidate ledger

| candidate | class | verdict |
|---|---|---|
| `@page` into a detached grouping rule | null deref | **confirmed on console**, control-validated (DoS) |
| bug 278657 ResizableSharedArrayBuffer injection | type confusion | dead: `SharedArrayBuffer` absent (measured) |
| `CachedString::m_jsString` | UAF | dead: pool indices only from `write(Identifier)` |
| bug 262616 array index vs `NonIndexPropertiesTag` | type confusion | dead from JS: serializer walks the index range, `structuredClone` never returns |
| bug 309776 XPath node-set race | UAF | dead: `visitAdditionalChildrenInGCThread` absent from this snapshot |
| OpenType vertical GSUB range (2196077a54) | OOB read | live and reachable via `@font-face`, but read-only into font data with no path back to JS - a crash, not a primitive |

Of 340 memory-safety patches examined (141 targeted + 191 write/race/uninit), 27 keep a contiguous pre-fix
block and only a handful touch subsystems this build actually ships. That is the real finding of this
round: the surface is small and Sony's backports are competent, not that the search was idle.

## CONFIRMED: OOB read in the vertical font parser, reachable from CSS alone

`@font-face` with a crafted font drives `OpenTypeVerticalData` into a heap-buffer-overflow **read**. ASAN,
on Sony's own tree:

```
READ of size 2 at 0x6070000ef33a
  #0 WebCore::OpenType::BigEndianUShort::operator unsigned short()   OpenTypeTypes.h:44
  #7 WebCore::OpenType::LookupTable::getSubstitutions()              OpenTypeVerticalData.cpp:182
  #9   GSUBTable::getVerticalGlyphSubstitutions()
  #10  OpenTypeVerticalData::loadVerticalGlyphSubstitutions()        :493
  #13  FontCache::verticalData(FontPlatformData const&)
  #21  CachedFont::createFont                                        (i.e. @font-face)
  #24  CSSFontFace::font
```

`fromEnd = end + 1` is `uint16_t`, so a Coverage Format 2 range whose `end` is `0xFFFF` yields `fromEnd == 0`;
`indexTo + (fromEnd - from)` then underflows to -1 and the guard passes, after which
`for (; from != fromEnd; ++from, ++indexTo) map->set(from, substitute[indexTo])` walks from `start` to
`0xFFFF` against a `substitute` array validated for one entry.

Font: `tools/fw1400/build_gsub_font.py` builds a 1008-byte TTF with minimal glyf/cmap/hmtx, **vhea+vmtx**
(loadMetrics returns early without them, so the vertical path is never entered) and a hand-written GSUB
carrying the poisoned range. Reproducer `guide_lab/www/cases/c013-font-gsub-oob.js` inlines the font as a
`data:` URI, so it needs nothing from the lab server.

**On the console it does not crash.** The case beacons `font-loaded:1` then `rendered`, and the process
survives: the read walks ~128 KB past a 2-byte array, and on retail that memory is mapped, so the loop
reads garbage instead of faulting. The bug is present and reached (same code, same font) but its effect
there is a silent out-of-bounds read, not a crash. No path was found from the read values (glyph ids
inserted into a `HashMap<uint16_t,uint16_t>` used for substitution) back to script, so it is not a leak
primitive either.

Why it still matters: it proves the **font parser is a live, unhardened surface reachable with zero
interaction** - an `@font-face` rule alone is enough, before any text is looked at. That is now the most
promising place to spend the next round, and unlike the DOM/CSS work it can be driven entirely by the local
ASAN build.
