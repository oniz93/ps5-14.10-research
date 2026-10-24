# Fuzzing the shipped engine: what a night of it proved

Everything below ran against **Sony's own 14.x JavaScriptCore**, built interpreter-only
(`ENABLE_JIT`/`DFG`/`FTL`/`WASM` off) under AddressSanitizer — i.e. the configuration the
console actually runs, not an upstream approximation.

## Results

| campaign | cases | sanitizer reports |
|---|---|---|
| `JSTests/stress` corpus (regression tests) | 4,022 files | 0 |
| Yarr / regex (compile + exec + split + replace + matchAll) | 100,000 | 0 |
| JS parser (`new Function`, parse-only, deep + malformed nesting) | 24,000 | 0 |
| `JSON.parse` / `stringify` (surrogates, depth 1024, numeric edges) | 30,000 | 0 |
| `Intl.*` over hostile inputs (ICU) | 30,000 | 0 |

About **184,000 generated cases plus the full stress corpus, zero reports.**

## What that does and does not mean

It does *not* mean the engine is free of bugs. These are naive generators without coverage
guidance; JSC is one of the most heavily fuzzed pieces of C++ in existence, and a night of
random generation will not out-fuzz years of Fuzzilli. A clean sweep is the expected
result, and treating it as reassurance would be the mistake.

What it does establish:

1. **The instrument works.** ASAN is live, the binary aborts on error, abnormal
   termination is counted as a finding, and batches are bisected to a single case. When
   something does trip, it will be reported with a reproducible file rather than a rumour.
2. **The engine floor is not where the bugs are.** Regex, parser, JSON and ICU all came
   back clean. That is a useful negative: it means time spent here is time not spent on
   the surface that is actually under-tested.
3. **Two fuzzer bugs were caught and fixed** — a recursive generator that blew the Python
   stack, and a JSON generator whose depth was exponential so it spent every batch
   building strings instead of parsing them. The second one produced *silent* zeros for a
   whole smoke run. Any result from a fuzzer that has not been checked for this is
   worthless, which is why both are recorded rather than quietly fixed.

## Where the remaining surface is

`docs/18` lists what the console can reach. Subtract everything JavaScriptCore, and what
is left is WebCore: DOM and HTML parsing, CSS parsing, image decoders (ICO/GIF/JPEG —
BMP is patched), `SerializedScriptValue`, `EventTarget` dispatch, custom elements,
`fetch`/XHR state machines, libxml2.

That is also where Sony's own backport list concentrated (`docs/17`): the proxy `toThis`
fix, the custom-element reparenting guard, the Yarr lookbehind fix, the BMP RLE index fix,
the `TransformStream` type check. WebCore is where this fork has recently needed patches —
which is the best available signal about where it still does.

## Next

Build **MiniBrowser** (WebCore + WebKit) with the same flags — `ENABLE_JIT=0`, no GPU
process, ASAN — and point the fuzzers at the DOM and the decoders. That is a multi-hour
build on this machine, and the honest precondition for any further WebKit work: without
it, every candidate has to be tested by hand on the console, one at a time, which is
exactly the loop that produced three dead ends tonight.

## Files

| path | what |
|---|---|
| `tools/fw1400/jsc_stress_asan.py` | runs `JSTests` through the ASAN binary |
| `tools/fw1400/yarr_fuzz.py` | regex generator, batched, bisecting |
| `tools/fw1400/jsc_frontend_fuzz.py` | parser / JSON / Intl generators |
| `docs/20-local-engine-build.md` | how the binary is built |
| `data/jsc-stress-asan-1410.json` | corpus result |
