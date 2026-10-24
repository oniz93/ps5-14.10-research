#!/usr/bin/env python3
"""Turn a wk_cve_sweep result file into a ranked, de-noised candidate list.

The sweep's own verdicts are deliberately permissive: VULN-SHAPE only means "the lines
the upstream fix deletes are still present", which is equally true of a refactor. The
first smoke run scored three std::span conversions as VULN-SHAPE, so triage is not
optional - a list that mixes refactors with real memory-safety fixes is worse than no
list, because it burns console time on nothing.

Ranking:
  +3  title names a memory-safety defect (UAF, overflow, OOB, dangling, type confusion...)
  +2  the touched file is in a surface the console actually reaches
  -3  title is a refactor/build/rename/versioning change
  -2  file is in a surface measured dead on 14.10 (workers, GPU, WebGL, IDB, wasm)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

MEM = re.compile(r"(use.after.free|UAF|out.of.bounds|OOB|overflow|underflow|type confusion|"
                 r"dangling|null.?deref|uninitiali[sz]ed|double.free|heap.buffer|stack.buffer|"
                 r"buffer overflow|race|stale|crash|memory corruption|SIGSEGV|wild)", re.I)
REFACTOR = re.compile(r"(Adopt |Modernize|Rename|Move |Remove |Replace |Use |Reduce use of|"
                      r"unsafe-buffer|Werror|build fix|Fix build|Versioning|Unreviewed|Bump |"
                      r"Refactor|Clean up|CLEANUP|rebaseline|Update tests|Add a test|"
                      r"Improve |Simplify|Tidy|Convert |Port )", re.I)
DEAD = re.compile(r"(Worker|ServiceWorker|Worklet|WebGL|WebGPU|GPUProcess|IndexedDB|IDB|"
                  r"WebAssembly|Wasm|MediaSession|Speech|Payment|WebXR|FileSystem)", re.I)
LIVE = re.compile(r"^Source/(WebCore|WebKit|WTF|JavaScriptCore)/")


def score(rec: dict) -> tuple[int, str]:
    title = rec.get("title", "")
    path = rec.get("file", "")
    why = []
    s = 0
    if MEM.search(title):
        s += 3
        why.append("memory-safety title")
    if REFACTOR.search(title):
        s -= 3
        why.append("refactor/build")
    if LIVE.search(path):
        s += 2
        why.append("live surface")
    if DEAD.search(path) or DEAD.search(title):
        s -= 2
        why.append("dead on 14.10")
    if rec.get("worst") == "VULN-SHAPE":
        s += 2
        why.append("pre-fix lines present")
    if rec.get("worst") == "BACKPORTED":
        s -= 4
        why.append("Sony took the fix")
    return s, ", ".join(why) or "unclassified"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="data/sweep-webcore-1410.json")
    ap.add_argument("--min", type=int, default=2)
    ap.add_argument("--out", default="data/candidates-ranked.json")
    a = ap.parse_args()

    rows = json.load(open(a.json))
    for r in rows:
        r["score"], r["why"] = score(r)
    rows.sort(key=lambda r: (-r["score"], r.get("date", "")))

    keep = [r for r in rows if r["score"] >= a.min]
    print(f"{len(rows)} sweep records -> {len(keep)} candidates at score >= {a.min}\n")
    print(f"{'sc':>3} {'date':10} {'verdict':11} {'sha':11} title")
    for r in keep:
        print(f"{r['score']:3} {r.get('date',''):10} {r['worst']:11} {r['sha']:11} {r['title'][:66]}")
        print(f"      {r['file']}")
    json.dump(keep, open(a.out, "w"), indent=1)
    print(f"\n-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
