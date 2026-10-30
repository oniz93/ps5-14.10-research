#!/usr/bin/env python3
"""Whole-tree sweep for the direct-JSC script entry points docs/75 audits.

    python3 tools/script-sweep.py > data/script-sweep/rows.json

Why this class exists: docs/70 recorded that `tools/pattern-sweep.py`'s `NAMES` cannot see
`JSC::call`/`JSC::evaluate`, and only `html/` was ever re-run with them (docs/71); docs/74 swept
`resolve(<DOM object>)` only. This sweep covers the last script-entry class: calls that enter JavaScript
directly instead of through an event dispatch or a promise settlement.

Two families, and the difference matters:

  SYNC   JSC::call / JSC::evaluate / JSC::profiledCall / JSExecState::call|evaluate|profiledCall /
         construct / callFunctionOn (Inspector) / executeScriptInWorld / evaluateScriptInExtensionTab /
         JSC::loadModule / linkAndEvaluateModule / performMicrotaskCheckpoint
         -- script runs *inside* the calling frame, so every statement after the call in that frame is a
            post-script use.

  DEFER  queueMicrotask / queueMicrotaskToEventLoop / queueTask
         -- the callable is queued on the event loop; it cannot run in the calling frame. These rows are
            listed (with their captures) only so the surface is complete, and are not windows.

`parseMicrotaskCheckpoint` is in SYNC because `MicrotaskQueue::performMicrotaskCheckpoint` drains the queue
synchronously (dom/Microtasks.cpp:51-107), which runs JSC jobs.

The tool is a net, not a verdict. A row still has to be read for (a) whether the call really enters script,
(b) whether the argument/callee is rooted, and (c) whether an unrooted C++ object is used after it.
"""
import os, re, sys, json

ROOT = "out/sony/full/WebKit-1400/WebKit-1400/Source/WebCore"
BS = chr(92); DQ = chr(34); SQ = chr(39); NL = chr(10)

SYNC = [
    "JSC::call(", "JSC::evaluate(", "JSC::profiledCall(", "JSC::profiledEvaluate(", "JSC::construct(",
    "JSExecState::call(", "JSExecState::evaluate(", "JSExecState::profiledCall(",
    "JSExecState::profiledEvaluate(", "JSExecState::runTask(", "JSExecState::loadModule(",
    "JSExecState::linkAndEvaluateModule(", "callFunctionOn(", "executeScriptInWorld(",
    "executeScriptInWorldIgnoringException(", "executeScriptIgnoringException(",
    "evaluateScriptInExtensionTab(", "linkAndEvaluateModule(", "performMicrotaskCheckpoint(",
    "evaluateModule(", "evaluateIfNecessary(",
]
DEFER = ["queueMicrotask(", "queueMicrotaskToEventLoop(", "queueTask(", "queueTaskKeepingObjectAlive("]

KEYWORDS = {"if", "for", "while", "switch", "catch", "sizeof", "return", "do", "else",
            "decltype", "alignof", "static_assert", "requires", "co_return"}
QUALIFIERS = ["const", "override", "final", "noexcept", "volatile", "mutable", "&", "&&"]


def strip_comments_strings(src):
    out = list(src); i, n = 0, len(src)
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


def match_paren_fwd(clean, open_i):
    depth = 0; k = open_i; n = len(clean)
    while k < n:
        if clean[k] == "(": depth += 1
        elif clean[k] == ")":
            depth -= 1
            if depth == 0: return k
        k += 1
    return -1


def match_paren_back(clean, close_i):
    depth = 0; k = close_i
    while k >= 0:
        if clean[k] == ")": depth += 1
        elif clean[k] == "(":
            depth -= 1
            if depth == 0: return k
        k -= 1
    return -1


def signature_before(clean, brace_i):
    k = brace_i - 1
    while k > 0 and clean[k] in " \t\r\n": k -= 1
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
    if clean[k] != ")": return None
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
    out = []; i = 0; n = len(clean); depth = 0
    while i < n:
        c = clean[i]
        if c == "{":
            sig = signature_before(clean, i)
            if sig and depth <= 4:
                name, s = sig
                d = 1; j = i + 1
                while j < n and d > 0:
                    if clean[j] == "{": d += 1
                    elif clean[j] == "}": d -= 1
                    j += 1
                out.append((name, i, j, depth)); i = j; continue
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        i += 1
    return out


def enclosing(funs, pos):
    best = None
    for name, b0, b1, _d in funs:
        if b0 <= pos < b1 and (best is None or (b1 - b0) < (best[2] - best[1])):
            best = (name, b0, b1)
    return best


def stmts_from(clean, pos, end):
    seg = clean[pos:end]; d = 0; cur = []; out = []
    for ch in seg:
        cur.append(ch)
        if ch in "({[": d += 1
        elif ch in ")}]":
            d -= 1
            if d < 0:
                d = 0
                s = "".join(cur[:-1]).strip()
                if s and s != ";": out.append(s)
                cur = []; continue
            if d == 0 and "".join(cur).strip().endswith("}"):
                s = "".join(cur).strip()
                if s and s != ";": out.append(s)
                cur = []; continue
        elif ch == ";" and d == 0:
            s = "".join(cur).strip()
            if s and s != ";": out.append(s)
            cur = []
    s = "".join(cur).strip()
    if s and s != ";": out.append(s)
    return out


def norm(t):
    return " ".join(t.split())


def collects(arg):
    """Rough capture analysis for the DEFER family."""
    caps = []
    for m in re.finditer(r"\[([^\]]*)\]", arg):
        body = m.group(1)
        for part in body.split(","):
            part = part.strip()
            if not part: continue
            if "=" in part:
                lhs, rhs = part.split("=", 1)
                caps.append("%s = %s" % (lhs.strip(), norm(rhs)[:60]))
            else:
                caps.append(part)
    return caps


MAIN = re.compile("(?<![A-Za-z0-9_:])(" + "|".join(sorted((re.escape(s) for s in SYNC + DEFER), key=len, reverse=True)) + ")")


def main():
    rows = []; counts = {"files": 0, "hits": 0, "sync": 0, "defer": 0, "with_tail": 0}
    names_sync = set(SYNC); names_defer = set(DEFER)
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fn in sorted(filenames):
            if not fn.endswith((".cpp", ".h")): continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            counts["files"] += 1
            try:
                src = open(full, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            clean = strip_comments_strings(src)
            funs = functions(clean)
            for m in MAIN.finditer(clean):
                name = m.group(1)
                op = m.end() - 1
                cl = match_paren_fwd(clean, op)
                if cl < 0: continue
                counts["hits"] += 1
                fam = "sync" if name in names_sync else "defer"
                counts[fam] += 1
                arg = clean[op + 1:cl]
                enc = enclosing(funs, m.start())
                tail = stmts_from(clean, cl + 1, enc[2] if enc else len(clean))
                if tail: counts["with_tail"] += 1
                rows.append({
                    "file": "Source/WebCore/" + rel,
                    "dir": rel.split("/")[0] + "/",
                    "func": enc[0] if enc else "",
                    "func_line": clean.count(NL, 0, enc[1]) + 1 if enc else 0,
                    "call": name,
                    "call_line": clean.count(NL, 0, m.start()) + 1,
                    "family": fam,
                    "arg": norm(arg)[:140],
                    "captures": collects(clean[op:cl + 1]) if fam == "defer" else [],
                    "n_after": len(tail),
                    "after": [norm(x)[:160] for x in tail[:5]],
                })
    print(json.dumps({"counts": counts, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
