# docs/107 — the Sony-only surface outside JavaScriptCore/WebCore: WTF, bmalloc, WebKit, and the unguarded file lists

**Action (GOAL item 1, the one docs/106 §8 named):** read the PS-only surface *outside*
`Source/JavaScriptCore` + `Source/WebCore` — `Source/WTF` (32 lines / 16 files), `Source/bmalloc`
(39 lines, 22 of them the `BPLATFORM` spelling) and `Source/WebKit` (118 lines / 57 files) — plus the files that are PS-only by **source list** and carry no `#if` at all
(docs/106 §7's blind spot). Classify every block with the docs/106 taxonomy, quote the decisive line, and for
every `dev` row either run an oracle arm or write down, explicitly, that it is console-only and unmeasured.

No console access was needed or used, and **no oracle run was needed**: every row below is either
`console-only` by construction (the code is inside `PLATFORM(PLAYSTATION)`, so the GTK oracle cannot execute
it) or a fact the oracle *already* exhibits in the opposite direction, which is quoted from the existing
logs. §3.5 adds a compile-time result that needs no run at all.

## 1. What ran

```
$ python3 tools/platform-playstation-sweep.py --root out/sony/full/WebKit-1400/WebKit-1400 \
      --json /tmp/regress_jsc_webcore.json
186 PS conditional blocks, 186 PS condition lines, 111 files
38 blocks with a non-PS alternative branch

$ python3 tools/platform-playstation-sweep.py --root out/sony/full/WebKit-1400/WebKit-1400 \
      --subdirs Source/WTF,Source/bmalloc,Source/WebKit \
      --json data/ps-branches/blocks-outer.json
183 PS conditional blocks, 184 PS condition lines, 94 files
53 blocks with a non-PS alternative branch

$ python3 tools/ps-outer-classify.py
blocks 183 {'add': 138, 'dev': 33, 'stub': 8, 'impl': 3, 'flag': 1}
by dir {'WTF': 30, 'WebKit': 117, 'bmalloc': 36}
dev kinds {'behav': 21, 'mem': 5, 'inert': 4, 'sec': 2, 'flag': 1}

$ python3 tools/ps-file-list-sweep.py --root out/sony/full/WebKit-1400/WebKit-1400 --dir Source/WebCore \
      --json data/ps-branches/files-WebCore.json
Source/WebCore PlayStation {'shared': 29, 'ps-only': 39}
$ … --dir Source/WebKit --json data/ps-branches/files-WebKit.json
Source/WebKit PlayStation {'ps-only': 83, 'shared': 70, 'missing': 1}
$ … --dir Source/WTF/wtf --json data/ps-branches/files-WTF.json
Source/WTF/wtf PlayStation {'shared': 1, 'ps-only': 14}
```

The first command is the docs/106 regression: the extractor now matches `B?PLATFORM(...)`, and it still
reports **186 / 186 / 111 / 38**, so the bmalloc spelling did not perturb the earlier count. The wider run
splits 30 / 117 / 36 by directory; the raw line counts were 32 / 118 / 61 and lines collapse where two PS
conditions live in one conditional (e.g. `#if X … #elif PLATFORM(PLAYSTATION)`).

`tools/ps-outer-classify.py` holds the verdict for every non-`add` block
(`data/ps-branches/verdicts-outer.json`), so the accounting is reproducible rather than narrative.
`tools/ps-file-list-sweep.py` is new: it answers the §7 blind spot by *file*, not by `#if` (§7).

## 2. The taxonomy, and what the counts mean

| verdict | n | meaning |
|---|---|---|
| `add` | **138** | adds a platform path, hook, field, method, enum value or include; no decision shared code also makes changes |
| `dev` | **33** | replaces shared logic — 21 behaviour, **5 memory/lifetime/stack**, 4 inert, 2 security, 1 build flag |
| `stub` | 8 | the shared definition is compiled out because the port supplies it in a `playstation/` or `posix/` file (all 8 are WTF `FileSystem` or `WebPreferences::platformInitializeStore`) |
| `impl` | 3 | PS-only implementation block (most of the port's own files are whole files with no `#if` at all — §7 counts those) |
| `flag` | 1 | `BENABLE_LIBPAS`' default, which the *build* overrides (§4.1) |

**The surface is additive to a much higher degree than WebCore's was.** docs/106 found 42 of 186 (23 %)
`dev`; here it is 33 of 183 (18 %), and only **five** rows touch memory, all of them in WTF/bmalloc — the
allocator layer, which is exactly where docs/106 §8 predicted the interesting facts would be.

## 3. Source/WTF (30 blocks): two real bounds, four crash-mode rows

### 3.1 Every non-JavaScript WTF thread on the console has a 64 KB stack

`Source/WTF/wtf/PlatformPlayStation.cmake:44` is a build define no other port sets:

```
add_definitions(-DDEFAULT_THREAD_STACK_SIZE_IN_KB=64)
```

and `Source/WTF/wtf/Threading.cpp:104-117` is the consumer:

```
#if PLATFORM(PLAYSTATION)
    if (threadType == ThreadType::JavaScript)
        return 512 * KB;
#elif OS(DARWIN) && ASAN_ENABLED
    …
#endif

#if defined(DEFAULT_THREAD_STACK_SIZE_IN_KB) && DEFAULT_THREAD_STACK_SIZE_IN_KB > 0
    return DEFAULT_THREAD_STACK_SIZE_IN_KB * 1024;
…
#else
    // Use the platform's default stack size
    return std::nullopt;
```

with `Thread::establishHandle` calling `pthread_attr_setstacksize(&attr, stackSize.value())`
(`posix/ThreadingPOSIX.cpp:294-295`). So on 14.10: **JavaScript threads 512 KB, every other WTF thread
64 KB**; on the oracle the same code returns `nullopt`, i.e. **no `setstacksize` at all** (8 MB glibc
default). This is a *bound shared code also has* — the same recursive code that runs on a WorkQueue,
`RunLoopGeneric`, the compiler thread or the IPC encoder on the oracle runs on 1/128 of the stack on the
console. It is not a deviation in a decision, and it cannot be measured on the oracle without rebuilding
with the same define; recorded as **console-only, unmeasured**.

Related, the port uses `generic/RunLoopGeneric.cpp` and `generic/WorkQueueGeneric.cpp` (§7), i.e. no GLib —
which is why the IPC connection needs its own monitor thread (§5.3).

### 3.2 The page-size ceiling is 16 KB, where every 4 KB port clamps at 4 KB

`Source/WTF/wtf/PageBlock.h:52`:

```
#if OS(DARWIN) || PLATFORM(PLAYSTATION) || CPU(MIPS) || … || (OS(LINUX) && CPU(ARM64) && !USE(64KB_PAGE_BLOCK))
constexpr size_t CeilingOnPageSize = 16 * KB;
```

and `PageBlock.cpp:60-69` is `s_pageSize = systemPageSize()` with
`RELEASE_ASSERT_WITH_MESSAGE(s_pageSize <= CeilingOnPageSize, "CeilingOnPageSize is too low, raise it in
PageBlock.h!")`. The block therefore *permits* a 16 KB page; it does not force one. The console's actual
page size is **not measurable from the drop** — but the define exists only because the port needs more than
4 KB, and three independent places in the port are written for 16 KB (`PageBlock`'s ceiling, libpas's
`PAS_GRANULE_DEFAULT_SHIFT 14` for `PAS_PLATFORM(PLAYSTATION)`, `pas_page_malloc.c`'s "We don't need to call
madvise to map page"). Verdict `dev/mem`, **console value unmeasured**. Its reach is narrower than it looks:
`vmPageSize()` feeds commit rounding and `isPageAligned`, but **not** bmalloc's small-heap geometry, which is
compile-time (§8.3).

### 3.3 Crash mode differs: `CRASH()` is SIGTRAP on the console, `abort()` on the oracle

`Assertions.h:271` selects the Darwin-style body for PS:

```
#if defined(NDEBUG) && (OS(DARWIN) || PLATFORM(PLAYSTATION))
    #define CRASH() do { WTFBreakpointTrap(); __builtin_unreachable(); } while (0)
#elif !ENABLE(DEVELOPER_MODE) && !OS(DARWIN)
    #define CRASH() std::abort()
```

`Assertions.cpp:342` does the same for `WTFCrash()` (PS/Darwin NDEBUG: `CRASH()`; every other NDEBUG port:
`WTFReportBacktrace()` then `*(int*)0xbbadbeef = 0`), `Assertions.cpp:652` compiles the register-dumping
`WTFCrashWithInfoImpl` for PS, and `Assertions.h:812` makes `CRASH_WITH_INFO` call
`callAssertReportFunction(__FILE__, __LINE__)` first. **Console-only, unmeasured**, and operationally
important in the other direction: docs/89's aborts and every `RELEASE_ASSERT` on 14.10 will arrive as
SIGTRAP with register dumps, not as a 0xbbadbeef fault.

The remaining WTF `dev` rows are behaviour-only and quoted in the verdict table: `DateMath.h:112`
(`maxUnixTime` 12/31/**2099** vs 12/31/2037), `DateMath.cpp:180` (the 2038 workaround), `PlatformEnable.h:891`
(`ENABLE_OPENTYPE_MATH` 1 on PS — **inert**, `OptionsPlayStation.cmake:268` sets `ENABLE_MATHML OFF`),
`PlatformHave.h:387` (`HAVE_MEMMEM` withheld), `ThreadingPOSIX.cpp:572` (out-of-line `Mutex`).

### 3.4 The memory-pressure handler installs and never fires

`Source/WTF/wtf/unix/MemoryPressureHandlerUnix.cpp:80-87` is the whole of `install()`:

```
void MemoryPressureHandler::install()
{
    if (m_installed || m_holdOffTimer.isActive())
        return;

    m_installed = true;
}
```

No signal, no poll, no timer — and the Linux `MemoryPressureMonitor` is a different file that this port does
not compile. So on the console `WTF::MemoryPressureHandler` has no producer: JSC's `didReceiveMemoryWarning`
release path, the page cache and the decoded-image eviction that hang off it never run. **Console-only,
unmeasured**; on the oracle the same `install()` is used only when the GLib/Linux monitor is absent, so the
oracle cannot show the console end either.

### 3.5 A compile-time fact: the PS build must define `__linux__` or `__FreeBSD__`

`MemoryPressureHandlerUnix.cpp:129-132` cannot compile for any other OS:

```
#else
#error "Missing a platform specific way of determining the memory usage"
#endif
```

and the file *is* in the PS source list. `PlatformOS.h` derives `OS(LINUX)` from `__linux__` and
`OS(FREEBSD)` from `__FreeBSD__`/`__FreeBSD_kernel__` with no PS special case, so **one of those macros is
defined by Sony's compiler**. The API set the port uses points at FreeBSD (`<pthread_np.h>` included
unconditionally under `BPLATFORM(PLAYSTATION)`, `pthread_setname_np(name)`, `pthread_get_name_np`,
`pthread_mutex_setname_np`, `getenv_np`, `clock_gettime_np(CLOCK_MONOTONIC_FAST)`), while `PlatformHave.h`
withholds `HAVE_MEMMEM` from PS explicitly and `OptionsPlayStation.cmake:663` renames `gmtime_r`, i.e. the
libc is neither glibc nor stock FreeBSD. **Inference, not measurement: `OS(FREEBSD)`.** Two consequences:

- docs/106 §6.2's conclusion (the config record is writable on 14.10) **stands**, and it stands twice over:
  `WTFConfig.cpp:150`'s protect arm is `#elif OS(LINUX)` **and** `VM.cpp:395-400` skips the freeze —

  ```
  #if PLATFORM(PLAYSTATION)
      // FIXME: <PLAYSTATION> REMOVE disableFreezingForTesting() call after RNPS no longer needs this behavior
      Config::disableFreezingForTesting();
  #endif
      if (!g_jscConfig.disabledFreezingForTesting)
          Config::permanentlyFreeze();
  ```

- Three shared-code branches that docs/106 treated as oracle-only are decided by that macro, and the
  `#if OS(LINUX)` ones are the ones the oracle takes: `WTFConfig.cpp:150` (protect), `processMemoryUsage()`
  (`/proc` vs `sysctl`), `PlatformHave.h`'s `HAVE_MEMMEM`. If the console is `OS(FREEBSD)` the oracle and the
  console disagree on all three; if it is `OS(LINUX)` they agree on the first. **The drop cannot settle it**;
  what it settles is that the assumption "the port is plain `OS(UNIX)`" that docs/106 §6.2 used as its first
  reason is **wrong** — the port is neither plain UNIX nor Linux-only.

## 4. Source/bmalloc (36 blocks): the release allocator, and why libpas does not exist here

### 4.1 libpas is off, by build flag, and every libpas block is dead

`BPlatform.h:341` *defaults* `BENABLE_LIBPAS 1` for `BPLATFORM(PLAYSTATION)`, but
`OptionsPlayStation.cmake:284,286` define `ENABLE_LIBPAS … OFF` and `:741-742` add `-DBENABLE_LIBPAS=0`, which
wins. So the 14 `PAS_PLATFORM(PLAYSTATION)` blocks in `Source/bmalloc/libpas/**` are **unreachable**, and the
running allocator is classic bmalloc (`bmalloc/bmalloc.cpp`). Two of those blocks would have been the only
interesting ones (`pas_page_malloc.c` skips `madvise(MADV_DODUMP)`; `pas_compact_heap_reservation.c` reserves
through Sony's `memory_extra::vss`), and both are moot. Verdict `flag`, recorded so nobody re-derives it.

### 4.2 The one PS-only purge path is compiled out by its own flag

`BPlatform.h:358-362`:

```
#if BPLATFORM(PLAYSTATION)
#define BUSE_PTHREAD_MUTEX 1
#define BUSE_RELEASE_LARGE_FREE 0
#endif
```

`Heap::releaseLargeFree` → `m_largeFree.purge()` (`Heap.cpp:138-142`) is a 51-line `LargeMap::purge()`
(`LargeMap.cpp:91`) that decommits free large ranges, and its **only** call site is
`bmalloc.cpp:151` — `#if BPLATFORM(PLAYSTATION) && BUSE(RELEASE_LARGE_FREE)`, which is false. So the console
keeps freed large ranges mapped where a `BUSE_RELEASE_LARGE_FREE 1` build would return them to the OS. A
lifetime addition that this build does not have; `add` with the flag quoted.

### 4.3 bmalloc's assertions stay live and crash differently

`BAssert.h:35` has the same shape as WTF's `CRASH()`: in NDEBUG on PS `BCRASH()` is `BBreakpointTrap()`
(`brk #0xc471` on ARM64, `int3` on x86) where every other non-Darwin NDEBUG port writes `0xbbadbeef`. Since
`BASSERT_IMPL` is unconditional, bmalloc's assertions are live in a release build on both platforms — only the
signal differs. `dev/behav`, console-only.

### 4.4 The oracle runs bmalloc as a *debug heap*; the console does not — this is the allocator mode raw

`Environment.cpp:110-148` ends `#elif BOS(UNIX) && !BPLATFORM(PLAYSTATION) … #else return false;`, and
`computeIsDebugHeapEnabled()` (:178-186) returns true when `isSanitizerEnabled()`. Therefore:

- **oracle** (GTK + ASAN): the `dlopen`/`dlsym("__asan_init")` path succeeds → `m_isDebugHeapEnabled = true`
  → the malloc fill every one of docs/92-94's arms had to neutralise with `max_malloc_fill_size=0`;
- **console**: the branch does not exist → false → a plain release heap unless `Malloc=` is set.

This is the cleanest statement of why an oracle heap measurement is not a console heap measurement, and it
is the row docs/93 was working around empirically. Recorded as `dev/mem`, console end unmeasured (it is the
absence of a mode).

### 4.5 `USE_ISO_MALLOC` is OFF on the console — 834 WebCore classes lose their dedicated heap

Not a block, but the allocator fact this directory's owner depends on. `OptionsPlayStation.cmake:210-211`:

```
# Don't use IsoMalloc
WEBKIT_OPTION_DEFAULT_PORT_VALUE(USE_ISO_MALLOC PRIVATE OFF)
```

and `IsoMallocInlines.h:30-36` turns every `WTF_MAKE_ISO_ALLOCATED` into `WTF_MAKE_FAST_ALLOCATED` when
`!USE(ISO_MALLOC)`. **834 headers in `Source/WebCore` declare `WTF_MAKE_ISO_ALLOCATED`** (counted:
`grep -rl WTF_MAKE_ISO_ALLOCATED Source/WebCore --include=*.h | wc -l` = 834). On the oracle each of those
classes lives in its own `IsoHeap`; on the console every one of them is in the general bmalloc heap, next to
attacker-controlled strings. `CSSFontFace` is unaffected either way — it is
`WTF_MAKE_FAST_ALLOCATED_WITH_HEAP_IDENTIFIER` (`css/CSSFontFace.h:61`), which is why docs/65's slot has
always behaved as a plain `fastFree` chunk.

Also worth recording from the same file: `ENABLE_JIT`, `ENABLE_FTL_JIT` and `ENABLE_DFG_JIT` are **OFF**
(`OptionsPlayStation.cmake:205-208`) — the console is LLInt-only, so there is no JIT code space at all.
That is consistent with docs/106's `isLLIntPC()` row and removes JIT spraying from any console chain.

### 4.6 One row per bmalloc block: does it change a bound, a container or a lifetime?

The action asked for this question explicitly. `—` means the block changes none of the three (tag values,
thread names, includes, calls, log hooks); `dead` means it is compiled out in the shipping build.

| site | spelling | bound | container | lifetime | verdict |
|---|---|---|---|---|---|
| `BAssert.h:35` | `BPLATFORM` | — | — | — | `dev/behav`: crash mode SIGTRAP vs 0xbbadbeef |
| `BPlatform.h:341` | `BPLATFORM` | — | — | — | `flag`: `BENABLE_LIBPAS` default, overridden to 0 |
| `BPlatform.h:360` | `BPLATFORM` | — | — | yes | `dev/flag`: `BUSE_RELEASE_LARGE_FREE 0` removes the purge |
| `BVMTags.h:30`, `:64` | `BPLATFORM` | — | — | — | `add`: include, `VM_TYPE_USER1..4` tags |
| `Environment.cpp:130` | `BPLATFORM` (excluded arm) | — | — | mode | `dev/mem`: no sanitizer ⇒ no debug heap on console |
| `Heap.cpp:138`, `Heap.h:91` | `BPLATFORM` | — | — | dead | `add`: `releaseLargeFree` → `purge()` |
| `LargeMap.cpp:91`, `LargeMap.h:49` | `BPLATFORM` | — | — | dead | `add`: 51-line decommit of free large ranges |
| `bmalloc.cpp:151` | `BPLATFORM` + `BUSE` | — | — | dead | `add`: the only caller, `BUSE(RELEASE_LARGE_FREE)` false |
| `Mutex.h:36`, `:101` | `BPLATFORM` | — | — | — | `add`: `pthread_np.h`, mutex name |
| `Scavenger.cpp:43`, `:386` | `BPLATFORM` | — | — | — | `add`: include, one-argument `pthread_setname_np` |
| `VMAllocate.h:135,154,174,233,254` | `BPLATFORM` + `BENABLE(MAT)` | — | — | dead | `add`: MAT virtual-memory logging, `ENABLE_MAT` OFF |
| `pas_compact_heap_reservation.c:35,46,63,97` | `PAS_PLATFORM` | — | — | dead | `add`: `vss` reservation + explicit commit loop |
| `pas_page_malloc.c:57,215` | `PAS_PLATFORM` | — | — | dead | `add`: `PAS_VM_TAG`, and no `madvise(MADV_DODUMP)` |
| `pas_config.h:41,57,102` | `PAS_PLATFORM` | dead | — | dead | `add`: asserts off, 256 granules, no spinlocks |
| `pas_internal_config.h:52` | `PAS_PLATFORM` | dead | — | dead | `add`: granule shift 14 (16 KB) |
| `pas_lock.h:195` | `PAS_PLATFORM` | — | — | dead | `add`: pthread mutex implementation |
| `pas_monotonic_time.c:83` | `PAS_PLATFORM` | — | — | dead | `add`: `clock_gettime_np(CLOCK_MONOTONIC_FAST)` |
| `pas_scavenger.c:175`, `pas_thread_local_cache.c:50,215` | `PAS_PLATFORM` | — | — | dead | `add`: thread name, includes |
| `pas_utils.h:69` | `PAS_PLATFORM` | — | — | — | `add`: `PAS_ALIGNOF` |

**No bmalloc block changes a bound or a container.** The page size enters bmalloc only through shared code
(`vmPageSize()` in `VMAllocate.h`, `Gigacage`, `DebugHeap`, `Vector.h:77`), and §8.3 shows the small-heap
geometry does not depend on it at all. The only lifetime changes are the purge path — which this build
disables — and the debug-heap mode, which is an oracle-side difference. That is a cleaner result than the
WebCore pass: **the console's allocator is classic bmalloc with fewer features enabled, not a different
allocator.**

## 5. Source/WebKit (117 blocks): four rows that change what the WebProcess does

### 5.1 The viewport meta tag is ignored, and the fixed visible content rect is built at scale −1

`WebProcess/WebPage/WebPage.cpp:2189-2202` (`sendViewportAttributesChanged`):

```
#if PLATFORM(PLAYSTATION)
    // [Bug 68264]
    // We don't use the layout size specified with a viewport meta tag.
    attr.layoutSize = m_viewSize;
    attr.initialScale = -1;

    contentFixedSize.scale(1 / attr.initialScale);
    view->setFixedVisibleContentRect(IntRect(contentFixedOrigin, roundedIntSize(contentFixedSize)));
#else
    contentFixedSize.scale(1 / attr.initialScale);
    view->setFixedVisibleContentRect(…);
    attr.initialScale = m_page->viewportArguments().zoom;
#endif
```

Two consequences, both page-observable in principle:

1. `<meta name="viewport">` is not honoured: layout size is the view size and `initialScale` stays −1.
2. `contentFixedSize` is the view size **multiplied by −1** (`FloatSize::scale`, `FloatSize.h:90-94`), so
   `setFixedVisibleContentRect` receives a **negative-size** `IntRect`. `LocalFrameView.cpp:2798-2805` then
   compares `visibleContentRect.size() != fixedVisibleContentRect().size()` on every viewport change and,
   because the stored rect has negative width/height, takes the "size changed" branch every time
   (`setViewportConstrainedObjectsNeedLayout()`), while `ScrollView::visibleContentRect()` falls back to the
   normal rect because `m_fixedVisibleContentRect.isEmpty()` (`ScrollView.cpp:337-338`). Net effect: a
   layout invalidation per viewport change plus a fixed rect whose size is negative — **not** a memory
   consequence, because the only direct reader, `RenderElement::canDestroyDecodedData`, is dead (§8.1).
   `dev/behav`, console-only.

### 5.2 COOP can never switch browsing-context group

`NetworkProcess/NetworkResourceLoader.cpp:985-990` returns `StayInGroup` unconditionally (the shared helper
`toBrowsingContextGroupSwitchDecision` is `#if !PLATFORM(PLAYSTATION)` and not compiled). With one
WebProcess by construction (the comment cites `webkit.org/b/263185`, single-WebProcess mode), the console has
no cross-origin process isolation to lose — but the *source* decision is gone, so a COOP-triggered group
switch cannot happen on 14.10 at all. `dev/sec`, console-only.

### 5.3 IPC: a monitor thread, a hand-written partial-write loop, and a close-before-stop ordering

`Platform/IPC/unix/ConnectionUnix.cpp` replaces three things:

- `platformOpen` (:341-380) spawns `Thread::create("SocketMonitor", …)` which loops
  `while ((fd = m_socketDescriptor) != -1) { select(maxFd+1, &fdSet, 0, 0, 0); if (FD_ISSET(fd)) readyReadHandler(); }`
  — `readyReadHandler()` runs **on that thread**, not on `m_connectionQueue`, where every other port
  dispatches it. `Thread::detach()` (`ThreadingPOSIX.cpp:379-388`) is the safe pattern (the thread holds a
  self-reference until it exits), so the capture's `RefPtr<Connection>` cannot go stale;
- `sendOutgoingMessage` (:493-556) walks `msg_iov` after a partial `sendmsg` and `poll(POLLOUT)`s on
  `EAGAIN`/`EWOULDBLOCK`/**`EMSGSIZE`** (the Sony comment). The GLib write-monitor path is not built;
- `platformInvalidate` (:109-135) closes the descriptor **first** (`:115-116`), then detaches the monitor,
  then sets `m_socketDescriptor = -1` (`:134`). Between the close and `:134` the monitor thread's loop still
  sees the old fd, so its `select()` returns −1 (EBADF) in a hot loop — and if the descriptor number is reused
  by another `open()` in the same process, `FD_ISSET` can fire for an unrelated file and
  `readyReadHandler()` will read *that* fd's bytes as IPC. **Console-only, unmeasured, and page-reachable only
  in so far as page traffic keeps the connection busy**; recorded as `dev/mem` with the ordering above rather
  than as a claim.

### 5.4 A failed provisional load replaces the frame with an engine error document

`WebProcess/WebCoreSupport/WebLocalFrameLoaderClient.cpp:682-712` builds an HTML error page
(`ERROR: 0x…`, `SSLError: 0x…`, `localizedDescription()`, `tlsVerificationErrorDescription()`) into a
`SharedBuffer` and calls `m_frame->coreLocalFrame()->loader().load(FrameLoadRequest(…, substituteData))`
**inside** `dispatchDidFailProvisionalLoad`. The document is loaded at the failing URL
(`SubstituteData …, failingURL, …, SessionHistoryVisibility::Visible`), i.e. it inherits that URL's origin.
The re-entrancy is guarded by the caller, which is worth writing down because it is docs/65's shape:
`FrameLoader::checkLoadCompleteForThisFrame` holds a `RefPtr` protector and has an explicit
"another load has been started by the delegate callback" branch (`FrameLoader.cpp:2649-2652`), and the only
post-callback use of `provisionalDocumentLoader` in `dispatchDidFailProvisionalLoad` is under
`ENABLE(CONTENT_FILTERING)` (`FrameLoader.cpp:2567-2570`), which is off. Verdict: `dev/behav`, no primitive.

### 5.5 The rest

`NetworkCacheStorage.cpp:878` returns `false` from `shouldStoreBodyAsBlob()` — every HTTP cache body is
written inline in the record instead of as a blob, so the record file is the container shared code uses for
small bodies only (`dev/mem`, disk layout). `NetworkDataTaskCurl.cpp:185` rewrites a response Sony's
`WebSecurity` blocks into a **302 to `WebSecurity::getBlockPageUrl()`** (`dev/sec`). `CacheModel.cpp:141`
fixes the disk cache at 128 MB. `WKPage.cpp:340` adds `ReloadOption::ExpiredOnly` to every reload.
`WebPage.cpp:4582` lets a PS page run with accelerated compositing off, where shared code forces it on.
`DrawingAreaProxyCoordinatedGraphics.cpp:200`, `WebPageProxy.cpp:8486/8542`, `WebProcessProxy.cpp:1945`,
`WebPage.cpp:3383`, `NetworkProcessProxy.cpp:267` and `ProcessLauncher.cpp:56` are the input/editor-state and
process-launch rows, all quoted in the verdict table. The 22 `WebsiteDataStore` path rows are directory
names, and the six `NativeWebKeyboardEvent`/`WebKeyboardEvent` blocks are the `WKKeyboardEvent` type.

## 6. The taxonomy reconciles with the raw line counts

| measure | WTF | bmalloc | WebKit | total |
|---|---|---|---|---|
| `grep -rn` `PLATFORM(PLAYSTATION)` | 32 | 39 (22 of them the `BPLATFORM` spelling) | 118 | **189** |
| blocks extracted | 30 | 36 | 117 | **183** |
| PS condition lines | 30 | 37 | 117 | 184 |
| blocks with a non-PS `#else`/`#elif` | 12 | 15 | 26 | **53** |

The gap between 189 raw lines and 183 blocks is the six `#endif`/trailer comments and the one conditional
that carries two PS conditions (bmalloc: 37 condition lines in 36 blocks).

## 7. The blind spot: files that are PS-only by source list

`tools/ps-file-list-sweep.py` answers docs/106 §7 the way it asked to be answered — by file, not by `#if`:

| directory | entries listed | `.cpp`/`.mm` | shared elsewhere | PS-only | displaces a `Sources.txt` definition |
|---|---|---|---|---|---|
| `Source/WebCore` | 68 | 63 (**18 guarded, 45 unguarded**) | 24 | **39** | 4 |
| `Source/WebKit` | 154 | 125 | 42 | **83** | 4 |
| `Source/WTF/wtf` | 15 | 14 | 0 | **14** | 0 |

**One correction to docs/106 §7 first:** it says 64 `.cpp/.mm`, 18 guarded, 46 unguarded. The list really has
**63**, because one `.cpp` is commented out in the CMake — `Source/WebCore/PlatformPlayStation.cmake:36`
reads `# editing/libwpe/EditorLibWPE.cpp`, and a `grep -c "\.cpp"` counts the comment. So 18 guarded + 45
unguarded = 63, and the blind spot is 45 files, not 46.

**The 39 WebCore PS-only files**, by directory: `accessibility/playstation/` ×2,
`editing/playstation/`, `page/playstation/` ×6, `page/scrolling/nicosia/` ×10 (the Nicosia scrolling tree,
shared with WPE), `platform/ScrollAnimation{Kinetic,Smooth}.cpp` (shared files re-listed),
`platform/gamepad/libwpe/` ×3, `platform/generic/Keyed{En,De}coderGeneric.cpp`,
`platform/graphics/{egl,libwpe,playstation}/` ×7, `platform/libwpe/` ×4, `platform/network/playstation/` ×2,
`platform/playstation/` ×6, `platform/text/{Hyphenation,LocaleICU}.cpp`, `platform/unix/LoggingUnix.cpp`,
`rendering/RenderThemePlayStation.cpp`. Of those, **only 4 supply a definition whose shared copy is compiled
by `Sources.txt`**, and every one of them is a docs/106 `stub` or an overload, not a new deviation:

- `platform/playstation/WidgetPlayStation.cpp` — `Widget::{setFrameRect,paint,setFocus,setCursor,show,hide}`,
  the docs/106 `Widget.cpp:277` stub;
- `page/playstation/EventHandlerPlayStation.cpp` — `EventHandler::tabsToAllFormControls`, the docs/106
  `EventHandler.cpp:5102` stub;
- `platform/graphics/playstation/eme/CDMFactoryPlayStation.cpp` — `CDMFactory::platformRegisterFactories`,
  the docs/106 `CDMFactory.cpp:64` stub;
- `editing/playstation/EditorPlayStation.cpp` — not a displacement at all: `Editor::confirmComposition(const
  String&, unsigned caretIndexInText)` is a **PS-only overload** (the shared `Editor::confirmComposition(text)`
  is untouched). Its body does
  `unsigned actualCaretIndex = (baseOffset - text.length() + caretIndexInText);` — unsigned arithmetic that
  wraps if `text.length() > baseOffset + caretIndexInText`. Callers are UI-only
  (`WebPage::confirmComposition` from `WebPageProxy::confirmComposition`, `WebPagePlayStation.cpp:459-465`),
  never page script, so it is recorded as a console-only integer-underflow candidate with its exact
  condition, not as a primitive.

**The 83 WebKit PS-only files** are the port itself: `UIProcess/neko/` (PageClientImpl 74 definitions,
PlayStationWebView 44, WebPageProxyPlayStation 23, WebProcessPoolPlayStation, WebPreferencesPlayStation,
WebPasteboardProxy, AutomationClient, popup menus, cookie store), `WebProcess/WebPage/neko/` (WebPagePlayStation
23, AcceleratedSurfacePlayStation 11), `WebProcess/playstation/WebProcessPlayStation.cpp`,
`Shared/neko/` (AuxiliaryProcessMain, WebEventFactory, WebAccessibilityObject{Data}, AssertReportPlayStation,
WebPunchHole), `NetworkProcess/curl/`, `UIProcess/WebsiteData/curl|playstation/`, `Platform/unix/ModuleUnix.cpp`,
`GPUProcess/**`. Four of them supply a definition that `Sources.txt` also compiles, and all four are the port
abstraction the CMake selects by directory: `AuxiliaryProcess::platformInitialize`,
`WebPasteboardProxy::readStringFromPasteboard`, `WebPreferences::platformInitializeStore` (the docs/106
`WebPreferences.cpp:243` stub) and `RemoteGraphicsContextGL::create` (`USE(GRAPHICS_LAYER_WC)`, and WebGL is
OFF).

**The 14 WTF files** are `generic/{MainThread,MemoryFootprint,RunLoop,WorkQueue}Generic.cpp`,
`playstation/{FileSystem,Language,OSAllocator,UniStdExtras}PlayStation.cpp`,
`posix/{CPUTimePOSIX,FileSystemPOSIX,ThreadingPOSIX}.cpp`,
`text/unix/TextBreakIteratorInternalICUUnix.cpp`, `unix/{LoggingUnix,MemoryPressureHandlerUnix}.cpp`. Two are
worth naming beyond §3: **`playstation/OSAllocatorPlayStation.cpp`** replaces every `mmap`/`mprotect` with
Sony's `memory_extra::vss` and **drops the guard-page request** (`ASSERT_UNUSED(includesGuardPages,
!includesGuardPages)` in `tryReserve*`, `reserve*` and `tryReserveUncommittedAligned`), and
`hintMemoryNotNeededSoon` is an empty body where shared code calls `madvise(MADV_DONTNEED)`. That is a bound
shared code has (guard pages around JSC/Gigacage reservations) that the console does not — console-only,
unmeasured, and it matters for criterion 2 because a guard page is what turns an out-of-bounds write into a
fault instead of silent corruption.

## 8. What this changes

1. **docs/106 §6.4's `canDestroyDecodedData` candidate is dead, and the reason is measurable by reading.**
   The PS override only differs inside `if (frameView.paintsEntireContents())`
   (`RenderElement.cpp:1475-1489`), and *nothing in the WebProcess ever sets that flag*:
   `grep -rn shouldPaintEntireContents Source/` finds `ChromeClient.h:363`'s `return false`, the
   `LocalFrameView.cpp:343` caller, and one **WebKitLegacy/mac** override that this port does not build. So on
   14.10 `canDestroyDecodedData()` is `!isVisibleInViewport()` — byte for byte the shared body. §6.4 should
   be read as *dead by construction*, not as a console-only candidate. (The negative-size fixed rect of §5.1
   would have made it destroy **everything** had the flag been reachable; it is not.)
2. **The allocator layer is where the console and the oracle differ, and it is now enumerated**: classic
   bmalloc (not libpas), `USE_ISO_MALLOC 0` (834 WebCore classes out of their dedicated heaps), a 16 KB page
   ceiling (and therefore a plausible 16 KB `pageSize()` vs the oracle's 4 KB), a 64 KB default thread stack,
   a debug heap on the oracle and a release heap on the console, no memory-pressure events, and no JIT.
   Every one of those is a bound or a lifetime that shared code also has and the oracle does not share.
3. **The consequence for the live primitives is a *negative* and it is worth as much as a positive.** I
   expected page geometry to differ; it does not. bmalloc's small allocator is built on compile-time
   constants — `smallLineSize = 256`, `smallPageSize = 4 * kB` ⇒ 16 lines per page, `chunkSize = 1 * MB`
   (`bmalloc/Sizes.h:51-54`) — none of which reads `vmPageSize()`. So the 192-byte chunk (class 192, line
   192) and docs/94's 32-byte element have **the same page geometry on the console as on the oracle**, and
   the measured adjacency and reuse order transfer. `vmPageSize()` enters bmalloc only at the VM layer
   (`vmAllocatePhysicalPagesSloppy`'s commit rounding, `Gigacage` reservation size, `DebugHeap`'s page
   mapping, and `bmalloc::Vector<T>::initialCapacity() = vmPageSize() / sizeof(T)`, `Vector.h:77`), i.e. in
   *commit* granularity, not in the layout of the freed slot. docs/65 §4.2 and docs/94's offsets stand
   unchanged; what does not transfer is the ~4× difference in how many small pages a 1 MB chunk's commits
   cover.
4. **The "console-only" label now has a second meaning**: the port is not plain `OS(UNIX)` (§3.5), so the
   `#if OS(LINUX)` branches docs/106 treated as oracle-only may or may not be the console's, and the drop
   cannot settle which. Recorded as a caveat on every such row instead of a fact.

## 9. Limits

- **Every `dev` row here is a source classification.** PS-only code cannot run on the GTK oracle, so §3, §4
  and §5 have no oracle arm at all — they are the explicit "console-only, unmeasured" the action asked for,
  with the line quoted so a later run can falsify one line rather than re-read a directory. The one row where
  the oracle shows the opposite end (§5.1's shared branch) is the code as written, not a run.
- The console's page size, thread stack use, and `OS(FREEBSD)`-vs-`OS(LINUX)` are **inferences from the
  drop**, not measurements; §3.2, §3.5 and §8.3 say so where they are used.
- The file-list sweep matches definitions by `Class::method` name, so it cannot see a definition supplied by
  a macro or a template, and it drops CMake entries written with a variable (`1` row in WebKit). Its
  "displaces" test is deliberately narrow: a definition in a file that `Sources.txt` compiles.
- No page was run and no console access was used, so nothing here changes a *measured* verdict; it changes
  which of them are structurally reachable.

## 10. Artefacts

- `tools/platform-playstation-sweep.py` — now takes `--subdirs` and matches `B?PLATFORM(PLAYSTATION)`
  (the docs/106 regression still gives 186/186/111/38).
- `tools/ps-outer-classify.py` — verdict for every non-`add` block; `data/ps-branches/verdicts-outer.json`
  (183 rows), `data/ps-branches/blocks-outer.json`.
- `tools/ps-file-list-sweep.py` — the source-list half; `data/ps-branches/files-{WebCore,WebKit,WTF}.json`.
