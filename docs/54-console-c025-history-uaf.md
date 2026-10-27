# Console results: c025 series (HistoryController UAF) - no crash, harness fixed twice

Target: fix `efe49205`, use-after-free in `HistoryController::recursiveGoToItem` when a popstate handler
re-enters history while the traversal still holds item pointers. Chosen because `HistoryController` is a plain
C++ object, so the IsoHeap segregation that killed the canvas route does not apply.

Three iterations, because the first two were harness bugs and not verdicts:

* **c025** - `iframe-added` then straight to `survived`, never `loaded`. The `onload` handler was assigned after
  the iframe was appended with `src` already set, so the load event fired into nothing.
* **c025b** - handler attached first; `loaded` fired, then `setup-threw: SecurityError`. `pushState` on an
  `about:blank` frame fails because the frame has an opaque origin, so its history is not scriptable.
* **c025c** - child frame loads a real same-origin document (`/cases/blank.html`). Full sequence reached:
  `pushed` -> `back-called` -> `popstate-ran` (40 iframes + churn) -> `survived`.

Verdict: **no crash on 14.10**. Strength of that negative is limited: the upstream test used
`GCController.collect()`, which does not exist outside testRunner, and the fallback (string churn) is what ran
here. So this reads as "not reproducible with a best-effort GC", not "proven patched".

Infrastructure note: the manifest hot-reload finally worked end to end (`HOTRELOAD` beacon then the new case
running), so cases can be swapped without touching the console.

## Sweep scoreboard so far (retail 14.10)

| candidate | shape | verdict |
|---|---|---|
| Canvas getContext UAF | UAF, IsoHeap class | alias only - cannot reclaim |
| TransformStream poisoned iterator | type confusion | LIVE - null-deref DoS |
| ReadableStream fake-Promise pipeTo | type confusion | throws TypeError - inert |
| WebCrypto SPKI length overread | OOB read | fixed (`DataError`) |
| Style::commitRelations `:has()` | UAF | survived (GC caveat) |
| HistoryController popstate | UAF | survived (GC caveat) |
| XMLDocumentParser startElementNs | UAF | guard present in Sony's drop |
| CSSFontFace setStatus | UAF | engine version in drop already has the Ref fix |
