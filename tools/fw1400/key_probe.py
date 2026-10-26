#!/usr/bin/env python3
"""Verify that a keystroke actually reaches the console, using the webcam as the oracle.

Compares two camera frames with ffmpeg's PSNR after downscaling to 160x90. The downscale is the
important part: at full resolution two idle frames differ by ~33 dB of webcam sensor noise on a TV
screen, which swamps any real signal. After averaging, idle-vs-idle measures ~49 dB while a genuine UI
change measures ~24 dB, so the default 40 dB threshold separates "the key did something" from "nothing
happened" without a human watching the screen.

Usage:
    key_probe.py --ssh root@<pi-ip> --key down
    key_probe.py --ssh root@<pi-ip> --key enter --threshold 42
"""

import argparse
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent


def capture(device: int, path: str, timeout: float = 25.0) -> bool:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "avfoundation",
         "-framerate", "30", "-i", str(device), "-frames:v", "1", path],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
    )
    p = pathlib.Path(path)
    return p.exists() and p.stat().st_size > 0


def psnr(a: str, b: str) -> float | None:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", a, "-i", b,
         "-lavfi", "[0:v]scale=160:90[x];[1:v]scale=160:90[y];[x][y]psnr", "-f", "null", "-"],
        capture_output=True, timeout=90,
    )
    for line in r.stderr.decode("utf-8", "replace").splitlines():
        if "average:" in line:
            try:
                return float(line.split("average:")[1].split()[0])
            except (IndexError, ValueError):
                return None
    return None


def press(ssh: str, key: str, keyfile: str) -> str:
    r = subprocess.run(
        [sys.executable, str(HERE / "ps5_input.py"), "--ssh", ssh, "--ssh-key", keyfile,
         "--timeout", "15", "press", key, "150"],
        capture_output=True, timeout=60,
    )
    return r.stdout.decode("utf-8", "replace").strip().splitlines()[-1] if r.stdout else "ERR"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssh", required=True, help="user@host of the Pi bridge")
    ap.add_argument("--ssh-key", default=str(pathlib.Path.home() / ".ssh" / "id_rsa"))
    ap.add_argument("--key", required=True, help="key name to press")
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=40.0,
                    help="PSNR below this means the screen changed (key had an effect)")
    ap.add_argument("--settle", type=float, default=1.5, help="seconds to wait after the press")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="keyprobe-")
    before = str(pathlib.Path(tmp) / "before.png")
    after = str(pathlib.Path(tmp) / "after.png")

    if not capture(args.device, before):
        print("CAPTURE_FAILED (camera busy or permission denied)", flush=True)
        return 3

    reply = press(args.ssh, args.key, args.ssh_key)
    time.sleep(args.settle)

    if not capture(args.device, after):
        print("CAPTURE_FAILED after press", flush=True)
        return 3

    score = psnr(before, after)
    if score is None:
        print("PSNR_FAILED", flush=True)
        return 4

    changed = score < args.threshold
    print(f"{'CHANGED' if changed else 'UNCHANGED'} psnr={score:.2f} threshold={args.threshold} "
          f"bridge={reply} frames={tmp}", flush=True)
    return 0 if changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
