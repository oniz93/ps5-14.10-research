# A local copy of the shipped JavaScriptCore

Built from Sony's own 14.x source drop, interpreter-only, under AddressSanitizer. This
is the instrument the rest of the hunt depends on: the console can only tell you "it
crashed"; this tells you *where*.

## Result

```
JavaScriptCore is now built (05m:47s)
out/sony/full/WebKit-1400/WebKit-1400/WebKitBuild/Debug/bin/jsc
```

- `jsc -e 'print(1+1)'` → `2`
- ASAN linked: `@rpath/libclang_rt.asan_osx_dynamic.dylib`
- `jsc --help` lists **no** `useJIT` / `useDFGJIT` / `useFTLJIT` options — the optimising
  tiers are compiled out, exactly like the console (oracle: ratio 1.14, JIT-OFF)
- control run over 12 `JSTests` (`regexp-*`, `structured-clone*`): 11 pass, 1 harness-only
  failure, **0 crashes**

## Build it

```bash
bash tools/fw1400/build_jsc_asan.sh 4      # -j4 keeps the machine usable
tail -f out/jsc-build.log
```

Two things had to be fixed to make a 2023-era tree build with a 2026 toolchain:

| problem | fix |
|---|---|
| CMake 4.4 rejects `if()` with unquoted lists in `WebKitMacros.cmake` | pin CMake 3.27.9 (`out/tools/...`), script puts it first on `PATH` |
| Xcode 27's clang makes `-Winvalid-offsetof` an error inside `WTF/Vector.h` | flags via `CFLAGS`/`CXXFLAGS` with `-Wno-error` (build-jsc splits `--cmakeargs` on spaces, so several flags cannot go that way) |

Also note: the zip loses the executable bit on `Tools/Scripts/*`, so `chmod +x` first.

## Using it

```bash
JSC=out/sony/full/WebKit-1400/WebKit-1400/WebKitBuild/Debug/bin/jsc
ASAN_OPTIONS=detect_leaks=0 "$JSC" case.js
```

Any `AddressSanitizer` report is a real memory-safety bug in *Sony's* engine, in the same
configuration the console runs. That is the first time this project has had that.

## What to point it at

Order by what the port actually reaches (see `docs/18`): HTML and CSS parsing, Yarr
regex, `SerializedScriptValue`, the image decoders that are still unpatched (ICO, GIF,
JPEG), libxml2. Not worth the cycles: anything under `dfg/`, `ftl/`, `b3/`, `air/`,
`wasm/`, plus workers, GPU, WebGL, audio and XSLT — none of it exists at runtime.

## Caveats

- This is the *source drop*, not the retail binary: same code, different compiler and
  allocator. A bug found here still has to be confirmed on the console.
- Debug configuration changes timing, so races that need release-level scheduling may
  not reproduce.
- ASAN's allocator changes heap layout, which affects exploitability — but not whether
  the bug is real.
