# Sony's browser patch set, recovered from the OSS drops

> Answer to "can we read all the patches". The drops contain no history, so no — but
> consecutive drops can be diffed, and that recovers Sony's own backports. Done for the
> 14.00 boundary: **59 changed files, ~11 with security-shaped guards**, each readable as
> a normal patch.

## Why a diff works

Each drop is a snapshot (no `.git`, no ChangeLog past 2022) but every archive's central
directory carries a **CRC32 and size per member**. Two archives → join on path → the
changed-file inventory costs two range reads and no content transfer. Only the changed
text files get fetched after that.

```bash
python3 tools/fw1400/remote_zip.py <webKit-1200.zip>  --manifest data/manifest-webkit-1200.json
python3 tools/fw1400/remote_zip.py <webKit_1400.zip>  --manifest data/manifest-webkit-1400.json
python3 tools/fw1400/wk_drops_diff.py \
  --base-manifest data/manifest-webkit-1200.json --base-url <WebKit-1200.zip> \
  --head-manifest data/manifest-webkit-1400.json --head-url <WebKit_1400.zip> \
  --out out/diffs --summary out/diffs/summary.json
```

| | drop A | drop B |
|---|---|---|
| covers | 12.00 – 14.00 | 14.00 – |
| members | 414,969 | 414,181 |
| changed | — | **69** (61 under `Source/`, 55 C/C++) |

Both declare WebKit `616.1.27.211.1`: Sony does not rebase, it cherry-picks. So the delta
is Sony's backport list for the 14.00/14.10 cycle.

## What is actually in it

Confirmed against upstream at the Safari 17.0 cut (`ba9730178b6a`, 2023-09-09): none of
these hunks exist there, so they are post-cut fixes Sony pulled forward.

**`Source/JavaScriptCore/builtins/ProxyHelpers.js` + `NodesCodegen.cpp` (+ `BytecodeIntrinsicRegistry.h`)**

```diff
-    var trapResult = trap.@call(handler, target, propertyName, receiver);
+    var trapResult = trap.@call(handler, target, propertyName, @toThis(receiver));
```

The `@toThis` intrinsic had to be added to the bytecode generator, so this is the complete
upstream patch. Passing an unboxed receiver into a proxy trap is the receiver/`super`
confusion class — and it is exactly why the p160 phase-1 probe returned `undefined` on
this console instead of leaking a scope object. Hardware result and source agree.

**`Source/WebCore/xml/parser/XMLDocumentParserLibxml2.cpp` (+17)**

A custom-element constructor can re-parent, adopt or detach the new element while the
reaction stack drains, and `parserAppendChild` requires an unparented node in the same
document. The fix re-validates and calls `stopParsing()`. Classic DOM lifetime bug,
reachable from plain HTML.

**`Source/JavaScriptCore/yarr/YarrPattern.cpp` (+8)**

```diff
+            if (parenthesisMatchDirection() == Backward && m_forwardReferencesInLookbehind.size()) {
+                UnresolvedForwardReference& mostRecentForwardReference = m_forwardReferencesInLookbehind.last();
+                if (mostRecentForwardReference.term() == &m_alternative->lastTerm())
+                    m_forwardReferencesInLookbehind.removeLast();
+            }
             m_alternative->removeLastTerm();
```

A `{0}`-quantified forward reference inside a lookbehind is elided but was still left in
the unresolved-reference vector — a dangling reference in the regex compiler. Reachable
with a regex literal: `(?<=\1{0}…)` shapes.

**`Source/WebCore/platform/image-decoders/bmp/BMPImageReader.cpp` (+38)**

An RLE absolute-mode run can begin mid-row, but the pixel index was computed from the
absolute column while the bounds check used the run start. Fixed by indexing relative to
`startX`. Out-of-bounds read, reachable by loading a crafted `.bmp`.

**`Source/WebCore/Modules/streams/TransformStream.cpp` (+14/−2)** — `ASSERT(size == 3)`
and unchecked `jsDynamicCast(...)->wrapped()` replaced with real TypeError paths.

**Also in the delta:** `SQLiteDatabase`/`SQLiteTransaction`/`SQLiteIDBCursor` (SQL-layer
hardening), `EventTarget.cpp`, `CSSParserImpl.cpp`, `FontPlatformDataFreeType.cpp`,
`GLContext.cpp`, `CheckedPtr.h`/`CheckedRef.h`, `JSCell.cpp`, `ArgList.h` (a −213 fast
path removal), `DFGByteCodeParser.cpp`, `Heap.cpp`, `VideoTrack.h`, `SVGStyleElement.h`,
`RenderListBox.h`.

**And Sony's own work:** `SerializedScriptValue.cpp` grows by 475 lines that are mostly a
serialization-tag naming table plus `DataLog` tracing (`verboseTrace = false`) — they were
debugging the structured-clone path, the exact surface the Relapse browser stage abused.
`AcceleratedSurfacePlayStation.cpp` (+100) and `FocusControllerPlayStation.cpp` are
PlayStation-only code.

## The other half: what they did *not* take

The delta shows Sony cherry-picking, which makes the negative space tractable and far
more valuable:

> upstream WebKit security fixes landed after 2023-09 **minus** the ones in this delta =
> candidate live bugs on 14.10.

Each candidate is testable in seconds with the same machinery: fetch the file from
`WebKit_1400.zip`, check for the fixed hunk. No console, no fuzzing, no guesswork.

Practical ordering, by what the console can actually reach (measured surface: no wasm, no
WebGL/GPU, no workers, no SharedArrayBuffer, no IndexedDB, no AudioWorklet):

1. JSC core — parser, bytecode generator, DFG/FTL, Yarr, `SerializedScriptValue`.
2. DOM/HTML parser and bindings, custom elements, streams, `EventTarget`.
3. Image decoders — BMP, ICO, GIF, JPEG (the console decodes images in this WebView).
4. CSS parser / fonts.
5. Out of scope: workers, GPU process, wasm, IndexedDB, audio — no surface on this build.

## Caveats

- One delta per firmware **boundary**, not a history: this recovers 14.00-cycle fixes, not
  everything since 2022. Earlier boundaries are recoverable the same way by diffing the
  earlier archive pairs.
- Some entries are Sony instrumentation or PlayStation port code, not security fixes;
  `data/wk-patch-inventory.json` scores each file by guard-shaped vs trace-shaped lines.
- The drop is a compliance artifact: what ships may be built with a different feature set.
  Verify reachability on the console before investing in a bug.

## Files

| path | what |
|---|---|
| `tools/fw1400/wk_drops_diff.py` | CRC-diff two drops, fetch changed files, write unified diffs |
| `out/diffs/*.diff` | 59 patches, Sony 12.00–14.00 → 14.00+ |
| `data/wk-1200-vs-1400-drift.json` | changed/added/removed member lists |
| `data/wk-patch-inventory.json` | per-file guard/trace scoring |
| `data/manifest-webkit-{1200,1400}.json` | name → CRC32/size for every member |
