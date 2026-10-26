# What the two 14.10 repos add, and the three bugs in our own probes

## pastawithpesto/PS5-14.10-Jailbreak-Research (same bug as ours)

It works CVE-2026-43720, the canvas `getContext()` re-entrant UAF, and its documented device results line up
with what we reproduced independently (`c014`: alias at index 4, readback 777.25, survived). What it adds:

* **bmalloc class 67** holds the 712-byte `CanvasRenderingContext2D`, and a **768-byte ArrayBuffer lands in the
  same class** - which reconciles our ASAN-measured 712 with the 768 used in AB sprays. Both numbers were right
  about different things: 712 is the object, 768 is the allocation that reuses its slot.
* **Gigacage disabled, IsoHeap disabled** (`BPLATFORM(PLAYSTATION)`, `bmalloc/Gigacage.h:43-47`), so AB backing
  stores share FastMalloc with WebCore/JSC objects. Same conclusion as the CSSFontFace write-up.
* **StructureID has no runtime validation**: `decode(bits) = (bits & 0x7FFFFFF) + startOfStructureHeap()`, and
  `ASSERT_WITH_SECURITY_IMPLICATION` compiles to nothing in release. So a corrupted JSObject cell header gives
  type confusion with no check - relevant once we can write.
* **Memory limits**: ~1200MB of ArrayBuffers before the WebContent process is OOM-killed; 5000+ concurrent
  buffers OOM during compilation. Our sprays of 500 are comfortably inside that.
* Documented dead ends worth not repeating: CSSFontFace UAF is DoS-only here (sole 192-byte occupant),
  butterfly UAF is pinned by conservative GC, MetadataTable overflows OOM, UMTX is stubbed on 14.10.

Caveat, stated plainly: the README's "ASLR defeat CONFIRMED, APNG overread leaks 1651 heap pointers (V674)" has
**no probe and no result artifact in the repo** - only prose in four docs and a `progress.json` field. Their own
`CONFIRMED_VULNS.md` still lists the info leak as *"Current blocker: all 12 Canvas2D APIs return typed JS
values - no path found to read a raw heap pointer"*, and `docs/DEAD_ENDS.md` records freed-memory reads crashing
because the destructor nulls `m_stateStack.m_buffer`. So treat V674 as an unverified claim, not a primitive.

Also note `probes/1410-guide/v527_ab_reclaim.html` is not their work: its header says it was rebuilt to spec by
a third party from "Portablelle v3" ingredients.

## ZigZagBoi1/PS5-14.10-Research

Confirms the surroundings of our chain from the other direction: all three Relapse WebKit bugs are patched on
14.10 (we had already established this by patch presence), and it reports UMTX dead because **shm is stubbed on
14.10** - which kills the whole umtx exploit family on this firmware, independently of version checks.

Its kernel-side primitives all come from the Lua loader (threads, `make_syscall`, GPU mmap), which is exactly the
rung we cannot reach without the game. Nothing there is reachable from the browser sandbox.

## The three bugs in our own reclaim probes

1. **We beaconed inside the critical window.** `c015` sent `c015-768:sprayed` between the free and the spray;
   `c017` sent `triggered` before spraying. Beacon XHRs and Image loads allocate in the same size class and
   compete for the freed slot. The V527 probe's own comment records this failure mode independently: *"NO
   beacons before the spray: beacon XHRs are same-class competitors (their v3-run2 death)."*
2. **We sprayed immediately after the free.** bmalloc defers frees through `m_objectLog` (flushed at 512
   entries) - the slot is not released yet. The working sequence frees, churns ~192MB of unrelated allocation,
   waits ~1.2s, and only then sprays.
3. **We never freed the aliased owner.** The working sequence is: trigger, 500x same-type spray to get an
   alias, then *free that aliased canvas+context*, then spray ABs into the reopened slot. We only ever freed the
   original inner context and then sprayed into a slot whose owner was still live and still holding it.

`c018` implements the corrected sequence with every beacon deferred until after the oracle read.
