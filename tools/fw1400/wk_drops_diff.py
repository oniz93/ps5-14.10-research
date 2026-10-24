#!/usr/bin/env python3
"""Diff two Sony OSS source drops, member by member, without downloading either.

The drops are snapshots with no history, so the only way to see what Sony changed
between two firmware ranges is to compare the archives. Their central directories
carry a CRC32 per member, so the *inventory* of changed files costs two range reads;
only the changed text files are then fetched in full.

    python3 wk_drops_diff.py \
        --base-manifest data/manifest-webkit-1200.json --base-url <WebKit-1200.zip> \
        --head-manifest data/manifest-webkit-1400.json --head-url <WebKit_1400.zip> \
        --out out/diffs --summary out/diffs/summary.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote_zip import RemoteZip  # noqa: E402

TEXT_EXT = (".cpp", ".h", ".mm", ".c", ".hpp", ".m", ".js", ".css", ".cmake", ".txt", ".py", ".json")
TOP = re.compile(r"^WebKit[-_](?:\d+|900)(?:/WebKit[-_]\d+)?")


def norm(name: str) -> str:
    return TOP.sub("", name).lstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-manifest", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--head-manifest", required=True)
    ap.add_argument("--head-url", required=True)
    ap.add_argument("--out", default="out/diffs")
    ap.add_argument("--summary", default="out/diffs/summary.json")
    ap.add_argument("--filter", default="Source/", help="only paths containing this")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    base = {norm(k): v for k, v in json.load(open(a.base_manifest)).items()}
    head = {norm(k): v for k, v in json.load(open(a.head_manifest)).items()}

    # map normalised path -> original member name, per archive
    base_name = {norm(k): k for k in json.load(open(a.base_manifest))}
    head_name = {norm(k): k for k in json.load(open(a.head_manifest))}

    common = set(base) & set(head)
    changed = sorted(n for n in common if base[n][0] != head[n][0] and a.filter in n)
    text = [n for n in changed if n.endswith(TEXT_EXT)]
    print(f"{len(changed)} changed members under {a.filter!r}; {len(text)} text files", file=sys.stderr)

    os.makedirs(a.out, exist_ok=True)
    zb = RemoteZip(a.base_url)
    zh = RemoteZip(a.head_url)

    cache = os.path.join(a.out, ".cache")
    os.makedirs(cache, exist_ok=True)

    def fetch(z, name: str, url: str) -> bytes:
        key = hashlib.sha1(f"{url}|{name}".encode()).hexdigest()
        fp = os.path.join(cache, key)
        if os.path.exists(fp):
            return open(fp, "rb").read()
        data = z.read(name)
        open(fp, "wb").write(data)
        return data

    def work(path: str):
        try:
            old = fetch(zb, base_name[path], a.base_url)
            new = fetch(zh, head_name[path], a.head_url)
        except Exception as exc:  # noqa: BLE001
            return path, None, str(exc)
        assert old is not None and new is not None
        o = old.decode("utf-8", "replace").splitlines(keepends=True)
        n = new.decode("utf-8", "replace").splitlines(keepends=True)
        d = list(difflib.unified_diff(o, n, fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
        return path, "".join(d), None

    summary = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(work, p): p for p in text}
        for fut in as_completed(futs):
            path, diff, err = fut.result()
            if err:
                print(f"  ! {path}: {err}", file=sys.stderr)
                summary.append({"path": path, "error": err})
                continue
            plus = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
            minus = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
            flat = path.replace("/", "__") + ".diff"
            if diff:
                open(os.path.join(a.out, flat), "w").write(diff)
            summary.append({"path": path, "added": plus, "removed": minus, "diff_file": flat if diff else None})

    summary.sort(key=lambda r: -(r.get("added", 0) + r.get("removed", 0)))
    json.dump(summary, open(a.summary, "w"), indent=1)

    print(f"\n{'net':>6}  {'+':>5} {'-':>5}  file")
    for r in summary[:25]:
        if "error" in r:
            print(f"{'ERR':>6}  {'':>5} {'':>5}  {r['path']}")
            continue
        print(f"{r['added'] - r['removed']:>6}  {r['added']:>5} {r['removed']:>5}  {r['path']}")
    total_a = sum(r.get("added", 0) for r in summary)
    total_r = sum(r.get("removed", 0) for r in summary)
    print(f"\n{len(summary)} files, +{total_a} / -{total_r} lines -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
