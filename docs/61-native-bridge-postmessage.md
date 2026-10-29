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

## It is not the empty string

`c036` asked the obvious follow-up with a well-formed message:

| run | payload | outcome |
|---|---|---|
| `c033` | `''` | no `post`, `LOW_MEMORY` modal |
| `c035` | `''` (fresh page) | no `post`, `LOW_MEMORY` modal |
| `c036` | `'{"type":"ping"}'` | no `post`, `LOW_MEMORY` modal |

So **any** call into `_PS.postMessage` wedges the console, not just an empty one. That changes the interpretation:
this is not an input-parsing bug where a zero-length message hits a bad path. It is the bridge refusing to serve
a page it did not expect, and doing so by blocking rather than by returning an error.

The most likely explanation is that the native handler validates the message origin or a handshake token that the
real Guide page obtains during its own bootstrap, and an unrecognised caller sends it into a wait that never
completes. The practical consequence is the same either way: the bridge is not usable from a page we serve, and
every attempt costs a console wedge to learn that again.

**Conclusion: stop probing it.** Two payloads and three runs are enough to establish that the gate is not in the
message contents, and each further attempt buys another `LOW_MEMORY` recovery cycle with no new information.

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

## The real Guide page never calls it

The Mac's resolver points at the lab, so fetching `manuals.playstation.net` normally returns our own campaign
page. Pinning the real address (`dig @1.1.1.1` -> `23.6.245.19`, then `curl --resolve`) returns Sony's actual
shell: a 3.8 KB static page titled *User's Guide*, referencing `setTheme.js`, a SiteCatalyst `s_code.js`, Google
Tag Manager and Microsoft Clarity. Its three inline scripts are analytics bootstraps.

**No `_PS`, no `postMessage`, no `postMessageNative`.** The real content page never talks to the bridge.

That explains the wedge. `_PS` is app-shell plumbing, not part of the page contract: it exists so the native Guide
UI can exchange messages with its own WebView, and a page that calls it is asking for something it was never
designed to serve. There is also no protocol reference to imitate — the real page gives us nothing to copy.

## Why this still matters

The bridge is a dead end for exploitation, but it is the first evidence that the Guide shell exposes native code
to page script at all. Two things follow for future work:

* The origin/state gate is the interesting object, not the payload. If a page ever *does* satisfy it — for example
  by being served on the exact host and path the real Guide uses, with whatever token it fetches during bootstrap
  — the handler behind it parses attacker-controlled strings in native code. That is a better target than the
  closed media demuxer, because the input is text and the code is Sony's.
* `postMessageNative` is `writable` and `configurable`, so page script can replace the shim. That is only useful
  against the page's own JS, not the native side, and is not worth pursuing.

## Cost accounting

Four probe cycles were spent on this surface: two wedges, two recoveries, one auto-reload loop. The wedge costs
about 90 seconds of console time and needs four `Escape` presses. Any further work here should assume that cost
per attempt.
