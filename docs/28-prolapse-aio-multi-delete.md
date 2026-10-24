# Prolapse: a kernel bug on 14.10, and what it changes

Reported by Jose Coixao (@notzecoxao) on 2026-10-24, as "prolapse coming to 14.00/14.10".
Second-hand claim, not yet verified by us, but it is specific enough to act on and it
contradicts a conclusion this repo had recorded as settled.

## The claim

- The bug is a **TOCTOU use-after-free / double-free in `aio_multi_delete`** — the delete
  path of Sony's own AIO block, not the `aio_multi_wait` decrement bug that Relapse used.
- It is **present on 14.00 and 14.10**.
- **14.20 kills it** by adding a targeted validation — a generation-ID check — which is
  precisely the kind of fix that closes a check-then-use race without changing the API.

## What this corrects in our own record

`docs/10-fw1400-position.md` and `docs/26-both-candidates-dead.md` both state, in effect,
that 14.10 has no public kernel path and that the rung above the WebView was missing. That
was true as of the public record we had. It is now outdated: **a kernel R/W bug exists for
14.10**, unreleased.

Operationally the most important line in the whole post is the one about 14.20. The standing
"do not update" advice now has a much harder reason behind it than "there is no public
kernel exploit": updating to 14.20 destroys this bug specifically, permanently, on this
console. Do not update.

## This is the sibling we predicted

`docs/11-sysent-dispatch-and-tools.md` established that the PS5 does not use FreeBSD's AIO
surface at all — most FreeBSD AIO syscalls are `nosys` — and instead carries a Sony-authored
block at **661–670, all ten live**, with 663 resolved to `aio_multi_wait`, the Relapse bug.
The note closed with:

> the natural place to look for a 14.00 sibling is the nine neighbouring entries in the same
> Sony block — hand-written, recently touched, and (as far as public evidence goes) patched
> only at 663.

`aio_multi_delete` is one of those nine. The prediction was right, and it arrived as a bug
found by someone else rather than by us.

## What we cannot do about it, and why

We wanted to audit those handlers statically. We cannot, and the reason is worth recording so
nobody wastes a day repeating the attempt:

- `docs/dumps_13.60/handler_<n>.bin` are **not handler bodies**. Each 4 KB file is a slice of
  the thunk area — the disassembly is `e9 <rel32> cc cc cc cc` repeated, i.e. the 8-byte-
  aligned relative-jump thunks that `sysent[i].sy_call` points at. Adjacent indices share
  windows, which is why 661 and 663 look nearly identical at the top.
- Resolving a thunk yields the handler RVA (663 → `0x3b01f0`), but the bytes at that RVA are
  not in any artifact we hold. The one real kernel-text capture in the research clone covers
  `0x37e000–0x38c000` (UMTX, syscall 454). The AIO block sits at `0x3af8f0–0x3b28d0`.
- So the handlers are readable only with a kernel read primitive on ≤13.60, i.e. the very
  thing we lack on 14.10. The loop is closed.

## The transferable lesson: generation IDs, one layer up

The fix shape is the interesting part. A generation/identity check exists to stop a
lookup-then-act sequence from acting on a *stale* object after the table it was looked up in
has changed. That failure mode does not respect the kernel/userland boundary, and Sony's
WebCore media glue has exactly the same shape:

`CDMInstanceSessionPlayStation` enqueues one callback per operation and dequeues **by
position** (`licenseCallbackQueue().dequeue()`), with no request identity and no generation
attached. If the platform backend completes two in-flight requests out of order — which an
asynchronous backend is entitled to do — the result of request B is delivered to the caller of
request A. That is the same class of defect the 14.20 kernel fix addresses: state matched by
arrival order instead of by identity.

It is not memory-unsafe on its own, but it is the kind of invariant break that composes badly,
and it is Sony-authored code with no upstream counterpart, reached from `generateRequest()`.

## What this means for the programme

1. **Do not update.** 14.20 closes prolapse. 14.10 keeps it.
2. **The kernel rung is not ours to build.** It is either released by the people who have it,
   or bought with hardware work. Nothing in this repo's software path produces it.
3. **Our half is still the entry.** A kernel bug does not boot itself: it needs userland code
   execution first, and on a console with no PS4 for save re-signing, the Guide WebView is the
   only entry available. That is unchanged by this news — but it now has a buyer, which it did
   not have yesterday.
4. **The audit target widened, not narrowed.** Sony-authored code that ships and has no
   upstream twin: `MediaPlayerPrivatePlayStation`, `SourceBufferPrivatePlayStation`,
   `CDMInstanceSessionPlayStation`, `CurlTMServiceRequest`. That is where the chains will come
   from, because it is the only code nobody else has read.

## Unverified

Everything above about prolapse is the author's claim as relayed in a screenshot. No PoC seen,
no advisory, no confirmation that 14.10 specifically is affected versus 14.00 only. Treat the
14.10 applicability as probable-but-unconfirmed until a release note or a second source
appears.
