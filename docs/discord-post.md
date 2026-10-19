# Discord post — ready to paste

Two versions. Use the short one in a busy channel if you want a reply without
derailing; use the long one in a dev/research channel.

Post in **#ps5-dev** (ps5-linux) first, then psdevwiki. BC-250 is a different
question — see the note at the bottom.

---

## Short version

> Been mapping the PUP outer container on current firmware — it's a two-level SLB2
> wrapper: entry table holds filenames (`PS5UPDATE1.PUP`, `PS5UPDATE2.PUP`), not
> component IDs, and the body from 0x200 is encrypted (scanned 96 MB, no nested
> SLB2, no plaintext ELF). So the 95-entry component table from the 5.50 writeup
> isn't at that level.
>
> Two questions: is the inner PUP reachable at all without console-side keys, and
> does anyone have a decrypted 13.xx/14.xx image they'd share? Happy to post my
> parser — read-only, no console interaction.

---

## Long version

> Been doing some container work on current firmware and hit a wall — wondering if
> anyone's gone further.
>
> What I verified myself, range-probing Sony's direct PUP URLs (2026_0928 release,
> so this is current, not 5.50):
>
> - Outer container is `SLB2`, format version 3
> - `0x08` flags: bit 24 (`0x01000000`) set only on the recovery PUP
> - Entry count: **1** for update, **2** for recovery
> - Entry table at `0x30`, 0x30-byte records — and the entries are **filenames**,
>   not component IDs: `PS5UPDATE1.PUP` and `PS5UPDATE2.PUP`
> - Constant `0x4B2F8A3D` at `0x24`, byte-identical across both files
> - Body from `0x200` is high-entropy. Scanned 96 MB on a stride: no nested `SLB2`,
>   no `\x7fELF` anywhere
> - Sanity check on my reading: recovery entry[0]'s first field (`2,463,688`)
>   equals the update PUP's `0x10` field exactly, and rec−sys comes to
>   `157,481,984` against `157,481,653` recorded in the entry — so recovery looks
>   like update + one ~157 MB payload, plus ~331 bytes of container overhead
>
> Which means the outer wrapper is two-level, and the 95-entry / 14-component-type
> table in the 5.50 writeup isn't this level — either that analysis was done on an
> exploded image, or the format differs from what it was.
>
> Two questions:
>
> 1. Is the inner PUP reachable at all without console-side keys, or is it
>    encrypted before storage?
> 2. Does anyone have a decrypted inner image from 13.xx or 14.xx they'd be willing
>    to share — or is the component table already documented somewhere I've missed?
>
> I'll post the parser if it's useful. Read-only, ~200 lines, no console interaction.

---

## Notes before posting

- **Don't lead with the memory-map question.** It's been asked a hundred times and
  reads as "give me the answer." Lead with the measurement you made — that's what
  gets a response from people who've done the work.
- **Don't mention the leak question** in these servers. It marks you as a tourist.
- If nobody answers in ~48h, reply to your own message with one concrete finding
  rather than bumping. Threads that contain data get answered; threads that ask
  get ignored.
- **BC-250 server is for a different question.** Don't ask them about PS5 boot
  chains — ask them about SMU mailbox messages, DDR init order, and the IOMMU
  register blocks. That's the bring-up knowledge you actually need from them, and
  it's knowledge they have.
