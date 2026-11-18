# PS5 boot-chain research — status

A personal research programme on the boot path of a PlayStation 5 I own, run to understand how
the platform starts and how its software is put together.

**This repository is a status page. It publishes no research content.**

<!-- status:begin -->
**Last updated:** 2026-11-18

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
<!-- status:end -->

## What is here

| File | What it is |
|---|---|
| `README.md` | this page — the status itself, kept current as stages move |
| `STATUS.md` | the same status as a single file, for anything that reads one document |
| `DISCLAIMER.md` | scope, jurisdiction, and what is withheld |
| `SECURITY.md` | how to reach me about this repository |
| `CONTRIBUTING.md` | why this repository does not accept code |
| `CHANGELOG.md` | dated, phase-level changes to this page |
| `LICENSE`, `NOTICE.md` | terms and attribution |

## What is not here

No firmware, update package, or extracted image. No key or signing material. No tooling,
measurement data, source excerpts, crash logs, addresses, memory layout, or procedure of any kind.
No artefact intended to gain access to a device, an account, or paid content.

The working notebook — notes, measurements, and the tooling that produced them — is kept in a
private repository. Nothing from it is mirrored here, and nothing here is derived from it in a
form that could be used to reproduce the work.

## Why

Distributing circumvention technology is restricted where this project is run from: 17 U.S.C.
§1201 in the United States, and Copyright Act s.41.1 in Canada, which carries no
security-research exception. Writing about a platform is one thing; publishing a reproducible
route into one is another. This project is a personal notebook, not a disclosure channel, so
the notebook stays closed and this page carries the status only.

If you are looking for a way to modify a console, this repository will never be that, and the
absence is deliberate.

## Scope

Personal research on hardware I own, unaffiliated with Sony Interactive Entertainment. No
warranty of any kind; see [`LICENSE`](LICENSE).
