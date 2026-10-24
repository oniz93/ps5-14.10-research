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
| 1 | `SerializedScriptValue` pool desync | is there a tag pair the two sides disagree on? | read both `apiSerialize`/`apiDeserialize` tag handling side by side; the checker tells you exactly which tags are pool-eligible |
| 2 | media append contract | does the backend retain the pointer? | console probe first (`cap-sony-surface.js`), then append/remove churn |
| 3 | CDM callback ordering | can two requests be in flight and reorder? | trigger `requestMediaKeySystemAccess` for two sessions |
| 4 | remaining behavioural patches | `YarrPattern.cpp` (+8), `XMLDocumentParserLibxml2.cpp` (+17), `TransformStream.cpp` (+14/−2), `ProxyHelpers.js` (+4/−4) | same 6-step method |

## Standing rule

Do not count a patch as a fix until you can name the path it fails to cover, or prove there is
none. Both of this repo's earlier "live candidates" passed an upstream-diff check and then
failed on hardware; the cheapness of the diff made it feel like progress. Reading a patch for
the assumption it encodes is slower per file and much faster per actual result.
