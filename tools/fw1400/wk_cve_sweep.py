#!/usr/bin/env python3
"""Which upstream WebKit security fixes did Sony NOT take?

Enumerates upstream fix commits (GitHub commit search), then tests each one against
the WebKit source Sony publishes for 14.x: fetch the file from the archive, look for
the lines the fix adds. Lines present => backported. Lines absent => candidate live
bug on the console.

    python3 wk_cve_sweep.py --query use-after-free --limit 40
    python3 wk_cve_sweep.py --query "out-of-bounds" --limit 40 --json out.json

Filtering is by surface on purpose: the console's WebView has no wasm, WebGL/GPU,
workers, SharedArrayBuffer, IndexedDB or AudioWorklet, so fixes in those paths are
skipped in the first pass rather than ranked.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote_zip import RemoteZip  # noqa: E402

SONY_ZIP = "https://www.playstation.com/content/dam/global_pdc/en-us/external-resources/oss/PS5/webkit/WebKit_1400.zip"
SONY_ROOT = "WebKit-1400/WebKit-1400/"
CACHE = os.path.join("out", "sony-cache")
PATCH_CACHE = os.path.join("out", "patch-cache")

# surface the console cannot reach (measured on 14.10)
DEAD = re.compile(r"(Worker|ServiceWorker|Worklet|WebGL|WebGPU|GPUProcess|IndexedDB|IDB|Wasm|WebAssembly|AudioWorklet|MediaSession|Speech|Payment|WebXR|FileSystemAccess)", re.I)
LIVE = ("Source/JavaScriptCore/", "Source/WebCore/", "Source/WebKit/", "Source/WTF/")

SEC = re.compile(r"(use.after.free|out.of.bounds|overflow|underflow|type.confusion|uninitiali[sz]ed|null.?deref|race|dangling|buffer|double.free|stale|leak|crash|assert|memory|security|sandbox)", re.I)
NOISE = re.compile(r"^(\[|REGRESSION|Unreviewed|Update |Versioning|Build fix|Fix build|Bump |Roll )", re.I)


def fetch_patch(sha: str) -> str:
    """mbox patch straight from github.com - no API quota, unlike /repos/.../commits."""
    fp = os.path.join(PATCH_CACHE, f"{sha}.patch")
    if os.path.exists(fp):
        return open(fp, encoding="utf-8", errors="replace").read()
    url = f"https://github.com/WebKit/WebKit/commit/{sha}.patch"
    out = subprocess.run(["curl", "-sL", "--max-time", "60", url], capture_output=True, text=True)
    text = out.stdout or ""
    if not text.startswith("From ") and "diff --git" not in text:
        raise RuntimeError("empty patch")
    os.makedirs(PATCH_CACHE, exist_ok=True)
    open(fp, "w", encoding="utf-8").write(text)
    return text


def split_patch(text: str) -> list[tuple[str, str]]:
    """[(path, diff)] from an mbox patch."""
    out = []
    cur = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("diff --git "):
            if cur is not None:
                out.append((cur, "\n".join(buf)))
            m = re.search(r" b/(\S+)$", line)
            cur = m.group(1) if m else ""
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out.append((cur, "\n".join(buf)))
    return out


def search(q: str, limit: int) -> list[dict]:
    url = "https://api.github.com/search/commits?q=" + urllib.parse.quote(q, safe=":>/-") + f"&per_page={min(limit, 100)}"
    tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {tok}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("items", [])


def signature_lines(patch: str, limit: int = 3, side: str = "+") -> list[str]:
    """Pick lines distinctive enough to prove a hunk is present.

    side='+' finds the fixed code, side='-' finds the pre-fix (vulnerable) code.
    The second one is what matters: a fix being absent only means Sony did not take
    it. The bug being present requires the code the fix deletes to still be there.
    """
    cands = []
    for line in patch.splitlines():
        if not line.startswith(side) or line.startswith(side * 3):
            continue
        body = line[1:].strip()
        if len(body) < 18 or body.startswith(("//", "/*", "*")):
            continue
        if body in ("{", "}", "});", "return;", "break;"):
            continue
        cands.append(body)
    cands.sort(key=len, reverse=True)
    out = []
    for c in cands:
        if all(c not in o for o in out):
            out.append(c)
        if len(out) >= limit:
            break
    return out


class SonyTree:
    def __init__(self) -> None:
        self.z = RemoteZip(SONY_ZIP)
        self.names = {e["name"] for e in self.z._cd}
        os.makedirs(CACHE, exist_ok=True)

    def get(self, path: str) -> str | None:
        member = SONY_ROOT + path
        if member not in self.names:
            return None
        fp = os.path.join(CACHE, member.replace("/", "__"))
        if os.path.exists(fp):
            return open(fp, encoding="utf-8", errors="replace").read()
        data = self.z.read(member).decode("utf-8", errors="replace")
        open(fp, "w", encoding="utf-8").write(data)
        return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="use-after-free")
    ap.add_argument("--since", default="2023-09-09")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", default="out/sweep.json")
    a = ap.parse_args()

    q = f"repo:WebKit/WebKit {a.query} committer-date:>{a.since}"
    items = search(q, a.limit)
    print(f"query: {q}\n{len(items)} commits\n")

    tree = SonyTree()
    results = []
    for it in items:
        sha = it["sha"]
        msg = it["commit"]["message"].splitlines()[0]
        if NOISE.search(msg):
            continue
        try:
            patch_text = fetch_patch(sha)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {sha[:8]} {exc}")
            continue
        verdicts = []
        for path, patch in split_patch(patch_text):
            if not patch or not path.startswith(LIVE):
                continue
            if DEAD.search(path) or DEAD.search(msg):
                verdicts.append(("SKIP-DEAD", path, ""))
                continue
            post = signature_lines(patch, side="+")
            pre = signature_lines(patch, side="-")
            if not post and not pre:
                continue
            body = tree.get(path)
            if body is None:
                verdicts.append(("NOFILE", path, ""))
                continue
            p_hit = sum(1 for x in post if x in body)
            v_hit = sum(1 for x in pre if x in body)
            if p_hit >= 1:
                state = "BACKPORTED"
            elif pre and v_hit * 2 >= len(pre):
                state = "VULN-SHAPE"
            elif p_hit == 0 and v_hit == 0:
                state = "DIVERGED"
            else:
                state = "PARTIAL"
            verdicts.append((state, path, f"fix {p_hit}/{len(post)} · pre {v_hit}/{len(pre)}"))
        if not verdicts:
            continue
        order = {"VULN-SHAPE": 0, "PARTIAL": 1, "NOFILE": 2, "DIVERGED": 3, "BACKPORTED": 4, "SKIP-DEAD": 5}
        worst = sorted(verdicts, key=lambda v: order[v[0]])[0]
        results.append({"sha": sha[:10], "date": it["commit"]["author"]["date"][:10],
                        "title": msg[:90], "worst": worst[0], "file": worst[1],
                        "sigs": worst[2], "all": verdicts})
        print(f"{worst[0]:<10} {sha[:8]} {it['commit']['author']['date'][:10]}  {msg[:64]}")
        time.sleep(0.2)

    os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
    json.dump(results, open(a.json, "w"), indent=1)
    tally = {}
    for r in results:
        tally[r["worst"]] = tally.get(r["worst"], 0) + 1
    print(f"\n{tally}\n-> {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
