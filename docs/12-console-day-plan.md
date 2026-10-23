# Firmware 14.00 — console day plan

> Written 2026-10-23, for a retail 14.00 unit that will not be updated. Nothing here
> requires a jailbroken PS4, a second console, or network access beyond the LAN.

## 0. Before touching anything (5 minutes, read-only)

| Check | Where | Record |
|---|---|---|
| Exact firmware string | Settings → System → System Software | e.g. `26.06-14.00.00.xx` |
| Auto-download / auto-install | System Software → Update Settings | must be **off** |
| Update notification | Leave it; do not "check for update" | |
| PSN signed in? | Users → Account | Must be signed **out**; PSN now demands 14.10 |
| Board revision | Rear label / teardown later | `CFI-11xx`, `EDM-0xx` |
| Free space, USB present | Storage | needed for dumps later |

Write these into `docs/13-console-facts.md` — the firmware string is the anchor every
later claim hangs on, and the exact build number (`14.00.00.xx`) matters more than "14.00".

## 1. The one question that decides the day: do we have userland?

Everything downstream needs code execution inside some process. Two candidate routes:

**A. mast1c0re (PS2 savegame escape) — RESOLVED: not available.**
Its SDK ships PS5 `libkernel` offsets only for **3.00–3.21, 4.00–4.03, 4.50–4.51, 6.50**.
There is no 14.00 support, and the offsets are hand-derived per build, so this route would
need a decrypted `libkernel_sys.sprx` first. The "14.00 has mast1c0re userland" line in the
status hubs describes the bug class, not a usable toolchain.

> **Check first, in the repo:** the firmware table in `sdk/`, and whether the PS2 title
> the save exploit needs is still purchasable on your store region. If the game is
> delisted, route A is dead regardless of offsets.

**B. Artemis / Lua loader (Hamidashi Creative) — richer primitives, higher entry fee.**
Memory R/W API, unfiltered `make_syscall(N)`, thread creation with controlled registers,
TCP 9026. But the save must be decrypted and re-signed under a matching PSN Account ID,
and the documented route for that is **a jailbroken PS4 + Apollo Save Tool**. Without
either, route B is not available tomorrow.

**C. The Guide WebView — the only route actually available with no PS4.**
DNS-redirect `ps5.np.playstation.net` and `manuals.playstation.net` to a LAN host with a
self-signed cert and the console runs your JavaScript, no exploit required. Build and plan:
`14-guide-webview-entry.md`, `tools/fw1400/guide_lab.py`. This does **not** give the syscall
surface — for that, §3 below stays blocked on a jailbroken PS4.

## 2. Measurements that need no exploit

1. **Update-client capture (safe, high value).** The console's update client speaks plain
   HTTP to `pc.ps5.update.playstation.net`. Put it behind a LAN proxy or a DNS override
   and record the exact request the console makes, including headers. The 14.10 project's
   captured path 404s off-console, so a *live* request from a real 14.00 unit is the one
   artifact they lack. Do **not** let it download or install.
2. **Store/PUP reachability.** Confirm which URLs your console can actually reach and
   with what parameters; that is the input to any future 14.00 PUP acquisition.
3. **NOR/board identification.** Photograph the board, read the SPI flash part number,
   confirm `EDM-0xx`. Read-only, preps the hardware path.
4. **LAN baseline.** Fixed IP, `send_probe`-compatible port map, so a future loader can
   be reached without re-engineering the network.

## 3. If userland exists: the 14.00-vs-14.10 comparison battery

The single most valuable experiment available. The 14.10 project has ~1,200 saved probe
results; if 14.00 behaves identically on the safe subset, **those results are a usable
proxy for this console**, and any kernel bug they land applies here too. Where 14.00
differs, you have found exactly what Sony changed between the builds.

Run in this order, aborting on the first divergence you cannot explain:

| # | Probe | Why | Risk |
|---|---|---|---|
| 1 | `getpid`, `getppid`, `getuid` | sanity: ABI and return conventions | none |
| 2 | zero-argument sweep of **532–560** | cheap presence map; compare against `data/sysent_1360_resolved.json` | low |
| 3 | zero-argument sweep of **561** (13.60: `nosys`; 14.10: reported lethal) | resolves a real contradiction between the two datasets | medium — may kill the process, not the console |
| 4 | `624` repeated (13.60 scalar VM read; 14.10 returned `0xD31`/`0xD30`) | checks whether the value tracks page mappings | low |
| 5 | AIO presence: **661, 662, 664–670** with zero args | are the nine siblings still live on 14.00? This decides the whole kernel hunt | low with zero args |
| 6 | `aio_suspend` (315) | the only surviving FreeBSD-lineage AIO entry | low |

Record for each: return value, errno, whether the process survived, and the sequence
number. Anything that returns a plausible pointer-shaped value gets re-run three times
to check for ASLR variation.

## 4. Do not run on day one

These have documented kernel-panic behaviour on 14.10. A panic is recoverable but risks
the filesystem, and this is the only 14.00 unit you have:

- `thr_create(430)` with `CS=0` — the documented panic path (`ISPL(0)` → kernel-mode
  fault → `trap_fatal`). Only run with `CS=0x43`/`SS=0x3B`, and only after probes 1–5.
- `kld*` family (307, 308, 337) and `sysctlbyname` — reported process-killing.
- Any probe whose expected outcome is "unknown, maybe panic". The 14.10 project's
  `TODO.md` is full of written-but-unrun probes; they are unrun for a reason.

## 5. Capture discipline

- One directory per session: `dumps/1400-<date>/`, plus `notes.md` with the firmware
  string and every probe's raw output.
- Never overwrite a capture. The 14.10 project's biggest documented problem is
  contradictory evidence from overlapping runs, not missing data.
- Every claim in a later write-up must name the probe that produced it.

## 6. After the session

Run the toolchain on anything captured:

```bash
python3 tools/fw1400/identify_fw.py --manifest dumps/1400-<date>/manifest.json
python3 tools/fw1400/find_sysent.py --image <region>.bin --base 0x<base>
python3 tools/fw1400/sysent_resolve.py diff data/sysent_1360_resolved.json data/sysent_1400_resolved.json
```

A `diff` that reports "661–670 unchanged, 663 changed" is the best possible outcome:
it confirms the Sony AIO block survived 14.00's patch, and it points the probe battery at
nine functions that were never audited publicly.
