# Lua entry on a Digital Edition PS5 (firmware 14.10)

No disc needed. The entry is the **free demo** of *Hamidashi Creative* (CUSA27390, Artemis engine with embedded
Lua 5.1), which is on the **Japanese** PSN store and is one of the 18 supported games in
`n0llptr/remote_lua_loader`.

What this gets us: userland code execution inside the game process, with `memory.*` (arbitrary process R/W),
`syscall.*` / `make_syscall(N)` (raw syscalls, bypassing the loader's own filter - kernel restrictions still
apply), threading, and a ROP chain builder. That is the platform needed to *test* a kernel bug instead of
arguing about it.

## Steps

1. **Japanese PSN account.** Create one; the demo is not on the US/EU store.
2. **Download the demo** on the PS5: `Hamidashi Creative Demo` (CUSA27390). Free.
3. **Confirm the console is PSN-activated** - save transfer for PS4 games requires it.
4. **Play ~5 minutes** so the game writes a save, then quit.
5. **Export the PS4 save to USB:** Settings > Saved Data and Game/App Settings > Saved Data (PS4) >
   Copy or Delete from USB Drive. Note the save folder name (`id_<CUSA27390>_savedata`).
6. **Decrypt it without a PS4.** The community service HTOS (Discord) does this with `/decrypt`, setting
   `SCE_SYS` to FALSE. (The documented alternative is a jailbroken PS4 with Apollo Save Tool; you don't need
   that.)
7. **Drop the payload in:** in the decrypted folder, delete everything **except** `sce_sys/`, then copy every
   file from `save-payload/` here into that folder. All 24 files are required - `main.lua` pulls in the
   helpers, and `elfldr.elf` / `ps5-elfldr.elf` are what kernel-side probes reach for.
8. **Re-encrypt and resign** with HTOS `/encrypt` and `/resign`, using your PSN ID / account name.
9. **Import the save onto the PS5** and launch the demo. Expect a black screen, then the notification
   `remote lua loader` / `listening on <ip>:9026`.
10. **From the Mac**, send a probe:
    `python3 research/remote_lua_loader/payloads/send_lua.py probe-01-procdesc-permitted.lua`

Each TCP connection spawns a fresh process (so ASLR changes every time and nothing persists between probes).
If the connection resets, the previous probe took the process down - relaunch the game.

## Why probe-01 first

`CVE-2026-45251` (procdesc poll/select UAF) is present in the FreeBSD 11 base this kernel forks, and the 13.60
dump shows `pdfork`/`pdgetpid`/`pdkill`/`pdwait4` all dispatched to real handlers rather than `nosys`. What is
still unknown is whether the PS4-compat sandbox **permits** those calls. Probe 01 answers that without
forking: `pdgetpid(-1)` and `pdkill(-1,0)` must return -1 (EBADF) if the handler is reachable, and a killed
process means the sandbox refused. Only if it returns cleanly is the race worth building.
