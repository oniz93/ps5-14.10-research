#!/usr/bin/env python3
"""docs/88 builder: write research/fuzz-cssom/seq4.html from seq3.html (docs/87).

seq3.html's md5 is quoted in docs/87, so it is never edited: this builder *reads* it and makes the two
changes GOAL.md item 1 asks for.

  1. `ext` is split by surface: `extf` (the destructive action the FontFace / Animation / clone / IDB
     windows take: delete a live face, churn the sheet, remove a frame), `extw` (worker termination,
     which any window may do) and `extm` (the delivery loop's own destruction: remove the observed
     node, churn, delete a face, force layout).  `ext` survives as the all-three shorthand so
     docs/86's and docs/87's arms stay expressible on this page; every docs/88 arm names the one knob
     it moves.
  2. one new op, `Mofr` (weight 2), plus `moFrame()`: the delivery loop resolves a face inside the
     second document and removes the frame that owns it *inside the same delivery* — the three-level
     nesting docs/87 §6 says its single destructive knob made unreachable (`ith=0`).

Every anchor must occur exactly once (a missing anchor aborts the build), the page's own script is
`node --check`ed, and the docs/84 + docs/86 + docs/87 op blocks are re-asserted verbatim on the output.

Run: python3 research/fuzz-cssom/build_seq4.py   (writes research/fuzz-cssom/seq4.html)
"""
import hashlib
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_seq    # noqa: E402  (docs/85 builder: extract_ops)
import build_seq2   # noqa: E402  (docs/86 builder: sub + srcdoc check)
import build_seq3   # noqa: E402  (docs/87 builder: the page-script check)

SRC = HERE / "seq3.html"
OUT = HERE / "seq4.html"
SRC_MD5 = "6ccdf12569d4da03da27a236e411462e"


def swap(text: str, anchor: str, new: str) -> str:
    """Replace `anchor` with `new`, requiring exactly one occurrence."""
    n = text.count(anchor)
    if n != 1:
        sys.exit("anchor %r occurs %d times (want 1) — seq3.html changed; fix the builder"
                 % (anchor[:70], n))
    return text.replace(anchor, new, 1)


KNOBS_OLD = """  // docs/86 knobs.  One variable per arm: `ath` installs the Animation window, `ext` is the
  // destructive action the windows take on the three new surfaces (terminate the worker, remove a
  // frame).  With both off the page is the docs/85 instrument plus three new ops in the stream.
  var ATH = K('ath', '0') === '1';
  var EXT = K('ext', '0') === '1';
"""

KNOBS_NEW = """  // docs/86 knobs, split by surface in docs/88.  `ath` installs the Animation window.  `extf` is the
  // destructive action the FontFace / Animation / clone / IDB windows take (delete a live face, churn
  // an unrelated sheet, remove a frame); `extw` is worker termination, which any window may do;
  // `extm` is the delivery loop's own destruction (remove the observed node, churn, face delete,
  // layout).  `ext` is kept as the all-three shorthand so a docs/86/87 arm is still expressible here;
  // every docs/88 arm names the one knob it moves, and the boot beacon prints all four.
  var ATH = K('ath', '0') === '1';
  var EXT = K('ext', '0') === '1';                    // shorthand: all three of the below
  var EXTF = K('extf', EXT ? '1' : '0') === '1';
  var EXTW = K('extw', EXT ? '1' : '0') === '1';
  var EXTM = K('extm', EXT ? '1' : '0') === '1';
  // docs/88: the delivery loop resolves a face in the SECOND document.  `mof=0` is the axis control —
  // identical frame pool, identical nudges, only the delivery's nested frame is off.
  var MOF = K('mof', '0') === '1';
"""

NEW_OP = r"""
  // ------------------------------------------- the delivery loop's nested frame (docs/88)
  // Mofr — docs/87 measured that a MutationObserver delivery never lands inside the round that queued
  // it (`moir=0` against ~13k nudges from engine frames), so the only engine frame a delivery can
  // host is one it creates itself.  docs/87 used that for a parent-realm face (`moload`); this op
  // keeps a second-document frame in the pool and nudges the observer, and the delivery itself
  // resolves a face INSIDE that document and then removes the frame — three levels: delivery ->
  // setStatus (inner Document) -> the inner realm's getter.  `mof=0` is the axis control: the same
  // op, the same pool, the same nudges, only the delivery's nested frame is off.
  OPS.push(['Mofr', 2, function (a, b) {
    if (MOF && frames.length < MAXFR) mkFrame();
    if (MOB) moNudge();
    if (p0) p0.setAttribute('mf', String(a % 5));
    if (DBG && mofRN < 4) { mofRN++; B('mofop', 'frames=' + frames.length + '&mof=' + (MOF ? 1 : 0)); }
  }]);
"""

MOFRAME = r"""
  // ------------------------------------------- the delivery loop's nested frame (docs/88)
  // The one nesting docs/87 measured was "a delivery hosting a setStatus of its own" (`moload`, in the
  // parent realm).  This goes one level further: the delivery inserts a rule into the SECOND document,
  // forces that document's layout so its CSSFontSelector builds the face, calls load() on it — so
  // CSSFontFace::setStatus runs inside MutationObserver::deliver and the inner realm's
  // FontFace.prototype getter is page script inside it — and then removes the frame element that owns
  // the document, in the same delivery.  `ith0`/`ith1` in the `mofr` beacon are the parent-side count
  // of inner windows around that load: the witness that the getter ran inside this frame.  The frame
  // pool and the nudges are identical with `mof=0`; only this block is gated.
  var moFrDrive = 0, moFrRem = 0, moFrSeen = 0, moFrEarly = 0, moFrN = 0, mofRN = 0;
  function moFrame() {
    if (!MOF) return;
    var fr = null;
    for (var i = 0; i < frames.length; i++) if (frames[i].isConnected) { fr = frames[i]; break; }
    if (!fr) { mkFrame(); return; }                    // a fresh srcdoc is parsed by the next delivery
    var W = null, d = null;
    try { W = fr.contentWindow; d = fr.contentDocument; } catch (e) { return; }
    // An iframe has a document BEFORE its srcdoc is parsed — the initial about:blank one, which has
    // `fonts`, `head` and `body` but no `FontFace.prototype` accessor, because the accessor is
    // installed by the srcdoc's own <script>.  Driving that document loads a face and resolves it
    // with nobody watching: the first build of this page did exactly that 19 times out of 20
    // (`ith=1` against `mofd=20`).  The srcdoc sets `window.__ran = 1` as its first statement, so
    // that is the readiness witness; a delivery that arrives too early skips and counts.
    if (!W.__ran) { moFrEarly++; return; }
    moFrSeen++;
    var nm = 'zzN' + (moHits % 4);
    var ith0 = (window.__ith || 0), f = null;
    try {
      var old = d.getElementById('nf' + nm);
      if (old && old.parentNode) old.parentNode.removeChild(old);
      var el = d.createElement('style');
      el.id = 'nf' + nm;
      el.textContent = '@font-face{font-family:' + nm + ';src:local("DejaVu Sans")}';
      d.head.appendChild(el);
      d.body.offsetHeight;                             // build the face in the SECOND selector
      d.fonts.forEach(function (x) { if (!f && String(x.family).indexOf(nm) >= 0) f = x; });
      if (f) {
        try { f.loaded; } catch (e) {}
        try { f.load().then(noop, noop); moFrDrive++; } catch (e) {}
      }
    } catch (e) { if (DBG && moFrN < 6) { moFrN++; B('moferr', 'e=' + (e && e.name)); } return; }
    var ith1 = (window.__ith || 0), rem = 0;
    try { if (fr.parentNode) { fr.parentNode.removeChild(fr); rem = 1; } } catch (e) {}
    if (rem) moFrRem++;
    for (var k = frames.length - 1; k >= 0; k--) { if (frames[k] === fr || !frames[k].isConnected) frames.splice(k, 1); }
    if (DBG && moFrN < 6) { moFrN++; B('mofr', 'h=' + moHits + '&found=' + (f ? 1 : 0) + '&st=' + (f ? f.status : '-') +
      '&ith0=' + ith0 + '&ith1=' + ith1 + '&rem=' + rem + '&ran=' + ((W && W.__ran) ? 1 : 0)); }
  }
"""

CCLONE_OLD = """          if (MOB) moNudge();
          if (EXT) {
            var lf = pick(live, clHits);
            if (lf) { live.splice(live.indexOf(lf), 1); document.fonts.delete(lf); }
            extWindow();
          }
"""

CCLONE_NEW = """          if (MOB) moNudge();
          if (EXTF || EXTW) {
            if (EXTF) {
              var lf = pick(live, clHits);
              if (lf) { live.splice(live.indexOf(lf), 1); document.fonts.delete(lf); }
            }
            extWindow();
          }
"""

IKEY_OLD = """          if (MOB) moNudge();
          if (EXT) extWindow();
"""

IKEY_NEW = """          if (MOB) moNudge();
          if (EXTF || EXTW) extWindow();
"""

EXTWIN_OLD = """  function extWindow() {
    // bounded: a worker costs a thread per creation, so an arm destroys at most 64 of them
    if (wrk && wterm < 64) { try { wrk.terminate(); wterm++; } catch (e) {} wrk = null; }
    if (frames.length) {
      var fr = frames.shift();
      try { if (fr && fr.parentNode) { fr.parentNode.removeChild(fr); frmHits++; } } catch (e) {}
    }
  }
"""

EXTWIN_NEW = """  function extWindow() {
    // docs/88: the two actions are separate variables.  `extw` is worker termination (bounded: a
    // worker costs a thread per creation, so an arm destroys at most 64 of them); `extf` is the frame
    // removal the font-side windows take.  `extw=1&extf=0` is what docs/87 §6 could not express: a
    // live script context destroyed inside the engine's frame while the frame pool stays alive.
    if (EXTW && wrk && wterm < 64) { try { wrk.terminate(); wterm++; } catch (e) {} wrk = null; }
    if (EXTF && frames.length) {
      var fr = frames.shift();
      try { if (fr && fr.parentNode) { fr.parentNode.removeChild(fr); frmHits++; } } catch (e) {}
    }
  }
"""

MO_OLD = """          if (EXT) {
            if (moP && moP.parentNode) { moP.parentNode.removeChild(moP); moDel++; }
            churnSheet();
            var lf = pick(live, moHits);
            if (lf) { live.splice(live.indexOf(lf), 1); document.fonts.delete(lf); }
            document.body.offsetHeight;
            // ...and host an engine frame from inside the delivery loop: a fresh face with a source
            // that resolves synchronously reaches Status::Success, so the FontFace window opens
            // inside MutationObserver::deliver (no prior run has put setStatus inside the loop).
            var th0 = thenHits;
            var nf = new FontFace('zzM' + (moHits % 8), 'local("DejaVu Sans")');
            document.fonts.add(nf);
            live.push(nf); trimFaces();
            try { nf.loaded; } catch (e) {}
            try { nf.load(); } catch (e) {}
            if (DBG && moHits <= 6) B('moload', 'h=' + moHits + '&th0=' + th0 + '&th1=' + thenHits);
            extWindow();
          }
"""

MO_NEW = """          if (EXTM) {
            if (moP && moP.parentNode) { moP.parentNode.removeChild(moP); moDel++; }
            churnSheet();
            var lf = pick(live, moHits);
            if (lf) { live.splice(live.indexOf(lf), 1); document.fonts.delete(lf); }
            document.body.offsetHeight;
          }
          // Host an engine frame from inside the delivery loop, unconditionally: a fresh face with a
          // source that resolves synchronously reaches Status::Success, so the FontFace window opens
          // inside MutationObserver::deliver.  docs/87 gated this behind `ext`, which made the only
          // nesting witness depend on the destructive knob; docs/88 measures it with `extm=0`.
          var th0 = thenHits;
          var nf = new FontFace('zzM' + (moHits % 8), 'local("DejaVu Sans")');
          document.fonts.add(nf);
          live.push(nf); trimFaces();
          try { nf.loaded; } catch (e) {}
          try { nf.load(); } catch (e) {}
          if (DBG && moHits <= 6) B('moload', 'h=' + moHits + '&th0=' + th0 + '&th1=' + thenHits);
          if (EXTF || EXTW) extWindow();
          moFrame();
"""


def check_page_and_inner(body: str) -> None:
    """`node --check` the page's own program, then evaluate the srcdoc expression with the stubs this
    page needs and `node --check` the inner script it produces.

    docs/86 shipped a brace error inside the srcdoc *string* that silently disabled the whole
    second-document surface, so the inner script is checked by evaluating the expression, not by
    reading it.  The stub is `EXT=1; EXTF=1` — docs/88's srcdoc gates its kill on `EXTF`.
    """
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        print("WARNING: node not found — neither script was syntax-checked")
        return
    i = body.rindex("\n<script>\n")
    j = body.rindex("\n</script>")
    script = body[i + len("\n<script>\n"):j]
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "page.js"
        p.write_text(script)
        r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("page script has a syntax error:\n%s" % r.stderr.strip()[:800])
        # the srcdoc: evaluate the expression, then check the script it built
        a = body.index("    fr.srcdoc = ")
        b = body.index("    fr.q = seq;", a)
        expr = body[a:b].strip().rstrip(";").split("=", 1)[1].strip()
        js = pathlib.Path(td) / "expr.js"
        js.write_text("var EXT=1;\nvar EXTF=1;\nprocess.stdout.write(%s);\n" % expr)
        out = subprocess.run([node, str(js)], capture_output=True, text=True)
        if out.returncode != 0:
            sys.exit("srcdoc expression does not evaluate: %s" % out.stderr.strip()[:400])
        m = re.search(r"<script>(.*)</script>", out.stdout, re.S)
        if not m:
            sys.exit("srcdoc has no <script> element — the inner window cannot be installed")
        inner = pathlib.Path(td) / "inner.js"
        inner.write_text(m.group(1))
        chk = subprocess.run([node, "--check", str(inner)], capture_output=True, text=True)
        if chk.returncode != 0:
            sys.exit("inner srcdoc script has a syntax error:\n%s" % chk.stderr.strip()[:800])
    print("page script: %d bytes, syntax OK" % len(script))
    print("inner srcdoc script: %d bytes, syntax OK" % len(m.group(1)))


def main() -> None:
    body = SRC.read_text()
    if hashlib.md5(body.encode()).hexdigest() != SRC_MD5:
        sys.exit("seq3.html is not the build docs/87 quotes (%s)" % SRC_MD5)

    # ---- provenance: the docs/84 ops and the docs/86 + docs/87 ops must survive byte for byte
    ops84 = build_seq.extract_ops((HERE / "fuzz.html").read_text())
    if ops84 not in body:
        sys.exit("seq3.html does not contain fuzz.html's op block verbatim")
    old_ops = []
    for op in ("Aanim", "Aframe", "Aworker", "Cclone", "Ikey", "Mobs"):
        m = re.search(r"  OPS\.push\(\['%s',.*?\n  \}\]\);\n" % op, body, re.S)
        if not m:
            sys.exit("seq3.html is missing the op %s" % op)
        old_ops.append(m.group(0))

    body = swap(body, KNOBS_OLD, KNOBS_NEW)

    # ---- (1) the ext split, one call site at a time
    body = swap(body, CCLONE_OLD, CCLONE_NEW)
    body = swap(body, IKEY_OLD, IKEY_NEW)
    body = swap(body, """      'var KILL=' + (EXT ? 1 : 0) + ';' +""",
                      """      'var KILL=' + (EXTF ? 1 : 0) + ';' +""")
    body = swap(body, """            if (EXT) {
              churnSheet();
              var sh = inlineSheet();
              if (sh && sh.cssRules.length) sh.deleteRule(0);
              try { self.cancel(); } catch (e) {}
              document.body.offsetHeight;
              extWindow();
            }
""", """            if (EXTF || EXTW) {
              if (EXTF) {
                churnSheet();
                var sh = inlineSheet();
                if (sh && sh.cssRules.length) sh.deleteRule(0);
                try { self.cancel(); } catch (e) {}
                document.body.offsetHeight;
              }
              extWindow();
            }
""")
    body = swap(body, """            if (EXT) extWindow();
            if (MOB) moNudge();
""", """            if (EXTF || EXTW) extWindow();
            if (MOB) moNudge();
""")
    body = swap(body, EXTWIN_OLD, EXTWIN_NEW)
    body = swap(body, MO_OLD, MO_NEW)

    # ---- (2) the new op and its machinery
    body = build_seq2.sub(body, "\n  var TOT = 0, CUM = [];", NEW_OP, where="before")
    body = build_seq2.sub(body, "  // ---------------------------------------------------------------- the script window\n",
                          MOFRAME, where="before")

    # ---- stale comments that say `ext` where they now mean one of the three
    body = swap(body, "  // When ext=1 the inner window removes its own frame element: the Document that owns the resolving",
                      "  // When extf=1 the inner window removes its own frame element: the Document that owns the resolving")
    body = swap(body, "    // The inner document installs its own FontFace.prototype.then window: when ext=1 that window",
                      "    // The inner document installs its own FontFace.prototype.then window: when extf=1 that window")
    body = swap(body, "  // The callback is a script window inside the engine's delivery loop: when ext=1 it removes the node",
                      "  // The callback is a script window inside the engine's delivery loop: when extm=1 it removes the node")

    # ---- beacons: the four knobs on `boot`, the delivery counters on `done`
    boot_anchor = "    '&ath=' + (ATH ? 1 : 0) + '&ext=' + (EXT ? 1 : 0) + '&mob=' + (MOB ? 1 : 0));"
    body = swap(body, boot_anchor,
                "    '&ath=' + (ATH ? 1 : 0) + '&ext=' + (EXT ? 1 : 0) + '&extf=' + (EXTF ? 1 : 0) +\n"
                "    '&extw=' + (EXTW ? 1 : 0) + '&extm=' + (EXTM ? 1 : 0) + '&mof=' + (MOF ? 1 : 0) +\n"
                "    '&mob=' + (MOB ? 1 : 0));")
    done_anchor = "      '&mn=' + moNudges + '&moir=' + moIn);"
    body = swap(body, done_anchor,
                "      '&mn=' + moNudges + '&moir=' + moIn +\n"
                "      '&mofd=' + moFrDrive + '&mofrem=' + moFrRem + '&mofseen=' + moFrSeen + '&mofearly=' + moFrEarly);")

    OUT.write_text(body)

    check_page_and_inner(body)
    if body.count("moFrame();\n") != 1:
        sys.exit("moFrame() is called %d times (want 1)" % body.count("moFrame();\n"))

    print("wrote %s (%d bytes, md5 %s)" % (OUT, len(body), hashlib.md5(body.encode()).hexdigest()))
    nops = len(re.findall(r"\n    \['[A-Za-z][A-Za-z0-9-]*', \d+, function", body)) + \
        len(re.findall(r"OPS\.push\(\['[A-Za-z][A-Za-z0-9-]*', \d+, function", body))
    print("ops present: %d (29 array + 9 pushed = 38)" % nops)
    for blk in old_ops:
        want = blk.replace(CCLONE_OLD, CCLONE_NEW).replace(IKEY_OLD, IKEY_NEW)
        if want not in body:
            sys.exit("a docs/86/87 op block did not survive the build (%r…)" % blk[:40])
    print("provenance: 29 docs/84 ops present, 6 docs/86/87 op blocks present (%d bytes verbatim)" %
          sum(len(b) for b in old_ops))
    for tok in ("EXTF", "EXTW", "EXTM", "MOF", "moFrame", "mofr"):
        print("  %-8s %d occurrences" % (tok, body.count(tok)))


if __name__ == "__main__":
    main()
