# Chain map: what a working 14.10 exploit actually needs, and which rung we are on

Written after Teo's steer: stop fuzzing, work out how entry points chain. The public Relapse chain
(7.00-13.60) is the ground truth for the architecture, and each of its stages can be checked against Sony's
14.10 tree instead of guessed at.

## The chain, with each gate named

**Rung 0 - delivery.** Attacker-controlled content must reach a JS engine on the console. Relapse uses the
YouTube app's cached `splash.html` (integrity not checked), i.e. V8/Cobalt, not WebKit. Our Guide WebView
gives JSC but the page must come from `manuals.playstation.net` over HTTPS - a lab DNS hijack is not an
attacker capability, so *deliverability is an open problem independent of the bug*.

**Rung 1 - engine compromise with a write primitive.** Relapse: "JSC info leaks and a structured clone
object pool mismatch to corrupt a typedarray". The needed output is not a crash, not a read - it is a
corrupted typed array, which yields `addrof` plus arbitrary read/write inside the WebProcess.

**Rung 1.5 - get out of the WebProcess.** The WebProcess is a separate `/app0/WebProcess.self` binary
(`ProcessLauncherPlayStation.cpp`, `MAKE_PROCESS_PATH`), spawned by Sony's `PlayStation::launchProcess`
with only `{fd, userId}` - WebKit passes **no sandbox profile**, so capabilities are fixed by the OS per
binary and are not in the OSS drop. The Y2JB route reached libkernel from the YouTube process; whether the
WebProcess may call the same syscalls is unknown and gates the whole chain.

**Rung 2 - kernel.** `aio_multi_delete` UAF (`prolapse`), alive on 14.00/14.10, killed in 14.20 by a
generation check. Needs the ability to issue the AIO syscalls from the compromised process - see rung 1.5.

**Rung 3 - privileges.** Kernel R/W then rewrites `ucred` (`cr_sceAuthID`, `cr_sceCaps`,
`cr_sceAttrs`), repoints `fd_cdir`/`fd_rdir` at `rootvnode`, which is what allows installing packages /
reaching Debug Settings.

## Checked against Sony's tree, not assumed

**Relapse's browser bug is dead here.** Fix `010c6bdfb0` (2024-01-26) split `m_gcBuffer` into
`m_objectPool` (indices that `ObjectReferenceTag` resolves against) and `m_keepAliveBuffer` (GC protection
only). Before the split, serializing a Map or Set appended `inMap`/`inSet` **and** `iterator` to the same
buffer the deserializer indexes, so every later object reference resolved to the wrong object - a clean
type confusion. Sony's tree has `m_objectPoolMap` and `m_keepAliveBuffer` and no `m_gcBuffer`, so the fix
is present. Note what that means: Sony backports *past* the 2023 base of this drop, so "the OSS zip is
17.0-era" is not evidence that a 2024 fix is missing.

Earlier rungs checked the same way: bug 278657 needs a growable `SharedArrayBuffer` (measured absent);
bug 309776's race needs `visitAdditionalChildrenInGCThread` (absent from the whole tree).

## What this implies for where to work

1. The critical path is **rung 1**: a JSC bug in Sony's 14.10 tree that yields a corrupted typed array.
   Read-only findings (font GSUB) and DoS findings (CSSOM) do not touch it.
2. Any candidate must be checked for *presence in this tree*, because Sony backports. The
   `patch_presence.py` gate does exactly that and is now the primary filter.
3. Before investing in a rung-1 bug, resolve rung 1.5: if the WebProcess cannot reach libkernel/AIO, a
   perfect WebKit exploit still dead-ends. That question is answerable from public research + the
   launcher/IPC surface, and it decides whether the Guide is even the right entry.
