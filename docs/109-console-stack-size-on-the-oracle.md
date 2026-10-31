# docs/109 — the console's 512 KiB stack, emulated on the oracle: the IDB key path has **two** recursions and the boundary is 376 levels

`docs/108` priced four page-driven walkers and had to stop at a threshold, because the oracle's WTF threads inherit
glibc's 8 MiB. This run moves that one variable: glibc derives the default *thread* stack size from `RLIMIT_STACK`
when the caller passes no `setstacksize`, which is exactly this port's situation, so `ulimit -s 512` in front of
`run_nq.sh` gives a worker the console's own 524 288 B. Everything else — page, runner, breakpoint, quarantine — is
`docs/108`'s.

The result is not the one the action expected, and it is a correction to `docs/108`:

1. **The stack size really is the console's, and it is measured from the process, not assumed.** The worker's
   `rw-p` mapping is exactly **524 288 B** with a 4 096-byte `---p` guard page below it (`u512_376`: `$rsp` at the
   deepest breakpoint lands in `7f68ea980000-7f68eaa00000`; the page below is `7f68ea97f000-7f68ea980000 ---p`).
   A second arm at `ulimit -s 1024` gives 1 048 576 B, so the knob moves linearly.
2. **The IDB key path recurses twice, not once.** `docs/108` instrumented the inbound walk
   `createIDBKeyFromValue` (912 B/level) and missed the outbound conversion
   `WebCore::toJS(JSGlobalObject&, JSGlobalObject&, IDBKey*)` (`IDBBindingUtilities.cpp:153-156`), which builds the
   JS array for each key level and calls itself once per level: **1 344 B/level**, constant over 278 and 377
   deltas. It is 1.47× the inbound frame and it is what a deep key actually dies of.
3. **The boundary at the console's stack size is 376 levels, and 377 crashes — in the *conversion*, not the walk.**
   `d=376` returns `widb ok` twice, with the deepest `toJS` hit **288 B** above the floor; `d=377` is an ASAN
   `stack-overflow` in `JSArray::tryCreate` ← `constructEmptyArray` ← `toJS` (`:153`). The inbound walk alone would
   have allowed 556 entries; the requested depth never reaches it because the conversion runs first.
4. **At the measured release frames the console cannot be pushed over by a legal structure.** Recompiling the same
   TU at `-O2` without ASAN gives `toJS` **144 B**/level (the recursive call goes straight to the `[clone .part.0]`
   body, bypassing the 16-byte public thunk) against `createIDBKeyFromValue`'s **128 B**. The legal maximum is
   2 000 levels, so the console's worker needs **288 000 B = 54.9 %** for the conversion and **256 000 B = 48.8 %**
   for the walk, in a 524 288-byte thread — the threshold being **262 B/level**, i.e. 1.82× above the conversion's
   release frame and 2.05× above the walk's.

## 1. Instrument

Two additive changes over `docs/108`, nothing else:

- `research/stack-depth/stkrun.sh` gained `STK_BT=1`, which appends two lines *after* the top-level `continue` in
  the gdb script. gdb only returns to the outer command file on a stop no breakpoint command list handled — i.e.
  the fault — so that is the crash transcript (`STOP rsp=… pc=… thread=…` + `bt 5`), with no effect on the hits.
- `research/stack-depth/ulrun.sh` is a one-arm wrapper: `<tag> <port> <depth> <ulimit|def>` → `stkrun.sh` with
  `STK_ULIMIT` set and the full signature of `createIDBKeyFromValue` as the breakpoint.

The page is unchanged (`research/stack-depth/stack.html`, md5 `9d7b7880bfc0061f6dc1a52ab17c21c6`); one depth per
run, one process per arm, fresh port per arm, `run_nq.sh` (quarantine **off**). The only variable between an arm and
its control is the thread stack size and the recursion depth.

## 2. The stack size is the console's, from `/proc/<pid>/maps`

`u512_8` (`arm=widb&d=8`, `ulimit -s 512`) is the smoke arm: the browser starts, the worker runs, the arm returns
`B widb ok d=8 type=Array ms=9`, 9 hits. The mapping containing the worker's `$rsp` (`0x7f44b5b625e0`):

```
7f44b5ae8000-7f44b5b68000 rw-p 00000000 00:00 0   SIZE= 524288 bytes = 512 KiB
```

and from the boundary arm `u512_376`, the same mapping with its guard line in context:

```
  ctx: 7f68ea87f000-7f68ea97f000 rw-p 00000000 00:00 0
  ctx: 7f68ea97f000-7f68ea980000 ---p 00000000 00:00 0     <- 4096-byte guard page
  ctx: 7f68ea980000-7f68eaa00000 rw-p 00000000 00:00 0     <- 524288-byte worker stack
```

The second stack size, `ulimit -s 1024`, gives exactly twice that (`maps_u1024_766.txt`), so the emulation is a knob
and not a coincidence. `docs/108` had already shown the same for 1 024 KiB; this run repeats it and adds the arm at
the console's own number.

## 3. Two recursions: 912 B/level in, 1 344 B/level out

`u512_278js` carries **two** breakpoints on the same page and the same depth (278):

```
=== u512_278js  pid=1530292  port=8988  q=arm=widb&d=278  secs=20  bps=2  ulimit=512
--- gdb attach:
  Breakpoint 1 at 0x7f005311285b
  Breakpoint 2 at 0x7f0053101209
  B widb ok d=278 type=Array ms=402
--- gdb: 558 hits
  H 1 t=10 bp=1 rsp=0x7f002869a260
  ... last: H 558 t=10 bp=2 rsp=0x7f002863e3a0
```

| breakpoint | function | hits | deltas | per level | first hit, below stack top | span |
|---|---|---|---|---|---|---|
| 1 | `createIDBKeyFromValue` | 279 | 278 | **912 B** (min = max) | 15 776 B (`0x3DA0`) | 253 536 B |
| 2 | `toJS(…, IDBKey*)` | 279 | 278 | **1 344 B** (min = max) | 18 656 B (`0x48E0`) | 373 632 B |

Both are exact: the per-level delta has a single value across all 278 deltas, and the same 912 B appears on every
one of the twenty-odd other arms (9 to 1 132 deltas), which is why the inbound number in `docs/108` reproduces even
at depths that crash.

`toJS` is `IDBBindingUtilities.cpp:141-159`: for a `KeyType::Array` level it calls
`constructEmptyArray(&globalObject, …, size)` (`:153`) and then, in the loop, `outArray->putDirectIndex(…,
toJS(lexicalGlobalObject, globalObject, inArray.at(i).get()))` (`:156`). One frame per key level, allocated
*before* the recursion — so the deepest array level is the one that runs out.

## 4. The boundary at 512 KiB is 376 levels — and the crash is in `toJS`

Full sweep, one depth per run, `d` = the page's nesting depth, `hits` = entries of `createIDBKeyFromValue`, outcome
from the beacon log (`B widb ok` / `B done`) and from ASAN:

| arm | ulimit | `d` | hits | outcome | where it died |
|---|---|---|---|---|---|
| `u512_8` | 512 | 8 | 9 | **ok** `ms=9` | — |
| `u512_188` | 512 | 188 | 189 | **ok** `ms=148` | — (half-depth control) |
| `u512_278` | 512 | 278 | 279 | **ok** `ms=204` | — |
| `u512_278js` | 512 | 278 | 279 + 279 (toJS) | **ok** `ms=402` | — (frame instrument) |
| `u512_370` | 512 | 370 | 371 | **ok** `ms=271` | — |
| `u512_373` | 512 | 373 | 374 | **ok** `ms=279` | — |
| `u512_375` | 512 | 375 | 376 | **ok** `ms=277` | — |
| **`u512_376`** | 512 | **376** | 377 | **ok** `ms=268` | — deepest that fits |
| `u512_376b` | 512 | 376 | 377 | **ok** `ms=269` | — repeat, same |
| `u512_376js` | 512 | 376 | 377 + 377 (toJS) | **ok** `ms=555` | — 288 B left at the deepest `toJS` hit |
| **`u512_377`** | 512 | **377** | 378 | **crash** | `toJS` → `constructEmptyArray` → `JSArray::tryCreate` |
| `u512_379` | 512 | 379 | 380 | **crash** | same |
| `u512_380` | 512 | 380 | 381 | **crash** | same |
| `u512_550` | 512 | 550 | 551 | **crash** | same — the inbound walk had *completed* |
| `u512_555` | 512 | 555 | 556 | **crash** | `malloc` ← `fastMalloc` ← `IDBKey::operator new` |
| `u512_556` | 512 | 556 | 557 | **crash** | `malloc` ← `fastMalloc` ← `createIDBKeyFromValue` |
| `u512_557` | 512 | 557 | 557 | **crash** | `Vector::append` `:228` (`asanBufferSizeWillChangeTo`) |
| `u512_558` | 512 | 558 | 557 | **crash** | same |
| `u512_2000` | 512 | 2000 | 557 | **crash** | same |
| `u1024_766` | 1024 | 766 | 767 | **ok** `ms=558` | — deepest that fits at 2× |
| `u1024_767` | 1024 | 767 | 768 | **crash** | `toJS` → `constructEmptyArray` |
| `u1024_2000` | 1024 | 2000 | 1132 | **crash** | `Vector::append` `:228` |

`d=376`, arm `u512_376js` — the closing datum of the ok side, both recursions armed:

```
--- gdb: 754 hits
toJS n 377 first 0x7f06cb513720 last 0x7f06cb498120 delta 1344 1344
bottom 0x7f06cb498000 last 0x7f06cb498120 headroom 288 levels left 0
```

377 `toJS` entries at 1 344 B each from 18 656 B below the top leave **288 B** above the 524 288-byte floor, and the
288 B are enough only because that last entry is the *number* at the bottom of the key, whose branch
(`toJS`:181-182) calls nothing. `d=377` puts an **array** level at that same position, and its
`constructEmptyArray` call is what crosses the floor:

```
==1533258==ERROR: AddressSanitizer: stack-overflow on address 0x7f1133e89d64 (pc 0x7f115f3300be bp 0x7f1133e8a110 sp 0x7f1133e89d50 T9)
    #0 0x7f115f3300be in JSC::JSArray::tryCreate(JSC::VM&, JSC::Structure*, unsigned int, unsigned int) …/JSArray.h:207
    #1 0x7f115f901841 in JSC::JSArray::tryCreate(JSC::VM&, JSC::Structure*, unsigned int) …/JSArray.h:253
    #2 0x7f115f901841 in JSC::constructEmptyArray(JSC::JSGlobalObject*, JSC::ArrayAllocationProfile*, unsigned int, JSC::JSValue) …/JSGlobalObjectInlines.h:273
    #3 0x7f115f901841 in WebCore::toJS(JSC::JSGlobalObject&, JSC::JSGlobalObject&, WebCore::IDBKey*) IDBBindingUtilities.cpp:153
    #4 0x7f115f901d08 in WebCore::toJS(JSC::JSGlobalObject&, JSC::JSGlobalObject&, WebCore::IDBKey*) IDBBindingUtilities.cpp:156
```

and the fault address is inside the guard page (`0x7f1133e89d64` against the mapping bottom `0x7f1133e8a000`, both
derived from the first hit plus the constant 15 776-byte offset the intact arms measure — 668 B below the floor, inside
the 4 096-byte `---p` page), so this is a fault, not silent corruption. The two deep-walk crashes are the same:
`u512_2000` faults 696 B below its floor, `u1024_767` 540 B below its 1 MiB floor.

## 5. Which recursion binds depends on the stack size

The inbound walk alone survives far deeper than the conversion: its own crash entry is **557** at 512 KiB and
**1132** at 1 MiB (`u512_2000`: 557 hits then `__sanitizer_annotate_contiguous_container` ←
`Vector<JSArray*>::append` ← `:228`; `u1024_2000`: 1 132 hits, same frame). So:

- at **512 KiB**, for `377 ≤ d ≤ 550` the walk completes and the **conversion** kills it (measured directly at
  `d=550`: 551 hits — every level of the walk — then `toJS` at `:153`); for `d ≥ 555` the walk itself dies first
  (`u512_555`: 556 hits, `StackDepotBase::Put` ← `Allocator::Allocate` ← `malloc` ← `fastMalloc` ←
  `IDBKey::operator new`; `u512_556`: 557 hits, `malloc` ← `fastMalloc` ← `createIDBKeyFromValue`), so the walk's
  own entry limit is 556-557 — it moves by one because the deepest frame's allocation path is ASAN's;
- at **1 MiB** the walk's own entry limit (1 132) is below the requested 2 000, so `u1024_2000` dies in the walk;
  the conversion's limit there is 766, which is why `u1024_767` dies in the conversion while `u1024_766` is `ok`.

Both limits are a one-parameter linear fit to the same two constants (frame, pre-recursion offset):

```
createIDBKey: crash entry = floor((S - 15 776) / 912)      512 KiB -> 557 ✓ (measured 557)
                                                            1 MiB   -> 1132 ✓ (measured 1132)
toJS:         deepest ok  = floor((S - 18 656) / 1 344)     512 KiB -> 376 ✓ (measured 376)
                                                            1 MiB   -> 766 ✓ (measured 766)
```

Both predictions are exact at both stack sizes, four for four, with no fitted parameter beyond the two frame sizes
and the two measured offsets.

## 6. The release frames, and the console arithmetic

`research/stack-depth/mkrepro.sh` (docs/108) compiles `bindings/js/IDBBindingUtilities.cpp` from the same tree with
the build's own includes and defines at `-O2 -g0 -DNDEBUG` and no sanitizer; the object is still at `/tmp/repro/idb.o`
on the oracle. `createIDBKeyFromValue` is `push rbp; push r15,r14,r13,r12,rbx; sub $0x48` → **128 B** including the
return address (docs/108). The same object's `toJS` is split, and the split is what makes the number small:

```
0000000000000c20 <WebCore::toJS(JSC::JSGlobalObject&, JSC::JSGlobalObject&, WebCore::IDBKey*)>:
     c20: test %rdx,%rdx
     c23: je   c30
     c25: push %rbp
     c26: mov  %rsp,%rbp
     c29: call 5c0 <… [clone .part.0]>
     c2e: pop  %rbp
     c2f: ret
00000000000005c0 <… [clone .part.0]>:
     5c0: push %rbp
     5c1: mov  %rsp,%rbp
     5c4: push %r15
     5c6: push %r14
     5cb: push %r13
     5cd: push %r12
     5cf: push %rbx
     5d3: sub  $0x58,%rsp
…
     7d2: call 5c0 <… [clone .part.0]>          <- the recursive call goes to the clone, not the thunk
```

so the per-level release cost is the clone alone: `(1+5)×8 + 0x58 + 8` = **144 B**, not 160 B. (The thunk adds
16 B only for the outermost call.)

The console's numbers from the port's own sizes (`Threading.cpp:101-118`, `PlatformPlayStation.cmake:44`): a
`ThreadType::JavaScript` thread gets **524 288 B**, and the IDB key builder is the deepest *legal* structure a page
can build (`maximumDepth = 2000`, `IDBBindingUtilities.cpp:194`).

| recursion | legal max | ASAN frame | `-O2` frame | 2 000 levels at `-O2` | threshold `524288/2000` | margin |
|---|---|---|---|---|---|---|
| `createIDBKeyFromValue` (in) | 2 000 | 912 B | **128 B** | 256 000 B = **48.8 %** | 262 B | **2.05×** |
| `toJS(…, IDBKey*)` (out) | 2 000 | 1 344 B | **144 B** | 288 000 B = **54.9 %** | 262 B | **1.82×** |

Adding the ASAN-measured pre-recursion offsets (15 776 B / 18 656 B, smaller in a release build) changes those to
51.8 % and 58.5 %. The release-shaped *boundaries* at 512 KiB would be 3 973 (in) and 3 511 (out) levels — both
above the 2 000 cap, and 7.1× / 9.3× above the ASAN boundaries measured here (557 / 376).

**So a legal 2 000-level IDB key cannot overflow a console worker's 512 KiB stack** at the measured release frames.
The margin is 1.82× for the binding function. The inequality the action asked about is settled in the safe
direction, with the one honest qualification in §9.

## 7. What this closes, and the three corrections it makes

- **`docs/108` missed a recursion.** Its four walkers were the *inbound* ones; `toJS` on `IDBKey*` is the outbound
  half of the same page-reachable path and costs 1.47× more per level under ASAN. The corrected statement is:
  the IDB key path has **two** page-driven recursions, and a deep key's limit is
  `min(2000, toJS_limit, createIDBKey_limit)`.
- **The 512 KiB arm is not the 8 MiB arm scaled.** The binding recursion *changes* with the stack size (376 in the
  conversion at 512 KiB; 1 132 in the walk at 1 MiB when 2 000 levels are requested), because the walk runs first
  and only dies in itself once its own limit is below the page's request. A single arm at one stack size would have
  attributed the wrong function.
- **`docs/108`'s conclusion stands and is now measured on the console's own number**: no page-reachable 64 KiB
  hazard (both recursions run on `ThreadType::JavaScript`), and the 2 000-level IDB key fits a worker with a 1.82×
  margin at the release frame. It is a DoS question only if Sony's compiler emits frames ≥ 262 B for either
  function — 1.82× above GCC 13's `toJS` and 2.05× above its `createIDBKeyFromValue`.

Not a memory primitive, and not criterion 3: a stack overflow in a worker is a crash, and the fault here lands in a
guard page.

## 8. Exact commands

```
# harness (additive to docs/108): STK_BT=1 adds the fault transcript, ulrun.sh is one arm
scp research/stack-depth/{stkrun.sh,ulrun.sh} teo@<lab-ip>:/tmp/
ssh teo@<lab-ip> 'cp /tmp/stkrun.sh /tmp/ulrun.sh ~/ && chmod +x ~/stkrun.sh ~/ulrun.sh'

ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_8   8980 8    512 20'   # smoke + maps 524288
ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_188 8996 188  512 20'   # half-depth control
ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_278 8985 278  512 20'
ssh teo@<lab-ip> 'A_IDB="WebCore::createIDBKeyFromValue(JSC::JSGlobalObject&, JSC::JSValue, WTF::Vector<JSC::JSArray*, 0ul, WTF::CrashOnOverflow, 16ul, WTF::FastMalloc>&)";
                        A_TOJS="WebCore::toJS(JSC::JSGlobalObject&, JSC::JSGlobalObject&, WebCore::IDBKey*)";
                        STK_ULIMIT=512 bash ~/stkrun.sh u512_278js 8988 "arm=widb&d=278" 20 "$A_IDB" "$A_TOJS"'
ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_370 8989 370  512 20'
ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_375 8991 375  512 20'
ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_376 8995 376  512 20'   # deepest ok
ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_377 8993 377  512 20'   # first crash (toJS)
ssh teo@<lab-ip> 'bash ~/ulrun.sh u512_2000 8981 2000 512 25' # crash in the walk at 557
ssh teo@<lab-ip> 'bash ~/ulrun.sh u1024_2000 8997 2000 1024 25'
ssh teo@<lab-ip> 'bash ~/ulrun.sh u1024_766 8998 766  1024 20' # deepest ok at 2x
ssh teo@<lab-ip> 'bash ~/ulrun.sh u1024_767 8999 767  1024 20' # first crash at 2x

# release-shaped frames from the same TU (docs/108's script, object still on the oracle)
objdump -d -C --no-show-raw-insn /tmp/repro/idb.o | sed -n '/\[clone .part.0\]>:/,/^$/p'
```

Logs: `data/stack-depth/ulimits/G_*.log` (gdb transcripts, one per arm), `R_*.log` (ASAN + `EXIT=`),
`maps_*.txt` (the `/proc/<pid>/maps` snapshot per surviving run), `srv*.log` (beacon server), and
`ulimits_summary.json` (hits, per-breakpoint deltas, first/last `$rsp`, ASAN header per arm).

Note on the tree: `research/stack-depth/stkrun.sh` (+3 lines) and the new `ulrun.sh` were swept into the concurrent
session's commit `73cddf1` by a `git add -A`; their content there is this run's, but the commit message does not
describe them.

## 9. Limits of this result

- The release frame is **GCC 13 `-O2`** from this drop's own headers; Sony's clang output is unknown. The number to
  hold against the console is the **262 B** threshold, and the measured margin is 1.82× for `toJS`. A clang build
  that inlines more of the loop would be smaller; one that spills more could be larger, and nothing here bounds it
  from above except the ASAN frame (1 344 B), which is 5.1× over the threshold.
- The stack sizes are glibc's `RLIMIT_STACK`-derived default on the oracle and `pthread_attr_setstacksize` on the
  console; both give a 524 288-byte usable region (measured), but the guard page is the libc's business and the
  console's libc may differ. That affects whether an overflow *faults* or corrupts, not whether it fits.
- The recursion depth is counted at the function boundary (symbol+20, after each prologue), so a caller-side frame
  between levels is included in the per-level delta only when the recursion passes through it; both functions here
  are direct self-calls under `-O2`, but the `toJS` release path goes through the public thunk once (§6).
- The pre-recursion offsets (15 776 B / 18 656 B) are ASAN/build-specific and are used only as an upper estimate of
  the console's fixed cost.
- Nothing here is a memory-safety primitive: a stack overflow in a worker is a crash (or, unguarded, corruption),
  and stage criterion 3 still needs a bug that copies engine bytes into JS.
