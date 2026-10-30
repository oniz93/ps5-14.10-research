#!/usr/bin/env python3
"""Whole-tree sweep for the *index-loop* shape (docs/81).

    python3 tools/index-loop-sweep.py > data/index-loop/loops.json

Every net so far keys on a range-for over a container (docs/79, docs/80), a push into a container
(docs/78), or a helper template that hides the range-for (docs/80). None of them can see

    for (size_t i = 0; i < m_foo.size(); ++i) {
        ...
        client.didSomething();     // script runs here and can remove from m_foo
        use(m_foo[i]);             // stale bound / stale buffer
    }

which is the one spelling left, and the one the drop writes itself (`Vector::map`,
WTF/wtf/Vector.h:1683-1691).

Two shapes are reported, both requiring the container to belong to the *owner object* (a member, or a
local reference/alias of one — a local copy is immune):

  * SHRINK  — a script window runs before the index read and the bound is cached in a local, or the body
              mutates the container, so the loop can read past the end of a container script has shrunk.
  * ELEMENT — the elements are non-owning (raw `*`), or the element call goes to a method whose own body
              reaches a sink, so an element can be freed/JS-entered while the loop still indexes it.

Passes:

  PASS 1  every function body -> direct script sink; callee sets (qualified calls included: docs/80 records
          that the older `CALL_RE` could not match `WTF::map(`); a method index (class, method) -> body, so a
          call on an element (`m_foo[i]->didX()`) resolves to *that class's* definition, not to a
          same-named function elsewhere in the tree. A bare-name route is followed only when the name has
          exactly one definition — `append` matches hundreds and made this tool's first run report 34 false
          candidates.

  PASS 2  every `for (i = A; i < B; ++i)` in `Source/WebCore` whose body indexes a container with the loop
          variable. The container comes from the index expression, then is linked to the bound (`c.size()`
          re-read, or a local assigned from it). Member types are resolved per owning class
          (`CSSFontFaceSet::m_faces`, not the first `m_faces` in the tree — a flat index reported
          `m_children` as `AccessibilityChildrenVector` in unrelated classes).

JSON on stdout, funnel and verdict counts on stderr.
"""
import os, re, sys, json, bisect, importlib.util
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("vls", os.path.join(HERE, "vector-local-sweep.py"))
vls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vls)

WEB_CORE = vls.WEB_CORE
strip = vls.strip_comments_strings
functions = vls.functions
DIRECT_RE = vls.DIRECT_RE
match_paren_fwd = vls.match_paren_fwd

NL = chr(10)
CALL_RE = re.compile(r"(?<![\w])((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\(")
FOR_RE = re.compile(r"\bfor\s*\(")
CLASS_RE = re.compile(r"\b(class|struct)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{]*)?\{")
NUM_TYPES = (r"(?:const\s+)?(?:auto|size_t|unsigned|unsigned\s+int|int|long|uint8_t|uint16_t|uint32_t|"
             r"uint64_t|int8_t|int16_t|int32_t|int64_t|ptrdiff_t|ssize_t)")
MUTATORS = ("clear", "remove", "removeAt", "removeAll", "removeFirst", "removeLast", "takeFirst", "takeLast",
            "take", "shrink", "resize", "shrinkToFit", "swap", "reverse", "sort", "fill", "truncate",
            "removeIf", "removeAllMatching", "removeFirstMatching", "pop_back", "pop_front", "erase")
CALLBACK_NAME = re.compile(r"^(?:did|will|should|can|notify|handle|fire|invoke|call|dispatch|update|schedule|"
                           r"perform|apply|visit|observe|on)[A-Z_]\w*$|^\w+(?:Changed|DidChange|StateChanged)$")
CALLBACK_RECV = re.compile(r"\b(\w+)\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*\(")
CLIENT_RECV = re.compile(r"^(?:m_)?(?:\w*_)?(?:clients?|observers?|handlers?|listeners?|delegates?|callbacks?|"
                         r"completions?|consumers?|visitors?|proxies?|inspector)s?\w*$", re.I)
INTERFACE_TYPE = re.compile(r"\b\w*(?:Client|Observer|Handler|Listener|Delegate|Consumer|Visitor|Proxy|Inspector)\b")
NOT_A_TYPE = {"return", "delete", "if", "while", "for", "case", "throw", "co_return", "using", "typedef",
              "else", "switch", "catch", "do", "new", "sizeof", "static_cast", "reinterpret_cast",
              "const_cast", "dynamic_cast", "template", "operator"}
SIZE_ANY = r"(?:->|\.)\s*(?:size|length)\s*\(\s*\)"


def line_starts(text):
    out = [0]
    for i, c in enumerate(text):
        if c == NL:
            out.append(i + 1)
    return out


def lineno(starts, pos):
    return bisect.bisect_right(starts, pos)


def call_names(body):
    return {m.group(1).split("::")[-1] for m in CALL_RE.finditer(body)}


def class_scopes(clean):
    out = []
    n = len(clean)
    for m in CLASS_RE.finditer(clean):
        ob = m.end() - 1
        d, j = 1, ob + 1
        while j < n and d > 0:
            if clean[j] == "{":
                d += 1
            elif clean[j] == "}":
                d -= 1
            j += 1
        out.append((m.group(2), ob, j))
    return out


def build_indexes(files):
    """direct sinks, callees, definition counts, method bodies, per-class member types."""
    direct, callees, defs = {}, {}, Counter()
    methods = {}       # (class, method) -> body
    members = {}       # (class, member) -> type
    flat_members = {}  # member -> type (fallback)
    for rel, clean, funcs, scopes, _dep in files:
        for name, f0, f1, _d in funcs:
            short = name.split("::")[-1]
            defs[short] += 1
            body = clean[f0:f1]
            hits = {m.group(0)[:-1] for m in DIRECT_RE.finditer(body)}
            if hits:
                direct.setdefault(short, set()).update(hits)
            callees.setdefault(short, set()).update(call_names(body))
            if "::" in name:
                cls = name.rsplit("::", 1)[0].split("::")[-1]
                methods.setdefault((cls, short), body)
            else:
                best = None
                for cname, ob, cb in scopes:
                    if ob < f0 < cb and (best is None or ob > best[1]):
                        best = (cname, ob)
                if best:
                    methods.setdefault((best[0], short), body)
        if rel.endswith(".h"):
            pat = re.compile(r"([A-Za-z_][\w:]*(?:\s*<[^;{}]*>)?)\s+(m_[A-Za-z_]\w*)\s*(?:[;{=])")
            for mm in pat.finditer(clean):
                if mm.group(1) in NOT_A_TYPE:
                    continue
                pos = mm.start()
                cname, best = None, None
                for c, ob, cb in scopes:
                    if ob < pos < cb and (best is None or ob > best):
                        best, cname = ob, c
                ty = " ".join(mm.group(1).split())
                flat_members.setdefault(mm.group(2), ty)
                if cname:
                    members.setdefault((cname, mm.group(2)), ty)
    return direct, callees, defs, methods, members, flat_members


def sink_route(name, direct, callees, defs, maxd=2):
    """Shortest route to a direct sink, following only uniquely-named definitions."""
    if defs.get(name, 0) != 1:
        return None
    seen, frontier = {name}, [name]
    for d in range(0, maxd + 1):
        nxt = []
        for cur in frontier:
            if cur in direct:
                return d
            for c in callees.get(cur, ()):
                if c not in seen and defs.get(c, 0) == 1:
                    seen.add(c)
                    nxt.append(c)
        frontier = nxt
    return None


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


def split_header(h):
    # `<`/`>` are comparisons far more often than template brackets in a classic-for header, and counting
    # them as nesting is what made this tool's first run see 24 loops out of thousands.
    out, d, cur = [], 0, ""
    for ch in h:
        if ch in "([{":
            d += 1
        elif ch in ")]}":
            d -= 1
        if ch == ";" and d == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def strip_this(expr):
    return re.sub(r"^this->", "", " ".join(expr.split()))


def local_decl(clean, name, before):
    """(decl_type, rhs, is_reference) for the last declaration of `name` before `before`."""
    window = clean[max(0, before - 6000):before]
    pat = re.compile(r"(?<![\w.])((?:const\s+)?(?:auto|Vector\s*<[^;{}]*>|FixedVector\s*<[^;{}]*>|"
                     r"Deque\s*<[^;{}]*>|ListHashSet\s*<[^;{}]*>|HashSet\s*<[^;{}]*>|"
                     r"HashMap\s*<[^;{}]*>|WeakHashSet\s*<[^;{}]*>|std::span\s*<[^;{}]*>|"
                     r"[A-Z]\w*(?:\s*<[^;{}]*>)?))\s*(&{0,2})\s*%s\s*=\s*([^;]{0,200});" % re.escape(name))
    hit = None
    for mm in pat.finditer(window):
        hit = mm
    if not hit:
        return "", "", False
    return " ".join(hit.group(1).split()), " ".join(hit.group(3).split()), bool(hit.group(2))


def element_class(ctype):
    if not ctype:
        return "unknown"
    if re.search(r"\b(Ref|RefPtr|UniqueRef|unique_ptr|WeakPtr|Weak|GCReachableRef|CheckedRef|Function|"
                 r"CompletionHandler|std::function|std::variant|std::pair)\s*<", ctype):
        return "owning"
    if "*" in ctype:
        return "raw"
    return "value"


def element_type(ctype):
    """`Vector<Ref<CSSFontFace>>` -> `CSSFontFace`; `Vector<Foo*>` -> `Foo`."""
    if not ctype or "<" not in ctype:
        return ""
    inner = ctype.split("<", 1)[1].rsplit(">", 1)[0]
    inner = inner.split(",")[0].strip()
    inner = re.sub(r"\b(const|volatile)\b", "", inner)
    inner = re.sub(r"\b(RefPtr|Ref|WeakPtr|Weak|unique_ptr|UniqueRef|GCReachableRef|CheckedRef|std::function|"
                   r"Function|CompletionHandler|std::reference_wrapper)\s*<", "", inner)
    inner = inner.strip().rstrip(">").strip()
    inner = inner.replace("*", "").replace("&", "").strip()
    return inner.split("::")[-1] if inner else ""


def main():
    files = []
    for dirpath, dirnames, filenames in os.walk(WEB_CORE):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fn in sorted(filenames):
            if not fn.endswith((".cpp", ".mm", ".h")):
                continue
            full = os.path.join(dirpath, fn)
            try:
                src = open(full, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            rel = "Source/WebCore/" + os.path.relpath(full, WEB_CORE)
            clean = strip(src)
            files.append((rel, clean, functions(clean), class_scopes(clean), None))

    direct, callees, defs, methods, members, flat_members = build_indexes(files)

    rows, counter = [], Counter()
    for rel, clean, funcs, scopes, _d in files:
        if "for" not in clean:
            continue
        starts = line_starts(clean)
        fstarts = [f[1] for f in funcs]
        for m in FOR_RE.finditer(clean):
            lp = m.end() - 1
            rp = match_paren_fwd(clean, lp)
            if rp < 0:
                continue
            parts = split_header(clean[lp + 1:rp])
            if len(parts) != 3:
                counter["not-three-part"] += 1
                continue
            init, cond, inc = (p.strip() for p in parts)
            mi = re.match(r"^(%s)\s+([A-Za-z_]\w*)\s*=\s*(.+)$" % NUM_TYPES, init)
            bare = False
            if not mi:
                # `for (i = 0; i < n; ++i)` — a member or an already-declared local. Also an index loop.
                mi = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", init)
                bare = True
            if not mi:
                counter["init-not-numeric"] += 1
                continue
            ivar = mi.group(2) if not bare else mi.group(1)
            init_rhs = mi.group(3) if not bare else mi.group(2)
            descending = False
            mc = re.match(r"^([A-Za-z_]\w*)\s*(<=|<|!=)\s*(.+)$", cond)
            if not mc or mc.group(1) != ivar:
                # descending: `for (int i = m_foo.size() - 1; i >= 0; --i)` — the init is evaluated once, so
                # the bound is cached by construction, whatever it is.
                mc = re.match(r"^([A-Za-z_]\w*)\s*(>=|>)\s*(.+)$", cond)
                if mc and mc.group(1) == ivar and re.search(
                        r"(?:--\s*%s\b|\b%s\s*--|\b%s\s*-=\s*1)" % ((re.escape(ivar),) * 3), inc):
                    descending = True
                else:
                    counter["cond-not-index"] += 1
                    continue
            op, bound = mc.group(2), mc.group(3).strip()
            if not descending and not re.search(
                    r"(?:\+\+\s*%s\b|\b%s\s*\+\+|\b%s\s*\+=\s*1)" % ((re.escape(ivar),) * 3), inc):
                counter["inc-not-step"] += 1
                continue
            bound_rhs = None
            if descending:
                bound = init_rhs.strip()
            elif re.fullmatch(r"[A-Za-z_]\w*", strip_this(bound)):
                wpat = re.compile(r"(?:%s)\s+%s\s*=\s*([^;]{0,200});|(?<![\w.>])%s\s*=\s*([^;]{0,200});"
                                  % (NUM_TYPES, re.escape(strip_this(bound)), re.escape(strip_this(bound))))
                hit = None
                for mm in wpat.finditer(clean[max(0, m.start() - 4000):m.start()]):
                    hit = mm
                if hit:
                    bound_rhs = (hit.group(1) or hit.group(2) or "").strip()
            b0, b1 = body_span(clean, rp)
            body = clean[b0:b1]
            if not body:
                continue
            idx_re = re.compile(r"(?<![\w.>])([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)\s*"
                                r"(?:\[\s*%s\s*(?:-\s*1)?\s*\]|\bat\s*\(\s*%s\s*(?:-\s*1)?\s*\))"
                                % (re.escape(ivar), re.escape(ivar)))
            cands, first_read_of = [], {}
            for h in idx_re.finditer(body):
                c = h.group(1)
                if c in NOT_A_TYPE:
                    continue
                if c not in cands:
                    cands.append(c)
                    first_read_of[c] = h.start()
            if not cands:
                counter["no-index-read-with-loop-var"] += 1
                continue
            scored = []
            for c in cands:
                if re.search(re.escape(c) + SIZE_ANY, bound):
                    link = "reread"
                elif bound_rhs and re.search(re.escape(c) + SIZE_ANY, bound_rhs):
                    link = "cached"
                else:
                    link = "unlinked"
                scored.append((link != "unlinked", c.startswith("m_"), link, c))
            scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
            _l, _mem, bkind, container = scored[0]
            rhs = bound_rhs if bkind == "cached" else None
            if descending:
                # `i = m_foo.size() - 1` is evaluated once, so this is a cached bound even though the text
                # contains `.size()`.
                bkind = "cached"
                rhs = init_rhs.strip()
            first_read = first_read_of[container]

            fi = bisect.bisect_right(fstarts, m.start()) - 1
            fname = funcs[fi][0] if 0 <= fi < len(funcs) else "?"
            owner_class = fname.rsplit("::", 1)[0].split("::")[-1] if "::" in fname else ""
            if not owner_class:
                best = None
                for c, ob, cb in scopes:
                    if ob < m.start() < cb and (best is None or ob > best):
                        best, owner_class = ob, c

            is_member = container.startswith("m_")
            dtype, drhs, dalias = "", "", False
            owner = container if is_member else None
            if not is_member:
                dtype, drhs, dalias = local_decl(clean, container, m.start())
                if dalias and re.match(r"^(?:this->)?m_[A-Za-z_]\w*$", drhs.split(".")[0]):
                    owner = drhs
            if is_member:
                ctype = members.get((owner_class, container), "") or flat_members.get(container, "")
            else:
                ctype = dtype
                if owner and owner != container and not ctype:
                    ctype = members.get((owner_class, owner), "") or flat_members.get(owner, "")

            # ---- window analysis -------------------------------------------------------------------
            mut = sorted({mm.group(1) for mm in
                          re.finditer(r"(?<![\w.>])%s\s*(?:->|\.)\s*(%s)\s*\(" %
                                      (re.escape(container), "|".join(MUTATORS)), body)})
            dir_hits = sorted({mm.group(0)[:-1] for mm in DIRECT_RE.finditer(body)})
            names = call_names(body)
            trans = []
            for n in sorted(names):
                d = sink_route(n, direct, callees, defs, 2)
                if d is not None and d >= 1:
                    trans.append((n, d))
            cb = sorted({mm.group(2) for mm in CALLBACK_RECV.finditer(body)
                         if CALLBACK_NAME.match(mm.group(2)) or CLIENT_RECV.match(mm.group(1))})
            elem_calls = sorted({mm.group(1) for mm in re.finditer(
                r"(?<![\w.>])%s\s*(?:\[[^\]]{0,80}\]|(?:->|\.)?at\s*\([^)]{0,80}\))\s*(?:->|\.)\s*(\w+)\s*\("
                % re.escape(container), body)})
            # The common spelling reads the element into a local first (`auto& run = m_runs[i];`) and then
            # calls on the local. Without this, a loop that calls a virtual on every element looks like it
            # has no call at all — which is what made this tool's third run report 2 windows in 1189 loops.
            elem_locals = {}
            for mm in re.finditer(r"\b(?:auto|const\s+auto|auto\s*\*|const\s+auto\s*\*)\s*(&{0,2})\s*"
                                  r"([A-Za-z_]\w*)\s*=\s*(?<![\w.>])%s\s*(?:\[[^\]]{0,80}\]|\.at\s*\([^)]{0,80}\))"
                                  % re.escape(container), body):
                elem_locals[mm.group(2)] = mm.group(1)
            for lname in elem_locals:
                for mm in re.finditer(r"(?<![\w.>])%s\s*(?:->|\.)\s*(\w+)\s*\(" % re.escape(lname), body):
                    elem_calls.append(mm.group(1))
            elem_calls = sorted(set(elem_calls))
            etype = element_type(ctype)
            elem_bodies = {}
            for en in elem_calls:
                eb = methods.get((etype, en)) if etype else None
                if eb:
                    elem_bodies[en] = {
                        "sinks": sorted({mm.group(0)[:-1] for mm in DIRECT_RE.finditer(eb)}),
                        "calls": sorted(call_names(eb))[:12],
                        "mutators": sorted({mm.group(0).strip() for mm in
                                            re.finditer(r"(?<![\w.>])\w+\s*(?:->|\.)\s*(?:%s)\s*\(" %
                                                        "|".join(MUTATORS), eb)}),
                        "len": len(eb),
                    }
            # Calls on `this` (`this->updateStyleIfNeeded()` or a bare `updateStyleIfNeeded()`): resolve them
            # against the owning class's own method table. That is the one route a bare-name index cannot take
            # without colliding with the hundreds of same-named functions in the tree.
            self_bodies = {}
            if owner_class:
                for n in sorted(names):
                    if n in ("if", "for", "while", "switch", "return", "sizeof", "ASSERT", "ASSERT_NOT_REACHED"):
                        continue
                    sb = methods.get((owner_class, n))
                    if sb and len(sb) > 40:
                        sinks = sorted({mm.group(0)[:-1] for mm in DIRECT_RE.finditer(sb)})
                        if sinks:
                            self_bodies[n] = {"sinks": sinks, "len": len(sb)}
            elem_iface = bool(INTERFACE_TYPE.search(ctype))
            window = []
            for p in set(DIRECT_RE.findall(body)):
                k = body.find(p)
                if k >= 0:
                    window.append((k, "direct:" + p[:-1]))
            for t in trans:
                k = body.find(t[0] + "(")
                if k >= 0:
                    window.append((k, "trans:" + t[0]))
            for cn in cb:
                k = body.find(cn)
                if k >= 0:
                    window.append((k, "recv:" + cn))
            for sn in self_bodies:
                k = body.find(sn + "(")
                if k >= 0:
                    window.append((k, "self:" + sn))
            for en in elem_calls:
                if en in elem_locals:
                    continue
                info = elem_bodies.get(en)
                if info and info["sinks"]:
                    k = body.find(en)
                    if k >= 0:
                        window.append((k, "elembody:" + en))
                elif elem_iface or CALLBACK_NAME.match(en) or CLIENT_RECV.match(en):
                    k = body.find(en)
                    if k >= 0:
                        window.append((k, "elem:" + en))
            window.sort()
            first_sink = window[0][0] if window else -1
            # A reference bound to a vector element and *used after* the window is the reallocation bug: an
            # append inside the window can move the buffer and leave the reference dangling. This is a
            # different failure from a stale bound, and an index loop is the only spelling that can do it
            # while also visiting the appended elements.
            ref_after = None
            for lname, amp in elem_locals.items():
                if not amp or first_sink < 0:
                    continue
                uses = [u.start() for u in re.finditer(r"(?<![\w.>])%s(?![\w])" % re.escape(lname), body)]
                later = [u for u in uses if u > first_sink]
                if later:
                    ref_after = lname
                    break
            # A read *after* a window in the same iteration is only part of the story: with a cached bound,
            # a shrink anywhere in the body invalidates the bound for the NEXT iteration, whose `c[i]` read
            # then happens after the script ran. Both spellings are recorded.
            read_positions = [h.start() for h in idx_re.finditer(body)
                              if h.group(1) == container]
            read_after_window = bool(window) and any(p > first_sink for p in read_positions)
            rows.append({
                "file": rel, "line": lineno(starts, m.start()), "function": fname, "class": owner_class,
                "index": ivar, "cond_op": op, "bound": bound, "bound_kind": bkind, "bound_rhs": rhs,
                "container": container, "container_decl": dtype, "container_rhs": drhs,
                "container_alias": dalias, "owner": owner,
                "container_type": ctype, "element": element_class(ctype), "element_type": etype,
                "mutations": mut, "direct_sinks": dir_hits,
                "transitive": [{"callee": t[0], "depth": t[1]} for t in trans],
                "callback_calls": cb, "element_calls": elem_calls,
                "element_call_bodies": elem_bodies, "element_interface": elem_iface,
                "self_call_bodies": self_bodies,
                "element_locals": sorted(elem_locals),
                "window": [{"pos": k, "kind": v} for k, v in window],
                "first_script_pos": first_sink, "first_read_pos": first_read,
                "read_after_window": read_after_window, "ref_used_after_window": ref_after,
                "script_before_read": 0 <= first_sink < first_read,
                "index_reads": len(list(idx_re.finditer(body))),
            })
            counter["loops"] += 1
            if bkind == "unlinked":
                counter["container-unlinked-to-bound"] += 1

    def verdict(r):
        any_window = bool(r["window"])
        on_owner = bool(r["owner"])
        cached = r["bound_kind"] == "cached"
        mutated = bool(r["mutations"])
        body_sinks = any(v["sinks"] for v in r["element_call_bodies"].values())
        # raw elements: a window can free an element that the container still points at, and the next
        # iteration dereferences it.
        if on_owner and any_window and r["element"] == "raw":
            return "ELEMENT-RAW"
        # cached bound: a shrink anywhere in the body breaks the NEXT iteration's read.
        # Any bound that is not the container's own `.size()` is cached *with respect to that container*:
        # `i < m_count`, `i < originalSize`, `i < numberOfInputs()` all stay put when the vector shrinks.
        if on_owner and any_window and (cached or mutated or r["bound_kind"] == "unlinked"):
            return "SHRINK-CACHED" if cached else ("SHRINK-MUTATED" if mutated else "SHRINK-SCALAR")
        if on_owner and any_window:
            return "OWNER-WINDOW"
        if any_window and body_sinks:
            return "LOCAL-ELEMENTBODY"
        if any_window:
            return "LOCAL-WINDOW"
        return "inert"

    for r in rows:
        r["verdict"] = verdict(r)

    summary = {"files": len(files), "loops": len(rows), "funnel": dict(counter),
               "verdicts": dict(Counter(r["verdict"] for r in rows)),
               "bound_kinds": dict(Counter(r["bound_kind"] for r in rows)),
               "rows": rows}
    json.dump(summary, sys.stdout, indent=1)
    print("files %d loops %d" % (len(files), len(rows)), file=sys.stderr)
    print("funnel %s" % dict(counter), file=sys.stderr)
    print("verdicts %s" % dict(Counter(r["verdict"] for r in rows)), file=sys.stderr)
    print("bound_kinds %s" % dict(Counter(r["bound_kind"] for r in rows)), file=sys.stderr)


if __name__ == "__main__":
    main()
