# 90 — the family behind the deserialization abort: six dispatch sites, one page-reachable throw

`GOAL.md` item 1. `docs/89` measured one member of the family behind

```
RELEASE_ASSERT(vm.hasPendingTerminationException());   // MessagePort.cpp:295, WorkerMessagingProxy.cpp:245
```

and recorded it as "a DoS, not a primitive" with a two-line repro. This run answers the action's two
questions — **how many page-reachable ways are there to make message deserialization fail, and which of
them need a resizable ArrayBuffer** — and corrects the count in `docs/89`: the assert is not in two
places, it is in **six**, in five files, and this run reaches all six from page script. Four of them
abort the WebProcess with the `docs/89` input. The other two are measured **not** to abort, each for a
reason that is itself measured, and the reason is the same one that makes the whole family one-instance
wide: **the deserializer is written to fail cleanly** — 70 `fail()` returns, every allocation it
controls goes through a `try*` factory — and only a *thrown* exception can reach the assert.

Page: `research/fuzz-cssom/caps10.html` (md5 `daed8a5fc70ded2ca1a798dadcbc910e`, 428 lines, one
mechanism per `mode=`), service-worker half `research/fuzz-cssom/sw90d.js`
(md5 `bd658cf382fe62a0e64226f6d12d3be5`), runner `research/fuzz-cssom/c10run.sh`
(md5 `09ce097f572558943d37473538994e58`). Everything is `run_nq.sh` (**quarantine off**), one fresh
port per arm, and every arm is scored from the **harness** — `EXIT` plus a `WTFCrashWithInfo` frame
naming a dispatch site — never from a beacon. Beacon extracts and the nine abort signatures are in
`data/deser-family/` (`beacons.txt`, `abort_signatures.txt`, `arms.txt`).

---

## 1. Source: six sites, one per `MessageEvent::create` caller

`grep -rn hasPendingTerminationException Source/WebCore Source/WebKit` gives six of this shape:

```cpp
auto event = MessageEvent::create(*globalObject, message.message.releaseNonNull(), …);
if (UNLIKELY(scope.exception())) {
    // Currently, we assume that the only way we can get here is if we have a termination.
    RELEASE_ASSERT(vm.hasPendingTerminationException());
    return;
}
```

| site | caller | message reaches it from |
|---|---|---|
| `BroadcastChannel.cpp:256` | `BroadcastChannel::dispatchMessageEvent` | another `BroadcastChannel` (no transfer list in this IDL) |
| `LocalDOMWindow.cpp:947` | `LocalDOMWindow::processPostMessage` | `window.postMessage(msg, target, transfer)` / `(msg, {transfer})` |
| `MessagePort.cpp:295` | `MessagePort::takeAllMessages` handler | `port.postMessage(msg, [buf])` |
| `WorkerMessagingProxy.cpp:199` | `WorkerMessagingProxy::postMessageToWorkerObject` | **worker → document** (`worker.postMessage`) |
| `WorkerMessagingProxy.cpp:245` | `WorkerMessagingProxy::postMessageToWorkerGlobalScope` | **document → worker** |
| `ServiceWorkerContainer.cpp:472` | `ServiceWorkerContainer::postMessage` | **service worker → page** (`client.postMessage`) |

`docs/89` knew two of them (`MessagePort`, `WorkerMessagingProxy:245`) and generalised "the class is
wider than the instance" without counting; the correction is that the class is six sites and that only
**four** of them are reachable with the one input this programme has.

## 2. Source: why `fail()` cannot fire the assert, and which two calls can throw

`MessageEvent::create` (`dom/MessageEvent.cpp:66-84`) deserializes with
`SerializationErrorMode::NonThrowing` and only reads `didFail`:

```cpp
auto deserialized = data->deserialize(globalObject, &globalObject, ports, SerializationErrorMode::NonThrowing, &didFail);
…
auto& eventType = didFail ? eventNames().messageerrorEvent : eventNames().messageEvent;
```

and `SerializedScriptValue::deserialize` only calls `maybeThrowExceptionIfSerializationFailed` when the
mode is `Throwing` (`:5585`). So a `SerializationReturnCode` other than `SuccessfullyCompleted` is
**clean**: `MessageEvent::create` produces a `messageerror` event and **no pending exception**, and the
`RELEASE_ASSERT` is not reached. What reaches it is an exception thrown *inside* the deserializer (or by
`transferArrayBuffers`) that nothing clears.

`CloneDeserializer` has **57 `fail();` call sites** (`grep -c 'fail();'` — the first at `:2115`, the last at
`:5006`) and every one of
them funnels into `ValidationError` at `:5006`. Every allocation it controls goes through a `try*`
factory and then `fail()`: `JSBigInt::tryCreateWithLength`/`tryCreateZero` (`:4409-4444`),
`ArrayBuffer::tryCreate` (`:3249`, `:3266`), `StringImpl` length guards (`:3149`),
`ImageData::createUninitialized`'s `ExceptionOr` (`:4288`). **Two `JSC` calls are not in that style:**

1. **`constructEmptyArray` (`:4847`)** — the only `scope.exception()` check in the whole deserializer
   (`:4848`). `constructEmptyArray` → `JSArray::tryCreate` → `throwOutOfMemoryError` when the array
   factory returns null. Measured **unreachable** from a page payload: §6.
2. **`JSDataView::create`, through `DataView::wrapImpl` (`runtime/DataView.cpp:65`)** — `readArrayBufferViewImpl`
   (`:3317`) calls `toJS(…, DataView::wrappedAs(buffer, byteOffset, length).get())` and the DataView
   wrapper *verifies* (`JSDataView.cpp:58-59`, `throwRangeError("Length out of range of buffer")`), where
   every typed array's `wrapImpl` uses the non-verifying `create` (`GenericTypedArrayViewInlines.h:145`).
   `DataView::wrapImpl` has a second exit that matters: `DataView::wrappedAs` (`runtime/DataView.cpp:47-58`)
   *skips* the sub-range check when the buffer is resizable — and **returns nullptr** when it is not.
   `toJS(nullptr)` is `jsNull()`, with no exception, so a non-resizable buffer degrades the view to
   `null` instead of throwing.

On the **sender** side nothing can reach the assert by construction: duplicate/detached/locked/
non-transferable transfer entries are rejected at `SerializedScriptValue.cpp:5377-5440`, and
`transferArrayBuffers` returns `Exception { TypeError }` if `transferTo` fails (`:5236-5255`) — in both
cases `create` returns an exception and `postMessage` throws, so no message and no deserializer.

## 3. The arms, and the four sites that abort

`caps10.html?mode=…` — one mechanism per arm, `delay=100` so the capability beacon is on the wire before
an arm can kill the process. `len=192` throughout; the capability line is identical for every arm:

```
cap&mode=dvport&n=268435457&len=192&reps=1&delay=100&resize=function&mc=function&wk=function&sc=function&agg=function&sw=object&pm3=1
```

| arm | `mode=` | what changes | result |
|---|---|---|---|
| K4 | `dvport` | DataView + resizable + shrink + `[buf]`, MessagePort | **abort** `MessagePort.cpp:295` |
| A4, R1, R2 | `dvwin` | same over `window.postMessage(msg,'*',[buf])` | **abort** `LocalDOMWindow.cpp:947` (3/3) |
| A5 | `dvwinopt` | same over `window.postMessage(msg,{transfer:[buf]})` | **abort** `LocalDOMWindow.cpp:947` |
| B2, R3 | `dvwksend` | a blob worker builds the message and posts it to the document | **abort** `WorkerMessagingProxy.cpp:199` (2/2) |
| B3 | `dvwkrecv` | the document posts it to a blob worker | **abort** `WorkerMessagingProxy.cpp:245`, thread **T9** |
| E4/E7 | `dvsw` | a service worker builds it and `client.postMessage`s it | **no abort**: the page receives `v === null` |
| H4 | `bcshrink2` | the same view and the same shrink over a `BroadcastChannel` | **no abort**: the DataView arrives intact |

The aborting arms all beacon the getter evidence first — the walk ran and the buffer was detached:

```
wxR0&mode=dvport&len=192&gx=192&gx2=0&gerr=-&gn=1&ms=1&post=1&tx=0            (K4)
wxR0&mode=dvwin&len=192&gx=192&gx2=0&gerr=-&gn=1&ms=1&post=1&tx=0             (A4)
wxR0&mode=dvwinopt&len=192&gx=192&gx2=0&gerr=-&gn=1&ms=0&post=1&tx=0          (A5)
wxR0&mode=dvwksend&len=192&gx=-1&gx2=-1&gerr=-&gn=0&sent=1                    (B2 — the getter ran in the worker)
wxR0&mode=dvwkrecv&len=192&gx=192&gx2=0&gerr=-&gn=1&ms=1&post=1&tx=0          (B3)
```

`gx=192` is what the getter read inside the walk, `gx2=0` the shrink it performed, `tx=0` the sender's
buffer afterwards. `B2`'s `gn=0` is correct and is the arm's own witness that the page's getter was never
called: that message was built in the worker.

The abort signatures are one shape, four sites (`data/deser-family/abort_signatures.txt`):

```
#3 … WTFCrashWithInfo(int, char const*, char const*, int) …wtf/Assertions.h:762
#4 … operator() /home/<user>/wk/WebKit/Source/WebCore/dom/MessagePort.cpp:295                         (K4)
#4 … operator() /home/<user>/wk/WebKit/Source/WebCore/page/LocalDOMWindow.cpp:947                      (A4, A5, R1, R2)
#4 … operator() /home/<user>/wk/WebKit/Source/WebCore/workers/WorkerMessagingProxy.cpp:199             (B2, R3)
#4 … operator()<WebCore::ScriptExecutionContext> …/workers/WorkerMessagingProxy.cpp:245             (B3)
```

`EXIT=124` in every arm, aborting or not: the abort is in the **WebProcess**, the UI process keeps
running until `timeout` — the same artefact `docs/89` §6 records. The score is the frame, not the exit
code.

## 4. The two sites that do **not** abort, and why (both measured)

### 4.1 The service worker: a 0-byte transfer loses resizability on the way back

The SW arm is fully wired. `sw90d.js` registers, activates, claims, receives the page's request, builds
the shrink message and posts it to the client — the SW-side beacons are the proof:

```
sw90d&recv=1&mx0=192&bl0=192&vl=192
sw90d&getter=1&pre=192
sw90d&getter2&post=0&mx=192          <- resize(0) worked; the buffer is still resizable in the SW
sw90d&posted=1&bl=0&mx=0             <- after postMessage the buffer is detached (0/0)
```

and the page receives the message, but with a **null** view and no exception:

```
rxR0&mode=dvsw&…&fromsw=1&rxv=0&vb=-1&bb=-1&keys=c,v,fromsw,g&c=1&go=undefined&tv=object&tn=1&tu=0
```

`tn=1` is `d.v === null`. That is `DataView::wrappedAs` returning nullptr — the non-resizable exit — not
`JSDataView::create` throwing. The variable was measured on both sides of the IPC:

| probe | transfer | SW side | page side |
|---|---|---|---|
| E6 `swres&probe=1` | resizable **192-byte** buffer | `mx=192&bl=192` | `mx=192&bl=192` |
| F2 `swres&probe=2` | resizable buffer **shrunk to 0** | `mx=192&bl=0` | **`mx=0&bl=0`** |
| G1 `mxprobe` | the same 0-byte buffer over a **MessagePort** | `tmx=192&tbl=0` | **`mx=192&bl=0`** |

So the 0-byte contents cross the SW→client IPC as a **non-resizable** ArrayBuffer while the identical
transfer inside one document stays resizable. With `mx=0`, `DataView::wrappedAs` takes the verifying
branch, `verifySubRangeLength(0-byte buffer, 0, 192)` fails, it returns nullptr, `toJS` yields `jsNull`,
`readArrayBufferViewImpl` returns **true** — the message completes, `v` is null, nothing is thrown and
`ServiceWorkerContainer.cpp:472` is never reached. **The site is reachable, the abort is not, and the
reason is measured, not argued.**

### 4.2 `BroadcastChannel`: no transfer list, so the payload cannot disagree

`dom/BroadcastChannel.idl:34` is `postMessage(any message)` — no transfer argument (`docs/67`). The
buffer is therefore written **in-line at the view's dump point**
(`dumpArrayBufferView` → `dumpIfTerminal(toJSArrayBuffer(...))`, `:1401`), i.e. with the byteLength it has
*before* any later getter runs. The shrink cannot make the payload and the contents disagree, and the
order that would (`{buf, getter, view}`) is rejected by the serializer's own `isOutOfBounds()` guard
(`dumpArrayBufferView:1372`) as a `DataCloneError`. Measured — the same view, the same shrink, the DataView arrives intact:

```
wxR0&mode=bcshrink2&bcplain=0&post=1&gx=192&tx=0
rxR0&mode=bcshrink2&bcplain=0&rxv=1&vb=192&bb=192&mx=384&gv=1
```

One instrument defect found on the way and fixed: a `BroadcastChannel` does **not** deliver a message to
the posting object in this build (`bcshrink`, same object: neither `message` nor `messageerror` in 3 s),
so the arm needs a **second** channel with the same name — `bcshrink2` is that build, and `bcplain=1` is
its no-shrink twin.

## 5. The one mechanism, stated exactly

Four things, all required (`docs/89` §3 measured the four-way isolation; this run re-verified the axis
with the shipped page):

1. a **`DataView` built with an explicit `byteLength`** — an auto-length view records `autoLengthMarker`
   and derives its length at read time, so it cannot disagree;
2. a **resizable** `ArrayBuffer` (`new ArrayBuffer(n, {maxByteLength: n})`);
3. a getter the serializer walks **after** the view was dumped (`Object.defineProperty(msg,'g',{get})`
   with the view inserted first) that **shrinks** the buffer;
4. the buffer in the **transfer** list.

Why those four: `CloneSerializer::serialize` runs the whole walk before `transferArrayBuffers` detaches
(`docs/89` §1), so the view's explicit length is frozen at 192 while the buffer the receiver builds from
the transferred contents is 0 bytes. A typed array in the same position merely becomes an out-of-bounds
view (`vl=0`, writes dropped); a `DataView` goes through the verifying `create` and throws.

## 6. The array family is a measured negative, on both sides of the boundary

`constructEmptyArray` is the deserializer's only other `scope.exception()` site, and a page *can* steer
the length it receives — so it looked like a second member that would need no resizable buffer at all. It
is not one, and the reason is the array storage, not the check:

- `JSArray::tryCreate(vm, structure, initialLength)` takes the **ArrayStorage** branch for
  `initialLength >= MIN_ARRAY_STORAGE_CONSTRUCTION_LENGTH`, and that branch allocates
  `ArrayStorage::sizeFor(BASE_ARRAY_STORAGE_VECTOR_LEN)` — a **fixed** vector (`runtime/JSArray.h:192-204`).
  The length is free; only the public length field is set.
- The `initialLength > MAX_STORAGE_VECTOR_LENGTH` guard (`IndexingHeader::maximumLength = 0x10000000`,
  `IndexingHeader.h:42`) is in the *contiguous* branch only (`JSArray.h:220`), which a deserialized array never takes at these
  lengths.

Measured, one variable apart, all through a `MessagePort`:

| arm | length | walk (sender) | result |
|---|---|---|---|
| TIME1 | 1,000,000 | `ms=82` | arrives, `al=1000000` |
| TIME2 | 10,000,000 | `ms=809` | arrives, `al=10000000` |
| TIME3 | 50,000,000 | `ms=3989` | arrives, `al=50000000` |
| ARROOM | **0x10000001** (one **past** `maximumLength`) | `ms=22306` | arrives, `al=268435457` |
| D1 | **0x10000000** (exactly `maximumLength`) | `ms=21767` | arrives, `al=268435456` |

```
wxR0&mode=arroom&n=268435457&al0=268435457&ms=22306&post=1
rxR0&mode=arroom&n=268435457&al0=268435457&al=268435457&cn=0
wxR0&mode=arrmax&n=268435456&al0=268435456&ms=21767&post=1
rxR0&mode=arrmax&n=268435456&al0=268435456&al=268435456&cn=0
wxR0&mode=arroomclone&n=268435457&al0=268435457&ms=21268&clerr=-&cln=268435457
```

Both sides of the boundary behave identically, `structuredClone` of the same array clones it
(`cln=268435457`), and the cost is linear and small: **≈80 ns per hole** (82 ms / 809 ms / 3,989 ms for
1e6 / 1e7 / 5e7), which is why the 268 M-element arms take ≈22 s in the sender and still arrive. The
array path cannot throw from a page payload; the walk is expensive but the allocation is not.

The other candidate inputs of the same shape are also measured clean:

```
wxR0&mode=tlreject&dup=DataCloneError&detached=DataCloneError&plain=DataCloneError
rxR0&mode=agg&name=Error&msg=boom&nerr=-1&str=Error: boom
```

— the three sender-side transfer-list rejections (`:5377` duplicate, `:5381`/`:5399` detached, `:5440`
non-transferable) all throw **at `postMessage`**, so no message exists; and an `AggregateError` in the
message round-trips as a plain `Error` (`nerr=-1`: the `errors` list is not serialized) with no abort,
i.e. `ErrorInstance::create` does not throw (`runtime/ErrorInstance.cpp:49-56`).

## 7. Controls on the one mechanism (shipped page, md5 `daed8a5f`)

```
wxR0&mode=dvportok&len=192&gx=192&gx2=-1&gerr=-&gn=1&ms=0&post=1&tx=0          no shrink
rxR0&mode=dvportok&…&rxv=1&vb=192&bb=192&gv=1
wxR0&mode=dvgrow&len=192&gx=192&gx2=384&gerr=-&gn=1&ms=1&post=1&tx=0         resize(384), not (0)
rxR0&mode=dvgrow&…&rxv=1&vb=192&bb=384&gv=1
wxR0&mode=dvclone&len=192&gx=192&gx2=0&gerr=-&gn=1&ms=6&clerr=TypeError&clmsg=Unable to deserialize data.&clv=0&tx=0
```

- **no shrink** → the view arrives at 192 bytes, no abort (`K1`, 2/2 with `A2`).
- **grow instead of shrink** → `gx2=384`, the view still fits, arrives, no abort (`K2`, 2/2 with `C1`).
  The first build of the grow arm was **not** a control: `SHRINK` was `/^dv/` minus one name, so
  `dvgrow` called `resize(0)` and reproduced the abort (`A3`, site `MessagePort.cpp:295`). Fixed and
  re-run; the faulty arm is kept in `data/deser-family/arms.txt` as the reminder.
- **`structuredClone` of the same message, transfer list included** → a catchable `TypeError("Unable to
  deserialize data.")`, `v` absent, **no abort**, 3/3 (`K3`, `F1b`, `F1c`). This is the sharpest control
  in the run: identical input, identical walk and transfer, and the failure is only fatal because of the
  *error mode* of the caller (`NonThrowing` + `RELEASE_ASSERT`), not because of the input.

## 8. Limits, corrections, method notes

- **The abort is a DoS, not a primitive.** No attacker byte is read or written; the process dies in
  `MessageEvent::create`'s caller before any message is dispatched. `RELEASE_ASSERT` is not compiled out
  of release builds, so the console behaviour is expected to be the same *if* the console build keeps
  `Options::useResizableArrayBuffer` (default true, `OptionsList.h:578`). **Unmeasured on hardware** —
  the Guide app still needs the operator's restart.
- **Which exception actually trips the assert is not measured, and `docs/89` over-states it.**
  `docs/89` says `JSDataView::create` throws `RangeError("Length out of range of buffer")` and cites
  `JSDataView.cpp:35`; in this drop line 35 is `DataView::DataView` (the constructor) and the two throws
  are at `:52` (`throwTypeError`, detached) and `:59` (`throwRangeError`, length). The ASAN stack of every
  aborting arm ends at the `RELEASE_ASSERT`, so it does not carry the throw's identity, and the
  `structuredClone` control reports the deserializer's `ValidationError`
  (`"Unable to deserialize data."`) rather than either. What *is* measured is that the message's buffer is
  resizable on the local paths (`mx=192`, `G1`) and not on the SW path (`mx=0`, `F2`), which is the only
  variable that decides between the throw and the null. Both candidate throws are in `JSDataView::create`,
  so the family claim does not depend on which one it is.
- **`docs/89`'s "two sites, two spellings" is corrected to six sites** (§1). The `LocalDOMWindow` site
  (`window.postMessage`, both IDL spellings) and `WorkerMessagingProxy:199` (worker → document) are new
  here; `ServiceWorkerContainer:472` and `BroadcastChannel:256` are the two that do not abort, for the
  reasons in §4.
- **Not claimed:** that the deserializer can leave a pending exception through any other path — §2 is a
  census of every `scope.exception()` and every `try*`/`fail()` in the file, and the two non-conforming
  calls are both measured (§6, §7). Also not claimed: anything about a second document, `SharedArrayBuffer`
  (`useSharedArrayBuffer` false), or a worker in a **separate process** — every arm here is one WebProcess.
- **Method: the harness sometimes never loads the page.** 4 of 39 arms (`F1_dvclone`, `H1_bcshrink`,
  `H3_bcplain`, `R4_dvport`) produced an empty server log — MiniBrowser started, no request arrived, no
  beacon, no crash — and were re-run unchanged (`F1b`, `H1b`, `H2`, `R5`, all of which did load). Any arm
  scored "none" must first be checked against `/tmp/srv<port>.log`: "no site" with no request is a
  harness non-start, "no site" with a full beacon set is a result. `R4` is the case that matters, because
  it is the arm that *does* abort: re-run as `R5`, it aborted at `MessagePort.cpp:295` again.
- **The ship revision matters.** `caps10.html` grew one `mode=` at a time; the aborting arms were re-run
  on the final build (`R1`–`R5`, `K1`–`K4`) and the site is identical to the first build's (`A1`,
  `MessagePort.cpp:295`; 3/3 for that site across two revisions). Arms that ran on earlier builds are
  named in `data/deser-family/arms.txt` with their site, and the `dvgrow` instrument defect above is the
  only change that ever moved a result.
