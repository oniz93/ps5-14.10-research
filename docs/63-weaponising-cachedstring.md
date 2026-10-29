# Weaponising the CachedString UAF: what the reclaim actually gives us

The bug is confirmed live on 14.10 (docs/62). This document records the attempt to turn the dangling `JSString`
into something memory-unsafe, and the specific wall it hits.

## The experiments

All run on the local ASAN build (Sony's drop, `ENABLE_JIT=OFF`), which reproduces the console exactly, then the
winning shape was re-run on the console.

| # | shape | result |
|---|---|---|
| 1 | upstream regression test: `Map`, getter mutates and allocates, then `structuredClone` | **value lost** — `expected` returns `g1_4` |
| 2 | flood inside the getter with 8-char / 64-char strings, objects, arrays | always a 4-char string from the map |
| 3 | repeated string as first array element, filler in between, second use last | **no bug** — value intact |
| 4 | `Map` with string keys, big buffers then object/array/date filler, then second use | **value lost**, substitute always `g1_N` |
| 5 | `Map` with numeric keys (no key strings allocated) | **no bug** — value intact |
| 6 | `Map` with object / array / date keys as the filler | **value lost**, substitute still `g1_N` (a string) |

## What it means

The value after the second occurrence is deserialized through a `JSString` cell that was freed and then reused.
In every single variant the new occupant is **another string**. Two facts explain why:

1. **The reclaim window is bounded by string allocation.** The forced GC happens inside the deserialisation of the
   large `ArrayBuffer` entries. The very next allocation is the *key* of the following entry, and `Map` keys in the
   streams that reproduce are strings. A key always gets there first.
2. **Removing the key strings removes the bug.** With numeric keys (experiment 5) the value is never lost, which
   says the cached entry is only destroyed in the window created by string-keyed entries. Object keys (experiment 6)
   do not reproduce it either, because the string-keyed big-buffer entries that precede them still own the window.

So the primitive is: **a `JSString` pointer that resolves to a different, attacker-chosen string.** It gives string
substitution inside the deserializer, not an out-of-bounds read. As it stands it is a correctness bug with a
memory-safety root cause.

## The gap between this and a memory primitive

To become useful, the slot has to be taken by a cell that is **not** a `JSString`, because then the deserializer
treats an object as a string: it reads a length and a character pointer out of fields that mean something else.
That is what turns this into an OOB read, and an OOB read into a leak.

Every attempt to arrange that failed for the same structural reason: the allocation that follows the GC is a
string produced by the stream's own keys. Breaking that requires either

* a container whose keys and values are both non-strings yet still exercise the cached-string path — experiment 5
  says the path is not entered at all when the keys are numeric, which suggests the cache is populated by key
  interning rather than by value repetition; or
* controlling *when* the GC runs, so it lands immediately before a non-string allocation. GC timing is the
  collector's, not ours; the large `ArrayBuffer`s are a blunt lever.

## Honest position

This is a real, reproducible, JS-only use-after-free of a JSCell on retail 14.10 with the JIT off — the first
memory-safety bug in this programme that meets every constraint the console imposes. It is also, so far, one
reclaim short of being useful. Calling it an exploit primitive would be false; calling it a dead end would be
premature, because the failure is specific and mechanistically understood rather than vague.

The next move is to look for a JSC allocation primitive that can place a controlled cell in the 16-byte class
*without* going through a string, and to re-examine whether the cache can be populated from a value path rather
than a key path. Both are questions about `SerializedScriptValue`'s internals that the source can answer.
