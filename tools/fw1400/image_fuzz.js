// Image decoder probe for the ASAN MiniBrowser.
//
// Targets the four decoders WebKit implements in-tree: BMP, ICO, WBMP, GIF. PNG/JPEG/WebP/AVIF go
// through system libraries, so a bug there is not a WebKit bug; the corpus includes a few only as a
// control.
//
// Two decode paths matter and they are not the same code: <img> + drawImage goes through
// ImageDecoder, while createImageBitmap takes BitmapImageSource and can call a different entry point
// with different lifetime handling. The probe alternates between them so both are exercised.
//
// Decoding is lazy. Setting .src and waiting for onload is not enough: the bytes may never be read.
// getImageData() after drawImage, and awaiting the createImageBitmap promise, both force a full
// decode - which is where a malformed header actually gets used.

(function () {
  'use strict';

  var seed = 1;
  if (typeof window.__SEED === 'number' && window.__SEED > 0) seed = window.__SEED;

  var SLICES = 6;          // corpus is split across seeds so one run stays short
  var TIMEOUT_MS = 2500;   // a malformed image must not be able to hang the whole slice

  function beacon(tag) {
    if (!window.__BEACON) return;
    try { (new Image()).src = window.__BEACON + '/' + encodeURIComponent(tag); } catch (e) {}
  }
  window.onerror = function (msg) {
    beacon('ERR-seed' + seed + '-' + String(msg).slice(0, 60).replace(/[^A-Za-z0-9 ._-]/g, '_'));
    return false;
  };
  beacon('BOOT-seed' + seed);

  var canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  var ctx = canvas.getContext('2d');

  function clamp(n) {
    if (!isFinite(n) || n <= 0) return 1;
    return Math.min(Math.floor(n), 2048);
  }

  function afterLoad(img) {
    // drawImage + getImageData is what forces the pixels to exist; a header that decoded to a bogus
    // size shows up here as an enormous allocation rather than a silent no-op.
    try {
      var w = clamp(img.naturalWidth);
      var h = clamp(img.naturalHeight);
      canvas.width = w;
      canvas.height = h;
      ctx.drawImage(img, 0, 0, w, h);
      ctx.getImageData(0, 0, canvas.width, canvas.height);
    } catch (e) {}
  }

  function loadViaImage(url, done) {
    var finished = false;
    var img = new Image();
    var timer = setTimeout(function () { if (!finished) { finished = true; done(); } }, TIMEOUT_MS);
    img.onload = function () {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      afterLoad(img);
      done();
    };
    img.onerror = function () {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      done();
    };
    img.src = url;
  }

  function loadViaBitmap(url, done) {
    if (typeof createImageBitmap !== 'function') { loadViaImage(url, done); return; }
    var finished = false;
    var timer = setTimeout(function () { if (!finished) { finished = true; done(); } }, TIMEOUT_MS);
    var settle = function () { if (!finished) { finished = true; clearTimeout(timer); done(); } };
    fetch(url).then(function (r) { return r.blob(); }).then(function (b) {
      return createImageBitmap(b).then(function (bmp) {
        try {
          var w = clamp(bmp.width), h = clamp(bmp.height);
          canvas.width = w; canvas.height = h;
          ctx.drawImage(bmp, 0, 0, w, h);
          ctx.getImageData(0, 0, w, h);
          if (bmp.close) bmp.close();     // ImageBitmap owns memory; closing must be safe to repeat
        } catch (e) {}
        settle();
      }, settle);
    }, settle);
  }

  var list = (window.__IMGS || []).filter(function (n, i) { return i % SLICES === seed % SLICES; });
  var i = 0;

  function tick() {
    if (i >= list.length) {
      document.title = 'DONE:' + seed;
      beacon('DONE-seed' + seed);
      return;
    }
    var idx = i;
    i += 1;
    if (i % 5 === 0) beacon('P' + i + '-s' + seed);
    var url = 'img/' + encodeURIComponent(list[idx]);
    var next = function () { setTimeout(tick, 0); };
    if (idx % 2 === 0) loadViaImage(url, next);
    else loadViaBitmap(url, next);
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!list.length) { beacon('NOIMG-seed' + seed); }
    tick();
  });
})();
