# docs/96 — the inverted `byteLength()` is reachable: IndexedDB's key builder reads an out-of-bounds resizable view

**Status:** measured 2026-10-30 on the drop (`SerializedScriptValue.cpp` `4e3d9ea5…`, quarantine off), page
`research/fuzz-cssom/caps15.html` md5 `60a9556b8af283814047e3953962065c`. One new **JS-visible read path**
and two crash spellings. **Not** stage criterion 3: every byte the bounded spellings can return is either
written by the page itself or a zero from the allocator.

---

## 0. What was open

`docs/95` §6 recorded a source-level deviation with a measured gate: the drop's
`ArrayBufferView::byteOffset()`/`byteLength()` test the bounds **inverted** relative to upstream main —

```cpp
// Source/JavaScriptCore/runtime/ArrayBufferView.h:98 (byteOffset) and :120 (byteLength)
if (UNLIKELY(!(byteOffsetStart > bufferByteLength || byteOffsetEnd > bufferByteLength)))
    return 0;
```

— so an **out-of-bounds** resizable view returns its *raw* offset/length where upstream returns 0, and an
**in-bounds** one returns 0 where upstream returns the real values. `docs/95` also measured that the ordinary
IDL BufferSource converter never hands such a view to WebCore (`TypeError: Underlying ArrayBuffer has been
detached from the view or out-of-bounds` on Blob, Response, TextDecoder, `crypto.subtle.digest`, ImageData) and
left the question this run answers: **is every producer gated?**

## 1. Answer

No. There is exactly one ungated producer and it has a consumer whose output the page reads back:

```
IDBKeyRange.only(view)                                   IDBKeyRange.cpp:71-78  (synchronous, no database)
  -> scriptValueToIDBKey                                 IDBBindingUtilities.cpp:426-429
  -> createIDBKeyFromValue                               IDBBindingUtilities.cpp:249-250  (raw jsDynamicCast<JSArrayBufferView*>)
  -> IDBKey::createBinary(JSC::JSArrayBufferView&)        IDBKey.cpp:53-59
  -> JSArrayBufferView::possiblySharedImpl()             JSArrayBufferView.cpp:336-350
  -> GenericTypedArrayView::wrappedAs()                   GenericTypedArrayViewInlines.h:107-118  (sub-range check SKIPPED for resizable)
  -> ThreadSafeDataBuffer::copyData(data(), byteLength()) ThreadSafeDataBuffer.h:70-73 -> memcpy :52
  -> IDBKey(Binary) -> range.lower -> ArrayBuffer         IDBBindingUtilities.cpp:161-172
```

`IDBKey::createBinary` in full (`IDBKey.cpp:53`):

```cpp
Ref<IDBKey> IDBKey::createBinary(JSC::JSArrayBufferView& arrayBufferView)
{
    auto bufferView = arrayBufferView.possiblySharedImpl();
    if (!bufferView)
        return createInvalid();
    return adoptRef(*new IDBKey(ThreadSafeDataBuffer::copyData(bufferView->data(), bufferView->byteLength())));
}
```

`ThreadSafeDataBufferImpl` then does a plain `memcpy(m_data.data(), data, length)` (`ThreadSafeDataBuffer.h:49-53`),
and the binary key comes back to JS as an `ArrayBuffer` (`IDBBindingUtilities.cpp:161-172`,
`ArrayBuffer::create(data->data(), data->size())`). So the *length* is `byteLength()` of a view built by
`wrappedAs`, and for an out-of-bounds resizable view that is `byteLengthRaw()`.

## 2. The producer table (audited, not guessed)

Tool `tools/oobview-audit.py` (md5 `af85572c5455529b1596b94503cd80f2`), JSON `data/oobview/audit.json`
(md5 `ae5ba05fd4555785ad7236d5a31de00e`). **12/12 checks pass.** Every check asserts a fact about the drop's text,
so a FAIL means the table below must be re-read.

| producer | sites | gate | verdict |
|---|---|---|---|
| `WrapperType::toWrapped` / `toWrappedAllowShared` (`BufferSourceConverter`, `JSDOMConvertUnion.h:241`) | all IDL BufferSource conversions | `JSGenericTypedArrayViewInlines.h:928-940` returns nullptr for `isResizableOrGrowableShared()` | **gated** (this is `docs/95`'s measurement) |
| `toPossiblySharedArrayBufferView` / `toUnsharedArrayBufferView` (`JSDOMConvertBufferSource.h:101-113`) | 1 caller: `SerializedScriptValue.cpp:1382` | call site tests `isOutOfBounds()` (`:1377`) and returns `DataCloneError` | **gated** |
| `JSArrayBufferView::possiblySharedImpl()` | 2 callers: `JSDOMConvertBufferSource.h:106` (the row above) and `IDBKey.cpp:55` | none in `createBinary` | **UNGATED — this run** |
| `XxxArray::wrappedAs` / `DataView::wrappedAs` | 16 call sites: `SerializedScriptValue.cpp` ×12 (deserializer), `StructuredClone.cpp` ×2, `JSArrayBufferView.cpp` ×2 | deserializer runs on a buffer that arrived from the same engine; `StructuredClone` clones the buffer at its *current* `byteLength()` first | read-only / self |
| raw `jsCast<JSArrayBufferView*>` in WebCore | 3: `IDBBindingUtilities.cpp:249`, `SerializedScriptValue.cpp:1377`, `StructuredClone.cpp:107` | first is the ungated one; second is gated; third writes the *clone* | 1 ungated |

`wrappedAs` is the hole in the type system, and it says so (`GenericTypedArrayViewInlines.h:111-112`):

```cpp
    // We do not check verifySubRangeLength for resizable buffer case since this function is only called from already created JS TypedArrays.
    // It is possible that verifySubRangeLength fails when underlying ArrayBuffer is resized, but it is OK since it will be just recognized as OOB TypedArray.
```

The comment's "just recognized as OOB" is exactly what `byteLength()` no longer does in this drop.

## 3. Measurements

Oracle: `teo@<lab-ip>`, `run_nq.sh` (quarantine off), pages served from `/tmp/wkp` on a fresh port,
beacons scored from the http server log. Runner `research/fuzz-cssom/c15run.sh`
(md5 `674894963c693475c0d76811ac18c3c6`). Every run below: `EXIT=124` (the harness's normal end),
`access: none` unless quoted.

### 3.1 The canonical read page — seven arms, one process

```
$ bash /tmp/wkp/c15run.sh read 9130 25 "arm=read"
caps15 arm=read only=- resize=function idbkr=function onlyfn=function sc=function idb=object
N1 jsBL=8192 jsLen=8192 off=0 bufBL=8192
N1 ok type=ArrayBuffer bl=8192
N1 head=5a5b58595e5f5c5d at4128=7a7b78797e7f7c7d tail=a2a3a0a1a6a7a4a5
N2 jsBL=4096 jsLen=4096 off=4096 bufBL=8192
N2 ok type=ArrayBuffer bl=4096
N2 head=3031323334353637 at4128= tail=c8c9cacbcccdcecf
R0 jsBL=8192 jsLen=8192 off=0 bufBL=8192
R0 ok type=ArrayBuffer bl=0
R1 jsBL=0 jsLen=0 off=0 bufBL=4112
R1 ok type=ArrayBuffer bl=8192
R1 head=5a5b58595e5f5c5d at4128=7a7b78797e7f7c7d tail=a2a3a0a1a6a7a4a5
D1 ctor=ok
D1 getter=TypeError:Underlying ArrayBuffer has been detached from the
D1 ok type=ArrayBuffer bl=8192
D1 head=1110131215141716 at4128=3130333235343736 tail=e9e8ebeaedecefee
S1 pre jsBL=0 bufBL=4112
S1 err=DataCloneError:The object can not be cloned.
B1 err=TypeError:Underlying ArrayBuffer has been detached from the
done arm=read
```

The page fills every buffer with `i ^ seed` before the shrink, so the key's bytes are a checksum of *where* the
copy came from. Reading them:

| arm | what it does | `view.byteLength` | key (`range.lower`) | verdict |
|---|---|---|---|---|
| `N1` | plain `ArrayBuffer(8192)`, view `0..8192` | 8192 | `ArrayBuffer` 8192, `head=5a5b…` | ordinary reference |
| `N2` | plain, view at offset 4096 | 4096 | 4096, `head=3031…` (offset-correct) | ordinary sub-range |
| `R0` | **resizable** 8192, view in bounds | 8192 | **0** | the inverted test's in-bounds branch: a valid view yields an empty key |
| `R1` | resizable 8192, `ab.resize(4112)`, view `0..8192` | **0** | **8192**, `head=5a5b… at4128=7a7b… tail=a2a3…` | **the target: a 8192-byte copy out of a 4112-byte buffer, returned to JS** |
| `D1` | the same through `new DataView(ab,0,8192)` | getter **throws** | 8192, `head=1110…` | same path, DataView spelling |
| `S1` | `structuredClone(view)` on the same OOB view | 0 | — | `DataCloneError` (control: refuses) |
| `B1` | `new Blob([view])` on the same OOB view | 0 | — | `TypeError` (control: refuses) |

Two isolated re-runs with a single arm give the same numbers (`only=R0` port 9131, `only=R1` port 9132):

```
$ bash /tmp/wkp/c15run.sh r1 9132 20 "arm=read&only=R1"
R1 jsBL=0 jsLen=0 off=0 bufBL=4112
R1 ok type=ArrayBuffer bl=8192
R1 head=5a5b58595e5f5c5d at4128=7a7b78797e7f7c7d tail=a2a3a0a1a6a7a4a5
```

`at4128 = 0x7a` is `(4128 ^ 0x5a)`, i.e. the copy crossed the buffer's logical end at 4112 and kept going.
The action's own predicted beacon was `oob size=4096 jsBL=0`; the spelling that produces it is an IDB key,
not a BufferSource. **The action's "non-resizable control returns 0" has no referent** — a non-resizable
view cannot be made out of bounds at all (the typed-array constructor validates against the current
`byteLength`), so the honest controls are `N1`/`N2` (ordinary path unchanged) and `R0` (in-bounds resizable →
0). `S1`/`B1` are the sharpest controls of all: on the *same object*, `structuredClone` and `Blob` refuse while
`IDBKeyRange.only` reads.

### 3.2 The two crash spellings, and why one of them does not crash

`PageCount::pageSize` is **64 KiB**, not the OS page (`PageCount.h:111`), and `ArrayBuffer::resize` mprotects
`[roundUpToMultipleOf<64KiB>(newLength), oldSize)` to `PROT_NONE` (`ArrayBuffer.cpp:475-531`). So a shrink that
stays inside the last 64 KiB page frees nothing:

```
$ bash /tmp/wkp/c15run.sh c1 9133 25 "arm=c1"         # 8192 -> resize(4096), view 0..8192
C1 pre jsBL=0 jsLen=0 off=0 bufBL=4096
C1 post bl=8192
done arm=c1
```

Cross a 64 KiB boundary and the same code faults in the `memcpy`:

```
$ bash /tmp/wkp/c15run.sh c3 9134 30 "arm=c3"         # 131072 -> resize(4096), view 0..131072
C3 pre jsBL=0 jsLen=0 off=0 bufBL=4096
==NNN==ERROR: AddressSanitizer: SEGV on unknown address 0x7f24034fbfe0 ... in __memcpy_avx_unaligned_erms
    #0 ... __memcpy_avx_unaligned_erms
    #1 WebCore::ThreadSafeDataBufferImpl::ThreadSafeDataBufferImpl(void const*, unsigned int) ThreadSafeDataBuffer.h:52
    #2 WebCore::ThreadSafeDataBuffer::ThreadSafeDataBuffer(void const*, unsigned int)   ThreadSafeDataBuffer.h:112
    #3 WebCore::ThreadSafeDataBuffer::copyData(void const*, unsigned int)              ThreadSafeDataBuffer.h:72
    #4 WebCore::IDBKey::createBinary(JSC::JSArrayBufferView&)                          IDBKey.cpp:58
    #5 createIDBKeyFromValue                                                           IDBBindingUtilities.cpp:250
    #7 WebCore::scriptValueToIDBKey                                                     IDBBindingUtilities.cpp:428
    #8 WebCore::IDBKeyRange::only(JSC::JSGlobalObject&, JSC::JSValue)                  IDBKeyRange.cpp:75
    #9 jsIDBKeyRangeConstructorFunction_onlyBody                                       JSIDBKeyRange.cpp:260
** (MiniBrowser): WARNING: WebProcess CRASHED
```

The **auto-length** spelling is worse, because `byteLength()` underflows: with `new Uint8Array(ab, 4096)`
(auto-length) over a 8256-byte buffer shrunk to 16, `byteOffsetStart (4096) > bufferByteLength (16)` takes the
inverted branch and `roundDownToMultipleOf(1, 16 - 4096)` is `2^64 - 4080`, truncated to `unsigned` by
`copyData`:

```
$ bash /tmp/wkp/c15run.sh c2 9135 45 "arm=c2"
C2 pre jsBL=0 jsLen=0 rawLen=4160 off=0 bufBL=16
==NNN==ERROR: AddressSanitizer: stack-buffer-underflow ... in __interceptor_memcpy
READ of size 4294963216 at 0x7f4759a02810 thread T0
    #0 __interceptor_memcpy
    #1 WebCore::ThreadSafeDataBufferImpl::ThreadSafeDataBufferImpl(void const*, unsigned int) ThreadSafeDataBuffer.h:52
    #3 WebCore::ThreadSafeDataBuffer::copyData(void const*, unsigned int)              ThreadSafeDataBuffer.h:72
    #4 WebCore::IDBKey::createBinary(JSC::JSArrayBufferView&)                          IDBKey.cpp:58
Address 0x7f4759a02810 is located in stack of thread T4 (ReceiveQueue) at offset 0 in frame
```

`READ of size 4294963216` = `2^32 - 4080`, i.e. the truncated underflow, and ASAN names a region that belongs
to *another thread's stack* — the request really does leave the buffer. The same arm in an earlier run
(port 9110) was classified `heap-buffer-overflow` and named "6144 bytes before 200256-byte region"; ASAN's
region naming depends on where the source pointer lands, the **size does not**. Either way the copy is 4 GiB
and the process dies before any byte reaches JS: **DoS, not a primitive.**

### 3.3 Can the bounded read ever return foreign bytes? Structural no, one measurement

Three facts from the drop close it:

- the copy length is `byteLengthRaw()` of a view whose length is bounded by `maxByteLength` at construction
  (the typed-array constructor refuses a longer view — measured: `RC2 THREW=RangeError:Length out of range of
  buffer`, so an OOB view **must** be made by shrinking, not by over-declaring);
- the reservation is `roundUpToMultipleOf<64KiB>(maxByteLength)` and is obtained **zeroed**:
  `Gigacage::tryAllocateZeroedVirtualPages` (`Gigacage.cpp:47-59`, `:115-120`) is
  `OSAllocator::reserveAndCommit` with an ASSERT loop that every word is 0, or
  `bmalloc::api::tryLargeZeroedMemalignVirtual`;
- `ArrayBuffer::resize` only ever `mprotect`s *down*: bytes below `roundUp(newLength)` keep their content.

So a bounded read returns what the page wrote plus zeros. Measured anyway (`arm=rc`, port 9136): a 64 KiB
resizable buffer is filled with `0xA5`, dropped, 400 000 objects are allocated, then 16 fresh 64 KiB resizable
buffers are shrunk to 16 and read whole (65536 bytes each, the full reservation):

```
RC wrote=65536 a5
RC bufs=16 nzBufs=0 a5=0 firstnz=-1 firsta5=-1 fails=0
```

16/16 all-zero. The arm's limit is its witness: `arm=rc2`'s `WeakRef` never fired — `RC2 collected=false` —
so **"the freed buffer was collected and its range reused" is not witnessed**, and the zero result is
consistent with both "no reuse" and "no collection". The source reading above is what carries the conclusion;
the measurement only fails to contradict it.

## 4. What this is, and what it is not

**Is:** the first measured reachability of `docs/95` §6's inversion from JS; a JS-visible length/contents
disagreement (a view whose `byteLength` is 0 yields an 8192-byte `ArrayBuffer`); an out-of-bounds read of the
buffer's own 64 KiB reservation including the range `[byteLength, roundUp64K(byteLength))` that the page never
wrote; a page-controlled-length `memcpy` (up to `2^32 - k`) that leaves the reservation and dies.

**Is not:** a disclosure of foreign heap data in any bounded spelling; a write; stage criterion 3. The
reclaimed-slot programme (`docs/65`) and the pointer dereference (`docs/94`) are unchanged by it.

**Reachability note for the console:** every arm needs `ArrayBuffer.prototype.resize` (measured `function` here)
and `IDBKeyRange` (measured `function`); `typeof indexedDB` is `object` on this build (`docs/78`),
`Options::useResizableArrayBuffer` is still unmeasured on the console, and nothing in this run changes that.

## 5. Files

- page `research/fuzz-cssom/caps15.html` md5 `60a9556b8af283814047e3953962065c` (225 lines, arms `read`
  with `only=N1,N2,R0,R1,D1,S1`, `c1`, `c3`, `c2`, `rc`, `rc2`)
- runner `research/fuzz-cssom/c15run.sh` md5 `674894963c693475c0d76811ac18c3c6`
- audit `tools/oobview-audit.py` md5 `af85572c5455529b1596b94503cd80f2`, JSON `data/oobview/audit.json`
  md5 `ae5ba05fd4555785ad7236d5a31de00e`, 12/12 checks
- logs `data/oobview/S_c15_{read,r0,r1,c1,c3,c2,rc,rc2}.log` and the beacon logs `data/oobview/srv913[0-7].log`

## 6. Next

The read direction is now exhausted in both spellings: bounded reads stay inside a zeroed reservation, and the
unbounded one always dies. What the same inversion has not been asked is whether it can **write** —
`ArrayBufferView::setImpl`/`setRangeImpl`/`zeroRangeImpl` bound a `memmove`/`memset` with `byteLength()`
(`ArrayBufferView.h:221-262`), and the only two `wrappedAs` producers found here are read-only. The next
action is the write-direction audit and, if a candidate exists, its measurement.
