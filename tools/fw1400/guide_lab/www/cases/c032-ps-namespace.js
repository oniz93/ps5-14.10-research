// c032: enumerate window._PS, Sony's proprietary namespace behind postMessageNative.
//
// postMessageNative turned out to be a shim: function(data) { window._PS.postMessage(String(data)); }
// So _PS is the real bridge, injected by the app shell outside WebKit. Its shims are JS, so their source may
// reveal exactly how data crosses into native code - the most valuable thing found so far.
(function () {
  function send(s) {
    // chunk long payloads: beacons are GET query strings
    s = String(s);
    for (var off = 0; off < s.length; off += 240)
      try { navigator.sendBeacon('/beacon', 'c032-' + s.slice(off, off + 240)); } catch (e) {}
  }
  send('boot');

  var P = window._PS;
  if (!P) { send('no-_PS'); return; }
  send('typeof=' + typeof P);

  var names = [];
  try { names = Object.getOwnPropertyNames(P); } catch (e) { send('enum-threw:' + e.name); return; }
  send('props[' + names.length + ']: ' + names.join(','));

  for (var i = 0; i < names.length && i < 40; i++) {
    var n = names[i], v, t;
    try { v = P[n]; t = typeof v; } catch (e) { send(n + ' -> throws ' + e.name); continue; }
    if (t === 'function') {
      var src = '';
      try { src = String(v).replace(/\s+/g, ' '); } catch (e) { src = '<unstringifiable>'; }
      send('fn ' + n + '/' + v.length + ' :: ' + src.slice(0, 300));
    } else if (t === 'object' && v) {
      var sub = [];
      try { sub = Object.getOwnPropertyNames(v); } catch (e) { sub = ['<throws>']; }
      send('obj ' + n + ' {' + sub.join(',') + '}');
    } else {
      try { send('val ' + n + ' = ' + String(v).slice(0, 60)); } catch (e) { send('val ' + n + ' unstringifiable'); }
    }
  }

  send('done');
})();
