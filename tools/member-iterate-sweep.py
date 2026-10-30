#!/usr/bin/env python3
"""Whole-tree sweep for the *iterate-and-callback* member shape (docs/79).

docs/79's first pass looked for `Vector<X*> m_foo` members that are appended inside a loop and read after a script
window. That found 16 rows and 0 with a sink, because for a member the dangerous direction is the opposite one:
the container is **iterated**, the loop body calls into a callee that runs script, and the script mutates the
container the loop is standing on. That is exactly CVE-2026-43715's shape (`iterateClients` over `m_clients`), and
it is why a member differs from a local: the buffer is heap for the owner's whole lifetime, script reaches the
owner (through the DOM, through a request callback), and `Vector::clear()` inside the callback frees the buffer the
range-for still holds `begin`/`end` into.

For every member container declaration in `Source/WebCore` (`Vector`, `FixedVector`, `Deque`, `ListHashSet`,
`HashSet`, `HashCountedSet`, `HashMap`, `WeakHashSet`, `WeakHashMap`) and every range-for over it:

  * the element class (raw pointer / Ref / RefPtr / WeakPtr / value),
  * whether the loop body contains a direct script sink, or one callee level deep (resolved for survivors),
  * whether the loop body itself mutates the container (`clear/append/remove/swap/removeAll/takeFirst/...`),
  * whether the body, or any callee it calls, resolves to a function that mutates that member.

    python3 tools/member-iterate-sweep.py > data/vector-member/iterate.json
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
DIRECT_RE = vls.DIRECT_RE
PROP_RE = vls.PROP_RE
CALL_RE = vls.CALL_RE
classify = vls.classify
class_index = vls.class_index
NL = chr(10)

CONTAINERS = ("Vector", "FixedVector", "Deque", "ListHashSet", "HashSet", "HashCountedSet", "HashMap",
              "WeakHashSet", "WeakHashMap")
# A loop body that invokes a client/callback interface runs script even when the callee is a virtual method,
# not a free function: `client.didX(...)`, `m_callback->handleEvent(...)`, `function(...)`. docs/65's
# `iterateClients` is exactly this shape and its only "sink token" was the virtual call itself.
CALLBACK_RE = re.compile(
    r"->\s*(?:handleEvent|call|invoke|did[A-Z]\w*|will[A-Z]\w*|notify\w*|fire\w*)\s*\("
    r"|\.\s*(?:handleEvent|call|invoke|notify\w*)\s*\("
    r"|\b(?:m_)?(?:callback|client|observer|handler|listener|delegate|function|completion|callbackFunction)\w*"
    r"\s*(?:->\s*\w+|\()")

MUTATORS = ("clear", "append", "uncheckedAppend", "appendVector", "appendRange", "insert", "prepend", "remove",
            "removeAll", "removeFirst", "removeLast", "takeFirst", "takeLast", "swap", "shrink", "resize",
            "reverse", "sort", "add", "set", "ensure", "deleteAllValues", "removeIf")
CLASS_RE = re.compile(r"\b(class|struct)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{]*)?\{")
FOR_RE = re.compile(r"\bfor\s*\(")


def depth_prefix(clean):
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
        out.append((m.group(2), ob, j))
    return out


def decl_name(clean, cl):
    dm = re.match(r"\s*(?:const\s+)?([A-Za-z_]\w*)\s*[;{(=,\[:\]]", clean[cl + 1:cl + 200])
    return dm.group(1) if dm else None


def elem_class(elem):
    e = elem
    if "RefPtr<" in e:
        return "refptr"
    if "Ref<" in e:
        return "ref"
    if "WeakPtr<" in e or "Weak<" in e:
        return "weak"
    if "unique_ptr<" in e or "UniqueRef<" in e:
        return "unique"
    if "*" in e:
        return "raw"
    return "value"


def main():
    idx = class_index()
    files = []
    for dirpath, dirnames, filenames in os.walk(WEB_CORE):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fn in sorted(filenames):
            if fn.endswith((".cpp", ".mm", ".h")):
                files.append(os.path.join(dirpath, fn))

    # ---------- pass 1: member container declarations ----------
    members = {}
    for path in files:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if "m_" not in src or not re.search(r"\b(%s)\s*<" % "|".join(CONTAINERS), src):
            continue
        clean = strip(src)
        scopes = class_scopes(clean)
        if not scopes:
            continue
        dep = depth_prefix(clean)
        rel = "Source/WebCore/" + os.path.relpath(path, WEB_CORE)
        for owner, ob, cb in scopes:
            bd = dep[ob] + 1
            for m in re.finditer(r"(?<![\w:>])(%s)\s*<" % "|".join(CONTAINERS), clean[ob:cb]):
                pos = ob + m.start()
                if dep[pos] != bd:
                    continue
                container = m.group(1)
                op = ob + m.end() - 1
                cl = match_angle(clean, op)
                if cl < 0 or cl > cb:
                    continue
                args = split_args(clean[op + 1:cl])
                if not args:
                    continue
                name = decl_name(clean, cl)
                if not name or not name.startswith("m_"):
                    continue
                elem = args[1] if (container in ("HashMap", "WeakHashMap") and len(args) > 1) else args[0]
                cap = args[1] if (container in ("Vector", "FixedVector", "Deque") and len(args) > 1
                                  and args[1].isdigit()) else "-"
                members.setdefault(name, []).append({
                    "name": name,
                    "owner": owner, "file": rel, "line": clean.count(NL, 0, pos) + 1,
                    "container": container, "elem": " ".join(elem.split()), "cap": cap,
                    "ekind": elem_class(elem),
                })
    print("MEMBER_CONTAINERS %d names / %d decls" % (len(members), sum(len(v) for v in members.values())),
          file=sys.stderr)

    name_re = re.compile(r"\b(" + "|".join(sorted(members, key=len, reverse=True)) + r")\b") if members else None
    counts = {"files": len(files), "files_cleaned": 0, "range_fors": 0, "with_sink": 0, "self_mutating": 0,
              "reentrant": 0}
    rows = []

    # ---------- pass 2: range-fors over those members ----------
    for path in files:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if not (name_re and name_re.search(src)):
            continue
        if not re.search(r"for\s*\([^;]{0,240}:\s*m_[A-Za-z_]", src):
            continue
        clean = strip(src)
        counts["files_cleaned"] += 1
        rel = "Source/WebCore/" + os.path.relpath(path, WEB_CORE)
        funs = functions(clean)
        for fm in FOR_RE.finditer(clean):
            op = fm.end() - 1
            cl = vls.match_paren_fwd(clean, op)
            if cl < 0:
                continue
            head = clean[op + 1:cl]
            if ";" in head:
                continue          # classic three-clause for, not a range-for
            hm = re.search(r":\s*(m_[A-Za-z_]\w*)\b", head)
            if not hm:
                continue
            name = hm.group(1)
            if name not in members:
                continue
            counts["range_fors"] += 1
            k = cl + 1
            while k < len(clean) and clean[k] in " \t\r\n":
                k += 1
            if k >= len(clean) or clean[k] != "{":
                continue
            d = 1
            j = k + 1
            while j < len(clean) and d > 0:
                if clean[j] == "{":
                    d += 1
                elif clean[j] == "}":
                    d -= 1
                j += 1
            body = clean[k:j]
            dhits = sorted({x.group(0)[:-1] for x in DIRECT_RE.finditer(body)})
            phits = sorted({"get" if x.group(0) in ("->get(", ".get(") else x.group(0)[:-1]
                            for x in PROP_RE.finditer(body)})
            mut = sorted({x for x in MUTATORS
                          if re.search(r"\b" + re.escape(name) + r"\s*(?:\.|->)\s*" + x + r"\s*\(", body)})
            if dhits:
                counts["with_sink"] += 1
            if mut:
                counts["self_mutating"] += 1
            calls = sorted({c.group(1) for c in CALL_RE.finditer(body)})
            cbish = sorted({" ".join(x.group(0).split()) for x in CALLBACK_RE.finditer(body)})
            var = None
            vm = re.match(r"\s*(?:const\s+)?(?:auto|[\w:<>]+)\s*[*&\s]*\s*([A-Za-z_]\w*)\s*:", head)
            if vm:
                var = vm.group(1)
            meths = []
            if var:
                for mm in re.finditer(r"\b" + re.escape(var) + r"\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*\(", body):
                    if mm.group(1) not in meths:
                        meths.append(mm.group(1))
            enc = None
            for f in funs:
                if f[1] <= fm.start() < f[2] and (enc is None or (f[2] - f[1]) < (enc[2] - enc[1])):
                    enc = f
            for decl in members[name]:
                if enc:
                    fn = enc[0]
                    base = os.path.basename(rel).split(".")[0]
                    same_owner = (fn.split("::")[0] == decl["owner"]
                                  or base == decl["owner"]
                                  or decl["file"] == rel)
                    if not same_owner:
                        continue
                pre = clean[max(0, fm.start() - 600):fm.start()]
                swapped = bool(re.search(r"\b" + re.escape(name) + r"\s*\.\s*swap\s*\(", pre)
                               or re.search(r"std::swap\s*\(\s*" + re.escape(name) + r"\b", pre))
                rows.append(dict(decl, **{
                    "swapped_before": swapped,
                    "func": enc[0] if enc else "?",
                    "func_file": rel,
                    "func_line": clean.count(NL, 0, enc[1]) + 1 if enc else 0,
                    "loop_line": clean.count(NL, 0, fm.start()) + 1,
                    "var": var,
                    "methods": meths[:8],
                    "direct": dhits,
                    "prop": phits,
                    "cbish": cbish[:10],
                    "mutates": mut,
                    "calls": calls[:24],
                    "body": " ".join(body.split())[:400],
                }))
                break

    # ---------- pass 3: one callee level — does a callee dispatch, or mutate the member? ----------
    MUT_RE = re.compile(r"\b(m_[A-Za-z_]\w*)\s*(?:\.|->)\s*(?:%s)\s*\(" % "|".join(MUTATORS))

    def resolve(want):
        stats = {}
        for path in files:
            try:
                src = open(path, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            if not any(n in src for n in want):
                continue
            clean = strip(src)
            for fname, f0, f1, _d in functions(clean):
                short = fname.split("::")[-1]
                if short not in want:
                    continue
                slot = stats.setdefault(short, {"defs": 0, "sink": 0, "mut": set()})
                slot["defs"] += 1
                body = clean[f0:f1]
                if DIRECT_RE.search(body):
                    slot["sink"] += 1
                for mm in MUT_RE.finditer(body):
                    if mm.group(1) in members:
                        slot["mut"].add(mm.group(1))
        return stats

    cache = {}
    todo = sorted({c for r in rows for c in r["calls"]} - set(cache))
    if todo:
        cache = resolve(todo)
    for r in rows:
        thru, mutthru = [], []
        for c in r["calls"]:
            s = cache.get(c)
            if not s or s["defs"] == 0 or s["defs"] > 12:
                continue
            if s["sink"] == s["defs"]:
                thru.append(c)
            if r["name"] in s["mut"]:
                mutthru.append(c)
        r["thru"] = thru
        r["mut_thru"] = mutthru
        if thru:
            counts["reentrant"] += 1

    rows.sort(key=lambda r: (-len(r["direct"]), -len(r["mut_thru"]), -len(r["thru"]), -len(r["cbish"] or []),
                            r["ekind"], r["file"]))
    print("EKINDS:", Counter(r["ekind"] for r in rows), file=sys.stderr)
    print("CBISH_ROWS", sum(1 for r in rows if r.get("cbish")), file=sys.stderr)
    print(json.dumps({"counts": counts, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
