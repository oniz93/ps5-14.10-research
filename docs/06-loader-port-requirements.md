# What a 14.x port actually requires

Derived from `ps5-linux/ps5-linux-loader` `source/offsets.c`, `gzimbric/ps5-linux-porting`,
and the PUP crypto layering in `04-slb2-format-confirmed.md`.

## Current loader coverage

`offsets.c` defines one `offset_list` per firmware. Present today:

```
3.00 3.10 3.20 3.21 4.00 4.02 4.03 4.50 4.51
5.00 5.02 5.10 5.50 6.00 6.02 6.50
7.00 7.01 7.20 7.40 7.60 7.61
13.00 13.20 13.60
```

**Absent: 8.x, 9.x, 10.x, 11.x, 12.x, and 14.x.** Mainline has a gap from 7.61 to
13.00; forks (`soniciso1`, `pLabs5`) fill parts of it. 14.x is empty everywhere.

## Cost of a port, measured in addresses

| Firmware | Fields in `offset_list` |
|---|---|
| 3.00 | 21 |
| 7.00 / 7.61 | 28 |
| 13.00 / 13.60 | **53** |

The table grew by 32 fields between 3.00 and 13.00 — mostly ROP gadgets and
hypervisor-call anchors that newer firmware required. A 14.x table is a **53-address
RE job minimum**, plus whatever 14.x adds on top.

What those 53 are, by category:

- **Kernel structures** — `IOMMU_SOFTC`, `VMSPACE_VM_VMID`, `VMSPACE_VM_PMAP`,
  `DATA_BASE_GVMSPACE`, `ACPIGBL_FACS`, `IDT`, `COMMON_TSS`, `DATA_CAVE`
- **Functions** — `FUN_PRINTF`, `FUN_MEMCPY`, `FUN_HV_IOMMU_SET_BUFFERS`,
  `FUN_HV_IOMM_WAIT_COMPLETION`, `FUN_SMP_RENDEZVOUS`,
  `FUN_SMP_NO_RENDEVOUS_BARRIER`, `HV_MP_STARTUP_CALL`, `MP_STARTUP_INIT_VECTOR`
- **~18 ROP gadgets** — `GAD_IRETQ`, `GAD_WRMSR_RET`, `GAD_SET_DR7_RET`, the
  `GAD_POP_*` set, `GAD_REP_MOVSB_RET`, …
- **Hypervisor** — `HV_CODE_CAVE_PA`, `HV_HANDLE_VMEXIT_PA`, `KERNEL_CODE_CAVE`,
  `HV_EFI_MAP_ROOT`, `NVS_SIGNATURE`
- **Display/audio** — `G_VBIOS`, `FUN_TRANSMITTER_CONTROL`, `FUN_MP3_INITIALIZE`,
  `FUN_MP3_INVOKE`
- **Misc** — `KERNEL_UART_OVERRIDE`, `KERNEL_CFI_CHECK`, `PS5_WIFI_FW_OFFSET/SIZE`

Every one is a **file offset inside the kernel or hypervisor binary**. You cannot
guess them; you read them out of the actual image.

## The seven boundaries beyond offsets

From `gzimbric/ps5-linux-porting` (the only public write-up of a successful
high-firmware port — 11.60, runs 15–17, HDMI and Wi-Fi working):

> A working hypervisor bypass is necessary for high-firmware Linux, but it is not
> the whole Linux port. The loader must also:
> 1. preserve a known-good bypass state across the payload-requested rest and
>    operator wake cycle;
> 2. load and stage the kernel, initrd, boot parameters, and identity map;
> 3. move every CPU out of the hypervisor through a controlled VM exit;
> 4. prevent one CPU from reaching the Linux barrier before its peers;
> 5. switch to the identity page table and a valid per-CPU stack;
> 6. park secondary CPUs and let one bootstrap CPU enter Linux;
> 7. provide firmware-appropriate memory, ACPI, IOMMU, VRAM, and command-line data.

> Most of the repeated 11.60 crashes came from treating one of those boundaries as
> if it were only an offset substitution.

Number 7 is the memory map. It is not optional and it is not derivable from the PUP.

## Dependency order (this is the real answer)

```
1. A jailbreak for 14.x            ← DOES NOT EXIST
2. Kernel R/W on 14.x              ← needs 1
3. Dump kernel + hypervisor        ← needs 2
4. RE the 53 offsets               ← needs 3
5. HV bypass for 14.x              ← needs 2
6. Loader port (7 boundaries)      ← needs 4 + 5
7. Per-firmware memory/ACPI/IOMMU/VRAM ← needs 6, empirical
```

## Where the decoded PUP sits — and why it is not the next step

A `.dec` would give: component list, sizes, **SELF headers with load addresses and
entry points**, segment layout. That is genuinely a piece of the memory map.

It would **not** give the kernel code. The crypto layers are:

| Layer | What | Gates the code? |
|---|---|---|
| 0 | PBKDF2 master derivation | solved, public |
| 1 | PUP container encryption | **blocked** — key not public |
| 2 | PUP segment-level | blocked behind 1 |
| 3 | Inner firmware (EMC/EAP) | solved, static keys public |
| 4 | SELF segment encryption | per-binary keys in Aeolia secure storage — **not public** |

So even with a `.dec`, the kernel image stays encrypted at layer 4. **You get the map,
not the code — and the 53 offsets need the code.** Therefore:

- The `.dec` **cannot** produce a 14.x offset table.
- The `.dec` requires a jailbroken **≤13.60** console, which is a different
  console requirement from the one blocking everything else.
- It sits off the critical path.

**The next real step is not the PUP. It is a jailbreak for 14.x — and nothing in the
public research changes that.**

## The two ways to actually get moving

**A. Hardware, on a console ≤ 5.02 firmware.** EMC UART (`symbrkrs/ps5-uart` + RP2040)
→ EMC shell → NAND dump → empirical memory map.

**This does not work on 14.x, or on anything past 5.02.** See `09-uart-firmware-gate.md`.
The `emc.unlock()` step is an overflow in the EMC's UCMD parser, and the tool ships
shellcode for exactly four EMC firmware versions, the newest being `E1E 0001 0008 0002
1B03` (system FW 5.02). On any newer console the tool returns `kFwConstsVersionUnknown`
and there is nothing to unlock.

So this route requires buying a ≤5.02 console, not using the one you have.

**B. Buy a second console on ≤7.61.** `ps5-linux` fully supports 3.00–7.61 with
HDMI, M.2, USB, BD, Bluetooth and Ethernet. If the goal is to *do the work*, that is
a supported platform today, and it's the standard move in this scene. A low-firmware
used PS5 is the cheapest research instrument available to this project.

Everything else is waiting, and waiting is not a step.
