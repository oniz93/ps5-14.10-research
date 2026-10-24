# The build flags change the whole attack surface

> Read out of the PlayStation port's own cmake in the 14.x source drop:
> `Source/cmake/OptionsPlayStation.cmake` (45 `WEBKIT_OPTION_DEFAULT_PORT_VALUE` lines)
> and `Source/cmake/WebKitFeatures.cmake`.

## The headline: no JIT

```
ENABLE_JIT       PRIVATE OFF
ENABLE_DFG_JIT   PRIVATE OFF
ENABLE_FTL_JIT   PRIVATE OFF
```

JSC on this port is **interpreter-only (LLInt)** — **confirmed on the retail console**
(`data/jit-oracle-1410.json`): cold 33.0 ms, warm 29.0 ms after ~8x10^7 warm-up
operations, ratio **1.14**, verdict **JIT-OFF**. A DFG/FTL build would have shown the
warmed run several times faster. If it holds for the retail binary,
it removes most of the modern WebKit exploit literature at a stroke: no DFG/FTL type
confusion, no JIT spray, no inline-cache-driven confusion, and every bug whose PoC needs
an optimising tier never reproduces.

It also explains the corpus result: 35 JSC crash regressions harvested from
post-Safari-17.0 fixes produced zero crashes, several of which are JIT-only repros. The
oracle (`tools/fw1400/probes/poc-jit-oracle.js`) then settled it on hardware.

## What else is compiled out

| feature | state | consequence |
|---|---|---|
| `ENABLE_GPU_PROCESS` | OFF | no GPU-process IPC surface; GPU CVEs dead |
| `ENABLE_WEBGL` | OFF | matches the JS probe (`webgl:false`) |
| `ENABLE_WEB_AUDIO` | OFF | AudioWorklet class dead |
| `ENABLE_XSLT` | OFF | kills the XSLT UAF candidate outright |
| `ENABLE_MATHML` | OFF | MathML parser bugs dead |
| `ENABLE_ASYNC_SCROLLING` | OFF | threaded scrolling UAFs (e.g. `RemoteScrollingTree`) dead |
| `ENABLE_CSS_COMPOSITING` | OFF | compositor-driven UAFs unlikely |
| `USE_ISO_MALLOC` | OFF | system/bmalloc allocator |
| `ENABLE_VARIATION_FONTS`, `USE_AVIF`, `USE_JPEGXL` | OFF | shrinks font and image-decoder surface |
| `ENABLE_NOTIFICATIONS`, `ENABLE_GEOLOCATION`, `ENABLE_CONTEXT_MENUS`, `ENABLE_USER_MESSAGE_HANDLERS` | OFF | no native-bridge surface from those APIs |

## What is compiled in and should not be, casually

```
ENABLE_REMOTE_INSPECTOR  PRIVATE ON      -> USE_INSPECTOR_SOCKET_SERVER ON
ENABLE_WEBDRIVER         PRIVATE ON      -> WEBDRIVER_KEYBOARD_INTERACTIONS ON
                                            WEBDRIVER_MOUSE_INTERACTIONS ON
ENABLE_WEB_CRYPTO        PRIVATE ON
ENABLE_TRACKING_PREVENTION PRIVATE ON
ENABLE_ACCESSIBILITY     OFF at line 214, ON at line 230 (later wins, but check scope)
```

A retail build with the **inspector socket server** and **WebDriver** compiled in is
worth probing: WebDriver with keyboard/mouse interactions would be programmable input
into the page, which is exactly what the date-input UAF needs. Almost certainly gated
behind a dev flag or an unexposed socket — but "almost certainly" is an assumption, and
this costs one probe.

## What survives the filter

Reachable from a plain page on this build:

1. **DOM / HTML / CSS parsing** — including custom elements, `EventTarget`, `getComputedStyle`.
2. **JSC core in interpreter mode** — parser, bytecode generator, GC, Yarr regex, `SerializedScriptValue`.
3. **Image decoders** — BMP, ICO, GIF, JPEG, PNG (AVIF/JXL off).
4. **XML (libxml2) without XSLT**, fetch/XHR, streams, Intl, WebCrypto.
5. **SVG** (default on, not overridden).

Dead by build config: GPU, WebGL, audio, XSLT, MathML, workers, async scrolling,
compositing paths.

## Candidate #1 — `ShadowBlur::blurShadowBuffer` heap-buffer-overflow

Upstream fix `1e8c797c` (bug 264978), one-line change:

```diff
-    blurLayerImage(layerData->bytes(), blurRect.size(), blurRect.width() * 4);
+    blurLayerImage(layerData->bytes(), layerData->size(), layerData->size().width() * 4);
```

`getPixelBuffer()` clamps what it hands back to the image bounds, but the old call kept
passing the *requested* rect. When the shadow's template size exceeds what the
ImageBuffer could allocate, the blur walks off the end of the buffer. Sony's tree still
has the old form verbatim.

**Why this is now the top candidate:** it is pure CSS. No keyboard, no user gesture, no
JIT — a `div` with absurd dimensions, a box-shadow and a filter is enough, which is
exactly what the upstream regression test does:

```css
div { box-shadow: blue 1.76px 0px 10px 24px inset;
      width: 33554432px; height: 33554432px;
      border-radius: 5px; filter: sepia(1); }
```

Probe: `tools/fw1400/probes/poc-shadowblur-oob.js` (four size variants, beacon before and
after each rendering update, so a crash names itself).

## Candidate #2 — `BaseDateAndTimeInputType::didChangeValueFromControl`

Upstream fix `869d5c55` (bug 310544, 2026-05-29): the function dispatches `input` without
protecting itself; a handler that changes `input.type` destroys the object, and the code
then calls `setupDateTimeChooserParameters()` / `showChooser()` on freed memory.

Sony's tree has the pre-fix shape verbatim:

```cpp
void BaseDateAndTimeInputType::didChangeValueFromControl()
{
    String value = sanitizeValue(m_dateTimeEditElement->value());
    InputType::setValue(value, value != element()->value(), DispatchInputAndChangeEvent, DoNotSet);
    DateTimeChooserParameters parameters;          // <-- this is now dangling
    if (!setupDateTimeChooserParameters(parameters))
        return;
    if (m_dateTimeChooser)
        m_dateTimeChooser->showChooser(parameters);
}
```

No `RefPtr` on the stack, so the fix is absent. Reachable path:
`DateTimeEditElement::fieldValueChanged()` → `didChangeValueFromControl()`, driven by
`DateTimeFieldElement::defaultEventHandler` on keydown → `setValueAsInteger(...,
DispatchInputAndChangeEvents)`.

**The catch:** the field elements live in a UA shadow root, so JS cannot dispatch at them.
Triggering needs real key events, i.e. a **USB keyboard** on the console typing into a
focused `<input type=date>` — or WebDriver, if it is live. `www/poc-date-uaf.html` sets
that up with on-screen instructions.

## Candidate #3 — `JSAttr::visitAdditionalChildren` / XHR `m_responseDocument`

Upstream `8d71b724` and `a8140803`: GC-thread visiting of `Attr::m_element` and
`XMLHttpRequest::optionalResponseXML()` races with main-thread mutation; the fixes add
locks and move the visit into `visitAdditionalChildrenInGCThread`. Sony's tree retains
the unlocked pre-fix shape. Scriptable in principle (Attr owner changes + XHR responseXML
in a tight GC loop), but a race, so expect a low-probability crash rather than a clean
repro — and with JIT off, GC scheduling differs from what the upstream tests assume.

## Method, and its limits

`tools/fw1400/wk_cve_sweep.py` enumerates upstream fix commits (GitHub commit search),
then tests each against Sony's tree two ways:

- **fix lines present** → backported;
- **pre-fix lines present** → `VULN-SHAPE`, meaning the code the fix deletes is still
  there and the bug is plausibly live.

Both matter. A fix being absent says nothing on its own: `SVGGeometryElement::getPointAtLength`
came back `DIVERGED`, and reading the code showed why — upstream introduced the caching bug
in a later refactor that Sony's frozen tree never received. Being frozen protects against
newer bugs as much as it exposes older ones. Only the pre-fix-shape test is evidence.

Status after four queries (`use-after-free`, `out-of-bounds`, `heap-buffer-overflow`,
`type confusion`), with JIT/GPU/worker/XSLT paths filtered out by build flag:

| verdict | count | meaning |
|---|---|---|
| VULN-SHAPE | 16 | pre-fix code present, fix absent → candidates |
| BACKPORTED | 6 | Sony took the fix |
| DIVERGED | 15 | code shape never existed here → not a bug here |
| NOFILE | 12 | file/feature absent from the port |
| SKIP-DEAD | 4 | feature compiled out |

Two cross-checks worth noting: `Out-of-bounds read in BMP RLE24 absolute-mode decoding`
came back DIVERGED, matching the earlier drop-diff which showed Sony already patched
`BMPImageReader.cpp`; and most `type confusion` hits are NOFILE/DIVERGED, which is what
you expect when the optimising tiers are gone.

## Next

1. Run `poc-jit-oracle.html` — establishes interpreter-only on hardware, which decides
   whether any JIT-dependent line of attack is worth pursuing at all.
2. Probe for WebDriver / inspector sockets being live (a few HTTP requests, no exploit).
3. With a USB keyboard attached, run `poc-date-uaf.html`.
4. Extend the sweep to `out-of-bounds`, `type confusion`, `integer overflow`, `race` and
   filter against the build flags above before ranking anything.
