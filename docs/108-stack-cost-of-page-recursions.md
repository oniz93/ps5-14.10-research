# docs/108 — what a page-driven recursion actually costs in stack, and the depth the console's thread sizes allow

GOAL action 1 after `docs/107` asked for a number, not a worry: `-DDEFAULT_THREAD_STACK_SIZE_IN_KB=64`
(`Source/WTF/wtf/PlatformPlayStation.cmake:44`) gives every WTF-created non-JavaScript thread 64 KiB, and the
action named four walkers a page can drive. This run prices each of them on the oracle by reading `$rsp` at
successive recursion depths, then converts the measurement into the console's depth limits with the port's own
stack sizes. One variable per arm: one walker, one depth, one breakpoint.

The three results that matter:

1. **Two of the four "recursive walkers" do not recurse in C++ at all.** `CloneSerializer::serialize` and
   `CloneDeserializer::deserialize` are iterative state machines with explicit stacks
   (`SerializedScriptValue.cpp:2494-2520`, `:4832-4850`); a depth-20 000 clone hits `serialize` **once** and a
   depth-20 000 `MessagePort` message hits `deserialize` **once**. Their limit is a heap cap,
   `maximumFilterRecursion = 40000` (`:141`), and going over it is a catchable JS error, not a stack event.
2. **The other two are bounded well below any stack limit, and both run on a JavaScript thread.** The IDB key
   builder recurses once per array level with `maximumDepth = 2000` (`IDBBindingUtilities.cpp:194`), and the CSS
   parser once per nested rule list with `maximumRuleListNestingLevel = 128` (`CSSParserImpl.cpp:67`). Measured
   frame costs are constant per level: **912 B** and **1 520 B** in this ASAN `-O1` build, **128 B** and
   **160 B** when the same TUs are recompiled at `-O2` without the sanitizer.
3. **At its legal maximum the deepest of them costs 48.8 % of a console worker's 512 KiB stack** — if the
   release frame is the `-O2` one. The safe-frame threshold is **262 B/level**; the measured `-O2` frame is
   128 B (2.05× under the line) and the measured ASAN frame is 912 B (3.5× over it). So the console prediction
   is an inequality with a measured margin, not a yes/no, and the oracle cannot settle it because its own
   threads are 8 MiB (measured, §5).

## 1. Instrument

`research/stack-depth/stack.html` (md5 `9d7b7880bfc0061f6dc1a52ab17c21c6`) parks on `/go.txt` until the
harness creates it, so gdb is attached and its breakpoints are set before any arm runs. `research/stack-depth/stkrun.sh`
serves the page from `/tmp/wkp` on a fresh port, starts `run_nq.sh` (quarantine **off**, the standard runner),
waits for the run's own `WebKitWebProcess`, attaches host gdb, then touches `go.txt`; `arms.sh` holds one line
per arm.

The ASAN build's `.debug_info` cannot be read through a host attach — gdb prints
`warning: Can't read data for section '.debug_info' in file 'target:/home/<user>/wk/WebKit/WebKitBuild/ASAN/lib/libwebkit2gtk-4.1.so.0'`
and then `No source file named IDBBindingUtilities.cpp`, so the file:line breakpoints of earlier docs do not
work here. The ELF symbol table does work, and a **quoted full signature** resolves to a relocated runtime
address:

```
(gdb) break 'WebCore::createIDBKeyFromValue(JSC::JSGlobalObject&, JSC::JSValue, WTF::Vector<JSC::JSArray*, 0ul, WTF::CrashOnOverflow, 16ul, WTF::FastMalloc>&)'
Breakpoint 1 at 0x7fb1f9d1285b
```

Each breakpoint carries its own `commands` block that increments a counter and prints
`H <n> t=<thread> bp=<n> rsp=<0x…>`. The breakpoint lands at **symbol+20**, which is *after* the prologue's
`push`/`sub` on both functions, so consecutive `$rsp` values give the frame directly.

## 2. The IDB walker: 912 B per level, exact and constant

`arm=idb&d=2000` — nested single-element arrays 2 000 deep, `IDBKeyRange.only()` on the main thread:

```
=== idb2000  pid=1509593  port=8951  q=arm=idb&d=2000  secs=40  bps=1
--- gdb attach:
  Breakpoint 1 at 0x7fcb9f71285b
--- beacons:
  B boot arm=idb d=2000 ua=101
  B go 1
  B idb ok d=2000 type=Array ms=1413
  B done
--- gdb: 2001 hits
  H 1 t=1 bp=1 rsp=0x7ffd650b5330
  H 2 t=1 bp=1 rsp=0x7ffd650b4fa0
  H 3 t=1 bp=1 rsp=0x7ffd650b4c10
  ... last: H 2001 t=1 bp=1 rsp=0x7ffd64ef7e30
--- faults:
```

All **2 000** deltas are **912 B** (`min = max = mode = 912`), and the total from the outermost to the deepest
frame is **1 824 000 B (1.74 MiB)**. The static prologue of the same function in the same binary agrees exactly:

```
6b12847: push %rbp
6b12848: mov  %rsp,%rbp
6b1284b: push %r15
6b1284d: push %r14
6b1284f: push %r13
6b12851: push %r12
6b12853: push %rbx
6b12854: sub  $0x358,%rsp        # 856 + 6*8 pushes = 904 frame, +8 return address = 912
```

Depth controls at 64 and 1 000 give the same 912 B per level (`G_idb64.log` 64 deltas, `G_idb1000.log` 1 000
deltas, both `min = max = 912`), and the arm completes at the engine's own cap: `d=2000` is legal
(`stack.size() >= maximumDepth` is checked *before* the append at `:225`, so the deepest call sees 1 999).

## 3. The same walk on a worker thread: identical, and it really is the worker

`arm=widb&d=2000` — the key is built inside a Blob worker, so `WorkerThread::createThread`
(`WorkerThread.cpp:117-131`) → `Thread::create(threadName(), …, ThreadType::JavaScript)` → the 512 KiB branch:

```
=== widb2000  pid=1510488  port=8953  q=arm=widb&d=2000  secs=45  bps=1
--- beacons:
  B wtype IDBKeyRange=function indexedDB=object isWorker=1
  B widb ok d=2000 type=Array ms=1467
--- gdb: 2001 hits
  ... last: H 2001 t=10 bp=1 rsp=0x7fe7037a6d60
```

Every hit is on **thread 10**, every delta is 912 B, total 1 824 000 B — the frame is a property of the
function, not of the thread, so the console's smaller stack changes the *limit*, never the cost. `IDBKeyRange`
is exposed in workers on this build (`wtype IDBKeyRange=function`), so the worker spelling of the walker is
real, not a source-level assumption.

## 4. The CSS walker: 1 520 B per nesting level, capped at 128 by the parser

`arm=css&d=128` — one `<style>` whose text is `@media all{` × 128 + `b{color:red}` + `}` × 128, parsed by
reading `sheet.cssRules`:

```
--- beacons:
  B css ok d=128 top=1 deep=128 ms=96
--- gdb: 128 hits
  ... last: H 128 t=1 bp=1 rsp=0x7ffc7922ae30
```

**127** deltas, all **1 520 B**; total **193 040 B (188.5 KiB)**. That per-level number is **not** the frame of
`consumeRegularRuleList` alone: its own ASAN prologue is
`push rbp; push r15,r14,r13,r12,rbx; sub $0x278` = 688 B including the return address, and the remaining
832 B are the two frames that sit between successive entries (`consumeRuleList` → the at-rule consumer →
`consumeRegularRuleList`). The recursion is indirect, so this is the honest per-nesting-level cost, not a
single function's frame. The cap is the source's:
`static constexpr auto maximumRuleListNestingLevel = 128;` (`CSSParserImpl.cpp:67`), enforced by
`NestingLevelIncrementer` + `if (m_ruleListNestingLevel > maximumRuleListNestingLevel) return { };`
(`:582-587`) — so 128 is both what the page can build and what the parser will recurse. `d=64` gives 64 hits
and the same 1 520 B (`G_css64.log`), and the page's own depth walk agrees with the parser (`deep=128`).

## 5. What the oracle cannot tell you: its threads are 8 MiB

Host `ulimit -s` is 8192 KiB and the GTK port passes **no** `setstacksize`
(`stackSize()` returns `std::nullopt` off-PLAYSTATION, `Threading.cpp:114-126`), so every WTF thread on the
oracle gets glibc's default. Measured from the worker arm `widb8`, by finding the mapping that contains the
worker's `$rsp` at its first hit (`0x7f3403af2260`):

```
mapping containing worker $rsp: 7f34032f6000-7f3403af6000 8388608 bytes = 8192 KiB (anon)
```

**8 388 608 B.** The console's JavaScript threads get 524 288 B from the port's own `stackSize()`, i.e. the
oracle is running this experiment with **16×** the stack the console will give the same thread. That is exactly
why the arms succeed here and why the deliverable is a threshold and not a verdict.

The oracle's stack size is not fixed, though — it is the one variable the next action can move, because glibc
derives the default *thread* stack size from `RLIMIT_STACK` when the caller passes no `setstacksize`, which is
this port's situation. Verified, same page and same runner, only `ulimit -s 1024` added in front of
`run_nq.sh`: the worker's stack mapping becomes **1 048 576 B = 1 024 KiB** (`data/stack-depth/maps_ul1024.txt`,
worker `$rsp` `0x7fbd2d5fc260` inside `7fbd2d500000-7fbd2d600000`), against 8 388 608 B for the same arm without
the `ulimit` (`maps_widb8.txt`). So the console's 512 KiB is emulable on the oracle, one arm per size.

## 6. The frame that matters is the release one, not this build's

The oracle is `RelWithDebInfo` with `-O1 -g -DNDEBUG` **and** `-fsanitize=address`; ASAN redzones are most of
the frame. Two TUs were recompiled from the same tree with the build's own include set and defines, changing
only the optimisation level and dropping the sanitizer (`/tmp/repro`, script in the log below):

| function | prologue at `-O2` without ASAN | frame incl. return address | ASAN `-O1` frame |
|---|---|---|---|
| `createIDBKeyFromValue` (recursive) | `push rbp; mov; push r15; push r14; push r13; push r12; push rbx; sub $0x48` | (1+5)×8 + 72 + 8 = **128 B** | 912 B (7.1×) |
| `consumeRegularRuleList` | `push rbp; mov; push r15; push r14; push r13; push r12; push rbx; sub $0x68` | (1+5)×8 + 104 + 8 = **160 B for this function alone**; the per-level cost also carries the two intermediate frames, which were not recompiled | 1 520 B (9.5× for the function itself: 688 B) |

So the two numbers bracket the console: the ASAN build is an upper bound that is 7-9.5× too expensive, the
`-O2` build is a lower, release-shaped estimate. Both are measured on this drop's own code; neither is the
console's compiler output, which is clang rather than this GCC 13. The IDB walker's bracket is tight, because
its recursion is a direct self-call: 128 B ≤ frame ≤ 912 B. The CSS bracket is one-sided — 160 B is only the
entry function, and the intermediate frames that make up the other 832 B under ASAN were not recompiled — so its
release per-level cost is somewhere between 160 B and 1 520 B. That asymmetry does not change any conclusion,
because the CSS walker's cap is 128 and it runs on the main thread.

## 7. The console's depth limits

Stack sizes from the port itself (`Threading.cpp:101-118` + `PlatformPlayStation.cmake:44`): **512 KiB** for
`ThreadType::JavaScript` (workers, and nothing else), **64 KiB** for every other WTF-created thread, and the
main thread is not WTF-created at all, so neither number applies to it.

| walker | legal max depth | frame (ASAN `-O1`) | frame (`-O2`, no ASAN) | cost at legal max (`-O2`) | depth in 512 KiB (`-O2`) | depth in 64 KiB (`-O2`) |
|---|---|---|---|---|---|---|
| IDB key (`createIDBKeyFromValue`) | **2 000** | 912 B | **128 B** | 250.0 KiB = **48.8 %** | 4 096 | 512 |
| CSS nesting (`consumeRegularRuleList`) | **128** | 1 520 B | **≥ 160 B** | ≥ 20.0 KiB = **≥ 3.9 %** | ≤ 3 276 | ≤ 409 |
| `CloneSerializer::serialize` | 40 000 objects | — (1 call) | — | 0 | ∞ | ∞ |
| `CloneDeserializer::deserialize` | 40 000 objects | — (1 call) | — | 0 | ∞ | ∞ |
| `JSON.parse` (`parseRecursively`) | unbounded | — (falls back) | — | 0 | ∞ | ∞ |

With the ASAN frames instead: the IDB walk needs 1.74 MiB at depth 2 000, which is **574 levels** of a
512 KiB stack (and 71 of a 64 KiB one); the CSS walk at its cap uses 188.5 KiB, i.e. 37.1 % of 512 KiB.

**The threshold.** 524 288 / 2 000 = **262 B per level** is the largest release frame at which the page's
deepest *legal* IDB structure still fits a console worker's stack. The `-O2` measurement is 128 B (2.05× under
it); the ASAN measurement is 912 B (3.5× over it). Nothing in this drop lets a page go past 2 000, so this is
the whole exposure of that walker.

## 8. What this closes, and the three corrections it makes

- **The 64 KiB threads.** None of the four walkers ever runs on one. CSS parsing and the IDB key builder run on
  the calling thread (main, or a worker's `ThreadType::JavaScript` thread — measured, thread 10); the
  serializer and the deserializer are iterative, so their thread's stack is irrelevant. **0 of the four is a
  page-reachable 64 KiB stack hazard.** The 64 KiB size still bounds any future page-driven C++ recursion that
  lands on a `WorkQueue`/IPC thread, and `OSAllocatorPlayStation` asserts `!includesGuardPages` on both reserve
  paths (`wtf/playstation/OSAllocatorPlayStation.cpp:40`, `:61`, `:81`), so such an overflow would be corruption rather
  than a fault — but that is a statement about `OSAllocator` reservations, **not** about thread stacks, which
  come from `pthread_attr_setstacksize` (`posix/ThreadingPOSIX.cpp:294-295`) and whose guard page is the C
  library's business. Do not merge the two.
- **`CloneSerializer` is not a recursive walk** (the action's first named item): `serialize` is a
  `while (1) switch (state)` machine with `inputObjectStack`/`stateStack` vectors, measured at **1 hit for
  depth 20 000**, and its `maximumFilterRecursion = 40000` is a *heap* cap whose breach is a JS error, measured:
  `clone err d=41000 RangeError:Maximum call stack size exceeded.` `CloneDeserializer::deserialize` is the same
  shape (1 hit at depth 20 000, message arrives `mp recv d=20000 ok=1`).
- **`SVGPathParser` is iterative too** (source-read, not instrumented): `parsePathData` is a `while (true)` segment
  loop (`SVGPathParser.cpp:303-319`) called only from the two static entry points (`:37-55`), with no self-call.
- **`JSON.parse` is recursive but stack-aware**, which is the contrast that makes WebCore's `maximumDepth` worth
  knowing about: `parseRecursivelyEntry` passes `vm.softStackLimit()` and `parseRecursively` falls back to the
  iterative parser when the C++ stack pointer crosses it (`runtime/LiteralParser.cpp:1190-1205`). Measured:
  `json ok d=100000 n=1 ms=59` — 100 000 levels parse, on the main thread, with no error and no growth. So
  JSC's recursions adapt to whatever stack the thread has; `createIDBKeyFromValue` does not consult stack bounds
  at all.

## 9. Exact commands

```
# page + runner on the oracle (fresh port per arm, quarantine off via run_nq.sh)
scp research/stack-depth/{stack.html,stkrun.sh,arms.sh} teo@<lab-ip>:/tmp/
ssh teo@<lab-ip> 'cp /tmp/stkrun.sh /tmp/arms.sh ~/ && chmod +x ~/stkrun.sh ~/arms.sh'
ssh teo@<lab-ip> 'bash ~/arms.sh idb64'      # smoke: 65 hits, 912 B deltas
ssh teo@<lab-ip> 'bash ~/arms.sh idb2000'    # 2001 hits, total 1824000 B
ssh teo@<lab-ip> 'bash ~/arms.sh idb1000'    # control at half depth
ssh teo@<lab-ip> 'bash ~/arms.sh widb2000'   # same walk on the worker thread (t=10)
ssh teo@<lab-ip> 'bash ~/arms.sh widb8'      # for the /proc/<pid>/maps stack-size measurement
ssh teo@<lab-ip> 'bash ~/arms.sh css128'     # 128 hits, 1520 B deltas
ssh teo@<lab-ip> 'bash ~/arms.sh css64'      # control at half depth
ssh teo@<lab-ip> 'bash ~/arms.sh clone20k'   # 1 hit  (iterative)
ssh teo@<lab-ip> 'bash ~/arms.sh clone41k'   # over maximumFilterRecursion -> JS RangeError
ssh teo@<lab-ip> 'bash ~/arms.sh mp20k'      # 1 hit on CloneDeserializer::deserialize()
ssh teo@<lab-ip> 'bash ~/arms.sh json100k'   # 100000 levels, iterative fallback

# release-shaped frames: same TU, same includes/defines, -O2 and no -fsanitize=address
scp research/stack-depth/mkrepro.sh teo@<lab-ip>:/tmp/
ssh teo@<lab-ip> 'distrobox enter wk --no-tty -- bash -lc "bash /tmp/mkrepro.sh"'
```

Logs: `data/stack-depth/G_*.log` (per-run gdb transcripts), `data/stack-depth/srv_*.log` (beacon server logs),
`data/stack-depth/maps_*.txt` (the `/proc/<pid>/maps` snapshot taken while each run was alive),
`data/stack-depth/summary.json` (hit counts, frames, totals).

## 10. Limits of this result

- The console's compiler and flags are unknown; the `-O2` frame is GCC 13 with this drop's headers, the ASAN
  frame is `-O1` + redzones. The number to hold against the console is the **262 B** threshold, not either frame.
- The recursion depth is measured at the function boundary; a walker that also pushes large temporaries *between*
  levels (the CSS arm measured `consumeRegularRuleList` including `consumeRuleList`/`consumeAtRule` in between,
  1 520 B/level) is captured, but a caller-side frame is not.
- The oracle's own thread size is 8 MiB, not the console's 512 KiB; `ulimit -s` does move it (measured 1 024 KiB),
  but nothing in this doc is scored under the console's number — that is the next action.
- Nothing here is a memory-safety primitive: a stack overflow in a worker is a DoS (or, unguarded, corruption),
  and stage criterion 3 still needs a bug that copies engine bytes into JS.
