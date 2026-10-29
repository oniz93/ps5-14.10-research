// c031: characterise window.postMessageNative, the one non-standard callable the Guide WebView exposes.
//
// It is not in Sony's OSS drop, so it is implemented in the app shell outside WebKit. That makes it a JS->native
// boundary we cannot read but can probe. Order matters: benign shapes first, each preceded by its own beacon, so
// if the process dies the last beacon names the input that killed it.
//
// Calling a host function with odd arguments is not fuzzing - each case is a question about the boundary:
// does it coerce, does it serialise, does it check arity, does it accept binary.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c031-' + s); } catch (e) {} }
  send('boot');

  var f = window.postMessageNative;
  if (typeof f !== 'function') { send('not-a-function:' + typeof f); return; }
  send('typeof=function length=' + f.length);
  try { send('src=' + String(f).replace(/\s+/g, ' ').slice(0, 120)); } catch (e) { send('src-threw'); }
  try {
    var d = Object.getOwnPropertyDescriptor(window, 'postMessageNative');
    send('own=' + (d ? 'yes' : 'no') + ' writable=' + (d ? d.writable : '?') + ' configurable=' + (d ? d.configurable : '?'));
  } catch (e) { send('desc-threw:' + e.name); }

  var cases = [
    ['1-noargs',   function () { return f(); }],
    ['2-string',   function () { return f('ping'); }],
    ['3-two',      function () { return f('ping', 'pong'); }],
    ['4-number',   function () { return f(1234); }],
    ['5-null',     function () { return f(null); }],
    ['6-undef',    function () { return f(undefined); }],
    ['7-object',   function () { return f({ a: 1, b: 'two' }); }],
    ['8-nested',   function () { var o = {}; var p = o; for (var i = 0; i < 6; i++) { p.n = {}; p = p.n; } return f(o); }],
    ['9-arraybuf', function () { var b = new ArrayBuffer(64); new Uint8Array(b).fill(0x41); return f(b); }],
    ['10-typed',   function () { return f(new Uint8Array([1,2,3,4])); }],
    ['11-bigstr',  function () { return f(new Array(4097).join('A')); }],
    ['12-proxy',   function () { return f(new Proxy({}, { get: function () { return 1; } })); }],
    ['13-getter',  function () { var o = {}; Object.defineProperty(o, 'x', { get: function () { send('13-getter-ran'); return 1; } }); return f(o); }],
  ];

  var i = 0;
  function next() {
    if (i >= cases.length) { send('done-all'); return; }
    var name = cases[i][0], fn = cases[i][1];
    i++;
    send('pre-' + name);
    var r, threw = '';
    try { r = fn(); } catch (e) { threw = e.name + ':' + String(e.message || '').slice(0, 40); }
    var desc;
    try { desc = threw ? ('threw ' + threw) : (typeof r) + (r === undefined ? '' : ' ' + String(r).slice(0, 40)); }
    catch (e) { desc = 'result-unstringifiable'; }
    send('post-' + name + ' -> ' + desc);
    setTimeout(next, 40);
  }
  next();
})();
