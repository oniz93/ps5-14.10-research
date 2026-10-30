#!/usr/bin/env python3
"""docs/89 builder: write research/fuzz-cssom/seq5.html from seq4.html (docs/88).

seq4.html's md5 is quoted in docs/88, so it is never edited: this builder *reads* it and adds the one
surface GOAL.md item 1 names — the transfer list, i.e. `postMessage(message, [buf])`.

  1. two knobs: `wxt` (enable the two new ops; default off, so a docs/88 arm keeps its stream shape)
     and `wxk` (1 = `postMessage(msg, [buf])`, 0 = the identical message with **no** transfer list —
     the axis control: the buffer is then serialized by value and the sender keeps it).
  2. two ops, `Mwx` (MessagePort, the local receiver) and `Awx` (a dedicated blob worker, the spelling
     `Worker.idl:35` declares).  Both build a 192-byte buffer (the freed CSSFontFace's size class), a
     `Uint8Array` over it, and a message whose enumerable getter runs *inside*
     `CloneSerializer::serialize` — after the view has been dumped — and does the docs/65 arming.
  3. counters and `done` fields: `wxh` (getter hits), `wxgx` (what the getter read from
     `buf.byteLength`), `wxtx` (the same buffer's byteLength after the call), `wxrx*` (the arrived
     view's shape), `wxerr`.

Every anchor must occur exactly once (a missing anchor aborts the build), the page's own script is
`node --check`ed, and the docs/84 + docs/86 + docs/87 + docs/88 op blocks are re-asserted verbatim.

Run: python3 research/fuzz-cssom/build_seq5.py   (writes research/fuzz-cssom/seq5.html)
"""
import hashlib
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_seq    # noqa: E402  (docs/85 builder: extract_ops)
import build_seq2   # noqa: E402  (docs/86 builder: sub + srcdoc check)
import build_seq4   # noqa: E402  (docs/88 builder: check_page_and_inner, EXTF stub)

SRC = HERE / "seq4.html"
OUT = HERE / "seq5.html"
SRC_MD5 = "aea291c7beb30d601aedb6780b5b52e5"


def swap(text: str, anchor: str, new: str) -> str:
    """Replace `anchor` with `new`, requiring exactly one occurrence."""
    n = text.count(anchor)
    if n != 1:
        sys.exit("anchor %r occurs %d times (want 1) — seq4.html changed; fix the builder"
                 % (anchor[:70], n))
    return text.replace(anchor, new, 1)


KNOB_ANCHOR = "  var MOF = K('mof', '0') === '1';\n"

KNOBS_NEW = """  var MOF = K('mof', '0') === '1';

  // docs/89 knobs.  `wxt` enables the two transfer-list ops; with it off the page is docs/88's
  // instrument plus two inert entries in the op table.  `wxk` is the axis control for the transfer
  // itself: 1 = `postMessage(msg, [buf])`, 0 = the identical message and getter with no transfer
  // list, so the buffer is serialized by value and the sender keeps it.
  var WXT = K('wxt', '0') === '1';
  var WXK = K('wxk', '1') === '1';
"""

NEW_OPS = r"""
  // ------------------------------------------- the transfer list (docs/89)
  // Mwx / Awx — `postMessage(message, [buf])`, the one IDL on this build that really carries a
  // transfer list (`workers/Worker.idl:35`, `dom/MessagePort.idl:35`).  docs/67 closed the
  // BroadcastChannel spelling for a reason that does not generalise: that IDL declares
  // `postMessage(any message)` with no transfer argument, so ArrayBuffers are written in-line and
  // copied (`SerializedScriptValue.cpp:3238-3250`) and `m_arrayBufferContentsArray` (:5187) is never
  // reached.  Here it is reached.
  //
  // The ordering is the point, and it is measured (docs/89 §1): `CloneSerializer::serialize()` runs
  // the whole walk at :5463, `transferArrayBuffers()` detaches at :5477 — so a page getter runs
  // BEFORE the buffer is detached and reads its FULL byteLength (`wxgx`).  The view is dumped first
  // by property order (`v` then `g`), so the payload records a 192-byte view while the getter is
  // still free to run page script — the docs/65 arming (unrelated sheet change, deleteRule, forced
  // layout) inside the serializer's own frame, the same free site `Cclone` uses in a different C++
  // frame.  `wxtx` is the same buffer's byteLength after the call: 0 means the transfer really
  // detached it.
  var wxHits = 0, wxRx = 0, wxRxOk = 0, wxErr = 0, wxDepth = 0;
  var wxGx = -1, wxTx = -1, wxLen = -1, wxRxLen = -1, wxRxByt = -1, wxRxBuf = -1, wxLast = '';
  function wxMsg(buf, len, a) {
    var u8 = new Uint8Array(buf);
    var msg = { v: u8, n: a % 97 };
    Object.defineProperty(msg, 'g', {
      enumerable: true, configurable: true,
      get: function () {
        wxHits++; wxLen = len;
        try { wxGx = buf.byteLength; } catch (e) { wxGx = -2; }
        if (wxDepth > 0) return 1;
        wxDepth++;
        try {
          if (DBG && wxHits <= 6) B('wxg', 'h=' + wxHits + '&gx=' + wxGx + '&len=' + len);
          churnSheet();
          var sh = inlineSheet();
          if (sh && sh.cssRules.length) sh.deleteRule(0);
          document.body.offsetHeight;
          if (MOB) moNudge();
          if (EXTF || EXTW) extWindow();
        } catch (e) {}
        wxDepth--;
        return 1;
      }
    });
    return msg;
  }
  OPS.push(['Mwx', 3, function (a, b) {
    if (!WXT) return;
    var len = 192 + (b % 3) * 8;
    var buf, ch;
    try { buf = new ArrayBuffer(len); ch = new MessageChannel(); } catch (e) { wxErr++; return; }
    var msg = wxMsg(buf, len, a);
    ch.port2.onmessage = function (ev) {
      wxRx++;
      var d = ev.data, v = d && d.v;
      if (v) { wxRxOk++; wxRxLen = v.length; wxRxByt = v.byteLength; wxRxBuf = v.buffer ? v.buffer.byteLength : -1; }
      try { ch.port1.close(); ch.port2.close(); } catch (e) {}
    };
    try {
      if (WXK) ch.port1.postMessage(msg, [buf]); else ch.port1.postMessage(msg);
      try { wxTx = buf.byteLength; } catch (e) { wxTx = -2; }
    } catch (e) { wxErr++; wxLast = (e && e.name) + ''; try { wxTx = buf.byteLength; } catch (e2) {} }
  }]);
  var wxwrk = null, wxwecho = 0;
  function wxWorker() {
    var src = 'onmessage=function(e){var r={n:e.data&&e.data.n};' +
      'try{var v=e.data&&e.data.v;if(v){r.vl=v.length;r.vb=v.byteLength;' +
      'r.bb=(v.buffer? v.buffer.byteLength : -1);}}catch(x){r.err=x.name;}' +
      'try{postMessage(r);}catch(x){}};';
    try {
      wxwrk = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
      wxwrk.onmessage = function (ev) {
        wxwecho++;
        var d = ev.data || {};
        wxRx = wxwecho;
        if (d.vb !== undefined) { wxRxOk++; wxRxLen = d.vl; wxRxByt = d.vb; wxRxBuf = d.bb; }
        if (d.err) wxLast = 'W:' + d.err;
        if (DBG && wxwecho <= 6) B('wxe', 'n=' + wxwecho + '&vl=' + d.vl + '&vb=' + d.vb + '&bb=' + d.bb + '&err=' + (d.err || '-'));
      };
      wxwrk.onerror = function (ev) { wxErr++; wxLast = 'werr'; };
    } catch (e) { wxwrk = null; wxErr++; wxLast = 'wkfail:' + (e && e.name); }
  }
  OPS.push(['Awx', 3, function (a, b) {
    if (!WXT) return;
    if (!wxwrk) wxWorker();
    if (!wxwrk) return;
    var len = 192 + (b % 3) * 8;
    var buf;
    try { buf = new ArrayBuffer(len); } catch (e) { wxErr++; return; }
    var msg = wxMsg(buf, len, a);
    try {
      if (WXK) wxwrk.postMessage(msg, [buf]); else wxwrk.postMessage(msg);
      try { wxTx = buf.byteLength; } catch (e) { wxTx = -2; }
    } catch (e) { wxErr++; wxLast = (e && e.name) + ''; try { wxTx = buf.byteLength; } catch (e2) {} }
  }]);
"""

BOOT_OLD = "    '&mob=' + (MOB ? 1 : 0));"
BOOT_NEW = ("    '&mob=' + (MOB ? 1 : 0) + '&wxt=' + (WXT ? 1 : 0) + '&wxk=' + (WXK ? 1 : 0));")

DONE_OLD = ("      '&mofd=' + moFrDrive + '&mofrem=' + moFrRem + '&mofseen=' + moFrSeen + '&mofearly=' + moFrEarly);")
DONE_NEW = ("      '&mofd=' + moFrDrive + '&mofrem=' + moFrRem + '&mofseen=' + moFrSeen + '&mofearly=' + moFrEarly +\n"
            "      '&wxh=' + wxHits + '&wxgx=' + wxGx + '&wxtx=' + wxTx + '&wxlen=' + wxLen +\n"
            "      '&wxrx=' + wxRx + '&wxrxok=' + wxRxOk + '&wxrxl=' + wxRxLen + '&wxrxb=' + wxRxByt + '&wxrxbuf=' + wxRxBuf +\n"
            "      '&wxerr=' + wxErr + '&wxlast=' + encodeURIComponent(wxLast));")


def main() -> None:
    src = SRC.read_text()
    md5 = hashlib.md5(src.encode()).hexdigest()
    if md5 != SRC_MD5:
        sys.exit("seq4.html md5 is %s, expected %s (docs/88 quotes it) — refusing to build" % (md5, SRC_MD5))

    body = src
    body = swap(body, KNOB_ANCHOR, KNOBS_NEW)
    body = build_seq2.sub(body, "\n  var TOT = 0, CUM = [];", NEW_OPS, where="before")
    body = swap(body, BOOT_OLD, BOOT_NEW)
    body = swap(body, DONE_OLD, DONE_NEW)

    OUT.write_text(body)
    build_seq4.check_page_and_inner(body)

    # ---- provenance: the docs/84 op block and the docs/86/87/88 op blocks must survive verbatim
    ops84 = build_seq.extract_ops((HERE / "fuzz.html").read_text())
    if ops84 not in body:
        sys.exit("seq5.html does not contain fuzz.html's op block verbatim")
    for op in ("Aanim", "Aframe", "Aworker", "Cclone", "Ikey", "Mobs", "Mofr"):
        pat = (r"  OPS\.push\(\['%s',.*?\n  \}\]\);\n" % op) if op == "Mofr" else None
        if pat is None:
            if ("['%s', " % op) not in body:
                sys.exit("seq5.html is missing the op %s" % op)
        elif not re.search(pat, body, re.S):
            sys.exit("seq5.html is missing the op %s" % op)
    if body.count("function moFrame()") != 1:
        sys.exit("moFrame() definition count is not 1")

    for tok in ("WXT", "WXK", "Mwx", "Awx", "wxMsg", "wxWorker", "wxgx"):
        print("  %-9s %d occurrences" % (tok, body.count(tok)))
    nops = len(re.findall(r"\n    \['[A-Za-z][A-Za-z0-9-]*', \d+, function", body)) + \
        len(re.findall(r"OPS\.push\(\['[A-Za-z][A-Za-z0-9-]*', \d+, function", body))
    print("wrote %s (%d bytes, md5 %s)" % (OUT, len(body), hashlib.md5(body.encode()).hexdigest()))
    print("ops present: %d (29 array + 11 pushed = 40)" % nops)


if __name__ == "__main__":
    main()
