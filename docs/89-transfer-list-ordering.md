# 89 — the transfer list: the walk runs before the detach, and a mid-walk shrink aborts the WebProcess

`GOAL.md` item 1. `docs/67` closed the top-ranked deserialization candidate (`cfe38930db`) on the
**BroadcastChannel** spelling, for a reason that does not generalise: `dom/BroadcastChannel.idl:34`
declares `postMessage(any message)` with no transfer argument, so an ArrayBuffer is written in-line and
copied (`SerializedScriptValue.cpp:3238-3250`) and `m_arrayBufferContentsArray` (`:5187`) is never
reached. `workers/Worker.idl:35` and `dom/MessagePort.idl:35` both do have the argument:
`postMessage(any message, sequence<object> transfer)`. This run reaches that path, answers the three
questions the action asks (does the transfer happen, where does page script run relative to it, what
does the getter read mid-walk), and finds a fourth thing the action did not ask for: a
page-script-reachable, deterministic **WebProcess abort** on both dispatch spellings.

Pages: `research/fuzz-cssom/caps8.html` (md5 `7b12e1ce1f4817626de01cbae4f0e9d0`, the wiring probe),
`caps9.html` (md5 `b6acff3ec385e16a5c66c69b32121741`, one combination per arm), the new instrument
`seq5.html` (md5 `e82af40a01f49f423ad2a456e39ffa32`, 40 ops), builder `build_seq5.py`
(md5 `25ebe0897f9fd3ecd76a0b3355741f5f`), runner `wxrun.sh` (md5 `a178f2359412605f856653965182da95`,
one arm, fresh port, beacons decoded), scorer `score_seq.py` (md5 `1d12cbe09cfb9a189511fdff7eca3c40`,
beacon log → the numbers below). Everything is `run_nq.sh` (**quarantine off**) except §5's
calibration, which is `run_asan_page.sh` (**quarantine on**), and every number is scored from the
**beacon log** (`new Image().src='/ev?m=…'`), never from harness state. Beacon extracts and the
four abort signatures are kept in `data/transfer-list/` (`sweep_beacons.txt`,
`capability_beacons.txt`, `asan_signatures.txt`).

---

## 1. Source: the walk runs before the transfer, and the view's length is checked twice, differently

**(a) The ordering.** `SerializedScriptValue::create` (`:5356`) parses the transfer list first —
rejecting a duplicate object outright (`uniqueTransferables`, `:5377`: `DataCloneError, "Duplicate
transferable for structured clone"`), rejecting a detached or shared buffer, rejecting a locked one —
and records the buffers in `arrayBuffers` **without detaching anything**. Then:

```
5463    auto code = CloneSerializer::serialize(&lexicalGlobalObject, value, messagePorts, arrayBuffers, …);
…
5477    auto arrayBufferContentsArray = transferArrayBuffers(vm, arrayBuffers);
```

`CloneSerializer::serialize` is the whole walk, page getters included (`getProperty`, `:1197`). Only
`transferArrayBuffers` (`:5236`) calls `JSC::ArrayBuffer::transferTo`, which is where the buffer is
actually detached (`runtime/ArrayBuffer.cpp`: `if (!m_contents.m_data) { … return false; }` for an
already-detached buffer, otherwise `result = m_contents.detach()`).
**So a getter the serializer walks reads the buffer *before* it is detached, and the detach happens
after the walk returns.** Measured in §2 (`gx` vs `tx`).

**(b) What the payload records for a view** (`dumpArrayBufferView`, `:1379-1396`):

```cpp
if (UNLIKELY(jsCast<JSArrayBufferView*>(obj)->isOutOfBounds())) { code = DataCloneError; return true; }
…
if (arrayBufferView->isResizableOrGrowableShared()) {
    write(arrayBufferView->byteOffsetRaw());
    uint64_t byteLength = arrayBufferView->byteLengthRaw();
    if (arrayBufferView->isAutoLength()) byteLength = autoLengthMarker;   // UINT64_MAX, :141
    write(byteLength);
}
```

`isAutoLength()` is `buffer->isResizableOrGrowableShared() && !byteLength`
(`ArrayBufferView.cpp:38`): a view built **without** an explicit length over a resizable buffer records
the marker and no number at all; a view built **with** an explicit length records that number, raw,
whatever the buffer's size becomes later.

**(c) The read side checks the length twice, and the two checks disagree.** `readArrayBufferViewImpl`
(`:3279`) parses offset and length and does **no** range check of its own; it calls
`Uint8Array::wrappedAs(buffer, byteOffset, length)` (or `DataView::wrappedAs`), which *skips*
`verifySubRangeLength` when the buffer is resizable —

```cpp
// GenericTypedArrayViewInlines.h:107 — and DataView.cpp:56 with the same comment
// We do not check verifySubRangeLength for resizable buffer case […].  It is possible that
// verifySubRangeLength fails when underlying ArrayBuffer is resized, but it is OK since it will be
// just recognized as OOB TypedArray.
```

Then `toJS(..., impl)` → `wrap`, and **the two `wrapImpl`s do different things**:

```cpp
// GenericTypedArrayViewInlines.h — typed arrays: the NON-verifying create
JSArrayBufferView* GenericTypedArrayView<Adaptor>::wrapImpl(JSGlobalObject*, JSGlobalObject* globalObject)
{ return Adaptor::JSViewType::create(globalObject->vm(), …, this); }
// -> JSGenericTypedArrayView::create(VM&, Structure*, RefPtr<ViewType>&&): ASSERT(context), no check

// JSDataView.cpp / DataView::wrapImpl — DataView: the VERIFYING create
return JSDataView::create(lexicalGlobalObject, structure, possiblySharedBuffer(), byteOffsetRaw(),
                          isAutoLength() ? std::nullopt : std::optional { byteLengthRaw() });
```

and `JSDataView::create` (`JSDataView.cpp:35`; `JSGenericTypedArrayViewInlines.h:114` is the typed-array
twin, reachable from other call sites) **throws**:

```cpp
if (!ArrayBufferView::verifySubRangeLength(*buffer, byteOffset, byteLength.value_or(0), 1)) {
    throwRangeError(globalObject, scope, "Length out of range of buffer"_s);
    return nullptr;
}
```

`verifySubRangeLength` (`ArrayBufferView.h:143`) compares against `buffer.byteLength()` **now**. So the
comment's promise — "it will be just recognized as OOB TypedArray" — holds for typed arrays and fails
for `DataView`, whose wrapper goes through a constructor that refuses instead.

**(d) Both dispatch callers assume that exception cannot exist:**

```cpp
// dom/MessagePort.cpp:293-296   (workers/WorkerMessagingProxy.cpp:243-246, identical)
auto event = MessageEvent::create(*globalObject, message.message.releaseNonNull(), …);
if (UNLIKELY(scope.exception())) {
    // Currently, we assume that the only way we can get here is if we have a termination.
    RELEASE_ASSERT(vm.hasPendingTerminationException());
    return;
}
```

`RELEASE_ASSERT` is not compiled out of release builds. A deserialization that fails for any reason
other than termination therefore aborts the WebProcess — and §3 shows a page can cause exactly that.

---

## 2. Measured: the wiring, and the two numbers the action asked for

`caps8.html`, quarantine off, two builds on fresh ports — 9901 (`/tmp/srv9901.log`) and 9902
(`/tmp/srv9902.log`). The lines quoted below are the **second** build, which prints `gn`/`cn`; §6
records why the first build's `gx`/`gn` columns are unusable. The capability line first:

```
cap&resize=function&transfer=undefined&resizable=true&mc=function&wk=function&sc=function&portxfer=0
```

`ArrayBuffer.prototype.resize` exists, `ArrayBuffer.prototype.transfer` does **not**, a resizable
buffer really is resizable, MessageChannel/Worker/structuredClone are all present, and
`portxfer=0` — a buffer posted with `[buf]` arrives detached at the sender.

Each test posts `{ v: view, g: <enumerable getter> }` with `postMessage(msg, [buf])` over a
`MessageChannel` and beacons the sender's witnesses and the arrived view's shape:

```
wxAt&mode=plain&gx=192&gx2=-1&gerr=-&tx=-2&txe=-                                  (sender, before the task)
wxA&mode=plain&gx=192&gx2=-1&gerr=-&tx=0&txe=-&rxv=1&vl=192&vb=192&bb=192&mx=192&rd=0&wr=1&rd2=65
wxB&mode=res&gx=192&gx2=-1&gerr=-&tx=0&txe=-&rxv=1&vl=192&vb=192&bb=192&mx=192&rd=0&wr=1&rd2=65
wxC&mode=shrink&gx=192&gx2=0&gerr=-&tx=0&txe=-&rxv=1&vl=0&vb=0&bb=0&mx=192&rd=undefined&wr=1&rd2=undefined
wxD&mode=detach&gx=192&gx2=-1&gn=1&tx=0&txe=TypeError
wxE&mode=shrinkrev&gx=192&gx2=0&gerr=-&tx=0&txe=-&rxv=1&vl=0&vb=0&bb=0&mx=192&rd=undefined&wr=1&rd2=undefined
```

Read off, one variable per arm:

- **(a) the transfer is real.** `tx=0` in every arm that posted with a transfer list: after the call
  the sender's buffer has `byteLength === 0`. `rx=1` with `vb=192` on the receiving side. The
  `docs/67` B2/B3 shape (buffer copied, sender keeps it) is what `wxk=0` looks like in §4:
  `wxtx=200`.
- **(b) the getter runs inside `SerializedScriptValue::create`, before the detach.** `gx=192` in
  *every* mode — including `shrink`, where the getter itself then sets it to 0 (`gx2=0`) — and `gn=1`
  says it ran exactly once. Nothing anywhere reads 0 from a buffer that is about to be transferred.
- **(c) what a mid-walk shrink produces depends on whether the view carried a length.** `C`'s view was
  `new Uint8Array(buf)` — **auto-length**, so the payload carried `autoLengthMarker` and there was no
  number to disagree with: it arrives as `vl=0` because it derives its length from a 0-byte buffer.
  `E` (getter defined *before* the view, so the shrink lands first) is the ordering control and gives
  the same shape for the same reason.
- **`D` is the other way to make the two disagree and it does not work**: detaching the buffer inside
  the getter makes `transferTo` return false (`m_contents.m_data` is already null), so the whole
  `postMessage` throws **TypeError** and no message exists. Measured, `txe=TypeError`.

The first build of `caps8` stopped after `D` — a post that throws leaves no receiver to chain from, so
`E`, `F`, `G` never ran. Fixed with a 400 ms fallback timer per test and recorded here because the
first run's silence after `D` is otherwise indistinguishable from a hang.

---

## 3. Measured: the crash, isolated to one combination

`caps8`'s last run reached its `DataView` test and the WebProcess aborted:

```
==762581==ERROR: AddressSanitizer: ABRT … T0
    #3 WTFCrashWithInfo(int, char const*, char const*, int) …/wtf/Assertions.h:762
    #4 operator() /home/<user>/wk/WebKit/Source/WebCore/dom/MessagePort.cpp:295
    #6 WTF::Function<void (WTF::Vector<WebCore::MessageWithMessagePorts, …>&&, …)>::operator()(…)
    #8 operator() /home/<user>/wk/WebKit/Source/WebKit/WebProcess/WebCoreSupport/WebMessagePortChannelProvider.cpp:104
```

`MessagePort.cpp:295` is the `RELEASE_ASSERT` of §1(d): `MessageEvent::create` left a pending exception
that is not a termination. `caps9.html` then isolated the trigger — one combination per arm, one
variable apart, quarantine off:

| arm | `view` | resizable | shrink in the getter | what happened |
|---|---|---|---|---|
| 9912 | `DataView(buf,0,192)` | yes | no | arrives: `vl=undefined vb=192 bb=192 mx=192 rd=0 wr=1 rd2=65` |
| 9913 | `DataView(buf,0,192)` | no | no | identical — plain buffers are unaffected |
| 9914 | `DataView(buf,0,192)` | yes | yes | **abort**, `MessagePort.cpp:295`, thread T0 |
| 9945 | `DataView(buf,0,192)` | yes | yes | **abort** again, same site, `reps=1` (4th independent abort) |
| 9917 | `DataView(buf,0,192)` | yes | yes (worker) | **abort**, `WorkerMessagingProxy.cpp:245`, thread T9 |
| 9915 | `DataView(buf,0,192)` | yes | yes, getter **before** the view | `txe=DataCloneError` at `postMessage`; no message, no crash |
| 9916 | `DataView(buf,0,192)` | yes | yes, `structuredClone` (no transfer list) | `cl=1 vb=192 bb=192` — the data is copied, no mismatch, no crash |
| 9941 | `Uint8Array(buf,0,192)` | yes | yes | **no crash**: `vl=0 vb=0 bb=0 mx=192 rd=undefined wr=1 rd2=undefined` |
| 9942 | `DataView(buf)` (auto-length) | yes | yes | **no crash**: `vb=0 bb=0 mx=192 rde=RangeError wre=RangeError` |
| 9943 | `Uint8Array(buf,0,192)` | yes | no | control: `vl=192 vb=192` |
| 9944 | `Uint8Array(buf)` (auto-length) | yes | yes | **no crash**: `gx=192 gx2=0 gn=1 vl=0 vb=0` |

The arms 9911-9917 ran on the build before `u8x`/`dva` were added (their query strings do not use
them); 9941-9945 ran on the shipped build, and the two rows that carry the argument — the
explicit-length typed array and the two `DataView` spellings — were re-run there (9941/9942/9943/9944)
so no row rests on the earlier build alone. **Four independent aborts**, two call sites, two spellings.


So the crash needs **all four**: a `DataView` built with an *explicit* `byteLength`, an
`ArrayBuffer(…, {maxByteLength})` (resizable), a getter the serializer walks *after* the view was
dumped, and the buffer in the **transfer** list. Two independent spellings abort — the document's
`MessagePort` and a blob `Worker` — at two different call sites, which is the same class (§1(d)) and
not one bug in one caller.

Why typed arrays survive and `DataView` does not is §1(c), and it is a one-line asymmetry: the typed
array's `wrapImpl` uses the non-verifying `create(VM&, Structure*, RefPtr<ViewType>&&)` — the OOB view
the code comment promises — while `DataView::wrapImpl` uses the verifying `create(…, byteOffset,
byteLength)` that throws `RangeError("Length out of range of buffer")`. The typed-array row is the
control that proves the mismatch really arrived and was merely tolerated: the same shrink, the same
explicit length, an OOB view (`vl=0`, a write to `v[64]` silently dropped) and no exception anywhere.

Controls that matter as much as the positive:

- **the order control (9915).** With the getter *first*, the view is dumped after the shrink, and the
  serializer's own `isOutOfBounds()` guard (`:1379`) turns it into `DataCloneError` **before** writing
  anything — a catchable exception from `postMessage`, no engine abort. That is what the mismatch
  looks like when the ordering is the other way round, and it is why the crash is an ordering fact and
  not a "DataView is broken" fact.
- **`structuredClone` (9916)** has no transfer list, so the buffer is written in-line at dump time
  (192 bytes) and the clone is correct. The mismatch is specific to the **transfer** list, i.e. to
  `transferArrayBuffers` running *after* the walk.
- **no shrink (9912, 9913, 9943)** and **auto-length views (9911, 9942)** arrive intact. `9942` also
  shows the auto-length `DataView` over a 0-byte buffer is a *normal* 0-length DataView whose accessors
  throw `RangeError` in JS — not an engine failure.

---

## 4. The instrument: `seq5.html`

`build_seq5.py` reads `seq4.html` (md5 checked against `docs/88`'s `aea291c7beb30d601aedb6780b5b52e5`)
and never edits it. Two knobs and two ops, nothing else:

```js
  var WXT = K('wxt', '0') === '1';        // enable the two transfer ops
  var WXK = K('wxk', '1') === '1';        // 1 = postMessage(msg,[buf]); 0 = the same message, no list
```

- **`Mwx`** (weight 3): a 192-byte (200/208 on `b % 3`) buffer, a `Uint8Array` over it, and a message
  whose enumerable getter runs the docs/65 arming — `churnSheet()`, one `deleteRule(0)` on the inline
  sheet, `document.body.offsetHeight`, `moNudge()`, `extWindow()` under the docs/88 knobs — inside
  `CloneSerializer::serialize`, then a `MessageChannel` `postMessage(msg, [buf])` whose receiver
  records the arrived view's `length`/`byteLength`/`buffer.byteLength`.
- **`Awx`** (weight 3): the same message through a **dedicated** blob worker (`wxWorker`, its own
  `wxwrk`, not `docs/86`'s `wrk`, so `Aworker`'s path is untouched) which echoes the shape it received.

The view is `new Uint8Array(buf)` — auto-length on purpose, so the op cannot carry the §3 crash into
the sweep. The arming is the point: the serializer's frame now hosts the same free site `Cclone` uses,
in a different C++ frame, with a live transferred buffer in the same call.

Counters on `done`: `wxh` (getter hits), `wxgx` (what the getter read), `wxtx` (the same buffer's
`byteLength` after the call), `wxrx`/`wxrxok` (arrivals, and arrivals that carried a view),
`wxrxl`/`wxrxb`/`wxrxbuf` (the last arrived view), `wxerr`, `wxlast`.

**Wiring arm** (`only=Mwx,Awx&wxt=1&dbg=1&n=300`, port 9921, 262 ms):

```
done&…&wxh=60&wxgx=200&wxtx=0&wxlen=200&wxrx=31&wxrxok=59&wxrxl=192&wxrxb=192&wxrxbuf=192&wxerr=0&wxlast=
census&op=Mwx&n=29&e=0
census&op=Awx&n=31&e=0
wxe&n=1&vl=200&vb=200&bb=200&err=-        (… six of these, 200/200/200, 208/208/208, 208…)
```

All three numbers the action asks for are there: `wxgx=200` (the getter read the **full** length inside
the walk), `wxtx=0` (the buffer was detached by the call), `wxrxok=59` = 29 + 30 arrivals with the
length intact. The **axis control** is one knob away — port 9922, `wxk=0`:

```
done&…&wxh=60&wxgx=200&wxtx=200&wxlen=200&wxrx=31&wxrxok=59&…&wxerr=0
```

Every field identical except `wxtx=200`: without the transfer list the buffer is copied and the sender
keeps it. That is `docs/67`'s B2/B3 shape in this instrument, and it is what makes `wxtx=0` mean the
transfer and not the post.

---

## 5. Calibration and sweep

**Calibration** on the shipped page, quarantine **on**, six runs (`cal=1&n=0`, ports 9931-9936):
`heap-use-after-free` in **6/6** — 3 `WRITE of size 1` at `CSSFontFace.cpp:595` and 3 `READ of size 1`
at `:592`, every one at `0x610000046bc2` (base + `0x82`). The 3/3 split is `docs/85`'s client-order
coin flip, unchanged by the two new ops.

**Sweep** (quarantine off, `skip=Rpage,Rnest-link,Fdoc`, `then=1 ath=1 extf=0 extw=1 extm=1 mof=1
wxt=1`, `every=250`, four seeds × 20,000 rounds):

| arm | port | ops | windows `then` | `ath` | `ith` | transfers `wxh` | arrivals `wxrxok` | `wxtx` | `wxerr` | `ms` |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 10021 | 84,089 | 6,358 | 5,828 | 2,719 | 4,417 | 4,411 | 0 | 0 | 156,966 |
| S2 | 10022 | 83,968 | 6,379 | 5,852 | 2,672 | 4,574 | 4,570 | 0 | 0 | 157,106 |
| S3 | 10023 | 84,028 | 6,400 | 5,876 | 2,705 | 4,534 | 4,530 | 0 | 0 | 156,838 |
| S4 | 10024 | 84,361 | 6,459 | 5,986 | 2,638 | 4,491 | 4,486 | 0 | 0 | 156,563 |
| GC4 | 10025 | 84,089 | 6,358 | 5,828 | 2,719 | 4,417 | 4,411 | 0 | 0 | 229,827 |
| C2 | 10026 | 84,089 | 0 | 0 | 2,719 | 4,417 | 4,411 | 0 | 0 | 136,790 |

- **336,446 operations and 18,016 transfers in the four required arms**, 504,624 operations over the
  six; 0 sanitizer reports in six ASAN logs, 0 exceptions in the page (`errors: {}` for every arm).
- **`wxtx=0` in every arm** — every one of those 18,016 posted buffers really was detached, at every
  size (192/200/208), in a page that at the same time drives 25,596 `setStatus` windows and 23,542
  `Animation` windows. The transfer surface is not inert in the sweep.
- The arrivals match the posts within a few in flight: S1 `Mwx` census 2,189 + `Awx` 2,228 vs
  `wxrxok` 4,411 = 2,185 port arrivals + 2,226 worker echoes.
- **C2 is the window-axis control** (`then=0&ath=0`) and it has the *identical stream* (84,089 ops,
  same census for every op) with `then=0`, `ath=0`, and the transfer counters **unchanged**
  (`wxh=4,417`, `wxrxok=4,411`): the transfer surface does not depend on the FontFace window being
  installed. GC4 likewise reproduces S1's stream exactly (84,089 ops, identical census).
- **`moir=0` and `mofd=1,188`/`mofrem=1,188`** are unchanged from `docs/88` (§`mofearly=795`, i.e. the
  `__ran` guard skipped 795 early deliveries, as designed).
- **The GC arm is a negative and is stated as one.** `gc=1&gcmax=60` churned 400k objects inside 60
  windows and the witness never turned: `gcprobe pre=8/8&post=8/8` at `h=1..6` and `gcalive=8/8` at the
  end — **no collection was observed inside any sampled window in this run**, so nothing here claims
  "a GC ran inside a transfer". `docs/88` collected in 1 of 6 windows sampled; this run collected in 0.

---

## 6. Limits, and what this changes

- **The abort is a DoS, not a memory primitive, and it is not claimed as one.** No attacker byte is
  read or written: the process dies in `MessageEvent::create`'s caller before any message is
  dispatched. What makes it worth a doc is that it is **sanitizer-free by construction** —
  `RELEASE_ASSERT` is enabled in release — and that it is reached entirely from page script with no
  worker/console requirement beyond `ArrayBuffer.prototype.resize`.
- **The class is wider than the instance.** §1(d) is a claim about *any* deserialization failure that
  is not a termination: the two callers have no other way out. This run exhibits one member with a
  two-line repro; it does not enumerate the family, and the next action is exactly that enumeration.
- **Not carried in the alphabet on purpose.** A deterministic abort would end every arm that drew the
  op and mask everything downstream, so `seq5.html`'s ops use an auto-length view and cannot produce
  the mismatch. The repro lives in `caps9.html` and is one query string long:
  `caps9.html?view=dv&res=1&shrink=1&reps=1` (aborts), with `rev=1`, `shrink=0`, `res=0`, `view=u8x`
  and `recv=clone` as the five controls above.
- **Console:** the crash needs `ArrayBuffer.prototype.resize`, i.e. `Options::useResizableArrayBuffer`
  (`OptionsList.h:578`, default **true** in this drop; `useSharedArrayBuffer` is `:579`, default false
  and only Cocoa XPC sets it). Whether the console build keeps the JSC default is **unmeasured** — the
  Guide app still needs the operator's restart — so this is a predicted DoS on hardware, not a measured
  one.
- **Not claimed:** that the getter ever observes the detached state (it cannot — it runs before the
  detach, which is the measurement), that any JS-observable out-of-bounds view exists (the typed-array
  row is an OOB view whose accesses are dropped, and the explicit-length `DataView` never arrives at
  all), or that `m_arrayBufferContentsArray` itself is read out of bounds (`computeMemoryCost` at
  `:5187` walks the contents array, but every `ArrayBufferContents` in it comes from
  `transferArrayBuffers` and no page input changes its size — `docs/67`'s finding that the writer and
  the declared length cannot disagree stands).
- **One method note.** The first `caps8` build beacons its sender-side witnesses from a snapshot string
  built *before* the post, so its `gx`/`gn` columns read `-1`/`0` for every arm. `caps9` builds the
  string at beacon time and is the one to trust; the numbers in §2 are from the fixed build. A getter
  that runs inside the walk cannot be measured by anything captured before the call.
