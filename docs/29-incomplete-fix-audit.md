# The incomplete-fix audit: a Php2Shell-shaped method for this target

CVE-2024-4577 was not a new bug. The PHP-CGI argument-injection flaw had been "fixed" in
2012; it became exploitable again because the fix validated *one* interpretation of the input
and the runtime used *another* (best-fit codepage mapping on Windows). The gap between "what
the patch checks" and "what actually reaches the sink" was the vulnerability.

That shape is directly applicable here, and it inverts the approach this repo has used so far.
Upstream-vs-Sony diffing asks: **"is this bug still present?"** — which we ran to exhaustion
(348 commits, 2 candidates, both dead on hardware). The incomplete-fix audit asks a different
question: **"is Sony's own patch sufficient?"** A patch is code written under time pressure by
someone who had one reproducer in hand. Its assumptions are the attack surface, and because
Sony's patch *removes* the pre-fix lines, no upstream-vs-Sony diff can ever surface the gap
that remains.

## The method

1. **Enumerate the patchset.** `out/diffs/summary.json` — 59 files Sony changed between the
   12.00 and 14.x drops of the *same* WebKit version. Everything here is a cherry-pick Sony
   chose to make; each one had a reason.
2. **Classify each patch.** Cosmetic (`virtual` removal, build fixes) → stop. Behavioural →
   continue. The classification matters: 3 of the 59 are purely `virtual`-keyword removal, and
   treating those as security work wastes an hour.
3. **State the patch's invariant.** Write down, in one sentence, what the patch assumes is
   true. For Sony's BMP fix: *"in RLE absolute mode, the source pixel read must be indexed
   relative to the run start, not the absolute column."*
4. **Hunt for the path that violates the assumption.** Every path that reaches the same sink
   with a different precondition is a candidate: other call sites, other overloads, other
   encodings, other entry points, release-vs-debug. This is the step where an LLM reader earns
   its keep, because it is exhaustive cross-referencing rather than insight.
5. **Ask whether the check is compiled out.** WebKit is full of `ASSERT`/`static_assert`
   guards. A fix whose invariant is only enforced in debug builds is not a fix on a shipped
   console.
6. **Only then reach for the console.** One probe, aimed at the specific violation.

## What the current patchset yielded

**Cosmetic, dismissed in minutes.** `SVGStyleElement.h`, `RenderListBox.h`, `CSSFontFace.h`,
`VideoTrack.h`, `PageOverlay.h`, `RemoteInspector.h` — removing `virtual` from overrides in
`final` classes, or a redundant virtual destructor. Notably these touch the two files behind
the two bugs we already declared dead (`SVGStyleElement`, `RenderListBox`), which rules out
"a quiet Sony fix explains why our reproducers didn't fire" — the changes there have no
behavioural content.

**BMP RLE decoder: patch is sound.** Sony re-based the absolute-mode read to `startX` and
computes `paddedNumBytes` from `numPixels`, so every read lands inside the checked window.
I tried to break it by asking what `startX` means on the non-RLE path (it is 0 at row start,
so the re-basing is a no-op there) and whether `endX > width` can be bypassed by a negative
column (it cannot: the rejection is on `startX + numPixels`, and the offset is
`(m_coord.x() - startX) * bytesPerPixel`, which stays non-negative). No gap found.

**SerializedScriptValue: hardening without enforcement.** Sony backported the object-pool
consistency checker — `canBeAddedToObjectPool(tag)` plus a tag-name table for diagnostics. But
it is used **only in `static_assert`**, i.e. it constrains each call site at compile time and
does nothing at runtime. The invariant it guards ("the serializer and deserializer push the
same tags in the same order, or one side's `m_objectPool` desynchronises and objects are
rebuilt as the wrong type") is therefore still unenforced in the shipped build. A desync
between the two sides is a type confusion with attacker-shaped data — this is the same file
and family as bug 278657, which we parked. **Ranked first for the next pass.**

**CDM session callbacks: the prolapse lesson, one layer up.** The 14.20 kernel fix for
`aio_multi_delete` is an identity/generation check to stop lookup-then-act on stale state.
Sony's WebCore CDM glue has the same defect in userspace: each operation enqueues a callback
and `licenseCallbackQueue().dequeue()` returns **by queue position**, with no request identity.
Two in-flight `generateRequest()` calls answered out of order deliver request B's result to
request A's caller. Not memory-unsafe on its own — but it is the same broken invariant, in
Sony-authored code, reachable from JavaScript.

**Media append: a contract we cannot see.** `SourceBufferPrivatePlayStation::appendInternal`
does `m_playstation->append(data->data(), data->size())` — a raw pointer into a `Ref<SharedBuffer>`
that is released when the function returns — into a backend that reports completion
asynchronously via `sourceBufferBackendAppendComplete`. That is the shape of a UAF (the backend
keeping a pointer past the caller's reference), and the size and contents are both
attacker-controlled. `PSSourceBufferBackend` is declared in Sony's proprietary SDK and is
**not in the OSS drop**, so the copy-vs-retain semantics are unknowable from source. Only the
console can settle it, and only via reachability first.

## Ranked queue

| # | target | question | how to answer |
|---|---|---|---|
| ~~1~~ | ~~`SerializedScriptValue` pool desync~~ | **closed by inspection** — see below | no interleaving point exists single-threaded |
| 1 | media append contract | does the backend retain the pointer? | console probe first (`cap-sony-surface.js`), then append/remove churn |
| 3 | CDM callback ordering | can two requests be in flight and reorder? | trigger `requestMediaKeySystemAccess` for two sessions |
| 4 | remaining behavioural patches | `YarrPattern.cpp` (+8), `XMLDocumentParserLibxml2.cpp` (+17), `TransformStream.cpp` (+14/−2), `ProxyHelpers.js` (+4/−4) | same 6-step method |

## Rank 1 closed, and why the reason matters

The serializer and deserializer push the same 14 tags, so there is no *static* asymmetry. The
only remaining desync mechanism is timing, and Sony's code is:

```cpp
if (arrayBuffer->isResizableOrGrowableShared()) {
    write(ResizableArrayBufferTag);
    uint64_t byteLength = arrayBuffer->byteLength();
    write(byteLength);
    uint64_t maxByteLength = arrayBuffer->maxByteLength().value_or(0);
    write(maxByteLength);
    write(static_cast<const uint8_t*>(arrayBuffer->data()), byteLength);   // pre-fix ordering
    return true;
}
```

`byteLength()` and `data()` are adjacent statements — **no JavaScript runs between them**, and
there is no getter, hook or finalizer in that window, so a resizable buffer cannot change size
between the length being written and the bytes being copied. The race in bug 278657 therefore
needs genuine concurrency: another thread resizing a *shared* buffer while this one copies.

The console reports `SharedArrayBuffer: false`, and this engine has no workers able to resize
one. So 278657 is dead here for a structural reason — the interleaving point does not exist —
rather than merely "the feature is switched off". That is a stronger negative than the one we
recorded earlier, and it is worth keeping the distinction: the earlier note would have sent a
future reader looking for a way to enable SAB, which would not have helped.

## Round 1 result: Sony's patchset is competent

Every behavioural patch in the 59-file set has now been examined against step 4 ("find the path
that violates the assumption"). None is a memory-safety gap.

| patch | verdict |
|---|---|
| `BMPImageReader.cpp` RLE re-basing | sound — `startX` is a no-op on the non-RLE path, a negative column cannot bypass `endX > width`, reads stay inside `paddedNumBytes` |
| `TransformStream.cpp` | properly fixed — the `ASSERT(size == 3)` became a checked return, and both `jsDynamicCast`s are null-checked before use |
| `YarrPattern.cpp` forward references | complete — the unconditional-looking append is unreachable in forward direction because the `if (parenthesisMatchDirection() == Forward) { … return; }` above it returns first. Confirmed empirically: eight candidate patterns (named backref before its group, quantified `{0}`, with a trailing lookbehind) run clean under the ASAN `jsc` built from this same tree |
| `XMLDocumentParserLibxml2.cpp` | complete for its site — post-constructor validation of parent/document before `parserAppendChild`, with a `stopParsing()` bail |
| `ProxyHelpers.js` `@toThis(receiver)` | spec-correctness hardening, not memory safety |
| `EventTarget.cpp` (`auto&` → `Ref`) | a real lifetime fix, and correctly generalised below |
| `FontPlatformDataFreeType.cpp` | build-only (`#if PLATFORM(PLAYSTATION)` around a Cairo feature macro) |
| `CSSParserImpl.cpp` nesting cap | **incomplete** — see below |

### The one incomplete fix: selector recursion is still uncapped

Sony added a nesting check to `consumeStyleRule` and hoisted `maximumRuleListNestingLevel = 128`
to file scope, closing deep *rule* nesting. `parseCSSSelector` has no depth counter, so a chain
like `:is(:is(:is(…)))` still recurses without bound and exhausts the stack. That is a
WebProcess crash, i.e. denial of service, **not** a code-execution primitive — recorded because
it is a genuine gap in the fix, and because a crash is a usable oracle even when it is not a
vulnerability.

### The EventTarget pattern, swept

`auto& context = *scriptExecutionContext();` appears at 17 more sites. The class only bites when
the reference is held across a **JS-reentrant** call, and that is rare:

- `XMLHttpRequest::prepareToSend` — spans `shouldIgnoreSyncXHRs`, `readyState`, CSP evaluation;
  no script runs, safe.
- `WebSocket::connect` — spans URL validation, console messages, CSP upgrade; safe.
- `MessagePort::disentangle` — spans channel-provider notification and three bookkeeping calls;
  safe.

`EventTarget` was the dangerous one precisely because it loops over listeners, and each listener
is arbitrary script. The sweep found no second site of that shape that is reachable on this
build. That is the useful form of a negative: the class is real, Sony fixed the instance that
mattered, and the neighbours are clean rather than unexplored.

## Standing rule

Do not count a patch as a fix until you can name the path it fails to cover, or prove there is
none. Both of this repo's earlier "live candidates" passed an upstream-diff check and then
failed on hardware; the cheapness of the diff made it feel like progress. Reading a patch for
the assumption it encodes is slower per file and much faster per actual result.
