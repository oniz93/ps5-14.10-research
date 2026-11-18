# Status

**Last updated:** 2026-11-18

Private notebook; this page carries phase-level status only.

## Where the work stands

The programme runs from the platform's boot path, through the browser engine, to the
system software underneath it. Three of its six stages are open at once, and the centre of
gravity has moved: the last update was cataloguing, this one is testing. No stage here is an
announcement that something works.

| Stage | Status |
|---|---|
| 1. Boot-chain and container format | complete |
| 2. Read-only inspection tooling | complete |
| 3. Browser-engine memory safety | in progress |
| 4. Process isolation on the target | not started |
| 5. System software behaviour | in progress |
| 6. Component survey (read-only) | in progress |

Where attention is, in the same order: stage 5 carries the bulk of the work, stage 6 keeps
widening its catalogue, stage 3 is steady with one line paused on an environment
constraint, and stage 4 stays shut until stage 3 opens it.

**What moved since 6 November.** Stage 5 turned from reading the system software into
testing it: questions are now settled by measuring the retail console rather than by argument,
and nearly every direction examined in the two weeks since closed instead of opened. That is
the result the stage was built to produce — the set of things still worth trying is materially
smaller than it was, and the notebook carries the measurement behind each closure. Stage 6 has
added more shipped components to its read-only catalogue, which is still far from complete.
Stage 3 has not moved: the engine study is where it was, with one line of it paused on a
constraint in my own test environment rather than on a question about the target. Stage 4
remains not started, and stays so until stage 3 produces something worth building on.

### How to read the states

States record research activity, never capability. A stage can sit *in progress* for
months while a dozen directions close inside it, and a stage that finishes its work is not a
stage that produced something usable.

| State | What it means |
|---|---|
| complete | the question the stage asks has been answered; what remains is engineering, not research |
| in progress | attention is on it now, and the notebook is being written |
| not started | nothing done beyond what an earlier stage required |

Notes, measurements, and tooling stay in the private notebook. Nothing here is derived from
them in a form that could be reproduced.

**Public artefact: none.** No stage publishes notes, measurements, tooling, or data.
See [`DISCLAIMER.md`](DISCLAIMER.md) for why.
