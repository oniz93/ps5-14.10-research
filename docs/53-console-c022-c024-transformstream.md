# Console results: c022-c024, and one new live 14.10 bug (DoS class)

## c022 - two candidates from Sony's own recent fixes: both dead on 14.10

* **WebCrypto SPKI/PKCS8 length-byte overread** (fix `d3de21e23b`): `importKey("spki", bad, ...)` on the 25-byte
  key whose trailing length byte is 0xFF returned **DataError** - the bounds check is present on 14.10.
  The PKCS8 variant threw SyntaxError. Dead.
* **Style::commitRelations UAF via MatchResultCache** (fix `f457aa2ebe`, `:has()` + nesting): survived.
  Caveat recorded: its regression test relied on `GCController.collect()`, and the heap-churn substitute does
  not guarantee the relation target is freed, so survival here is weak evidence, not proof.

## c023 - TransformStream type confusion: LIVE on 14.10, and it kills the WebProcess

Poisoning `Array.prototype[Symbol.iterator]` and constructing a `TransformStream` makes
`createInternalTransformStream` iterate a substituted array; `convert<IDLSequence<IDLObject>>` accepts the
attacker's objects for the readable/writable slots.

Console: `c023-B-start` arrived, then nothing - no `built`, no `survived`, no `done`. The WebProcess died inside
`new TransformStream(...)`. First confirmed live memory-safety bug of this session on 14.10.

## c024 - severity: null-deref DoS, not a controllable confusion

The fix (8fd92b10) shows the pre-patch code:

```cpp
ASSERT(results.size() == 3);   // compiled out in release
... dynamicDowncast<JSReadableStream>(results[1].get())->wrapped() ...
```

`dynamicDowncast` returns null on a wrong-type object and the dereference follows immediately, so the crash is
a null deref. To confirm severity rather than assume it, c024 supplied **real** `ReadableStream`/`WritableStream`
instances in slots 1 and 2 - so that dereference cannot fail - and an arbitrary object in slot 0:

`built`, `exercised`, `read:x`, `done` - construction succeeded, the stream worked end to end, and the arbitrary
slot-0 object was never used in any dangerous way.

Conclusion: CVE-class TransformStream bug is present on 14.10 and reachable from the Guide WebView, but it is a
null-pointer dereference. It gives a repeatable WebProcess kill and nothing further; there is no object the
attacker controls being reinterpreted as a different type.

## What this run of the corpus established

Of the reachable candidates tested so far on retail 14.10:

| candidate | verdict |
|---|---|
| Canvas getContext UAF (CVE-2026-43720) | alias only - class is IsoHeap-segregated |
| WebCrypto SPKI length overread | fixed (DataError) |
| Style::commitRelations via MatchResultCache | survived (weak GC caveat) |
| ReadableStream fake-Promise pipeTo | throws TypeError - inert |
| TransformStream poisoned iterator | **LIVE - null deref DoS** |
| XMLDocumentParser startElementNs UAF | fix present in Sony's drop |
| CSSFontFace UAF | not tested - engine version in the drop already carries the Ref lifetime fix |

The corpus index (`data/test-corpus/index.json`) holds 64 memory-safety fixes with shipped html/xhtml/JS
regression tests; the ones whose API surface exists on PS5 are the remaining queue.
