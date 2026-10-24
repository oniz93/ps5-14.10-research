# Night report — what eight hours of digging actually produced

Started 03:35, ended ~07:00 local. Three parallel tracks: fuzzing the local engine, sweeping
upstream fixes against Sony's tree, and trying to build WebCore to test candidates locally.

## 1. The one result that matters

**WebKit bug 260896 — heap-use-after-free in `Style::Scope::removeStyleSheetCandidateNode` —
is live in Sony's 14.x WebKit.** Full analysis in `docs/23-style-scope-uaf.md`. Upstream
fixed it 2023-11-02; the drop is from September 2023 and both halves of the fix are absent:
the unused `RefPtr<SVGElement> m_element` that creates a RenderStyle → DOM cycle, and the
`weakPtrFactory().revokeAll()` that `~Scope()` never had.

This is the first memory-corruption bug in this whole project that is (a) confirmed present
in the code Sony ships, (b) reachable from a page, and (c) a use-after-free rather than a
crash. Probe is armed: `poc-style-scope-uaf.js`.

The dangling operation is a `WeakListHashSet::remove` **on the freed `Scope` object**, and
the RenderStyle→DOM cycle means the dangling call happens later, during GC, with JavaScript
running in between. That gap is what makes reclaim plausible — see the exploitation notes at
the end of `docs/23`.

## 2. How the candidate list was narrowed

Three sweeps, **348 unique upstream commits** scored against Sony's extracted tree. Raw
scoring is useless on its own (`VULN-SHAPE` also matches refactors), so two filters were
added:

- **Refactor / hardening rejection.** Three `std::span` conversions and a "should crash when
  deserializing" assertion scored as vulnerabilities before this. A fix that *adds* an
  assertion defends against a state the engine cannot produce — not a bug.
- **Era filter.** A fix landed in 2025 or 2026 may repair a regression introduced after
  September 2023, in which case Sony's older code is unaffected. Only fixes landed between
  Sep 2023 and Dec 2024 have pre-fix code that can plausibly *be* the code in this snapshot.

Of 348 commits, **11 memory-safety fixes land in that window**. Of those:

| date | verdict | what | status |
|---|---|---|---|
| 2023-11-02 | VULN-SHAPE | **Style::Scope UAF** | live, probe armed |
| 2024-01-24 | VULN-SHAPE | `ShadowBlur::blurLayerImage` heap-buffer-overflow | tested on console — does not reproduce (layer size is clamped to the clip) |
| 2024-08-05 | VULN-SHAPE | `RenderMenuList::setTextFromOption` UAF (`<select>` + `multiple`) | **live**: `usesMenuList()` is `!multiple && size <= 1`, so every plain `<select>` uses this renderer. Probe armed |
| 2024-09-04 | NOFILE | image frame size integer overflow | file did not exist in 2023 |
| 2024-04-15/20 | NOFILE | two `ViewTransition` UAFs | feature did not exist in 2023 |
| 2023-10-09 → 2024-08-02 | dead | four WebCodecs heap overflows | `ENABLE_WEB_CODECS` defaults OFF and the port does not override it |
| 2023-10-09 | dead | IndexedDB backing store UAF | IndexedDB is disabled on this WebView |

Four of eleven die on `ENABLE_WEB_CODECS` alone. That is the value of the era+surface filter:
without it, the list looks like a dozen opportunities and is actually one.

Also confirmed statically, as a second (weaker) find: `parseSimpleTransformValue` in
`CSSParserFastPaths.cpp` bounds-checks for 9 characters and then reads `pos[9]`, `pos[10]`
and `pos[11]`. Upstream only noticed in 2025. One-to-three byte over-read, reachable with
`element.style.transform = "translate"`, almost never fatal without a sanitizer — worth
nothing on the console, worth remembering if we ever get an ASAN build of WebCore.

## 3. What failed: the local WebCore build

The goal was a MiniBrowser from Sony's tree, so candidates could be tested without the
console. Six separate Xcode 27 incompatibilities were fixed:

| failure | fix |
|---|---|
| `xcodebuild: invalid option '--minibrowser'` | the flag is not a build-webkit option in this tree; drop it |
| `cannot execute tool 'metal' due to missing Metal Toolchain` | `xcodebuild -downloadComponent MetalToolchain` |
| `generate-unified-sources.sh: Permission denied` | the zip loses exec bits; `chmod +x` every `*.sh`/`*.py`/`*.pl`/`*.rb` under `Source` and `Tools` |
| `No such file: .../wtf/Scripts/generate-unified-source-bundles.rb` | seed `WebKitBuild/Debug/usr/local/include/wtf/Scripts` from `Source/WTF/Scripts` |
| `Copy of InspectorBackendCommands.js failed` | copy the generated file into `JavaScriptCore/PrivateHeaders` |
| `_LIBCPP_ENABLE_ASSERTIONS has been removed` | libc++ in the macOS 27 SDK makes it a hard error; drop the flag |
| libvpx/libsrtp `-Werror` on new warnings | `GCC_TREAT_WARNINGS_AS_ERRORS=NO` at the xcodebuild level, plus a `(double)` cast in `vp9_encoder.c` |

It compiled **1292 objects** before dying on bmalloc's TAPI filelist step
(`all-product-headers.yaml` missing), which is where it was abandoned. The remaining work is
mechanical but unbounded, and nothing suggests a 2023 WebKit will ever link cleanly against
Xcode 27 without a long tail of patches.

**Recommendation: build WebCore on Linux, not macOS.** The GTK or WPE port compiles with a
modern GCC/Clang and glibc, has no Xcode to fight, and the same source. A cheap Hetzner
instance or a Docker container would produce a working `MiniBrowser` in a couple of hours
instead of a hundred small patches. That is the single highest-leverage infrastructure
change available to this project.

## 4. Fuzzing

Exactly **160,500 additional cases** through the interpreter-only ASAN `jsc` (seeds 111, 222,
333 — three runs of 150 Yarr batches x 250 cases plus 80 parser batches x 200 cases each).
**Zero reports**, consistent with the earlier ~186,000. Running total across the session:
about 346,000 generated cases plus the 4,022-file regression corpus, and not one sanitizer
report. The engine floor is tight and further blind fuzzing of it is not worth the cycles.

## 5. Console queue for the morning

In order. Each is a two-minute test with the lab running.

1. **`/page/style-scope-upstream.html` first**, then `poc-style-scope-uaf.js` — the UAF.
   The upstream file is the fuzzer case verbatim and is the higher-fidelity test; the scripted
   probe approximates it. One correction worth recording: the crash stack is
   `SVGStyleElement::~SVGStyleElement → Scope::removeStyleSheetCandidateNode`, so the dying
   node is an **SVG `<style>` element**, and a probe without one cannot trigger this bug — the
   probe now inserts one, but that is exactly the kind of detail a hand-rebuilt reproducer
   gets wrong, which is why the authentic file is listed first. Expect `SCOPE-SURVIVED` on a
   patched engine, a blank WebView on a vulnerable one; the last `SCOPE-ITER-<n>` beacon gives
   the iteration count.
2. **`poc-select-uaf.js`** — the second UAF. Four lines upstream: `select { container: a1 / inline-size }`,
   mutate `options[1]`, then `select.multiple = true`. Sony's `itemStyle()` still dereferences
   `*element->computedStyle()` with no null check, and the fix's whole point is that a full
   style resolution there can free the renderer that is executing.
3. **`poc-sab-gates.js`** — the clone-race prerequisites (`crossOriginIsolated`,
   `SharedArrayBuffer`, resizable/growable buffers, worker round-trip). One gate decides
   whether the 2024 `CloneSerializer` bug is reachable at all.
4. **`poc-css-nesting-inval.js`** — `cssNestingEnabled` plus the bug 276942 crash path.

The lab now sends `COOP`/`COEP`/`CORP` on every response, so the SAB probe measures what
isolation unlocks rather than the non-isolated baseline.

There is also a new **`/page/<file>` route** that serves a file from
`tools/fw1400/guide_lab/www/pages/` byte-for-byte. This matters more than it sounds: some
upstream reproducers cannot be rebuilt from script, because they depend on the HTML parser's
error recovery (misnested tags, duplicate ids) to produce the tree that crashes — and
`innerHTML` cannot reproduce that, since the parser already normalised the markup when the
file was authored. Two authentic reproducers are in place:

| URL | content |
|---|---|
| `https://<mac>/page/style-scope-upstream.html` | bug 260896's original fuzzer case, verbatim |
| `https://<mac>/page/select-multiple-upstream.html` | bug 272882's four-line case, verbatim |

So the highest-fidelity test costs nothing extra: navigate the guide's WebView at those
paths instead of the wrapped probe. Both files are the upstream tests with only the
`testRunner` shim removed.

### Running the queue

```bash
cd ~/Documents/ps5-bootchain
python3 tools/fw1400/guide_lab.py --serve --lan-ip <mac-ip> --https-only         --https-port 8443 --dns-port 5353
# arm a scripted probe by name (this file, not guide_lab/www/current):
echo poc-style-scope-uaf.js > tools/fw1400/guide_lab/current
# or test an authentic reproducer by URL:
#   https://<mac>/page/style-scope-upstream.html
tail -f tools/fw1400/guide_lab/results/beacons.jsonl
```

A blank WebView plus a beacon sequence that stops at a known tag is a crash; the last tag
names the step.

## 6. Traps recorded, so they are not re-learned

- `guide_lab.py` reads `guide_lab/current`, **not** `guide_lab/www/current`. Arming the wrong
  file serves the previous probe and looks like a probe that did nothing.
- The PlayStation CDN intermittently serves a chain without intermediates; range reads then
  fail and a sweep reports zero candidates, which is indistinguishable from "nothing found".
  `wk_cve_sweep.py` now reads the local extraction.
- `urllib` cannot verify GitHub's chain on this Python; every search failed silently the same
  way. Now `curl`.
- A fuzzer whose generator is broken returns silent zeros. Both fuzzers have had that bug
  once each (Python recursion depth; exponential JSON depth).

Six silent-zero failures across the session. Every one looked like a negative result.
