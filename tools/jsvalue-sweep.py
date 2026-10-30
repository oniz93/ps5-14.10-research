#!/usr/bin/env python3
"""Inventory of raw JSValue / JSCell* storage in the drop (docs/77).

    python3 tools/jsvalue-sweep.py > data/jsvalue-sweep/inventory.json

Why this class: docs/76 closed the one `CachedString` instance and showed that a raw `JSValue`
member of a heap C++ object is the only way this drop frees a JSCell from plain JavaScript — the
GC cannot see such a field (conservative stack scanning covers the stack, docs/75; a `WriteBarrier`
field of a JSCell is visited through its owner's visitChildren; a raw field of a *non*-GC object is
visited by nobody).

So the tool does not look for script sinks (docs/69-75 did that). It looks for *storage*:

  MEMBER   declaration at class/struct body depth (the interesting class: lives in the heap)
  LOCAL    declaration inside a function body (a conservative-scan root, docs/75 — not a window)
  PARAM    function parameter (same as LOCAL)
  RETURN   return type

and flags whether the keeping wrappers (`MarkedVector`, `MarkedArgumentBuffer`, `Strong<>`,
`WriteBarrier`, `Protect`, `JSValueInWrappedObject`, `Weak<>`, `Handle`, `EnsureStillAliveScope`,
`LazyProperty`) are on the declaration. For MEMBER rows it also looks for an owner-side marking
path: `Class::visitChildren*` mentioning the field, or a `visitor.append`/`visitor.visit` of it.

The tool is a net, not a verdict: a MEMBER row still has to be read for (a) whether the field can
hold a *cell* at all, (b) whether the containing object is heap-allocated, and (c) whether an
allocation/GC can run between the store and the load.
"""
import os, re, sys, json

SOURCES = [
    ("WebCore", "out/sony/full/WebKit-1400/WebKit-1400/Source/WebCore"),
    ("JavaScriptCore", "out/sony/full/WebKit-1400/WebKit-1400/Source/JavaScriptCore"),
]

CELL_TYPES = [
    "JSValue", "JSCell", "JSObject", "JSString", "JSFunction", "JSArray",
    "JSGlobalObject", "JSModuleLoader", "JSInternalPromise", "JSPromise",
]
KEEPING = [
    "MarkedVector", "MarkedArgumentBuffer", "Strong<", "Strong ", "WriteBarrier",
    "Protect", "JSValueInWrappedObject", "Weak<", "Weak ", "Handle<", "EnsureStillAliveScope",
    "LazyProperty", "WeakGCMap", "GCReachableRef", "RefPtr", "Ref<",
]
# Types whose members are containers we still want to see (a raw cell inside one is the bug shape).
CONTAINERS = ["Vector", "FixedVector", "HashMap", "HashSet", "std::array", "std::optional", "std::pair"]

BS = chr(92); DQ = chr(34); SQ = chr(39); NL = chr(10)


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


DECL = re.compile(
    r"(?<![\w:.>])(?:(?:JSC|WTF)::)?(" + "|".join(CELL_TYPES) + r")(?![\w])"
    r"\s*(const\s*)?(\*{0,2})\s*(?:const\s*)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?=[;{=,\[)])"
)


def scope_map(clean):
    """Return a list of (offset, kind, name) scope openers: kind in {class, struct, function, block}."""
    scopes = []
    # find class/struct/namespace/function openers with a crude scan
    pat = re.compile(r"\b(class|struct|namespace|union)\s+([A-Za-z_][A-Za-z0-9_:<>]*)?")
    for m in pat.finditer(clean):
        # find the brace that opens this class body (skip forward past base list / semicolons)
        i = m.end(); n = len(clean); depth = 0
        while i < n:
            c = clean[i]
            if c == "(": i = match_paren(clean, i); continue
            if c == "{":
                scopes.append((i, m.group(1), m.group(2) or "")); break
            if c == ";": break
            i += 1
    return scopes


def match_paren(clean, open_i):
    depth = 0; k = open_i; n = len(clean)
    while k < n:
        if clean[k] == "(": depth += 1
        elif clean[k] == ")":
            depth -= 1
            if depth == 0: return k + 1
        k += 1
    return n


def build_scope_starts(clean):
    """Map brace offset -> declaration of the enclosing class/struct (for MEMBER detection)."""
    class_starts = {}
    for off, kind, name in scope_map(clean):
        class_starts[off] = (kind, name)
    return class_starts


def paren_depth_array(clean):
    n = len(clean); depth = [0] * (n + 1); d = 0
    for i, c in enumerate(clean):
        depth[i] = d
        if c == "(": d += 1
        elif c == ")": d = max(0, d - 1)
    depth[n] = d
    return depth


def brace_depth_array(clean):
    """depth[i] = number of unmatched '{' before position i."""
    n = len(clean); depth = [0] * (n + 1); d = 0
    for i, c in enumerate(clean):
        depth[i] = d
        if c == "{": d += 1
        elif c == "}": d = max(0, d - 1)
    depth[n] = d
    return depth


def build_class_ranges(clean):
    """Sorted list of (body_start, body_end, kind, name) for every class/struct/union body."""
    ranges = []
    for off, kind, name in scope_map(clean):
        depth = 0; i = off; n = len(clean)
        while i < n:
            if clean[i] == "{": depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0: break
            i += 1
        ranges.append((off, i, kind, name))
    ranges.sort()
    return ranges


def enclosing_class(ranges, pos):
    best = None
    for off, end, kind, name in ranges:
        if off >= pos:
            break
        if pos < end:
            best = (off, kind, name)
    return best


def is_in_function_body(clean, class_starts, pos):
    """True if pos sits inside a brace block that is NOT a class body (i.e. a function/block)."""
    # crude: look backwards for the nearest unmatched '{' and ask whether it was a class body
    i = pos; depth = 0
    while i >= 0:
        if clean[i] == "}": depth += 1
        elif clean[i] == "{":
            if depth == 0:
                return i not in class_starts
            depth -= 1
        i -= 1
    return False


def keeping_near(line):
    hits = [k.strip() for k in KEEPING if k in line]
    return hits


def main():
    rows = []
    counts = {}
    for tree, root in SOURCES:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not (fn.endswith(".h") or fn.endswith(".cpp") or fn.endswith(".mm")):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    src = open(path, "r", errors="replace").read()
                except OSError:
                    continue
                clean = strip_comments_strings(src)
                lines = src.split(NL)
                class_starts = build_scope_starts(clean)
                ranges = build_class_ranges(clean)
                pdepth = paren_depth_array(clean)
                for m in DECL.finditer(clean):
                    typ, cst, stars, name = m.group(1), m.group(2), m.group(3), m.group(4)
                    pos = m.start()
                    line_start = clean.rfind(NL, 0, pos) + 1
                    line_end = clean.find(NL, pos)
                    line_end = len(clean) if line_end < 0 else line_end
                    line = clean[line_start:line_end]
                    raw_line = lines[src[:pos].count(NL)] if src[:pos].count(NL) < len(lines) else ""
                    # skip function declarations/definitions: name followed by '('
                    after = clean[m.end():m.end() + 40].lstrip()
                    if pdepth[pos] > 0:
                        kind = "param"
                    elif after.startswith("("):
                        kind = "function"
                    elif is_in_function_body(clean, class_starts, pos):
                        kind = "local"
                    else:
                        enc = enclosing_class(ranges, pos)
                        if enc:
                            kind = "member"
                        else:
                            kind = "unknown"
                    if kind == "function":
                        continue
                    keep = keeping_near(line)
                    enc = enclosing_class(ranges, pos)
                    if re.match(r"^\s*(class|struct)\b", line) or ": public" in line or ": private" in line or ": protected" in line:
                        continue  # base-class list, not storage
                    if "typedef" in line or re.match(r"^\s*using\b", line) or "static constexpr" in line:
                        continue  # alias / constant, not storage

                    row = {
                        "tree": tree,
                        "file": path.split("Source/", 1)[1],
                        "line": src[:pos].count(NL) + 1,
                        "kind": kind,
                        "type": typ + stars + (" const" if cst else ""),
                        "name": name,
                        "class": enc[2] if enc and kind == "member" else "",
                        "keeping": keep,
                        "text": raw_line.strip()[:200],
                    }
                    rows.append(row)
    # ---- owner-side marking analysis ----
    # JSC marks raw fields with `visitor.append*(...)` / `visitor.visit*(...)` inside a
    # visitChildren/visitAggregate definition, often in a different file (or a macro). So the test
    # is: does any line that mentions `visitor` in the owner's file(s) also mention the field?
    cache = {}

    def mark_sources(row):
        base = row["file"].rsplit(".", 1)[0]
        out = []
        for cand in (base + ".cpp", base + ".h"):
            path = "out/sony/full/WebKit-1400/WebKit-1400/Source/" + cand
            if path in cache:
                out.append(cache[path]); continue
            try:
                txt = strip_comments_strings(open(path, "r", errors="replace").read())
            except OSError:
                txt = ""
            cache[path] = txt
            out.append(txt)
        return out

    for r in rows:
        if r["kind"] != "member":
            continue
        marked = "no-visitor-line"
        for txt in mark_sources(r):
            for line in txt.split(NL):
                if "visitor" in line and re.search(r"\b" + re.escape(r["name"]) + r"\b", line):
                    marked = "marked"
                    break
            if marked == "marked":
                break
        r["owner_marks"] = marked

    # ---- summary ----
    def key(r):
        return (r["tree"], r["kind"])
    for r in rows:
        counts[key(r)] = counts.get(key(r), 0) + 1
    members = [r for r in rows if r["kind"] == "member"]
    from collections import Counter
    print("OWNER-MARK:", Counter((r["tree"], r.get("owner_marks")) for r in members), file=sys.stderr)
    unkept_members = [r for r in members if not r["keeping"]]
    print(json.dumps({
        "total": len(rows),
        "counts": {"%s/%s" % k: v for k, v in sorted(counts.items())},
        "members": len(members),
        "unkept_members": len(unkept_members),
        "unkept_member_rows": unkept_members,
        "rows": rows,
    }, indent=1))


if __name__ == "__main__":
    main()
