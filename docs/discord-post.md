# Discord post — ready to paste

Post in **#ps5-dev** (ps5-linux) first, then psdevwiki. The position is now much
stronger than the first draft, because the layout is confirmed and the arithmetic
closes exactly.

---

## Short version

> Mapped the outer SLB2 container on current firmware (2026_0928) and closed the
> layout out numerically — `0x10 × 512` equals the on-disk size to the byte on both
> the system and recovery PUPs, entry spans and trailers all reconcile.
>
> Confirmed: header 0x20, `0x0C` = entry count (1 sys / 2 rec), `0x10` = total size
> in 0x200 blocks, entries at 0x20 at 0x30 stride = `{u32 block_offset×0x200, u32
> size, 8×0, char[0x20] name}`. Recovery = system payload (1,261,406,781 B) + a
> second 157,481,653 B payload, 451 B gap, 331 B trailer.
>
> Remaining wall is Layer 1. Has anyone got a 14.xx `.dec`, or is the container key
> documented anywhere public? Everything past the wrapper needs it.

---

## Long version

> Been mapping the PUP outer container on current firmware and closed the layout
> out numerically. Sharing in case it's useful, and because I've got one question
> I can't answer from public sources.
>
> **Confirmed layout** (2026_0928, verified against live Sony files):
>
> ```
> 0x00  4    "SLB2"
> 0x04  4    version = 3
> 0x08  4    flags — bit 24 (0x01000000) = recovery
> 0x0C  4    entry count — 1 = system, 2 = recovery
> 0x10  8    total size, in 0x200-byte blocks
> 0x18  8    zero
> 0x20  N*0x30  entries
>
> entry: +0x00 u32 block_offset (×0x200)
>        +0x04 u32 size
>        +0x08 8 bytes zero
>        +0x10 char[0x20] name
> ```
>
> **Proof it's right** — the arithmetic closes to the byte on both files:
>
> ```
> system   (1,261,408,256 B): 0x10 = 2,463,688 blocks × 512 = 1,261,408,256 ✓
>          entry[0] PS5UPDATE1.PUP  block 2 → byte 1,024  size 1,261,406,781
>          trailer 451 B
>
> recovery (1,418,890,240 B): 0x10 = 2,771,270 blocks × 512 = 1,418,890,240 ✓
>          entry[0] PS5UPDATE1.PUP  block 2         size 1,261,406,781  end 1,261,407,805
>          entry[1] PS5UPDATE2.PUP  block 2,463,688 size 157,481,653    end 1,418,889,909
>          gap 451 B · trailer 331 B
> ```
>
> So recovery = system payload + one extra ~150 MiB payload. Body is a 32-byte
> digest at 0x200 then high-entropy data from ~0x400; no nested SLB2, no plaintext
> ELF (scanned 96 MiB).
>
> Worth flagging: the 5.50 writeup's 95-entry / 14-component-type table isn't this
> level. Either it was done on an exploded image or the format moved.
>
> **The question:** everything past the wrapper needs Layer 1 (container
> encryption). TitaniaPy maps the stack with Layer 0 and Layer 3 solved and Layer 1
> blocked on a key that isn't public. Has anyone got a 14.xx `.dec` they can share,
> or is the container key documented anywhere I've missed?
>
> Parser is read-only, ~200 lines, prints the header-derived size and flags itself
> if the arithmetic stops closing. Happy to post it.

---

## Notes before posting

- **Lead with the arithmetic, not the ask.** "It reconciles to the byte" is what
  makes people reply. "Does anyone have X" alone gets ignored.
- **Don't mention the leak question** in these servers.
- **Don't offer keys, ask for keys, or hint at circumvention.** The question as
  written — "is the container key documented anywhere public" — is a literature
  question, which is fine. Keep it that way.
- If nobody answers in ~48h, reply to your own message with one concrete finding
  rather than bumping.
- **BC-250 server is a different question.** Ask them about SMU mailbox messages,
  DDR init order, and IOMMU register blocks — not PS5 boot chains. That's the
  bring-up knowledge you actually need from them.
