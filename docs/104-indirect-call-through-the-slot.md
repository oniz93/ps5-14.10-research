# 104 — with a live module address in the slot the engine executes `call *(*value + 0x20)`, and slot 4 is `sinkIntoImageBuffer`

**Status:** measured 2026-10-30, quarantine and malloc fill **off**. This is the first arm where the value planted
in the `docs/94` slot is a *real address of the running image*, and the report names what the engine did with it.
It converts the slot from "a pointer that faults" into **an indirect call whose target is resolved through the
bytes we choose** — with one caveat that decides how a fake vtable must be built (§3).

## 1. Harness: the address comes from the run, not from a guess

The slot's low byte is forced to `0x00` (the serialize stream's length MSB sits at element+8, `docs/101`), so
only 256-aligned values are expressible. `research/canvas-alias/vrun.sh` therefore:

1. starts the browser with the page pointing at `/live/ptr.txt`,
2. reads `/proc/<WebKitWebProcess>/maps` **of that run**, takes the first `libwebkit2gtk-4.1.so` mapping as the
   base, computes `base + <offset>`, rounds it **down** to 256 and writes it to `ptr.txt`,
3. the page (`vcall.html`) polls the file and only then fires the clone arm.

No ASLR disable, and the value is a genuine address of that process. `max_malloc_fill_size=0` is mandatory here:
with the fill on, an allocation after the clone re-fills the slot and every value crashes (`docs/101` §1).

## 2. What the engine does with it — five arms, the fault address tracks the target

| arm | target offset | ASAN fault | the qword at the target |
|---|---|---|---|
| `vc_vt` | `0xe153e00` (vtable of `DefaultSerializedImageBuffer`) | `0x0000000000000020` | offset-to-top = 0, so `*(vptr)` is 0 |
| `vcf_0x7f800` | `0x7f800` | **`0x00000e070118`** | `0xe0700f8` |
| `vcf_0x83d00` | `0x83d00` | **`0x00000e0728c8`** | `0xe0728a8` |
| `vcg_0x84600` | `0x84600` | **`0x00000e072dc8`** | `0xe072da8` |
| `vcg_0x94b00` | `0x94b00` | **`0x00000e07d730`** | `0xe07d710` |
| `vcg_0x98a00` | `0x98a00` | **`0x00000e081070`** | `0xe081050` |

Every fault is exactly `qword_at_target + 0x20`, and the top frame is `ImageBuffer.cpp:119`
(`return buffer->sinkIntoImageBuffer()`). So the sequence is proven end to end:

```
element+8 -> this            (our value, mapped and chosen)
*(this)   -> vptr            (bytes at the address we planted)
call *(vptr + 0x20)          (fault or execution)
```

`0x20` is **slot 4**, and slot 4 is `sinkIntoImageBuffer`: the vtable order is `~SerializedImageBuffer` (D1, slot
0), D0 (slot 1), `memoryCost()` (2), `isRemoteSerializedImageBufferProxy()` (3), `sinkIntoImageBuffer()` (4)
(`platform/graphics/ImageBuffer.h:248-259`). The engine is calling exactly the virtual the exploit needs.

Note the readout: these values are canonical and small, so ASAN prints them — unlike the high pointers earlier in
this programme, which print only `pc`.

## 3. The caveat: those qwords are link-time, so a fake vtable needs `base + …`

The fault addresses are `0xe07…`-style, not `0x7f…`, i.e. **the vtable pointers stored in the static tables of
this build are link-time offsets, not relocated runtime addresses.** A second-level dereference is therefore out
of reach for the page on its own: `*(value)` yields an offset, and the call goes to an unmapped low address.

For an exploit that is a small, well-understood problem, not a wall: once anything leaks `base`, the fake vtable
is `base + *value`, and the *page* only has to add a constant it already holds from the same dump. What the arms
above fix is the part that used to be guesswork — the indirection shape and the slot index.

## 4. What a real (non-faulting) call now needs

The call needs `*(value) + 0x20` to be a **runtime** code address, so `value` has to point at memory the engine
has already relocated:

1. **A live heap object with a vtable** — then `*(value)` is a relocated vptr and slot 4 resolves into a real
   function. Any `ImageBitmap`-adjacent object is a candidate if its address can be learned; this is exactly the
   leak that `docs/95`/`docs/98`/`docs/100`/`docs/102` could not produce from an API.
2. **A writable buffer we fill with a vptr ourselves** — needs the buffer's address, and needs `base` to build the
   value, so it reduces to (1) plus arithmetic.
3. **The `.got`** holds runtime code pointers, but slot arithmetic still reads `code+0x20` as a *pointer known
   only at runtime* — worth one arm once `base` is available, and the cheapest remaining experiment that needs no
   leak of a heap address (only of `base`).

## 5. Limits

- One target per run (a fault ends the process); the harness is a validator, exactly like `docs/101`.
- The offsets are this ASAN build's `libwebkit2gtk`; the console's `libSceNKWebKit` differs, so both the target
  table and possibly the relocation behaviour have to be re-derived there.
- The round-down to 256 means a target can be at most 255 bytes early; the six arms above show the effect is
  benign when the qword at the rounded address is still a pointer.

## 6. Commands

```
bash research/canvas-alias/vrun.sh vc_7f800 10520 30 0x7f800 'tmo=20000'
```

`vrun.sh` kills only its own port, ships `vcall.html`, resolves the address, decodes beacons, prints the
`ERROR/SUMMARY` line and the top two frames. Logs `/tmp/S_vc_*.log`, `/tmp/srv105*.log`.
