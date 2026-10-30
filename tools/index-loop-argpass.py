#!/usr/bin/env python3
"""The argument-passing spelling of "the container shrinks under the loop" (docs/83).

    python3 tools/index-loop-argpass.py > data/index-loop/argpass.json

docs/79-docs/82 read mutation in the loop body only: `container.remove(...)` written there
(docs/81) or a same-named member mutated inside a callee body (docs/82's `mutator_in_route`,
empty for all 310 owner rows). The spelling none of them can see is the container leaving the
frame **as an argument**: a callee that takes it by non-const reference and removes from the
parameter shrinks the loop's container without ever naming it in the body.

This tool takes the 310 owner-container loops of data/index-loop/loops.json (container types as
resolved by docs/82 in resolve.json) and:

  1. finds every call in the loop body and every argument position, matching the container
     expression in the spellings that pass a handle: bare, `this->`, `&`, `*ptr`, `WTFMove(`,
     `std::move(`, `WTF::move(`, `std::exchange(`; plus any local alias of it (`auto& v = m_foo`)
     declared in the enclosing function. Element expressions (`m_foo[i]`, `.at(i)`, `.size()`,
     `.begin()`, `.data()`) are counted separately — they do not pass the container;
  2. resolves each callee that does pass it through the receiver-typed index of
     tools/index-loop-resolve.py (static `Cls::m`, `recv.m`/`recv->m` by receiver type, bare name
     through the owning class, then the base chain), parses the callee's parameters, and asks
     whether the parameter at that position is a non-const reference/pointer (a value or const&
     parameter cannot shrink the caller's container) and whether the body mutates it;
  3. the depth-2 spelling docs/82 misses, and only for callees of the *same class or a base* (so
     `m_<name>` is the same object, not a name collision): inside the callee body, the member is
     handed as an argument again and *that* callee mutates its parameter; plus the
     `owner->m_foo.remove()` receiver spelling, which docs/82's `(this->)?m_<name>` cannot see;
  4. two sensitivity controls: the same matcher over all 1,261 loops (local containers do get
     passed), and the known helper idiom `iterateClients(m_clients, …)` of docs/80, which the
     argument matcher must find.

JSON on stdout, funnel on stderr. Every depth-2 row is a candidate and is read in source before
docs/83 records it.
"""
import os, re, sys, json, importlib.util
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("vls", os.path.join(HERE, "vector-local-sweep.py"))
vls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vls)
_spec2 = importlib.util.spec_from_file_location("ilr", os.path.join(HERE, "index-loop-resolve.py"))
ilr = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(ilr)

strip = vls.strip_comments_strings
split_args = vls.split_args
match_paren_fwd = vls.match_paren_fwd
signature_before = vls.signature_before

MUTATORS = ("clear", "remove", "removeAt", "removeAll", "removeAllMatching", "removeFirst",
            "removeFirstMatching", "removeLast", "removeIf", "takeFirst", "takeLast", "take",
            "shrink", "shrinkToFit", "resize", "truncate", "pop_back", "pop_front", "erase",
            "swap", "reverse", "sort", "fill")
MUT_RE = "|".join(MUTATORS)
CONTROL_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "catch", "do", "else",
                    "ASSERT", "ASSERT_NOT_REACHED", "RELEASE_ASSERT", "UNUSED_PARAM",
                    "dynamic_cast", "static_cast", "reinterpret_cast", "const_cast", "decltype",
                    "WTFMove", "std::move", "WTF::move", "std::exchange", "WTF::exchange",
                    "std::size", "std::begin", "std::end", "std::data", "std::as_const",
                    "WTF::asConst", "ASSERT_WITH_MESSAGE", "RELEASE_ASSERT_WITH_MESSAGE",
                    "WTFLogAlways", "RELEASE_LOG", "RELEASE_LOG_ERROR", "RELEASE_LOG_INFO"}
WRAPS = ("WTFMove(", "std::move(", "WTF::move(", "std::exchange(", "std::as_const(", "WTF::asConst(")


def norm(s):
    s = " ".join((s or "").split())
    return re.sub(r"\s*(->|\.|::)\s*", r"\1", s)


def strip_wrap(s):
    """`WTFMove(m_foo)` -> (`m_foo`, 'WTFMove'); parentheses are peeled first."""
    s = (s or "").strip()
    while s.startswith("(") and s.endswith(")") and match_paren_fwd(s, 0) == len(s) - 1:
        s = s[1:-1].strip()
    for w in WRAPS:
        if s.startswith(w) and s.endswith(")") and match_paren_fwd(s, len(w) - 1) == len(s) - 1:
            inner = s[len(w):-1]
            if w.startswith("std::exchange"):
                parts = split_args(inner)
                inner = parts[0] if parts else inner
            return inner.strip(), w[:-1]
    return s, ""


def call_sites(body):
    """[(callee, start, args)] for every `f(...)` in `body`, nested calls included."""
    out = []
    for m in re.finditer(r"\(", body):
        op = m.start()
        j = op - 1
        while j >= 0 and body[j] in " \t\r\n":
            j -= 1
        e = j + 1
        while j >= 0 and (body[j].isalnum() or body[j] in "_:"):
            j -= 1
        while True:                                  # one `->`/`.` chain backwards
            k2 = j
            while k2 >= 0 and body[k2] in " \t\r\n":
                k2 -= 1
            if k2 >= 1 and body[k2] == ">" and body[k2 - 1] == "-":
                j = k2 - 2
            elif k2 >= 0 and body[k2] == ".":
                j = k2 - 1
            else:
                break
            while j >= 0 and body[j] in " \t\r\n":
                j -= 1
            while j >= 0 and (body[j].isalnum() or body[j] in "_:"):
                j -= 1
        callee = body[j + 1:e]
        if not callee:
            continue
        cp = match_paren_fwd(body, op)
        if cp < 0:
            continue
        out.append((callee, op, split_args(body[op + 1:cp])))
    return out


def line_starts(text):
    out = [0]
    for i, c in enumerate(text):
        if c == "\n":
            out.append(i + 1)
    return out


def find_loop_body(clean, line, starts):
    pos = starts[line - 1] if line - 1 < len(starts) else 0
    m = re.compile(r"\bfor\s*\(").search(clean, pos)
    if not m:
        return None
    rp = match_paren_fwd(clean, m.end() - 1)
    if rp < 0:
        return None
    k = rp + 1
    while k < len(clean) and clean[k] in " \t\r\n":
        k += 1
    if k < len(clean) and clean[k] == "{":
        d, j = 1, k + 1
        while j < len(clean) and d > 0:
            if clean[j] == "{":
                d += 1
            elif clean[j] == "}":
                d -= 1
            j += 1
        return k, clean[k:j], clean[m.start():k]
    j = clean.find(";", k)
    if j < 0:
        return None
    return k, clean[k:j + 1], clean[m.start():k]


def aliases_of(clean, f0, f1, cexpr):
    """Locals of the enclosing function that name the container: name -> ref|ptr|moved|value.

    The type and the name must be separated by whitespace: with `\\s*` between them an
    identifier could be split into a fake type and a one-letter name — `m_currentCharacter =
    *m_currentSubstring.currentCharacter8;` parses as type `m_currentCharacte`, name `r`, which is
    how the first version of this function reported two aliases in SegmentedString.h that do not
    exist (docs/83 §7).
    """
    out = {}
    seg = clean[f0:f1]
    for m in re.finditer(r"(?<![$\w])(?:auto|[A-Za-z_][\w:]*(?:\s*<[^;{}]{0,120}>)?)\s*(&&|&|\*)?\s+"
                         r"([A-Za-z_]\w*)\s*=\s*([^;]{1,200});", seg):
        kind, name, rhs = m.group(1), m.group(2), norm(m.group(3))
        core, wrap = strip_wrap(rhs)
        core = core.lstrip("&*").strip()
        if core not in (cexpr, "this->" + cexpr):
            continue
        if kind in ("&", "&&"):
            out[name] = "ref"
        elif kind == "*" or rhs.startswith("&"):
            out[name] = "ptr"
        elif wrap:
            out[name] = "moved"
        else:
            out[name] = "value"
    return out


def params_of(R, rel, f0):
    """[(type, name, kind)] for the definition whose opening brace is at f0."""
    clean = R.clean_of(rel)
    sig = signature_before(clean, f0)
    if not sig:
        return []
    op = clean.find("(", sig[1])
    if op < 0:
        return []
    cp = match_paren_fwd(clean, op)
    if cp < 0:
        return []
    out = []
    for p in split_args(clean[op + 1:cp]):
        p = p.split("=")[0].strip()
        if not p or p == "void":
            continue
        m = re.search(r"([A-Za-z_]\w*)\s*$", p)
        if not m:
            out.append((" ".join(p.split()), "", "value"))
            continue
        name = m.group(1)
        ty = " ".join(p[:m.start()].split())
        if ty.endswith("&&") or ty.endswith("&"):
            kind = "ref"
        elif "*" in ty:
            kind = "ptr"
        else:
            kind = "value"
        if re.search(r"(^|\s|<)const(\s|>|$)", ty) and kind == "ref":
            kind = "constref"
        out.append((ty, name, kind))
    return out


def mutated_params(body, pname):
    if not pname:
        return []
    p = re.escape(pname)
    hits = set()
    for m in re.finditer(r"(?<![\w.>])(?:\*\s*)?%s\s*(?:->|\.)\s*(%s)\s*\(" % (p, MUT_RE), body):
        hits.add("%s.%s()" % (pname, m.group(1).split(".")[-1]))
    for m in re.finditer(r"(?<![\w.>])%s\s*=\s*(?:WTFMove|std::move|WTF::move|Vector|HashMap|HashSet|\{\})" % p, body):
        hits.add("%s = <new container>" % pname)
    for m in re.finditer(r"\b(?:WTFMove|std::move|WTF::move)\s*\(\s*%s\s*\)" % p, body):
        hits.add("%s moved" % pname)
    return sorted(hits)


def match_handle(arg, cexpr, root, aliases):
    """(matched, how) for one argument expression. Element expressions never match."""
    core, wrap = strip_wrap(arg)
    core_n = norm(core)
    pre = ""
    while core_n[:1] in ("&", "*"):
        pre += core_n[0]
        core_n = core_n[1:].strip()
    if core_n in ("this->" + cexpr, cexpr):
        return True, "handle" + ("<" + wrap + ">" if wrap else "") + pre
    if core_n in aliases:
        return True, "alias:%s(%s)%s" % (core_n, aliases[core_n], pre)
    return False, ""


def mention_kind(arg, root):
    a = norm(arg)
    if not re.search(r"(?<![\w.>])%s\s*[\[\.]" % re.escape(root), a):
        return ""
    for key, label in ((".isEmpty(", "isEmpty"), (".at(", "element-at"), (".size(", "size"),
                       (".begin(", "begin"), (".end(", "end"), (".data(", "data"),
                       (".first(", "first"), (".last(", "last"), ("[", "element-index")):
        if key in a:
            return label
    return "other"


class Index:
    def __init__(self):
        self.R = ilr.Resolver()
        self.R.scan()

    def bodies_for(self, cls, method):
        out, seen, frontier = [], set(), [cls]
        while frontier and len(seen) < 64:
            c = frontier.pop(0)
            if not c or c in seen:
                continue
            seen.add(c)
            out.extend(self.R.methods.get((c, method), ()))
            h = self.R.cls_idx.get(c)
            if h:
                frontier.extend(vls.base_names(h[1]))
        return out

    def is_same_object_class(self, a, b):
        """True if `a` is `b`, or `b` is a base of `a` (so `m_<name>` is the same member)."""
        if not a or not b:
            return False
        if a == b:
            return True
        seen, frontier = set(), [a]
        while frontier and len(seen) < 64:
            c = frontier.pop(0)
            if c in seen:
                continue
            seen.add(c)
            h = self.R.cls_idx.get(c)
            if h:
                bases = vls.base_names(h[1])
                if b in bases:
                    return True
                frontier.extend(bases)
        return False

    def callee_bodies(self, clean, b0, pos, callee, cls, elem_locals):
        name = callee.split("::")[-1]
        out = []
        m = re.match(r"^([A-Z][\w]*)::([A-Za-z_]\w*)$", callee)
        if m and m.group(1) in self.R.cls_idx:
            for rel, f0, f1 in self.bodies_for(m.group(1), name):
                out.append(("static", m.group(1), name, rel, f0, f1))
            return out
        m = re.match(r"^(.*?)(?:->|\.)\s*([A-Za-z_]\w*)$", callee)
        if m:
            ric, meth = m.group(1), m.group(2)
            rc = elem_locals.get(ric) or self.R.recv_cls(ric, clean, 0, b0 + pos, cls)
            if rc:
                rc = ilr.strip_template(rc)
                for rel, f0, f1 in self.bodies_for(rc, meth):
                    out.append(("recv:" + rc, rc, meth, rel, f0, f1))
            return out
        if re.fullmatch(r"[A-Za-z_]\w*", callee):
            for rel, f0, f1 in self.bodies_for(cls, name):
                out.append(("bare-own", cls, name, rel, f0, f1))
            if not out:
                b = self.R.bare.get(name, ())
                if len(b) == 1 and b[0][0]:
                    out.append(("bare-unique", b[0][0], name, b[0][1], b[0][2], b[0][3]))
        return out


def sweep_body(I, rel, clean, b0, body, cls, cexpr, aliases, depth, path):
    """Argument-passing sites of `cexpr` in one body, with the callee's parameter analysed."""
    R = I.R
    root = cexpr.split(".")[-1].split("->")[-1]
    elem_locals = {}
    for m in re.finditer(r"\b(?:auto|const\s+auto)\s*(&{0,2})\s*([A-Za-z_]\w*)\s*=\s*"
                         r"(?<![\w.>])%s\s*(?:\[|\.at\s*\()" % re.escape(cexpr), body):
        elem_locals[m.group(2)] = "element"
    out = []
    for callee, pos, args in call_sites(body):
        if callee.split("::")[-1] in CONTROL_KEYWORDS:
            continue
        for i, a in enumerate(args):
            hit, how = match_handle(a, cexpr, root, aliases)
            if not hit:
                if depth == 0:
                    k = mention_kind(a, root)
                    if k:
                        out.append({"mention": k, "arg": norm(a)[:80], "callee": callee})
                continue
            rec = {"depth": depth, "file": rel, "path": path + [callee], "container": cexpr,
                   "callee": callee, "arg_index": i, "arg": norm(a)[:120], "how": how,
                   "callees": []}
            for kind, ccls, meth, crel, cf0, cf1 in I.callee_bodies(clean, b0, pos, callee, cls, elem_locals):
                params = params_of(R, crel, cf0)
                pty, pname, pkind = (params[i] if i < len(params) else ("", "", "?"))
                cbody = R.clean_of(crel)[cf0:cf1]
                rec["callees"].append({
                    "kind": kind, "class": ccls, "method": meth, "at": "%s:%d" % (crel, cf0),
                    "nparams": len(params), "param": pname, "param_type": pty, "param_kind": pkind,
                    "mutators": mutated_params(cbody, pname),
                    "same_object_class": I.is_same_object_class(ccls, cls),
                    "_rel": crel, "_f0": cf0, "_f1": cf1})
            out.append(rec)
    return out


def main():
    base = os.path.join(HERE, os.pardir, "data", "index-loop")
    loops = json.load(open(os.path.join(base, "loops.json")))["rows"]
    owner = json.load(open(os.path.join(base, "resolve.json")))["rows"]
    I = Index()
    R = I.R

    counts = Counter()
    mentions = Counter()
    sites = []
    depth2 = []
    member_in_callee = []
    alias_rows = []
    total_calls = 0
    total_args = 0
    not_found = []

    def context(row):
        rel = row["file"]
        clean = R.clean_of(rel)
        lb = find_loop_body(clean, row["line"], line_starts(clean))
        if not lb:
            return None
        b0, body, _h = lb
        cls = row["class"]
        if cls in ("", "?", "template"):
            cls = R.enclosing_class(rel, b0) or R.class_from_context(clean, b0)
        cexpr = norm(row["container"])
        f = None
        for name, f0, f1, _d in R.file_funcs.get(rel, ()):
            if f0 <= b0 < f1 and (f is None or f0 > f[1]):
                f = (name, f0, f1)
        aliases = aliases_of(clean, f[1], f[2], cexpr) if f else {}
        return rel, clean, b0, body, cls, cexpr, aliases

    for row in owner:
        ctx = context(row)
        if not ctx:
            counts["loop-not-found"] += 1
            not_found.append([row["file"], row["line"]])
            continue
        rel, clean, b0, body, cls, cexpr, aliases = ctx
        if aliases:
            muts = []
            for nm in aliases:
                for m in re.finditer(r"(?<![\w.>])%s\s*(?:->|\.)\s*(%s)\s*\(" % (re.escape(nm), MUT_RE), body):
                    muts.append("%s.%s()" % (nm, m.group(1)))
            alias_rows.append({"file": rel, "line": row["line"], "container": row["container"],
                               "aliases": aliases, "mutator_via_alias_in_body": sorted(set(muts))})
            if muts:
                counts["alias-mutator-in-body"] += 1
        body_sites = sweep_body(I, rel, clean, b0, body, cls, cexpr, aliases, 0, [])
        total_calls += len([c for c in call_sites(body) if c[0].split("::")[-1] not in CONTROL_KEYWORDS])
        total_args += len([a for c in call_sites(body) if c[0].split("::")[-1] not in CONTROL_KEYWORDS
                           for a in c[2]])
        for s in body_sites:
            if "mention" in s:
                mentions[s["mention"]] += 1
                continue
            s.update({"line": row["line"], "function": row["function"], "row_class": cls,
                      "container_type": row["container_type_after"],
                      "window_before": row["window_before"], "verdict_before": row["verdict_before"]})
            sites.append(s)

    # ---- every call in the 310 bodies, resolved, then read for the two callee-side spellings ---
    # (a) widened `mutator_in_route`: docs/82 looked for `(this->)?m_<name>.<mut>`; any receiver
    #     spelling (`self.m_foo.remove()`, `owner->m_foo.clear()`) is the same mutation and is
    #     invisible to that pattern.  (b) depth-2 argument passing: the member handed on as an
    #     argument *inside* the callee body, to a further callee that mutates its parameter.
    callee_calls = 0
    callee_resolved = 0
    unresolved_callees = Counter()
    growth_in_callee = []
    member_arg_in_callee = []
    callee_body_bytes = []
    root_in_callee = 0
    root_in_callee_samples = []
    GROW_RE = ("append", "uncheckedAppend", "appendVector", "appendWithCrashOnOverflow", "insert",
               "prepend", "add", "addAll", "set")
    for row in owner:
        ctx = context(row)
        if not ctx:
            continue
        rel, clean, b0, body, cls, cexpr, aliases = ctx
        root = cexpr.split(".")[-1].split("->")[-1]
        if not root.startswith("m_"):
            counts["container-not-a-member"] += 1
            continue
        pat_mut = re.compile(r"(?<![\w.>])(?:([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*(?:->|\.)\s*)?"
                             r"%s\s*(?:->|\.)\s*(%s)\s*\(" % (re.escape(root), MUT_RE))
        for callee, pos, args in call_sites(body):
            if callee.split("::")[-1] in CONTROL_KEYWORDS:
                continue
            callee_calls += 1
            bodies = I.callee_bodies(clean, b0, pos, callee, cls, {})
            if not bodies:
                unresolved_callees[callee.split("::")[-1]] += 1
                continue
            callee_resolved += 1
            for kind, ccls, meth, crel, cf0, cf1 in bodies:
                cclean = R.clean_of(crel)
                cbody = cclean[cf0:cf1]
                callee_body_bytes.append(len(cbody))
                if root in cbody:
                    root_in_callee += 1
                    if len(root_in_callee_samples) < 12:
                        i0 = cbody.find(root)
                        root_in_callee_samples.append({
                            "callee": "%s::%s" % (ccls, meth), "file": rel, "line": row["line"],
                            "container": row["container"], "call": callee,
                            "ctx": re.sub(r"\s+", " ", cbody[max(0, i0 - 60):i0 + 70])})
                for m in pat_mut.finditer(cbody):
                    member_in_callee.append({
                        "file": rel, "line": row["line"], "function": row["function"],
                        "call": callee, "callee": "%s::%s" % (ccls, meth),
                        "container": row["container"], "container_type": row["container_type_after"],
                        "receiver": m.group(1) or "(implicit this)",
                        "mutator": "%s.%s()" % (root, m.group(2)),
                        "same_object_class": I.is_same_object_class(ccls, cls),
                        "window_before": row["window_before"], "verdict_before": row["verdict_before"]})
                # control: the same walk with growth verbs — proves body slicing + regex plumbing
                pat_grow = re.compile(r"(?<![\w.>])(?:([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*(?:->|\.)\s*)?"
                                      r"%s\s*(?:->|\.)\s*(%s)\s*\(" % (re.escape(root), "|".join(GROW_RE)))
                for m in pat_grow.finditer(cbody):
                    if len(growth_in_callee) < 40:
                        growth_in_callee.append({"call": callee, "callee": "%s::%s" % (ccls, meth),
                                                 "receiver": m.group(1) or "(implicit this)",
                                                 "verb": m.group(2), "file": rel, "line": row["line"]})
                for callee2, pos2, args2 in call_sites(cbody):
                    if callee2.split("::")[-1] in CONTROL_KEYWORDS:
                        continue
                    for i, a in enumerate(args2):
                        hit, how = match_handle(a, cexpr, root, aliases)
                        if not hit:
                            continue
                        if len(member_arg_in_callee) < 40:
                            member_arg_in_callee.append({"callee": "%s::%s" % (ccls, meth), "call": callee2,
                                                         "arg": norm(a)[:90], "how": how,
                                                         "file": rel, "line": row["line"]})
                        for k2, c2, m2, r2, f2, g2 in I.callee_bodies(cclean, cf0, pos2, callee2, ccls, {}):
                            params = params_of(R, r2, f2)
                            pty, pname, pkind = (params[i] if i < len(params) else ("", "", "?"))
                            depth2.append({
                                "file": rel, "line": row["line"], "function": row["function"],
                                "container": row["container"], "container_type": row["container_type_after"],
                                "via": "%s::%s" % (ccls, meth), "callee": callee2, "arg_index": i,
                                "arg": norm(a)[:120], "how": how, "param": pname,
                                "param_type": pty, "param_kind": pkind,
                                "mutators": mutated_params(R.clean_of(r2)[f2:g2], pname),
                                "same_object_class": I.is_same_object_class(c2, cls),
                                "window_before": row["window_before"], "verdict_before": row["verdict_before"]})

    # ---- control 1: the same matcher over all 1,261 loops -------------------------------------
    ctrl_hits, ctrl_calls = [], 0
    for row in loops:
        ctx = context(row)
        if not ctx:
            continue
        rel, clean, b0, body, cls, cexpr, aliases = ctx
        for callee, pos, args in call_sites(body):
            if callee.split("::")[-1] in CONTROL_KEYWORDS:
                continue
            ctrl_calls += 1
            for i, a in enumerate(args):
                hit, how = match_handle(a, cexpr, cexpr.split(".")[-1].split("->")[-1], aliases)
                if hit:
                    ctrl_hits.append({"file": rel, "line": row["line"], "callee": callee, "arg_index": i,
                                      "arg": norm(a)[:90], "container": row["container"],
                                      "owner": row["owner"], "how": how})
    # ---- control 2: iterateClients(m_clients, ...) — docs/80's 11 sites ------------------------
    ctrl_iterate = []
    for rel in ("Source/WebCore/css/CSSFontFace.cpp", "Source/WebCore/css/CSSFontFaceSet.cpp",
                "Source/WebCore/dom/ActiveDOMObject.cpp"):
        if rel not in R.file_funcs:
            continue
        clean = R.clean_of(rel)
        for m in re.finditer(r"iterateClients\s*\(", clean):
            cp = match_paren_fwd(clean, m.end() - 1)
            args = split_args(clean[m.end():cp]) if cp > 0 else []
            if args:
                hit, how = match_handle(args[0], "m_clients", "m_clients", {})
                ctrl_iterate.append({"file": rel, "arg0": norm(args[0])[:60], "matched": hit, "how": how})

    summary = {
        "owner_rows": len(owner), "loops_not_found": not_found,
        "calls_in_owner_bodies": total_calls, "args_in_owner_bodies": total_args,
        "argpass_sites": len(sites), "depth2_sites": len(depth2),
        "alias_rows": alias_rows, "member_in_callee": member_in_callee,
        "growth_in_callee": growth_in_callee, "member_arg_in_callee": member_arg_in_callee,
        "root_in_callee": {"count": root_in_callee, "bodies": len(callee_body_bytes),
                           "bytes_min": min(callee_body_bytes) if callee_body_bytes else 0,
                           "bytes_median": sorted(callee_body_bytes)[len(callee_body_bytes) // 2] if callee_body_bytes else 0,
                           "samples": root_in_callee_samples},
        "callee_scan": {"calls": callee_calls, "resolved": callee_resolved,
                        "unresolved": dict(unresolved_callees.most_common(20))},
        "mentions": dict(mentions), "counts": dict(counts),
        "control_all_loops": {"calls": ctrl_calls, "hits": len(ctrl_hits), "rows": ctrl_hits},
        "control_iterate_clients": ctrl_iterate,
        "sites": [{k: v for k, v in s.items() if k != "callees"} |
                  {"callees": [{kk: vv for kk, vv in c.items() if not kk.startswith("_")} for c in s["callees"]]}
                  for s in sites],
        "depth2_detail": [{k: v for k, v in x.items() if k != "callees"} |
                          {"callees": [{kk: vv for kk, vv in c.items() if not kk.startswith("_")} for c in x["callees"]]}
                          for x in depth2],
    }
    json.dump(summary, sys.stdout, indent=1)
    print("owner rows %d | calls %d | args %d" % (len(owner), total_calls, total_args), file=sys.stderr)
    print("argpass %d depth2 %d alias-rows %d member-in-callee %d growth-ctrl %d member-arg-ctrl %d %s" %
          (len(sites), len(depth2), len(alias_rows), len(member_in_callee),
           len(growth_in_callee), len(member_arg_in_callee), dict(counts)), file=sys.stderr)
    print("callee scan: %d calls, %d resolved, unresolved %s" %
          (callee_calls, callee_resolved, dict(unresolved_callees.most_common(8))), file=sys.stderr)
    print("mentions %s" % dict(mentions), file=sys.stderr)
    print("control all loops: %d calls %d hits" % (ctrl_calls, len(ctrl_hits)), file=sys.stderr)
    print("control iterateClients: %s" % ctrl_iterate[:3], file=sys.stderr)


if __name__ == "__main__":
    main()
