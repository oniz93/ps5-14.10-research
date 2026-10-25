#!/usr/bin/env python3
"""Watch the PS5 screen and classify what it is showing.

The point is not the OCR: it is knowing, without a human, whether the console is sitting on an error
dialog, showing an update prompt, or is back at the Guide. That is what turns "run this PoC 200
times" from an evening of babysitting into a loop.

Safety design: an update prompt is classified as a distinct state and is never dismissed by this tool.
The console is deliberately pinned to 14.10 because 14.20 adds a generation-ID check that would kill
the kernel-side work, so any automatic input on that dialog is the one thing that must not happen.

Usage:
    console_watch.py --once                      # single frame, print state, exit
    console_watch.py --image shot.png --once     # classify a still (testing)
    console_watch.py --device 0 --interval 1.0 --log watch.jsonl

Input actuation is deliberately pluggable and off by default (--input none). When a backend is wired
up, --on-recover <command> runs on transition into PS_ERROR, and --on-alarm <command> on UPDATE_PROMPT.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATES = ("UPDATE_PROMPT", "PS_ERROR", "GUIDE", "SYSTEM_UI", "UNKNOWN")

# Ordered: the first match wins, so the alarm state is checked before anything else.
RULES = [
    ("UPDATE_PROMPT", re.compile(
        r"\b(update|updating)\b.*\b(system software|software|now|console)\b"
        r"|system software update|latest version of the system software|"
        r"\bupdate now\b|\bsoftware update\b", re.I)),
    ("PS_ERROR", re.compile(
        r"cannot be displayed|can't be displayed|error has occurred|an error occurred|"
        r"\bCE-\d{5}-\d\b|\bNP-\d|failed to load|page (could not|can't) be", re.I)),
    ("GUIDE", re.compile(r"\bguide\b|\bplaystation\b|\bsearch the web\b|\bbookmarks?\b", re.I)),
    ("SYSTEM_UI", re.compile(r"\b(games|media|library|settings|store|switcher|home)\b", re.I)),
]


def capture(device: int, out_path: str, timeout: float = 15.0) -> bool:
    """Grab one frame. ffmpeg's avfoundation backend needs the device index, not a path."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "avfoundation", "-framerate", "30",
        "-i", str(device), "-frames:v", "1", out_path,
    ]
    try:
        subprocess.run(cmd, timeout=timeout, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False
    return Path(out_path).exists() and Path(out_path).stat().st_size > 0


def ocr(image_path: str, ocr_bin: str) -> list:
    try:
        r = subprocess.run([ocr_bin, image_path], capture_output=True, timeout=25, check=False)
        if r.returncode != 0:
            return []
        return json.loads(r.stdout.decode("utf-8", "replace") or "[]")
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def classify(lines: list) -> tuple:
    """Return (state, evidence). Evidence is the matched text, kept for the log so a wrong
    classification can be understood later without re-running."""
    joined = " ".join(l.get("text", "") for l in lines)
    for state, rx in RULES:
        m = rx.search(joined)
        if m:
            return state, m.group(0)[:80]
    return "UNKNOWN", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=0, help="avfoundation video device index")
    ap.add_argument("--ocr-bin", default=str(Path(__file__).with_name("ocr")),
                    help="compiled ocr helper")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--log", default="console-watch.jsonl")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--image", help="classify this file instead of capturing")
    ap.add_argument("--input", choices=["none"], default="none",
                    help="actuation backend; none keeps this read-only")
    ap.add_argument("--on-recover", default=None,
                    help="command run when entering PS_ERROR (recovery, e.g. press X)")
    ap.add_argument("--on-alarm", default=None,
                    help="command run when the update prompt appears")
    args = ap.parse_args()

    if not Path(args.ocr_bin).exists():
        sys.stderr.write(f"ocr helper missing: {args.ocr_bin}\nbuild it with: swiftc -O ocr.swift -o ocr\n")
        return 2

    log = open(args.log, "a", buffering=1)
    last_state = None
    frames = 0

    while True:
        if args.image:
            frame = args.image
        else:
            frame = str(Path(tempfile.gettempdir()) / "console-watch-frame.png")
            if not capture(args.device, frame):
                entry = {"ts": time.time(), "state": "CAPTURE_FAILED"}
                log.write(json.dumps(entry) + "\n")
                print("CAPTURE_FAILED", flush=True)
                if args.once:
                    return 3
                time.sleep(args.interval)
                continue

        lines = ocr(frame, args.ocr_bin)
        state, evidence = classify(lines)
        frames += 1

        if state != last_state or args.once:
            entry = {
                "ts": time.time(),
                "state": state,
                "evidence": evidence,
                "lines": [l.get("text", "") for l in lines][:12],
            }
            log.write(json.dumps(entry) + "\n")
            print(f"{time.strftime('%H:%M:%S')} {state:12s} {evidence}", flush=True)

            # The alarm state must never be dismissed automatically, whatever else is configured.
            if state == "UPDATE_PROMPT" and args.on_alarm:
                subprocess.run(args.on_alarm, shell=True, check=False)
            elif state == "PS_ERROR" and args.on_recover and args.input != "none":
                subprocess.run(args.on_recover, shell=True, check=False)

            last_state = state

        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
