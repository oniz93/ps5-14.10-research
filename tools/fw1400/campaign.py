#!/usr/bin/env python3
"""Unattended campaign supervisor for the Guide WebView.

Why this exists
---------------
`guide_lab/www/runner.html` walks `/cases/manifest.json` and beacons `start:i` before each case and
`survived:i` / `threw:i` after it. A case that beacons `start` and never finishes took the WebProcess
down - that is the only crash oracle available without a debugger. But when that happens the runner page
itself is dead: the console is left on an error dialog and nothing advances. Every campaign so far ended
there, waiting for a human to press a button.

This closes the loop with the Pi's HID keyboard: it reads the beacon log for progress, and when progress
stalls it looks at the screen and presses the key the current state needs - dismiss the dialog, re-open
the User's Guide from the menu, and let `/resume` pick up at the first unfinished case.

Hard rule: an update prompt is never dismissed. It is an alarm state, and the supervisor stops acting
and says so. Input automation must not undo the network containment that keeps the console off 14.20.

Usage:
    campaign.py --ssh root@<pi-ip> --minutes 90
    campaign.py --ssh root@<pi-ip> --dry-run --minutes 1     # decide, do not press
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import console_watch as cw            # noqa: E402  capture() / ocr() / classify()

BEACONS = os.path.join(HERE, "guide_lab", "results", "beacons.jsonl")
INPUT = os.path.join(HERE, "ps5_input.py")


class BeaconTail:
    """Incremental reader over the beacon log.

    A fixed tail window is wrong: the log already contains a FUZZ-RUNNER-DONE from an earlier run, so
    reading "the last 64 KB" makes a fresh supervisor believe the campaign finished before it started.
    This reads only bytes appended after construction, and keeps a partial trailing line for the next
    poll, because a write can land mid-line.
    """

    def __init__(self, path):
        self.path = path
        self.total = 0
        self.last_start = -1
        self.done = False
        self._buf = ""
        self.offset = os.path.getsize(path) if os.path.exists(path) else 0

    def poll(self):
        if not os.path.exists(self.path):
            return self.total
        size = os.path.getsize(self.path)
        if size < self.offset:               # truncated or rotated: start over
            self.offset, self._buf = 0, ""
        if size > self.offset:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                self._buf += f.read().decode("utf-8", "replace")
                self.offset = f.tell()
        *complete, self._buf = self._buf.split("\n")
        for line in complete:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.total += 1
            body = rec.get("body") or ""
            if body.startswith("start:"):
                try:
                    self.last_start = max(self.last_start, int(body.split(":", 1)[1]))
                except ValueError:
                    pass
            elif body.startswith("FUZZ-RUNNER-DONE"):
                self.done = True
        return self.total


def press(ssh, key, keyfile, log):
    cmd = [sys.executable, INPUT, "--ssh", ssh, "--ssh-key", keyfile, "--timeout", "20",
           "press", key, "200"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        out = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        reply = out[-1] if out else "ERR"
    except subprocess.TimeoutExpired:
        reply = "TIMEOUT"
    log.write(json.dumps({"t": time.strftime("%H:%M:%S"), "press": key, "reply": reply}) + "\n")
    log.flush()
    return reply


def look(device):
    """One screen observation: (state, evidence)."""
    frame = "/tmp/campaign-frame.png"
    if not cw.capture(device, frame):
        return "CAPTURE_FAILED", ""
    lines = cw.ocr(frame, os.path.join(HERE, "ocr"))
    return cw.classify(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssh", required=True)
    ap.add_argument("--ssh-key", default=os.path.expanduser("~/.ssh/id_rsa"))
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--poll", type=float, default=3.0)
    ap.add_argument("--stall", type=float, default=25.0,
                    help="seconds without a new beacon before the screen is inspected")
    ap.add_argument("--dry-run", action="store_true", help="decide, never press")
    args = ap.parse_args()

    logpath = os.path.join(HERE, "guide_lab", "results", "campaign.jsonl")
    os.makedirs(os.path.dirname(logpath), exist_ok=True)
    log = open(logpath, "a", buffering=1)
    log.write(json.dumps({"t": time.strftime("%H:%M:%S"), "event": "start",
                          "minutes": args.minutes, "dry_run": args.dry_run}) + "\n")

    deadline = time.time() + args.minutes * 60
    tail = BeaconTail(BEACONS)          # only records written from now on
    tail.poll()
    last_total, last_progress = tail.total, time.time()
    seen_start = 0

    while time.time() < deadline:
        total, idx, done = tail.poll(), tail.last_start, tail.done
        if done:
            log.write(json.dumps({"t": time.strftime("%H:%M:%S"), "event": "runner_done",
                                  "cases_started": idx}) + "\n")
            print(f"runner reported DONE at case {idx}", flush=True)
            return 0
        if total != last_total:
            if idx != seen_start:
                seen_start = idx
                log.write(json.dumps({"t": time.strftime("%H:%M:%S"), "event": "case",
                                      "index": idx}) + "\n")
                print(f"case {idx}", flush=True)
            last_total, last_progress = total, time.time()
            time.sleep(args.poll)
            continue

        if time.time() - last_progress < args.stall:
            time.sleep(args.poll)
            continue

        # Stalled: work out what the screen needs.
        state, evidence = look(args.device)
        entry = {"t": time.strftime("%H:%M:%S"), "event": "stall", "state": state,
                 "evidence": evidence, "case": idx}
        log.write(json.dumps(entry) + "\n")
        print(f"stall -> {state} {evidence} (case {idx})", flush=True)

        if state == "UPDATE_PROMPT":
            # Never. This dialog is the one thing input automation must not touch.
            log.write(json.dumps({"t": time.strftime("%H:%M:%S"), "event": "ALARM",
                                  "reason": "update prompt on screen"}) + "\n")
            print("ALARM: update prompt visible - refusing to press anything", flush=True)
            return 2

        if args.dry_run:
            print(f"[dry-run] would press for state {state}", flush=True)
            last_progress = time.time()
            continue

        if state in ("PS_ERROR", "NET_ERROR"):
            # A crashed WebProcess or a blocked fetch leaves a dialog with an OK button.
            press(args.ssh, "enter", args.ssh_key, log)
        elif state == "GUIDE":
            # Back on the Guide menu: Enter opens the User's Guide, which serves the runner again
            # and /resume continues at the first unfinished case.
            press(args.ssh, "enter", args.ssh_key, log)
        else:
            # Unknown or blank: back out once, then try to re-enter.
            press(args.ssh, "escape", args.ssh_key, log)
            press(args.ssh, "enter", args.ssh_key, log)

        last_progress = time.time()
        time.sleep(args.poll)

    log.write(json.dumps({"t": time.strftime("%H:%M:%S"), "event": "timeout",
                          "cases_started": seen_start}) + "\n")
    print(f"time budget exhausted at case {seen_start}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
