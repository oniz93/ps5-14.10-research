# Both WebKit candidates are dead — where the campaign actually stands

Reported 2026-10-24 on retail 14.10. This closes the "replay upstream fixes against Sony's
frozen snapshot" line of attack.

## The two survivors, and how they died

| bug | shape | test | result |
|---|---|---|---|
| 260896 `Style::Scope` | shadow root + SVG cycle, teardown | 226 document loads, 225 complete runs, ~13,700 shadow-root destructions | 0 faults, 0 exceptions |
| 272882 `RenderMenuList` | `<select>`, `options[1]=undefined`, `multiple=true`, layout | 200 iterations × 2 runs, `SEL-CONTAINER-yes` | `survived 200`, 0 faults |

`SEL-CONTAINER-yes` matters: it confirms container queries are supported on this build, so the
reproducer's trigger condition (a size-container select forcing style resolution during layout)
was genuinely in play rather than silently skipped. Without that beacon the negative would not
be trustworthy — the same trap that made the first Style::Scope run vacuous.

## Why this is a real negative, not another silent zero

Each of the three vacuous runs found earlier in this campaign failed for a nameable reason we
could see: the wrong `current` path, the old server still holding the previous module, a probe
with no SVG `<style>`, a test that never removed the host. Every one of them was caught by a
beacon that should have appeared and did not. Here the beacons are complete and numbered:
`1-ENTER` through `Z-SURVIVED` plus all 120 loop beacons in one case, and all 200 iterations in
the other. The engine executed the full sequence and did not fault.

## Why pre-fix source and no crash can coexist

Recorded as open, not resolved. Three explanations remain and the tests cannot separate them:

1. **Sony carries a different fix.** The drop diff covers 59 changed text files; for these two
   bugs we compared only the hunks upstream's patches touch. A localised change elsewhere —
   revoking weak pointers during a different phase, or a different renderer-swap order — would
   defeat the regression test without matching the patch we diffed.
2. **Teardown order happens to be safe in this build.** That is luck, not a patch, and it still
   means the bug is unreachable from a page.
3. **The reduced reproducers under-trigger.** Both are hand-reduced fuzzer cases; reduction
   routinely drops a condition.

Separating 1 from 2 needs a debug build that prints object lifetimes and renderer destruction
order — the same missing instrument as the `Style::Scope` allocation-size question.

## What the campaign bought

The method itself works: it found, in Sony's shipped tree, two genuine pre-fix shapes that
survive every filter (compiled-in, runtime-enabled, pre-fix code present, era-correct). It then
established, on hardware, that neither fires. That is the correct outcome of a filter that is
allowed to be wrong — and the reason the filter was built to be cheap.

What it did not buy is a foothold. Roughly 348 upstream fixes swept, 2 candidates, 0 primitives.

## The fork, stated plainly

**Option A — build WebCore on Linux and fuzz it.** A GTK or WPE build of the same source, with
libFuzzer or AFL on the DOM/CSS entry points. This is the only option that finds *unknown* bugs
rather than replaying known ones, which matters when the known ones have all been replayed and
failed. Cost: 1–2 days of setup, then sustained compute. The macOS build is blocked on bmalloc's
TAPI step and seven Xcode-27 incompatibilities; on Linux none of that exists.

**Option B — stop the WebKit line.** The WebView rung has now been tested for reachability
twice over: the published exploit families are closed, the fixes for everything after the
snapshot are either present or unreachable, and the engine is interpreter-only. Move effort to
the kernel side (FreeBSD advisory backports on a reachable syscall surface) or to hardware
(UART unlock, NOR dump, empirical memory map).

**Not an option: keep replaying fixes at lower intensity.** 348 swept with two survivors, both
dead, is not a sample that justifies another sweep pass.

## Files

- `docs/25-style-scope-verdict.md` — candidate 1, full accounting
- `tools/fw1400/probes/poc-select-uaf.js` — candidate 2 probe (94 lines)
- `tools/fw1400/guide_lab/www/pages/style-scope-instrumented.html` — candidate 1, instrumented
- `data/sweep-*.json` — the 348-commit sweep corpus and its triage
