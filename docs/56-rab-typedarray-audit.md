# Resizable ArrayBuffer audit: one fixed instance, several unfixed siblings

Second surface in the targeted reading programme. RAB is worth reading because it is enabled here while most
of the deployed-base literature assumes SharedArrayBuffer, which is absent — so this is under-tested code, not
re-tested code.

## The instance upstream fixed

`TypedArrayConstructor.js`, `from()`, array-like branch as shipped in Sony's tree:

```js
var arrayLikeLength = @toLength(arrayLike.length);   // cached once
var result = new this(arrayLikeLength);
...
for (var k = 0; k < arrayLikeLength; k++) {
    var value = arrayLike[k];                        // no re-check after the callback
    if (mapFn)
        result[k] = thisArg === @undefined ? mapFn(value, k) : mapFn.@call(thisArg, value, k);
    else
        result[k] = value;
}
```

Fix `7a9d1499` (30 Jun 2026) inserts both a source-side and a result-side break:

```js
if (@isTypedArrayView(arrayLike) && (@isDetached(arrayLike) || k >= @typedArrayLength(arrayLike))) break;
...
if (@isTypedArrayView(result) && (k >= @typedArrayLength(result) || @isDetached(result))) break;
```

**That fix is absent from Sony's drop** — the opposite of the TransformStream calibration. Absence in the
newest published tree means the fix postdates it, so 14.10 lacks it too.

Trigger shape comes from the shipped regression test (`JSTests/stress/typedarray-from-oob.js`), and one detail
matters: the test sets `source[Symbol.iterator] = null`, because a typed array normally routes `from()` down the
*iterator* branch. Shadowing the iterator is what puts `arrayLike` — still a typed array view over a resizable
buffer — into the vulnerable array-like loop.

## The siblings nobody fixed

The same file's prototype methods cache the length and call the attacker's callback with no in-loop re-check:

```js
function map(callback, thisArg) {
    var length = @typedArrayLength(this);       // cached once
    ...
    for (var i = 0; i < length; i++)
        var mappedValue = callback.@call(thisArg, this[i], i, this);   // this[i] read after the callback
}
```

Verified identical shape in `map`, `forEach`, `filter` (and by construction `reduce`, `reduceRight`, `some`,
`every`, `find*`, all of which fetch `@typedArrayLength(this)` before the loop). A callback that shrinks the
view's resizable buffer leaves the remaining iterations reading `this[i]` past the end.

`map` is the interesting one because it copies what it read into a fresh result array, so a genuine OOB read is
directly JS-observable — that is a leak primitive, not a crash.

Mechanical triage of all of `builtins/*.js`: 25 functions cache a length and invoke a callback inside a loop.
Every typed-array one carries `@isDetached`/`@typedArrayLength` **only as the initial length fetch**, not as an
in-loop re-validation. So the June fix closed `from()` and left the class open elsewhere.

## The open severity question

The bug is titled "Out-of-Bounds Read", which implies the element access uses a cached vector and length — an
IC/JIT property. On an interpreter-only build the access may reload the view's length and be bounds-checked,
in which case the same code degrades to a spec deviation (extra callback invocations, `undefined` where a value
was expected) with no memory consequence.

That distinction is the whole value of the probe, so the probes report the two things separately:

| observation | meaning |
|---|---|
| callbacks continue past the new length | the unfixed loop is being taken (source shape confirmed) |
| tail values `== fill` | access was bounds-checked → spec bug only, dead for exploitation |
| tail values `!= fill`, non-zero | out-of-bounds read, and the differing values are leaked heap bytes |

## Staged probes

* `c026b-typedarray-from-rab.js` — `from()` path, four element types, reports callback count *and* tail values.
* `c027-typedarray-map-rab.js` — `map()` and `filter()` on a resizable view, three shrink configurations; the
  result array is the leak channel.

## Blocker: hardware is offline

* console <console-ip> — no ICMP reply (powered off / asleep)
* BC-250 <build-host-ip> — SSH connection timed out (off or off-network)
* `guide_lab.py` not running, nothing listening on 443
* capture device list changed: index 0 is now `OBS Virtual Camera`, `Capture screen 0` is index 1, and the
  physical capture dongle is absent — so even the screen oracle is unavailable, and blind key presses are
  forbidden because Enter is the one key that can accept an update prompt

Both probes are staged and the manifest points at `c027`; the moment either host returns they can run. The local
ASAN build is the better first stop: same tree, same JIT-off configuration, sanitizer attached — it answers the
severity question without console round-trips.
