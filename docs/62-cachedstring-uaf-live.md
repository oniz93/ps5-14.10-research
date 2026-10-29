# A live JSCell use-after-free on 14.10: structuredClone's CachedString

This is the first memory-safety bug in this programme that is confirmed on retail 14.10, reachable from plain
JavaScript, and independent of the JIT. It is a use-after-free of a `JSString` cell inside
`SerializedScriptValue`'s deserializer.

## The bug

`CloneDeserializer::CachedString` caches the `JSString` it builds for a repeated string:

```cpp
struct CachedString {
    JSValue jsString(JSGlobalObject* lexicalGlobalObject)
    {
        if (!m_jsString)
            m_jsString = JSC::jsString(lexicalGlobalObject->vm(), m_string);
        return m_jsString;
    }
private:
    String m_string;
    JSValue m_jsString;      // raw JSValue: no write barrier, no keep-alive
};
```

A raw `JSValue` in a C++ container is invisible to the collector. Anything that runs GC between the moment the
string is cached and the moment it is used again frees the cell, and `m_jsString` becomes a dangling pointer that
is handed back to script.

Upstream fixed this in `442482ad` by moving a `MarkedArgumentBuffer m_keepAliveBuffer` up into `CloneBase` and
appending every cached string to it:

```cpp
m_jsString = JSC::jsString(vm, m_string);
deserializer.m_keepAliveBuffer.appendWithCrashOnOverflow(m_jsString);
```

**The fix is absent from Sony's drop.** The drop still has the raw `JSValue m_jsString` with no append, so the bug
is live in the newest tree we can read — and the console is older than the drop.

## The trigger, and what it proves

Upstream's own regression test (`structured-clone-of-CachedString-in-map.html`) is the trigger: build a `Map`
whose second entry has a getter that deletes and rewrites entries and allocates hard enough to force GC, then
`structuredClone` the map. The getter runs during serialisation, and the deserializer's cached strings die.

On 14.10 the value comes back **wrong**, and wrong in a specific and informative way:

```
c038-boot
c038-before-clone
c038-after-clone
c038-VERDICT-value-lost got=gc1_4 kind=string/other
c038-done
```

`result.get('expected')` returned the string `gc1_4` — a *different string from the same map* — instead of
`Expected result`. That is exactly what a dangling `JSString` pointer looks like when its cell has been reused by
another string allocation: the deserializer hands script a pointer into a live, unrelated string object.

The same page run under the local ASAN build from the same source produced the same wrong value and no sanitizer
report — expected, because JSC cells come from `MarkedBlock`, which ASAN does not instrument. The bug is real and
invisible to the sanitizer; only the JS-visible value reveals it.

## Why this matters more than anything else found so far

* **No JIT involved.** It reproduces on the LLInt-only configuration the console actually runs.
* **No reclaim of freed web-process memory required.** The object is freed by JSC's own collector and the pointer
  is used by JSC's own code, so the IsoHeap wall that killed the canvas UAF does not apply.
* **The dangling pointer is a JSCell.** Unlike a freed `CanvasRenderingContext2D`, the target's size class is a
  JSC heap size class, and the reuse we already observe (another `JSString`) is attacker-influenced: the strings
  that reclaim the cell are the ones the attacker puts in the map.
* **It is a string, so the immediate consequences are a length field and a character pointer.** If the reclaimed
  cell is not a string at all, the deserializer still treats it as one — the shape that turns into an out-of-bounds
  read, hence a leak, hence an ASLR defeat.

## Next

Characterise the reuse: whether the substitute is deterministic, whether it is always a string, and what happens
when the attacker floods the same size class with a different kind of object between the free and the use. The
question that decides exploitability is whether the reconstructed string's `length` can be made to differ from the
real one, because that is what turns a wrong string into an out-of-bounds read.
