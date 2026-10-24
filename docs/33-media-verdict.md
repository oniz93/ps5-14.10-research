# Media verdict: drivable events, undrivable decoders

Three oracles were tried on this path and all three were wrong. The sequence matters more than
the conclusion, because the same mistake was made three times.

| attempt | signal | why it was wrong |
|---|---|---|
| round 1 | `updateend` | the bytes were accepted, not parsed |
| round 2/3 | `loadedmetadata` / `canplay` / `playing` | driven by the **demuxer's** track info from `moov`, which every mutation left intact |
| round 4 | `requestVideoFrameCallback` | **not present** in this WebView (`rvfc=no`), so `frames` was always 0 |
| round 4 fallback | `drawImage(video)` pixel sample | the control case `valid` produced `nonblack=0`, i.e. an all-black capture |

The control is the point. `V-OK-valid-frames=0-nonblack=0` means the *unmodified* file produced no
visible frames through this path either. Either nothing is decoding, or the capture path cannot see
the output (hardware compositing, or a media stack that reports events without producing pictures).
From inside the page those two are indistinguishable, and no fourth in-page oracle is likely to
separate them.

## What is actually established

- The demuxer parses these files. Malformed length fields (`cfg_lengthsize_3of4`, `nal_len_zero`,
  `nal_len_huge`, `nal_len_swallowing_mdat`) are **rejected** with a media error; everything else is
  accepted. That is real parser behaviour, observed.
- Across 54 media cases (32 container + 22 bitstream) the WebProcess never crashed.
- Whether any H.264 frame was decoded is **not established**, and the earlier claim that nine cases
  reached full playback is withdrawn: `playing` was never evidence of decoding.

## The useful conclusion

The media surface is not closed because it proved robust. It is closed because it cannot be
**driven** from this WebView: the only signals reachable from JavaScript are demux-level events, and
they fire whether or not a decoder runs. Fuzzing a decoder you cannot observe, with no coverage and
a console restart per crash, is not a viable path.

One incidental finding worth keeping: `requestVideoFrameCallback` is absent. Safari 17 has had it
since 15.4. Together with EME being undefined and the date/time input types being missing, this
WebView is a **stripped build**, not a full Safari. That is strategically useful in the negative
direction: each removed API is a removed attack surface, and it suggests enumerating what is absent
is a better use of time than probing what is present.
