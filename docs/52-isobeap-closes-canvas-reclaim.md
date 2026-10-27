# CVE-2026-43720 is alias-only on 14.10: the class is IsoHeap-segregated

Four console runs, three different non-same-type sprays, and the source. The reclaim is not a timing problem
and not a deferred-free problem - the freed slot can only ever be taken by another Canvas2D context.

## Console evidence (14.10, retail)

| spray | size | result |
|---|---|---|
| Canvas2D contexts (same type) | 712 | alias every time - idx 4 (c014), 2 and 13 (c019), 1 and 7 (c021) |
| ArrayBuffer | 768 | no reclaim (c018, c019 A0, c019 B700) |
| ArrayBuffer | 712 | no reclaim (c021 A) |
| createImageData(178,1) | 712 | no reclaim (c021 B) |
| String (712 chars) | ~712 | no reclaim (c016/c020 design) |

c019 also ruled out the deferred-free theory directly: variant B700 allocated and dropped 700 same-class
contexts (pushing >512 frees through the small-class deallocator) before spraying, and still read
`lw=1 no-reclaim`. Draining bmalloc's `m_objectLog` changed nothing.

Under any *flat* allocator, 400-600 allocations of exactly the object's size would take a freed slot with
overwhelming probability. Four independent failures from four different allocation paths, against universal
success for same-type allocations, is the signature of type segregation - not of luck.

## Source evidence

From Sony's shipped tree (WebKit-1400, file dates 2026-10-04):

```
Source/WebCore/html/canvas/CanvasRenderingContext2D.h:37
    WTF_MAKE_ISO_ALLOCATED(CanvasRenderingContext2D);
Source/WebCore/html/canvas/CanvasRenderingContext2DBase.h:93
    WTF_MAKE_ISO_ALLOCATED(CanvasRenderingContext2DBase);
```

`Source/WTF/wtf/IsoMalloc.h:31-49`: `WTF_MAKE_ISO_ALLOCATED` degrades to plain `WTF_MAKE_FAST_ALLOCATED` only
`#if USE(SYSTEM_MALLOC) || !USE(ISO_MALLOC)`; otherwise it becomes `MAKE_BISO_MALLOCED` - a real IsoHeap.
`Source/WTF/wtf/PlatformUse.h:324-326` defaults `USE_ISO_MALLOC` to 1, and there is no PlayStation override of
`USE_ISO_MALLOC`/`USE_SYSTEM_MALLOC` anywhere in the drop (no `PlatformPlayStation.h` exists).

Caveat on that static half, stated plainly: an OSS source drop cannot prove the flags Sony actually compiles
with, since the build system is not shipped. So the source only shows the macro *can* be a real IsoHeap and
that nothing in the shipped tree disables it. The console is what proves the behaviour.

## Why this closes the public chain's premise

pastawithpesto's plan is "same-type reclaim -> AB reclaim of the 768B slot -> forge the lineDash `Vector` in the
AB -> arbitrary R/W". IsoHeap segregation makes the second step impossible for this class. Their supporting
claim - "IsoHeap OFF, `BPLATFORM(PLAYSTATION)` at BPlatform.h:341" - is a misread of the tree: line 341 is the
**libpas enablement** condition (`BENABLE_LIBPAS`), which says Sony uses bmalloc+libpas, not that IsoHeap is
disabled. IsoHeap is a separate mechanism layered on top of it.

Consistent with that, their own `CONFIRMED_VULNS.md` still lists the info leak as the current blocker, its V527
probe is a third-party reconstruction whose header says so, and V674 (the "1651 leaked pointers") has no probe
and no result artifact in the repository.

## What CVE-2026-43720 actually gives

An alias to a **live** Canvas2D context. Two JS wrappers drive one C++ object; every canvas API reaches the
object's own state stack through a pointer we cannot corrupt, because we can never place bytes into the object.
That is a functional bug and a DoS (it is also why Sony shipped 14.20 without an urgent fix), but it is not a
memory primitive.

## Consequence: choose targets by allocator, not by API surface

The reclaim window only exists for objects allocated through plain `WTF::fastMalloc`:

* `Vector` element buffers (state stacks, dash arrays, path data)
* `StringImpl` / string buffers
* `ImageData` pixel buffers allocated by WebCore (not the JSC typed-array path)
* parser/serializer scratch buffers
* `CSSFontFace`-style CSS objects (the reference_wrapper family)

Anything marked `WTF_MAKE_ISO_ALLOCATED` - DOM nodes, canvas contexts, many WebCore types - can only be
re-entered by its own type, so a UAF there yields an alias, not control.

The already-confirmed JS-reachable OOB read in the OpenType vertical GSUB path is in the right category (font
parsing uses flat allocations), and the serializer/parser families we audited earlier are too. Those are the
surfaces worth spending console time on now.
