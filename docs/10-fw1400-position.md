# Firmware 14.00 — what is alive, what is dead, and the one rung that is missing

> Verified 2026-10-23. Written for a retail **14.00** console that will not be updated.
> Every claim below carries its source; anything inferred is labelled as inference.

## 1. The patch boundary, precisely

| Firmware | What it closed | Evidence |
|---|---|---|
| 13.60 | *still open* — latest fully exploitable build | Relapse ships `offsets/` for 7.00–13.60 only |
| **14.00** | Relapse kernel bug: `aio_multi_wait` decrement UaF + `get_aio_debug_request_info` info leak | Relapse README range ends at 13.60; psdevwiki `Vulnerabilities` lists the bug as `?5.00–13.60` |
| **14.00** | **NOT** the hypervisor bug | Byepervisor-Reborn README, quoted in full below |
| 14.10 | the hypervisor bug — S3-resume `khv_startup_mp` AP-launch | Sonic_Iso, confirmed ~Oct 3–4 2026 |
| 14.20 | reportedly the A53 coprocessor (`/dev/ajm`) vector; userland reportedly reached within hours | notebookcheck 2026-10-21; unverified |

Byepervisor-Reborn's README, verbatim:

> "However this bug should technically be exploitable as low as 6.xx. With modifications,
> it could work on 14.00 as well, but this is not provided here, especially since there
> is no public 14.00 kernel exploit anyways."

That sentence is about **missing offsets**, not about the bug being fixed. So:

- **14.00 keeps the hypervisor vector. 14.10 destroys it.** Updating 14.00 → 14.10 trades the only live
  HV rung for nothing: 14.10 has no public kernel exploit either.
- The cost of staying: PSN has required 14.10 since ~13–15 Oct 2026, and *GTA 6* reportedly
  requires it too. A 14.00 console is now an **offline research unit**, not a console.

## 2. The useful discovery: 14.00 and 14.10 share the kernel data layout

Upstream `ps5-payload-dev/sdk`, `crt/kernel.c`, collapses both firmware IDs into a single case block:

```c
case 0x14000000:   /* 14.00 */
case 0x14100000:   /* 14.10 */
  KERNEL_ADDRESS_TEXT_BASE        = KERNEL_ADDRESS_DATA_BASE - 0x0CE0000;
  KERNEL_ADDRESS_ALLPROC          = KERNEL_ADDRESS_DATA_BASE + 0x28D9EA0;
  KERNEL_ADDRESS_SECURITY_FLAGS   = KERNEL_ADDRESS_DATA_BASE + 0x0DA4064;
  KERNEL_ADDRESS_ROOTVNODE        = KERNEL_ADDRESS_DATA_BASE + 0x315B510;
  KERNEL_ADDRESS_BUS_DATA_DEVICES = KERNEL_ADDRESS_DATA_BASE + 0x20A8878;
  KERNEL_OFFSET_VMSPACE_P_ROOT    = 0x1d0;
  KERNEL_OFFSET_VMSPACE_VM_PMAP   = 0x2e8;
```

and `ps5-payload-dev/ftpsrv`, `self-prospero.c`:

```c
case 0x1400:
case 0x1410:
  KERNEL_ADDRESS_PAGER_TABLE = KERNEL_ADDRESS_DATA_BASE + 0xE13E00;
```

`D` = live kernel data base, supplied by whatever payload/exploit is running. Derived:

| Symbol | Expression | Note |
|---|---|---|
| kernel text base | `D - 0x0CE0000` | |
| `allproc` | `D + 0x28D9EA0` | proc list head |
| `security_flags` | `D + 0x0DA4064` | `targetid = +0x09`, `qa_flags = +0x24`, `utoken_flags = +0x8C` |
| `rootvnode` | `D + 0x315B510` | |
| `bus_data_devices` | `D + 0x20A8878` | |
| pager table | `D + 0xE13E00` | FTP SELF mapper |
| `vmspace.p_root` | `+0x1d0` | |
| `vmspace.vm_pmap` | `+0x2e8` | |
| `proc.p_ucred / p_fd / p_pid / p_vmspace` | `0x40 / 0x48 / 0xBC / 0x200` | firmware-independent in this SDK |

**Consequence:** any 14.10 kernel dump, leak or offset set transfers to 14.00 for these symbols,
and vice versa. The 14.10 open research project's kernel work is therefore not stranded from
this console — it is one build away from being directly useful. Conversely, a 14.00 dump would
serve the 14.10 project.

## 3. Drift since 13.60 (for validating any future dump)

From the `0x13600000` case in the same file, versus the 14.00 block above:

| Symbol | 13.60 | 14.00 | delta |
|---|---|---|---|
| text base | `D - 0x0CC0000` | `D - 0x0CE0000` | −0x20000 |
| `allproc` | `+0x28C9E80` | `+0x28D9EA0` | +0x10020 |
| `security_flags` | `+0x0D9C064` | `+0x0DA4064` | +0x8000 |
| `rootvnode` | `+0x314B510` | `+0x315B510` | +0x10000 |
| `bus_data_devices` | `+0x2098228` | `+0x20A8878` | +0x10650 |

Small, uniform drift — consistent with a single build bump. That makes a 14.00 image
pattern-matchable: if you ever hold a dump, these six relations are a cheap correctness test.

## 4. The ladder on 14.00, rung by rung

```
userland        mast1c0re (public, 14.00 per ps5jbstatus)  —  or the Artemis/Lua loader,
                which is a game-side bug and therefore probably firmware-agnostic (unverified on 14.00)
kernel R/W      ** MISSING **  ← the entire problem
HV bypass       Byepervisor-Reborn (public, ≤13.60; author says 14.00 "with modifications")
kernel dump     needs R/W + HV
decrypted HV    needs the dump
```

Everything above the missing rung is published and waiting. Nothing below it can start.
So the entire research programme on this console reduces to **one kernel R/W bug on 14.00**.

## 5. Ranked work, 14.00-specific

1. **Freeze.** Auto-update off, no PSN sign-in. 14.10 is the destructive update for this unit.
2. **Hunt the kernel rung where Sony patched narrowly.** 14.00's kernel diff is anchored on
   `vfs_aio.c`: Sony closed `aio_multi_wait` and the `get_aio_debug_request_info` leak. Narrow
   patches leave siblings — the rest of the AIO family, other `copyout`-on-uninitialised paths.
   The 13.60 dossier set in `research/PS5-14.10-Research/docs/dumps_13.60/` (145 handler samples,
   15 MB text prefix, 679-entry sysent) is the decompilation base, and it is one build away.
3. **Sweep the open 2026 FreeBSD candidates** the 14.10 project already flagged but could not
   reach: `CVE-2026-49412` (IPV6_MSFILTER setsockopt UAF), `CVE-2026-58083` (kqueue timer
   knote UAF), `CVE-2026-7270` (execve argument overflow). Unresolved on PS5, not disproven.
4. **Build the validate-on-arrival harness now.** A script that takes any future dump or leak and
   checks the six relations in §2 plus `allproc → p_pid` chain consistency. Zero console needed,
   and it converts a lucky break into an offset table in minutes instead of weeks.
5. **Hardware path, unchanged and independent.** NOR dump (read-only, safe) gives `bootloader0`/LDLR
   — the stage-1 route that needs nobody's exploit. EMC UART remains gated at ≤5.02.

## 6. Honest odds

A solo researcher finding a 14.00 kernel R/W bug is a months-long bet with a real chance of zero,
against a scene that is actively working the same surface. The counterweight: the payoff is larger
than on any other retail build, because 14.00 is the newest firmware that still has a live,
publicly-implemented hypervisor bug behind it. That combination — HV bug alive, kernel layout known,
13.60 corpus in hand — exists on exactly one firmware, and it is the one on the shelf.
