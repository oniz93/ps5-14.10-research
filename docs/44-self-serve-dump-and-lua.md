# Self-serve results: 13.60 kernel dump recovered, procdesc confirmed present, Lua entry mapped

Teo asked me to look things up myself rather than ask him. Done: the two things I had declared blocked
were both findable.

## The 13.60 kernel dump exists, one URL away

The repo referenced by the public research (`zigzagboi1/ps5-13.60-kernel-dump`) 404s, but the capture was
re-published at `terrafirma2021/ps5-13.60-kernel-dump` (captured 2026-10-13).

Downloaded and verified:

```
kernel-13.60-live.bin.gz   23,286,602 bytes
kernel-13.60-live.bin     103,546,880 bytes
sha256 c3f745e25dc25ee7afef89eb418b295b6334bbefe8aa17e6886483c35d78cddd   <- matches the documented hash
```

Layout: text 0x0..0xcc0000 at VA 0xffffffff9e3f0000, data after. Flat binary, no symbols.

## pdfork is compiled into Sony's kernel

Read straight out of the sysent table (file 0xe6e5c0, stride 48, `sy_call` at +8, nosys at
0xffffffff9e9520e0):

| syscall | nr | narg | handler |
|---|---|---|---|
| pdfork | 544 | 2 | 0xffffffff9e655d40 |
| pdgetpid | 545 | 2 | 0xffffffff9e655d48 |
| pdkill | 546 | 3 | 0xffffffff9e655d50 |
| pdwait4 | 616 | 2 | 0xffffffff9e655e70 |
| poll | 209 | 3 | 0xffffffff9e655a80 |
| aio_multi_delete | 661 | 4 | 0xffffffff9e655710 |

None of the pd* entries are nosys, so the procdesc subsystem is built in - the precondition for
CVE-2026-45251 holds at the dispatch level. Whether the sandbox *permits* an unprivileged process to call
pdfork is a separate, still-open question.

## Where the procdesc RE stands

Sony builds without INVARIANTS: the `procdesc_free: pd_proc != NULL` KASSERT strings are absent from the
image, so string-anchored identification does not work. The handlers are thunks
(`pdfork -> 0xffffffff9efa0150`), and the pdfork path calls into the procdesc code around
`0xffffffff9ef9f4d0`, which is the anchor for finding `procdesc_free` and checking whether it calls
`seldrain` (fixed) or jumps straight to `knlist_destroy` + `uma_zfree` (vulnerable, as in the FreeBSD 11.0
source). That is the next piece of work, and it is mechanical from here: locate the function, count its
calls before the zone free.

## The Lua entry, mapped

* Games: 18 supported, `Hamidashi Creative (CUSA27389)` and its demo (CUSA27390) among them.
* Constraint: **disc version recommended** - since 12.60/13.00 Sony added 30-day expirations to downloaded
  software used by these engines, so a digital copy may stop launching.
* Console must be **activated** to copy PS4 saves; save goes to USB, is decrypted and resigned through the
  HTOS service (`/decrypt`, `/encrypt`, `/resign` with PSN ID), then copied back.
* Reported working on 14.20, so 14.10 is covered. Payloads go to the loader on TCP 9026.
* This is the only public entry on 14.10 that already has libkernel/syscall access - i.e. the only way to
  *test* a kernel bug at runtime rather than argue about it statically.
