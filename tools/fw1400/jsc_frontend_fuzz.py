#!/usr/bin/env python3
"""Fuzz JavaScriptCore's parser and front end on the interpreter-only ASAN build.

Regex was one surface; this is the other half of the engine floor. Everything here is
reachable from a page, needs no JIT, and is pure C++:

  parser  - token soup through `new Function(...)`, i.e. parse-only. Deep or malformed
            nesting is where recursive-descent parsers corrupt memory or blow the stack.
  json    - JSON.parse / stringify over generated documents, including lone surrogates,
            huge depths and numeric edge cases.
  intl    - Intl formatting over hostile inputs; ICU is a large C++ surface behind a
            one-line API, and it ships in this build (libicucore).

    python3 jsc_frontend_fuzz.py --target parser --batches 100

Findings are bisected to a single case and written to out/frontend-findings/.
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
FINDINGS = os.path.join(ROOT, "out/frontend-findings")
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1:print_summary=1")

TOKENS = ["function", "=>", "(", ")", "{", "}", "[", "]", "class", "extends", "return",
          "async", "await", "yield", "const", "let", "var", "...", "?.", "??", "??=",
          "`", "${", "//", "/*", "*/", "'", '"', "\\", "\\u{", "\\u", "0x", "1e", ".",
          ",", ";", ":", "?", "break", "new", "typeof", "in", "instanceof", "delete",
          "/re/g", "++", "--", "**", "&&", "||", "!", "~", "@", "#", "%", "&", "|", "^",
          "static", "get", "set", "super", "this", "arguments", "import", "export", "with"]


def gen_tokens(rng: random.Random, n: int) -> str:
    parts = []
    for _ in range(n):
        r = rng.random()
        if r < 0.60:
            parts.append(rng.choice(TOKENS))
        elif r < 0.78:
            parts.append(rng.choice(TOKENS) * rng.randint(1, 6))
        elif r < 0.90:
            # pathological nesting, the thing recursive-descent parsers hate
            k = rng.randint(2, 40)
            opener, closer = rng.choice([("(", ")"), ("[", "]"), ("{", "}"),
                                         ("function f(){", "}")])
            parts.append(opener * k + closer * rng.choice([k, max(0, k - 1), k + 1]))
        else:
            parts.append(rng.choice(["a", "0", "1.5", "1e309", "0x10", "'x'", '"y"',
                                     "`t${1}`", "/[a-z]/", "true", "null", "undefined"]))
    return " ".join(parts)


def gen_json(rng: random.Random) -> str:
    """Node-budgeted generator. The first version rolled depth up to 200 with up to four
    children per level, which is exponential - every batch hit the timeout instead of
    fuzzing. Depth is capped at 8 and the total node count is bounded."""
    # deep chains exercise the recursive descent path directly, which is the shape that
    # exhausts the stack; the budgeted trees below cover structural variety instead
    if rng.random() < 0.12:
        k = rng.choice([64, 128, 256, 512, 1024])
        pair = rng.choice([("[", "]"), ("{", "}")])
        return pair[0] * k + pair[1] * rng.choice([k, k - 1, k + 1])

    budget = [rng.randint(30, 300)]
    literals = ['0', '-0', '1e309', '-1e-309', '"\\ud800"', '"\\u0000"', 'true', 'false',
                'null', str(rng.randint(-2**63, 2**63)),
                '"' + "x" * rng.randint(0, 40) + '"']

    def value(d: int) -> str:
        budget[0] -= 1
        if d <= 0 or budget[0] <= 0 or rng.random() < 0.28:
            return rng.choice(literals)
        if rng.random() < 0.55:
            return "[" + ",".join(value(d - 1) for _ in range(rng.randint(0, 3))) + "]"
        return "{" + ",".join(f'"k{i}":{value(d - 1)}' for i in range(rng.randint(0, 3))) + "}"

    return value(rng.randint(1, 8))


def gen_intl(rng: random.Random) -> str:
    fn = rng.choice(["Intl.NumberFormat", "Intl.DateTimeFormat", "Intl.Collator",
                     "Intl.PluralRules", "Intl.RelativeTimeFormat", "Intl.ListFormat",
                     "Intl.Segmenter", "Intl.DisplayNames"])
    arg = rng.choice(['"en"', '"en-US-u-nu-arab"', '["de","en"]', '"und"', '"en-u-ca-hebrew"'])
    opts = rng.choice(["{}", '{style:"unit",unit:"kilometer"}', '{maximumFractionDigits:999}',
                       '{dateStyle:"full",timeStyle:"full"}', '{type:"language"}',
                       '{sensitivity:"base",numeric:true}', '{granularity:"word"}'])
    subject = rng.choice(['1234567890123', '-0', 'NaN', 'Infinity', 'new Date(8.64e15)',
                          '"\\ud800"', '"a".repeat(200)', '[]'])
    return (f"try{{var o=new {fn}({arg},{opts});"
            f"o.format?o.format({subject}):(o.formatToParts?o.formatToParts({subject}):"
            f"(o.segment?[...o.segment({subject})]:o.compare({subject},{subject})));}}catch(e){{}}\n")


def case_js(target: str, src: str) -> str:
    if target == "parser":
        s = json.dumps(src)
        return f"try{{new Function({s});}}catch(e){{}}\n"
    if target == "json":
        s = json.dumps(src)
        return (f"try{{var v=JSON.parse({s});JSON.stringify(v);"
                f"try{{JSON.parse(JSON.stringify(v))}}catch(e){{}}}}catch(e){{}}\n")
    return src + "\n"


def run_batch(target: str, batch: list[str], timeout: int) -> tuple[bool, str, int]:
    script = "".join(case_js(target, s) for s in batch)
    try:
        p = subprocess.run([JSC, "-e", script], capture_output=True, text=True,
                           timeout=timeout, env=ENV)
    except subprocess.TimeoutExpired:
        return False, "timeout", 0
    err = p.stderr or ""
    crashed = p.returncode in (-11, -6, 139, 134, 138)
    return ("AddressSanitizer" in err or crashed), err, p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["parser", "json", "intl"], default="parser")
    ap.add_argument("--batches", type=int, default=50)
    ap.add_argument("--per-batch", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "out/frontend-results.jsonl"))
    a = ap.parse_args()

    os.makedirs(FINDINGS, exist_ok=True)
    seed0 = a.seed if a.seed is not None else int(time.time())
    rng = random.Random(seed0)

    def make(n: int) -> list[str]:
        if a.target == "parser":
            return [gen_tokens(rng, rng.randint(1, 120)) for _ in range(n)]
        if a.target == "json":
            return [gen_json(rng) for _ in range(n)]
        return [gen_intl(rng) for _ in range(n)]

    jobs = [(i, make(a.per_batch)) for i in range(a.batches)]
    print(f"jsc={JSC}\ntarget={a.target} seed={seed0} batches={a.batches}", file=sys.stderr)

    def work(job):
        i, batch = job
        hit, err, rc = run_batch(a.target, batch, a.timeout)
        if not hit:
            return {"batch": i, "hit": False, "rc": rc}
        for case in batch:
            h2, err2, rc2 = run_batch(a.target, [case], a.timeout)
            if h2:
                path = os.path.join(FINDINGS, f"{a.target}-{seed0}-{i}.js")
                open(path, "w").write(case_js(a.target, case))
                return {"batch": i, "hit": True, "rc": rc2, "file": path,
                        "case": case[:2000], "trace": (err2 or "").splitlines()[:20]}
        return {"batch": i, "hit": True, "note": "batch-only, no single case",
                "trace": (err or "").splitlines()[:20]}

    counts = {"batches": 0, "hits": 0}
    with ThreadPoolExecutor(max_workers=a.workers) as ex, open(a.out, "a") as fh:
        for rec in ex.map(work, jobs):
            counts["batches"] += 1
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if rec["hit"]:
                counts["hits"] += 1
                print(f"!! {a.target} batch {rec['batch']} rc={rec.get('rc')} -> {rec.get('file')}",
                      file=sys.stderr)
                for line in rec.get("trace", [])[:5]:
                    print(f"   {line}", file=sys.stderr)
            if counts["batches"] % 20 == 0:
                print(f"  {counts}", file=sys.stderr)

    print(f"\ndone: {counts}\nresults -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
