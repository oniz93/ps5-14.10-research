# BC-250 state: Steam is stopped (2026-10-30)

Stopped at the user's request so the board is a dedicated build/probe host. Restore it when he asks.

## What was done

The Steam Deck UI runs as a *user* unit, `gamescope-session-plus@steam.service`. A plain `stop` did nothing useful: an
autologin supervisor (`/usr/bin/sh /usr/bin/gamescope-session-plus steam`) re-issued
`systemctl --user --wait start ...` within seconds, and the unit itself is `Restart=no`, so the restart came from the
supervisor rather than systemd. Holding it down therefore needs a **mask**:

```bash
ssh teo@<lab-ip> 'export XDG_RUNTIME_DIR=/run/user/1000;   systemctl --user mask gamescope-session-plus@steam.service;   systemctl --user stop gamescope-session-plus@steam.service'
```

State after: `is-active` → `inactive`, `is-enabled` → `masked`, no `steam*`/`gamescope*` processes left apart from the
two small `steamos-manager` daemons (~17 MB total).

## Measured effect

| | before | after |
|---|---|---|
| VRAM used | ~512 MiB (gamescope) | **24 MiB** |
| GTT used | — | 13 MiB |
| RAM free | ~12.4 GiB avail | ~10–12 GiB avail (varies with the running probe) |

VRAM is the useful part: the desktop session held the 512 MiB carve-out, which is exactly the pool the ASAN browser
and any GPU-adjacent probe compete for.

## Restoring it

```bash
ssh teo@<lab-ip> 'export XDG_RUNTIME_DIR=/run/user/1000;   systemctl --user unmask gamescope-session-plus@steam.service'
```

then either reboot the board (autologin brings the session back) or start it at the physical console. Starting it
over SSH will not attach it to a seat reliably — logout/reboot is the honest route. **Do not forget the unmask**: a
masked unit fails silently at autologin and the console comes up to a black screen with no UI, which is easy to
misread as a fault.

## Where the procedure lives

The durable version of both halves — the CMOS `UMA_SIZE` VRAM split and taking the Steam session down — is in the
`ps5-boot-chain` skill, `references/local-engine-build.md` ("The build host itself"). This file records only the
*current state* of this board; if the two ever disagree, the skill is the procedure and this is the snapshot.

## Why this is in the repo rather than chat

Any run that needs GPU memory or more RAM now depends on Steam staying down, and any run that restarts the board
inherits a masked unit. Recording the mask here stops a future session from chasing "black screen on the BC-250" as a
hardware failure.
