# 35 - ASAN sweep results (first valid run)

## Result

1,600 seeds across three probes, every one reaching its `DONE` beacon, **zero AddressSanitizer
reports**, zero reproducible non-ASAN failures.

| probe | seeds | completed | ASAN | notes |
|---|---|---|---|---|
| `dom_fuzz.js` | 1200 | 1200 | 0 | 612 serial + 588 by 6-worker pool |
| `jsserializer_fuzz.js` | 200 | 200 | 0 | structuredClone / transfers / workers |
| `parser_fuzz.js` | 200 | 200 | 0 | HTML misnesting / custom element reactions |

9 seeds exited non-zero on the first pass (6 DOM, 3 serializer, 3 parser) and **all 9 completed
cleanly when re-run alone**. They are contention flakes from six concurrent browsers, not bugs - each
was reproduced individually rather than written off.

## What each probe actually exercises

**`dom_fuzz.js`** - shadow root attach/remove while children reference them (Style::Scope teardown),
SVG clip-path/mask/filter reference removal, CSS insertRule/deleteRule churn with nesting, container
queries, `@layer` and `:has()`, template content cloning with adopted stylesheets, slot assignment
changes with `slotchange` handlers that mutate the tree, Web Animations cancelled mid-flight on
detached elements, Range/Selection across removed nodes, MutationObserver re-entrancy, iframes
destroyed during load.

**`jsserializer_fuzz.js`** - deep and cyclic graphs, transfer lists, use-after-detach, resizable
ArrayBuffers resized under a live view, transfer-then-resize, re-serialising on receipt,
`Worker.terminate()` racing an in-flight payload. This is the surface where bug 278657 was closed by
inspection; the inspection covered only the serializer's `byteLength()`/`data()` window, so the
deserializer, transfer handling and worker teardown were untested until now.

**`parser_fuzz.js`** - misnested formatting elements, foster parenting, tables inside tables, SVG
`foreignObject` namespace switching, MathML annotation-xml, `template` with table content, custom
elements whose connected/disconnected/adopted/attributeChanged callbacks move the node they are
called on, adoptNode/importNode across documents, `Range.surroundContents` on half-parsed trees.

## What this does NOT prove

- Media is unexercised: `MediaPlayerPrivateGStreamer` aborts on `RELEASE_ASSERT(audioSink)` because
  the container has no audio device, and Sony's media stack is proprietary so its behaviour would
  not transfer anyway.
- EME, WebGL and Web Audio are absent from the console; WebGL and EME are absent from this build too.
- Absence of a crash in 1,600 seeds says these *classes* are not trivially broken. It does not clear
  the code; a bug needing a specific interleaving or a shape these generators never emit would
  survive.

## Harness caveats learned the hard way

- A "clean" seed means the page reached `DONE`, nothing more. Nine separate defects earlier made
  runs look clean while testing nothing (docs/34).
- Exit code 143/137 from 1,200-seed sweeps is the runner's own group kill for a seed that never
  finished, not a crash. Both `run_fuzz.sh` and the pool now classify that as NOT-COMPLETED.
- Under six concurrent browsers, roughly 1 seed in 200 exits 1 at startup. Always re-run a failing
  seed alone before believing it.

## Throughput

- serial: ~12 seeds/min
- 6-worker pool: ~67 seeds/min (5.6x), load 3.0 of 12 threads, memory comfortable at 15 GB

The board had been running at load ~1.7 because a single MiniBrowser is effectively single-threaded;
the pool is what makes this hardware worth having.
