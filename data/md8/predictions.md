# Predictions — docs/103: is the `docs/94` element's `m_data8` slot page-selectable, and can candidate (b) leak?

Written **before** the run. Quarantine off, `max_malloc_fill_size=0` (the `docs/101` condition: with the ASAN
fill on, any allocation after the free re-fills the block and every arm crashes the same way).

## What the slot is, from the source (no measurement needed)

`SerializedScriptValue.cpp:4042-4048` → `m_backingStores.at(index)->connect(*executionContext(...))` on a
**disengaged** `std::optional<ImageBitmapBacking>`, then `ImageBitmap::create(WTFMove(...))`.
`ImageBitmapBacking::connect` (`html/ImageBitmapBacking.cpp:80-94`) reads exactly two things of the dead object:

```
ASSERT(!m_bitmapData);                       // compiled out (release) / reads a field (assert build)
if (!m_serializedBitmap) return;             // +8, the field docs/94 owns
... m_bitmapData = client->sinkIntoImageBuffer(WTFMove(m_serializedBitmap));
```

The document path is `ChromeClient::sinkIntoImageBuffer` (`page/ChromeClient.cpp:48`) →
`SerializedImageBuffer::sinkIntoImageBuffer` (`platform/graphics/ImageBuffer.cpp:117-119`) →

```
RefPtr<ImageBuffer> SerializedImageBuffer::sinkIntoImageBuffer(std::unique_ptr<SerializedImageBuffer> buffer)
{
    return buffer->sinkIntoImageBuffer();     // ONE virtual call through the value at +8
}
```

`ImageBuffer.h:242-258` — `SerializedImageBuffer` is `WTF_MAKE_FAST_ALLOCATED`, has a virtual dtor,
`memoryCost()` and `sinkIntoImageBuffer()`. So the value at +8 is used as (1) a truthiness test, (2) a vptr load,
(3) — if the call returns — the `unique_ptr`'s destructor, i.e. a *virtual* `delete` of that pointer.
`WebChromeClient::sinkIntoImageBuffer`'s `is<RemoteSerializedImageBufferProxy>` arm
(`Source/WebKit/…/WebChromeClient.cpp:944-951`) is the GPU-process spelling; the measured fault frame is
`ImageBuffer.cpp:119`, so the build takes the non-GPU path and there is exactly one vptr load.

**Prediction P0 (source):** no byte of the value at +8 ever reaches script. The only value `connect()` produces
for the page is `m_bitmapData`, and that is non-null only if the virtual call *returns*, which requires a real
`SerializedImageBuffer` vtable. `docs/95` measured that no page surface yields a ≥10-digit hex token (193
records, two processes), and `docs/101` measured that five candidates (`0x4141414100`, `0x7f00000000`,
`0x7f00001000`, two zeros) all crash. Therefore candidate (b) — "a fake object whose vtable slot lands on a real
function would make the call return and reveal where it went" — cannot produce a disclosure: the *reveal* is
`width`/`height` of a real `ImageBuffer`, and reaching it needs an address the page cannot obtain.

## The one thing left to measure: is the `m_data8` block even ours?

`docs/94` §4 measured that with `quiet=1` (no beacons in the getter) the slot holds a **heap pointer** — the
`m_data8`/`m_data16` of a freed `StringImpl` (`StringImpl.h:161-171`) — and the engine's load of 8 bytes at that
pointer is an ASAN `heap-buffer-overflow`. That was measured with the *engine's own* string. Whether the page can
put **its own** `StringImpl` there, and so make the 8 bytes at the character pointer page-chosen, has never been
measured. Arms (`research/fuzz-cssom/caps19.html`), one variable each:

| arm | getter does, after `b.close()` | prediction |
|---|---|---|
| `A0` `arm=md8` | nothing (beacons suppressed) | reproduces `docs/94`'s quiet shape: ASAN names a **heap** address as the 8-byte load site (`heap-buffer-overflow`/`heap-use-after-free` READ of size 8), no page bytes involved |
| `A1` `arm=md8&sk=title&u=1000` | `document.title = <8-unit 16-bit string>` then `= ''` | if the slot takes the freed `StringImpl` (or its class-32 characters) the 8-byte load moves **off** A0: either a UAF/OOB report at the character buffer, or a `SEGV` at `0x0000000000001000` |
| `A2` `arm=md8&sk=title&u=1000&reuse=1` | as A1, then a class-16 `Uint8Array(16)` whose first 8 bytes are `00 10 00 00 00 00 00 00` | if the character buffer is what the slot took, the reuse puts our word there → **`SEGV` on `0x0000000000001000`**, named by ASAN |
| `A3` `arm=md8&sk=title&u=2000&reuse=1` | identical, value `0x2000` | **`SEGV` on `0x0000000000002000`** — one variable from A2; the move proves page control of the call target |
| `A4` `arm=md8&sk=title&u=1000&pre=1` | the string is created and freed **before** the walk; getter is inert | control: the slot reverts to A0's shape, proving the *placement inside the getter* is what selects it |

**Falsifiers.** If A2 and A3 both report A0's heap-address shape, the md8 block is engine-internal and not
page-selectable → (b) is closed twice over (not ours, and not leaky). If A2 names `0x1000` but A3 does not name
`0x2000`, the reuse took the slot but the value is not the one we wrote → record that and stop.

**Scope, stated in advance.** Even the best case is a **DoS with a fully page-chosen 64-bit call target** — it
improves `docs/94`'s encoding (which forces the pointer's low byte to `0x00` because byte 8 of the stream is the
length MSB, `docs/101` §2) but it is still one virtual call into a value, not a read/write primitive. It does
**not** touch criterion 3, and it cannot leak: the call's only product that reaches JS is an `ImageBuffer`
returned by a real function, which needs a real vtable address, which no page surface provides.

**Leak scoring (docs/95's rule).** Every arm that reaches JS at all (only the ones that do not crash) is run in
**two** processes and scored with `research/leak-sweep/diff.py`: a JS-visible value that changes across ASLR and
lies inside a mapping is a disclosure; a stable one is a constant and is written as a negative.
