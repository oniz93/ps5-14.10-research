# docs/91 — a failed wrapper creation in the deserializer: where the null is stored, and why it is inert

`docs/90` ended on a shape, not a bug: `readArrayBufferViewImpl` calls `toJS(...)` for a
`DataView`/typed-array wrapper, **never looks at the result**, and returns `true`. When the wrapper
cannot be created the value is `jsNull()`; when it cannot be created *and* an exception is left
pending, the four `RELEASE_ASSERT` dispatch sites die on it. This document answers the part the abort
hides, because it is the only remaining route from this shape to stage criterion 3:

1. **Which** wrapper-creation results in `SerializedScriptValue.cpp` are not null-checked (§1 — all of
   them except two, and only one family can actually fail).
2. **Why** the native can be null, and why only the `DataView` spelling can throw (§2).
3. Whether the null is **stored**, whether an object-pool **reference** to it resolves to it, and what
   page script sees (§3, §4 — measured: yes, it is stored, and it is inert).
4. The **second** unchecked site, `cryptoKey = getJSValue(result.get())`, and its reachability (§5 —
   measured on three key classes: the native is never null for a key a page can produce).

**Result: negative, and the negative is complete for this shape.** A failed view wrapper is stored as
`null`, is reachable through the object pool, is consumed by page script as an ordinary `null` (a
`TypeError` at worst, thrown by the page's own property read), and cannot become an object of the
wrong type, because the deserializer's only typed consumer of a pooled value re-checks
`inherits<JSArrayBuffer>()` before it uses it. The one throwing input is `DataView`-only, needs a
resizable `ArrayBuffer` **in a transfer list**, and every transport that carries a transfer list is
one of the four asserting call sites — so that input is always a crash, never a value.

## 1. The audit — every `toJS` / `toJSNewlyCreated` / `wrap` site in the deserializer

`grep -n "toJS\|toJSNewlyCreated\|\bwrap\b\|wrapImpl\|wrappedAs"` over
`Source/WebCore/bindings/js/SerializedScriptValue.cpp` gives 41 lines: 3 serializer-side calls
(1097, 1110, 1333), the `getJSValue` template definition itself (3864/3866), 3 `toJS(context)` API
entry points (5530, 5535, 5592), and **35 deserializer call sites**, aggregated into the 21 rows
below. Each row was read in its enclosing function. "Native can be null" is a property of the
*expression* passed in; "throws" is a property of the wrapper-creation path the binding takes.

| # | line(s) | expression / native | result checked? | native can be null | wrapper create can throw | page-reachable |
|---|---------|--------------------|-----------------|--------------------|--------------------------|----------------|
| 1 | 3318, 3321, 3324, 3327, 3330, 3333, 3336, 3339, 3342, 3345, 3348, 3351 (12 sites) | `X::wrappedAs(arrayBuffer.releaseNonNull(), byteOffset, length).get()` — DataView + 11 typed arrays | **no** — `return true` on the next line | **yes**, `wrappedAs` returns nullptr | **yes for DataView only** (§2) | **yes** |
| 2 | 3848 | `getJSValue(result.get())` — `RefPtr<CryptoKey>` from `CryptoKey*::import*` | **no** — `cryptoKey = …; return true` | **yes in principle** (import can fail) | no | yes, but the key is re-imported from bytes the page cannot forge (§5) |
| 3 | 3885 | `toJSNewlyCreated(…, T::create(x,y,z,w))` — `DOMPoint` | no (nothing to check) | no — `Ref` | no | yes |
| 4 | 3916, 3968 | `toJSNewlyCreated(…, T::create(WTFMove(matrix), Is2D))` — `DOMMatrix`/`DOMMatrixReadOnly` | no | no — `Ref` | no | yes |
| 5 | 3988 | `toJSNewlyCreated(…, T::create(x,y,width,height))` — `DOMRect` | no | no — `Ref` | no | yes |
| 6 | 4021 | `toJSNewlyCreated(…, DOMQuad::create(…))` | no | no — `Ref` | no | yes |
| 7 | 4039 | `getJSValue(bitmap)` — `m_imageBitmaps[index]`, `ImageBitmap::create` one line above | no | no — `Ref` | no | yes |
| 8 | 4056, 4067 | `getJSValue(offscreenCanvas)` / `m_inMemoryOffscreenCanvases[index]` | no | no — `Ref` | no | `ENABLE(OFFSCREEN_CANVAS_IN_WORKERS)` |
| 9 | 4114 | `toJSNewlyCreated(…, WTFMove(rtcCertificate))` | no | no — `Ref` | no | `ENABLE(WEB_RTC)` |
| 10 | 4131 | `getJSValue(m_rtcDataChannels[index].get())` | no | no — `Ref` | no | `ENABLE(WEB_RTC)` |
| 11 | 4148 | `getJSValue(m_videoChunks[index].get())` | no | no — `Ref` | no | `ENABLE(WEB_CODECS)` |
| 12 | 4162 | `getJSValue(m_videoFrames[index].get())` | no | no — `Ref` | no | `ENABLE(WEB_CODECS)` |
| 13 | 4200 | `getJSValue(bitmap)` (`readImageBitmap`, the copy path) | no | no — `Ref` | no | yes |
| 14 | 4212 | `getJSValue(exception)` — `DOMException::create` | no | no — `Ref` | no | yes |
| 15 | 4383 | `toJS(…, file.get())` — `RefPtr<File>` from `readFile` | guarded *before* the call (`if (!m_canCreateDOMObject) return jsNull();`) | yes, but filtered by that same flag | no | yes |
| 16 | 4400 | `getJSValue(FileList::create(WTFMove(files)).get())` | no | no — `Ref` | no | yes |
| 17 | 4412 | `getJSValue(m_imageDataPool[*index])` | no | no — `Ref` | no | yes |
| 18 | 4451 | `getJSValue(result.releaseReturnValue())` | checked by `result.hasException()` just above | no | no | yes |
| 19 | 4468 | `getJSValue(Blob::deserialize(…))` | no | no — `Ref<Blob>` (`fileapi/Blob.h:89`) | no | yes |
| 20 | 4553 | `getJSValue(m_messagePorts[index].get())` | no | no — `Ref` | no | yes |
| 21 | 4668, 4681 | `getJSValue(m_arrayBuffers[index].get())`, `getJSValue(buffer.get())` | no | no — created inline | no | yes |

Both serializer-side call shapes are null-safe: `fillTransferMap` does `value.getObject()` then
`if (obj && …)`, and 1333 passes `&arrayBuffer`.

So the answer to "how many places can continue after a failed wrapper creation" is **one family**: the
twelve `wrappedAs` arms. Its native can be null in exactly two ways and its wrapper creation can throw
in exactly one way, and both are visible in the code:

```cpp
// SerializedScriptValue.cpp:3299-3303
RefPtr<ArrayBuffer> arrayBuffer = toPossiblySharedArrayBuffer(vm, arrayBufferObj);
if (!arrayBuffer) {
    arrayBufferView = jsNull();          // (a) no native -> jsNull, no exception
    return true;                          //     and the deserializer calls this success
}
...
case DataViewTag:
    arrayBufferView = toJS(m_lexicalGlobalObject, m_globalObject, DataView::wrappedAs(arrayBuffer.releaseNonNull(), byteOffset, length).get());
    return true;                          // (b) wrapper creation may have thrown here
```

## 2. Why only `DataView` can throw — the `wrapImpl` asymmetry

Both view classes share a `wrappedAs` that *skips* subrange verification when the buffer is resizable
(`runtime/DataView.cpp:51-63`, `runtime/GenericTypedArrayViewInlines.h:107-121`; the comment in both
says verification is skipped "since this function is only called from already created JS views"). The
difference is the next step, `wrapImpl`, which is what `toJS` invokes:

```cpp
// runtime/DataView.cpp:67-72
JSArrayBufferView* DataView::wrapImpl(JSGlobalObject* lexicalGlobalObject, JSGlobalObject* globalObject)
{
    return JSDataView::create(               // the VERIFYING overload
        lexicalGlobalObject, globalObject->typedArrayStructure(TypeDataView, isResizableOrGrowableShared()),
        possiblySharedBuffer(), byteOffsetRaw(),
        isAutoLength() ? std::nullopt : std::optional { byteLengthRaw() });
}

// runtime/GenericTypedArrayViewInlines.h:145-149
JSArrayBufferView* GenericTypedArrayView<Adaptor>::wrapImpl(JSGlobalObject*, JSGlobalObject* globalObject)
{
    return Adaptor::JSViewType::create(      // the NON-verifying overload: (vm, structure, impl)
        globalObject->vm(), globalObject->typedArrayStructure(Adaptor::typeValue, isResizableOrGrowableShared()), this);
}
```

`JSDataView::create` throws three times (`runtime/JSDataView.cpp:52` detached `TypeError`, `:59`
`RangeError("Length out of range of buffer")`, `:64` `RangeError("Byte offset is not aligned")`), each
followed by `return nullptr`. The typed-array path can throw too — `JSGenericTypedArrayView::create` at
`JSGenericTypedArrayViewInlines.h:115` has the same `RangeError` — but `wrapImpl` does not call it.
**That is the whole asymmetry, and it is why `docs/89`'s typed arrays arrive as out-of-bounds views
while the DataView spelling aborts the process.**

The out-of-bounds view is not a hole, and this is worth stating because it looks like one:
`JSDataViewPrototype.cpp:150/207` take `dataView->viewByteLength(getter)`, and
`JSArrayBufferView.h:59-78` returns `std::nullopt` as soon as `byteLengthRaw() + byteOffsetRaw() >
bufferByteLength`, so every `getX`/`setX` throws instead of touching memory. Measured on this build:
a typed array that arrives with `byteLength 0` over a 0-byte buffer answers `undefined` and drops a
write (§3, `taport`). And an out-of-bounds view cannot be re-serialized at all:
`SerializedScriptValue.cpp:1376` refuses with `DataCloneError` before dumping.

## 3. The arms

Page `research/fuzz-cssom/caps12.html` (final md5 `1d19801f33e75f07000abbd045601e4f`), SW half
`sw12.js` (md5 `20e217ce9debe8ba27023cbd61430dbd`), runner `c12run.sh` (md5
`1a8e167f746ca95796be9b8e9fb0c481`). One variable per arm; the design table is `ARMS` in the page, and
every arm has its twin named in the comment above it. Quarantine off (`run_nq.sh`) throughout; a fresh
port per arm; the score is the beacon log and the crash frame, never harness state.

| arm | transport | view | shrink | `LEN` | received on the page |
|-----|-----------|------|--------|-------|----------------------|
| `dvport` | MessagePort | `DataView(buf,0,n)` | yes | 192 | **abort** — `ABRT … MessagePort.cpp:295` (3/3) |
| `dvportok` | MessagePort | same | no | 192 | `DataView`, `vb192 bb192` |
| `dvportauto` | MessagePort | `DataView(buf)` (auto length) | yes | 192 | `DataView`, `vb0 bb0`, no abort |
| `dvsw` | SW → client | `DataView(buf,0,n)` | yes | 192 | **`null`** (`v=tn1,tyobject`), no abort (2/2) |
| `dvswok` | SW → client | same | no | 192 | `DataView`, `vb192 bb192` |
| `dvswauto` | SW → client | `DataView(buf)` | yes | 192 | `messageerror`, no abort |
| `dvswautook` | SW → client | `DataView(buf)` | no | 192 | `messageerror`, no abort |
| `poolsw` | SW → client | `{a:v,b:v,cc:[v,v],d:v}` | yes | 192 | `a,b,d,cc[0],cc[1]` all **`null`**, all identical (`ab1 ac01 ad1`) |
| `poolswok` | SW → client | same | no | 192 | four `DataView`s, `vb192 bb192`, identical |
| `tasw` | SW → client | `Uint8Array(buf,0,n)` | yes | 192 | **`null`** |
| `taswok` | SW → client | same | no | 192 | `Uint8Array`, `vb192`, `w0=7` |
| `taport` | MessagePort | `Uint8Array(buf,0,n)` | yes | 192 | **object**, `vb0 bb0`, write dropped (`w0=undefined`) |
| `taportok` | MessagePort | same | no | 192 | `Uint8Array`, `vb192`, `w0=7` |
| `ckport` | MessagePort | a generated `CryptoKey` (§5) | — | — | `CryptoKey`, `type=secret alg=HMAC ext=true us=sign.verify` |
| `cknonext` | MessagePort | non-extractable HMAC key | — | — | `CryptoKey`, `ext=false` |
| `ckec` | MessagePort | ECDSA P-256 pair | — | — | `private` + `public` `CryptoKey`s |

Exact commands and exact output (quoted from `/tmp/arms12.out` on the build box):

```
$ bash /tmp/wkp/c12run.sh F_POOLSW 12122 20 "mode=poolsw"
--- beacons (in order):
  cap&mode=poolsw&via=sw&kind=dv&shrink=1&pool=1&len=192&rs=function&sw=object&mc=function&stc=function
  wxA&mode=poolsw&reg=pending
  wxA&mode=poolsw&ready=1&act=1
  wxA&mode=poolsw&asked=1
  sw12&mk=1&kind=dv&mx0=192&bl0=192&vl=192&shr=1&pool=1
  sw12&getter=1&pre=192
  sw12&getter2&post=0&mx=192
  sw12&posted=1&bl=0&mx=0&keys=c.a.b.cc.d.g
  rxA&mode=poolsw&via=sw&v=tn0,tyundefined,tu1&a=tn1,tyobject&b=tn1,tyobject&d=tn1,tyobject&c0tn1&c1tn1&ab1&ac01&ad1&keys=c.a.b.cc.d.g&use=threw:TypeError&mapsz=1&json={"c":1,"a":null,"b":null,"cc":[null,null
  done&mode=poolsw&tag=A
--- abort:
  access: none
    EXIT=124
```

```
$ bash /tmp/wkp/c12run.sh F_DVPORT 12124 20 "mode=dvport"
--- beacons (in order):
  cap&mode=dvport&via=port&kind=dv&shrink=1&pool=0&len=192&rs=function&sw=object&mc=function&stc=function
  mkA&mode=dvport&mx0=192&bl0=192&vl=192
  getterA&mode=dvport&pre=192
  getter2A&mode=dvport&post=0&mx=192
  wxA&mode=dvport&via=port&post=1&tx=0
--- abort:
==874945==ERROR: AddressSanitizer: ABRT on unknown address 0x03e8000d59c1 (pc 0x7f686255d8a4 bp 0x7ffcf34e3880 sp 0x7ffcf34e3840 T0)
    #3 0x7f6870a5d1c2 in WTFCrashWithInfo(int, char const*, char const*, int) …/wtf/Assertions.h:762
    #4 0x7f6870a5d1c2 in operator() /home/<user>/wk/WebKit/Source/WebCore/dom/MessagePort.cpp:295
--- sites:
        1 MessagePort.cpp:295
```

```
$ bash /tmp/wkp/c12run.sh F_TAPORT 12123 20 "mode=taport"
  rxA&mode=taport&via=port&v=tn0,tyobject,vb0,bb0&…&json={"c":1,"v":{},"g":1}&w0=undefined
  done&mode=taport&tag=A
--- abort:
  access: none
```

```
$ bash /tmp/wkp/c12run.sh F_DVSW 12121 20 "mode=dvsw"
  rxA&mode=dvsw&via=sw&v=tn1,tyobject&…&json={"c":1,"v":null,"g":1}
  done&mode=dvsw&tag=A
--- abort:
  access: none
```

`EXIT=124` is the harness's normal end (`timeout` kills MiniBrowser), as `docs/65` "Attempt 11"
established; it is not a result in either direction. The discriminator is the ASAN/`WTFCrashWithInfo`
frame, or its absence plus a `done` beacon.

**What the four decisive arms say, one variable at a time.** `dvsw` vs `dvswok`: the shrink turns the
same message into `null` and changes nothing else (`mx0/bl0/vl` identical, `posted` identical).
`taport` vs `taportok`: the shrink turns the same message into a 0-length object. `dvport` vs
`dvportok`: the shrink turns the same message into a process abort. And `dvsw` vs `dvport` — the pair
that matters most here — is **one variable, the transport**: the identical payload, buffer state and
getter produce `null` over `client.postMessage` and an abort over a `MessagePort`, because the SW IPC
delivers the transferred buffer as non-resizable (`mx=0`, `sw12&posted=1&bl=0&mx=0`), so `wrappedAs`
declines before `wrapImpl` can throw. `docs/90` measured that once; it reproduces here in a second,
independent page.

`dvswauto`/`dvswautook` are a pair that came out **not** isolating the shrink, and the reason is worth
keeping: an auto-length view fails at `SerializedScriptValue.cpp:3311-3315`
(`if (!arrayBuffer->isResizableOrGrowableShared()) return false;`) because the *arriving* buffer is
non-resizable — with or without the shrink. So the auto-length spelling is a clean `messageerror` on
that transport in both directions, and over a `MessagePort` (`dvportauto`) it is a valid empty
`DataView` because 0 fits in 0. **The explicit-length spelling is the only one that reaches the
throw.**

## 4. The null is in the object pool, and everything that consumes it is inert

`poolsw` is the arm that answers "is the null *stored*": the message contains the same view four times,
so `CloneSerializer` dumps it once and writes three `ObjectReferenceTag`s. All four slots arrive
`null`, and `a === b`, `a === cc[0]`, `a === d` are all true — so the pool entry itself is
`jsNull()`, not four independent failures. Page script then consumes that slot in four ways and only
one throws: `new Map([[d.a,1]]).size` is `1`, `JSON.stringify` yields `null`, `Object.keys` is
unaffected, and `d.a.byteLength` throws a plain page-side `TypeError` (nothing sanitizer-visible,
`access: none`, `done` beacon after it).

The deserializer's consumer side is five `readTerminal()` sites (`grep -n "readTerminal()"`:
`3290`, `4871`, `4911`, `4981`), and only the first is typed:

```cpp
// SerializedScriptValue.cpp:3290-3293
JSValue arrayBufferValue = readTerminal();
if (!arrayBufferValue || !arrayBufferValue.inherits<JSArrayBuffer>())
    return false;
JSObject* arrayBufferObj = asObject(arrayBufferValue);
```

`inherits<>()` is false for `jsNull()` (`isCell()` is false), so a view whose buffer slot is a null —
i.e. a payload that names a failed view as another view's buffer — returns `false` and becomes a clean
`fail()` → `ValidationError` → `messageerror`. The other three sites feed
`putProperty(...)`/`outValue` (`:4872`, `:4912`, `:4982`), i.e. plain JS value positions where `null`
is a legal value. `addToObjectPool<ArrayBufferViewTag>(arrayBufferView)` (`:4691`) stores the null
deliberately, and the tag list stays aligned with the serializer's, so the object-pool *order*
invariant is untouched. There is no place left where a pooled value is used as an object without a
check.

That is the whole finding for the shape: **the fail-silent wrapper produces `null`, and `null` cannot
be made to look like a view.** For it to be a type confusion, some consumer would have to skip the
`inherits<>` test; the deserializer's only typed consumer is the one above.

## 5. The second unchecked site: `cryptoKey = getJSValue(result.get())`

`SerializedScriptValue.cpp:3848` passes a `RefPtr<CryptoKey>` from `CryptoKeyHMAC::importRaw`,
`CryptoKeyAES::importRaw`, `CryptoKeyRSA`, `CryptoKeyEC::importRaw`/`importPkcs8`,
`CryptoKeyOKP::importRaw` or `CryptoKeyRaw::create` (all `:3616`-`:3767`) straight into `getJSValue`
with no null test, so an import that returned null would put a `null` into the message the same way.
It is reachable from page script — `JSCryptoKey` is serialized at `:1852` through
`wrapCryptoKey` — so the reachability question is whether a page-produced key can fail to re-import
on the receiving side. Measured on three key classes, it cannot:

```
ckport  : genA&mode=ckport&tk=object&pair=false&type=secret
          rxA&mode=ckport&tk=object&nullk=0&undk=0&inst=true&type=secret&alg=HMAC&ext=true&us=sign.verify&keys=k
cknonext: rxA&mode=cknonext&…&inst=true&type=secret&alg=HMAC&ext=false&us=sign.verify&keys=k
ckec    : rxA&mode=ckec&…&inst=true&type=private&alg=ECDSA&ext=true&us=sign&tk2=object&nullk2=0&type2=public&keys=k.k2
```

All three arrive as real `CryptoKey` objects with their `algorithm`/`extractable`/`usages` intact, no
`messageerror`, no sanitizer line. The wire bytes are produced by the sender's own `wrapCryptoKey`, so
a page cannot hand the deserializer a key body its import will reject; this site therefore has the
same shape as (1) but no page-side null, and it stays in the table as "unchecked, not
page-inducible" rather than as a candidate.

## 6. Corrections, limits, and what this closes

- **Correction to the action's premise.** "A null in an object pool, a `Blob` with a null body, a `Map`
  key that is null where the payload says view" — of those, only the first exists. `Blob::deserialize`
  returns `Ref<Blob>` (`fileapi/Blob.h:89`, three call sites all `Ref`), `FileList::create` and
  `ImageData::createUninitialized` are `Ref`/`ExceptionOr` and checked, and `constructEmptyArray` is
  exception-checked at `:4847-4850` (and `docs/90` measured that it cannot throw from a page payload
  anyway).
- **Correction to `docs/89`'s typed-array note.** The OOB typed array is not "wrapped without
  verification by accident": `GenericTypedArrayView::wrapImpl` calls the *non-verifying* `create`
  overload on purpose (`GenericTypedArrayViewInlines.h:148`), and the clamp in
  `JSDataView.h:59-78`/`JSArrayBufferView.h:311-320` is what makes it inert. The DataView spelling
  differs only in calling the verifying overload.
- **A measured non-isolation, recorded as such:** `dvswauto`/`dvswautook` do not isolate the shrink on
  the SW transport (§3). The arm is still the pair's control for the *mechanism*, but it is not a
  shrink control.
- **Limits.** One `LEN` (192) on the SW arms; the SW path's `mx=0` was measured at 192 and 0
  (`sw90d.js` probe2) and not re-swept here; `MessagePort` arms are same-realm (a dedicated worker's
  port would add an IPC hop, `docs/89` measured that separately and it aborts identically); the
  `dvport` abort was reproduced on four ports (12103, 12115, 12116, 12124) and `dvsw` on three
  (12102, 12117, 12121); the four decisive arms were re-run on the final page build `1d19801f…`, the
  rest ran on build `876e1de9…`; every arm is named with its port and score in `data/deser-null/arms.txt`,
  and the raw per-port beacon sets are in `data/deser-null/beacons.txt`.
- **What this closes.** Stage criterion 3 cannot be reached from this shape by way of a null: a null
  is stored, is page-observable, and has no typed consumer that skips its check. The remaining value
  in this bug is the DoS (four abort sites, one input, release-build `RELEASE_ASSERT`) and the
  transport asymmetry itself — the same payload being `null`, an empty object, or a process abort
  depending only on which IPC it took. The next action returns to the search for a *write*: this
  document removes the fail-silent-wrapper hypothesis from the list.
