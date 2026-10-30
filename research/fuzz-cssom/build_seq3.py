#!/usr/bin/env python3
"""docs/87 builder: write research/fuzz-cssom/seq3.html from seq2.html (docs/86).

seq2.html's md5 is quoted in docs/86, so it is never edited: this builder *reads* it and inserts the
three surfaces docs/86 §6 lists as still outside the alphabet — `structuredClone`'s serializer walk,
IndexedDB's key builder, `MutationObserver` — at anchors that must each occur exactly once.  A
missing anchor aborts the build, so the two pages cannot silently drift.

The fourth surface GOAL.md item 1 names, `window.open`, is *not* an op: `caps5`/`caps6` measured that
every spelling returns null on this build (the popup blocker's `allowPopUp()` is false for script, and
`showModalDialog` is not exposed).  The negative is recorded in docs/87 rather than wired.

Provenance is re-asserted on the output, not assumed: the 29 docs/84 operations and the three docs/86
operations must appear in seq3.html as the same bytes, and the page's own inline script is
syntax-checked with `node --check` (a build defect that ships as a *string* is invisible to the page —
docs/86 shipped exactly that once).

Run: python3 research/fuzz-cssom/build_seq3.py   (writes research/fuzz-cssom/seq3.html)
"""
import hashlib
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_seq   # noqa: E402  (docs/85 builder: extract_ops)
import build_seq2  # noqa: E402  (docs/86 builder: anchor helper + srcdoc check)

SRC = HERE / "seq2.html"
OUT = HERE / "seq3.html"


def main() -> None:
    body = SRC.read_text()

    # ---- provenance: the docs/84 ops and the docs/86 ops must survive byte for byte
    ops84 = build_seq.extract_ops((HERE / "fuzz.html").read_text())
    if ops84 not in body:
        sys.exit("seq2.html does not contain fuzz.html's op block verbatim")
    ops86 = []
    for op in ("Aanim", "Aframe", "Aworker"):
        m = re.search(r"  OPS\.push\(\['%s',.*?\n  \}\]\);\n" % op, body, re.S)
        if not m:
            sys.exit("seq2.html is missing the docs/86 op %s" % op)
        ops86.append(m.group(0))
    ops86_block = ops86

    KNOBS = """
  // docs/87 knob.  `mob=0` removes the MutationObserver from the page entirely, i.e. the control for
  // the one new surface whose install is a page-level object rather than a per-op call.
  var MOB = K('mob', '1') === '1';
"""

    NEW_OPS = r"""
  // ------------------------------------------- the three surfaces still outside the alphabet (docs/87)
  // (a) Cclone — structuredClone's serializer walk.  docs/77 read `inputObjectStack`
  // (Vector<JSObject*, 32>) clean because every walked object is already in `m_objectPool`, so the
  // keep-alive is a MarkedArgumentBuffer and not the vector.  This op puts a getter at depth 24..43,
  // i.e. mostly past the 32-entry inline boundary where the vector is in its heap buffer, and the
  // getter does the docs/65 arming (sheet churn + deleteRule + layout) *inside* the serializer's own
  // frame.  A Proxy cannot be used to open the same window: measured, structuredClone rejects it
  // with DataCloneError before any trap runs (caps6).
  OPS.push(['Cclone', 5, function (a, b) {
    var d = 24 + (a % 20);
    var root2 = { v: a % 7, s: 'c' + (b % 5) }, cur = root2;
    for (var i = 0; i < d; i++) { var nx = { i: i }; cur.next = nx; cur = nx; }
    Object.defineProperty(cur, 'late', {
      enumerable: true, configurable: true,
      get: function () {
        clHits++;
        if (clDepth > 0) return 'L';
        clDepth++;
        try {
          if (DBG && clHits <= 6) B('cget', 'h=' + clHits + '&d=' + d + '&in=' + IN_CCLONE);
          churnSheet();
          var sh = inlineSheet();
          if (sh && sh.cssRules.length) sh.deleteRule(0);
          document.body.offsetHeight;
          if (MOB) moNudge();
          if (EXT) {
            var lf = pick(live, clHits);
            if (lf) { live.splice(live.indexOf(lf), 1); document.fonts.delete(lf); }
            extWindow();
          }
        } catch (e) {}
        clDepth--;
        return 'L';
      }
    });
    var out = null;
    IN_CCLONE++;
    try { out = structuredClone(root2); } catch (e) { clErr++; }
    IN_CCLONE--;
    var n = 0, c = out;
    while (c && c.next) { n++; c = c.next; }
    if (n === d && c && c.late === 'L') clOk++;
  }]);
  // (b) Ikey — IndexedDB's key builder.  `createIDBKeyFromValue` (docs/78) pushes every JSArray into
  // a `Vector<JSArray*>` with capacity 0, i.e. always in its heap buffer, and reads element i with
  // getIndex(); a HOLE falls through to the prototype chain and calls page script.  The getter goes on
  // the array's OWN prototype: measured, the receiver is the array and ordinary arrays in the page do
  // not see it (caps7), so nothing else in the instrument is perturbed.  IDBKeyRange.only is the
  // cheapest synchronous entry into that function — no database, no task, no version change.
  OPS.push(['Ikey', 3, function (a, b) {
    var leaf = [1, , 3 + (a % 5)];
    var arr = leaf, nest = a % 4;
    for (var i = 0; i < nest; i++) arr = [arr, i];
    var proto = {};
    Object.defineProperty(proto, '1', {
      configurable: true,
      get: function () {
        ikHits++;
        if (ikDepth > 0) return 7;
        ikDepth++;
        try {
          if (DBG && ikHits <= 6) B('iget', 'h=' + ikHits + '&in=' + IN_IKEY + '&nest=' + nest);
          churnSheet();
          var sh = inlineSheet();
          if (sh && sh.cssRules.length) sh.deleteRule(0);
          document.body.offsetHeight;
          if (MOB) moNudge();
          if (EXT) extWindow();
        } catch (e) {}
        ikDepth--;
        return [4, 5];
      }
    });
    try { Object.setPrototypeOf(leaf, proto); } catch (e) { return; }
    IN_IKEY++;
    try { var r = IDBKeyRange.only(arr); if (r) ikOk++; } catch (e) { ikErr++; }
    IN_IKEY--;
    try { Object.setPrototypeOf(leaf, Array.prototype); } catch (e) {}   // leave no getter behind
  }]);
  // (c) Mobs — MutationObserver.  docs/78 read the delivery loop inert by ownership
  // (`Vector<MutationObserverRegistration*, 1>`, the CVE ordering with a cap of 1); no run has fired
  // a callback that destroys the observed container from inside the delivery.  The observer is
  // installed once and every record the alphabet's own DOM churn queues is delivered by the engine's
  // microtask checkpoints — which are the checkpoints inside the FontFace/Animation windows' own C++
  // frames.  `mob=0` is the axis control: the page then has no observer at all.
  OPS.push(['Mobs', 3, function (a, b) {
    if (!mo && MOB) mkMo();
    var el = document.createElement('i');
    el.textContent = 'm' + (a % 9);
    root.appendChild(el); els.push(el); trimEls();
    if (p0) p0.setAttribute('k', String(b % 7));
    if ((a & 1) === 0 && moP) {
      if (moP.isConnected) { moP.parentNode.removeChild(moP); } else { root.appendChild(moP); }
    }
  }]);
"""

    MACHINERY = """
  // ------------------------------------------- the three new surfaces' machinery (docs/87)
  var clHits = 0, clOk = 0, clErr = 0, clDepth = 0, IN_CCLONE = 0;
  var ikHits = 0, ikOk = 0, ikErr = 0, ikDepth = 0, IN_IKEY = 0;
  var mo = null, moP = null, moHits = 0, moRecs = 0, moDepth = 0, moDel = 0, moNudges = 0, moIn = 0;
  // A cheap mutation of an OBSERVED node from inside an engine frame.  Without it every delivery
  // waits for the task boundary (measured: the first `mocb` reports q=10, i.e. the end of batch 10,
  // where BATCH is 10).  With it the record is queued inside the frame and the microtask checkpoint
  // drains it before that frame returns — `moIn` counts deliveries whose `seq` is not a batch
  // multiple, which is the witness that the delivery landed inside a round's own C++ frame.
  function moNudge() {
    if (!mo) return;
    moNudges++;
    try { root.setAttribute('mn', String(moNudges & 1023)); } catch (e) {}
  }
  // One observer on the container the alphabet mutates and one on p0 (the text node Gtext rewrites).
  // The callback is a script window inside the engine's delivery loop: when ext=1 it removes the node
  // it is being told about, churns an unrelated sheet, drops a live FontFace and kills a frame/worker.
  function mkMo() {
    if (!MOB) return;
    try {
      if (!moP) { moP = document.createElement('p'); moP.id = 'moP'; moP.textContent = 'mp'; root.appendChild(moP); }
      mo = new MutationObserver(function (recs, obs) {
        moHits++; moRecs += recs.length;
        if (BATCH > 1 && (seq % BATCH) !== 0) moIn++;
        if (DBG && moHits <= 6) B('mocb', 'h=' + moHits + '&n=' + recs.length +
          '&t=' + (recs[0] && recs[0].type) + '&q=' + seq + '&gd=' + moDepth);
        if (moDepth > 0) return;
        moDepth++;
        try {
          if (EXT) {
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
          try { obs.takeRecords(); } catch (e) {}
        } catch (e) {}
        moDepth--;
      });
      mo.observe(root, { childList: true, subtree: true, attributes: true, characterData: true });
      if (p0) mo.observe(p0, { attributes: true, subtree: true, characterData: true, childList: true });
    } catch (e) { mo = null; if (DBG) B('mofail', 'e=' + (e && e.name)); }
  }
"""

    body = build_seq2.sub(body, "  var EXT = K('ext', '0') === '1';\n", KNOBS)
    body = build_seq2.sub(body, "\n  var TOT = 0, CUM = [];", NEW_OPS, where="before")
    body = build_seq2.sub(body, "  // ---------------------------------------------------------------- the script window\n",
                          MACHINERY, where="before")
    # The FontFace window must ALSO mutate a node the observer watches, or every delivery waits for
    # the task boundary: measured, without this the first `mocb` reports q=10 (the end of batch 10).
    body = build_seq2.sub(body, "            if (EXT) extWindow();\n", "            if (MOB) moNudge();\n")
    body = build_seq2.sub(body, "\n  B('boot', 'seed='", "  if (MOB) mkMo();\n", where="before")

    if body.count("'&ath=' + (ATH ? 1 : 0) + '&ext=' + (EXT ? 1 : 0));") != 1:
        sys.exit("boot-beacon anchor is not unique")
    body = body.replace("'&ath=' + (ATH ? 1 : 0) + '&ext=' + (EXT ? 1 : 0));",
                        "'&ath=' + (ATH ? 1 : 0) + '&ext=' + (EXT ? 1 : 0) + '&mob=' + (MOB ? 1 : 0));", 1)

    done_anchor = ("      '&kerr=' + (window.__killerr || 0) + '&nofe=' + (window.__nofe || 0));")
    if body.count(done_anchor) != 1:
        sys.exit("done-beacon anchor occurs %d times" % body.count(done_anchor))
    extra = [
        "      '&kerr=' + (window.__killerr || 0) + '&nofe=' + (window.__nofe || 0) +",
        "      '&clh=' + clHits + '&clok=' + clOk + '&clerr=' + clErr +",
        "      '&ikh=' + ikHits + '&ikok=' + ikOk + '&ikerr=' + ikErr +",
        "      '&moh=' + moHits + '&mors=' + moRecs + '&mod=' + moDel + '&moi=' + (mo ? 1 : 0) +",
        "      '&mn=' + moNudges + '&moir=' + moIn);",
    ]
    body = body.replace(done_anchor, "\n".join(extra), 1)

    OUT.write_text(body)

    # --- the page's own inline script is a program, not a string: parse it before shipping it
    shutil_node_check(body)

    print("wrote %s (%d bytes, md5 %s)" % (OUT, len(body), hashlib.md5(body.encode()).hexdigest()))
    nops = len(re.findall(r"\n    \['[A-Za-z][A-Za-z0-9-]*', \d+, function", body)) + \
        len(re.findall(r"OPS\.push\(\['[A-Za-z][A-Za-z0-9-]*', \d+, function", body))
    print("ops present: %d (29 array + 8 pushed = 37)" % nops)
    for blk in ops86_block:
        if blk not in body:
            sys.exit("a docs/86 op block did not survive the build verbatim")
    print("provenance: 29 docs/84 ops present, 3 docs/86 ops present (%d bytes verbatim)" %
          sum(len(b) for b in ops86_block))


def shutil_node_check(body: str) -> None:
    """`node --check` the page's last <script> program (the instrument itself, not the srcdoc)."""
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        print("WARNING: node not found — page script NOT syntax-checked")
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
    print("page script: %d bytes, syntax OK" % len(script))
    # and the srcdoc's inner script, exactly as docs/86's builder does it
    build_seq2.check_inner_script(body)


if __name__ == "__main__":
    main()
