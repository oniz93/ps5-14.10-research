# docs/103 — the `docs/94` element's value is an engine pointer, level by level; candidates (b) and (c) close

The action (`GOAL.md`, item 1) said the leak has to come from a memory-safety bug now that every API surface is
closed, and named two remaining candidates: **(b)** the slot's `m_data8` arm — "a freed `StringImpl` hands the
element a real character pointer, and `sinkIntoImageBuffer` reads a vptr from it, so a fake object whose vtable
slot lands on a real function would make the call return and reveal where it went" — and **(c)** "any new
ungated producer of a view/OOB length". This run measured (b) at the element itself with gdb and swept (c)
tree-wide.

Result in one sentence: **the value at element+8 is an engine pointer, and the engine chases two of its own
indirections before calling — `+8` → an object → its first word → `slot(+0x20)` — so no page byte is ever in the
chain; and in the one arm where the value did point at a live `StringImpl`, the "vptr" the engine loaded was
`(m_length << 32) | m_refCount` = `0x0000000300000002`, which is structurally never a vtable.** Candidate (c)
closes with a count: **2** raw `JSC::JSArrayBufferView` occurrences in `Source/WebCore` outside `bindings/js`,
and both are `docs/96`'s already-measured `IDBKey`.

## 0. The path, from the source (unchanged by this run)

`SerializedScriptValue.cpp:4042-4048` calls `connect()` on a **disengaged** `std::optional<ImageBitmapBacking>`;
`ImageBitmapBacking::connect` (`html/ImageBitmapBacking.cpp:80-94`) reads `+8` once (`if (!m_serializedBitmap)
return;`) and hands it to `Chrome::sinkIntoImageBuffer` → `ChromeClient::sinkIntoImageBuffer`
(`page/ChromeClient.cpp:48-50`) → `SerializedImageBuffer::sinkIntoImageBuffer` (`ImageBuffer.cpp:117-119`):

```
RefPtr<ImageBuffer> SerializedImageBuffer::sinkIntoImageBuffer(std::unique_ptr<SerializedImageBuffer> buffer)
{
    return buffer->sinkIntoImageBuffer();      // one vptr load, then one virtual call
}
```

The measured stack is exactly that chain and no other (`#0 ImageBuffer.cpp:119 ← #1 ChromeClient.cpp:50 ←
#2 Chrome.cpp:554 ← #3 ImageBitmapBacking.cpp:91 ← #4 SerializedScriptValue.cpp:4034`), so the WebKit
GPU-process arm (`WebChromeClient::sinkIntoImageBuffer`'s `is<RemoteSerializedImageBufferProxy>`,
`WebProcess/WebCoreSupport/WebChromeClient.cpp:944-951`) is not on this path. `SerializedImageBuffer`
(`ImageBuffer.h:242-258`) declares `virtual ~`, `memoryCost()`, `isRemoteSerializedImageBufferProxy()` and
`sinkIntoImageBuffer()`; the load the fault lands on is `vptr + 0x20`, i.e. slot 4 — `sinkIntoImageBuffer()`,
and nothing else is called first.

## 1. Method: read the element, don't infer it

`docs/94` scored the slot from ASAN's fault address only, and `docs/94` §6 recorded that the element's own bytes
were never printed. This run adds a gdb probe that stops at `connect()` entry and dumps the 32-byte element
(`$rdi` — the WebKit ASAN build carries line tables but no variable info, so `this` is unavailable and the SysV
first argument is used), then continues and prints `si_addr` at the fault. Predictions were written first:
`data/md8/predictions.md`. Page: `research/fuzz-cssom/caps19.html` (one arm `md8`, one variable per knob).
Every run: quarantine **off**, `max_malloc_fill_size=0` (the `docs/101` §1 condition).

```
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:\
quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0:max_malloc_fill_size=0"
bash research/leak-sweep/md8gdb.sh G4 11066 "arm=md8&sk=none&delay=9000" 40
bash research/leak-sweep/md8gdb.sh G2 11062 "arm=md8&sk=title&u=1000&delay=9000" 40
bash research/leak-sweep/oarun.sh A2 11064 30 "arm=md8&sk=title&u=1000&reuse=1" caps19.html "$AO"
bash research/leak-sweep/oarun.sh A3 11065 30 "arm=md8&sk=title&u=2000&reuse=1" caps19.html "$AO"
```

## 2. What the element actually holds — two arms, byte for byte

**`A0` (`sk=none`, the `docs/94` quiet baseline).** Element and the two levels below it:

```
ELEM=0x6030000b3bf0 (rdi)
0x6030000b3bf0: 0x000000000001e78d  0x0000611000040c80     <- +0x00, +0x08 (the field docs/94 owns)
0x6030000b3c00: 0x00007f63a1675655  0x0000000000000000     <- +0x10, +0x18 (engagement byte 0)
FIELD8=0x611000040c80
0x611000040c80: 0x00006030000b5600  0x0000000000000000     <- first word is another engine pointer
0x611000040c90: 0x0000611000042080  0x000062d000006ca0
```

and the fault:

```
==1441572==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x6030000b5530 … READ of size 8
SUMMARY: AddressSanitizer: heap-buffer-overflow … ImageBuffer.cpp:119 in SerializedImageBuffer::sinkIntoImageBuffer
```

`0x6030000b5620` is exactly `(first word of the object at FIELD8) + 0x20` — `0x6030000b5600 + 0x20` — i.e. **the
vtable slot the engine reads is derived from engine memory, two indirections in**, and ASAN flags it because it
lands past the end of a 32-byte allocation. (An earlier `A0` process reported `0x6030000b5530` with the same
`FIELD8` value `0x611000040c80`, so the object at that address differs per run while the chain does not: the load
is always `*(*(+8)) + 0x20`.) This is `docs/94` §4's quiet row reproduced on today's drop, now with the element's
own bytes: the page contributed nothing.

**`A1` (`sk=title`: `document.title = <8-unit 16-bit string>`, then `document.title = ''`).** The value at `+8`
changed — so a page action *does* select which engine block lands in the slot — and it selected a `StringImpl`:

```
FIELD8=$1 = 0x6030000b5e40
0x6030000b5e40: 0x0000000300000002  0x00006030000b5e54
0x6030000b5e50: 0x00646170a87ccf04  0x00006030000b5de0
```

Read against `StringImplShape` (`WTF/wtf/text/StringImpl.h:157-171`):
`m_refCount=2`, `m_length=3`, `m_data16 = 0x6030000b5e54 = self + 0x14`, `m_hashAndFlags=0xa87ccf04`, and the
four bytes at `+0x14` are `0x00646170` = `'p','a','d',NUL` — the engine's own atom for the **`pad`** property
name, with its characters **inline in the string object**. Then:

```
SI_ADDR=$2 = 0xdfff8004        (the shadow of 0x300000022, not the pointer)
rdi = 0x300000022              rax = 0x300000002
SUMMARY: AddressSanitizer: SEGV … ImageBuffer.cpp:119
```

`0x300000002 = (m_length << 32) | m_refCount`. The engine loaded **that** as the vptr and read the function
pointer at `+0x20`; the address ASAN printed is the *shadow* of `0x300000022`, which is why it looks unrelated
to any pointer. No ASAN report precedes it — the object is **live**, so the read of its first eight bytes is a
legal access; the crash is entirely the interpretation of two 32-bit integers as a vtable address.

**`A2`/`A3` (the reuse arms) — prediction falsified, and the layout explains why.** Both were predicted to name
`0x1000`/`0x2000` if a class-16 reuse could take a freed character buffer. Both instead:

```
==…==ERROR: AddressSanitizer: SEGV on unknown address (pc …)        (no address field)
SUMMARY: AddressSanitizer: SEGV … ImageBuffer.cpp:119
```

with no sign of `0x1000` or `0x2000`. Reason: a short string's characters are **inside** the `StringImpl` block
(`m_data16 = self+0x14`, §2 above), so there is no separate class-16 character allocation for a `Uint8Array(16)`
to reuse. `docs/93`'s "the characters start at 0x14" and `docs/94` §0's correction of it are both right; what
neither recorded is that `m_data16` **points to `self+0x14`**, which is what makes the character pointer
unaimable: it is a fixed offset from a block the page never learns the address of.

## 3. Why candidate (b) cannot leak — the argument the measurement now supports

The action's hypothesis needs a *fake object at a known address* whose first eight bytes are a real
`SerializedImageBuffer` vtable. The three ways the page can write `+8` all fail at one of those two words:

| spelling | what the page controls | why the call cannot return |
|---|---|---|
| beacon (`docs/94` §4) | 8 **ASCII** bytes (the URL host) sit *at* `+8`; the engine reads a vptr at `0x2e302e002e373231` | ASCII-only, and the value is a non-address |
| `structuredClone` (`docs/94` §5, `docs/101`) | the 8 bytes of the serialize stream at `+8`, arbitrary except the **low byte must be `0x00`/`0x80`** (it is the length MSB, `docs/101` §2) | the page cannot populate the address it names |
| `m_data8` (this doc) | *nothing*: the value is an engine object pointer, and even if the page's own `StringImpl` landed there its first word is `(length<<32)|refCount` | that word is two small integers, never a vtable address |

So the "call returns and reveals where it went" step needs an address the page cannot obtain: `docs/95` measured
**no** ≥10-digit hex token on 193 records over five API surfaces and two processes, and `docs/101` §1 measured
that all five guessed candidates crash. Candidate (b) is therefore **closed as structurally impossible, not as
untested** — and it cannot even become a criterion-3 read, because the only product of the call that reaches JS
is `ImageBitmap.width/height` of an `ImageBuffer` a *real* function returned.

## 4. Candidate (c): the raw-view census, and the gate's full spelling list

```
grep -rn "JSC::JSArrayBufferView\|JSArrayBufferView&\|JSArrayBufferView\*" Source/WebCore --include=*.cpp --include=*.h \
  | grep -v "bindings/js/"            ->  2   (IDBKey.h:104, IDBKey.cpp:53 — docs/96's measured site)
grep -rn "JSC::JSArrayBuffer\b\|JSC::JSArrayBuffer&\|JSC::JSArrayBuffer\*" …  ->  2   (PDFDocument.cpp:216 creates one;
                                                                                     IDBKey.h:103/:47 takes one)
```

**Zero** other WebCore functions take a raw `JSC::JSArrayBufferView`, so no second consumer can bypass the
converter gate. An independent pass on the same question ran in parallel
(`docs/102-producer-closure-and-canvas-carrier.md` §1) and enumerated the copy sites that take
`data()`+`byteLength()` — `BlobBuilder.cpp:60`, `StructuredClone.cpp:61`, `ImageBitmap.cpp:817`,
`ShareDataReader.cpp:79`, `NetworkSendQueue.cpp:60` — every one of them behind the same gated converter or
handling an `ArrayBuffer`/`data()` pair rather than a raw view, and none leaking. The two passes agree from
opposite directions; this one adds the raw-handle count and the gate's spelling list. That parallel run also
proved the **output** half of a future leak: canvas is byte-faithful when the payload sits in a colour channel
with alpha pinned (`pxshape.html`, 256/256, `same=8/8`), which `docs/98`'s premultiplication loss did not
contradict — it was the packing, not the canvas. The gate itself is now measured in all three spellings, not just the unshared one:

- `JSArrayBufferView::toWrapped` (`JSArrayBufferViewInlines.h:94-100`) — `!view->isShared() &&
  !view->isResizableOrGrowableShared()`;
- `JSArrayBufferView::toWrappedAllowShared` (`:103-110`) — `!view->isResizableOrGrowableShared()`;
- `JSGenericTypedArrayView<Adaptor>::toWrapped` / `toWrappedAllowShared` (`JSGenericTypedArrayViewInlines.h:928-942`)
  and `JSArrayBuffer::toWrapped` / `toWrappedAllowShared` (`JSArrayBuffer.h:86-100`) — same test in all four.

That is the point `docs/97` asserted from the six producer spellings: **the resizable refusal is not a
shared-vs-unshared by-product, it is applied by every converter including the `AllowShared` ones**, so
`Converter<IDLAllowSharedAdaptor<T>>` (`JSDOMConvertBufferSource.h:455-468`) cannot be used to smuggle the
`docs/95` §6 inversion into a consumer. Candidate (c) is **closed: 0 new ungated producers**.

## 5. Leak scoring — why there is nothing to score on this surface

`docs/95`'s rule needs a JS-visible value that changes across ASLR. **No md8 arm produces one**: the only
beacon these arms emit is `cap` (the pre-beacon); the message never arrives, because the deserialization itself
faults at the vptr load. That is a stronger statement than a negative diff — the surface has **no output
channel**, so a leak from it is impossible regardless of the heap state. `docs/101` §4's "validator, not a
scanner" is the same fact from the other side.

## 6. What this changes

- `GOAL.md` item 1 (the leak) now has **no candidate left**: (a) GSUB is a 15-bit glyph-id funnel absent from the
  console (`docs/102`), (b) is closed here, (c) is closed here. The leak must come from a *different* bug class
  than "an OOB length that reaches a copy" — the two instances of that class in this drop are measured
  (`docs/96` reads its own zero pages, `docs/97` has no writer).
- Two corrections to record: `docs/94` §6's "ASAN never prints an address" is refined — it prints the **shadow**
  address (`0xdfff8004` for `0x300000022`), which is worse than no address because it looks like one; and
  `docs/94` §4's quiet row is now attributed: the `+8` value is a pointer to an object whose first word is a
  heap pointer, and the vtable-slot read lands 0x20 past it.
- Next action is `GOAL.md` item 2 (the OTF table-by-table capture), which is a `docs/101` §4 loose end with a
  defined gdb + fontTools verification, and it is independent of the leak question.
