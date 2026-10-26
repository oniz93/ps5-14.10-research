// Upstream fix 84cde5ed5a: "SerializedScriptValue::deserialize cannot be called more than once
// (affects BroadcastChannel)".
//
// The invariant the fix restores is that one serialized value is deserialized once. Two listeners on a
// single channel, and a port with both an addEventListener handler and an onmessage handler, are the
// shapes that make the same value go through deserialization twice - which is a lifetime bug, not a
// null dereference, so it is worth the run even though the CSSOM case was only a DoS.
try {
  var ch = new BroadcastChannel('lab-' + Math.random().toString(36).slice(2));
  var got = 0;
  ch.addEventListener('message', function () { got++; });
  ch.onmessage = function () { got++; };
  ch.postMessage({ a: [1, 2, 3], s: new Array(80).join('x'), nested: { k: [4, 5] } });
  ch.postMessage([1, 2, 3]);

  var mc = new MessageChannel();
  mc.port1.addEventListener('message', function () {});
  mc.port1.onmessage = function () {};
  mc.port1.start();
  mc.port2.postMessage({ deep: { nested: [1, 2, 3] }, s: new Array(80).join('y') });
} catch (e) { }
