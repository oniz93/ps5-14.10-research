# What the successful PS5 chains actually did, and where we diverge

Read from the primary writeups (ChendoChap/Znullptr 4.03, PS5Dev UMTX, CyB1K 4.03 kernel), not summaries.

## The procedure that worked, in order

1. **WebKit bug -> userland arb R/W.** In every public PS5 chain the browser bug is only ever used to obtain
   `leakobj()`/`fakeobj()` and arbitrary read/write inside the WebProcess. Nobody uses the browser bug to reach
   the kernel directly.
2. **Do not attack virtual calls.** ChendoChap is explicit: on PS4 they leaked an `HTMLTextArea` vtable and
   smashed a virtual call; on PS5 that fails because clang CFI (`-fsanitize=cfi-vcall/-nvcall/-icall`) checks
   the vptr's dynamic type at every call site. This is a forward-edge-only defence.
3. **Attack the backward edge instead.** No shadow stack => return addresses are fair game. They walk
   libkernel's thread list (`lk__thread_list`, `next_thread` +0x38, `stack_addr` +0xA8, `stack_size` +0xB0),
   pick a Web Worker (stack size 0x80000), and overwrite the deterministic return address at `stack+0x7FB88`
   with a `pop rsp` gadget, pivoting into a ROP chain. Their stated reason for liking Workers: a reliable,
   leakable stack and a thread to pivot onto.
4. **Kernel bug is separate and always a race/UAF.** 4.03 = TheFlow's `ip6_pktopts` UAF; UMTX =
   CVE-2024-43102 umtx race; Relapse/Prolapse = `aio_multi_*`. Kernel entry is never a browser bug.
5. **Kernel R/W, then a *data* patch for the goal.** Both 4.03 writeups list "Enables debug settings menu" as a
   data patch, and both are explicit that code execution is impossible: kernel `.text` is XOM, reading it
   panics, the hypervisor enforces write protection, so no hooks. The debug menu comes from flipping kernel
   data - consistent with our own landmark `security_flags` at `D+0xDA4064` on 14.10.
6. **Cleanup is part of the exploit.** UMTX leaks a refcount and zeroes `td_kstack`; 4.03 bumps socket
   refcounts. Without it, closing the browser panics because process teardown frees things twice.

## Where our chain stands against that template

| step | template | ours |
|---|---|---|
| 1 | WebKit bug -> arb R/W | **missing**: canvas UAF reproduced, alias proven, no R/W |
| 2 | avoid vtable/CFI | we have not attempted a vtable hijack - keep it that way |
| 3 | thread-list walk + return-address pivot | not attempted; needs step 1 |
| 4 | kernel race UAF | CVE-2026-45251 (procdesc) is the only candidate, and prolapse is private |
| 5 | data patch -> debug menu | target known (`security_flags`), unreachable without 4 |
| 6 | cleanup | not applicable yet |

So the whole chain is gated on step 1, and step 1 is exactly the reclaim we have been failing at.

## What the FontFace-era primitive implies for a 712-byte WebCore UAF

The PS4/PS5 FontFace exploit also starts from a WebCore `fastMalloc` object that is freed and reused after a
re-entrancy bug. It gets `leakobj/fakeobj` by making the freed object overlap **JavaScriptCore's own data** -
a JSArray's butterfly - so that JS can both observe and write the object's fields. Two consequences:

* Strings are the wrong spray. They let us *observe* an overlap but never *write* to it, so an overlap could
  not be turned into a primitive.
* A contiguous double `Array` has a butterfly of `8*n + 8` bytes, so `n ~= 88` lands in the same class as the
  712-byte context. If the butterfly takes the slot, the array elements *are* the object's first fields, so
  `beginPath()` (which stores a fresh `Path*` into the object) changes visible array elements and leaks a heap
  pointer, and array writes give us control over the object's fields.

That is `c017`: same oracle as `c016`, but the spray is double arrays swept around n=60..120, because a
writeable overlap is the whole point.

## The one thing we cannot copy

Relapse/Prolapse are private; CVE-2026-45251 needs a 14.10 image to confirm and a userland primitive to reach.
Step 4 has no public solution for 14.10 - which is why step 1 still deserves the effort even though it cannot
finish the chain alone.
