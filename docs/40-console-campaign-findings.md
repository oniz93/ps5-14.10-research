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
