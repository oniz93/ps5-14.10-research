# PS5 boot-chain research — status

A personal research programme on the boot path of a PlayStation 5 I own, run to understand how
the platform starts and how its software is put together.

**This repository is a status page. It publishes no research content.**

## Where the work stands

The programme runs from the platform's boot path, through the browser engine, to the system
software underneath it. [`STATUS.md`](STATUS.md) tracks a stage for each part of that arc, so
the page says where attention currently is without saying what has been achieved.

States record research activity, not capability. No stage here is an announcement that
something works — that would be the very thing this repository exists to avoid publishing.

| Stage | Research area | State |
|---|---|---|
| 1 | Boot-chain and container format | complete |
| 2 | Read-only inspection tooling | complete |
| 3 | Browser-engine memory safety | in progress |
| 4 | Process isolation on the target | not started |
| 5 | System software behaviour | in progress |
| 6 | Component survey (read-only) | in progress |

This is the same table [`STATUS.md`](STATUS.md) carries, repeated here so the current state
can be read and parsed without opening a second file. Where the two ever disagree,
[`STATUS.md`](STATUS.md) is the rendered one.

## What is here

| File | What it is |
|---|---|
| `STATUS.md` | where the programme stands, in phase terms |
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
