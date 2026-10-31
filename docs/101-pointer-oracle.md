# 101 — a pointer oracle over the `docs/94` slot, calibrated both ways

**Status:** measured 2026-10-30, quarantine **off** and `max_malloc_fill_size=0`. This is an instrument, not a
finding: it makes any candidate 8-byte value testable against the slot `docs/94` produced, and it settles what
the slot can and cannot tell us. **It does not replace an address leak** — §5 is the reason.

The slot: a transferred `ImageBitmap` closed inside the walk leaves a disengaged
`std::optional<ImageBitmapBacking>`; the element reuses the last class-32 block the walk frees, and if that block
is a `structuredClone` serialize buffer, its bytes 8..15 are the page's (`docs/94`). `readTransferredImageBitmap`
then calls `buffer->sinkIntoImageBuffer()` through that value (`SerializedScriptValue.cpp:4034` →
`ImageBuffer.cpp:119`).

## 1. The three outcomes, and how each is scored

| candidate | engine path | observable |
|---|---|---|
| a **valid** `SerializedImageBuffer` vptr | the virtual call returns, `ImageBitmap::create` runs, the message **arrives** | `rx&d=ImageBitmap:…&w=&h=` |
| **0** | `ImageBitmapBacking.cpp:83` early return, `ImageBitmap::create(nullopt)` | `rx` with a **detached** bitmap, `w=0 h=0` |
| anything else | `SEGV` at the vtable load | `ERROR: AddressSanitizer: SEGV … ImageBuffer.cpp:119`, WebProcess gone |

Both calibration arms exist:

```
# zero, fill off  -> arrival, detached
rx&d=ImageBitmap:w0h0&w=0&h=0&g=[object Object]            (port 10445, access: none)
# zero, fill ON   -> crash (the same arm)
==…==ERROR: AddressSanitizer: SEGV … ImageBuffer.cpp:119   (port 10444)
# any other value -> crash
0x4141414100 / 0x7f00000000 / 0x7f00001000                 (ports 1045x, all crash)
```

**The fill sensitivity is real and must be respected: with ASAN's malloc fill on, every value crashes** — an
allocation after the clone re-fills the block, so the fill, not the page, decides. Every arm here runs with
`max_malloc_fill_size=0`, and that is the same condition a release build is closest to.

## 2. Encoding (and the three traps in it)

`research/leak-sweep/poracle.sh <tag> <port> <ptr>` builds the clone string and drives `caps14.html`'s
`arm=clone`. The stream is `[version:4][StringTag:1][length|8BitFlag:4][chars]`, so element+8 is the length's
MSB and the pointer — little-endian — starts there. Consequences:

- **The pointer's low byte must be `0x00`** because byte 8 is the length MSB. Candidates must be 256-aligned;
  the wrapper refuses others.
- **The string must be 16-bit or the low byte shifts to `0x80`.** An all-ASCII payload serialises 8-bit
  (`length | StringDataIs8BitFlag` puts `0x80` at byte 8). A trailing `U+0100` unit past the pointer bytes
  forces 16-bit; `docs/94` used the same trick.
- **The stream must be 25 bytes** (8 units: 4 pointer units + 3 zero units + the `0100` unit) so the
  `Vector<uint8_t>` grows 16 → 25 and the freed block is class 32. Shorter payloads (5 units, 19 bytes) were
  tried and did not land.

The message shape matters too, and is copied from `docs/94`: `{ pad: 'x'.repeat(200), k: <bitmap>, g: { get z() {
close(); structuredClone(<string>); } } }` — the pad grows the message buffer past class 32 before the getter,
and the getter is the last thing the walk does.

## 3. An independent page that does *not* reach the slot (recorded so nobody re-derives it)

`research/fuzz-cssom/caps18.html` (the only copy) re-implements the same arm with a `localStorage` cursor so a sweep survives a
crash, and it **always crashes, even for `p=0`** — 4 runs, two encodings (4-unit/17-byte and 5-unit/19-byte
streams), with the property order, the nested getter and the 200-byte pad all matched. What it does *not* share
with `docs/94`'s page is the 8-unit/25-byte stream, i.e. it reproduces trap 3 in §2. It is kept as the sweep
harness skeleton; the scored page is `caps14.html`.

## 4. What the oracle is good for

Testing a pointer that came from somewhere else: a partial leak, a value captured from the console, or a guess
with a known shape. One pointer per process (a crash ends the run), so it is a validator, not a scanner.

## 5. What it cannot do — and why it is not a leak

A wrong-but-mapped address does **not** arrive: the engine loads the value at the candidate and *calls* it, so a
successful arm needs a real `SerializedImageBuffer` vtable, not readable memory. Sampling the heap therefore has
the same odds as guessing a vtable address. The five candidates tried here (`0x4141414100`, `0x7f00000000`,
`0x7f00001000` and the two zero controls) all crashed, which is the expected outcome without a leak.

Two further limits: only the three outcomes in §1 are visible (no field of the fake object is read back), and
`ImageBitmapBacking::connect` is only reached when the element is disengaged, so the arm always closes the
bitmap — the `w`/`h` fields it reports are the *detached* bitmap's, not the fake object's.

## 6. Exact commands

```
bash research/leak-sweep/poracle.sh cal_zero 10445 0            # arrival, w=0 h=0
bash research/leak-sweep/poracle.sh cal_41   10441 0x4141414100 # SEGV at ImageBuffer.cpp:119
```

Runner `oarun.sh` (kills only its own port, ships the page, decodes beacons, extracts the abort frames).
Logs `/tmp/S_oa_*.log`. Files: `poracle.sh`, `oarun.sh`, page `research/fuzz-cssom/caps14.html` (md5 recorded in
`docs/94`).
