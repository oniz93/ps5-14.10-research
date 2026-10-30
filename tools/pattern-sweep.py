#!/usr/bin/env python3
"""Enumerate function bodies under Source/WebCore/<dir>/, find script-running calls, and dump
the statements that follow each call inside the same function body.

    python3 tools/pattern-sweep.py            # defaults to css dom (what docs/69 audited)
    python3 tools/pattern-sweep.py html       # next subsystem (GOAL.md)

Run from the repo root: ROOT is relative to the working directory. Output is JSON on stdout,
one object per (function, script-running call). It is a net, not a verdict: every row still has
to be read in source for (a) whether the sink is synchronous (events and resolve(<object>) are;
reject(Exception) and resolve() are not) and (b) who owns the object used afterwards.
"""
import os, json

ROOT = "out/sony/full/WebKit-1400/WebKit-1400/Source/WebCore"
BS = chr(92); DQ = chr(34); SQ = chr(39); NL = chr(10)

KEYWORDS = {"if", "for", "while", "switch", "catch", "sizeof", "return", "do", "else",
            "decltype", "alignof", "static_assert", "requires", "co_return"}

QUALIFIERS = ["const", "override", "final", "noexcept", "volatile", "mutable", "&", "&&"]


def strip_comments_strings(src):
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find(NL, i); j = n if j < 0 else j
            for k in range(i, j): out[k] = " "
            i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            for k in range(i, j):
                if src[k] != NL: out[k] = " "
            i = j
        elif c == DQ or c == SQ:
            q = c; j = i + 1
            while j < n:
                if src[j] == BS: j += 2; continue
                if src[j] == q: j += 1; break
                j += 1
            for k in range(i, min(j, n)):
                if src[k] != NL: out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def match_paren_back(clean, close_i):
    depth = 0
    k = close_i
    while k >= 0:
        if clean[k] == ")": depth += 1
        elif clean[k] == "(":
            depth -= 1
            if depth == 0: return k
        k -= 1
    return -1


def signature_before(clean, brace_i):
    """If the '{' at brace_i opens a function body, return (name, sig_start). Else None."""
    k = brace_i - 1
    while k > 0 and clean[k] in " \t\r\n": k -= 1
    # strip trailing qualifiers
    changed = True
    while changed:
        changed = False
        for q in QUALIFIERS:
            if k - len(q) >= 0 and clean[k - len(q) + 1:k + 1] == q:
                j = k - len(q)
                if j >= 0 and clean[j] in " \t\r\n":
                    k = j
                    while k > 0 and clean[k] in " \t\r\n": k -= 1
                    changed = True
    # trailing return type -> skip to the ')' before '->'
    if clean[k] == ")" or clean[k] == "]":
        pass
    else:
        return None
    if clean[k] != ")":
        return None
    op = match_paren_back(clean, k)
    if op < 0: return None
    m = op - 1
    while m > 0 and clean[m] in " \t\r\n": m -= 1
    e = m + 1
    while m > 0 and (clean[m].isalnum() or clean[m] == "_"): m -= 1
    name = clean[m + 1:e]
    if not name or name in KEYWORDS: return None
    return name, m + 1


def functions(clean):
    """All top-level-ish function bodies: (name, brace_i, end_i, depth)."""
    out = []
    i = 0; n = len(clean); depth = 0
    while i < n:
        c = clean[i]
        if c == "{":
            sig = signature_before(clean, i)
            if sig and depth <= 2:
                name, s = sig
                d = 1; j = i + 1
                while j < n and d > 0:
                    if clean[j] == "{": d += 1
                    elif clean[j] == "}": d -= 1
                    j += 1
                out.append((name, i, j, depth))
                i = j
                continue
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        i += 1
    return out


NAMES = ["resolve", "reject", "dispatchEvent", "dispatchEventForBindings", "invokeCallback",
         "handleEvent", "getProperty", "fireEventListeners", "dispatchDOMEvent",
         "dispatchErrorEvent", "enqueueEvent", "postTask", "notifyLoaded",
         # docs/70 blind spot: the parser's own script window and JSC entry points.
         "executeScript", "executeScriptIgnoringException", "executePendingScript",
         "evaluate", "evaluateScript", "JSC::call", "JSC::evaluate", "callFunction",
         "performMicrotaskCheckpoint", "runScriptsForPausedTreeBuilder",
         "runScriptsForPausedTreeBuilderForSVG", "notifyScriptExecuted", "execute",
         "microtaskCheckpoint", "callOnMainThread"]


def find_calls(clean, b0, b1):
    hits = []
    for name in NAMES:
        s = b0
        while True:
            i = clean.find(name, s, b1)
            if i < 0: break
            s = i + 1
            if i > b0 and (clean[i - 1].isalnum() or clean[i - 1] == "_"): continue
            j = i + len(name)
            while j < b1 and clean[j] in " \t": j += 1
            if j >= b1 or clean[j] != "(": continue
            hits.append((i, name))
    hits.sort()
    return hits


def stmts_from(clean, pos, end):
    seg = clean[pos:end]; d = 0; cur = []; out = []
    for ch in seg:
        cur.append(ch)
        if ch in "({[": d += 1
        elif ch in ")}]":
            d -= 1
            if d < 0: break
        elif ch == ";" and d == 0:
            out.append("".join(cur).strip()); cur = []
    if "".join(cur).strip(): out.append("".join(cur).strip())
    return out


def norm(t):
    return " ".join(t.split())


def main():
    rows = []
    import sys
    for sub in (sys.argv[1:] or ["css", "dom"]):
        dpath = os.path.join(ROOT, sub)
        if not os.path.isdir(dpath):
            print("no such directory: " + dpath, file=sys.stderr)
            continue
        for fn in sorted(os.listdir(dpath)):
            if not fn.endswith(".cpp"): continue
            sel = os.path.join(dpath, fn)
            clean = strip_comments_strings(open(sel, encoding="utf-8", errors="replace").read())
            for name, b0, b1, depth in functions(clean):
                if b1 - b0 < 40: continue
                hits = find_calls(clean, b0, b1)
                if not hits: continue
                for pos, cname in hits:
                    aft = stmts_from(clean, pos + len(cname), b1)
                    if not aft: continue
                    rows.append({
                        "file": "Source/WebCore/%s/%s" % (sub, fn),
                        "func": name,
                        "func_line": clean.count(NL, 0, b0) + 1,
                        "call": cname,
                        "call_line": clean.count(NL, 0, pos) + 1,
                        "n_after": len(aft),
                        "after": [norm(x)[:240] for x in aft[:8]],
                    })
    print(json.dumps(rows, indent=1))
    print("TOTAL", len(rows), file=open("/tmp/audit3.count", "w"))


main()
