#!/usr/bin/env python3
"""Structure-aware SVG/CSS case generator for the ASAN MiniBrowser sweep.

Not random bytes: it composes real SVG trees and mutates them at the token level, because the interesting bugs in
this subsystem live in the parsing of numbers, path data, references between elements (use/marker/clipPath/mask/
pattern/gradient) and the interaction of those with layout. Each case runs in its own iframe on one page so the
whole batch is one browser start, and a beacon names the case before it runs - a crash therefore identifies the
culprit without bisecting.

Usage: svg_sweep.py --out page.html --start 0 --count 120 --seed 7
"""
import argparse, random

NUMBERS = ["0", "-0", "1", "-1", "1e308", "-1e308", "1e-308", "NaN", "Infinity", "-Infinity",
           "2147483647", "-2147483648", "4294967296", "0.0000001", "1e39", "-1e39",
           "1,2", "1 2", "1-2", ".5.5", "1e", "--1", "1.2.3", " 1 ", "\t1\n"]

PATH_COMMANDS = "MmLlHhVvCcSsQqTtAaZz"

ATTRS_COMMON = [
    ("d", None), ("x", None), ("y", None), ("width", None), ("height", None), ("r", None),
    ("rx", None), ("ry", None), ("cx", None), ("cy", None), ("x1", None), ("y1", None),
    ("x2", None), ("y2", None), ("points", None), ("transform", None), ("viewBox", None),
    ("preserveAspectRatio", None), ("gradientTransform", None), ("patternTransform", None),
    ("markerWidth", None), ("markerHeight", None), ("refX", None), ("refY", None),
    ("pathLength", None), ("offset", None), ("stroke-dasharray", None), ("stroke-width", None),
    ("filterRes", None), ("stdDeviation", None), ("baseFrequency", None), ("numOctaves", None),
    ("scale", None), ("values", None), ("keyTimes", None), ("keySplines", None), ("dur", None),
    ("repeatCount", None), ("attributeName", None), ("from", None), ("to", None), ("by", None),
]

TAGS = ["svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
        "defs", "use", "symbol", "marker", "pattern", "linearGradient", "radialGradient",
        "stop", "clipPath", "mask", "filter", "feGaussianBlur", "feOffset", "feBlend",
        "feImage", "feTurbulence", "feDisplacementMap", "feMerge", "feMergeNode",
        "text", "tspan", "textPath", "image", "switch", "foreignObject", "a", "view"]

CSS_SNIPPETS = [
    "path{d:path('M0 0')}", "svg{overflow:visible}", "*{transform-box:fill-box}",
    "g:has(> path){opacity:.5}", "@media (min-width:0px){path{stroke-width:1e39}}",
    "@supports (d:path('M0 0')){path{fill:red}}", "path{content-visibility:auto}",
    "svg{contain-intrinsic-size:1px}", "@container (min-width:0px){path{opacity:1}}",
    "path{marker-end:url(#m)}", "path{clip-path:url(#c)}", "path{mask:url(#k)}",
    "path{filter:url(#f)}", "path{mix-blend-mode:multiply}",
]


def num(rng):
    return rng.choice(NUMBERS)


def pathd(rng):
    out = []
    for _ in range(rng.randint(0, 6)):
        out.append(rng.choice(PATH_COMMANDS))
        for _ in range(rng.randint(0, 4)):
            out.append(num(rng))
    return " ".join(out)


def attr_value(name, rng):
    if name == "d":
        return pathd(rng)
    if name in ("points",):
        return " ".join(num(rng) for _ in range(rng.randint(0, 8)))
    if name == "transform":
        return rng.choice(["translate(%s,%s)" % (num(rng), num(rng)),
                           "matrix(%s)" % " ".join(num(rng) for _ in range(6)),
                           "rotate(%s)scale(%s)" % (num(rng), num(rng)),
                           "scale(%s,,%s)" % (num(rng), num(rng))])
    if name == "viewBox":
        return " ".join(num(rng) for _ in range(rng.choice([0, 2, 4, 5, 7])))
    if name == "values":
        return ";".join(num(rng) for _ in range(rng.randint(0, 4)))
    if name == "attributeName":
        return rng.choice(["d", "x", "width", "transform", "viewBox", "pathLength", "points"])
    if name == "dur":
        return rng.choice(["1s", "0", "-1s", "1e39s", "1ms"])
    return num(rng)


def element(rng, depth, ids):
    tag = rng.choice(TAGS)
    parts = ["<", tag]
    for _ in range(rng.randint(0, 3)):
        name, _v = rng.choice(ATTRS_COMMON)
        parts.append(' %s="%s"' % (name, attr_value(name, rng)))
    if rng.random() < 0.25:
        eid = "e%d" % len(ids)
        ids.append(eid)
        parts.append(' id="%s"' % eid)
    if rng.random() < 0.2 and ids:
        parts.append(' xlink:href="#%s"' % rng.choice(ids))
    if tag in ("use", "image", "feImage") and rng.random() < 0.5:
        parts.append(' href="#%s"' % (rng.choice(ids) if ids else "nope"))
    if depth <= 0 or rng.random() < 0.3:
        parts.append("/>")
        return "".join(parts)
    parts.append(">")
    for _ in range(rng.randint(0, 3)):
        parts.append(element(rng, depth - 1, ids))
    parts.append("</%s>" % tag)
    return "".join(parts)


def case(rng, idx):
    ids = []
    body = element(rng, rng.randint(1, 4), ids)
    style = "".join(rng.sample(CSS_SNIPPETS, rng.randint(0, 3)))
    # occasionally exercise the geometry API against the generated tree
    js = ""
    if rng.random() < 0.45 and "path" in body:
        js = ("<script>try{var p=document.querySelector('path');"
              "if(p){p.getTotalLength();p.getPointAtLength(%s);p.getPointAtLength(%s);"
              "p.isPointInFill(new DOMPoint(%s,%s));}}catch(e){}</script>") % (
                  num(rng), num(rng), num(rng), num(rng))
    return ('<style>%s</style>%s%s' % (style, body, js))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=120)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    cases = []
    for i in range(a.count):
        idx = a.start + i
        cases.append(case(rng, idx))

    parts = ["<!doctype html><meta charset='utf-8'><body>",
             "<script>function b(s){try{new Image().src='/ev?m=svg-'+encodeURIComponent(s)}catch(e){}}</script>"]
    for i, c in enumerate(cases):
        parts.append("<script>b('pre-%d')</script>" % (a.start + i))
        parts.append("<iframe style='width:60px;height:60px' srcdoc=\"%s\"></iframe>" % (
            c.replace("&", "&amp;").replace('"', "&quot;")))
        parts.append("<script>b('post-%d')</script>" % (a.start + i))
    parts.append("<script>b('batch-done')</script>")
    open(a.out, "w").write("".join(parts))
    print("wrote %s with %d cases (start=%d seed=%d)" % (a.out, len(cases), a.start, a.seed))


if __name__ == "__main__":
    main()
