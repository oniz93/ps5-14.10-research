# The other jailbreaks: every public bug, and the one procedure that transfers

Inventory from the PS5/PS4 dev wikis (fetched 2026-10-26), plus ntfargo/ufm42's CSSFontFace write-up, which is
the only public document that weaponizes a bug of the same **shape** as our canvas UAF.

## Public kernel bugs, by firmware window

| bug | window | patched | class |
|---|---|---|---|
| IPv6 `ip6_pktopts` UAF (TheFloW) | 3.00-4.51 | 6.xx | UAF + spray overlap |
| umtx race (CVE-2024-43102) | 1.xx-5.50 | 8.00 | double free -> vmobject overlap |
| `aio_multi_delete` double free (bad locking) | <= 10.01 | 10.01 | double free |
| netcontrol / "poopsploit" | <= 12.50 era | ~12.50 | netcontrol path |
| `aio_multi_wait` decrement-by-one UaF + `get_aio_debug_request_info` leak | ~5.00-13.60 | **14.00** | race, arbitrary decrement |
| `aio_multi_delete` TOCTOU/UAF+double-free ("Prolapse") | 14.00-14.10 | **14.20** | race - PRIVATE |
| `get_aio_debug_request_info` info leak | ?-13.60 | unknown | leak only |

## Public userland bugs (the entry layer)

| bug | window | patched |
|---|---|---|
| `ValidationMessage::buildBubbleTree` UaF (Synacktiv) | 6.00-7.55 | 7.55 |
| `FrameLoader::loadInSameDocument` UaF (CVE-2022-22620) | <= 5.50 | 5.50 |
| `CSSFontFaceSet` vulns | 9.00-9.04 | 9.04 |
| `CSSFontFace::setStatus`/`pump` UaF (reference_wrapper lifetime) | 6.00-11.02 PS4 / 1.xx-8.60 PS5 | 11.50 |
| Slopkit (four JSC+WebCore bugs) | 7.00-13.60 | **partially, 14.00** |
| BD-JB family | <= 13.42/13.60 | 14.00 (disc only anyway) |
| Y2JB (YouTube app) | <= 12.70 | 12.70 |
| Mast1c0re (PS2 emu) | <= 7.60 | 7.60 |
| Lua (Artemis) / YARPE (Ren'Py) save exploits | all firmware | not patched (engine flaw) |

Slopkit is worth stating precisely because it is the temptation: the PS4 wiki says *"No as of PS4 FW 13.52 and
PS5 FW 13.60. **Yes** (at least partially) on PS4 FW 14.00 and PS5 FW 14.00."* So its four bugs are already
partly closed on 14.10 - testing it is cheap but unlikely to pay.

## The transferable procedure: CSSFontFace -> ARW

Same shape as our bug: a WebCore object held by a non-owning reference (`std::reference_wrapper`) across a
re-entrant JS callback, freed underneath the native loop, then used again.

1. **Groom, don't just spray.** Place the victim between many dummy rules; during re-entry delete the
   neighbours first, spray matching-size allocations, and *then* free the victim, so the freed slot is
   surrounded by freshly allocated neighbours of the right size class.
2. **The free is delayed.** bmalloc pushes freed small objects into `m_objectLog` and only processes it at
   **512 entries** (or on allocator slow path). A spray issued right after the free is racing a slot that has
   not been released yet - which is exactly what our c015/c016/c017 attempts did.
3. **Reclaim with a JS-visible allocation (ArrayBuffer), not strings.** The same buffer then serves as the
   leak: after native code repopulates wrapper state, the sprayed buffer contains heap pointers.
4. **Survive the remaining native use.** On PS5 the object is recycled through build-specific checks; the
   write-up shows an immediate vtable compare after the callback (`cmp [rdi], rax; jnz`), so the reclaimed
   bytes must carry the *correct* vtable pointer - i.e. PS5 needs an ASLR defeat before reclaim pays off.
5. **Turn it into a JS primitive.** Corrupt an array indexing header -> oversized double array paired with an
   object array -> `addrof`/`fakeobj` -> fake typed array -> `DataView` ARW.
6. **Only then** code execution, and per the 4.03 write-up that means a backward-edge pivot on a worker
   stack, not a vtable call.

Critical environment facts from the write-up that confirm our assumptions:
* On PlayStation **IsoHeap/IsoSubspace and the Gigacaged heap are disabled** - only `WTF::fastMalloc`/bmalloc
  matters. JS objects and ArrayBuffers therefore share the heap with WebCore objects, which is what makes
  steps 3 and 5 possible at all.
* Reproduction needs `-DUSE_SYSTEM_MALLOC=OFF -DUSE_ISO_MALLOC=OFF -DENABLE_JIT=OFF` and `GIGACAGE_ENABLED=0`,
  i.e. a bmalloc build - the thing that would not configure on the BC-250 for GTK, so reproduction stays
  console-side.
* The relative-read trick through `m_featureSettings` no longer works on newer WebKit (the getter is routed
  through cached CSS values behind `m_propertiesOrCSSConnection`), so only the reclaim/OOB route survives.

## What this changes in our plan

* c015/c016/c017 all sprayed before the deallocator log flushed. The sprays need a flush step: allocate and
  free >= 512 same-class objects after the victim is freed, then spray.
* Dummy neighbours around the victim are not decoration; they are what keeps the slot in the right page.
* The next oracle should be an ArrayBuffer (observable bytes) rather than a string, and the check should be
  "did the reclaimed buffer gain engine-written pointers", not "did a canvas call throw".

## The honest bottom line on 14.10

Every published kernel bug is closed on 14.10 except Prolapse, which is private. Every published userland bug
is closed except the save-game engine flaws, which need a game we cannot acquire. So the only paths left are a
new userland bug (ours) plus either an old kernel bug that turns out not to have been backported or a new one -
and CVE-2026-45251 is the only candidate we can name, still unconfirmed on a 14.10 image.
