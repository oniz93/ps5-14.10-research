# The IsoHeap gate: both builds this programme can touch run the 834 ISO classes in the general heap — and `docs/65`'s object was never an ISO class

The open question (`GOAL.md` action 1) was a disagreement between a source line and a console measurement:
`OptionsPlayStation.cmake:211` says `USE_ISO_MALLOC OFF`, while `docs/108-canvas-alias-on-retail.md` read the
console case `c043b` — a freed `CanvasRenderingContext2D` slot taken by the 80th same-type allocation — as IsoHeap
*on*, and read our ASAN build as IsoHeap *off*. Several of this programme's "same-type only" closures were said to
change meaning with the answer. They do not all change: the gate is one condition with two arms, the drop fixes the
console's arm, and `docs/65`'s object turns out not to be an ISO class at all.

All commands and their exact output are in `data/isoheap/census.txt`; the quotes with line numbers are in
`data/isoheap/gate.txt`; the per-build verdicts are `data/isoheap/verdicts.json`.

## 1. The gate, in full

```
Source/WTF/wtf/IsoMalloc.h:31   #if USE(SYSTEM_MALLOC) || !USE(ISO_MALLOC)
                       :35      #define WTF_MAKE_ISO_ALLOCATED(name) WTF_MAKE_FAST_ALLOCATED
                       :45      #define WTF_MAKE_ISO_ALLOCATED(name) MAKE_BISO_MALLOCED(name, WTF_NOEXPORT)
Source/WTF/wtf/IsoMallocInlines.h:30  the same condition, :35 IMPL -> `struct WTFIsoMallocSemicolonifier##name { }`,
                                      :43 IMPL -> MAKE_BISO_MALLOCED_IMPL(name)
Source/WTF/wtf/PlatformUse.h:36  #define USE(WTF_FEATURE) (defined USE_##WTF_FEATURE && USE_##WTF_FEATURE)
Source/WTF/wtf/PlatformUse.h:324 #if !defined(USE_ISO_MALLOC) / #define USE_ISO_MALLOC 1
```

So `USE_ISO_MALLOC`'s value is irrelevant whenever `USE_SYSTEM_MALLOC` is 1, and there are **two** independent ways to
land on the general heap. What each branch compiles to is not ambiguous either:

- off → `operator new(size_t) { return ::WTF::fastMalloc(size); }` (`FastMalloc.h:312-330`), and the `_IMPL` macro
  expands to an empty struct, so a class's TU defines no allocator symbols at all;
- on → `bisoHeap()` plus an out-of-line `operator new`/`operator delete`/`freeAfterDestruction`
  (`IsoHeap.h:136-149`), whose body is `return bisoHeap().allocate()` over a
  `static ::bmalloc::api::IsoHeap<isoType> heap("WebKit "#isoType)` (`IsoHeapInlines.h:155-162`).

That gives the census a binary signature: a mangled `_ZN6bmalloc3api7IsoHeap…` name, and a *defined*
`<class>::operator new` in the class's own object. Neither exists on either build below.

## 2. Verdict per build

**Console 14.10, per the drop: IsoHeap off.** `WEBKIT_OPTION_DEFAULT_PORT_VALUE(USE_ISO_MALLOC PRIVATE OFF)`
(`OptionsPlayStation.cmake:211`, preceded by the comment `# Don't use IsoMalloc`) against the generic default
`PRIVATE ON` (`WebKitFeatures.cmake:267`); those are the only two sites in the tree
(`grep -rn "USE_ISO_MALLOC" Source/cmake/`). `USE_SYSTEM_MALLOC` defaults OFF on x86-64
(`WebKitFeatures.cmake:90-92`), so the console is `USE_SYSTEM_MALLOC 0 && USE_ISO_MALLOC 0` → `!USE(ISO_MALLOC)` is
true → every one of the 834 classes is `WTF_MAKE_FAST_ALLOCATED` and lands in the general bmalloc heap. The verdict is
robust to the one doubt that could flip `USE_SYSTEM_MALLOC`: with `USE_64KB_PAGE_BLOCK` on, the default becomes ON
(`:82`) and the first arm of the gate fires anyway. The single remaining escape is an explicit
`-DUSE_ISO_MALLOC=ON` on Sony's own cmake invocation — the drop contains no such reference, and the shipped value is
not readable from source. This is the same conclusion `docs/107` §3 already recorded; it now has the gate behind it.

**Our ASAN oracle: IsoHeap off — by the other arm.** `~/wk/WebKit/WebKitBuild/ASAN/cmakeconfig.h` (6 983 B,
sha256 `4d1cfe68…b99`) says `:200 #define USE_ISO_MALLOC 1` and `:211 #define USE_SYSTEM_MALLOC 1`, and
`WebCore/config.h:22-23` includes that header under `HAVE_CONFIG_H && BUILDING_WITH_CMAKE`, so it is what the target
compiled with. The cache's `USE_ISO_MALLOC:BOOL=ON` therefore changes nothing: `USE(SYSTEM_MALLOC)` is true and the
ISO macro collapses to `WTF_MAKE_FAST_ALLOCATED`, i.e. `fastMalloc` → `malloc` (`FastMalloc.cpp:156`, `:236`,
`:265`) → ASAN's allocator.

Measured at object level, one variable (the class) — the real TU, compiled with the build's own
`DEFINES/INCLUDES/FLAGS` lifted from `build.ninja` (`page/UserMessageHandler.cpp.o`, same target), inside the
`wk` distrobox, 12 218 040-byte object:

```
$ nm -C --defined-only ctx2d_real.o | grep -E "CanvasRenderingContext2D.*(operator new|operator delete|bisoHeap|freeAfterDestruction)"
(no output)
$ nm -u -C ctx2d_real.o | grep -E "fastMalloc|IsoHeap"
                 U WTF::fastMalloc(unsigned long)
$ nm ctx2d_real.o | grep -c "_ZN6bmalloc3api7IsoHeap"
0
```

Those four absent symbols are exactly what `WTF_MAKE_ISO_ALLOCATED_IMPL(CanvasRenderingContext2D)`
(`CanvasRenderingContext2D.cpp:69`) defines under the ISO-on branch, so their absence is a positive detection of the
off branch rather than a failed string search. Measured at library level too: the oracle's own 3 695 564 176-byte
`libwebkit2gtk-4.1.so.0.11.0` keeps a `.symtab` (1 section) and contains **0** mangled `_ZN6bmalloc3api7IsoHeap`
names and 0 `bisoHeap` strings; its 77 `IsoHeap*` strings are 44 `IsoHeapCellType` + 32 `IsoHeapCellTypeC` + 1
`IsoHeap`, all JSC GC cell-type names. The pipeline control runs on the same file: `IsoSubspace` gives **2 928**
hits, so the scan does find heap-class names in this binary. (`nm -D` is useless here — WebKit is
`-fvisibility=hidden`, so class allocators never reach `.dynsym`; the byte scan covers `.symtab`, where they live.)

**The system library: undetermined.** `/usr/lib64/libwebkit2gtk-4.1.so.0.21.5` has **0** `.symtab` sections — it is
stripped, and hidden-visibility class allocators are absent from `.dynsym` by construction. Its zeros are not
evidence and it is not a usable positive control; nothing is claimed about Fedora's build.

**Limits of this run.** (a) The ISO-*on* arm could not be compiled on the oracle: with `USE_SYSTEM_MALLOC 0` the TU
needs `bmalloc/GigacageConfig.h`, a generated header this build dir has never produced (`find … -name
GigacageConfig.h` → nothing), so the on-shape is quoted from source rather than built. (b) The console's shipped
binary was not read — no console access, and the drop contains no compiled library. (c) The distro library is
stripped, so no third build could be measured.

## 3. Which closures this actually touches

- **`docs/65` is unaffected — measured in the source, and it is the load-bearing correction.**
  `css/CSSFontFace.h:61` is `WTF_MAKE_FAST_ALLOCATED_WITH_HEAP_IDENTIFIER(CSSFontFace)`, *not*
  `WTF_MAKE_ISO_ALLOCATED`. The CVE-2026-43715 object was never an ISO class in any build configuration, so none of
  `docs/65`'s results (the atob reclaim, the `+0x68` pointer read, the status flip, the 262-byte stack threshold
  reasoning) ever depended on this gate. `docs/65`'s "plain fastFree, not IsoHeap" was right for a stronger reason
  than it gave.
- **`docs/76` is unaffected.** `Source/JavaScriptCore` contains no reference to `USE(ISO_MALLOC)` at all; JSC's
  `IsoSubspace` (`stringSpace`, `JSString.h:118-124`) is JSC's own cell space inside the JSC heap, not a WTF class
  heap, so the 16-byte `JSString` segregation stands on both builds.
- **`docs/103`'s measurement stands, its explanation does not.** The local canvas reclaim failed on a build that has
  no type segregation at all, so "IsoHeap off is why the local test fails" cannot be the mechanism. What made that
  arm fail is unmeasured and is now an explicit open question — `docs/65` shows the same oracle handing a freed
  192-byte chunk back 30/30, so "the ASAN allocator quarantines everything" is not an answer either.
- **`docs/108-canvas-alias-on-retail.md`'s rule needs restating**: an IsoHeap class cannot be judged by the ASAN
  oracle, but neither can a non-ISO class, and on these two builds the 834 classes are not in an IsoHeap at all —
  what differs between the oracle and the console for every class is the *allocator* (ASAN malloc vs bmalloc), not
  type segregation. Its practical conclusion (the console is the only oracle for occupation) survives; its mechanism
  does not.
- **`c043b` cannot discriminate, by construction.** It sprays the same class 80 times and sees the stale wrapper
  alias `spray[2]`. IsoHeap gives same-type-only reuse; a plain bmalloc size-class free list gives type-agnostic
  reuse that includes same-type. Both explain `alias=2` (and neither predicts index 2 over index 0 without knowing
  what else of that size the loop allocates). The discriminating input is a **cross-type** allocation of the same
  size class in the freed context's place — only the console can run it, and the console campaign owns that case.

## 4. What the next action inherits

`docs/103`'s canvas arm is the one local result this gate leaves un-explained, and it is worth one bounded
experiment because it decides whether the console's deterministic same-type reclaim has any local analogue: on the
oracle, quarantine off and `max_malloc_fill_size=0`, instrument the exact `c043b`/`docs/103` trigger with gdb at
`WTF::fastFree` and `WTF::fastMalloc`, record the 712-byte chunk's address, and report every later allocation that
returns it — with the spray omitted as the control. That is `GOAL.md` action 1 now.
