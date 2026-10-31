#!/usr/bin/env python3
"""docs/96 — the reachability audit behind the IDB out-of-bounds read.

The question is narrow and mechanical: `ArrayBufferView::byteOffset()/byteLength()` test the bounds INVERTED
relative to upstream (docs/95 §6), so any consumer that is handed an out-of-bounds *resizable* view reads the
view's raw length instead of 0. Which producers of a WebCore-facing `JSC::ArrayBufferView` can hand over such
a view, and which consumer actually runs?

This tool does not guess: it asserts a list of exact source facts against the drop and prints PASS/FAIL for
each, so the doc can quote the run instead of a grep transcript. A FAIL means the drop's text moved and the
doc's table must be re-read.

  python3 tools/oobview-audit.py [-o data/oobview/audit.json]
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DROP = os.path.join(REPO, "out/sony/full/WebKit-1400/WebKit-1400/Source")


def path(rel):
    return os.path.join(DROP, rel)


def text(rel):
    with open(path(rel), "r", errors="replace") as f:
        return f.read()


def lines(rel):
    return text(rel).splitlines()


def md5(rel):
    h = hashlib.md5()
    with open(path(rel), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count(rel, pattern):
    return len(re.findall(pattern, text(rel)))


CHECKS = []


def check(name, ok, detail):
    CHECKS.append({"check": name, "ok": bool(ok), "detail": detail})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    ABV = "JavaScriptCore/runtime/ArrayBufferView.h"
    GTVI = "JavaScriptCore/runtime/JSGenericTypedArrayViewInlines.h"
    GTVI_H = "JavaScriptCore/runtime/GenericTypedArrayViewInlines.h"
    DV_CPP = "JavaScriptCore/runtime/DataView.cpp"
    JABV_CPP = "JavaScriptCore/runtime/JSArrayBufferView.cpp"
    JSON_INCLUDE_FILES = ["JavaScriptCore/JSTypedArray.h", "JavaScriptCore/JSArrayBuffer.h"]

    # 1. the inverted test, both accessors
    abv = text(ABV)
    check("ArrayBufferView::byteOffset has the inverted test",
          abv.count("if (UNLIKELY(!(byteOffsetStart > bufferByteLength || byteOffsetEnd > bufferByteLength)))") == 2,
          "two accessors (byteOffset, byteLength) carry `!(`; upstream main has no `!`")

    # 2. the IDL gate
    gtvi = text(GTVI)
    check("toWrapped refuses resizable/growable-shared views",
          re.search(r"toWrapped\(VM& vm, JSValue value\)\s*\{[^}]*isResizableOrGrowableShared\(\)[^}]*return nullptr",
                    gtvi, re.S) is not None
          and re.search(r"toWrappedAllowShared\(VM& vm, JSValue value\)\s*\{[^}]*isResizableOrGrowableShared\(\)[^}]*return nullptr",
                        gtvi, re.S) is not None,
          "JSGenericTypedArrayViewInlines.h toWrapped and toWrappedAllowShared both return nullptr for such views")

    # 3. wrappedAs skips the sub-range check for resizable buffers
    check("GenericTypedArrayView::wrappedAs skips verifySubRangeLength for resizable buffers",
          "wrappedAs(Ref<ArrayBuffer>&& buffer, size_t byteOffset, std::optional<size_t> length)" in text(GTVI_H)
          and "if (!buffer->isResizableOrGrowableShared()) {" in text(GTVI_H),
          "GenericTypedArrayViewInlines.h:107-118")
    check("DataView::wrappedAs skips verifySubRangeLength for resizable buffers",
          "if (!buffer->isResizableOrGrowableShared()) {" in text(DV_CPP),
          "DataView.cpp:59")

    # 4. every wrappedAs() call site, by file
    sites = {}
    for rel in ("WebCore/bindings/js/SerializedScriptValue.cpp",
                "WebCore/bindings/js/StructuredClone.cpp",
                "JavaScriptCore/runtime/JSArrayBufferView.cpp"):
        sites[rel] = len(re.findall(r"::wrappedAs\(", text(rel)))
    check("wrappedAs() call sites are exactly 12 + 2 + 2",
          sites == {"WebCore/bindings/js/SerializedScriptValue.cpp": 12,
                    "WebCore/bindings/js/StructuredClone.cpp": 2,
                    "JavaScriptCore/runtime/JSArrayBufferView.cpp": 2},
          json.dumps(sites, sort_keys=True))

    # 5. possiblySharedImpl callers
    callers = []
    for base, _dirs, files in os.walk(os.path.join(DROP, "WebCore")):
        for name in files:
            if not name.endswith((".cpp", ".h", ".mm")):
                continue
            p = os.path.join(base, name)
            with open(p, "r", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if "possiblySharedImpl()" in line and "JS_EXPORT_PRIVATE" not in line:
                        callers.append(f"{os.path.relpath(p, DROP)}:{i}")
    check("possiblySharedImpl() has exactly two WebCore callers",
          len(callers) == 2
          and any(c.endswith("JSDOMConvertBufferSource.h:106") for c in callers)
          and any("IDBKey.cpp:" in c for c in callers),
          json.dumps(callers))

    # 6. the serializer's use is gated at the call site
    ssv = lines("WebCore/bindings/js/SerializedScriptValue.cpp")
    idx = next(i for i, l in enumerate(ssv) if "toPossiblySharedArrayBufferView(vm, obj)" in l)
    check("the serializer's producer is preceded by an isOutOfBounds() guard",
          "isOutOfBounds()" in "".join(ssv[max(0, idx - 8):idx]),
          f"SerializedScriptValue.cpp:{idx + 1}")

    # 7. the IDB consumer: no gate, raw length
    idb = lines("WebCore/Modules/indexeddb/IDBKey.cpp")
    idx = next(i for i, l in enumerate(idb) if "IDBKey::createBinary(JSC::JSArrayBufferView&" in l)
    body = "".join(idb[idx:idx + 8])
    check("IDBKey::createBinary(view) has no resizable/OOB gate",
          "isResizableOrGrowableShared" not in body and "isOutOfBounds" not in body,
          "IDBKey.cpp:%d-: copyData(bufferView->data(), bufferView->byteLength())" % (idx + 1))
    check("IDBKey::createBinary(view) copies byteLength() bytes",
          re.search(r"copyData\(bufferView->data\(\), bufferView->byteLength\(\)\)", body) is not None,
          "ThreadSafeDataBuffer::copyData(const void*, unsigned) -> memcpy")

    # 8. the allocator facts
    pc = text("JavaScriptCore/runtime/PageCount.h")
    check("PageCount::pageSize is 64 KiB (the mprotect granularity of resize)",
          "static constexpr uint32_t pageSize = 64 * KB;" in pc,
          "PageCount.h:111")
    g = text("WTF/wtf/Gigacage.cpp")
    check("the growable-bounds-checking reservation is allocated zeroed",
          "OSAllocator::reserveAndCommit(size)" in g and "tryLargeZeroedMemalignVirtual" in g,
          "Gigacage::tryAllocateZeroedVirtualPages (SYSTEM_MALLOC: reserveAndCommit, else bmalloc zeroed)")
    abc = text("JavaScriptCore/runtime/ArrayBuffer.cpp")
    check("resize mprotects [roundUp(newLength), oldSize) PROT_NONE",
          "OSAllocator::protect(startAddress, bytesToSubtract, readable, writable)" in abc
          and "constexpr bool readable = false;" in abc,
          "ArrayBuffer::resize, shrink branch")

    payload = {
        "drop": os.path.relpath(DROP, REPO),
        "md5": {rel: md5(rel) for rel in (ABV, GTVI, GTVI_H, DV_CPP, JABV_CPP)},
        "checks": CHECKS,
        "passed": sum(1 for c in CHECKS if c["ok"]),
        "total": len(CHECKS),
    }
    blob = json.dumps(payload, indent=1, sort_keys=True)
    if args.out:
        with open(args.out, "w") as f:
            f.write(blob)
    for c in CHECKS:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + "  [" + c["detail"] + "]")
    print(f'{payload["passed"]}/{payload["total"]} checks pass')
    if args.out:
        print("wrote " + args.out + " md5 " + hashlib.md5(blob.encode()).hexdigest())
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
