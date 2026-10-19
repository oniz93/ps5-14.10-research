# Resources

## Discord servers

| Server | Invite | Why |
|---|---|---|
| **psdevwiki** | https://discord.gg/2M9ECQPgPt | The PS reverse-engineering wiki's community. Best place for boot chain / hardware questions. |
| **ps5-linux** | https://discord.gg/PeMGVB7BAm | The people who actually boot Linux on PS5. HV exploit chain, offsets, UART work. |
| **BC-250** | https://discord.gg/8eZfFWhczz | Same Oberon APU with no Sony boot chain — the bring-up reference. 3,500+ members, heavily technical. |
| **Se7enSins** | https://discord.gg/Se7enSins | Forum where the PUP format writeup lives. |

**Day-one move:** post in psdevwiki + ps5-linux asking what's already known about the
SELF load map, the LDLR container format, and whether any decrypted 13.xx/14.xx image
is available. Ask before building.

## Wikis & forums

- psdevwiki PS5 — https://www.psdevwiki.com/ps5/ (see `ps5/Hypervisor`, `ps5/Vulnerabilities`)
- Se7enSins PS5 forum — PUP format RE thread, tooling, modding tutorials
- GBAtemp PS5 forum — active PUP decryption research threads
- BC-250 docs — https://elektricm.github.io/amd-bc250-docs/

## Firmware archive

- https://darthsternie.net/ps5-firmwares/ — 66 official + 60 recovery PUPs, MEGA mirrors.
  Includes 14.10, 14.00, 13.60, 13.42, 13.40, 13.20, 13.00, 12.70 …

## Tools & repos

### PUP / firmware
- `zecoxao/ps5-pup-unpacker` — unpack decrypted PUPs
- `zecoxao/ps5-pup-decrypt` — console-side PUP decryption
- se7ensins `pup_extract.py`, `analyse_extracted.py` — PC-side structure parsing

### Boot chain / Linux on PS5
- `ps5-linux/ps5-linux-loader` — HV-patch route to Linux; keeps Sony's chain.
  `source/offsets.c` is the address reference for every supported firmware.
- `ps5-linux/ps5-linux-patches`, `ps5-linux/ps5-linux-tools`
- `ps5-payload-dev/sdk` — payload SDK (what the community payloads build against)
- `flatz` HV exploit gist — the original hypervisor break
- `cragson/ps5-hen` — HV exploit implementation
- `fail0verflow/prosperous` — loader prior art
- `symbrkrs/ps5-uart` — EMC UART unlock via Raspberry Pi Pico (Stage 2)

### Hardware / bring-up reference
- `elektricM/amd-bc250-docs` — Linux setup, BIOS, SMU governor, 8-core unlock via SMN
  `0x0115A870` written through SMU mailbox message `0x98`. Real SMU mailbox examples.
- `mothenjoyer69/bc250-documentation`
- `akandr/bc250` — setup, benchmarks, configs

## Key facts to keep straight

- BootROM verifies **only** LDLR. Fused **symmetric** keys. Leaked → custom LDLR possible.
- The leaked keys do **not** sign LV2 or the kernel. They decrypt/forge LDLR, nothing else.
- If you replace LDLR, LV2 is optional. Your loader decides what runs.
- LV2 is what enforces XOM (`EFER.nda`), CR0.WP, SMEP/SMAP, nested page tables, and IOMMU.
  Skipping it means re-implementing that bring-up yourself.
- Anti-rollback (syscon/NOR) blocks **downgrades**. It does not block overwriting flash
  with your own image — different problems.
- There is **no complete public physical memory map**. Treat any claimed full map as unverified.

## Known addresses (from `ps5-linux/ps5-linux-loader` `source/offsets.c`)

- Kernel text virtual base: `0xFFFFFFFF80210000`
- Hypervisor code-cave physical: `0x62806F00`
- Per-firmware and variable: `HV_HANDLE_VMEXIT_PA`, `IOMMU_SOFTC`, `VMSPACE_VM_PMAP`,
  `DATA_BASE_GVMSPACE`, `KERNEL_CODE_CAVE`, IDT, TSS — always read the table for the
  target firmware version.

## Legal

- DMCA §1201 (US) and Copyright Act s.41.1 (Canada) apply to trafficking in
  circumvention tools. Analysis and read-only tooling: fine. Bootable circumvention
  images: never published.
- Sony HackerOne (hackerone.com/playstation) explicitly excludes jailbreak work.
