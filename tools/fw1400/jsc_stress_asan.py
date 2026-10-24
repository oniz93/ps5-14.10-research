#!/usr/bin/env python3
"""Run JavaScriptCore's own stress corpus through the ASAN build of Sony's engine.

The point is not to see tests pass — it is to see AddressSanitizer speak. A sanitizer
report on a test that has been in the tree for years is either a build-specific
artefact worth understanding or a real memory-safety bug in the shipped code.

    python3 jsc_stress_asan.py --limit 100          # smoke
    python3 jsc_stress_asan.py --limit 4000         # overnight

Resumable: paths already present in the output JSONL are skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.expanduser("~/Documents/ps5-bootchain")
JSC = os.path.join(ROOT, "out/sony/full/WebKit-1400/WebKit-1400/WebKitBuild/Debug/bin/jsc")
DEFAULT_DIR = os.path.join(ROOT, "out/sony/full/WebKit-1400/WebKit-1400/JSTests/stress")

ASAN_MARK = re.compile(r"(AddressSanitizer|SUMMARY: |ERROR: AddressSanitizer)")
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1:print_summary=1",
           JSC_useJIT="false")


def load_done(out: str) -> set[str]:
    done: set[str] = set()
    if os.path.exists(out):
        for line in open(out, errors="replace"):
            try:
                done.add(json.loads(line)["path"])
            except Exception:  # noqa: BLE001
                pass
    return done


def run_one(path: str, timeout: int) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run([JSC, path], capture_output=True, text=True,
                           timeout=timeout, env=ENV)
        rc, err = p.returncode, (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, err = "timeout", ""
    dt = round(time.time() - t0, 2)
    asan = bool(ASAN_MARK.search(err))
    rec = {"path": path, "rc": rc, "secs": dt, "asan": asan}
    if asan:
        keep = [l for l in err.splitlines() if l.strip()][:25]
        rec["trace"] = keep
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(ROOT, "out/jsc-asan-results.jsonl"))
    a = ap.parse_args()

    if not os.path.exists(JSC):
        print(f"missing jsc: {JSC}", file=sys.stderr)
        return 1

    files = sorted(f for f in os.listdir(a.dir) if f.endswith(".js"))
    done = load_done(a.out)
    todo = [os.path.join(a.dir, f) for f in files if os.path.join(a.dir, f) not in done][: a.limit]

    print(f"{len(files)} files in {os.path.basename(a.dir)}, {len(done)} already run, "
          f"{len(todo)} queued", file=sys.stderr)

    hits, counts = [], {"ok": 0, "fail": 0, "timeout": 0, "asan": 0}
    with ThreadPoolExecutor(max_workers=a.workers) as ex, open(a.out, "a") as fh:
        futs = {ex.submit(run_one, p, a.timeout): p for p in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            if rec["asan"]:
                counts["asan"] += 1
                hits.append(rec)
                print(f"!! ASAN  {rec['path']}", file=sys.stderr)
                for line in rec.get("trace", [])[:6]:
                    print(f"     {line}", file=sys.stderr)
            elif rec["rc"] == "timeout":
                counts["timeout"] += 1
            elif rec["rc"] == 0:
                counts["ok"] += 1
            else:
                counts["fail"] += 1
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}  {counts}", file=sys.stderr)

    print(f"\ndone: {counts}\nresults -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
