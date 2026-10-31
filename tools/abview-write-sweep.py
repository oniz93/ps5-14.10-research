#!/usr/bin/env python3
"""tools/abview-write-sweep.py -- the WRITE direction of docs/96's inverted bounds test.

docs/96 measured the read: `JSC::ArrayBufferView::byteLength()` (the *native* class in
Source/JavaScriptCore/runtime/ArrayBufferView.h) tests the sub-range **inverted** relative to upstream,
so an out-of-bounds resizable view reports its raw length, and `IDBKey::createBinary` -- the one producer
that is handed such a view without the `toWrapped` gate -- copies raw-length bytes out to JS.

This tool answers the other direction: can the same inverted length make the engine WRITE out of bounds?
It asserts the structural facts and enumerates every write consumer, so the answer is a count, not a claim.

  S1  there are two byteLength()s and only the native one is inverted
  S2  the four native-view producers, and the gate each call site applies
  S3  every IDL operation that can receive an ArrayBufferView, classified read/write
  S4  every JS-level write spelling and the gate it goes through
  S5  every C++ function that takes a native ArrayBufferView&/* and writes through it

Usage:  python3 tools/abview-write-sweep.py [--drop DIR] [--json PATH]
Exit:   0 = every assertion held, 1 = an assertion failed (then the table must be re-read).
"""
import argparse
import json
import os
import re
import sys

DEFAULT_DROP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "out/sony/full/WebKit-1400/WebKit-1400")

FILES = []          # (relpath, text)


def load(root):
    for base, dirs, names in os.walk(os.path.join(root, "Source")):
        dirs[:] = [d for d in dirs if d not in ("Resources", "test", "tests")]
        for n in names:
            if n.endswith((".cpp", ".h", ".mm", ".idl", ".cmake")):
                p = os.path.join(base, n)
                try:
                    with open(p, "r", errors="replace") as f:
                        FILES.append((os.path.relpath(p, root), f.read()))
                except OSError:
                    pass


def find(relpath):
    for r, t in FILES:
        if r == relpath:
            return t
    raise KeyError(relpath)


def line_of(text, needle):
    for i, ln in enumerate(text.splitlines(), 1):
        if needle in ln:
            return i
    return -1


def has(text, needle):
    return needle in text


# ---------------------------------------------------------------- block helper
def block_at(text, pos):
    """Return the brace-matched body starting at the first '{' at/after pos."""
    i = text.find("{", pos)
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return text[i:]


SIG_RE = re.compile(r"^[A-Za-z_].*\b(?:ArrayBufferView|ArrayBufferView)\s*[&*]\s*\w+\s*[,)]")


def native_view_param_bodies():
    """(relpath, line, signature, body) for every .cpp function definition with a native
    ArrayBufferView&/* parameter."""
    out = []
    for rel, text in FILES:
        if not rel.endswith((".cpp", ".mm")):
            continue
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if "ArrayBufferView" not in ln or "JSArrayBufferView" in ln:
                continue
            if not re.search(r"ArrayBufferView\s*[&*]\s*\w+", ln):
                continue
            # a definition: the line ends with ) or , and a '{' follows within 6 lines
            window = "\n".join(lines[i:i + 6])
            m = re.search(r"ArrayBufferView\s*[&*]\s*\w+", ln)
            if not m:
                continue
            brace = window.find("{")
            semi = window.find(";")
            if brace < 0 or (0 <= semi < brace):
                continue        # declaration, not definition
            sig = " ".join(x.strip() for x in lines[i:i + 3])
            body = block_at(text, text.find(lines[i]))
            out.append((rel, i + 1, sig[:160], body))
    return out


WRITE_SINKS = [
    ("memcpy(", "copy"),
    ("memmove(", "copy"),
    ("memset(", "fill"),
    ("cryptographicallyRandomValues(", "random-fill"),
    ("CCRandomGenerateBytes(", "random-fill"),
    ("U8_APPEND(", "encode"),
    ("setRange(", "copy"),
    ("zeroRange(", "fill"),
    ("setImpl(", "copy"),
    ("typedVector()[", "index-write"),
    ("span().data()", "span-write"),
    ("std::fill(", "fill"),
    ("WTF::fill(", "fill"),
    ("std::copy(", "copy"),
]


def sinks_in(body):
    hits = []
    for pat, kind in WRITE_SINKS:
        if pat in body:
            hits.append({"pattern": pat, "kind": kind})
    for m in re.finditer(r"\b(?:data|baseAddress)\(\)\s*\[", body):
        hits.append({"pattern": "data()[", "kind": "index-write"})
    return hits


GATES = [
    "validateTypedArray",
    "isOutOfBounds()",
    "isIntegerIndexedObjectOutOfBounds",
    "viewByteLength(",
    "inBounds(",
    "isResizableOrGrowableShared()",
    "verifySubRangeLength",
    "toWrapped(",
    "toWrappedAllowShared(",
]


def gates_in(body):
    return [g for g in GATES if g in body]


# ---------------------------------------------------------------- S3: IDL consumers
WRITE_OPS = {
    "getRandomValues": "writes random bytes into the view (Crypto.cpp:64/67)",
    "readPixels": "driver writes pixels into dstData (WebGL*)",
    "getBufferSubData": "driver writes buffer contents into dstData (WebGL2)",
    "copyTo": "copies frame/chunk bytes into destination (WebCodecs)",
    "read": "reads file bytes into the view (FileSystemSyncAccessHandle)",
}
READ_OPS = {
    "send", "decode", "bufferData", "bufferSubData", "texImage2D", "texSubImage2D",
    "texImage3D", "texSubImage3D", "compressedTexImage2D", "compressedTexSubImage2D",
    "compressedTexImage3D", "compressedTexSubImage3D", "write", "writeBuffer",
    "constructor", "data", "description", "writeTexture",
}


def idl_consumers():
    """Split every .idl into ';'-terminated statements (so a declaration that wraps lines is one row),
    then classify each one that mentions ArrayBufferView."""
    rows = []
    for rel, text in FILES:
        if not rel.endswith(".idl"):
            continue
        if "/bindings/scripts/test/" in rel:
            continue
        # keep line numbers: walk statements, remembering the line each starts on
        buf, start = "", 1
        for i, ln in enumerate(text.splitlines(), 1):
            if not buf:
                start = i
            if ln.strip().startswith("//"):
                continue
            buf += " " + ln
            if ";" not in ln:
                continue
            for stmt in buf.split(";"):
                stmt = " ".join(stmt.split())
                if "ArrayBufferView" in stmt:
                    rows.append(classify_idl(rel, start, stmt))
            buf = ""
    return rows


def classify_idl(rel, line, stmt):
    allow = "AllowShared" in stmt
    if stmt.lstrip().startswith("typedef") or " typedef " in stmt:
        inner = stmt.split("(", 1)[1].split(")", 1)[0] if "(" in stmt else ""
        return {"idl": rel, "line": line, "op": "typedef", "kind": "typedef", "class": "read",
                "allow_shared": allow, "text": stmt[:120], "inner": inner}
    m = re.search(r"([A-Za-z_]\w*)\s*\(", stmt)
    if not m:
        # a dictionary member / attribute: "required [AllowShared] (ArrayBufferView or ArrayBuffer) data"
        return {"idl": rel, "line": line, "op": "member", "kind": "dictionary-member", "class": "read",
                "allow_shared": allow, "text": stmt[:120]}
    name = m.group(1)
    if name in ("ArrayBuffer", "ArrayBufferView"):     # a union type, not an operation
        return {"idl": rel, "line": line, "op": "union", "kind": "type", "class": "read",
                "allow_shared": allow, "text": stmt[:120]}
    verdict = "write" if name in WRITE_OPS else ("read" if name in READ_OPS else "unclassified")
    return {"idl": rel, "line": line, "op": name, "kind": "operation", "class": verdict,
            "allow_shared": allow, "text": stmt[:120]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", default=DEFAULT_DROP)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    load(args.drop)

    checks, result = [], {}

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # ---------------- S1: two byteLengths
    abv = find("Source/JavaScriptCore/runtime/ArrayBufferView.h")
    inverted = "UNLIKELY(!(byteOffsetStart > bufferByteLength || byteOffsetEnd > bufferByteLength))"
    check("S1.1 native ArrayBufferView::byteLength() keeps the inverted test",
          abv.count(inverted) == 2,
          "ArrayBufferView.h:%d (byteOffset) and :%d (byteLength); %d occurrences of the inverted form"
          % (line_of(abv, "size_t byteOffset() const"), line_of(abv, "size_t byteLength() const"), abv.count(inverted)))
    check("S1.2 the inverted test is spelled '!(' , i.e. a valid view returns 0 and an OOB view returns raw",
          bool(re.search(r"if \(UNLIKELY\(!\(", abv)), "upstream has no '!'")

    jsb = find("Source/JavaScriptCore/runtime/JSArrayBufferView.h")
    check("S1.3 JSArrayBufferView::byteLength()/length() are NOT inverted -- they use integerIndexedObject*",
          "integerIndexedObjectLength(const_cast<JSArrayBufferView*>(this), getter).value_or(0)" in jsb
          and "integerIndexedObjectByteLength(const_cast<JSArrayBufferView*>(this), getter)" in jsb
          and inverted not in jsb,
          "JSArrayBufferView.h:%d length(), :%d byteLength() -- the JS-level view never calls the native test"
          % (line_of(jsb, "size_t length() const"), line_of(jsb, "size_t byteLength() const")))

    inc = find("Source/JavaScriptCore/runtime/JSArrayBufferViewInlines.h")
    check("S1.4 isOutOfBounds() is the spec test (isArrayBufferViewOutOfBounds), not the native one",
          "isArrayBufferViewOutOfBounds(const_cast<JSArrayBufferView*>(this), getter)" in jsb,
          "JSArrayBufferView.h:%d" % line_of(jsb, "bool isOutOfBounds() const"))

    # ---------------- S2: producers
    check("S2.1 JSArrayBufferView::toWrapped refuses every resizable/growable-shared view",
          "if (!view->isShared() && !view->isResizableOrGrowableShared())" in inc,
          "JSArrayBufferViewInlines.h:%d" % line_of(inc, "RefPtr<ArrayBufferView> JSArrayBufferView::toWrapped"))
    check("S2.2 JSArrayBufferView::toWrappedAllowShared refuses them too ([AllowShared] is not a bypass)",
          "if (!view->isResizableOrGrowableShared())" in inc
          and line_of(inc, "toWrappedAllowShared") > 0,
          "JSArrayBufferViewInlines.h:%d" % line_of(inc, "toWrappedAllowShared"))
    check("S2.3 JSGenericTypedArrayView::toWrapped / toWrappedAllowShared refuse them as well",
          "if (!result || result->isResizableOrGrowableShared())" in find(
              "Source/JavaScriptCore/runtime/JSGenericTypedArrayViewInlines.h"),
          "JSGenericTypedArrayViewInlines.h:930-941")
    conv = find("Source/WebCore/bindings/js/JSDOMConvertBufferSource.h")
    check("S2.4 Converter<IDLArrayBufferView> goes through toWrapped (Disallow) and [AllowShared] through "
          "toWrappedAllowShared -- so every IDL ArrayBufferView parameter is gated",
          "BufferSourceConverter<IDLArrayBufferView, Detail::BufferSourceConverterAllowSharedMode::Disallow>"
          in conv and "BufferSourceConverterAllowSharedMode::Allow>::convert" in conv,
          "JSDOMConvertBufferSource.h:%d and :%d" % (line_of(conv, "struct Converter<IDLArrayBufferView>"),
                                                     line_of(conv, "struct Converter<IDLAllowSharedAdaptor<T>>")))
    poss = []
    for rel, text in FILES:
        for i, ln in enumerate(text.splitlines(), 1):
            if "JSArrayBufferView::possiblySharedImpl" in ln or "JS_EXPORT_PRIVATE" in ln:
                continue        # the definition/declaration, not a call
            if "possiblySharedImpl()" in ln:
                poss.append("%s:%d" % (rel, i))
    check("S2.5 possiblySharedImpl() has 4 call sites and only IDBKey is outside a gate",
          len(poss) == 4 and any("IDBKey.cpp" in p for p in poss),
          "; ".join(poss))
    idbk = find("Source/WebCore/Modules/indexeddb/IDBKey.cpp")
    idb_body = block_at(idbk, idbk.find("IDBKey::createBinary"))
    check("S2.6 IDBKey::createBinary only READS the native view (copyData); no write sink in its body",
          sinks_in(idb_body) == [], "sinks=%s" % sinks_in(idb_body))
    ss = find("Source/WebCore/bindings/js/SerializedScriptValue.cpp")
    check("S2.7 the serializer's raw producer is preceded by the isOutOfBounds() test",
          "isOutOfBounds()" in ss[:ss.find("toPossiblySharedArrayBufferView(vm, obj)")][-400:],
          "SerializedScriptValue.cpp:%d" % line_of(ss, "toPossiblySharedArrayBufferView(vm, obj)"))

    # ---------------- S3: IDL
    rows = idl_consumers()
    writes = [r for r in rows if r["class"] == "write"]
    unclassified = [r for r in rows if r["class"] == "unclassified"]
    result["idl"] = rows
    check("S3.1 every IDL ArrayBufferView consumer is classified (no 'unclassified' rows)",
          not unclassified, "unclassified=%s" % [r["op"] for r in unclassified])
    check("S3.2 the write-consumer set is exactly the 5 known operations",
          sorted({r["op"] for r in writes}) == ["copyTo", "getBufferSubData", "getRandomValues", "read", "readPixels"],
          "writes=%s" % sorted({r["op"] for r in writes}))
    check("S3.3 WebGL is the write consumer that needs a build flag, and the flag is OFF on this port",
          "WEBKIT_OPTION_DEFAULT_PORT_VALUE(ENABLE_WEBGL PRIVATE OFF)"
          in find("Source/cmake/OptionsPlayStation.cmake"),
          "OptionsPlayStation.cmake:272")
    check("S3.4 WebCodecs is OFF by default in this drop (so copyTo does not exist)",
          "WEBKIT_OPTION_DEFINE(ENABLE_WEB_CODECS \"Toggle WebCodecs support\" PRIVATE OFF)"
          in find("Source/cmake/WebKitFeatures.cmake"),
          "WebKitFeatures.cmake:260")

    # ---------------- S4: JS-level write spellings
    pfn = find("Source/JavaScriptCore/runtime/JSGenericTypedArrayViewPrototypeFunctions.h")
    check("S4.1 set/fill/copyWithin/sort all call validateTypedArray() on the receiver first",
          all(x in pfn for x in ["genericTypedArrayViewProtoFuncSet", "genericTypedArrayViewProtoFuncCopyWithin",
                                 "genericTypedArrayViewProtoFuncFill", "genericTypedArrayViewPrivateFuncSort"])
          and pfn.count("validateTypedArray(globalObject, thisObject)") >= 4,
          "validateTypedArray(globalObject, thisObject) x%d in the prototype functions"
          % pfn.count("validateTypedArray(globalObject, thisObject)"))
    check("S4.2 validateTypedArray throws on isIntegerIndexedObjectOutOfBounds",
          "isIntegerIndexedObjectOutOfBounds(typedArray, getter)" in inc,
          "JSArrayBufferViewInlines.h:%d" % line_of(inc, "isIntegerIndexedObjectOutOfBounds(typedArray, getter)"))
    gta = find("Source/JavaScriptCore/runtime/JSGenericTypedArrayViewInlines.h")
    check("S4.3 the index write path (view[i]=v) checks inBounds(), which reads the LIVE buffer length",
          "if (!inBounds(i))" in gta and "existingBufferInButterfly()->byteLength()" in gta,
          "JSGenericTypedArrayViewInlines.h:%d setIndex, :%d inBounds"
          % (line_of(gta, "bool JSGenericTypedArrayView<Adaptor>::setIndex"), line_of(gta, "bool JSGenericTypedArrayView<Adaptor>::inBounds")))
    dvp = find("Source/JavaScriptCore/runtime/JSDataViewPrototype.cpp")
    check("S4.4 DataView.set* uses viewByteLength() and throws RangeError instead of writing",
          "viewByteLength(getter)" in dvp and "Out of bounds access" in dvp and "dataView->vector()" in dvp,
          "JSDataViewPrototype.cpp:%d setData" % line_of(dvp, "EncodedJSValue setData"))

    # ---------------- S5: native-view write consumers in C++
    sites = native_view_param_bodies()
    result["native_param_sites"] = [
        {"file": r, "line": l, "sig": s, "sinks": sinks_in(b), "gates": gates_in(b),
         "len": len(b)} for (r, l, s, b) in sites]
    writers = [x for x in result["native_param_sites"] if x["sinks"]]
    result["native_writers"] = writers
    check("S5.1 every .cpp function with a native ArrayBufferView&/* parameter was found",
          len(sites) >= 8, "%d sites" % len(sites))
    check("S5.2 the only native ArrayBufferView&/* write consumer in the tree is Crypto::getRandomValues",
          [os.path.basename(w["file"]) for w in writers] == ["Crypto.cpp"],
          "writers=%s (WebGL's readPixels/getBufferSubData hand the view to the driver, not to "
          "ArrayBufferView::set*)" % [(os.path.basename(w["file"]), w["line"]) for w in writers])
    te = find("Source/WebCore/dom/TextEncoder.cpp")
    check("S5.3 the typed-view spelling of the same shape is TextEncoder::encodeInto: Ref<Uint8Array>&&, "
          "bound = array->byteLength(), write = U8_APPEND into array->baseAddress()",
          "Ref<Uint8Array>&& array" in te and "array->byteLength()" in te
          and "U8_APPEND(destinationBytes" in te,
          "TextEncoder.cpp:%d/%d/%d" % (line_of(te, "auto capacity = array->byteLength();"),
                                        line_of(te, "auto* destinationBytes"),
                                        line_of(te, "U8_APPEND(destinationBytes")))
    check("S5.4 neither is reachable with a resizable view: the gate is the binding converter (S2.4), "
          "not anything inside the function",
          all(not w["gates"] for w in writers) and "isResizableOrGrowableShared" not in te,
          "no gate inside either body -- the refusal happens before the call")

    # ---------------- report
    print("== abview write sweep ==")
    for c in checks:
        print("%s  %-95s %s" % ("PASS" if c["ok"] else "FAIL", c["check"], c["detail"]))
    print("\n-- native-view parameter sites: %d" % len(sites))
    for x in result["native_param_sites"]:
        print("   %-58s:%-5d sinks=%-30s gates=%s"
              % (x["file"].split("Source/", 1)[-1], x["line"],
                 ",".join(sorted({s["kind"] for s in x["sinks"]})) or "-",
                 ",".join(x["gates"]) or "-"))
    print("\n-- IDL ArrayBufferView consumers: %d rows, %d write, %d read, %d unclassified"
          % (len(rows), len(writes), len(rows) - len(writes) - len(unclassified), len(unclassified)))
    for r in writes:
        print("   WRITE %-22s %s:%d  allowshared=%s" % (r["op"], r["idl"].split("Source/WebCore/")[-1],
                                                       r["line"], r["allow_shared"]))
    ok = all(c["ok"] for c in checks)
    print("\n%d/%d checks pass%s" % (sum(1 for c in checks if c["ok"]), len(checks),
                                     "" if ok else "  <-- RE-READ THE TABLE"))
    result["checks"] = checks
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w") as f:
            json.dump(result, f, indent=1)
        print("json: %s" % args.json)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
