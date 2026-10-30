# Retail divergence: the ASAN "survives and flips status" does not transfer to the console

First hardware runs of CVE-2026-43715, after the local ASAN work in `docs/65`. Both cases were staged as
`tools/fw1400/guide_lab/www/cases/` and picked up by the campaign harness on the retail 14.10 console.

## c040 — the plain upstream trigger kills the retail WebProcess

Beacons, 20:56:31:

```
c040-calling-load
c040-getter-enter
c040-v-removed
c040-getter-returning
(nothing further)
```

`load-returned` and the 2 s liveness beacon never arrive, and the console screen goes to
`LOW_MEMORY — not enough free system memory`, which is what this console shows after the WebProcess dies
(seen before with `c035`). So the stale `m_status = newStatus` after the getter's `style.remove()` is fatal on
retail: **CVE-2026-43715 is live on 14.10 hardware.** That is the first hardware confirmation of this bug in the
programme, and it matches the ASAN verdict (`WRITE of size 1` at `CSSFontFace.cpp:595`).

## c042 — the shape that survives under ASAN also dies on retail

Same trigger, but the getter allocates eight `new FontFace(..., 'local("NoSuchFontName")')` *after* the free.
Under ASAN this is the one shape that does not crash: the first post-free `CSSFontFace` takes the freed chunk and
the stale write flips its status, so face 0 reads `loaded` while 1–7 read `unloaded`.

On retail it ran twice (20:58:14 and 20:58:29) and both times the beacons stop at the same place:

```
c042-boot / face=found / calling-load / getter-enter / layout / made=8
(nothing further — no load-returned, no FACE status lines)
```

and the console is back to `LOW_MEMORY`. The status flip is therefore **not observable on hardware**: the process
dies before the statuses can be read.

## What this corrects

The occupation result in `docs/65` was measured with ASAN's allocator, whose redzones change chunk sizes and
placement. On retail the same allocation pattern does not land in the freed slot at all — so the surviving,
status-flipping reclaim is an **artefact of the instrumented build**, not a property of the console.

Consequences, in order:

1. Criterion 1 in `GOAL.md` ("a reclaim with a JS-observable effect") must be scoped to the ASAN build. On retail
   the only verified behaviour is a crash.
2. Every future "occupation" claim needs a **retail** survival test, not an ASAN one: if the page cannot reach its
   own `setTimeout`, nothing has been reclaimed on hardware.
3. The next useful console experiment is therefore a shape whose survival does not depend on ASAN placement —
   for example draining the 192-byte class before the free, or holding pre-free containers that the freed chunk can
   fall back into. Both are testable as "does the page reach ALIVE", which retail can answer.

## Console procedure that worked

Stage case + `manifest.json` in `tools/fw1400/guide_lab/www/cases/`; the campaign page hot-reloads on the next
poll (`HOTRELOAD:` beacon). After a crash the console sits in `LOW_MEMORY`; four rapid `escape` presses through the
Pi gadget return it to `GUIDE`, and `right,enter` twice re-enters the page.
