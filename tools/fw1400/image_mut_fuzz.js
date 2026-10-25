// In-browser image mutation fuzzer.
//
// The first probe ran one file per case, which caps you at however many files you can stage (458).
// This one fetches the corpus once as bytes and mutates in the page, so a single seed can run
// thousands of decodes against structurally valid headers.
//
// Mutation strategy: start from a real BMP/ICO/WBMP/GIF, then apply a few edits. Purely random bytes
// are rejected by the magic-number check and never reach the decoder, so most mutations are biased to
// the header region where the decoder does its arithmetic - plus occasional truncation, which is the
// cheapest way to reach partial-read paths.
//
// Both decode entry points are exercised: createImageBitmap(Blob) and <img> with an object URL,
// because they take different paths through ImageDecoder.

(function () {
  'use strict';

  var seed = 1;
  if (typeof window.__SEED === 'number' && window.__SEED > 0) seed = window.__SEED;

  var ITER = 1500;
  var TIMEOUT_MS = 2000;

  function beacon(tag) {
    if (!window.__BEACON) return;
    try { (new Image()).src = window.__BEACON + '/' + encodeURIComponent(tag); } catch (e) {}
  }
  window.onerror = function (msg) {
    beacon('ERR-seed' + seed + '-' + String(msg).slice(0, 60).replace(/[^A-Za-z0-9 ._-]/g, '_'));
    return false;
  };
  beacon('BOOT-seed' + seed);

  var s = seed | 0 || 1;
  function rnd() { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return (s >>> 0) / 4294967296; }
  function ri(n) { return Math.floor(rnd() * n); }
  function pick(a) { return a[ri(a.length)]; }

  var canvas = document.createElement('canvas');
  canvas.width = 64; canvas.height = 64;
  var ctx = canvas.getContext('2d');

  var bases = [];

  function mutate(base) {
    var out = new Uint8Array(base);          // copy; do not corrupt the cached original
    var n = 1 + ri(6);
    for (var k = 0; k < n; k++) {
      var mode = ri(10);
      var pos;
      if (mode < 6) pos = ri(Math.min(64, out.length));      // header region
      else if (mode < 9) pos = ri(out.length);              // anywhere
      else { out = out.subarray(0, Math.max(1, ri(out.length))); continue; }  // truncate

      if (pos >= out.length) continue;
      var how = ri(4);
      if (how === 0) out[pos] ^= 1 << ri(8);
      else if (how === 1) out[pos] = 0xFF;
      else if (how === 2) out[pos] = 0x00;
      else out[pos] = ri(256);
    }
    return out;
  }

  function decodeBlob(bytes, done) {
    var finished = false;
    var timer = setTimeout(function () { if (!finished) { finished = true; done(); } }, TIMEOUT_MS);
    var settle = function () { if (!finished) { finished = true; clearTimeout(timer); done(); } };
    var blob;
    try { blob = new Blob([bytes]); } catch (e) { settle(); return; }

    if (typeof createImageBitmap === 'function') {
      createImageBitmap(blob).then(function (bmp) {
        try {
          var w = Math.min(Math.max(bmp.width, 1), 512);
          var h = Math.min(Math.max(bmp.height, 1), 512);
          canvas.width = w; canvas.height = h;
          ctx.drawImage(bmp, 0, 0, w, h);
          ctx.getImageData(0, 0, w, h);
          if (bmp.close) bmp.close();
        } catch (e) {}
        settle();
      }, settle);
      return;
    }

    var url;
    try { url = URL.createObjectURL(blob); } catch (e) { settle(); return; }
    var img = new Image();
    img.onload = function () {
      try {
        var w = Math.min(Math.max(img.naturalWidth, 1), 512);
        var h = Math.min(Math.max(img.naturalHeight, 1), 512);
        canvas.width = w; canvas.height = h;
        ctx.drawImage(img, 0, 0, w, h);
        ctx.getImageData(0, 0, w, h);
      } catch (e) {}
      try { URL.revokeObjectURL(url); } catch (e) {}
      settle();
    };
    img.onerror = function () {
      try { URL.revokeObjectURL(url); } catch (e) {}
      settle();
    };
    img.src = url;
  }

  function loadBases() {
    var names = window.__IMGS || [];
    var pending = names.length;
    if (!pending) { beacon('NOIMG-seed' + seed); return; }
    names.forEach(function (n) {
      fetch('img/' + encodeURIComponent(n)).then(function (r) { return r.arrayBuffer(); }).then(function (b) {
        // Keep the small ones: giant bases make every mutation slow without adding header coverage.
        if (b.byteLength > 0 && b.byteLength < 65536) bases.push(new Uint8Array(b));
      }, function () {}).then(function () {
        pending -= 1;
        if (pending === 0) start();
      });
    });
  }

  var i = 0;
  function tick() {
    if (i >= ITER || !bases.length) {
      document.title = 'DONE:' + seed;
      beacon('DONE-seed' + seed);
      return;
    }
    i += 1;
    if (i % 100 === 0) beacon('P' + i + '-s' + seed);
    decodeBlob(mutate(pick(bases)), function () { setTimeout(tick, 0); });
  }

  function start() {
    beacon('BASES-seed' + seed + '-' + bases.length);
    tick();
  }

  document.addEventListener('DOMContentLoaded', loadBases);
})();
