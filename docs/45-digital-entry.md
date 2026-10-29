# Digital-edition entry: free demo + Lua loader (no disc)

Teo's console is a Digital Edition, so the disc-based advice is out. The entry still exists and costs nothing.

## The path

`Hamidashi Creative Demo` (CUSA27390) is **free on the Japanese PSN store** and is one of the 18 games the
Remote Lua Loader supports. The 14.10 research uses exactly this game ("Save file exploit via PS4 backwards
compatibility"). Artemis engine, embedded Lua 5.1.

What it yields once running: userland code execution in the game process with `memory.*` arbitrary R/W,
`syscall.*` and `make_syscall(N)` raw syscalls, threading, and a ROP chain builder. That is the only public
platform on 14.10 with libkernel access, and therefore the only way to *test* a kernel bug rather than argue
about it statically.

## No PS4 required

The documented route assumes a jailbroken PS4 for the decrypt/re-encrypt step. The community HTOS service does
the same work remotely (`/decrypt` with `SCE_SYS=FALSE`, then `/encrypt` and `/resign` with the PSN ID), so a
Digital PS5 + PC + USB stick is enough.

## What is packaged here

`deliverables/lua-entry/`
  `probe-01-procdesc-permitted.lua`   first probe: does the sandbox allow the pd* syscalls at all?
  `README.md`            the entry class and the procedure

The loader payload itself (24 files, `.iet` injection script, game save) is **not**
distributed in this repository — it is third-party artefact code with no licence stated.
Provenance and re-fetch instructions: `research/UPSTREAM.md`, `NOTICE.md` §"Removed
third-party code".

## Why probe 01 is deliberately boring

`CVE-2026-45251` is present in the FreeBSD 11 base (procdesc_free has no seldrain) and the 13.60 dump shows
pdfork(544), pdgetpid(545), pdkill(546) and pdwait4(616) dispatched to real handlers rather than nosys. What
is unknown is whether the PS4-compat sandbox permits those calls. Probe 01 answers that without forking:
`pdgetpid(-1)` and `pdkill(-1,0)` must return EBADF if the handler is reachable, and a dead process means the
sandbox refused. Forking first would create a child that keeps running the engine's Lua and would take the
game down before we learned anything.

## Where the kernel RE stands (scripted pass)

- sysent table (file 0xe6e5c0, stride 48, sy_call +8) parsed: the pd* family is implemented.
- The zone-name string `procdesc` is referenced at `0xffffffff9f0249ab`, inside a function that does
  `mtx_init(&pd->lock, "procdesc", NULL, MTX_DEF)` - i.e. the procdesc allocator cluster, which is where
  `procdesc_free` lives.
- Sony builds without INVARIANTS, so the `procdesc_free` KASSERT strings are absent and string-anchored
  identification fails. Confirming the `seldrain` call needs a real disassembler session (Ghidra) rather than
  byte-scanning; that is the next piece of static work, and it is independent of the console.
