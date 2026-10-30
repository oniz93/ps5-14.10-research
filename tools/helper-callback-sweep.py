#!/usr/bin/env python3
"""Whole-tree sweep for the *helper-template* shape (docs/80).

docs/79 closed both enumerable member shapes and named the hole in its own net: WebKit writes client iteration
as a helper template —

    template<typename T> void iterateClients(WeakHashSet<CSSFontFace::Client>& clients, T callback)
    {
        for (auto& client : copyToVectorOf<Ref<CSSFontFace::Client>>(clients))
            callback(client);
    }

so the member never appears in a range-for head at the call site: it is passed to a function whose body owns
the loop. A per-call-site sweep for `for (... : m_member)` cannot see it, and `iterateClients` is exactly
CVE-2026-43715's bug (docs/65).

Two passes:

  H. index every function definition in `Source/WebCore` whose body **iterates one parameter** and **calls
     another parameter** from inside that loop — the iterate-and-callback helper population. For each variant
     record the container parameter's declared type (element class), the callback parameter, whether the loop
     head snapshots (`copyToVectorOf<...>`, `copyToVector`, `WTF::map`), and the loop head itself.

  S. for each call to such a helper where the argument in the *iterated* position is a member container
     (`m_foo`, `this->m_foo`, `x->m_foo`), record the site, the callback body's first method call on the
     element, and decide the shape: `raw` (range-for directly over the argument) or `snapshot`.

    python3 tools/helper-callback-sweep.py > data/helper-callback/sites.json
"""
import os, re, sys, json, importlib.util
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("vls", os.path.join(HERE, "vector-local-sweep.py"))
vls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vls)

WEB_CORE = vls.WEB_CORE
strip = vls.strip_comments_strings
split_args = vls.split_args
functions = vls.functions
CALL_RE = vls.CALL_RE

MEMBER_EXPR = re.compile(r"^(?:this\s*->\s*)?(m_[A-Za-z_]\w*)$")
MEMBER_ANY = re.compile(r"(?:^|->|\.)(m_[A-Za-z_]\w*)$")
SNAPSHOT_RE = re.compile(
    r"copyToVectorOf\s*<|copyToVector\s*\(|WTF::map\s*\(|WTF::filter\s*\(|makeVector\s*\(|Vector<[^>]+>\s+\w+\s*[={]")
# A parameter that can be *called* — a lambda/function type, not a scalar accumulator. `combineSegmentsData(
# Vector<Segment>& segments, size_t& size)` is the false positive this removes.
CALLABLE_RE = re.compile(
    r"\b(?:Function|Callback|Handler|Functor|Visitor|Predicate|Task|CompletionHandler|MapFunction|"
    r"AnyOfFunction|AllOfFunction|MappedFunction)\b|^\s*(?:const\s+)?[A-Z]\w*\s*(?:&&|&)?\s*\w*$")
METHOD_HELPERS = ("forEach", "reverseForEach", "map", "forEachInContainer")
MEMBER_DECL = re.compile(
    r"\b(Vector|FixedVector|Deque|ListHashSet|HashSet|HashCountedSet|WeakHashSet|WeakHashMap|HashMap)"
    r"\s*<(.+?)>\s+(m_[A-Za-z_]\w*)\s*(?:;|\{|\[|=)")
CLIENT_NAME = re.compile(r"(?:Client|Observer|Listener|Delegate|Handler|Callback|Consumer|Provider)$")
ELEM_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*\(")
NON_SCRIPT_METHODS = {
    "size", "isEmpty", "isNull", "begin", "end", "get", "ptr", "data", "has", "contains", "remove", "add",
    "append", "clear", "lock", "unlock", "ref", "deref", "toString", "string", "name", "identifier", "type",
    "isValid", "operator", "toRawPtr", "releaseNonNull", "copyRef", "isHashTableDeletedValue", "isHashTableEmptyValue",
}


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def sig_text(clean, brace_i):
    """The declaration text in front of a `{` (back to the previous `{`, `}` or `;`)."""
    j = brace_i - 1
    while j > 0 and clean[j] not in "{};":
        j -= 1
    return clean[j + 1:brace_i]


def params_of(sig):
    """[(name, decl_text)] of a declaration (`template<class T> void f(Type& a, T b)`)."""
    k = sig.rstrip()
    while k and k[-1] != ")":
        k = k[:-1].rstrip()
    if not k:
        return []
    op = vls.match_paren_back(k, len(k) - 1)
    if op < 0:
        return []
    out = []
    for a in split_args(k[op + 1:-1]):
        a = a.strip()
        if not a:
            continue
        mm = re.search(r"([A-Za-z_]\w*)\s*(?:=\s*[^,]+)?$", a)
        if mm:
            out.append((mm.group(1), a))
    return out


def loop_heads(body):
    """[(head_text, start, end)] for every `for (...)` in a body."""
    out = []
    for fm in re.finditer(r"\bfor\s*\(", body):
        op = fm.end() - 1
        d = 1
        j = op + 1
        while j < len(body) and d > 0:
            if body[j] == "(":
                d += 1
            elif body[j] == ")":
                d -= 1
            j += 1
        head = body[op + 1:j - 1]
        # the loop body: from the next `{` to its match (or the single statement after `)`)
        k = j
        while k < len(body) and body[k] in " \t\r\n":
            k += 1
        if k < len(body) and body[k] == "{":
            d = 1
            e = k + 1
            while e < len(body) and d > 0:
                if body[e] == "{":
                    d += 1
                elif body[e] == "}":
                    d -= 1
                e += 1
            out.append((head, k, e))
        else:
            e = body.find("\n", k)
            out.append((head, k, len(body) if e < 0 else e))
    return out


def elem_of(decl):
    """Element type text of a container parameter declaration, e.g. `WeakHashSet<Foo::Client>&` -> `Foo::Client`."""
    m = re.search(r"<\s*(.+?)\s*>", decl)
    if m:
        return m.group(1)
    return None


def elem_class(elem):
    if not elem:
        return "unknown"
    if "RefPtr<" in elem:
        return "refptr"
    if re.search(r"(?:^|[\s,(])Ref<", elem):
        return "ref"
    if "WeakPtr<" in elem:
        return "weakptr"
    if "*" in elem:
        return "raw"
    return "value"


def collect_helpers(paths):
    """(helpers, defs).

    helpers: name -> [ {file,line,sig,params,iter_idx,cont_type,elem,cb_idx,snapshot,loop_head,body} ]
    defs:    name -> [ {file,line,sig,params,loop_over_param, calls_param_in_loop} ] — *every* definition,
             so a call site that does not resolve can be explained rather than dropped.
    """
    helpers = defaultdict(list)
    defs = defaultdict(list)
    for path in paths:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "for" not in src or "(" not in src:
            continue
        clean = strip(src)
        for name, a, b, depth in functions(clean):
            body = clean[a:b]
            sig = sig_text(clean, a).strip()
            if not sig or "(" not in sig:
                continue
            params = params_of(sig)
            if not params:
                continue
            heads = loop_heads(body)
            d = {
                "file": os.path.relpath(path, vls.TREES[0][0]), "line": line_of(clean, a),
                "sig": re.sub(r"\s+", " ", sig)[:200], "params": [p[0] for p in params],
                "loop_over_param": None, "calls_param_in_loop": None,
            }
            for idx, (pname, pdecl) in enumerate(params):
                for head, ls, le in heads:
                    # `for (auto& x : PARAM)` — the param must be the range expression
                    if ":" not in head:
                        continue
                    rng = head.split(":", 1)[1]
                    if not re.search(r"(?<![\w.>])" + re.escape(pname) + r"\b", rng):
                        continue
                    if d["loop_over_param"] is None:
                        d["loop_over_param"] = pname
                    member_read = None
                    mr = re.search(r"(?:^|[\s.(])" + re.escape(pname) + r"\s*(?:->|\.)\s*(m_[A-Za-z_]\w*)", rng)
                    if mr:
                        member_read = mr.group(1)
                    inner = body[ls:le]
                    cb = None
                    for jdx, (cname, cdecl) in enumerate(params):
                        if jdx == idx:
                            continue
                        if not CALLABLE_RE.search(cdecl):
                            continue
                        if re.search(r"(?<![\w.])" + re.escape(cname) + r"\s*\(", inner):
                            cb = jdx
                            break
                    if cb is None:
                        continue
                    if d["calls_param_in_loop"] is None:
                        d["calls_param_in_loop"] = params[cb][0]
                    helpers[name].append({
                        "file": os.path.relpath(path, vls.TREES[0][0]),
                        "line": line_of(clean, a),
                        "sig": re.sub(r"\s+", " ", sig)[:200],
                        "params": [p[0] for p in params],
                        "iter_idx": idx,
                        "cont_type": pdecl,
                        "cont_member": member_read,
                        "elem": elem_of(pdecl),
                        "cb_idx": cb,
                        "cb_param": params[cb][0],
                        "snapshot": bool(SNAPSHOT_RE.search(head)),
                        "loop_head": re.sub(r"\s+", " ", head).strip()[:160],
                        "body_excerpt": re.sub(r"\s+", " ", inner).strip()[:200],
                    })
                    break
            defs[name].append(d)
    return helpers, defs


CALL_SITE_RE = re.compile(r"(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)\s*\(")


def find_sites(paths, helpers):
    sites = []
    for path in paths:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if not any(n in src for n in helpers):
            continue
        clean = strip(src)
        for m in CALL_SITE_RE.finditer(clean):
            name = m.group(1)
            if name not in helpers:
                continue
            op = clean.find("(", m.start())
            if op < 0:
                continue
            d = 1
            j = op + 1
            n = len(clean)
            while j < n and d > 0:
                c = clean[j]
                if c == "(":
                    d += 1
                elif c == ")":
                    d -= 1
                j += 1
            args = split_args(clean[op + 1:j - 1])
            for hv in helpers[name]:
                ai = hv["iter_idx"]
                if ai >= len(args):
                    continue
                a0 = args[ai].strip()
                mm = MEMBER_EXPR.match(a0) or MEMBER_ANY.search(a0)
                owner = False
                if not mm:
                    # `helper(*this, [&](auto& c) { ... })` — the helper iterates `parameter.m_member`, so the
                    # container never appears at the call site. Only meaningful when the helper's loop head
                    # names a member of the parameter.
                    if re.match(r"^(?:\*|&)?\s*(?:this|self|protectedThis|owner|object)$", a0) and hv.get("cont_member"):
                        owner = True
                        mm = None
                    else:
                        continue
                cb = None
                if hv["cb_idx"] < len(args):
                    cb = args[hv["cb_idx"]].strip()
                sites.append({
                    "shape_owner": owner,
                    "file": os.path.relpath(path, vls.TREES[0][0]),
                    "line": line_of(clean, m.start()),
                    "helper": name,
                    "helper_file": hv["file"],
                    "helper_line": hv["line"],
                    "container": mm.group(1) if mm else hv.get("cont_member"),
                    "container_expr": a0[:80],
                    "cont_type": hv["cont_type"],
                    "elem": hv["elem"],
                    "elem_class": elem_class(hv["elem"]),
                    "client_shaped": bool(hv["elem"] and CLIENT_NAME.search(hv["elem"].split("::")[-1].strip())),
                    "snapshot": hv["snapshot"],
                    "loop_head": hv["loop_head"],
                    "callback": cb[:400] if cb else None,
                    "nargs": len(args),
                })
                break
    return sites


def build_member_index(paths):
    """member name -> [(kind, elem, file)] over the whole tree. Members are declared in headers, so a per-file
    lookup misses almost all of them (`docs/79` recorded the same name-join caveat)."""
    idx = defaultdict(list)
    for path in paths:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "m_" not in src:
            continue
        clean = strip(src)
        for dm in MEMBER_DECL.finditer(clean):
            idx[dm.group(3)].append((dm.group(1), dm.group(2).strip()[:70], os.path.relpath(path, vls.TREES[0][0])))
    return idx


def resolve_member(member_index, member, use_file):
    """Pick the declaration most likely to belong to `use_file`: same stem, then same directory, then any."""
    cands = member_index.get(member, [])
    if not cands:
        return ("?", "")
    stem = os.path.splitext(os.path.basename(use_file))[0]
    d = os.path.dirname(use_file)

    def score(c):
        f = c[2]
        s = 0
        if os.path.splitext(os.path.basename(f))[0] == stem:
            s += 3
        if os.path.dirname(f) == d:
            s += 2
        return s
    best = max(cands, key=score)
    return (best[0], best[1])


def method_sites(paths, member_index):
    """`m_member.<forEach|map|...>(lambda)` — the same shape written as a method call on the member, where the
    call site's receiver (not an argument) is the container."""
    hits = []
    for path in paths:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "m_" not in src or "[" not in src:
            continue
        clean = strip(src)
        rel = os.path.relpath(path, vls.TREES[0][0])
        for hm in re.finditer(r"\b(m_[A-Za-z_]\w*)\s*\.\s*(" + "|".join(METHOD_HELPERS) + r")\s*\(", clean):
            member, meth = hm.group(1), hm.group(2)
            op = clean.find("(", hm.end() - 1)
            d = 1
            j = op + 1
            n = len(clean)
            while j < n and d > 0:
                c = clean[j]
                if c == "(":
                    d += 1
                elif c == ")":
                    d -= 1
                j += 1
            args = split_args(clean[op + 1:j - 1])
            if not args or not args[0].strip().startswith("["):
                continue
            kind, elem = resolve_member(member_index, member, rel)
            hits.append({
                "file": rel,
                "line": line_of(clean, hm.start()),
                "member": member, "method": meth,
                "container_kind": kind, "elem": elem,
                "callback": args[0].strip()[:300],
                "callback_calls": [m.group(1) + "." + m.group(2) for m in ELEM_CALL.finditer(args[0])
                                   if m.group(2) not in NON_SCRIPT_METHODS][:4],
            })
    return hits


def main():
    source = os.path.dirname(WEB_CORE)  # .../Source
    paths = []
    for dirpath, dirnames, filenames in os.walk(WEB_CORE):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fn in sorted(filenames):
            if fn.endswith((".cpp", ".mm", ".h")):
                paths.append(os.path.join(dirpath, fn))
    # The helper itself may live outside WebCore: `WTF::anyOf`/`map`/`compactMap` are in
    # Source/WTF/wtf/Algorithms.h, and that is where 9 of the 22 helper names in the call-site
    # population are defined. Index helpers over Source/WTF + Source/WebCore.
    helper_paths = list(paths)
    for extra in ("WTF", "WebCore"):
        base = os.path.join(source, extra)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d != ".git")
            for fn in sorted(filenames):
                if fn.endswith((".h", ".cpp", ".mm")):
                    p = os.path.join(dirpath, fn)
                    if p not in helper_paths:
                        helper_paths.append(p)
    sys.stderr.write("files: %d (helper index: %d)\n" % (len(paths), len(helper_paths)))

    helpers, defs = collect_helpers(helper_paths)
    sys.stderr.write("helpers: %d names, %d variants (iterate-param + call-param inside the loop)\n" %
                     (len(helpers), sum(len(v) for v in helpers.values())))

    sites = find_sites(paths, helpers)
    sys.stderr.write("sites (member in the iterated position): %d\n" % len(sites))

    for s in sites:
        hits = []
        if s["callback"]:
            for m in ELEM_CALL.finditer(s["callback"]):
                if m.group(2) in NON_SCRIPT_METHODS:
                    continue
                hits.append(m.group(1) + "." + m.group(2))
        s["callback_calls"] = hits[:4]
        s["shape"] = "snapshot" if s["snapshot"] else "raw"

    member_index = build_member_index(paths)
    sys.stderr.write("member declarations indexed: %d names\n" % len(member_index))
    for s_ in sites:
        kind, elem = resolve_member(member_index, s_["container"], s_["file"])
        s_["site_container_kind"] = kind
        s_["site_elem"] = elem
        s_["site_elem_class"] = elem_class(elem)
    msites = method_sites(paths, member_index)
    sys.stderr.write("method-helper sites (m_x.<forEach|map>(lambda)): %d\n" % len(msites))

    # Per-name accounting for *every* helper name that a `helper(member, [...]` call site mentions, so the
    # names outside the iterate-and-callback population are explained, not silently dropped.
    label = re.compile(r"\b([A-Za-z_]\w*)\s*\(\s*(?:this\s*->\s*)?m_[A-Za-z_]\w*\s*,\s*\[")
    name_sites = Counter()
    name_example = {}
    for p in paths:
        try:
            src = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "m_" not in src or "[" not in src:
            continue
        clean = strip(src)
        for m in label.finditer(clean):
            n = m.group(1)
            name_sites[n] += 1
            name_example.setdefault(n, os.path.relpath(p, vls.TREES[0][0]) + ":" + str(line_of(clean, m.start())))
    acct = []
    for n, cnt in name_sites.most_common():
        ds = defs.get(n, [])
        acct.append({
            "name": n, "sites": cnt, "example": name_example[n], "defs": len(ds),
            "defs_iterating_a_param": len([d for d in ds if d["loop_over_param"]]),
            "defs_calling_a_param_in_that_loop": len([d for d in ds if d["calls_param_in_loop"]]),
            "resolved_variants": len(helpers.get(n, [])),
            "first_def": ds[0]["file"] + ":" + str(ds[0]["line"]) if ds else None,
        })
    sys.stderr.write("syntactic helper(member, lambda) sites: %d across %d names\n" %
                     (sum(name_sites.values()), len(name_sites)))

    print(json.dumps({
        "helpers": {k: v for k, v in sorted(helpers.items())},
        "sites": sites,
        "method_sites": msites,
        "name_accounting": acct,
        "n_sites": len(sites),
        "n_method_sites": len(msites),
        "n_helpers": len(helpers),
        "n_syntactic_sites": sum(name_sites.values()),
    }, indent=1))

    c = Counter(s["shape"] for s in sites)
    sys.stderr.write("shapes: %s\n" % dict(c))
    raws = [s for s in sites if s["shape"] == "raw"]
    sys.stderr.write("raw sites: %d, distinct containers %d, client-shaped %d\n" %
                     (len(raws), len({s["container"] for s in raws}),
                      len([s for s in raws if s["client_shaped"]])))
    cc = Counter((s["helper"], s["shape"]) for s in sites)
    for k, v in cc.most_common(30):
        sys.stderr.write("  %-40s %-9s %d\n" % (k[0], k[1], v))


if __name__ == "__main__":
    main()
