# MSE append churn: the backend copies

146 beacons, no gap, `MSE-DONE`. The raw-pointer hypothesis is dead.

## What ran

A real fragmented MP4 (ffmpeg, baseline AVC, `empty_moov` + `moof`/`mdat`, 6053 bytes) was
appended to a `SourceBuffer` obtained from a genuine `sourceopen` on retail 14.10:

- `MSE-SOURCEOPEN` -> `MSE-SB-ADDED` -> first `appendBuffer` -> `MSE-UPDATEEND`
- 120 further appends under GC pressure, state stayed `open`, **every one** returned
  `updateend`, zero `error` events
- final append issued, then 30 ms later `src = ''`, `remove()`, `revokeObjectURL`, all
  references dropped, GC forced twice
- `MSE-PHASE3-TORN-DOWN` -> `MSE-SURVIVED` -> `MSE-DONE`

## What it means

`SourceBufferPrivatePlayStation::appendInternal` does

```cpp
m_playstation->append(data->data(), data->size());
```

and returns immediately, with completion arriving later through
`sourceBufferBackendAppendComplete`. Reading that alone suggests a retained raw pointer into a
`Ref<SharedBuffer>` that dies at scope exit. The console says otherwise: an append issued
30 ms before the entire pipeline was destroyed still completed, and 120 appends churned with
the buffer freed underneath them produced no error and no crash.

`PSSourceBufferBackend::append` therefore copies synchronously. The "raw pointer" reading was
a false alarm about the API contract — the kind that only the hardware can settle, because that
class lives in Sony's proprietary SDK and appears nowhere in the OSS drop. Recorded as closed:
do not reopen this without new evidence.

## Incidental result: the codec matrix claims more than baseline AVC

`MediaSource.isTypeSupported` reported **yes** for `avc1.64001F` (AVC High), `hvc1.1.6.L93.B0`
(**HEVC**) and `video/webm; codecs="vp9"`. That means Sony's stack will parse container and
bitstream data well beyond the profile this probe appended, and — more importantly — the
backend *parses every byte a page hands it*. That is a reachable proprietary parser, so
malformed MP4 box structure is an open target. It is unattractive to fuzz blind (no coverage
feedback, a crash costs a console restart) but it is not closed the way the pointer question is.

## Also closed here

The `performTaskAtMediaTime` callback queue is a **per-instance** member, not a static, so
there is no cross-player callback mix-up of the kind the CDM code has. Its async path binds
`weakThis` and bails if expired, so the teardown race is guarded too.
