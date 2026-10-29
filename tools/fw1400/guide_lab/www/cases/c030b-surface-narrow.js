// c030b: narrow the global enumeration to things that could be a host bridge or a Sony API.
//
// c030 showed 754 globals and no window.webkit, but its "unknown" list was capped before reaching anything
// interesting. This filters by name pattern instead of by count, and separately reports navigator/document
// additions.
(function () {
  function send(s) { try { navigator.sendBeacon('/beacon', 'c030b-' + s); } catch (e) {} }
  send('boot');

  function typeOf(o, k) { try { return typeof o[k]; } catch (e) { return 'throws'; } }

  // 1. anything whose name smells like a bridge or a platform API
  var HINTS = /(ps[0-9]?|play|sony|prospero|sce|sys|nat|native|bridge|handler|device|shell|host|app|webkit|__)/i;
  var hits = [];
  var names = Object.getOwnPropertyNames(window);
  for (var i = 0; i < names.length; i++) {
    var n = names[i];
    if (!HINTS.test(n)) continue;
    if (/^(webkit(Request|Cancel|URL|RTCPeer|Speech)|app(CodeName|Name|Version|VersionExtra))$/.test(n)) continue;
    hits.push(n + ':' + typeOf(window, n));
  }
  send('hinted[' + hits.length + '] ' + hits.join(' ').slice(0, 900));

  // 2. navigator / document additions
  try {
    var nav = Object.getOwnPropertyNames(Object.getPrototypeOf(navigator)).concat(Object.getOwnPropertyNames(navigator));
    send('navigator[' + nav.length + '] ' + nav.join(',').slice(0, 600));
  } catch (e) { send('nav-threw:' + e.name); }

  // 3. callable objects that are not standard constructors - the strangest surface
  var fns = [];
  for (var j = 0; j < names.length; j++) {
    var m = names[j];
    var t = typeOf(window, m);
    if (t !== 'function') continue;
    if (/^[A-Z]/.test(m)) continue;                 // constructor-looking: normal
    if (/^(on|webkit)/.test(m)) continue;
    fns.push(m);
  }
  send('lowercase-fns[' + fns.length + '] ' + fns.join(' ').slice(0, 700));

  send('done');
})();
