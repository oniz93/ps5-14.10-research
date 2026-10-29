# The Guide WebView has a native bridge, and it does not survive an empty string

First target-specific attack surface found that is neither a closed system library nor generic WebKit. It is a
JS-to-native bridge injected by Sony's Guide app shell, outside the OSS drop.

## How it was found

Enumerating `Object.getOwnPropertyNames(window)` on 14.10 returned 754 globals. Filtering to lowercase callables
that any WebKit build would not have produced exactly one anomaly: `postMessageNative`. Its own source is a JS
shim, so it named the real entry point:

```js
function(data) { window._PS.postMessage(String(data)); }
```

`window._PS` has a single property, `postMessage`, which is `[native code]` with `length === 0`. The whole bridge
is therefore: JS string -> `_PS.postMessage` -> native handler in the Guide shell.

`postMessageNative` is `writable` and `configurable`, so it can be replaced by page script — relevant later, not a
bug on its own.

## The behaviour

`_PS.postMessage('')` **does not return**. The WebProcess stops executing at that call: the beacon sent
immediately after it never arrives, and within roughly 30 seconds the console displays the system modal
*"There is not enough free system memory"*. Four rapid `Escape` presses clear it, and the Guide returns to its
menu.

Reproduced twice, the second time from a freshly reloaded page with no prior allocations of that kind:

| run | sequence | outcome |
|---|---|---|
| `c033` | boot, pre-1-empty, `_PS.postMessage('')` | no `post`, `LOW_MEMORY` modal |
| `c035` | boot, pre, `_PS.postMessage('')`, nothing else | no `post`, `LOW_MEMORY` modal |

The second run rules out the obvious confound: `c029b` had leaked sixteen `MediaSource`/`video` pairs with live
object URLs, and this console has a history of `LOW_MEMORY` from exactly that. Reloading between runs released
that state, and the modal still appeared.

## Severity, stated honestly

This is a denial of service in Sony's own code, reachable from any page served into the Guide. It is not a memory
primitive: no corruption was observed, the WebProcess itself survives (it resumed polling after the modal was
cleared in the first run), and the modal is console-wide rather than confined to the app.

What makes it worth keeping: it proves the bridge is a **live native parse path** that reacts to input, which is
more than anything else on this target has shown. An empty string being the input that breaks it suggests the
handler computes something from the message length — a zero-length message taking a path that either loops or
allocates without bound.

## Operational lesson that cost us two cycles

The campaign page auto-reloads after a hang (`BOOT:1-from-0-aN`), and the manifest still pointed at the offending
case, so every reload re-ran `_PS.postMessage('')` and re-wedged the console. Clearing the manifest to `[]` stopped
it. **Never leave a case that can hang in the manifest** — clear it before recovering, or recovery will not hold.

## Next, one variable at a time

* `_PS.postMessage('{"type":"ping"}')` — does a well-formed message return cleanly? That separates "empty string
  is special" from "any call blocks".
* Then malformed JSON, then a non-string argument passed directly to `_PS.postMessage` (bypassing the shim's
  `String()` coercion), then depth.

Each run is single-variable, and the manifest is cleared to `[]` immediately after the case fires, so a hang cannot
loop.
