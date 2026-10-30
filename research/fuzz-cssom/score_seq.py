#!/usr/bin/env python3
"""docs/89 scorer: turn one HTTP server beacon log into the numbers a doc quotes.

    python3 research/fuzz-cssom/score_seq.py /tmp/srv10021.log [more.log ...]

Prints one JSON object per arm: the `done` beacon's fields, the executed-op total (sum of the census
`n` fields, which is what "operations" means in docs/84-88), the per-op census for the ops that ran,
and the `wx*` witnesses.  Scoring from the beacon log — never from harness state.
"""
import json
import re
import sys
import urllib.parse

PAT = re.compile(r"GET /ev\?m=([^ ]*)")


def parse(path):
    beacons = []
    with open(path, "rb") as fh:
        for line in fh:
            m = PAT.search(line.decode("utf-8", "replace"))
            if m:
                beacons.append(urllib.parse.unquote(m.group(1)))
    out = {"log": path, "beacons": len(beacons), "done": None, "boot": None, "ops": 0,
           "census": {}, "errors": {}, "wxg": 0, "wxe": 0, "moload": 0, "then": 0}
    for b in beacons:
        name, _, rest = b.partition("&")
        kv = {}
        for part in rest.split("&"):
            k, _, v = part.partition("=")
            kv[k] = v
        if name == "done":
            out["done"] = kv
        elif name == "boot":
            out["boot"] = kv
        elif name == "census":
            op = kv.get("op", "?")
            n = int(kv.get("n", "0") or 0)
            out["census"][op] = n
            out["ops"] += n
            if kv.get("e", "0") not in ("0", ""):
                out["errors"][op] = kv.get("x", "?")
        elif name == "wxg":
            out["wxg"] += 1
        elif name == "wxe":
            out["wxe"] += 1
        elif name == "moload":
            out["moload"] += 1
        elif name == "then":
            out["then"] += 1
    d = out["done"] or {}
    keep = ("rounds", "then", "gc", "ms", "ath", "ith", "frm", "wterm", "wecho", "clh", "ikh", "moh",
            "mors", "mod", "moir", "mofd", "mofrem", "mofearly", "wxh", "wxgx", "wxtx", "wxlen",
            "wxrx", "wxrxok", "wxrxl", "wxrxb", "wxrxbuf", "wxerr")
    out["summary"] = {k: d[k] for k in keep if k in d}
    out["census_nonzero"] = {k: v for k, v in sorted(out["census"].items()) if v}
    del out["census"]
    return out


for p in sys.argv[1:]:
    print(json.dumps(parse(p), sort_keys=False))
