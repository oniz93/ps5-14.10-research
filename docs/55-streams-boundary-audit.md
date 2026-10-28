# Streams boundary audit (WebKit-1400 drop)

First pass of the targeted reading programme: the Streams module, chosen because our only live console bug came
from exactly this boundary (an unchecked downcast on an IDL conversion) and because the code is new, dense, and
fully reachable on this port (ReadableStream, WritableStream, TransformStream are all present; no JIT needed).

## Why this module and this method

JIT is off, so the entire speculative/IC bug literature is inapplicable. What remains reachable is four classes:

1. re-entrancy — script runs mid-operation and frees/updates something C++ still holds;
2. lifetime — `Ref` vs `reference_wrapper`, missing `protect()`;
3. index/size arithmetic — unsigned underflow producing an OOB subvector;
4. unchecked downcast after an IDL conversion.

The triggering insight came from calibrating the drop against the console: **the drop contains the
TransformStream null check (TransformStream.cpp:118-126) and the console does not** (it crashed on 14.10). So
Sony's published tree is *ahead* of the shipping firmware, "this fix is in the drop" is not evidence of console
behaviour, and backport archaeology is dead as a filter. The only sound direction is bugs that are still broken
in the newest tree.

## The 19 sites that matter

Mechanical filter: every WebCore site that calls into a JS builtin and consumes the result —
`grep -rn "builtinFunctions()\..*PrivateName()" Source/WebCore --include=*.cpp` → **19 sites**:

| file | sites |
|---|---|
| `bindings/js/InternalReadableStream.cpp` | 9 |
| `bindings/js/InternalWritableStream.cpp` | 6 |
| `bindings/js/ReadableStreamDefaultController.cpp` | 3 |
| `Modules/streams/TransformStream.cpp` | 1 (the known bug) |

`Modules/streams/*.cpp` themselves are only 354 lines total and contain exactly one builtin call — so the module's
C++ surface is small and essentially closed apart from the TransformStream defect.

## The one shape worth checking, and why it is safe

Two sites convert a builtin's return value with an `ASSERT`-only guard:

```
InternalReadableStream.cpp:72  ASSERT(result.returnValue().isObject());
InternalReadableStream.cpp:73  return adoptRef(*new InternalReadableStream(globalObject, *result.returnValue().toObject(&globalObject)));
InternalWritableStream.cpp:69  ASSERT(result.returnValue().isObject());
InternalWritableStream.cpp:70  return adoptRef(*new InternalWritableStream(globalObject, *result.returnValue().toObject(&globalObject)));
```

`ASSERT` compiles out in release, and `toObject` returns null on failure, so a non-object return would be a null
dereference. That is the TransformStream shape exactly. Both were cleared by reading the producer:

* `createInternalReadableStreamFromUnderlyingSource` (ReadableStreamInternals.js:29) — one `return stream` at the
  end, every other exit is `@throwTypeError`/`@throwRangeError`. Cannot return a non-object.
* `createInternalWritableStreamFromUnderlyingSink` (WritableStreamInternals.js:62) — same shape, single
  `return stream`.

So both conversions are unreachable with a non-object, and `result.hasException()` is already checked at both
call sites (InternalReadableStream.cpp:69, InternalWritableStream.cpp:66).

## Re-entrancy points noted (no bug, but the useful places to look again)

Construction runs attacker getters while internal state exists:

* `underlyingSource.type` is read at ReadableStreamInternals.js:62 — a getter the attacker controls.
* `"start" in underlyingSink` at WritableStreamInternals.js:84 invokes a Proxy `has` trap; line 85 then reads
  `underlyingSink.start`, invoking a getter.
* `@setupReadableStreamDefaultController` receives `underlyingSource.start/pull/cancel` **by property read at the
  call site**, so three getters can run during controller setup.

In every case the `stream` object is not yet reachable from the getters, which is what keeps these from turning
into the canvas-style pattern (a wrapper surviving a free). That property is the thing to re-check against any
future change in this file, not the getters themselves.

## Verdict

The Streams boundary is clean in the current tree. The only defect in it is the TransformStream null check, which
is already fixed upstream and live on our console only because 14.10 predates the fix — i.e. we have already
extracted everything this surface has to give.

## Next surfaces, ranked by expected yield on this port

1. **Resizable ArrayBuffer + typed-array iteration** — enabled here while most other embedders assume SAB; the
   resize-during-callback pattern is the same TOCTOU class as the fixed `TypedArray.from` bug and is JS-only.
2. **Canvas 2D image paths** — `createImageBitmap`, `putImageData` dimension mismatches, filters/blur: attacker
   controls both dimensions and buffer sizes, and we already know this subsystem is not IsoHeap-protected
   end-to-end.
3. **FontFace / CSS font loading** — the one CSS-reachable parser; we already hold an ASAN-confirmed OOB read
   there, so the surrounding code has demonstrated reach.
4. **structuredClone / SerializedScriptValue** — many conversion paths, and the known race is dead only because
   SAB is absent, not because the code is clean.
