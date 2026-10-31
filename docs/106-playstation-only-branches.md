# docs/106 — every Sony-only branch in the drop, classified

**Action (GOAL item 1):** read every `PLATFORM(PLAYSTATION)` block in `Source/JavaScriptCore` and
`Source/WebCore`, classify each as *adds a platform path* (inert for a GTK-only oracle) or *replaces
shared logic* (a deviation candidate), quote each site, and record — for a verdict that changes an
invariant shared code also has — where that invariant is measurable on the Linux oracle. PS-only code
cannot run on the oracle, so a candidate that exists only on console is recorded as *console-only,
unmeasured* rather than guessed at.

No console access was needed or used. One page was run on the oracle (§6.1).

## 1. What ran

```
$ python3 tools/platform-playstation-sweep.py --root out/sony/full/WebKit-1400/WebKit-1400 \
      --json data/ps-branches/blocks.json
186 PS conditional blocks, 186 PS condition lines, 111 files
38 blocks with a non-PS alternative branch
```

```
$ python3 tools/ps-branch-classify.py
blocks 186 {'add': 86, 'test': 8, 'dev': 42, 'log': 13, 'stub': 5, 'impl': 32}
dev kinds {'behav': 30, 'mem': 6, 'inert': 4, 'sec': 2}
```

`tools/platform-playstation-sweep.py` builds the conditional stack in **one forward pass** and attributes
each PS line to the innermost conditional that really contains it. The first version walked *backwards*
from the hit and stopped at the first `#if` at depth 0, which mis-attributed a line inside a nested `#if`
to that inner block and invented 24 phantom blocks (210 vs 186); the correction is what makes 186 exact.
`tools/ps-branch-classify.py` holds the verdict for every block and writes
`data/ps-branches/verdicts.json`, so the accounting is reproducible rather than narrative.

**Counts reconcile with GOAL's 17 + 185 exactly.** Raw lines matching `PLATFORM(PLAYSTATION)`:

| measure | JSC | WebCore | total |
|---|---|---|---|
| `grep -rn` all extensions | 21 | 185 | 206 |
| `PLATFORM (PLAYSTATION)` (space before the paren) | 0 | 4 | 4 |
| `#endif // … PLATFORM(PLAYSTATION)` trailer comments | 0 | 24 | 24 |
| **real conditional blocks** | **21** | **165** | **186** |

GOAL's "17 in JavaScriptCore" is the `.cpp`/`.h` subset (the four `API/tests/testapi.c` sites are `.c`);
its "185 in WebCore" includes the four spaced spellings and the 24 trailer comments.

## 2. The taxonomy, and what each verdict means here

| verdict | n | meaning |
|---|---|---|
| `dev` | **42** | the block **replaces shared logic** — a different bound, operand, container, error path, test, virtuality or implementation. Deviation candidate. |
| `stub` | 5 | the shared definition is compiled out for PS because the port defines it in a `playstation/` file |
| `log` | 13 | `PS_LOG`/`LOG` only |
| `impl` | 32 | PS-only implementation file (`platform/**/playstation/**`) |
| `test` | 8 | JSC API tests and the `testmem` tool — not shipped |
| `add` | 86 | adds a platform path, hook, field, enum value, method or include without changing a decision shared code also makes |

Of the 42 `dev` rows: 30 behaviour-only, 6 memory-lifetime/layout, 2 security, 4 inert (they change a
cast, a member section or an enum value that nothing persists). The 38 non-inert rows are §3/§4.

A block with a non-PS `#else` is the shape to look at hardest, but the shape alone decides nothing: 18 of
the 38 alternative-branch blocks are additions (§5), and the single inverted test in the whole surface
turns out to be a **downstream fix** (§6.5).

## 3. Every JavaScriptCore site (21 blocks)

| site | condition | kind | verdict |
|---|---|---|---|
| `API/JSBase.cpp:144` | `#if PLATFORM(PLAYSTATION) // for downstream-only` | add | `JSRunLoop()` runs `WTF::initializeMainThread(); RunLoop::run();`; the non-PS body is empty. Embedder API, not page-reachable. |
| `API/JSBase.cpp:152` | `#if PLATFORM(PLAYSTATION) // for downstream-only` | add | `JSSetOptions` really sets options on PS, `UNUSED_PARAM(args)` elsewhere. |
| `API/tests/FunctionOverridesTest.cpp:44` | `#if PLATFORM(PLAYSTATION)` | test | script path `/app0/testapiScripts/…`. |
| `API/tests/TypedArrayCTest.cpp:267` | `#if !PLATFORM(PLAYSTATION)` | test | skips the `JSObjectMakeTypedArray(context, type, UINT_MAX)` loop. |
| `API/tests/testapi.c:1409` | `#if !PLATFORM(PLAYSTATION)` | test | `testCAPIViaCpp` skipped. |
| `API/tests/testapi.c:2018` | `#if PLATFORM(PLAYSTATION)` | test | script path `/app0/…`. |
| `API/tests/testapi.c:2126` | `#if !PLATFORM(PLAYSTATION)` | test | `testFunctionOverrides` skipped. |
| `API/tests/testapi.c:2193` | `#if !PLATFORM(PLAYSTATION)` | test | `testExecutionTimeLimit` skipped. |
| `heap/BlockDirectory.cpp:63` | `#if OS(UNIX) && !PLATFORM(PLAYSTATION)` | dev/behav | the `mincore()` paged-out-page statistic is replaced by `UNUSED_PARAM(stats)`. Statistics only (`BlockDirectory::updatePercentageOfPagedOutPages`); no allocator decision reads it. |
| `inspector/remote/socket/RemoteInspectorSocket.cpp:41` | `#if PLATFORM(PLAYSTATION)` | add | `extern const char* kInspectorBackendCommandsString;` |
| `inspector/remote/socket/RemoteInspectorSocket.cpp:262` | `#if PLATFORM(PLAYSTATION)` | add | returns that string instead of the generated one. Inspector only. |
| `inspector/remote/socket/posix/RemoteInspectorSocketPOSIX.cpp:96` | `#if PLATFORM(PLAYSTATION)` | add | `setsockopt(fdListen, SOL_SOCKET, SO_USE_DEVLAN, …)` — a PS-only socket option. |
| `llint/LLIntPCRanges.h:46` | `#if PLATFORM(PLAYSTATION)` | dev/behav | `isLLIntPC()` returns **false** for every PC. Live consequence: `VMTraps.cpp:100 if (!isJITPC(trapPC) && !LLInt::isLLIntPC(trapPC)) return;` — a trap taken while executing LLInt code is ignored, so a watchdog/termination request that fires there installs no breakpoints. Everything else that asks is profiling or an assertion (`SamplingProfiler.cpp:243,399`, `CallFrame.h:373` under `USE(BUILTIN_FRAME_ADDRESS)`, `A64DOpcode.cpp:216`); `isFromJSCode()` therefore answers false for LLInt frames, and in a release build that only feeds `ASSERT`s. No memory consequence found. |
| `runtime/JSDateMath.cpp:147` | `#if PLATFORM(PLAYSTATION)` | dev/behav | `DateCache::calculateLocalTimeOffset` returns `WTF::calculateLocalTimeOffset(...)` **before** the ICU path, so the rest of the function is unreachable on PS. Page-observable through `Date`/`getTimezoneOffset()`. |
| `runtime/JSDateMath.cpp:501` | `#if PLATFORM(PLAYSTATION)` | dev/behav | timezone display names return `""_s` because "ICU's Timezone does not work well". Page-observable through `Intl.DateTimeFormat`/`toLocaleString`. |
| `runtime/JSLock.cpp:160` | `#if PLATFORM(PLAYSTATION)` | add | `CRASH()` when `Options::enableSingleThreadCheck()` and more than one thread is registered to a VM. Debug option, default off. |
| `runtime/Options.cpp:452` | `#if PLATFORM(PLAYSTATION)` | dev/mem | `Options::useConcurrentGC() = false;` **inside `#if ENABLE(MAT)`**, and `ENABLE_MAT` is `WEBKIT_OPTION_DEFINE(ENABLE_MAT … PUBLIC OFF)` (`OptionsPlayStation.cmake:290`). In the default build the block is compiled out and concurrent GC keeps its default. Console-only and build-dependent; the shipping build's cache is not in the drop. |
| `runtime/StructureID.h:50` | `#elif PLATFORM(PLAYSTATION)` | dev/mem | `structureHeapAddressSize = 128 * MB`, so `structureIDMask = 0x07ffffff` (§6.3). |
| `runtime/VM.cpp:395` | `#if PLATFORM(PLAYSTATION)` | dev/mem | `Config::disableFreezingForTesting();` at the end of `VM::finishInitialization`, with a FIXME saying to remove it when RNPS stops needing it (§6.2). |
| `testmem/testmem.cpp:38` | `#if PLATFORM(PLAYSTATION)` | test | `#include <memory-extra/showmap.h>` |
| `testmem/testmem.cpp:53` | `#if PLATFORM(PLAYSTATION)` | test | `SceNKFastMalloc` footprint via showmap |

## 4. WebCore sites that replace shared logic (42 blocks)

Quoted condition and the decisive line are in the verdict column; `mem` = memory-lifetime or layout,
`sec` = security decision, `inert` = a difference with no observable consequence.

| site | condition | kind | what it replaces |
|---|---|---|---|
| `Modules/mediasource/MediaSource.cpp:334` | `#if PLATFORM(PLAYSTATION)` | behav | `static NeverDestroyed<MediaTime> fudgeFactor(1, 10);` (100 ms) against `2002/24000` (83.4 ms). A bound in `hasCurrentTime()`. |
| `Modules/mediasource/SourceBuffer.cpp:250` | `#if !PLATFORM(PLAYSTATION)` | behav | `monitorBufferingRate();` is not called on `appendBuffer`. |
| `Modules/mediasource/SourceBuffer.cpp:628` | `#if !PLATFORM(PLAYSTATION)` | behav | same call removed on append completion. |
| `dom/Document.cpp:7552` | `#if PLATFORM(PLAYSTATION)` | behav | `if (m_userActivatedMediaFinishedPlayingTimestamp && …)` — the extra `timestamp &&` only changes the first 5 s of process uptime, when `MonotonicTime()` + 5 s is still `>= now()`. |
| `editing/FrameSelection.cpp:1435` | `#if PLATFORM(PLAYSTATION)` | behav | `if (!caretIsVisible()) return false;` before any selection modification. |
| `html/HTMLSelectElement.cpp:1325` | `#if PLATFORM(PLAYSTATION)` | behav | `multi = true;` — every mouse-driven `updateSelectedState()` behaves as ctrl-click. |
| `loader/DocumentLoader.cpp:2530` | `#if PLATFORM(PLAYSTATION)` | inert | the `static_cast<ScriptExecutionContext*>` is dropped; the same `addConsoleMessage(messageSource, messageLevel, message, requestIdentifier)` is called. Comment: CFI bug in LLVM-9. |
| `page/csp/ContentSecurityPolicy.cpp:827` | `#if PLATFORM(PLAYSTATION)` | **sec** | `if (!usesReportTo \|\| !is<Document>(m_scriptExecutionContext))` against upstream `&&` (§6.5). |
| `platform/ReferrerPolicy.h:50` | `#if PLATFORM(PLAYSTATION)` | **sec** | `Default = NoReferrerWhenDowngrade` against `Default = StrictOriginWhenCrossOrigin` (§6.1). |
| `platform/WebCorePersistentCoders.cpp:468` | `#if PLATFORM(PLAYSTATION) // for downstream-only` | behav | the encoder writes `hasPrivateKey`, `privateKey` and `privateKeyPassword` after the chain. |
| `platform/WebCorePersistentCoders.cpp:499` | `#if PLATFORM(PLAYSTATION) // for downstream-only` | behav | the decoder *requires* those three fields. Self-consistent on PS; the enum/payload shape differs from every other CURL port. |
| `platform/encryptedmedia/CDMInstance.h:82` | `#if PLATFORM(PLAYSTATION)` | inert | `Playstation` is inserted **mid-enum**: `Remote` 3→4 and `Thunder` 4→5 on PS. Nothing persists the value; comparisons are in-process. |
| `platform/graphics/AudioTrackPrivate.h:61` | `#if PLATFORM(PLAYSTATION)` | behav | `virtual bool enabled() const` against a non-virtual inline — dispatch changes for the PS track classes. |
| `platform/graphics/Font.cpp:606` | `#if !PLATFORM(PLAYSTATION)` | behav | `canRenderCombiningCharacterSequence` for a variation selector: PS tests `(isColorBitmapFont() && vsText) \|\| (!supportsCodePoint(codePoint) \|\| (!vsText && !supportsCodePoint(*it)))` with `vsText = (*it == 0xFE0E)`, so **FE0E is accepted from a font that has no glyph for it** and refused outright in a colour-bitmap font. |
| `platform/graphics/ImageSource.cpp:604` | `#if PLATFORM(PLAYSTATION)` | behav | adds `else if (!m_frames.isEmpty() && isDecoderAvailable() && m_decoder->isSizeAvailable()) size = m_decoder->size();` — the size comes from the decoder and the frame-metadata cache is **not** written, where shared code calls `firstFrameMetadataCacheIfNeeded(...)`. Page-reachable through `naturalWidth`/`naturalHeight`. |
| `platform/graphics/MediaPlayer.cpp:1087` | `#if !PLATFORM(PLAYSTATION)` | behav | the `if (m_presentationSize == size) return;` short-circuit is removed: PS always calls `m_private->setPresentationSize(size)`. |
| `platform/graphics/PlatformDisplay.h:86` | `#if PLATFORM(PLAYSTATION)` | inert | `PlayStation` inserted before the `USE(EGL)` values: `Surfaceless`/`GBM` shift by one on PS. |
| `platform/graphics/SourceBufferPrivate.cpp:1114` | `#if PLATFORM(PLAYSTATION)` | behav | with `LibTweak::USE_1MEDIASAMPLE_MULTIPLEFRAMES` active: `hpt - tolerance < frameEndTimestamp`, otherwise `<= presentationTimestamp`. Both the comparison **and** the right-hand operand change, and `frameEndTimestamp > presentationTimestamp` for any non-zero duration, so the tweak makes the erasure branch fire far more often. |
| `platform/graphics/SourceBufferPrivate.cpp:1157` | `#if PLATFORM(PLAYSTATION)` | behav | tweak-gated extra erasure: samples whose decode timestamp equals `lastDecodeTimestamp()` and whose presentation range is `[presentationTimestamp, frameEndTimestamp)`. |
| `platform/graphics/WidthIterator.cpp:225` | `#if !PLATFORM(PLAYSTATION)` | behav | the `glyphBuffer.add(0, font, 0, currentCharacterIndex + 1)` padding for `!U_IS_BMP(character)` is **not** emitted, so on PS the glyph buffer is one entry shorter than the code-unit count for every non-BMP character. Character indices come from the text iterator, so widths do not move; the padding is what a shaper uses to map a cluster to its last code unit. |
| `platform/graphics/cairo/CairoOperations.cpp:906` | `#if PLATFORM(PLAYSTATION)` | behav | `CAIRO_FILTER_BILINEAR` where shared code uses `CAIRO_FILTER_GOOD`. |
| `platform/graphics/cairo/CairoOperations.cpp:913` | `#if PLATFORM(PLAYSTATION)` | behav | `CAIRO_FILTER_BILINEAR` where shared code uses `CAIRO_FILTER_BEST`. |
| `platform/graphics/freetype/FontPlatformDataFreeType.cpp:127` | `#if PLATFORM(PLAYSTATION)` | behav | `m_syntheticBold = false;` — PS never synthesises bold. |
| `…/FontPlatformDataFreeType.cpp:254` | `#if PLATFORM(PLAYSTATION)` | behav | the font matrix is built from `FC_MATRIX` instead of `cairo_matrix_init(&fontMatrix, 1, -yx, -xy, 1, 0, 0)`. |
| `…/FontPlatformDataFreeType.cpp:274` | `#if PLATFORM(PLAYSTATION)` | behav | translates the matrix by `(xy, -yx)` and calls `cairo_ft_font_face_reset_synthesize_weight`. |
| `…/FontPlatformDataFreeType.cpp:287` | `#if PLATFORM(PLAYSTATION)` | behav | `syntheticObliqueSkew = -((double)0x03a / (double)0x100)` (-0.2266) against `-tanf(14°)` (-0.2493). |
| `platform/graphics/freetype/SimpleFontDataFreeType.cpp:137` | `#if PLATFORM(PLAYSTATION)` | behav | ascent/descent from `OS/2` `usWinAscent`/`usWinDescent` ("to keep compatibility with Silk porting") instead of the typo metrics that shared code prefers when `USE_TYPO_METRICS` is set. |
| `platform/graphics/texmap/TextureMapper.cpp:36` | `#if PLATFORM(PLAYSTATION)` | **mem** | `acquireTextureFromPool` calls `createTexture()` on every acquire — **no texture pool, no reuse** — against `m_texturePool->acquireTexture(size, flags)`. Every acquire allocates a new `BitmapTexture` and nothing returns it to a pool; a different allocation count and lifetime for the compositor. |
| `platform/network/curl/CurlRequest.cpp:467` | `#if PLATFORM(PLAYSTATION) // for downstream-only` | behav | `didReceiveResponse` is also invoked when `WebSecurity::shouldBlock(m_response.statusCode, m_response.httpConnectCode)` — an external Sony library decides. |
| `platform/network/curl/CurlRequest.h:71` | `#if PLATFORM(PLAYSTATION)` | behav | `resume()`/`cancel()` become `virtual`. |
| `platform/network/curl/CurlRequest.h:90` | `#if PLATFORM(PLAYSTATION) // for downstream-only` | inert | the member section becomes `protected:` instead of `private:`. |
| `rendering/RenderElement.cpp:1475` | `#if PLATFORM(PLAYSTATION)` | **mem** | `canDestroyDecodedData()` gets an out-of-line body: if `frameView.paintsEntireContents()`, it computes `fixedVisibleContentRect()` and returns `!isVisibleInDocumentRect(...)`; shared code is `{ return !isVisibleInViewport(); }`, which the header's own comment says is always **false** in that configuration (§6.4). |
| `rendering/RenderElement.h:369` | `#if PLATFORM(PLAYSTATION)` | **mem** | declares that override `final` instead of the inline one-liner. |
| `rendering/RenderLayer.cpp:2129` | `#if PLATFORM(PLAYSTATION)` | behav | `if (!parentLayer) return;` before `ASSERT(parentLayer)` — a null filter-repaint parent is tolerated instead of asserted. |
| `rendering/RenderLayer.cpp:5638` | `#if PLATFORM(PLAYSTATION)` | behav | `renderer().view().setHasSoftwareFilters(true);` on **every** filtered layer, which switches `RenderObject::containerForRepaint()` (`RenderObject.cpp:884`) into the enclosing-filter-layer path for the whole view. |

## 5. The rest of WebCore, by shape

**Stubs (5)** — shared definition compiled out because the port has its own:
`platform/Widget.cpp:277` (`Widget::~Widget`/`setFrameRect`), `platform/encryptedmedia/CDMFactory.cpp:64`
(`platformRegisterFactories` → `playstation/eme/CDMFactoryPlayStation.cpp`),
`platform/graphics/freetype/FontCacheFreeType.cpp:127` (`systemFallbackForCharacters` →
`playstation/FontCachePlayStation.cpp:117`), `platform/graphics/harfbuzz/FontDescriptionHarfBuzz.cpp:31`
(`effectiveFamilyCount/At` → `playstation/FontDescriptionPlayStation.cpp:52`),
`page/EventHandler.cpp:5102` (`tabsToAllFormControls` → `page/playstation/EventHandlerPlayStation.cpp:36`).
The last one is the audit's proof that a PS-only implementation does not need a `#if` at all (§7).

**Logs (13)** — `SourceBuffer.cpp:143,186,218,246,313,539,600,633`,
`SourceBufferPrivate.cpp:475,510,574,583`, `CookieJarDB.cpp:541`. One of them is not purely a log:
`SourceBufferPrivate.cpp:562` computes `initialBufferedSize` before the eviction loop so the later logs can
report the delta; it is in the `add` column because no decision reads it.

**PS-only implementations (32)** — every `platform/graphics/playstation/**` and
`platform/network/playstation/**` guard: `MediaPlayerPrivatePlayStation.{cpp,h}`,
`PlatformDisplayPlayStation.h`, `eme/CDM{Factory,Instance,InstanceSession,Private,Util}PlayStation.{cpp,h}`,
`mse/{Audio,Video}TrackPrivatePlayStation.{cpp,h}`, `mse/InbandTextTrackPrivatePlayStation.{cpp,h}`,
`mse/MediaDescriptionPlayStation.{cpp,h}`, `mse/MediaSamplePrivatePlayStation.{cpp,h}`,
`mse/MediaSourcePrivatePlayStation.{cpp,h}`, `mse/SourceBufferPrivatePlayStation.{cpp,h}`,
`network/playstation/CurlSSLHandlePlayStation.cpp:38,53`,
`network/playstation/CurlTMServiceRequest.{cpp,h}`, `network/playstation/ResourceErrorPlayStation.cpp`.

**Additions (86)**, grouped: 9 includes (`CDMPrivatePlayStation.h`, `libtweak/libtweak.h` ×3,
`MediaPlayerPrivatePlayStation.h`, `PlatformDisplayPlayStation.h`, `WebKitResources.h`,
`WebSecurity/WebSecurity.h`, `memory-extra/showmap.h`), 22 declarations (AX notifications in `Chrome`/
`ChromeClient`/`EventHandler:2278`, `Editor::confirmComposition`, `FocusController` editable-element
helpers, `NicosiaContentLayerTextureMapperImpl::needsSwapBuffersOnCompositingThread`,
`TextureMapperShaderProgram::setOptions` and its binary-shader constructor, `PlayStationMediaPlayerEnabled`
plumbing, `CurlRequest::setClientCertificate`, `CurlSSLHandle::setAdditionalRootCA`,
`ResourceError::cancelledInServerTrustEvaluationError`, `MediaPlayer::contentTypeRaw`), and 55 value
additions (enum members, `PSMediaSampleRef`, `PS_LOG`-free diagnostic counters, `Thread::yield()`,
`structureIDMask`-adjacent helpers, the `TEXMAP_UNIFORM_VARIABLES` list, `cairo` filter constants,
`PlatformDisplay::create()`, `GLContext` EGL cases, `NavigatorBase` vendor/platform strings,
`LocalizedStrings::formatLocalizedString`, `DeprecatedGlobalSettings`, `MediaStrategy`).
Two of the 55 are worth naming because they *look* like deviations and are not: the
`TEXMAP_UNIFORM_VARIABLES` list inserts `expandedQuadEdgesInScreenSpace` at position 7 and appends
`optionsMatrix` (a per-build enum, nothing persisted), and `NavigatorBase.cpp:61` sets
`navigator.vendor` to `"Sony Interactive Entertainment Inc."` — a covert console fingerprint that costs
nothing to record.
The complete per-block list, with condition text, is `data/ps-branches/verdicts.json`.

## 6. What the classification turned up

### 6.1 The referrer default is a real, page-observable security deviation — and the oracle half is measured

`ReferrerPolicy::Default` is not a sentinel: `SecurityContext::m_referrerPolicy { ReferrerPolicy::Default }`
(`SecurityContext.h:158`), `PolicyContainer.h:40`, `FrameLoader.cpp:4207` and `CachedResourceLoader.cpp:1026`
all use it. On PS it is **the same enumerator value as `NoReferrerWhenDowngrade`**, so
`SecurityPolicy::generateReferrerHeader` falls through the `switch` (`SecurityPolicy.cpp:102-103,135`) and
returns the full referrer; on every other port the value is `StrictOriginWhenCrossOrigin`
(`:122-129`) and a cross-origin request gets the origin only.

Measured on the oracle, one page, three attributes, `research/referrer/refrun.sh r1 8971 8972 20`
(`data/referrer/r1.log`, verbatim; the first two lines are the runner's own `curl` warm-up and the last is
the browser fetching `/favicon.ico`):

```
16:19:27 page /arm=a referer=<none>
16:19:27 res /res.png?arm=warm referer=<none>
16:19:31 page /arm=a referer=<none>
16:19:31 res /res.png?arm=a referer=http://localhost:8971/
16:19:31 res /res.png?arm=b referer=http://localhost:8971/arm=a
16:19:31 res /res.png?arm=c referer=<none>
16:19:31 page /favicon.ico referer=http://localhost:8971/arm=a
```

The browser run's last line was `EXIT=124` — the harness timeout, which is how every `run_nq.sh` run ends.

Arm `a` is the default: **origin only** — the oracle is `StrictOriginWhenCrossOrigin`, as the source says.
Arm `b` (`referrerpolicy="unsafe-url"`) sends the full URL, arm `c` (`no-referrer`) sends nothing, so the
header really is produced by this policy path and the log is a true oracle. The console half is
compile-time: the same expression with `Default == NoReferrerWhenDowngrade` returns `referrer`, i.e.
`http://localhost:8971/arm=a?…` including path and query, on every cross-origin request from a document
that has not set a policy. **Console arm not run** (the console is wedged, GOAL bottom), so what is
measured here is the oracle end of the delta; the console end is read from the enum, not run.

### 6.2 The console's JSC/WTF config record is never made read-only — two independent reasons

`JSC::Config` is not a separate object in this build: `ENABLE_UNIFIED_AND_FREEZABLE_CONFIG_RECORD` is 1 for
every non-Windows port (`PlatformEnable.h:840-844`), and
`#define g_jscConfig (*bitwise_cast<JSC::Config*>(&g_wtfConfig.spaceForExtensions))` (`JSCConfig.h:124`)
puts it inside `WebConfig::g_config` — the same record as `g_wtfConfig` and the Gigacage config.

That record is protected in exactly one place: `WTF::Config::permanentlyFreeze()` runs
`mprotect(&WebConfig::g_config, ConfigSizeToProtect, PROT_READ)` under **`#elif OS(LINUX)`**
(`WTFConfig.cpp:150-151`); the Cocoa arm uses `vm_protect` and the Windows arm is a FIXME. The port is not
`OS(LINUX)`: `WebKitCommon.cmake:130-137` classifies a UNIX `CMAKE_SYSTEM_NAME` that is not `Linux` as
plain `WTF_OS_UNIX`, and `OptionsPlayStation.cmake:317` shows the name it is built with
(`CMAKE_SYSTEM_NAME STREQUAL "PlayStation4"`). So on the console the freeze call has **no branch that
protects anything** — `result` stays 0 and the `RELEASE_ASSERT(!result)` passes.

Second reason, PS-specific: `VM::finishInitialization` calls `Config::disableFreezingForTesting()` before
`if (!g_jscConfig.disabledFreezingForTesting) Config::permanentlyFreeze();` (`VM.cpp:395-400`), so the flag
is set and the call is skipped outright.

Consequence, stated as a source fact and **not** measured: on 14.10 `g_jscConfig` and `g_wtfConfig` are
writable memory, so the usual "corrupt a JSC option" step needs no `mprotect` bypass. The caveat is real
and belongs in the record: the drop does not contain the toolchain's predefine list, so if Sony's compiler
also defines `__linux__` (or `__FreeBSD__`), `PlatformOS.h:86,101` would set that OS macro and the
`#elif OS(LINUX)` arm would run. Two facts argue against it — `HAVE_MEMMEM` is explicitly *excluded* for PS
(`PlatformHave.h:387`, while glibc has it) and `OptionsPlayStation.cmake:663` defines
`-Dgmtime_r=gmtime_s`, i.e. a libc that is not the Linux one — but neither is proof. Cannot be measured on
the oracle: GTK **is** `OS(LINUX)`, so the oracle takes the very branch the console lacks.

### 6.3 The structure heap is 128 MB, and that is a containment property

`structureHeapAddressSize = 128 * MB` (`StructureID.h:50-51`) makes `structureIDMask = 0x07ffffff`
(`:72`) and `StructureID::decode()` = `(bits & mask) + startOfStructureHeap()` (`:132`).
`tryDecode()` additionally rejects `offset < MarkedBlock::blockSize || offset >= g_jscConfig.sizeOfStructureHeap`
(`:139`), and `g_jscConfig.sizeOfStructureHeap` is the **mapped** size, not the reservation
(`StructureAlignedMemoryAllocator.cpp:93,105`). So a corrupted `StructureID` — the classic JSC exploit
step — can only ever decode into the structure reservation on console, and into 32× less of it than
upstream's 4 GB mask allows. Not a primitive; a boundary that a console chain would have to live with.
Unmeasurable on the oracle (4 GB there), and console-only.

### 6.4 Decoded image data is destroyed in a configuration where shared code refuses — console-only

`ImageObserver::canDestroyDecodedData` is what `BitmapImage::destroyDecodedDataIfNecessary`
(`BitmapImage.cpp:82`) and `CachedImage::canDestroyDecodedData` (`CachedImage.cpp:663-670`) ask before
freeing decoded frames. Shared code answers `!isVisibleInViewport()`, and `RenderElement.h:370-371`'s own
comment says that is always false once `ScrollView::m_paintsEntireContents` is set — which
`LocalFrameView::init` does when `page->chrome().client().shouldPaintEntireContents()` (`:342-344`).
The PS override answers "destroy" for everything outside `fixedVisibleContentRect()`.

So on the console, in a `shouldPaintEntireContents()` page, an image element that shared code keeps
decoded can have its frames freed. Whether that is a UAF needs a paint or filter pass that still holds a
decoded frame across the decision — not established here, and **not measurable on the oracle** (GTK is not
coordinated and does not set `paintsEntireContents`). Recorded as a console-only candidate with the exact
condition. Note `RenderLayer.cpp:5638` is a *different* flag (`RenderView::m_hasSoftwareFilters`), not this
one — the two PS blocks are unrelated even though both are about filters.

### 6.5 The one inverted test in the surface is a downstream *fix*

`ContentSecurityPolicy::reportViolation` returns early on
`if (!usesReportTo || !is<Document>(m_scriptExecutionContext))` on PS and on the upstream
`if (!usesReportTo && !is<Document>(...))` elsewhere (`:827-836`), with a comment saying the `AND`
judgement cannot prove the downcast. It is right: upstream proceeds to
`auto& document = downcast<Document>(*m_scriptExecutionContext);` (`:838`) when `usesReportTo` is true even
if the context is not a `Document`. `WorkletGlobalScope.cpp:63,81` is the one constructor that gives a CSP
a **null `m_client`** and a non-Document context, so a worklet CSP carrying `report-to` tokens that reports
a violation is a candidate for that UB — on the oracle, not on the console. Unmeasured, and it cannot help
the console: the safe branch is the PS one.

### 6.6 Smaller facts worth keeping

- `OptionsPlayStation.cmake:284,286` defines `ENABLE_LIBPAS … OFF` and `:741-742` then adds
  `-DBENABLE_LIBPAS=0`: **libpas is off on the console**, so the allocator is classic bmalloc. That is a
  heap-behaviour fact for every future grooming experiment and it is not covered by this audit (§8).
- `MediaPlayerEnums.h:40,97` and `MediaSample.h:63` append at the end of their enums, so no value moves;
  only `CDMInstance::ImplementationType` and `PlatformDisplay::Type` shift values (`Remote` 3→4,
  `Surfaceless`/`GBM` +1), and nothing persists either.
- `Document::processingUserGestureForMedia`'s extra guard is a **no-op after the first 5 s of uptime**,
  which is worth knowing before anyone reads it as a hardening.
- `ImageSource::sourceSize` on PS can read the decoder's size while the frame-metadata cache stays empty;
  that is the one image-size source in the tree that is not `firstFrameMetadataCacheIfNeeded`, and it is
  page-observable through `naturalWidth`/`naturalHeight`.

## 7. Limits

- **The audit covers `#if PLATFORM(PLAYSTATION)` blocks, not PS-only files.** `PlatformPlayStation.cmake`
  in WebCore lists **64** `.cpp/.mm` files that exist in the drop; **18** carry a PS guard and **46 carry
  none** — they are PS-only by virtue of the source list. `page/playstation/EventHandlerPlayStation.cpp`
  (which defines `tabsToAllFormControls` for PS) is one of the 46, i.e. the grep-based surface
  *undercounts* the port's own code. The same file lists 142 entries in `Source/WebKit` and 14 in
  `Source/WTF`. This action's scope was the conditional blocks; the file lists are §8.
- PS code cannot run on the GTK oracle, so every `dev` verdict is a **source** classification. Only §6.1
  has a measured oracle arm, and it measures the oracle end of the delta, not the console end.
- One read per site, no dynamic confirmation. Two verdicts (`Options.cpp:452`, `CDMInstance.h:82`) depend
  on build configuration or on nothing persisting the value; both are stated with that dependency.
- The classifier is a rule plus an explicit table; the rules are in `tools/ps-branch-classify.py` and every
  block's verdict is in `data/ps-branches/verdicts.json`, so a disagreement is a one-line diff rather than
  a re-read.

## 8. What this changes

1. **The "Sony-only branch that changes shared logic" hypothesis is now enumerated and it is not where the
   memory bugs are.** 42 of 186 blocks replace shared logic; 6 touch memory lifetime or layout, and **none
   of them is reachable on the oracle** — 2 are console-only by construction (`StructureID`, the config
   record), 1 is console-only in practice (`RenderElement::canDestroyDecodedData`), 1 is build-dependent
   (`Options::useConcurrentGC`), 1 is allocation behaviour (`TextureMapper`), and 1 is a statistics path.
   The two security deviations (§6.1, §6.5) are the referrer default and a downstream CSP fix.
2. **`docs/65` and `docs/94` remain the programme's only live memory primitives**, and nothing in this
   audit adds a third.
3. **The next surface is the rest of the tree**: `Source/WTF` (32 lines / 16 files), `Source/bmalloc`
   (39 `PLATFORM(PLAYSTATION)` + 22 `BPLATFORM(PLAYSTATION)` / 22 files) and `Source/WebKit`
   (118 lines / 57 files), plus the 46 unguarded PS-only files in WebCore's source list. The allocator and
   the config record live there, and §6.2 and the `ENABLE_LIBPAS=0` fact both came from that layer.

## 9. Artefacts

- `tools/platform-playstation-sweep.py` — the block extractor (one forward pass; `--json`).
- `tools/ps-branch-classify.py` — verdict table, categories above.
- `data/ps-branches/blocks.json`, `data/ps-branches/verdicts.json` — 186 blocks, 186 verdicts.
- `data/ps-branches/listing.txt` — the raw per-block digest the reading was done from.
- `research/referrer/{refsrv.py,refrun.sh}` — the two-origin referrer probe and its runner.
