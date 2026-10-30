#!/usr/bin/env python3
"""Recall check for tools/index-loop-resolve.py (docs/82).

    python3 tools/index-loop-resolve-validate.py

The resolver's claim is "a call in a loop body is followed to a script window up to three hops
away, by receiver type". A negative result from it is only worth recording if the walker can be
shown to find windows that are there. This builds a ground truth without hand-picking cases:

  for every method body C with no script window of its own, find a call C makes to a method M
  that *does* contain a window (depth 1 by construction). C -> M is then a real multi-hop chain,
  and route(C) must reach M at depth >= 2.

Two routes are exercised separately, because they are different code paths:

  bare     C calls M with no receiver (`dispatchDOMEvent(...)`) — resolved through the owning
           class's method table first, the unique-name index second;
  receiver C calls `obj->M(...)`, where obj's type is resolved from a member or a local.

The first version of this check compared route(C)'s last hop against M and scored 0/6 — every one
of those six callers contained its own `dispatchEvent(`, so route(C) correctly stopped at depth 1.
A caller that has its own window is not a multi-hop test; both arms below exclude it.
"""
import importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ilr", os.path.join(HERE, "index-loop-resolve.py"))
ilr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ilr)

BARE = re.compile(r"(?<![\w.>:])([A-Za-z_]\w*)\s*\(")
CALLEES = ["dispatchDOMEvent", "dispatchChildInsertionEvents", "dispatchChildRemovalEvents",
           "performMicrotaskCheckpoint", "enqueueEvent", "didReceiveData",
           "runScriptsForPausedTreeBuilder", "executePendingScript", "getOwnPropertySlotByIndex"]
RECV = re.compile(r"(?<![\w.>])([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*(?:->|\.)\s*(%s)\s*\("
                  % "|".join(CALLEES))


def main():
    R = ilr.Resolver()
    R.scan()
    ok = miss = used = 0
    misses = []
    seen = set()
    for rel, funcs in R.file_funcs.items():
        clean = R.clean_of(rel)
        for name, f0, f1, _d in funcs:
            short = name.split("::")[-1]
            cls = name.rsplit("::", 1)[0].split("::")[-1] if "::" in name \
                else R.enclosing_class(rel, f0) or R.class_from_context(clean, f0)
            if not cls or (cls, short) in seen:
                continue
            body = clean[f0:f1]
            if ilr.DIRECT_RE.search(body):
                continue        # a caller with its own window is depth 1, not a multi-hop test
            callee = None
            for mm in BARE.finditer(body):
                n = mm.group(1)
                if n in ilr.CALL_KEYWORDS or n == short:
                    continue
                b, _ = R.method_body_any(cls, n)
                if b and ilr.DIRECT_RE.search(b):
                    callee = n
                    break
            if not callee:
                continue
            seen.add((cls, short))
            used += 1
            routes, _ = R.route(cls, short, 3)
            if [x for x in routes if x["route"][-1].split("::")[-1] == callee and x["depth"] >= 2]:
                ok += 1
            elif len(misses) < 8:
                misses.append((cls, short, callee, [x["route"][-1] for x in routes][:3]))
            else:
                miss += 1
            if used >= 60:
                break
        if used >= 60:
            break
    print("bare multi-hop callers tested: %d  ok=%d  miss=%d" % (used, ok, miss + len(misses)))
    for x in misses:
        print("  MISS", x)

    # receiver arm: a call `obj->M(...)` where obj's type resolves and M has a window.
    rok = rmiss = rused = 0
    rmisses = []
    for rel, funcs in R.file_funcs.items():
        clean = R.clean_of(rel)
        for name, f0, f1, _d in funcs:
            short = name.split("::")[-1]
            cls = name.rsplit("::", 1)[0].split("::")[-1] if "::" in name \
                else R.enclosing_class(rel, f0) or R.class_from_context(clean, f0)
            if not cls or (cls, short) in seen:
                continue
            body = clean[f0:f1]
            if ilr.DIRECT_RE.search(body):
                continue
            hit = None
            for mm in RECV.finditer(body):
                rc = R.recv_cls(mm.group(1), clean, 0, f0 + mm.start(), cls)
                if rc and R.method_body_any(rc, mm.group(2))[0] and \
                        ilr.DIRECT_RE.search(R.method_body_any(rc, mm.group(2))[0]):
                    hit = (mm.group(1), mm.group(2), rc)
                    break
            if not hit:
                continue
            seen.add((cls, short))
            rused += 1
            routes, _ = R.route(cls, short, 3)
            want = "%s::%s" % (hit[2], hit[1])
            if [x for x in routes if x["route"][-1] == want and x["depth"] >= 2]:
                rok += 1
            elif len(rmisses) < 8:
                rmisses.append((cls, short) + hit + ([x["route"][-1] for x in routes][:3],))
            else:
                rmiss += 1
            if rused >= 40:
                break
        if rused >= 40:
            break
    print("receiver multi-hop callers tested: %d  ok=%d  miss=%d" % (rused, rok, rmiss + len(rmisses)))
    for x in rmisses:
        print("  MISS", x)
    return 0 if (miss + len(misses) + rmiss + len(rmisses)) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
