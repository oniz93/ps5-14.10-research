# ps5-uart firmware gate — the EMC exploit is not universal

Found 2026-10-19 by reading the source after ordering hardware. This corrects an
earlier claim in `06-loader-port-requirements.md` that the EMC UART route "works
today, needs no jailbreak."

## The gate

`tool.py`, lines 359–362:

```python
def emc_uart_bug_is_patched(self):
    version = self.cmd_send_recv('version')
    # TODO check if version >= "E1E 0001 0008 0003 1B9B" (fw 5.10)
    # last known vulnerable version is "E1E 0001 0008 0002 1B03" (fw 5.02)
```

`uart/ps5_uart.cpp`, the `fw_constants_map` — **four entries only**:

| EMC firmware string | Notes |
|---|---|
| `E1E 0001 0000 0004 13D0` | oldest supported |
| `E1E 0001 0002 0003 1580` | |
| `E1E 0001 0004 0002 1752` | |
| `E1E 0001 0008 0002 1B03` | **newest — system FW 5.02**, per the comment above |

For any other version string, `set_fw_consts` returns `kFwConstsVersionUnknown` and
`emc.unlock()` has no shellcode to run.

## Why this blocks the whole chain

```
emc.unlock()          ← the overflow in the EMC UCMD parser; gated as above
  └─ emc.unlock_efc() ← starts with emc_write(0x13423A, ...), needs the unlocked set
      └─ emc.load_eap()
          └─ NAND access, EAP/EFC shells, memory reads, dumps
```

Everything downstream of `unlock()` needs the unlocked command set. There is no
side door in the documented flow.

## Not in the README

The requirement exists only as a code comment. The README says nothing about
firmware versions. This is the single most expensive omission in the project for
anyone who owns a modern console, and it is why the notes should be read from source
rather than from the front page.

## Is it strictly impossible on 14.x? Not provably — but not reachable

`pico_fw_const(version, buf_addr, shellcode)` accepts **arbitrary** constants, so the
tool can be taught a new firmware version. To do that for 14.x you would need:

1. the `ucmd_ua_buf_addr` for that EMC firmware version, and
2. shellcode assembled for that version's parser

Both require the EMC firmware image. That image is `emc_ipl` (PUP entry `0x200`) —
behind Layer 1 encryption, which is the same wall as everything else. Nobody has
published these constants for any firmware past 5.02.

## What survives

| Thing | Status |
|---|---|
| The wiring, pinout, I²C map, header location | **Still correct.** The cable isn't gated. |
| `titania/` NAND decode | **Works offline on any dump** — no console, no Pico, no firmware limit |
| `uart/notes/` logs (EAP MMIO map, PSQ sequence, ABL timeline) | **Still valid** — measured on real silicon |
| `emc.unlock()` on a 14.10 console | **Blocked** |
| The Pico itself | Fine hardware; correct for a ≤5.02 console |

## The one untested door

Pulling **EMC GPIO A1 low at boot** drops the EMC into its **mask ROM** UART shell at
460800 — not the patched firmware. ROM is immutable and can never be patched.

`tool.py` contains `rom_cmd`, `rom_send` and `rom_jump`, and builds an IPL-style
sector image (MBR fields, `ipl_offset`, `ipl_size`) before jumping. So the ROM
bootloader path exists in the code and someone was exploring it.

What is **not** known: whether that ROM shell gives enough to be useful on a modern
console. It is the only genuinely unpatchable entry point on this hardware, and it is
unexplored territory rather than a recipe.

## Corrected guidance

- **Don't** open a 14.x console expecting the documented flow to work.
- **Do** consider the ROM path as a research question, with no expectation of a dump.
- **Do** keep the Pico — it is the right tool for a ≤5.02 console.
- **Or** skip hardware and work from a NAND dump someone else took; `titania/` reads
  those without any console at all.
