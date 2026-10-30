#!/usr/bin/env python3
"""docs/86 builder: write research/fuzz-cssom/seq2.html from seq.html (docs/85).

seq.html's md5 is quoted in docs/85, so it is never edited: this builder *reads* it and inserts the
three surfaces docs/85 §6 lists as missing — a second document (iframe), `Animation`'s resolve
windows, and a worker — at anchors that must each occur exactly once.  A missing anchor aborts the
build, so the two pages cannot silently drift.

Provenance is re-asserted on the output, not assumed: build_seq.py's extract_ops(fuzz.html) must
appear verbatim in seq2.html too, i.e. the 29 docs/84 operations in the new page are the same bytes
as in the old one.

Run: python3 research/fuzz-cssom/build_seq2.py   (writes research/fuzz-cssom/seq2.html)
"""
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_seq  # noqa: E402  (same directory, the docs/85 builder)

SRC = HERE / "seq.html"
OUT = HERE / "seq2.html"


def sub(text: str, anchor: str, insert: str, where: str = "after") -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit("anchor %r occurs %d times (want 1) — seq.html changed; fix the builder" % (anchor, n))
    if where == "before":
        return text.replace(anchor, insert + anchor, 1)
    return text.replace(anchor, anchor + insert, 1)


KNOBS = """
  // docs/86 knobs.  One variable per arm: `ath` installs the Animation window, `ext` is the
  // destructive action the windows take on the three new surfaces (terminate the worker, remove a
  // frame).  With both off the page is the docs/85 instrument plus three new ops in the stream.
  var ATH = K('ath', '0') === '1';
  var EXT = K('ext', '0') === '1';
"""

EXTRA_OPS = """
  // ------------------------------------------- the three surfaces docs/85 could not reach (docs/86)
  // (a) Aanim — WebAnimation's promise frames.  docs/74 read 7 `resolve`-with-a-tail sites and
  // measured two by hand; this drives them from the alphabet.  Precondition, the same one docs/85 §3
  // found for FontFace: DOMPromiseProxy only settles the DeferredPromises that already exist, so
  // `ready`/`finished` must be materialised before the resolve or the C++ call creates no JS value
  // at all (docs/74's `pre=0` control).  play() before finish() puts a pending play task in flight,
  // which is what makes finish() take `m_readyPromise->resolve(*this)` (:873) as well as
  // finishNotificationSteps' `m_finishedPromise->resolve(*this)` (:1003) — two windows per call.
  OPS.push(['Aanim', 4, function (a, b) {
    var el = pick(els, a);
    if (!el || !el.isConnected) el = p0;
    var an = null;
    try { an = el.animate([{ opacity: 0.92 }, { opacity: 1 }], { duration: 40 + (b % 500) }); } catch (e) { return; }
    anims.push(an); trimAnims();
    try { an.ready; an.finished; } catch (e) {}      // materialise, or the resolve is a no-op for script
    try { an.play(); } catch (e) {}                  // pending play task -> finish() resolves ready in-frame
    if (DBG && ANIMN < 6) { ANIMN++; B('anim', 'ctor=' + (an.constructor && an.constructor.name) +
      '&ps=' + an.playState + '&n=' + anims.length); }
    IN_AANIM++;
    try { an.finish(); } catch (e) { if (DBG && ANIMN < 8) B('animerr', 'e=' + (e && e.name)); }
    IN_AANIM--;
    if (DBG && ANIMN < 8) B('animpost', 'ps=' + an.playState + '&ath=' + athHits);
  }]);
  // (b) Aframe — a SECOND Document, with its own CSSFontSelector and FontFaceSet.  Even draws create
  // an iframe whose srcdoc carries its own FontFace.prototype.then window; odd draws drive the oldest
  // frame's document from here (a font load inside the second document, synchronously in this task).
  // When ext=1 the inner window removes its own frame element: the Document that owns the resolving
  // face is detached inside the engine's setStatus frame.  docs/73 measured a frame tail by hand with
  // a same-document navigation; no run has done it with a font load in the window.
  OPS.push(['Aframe', 4, function (a) {
    // a frame whose element was removed by the inner window (ext=1) is dead: drop it, or the pool
    // stays full of unreachable documents and the op silently stops creating new ones.
    for (var k = frames.length - 1; k >= 0; k--) {
      if (!frames[k].isConnected) {
        // the inner window removed its own frame: this is the parent-side witness of the
        // destruction (the inner context's own counter never reaches us — measured, docs/86 §2)
        frames.splice(k, 1); frmHits++;
        if (DBG && FRN < 8) { FRN++; B('frgone', 'n=' + frmHits + '&q=' + seq); }
      }
    }
    if (frames.length < MAXFR && (a & 1) === 0) { mkFrame(); return; }
    var fr = null;
    for (var i = 0; i < frames.length; i++) { if (frames[i].q < seq) { fr = frames[i]; break; } }
    if (!fr) { if (frames.length < MAXFR) mkFrame(); return; }
    var W = null, d = null;
    try { W = fr.contentWindow; d = fr.contentDocument; } catch (e) { return; }
    if (!d || !W || !d.fonts || !d.head) return;     // document replaced, or not parsed yet
    var nm = 'zzI' + (a % 4);
    try {
      var old = d.getElementById('if' + nm);
      if (old && old.parentNode) old.parentNode.removeChild(old);
      var el = d.createElement('style');
      el.id = 'if' + nm;
      el.textContent = '@font-face{font-family:' + nm + ';src:local("DejaVu Sans")}';
      d.head.appendChild(el);
      d.body.offsetHeight;                           // build the face in the SECOND selector
      var f = null, cnt = 0;
      d.fonts.forEach(function (x) { cnt++; if (!f && String(x.family).indexOf(nm) >= 0) f = x; });
      if (DBG && FRN < 6) { FRN++; B('frdrive', 'n=' + nm + '&found=' + (f ? 1 : 0) + '&fc=' + cnt +
        '&st=' + (f ? f.status : '-') + '&ran=' + (W.__ran || 0) + '&ithw=' + (W.__ith || 0)); }
      if (f) {
        try { f.loaded; } catch (e) {}
        try { f.load(); } catch (e) { if (DBG && FRN < 8) B('frloaderr', 'e=' + (e && e.name)); }
        if (DBG && FRN < 8) B('frpost', 'st=' + f.status + '&ith=' + (window.__ith || 0) + '&q=' + fr.q);
      }
    } catch (e) { if (DBG && FRN < 8) B('frerr', 'e=' + (e && e.name)); }
  }]);
  // (c) Aworker — the one script context with its own ScriptExecutionContext.  One blob worker is
  // kept alive; every op posts it a message that allocates and echoes.  When ext=1 the window
  // terminates it, so the engine destroys a live script context inside its own frame and the next op
  // recreates it.  docs/75(b) measured a ref'd context surviving its window; no run has fuzzed one
  // that is actually destroyed.
  OPS.push(['Aworker', 3, function (a) {
    if (!wrk) mkWorker();
    if (!wrk) return;
    try { wrk.postMessage({ n: a % 97 }); wpost++; } catch (e) { wrk = null; }
    if (DBG && wpost < 5) B('wkpost', 'n=' + wpost + '&live=' + (wrk ? 1 : 0));
  }]);
"""

MACHINERY = """
  // ------------------------------------------- extended-surface machinery (docs/86)
  var MAXAN = 4, MAXFR = 2, FRQ = 0;
  var anims = [], frames = [], wrk = null, wpost = 0, wterm = 0, wecho = 0;
  var athHits = 0, frmHits = 0, ANIMN = 0, FRN = 0, IN_AANIM = 0;   // inner-window count lives on window.__ith
  function trimAnims() { while (anims.length > MAXAN) { var an = anims.shift(); try { an.cancel(); } catch (e) {} } }
  function mkFrame() {
    while (frames.length >= MAXFR) { var of = frames.shift(); try { if (of && of.parentNode) of.parentNode.removeChild(of); } catch (e) {} }
    var fr = document.createElement('iframe');
    fr.id = 'zzfr' + (FRQ++);
    fr.width = 8; fr.height = 8;
    // The inner document installs its own FontFace.prototype.then window: when ext=1 that window
    // destroys the frame element that owns it, i.e. the Document is detached while one of its
    // CSSFontFaces is inside setStatus.  The beacon is the witness that the inner window ran.
    fr.srcdoc = '<!doctype html><meta charset="utf-8"><style id="iv">y{}</style><body><p>i</p><script>' +
      '(function(){window.__ran=1;try{parent.__inran=(parent.__inran||0)+1;}catch(e){}' +
      'var KILL=' + (EXT ? 1 : 0) + ';' +
      'try{Object.defineProperty(FontFace.prototype,"then",{configurable:true,get:function(){' +
      'window.__ith=(window.__ith||0)+1;try{parent.__ith=(parent.__ith||0)+1;}catch(e){}' +
      'try{(new Image()).src="/ev?m=ithen&i="+window.__ith;}catch(e){}' +
      // the kill's witness is a PARENT-side counter, not a beacon: the beacon would be sent by the
      // document that is being detached, which is exactly the silencer docs/65 recorded.
      'if(KILL){try{parent.__killTry=(parent.__killTry||0)+1;var fe=window.frameElement;' +
      'if(fe&&fe.parentNode){fe.parentNode.removeChild(fe);parent.__killed=(parent.__killed||0)+1;}' +
      'else{parent.__nofe=(parent.__nofe||0)+1;}}catch(e){parent.__killerr=(parent.__killerr||0)+1;}}' +
      'try{document.body.offsetHeight;}catch(e){}' +
      'return undefined;},set:function(v){}});}catch(e){}' +
      'if(KILL){try{var w=document.createElement("style");w.id="iw";w.textContent="z{color:#333}";' +
      'document.head.appendChild(w);}catch(e){}}' +
      '})();<\\/script>';
    fr.q = seq;
    document.body.appendChild(fr);
    frames.push(fr);
    if (DBG && FRN < 8) { FRN++; B('frame', 'id=' + fr.id + '&n=' + frames.length + '&q=' + seq); }
  }
  function mkWorker() {
    var src = 'onmessage=function(e){var a=[],i;for(i=0;i<256;i++)a.push(i*3);' +
      'try{postMessage({echo:e.data.n,len:a.length});}catch(x){}};';
    try {
      wrk = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
      wrk.onmessage = function (e) { wecho++; if (DBG && wecho < 5) B('wkecho', 'n=' + (e.data && e.data.echo) + '&len=' + (e.data && e.data.len)); };
      wrk.onerror = function (e) { if (DBG) B('wkerr', 'm=' + encodeURIComponent(String(e && e.message))); };
    } catch (e) { wrk = null; if (DBG) B('wkfail', 'e=' + (e && e.name)); }
  }
  // The FontFace window's actions on the two context surfaces: destroy a live script context and a
  // live Document inside the engine's own frame.  Deliberately no allocation of the freed 192-byte
  // class here (an iframe is a different class and only created by the op, not by the window), so
  // this page stays what docs/85 §6 says it is: a crash hunt, not a reclaim oracle.
  function extWindow() {
    // bounded: a worker costs a thread per creation, so an arm destroys at most 64 of them
    if (wrk && wterm < 64) { try { wrk.terminate(); wterm++; } catch (e) {} wrk = null; }
    if (frames.length) {
      var fr = frames.shift();
      try { if (fr && fr.parentNode) { fr.parentNode.removeChild(fr); frmHits++; } } catch (e) {}
    }
  }
  // Animation's window.  Same shape as the FontFace one — a real stylesheet-collection change and a
  // forced layout inside the engine's frame — plus the action docs/74 measured by hand: cancel() and
  // remove() the animation that is resolving.  depth is the shared reentrancy guard.
  function installAth() {
    try {
      Object.defineProperty(Animation.prototype, 'then', {
        configurable: true,
        get: function () {
          var self = this;
          if (depth > 0) return undefined;
          athHits++;
          depth++;
          try {
            if (DBG && athHits <= 6) B('athen', 'on=' + (self && self.constructor ? self.constructor.name : '?') +
              '&in=' + IN_AANIM + '&ps=' + (function () { try { return self.playState; } catch (e) { return 'ERR'; } })());
            if (EXT) {
              churnSheet();
              var sh = inlineSheet();
              if (sh && sh.cssRules.length) sh.deleteRule(0);
              try { self.cancel(); } catch (e) {}
              document.body.offsetHeight;
              extWindow();
            }
          } catch (e) {}
          depth--;
          return undefined;
        },
        set: function (v) {}
      });
    } catch (e) { B('athfail', 'e=' + (e && e.name)); }
  }
"""


def check_inner_script(body: str) -> None:
    """Evaluate the page's srcdoc expression under node and syntax-check the script it builds."""
    import json
    import re
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        print("WARNING: node not found — inner srcdoc script NOT syntax-checked")
        return
    i = body.index("    fr.srcdoc = ")
    j = body.index("    fr.q = seq;", i)
    expr = body[i:j].strip().rstrip(";")
    expr = expr.split("=", 1)[1].strip()
    program = "var EXT=1;\nprocess.stdout.write(%s);\n" % expr
    with tempfile.TemporaryDirectory() as td:
        js = pathlib.Path(td) / "expr.js"
        js.write_text(program)
        out = subprocess.run([node, str(js)], capture_output=True, text=True)
        if out.returncode != 0:
            sys.exit("srcdoc expression does not evaluate: %s" % out.stderr.strip()[:400])
        srcdoc = out.stdout
        m = re.search(r"<script>(.*)</script>", srcdoc, re.S)
        if not m:
            sys.exit("srcdoc has no <script> element — the inner window cannot be installed")
        inner = pathlib.Path(td) / "inner.js"
        inner.write_text(m.group(1))
        chk = subprocess.run([node, "--check", str(inner)], capture_output=True, text=True)
        if chk.returncode != 0:
            sys.exit("inner srcdoc script has a syntax error:\n%s" % chk.stderr.strip()[:800])
        print("inner srcdoc script: %d bytes, syntax OK" % len(m.group(1)))


def main() -> None:
    body = SRC.read_text()

    # The 29 docs/84 ops must be present in the new page as the same bytes.
    ops_block = build_seq.extract_ops((HERE / "fuzz.html").read_text())
    if ops_block not in body:
        sys.exit("seq.html does not contain fuzz.html's op block verbatim")

    body = sub(body, "  var TICK  = Math.max(0, parseInt(K('tick', '5000'), 10));\n", KNOBS)
    body = sub(body, "\n  var TOT = 0, CUM = [];", EXTRA_OPS, where="before")
    body = sub(body, "  // ---------------------------------------------------------------- the script window\n",
               MACHINERY, where="before")
    body = sub(body, "            if (GC) gcWindow();\n", "            if (EXT) extWindow();\n")
    body = sub(body, "\n  B('boot', 'seed='", "  if (ATH) installAth();\n", where="before")
    if body.count("'&batch=' + BATCH + '&every=' + EVERY + '&del=' + (DELF ? 1 : 0));") != 1:
        sys.exit("boot-beacon anchor is not unique")
    body = body.replace("'&batch=' + BATCH + '&every=' + EVERY + '&del=' + (DELF ? 1 : 0));",
                        "'&batch=' + BATCH + '&every=' + EVERY + '&del=' + (DELF ? 1 : 0) +\n"
                        "    '&ath=' + (ATH ? 1 : 0) + '&ext=' + (EXT ? 1 : 0));", 1)
    done_anchor = ("      '&fc=' + fc + '&cr=' + cr + '&lk=' + lk + '&sc=' + document.head.querySelectorAll('style').length +\n"
                   "      '&eh=' + document.body.offsetHeight);")
    if body.count(done_anchor) != 1:
        sys.exit("done-beacon anchor occurs %d times" % body.count(done_anchor))
    body = body.replace(done_anchor,
                        "      '&fc=' + fc + '&cr=' + cr + '&lk=' + lk + '&sc=' + document.head.querySelectorAll('style').length +\n"
                        "      '&eh=' + document.body.offsetHeight +\n"
                        "      '&ath=' + athHits + '&ith=' + (window.__ith || 0) + '&frm=' + frmHits +\n"
                        "      '&wterm=' + wterm + '&wecho=' + wecho + '&an=' + anims.length + '&fr=' + frames.length +\n"
                        "      '&killed=' + (window.__killed || 0) + '&ktry=' + (window.__killTry || 0) +\n"
                        "      '&kerr=' + (window.__killerr || 0) + '&nofe=' + (window.__nofe || 0));", 1)

    OUT.write_text(body)

    # The srcdoc's inner script is a *string* in the page: neither this builder's Python nor
    # `node --check` on the page can see its syntax, and the first build of this page shipped a
    # brace error that silently disabled the whole second-document surface.  So the builder
    # evaluates the srcdoc expression with node and syntax-checks the inner script it produces.
    check_inner_script(body)

    print("wrote %s (%d bytes, md5 %s)" % (OUT, len(body), hashlib.md5(body.encode()).hexdigest()))
    print("ops present: %d (31 + 3 = 34)" % len(__import__("re").findall(r"\[['\"]([A-Za-z][A-Za-z0-9-]*)['\"],\s*\d+,\s*function", body)))


if __name__ == "__main__":
    main()
