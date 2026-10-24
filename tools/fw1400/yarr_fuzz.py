#!/usr/bin/env python3
"""Fuzz Yarr - JavaScriptCore's regex engine - on the interpreter-only ASAN build.

Why this target: regex compiles and runs on the LLInt path, so no JIT is needed to reach
it; a page can trigger it with a literal; and Sony's own backport list already contains a
YarrPattern fix (a {0}-quantified forward reference left dangling inside a lookbehind),
which says this code has had memory-safety bugs recently.

Strategy: generate regex sources weighted towards the constructs that historically break
parsers - lookbehind with forward back-references, nested quantifiers, named groups,
unicode property escapes, class subtraction, and the v flag - then compile and *run*
them against generated subjects. Cases are batched so process startup is amortised; a
batch that trips ASAN is bisected down to the single source.

    python3 yarr_fuzz.py --batches 200 --workers 4

Findings land in out/yarr-findings/ as .js files, plus a JSONL index.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.expanduser("~/Documents/ps5-bootchain")
JSC = os.path.join(ROOT, "out/sony/full/WebKit-1400/WebKit-1400/WebKitBuild/Debug/bin/jsc")
FINDINGS = os.path.join(ROOT, "out/yarr-findings")
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1:print_summary=1")

ATOMS = ["a", "b", "0", ".", r"\d", r"\w", r"\s", r"\p{L}", r"\P{L}", r"\u{1F600}",
         "[a-z]", "[^0-9]", r"[\w-]", r"[\p{L}&&\p{N}]", r"\b", "^", "$", r"\1", r"\2",
         r"\k<n>", "(?<n>x)", "(?:ab)", "(a|b)", "(?=a)", "(?!a)", "(?<=a)", "(?<!a)"]
QUANT = ["", "*", "+", "?", "{0}", "{1,2}", "{2,}", "{0,0}", "*?", "+?", "{1,3}?"]
FLAGS = ["", "g", "i", "m", "s", "u", "y", "gu", "iu", "sv", "v", "gv"]


def gen_regex(rng: random.Random, depth_left: int = 3) -> str:
    """Grammar-weighted generator. Depth is bounded explicitly: an earlier version
    re-rolled a fresh depth on every recursive call and blew the Python stack."""
    out = []
    for _ in range(rng.randint(1, 4)):
        style = rng.random()
        if style < 0.22:
            # lookbehind containing a forward reference: the shape Sony patched
            out.append(rng.choice([
                r"(?<=\1{0}a)", r"(?<=\1{0,0})", r"(?<=\2{0}b\1)", r"(?<!(\1){0})",
                r"(?<=\1{0}\2{0})", r"(?<=(?:\1){0})",
            ]))
        elif style < 0.62 or depth_left <= 0:
            out.append(rng.choice(ATOMS) + rng.choice(QUANT))
        elif style < 0.74:
            out.append("(" + gen_regex(rng, depth_left - 1) + ")" + rng.choice(QUANT))
        elif style < 0.86:
            out.append("(?:" + gen_regex(rng, depth_left - 1) + "|" + gen_regex(rng, depth_left - 1) + ")")
        elif style < 0.94:
            out.append(rng.choice(["(?<=", "(?<!", "(?=", "(?!"]) + gen_regex(rng, depth_left - 1) + ")")
        else:
            out.append(rng.choice([r"\p{Script=Greek}", r"[[:alpha:]]", r"[\q{ab}]",
                                   r"\u{10FFFF}", r"[\r\n]", r"(?i:abc)"]))
    return "".join(out)


def gen_subject(rng: random.Random) -> str:
    alphabet = "ab01 \n\t\u00e9\u0391\U0001F600-]"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))


def make_batch(rng: random.Random, n: int) -> list[tuple[str, str, str]]:
    cases = []
    for _ in range(n):
        src = gen_regex(rng)
        flags = rng.choice(FLAGS)
        cases.append((src, flags, gen_subject(rng)))
    return cases


def case_js(src: str, flags: str, subject: str) -> str:
    s = json.dumps(src)
    f = json.dumps(flags)
    sub = json.dumps(subject)
    return (f"try{{var r=new RegExp({s},{f});"
            f"r.exec({sub});r.test({sub});{sub}.split(r);{sub}.replace(r,'x');"
            f"r[Symbol.matchAll]&&[...{sub}.matchAll(r)];}}catch(e){{}}\n")


def run_batch(batch: list[tuple[str, str, str]], timeout: int) -> tuple[bool, str]:
    script = "".join(case_js(*c) for c in batch)
    try:
        p = subprocess.run([JSC, "-e", script], capture_output=True, text=True,
                           timeout=timeout, env=ENV)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    err = p.stderr or ""
    return ("AddressSanitizer" in err), err


def bisect(batch, timeout):
    """Find the single case that trips ASAN; returns the case or None."""
    for case in batch:
        hit, err = run_batch([case], timeout)
        if hit:
            return case, err
    return None, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=int, default=50)
    ap.add_argument("--per-batch", type=int, default=250)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "out/yarr-results.jsonl"))
    a = ap.parse_args()

    os.makedirs(FINDINGS, exist_ok=True)
    seed0 = a.seed if a.seed is not None else int(time.time())
    print(f"jsc={JSC}\nseed={seed0} batches={a.batches} per_batch={a.per_batch}", file=sys.stderr)

    rng = random.Random(seed0)
    jobs = [(i, make_batch(rng, a.per_batch)) for i in range(a.batches)]

    def work(job):
        i, batch = job
        hit, err = run_batch(batch, a.timeout)
        if not hit:
            return {"batch": i, "n": len(batch), "hit": False, "note": err[:80]}
        case, trace = bisect(batch, a.timeout)
        rec = {"batch": i, "hit": True, "case": case, "trace": trace.splitlines()[:20]}
        if case:
            name = os.path.join(FINDINGS, f"yarr-{seed0}-{i}.js")
            open(name, "w").write(case_js(*case))
            rec["file"] = name
        return rec

    counts = {"batches": 0, "hits": 0}
    with ThreadPoolExecutor(max_workers=a.workers) as ex, open(a.out, "a") as fh:
        for rec in ex.map(work, jobs):
            counts["batches"] += 1
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if rec["hit"]:
                counts["hits"] += 1
                print(f"!! ASAN batch {rec['batch']} -> {rec.get('file')}", file=sys.stderr)
                for line in rec.get("trace", [])[:5]:
                    print(f"   {line}", file=sys.stderr)
            if counts["batches"] % 20 == 0:
                print(f"  {counts}", file=sys.stderr)

    print(f"\ndone: {counts}\nresults -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
