// c033: what does _PS.postMessage accept, and what does it do with it?
//
// The Guide shell takes a JS string and hands it to native code. Questions worth asking in order of risk:
// does it require JSON, does it reject malformed input, does it coerce non-strings, and how does a native
// parser handle depth. Anything that changes the page's own behaviour tells us the message reached a real
// handler rather than a debug sink.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c033-' + String(s)); } catch (e) {} }
  send('boot');

  var P = (window._PS && window._PS.postMessage);
  if (typeof P !== 'function') { send('no-bridge'); return; }

  function deep(n) {
    var s = '';
    for (var i = 0; i < n; i++) s += '[';
    for (var j = 0; j < n; j++) s += ']';
    return s;
  }

  var cases = [
    ['1-empty',      function () { return P(''); }],
    ['2-obj',        function () { return P('{}'); }],
    ['3-type-ping',  function () { return P('{"type":"ping"}'); }],
    ['4-not-json',   function () { return P('not json at all'); }],
    ['5-json-str',   function () { return P('"hello"'); }],
    ['6-raw-string', function () { return P('hello'); }],
    ['7-obj-arg',    function () { return P({ type: 'ping' }); }],
    ['8-null-arg',   function () { return P(null); }],
    ['9-bignum',     function () { return P('{"type":"ping","n":1e309}'); }],
    ['10-deep1k',    function () { return P(deep(1000)); }],
    ['11-deep50k',   function () { return P(deep(50000)); }],
  ];

  var i = 0;
  function next() {
    if (i >= cases.length) { send('done-all'); return; }
    var name = cases[i][0], fn = cases[i][1];
    i++;
    send('pre-' + name);
    var r, threw = '';
    try { r = fn(); } catch (e) { threw = e.name; }
    send('post-' + name + (threw ? ' threw:' + threw : ' ok ret=' + typeof r));
    setTimeout(next, 60);
  }
  next();
})();
