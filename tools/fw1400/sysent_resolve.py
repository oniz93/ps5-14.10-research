#!/usr/bin/env python3
"""Resolve a PS5 sysent capture into real handler addresses, and diff two captures.

Why this exists
---------------
On PS5, `sysent[i].sy_call` does NOT point at the implementing handler. It points at
an 8-byte thunk:

    e9 <rel32>   cc cc cc        ; jmp rel32, then padding

The real handler is `thunk + 5 + rel32`. Reading sy_call as the handler silently gives
you a 33 KB window of thunks (verified on the 13.60 capture: every one of the 679
entries lands in 0x25dc28..0x265fa8) and makes cross-firmware comparison meaningless,
because you would be comparing thunk placement rather than code.

Usage
-----
    # resolve a capture
    python3 sysent_resolve.py resolve \
        --sysent ../../research/PS5-14.10-Research/docs/dumps_13.60/sysent_raw.bin \
        --text   ../../research/PS5-14.10-Research/docs/dumps_13.60/kernel_text.bin \
        --base   0xffffffff8a9c0000 \
        -o data/sysent_resolved.json

    # diff two resolved captures (e.g. 13.60 vs a future 14.00 dump)
    python3 sysent_resolve.py diff a.json b.json

    # self-check against the handler offsets published in the 13.60 docs
    python3 sysent_resolve.py selftest
"""

import argparse
import json
import os
import struct
import sys

STRIDE = 48                      # sysent entry size on PS5
THUNK = b"\xe9"                  # jmp rel32
PAD = b"\xcc"

# Handler RVAs documented independently in the 14.10 research repo's analysis docs.
# Resolution must reproduce these or the model of the table is wrong.
DOCUMENTED = {
    563: 0x602FE0,   # process-control family
    596: 0x34C750,   # dynlib cluster
    624: 0xABD4F0,   # VM-state scalar read
    663: 0x3B01F0,   # aio_multi_wait (Sony-added; not a FreeBSD 11 syscall)
}

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DUMPS = os.path.join(REPO, "research", "PS5-14.10-Research", "docs", "dumps_13.60")


def is_canonical(x: int) -> bool:
    return (x >> 48) == 0xFFFF


def resolve(sysent: bytes, text: bytes, base: int):
    """Return (entries, problems). Each entry carries the resolved handler RVA."""
    if len(sysent) % STRIDE:
        raise SystemExit(f"sysent size {len(sysent)} is not a multiple of {STRIDE}")
    entries, problems = [], []
    nosys_targets = set()

    for num in range(len(sysent) // STRIDE):
        narg = struct.unpack_from("<I", sysent, num * STRIDE)[0]
        call = struct.unpack_from("<Q", sysent, num * STRIDE + 8)[0]
        if not is_canonical(call):
            problems.append((num, f"sy_call {call:#x} not a canonical kernel pointer"))
            entries.append({"num": num, "narg": narg, "thunk_off": None, "handler_off": None})
            continue

        toff = call - base
        if not (0 <= toff < len(text)):
            problems.append((num, f"thunk {toff:#x} outside captured text"))
            entries.append({"num": num, "narg": narg, "thunk_off": toff, "handler_off": None})
            continue
        if text[toff:toff + 1] != THUNK:
            problems.append((num, f"thunk {toff:#x} is not a jmp rel32: "
                                  f"{text[toff:toff + 6].hex()}"))
            entries.append({"num": num, "narg": narg, "thunk_off": toff, "handler_off": None})
            continue

        rel = struct.unpack_from("<i", text, toff + 1)[0]
        handler = toff + 5 + rel
        if not (0 <= handler < len(text)):
            problems.append((num, f"handler {handler:#x} outside captured text"))
            handler = None
        entries.append({"num": num, "narg": narg, "thunk_off": toff, "handler_off": handler})

    # the shared nosys stub is whichever target the most entries resolve to
    counts: dict[int, int] = {}
    for e in entries:
        if e["handler_off"] is not None:
            h = int(e["handler_off"])
            counts[h] = counts.get(h, 0) + 1
    nosys = max(counts, key=lambda k: counts[k]) if counts else None
    for e in entries:
        e["nosys"] = (e["handler_off"] == nosys)
    return entries, problems, nosys


def cmd_resolve(a):
    sysent = open(a.sysent, "rb").read()
    text = open(a.text, "rb").read()
    entries, problems, nosys = resolve(sysent, text, a.base)
    live = [e for e in entries if not e["nosys"] and e["handler_off"] is not None]
    sony = [e for e in entries if 532 <= e["num"] <= 676]
    sony_live = [e for e in sony if not e["nosys"]]

    doc = {
        "source": {"sysent": os.path.abspath(a.sysent), "text": os.path.abspath(a.text)},
        "kernel_base": hex(a.base),
        "entry_count": len(entries),
        "nosys_handler_off": hex(nosys) if nosys else None,
        "live_handlers": len(live),
        "nosys_entries": len(entries) - len(live),
        "sony_range": {"num_first": 532, "num_last": 676,
                       "live": len(sony_live), "nosys": len(sony) - len(sony_live)},
        "distinct_handlers": len({e["handler_off"] for e in live}),
        "problems": [{"num": n, "problem": p} for n, p in problems],
        "entries": entries,
    }
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(doc, f, indent=1)
    print(json.dumps({k: v for k, v in doc.items() if k != "entries"}, indent=2))
    return doc


def cmd_diff(a):
    A = json.load(open(a.a))
    B = json.load(open(a.b))
    ea = {e["num"]: e for e in A["entries"]}
    eb = {e["num"]: e for e in B["entries"]}
    changed, added, missing = [], [], []
    for num in sorted(set(ea) | set(eb)):
        x, y = ea.get(num), eb.get(num)
        if x is None:
            added.append(num)
        elif y is None:
            missing.append(num)
        elif x["handler_off"] != y["handler_off"] or x["narg"] != y["narg"]:
            changed.append({
                "num": num,
                "narg": [x["narg"], y["narg"]],
                "handler": [hex(x["handler_off"]) if x["handler_off"] is not None else None,
                            hex(y["handler_off"]) if y["handler_off"] is not None else None],
            })
    print(json.dumps({"changed": changed, "only_in_a": missing, "only_in_b": added[:50]},
                     indent=2))
    return changed


def cmd_selftest(_a):
    sysent = os.path.join(DUMPS, "sysent_raw.bin")
    text = os.path.join(DUMPS, "kernel_text.bin")
    if not (os.path.exists(sysent) and os.path.exists(text)):
        raise SystemExit("13.60 capture not found; clone the 14.10 research repo first")
    entries, problems, nosys = resolve(open(sysent, "rb").read(),
                                       open(text, "rb").read(), 0xFFFFFFFF8A9C0000)
    by_num = {e["num"]: e for e in entries}
    ok = True
    for num, want in DOCUMENTED.items():
        got = by_num[num]["handler_off"]
        good = got == want
        ok &= good
        label = f"{got:#x}" if got is not None else "None"
        print(f"sys {num}: resolved {label} "
              f"vs documented {want:#x}  {'MATCH' if good else 'MISMATCH'}")
    live = [e for e in entries if not e["nosys"]]
    sony = [e for e in live if 532 <= e["num"] <= 676]
    print(f"entries {len(entries)}  live {len(live)}  nosys {len(entries)-len(live)}  "
          f"sony-live {len(sony)}  nosys-stub {hex(nosys)}")
    print(f"problems {len(problems)}")
    return 0 if ok and not problems else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve")
    r.add_argument("--sysent", required=True)
    r.add_argument("--text", required=True)
    r.add_argument("--base", required=True, type=lambda s: int(s, 0))
    r.add_argument("-o", "--out")
    r.set_defaults(func=cmd_resolve)

    d = sub.add_parser("diff")
    d.add_argument("a")
    d.add_argument("b")
    d.set_defaults(func=cmd_diff)

    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    rc = a.func(a)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
