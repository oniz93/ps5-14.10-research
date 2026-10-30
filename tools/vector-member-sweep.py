#!/usr/bin/env python3
"""Whole-tree sweep for the `Vector<X*> m_foo` *member* shape (docs/79), plus `HashMap`/`HashSet<X*>` locals.

Why this class, and why docs/78 does not cover it: `docs/78` swept *locals*. A local vector's first N elements
live on the stack, which the conservative stack scan marks (measured as a GC constraint: `Heap.cpp:2841`,
`MachineStackMarker.cpp:39-48`). A *member* vector's buffer is heap for the owner's whole lifetime, so the scan
never sees it, and the owner's lifetime is something page script can influence. docs/77 swept JSValue/JSCell
*members* only (147 rows); a raw `Vector<Element*>` / `Vector<Node*>` / `Vector<RefCountedThing*>` member — a
pointer that refs nothing — is the same shape with no rooting.

Two analyses in one pass, sharing the cleaned source:

  A. MEMBERS   every `Vector|FixedVector|Deque|ListHashSet<X*[, N]> m_*` declared at class scope (owner class,
               capacity recorded), then every push to that name in the tree. Keep the ones where a push sits
               inside a `for`/`while`/`do` (or the enclosing function recurses), the same function reads the
               vector after the push, and the interval [first push, last read] contains a script sink — direct,
               or one level deep through a callee (phase B, resolved only for the surviving rows).

  B. HASH      every `HashSet<X*>` / `HashCountedSet<X*>` / `HashMap<K, X*>` *local* (always heap, so no
               capacity question) inserted inside a loop, read after the insert, with a sink in the interval.

The tool is a net, not a verdict. A row is a bug only if the pointee can lose its last ref (or its last GC root)
inside the window; that is read in source, one row at a time.

    python3 tools/vector-member-sweep.py > data/vector-member/inventory.json
"""
import os, re, sys, json, importlib.util
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("vls", os.path.join(HERE, "vector-local-sweep.py"))
vls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vls)

WEB_CORE = vls.WEB_CORE
strip = vls.strip_comments_strings
match_angle = vls.match_angle
split_args = vls.split_args
functions = vls.functions
in_loop = vls.in_loop
class_index = vls.class_index
classify = vls.classify
DIRECT_RE = vls.DIRECT_RE
PROP_RE = vls.PROP_RE
CALL_RE = vls.CALL_RE
KEEPING_ELEM = vls.KEEPING_ELEM
CELL_ELEMS = vls.CELL_ELEMS
NL = chr(10)

VEC_CONTAINERS = ("Vector", "FixedVector", "Deque", "ListHashSet")
HASH_CONTAINERS = ("HashSet", "HashCountedSet", "HashMap")
PUSHES = ("append", "uncheckedAppend", "appendWithCrashOnOverflow", "appendVector", "appendRange",
          "insert", "prepend", "push_back", "appendSlowCase")
HASH_PUSHES = ("add", "insert", "set", "ensure", "addVectorsFrom", "fastAdd")
CLASS_RE = re.compile(r"\b(class|struct)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{]*)?\{")


def depth_prefix(clean):
    """depth[i] = brace depth immediately before index i."""
    n = len(clean)
    dep = [0] * n
    d = 0
    for i in range(n):
        dep[i] = d
        c = clean[i]
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
    return dep


def class_scopes(clean):
    out = []
    n = len(clean)
    for m in CLASS_RE.finditer(clean):
        ob = m.end() - 1
        d = 1
        j = ob + 1
        while j < n and d > 0:
            c = clean[j]
            if c == "{":
                d += 1
            elif c == "}":
                d -= 1
            j += 1
        out.append((m.group(2), m.group(1), ob, j))
    return out


def decl_name(clean, cl):
    """The declared name right after a closing `>`, or None."""
    dm = re.match(r"\s*(?:const\s+)?([A-Za-z_]\w*)\s*[;{(=,\[:\]]", clean[cl + 1:cl + 200])
    return dm.group(1) if dm else None


def main():
    idx = class_index()

    # ---------- A1: member declarations (headers first; classes can also live in .cpp) ----------
    members = {}          # name -> list of rows
    files_on_disk = []
    for dirpath, dirnames, filenames in os.walk(WEB_CORE):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fn in sorted(filenames):
            if fn.endswith((".cpp", ".mm", ".h")):
                files_on_disk.append(os.path.join(dirpath, fn))
    print("FILES %d" % len(files_on_disk), file=sys.stderr)

    for path in files_on_disk:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if not re.search(r"\b(Vector|FixedVector|Deque|ListHashSet|HashSet|HashCountedSet|HashMap)\s*<", src):
            continue
        clean = strip(src)
        scopes = class_scopes(clean)
        if not scopes:
            continue
        dep = depth_prefix(clean)
        for owner, _kw, ob, cb in scopes:
            body_depth = dep[ob] + 1
            for m in re.finditer(r"(?<![\w:>])(%s)\s*<" % "|".join(VEC_CONTAINERS), clean[ob:cb]):
                pos = ob + m.start()
                if dep[pos] != body_depth:
                    continue
                container = m.group(1)
                op = ob + m.end() - 1
                cl = match_angle(clean, op)
                if cl < 0 or cl > cb:
                    continue
                args = split_args(clean[op + 1:cl])
                if not args:
                    continue
                elem = args[0]
                cap = args[1] if len(args) > 1 and args[1].isdigit() else ("0" if len(args) < 2 else "?")
                if any(k in elem for k in KEEPING_ELEM):
                    continue
                if "*" not in elem and elem.strip().split("::")[-1] not in CELL_ELEMS:
                    continue
                name = decl_name(clean, cl)
                if not name or not name.startswith("m_"):
                    continue
                eb, kind, bases = classify(elem, idx)
                members.setdefault(name, []).append({
                    "owner": owner,
                    "file": "Source/WebCore/" + os.path.relpath(path, WEB_CORE),
                    "line": clean.count(NL, 0, pos) + 1,
                    "container": container,
                    "elem": " ".join(elem.split()),
                    "cap": cap,
                    "elem_base": eb,
                    "elem_kind": kind,
                    "elem_bases": bases[:140],
                })
    print("MEMBER_DECLS %d distinct names, %d declarations"
          % (len(members), sum(len(v) for v in members.values())), file=sys.stderr)

    # ---------- A2/B: one pass over the tree for uses ----------
    names_re = re.compile(r"\b(" + "|".join(sorted(members, key=len, reverse=True)) + r")\b") if members else None
    push_re = re.compile(r"\b(m_[A-Za-z_]\w*)\s*(?:\.|->)\s*(%s)\s*\(" % "|".join(PUSHES))
    hash_decl_re = re.compile(r"(?<![\w:>])(%s)\s*<" % "|".join(HASH_CONTAINERS))
    hash_push_re = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*(%s)\s*\(" % "|".join(HASH_PUSHES))

    counts = {"files_scanned": 0, "files_cleaned": 0, "member_names_live": 0, "push_sites": 0,
              "push_in_loop": 0, "with_read": 0, "with_sink": 0,
              "hash_decls": 0, "hash_push_in_loop": 0, "hash_with_read": 0, "hash_with_sink": 0}
    member_rows = []
    hash_rows = []

    for path in files_on_disk:
        counts["files_scanned"] += 1
        rel = os.path.relpath(path, WEB_CORE)
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        has_member = bool(names_re and names_re.search(src))
        has_hash = bool(hash_decl_re.search(src))
        if not (has_member or has_hash):
            continue
        clean = strip(src)
        counts["files_cleaned"] += 1
        funs = functions(clean)
        if not funs:
            continue

        def enc(pos):
            best = None
            for f in funs:
                if f[1] <= pos < f[2] and (best is None or (f[2] - f[1]) < (best[2] - best[1])):
                    best = f
            return best

        # --- members ---
        if has_member:
            for pm in push_re.finditer(clean):
                name = pm.group(1)
                if name not in members:
                    continue
                pos = pm.start()
                f = enc(pos)
                if not f:
                    continue
                counts["push_sites"] += 1
                fname, f0, f1 = f[0], f[1], f[2]
                body = clean[f0:f1]
                looped, loopkw = in_loop(clean, pos, f0)
                short = fname.split("::")[-1]
                if not looped and re.search(r"\b" + re.escape(short) + r"\s*\(", body):
                    looped, loopkw = True, "recursion"
                if not looped:
                    continue
                counts["push_in_loop"] += 1
                readpat = (r"\b" + re.escape(name) + r"\s*(?:\.|->)\s*"
                           r"(?:last|at|first|begin|end|size|isEmpty|reverseBegin|removeLast|takeLast|operator\[\])\s*\("
                           r"|\b" + re.escape(name) + r"\s*\["
                           r"|:\s*" + re.escape(name) + r"\s*\)")
                reads = [f0 + rm.start() for rm in re.finditer(readpat, body) if f0 + rm.start() > pos]
                if reads:
                    counts["with_read"] += 1
                lo, hi = pos, (max(reads) if reads else f1)
                interval = clean[lo:hi]
                dhits = sorted({x.group(0)[:-1] for x in DIRECT_RE.finditer(interval)})
                phits = sorted({"get" if x.group(0) in ("->get(", ".get(") else x.group(0)[:-1]
                                for x in PROP_RE.finditer(interval)})
                if dhits:
                    counts["with_sink"] += 1
                calls = sorted({c.group(1) for c in CALL_RE.finditer(interval)})
                # the snapshot-callback loop shape: `for (auto* e : m_x) e->something()`
                cbs = []
                for lm in re.finditer(r"\bfor\s*\(([^)]{0,200})\)", clean[f0:f1]):
                    head = lm.group(1)
                    if name not in head:
                        continue
                    var = None
                    hm = re.search(r"([A-Za-z_]\w*)\s*:\s*" + re.escape(name) + r"\b", head)
                    if hm:
                        var = hm.group(1)
                    d = 1
                    k = f0 + lm.end()
                    while k < len(clean) and d > 0:
                        if clean[k] == "{":
                            d += 1
                        elif clean[k] == "}":
                            d -= 1
                        k += 1
                    body2 = clean[f0 + lm.end():k]
                    meths = []
                    if var:
                        for mm in re.finditer(r"\b" + re.escape(var) + r"\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*\(", body2):
                            if mm.group(1) not in meths:
                                meths.append(mm.group(1))
                    cbs.append({"var": var, "methods": meths[:6]})
                for decl in members[name]:
                    member_rows.append(dict(decl, **{
                        "func": fname,
                        "func_file": "Source/WebCore/" + rel,
                        "func_line": clean.count(NL, 0, f0) + 1,
                        "push_line": clean.count(NL, 0, pos) + 1,
                        "loop": loopkw,
                        "reads": len(reads),
                        "direct": dhits,
                        "prop": phits,
                        "calls": calls[:24],
                        "cb": cbs[:3],
                        "interval": " ".join(interval.split())[:500],
                    }))
                    break

        # --- hash locals ---
        if has_hash:
            for hm in hash_decl_re.finditer(clean):
                container = hm.group(1)
                pos = hm.start()
                f = enc(pos)
                if not f:
                    continue
                op = hm.end() - 1
                cl = match_angle(clean, op)
                if cl < 0:
                    continue
                args = split_args(clean[op + 1:cl])
                if not args:
                    continue
                elem = args[1] if (container == "HashMap" and len(args) > 1) else args[0]
                if "*" not in elem or any(k in elem for k in KEEPING_ELEM):
                    continue
                name = decl_name(clean, cl)
                if not name:
                    continue
                fname, f0, f1 = f[0], f[1], f[2]
                body = clean[f0:f1]
                if not re.search(r"\b" + re.escape(name) + r"\s*\.\s*(%s)\s*\(" % "|".join(HASH_PUSHES), body):
                    continue
                counts["hash_decls"] += 1
                pushes = [f0 + pm.start() for pm in
                          re.finditer(r"\b" + re.escape(name) + r"\s*\.\s*(%s)\s*\(" % "|".join(HASH_PUSHES), body)]
                looped = False
                loopkw = ""
                for pp in pushes:
                    ok, kw = in_loop(clean, pp, f0)
                    if ok:
                        looped, loopkw = True, kw
                        break
                short = fname.split("::")[-1]
                if not looped and re.search(r"\b" + re.escape(short) + r"\s*\(", body):
                    looped, loopkw = True, "recursion"
                if not looped:
                    continue
                counts["hash_push_in_loop"] += 1
                readpat = (r"\b" + re.escape(name) + r"\s*\.\s*"
                           r"(?:contains|find|get|size|isEmpty|begin|end|values|keys)\s*\("
                           r"|\bfor\s*\([^)]{0,160}:\s*" + re.escape(name) + r"\s*\)")
                reads = [f0 + rm.start() for rm in re.finditer(readpat, body) if f0 + rm.start() > min(pushes)]
                if reads:
                    counts["hash_with_read"] += 1
                lo, hi = min(pushes), (max(reads) if reads else f1)
                interval = clean[lo:hi]
                dhits = sorted({x.group(0)[:-1] for x in DIRECT_RE.finditer(interval)})
                phits = sorted({"get" if x.group(0) in ("->get(", ".get(") else x.group(0)[:-1]
                                for x in PROP_RE.finditer(interval)})
                if dhits:
                    counts["hash_with_sink"] += 1
                calls = sorted({c.group(1) for c in CALL_RE.finditer(interval)})
                eb, kind, bases = classify(elem, idx)
                hash_rows.append({
                    "file": "Source/WebCore/" + rel,
                    "line": clean.count(NL, 0, pos) + 1,
                    "func": fname,
                    "func_line": clean.count(NL, 0, f0) + 1,
                    "container": container,
                    "elem": " ".join(elem.split()),
                    "name": name,
                    "loop": loopkw,
                    "pushes": len(pushes),
                    "reads": len(reads),
                    "direct": dhits,
                    "prop": phits,
                    "calls": calls[:24],
                    "elem_base": eb,
                    "elem_kind": kind,
                    "elem_bases": bases[:140],
                    "interval": " ".join(interval.split())[:500],
                })

    # ---------- phase B: resolve one callee level for rows with no direct sink ----------
    def callee_sinks(names, limit_defs=12):
        """names -> list of names every one of whose definitions contains a direct sink."""
        if not names:
            return []
        pat = re.compile(r"\b(" + "|".join(sorted(set(names), key=len, reverse=True)) + r")\s*\(")
        stats = {}
        for path in files_on_disk:
            try:
                src = open(path, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            if not any(n in src for n in names):
                continue
            clean = strip(src)
            for fname, f0, f1, _d in functions(clean):
                short = fname.split("::")[-1]
                if short not in names:
                    continue
                slot = stats.setdefault(short, [0, 0])
                slot[0] += 1
                if DIRECT_RE.search(clean[f0:f1]):
                    slot[1] += 1
        return sorted(n for n, (nd, ns) in stats.items() if nd and ns == nd and nd <= limit_defs)

    thru_cache = {}
    for row in member_rows + hash_rows:
        if row["direct"] or not row["calls"]:
            row["thru"] = []
            continue
        want = [c for c in row["calls"] if c not in thru_cache]
        if want:
            for n in callee_sinks(want):
                thru_cache[n] = True
            for n in want:
                thru_cache.setdefault(n, False)
        row["thru"] = [c for c in row["calls"] if thru_cache.get(c)]

    member_rows.sort(key=lambda r: (-len(r["direct"]), -len(r["thru"]), r["elem_kind"], r["file"]))
    hash_rows.sort(key=lambda r: (-len(r["direct"]), -len(r["thru"]), r["elem_kind"], r["file"]))
    print("KINDS members:", Counter(r["elem_kind"] for r in member_rows), file=sys.stderr)
    print("KINDS hash   :", Counter(r["elem_kind"] for r in hash_rows), file=sys.stderr)
    print(json.dumps({
        "counts": counts,
        "member_decl_count": sum(len(v) for v in members.values()),
        "member_names": {k: v for k, v in sorted(members.items())},
        "members": member_rows,
        "hash": hash_rows,
    }, indent=1))


if __name__ == "__main__":
    main()
