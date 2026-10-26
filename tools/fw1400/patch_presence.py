#!/usr/bin/env python3
"""Does the pre-fix code actually survive in Sony's tree?

The ranked candidate list was built on soft signals ("fix 0/3 . pre 2/3") and it over-predicts badly:
of 56 candidates, most are refactors like "Fold TreeDepthLimit.h into XMLDocumentParser.cpp" with no
security content at all. This asks a sharper question of each upstream patch:

    for every line the fix DELETES, does that line still exist in the matching file of Sony's source?

A patch that removes lines which are still present is describing code that is still there. If the patch
also adds a LayoutTest, upstream handed us a reproducer as well, which is the only thing that makes a
console run cheap.

Usage:
    patch_presence.py /tmp/wkpatch/*.patch --tree out/sony/full/WebKit-1400/WebKit-1400
    patch_presence.py /tmp/wkpatch/*.patch --tree ... --json data/patch-presence.json
"""

import argparse
import glob
import json
import os
import re
import sys


def parse_patch(path):
    """Return (files, test_added, subject). files maps repo path -> list of deleted line bodies."""
    text = open(path, encoding="utf-8", errors="replace").read()
    if not text.startswith("From "):
        return {}, False, ""

    subject = ""
    m = re.search(r"^Subject: \[PATCH\]\s*(.*?)(?:\n\n|\n\*|\Z)", text, re.S | re.M)
    if m:
        subject = " ".join(m.group(1).split())

    files, cur = {}, None
    test_added = False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m2 = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            cur = m2.group(2) if m2 else None
            if cur:
                files.setdefault(cur, [])
            continue
        if line.startswith("+++ ") and "LayoutTests/" in line and ".html" in line:
            test_added = True
        if cur is None or not line.startswith("-") or line.startswith("---"):
            continue
        body = line[1:].strip()
        # Skip noise: hunk separators, bare braces and includes match everywhere and tell us nothing.
        if not body or body in ("{", "}", "};", ")", "}", "#include"):
            continue
        if len(body) < 12:
            continue
        files[cur].append(body)
    return files, test_added, subject


def normalise(s):
    return re.sub(r"\s+", " ", s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patches", nargs="+")
    ap.add_argument("--tree", required=True, help="root of the Sony WebKit source tree")
    ap.add_argument("--json", help="write full results here")
    ap.add_argument("--min-lines", type=int, default=1,
                    help="how many deleted lines must still be present")
    args = ap.parse_args()

    paths = []
    for p in args.patches:
        paths.extend(glob.glob(p))

    cache, rows = {}, []
    for patch in paths:
        files, test_added, subject = parse_patch(patch)
        sha = os.path.basename(patch).split(".")[0]
        total_removed = total_present = 0
        best_run, best_text = 0, ""
        evidence = []
        for repo_path, deleted in files.items():
            if not repo_path.startswith("Source/"):
                continue
            target = os.path.join(args.tree, repo_path)
            if target not in cache:
                try:
                    cache[target] = normalise(open(target, encoding="utf-8",
                                                    errors="replace").read())
                except OSError:
                    cache[target] = None
            blob = cache[target]
            if blob is None:
                continue
            # A single matching line means nothing: `case VideoPixelFormat::RGBX:` exists in every
            # version. What identifies an unpatched block is a CONTIGUOUS run of deleted lines still
            # present, so score the longest run found rather than the count of loose matches.
            run = []
            for d in deleted:
                total_removed += 1
                run.append(d)
                joined = normalise(" ".join(run))
                if joined in blob:
                    total_present += 1
                    if len(run) > best_run:
                        best_run, best_text = len(run), " ".join(run)[:140]
                else:
                    run = [d] if normalise(d) in blob else []
        rows.append({
            "sha": sha, "subject": subject[:95], "test": test_added,
            "removed": total_removed, "present": total_present,
            "block": best_run, "block_text": best_text,
            "crash_test": bool(re.search(r"crash|uaf|overflow|assert|security", subject, re.I)),
            "files": sum(1 for p in files if p.startswith("Source/")),
            "evidence": evidence,
        })

    rows.sort(key=lambda r: (r["block"], r["test"]), reverse=True)

    kept = [r for r in rows if r["block"] >= args.min_lines]
    print(f"{len(rows)} patches . {len(kept)} keep a contiguous pre-fix block (>= {args.min_lines} lines)\n")
    for r in kept:
        print(f"[{r['sha']}] block={r['block']} lines . test={'yes' if r['test'] else 'no'}"
              f" . crash-test={'yes' if r['crash_test'] else 'no'}")
        print(f"   {r['subject']}")
        if r["block_text"]:
            print(f"     surviving block: {r['block_text']}")
    if args.json:
        json.dump(rows, open(args.json, "w"), indent=1)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
