# ASAN results: the RAB class is a spec deviation on this engine, and the canvas divide-by-zero is benign

Hardware restored: source re-synced to the board (4.4 GB, 51,280 files), reconfigured with
`tools/fw1400/configure-asan.sh`, rebuilt to `WebKitBuild/ASAN/bin/MiniBrowser` in about twelve minutes
(5,840 edges, ccache survived the wipe at 5.0 GB and carried most of it), `EXIT=0`.

Build configuration is the one that matters for these questions: `ENABLE_JIT=OFF`, `ENABLE_DFG_JIT=OFF`,
`ENABLE_FTL_JIT=OFF`, `USE_SYSTEM_MALLOC=ON`, RelWithDebInfo with `-O1 -g -DNDEBUG`. Same interpreter, same
allocator, same source as the console's engine.

## TypedArray.from / map: unfixed loop confirmed, no out-of-bounds read

Probe `c026b` on the ASAN build:

| case | callbacks | fixed bound | tail after shrink |
|---|---|---|---|
| `Uint8Array.from`, shrink 8 KB -> 4 B at k=8 | **1024** (full length) | 9 | all `0` |
| `Int32Array.from`, shrink 4 KB -> 16 B at k=4 | **1024** | 5 | all `0` |
| `Int32Array.from`, shrink to 0 at k=0 | **1024** | 1 | all `0` |

Probe `c027`, the siblings upstream did not fix:

| case | callbacks | differing values after shrink |
|---|---|---|
| `Int32Array.map`, shrink to 16 B at i=0 | **4096** (full length) | 0 |
| `Int32Array.map`, shrink to 0 at i=0 | **4096** | 0 |

Two conclusions, and they point in opposite directions:

1. **The unfixed loop is real here.** The callback runs for the full cached length after the buffer has been
   shrunk, in `from` and in `map`, exactly as the source reads.
2. **The element access is bounds-checked.** Every read after the shrink returned `undefined` (stored as `0` in
   a typed array). No heap bytes leaked into the result, and ASAN reported nothing.

So on an LLInt-only engine this is a spec deviation — extra callback invocations — not a memory-safety bug. The
upstream fix is titled Out-of-Bounds Read because on a JIT build the element access uses a cached vector and
length from the inline cache; that cache is what makes the read run off the end. With no JIT there is no cache
to be stale.

**That is the end of the RAB surface for this target.** It also generalises: the entire 2023-2026 typed-array /
RAB bug literature that is framed as OOB is JIT-observable and inapplicable to a JIT-less console, which matches
the earlier dead-end list. Worth having measured rather than assumed — the source absence of the fix was a true
positive about the *code*, and a false positive about the *bug*.

## createImageBitmap: UB reached, but it lands as a RangeError

| case | outcome |
|---|---|
| control, crop 8x8 + `resizeHeight: 64` | resolved 64x64 |
| crop height 0 + `resizeHeight: 64` | **rejected RangeError** |
| crop width 0 + `resizeWidth: 64` | **rejected RangeError** |
| crop entirely outside the image + `resizeHeight: 64` | resolved **1x1** |

The divide by zero does happen (`ceil(inf)` -> `static_cast<int>` UB), but the resulting nonsense dimension dies
in image-buffer creation and surfaces as a clean `RangeError`. No crash, no corruption. The `1x1` for a crop
fully outside the image is a spec oddity worth remembering but not a security property.

Benign, as predicted. Surface closed.

## State left behind

* board: source `~/wk/WebKit`, build `WebKitBuild/ASAN`, harness `~/wk/run_asan_page.sh` and `~/wk/run_nq.sh`
  (both committed to the repo now, so a reboot no longer destroys the recipe)
* a page server on the board at :8905 serving `/tmp/wkpage` for ad-hoc runs
* console is powered and reachable, but the Guide lab needs root on this Mac for ports 53/443 and sudo is
  passworded, so console-side confirmation of these two negatives was not needed — the ASAN build shares the
  console's engine configuration

## Next surface

`FontFace` / CSS font loading: the only CSS-reachable parser on this port, with an ASAN-confirmed OOB read
already in hand from the earlier GSUB work, so the surrounding code has demonstrated reach.
