#!/usr/bin/env python3
"""Whole-tree sweep for the `Vector<X*, N>` local shape (docs/78).

    python3 tools/vector-local-sweep.py > data/vector-local/inventory.json

Why this class: docs/77 closed the one raw-JSCell *member* shape, and the one `Vector<T*, N>` local it
found — `CloneSerializer::inputObjectStack` — is inert only because every pointee is separately rooted in
`m_objectPool`. The same shape *without* a separate root is a use-after-free: the 33rd entry moves the array
to the heap, where the conservative stack scan cannot see it, script runs inside the same frame (a getter, a
`resolve(`, an event dispatch, a JSC call, or any helper that does one of those), and a later `last()` /
`[i]` reads a pointer to an object script has freed.

The tool is a net, not a verdict. Two passes:

  PASS 1  every function body in `Source/WebCore` -> does it contain a *direct* script sink
          (`DISPATCH`), and only C++-level work (`QUIET`). This gives name -> has-sink, so a call from the
          interval can be resolved one level deep: `notifyObservers()` counts as a window because
          `notifyObservers` dispatches, even though the call site has no sink token.

  PASS 2  every local `Vector<X*, N>` / `Vector<X*>` / `FixedVector<X*, N>` / `Deque<X*>` (X not a keeping
          wrapper: `Ref`, `RefPtr`, `WeakPtr`, `unique_ptr`, `Strong`, `MarkedVector`) that is appended to
          inside a `for`/`while`/`do` body (so the count is not bounded by a literal) and read after the
          push. For each, the interval [first push, last read] is scanned for direct sinks and one-level
          sink-transitive callees.

X is resolved against every class declaration in both trees: `gc` = JSCell subclass, `node` = DOM
node/event/frame/style object, `ref` = RefCounted/CanMakeWeakPtr, `other` = not found, `primitive` = not a
class. A `ref`/`node` row is a bug only if the pointee can lose its last ref inside the window; a `gc` row
only if the pointee is not reachable from a stack root or a MarkedVector.
"""
import os, re, sys, json
from collections import Counter

TREES = [
    ("WebCore", "out/sony/full/WebKit-1400/WebKit-1400/Source/WebCore"),
    ("JSC", "out/sony/full/WebKit-1400/WebKit-1400/Source/JavaScriptCore"),
]
WEB_CORE = TREES[0][1]
BS = chr(92); DQ = chr(34); SQ = chr(39); NL = chr(10)

# Direct script sinks. Every family is already measured in this programme: dispatchEvent (docs/70/73),
# resolve(/reject( (docs/74), JSC::call and friends (docs/75), getProperty/getValue (docs/77 —
# PropertySlot::getValue calls an own getter), performMicrotaskCheckpoint + the parser entries (docs/71),
# custom element reactions (docs/75).
DISPATCH = [
    "dispatchEvent(", "resolve(", "reject(",
    "JSC::call(", "JSC::evaluate(", "JSC::construct(", "JSC::profiledCall(", "JSC::profiledEvaluate(",
    "JSExecState::call(", "JSExecState::evaluate(", "JSExecState::profiledCall(",
    "performMicrotaskCheckpoint(", "getProperty(", "getValue(", "getOwnPropertySlot(",
    "invokeCallback", "callFunctionOn(", "executeScript", "evaluateScript",
    "invokeCustomElementReaction", "runScriptsForPausedTreeBuilder(", "executePendingScript(",
    "loadModule(", "linkAndEvaluateModule(", "evaluateModule(", "reportException(",
]
# Tokens that make a `resolve(`/`getValue(` hit a false positive (parser/CSS/animation resolvers).
FALSE = ["CSSPropertyParser", "MediaQueryEvaluator", "ValueToColor", "StyleResolver", "resolveColor",
         "resolveLength", "resolveURI", "resolvePath"]

PUSHES = ["append", "uncheckedAppend", "appendWithCrashOnOverflow", "insert", "prepend", "appendVector"]
KEEPING_ELEM = ["Ref<", "RefPtr<", "WeakPtr<", "Weak<", "unique_ptr<", "UniqueRef<", "Strong<",
                "MarkedVector<", "MarkedArgumentBuffer", "GCReachableRef<", "CheckedRef<", "std::variant"]

CELL_ELEMS = {"JSValue", "JSCell", "JSObject", "JSString", "JSFunction", "JSArray", "JSGlobalObject"}
PRIMITIVES = {"char", "unsigned", "signed", "int", "short", "long", "uint8_t", "uint16_t", "uint32_t",
              "uint64_t", "int8_t", "int16_t", "int32_t", "int64_t", "size_t", "double", "float", "bool",
              "void", "UChar", "LChar", "AtomString", "String", "Identifier", "uintptr_t", "char16_t"}

KEYWORDS = {"if", "for", "while", "switch", "catch", "sizeof", "return", "do", "else", "decltype",
            "alignof", "static_assert", "requires", "co_return"}
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


def match_angle(clean, open_i):
    depth = 0; k = open_i; n = len(clean)
    while k < n:
        c = clean[k]
        if c == "<": depth += 1
        elif c == ">":
            depth -= 1
            if depth == 0: return k
        elif c in ";{":
            return -1
        k += 1
    return -1


def split_args(s):
    out = []; d = 0; cur = ""
    for ch in s:
        if ch in "<([": d += 1
        elif ch in ">)]": d -= 1
        if ch == "," and d == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip(): out.append(cur)
    return [x.strip() for x in out]


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
    while m > 0 and (clean[m].isalnum() or clean[m] in "_:~"): m -= 1
    name = clean[m + 1:e]
    if not name or name.split("::")[-1] in KEYWORDS: return None
    return name, m + 1


def functions(clean):
    out = []; i = 0; n = len(clean); depth = 0
    while i < n:
        c = clean[i]
        if c == "{":
            sig = signature_before(clean, i)
            if sig and depth <= 5:
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


def in_loop(clean, pos, floor):
    i = pos; depth = 0; hops = 0
    while i > floor and hops < 8:
        if clean[i] == "}": depth += 1
        elif clean[i] == "{":
            if depth == 0:
                hops += 1
                k = i - 1
                while k > floor and clean[k] in " \t\r\n": k -= 1
                if clean[k] == ")":
                    op = match_paren_back(clean, k)
                    if op > 0:
                        j = op - 1
                        while j > floor and clean[j] in " \t\r\n": j -= 1
                        e = j + 1
                        while j > floor and (clean[j].isalnum() or clean[j] == "_"): j -= 1
                        if clean[j + 1:e] in ("for", "while"):
                            return True, clean[j + 1:e]
                else:
                    j = k; e = j + 1
                    while j > floor and (clean[j].isalnum() or clean[j] == "_"): j -= 1
                    if clean[j + 1:e] == "do":
                        return True, "do"
            else:
                depth -= 1
        i -= 1
    return False, ""


def class_index():
    idx = {}
    for _tree, root in TREES:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".h"): continue
                path = os.path.join(dirpath, fn)
                try:
                    src = open(path, "r", errors="replace").read()
                except OSError:
                    continue
                clean = strip_comments_strings(src)
                for m in re.finditer(r"\b(class|struct)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(?::([^{;]*))?\{", clean):
                    name = m.group(2)
                    bases = " ".join((m.group(3) or "").split())
                    if name not in idx or (idx[name][1] == "" and bases):
                        idx[name] = (path.split("Source/", 1)[-1], bases, m.group(1))
    return idx


def base_names(bases):
    """Top-level base class identifiers out of a base-clause string."""
    out = []
    d = 0; cur = ""
    for ch in bases:
        if ch in "<(": d += 1
        elif ch in ">)": d -= 1
        if ch == "," and d == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip(): out.append(cur)
    names = []
    for part in out:
        part = re.sub(r"\b(public|private|protected|virtual)\b", " ", part)
        part = part.split("<")[0]
        part = " ".join(part.split())
        if not part: continue
        names.append(part.split("::")[-1])
    return names


def classify(elem, idx):
    base = re.sub(r"\b(const|volatile)\b", "", elem).replace("*", " ").strip()
    base = base.split("::")[-1]
    base = re.sub(r"<.*", "", base).strip()
    if base in PRIMITIVES:
        return base, "primitive", ""
    hit = idx.get(base)
    if not hit:
        return base, "unknown", ""
    # walk the base chain (BFS, depth 8): a DOM object's own base list rarely names the class that
    # proves its kind (`Element : public ContainerNode`, `RenderBox : public RenderBoxModelObject`).
    seen = set(); frontier = [base]; chain = []
    gc = node = ref = False
    while frontier and len(seen) < 64:
        cur = frontier.pop(0)
        if cur in seen: continue
        seen.add(cur)
        h = idx.get(cur)
        if not h: continue
        chain.append(cur)
        bl = h[1]
        if re.search(r"\b(JSCell|JSObject|JSValue|JSString|JSFunction|JSArray|JSGlobalObject)\b", bl): gc = True
        if re.search(r"\b(Node|Element|Document|Event|EventTarget|Frame|CSSValue|StyleRule|CSSRule|"
                     r"RenderObject|ScriptExecutionContext|StyleSheet|ContainerNode)\b", bl): node = True
        if re.search(r"\b(RefCounted|ThreadSafeRefCounted|CanMakeWeakPtr|AbstractRefCounted|"
                     r"RefCountedAndCanMakeWeakPtr)\b", bl): ref = True
        if len(chain) < 8:
            frontier.extend(base_names(bl))
    kind = "gc" if gc else ("node" if node else ("ref" if ref else "other"))
    return base, kind, " > ".join(chain[:6])


# Getter-capable calls: a `get` that can reach `PropertySlot::getValue` / a Proxy / a custom accessor. They are
# reported separately from DISPATCH because most `get()` calls in WebCore are C++ accessors, and because they are
# exactly the blind spot that hid the IDB row (JSObject::getIndex falls back to `get`, JSObject.h:409-414).
PROPERTY = ["getIndex(", "getProperty(", "getOwnPropertySlot(", "getOwnPropertySlotByIndex(",
            "getIfPropertyExists(", "getByIndex(", "->get(", ".get("]
PROP_RE = re.compile("|".join(sorted((re.escape(s) for s in PROPERTY), key=len, reverse=True)))
DIRECT_RE = re.compile("|".join(sorted((re.escape(s) for s in DISPATCH), key=len, reverse=True)))
CALL_RE = re.compile(r"(?<![\w:>])([A-Za-z_]\w*)\s*\(")


def main():
    idx = class_index()
    direct = {}          # func name -> sorted list of direct sink tokens
    files = []
    # ---------- pass 1: function -> direct sink ----------
    for dirpath, dirnames, filenames in os.walk(WEB_CORE):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fn in sorted(filenames):
            if not fn.endswith((".cpp", ".mm", ".h")): continue
            full = os.path.join(dirpath, fn)
            try:
                src = open(full, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            clean = strip_comments_strings(src)
            files.append((os.path.relpath(full, WEB_CORE), clean, functions(clean)))
            for name, f0, f1, _d in files[-1][2]:
                body = clean[f0:f1]
                hits = sorted({m.group(0)[:-1] for m in DIRECT_RE.finditer(body)})
                slot = direct.setdefault(name.split("::")[-1], [0, 0, set()])
                slot[0] += 1
                if hits:
                    slot[1] += 1
                    slot[2].update(hits)
    counts = {"files": len(files), "funcs_with_sink": len(direct), "decls": 0, "with_push": 0,
              "push_in_loop": 0, "with_read": 0, "with_window": 0}
    rows = []
    # ---------- pass 2: the vector rows ----------
    for rel, clean, funs in files:
        for m in re.finditer(r"(?<![\w:>])(Vector|FixedVector|Deque|ListHashSet)\s*<", clean):
            container = m.group(1)
            op = m.end() - 1
            cl = match_angle(clean, op)
            if cl < 0: continue
            args = split_args(clean[op + 1:cl])
            if not args: continue
            elem = args[0]
            cap = args[1] if len(args) > 1 and args[1].isdigit() else ("0" if len(args) < 2 else "?")
            if any(k in elem for k in KEEPING_ELEM): continue
            if "*" not in elem and container != "Deque" and elem.strip().split("::")[-1] not in CELL_ELEMS:
                continue
            dm = re.match(r"\s*(?:const\s+)?([A-Za-z_]\w*)\s*[;{(=,\[]", clean[cl + 1:cl + 160])
            if not dm: continue
            name = dm.group(1); pos = m.start()
            enc = None
            for f in funs:
                if f[1] <= pos < f[2] and (enc is None or (f[2] - f[1]) < (enc[2] - enc[1])):
                    enc = f
            if enc is None: continue
            fname, f0, f1 = enc[0], enc[1], enc[2]
            body = clean[f0:f1]
            counts["decls"] += 1
            npush = r"\b" + re.escape(name) + r"\s*(?:\.|->)\s*(?:" + "|".join(PUSHES) + r")\s*\("
            pushes = [f0 + pm.start() for pm in re.finditer(npush, body)]
            if not pushes: continue
            counts["with_push"] += 1
            looped, loopkw = False, ""
            for pp in pushes:
                ok, kw = in_loop(clean, pp, f0)
                if ok:
                    looped, loopkw = True, kw; break
            # Recursion counts as unbounded too (GOAL.md: "an unbounded loop or recursion pushes"):
            # IDBBindingUtilities::createIDBKeyFromValue appends outside its loop and grows by calling itself.
            if not looped:
                short = fname.split("::")[-1]
                if re.search(r"\b" + re.escape(short) + r"\s*\(", body[f0 - f0:]):
                    looped, loopkw = True, "recursion"
            if not looped: continue
            counts["push_in_loop"] += 1
            # reads after the first push
            readpat = (r"\b" + re.escape(name) + r"\s*(?:\.|->)\s*(?:last|at|first|begin|end|size|isEmpty|reverseBegin)\s*\("
                       r"|\b" + re.escape(name) + r"\s*\["
                       r"|:\s*" + re.escape(name) + r"\s*\)")
            reads = [f0 + rm.start() for rm in re.finditer(readpat, body) if f0 + rm.start() > min(pushes)]
            if reads: counts["with_read"] += 1
            lo, hi = min(pushes), (max(reads) if reads else f1)
            interval = clean[lo:hi]
            dhits = sorted({x.group(0)[:-1] for x in DIRECT_RE.finditer(interval)})
            phits = sorted({"get" if x.group(0) in ("->get(", ".get(") else x.group(0)[:-1]
                            for x in PROP_RE.finditer(interval)})
            calls = sorted({c.group(1) for c in CALL_RE.finditer(interval)})
            # one level deep, but only for names that are unambiguous: every definition of the name
            # dispatches, and the name is not a generic helper with dozens of definitions.
            thru = []
            for c in calls:
                slot = direct.get(c)
                if not slot: continue
                ndefs, nsink, toks = slot
                if ndefs <= 12 and nsink == ndefs:
                    thru.append(c)
            thru = sorted(set(thru))
            if dhits or thru:
                counts["with_window"] += 1
            # snapshot-callback loop: a for/while whose body reads the vector and calls a method on
            # the element — the docs/65 shape (`for (auto* client : clients) client->fontStateChanged()`).
            cb = []
            for lm in re.finditer(r"\bfor\s*\(([^)]{0,200})\)", clean[f0:f1]):
                head = lm.group(1)
                if name not in head: continue
                vs = re.search(r"([A-Za-z_]\w*)\s*(?:\*|&)?\s*(?::|,)", head)
                var = None
                hm = re.match(r"\s*(?:const\s+)?(?:auto|" + re.escape(elem.replace("*", "").strip()) + r")\s*[*&]?\s*([A-Za-z_]\w*)\s*:", head.replace(" ", " "))
                if hm: var = hm.group(1)
                else:
                    hm2 = re.search(r"([A-Za-z_]\w*)\s*:\s*" + re.escape(name) + r"\b", head)
                    var = hm2.group(1) if hm2 else None
                d = 1; k = f0 + lm.end(); nn = len(clean)
                while k < nn and d > 0:
                    if clean[k] == "{": d += 1
                    elif clean[k] == "}": d -= 1
                    k += 1
                body2 = clean[f0 + lm.end():k]
                meths = []
                if var:
                    for mm in re.finditer(r"\b" + re.escape(var) + r"\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*\(", body2):
                        if mm.group(1) not in meths: meths.append(mm.group(1))
                cb.append({"var": var, "methods": meths[:6]})
            eb, ekind, ebases = classify(elem, idx)
            rows.append({
                "file": "Source/WebCore/" + rel,
                "line": clean.count(NL, 0, pos) + 1,
                "func": fname,
                "func_line": clean.count(NL, 0, f0) + 1,
                "container": container,
                "elem": " ".join(elem.split()),
                "cap": cap,
                "name": name,
                "loop": loopkw,
                "pushes": len(pushes),
                "direct": dhits,
                "prop": phits,
                "thru": thru[:8],
                "interval": " ".join(clean[lo:hi].split())[:400],
                "reads": len(reads),
                "elem_base": eb,
                "elem_kind": ekind,
                "elem_bases": ebases[:140],
                "cb": cb[:3],
            })
    rows.sort(key=lambda r: (-len(r["direct"]), -len(r["thru"]), r["elem_kind"], r["file"]))
    print("KINDS:", Counter(r["elem_kind"] for r in rows), file=sys.stderr)
    print(json.dumps({"counts": counts, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
