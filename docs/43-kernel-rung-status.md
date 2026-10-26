# Kernel rung: candidate found, verification blocked

Goal criterion added mid-loop: find a kernel bug if needed. Work done against the FreeBSD 11 lineage that
the PS5 kernel forks (r230171), because Sony's own source is not public.

## CVE-2026-7270 (execve memmove OOB write) - ELIMINATED

The public assessment in this repo left it "unconfirmed". It can be settled from source: the fix changes
`exec_args_adjust_args()` in `sys/kern/kern_exec.c`. FreeBSD `releng/11.0`'s `kern_exec.c` contains **no
`memmove` at all** and no such function - the helper arrived with the later exec argument rewrite. A kernel
forked from r230171 therefore cannot contain the vulnerable expression, so a public exploit for it cannot be
ported no matter how good it is.

Method note: check that the *function the fix touches* exists in the vendor's base before assessing
applicability. "Present since FreeBSD 11" claims in secondary sources are not reliable.

## CVE-2026-45251 (procdesc poll/select UAF) - PRESENT IN THE BASE

FreeBSD-SA-26:19.file, fixed May 2026. The advisory's fix adds one line:

```c
seldrain(&pd->pd_selinfo);
```

to `procdesc_free()` in `sys/kern/sys_procdesc.c`, and moves `selwakeup()` out of the conditional that
`PDF_SELECTED` used to gate.

FreeBSD `releng/11.0` `procdesc_free()` is the pre-fix shape:

```c
if (refcount_release(&pd->pd_refcount)) {
    KASSERT(pd->pd_proc == NULL, ...);
    KASSERT((pd->pd_flags & PDF_CLOSED), ...);
    knlist_destroy(&pd->pd_selinfo.si_note);      /* no seldrain() */
    PROCDESC_LOCK_DESTROY(pd);
    uma_zfree(procdesc_zone, pd);
}
```

and `procdesc_poll()` does `selrecord(td, &pd->pd_selinfo)` + `PDF_SELECTED` without holding a reference to
the procdesc. So a thread blocked in `poll()` on a pdfork descriptor can outlive the object: close the fd in
another thread, `procdesc_free()` returns it to the zone, and the wakeup walks freed memory.

Requirements on PS5, none of which are verified:
1. `pdfork(2)` reachable from the compromised process (the sandbox may deny it).
2. A second thread, since the race needs a blocked thread and a closer.
3. Sony not having backported the May 2026 fix - **unknown**.

## Why verification is blocked

- No 14.10 kernel image exists here. `docs/KERNEL_IMAGE_ROUTES.md` in the public research reached the same
  conclusion.
- The 13.60 dump referenced by that research (`zigzagboi1/ps5-13.60-kernel-dump`) returns **404** now, so
  even the 13.60 baseline is unavailable for a `seldrain` check.
- Runtime testing needs code execution, which is the browser chain, which is not finished.

## Browser chain status after this round

`c015` tried to convert the alias into controlled object bytes: reclaim the freed 768-byte
`CanvasRenderingContext2D` with ArrayBuffers instead of canvas contexts, then write `lineWidth` through the
stale wrapper and scan the buffers for the double.

Result on the console: `c015-768:sprayed` then death - the write landed on freed memory, so 1200 buffers of
that exact size did not reclaim the slot. ASAN cannot answer this question (it quarantines freed
allocations), so the console is the only oracle and each failed attempt costs a WebProcess restart. Next
iterations need proper grooming: prime and drain the size class before the trigger, sweep neighbouring size
classes (800/832/896/960), and keep the write and the scan in separate attempts so a failed write does not
destroy the evidence.
