# 34 - The ASAN WebKit harness: what it took to make a result mean anything

## Why this exists

Every sanitizer result so far was produced by a build that could not detect anything, or by a
harness that never executed. This document records the two failures and how each was proven, so
the next person does not repeat a sweep that proves nothing.

## The build

Final configuration (`tools/fw1400/configure-asan.sh`):

- PORT=GTK, RelWithDebInfo, `-O1 -g -DNDEBUG`, `ENABLE_SANITIZERS=address`
- JIT/DFG/FTL off (matches retail 14.10, which is interpreter-only)
- WEBGL off, MEDIA_STREAM off, WEBDRIVER/SPELLCHECK/GAMEPAD/GEOLOCATION off
- WEB_AUDIO **on** (not a preference - see below)

### `-DNDEBUG` is not optional

WebKit's RelWithDebInfo defaults carry `-DNDEBUG`. Dropping it to get better stacks sets
`ASSERT_ENABLED=1`, which compiles code that has never been built in this tree:

    SerializedScriptValue.cpp:1015  passes an undeclared inMemoryMessagePorts
    SerializedScriptValue.cpp:5028  uses DetachedImageBitmap, undefined under this feature set

The retail WebProcess is a release build, so NDEBUG is also the faithful choice. Patching those
lines instead would have meant editing the exact file where bug 278657 was proven unreachable -
corrupting the oracle to make the harness compile.

### Web Audio had to be enabled

`platform/GStreamer.cmake:128` puts both `VectorMath.cpp` and `${GSTREAMER_FFT_LIBRARIES}` inside
`if (ENABLE_WEB_AUDIO)`, but `platform/audio/gstreamer/FFTFrameGStreamer.cpp` compiles under
`ENABLE_VIDEO` and calls `VectorMath::multiplyByScalar` and the `gst_fft_*` API regardless. With
Web Audio off the link fails on both.

Hand-patching was attempted and failed: `target_sources(WebCore ...)` silently did nothing because
this tree declares that target through a macro, not `add_library` - confirmed by the file having
**zero** build edges afterwards. Enabling WEB_AUDIO is WebKit's supported path and supplies both
dependencies. The cost is an AudioContext surface the console lacks; the DOM/CSS code under test is
unaffected.

Note: removing `-DENABLE_WEB_AUDIO=OFF` from the script is not enough. CMake **caches** it, so it
stays OFF until it is set explicitly to ON.

### ANGLE does not build here

`SharedContextMutex.cpp` has `always_inline` recursion that GCC 13 rejects once ASAN instruments
the call (`inlining failed ... recursive inlining`). Fixed by `ENABLE_WEBGL=OFF`, which also matches
the console's build flags (WEBGL OFF, GPU_PROCESS OFF) and removes the ANGLE target entirely.

## The harness defects

A run only counts if an HTTP beacon for `DONE-seed<N>` appears. Exit codes cannot tell "ran to
completion" from "never loaded", and that distinction hid four separate bugs:

1. **`root` was null.** `document.getElementById('sandbox') || document.body` evaluated in `<head>`,
   where `document.body` does not exist, so the first `tick()` threw TypeError and the page idled
   until timeout. Every "clean" sweep before this was a no-op.
2. **Seed came from a `file://` query string**, which WebKit may drop, so every run could silently
   be seed 1. The runner now writes a wrapper page that sets `window.__SEED`.
3. **Errors were unobservable.** `window.onerror` now beacons the message, which is how defect 1 was
   found; `file://` scripts are opaque origins, so the page is served over HTTP to stop WebKit
   rewriting messages to "Script error."
4. **The driver recursed synchronously** (`else tick()`), growing the stack instead of yielding.
   Now it alternates a macrotask and a microtask.

Runner-side traps, both silent:

- A stale `http.server` from an earlier sweep held the beacon port and swallowed every beacon while
  its log had been deleted. The runner now reclaims the port and refuses to sweep without a live
  server.
- Python block-buffers stdout, so the "Serving HTTP" banner never flushed and the readiness check
  failed on a healthy server. Fixed with `python3 -u`.

## Two crash classes that were not bugs

- **Media aborts.** `MediaPlayerPrivateGStreamer::createAudioSink()` holds
  `RELEASE_ASSERT(audioSink)`; the container has no audio device, so any `<video>` load kills the
  process. The media op is out of scope anyway - Sony's media stack is proprietary and absent from
  the OSS drop, so its behaviour here says nothing about the console.
- **GC SEGV.** `ConservativeRoots::genericAddSpan` crashed on every run. JSC finds roots by scanning
  the raw stack, and ASAN's fake stack frames live in a region that scan treats as unmapped.
  `detect_stack_use_after_return=0` is mandatory, not tuning - WebKit's own runner sets it.

Both looked exactly like WebKit memory bugs. Neither is.

## Throughput

A 220-iteration run takes about one second; wall clock is dominated by MiniBrowser startup. Per-seed
timeout is 15s, giving roughly 4-5 seeds/min, so a 300-seed sweep is about an hour.

## What a valid sweep looks like

    preflight: ASAN runtime linked
    preflight: deliberate use-after-free detected (oracle works)
    preflight: beacon server up on 8123
    done: clean=N completed=N asan_crashes=0 ...

`completed` counts only seeds that reached `DONE`. If `completed` is 0, nothing was tested.
