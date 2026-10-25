# 36 - Console automation: screen half

## Why this exists

Everything that finds bugs runs on the BC-250. The bottleneck is *validation on the console*: a
candidate PoC needs many repetitions, and each repetition currently costs a manual session. A WebProcess
crash leaves the console on an error dialog that needs a button press before the next attempt, so a
200-run reliability measurement is an evening of sitting there.

This is the read half: know what the console is showing, without a human.

## What is built

- `tools/fw1400/ocr.swift` - Vision OCR, compiled with `swiftc -O ocr.swift -o ocr`. No brew
  dependency and no pyobjc; macOS ships Vision. Emits one JSON object per recognised line with
  normalised bounding boxes.
- `tools/fw1400/console_watch.py` - captures a frame with ffmpeg/avfoundation, OCRs it, classifies
  the screen, and appends one JSONL record per state transition with the evidence text.

States: `UPDATE_PROMPT`, `PS_ERROR`, `GUIDE`, `SYSTEM_UI`, `UNKNOWN`.

Verified on synthetic frames: error dialog -> `PS_ERROR` ("cannot be displayed"), update dialog ->
`UPDATE_PROMPT` ("Update System Software now? Update Now"), Guide -> `GUIDE`, home -> `SYSTEM_UI`.

## The safety rule

`UPDATE_PROMPT` is a distinct state and is never auto-dismissed, regardless of configuration. The
console is pinned to 14.10 because 14.20 adds a generation-ID check that kills the kernel-side work,
so an automatic confirm on that dialog is the single worst action this tool could take. Only
`--on-alarm` fires on it, and that is for alerting, not for input.

## Open item

Live capture currently fails with `Error opening input: Input/output error`: macOS TCC denies camera
access to the shell process. Granting it is a manual step (System Settings -> Privacy & Security ->
Camera). Until then `--image` works and the classification logic is testable.

An HDMI->UVC capture card would beat a camera pointed at a TV: exact pixels, no glare or perspective,
and error codes become reliably readable.
