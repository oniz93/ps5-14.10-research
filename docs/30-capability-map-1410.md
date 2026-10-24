# Capability map of the 14.10 Guide WebView

One page load, 20 beacons, and the reachability questions that were blocking the Sony-surface
audit are answered. Everything below is measured on retail hardware, not inferred from flags.

| channel | result | consequence |
|---|---|---|
| `MediaSource` / `SourceBuffer` | `function` / `function` | MSE is present |
| `isTypeSupported('video/mp4; codecs="avc1.42E01E"')` | **true** | AVC-in-MP4 is claimed decodable |
| `appendBuffer()` | **issued** | `SourceBufferPrivatePlayStation::appendInternal` really executes — the raw-pointer append is reachable |
| `sourceopen` | fires, but **later than 1.5 s** | the media pipeline initialises slowly; earlier timeouts were probe impatience, not absence |
| `requestMediaKeySystemAccess` | **undefined** | EME is not exposed at all |
| `FontFace` / `document.fonts` | `function` / `yes` | custom font loading works |
| woff2 | **accepted** | raw font bytes reach the platform font stack |
| `DOMParser` XML | `a` | XML/libxml2 parsing works |
| `getImageData` | `ok` | canvas readback works |
| out-of-bounds readback non-zero bytes | **0** | no leak through the canvas channel, confirming the `zeroFill()` reading |
| `ResizableArrayBuffer` | **yes** | growable/shrinkable buffers exist |

Also observed: `smetrics.aem.playstation.com` was queried twice and **blocked** by the lab
resolver. That is the containment working on a live attempt, and a reminder that the console
does reach for Sony endpoints as soon as a page loads.

## What this closes

**The CDM callback-ordering bug is unreachable.** `requestMediaKeySystemAccess` is undefined, so
`CDMInstanceSessionPlayStation`'s FIFO-by-position queue can never be exercised from a page. One
of the two remaining Sony-authored candidates is dead by absence of the API, not by patching.
That is a clean negative and it came from one beacon.

**The canvas leak channel is closed**, as the source reading predicted (`ImageBufferBackend::
getPixelBuffer` zero-fills when destination and source rect sizes differ). Zero non-zero bytes
out of an out-of-bounds readback is what a working zero-fill looks like.

## What this opens, in priority order

1. **MSE append.** This is now the only reachable Sony-authored path where memory ownership is
   visible in the OSS drop but the callee is proprietary. `appendInternal` does

   ```cpp
   m_playstation->append(data->data(), data->size());   // raw pointer into a Ref<SharedBuffer>
   ```

   and returns immediately, with completion reported later through
   `sourceBufferBackendAppendComplete`. If `PSSourceBufferBackend::append` retains that pointer
   instead of copying, every append is a use-after-free on attacker-chosen, attacker-sized
   contents — the prolapse shape, but in the WebProcess. Probe: `mse-append-churn.js`, which
   appends a real fragmented MP4 (generated with ffmpeg, baseline AVC, `empty_moov` +
   `moof`/`mdat`), then churns 120 appends under GC pressure, then tears the pipeline down with
   an append in flight.

2. **Fonts.** `FontFace` accepts woff2 and there is **no OpenTypeSanitizer anywhere in this
   tree**, so font bytes reach the platform font stack unsanitised. That turns Sony's system
   FreeType into the parser of record. Second probe after MSE.

3. Everything else stays closed: EME (no API), canvas readback (zero-fill), Style::Scope,
   RenderMenuList, Yarr forward refs, the 278657 pool race.
