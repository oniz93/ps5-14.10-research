# Bug 260896 on retail 14.10: does not reproduce

**Verdict: dead on this build.** The bug is present in Sony's source in its pre-fix shape, but
the shipped engine does not crash under any of the three teardown shapes we could construct.
Reported 2026-10-24 on a retail 14.10 console via the Guide WebView.

## What was tested

| shape | beacons | result |
|---|---|---|
| authentic upstream case, verbatim | `SS-*` | rendered, no crash, complete run |
| + shadow host removed, 60 clone teardowns, forced GC | `1..130` | complete: `1-ENTER` → `9-AFTER-GC2` → `B1/R1 … B60/R60` → `Z-SURVIVED`, 0 exceptions |
| + 24 hosts held live across a GC, dropped, then document reload in a loop | `DOC-n` | **226 document loads, 225 complete runs, 224 `KEEP-DROPPED`, 0 `THREW`, 0 `ERROR`** over 21 minutes |

The third row is the strongest: 224 document teardowns × ~61 host teardowns each is roughly
13,700 shadow-root destructions, every one of which destroys a `Style::Scope` while an
`SVGElement` in the tree is still referenced from a `RenderStyle`. That is the exact
arrangement the upstream fix describes, and it never faulted.

Reproducer: `guide_lab/www/pages/style-scope-instrumented.html` (markup byte-identical to
`LayoutTests/fast/css/style-scope-destruction-crash.html` below `</head>`; only the script is
instrumented). Raw fuzzer case: `www/pages/style-scope-upstream.html`.

## What the console established along the way

- `x5` parses into the **XHTML** namespace, not SVG. The `<blockquote>` hits the
  foreign-content *breakout* rule and pops out of the SVG subtree, which is why
  `attachShadow` is legal on it. The rest of the fuzzer markup is recovered the way the test
  assumes (`x11`, `x18` stay in `http://www.w3.org/2000/svg`).
- So the case is not blocked by the parser, by `attachShadow` support, or by the SVG being
  inside a shadow tree. It runs end to end.

## Why the source is pre-fix yet the engine does not crash

Recorded honestly as open, not resolved:

1. Sony may carry a different fix for the same defect. The drop diff shows 59 changed text
   files under `Source/`, and we only compared the two specific hunks the upstream patch
   touches (`ReferencePathOperation::m_element`, `Scope::~Scope`). A third, localised change
   — for example revoking the weak pointers somewhere else in the teardown order — would not
   show up in that comparison and would defeat the regression test without defeating the bug
   signature.
2. The teardown order in this build may destroy the element before the scope, closing the
   window without fixing anything. That would be luck, not a patch, and would also mean the
   bug is unreachable rather than absent.
3. The regression test may under-trigger: it is a fuzzer case reduced by hand, and reduction
   loses trigger conditions routinely.

Distinguishing 1 from 2 needs a debug build with the object lifetimes printed — which is the
same missing instrument as the Style::Scope allocation-size question, and still unfunded.

## Consequence for the programme

Do not spend more console time on this bug. The relevant question for exploitation is "does it
fire on the target", and the answer is no, three times, with 13,700 chances. The second
candidate (bug 272882, `RenderMenuList`) is a different shape entirely — no GC timing, no
parser trickery, plain DOM operations — and is the next test.
