#!/usr/bin/env python3
"""Whole-tree sweep for `resolve(<DOM object>)` sites: the script window docs/69 measured.

    python3 tools/resolve-sweep.py > /tmp/resolve-sweep.json

Walks every .cpp under Source/WebCore (all subdirectories, recursive), strips comments and
string literals, finds every promise settlement spelled `resolve(`, `resolveWith*(` or
`settle(`, and for each hit emits: the enclosing function, the raw argument text, a coarse
class for that argument, and the statements that follow inside the same function body.

It is a net, not a verdict. A row still has to be read in source for (a) whether the
argument is a DOM object (so that JSC's Promise Resolve Function reads `then` and runs
script synchronously) and (b) whether anything is used after that call which script can
free. Rows in css/ dom/ html/ html/parser style/ page/ loader/ were already audited
(docs/69-73); this tool marks them so the new surface is obvious.
"""
import os, re, sys, json

ROOT = "out/sony/full/WebKit-1400/WebKit-1400/Source/WebCore"
BS = chr(92); DQ = chr(34); SQ = chr(39); NL = chr(10)

AUDITED = ("css/", "dom/", "html/", "style/", "page/", "loader/")

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


def match_paren_fwd(clean, open_i):
    depth = 0
    k = open_i
    n = len(clean)
    while k < n:
        if clean[k] == "(": depth += 1
        elif clean[k] == ")":
            depth -= 1
            if depth == 0: return k
        k += 1
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
    # grab a class qualification if present: Foo::bar
    q = m
    while q > 1 and (clean[q].isalnum() or clean[q] in "_:<>, *&"):
        q -= 1
    head = clean[q + 1:m + 1]
    if "::" in head:
        name = head.split()[-1] + "::" + name if "::" not in name else name
    return name, m + 1


def functions(clean):
    out = []
    i = 0; n = len(clean); depth = 0
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
                out.append((name, i, j, depth))
                i = j
                continue
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        i += 1
    return out


SETTLE_RE = re.compile(r"(?<![A-Za-z0-9_])(resolve|resolveWith[A-Za-z]*|settle)\s*\(")


def enclosing(funs, pos):
    best = None
    for name, b0, b1, _d in funs:
        if b0 <= pos < b1:
            if best is None or (b1 - b0) < (best[2] - best[1]):
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
                # The call sat inside a block that just closed. Keep going at the outer level so
                # statements after the enclosing `if`/`for` are still seen (docs/74 blind spot #1).
                d = 0
                s = "".join(cur[:-1]).strip()
                if s and s != ";": out.append(s)
                cur = []
                continue
            if d == 0 and cur and "".join(cur).strip().endswith("}"):
                s = "".join(cur).strip()
                if s and s != ";": out.append(s)
                cur = []
                continue
        elif ch == ";" and d == 0:
            s = "".join(cur).strip()
            if s and s != ";": out.append(s)
            cur = []
    s = "".join(cur).strip()
    if s and s != ";": out.append(s)
    return out


def norm(t):
    return " ".join(t.split())


PRIM_MARKERS = ("Exception", "TypeError", "NetworkError", "NotSupportedError", "jsUndefined",
                "jsNull", "nullptr", "std::nullopt", "PermissionState::", "jsBoolean",
                "SyntaxError", "SecurityError", "InvalidStateError", "NotAllowedError",
                "AbortError", "QuotaExceededError", "NotFoundError", "UnknownError")


def classify(arg):
    a = arg.strip()
    if a == "":
        return "empty"
    if a.startswith("{"):
        return "braces"
    if re.match(r"^WTFMove\((.*)\)$", a):
        inner = re.match(r"^WTFMove\((.*)\)$", a).group(1)
        return "move:" + classify(inner)
    if re.match(r"^std::forward<.*>\((.*)\)$", a):
        return "fwd"
    if a == "*this":
        return "this"
    if a.startswith("*"):
        return "deref"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", a):
        return "ident"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_:<>]*::[A-Za-z_][A-Za-z0-9_]*\(.*\)$", a, re.S):
        return "factory"
    if a.endswith("releaseNonNull()"):
        return "refnn"
    if "(" in a:
        return "call"
    return "other"


def loop_headers(clean, b0, b1):
    """All for/while loops in [b0,b1) as (kind, header_text, body_start, body_end)."""
    out = []
    i = b0
    while i < b1:
        m = LOOP_RE.search(clean, i, b1)
        if not m: break
        kind = m.group(1)
        op = m.end() - 1
        cl = match_paren_fwd(clean, op)
        if cl < 0: break
        header = clean[op + 1:cl]
        j = cl + 1
        while j < b1 and clean[j] in " \t\r\n": j += 1
        if j < b1 and clean[j] == "{":
            d = 1; k = j + 1
            while k < b1 and d > 0:
                if clean[k] == "{": d += 1
                elif clean[k] == "}": d -= 1
                k += 1
            body = (j, k)
        else:
            d = 0; k = j
            while k < b1:
                if clean[k] in "({[": d += 1
                elif clean[k] in ")}]":
                    d -= 1
                    if d < 0: break
                elif clean[k] == ";" and d == 0:
                    k += 1; break
                k += 1
            body = (j, k)
        out.append((kind, norm(header), body[0], body[1]))
        i = cl + 1
    return out


def settlements_in_loops(clean, fun):
    """For each settlement call in this function body, the enclosing loops."""
    res = []
    name, b0, b1 = fun
    loops = loop_headers(clean, b0, b1)
    if not loops: return res
    for m in SETTLE_RE.finditer(clean, b0, b1):
        enc = [l for l in loops if l[2] <= m.start() < l[3]]
        if enc:
            res.append((m.start(), enc))
    return res


LOOP_RE = re.compile(r"(?<![A-Za-z0-9_])(for|while)\s*\(")


def main():
    rows = []
    counts = {"files": 0, "hits": 0}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git",))
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
            for m in SETTLE_RE.finditer(clean):
                name = m.group(1)
                op = m.end() - 1
                cl = match_paren_fwd(clean, op)
                if cl < 0: continue
                counts["hits"] += 1
                arg = clean[op + 1:cl]
                enc = enclosing(funs, m.start())
                tail = stmts_from(clean, cl + 1, enc[2] if enc else len(clean))
                loops = []
                if enc:
                    for kind, header, lb0, lb1 in loop_headers(clean, enc[1], enc[2]):
                        if lb0 <= m.start() < lb1:
                            loops.append(header)
                rows.append({
                    "file": "Source/WebCore/" + rel,
                    "dir": rel.split("/")[0] + "/",
                    "audited": any(rel.startswith(p) for p in AUDITED),
                    "func": enc[0] if enc else "",
                    "func_line": clean.count(NL, 0, enc[1]) + 1 if enc else 0,
                    "call": name,
                    "call_line": clean.count(NL, 0, m.start()) + 1,
                    "arg": norm(arg)[:160],
                    "cls": classify(arg),
                    "loops": [norm(h)[:140] for h in loops],
                    "n_after": len(tail),
                    "after": [norm(x)[:200] for x in tail[:6]],
                })
    print(json.dumps({"counts": counts, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
