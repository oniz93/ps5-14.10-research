#!/usr/bin/env python3
"""Depth-3, type-aware call resolver for the index loops of docs/81 (docs/82).

    python3 tools/index-loop-resolve.py > data/index-loop/resolve.json

docs/81 followed a callee only when its name had exactly one definition in the tree (a bare-name
route collides: `append`/`at`/`get` gave 34 false candidates) and resolved one hop through the
class-qualified (class, method) index. Two consequences it could not measure:

  * 828 of 1,261 rows have no `container_type` — 45 of them are *owner* rows, where the verdict
    logic needs the type to tell `Vector<Ref<X>>` (owning) from `Vector<X*>` (raw) and to name the
    element class. Causes: the member is declared in a base class, or the container is a member
    chain (`m_atomData.group.terms`), which the first pass keys as one literal member name.
  * a call whose receiver type is known but whose method name is not unique is never followed, so a
    script window two or three hops away through `m_document->updateStyleIfNeeded()` or
    `page->chrome().client().didX()` is invisible.

This tool re-resolves both. It does not re-scan for loops: it takes data/index-loop/loops.json.

  1. member types through the base-class chain (BFS over vls.class_index()'s base lists) and through
     member chains, so `m_atomData.group.terms` resolves to `Vector<Ref<Term>>`-style text;
  2. every call in each owner row's loop body resolved by *receiver type* — `this`/bare -> the
     owning class, `m_x` -> its member type, a local -> its declaration (following an `auto` rhs
     through a member chain or a method return type), `expr->m()` -> that method's return type —
     then that body's own calls, to depth 3, and whether the route reaches a DIRECT_RE sink
     (docs/75's list: dispatchEvent, resolve(, JSC::call, getProperty, ...);
  3. a mutator call (remove/clear/shrink/...) on the container expression inside the body, or on a
     member with the same name inside a callee body in the route.

JSON on stdout; a funnel per row class on stderr. Every "new window" row is a *candidate*: the
resolver's method table keeps the first definition of an overloaded name, so each hit is read in
source before it is called a finding (docs/82 does that).
"""
import os, re, sys, json, bisect, importlib.util
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("vls", os.path.join(HERE, "vector-local-sweep.py"))
vls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vls)

WEB_CORE = vls.WEB_CORE
strip = vls.strip_comments_strings
functions = vls.functions
DIRECT_RE = vls.DIRECT_RE
match_paren_fwd = vls.match_paren_fwd
class_index = vls.class_index
base_names = vls.base_names

NL = chr(10)
FOR_RE = re.compile(r"\bfor\s*\(")
CLASS_RE = re.compile(r"\b(class|struct|union)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{]*)?\{")
TYPE = (r"((?:const\s+)?[A-Za-z_][\w:]*(?:\s*<[^;{}]*>)?(?:\s*[*&]+)?)")
# A member declaration can carry an annotation between the name and the terminator
# (`m_frameBufferCache WTF_GUARDED_BY_LOCK(m_lock);`, ScalableImageDecoder.h:197).
MEMBER_RE = re.compile(TYPE + r"\s+(m_[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*"
                       r"(?:\s+WTF_[A-Z_]+\([^)]*\))?\s*(?:[;{=])")
FILEVEL_RE = re.compile(TYPE + r"\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*"
                        r"(?:\s+WTF_[A-Z_]+\([^)]*\))?\s*(?:[;{=])")
CXX_KEYWORDS = {"return", "if", "else", "for", "while", "do", "switch", "case", "break", "continue",
                "goto", "throw", "try", "catch", "new", "delete", "sizeof", "typedef", "using",
                "namespace", "template", "typename", "public", "private", "protected", "class",
                "struct", "union", "enum", "static", "const", "constexpr", "inline", "virtual",
                "operator", "friend", "explicit", "extern", "volatile", "mutable", "this"}
NOT_A_TYPE = {"return", "delete", "if", "while", "for", "case", "throw", "co_return", "using",
              "typedef", "else", "switch", "catch", "do", "new", "sizeof", "template", "operator"}
QUALIFIER_RE = re.compile(r"\b(?:virtual|inline|static|constexpr|explicit|ALWAYS_INLINE|WTF_INLINE|"
                          r"NEVER_INLINE|const|override|final)\b")
MUTATORS = ("clear", "remove", "removeAt", "removeAll", "removeFirst", "removeLast", "takeFirst",
            "takeLast", "take", "shrink", "resize", "shrinkToFit", "swap", "reverse", "sort", "fill",
            "truncate", "removeIf", "removeAllMatching", "removeFirstMatching", "pop_back",
            "pop_front", "erase")
RECV_CALL = re.compile(r"(?<![\w.>])([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*(?:->|\.)\s*"
                       r"([A-Za-z_]\w*)\s*\(")
STATIC_CALL = re.compile(r"(?<![\w.>:])([A-Z][A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(")
BARE_CALL = re.compile(r"(?<![\w.>])([A-Za-z_]\w*)\s*\(")
CALLBACK_NAME = re.compile(r"^(?:did|will|should|can|notify|handle|fire|invoke|call|dispatch|update|schedule|"
                           r"perform|apply|visit|observe|on)[A-Z_]\w*$|^\w+(?:Changed|DidChange|StateChanged)$")
INTERFACE_TYPE = re.compile(r"\b\w*(?:Client|Observer|Handler|Listener|Delegate|Consumer|Visitor|Proxy)\b")
CALL_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "catch", "do", "else",
                 "ASSERT", "ASSERT_NOT_REACHED", "RELEASE_ASSERT", "UNUSED_PARAM", "WTFMove",
                 "dynamic_cast", "static_cast", "reinterpret_cast", "const_cast", "decltype"}


def line_starts(text):
    out = [0]
    for i, c in enumerate(text):
        if c == NL:
            out.append(i + 1)
    return out


def body_span(clean, rparen):
    k, n = rparen + 1, len(clean)
    while k < n and clean[k] in " \t\r\n":
        k += 1
    if k < n and clean[k] == "{":
        d, j = 1, k + 1
        while j < n and d > 0:
            if clean[j] == "{":
                d += 1
            elif clean[j] == "}":
                d -= 1
            j += 1
        return k, j
    j = clean.find(";", k)
    return k, (j + 1 if j >= 0 else n)


def strip_template(t):
    """`Vector<Ref<X>>` -> `Vector`; `X*` -> `X`; `const X&` -> `X`."""
    t = re.sub(r"\b(const|volatile|struct|class)\b", " ", t or "")
    t = t.strip()
    t = re.sub(r"<.*", "", t)
    t = t.replace("*", " ").replace("&", " ")
    t = " ".join(t.split())
    return t.split("::")[-1] if t else ""


def elem_of(t):
    if not t or "<" not in t:
        return ""
    inner = t.split("<", 1)[1].rsplit(">", 1)[0].split(",")[0].strip()
    inner = re.sub(r"\b(const|volatile)\b", " ", inner)
    for _ in range(3):
        inner = re.sub(r"^\s*(?:RefPtr|Ref|WeakPtr|Weak|unique_ptr|UniqueRef|GCReachableRef|"
                       r"CheckedRef|std::unowned_ptr|MarkedVector)\s*<", "", inner).strip()
    return strip_template(inner)


class Resolver:
    def __init__(self):
        self.cls_idx = class_index()          # name -> (rel path, bases, kind)
        self.members = {}                     # (class, member) -> type
        self.fields = {}                      # (class, any field) -> type, nested structs included
        self.methods = defaultdict(list)      # (class, method) -> [(rel, f0, f1)]
        self.bare = defaultdict(list)         # method -> [(class, rel, f0, f1)]
        self.rets = {}                        # (class, method) -> return type
        self.file_funcs = {}                  # rel -> [(name, f0, f1, depth)]
        self._scopes = {}                     # rel -> [(class, open brace, close brace)]
        self._clean = {}
        self._paths = {}

    # ---- parse ---------------------------------------------------------------------------
    def scan(self):
        for dirpath, dirnames, filenames in os.walk(WEB_CORE):
            dirnames[:] = sorted(d for d in dirnames if d != ".git")
            for fn in sorted(filenames):
                if not fn.endswith((".cpp", ".mm", ".h")):
                    continue
                full = os.path.join(dirpath, fn)
                rel = "Source/WebCore/" + os.path.relpath(full, WEB_CORE)
                self._paths[rel] = full
                try:
                    src = open(full, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                clean = strip(src)
                funcs = functions(clean)
                scopes = []
                if any(k in clean for k in ("class", "struct", "union")):
                    for m in CLASS_RE.finditer(clean):
                        ob = m.end() - 1
                        d, j, n = 1, ob + 1, len(clean)
                        while j < n and d > 0:
                            if clean[j] == "{":
                                d += 1
                            elif clean[j] == "}":
                                d -= 1
                            j += 1
                        scopes.append((m.group(2), ob, j))
                    sobs = [s[1] for s in scopes]
                    order = sorted(range(len(scopes)), key=lambda i: scopes[i][1])
                    sobs = [scopes[i][1] for i in order]

                    def owner_at(pos):
                        i = bisect.bisect_right(sobs, pos) - 1
                        while i >= 0:
                            c, ob, cb = scopes[order[i]]
                            if ob < pos < cb:
                                return c
                            i -= 1
                        return None

                    fstarts = [f[1] for f in funcs]

                    def in_func(pos):
                        i = bisect.bisect_right(fstarts, pos) - 1
                        return i >= 0 and funcs[i][1] < pos < funcs[i][2]

                    for mm in MEMBER_RE.finditer(clean):
                        if mm.group(1) in NOT_A_TYPE:
                            continue
                        cname = owner_at(mm.start())
                        if cname:
                            self.members.setdefault((cname, mm.group(2)),
                                                    " ".join(mm.group(1).split()))
                    # Nested struct fields (`union AtomData { Group group; }`) — needed to walk a member
                    # chain like `m_atomData.group.terms`. Declarations inside a function body are skipped:
                    # a local `Vector<X> foo;` inside an inline method must not be keyed to its class.
                    for mm in FILEVEL_RE.finditer(clean):
                        if mm.group(1) in CXX_KEYWORDS or mm.group(2) in CXX_KEYWORDS:
                            continue
                        pos = mm.start()
                        if in_func(pos):
                            continue
                        cname = owner_at(pos)
                        if cname:
                            self.fields.setdefault((cname, mm.group(2)),
                                                   " ".join(mm.group(1).split()))
                    # `union AtomData { ... } m_atomData;` — the member's type is the brace body's name,
                    # and the member belongs to the class that encloses that declaration, not to AtomData.
                    for sname, ob, cb in scopes:
                        mm = re.match(r"\s*(m_[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*[;{=]",
                                      clean[cb:cb + 90])
                        if not mm:
                            continue
                        owner = owner_at(ob)
                        if owner:
                            self.members.setdefault((owner, mm.group(1)), sname)
                self.file_funcs[rel] = funcs
                for name, f0, f1, _d in funcs:
                    short = name.split("::")[-1]
                    sig = vls.signature_before(clean, f0)
                    if "::" in name:
                        cls = name.rsplit("::", 1)[0].split("::")[-1]
                        self.methods[(cls, short)].append((rel, f0, f1))
                        if sig and sig[0].split("::")[-1] == short:
                            k = sig[1] - 1
                            while k > 0 and clean[k] not in ";{}":
                                k -= 1
                            rt = self._ret_from_seg(clean[k + 1:sig[1]], short)
                            if rt:
                                self.rets.setdefault((cls, short), rt)
                    else:
                        best, bcls = None, ""
                        for c, ob, cb in scopes:
                            if ob < f0 < cb and (best is None or ob > best):
                                best, bcls = ob, c
                        cls = bcls
                        if cls:
                            self.methods[(cls, short)].append((rel, f0, f1))
                            if sig and sig[0].split("::")[-1] == short:
                                k = sig[1] - 1
                                while k > 0 and clean[k] not in ";{}":
                                    k -= 1
                                rt = self._ret_from_seg(clean[k + 1:sig[1]], short)
                                if rt:
                                    self.rets.setdefault((cls, short), rt)
                        self.bare[short].append((cls, rel, f0, f1))
        # a bare-name function with one definition is the only unambiguous bare route (docs/81)
        for name in list(self.bare):
            if len(self.bare[name]) == 1 and self.bare[name][0][0]:
                cls, rel, f0, f1 = self.bare[name][0]
                self.methods.setdefault((cls, name), [(rel, f0, f1)])

    @staticmethod
    def _ret_from_seg(seg, name):
        seg = seg.split("#")[0]
        seg = " ".join(seg.split())
        if not seg or "template" in seg:
            return ""
        rt = QUALIFIER_RE.sub(" ", seg)
        rt = " ".join(rt.split())
        if not rt:
            return ""
        last = rt.split()[-1]
        if last in NOT_A_TYPE or last in ("void", "auto"):
            return ""
        return rt

    # ---- text ----------------------------------------------------------------------------
    def clean_of(self, rel):
        if rel not in self._clean:
            try:
                self._clean[rel] = strip(open(self._paths[rel], encoding="utf-8",
                                              errors="replace").read())
            except Exception:
                self._clean[rel] = ""
        return self._clean[rel]

    def file_scopes(self, rel):
        if rel not in self._scopes:
            clean = self.clean_of(rel)
            out = []
            for m in CLASS_RE.finditer(clean):
                ob = m.end() - 1
                d, j, n = 1, ob + 1, len(clean)
                while j < n and d > 0:
                    if clean[j] == "{":
                        d += 1
                    elif clean[j] == "}":
                        d -= 1
                    j += 1
                out.append((m.group(2), ob, j))
            self._scopes[rel] = out
        return self._scopes[rel]

    def class_from_context(self, clean, pos):
        """Out-of-line member definitions (`Foo<T>::Foo() : Base(...) {`) sit outside the class brace."""
        seg = clean[max(0, pos - 2500):pos]
        ms = re.findall(r"([A-Za-z_]\w*)\s*(?:<[^<>;{}()]{0,80}>)?::\s*~?[A-Za-z_]\w*\s*\(", seg)
        return ms[-1] if ms else ""

    def enclosing_class(self, rel, pos):
        best, name = None, ""
        for c, ob, cb in self.file_scopes(rel):
            if ob < pos < cb and (best is None or ob > best):
                best, name = ob, c
        return name

    def body(self, cls, method):
        for rel, f0, f1 in self.methods.get((cls, method), ()):
            txt = self.clean_of(rel)[f0:f1]
            if txt:
                return txt, rel
        return "", ""

    # ---- types ---------------------------------------------------------------------------
    def member_type(self, cls, name):
        seen, frontier = set(), [cls]
        while frontier and len(seen) < 64:
            c = frontier.pop(0)
            if not c or c in seen:
                continue
            seen.add(c)
            t = self.members.get((c, name)) or self.fields.get((c, name))
            if t:
                return t, c
            h = self.cls_idx.get(c)
            if h:
                frontier.extend(base_names(h[1]))
        return "", ""

    def member_chain(self, cls, expr):
        parts = [p for p in re.split(r"\s*(?:->|\.)\s*", re.sub(r"^this->", "", expr.strip())) if p]
        if not parts:
            return "", ""
        t, decl = self.member_type(cls, parts[0])
        for p in parts[1:]:
            if not t:
                return "", decl
            # `std::unique_ptr<WebMData> m_webmData;` continues into WebMData, not into unique_ptr.
            t2, d2 = self.member_type(elem_of(t) or strip_template(t), p)
            if not t2:
                return "", decl
            t, decl = t2, decl or d2
        return t, decl

    def local_type(self, clean, f0, pos, name):
        window = clean[max(f0, pos - 8000):pos]
        pat = re.compile(r"(?<![\w.])((?:const\s+)?(?:auto|[\w:]+(?:\s*<[^;{}]*>)?)(?:\s*[*&]{1,2})?)"
                         r"\s+%s\s*=\s*([^;]{0,240});" % re.escape(name))
        hit = None
        for mm in pat.finditer(window):
            hit = mm
        if not hit:
            return ""
        ty = " ".join(hit.group(1).split())
        if re.fullmatch(r"(?:const\s+)?auto\s*[*&]{0,2}", ty):
            return self.expr_type(hit.group(2), clean, f0, max(f0, pos - 8000) + hit.start())
        return ty

    def expr_type(self, expr, clean, f0, pos, cls=""):
        e = re.sub(r"^\s*\*+\s*", "", " ".join((expr or "").split()))
        e = re.sub(r"^\(\s*\*\s*this\s*\)", "this", e)
        if not e:
            return ""
        if e == "this":
            return cls
        if re.match(r"^(?:this->)?m_[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*$", e):
            t, _ = self.member_chain(cls, e)
            return t
        m = re.match(r"^([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*\(",
                     e)
        if m:
            rcls = self.expr_type(m.group(1), clean, f0, pos, cls)
            if rcls:
                return self.rets.get((strip_template(rcls), m.group(2)), "")
            return ""
        if re.fullmatch(r"[A-Za-z_]\w*", e):
            return self.local_type(clean, f0, pos, e)
        return ""

    def recv_cls(self, recv, clean, f0, pos, cls):
        r = recv.strip()
        if r in ("this", "*this"):
            return cls
        if r.startswith("m_"):
            t, _ = self.member_chain(cls, r)
            return strip_template(t)
        if re.fullmatch(r"[A-Za-z_]\w*", r):
            t = self.local_type(clean, f0, pos, r)
            return strip_template(t)
        # chain ending in a call: `page->chrome()` etc.
        m = re.match(r"^(.*?)(?:->|\.)\s*([A-Za-z_]\w*)\s*\(.*\)$", r)
        if m:
            inner = self.expr_type(r, clean, f0, pos, cls)
            return strip_template(inner)
        return ""

    def method_body_any(self, cls, method):
        """(body, owner) for a method, trying the class and then its base chain."""
        seen, frontier = set(), [cls]
        while frontier and len(seen) < 64:
            c = frontier.pop(0)
            if not c or c in seen:
                continue
            seen.add(c)
            b, rel = self.body(c, method)
            if b:
                return b, c
            h = self.cls_idx.get(c)
            if h:
                frontier.extend(base_names(h[1]))
        return "", ""

    def route(self, cls, method, maxd=3):
        """[(depth, cls, method)] routes that reach a sink, breadth-first, plus the bodies seen."""
        out, seen, frontier = [], set(), [(cls, method, 0, [])]
        bodies = []
        while frontier:
            c, meth, d, path = frontier.pop(0)
            key = (c, meth)
            if key in seen or d > maxd:
                continue
            seen.add(key)
            b, owner = self.method_body_any(c, meth)
            if not b:
                continue
            bodies.append((owner, meth, b))
            hits = sorted({mm.group(0)[:-1] for mm in DIRECT_RE.finditer(b)})
            if hits:
                out.append({"depth": d + 1, "route": path + ["%s::%s" % (owner, meth)],
                            "sinks": hits, "entry": [cls, method], "kind": "literal"})
                continue
            if d == maxd:
                continue
            for mm in RECV_CALL.finditer(b):
                ric, name = mm.group(1), mm.group(2)
                if name in CALL_KEYWORDS:
                    continue
                rc = self.recv_cls(ric, b, 0, mm.start(), owner)
                if not rc:
                    continue
                # A virtual call on a client/observer/… receiver runs script (docs/66, docs/80). Its
                # implementation lives in whoever implements the interface, so the walk stops here.
                if INTERFACE_TYPE.search(rc) and CALLBACK_NAME.match(name):
                    out.append({"depth": d + 1, "route": path + ["%s::%s" % (owner, meth)],
                                "sinks": ["client-callback:%s::%s" % (rc, name)],
                                "entry": [cls, method], "kind": "client"})
                    continue
                frontier.append((rc, name, d + 1, path + ["%s::%s" % (owner, meth)]))
            for mm in BARE_CALL.finditer(b):
                name = mm.group(1)
                if name in CALL_KEYWORDS:
                    continue
                if self.method_body_any(owner, name)[0]:
                    frontier.append((owner, name, d + 1, path + ["%s::%s" % (owner, meth)]))
                elif len(self.bare.get(name, ())) == 1 and self.bare[name][0][0]:
                    frontier.append((self.bare[name][0][0], name, d + 1,
                                     path + ["%s::%s" % (owner, meth)]))
        return out, bodies


def find_loop_body(clean, line, starts):
    pos = starts[line - 1] if line - 1 < len(starts) else 0
    m = FOR_RE.search(clean, pos)
    if not m:
        return None, None, None
    lp = m.end() - 1
    rp = match_paren_fwd(clean, lp)
    if rp < 0:
        return None, None, None
    b0, b1 = body_span(clean, rp)
    return m.start(), b0, clean[b0:b1]


def main():
    loops = json.load(open(os.path.join(HERE, os.pardir, "data", "index-loop", "loops.json")))
    rows = loops["rows"]
    R = Resolver()
    R.scan()

    # ---- over-approximation: union over *every* definition of a name (docs/81's blind spot) --------
    # docs/81 followed a callee only when its name had exactly one definition. Here every same-named
    # definition in the tree counts, so a name collision can only add candidates, never hide one.
    CLIENTISH = re.compile(r"^(?:m_)?(?:\w*_)?(?:clients?|observers?|handlers?|listeners?|delegates?|"
                           r"callbacks?|completions?|consumers?|visitors?|proxies?)\w*$", re.I)

    def body_window_names(b):
        """Names of the calls that can run script in `b`, by spelling only (no type resolution)."""
        out = set()
        for p in DIRECT_RE.findall(b):
            out.add(p[:-1])
        for mm in re.finditer(r"(?:->|\.)\s*([A-Za-z_]\w*)\s*\(", b):
            nm = mm.group(1)
            head = b[max(0, mm.start() - 40):mm.start()]
            if CALLBACK_NAME.match(nm) or CLIENTISH.search(head.strip().split("->")[-1].split(".")[-1][-30:]):
                out.add(nm)
        return out

    name_calls = {}
    name_depth = {}
    for (cls, name) in list(R.methods):
        b, _ = R.body(cls, name)
        if not b:
            continue
        wn = body_window_names(b)
        if wn:
            name_depth[name] = 1
        name_calls.setdefault(name, set()).update(wn)
    for d in (2, 3):
        for name, callees in name_calls.items():
            if name_depth.get(name, 99) <= d - 1:
                continue
            if any(name_depth.get(c, 99) <= d - 1 for c in callees):
                name_depth[name] = d

    before_unres = sum(1 for r in rows if not r["container_type"])
    before_unres_owner = sum(1 for r in rows if r["owner"] and not r["container_type"])
    resolved_container = 0
    owner_rows = [r for r in rows if r["owner"]]
    out_rows = []
    new_windows = []
    counts = Counter()

    for r in owner_rows:
        rel = r["file"]
        clean = R.clean_of(rel)
        starts = line_starts(clean)
        mstart, b0, body = find_loop_body(clean, r["line"], starts)
        if body is None:
            counts["loop-not-found"] += 1
            continue
        cls = r["class"]
        # docs/81 loses the owner for constructors in templates and for classes declared inside a
        # .cpp (`function` came out as `?`); take the enclosing class at the loop instead.
        if cls in ("", "?", "template"):
            cls = R.enclosing_class(rel, mstart) or R.class_from_context(clean, mstart)
        # ---- the 45: resolve the container type through the base chain / member chain
        ctype = r["container_type"]
        source = "pass2"
        if not ctype:
            if re.match(r"^(?:this->)?m_[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+$", r["container"]):
                ctype, decl = R.member_chain(cls, r["container"])
                source = "member-chain:%s" % (decl or "?")
            elif r["container"].startswith("m_"):
                ctype, decl = R.member_type(cls, r["container"])
                source = "base-chain:%s" % (decl or "?")
            else:
                ctype = R.local_type(clean, 0, mstart, r["container"])
                source = "local-decl"
            if ctype:
                resolved_container += 1
        # ---- calls in the body, resolved by receiver type, to depth 3
        routes = []
        # A local bound to an element of the loop's own container carries the element type: the
        # `auto& event = m_deferredEvents[i];` spelling hides the class from any name-based route.
        elem_locals = {}
        if ctype:
            for mm in re.finditer(r"\b(?:auto|const\s+auto)\s*(&{0,2})\s*([A-Za-z_]\w*)\s*=\s*"
                                  r"(?<![\w.>])%s\s*(?:\[|\.at\s*\()" % re.escape(r["container"]),
                                  body):
                et = elem_of(ctype)
                if et:
                    elem_locals[mm.group(2)] = et
        cov = {"calls": 0, "resolved": 0, "static": 0}
        unknown = []
        for mm in RECV_CALL.finditer(body):
            ric, name = mm.group(1), mm.group(2)
            if name in CALL_KEYWORDS:
                continue
            cov["calls"] += 1
            rc = elem_locals.get(ric) or R.recv_cls(ric, clean, 0, b0 + mm.start(), cls)
            if not rc:
                counts["recv-unresolved"] += 1
                if len(unknown) < 12:
                    unknown.append("%s->%s" % (ric, name))
                continue
            cov["resolved"] += 1
            rs, _ = R.route(rc, name, 3)
            for hit in rs:
                routes.append({"call": "%s->%s" % (ric, name), "recv_type": rc, **hit})
        # `m_foo[i].bar()` / `m_foo.at(i)->bar()` — the receiver is an element expression.
        if ctype:
            et = elem_of(ctype)
            for mm in re.finditer(r"(?<![\w.>])%s\s*(?:\[[^\]]{0,60}\]|\.at\s*\([^)]{0,60}\))"
                                  r"\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*\(" % re.escape(r["container"]),
                                  body):
                name = mm.group(1)
                if not et or name in CALL_KEYWORDS:
                    continue
                rs, _ = R.route(et, name, 3)
                for hit in rs:
                    routes.append({"call": "%s[...]->%s" % (r["container"], name),
                                   "recv_type": et, **hit})
        for mm in STATIC_CALL.finditer(body):
            scls, name = mm.group(1), mm.group(2)
            if name in CALL_KEYWORDS or scls not in R.cls_idx:
                continue
            cov["calls"] += 1
            cov["static"] += 1
            rs, _ = R.route(scls, name, 3)
            for hit in rs:
                routes.append({"call": "%s::%s" % (scls, name), "recv_type": scls, **hit})
        for mm in BARE_CALL.finditer(body):
            name = mm.group(1)
            if name in CALL_KEYWORDS:
                continue
            cov["calls"] += 1
            rs, _ = R.route(cls, name, 3)
            if rs:
                cov["resolved"] += 1
            for hit in rs:
                routes.append({"call": name + "()", "recv_type": cls, **hit})
        # dedupe by (call, route)
        seen = set()
        uniq = []
        for x in routes:
            k = (x["call"], tuple(x["route"]))
            if k not in seen:
                seen.add(k)
                uniq.append(x)
        # ---- did any of them name a mutator on the same member, in a body on the route?
        mut_in_chain = []
        for x in uniq:
            for owner, meth, b in R.route_bodies(x["entry"][0], x["entry"][1], 3):
                for mm in re.finditer(r"(?<![\w.>])((?:this->)?m_[A-Za-z_]\w*)\s*(?:->|\.)\s*(%s)\s*\(" %
                                      "|".join(MUTATORS), b):
                    if mm.group(1).split("->")[-1] == r["container"].split(".")[-1].split("->")[-1]:
                        mut_in_chain.append({"body": "%s::%s" % (owner, meth),
                                             "call": "%s.%s()" % (mm.group(1), mm.group(2))})
        known = bool(r["window"])
        cand = uniq if not known else []
        out_rows.append({
            "file": rel, "line": r["line"], "function": r["function"], "class": cls,
            "container": r["container"], "container_type_before": r["container_type"],
            "container_type_after": ctype, "type_source": source,
            "bound_kind": r["bound_kind"], "mutations": r["mutations"],
            "verdict_before": r["verdict"], "window_before": [w["kind"] for w in r["window"]],
            "coverage": cov, "unknown_receivers": unknown,
            "routes": uniq[:8], "new_routes": cand[:8], "mutator_in_route": mut_in_chain[:6],
        })
        # names in the body that reach a window through *some* definition, regardless of receiver
        amb = []
        for mm in BARE_CALL.finditer(body):
            n = mm.group(1)
            if n in CALL_KEYWORDS or n == r["function"].split("::")[-1]:
                continue
            if name_depth.get(n, 99) <= 3 and n not in amb:
                amb.append(n)
        out_rows[-1]["ambiguous_names"] = amb[:10]
        out_rows[-1]["ambiguous_depth"] = {n: name_depth[n] for n in amb[:10]}
        if amb:
            counts["rows-with-ambiguous-name"] += 1
        if cand:
            new_windows.append(out_rows[-1])
            counts["rows-with-new-route"] += 1
            if mut_in_chain:
                counts["rows-with-new-route-and-mutator"] += 1

    after_unres = sum(1 for x in out_rows if not x["container_type_after"]) + \
        sum(1 for r in rows if not r["owner"] and not r["container_type"])
    summary = {
        "files": len(R.file_funcs), "owner_rows": len(owner_rows),
        "before": {"unresolved_all": before_unres, "unresolved_owner": before_unres_owner},
        "after": {"unresolved_all": after_unres,
                  "unresolved_owner": sum(1 for x in out_rows if not x["container_type_after"]),
                  "resolved_owner": resolved_container},
        "counts": dict(counts),
        "new_window_rows": new_windows,
        "rows": out_rows,
    }
    json.dump(summary, sys.stdout, indent=1)
    print("files %d owner_rows %d" % (len(R.file_funcs), len(owner_rows)), file=sys.stderr)
    print("unresolved before %s after %s" % (summary["before"], summary["after"]), file=sys.stderr)
    print("counts %s" % dict(counts), file=sys.stderr)
    print("new-window rows %d" % len(new_windows), file=sys.stderr)


# route() already returns bodies only for sinks; a separate accessor keeps main() readable.
def _route_bodies(self, cls, method, maxd):
    out, seen, frontier = [], set(), [(cls, method, 0)]
    while frontier:
        c, meth, d = frontier.pop(0)
        if (c, meth) in seen or d > maxd:
            continue
        seen.add((c, meth))
        b, owner = self.method_body_any(c, meth)
        if not b:
            continue
        out.append((owner, meth, b))
        if d == maxd:
            continue
        for mm in RECV_CALL.finditer(b):
            if mm.group(2) in CALL_KEYWORDS:
                continue
            rc = self.recv_cls(mm.group(1), b, 0, mm.start(), owner)
            if rc:
                frontier.append((rc, mm.group(2), d + 1))
        for mm in BARE_CALL.finditer(b):
            name = mm.group(1)
            if name in CALL_KEYWORDS:
                continue
            if self.method_body_any(owner, name)[0]:
                frontier.append((owner, name, d + 1))
            elif len(self.bare.get(name, ())) == 1 and self.bare[name][0][0]:
                frontier.append((self.bare[name][0][0], name, d + 1))
    return out


Resolver.route_bodies = _route_bodies

if __name__ == "__main__":
    main()
